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
import json
import logging
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import discord
import yaml

from .admin.pdf_import import PdfImportError, draft_markdown, extract_pages_isolated
from .config import KnowledgeUpdatesSettings
from .discord_common import find_text_channel
from .knowledge_store import (
    MAX_PDF_BYTES,
    MAX_TEXT_BYTES,
    NAME_RE,
    ReconnectingStore,
    StoreError,
    check_pdf,
    now_iso,
    open_store,
    redact_location,
    slugify,
    validate_document,
)
from .tutorials import load_tutorials

log = logging.getLogger(__name__)

PUBLISH, PUBLISH_QWEN = "gab_kb:publish", "gab_kb:publish_qwen"
DISCARD, DELETE = "gab_kb:discard", "gab_kb:delete"
PANEL_UPLOAD, PANEL_LIST = "gab_kb:panel_upload", "gab_kb:panel_list"
PANEL_IMPORT = "gab_kb:panel_import"
PANEL_FILES, PANEL_ARCHIVE_ALL = "gab_kb:panel_files", "gab_kb:panel_archive_all"
PANEL_VIDEO = "gab_kb:panel_video"
PANEL_CHANNELS = "gab_kb:panel_channels"
CHANNELS_FILE = "answer-channels.json"
MAX_EXTRA_CHANNELS = 20
DRIVE_HOSTS = ("drive.google.com", "docs.google.com")
ENTRY_ID = re.compile(r"^[A-Z]{1,3}\d+[a-z]?$")
MAX_VIDEO_ENTRIES = 12
PANEL_FOOTER = "gigi-updates-panel"
FOOTER = re.compile(r"^document: ([a-z0-9][a-z0-9-]{0,62}\.md)$")
MAX_PDFS_PER_MESSAGE = 5
PROBLEM_REPLY_EVERY = 600  # seconds between "this channel is not private" explanations

HELP = (
    "**Drop a PDF** here and I'll draft FAQ entries from it. Nothing goes live until you press "
    "Publish.\n"
    "**Edit a draft:** download the attached `.md`, change it, and post it back here under the "
    "same file name.\n"
    "`list` · `get <name>` · `archive <name>` · `restore <name>` · `delete <name>` · "
    "`qwen <name> on|off` · `import builtin` (once, before the first publish) · `panel` (post the "
    "button panel again)\n"
    "Archive takes a live document offline (restore brings it back). Delete is permanent and "
    "only for drafts and archived documents; saved versions and the activity log are kept."
)


def _clip(text: str, limit: int) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def parse_drive_link(raw: str) -> str:
    """A Google Drive link and nothing else: https, the Drive/Docs host exactly (so
    drive.google.com.evil.example and user@ tricks are refused), no spaces, no credentials."""
    link = (raw or "").strip()
    try:
        parts = urlsplit(link)
        port = parts.port
    except ValueError:
        raise StoreError("That is not a valid link.") from None
    if (
        not link
        or len(link) > 500
        or any(c.isspace() or c in "<>\"'" for c in link)
        or parts.scheme != "https"
        or parts.username is not None
        or parts.password is not None
        or port not in (None, 443)
        or (parts.hostname or "").lower() not in DRIVE_HOSTS
    ):
        raise StoreError(
            "Paste a Google Drive link that starts with https://drive.google.com/ "
            "(or https://docs.google.com/)."
        )
    return link


def parse_entry_ids(raw: str) -> list[str]:
    """'a5, PG3  in6' -> ['A5', 'PG3', 'IN6']: the FAQ entries the video belongs to."""
    ids = []
    for token in re.split(r"[\s,;]+", (raw or "").strip()):
        if not token:
            continue
        ident = token.upper()
        if not ENTRY_ID.match(ident):
            raise StoreError(
                f"`{token[:20]}` is not a FAQ entry ID. Entry IDs look like A5, PG3 or IN28."
            )
        if ident not in ids:
            ids.append(ident)
    if not ids:
        raise StoreError("Say which FAQ entries the video belongs to, for example A5, PG3.")
    if len(ids) > MAX_VIDEO_ENTRIES:
        raise StoreError(f"At most {MAX_VIDEO_ENTRIES} entries per video.")
    return ids


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
        "panel": 0,
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
class UploadedFiles:
    """What has been uploaded: the PDFs (and the document each became) and the tutorial videos
    Gigi attaches to answers (links in the catalog; videos themselves are not uploaded here)."""

    pdfs: tuple[dict, ...]
    videos: tuple[dict, ...]


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


class ChannelScope:
    """Channels, besides the ones in config.yaml, where Gigi answers when someone @mentions it.
    Saved in the database (so it survives restarts); read from memory when a message arrives.
    Never turns on auto-answering: those channels are only ever mention-only."""

    def __init__(self, store):
        self.store = store
        self.channels: dict[str, dict] = {}
        self.ids: frozenset[str] = frozenset()

    def _set(self, channels: dict[str, dict]) -> None:
        self.channels, self.ids = channels, frozenset(channels)  # replaced whole: safe to read

    def load(self) -> None:
        text = self.store.get_support(CHANNELS_FILE)
        try:
            items = json.loads(text)["channels"] if text else []
        except (ValueError, KeyError, TypeError):
            log.error("[Updates] %s is unreadable; no extra channels are active", CHANNELS_FILE)
            items = []
        self._set(
            {
                str(c["id"]): c
                for c in items
                if isinstance(c, dict) and str(c.get("id", "")).isdigit()
            }
        )

    def _save(self, channels: dict[str, dict], actor: str) -> None:
        self.store.set_support(
            CHANNELS_FILE, json.dumps({"channels": list(channels.values())}, indent=1), actor
        )
        self._set(channels)  # only after the database accepted it

    def add(self, channel_id: str, name: str, actor: str) -> None:
        if channel_id in self.channels:
            raise StoreError(f"Gigi already answers in #{name}.")
        if len(self.channels) >= MAX_EXTRA_CHANNELS:
            raise StoreError(f"At most {MAX_EXTRA_CHANNELS} extra channels. Turn one off first.")
        entry = {"id": channel_id, "name": name[:100], "added_by": actor, "added_at": now_iso()}
        self._save({**self.channels, channel_id: entry}, actor)

    def remove(self, channel_id: str, actor: str) -> dict:
        if channel_id not in self.channels:
            raise StoreError("Gigi is not on in that channel.")
        gone = self.channels[channel_id]
        self._save({k: v for k, v in self.channels.items() if k != channel_id}, actor)
        return gone


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
        # Discord turns spaces in uploaded file names into underscores: show them as spaces again.
        stem = " ".join(filename.rsplit(".", 1)[0].replace("_", " ").split())
        title = title or stem or "Untitled"
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

    def _videos(self) -> tuple[dict, ...]:
        text = self.store.get_support("playground-videos.yaml")
        if text is None and self.builtin_dir:
            catalog = self.builtin_dir / "playground-videos.yaml"
            text = catalog.read_text(encoding="utf-8") if catalog.exists() else None
        try:
            data = yaml.safe_load(text or "") or {}
        except yaml.YAMLError:
            return ()
        items = data.get("videos") if isinstance(data, dict) else None
        videos = []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and item.get("title"):
                url = str(item.get("url") or "")
                videos.append(
                    {
                        "title": str(item["title"]),
                        "url": url if url.startswith(("https://", "http://")) else "",
                        "faq_ids": [str(i) for i in item.get("faq_ids") or []],
                    }
                )
        return tuple(videos)

    def add_video(self, title: str, url: str, entry_text: str, actor: str) -> dict:
        """Add a Google Drive video to the tutorial catalog. Gigi then shows the link next to the
        answers for those FAQ entries. The catalog is extended, never replaced: if the database
        has none yet it starts from the one built into the image."""
        title = clean_title(title)
        if not title:
            raise StoreError("Give the video a title.")
        link = parse_drive_link(url)
        ids = parse_entry_ids(entry_text)
        known = set().union(*self.store.entry_ids_of_current().values())
        if not known:
            raise StoreError(
                "The database has no live documents yet, so there are no FAQ entries to attach "
                "the video to. Press Import built-in first."
            )
        unknown = [i for i in ids if i not in known]
        if unknown:
            raise StoreError(
                f"These FAQ entries are not in any live document: {', '.join(unknown)}. Open "
                "Documents and Download .md to see the entry IDs."
            )
        text = self.store.get_support("playground-videos.yaml")
        if text is None and self.builtin_dir:
            catalog = self.builtin_dir / "playground-videos.yaml"
            text = catalog.read_text(encoding="utf-8") if catalog.exists() else None
        data = yaml.safe_load(text or "") or {}
        if not isinstance(data, dict):
            data = {}
        videos = list(data.get("videos") or [])
        if any(str(v.get("url") or "") == link for v in videos if isinstance(v, dict)):
            raise StoreError("That link is already in the tutorial catalog.")
        taken = {str(v.get("id")) for v in videos if isinstance(v, dict)}
        base = slugify(title)[:-3][:40].strip("-") or "video"
        ident, number = base, 2
        while ident in taken:
            ident, number = f"{base}-{number}", number + 1
        entry = {"id": ident, "title": title, "url": link, "faq_ids": ids}
        data["videos"] = videos + [entry]
        data["updated"] = date.today().isoformat()
        out = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        self._check_catalog(out)
        self.store.set_support("playground-videos.yaml", out, actor)
        return entry

    @staticmethod
    def _check_catalog(text: str) -> None:
        """The bot's own catalog loader must accept it, or nothing is saved."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "playground-videos.yaml"
            path.write_text(text, encoding="utf-8")
            try:
                load_tutorials(path)
            except ValueError as error:
                raise StoreError(f"That video could not be added: {error}") from None

    def files(self) -> UploadedFiles:
        by_file: dict[str, list[str]] = {}
        for doc in self.store.list_documents():
            if doc.source_sha256:
                by_file.setdefault(doc.source_sha256, []).append(doc.name)
        pdfs = tuple(
            {**row, "documents": tuple(by_file.get(row["sha256"], ()))}
            for row in self.store.list_pdfs()
        )
        return UploadedFiles(pdfs, self._videos())

    def archive_all_except(self, keep, actor: str) -> tuple[list[str], list[str]]:
        """Archive every live document except `keep`. At least one must stay live: Gigi always
        needs something to answer from. Returns (archived names, failures with reasons)."""
        live = {d.name for d in self.store.list_documents("current")}
        kept = set(keep) & live
        if not kept:
            raise StoreError(
                "Choose at least one live document to keep: Gigi always needs something to "
                "answer from."
            )
        archived, failed = [], []
        for name in sorted(live - kept):
            try:
                self.store.archive(name, actor)
                archived.append(name)
            except StoreError as error:
                failed.append(f"{name}: {error}")
        return archived, failed

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


def _escape(text: str) -> str:
    """Keep a file or video title from turning into Discord formatting or a fake link."""
    return re.sub(r"([\\*_`~|>\[\]()])", r"\\\1", str(text))


def _size(count: int) -> str:
    return (
        f"{count / 1024 / 1024:.1f} MB" if count >= 1024 * 1024 else f"{max(1, count // 1024)} KB"
    )


def _field_text(lines: list[str], empty: str, limit: int = 1000) -> str:
    if not lines:
        return empty
    shown, used = [], 0
    for line in lines:
        if used + len(line) + 1 > limit:
            shown.append(f"…and {len(lines) - len(shown)} more")
            break
        shown.append(line)
        used += len(line) + 1
    return "\n".join(shown)


def files_embed(files: UploadedFiles) -> discord.Embed:
    pdf_lines = []
    for row in files.pdfs:
        who = str(row.get("uploaded_by", "")).split(" (")[0]
        became = ", ".join(f"`{n}`" for n in row["documents"]) or "(document deleted)"
        pdf_lines.append(
            f"• **{_escape(row['filename'])}** · {_size(row['size'])} · "
            f"{who} · {str(row['uploaded_at'])[:10]} → {became}"
        )
    video_lines = []
    for video in files.videos:
        title = _escape(video["title"])
        label = f"[{title}]({video['url']})" if video["url"] else title
        used = ", ".join(video["faq_ids"][:6]) or "no entries"
        video_lines.append(f"• {label} → {used}")
    embed = discord.Embed(title="Uploaded files", colour=discord.Colour.blurple())
    embed.add_field(
        name=f"PDFs uploaded ({len(files.pdfs)})",
        value=_field_text(pdf_lines, "None yet. Press **Upload PDF**."),
        inline=False,
    )
    embed.add_field(
        name=f"Tutorial videos ({len(files.videos)})",
        value=_field_text(video_lines, "None in the tutorial catalog."),
        inline=False,
    )
    embed.set_footer(
        text="Videos are links Gigi shows next to the matching answers. Upload accepts PDFs only."
    )
    return embed


def panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Gigi's documents",
        description=(
            "**Upload PDF** — pick a guideline PDF and I draft FAQ entries from it. Nothing goes "
            "live until you publish.\n"
            "**Documents** — see them all, then download, publish, archive, restore, delete or "
            "change Qwen access.\n"
            "**Uploaded files** — the PDFs uploaded so far and the tutorial videos Gigi knows.\n"
            "**Add video link** — attach a Google Drive video to the FAQ entries it explains.\n"
            "**Archive everything** — take all live documents offline except the ones you keep.\n"
            "**Gigi in other channels** — let Gigi answer in more channels, only when "
            "someone @mentions it.\n"
            "**Import built-in** — once, before the first publish, so Gigi keeps the FAQ it "
            "already has."
        ),
        colour=discord.Colour.blurple(),
    )
    embed.set_footer(text=PANEL_FOOTER)
    return embed


class PanelView(discord.ui.View):
    """The standing buttons under the panel message. Fixed custom_ids: they survive restarts."""

    def __init__(self, updates: KnowledgeUpdates):
        super().__init__(timeout=None)
        self.updates = updates

    @discord.ui.button(
        label="Upload PDF", style=discord.ButtonStyle.primary, custom_id=PANEL_UPLOAD
    )
    async def upload(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.open_upload(interaction)

    @discord.ui.button(label="Documents", style=discord.ButtonStyle.secondary, custom_id=PANEL_LIST)
    async def documents(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.open_documents(interaction)

    @discord.ui.button(
        label="Uploaded files", style=discord.ButtonStyle.secondary, custom_id=PANEL_FILES
    )
    async def uploaded_files(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.open_files(interaction)

    @discord.ui.button(
        label="Add video link", style=discord.ButtonStyle.secondary, custom_id=PANEL_VIDEO
    )
    async def add_video(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.open_add_video(interaction)

    @discord.ui.button(
        label="Archive everything", style=discord.ButtonStyle.danger, custom_id=PANEL_ARCHIVE_ALL
    )
    async def archive_everything(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.open_archive_all(interaction)

    @discord.ui.button(
        label="Gigi in other channels",
        style=discord.ButtonStyle.secondary,
        custom_id=PANEL_CHANNELS,
    )
    async def other_channels(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.open_channels(interaction)

    @discord.ui.button(
        label="Import built-in", style=discord.ButtonStyle.secondary, custom_id=PANEL_IMPORT
    )
    async def import_builtin(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.updates.import_builtin_button(interaction)


class UploadModal(discord.ui.Modal):
    """The file-picker dialog opened by Upload PDF."""

    def __init__(self, updates: KnowledgeUpdates):
        super().__init__(title="Upload a PDF", timeout=None)
        self.updates = updates
        self.title_input = discord.ui.TextInput(
            required=False, max_length=120, placeholder="Leave empty to use the file name"
        )
        self.file_input = discord.ui.FileUpload(required=True, min_values=1, max_values=1)
        self.add_item(discord.ui.Label(text="Title (optional)", component=self.title_input))
        self.add_item(
            discord.ui.Label(
                text="PDF file",
                description="A PDF with selectable text, up to 25 MB",
                component=self.file_input,
            )
        )

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.updates.on_upload_submit(
            interaction, self.title_input.value or "", list(self.file_input.values)
        )


class AddVideoModal(discord.ui.Modal):
    """The dialog opened by Add video link."""

    def __init__(self, updates: KnowledgeUpdates):
        super().__init__(title="Add a video link", timeout=None)
        self.updates = updates
        self.title_input = discord.ui.TextInput(max_length=120, placeholder="What the video shows")
        self.link_input = discord.ui.TextInput(
            max_length=500, placeholder="https://drive.google.com/file/d/..."
        )
        self.entries_input = discord.ui.TextInput(
            max_length=120, placeholder="FAQ entry IDs it explains, e.g. A5, PG3"
        )
        self.add_item(discord.ui.Label(text="Title", component=self.title_input))
        self.add_item(
            discord.ui.Label(
                text="Google Drive link",
                description="Share it as 'anyone with the link can view'",
                component=self.link_input,
            )
        )
        self.add_item(discord.ui.Label(text="FAQ entries", component=self.entries_input))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.updates.on_add_video_submit(
            interaction,
            self.title_input.value or "",
            self.link_input.value or "",
            self.entries_input.value or "",
        )


class ChannelSelect(discord.ui.ChannelSelect):
    def __init__(self, updates: KnowledgeUpdates):
        super().__init__(
            placeholder="Turn Gigi on in a channel…",
            channel_types=[discord.ChannelType.text],
            min_values=1,
            max_values=1,
        )
        self.updates = updates

    async def callback(self, interaction: discord.Interaction):
        await self.updates.choose_channel(interaction, self.values[0])


class TurnOffSelect(discord.ui.Select):
    def __init__(self, updates: KnowledgeUpdates, channels: list[dict]):
        super().__init__(
            placeholder="Turn Gigi off in…",
            options=[
                discord.SelectOption(label=_clip("#" + c["name"], 100), value=c["id"])
                for c in channels[:25]
            ],
        )
        self.updates = updates

    async def callback(self, interaction: discord.Interaction):
        await self.updates.disable_channel(interaction, self.values[0])


class ChannelsView(discord.ui.View):
    def __init__(self, updates: KnowledgeUpdates):
        super().__init__(timeout=900)
        self.add_item(ChannelSelect(updates))
        if updates.scope.channels:
            self.add_item(TurnOffSelect(updates, list(updates.scope.channels.values())))


class DocumentSelect(discord.ui.Select):
    def __init__(self, updates: KnowledgeUpdates, infos: list[DocInfo]):
        options = [
            discord.SelectOption(
                label=_clip(i.title or i.name, 100),
                value=i.name,
                description=_clip(
                    f"{STATUS_WORD.get(i.status, i.status)} · {i.entries} entries · "
                    f"Qwen {'yes' if i.qwen else 'no'}",
                    100,
                ),
            )
            for i in infos[:25]
        ]
        super().__init__(placeholder="Choose a document…", options=options)
        self.updates = updates

    async def callback(self, interaction: discord.Interaction):
        await self.updates.show_document(interaction, self.values[0])


class DocumentsView(discord.ui.View):
    def __init__(self, updates: KnowledgeUpdates, infos: list[DocInfo]):
        super().__init__(timeout=900)
        self.add_item(DocumentSelect(updates, infos))


class ActionButton(discord.ui.Button):
    """One button that runs one action on one document."""

    def __init__(self, updates: KnowledgeUpdates, name: str, action: str, label: str, style):
        super().__init__(label=label, style=style)
        self.updates, self.doc, self.action = updates, name, action

    async def callback(self, interaction: discord.Interaction):
        await self.updates.document_action(interaction, self.doc, self.action)


class DocumentView(discord.ui.View):
    """The buttons that fit this document's state (a draft can be published, a live one
    archived, an archived one restored). Not persistent: reopen Documents after a restart."""

    def __init__(self, updates: KnowledgeUpdates, info: DocInfo):
        super().__init__(timeout=900)
        style = discord.ButtonStyle

        def add(action: str, label: str, look) -> None:
            self.add_item(ActionButton(updates, info.name, action, label, look))

        add("download", "Download .md", style.secondary)
        if info.status == "draft":
            add("publish", "Publish", style.success)
            add("publish_qwen", "Publish & allow Qwen", style.primary)
        elif info.status == "current":
            add("archive", "Archive", style.secondary)
            add(
                "qwen_off" if info.qwen else "qwen_on",
                "Stop Qwen using it" if info.qwen else "Allow Qwen",
                style.secondary,
            )
        elif info.status == "archived":
            add("restore", "Restore", style.success)
        if info.status != "current":
            add("ask_delete", "Delete…", style.danger)
        add("back", "Back to the list", style.secondary)


class CallbackButton(discord.ui.Button):
    def __init__(self, label: str, style, callback):
        super().__init__(label=label, style=style)
        self._callback = callback

    async def callback(self, interaction: discord.Interaction):
        await self._callback(interaction)


class KeepSelect(discord.ui.Select):
    def __init__(self, updates: KnowledgeUpdates, live: list[DocInfo]):
        options = [
            discord.SelectOption(
                label=_clip(i.title or i.name, 100),
                value=i.name,
                description=_clip(f"{i.entries} entries · Qwen {'yes' if i.qwen else 'no'}", 100),
            )
            for i in live[:25]
        ]
        super().__init__(
            placeholder="Documents to KEEP live (at least one)",
            min_values=1,
            max_values=len(options),
            options=options,
        )
        self.updates = updates

    async def callback(self, interaction: discord.Interaction):
        await self.updates.choose_keep(interaction, list(self.values))


class KeepView(discord.ui.View):
    def __init__(self, updates: KnowledgeUpdates, live: list[DocInfo]):
        super().__init__(timeout=900)
        self.add_item(KeepSelect(updates, live))


class ConfirmArchiveAllView(discord.ui.View):
    def __init__(self, updates: KnowledgeUpdates, keep: list[str], count: int):
        super().__init__(timeout=300)

        async def confirm(interaction: discord.Interaction):
            await updates.confirm_archive_all(interaction, keep)

        async def cancel(interaction: discord.Interaction):
            await updates.cancel(interaction)

        self.add_item(
            CallbackButton(f"Archive {count} document(s)", discord.ButtonStyle.danger, confirm)
        )
        self.add_item(CallbackButton("Cancel", discord.ButtonStyle.secondary, cancel))


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, updates: KnowledgeUpdates, name: str):
        super().__init__(timeout=300)
        self.add_item(
            ActionButton(
                updates, name, "delete", "Yes, delete permanently", discord.ButtonStyle.danger
            )
        )
        self.add_item(ActionButton(updates, name, "show", "Cancel", discord.ButtonStyle.secondary))


# ---- the channel -----------------------------------------------------------------------------
class KnowledgeUpdates:
    def __init__(self, bot, settings: KnowledgeUpdatesSettings, ops: DocumentOps):
        self.bot, self.settings, self.ops = bot, settings, ops
        self.scope = ChannelScope(ops.store)
        self._explained: dict[int, float] = {}

    async def start(self) -> None:
        """Makes the buttons on old messages work again after a restart."""
        self.bot.add_view(UpdateView(self))
        self.bot.add_view(DeleteView(self))
        self.bot.add_view(PanelView(self))
        await self.reload_scope()

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
        if word == "panel":
            await self.ensure_panel(message.channel)
            await self.say(message, "The panel is at the top of the channel (pinned if I may).")
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
        if not await self._gate(interaction):
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

    # -- the panel and its flows
    async def _gate(self, interaction: discord.Interaction) -> bool:
        """The same rules for every button, menu and dialog: right channel, private, right role.
        Answers the person (privately) and returns False when any fails."""
        channel = interaction.channel
        if not self.is_updates_channel(channel) or self.channel_problem(channel):
            await interaction.response.send_message(
                "These buttons only work in Gigi's private updates channel.", ephemeral=True
            )
            return False
        if not self.allowed(interaction.user):
            await interaction.response.send_message(
                "You do not have a role that may change Gigi's documents.", ephemeral=True
            )
            return False
        return True

    async def ensure_panel(self, channel) -> None:
        """Post the button panel in the channel, or refresh the one already there."""
        existing = None
        async for message in channel.history(limit=50):
            if (
                message.author.id == self.bot.user.id
                and message.embeds
                and (message.embeds[0].footer.text or "") == PANEL_FOOTER
            ):
                existing = message
                break
        if existing:
            await existing.edit(embed=panel_embed(), view=PanelView(self))
            return
        posted = await channel.send(
            embed=panel_embed(),
            view=PanelView(self),
            allowed_mentions=discord.AllowedMentions.none(),
        )
        try:
            await posted.pin()
        except discord.HTTPException:
            pass  # no Manage Messages: the panel simply is not pinned

    async def ensure_panels(self, guilds) -> None:
        """At start-up: a panel in the updates channel of every server this bot is in."""
        for guild in guilds:
            channel = find_text_channel(guild, self.settings.channel)
            if channel is None:
                continue
            problem = self.channel_problem(channel)
            if problem:
                log.warning("[Updates] No panel in #%s: %s", channel.name, problem)
                continue
            try:
                await self.ensure_panel(channel)
            except discord.HTTPException:
                log.exception("[Updates] Could not post the panel in #%s", channel.name)

    async def open_upload(self, interaction: discord.Interaction) -> None:
        if await self._gate(interaction):
            await interaction.response.send_modal(UploadModal(self))

    async def on_upload_submit(self, interaction: discord.Interaction, title: str, files) -> None:
        if not await self._gate(interaction):
            return
        attachment = files[0] if files else None
        if attachment is None or not attachment.filename.lower().endswith(".pdf"):
            await interaction.response.send_message(
                "That is not a PDF. Choose a `.pdf` file.", ephemeral=True
            )
            return
        if attachment.size > MAX_PDF_BYTES:
            await interaction.response.send_message(
                f"`{attachment.filename}` is larger than 25 MB.", ephemeral=True
            )
            return
        await interaction.response.defer(thinking=True)  # reading a PDF takes a few seconds
        try:
            data = await attachment.read()
            info = await self.run(
                self.ops.new_draft,
                data,
                attachment.filename,
                clean_title(title),
                self.actor(interaction.user),
            )
        except (StoreError, PdfImportError) as error:
            await interaction.followup.send(f"I could not use `{attachment.filename}`: {error}")
            return
        except discord.HTTPException:
            await interaction.followup.send(f"I could not download `{attachment.filename}`.")
            return
        except Exception:
            log.exception("[Updates] Upload from the panel failed")
            await interaction.followup.send("Something went wrong (details are in the bot's log).")
            return
        await interaction.followup.send(
            embed=document_embed(info),
            file=discord.File(io.BytesIO(info.text.encode("utf-8")), filename=info.name),
            view=UpdateView(self),
        )

    async def open_documents(self, interaction: discord.Interaction, edit: bool = False) -> None:
        if not await self._gate(interaction):
            return
        if edit:
            await interaction.response.defer()
        else:
            await interaction.response.defer(ephemeral=True)
        infos = await self.run(self.ops.listing)
        if not infos:
            text = "No documents yet. Press **Upload PDF**, or **Import built-in** first."
            if edit:
                await interaction.edit_original_response(content=text, embed=None, view=None)
            else:
                await interaction.followup.send(text, ephemeral=True)
            return
        embed, view = listing_embed(infos), DocumentsView(self, infos)
        if edit:
            await interaction.edit_original_response(content=None, embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def show_document(self, interaction: discord.Interaction, name: str) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer()
        try:
            info = await self.run(self.ops.info, name)
        except StoreError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await interaction.edit_original_response(
            content=None, embed=document_embed(info), view=DocumentView(self, info)
        )

    async def document_action(self, interaction: discord.Interaction, name: str, action: str):
        if not await self._gate(interaction):
            return
        actor = self.actor(interaction.user)
        if action == "back":
            await self.open_documents(interaction, edit=True)
            return
        if action == "ask_delete":
            embed = discord.Embed(
                title=_clip(f"Delete {name} permanently?", 250),
                description="This cannot be undone. Saved versions and the activity log are kept.",
                colour=discord.Colour.red(),
            )
            await interaction.response.edit_message(
                content=None, embed=embed, view=ConfirmDeleteView(self, name)
            )
            return
        if action == "download":
            try:
                info = await self.run(self.ops.info, name)
            except StoreError as error:
                await interaction.response.send_message(str(error), ephemeral=True)
                return
            await interaction.response.send_message(
                file=discord.File(io.BytesIO(info.text.encode("utf-8")), filename=name),
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        note = None
        try:
            if action in ("publish", "publish_qwen"):
                info = await self.run(self.ops.publish, name, actor, action == "publish_qwen")
                note = (
                    f"Published. Gigi answers from it on the next question "
                    f"(Qwen may use it: {'yes' if info.qwen else 'no'})."
                )
            elif action == "archive":
                await self.run(self.ops.archive, name, actor)
                note = "Archived. Gigi no longer answers from it."
            elif action == "restore":
                info = await self.run(self.ops.restore, name, actor)
                note = f"Live again (Qwen may use it: {'yes' if info.qwen else 'no'})."
            elif action in ("qwen_on", "qwen_off"):
                await self.run(self.ops.set_qwen, name, action == "qwen_on", actor)
                note = "Qwen access updated."
            elif action == "delete":
                await self.run(self.ops.delete, name, actor)
                await interaction.edit_original_response(
                    content=f"Deleted `{name}`. Its saved versions and the activity log are kept.",
                    embed=None,
                    view=None,
                )
                return
            info = await self.run(self.ops.info, name)
        except StoreError as error:
            await interaction.followup.send(_clip(f"Not done: {error}", 1900), ephemeral=True)
            return
        except Exception:
            log.exception("[Updates] Panel action %s failed for %s", action, name)
            await interaction.followup.send(
                "Something went wrong (details are in the bot's log).", ephemeral=True
            )
            return
        await interaction.edit_original_response(
            content=note, embed=document_embed(info), view=DocumentView(self, info)
        )

    async def open_add_video(self, interaction: discord.Interaction) -> None:
        if await self._gate(interaction):
            await interaction.response.send_modal(AddVideoModal(self))

    async def on_add_video_submit(
        self, interaction: discord.Interaction, title: str, link: str, entries: str
    ) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            video = await self.run(
                self.ops.add_video, title, link, entries, self.actor(interaction.user)
            )
        except StoreError as error:
            await interaction.followup.send(_clip(f"Not added: {error}", 1900), ephemeral=True)
            return
        except Exception:
            log.exception("[Updates] Adding a video failed")
            await interaction.followup.send(
                "Something went wrong (details are in the bot's log).", ephemeral=True
            )
            return
        await interaction.followup.send(
            f"Added **{video['title']}**. Gigi shows the link next to its answers for "
            f"{', '.join(video['faq_ids'])} from the next question.",
            ephemeral=True,
        )

    # -- Gigi in other channels (mention-only)
    async def reload_scope(self) -> None:
        try:
            await self.run(self.scope.load)
        except Exception:
            log.exception("[Updates] Could not read the extra channels; none are active")

    def in_extra_scope(self, *keys) -> bool:
        """True if one of these channel keys (names, IDs, a thread's parent) was added with the
        Gigi in other channels button. Used by the FAQ answering to widen its scope."""
        ids = self.scope.ids
        return any(key in ids for key in keys if key)

    def _channels_embed(self) -> discord.Embed:
        lines = [
            f"• <#{c['id']}> — turned on by {str(c.get('added_by', '?')).split(' (')[0]}"
            for c in self.scope.channels.values()
        ]
        return discord.Embed(
            title="Gigi in other channels",
            description=(
                "Gigi answers in these channels **only when someone @mentions it**. It never "
                "answers unprompted, and everyone who can read a channel can ask there. The "
                "channels in config.yaml keep working as before.\n\n"
                + (_clip("\n".join(lines), 3000) if lines else "None added yet.")
            ),
            colour=discord.Colour.blurple(),
        )

    async def open_channels(self, interaction: discord.Interaction, edit: bool = False) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer(ephemeral=not edit)
        await self.reload_scope()
        embed, view = self._channels_embed(), ChannelsView(self)
        if edit:
            await interaction.edit_original_response(content=None, embed=embed, view=view)
        else:
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def choose_channel(self, interaction: discord.Interaction, picked) -> None:
        if not await self._gate(interaction):
            return
        guild = interaction.guild
        channel = guild.get_channel(picked.id) if guild else None
        problem = None
        if not isinstance(channel, discord.TextChannel):
            problem = "I can only answer in text channels of this server."
        elif self.is_updates_channel(channel):
            problem = "That is this staff channel. Pick a channel where freelancers ask."
        elif str(channel.id) in self.scope.ids:
            problem = f"Gigi already answers in #{channel.name}."
        else:
            allowed = channel.permissions_for(guild.me)
            if not (allowed.view_channel and allowed.send_messages):
                problem = (
                    f"I cannot see or post in #{channel.name}. Give me View Channel and Send "
                    "Messages there first, then try again."
                )
        if problem:
            await interaction.response.send_message(problem, ephemeral=True)
            return
        await interaction.response.defer()
        embed = discord.Embed(
            title=f"Turn Gigi on in #{channel.name}?",
            description=(
                "Everyone who can read the channel will be able to ask Gigi by **@mentioning** "
                "it. Gigi will not answer anything else there. Answers come from the shared "
                "FAQ (and use the Qwen quota)."
            ),
            colour=discord.Colour.orange(),
        )
        view = discord.ui.View(timeout=300)

        async def confirm(i: discord.Interaction):
            await self.enable_channel(i, str(channel.id), channel.name)

        async def cancel(i: discord.Interaction):
            await self.open_channels(i, edit=True)

        view.add_item(CallbackButton("Turn on", discord.ButtonStyle.success, confirm))
        view.add_item(CallbackButton("Cancel", discord.ButtonStyle.secondary, cancel))
        await interaction.edit_original_response(content=None, embed=embed, view=view)

    async def enable_channel(self, interaction, channel_id: str, name: str) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer()
        try:
            await self.run(self.scope.add, channel_id, name, self.actor(interaction.user))
        except StoreError as error:
            await interaction.followup.send(_clip(f"Not done: {error}", 1900), ephemeral=True)
            return
        except Exception:
            log.exception("[Updates] Turning Gigi on in #%s failed", name)
            await interaction.followup.send(
                "Something went wrong (details are in the bot's log).", ephemeral=True
            )
            return
        embed, view = self._channels_embed(), ChannelsView(self)
        await interaction.edit_original_response(
            content=f"Gigi now answers in #{name} when someone @mentions it.",
            embed=embed,
            view=view,
        )

    async def disable_channel(self, interaction: discord.Interaction, channel_id: str) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer()
        try:
            gone = await self.run(self.scope.remove, channel_id, self.actor(interaction.user))
        except StoreError as error:
            await interaction.followup.send(_clip(f"Not done: {error}", 1900), ephemeral=True)
            return
        except Exception:
            log.exception("[Updates] Turning Gigi off failed")
            await interaction.followup.send(
                "Something went wrong (details are in the bot's log).", ephemeral=True
            )
            return
        await interaction.edit_original_response(
            content=f"Gigi no longer answers in #{gone.get('name', 'that channel')}.",
            embed=self._channels_embed(),
            view=ChannelsView(self),
        )

    async def open_files(self, interaction: discord.Interaction) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        files = await self.run(self.ops.files)
        await interaction.followup.send(embed=files_embed(files), ephemeral=True)

    async def open_archive_all(self, interaction: discord.Interaction) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        live = [i for i in await self.run(self.ops.listing) if i.status == "current"]
        if len(live) < 2:
            await interaction.followup.send(
                f"There {'is' if len(live) == 1 else 'are'} {len(live)} live document(s). Gigi "
                "needs at least one to answer from, so there is nothing to archive. Publish a "
                "new document first, then come back.",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="Archive everything",
            description=(
                "Gigi must always keep at least one live document. **Choose the document(s) to "
                "keep live**; I'll archive all the other live documents after you confirm. "
                "Archived documents can be restored, and drafts are not touched."
            ),
            colour=discord.Colour.red(),
        )
        await interaction.followup.send(embed=embed, view=KeepView(self, live), ephemeral=True)

    async def choose_keep(self, interaction: discord.Interaction, keep: list[str]) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer()
        live = [i for i in await self.run(self.ops.listing) if i.status == "current"]
        going = [i for i in live if i.name not in keep]
        if not going:
            await interaction.edit_original_response(
                content="Everything live is already in your keep list: nothing to archive.",
                embed=None,
                view=None,
            )
            return
        embed = discord.Embed(
            title=f"Archive {len(going)} document(s)?",
            description=(
                "**Stays live:** " + ", ".join(f"`{n}`" for n in keep) + "\n"
                "**Will be archived:** " + ", ".join(f"`{i.name}`" for i in going) + "\n\n"
                "Gigi will answer only from the documents that stay live. Archived documents "
                "can be restored from **Documents**."
            )[:4000],
            colour=discord.Colour.red(),
        )
        await interaction.edit_original_response(
            content=None, embed=embed, view=ConfirmArchiveAllView(self, keep, len(going))
        )

    async def confirm_archive_all(self, interaction: discord.Interaction, keep: list[str]) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer()
        try:
            archived, failed = await self.run(
                self.ops.archive_all_except, keep, self.actor(interaction.user)
            )
        except StoreError as error:
            await interaction.edit_original_response(
                content=_clip(f"Not done: {error}", 1900), embed=None, view=None
            )
            return
        except Exception:
            log.exception("[Updates] Archive everything failed")
            await interaction.edit_original_response(
                content="Something went wrong (details are in the bot's log).",
                embed=None,
                view=None,
            )
            return
        text = f"Archived {len(archived)} document(s). Gigi answers from: " + ", ".join(
            f"`{n}`" for n in keep
        )
        if failed:
            text += "\nNot archived: " + "; ".join(failed)
        await interaction.edit_original_response(content=_clip(text, 1900), embed=None, view=None)

    async def cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(
            content="Cancelled. Nothing changed.", embed=None, view=None
        )

    async def import_builtin_button(self, interaction: discord.Interaction) -> None:
        if not await self._gate(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            names = await self.run(self.ops.import_builtin, self.actor(interaction.user))
        except StoreError as error:
            await interaction.followup.send(str(error), ephemeral=True)
            return
        await interaction.followup.send(
            f"Imported {len(names)} built-in document(s). They are live, with the same Qwen "
            "settings as before."
            if names
            else "Nothing to import: the built-in documents are already here.",
            ephemeral=True,
        )


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
