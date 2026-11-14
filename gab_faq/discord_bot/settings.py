"""Validated settings for message collection and Discord administration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import CONFIG_PATH
from ..runtime_config import RuntimeSettings


@dataclass(frozen=True)
class BotSettings:
    watched_names: frozenset[str]
    faq_channel: str
    categories: tuple[dict, ...]
    query_phrases: tuple[str, ...]
    question_mark_counts: bool = True
    auto_backfill: bool = False
    history_limit: int = 200
    export_limit: int = 50_000
    export_top_n: int = 10
    output_dir: Path = Path("output")
    moderation: dict | None = None
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    faq_required: bool = True
    production: bool = False

    @classmethod
    def load(cls, path: Path = CONFIG_PATH) -> BotSettings:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("config.yaml must contain a mapping")
        for key in ("categories", "channel_names", "faq_channel_name", "history_limit"):
            if key not in data:
                raise ValueError(f"config.yaml is missing {key!r}")
        names = frozenset(str(name).strip().casefold() for name in data["channel_names"] if name)
        faq = str(data["faq_channel_name"] or "").strip().lstrip("#")
        if not names or not faq:
            raise ValueError("channel_names and faq_channel_name must not be empty")
        categories = data["categories"]
        if (
            not isinstance(categories, list)
            or not categories
            or any(not isinstance(item, dict) or not item.get("name") for item in categories)
        ):
            raise ValueError("categories must be a nonempty list of named categories")
        detection = data.get("query_detection") or {}
        environment = (
            str(
                os.environ.get(
                    "GAB_ENVIRONMENT", (data.get("gab_faq") or {}).get("environment", "staging")
                )
            )
            .strip()
            .casefold()
        )
        if environment not in {"staging", "production"}:
            raise ValueError("Environment must be staging or production")
        settings = cls(
            runtime=RuntimeSettings.parse(data.get("runtime")),
            faq_required=bool((data.get("gab_faq") or {}).get("enabled", False)),
            production=environment == "production",
            watched_names=names,
            faq_channel=faq,
            categories=tuple(categories),
            query_phrases=tuple(
                str(p).strip().casefold() for p in detection.get("phrases", []) if p
            ),
            question_mark_counts=bool(detection.get("question_mark_counts", True)),
            auto_backfill=bool(data.get("auto_backfill_on_startup", False)),
            history_limit=int(data.get("history_limit", 200)),
            export_limit=int(data.get("export_max_messages", 50_000)),
            export_top_n=int(data.get("export_top_n", 10)),
            output_dir=Path(data.get("output_dir") or "output"),
            moderation=data.get("moderation") or {},
        )
        if (
            settings.history_limit < 0
            or settings.export_limit < 1
            or not 1 <= settings.export_top_n <= 25
        ):
            raise ValueError(
                "history_limit must be >= 0, export_max_messages > 0, and export_top_n 1..25"
            )
        return settings
