"""Gigi's staff upload channel: the PM manages the FAQ documents from a private Discord channel.

    drop a PDF            -> Gigi reads it (in a separate, secret-free process), drafts numbered
                             FAQ entries, shows the checks and attaches the draft as <name>.md.
                             NOTHING is live yet. Buttons: Publish / Publish & allow Qwen / Discard.
    post <name>.md back   -> replaces that document's text (the way to edit a draft).
    list | get <name> | archive <name> | restore <name> | delete <name> | qwen <name> on|off
    import builtin (once, before the first publish) | help

Safety, in order of importance:
  * Gigi works only in the configured channel and refuses if @everyone can read it.
  * Optionally only members with an allowed role may use it (checked again on every button).
  * Publishing is always a deliberate button/command; a draft is never served.
  * "Allow Qwen" is its own button and never on by default.
  * The database account used here can write; the bot's answering path keeps its read-only one.
  * Every change is recorded with who did it (Discord name and ID).

Needs the Message Content intent (the bot already requires it) to see attachments and text.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import discord

from .admin.pdf_import import PdfImportError, draft_markdown, extract_pages_isolated
from .config import KnowledgeUpdatesSettings
from .knowledge_store import (
    MAX_PDF_BYTES,
    MAX_TEXT_BYTES,
    NAME_RE,
    ReconnectingStore,
    StoreError,
    check_pdf,
    open_store,
    redact_location,
    slugify,
    validate_document,
)

log = logging.getLogger(__name__)

PUBLISH, PUBLISH_QWEN = "gab_kb:publish", "gab_kb:publish_qwen"
DISCARD, DELETE = "gab_kb:discard", "gab_kb:delete"
FOOTER = re.compile(r"^document: ([a-z0-9][a-z0-9-]{0,62}\.md)$")
MAX_PDFS_PER_MESSAGE = 5
PROBLEM_REPLY_EVERY = 600  # seconds between "this channel is not private" explanations

HELP = (
    "**Drop a PDF** here and I'll draft FAQ entries from it. Nothing goes live until you press "
    "Publish.\n"
    "**Edit a draft:** download the attached `.md`, change it, and post it back here under the "
    "same file name.\n"
    "`list` · `get <name>` · `archive <name>` · `restore <name>` · `delete <name>` · "
    "`qwen <name> on|off` · `import builtin` (once, before the first publish)\n"
    "Archive takes a live document offline (restore brings it back). Delete is permanent and "
    "only for drafts and archived documents; saved versions and the activity log are kept."
)


def _clip(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def clean_title(text: str) -> str:
    """A document title from the message text: first line, no mentions or control characters."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    first = re.sub(r"<[@#!&][^>]*>|[\x00-\x1f<>]", " ", first)
    return " ".join(first.split())[:120]


def parse_command(text: str):
    """('list', []) for exact command forms only, so ordinary staff chatter is never mistaken
    for one. Accepts an optional leading 'gigi'."""
    parts = (text or "").strip().split()
    if parts and parts[0].lower() == "gigi":
        parts = parts[1:]
    if not parts:
        return None
    word, args = parts[0].lower(), parts[1:]
    shapes = {
        "help": 0,
        "list": 0,
        "import": 1,
        "get": 1,
        "archive": 1,
        "restore": 1,
        "delete": 1,
        "qwen": 2,
    }
    if shapes.get(word) != len(args):
        return None
    return word, args


def doc_name(raw: str) -> str | None:
    name = raw.strip().lower()
    if not name.endswith(".md"):
        name += ".md"
    return name if NAME_RE.match(name) else None


@dataclass(frozen=True)
class DocInfo:
    name: str
    title: str
    status: str
    entries: int
    qwen: bool
    problems: tuple[str, ...]
    warnings: tuple[str, ...]
    updated_by: str
    text: str


class DocumentOps:
    """Everything the channel does to the knowledge database. Plain blocking functions with no
    Discord in them: the channel runs them in worker threads, tests call them directly."""

    def __init__(self, store, builtin_dir=None):
        self.store = store
        self.builtin_dir = Path(builtin_dir) if builtin_dir else None
        self._reading = threading.Lock()  # one PDF at a time: each read is its own process

    def _guard_first_publish(self) -> None:
        """Gigi answers from the database alone once it holds a live document. Publishing the
        first one into an EMPTY database would therefore silently replace the FAQ built into the
        image with just that one document."""
        if (
            self.builtin_dir
            and any(self.builtin_dir.glob("*.md"))
            and not self.store.list_documents("current")
        ):
            raise StoreError(
                "The database has no live documents yet, so publishing this would replace "
                "Gigi's built-in FAQ with only this one. Say `import builtin` first to bring "
                "the built-in documents in, then publish."
            )

    def import_builtin(self, actor: str) -> list[str]:
        if not self.builtin_dir:
            raise StoreError("No built-in documents are configured.")
        return self.store.import_directory(self.builtin_dir, actor)

    def info(self, name: str) -> DocInfo:
        doc = self.store.get_document(name)
        if doc is None:
            raise StoreError(f"There is no document called {name}. Say `list` to see them.")
        check = self.store.validate(name, doc.text)
        return DocInfo(
            name,
            doc.title,
            doc.status,
            len(check.entry_ids),
            doc.external_processing_approved,
            check.problems,
            check.warnings,
            doc.updated_by,
            doc.text,
        )

    def new_draft(self, data: bytes, filename: str, title: str, actor: str) -> DocInfo:
        check_pdf(data)
        with self._reading:
            pages = extract_pages_isolated(data)
        digest = self.store.put_pdf(data, filename, actor)
        title = title or filename.rsplit(".", 1)[0] or "Untitled"
        name = self.store.unique_name(slugify(title))
        text = draft_markdown(title, filename, pages, self.store.prefixes())
        self.store.create_draft(name, text, actor, source_sha256=digest, source_filename=filename)
        return self.info(name)

    def replace(self, name: str, text: str, actor: str) -> DocInfo:
        self.info(name)  # a clear "no such document" before anything else
        self.store.save_text(name, text, actor, note="replaced from Discord")
        return self.info(name)

    def publish(self, name: str, actor: str, qwen: bool | None) -> DocInfo:
        """qwen=None keeps the document's current Qwen setting (restoring must not change it)."""
        current = self.info(name)
        self._guard_first_publish()
        flag = current.qwen if qwen is None else qwen
        self.store.publish(name, actor, external_processing_approved=flag)
        return self.info(name)

    def restore(self, name: str, actor: str) -> DocInfo:
        if self.info(name).status != "archived":
            raise StoreError(f"{name} is not archived, so there is nothing to restore.")
        return self.publish(name, actor, None)

    def discard(self, name: str, actor: str) -> None:
        if self.info(name).status != "draft":
            raise StoreError("Only a draft can be discarded. Archive a live document instead.")
        self.store.delete(name, actor)

    def archive(self, name: str, actor: str) -> DocInfo:
        self.store.archive(name, actor)
        return self.info(name)

    def delete(self, name: str, actor: str) -> None:
        self.info(name)
        self.store.delete(name, actor)

    def set_qwen(self, name: str, on: bool, actor: str) -> DocInfo:
        self.store.set_external_approval(name, on, actor)
        return self.info(name)

    def listing(self) -> list[DocInfo]:
        docs = []
        for doc in self.store.list_documents():
            check = validate_document(doc.name, doc.text)  # entry count only
            docs.append(
                DocInfo(
                    doc.name,
                    doc.title,
                    doc.status,
                    len(check.entry_ids),
                    doc.external_processing_approved,
                    (),
                    (),
                    doc.updated_by,
                    "",
                )
            )
        return docs


# ---- how it looks in Discord -----------------------------------------------------------------
STATUS_WORD = {"draft": "Draft", "current": "Live", "archived": "Archived"}


def document_embed(info: DocInfo, saved: bool = False) -> discord.Embed:
    state = STATUS_WORD.get(info.status, info.status)
    if info.status == "draft":
        lead = (
            "**Not live yet.** Open the attached file to review it. To change it, edit the file "
            "and post it back here under the same name."
        )
    elif info.status == "current":
        lead = "**Live.** Gigi answers from this document." + (
            " Your change is in use." if saved else ""
        )
    else:
        lead = "**Archived.** Gigi does not use it. Say `restore <name>` to bring it back."
    embed = discord.Embed(
        title=_clip(f"{state}: {info.title}", 250),
        description=lead,
        colour=discord.Colour.red() if info.problems else discord.Colour.green(),
    )
    embed.add_field(name="Entries", value=str(info.entries))
    embed.add_field(name="Qwen may use it", value="yes" if info.qwen else "no")
    if info.problems:
        embed.add_field(
            name="Cannot be published until fixed",
            value=_clip("\n".join(f"• {p}" for p in info.problems), 1000),
            inline=False,
        )
    else:
        embed.add_field(name="Checks", value="Passed", inline=False)
    if info.warnings:
        embed.add_field(
            name="Warnings",
            value=_clip("\n".join(f"• {w}" for w in info.warnings), 1000),
            inline=False,
        )
    if info.status == "draft":
        embed.add_field(
            name="Publish or Publish & allow Qwen?",
            value=(
                "**Publish** keeps it away from Qwen: a question that matches it is passed to "
                "staff. **Publish & allow Qwen** lets Qwen (Alibaba Cloud, Singapore) answer "
                "from it."
            ),
            inline=False,
        )
    embed.set_footer(text=f"document: {info.name}")
    return embed


def listing_embed(infos: list[DocInfo]) -> discord.Embed:
    lines = [
        f"`{i.name}` · {STATUS_WORD.get(i.status, i.status)} · {i.entries} entries · "
        f"Qwen {'yes' if i.qwen else 'no'} · {i.updated_by.split(' (')[0]}"
        for i in infos
    ]
    return discord.Embed(
        title=f"{len(infos)} document(s)",
        description=_clip("\n".join(lines) or "None yet. Drop a PDF here.", 4000),
    )


class UpdateView(discord.ui.View):
    """Under every draft. Fixed custom_ids keep the buttons working after a restart; the document
    is named in the embed footer."""

    def __init__(self, updates: KnowledgeUpdates):
        super().__init__(timeout=None)
        self.updates = updates

    @discord.ui.button(label="Publish", style=discord.ButtonStyle.success, custom_id=PUBLISH)
    async def publish(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.on_button(interaction, "publish")

    @discord.ui.button(
        label="Publish & allow Qwen", style=discord.ButtonStyle.primary, custom_id=PUBLISH_QWEN
    )
    async def publish_qwen(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.on_button(interaction, "publish_qwen")

    @discord.ui.button(label="Discard draft", style=discord.ButtonStyle.danger, custom_id=DISCARD)
    async def discard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.on_button(interaction, "discard")


class DeleteView(discord.ui.View):
    def __init__(self, updates: KnowledgeUpdates):
        super().__init__(timeout=None)
        self.updates = updates

    @discord.ui.button(
        label="Delete permanently", style=discord.ButtonStyle.danger, custom_id=DELETE
    )
    async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.on_button(interaction, "delete")


# ---- the channel -----------------------------------------------------------------------------
class KnowledgeUpdates:
    def __init__(self, bot, settings: KnowledgeUpdatesSettings, ops: DocumentOps):
        self.bot, self.settings, self.ops = bot, settings, ops
        self._explained: dict[int, float] = {}

    async def start(self) -> None:
        """Makes the buttons on old messages work again after a restart."""
        self.bot.add_view(UpdateView(self))
        self.bot.add_view(DeleteView(self))

    # -- where and who
    def is_updates_channel(self, channel) -> bool:
        if channel is None or isinstance(channel, discord.Thread):
            return False
        if getattr(channel, "guild", None) is None:
            return False
        wanted = self.settings.channel
        if wanted.isdigit():
            return str(channel.id) == wanted
        return (getattr(channel, "name", "") or "").casefold() == wanted.casefold()

    def channel_problem(self, channel) -> str | None:
        if channel.permissions_for(channel.guild.default_role).view_channel:
            return (
                "I only work in a private staff channel, and everyone in the server can read "
                "this one. Make it private (deny View Channel to @everyone, allow the staff "
                "roles and me), then try again."
            )
        return None

    def allowed(self, member) -> bool:
        if not self.settings.allowed_roles:
            return True
        held = {str(r.id) for r in getattr(member, "roles", [])} | {
            r.name.casefold() for r in getattr(member, "roles", [])
        }
        return any(role.casefold() in held for role in self.settings.allowed_roles)

    @staticmethod
    def actor(user) -> str:
        return f"{getattr(user, 'display_name', 'unknown')} (discord:{user.id})"[:120]

    async def say(self, message, text=None, **kwargs):
        return await message.reply(
            text, mention_author=False, allowed_mentions=discord.AllowedMentions.none(), **kwargs
        )

    async def run(self, function, *args):
        return await asyncio.to_thread(function, *args)

    # -- messages
    async def handle(self, message) -> bool:
        """True if the message was in the updates channel (it is then never treated as a
        question, whatever it says). Never raises."""
        if not self.is_updates_channel(message.channel):
            return False
        try:
            await self._handle(message)
        except Exception:
            log.exception("[Updates] Failed to handle message %s", message.id)
            try:
                await self.say(message, "Something went wrong (details are in the bot's log).")
            except discord.HTTPException:
                pass
        return True

    async def _handle(self, message) -> None:
        pdfs = [a for a in message.attachments if a.filename.lower().endswith(".pdf")]
        texts = [a for a in message.attachments if a.filename.lower().endswith(".md")]
        command = None if (pdfs or texts) else parse_command(message.content)
        if not (pdfs or texts or command):
            return  # ordinary staff chatter: ignored, silently
        problem = self.channel_problem(message.channel)
        if problem:
            now = time.monotonic()
            if (
                now - self._explained.get(message.channel.id, -PROBLEM_REPLY_EVERY)
                > PROBLEM_REPLY_EVERY
            ):
                self._explained[message.channel.id] = now
                log.warning("[Updates] Refusing to work in #%s: %s", message.channel.name, problem)
                await self.say(message, problem)
            return
        if not self.allowed(message.author):
            await self.say(message, "You do not have a role that may change Gigi's documents.")
            return
        actor = self.actor(message.author)
        if pdfs:
            if len(pdfs) > MAX_PDFS_PER_MESSAGE:
                await self.say(message, f"I read the first {MAX_PDFS_PER_MESSAGE} PDFs only.")
            title = clean_title(message.content) if len(pdfs) == 1 else ""
            for attachment in pdfs[:MAX_PDFS_PER_MESSAGE]:
                await self._new_draft(message, attachment, title, actor)
        elif texts:
            await self._replace(message, texts[0], actor)
        else:
            await self._command(message, *command, actor)

    async def _new_draft(self, message, attachment, title: str, actor: str) -> None:
        if attachment.size > MAX_PDF_BYTES:
            await self.say(message, f"`{attachment.filename}` is larger than 25 MB.")
            return
        async with message.channel.typing():
            try:
                data = await attachment.read()
                info = await self.run(self.ops.new_draft, data, attachment.filename, title, actor)
            except (StoreError, PdfImportError) as error:
                await self.say(message, f"I could not use `{attachment.filename}`: {error}")
                return
            except discord.HTTPException:
                await self.say(message, f"I could not download `{attachment.filename}`.")
                return
        await self.say(
            message,
            embed=document_embed(info),
            file=discord.File(io.BytesIO(info.text.encode("utf-8")), filename=info.name),
            view=UpdateView(self),
        )

    async def _replace(self, message, attachment, actor: str) -> None:
        name = doc_name(attachment.filename)
        if name is None or attachment.size > MAX_TEXT_BYTES:
            await self.say(
                message,
                "Post the `.md` file back under its original name (lowercase letters, digits and "
                "dashes), and keep it under 1 MB.",
            )
            return
        try:
            text = (await attachment.read()).decode("utf-8").replace("\r\n", "\n")
            info = await self.run(self.ops.replace, name, text, actor)
        except UnicodeDecodeError:
            await self.say(message, "That file is not UTF-8 text.")
            return
        except StoreError as error:
            await self.say(message, str(error))  # the store's own wording ("Not saved: ...")
            return
        await self.say(
            message,
            embed=document_embed(info, saved=True),
            view=UpdateView(self) if info.status == "draft" else None,
        )

    async def _command(self, message, word: str, args: list[str], actor: str) -> None:
        if word == "help":
            await self.say(message, HELP)
            return
        if word == "list":
            await self.say(message, embed=listing_embed(await self.run(self.ops.listing)))
            return
        if word == "import":
            if args[0].lower() != "builtin":
                await self.say(message, "Say `import builtin` to bring in the built-in documents.")
                return
            try:
                names = await self.run(self.ops.import_builtin, actor)
            except StoreError as error:
                await self.say(message, str(error))
                return
            await self.say(
                message,
                f"Imported {len(names)} built-in document(s). They are live, with the same Qwen "
                "settings as before. Say `list` to see them."
                if names
                else "Nothing to import: the built-in documents are already here.",
            )
            return
        name = doc_name(args[0])
        if name is None:
            await self.say(message, "That is not a document name. Say `list` to see them.")
            return
        try:
            if word == "get":
                info = await self.run(self.ops.info, name)
                await self.say(
                    message,
                    embed=document_embed(info),
                    file=discord.File(io.BytesIO(info.text.encode("utf-8")), filename=name),
                )
            elif word == "archive":
                info = await self.run(self.ops.archive, name, actor)
                await self.say(message, f"Archived `{name}`. Gigi no longer answers from it.")
            elif word == "restore":
                info = await self.run(self.ops.restore, name, actor)
                await self.say(
                    message,
                    f"`{name}` is live again (Qwen may use it: {'yes' if info.qwen else 'no'}).",
                )
            elif word == "qwen":
                if args[1].lower() not in ("on", "off"):
                    await self.say(message, "Say `qwen <name> on` or `qwen <name> off`.")
                    return
                on = args[1].lower() == "on"
                await self.run(self.ops.set_qwen, name, on, actor)
                await self.say(message, f"Qwen {'may' if on else 'may no longer'} use `{name}`.")
            elif word == "delete":
                info = await self.run(self.ops.info, name)
                if info.status == "current":
                    await self.say(message, "That document is live. Archive it first.")
                    return
                embed = discord.Embed(
                    title=_clip(f"Delete {info.title} permanently?", 250),
                    description=(
                        "This cannot be undone. Saved versions and the activity log are kept."
                    ),
                    colour=discord.Colour.red(),
                )
                embed.set_footer(text=f"document: {name}")
                await self.say(message, embed=embed, view=DeleteView(self))
        except StoreError as error:
            await self.say(message, str(error))

    # -- buttons
    async def on_button(self, interaction: discord.Interaction, action: str) -> None:
        channel = interaction.channel
        if not self.is_updates_channel(channel) or self.channel_problem(channel):
            await interaction.response.send_message(
                "These buttons only work in Gigi's private updates channel.", ephemeral=True
            )
            return
        if not self.allowed(interaction.user):
            await interaction.response.send_message(
                "You do not have a role that may change Gigi's documents.", ephemeral=True
            )
            return
        footer = interaction.message.embeds[0].footer.text if interaction.message.embeds else ""
        found = FOOTER.match(footer or "")
        if not found:
            await interaction.response.send_message(
                "I cannot tell which document this is. Say `list`.", ephemeral=True
            )
            return
        name, actor = found.group(1), self.actor(interaction.user)
        await interaction.response.defer()
        try:
            if action in ("publish", "publish_qwen"):
                info = await self.run(self.ops.publish, name, actor, action == "publish_qwen")
                done = (
                    f"Published **{info.title}** ({info.entries} entries). Gigi answers from it "
                    f"on the next question. Qwen may use it: {'yes' if info.qwen else 'no'}."
                )
            elif action == "discard":
                await self.run(self.ops.discard, name, actor)
                done = f"Discarded the draft `{name}`."
            else:
                await self.run(self.ops.delete, name, actor)
                done = f"Deleted `{name}`. Its saved versions and the activity log are kept."
        except StoreError as error:
            await interaction.followup.send(_clip(f"Not done: {error}", 1900), ephemeral=True)
            return
        except Exception:
            log.exception("[Updates] Button %s failed for %s", action, name)
            await interaction.followup.send(
                "Something went wrong (details are in the bot's log).", ephemeral=True
            )
            return
        try:
            await interaction.message.edit(view=None)  # the buttons have done their job
        except discord.HTTPException:
            pass
        await interaction.followup.send(done, allowed_mentions=discord.AllowedMentions.none())


def build_knowledge_updates(bot, settings) -> KnowledgeUpdates | None:
    """None (with the reason logged) unless the channel is switched on and the write account is
    set. Never raises: the rest of the bot must start regardless."""
    cfg = settings.knowledge_updates
    if not cfg.enabled:
        return None
    url = os.environ.get("GAB_KNOWLEDGE_ADMIN_DB", "").strip()
    if not url:
        log.error(
            "[Updates] The upload channel is OFF: set GAB_KNOWLEDGE_ADMIN_DB (the database "
            "account that may write the documents)"
        )
        return None
    if settings.knowledge_store is None:
        log.warning(
            "[Updates] GAB_KNOWLEDGE_DB (the bot's read-only account) is not set, so Gigi will "
            "not pick up documents published here"
        )
    store = ReconnectingStore(lambda: open_store(url))
    log.info(
        "[Updates] Upload channel #%s is ON (private staff channel; database %s)",
        cfg.channel,
        redact_location(url),
    )
    return KnowledgeUpdates(bot, cfg, DocumentOps(store, settings.knowledge_dir))
