"""Discord boundaries shared by the app, FAQ answering, and support commands."""

from __future__ import annotations

import logging
import re

import discord

from .routing import MENTION_TOKEN_RE

log = logging.getLogger(__name__)


def readable_channels(member, channels) -> list:
    if member is None:
        return []
    readable = []
    for channel in channels:
        try:
            permissions = channel.permissions_for(member)
        except (AttributeError, TypeError):
            continue
        if permissions.view_channel and permissions.read_message_history:
            readable.append(channel)
    return readable


def allowed_mentions(*texts: str) -> discord.AllowedMentions:
    users, roles = [], []
    for text in texts:
        for kind, ident in MENTION_TOKEN_RE.findall(text or ""):
            (roles if kind == "&" else users).append(discord.Object(id=int(ident)))
    return discord.AllowedMentions(
        everyone=False, users=users or False, roles=roles or False, replied_user=False
    )


async def notify_contact(client, channel, contact, *, embed, card=None, intro: str) -> None:
    """Tell the routed contact about a new staff card by direct message, not by a ping in the channel.

    Each user in `contact.mention` gets a DM with the card's embed and a link to the card (the
    buttons live on the card). Only people who can't be reached that way are pinged in the staff
    channel instead, so a closed DM never means a missed question: users whose DMs are closed or who
    can't be found, and roles (a role can't be sent a DM). Nobody else is ever pinged, and nothing
    here raises: a failed notification must not undo a card that was already delivered."""
    if contact is None or not contact.mention:
        return
    users, roles = contact.mention_ids()
    pending = [f"<@&{role_id}>" for role_id in roles]
    link = getattr(card, "jump_url", "") or ""
    text = intro + (f"\nStaff card: {link}" if link else "")
    for user_id in users:
        try:
            user = client.get_user(user_id) or await client.fetch_user(user_id)
            await user.send(
                content=text, embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
        except discord.HTTPException as e:  # DMs closed (Forbidden), unknown user (NotFound), ...
            log.warning(
                "[FAQ] Couldn't DM contact %s (%s); pinging them in the staff channel instead",
                user_id,
                type(e).__name__,
            )
            pending.append(f"<@{user_id}>")
        except Exception:
            log.exception(
                "[FAQ] Unexpected error DMing contact %s; pinging in the channel", user_id
            )
            pending.append(f"<@{user_id}>")
    if not pending:
        return
    ping = " ".join(pending)
    extra = {"reference": card} if card is not None else {}
    try:
        await channel.send(content=ping, allowed_mentions=allowed_mentions(ping), **extra)
    except Exception:
        log.exception("[FAQ] Couldn't ping the contact in the staff channel either")


def strip_mentions(text: str, bot_id: int, role_id: int | None = None, names=()) -> str:
    """The message without the ways of calling the bot: <@bot>, <@&bot's role>, "@name" typed."""
    text = re.sub(rf"<@!?{bot_id}>", "", text or "")
    if role_id is not None:
        text = re.sub(rf"<@&{role_id}>", "", text)
    for name in names:
        text = _typed_call(name).sub("", text)
    return text.strip()


def _typed_call(name: str) -> re.Pattern:
    # "@gigi" typed as text, any case; not part of an e-mail address or a longer name. A comma or
    # colon right after it ("@gigi, ...") goes with it.
    return re.compile(rf"(?<![\w@])@{re.escape(name)}(?![\w-])[,:]?", re.IGNORECASE)


def bot_names(bot_user, guild=None) -> list[str]:
    """Names people type after @ to call the bot: its username, display name and server nick."""
    names = {getattr(bot_user, "name", None), getattr(bot_user, "global_name", None)}
    names.add(getattr(getattr(guild, "me", None), "nick", None))
    return sorted(name for name in names if name)


def bot_role_id(guild) -> int | None:
    """The role Discord creates for the bot in a server; "@gigi" autocomplete offers it too."""
    return getattr(getattr(guild, "self_role", None), "id", None)


def calls_bot(message, bot_user) -> bool:
    """True when the message calls the bot with @: a real mention, a mention of the bot's own
    server role, or "@name" typed as plain text (sent without picking the autocomplete entry)."""
    if bot_user in message.mentions:
        return True
    role_id = bot_role_id(message.guild)
    if role_id is not None and any(
        getattr(role, "id", None) == role_id for role in getattr(message, "role_mentions", ())
    ):
        return True
    content = message.content or ""
    return any(_typed_call(name).search(content) for name in bot_names(bot_user, message.guild))


def strip_bot_call(text: str, bot_user, guild=None) -> str:
    return strip_mentions(text, bot_user.id, bot_role_id(guild), bot_names(bot_user, guild))


def _keys(channel, channel_id=None) -> list[str]:
    name = getattr(channel, "name", None) or ""
    keys = [name, str(channel_id or getattr(channel, "id", "") or "")]
    category = getattr(channel, "category", None)
    if category is not None:
        keys += [category.name, str(category.id), f"{category.name}/{name}"]
    return [key for key in keys if key]


def channel_keys(channel) -> tuple[list[str], list[str]]:
    if isinstance(channel, discord.Thread):
        parent = channel.parent
        parent_keys = _keys(parent, channel.parent_id) if parent else [str(channel.parent_id or "")]
        return _keys(channel), [key for key in parent_keys if key]
    return _keys(channel), []


def find_text_channel(guild, wanted: str):
    """Resolve destinations inside the source guild; IDs never cross guild boundaries."""
    if guild is None or not wanted:
        return None
    return discord.utils.find(
        lambda channel: (
            str(channel.id) == wanted
            if wanted.isdigit()
            else channel.name.casefold() == wanted.casefold()
        ),
        guild.text_channels,
    )
