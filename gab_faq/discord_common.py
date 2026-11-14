"""Discord boundaries shared by the app, FAQ answering, and support commands."""

from __future__ import annotations

import re

import discord

from .routing import MENTION_TOKEN_RE


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


def strip_mentions(text: str, bot_id: int) -> str:
    return re.sub(rf"<@!?{bot_id}>", "", text or "").strip()


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
