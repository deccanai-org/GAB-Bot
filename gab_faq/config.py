"""Settings for the FAQ answering part of the bot.

Two places, the same as the rest of the bot:
  - Normal settings: the `gab_faq:` section of config.yaml (which channels to answer in, the model...).
  - Secrets: environment variables. Locally they come from .env; in Kubernetes each secret is a file
    in /app/secrets/ named after the variable. Secrets used here:
      DISCORD_TOKEN       the same bot token the rest of bot.py uses
      SLACK_BOT_TOKEN, SLACK_APP_TOKEN   only for the Slack bot
      DASHSCOPE_API_KEY   Qwen3-Omni-Flash in Alibaba Cloud Model Studio (Singapore)

Secrets are never written in code or in config.yaml.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .model_limits import ModelLimits
from .routing import SupportSettings, check_route, parse_contacts
from .runtime_config import RuntimeSettings
from .search import SearchSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.yaml"
SECRETS_DIR = Path("/app/secrets")


def load_secret_files(directory: Path) -> list[str]:
    """Copy each file in `directory` into an environment variable of the same name, unless that
    variable is already set. Returns the names loaded (never the values). Hidden entries are
    skipped; Kubernetes keeps its own bookkeeping in hidden '..data' folders there."""
    directory = Path(directory)
    if not directory.is_dir():
        return []
    loaded = []
    for f in sorted(directory.iterdir()):
        if f.name.startswith(".") or not f.is_file() or f.name in os.environ:
            continue
        os.environ[f.name] = f.read_text(encoding="utf-8").strip()
        loaded.append(f.name)
    return loaded


SECRET_NAMES = ("DISCORD_TOKEN", "DASHSCOPE_API_KEY", "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN")


def normalize_secrets() -> list[str]:
    """Remove one pair of angle brackets around a secret ("<sk-...>"), a common paste mistake
    from "KEY=<your key>" templates that makes every provider call fail with 401. Returns the
    names fixed (never the values); a warning asks for the stored value to be corrected."""
    fixed = []
    for name in SECRET_NAMES:
        value = os.environ.get(name, "").strip()
        inner = value[1:-1].strip()
        if len(value) > 2 and value[0] == "<" and value[-1] == ">" and not set("<>") & set(inner):
            os.environ[name] = inner
            fixed.append(name)
            logging.getLogger(__name__).warning(
                "%s was wrapped in <...>; the brackets were removed. Store it without them.", name
            )
    return fixed


def load_environment() -> None:
    """Read .env (on a laptop) and /app/secrets/ (in Kubernetes). bot.py does this too; running it
    twice is harmless because neither overwrites a variable that is already set."""
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    load_secret_files(Path(os.environ.get("SECRETS_DIR", SECRETS_DIR)))
    normalize_secrets()


def _names(values) -> frozenset[str]:
    """Channel names or IDs from config.yaml, compared without case and without a leading #."""
    return frozenset(_channel_key(v) for v in (values or []) if str(v).strip())


def _channel_key(value) -> str:
    return str(value).strip().lstrip("#").lower()


def channel_pattern_matches(pattern: str, key: str) -> bool:
    """`*` matches any run of characters (none included); every other character is literal, so
    names with [ ] ? in them still match exactly. Both sides are already lower-cased keys."""
    if "*" not in pattern:
        return pattern == key
    regex = ".*".join(re.escape(part) for part in pattern.split("*"))
    return re.fullmatch(regex, key, flags=re.DOTALL) is not None


def _matches(patterns: frozenset[str], channels) -> bool:
    keys = [_channel_key(c) for c in channels if c]
    return any(channel_pattern_matches(p, k) for p in patterns for k in keys)


@dataclass(frozen=True)
class PlatformSettings:
    """Where the bot answers, and how it treats each channel, on one platform.

    Every list below can hold any number of entries, in any mix (compared without case or a
    leading #):
      - a channel name:                  project-related-queries
      - a category (section) name:       Project GAB P6 QC Deployed   (= every channel in it)
      - a category/channel pair:         Project GAB P6 QC Deployed/support   (one exact channel)
      - a channel or category ID:        1570402201296175157
      - a pattern with * wildcards:      Project GAB*/project-related-queries  (every match,
                                         including channels and sections created later)
    "*" alone means every channel. Slack has no categories: use channel IDs there."""

    # Limit the bot to these channels/categories: outside them it ignores everything, @mentions
    # included. Empty = anywhere. Useful on a server shared with other projects.
    only_in: frozenset[str] = frozenset()
    # Channels where the bot answers EVERY new message (e.g. #ask-the-bot). Everywhere else it only
    # answers when @mentioned (or in a direct message, if answer_in_dms is on).
    answer_channels: frozenset[str] = frozenset()
    answer_in_dms: bool = False  # least privilege: off unless config.yaml turns it on
    # Channels whose members are annotators / QC reviewers, so the bot uses the right FAQ.
    annotator_channels: frozenset[str] = frozenset()
    qc_channels: frozenset[str] = frozenset()
    # Channels for Queue Managers only. Only here does the bot use the internal QM documents.
    qm_channels: frozenset[str] = frozenset()
    # Who gets tagged in the reply when the bot can't answer (optional).
    # Discord: "<@123>" for a person or "<@&456>" for a role. Slack: "<@U123>" or "<!subteam^S123>".
    escalation_mention: str = ""
    # Discord only: channel where the bot posts every question it couldn't answer, so the team can
    # reply and add it to the FAQ. Empty = don't post.
    unanswered_channel: str = ""

    def role_for_channel(self, *channels: str | None) -> str:
        """The asker's role, from the channel (name or ID). Pass the thread's parent channel too:
        a thread inherits its parent's role."""
        for channel in channels:
            if not channel:
                continue
            if _matches(self.qm_channels, [channel]):
                return "qm"
            if _matches(self.qc_channels, [channel]):
                return "qc"
            if _matches(self.annotator_channels, [channel]):
                return "annotator"
        return "unknown"

    def is_answer_channel(self, *channels: str | None) -> bool:
        return _matches(self.answer_channels, channels)

    def in_scope(self, *channels: str | None) -> bool:
        if not self.only_in:
            return True
        return _matches(self.only_in, channels)

    def unmatched_answer_channels(self, keys) -> list[str]:
        """answer_channels entries that match none of these channel keys (a startup check)."""
        return sorted(p for p in self.answer_channels if not _matches(frozenset([p]), keys))


def _platform(section: dict | None) -> PlatformSettings:
    section = section or {}
    return PlatformSettings(
        only_in=_names(section.get("only_in")),
        answer_channels=_names(section.get("answer_channels")),
        answer_in_dms=bool(section.get("answer_in_dms", False)),
        annotator_channels=_names(section.get("annotator_channels")),
        qc_channels=_names(section.get("qc_channels")),
        qm_channels=_names(section.get("qm_channels")),
        escalation_mention=str(section.get("escalation_mention") or "").strip(),
        unanswered_channel=str(section.get("unanswered_channel") or "").strip().lstrip("#"),
    )


ENGINES = ("search", "qwen")
QWEN_MODEL = "qwen3-omni-flash"


@dataclass(frozen=True)
class FollowupSettings:
    """What happens to questions the bot couldn't answer (see followup.py)."""

    after_minutes: int = 60  # nobody replied this long -> reminder in Discord
    check_every_minutes: int = 5
    batch_size: int = 50
    history_batch_size: int = 1000
    reply_batch_size: int = 200
    # Where the reminder goes (channel name or ID). Empty = the unanswered-questions channel.
    reminder_channel: str = ""
    # Who the reminder tags: "<@&ROLE_ID>" for a role, "<@USER_ID>" for a person, several allowed.
    reminder_mention: str = ""

    def __post_init__(self):
        if (
            min(
                self.after_minutes,
                self.check_every_minutes,
                self.batch_size,
                self.history_batch_size,
                self.reply_batch_size,
            )
            <= 0
        ):
            raise ValueError("Follow-up intervals and batch sizes must be positive")


def _followup(section: dict | None) -> FollowupSettings:
    section = section or {}
    return FollowupSettings(
        after_minutes=int(section.get("after_minutes", 60)),
        batch_size=int(section.get("batch_size", 50)),
        history_batch_size=int(section.get("history_batch_size", 1000)),
        reply_batch_size=int(section.get("reply_batch_size", 200)),
        check_every_minutes=max(1, int(section.get("check_every_minutes", 5))),
        reminder_channel=str(section.get("reminder_channel") or "").strip().lstrip("#"),
        reminder_mention=str(section.get("reminder_mention") or "").strip(),
    )


def _search(section: dict | None) -> SearchSettings:
    section = section or {}
    defaults = SearchSettings()
    cache_dir = Path(section.get("model_dir") or defaults.cache_dir)
    if not cache_dir.is_absolute():
        cache_dir = PROJECT_ROOT / cache_dir
    return SearchSettings(
        model=str(section.get("model") or defaults.model),
        cache_dir=cache_dir,
        keyword_weight=float(section.get("keyword_weight", defaults.keyword_weight)),
        confident_score=float(section.get("confident_score", defaults.confident_score)),
        min_score=float(section.get("min_score", defaults.min_score)),
        related_margin=float(section.get("related_margin", defaults.related_margin)),
        role_penalty=float(section.get("role_penalty", defaults.role_penalty)),
        summary_penalty=float(section.get("summary_penalty", defaults.summary_penalty)),
    )


def _support(section: dict | None) -> SupportSettings:
    section = section or {}
    d = SupportSettings()
    return SupportSettings(
        enabled=bool(section.get("enabled", d.enabled)),
        contacts=parse_contacts(section.get("contacts")),
        throttle_route=check_route(
            "throttle_requests_go_to", section.get("throttle_requests_go_to", d.throttle_route)
        ),
        task_issue_route=check_route(
            "task_issues_go_to", section.get("task_issues_go_to", d.task_issue_route)
        ),
        default_route=check_route(
            "other_questions_go_to", section.get("other_questions_go_to", d.default_route)
        ),
        requests_channel=str(section.get("requests_channel") or "").strip().lstrip("#"),
        mention_in_reply=bool(section.get("mention_contacts_in_replies", d.mention_in_reply)),
        request_cooldown_seconds=max(
            0, int(section.get("request_cooldown_seconds", d.request_cooldown_seconds))
        ),
        max_attachment_mb=max(
            1, min(25, int(section.get("max_attachment_mb", d.max_attachment_mb)))
        ),
    )


@dataclass(frozen=True)
class Settings:
    runtime: RuntimeSettings = field(default_factory=RuntimeSettings)
    enabled: bool = False
    # Qwen is the bot's LLM; local search requires an explicit engine selection.
    engine: str = "qwen"
    model: str = QWEN_MODEL
    search: SearchSettings = field(default_factory=SearchSettings)
    # With engine qwen: when Qwen says "not in the FAQ" or fails, post a CONFIDENT local search
    # match instead of escalating. Needs the embedding model (bundled in the image).
    local_backstop: bool = True
    external_questions_approved: bool = False
    external_history_approved: bool = False
    enable_thinking: bool = False
    provider_usage_path: Path = PROJECT_ROOT / "output" / "provider_usage.sqlite3"
    followup: FollowupSettings = field(default_factory=FollowupSettings)
    # Contacts, /throttle-request and /task-issue (routing.py, support.py).
    support: SupportSettings = field(default_factory=SupportSettings)
    environment: str = "staging"  # staging (replies start with [TEST BOT]) | production
    max_history_messages: int = 4
    model_limits: ModelLimits = field(default_factory=ModelLimits)
    knowledge_dir: Path = PROJECT_ROOT / "knowledge" / "current"
    # Optional knowledge database edited through the admin UI (gab_faq.admin). When set, the bot
    # serves the published documents from it; knowledge_dir stays the built-in fallback and
    # knowledge_live_dir is where the published files are written for the bot to read.
    knowledge_store: Path | None = None
    knowledge_live_dir: Path = Path("output") / "knowledge-live"
    # Where questions are logged. Same folder the rest of the bot saves its files in.
    log_dir: Path = Path("output")
    discord: PlatformSettings = field(default_factory=PlatformSettings)
    slack: PlatformSettings = field(default_factory=PlatformSettings)
    discord_token: str = field(default="", repr=False)
    slack_bot_token: str = field(default="", repr=False)
    slack_app_token: str = field(default="", repr=False)
    dashscope_api_key_set: bool = field(default=False, repr=False)

    def __post_init__(self):
        if self.engine not in ENGINES:
            raise ValueError(f"engine must be one of {ENGINES}")
        if self.engine == "qwen" and self.model != QWEN_MODEL:
            raise ValueError(f"gab_faq.model must be {QWEN_MODEL!r} for the qwen engine")
        if type(self.enable_thinking) is not bool:
            raise ValueError("gab_faq.enable_thinking must be true or false")
        if not 0 <= self.max_history_messages <= 50:
            raise ValueError("max_history_messages must be between 0 and 50")


def load_settings(config_path: Path = CONFIG_PATH) -> Settings:
    """Read the gab_faq section of config.yaml plus the secrets from the environment.
    Call load_environment() first if .env / /app/secrets haven't been read yet."""
    cfg = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    faq = cfg.get("gab_faq") or {}
    environment = (
        str(os.environ.get("GAB_ENVIRONMENT", faq.get("environment", "staging"))).strip().lower()
    )
    if environment not in ("staging", "production"):
        raise ValueError(
            f"gab_faq.environment in config.yaml must be staging or production, got {environment!r}"
        )
    knowledge_dir = Path(faq.get("knowledge_dir") or "knowledge/current")
    if not knowledge_dir.is_absolute():
        knowledge_dir = PROJECT_ROOT / knowledge_dir
    engine = str(faq.get("engine", "qwen")).strip().lower()
    if engine not in ENGINES:
        raise ValueError(f"gab_faq.engine in config.yaml must be one of {ENGINES}, got {engine!r}")
    store = faq.get("knowledge_store")
    store_path = os.environ.get("GAB_KNOWLEDGE_DB") or (
        store.get("path") if isinstance(store, dict) else store
    )
    log_dir = Path(faq.get("log_dir") or cfg.get("output_dir") or "output")
    return Settings(
        runtime=RuntimeSettings.parse(cfg.get("runtime")),
        enabled=bool(faq.get("enabled", False)),
        engine=engine,
        model=str(faq.get("model", QWEN_MODEL)).strip().lower(),
        search=_search(faq.get("search")),
        local_backstop=bool(faq.get("local_backstop", True)),
        external_questions_approved=faq.get("external_questions_approved") is True,
        external_history_approved=faq.get("external_history_approved") is True,
        enable_thinking=faq.get("enable_thinking", False),
        provider_usage_path=Path(
            os.environ.get("GAB_PROVIDER_USAGE_PATH")
            or faq.get("provider_usage_path")
            or PROJECT_ROOT / "output" / "provider_usage.sqlite3"
        ),
        followup=_followup(faq.get("followup")),
        support=_support(faq.get("support")),
        environment=environment,
        max_history_messages=int(faq.get("max_history_messages", 4)),
        model_limits=ModelLimits.parse(faq.get("model_limits")),
        knowledge_dir=knowledge_dir,
        knowledge_store=Path(str(store_path)) if store_path else None,
        knowledge_live_dir=Path(
            os.environ.get("GAB_KNOWLEDGE_LIVE_DIR")
            or faq.get("knowledge_live_dir")
            or log_dir / "knowledge-live"
        ),
        log_dir=log_dir,
        discord=_platform(faq.get("discord")),
        slack=_platform(faq.get("slack")),
        discord_token=os.environ.get("DISCORD_TOKEN", ""),
        slack_bot_token=os.environ.get("SLACK_BOT_TOKEN", ""),
        slack_app_token=os.environ.get("SLACK_APP_TOKEN", ""),
        dashscope_api_key_set=bool(os.environ.get("DASHSCOPE_API_KEY", "").strip()),
    )
