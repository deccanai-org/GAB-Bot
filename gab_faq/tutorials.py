"""Approved playground video references attached to FAQ answers by entry ID."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from .redact import contains_secret


@dataclass(frozen=True)
class TutorialVideo:
    id: str
    title: str
    url: str
    faq_ids: tuple[str, ...]


def load_tutorials(path: Path) -> tuple[TutorialVideo, ...]:
    """An optional local catalog; never infer a public URL from an archive filename."""
    if not path.exists():
        return ()
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("videos"), list):
        raise ValueError(f"{path.name}: expected a videos list")
    videos = []
    ids = set()
    for item in data["videos"]:
        if not isinstance(item, dict):
            raise ValueError(f"{path.name}: each video must be a mapping")
        ident = item.get("id")
        title = item.get("title")
        faq_ids = item.get("faq_ids")
        url = item.get("url") or ""
        if (
            not isinstance(ident, str)
            or not ident.strip()
            or ident in ids
            or not isinstance(title, str)
            or not title.strip()
            or not isinstance(faq_ids, list)
            or not faq_ids
            or any(not isinstance(ref, str) or not ref.strip() for ref in faq_ids)
            or not isinstance(url, str)
        ):
            raise ValueError(f"{path.name}: invalid or duplicate video {ident!r}")
        title, url = title.strip(), url.strip()
        parsed = urlsplit(url)
        if url and (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or any(char.isspace() or char in "<>" for char in url)
        ):
            raise ValueError(f"{path.name}: {ident} needs an HTTPS video or folder link")
        if contains_secret(f"{title}\n{url}"):
            raise ValueError(f"{path.name}: {ident} contains a possible secret")
        ids.add(ident)
        videos.append(TutorialVideo(ident, title, url, tuple(faq_ids)))
    return tuple(videos)


def with_tutorials(body: str, videos: tuple[TutorialVideo, ...]) -> str:
    if not videos:
        return body
    # Prefer supplied related walkthroughs over archive items whose URL is unknown.
    linked = tuple(video for video in videos if video.url)
    videos = linked or videos
    lines = [body.rstrip(), "", "Related playground videos:"]
    for video in videos:
        if video.url:
            lines.append(f"- {video.title}: <{video.url}>")
        else:
            lines.append(f"- {video.title} (ask your QM for the video link).")
    return "\n".join(lines).strip()
