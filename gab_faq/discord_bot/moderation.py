"""Per-bot moderation state and policy; constructed explicitly by the app."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

import discord

from ..redact import redact_secrets

log = logging.getLogger(__name__)


def parse_timestamp(text):
    value = datetime.fromisoformat(text)
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


class ModerationService:
    def __init__(self, config):
        self._mod_cfg = config or {}
        self.enabled: bool = bool(self._mod_cfg.get("enabled", False))
        self.alert_channel: str = (
            (self._mod_cfg.get("alert_channel_name") or "mod-alerts").strip().lower()
        )
        self._thresholds = self._mod_cfg.get("thresholds") or {}
        self.mod_thresh_warn: int = int(self._thresholds.get("warn_alert", 3))
        self.mod_thresh_crit: int = int(self._thresholds.get("critical_alert", 5))
        self._agg_signals = self._mod_cfg.get("aggression_signals") or {}
        self.agg_caps_ratio: float = float(self._agg_signals.get("caps_ratio", 0.7))
        self.agg_caps_score: int = int(self._agg_signals.get("caps_score", 2))
        self.agg_excl_threshold: int = int(self._agg_signals.get("excessive_punctuation", 3))
        self.agg_excl_score: int = int(self._agg_signals.get("excessive_punctuation_score", 1))
        self.agg_repeat_threshold: int = int(self._agg_signals.get("repeated_chars", 5))
        self.agg_repeat_score: int = int(self._agg_signals.get("repeated_chars_score", 1))
        self._re_excessive_punct = re.compile("[!?]{" + str(self.agg_excl_threshold) + ",}")
        self._re_repeated_chars = re.compile(
            "(.)\\1{" + str(self.agg_repeat_threshold - 1) + ",}", re.IGNORECASE
        )
        self.mod_tiers: List[Tuple[str, re.Pattern, int]] = []
        for _tier_key in ("mild_aggression", "profanity", "threats_and_violence", "hinglish"):
            _pat, _score = self._build_tier_regex(_tier_key)
            if _pat:
                self.mod_tiers.append((_tier_key, _pat, _score))
        self.mod_obfuscation: List[Tuple[re.Pattern, int]] = self._build_obfuscation_regexes()
        self._violation_history: Dict[str, list] = defaultdict(list)
        self.violation_window_hours: int = 24
        self.max_violation_history: int = 50
        _autodel_cfg = self._mod_cfg.get("auto_delete") or {}
        self.autodel_enabled: bool = bool(_autodel_cfg.get("enabled", False))
        self.autodel_min_score: int = int(_autodel_cfg.get("min_score", 5))
        self.autodel_min_reasons: int = int(_autodel_cfg.get("min_reasons", 2))
        self.autodel_min_words: int = int(_autodel_cfg.get("min_word_count", 3))
        self.autodel_require_keyword: bool = bool(_autodel_cfg.get("require_keyword_tier", True))
        self.autodel_solo_tiers: set = set(_autodel_cfg.get("solo_delete_tiers") or [])
        self.autodel_exempt_channels: set = {
            str(c).strip().lower()
            for c in _autodel_cfg.get("exempt_channels") or []
            if str(c).strip()
        }
        self._audit_cfg = self._mod_cfg.get("audit") or {}
        self.audit_enabled: bool = bool(self._audit_cfg.get("enabled", False))
        self.audit_interval: int = int(self._audit_cfg.get("interval_minutes", 30))
        self.audit_lookback: int = int(self._audit_cfg.get("lookback_minutes", 35))
        self.audit_limit: int = int(self._audit_cfg.get("max_messages_per_channel", 500))
        self._audited_msg_ids: dict[str, None] = {}
        self.audited_ids_max: int = 10000
        self.keyword_tier_names: set = {
            "mild_aggression",
            "profanity",
            "threats_and_violence",
            "hinglish",
        }

    def _build_tier_regex(self, tier_key: str) -> Tuple[re.Pattern, int]:
        """Build a compiled word-boundary regex from a moderation tier in config."""
        tier = self._mod_cfg.get(tier_key) or {}
        score = int(tier.get("score", 1))
        words = [str(w).strip() for w in tier.get("words") or [] if str(w).strip()]
        if not words:
            return (None, score)
        escaped = [re.escape(w).replace("\\ ", "\\s+") for w in words]
        pattern = re.compile("\\b(" + "|".join(escaped) + ")\\b", re.IGNORECASE)
        return (pattern, score)

    def _build_obfuscation_regexes(self) -> List[Tuple[re.Pattern, int]]:
        """Build compiled regexes from the obfuscation_patterns tier."""
        tier = self._mod_cfg.get("obfuscation_patterns") or {}
        score = int(tier.get("score", 3))
        out: List[Tuple[re.Pattern, int]] = []
        for raw in tier.get("regexes") or []:
            try:
                out.append((re.compile(raw, re.IGNORECASE), score))
            except re.error:
                log.warning("Invalid obfuscation regex, skipped: %s", raw)
        return out

    def check(self, content: str) -> Tuple[int, List[str]]:
        """
        Score a message for foul / aggressive content.
        Returns (total_score, [list of human-readable reasons]).
        """
        if not content or not content.strip():
            return (0, [])
        total = 0
        reasons: List[str] = []
        text = content.strip()
        for tier_name, pattern, score in self.mod_tiers:
            matches = pattern.findall(text)
            if matches:
                unique = sorted(
                    set((m.lower() if isinstance(m, str) else m[0].lower() for m in matches))
                )
                total += score
                label = tier_name.replace("_", " ").title()
                reasons.append(f"{label}: {', '.join(unique)}")
        for obf_pat, score in self.mod_obfuscation:
            if obf_pat.search(text):
                total += score
                reasons.append("Obfuscated profanity detected")
                break
        alpha = re.sub("[^a-zA-Z]", "", text)
        if len(alpha) >= 8:
            upper_ratio = sum((1 for c in alpha if c.isupper())) / len(alpha)
            if upper_ratio >= self.agg_caps_ratio:
                total += self.agg_caps_score
                reasons.append(f"ALL CAPS ({upper_ratio:.0%} uppercase)")
        if self._re_excessive_punct.search(text):
            total += self.agg_excl_score
            reasons.append("Excessive punctuation (!!!/???)")
        if self._re_repeated_chars.search(text):
            total += self.agg_repeat_score
            reasons.append("Repeated character spam")
        return (total, reasons)

    def _user_recent_violations(self, user_id: str) -> int:
        """Count violations in the last VIOLATION_WINDOW_HOURS for this user."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.violation_window_hours)
        count = 0
        for ts, _score in self._violation_history.get(user_id, []):
            try:
                if parse_timestamp(ts) >= cutoff:
                    count += 1
            except (ValueError, TypeError):
                count += 1
        return count

    def _record_violation(self, user_id: str, score: int):
        """Track violation in memory for repeat-offender counting."""
        ts = datetime.now(timezone.utc).isoformat()
        hist = self._violation_history[user_id]
        hist.append((ts, score))
        if len(hist) > self.max_violation_history:
            self._violation_history[user_id] = hist[-self.max_violation_history :]

    def _build_mod_alert_embed(
        self, msg: discord.Message, score: int, reasons: List[str], repeat_count: int
    ) -> discord.Embed:
        severity = "CRITICAL" if score >= self.mod_thresh_crit else "WARNING"
        color = discord.Color.red() if score >= self.mod_thresh_crit else discord.Color.orange()
        snippet = redact_secrets(msg.content or "")[:500]
        if len(msg.content or "") > 500:
            snippet += "..."
        embed = discord.Embed(
            title=f"Content Flag — {severity}", color=color, timestamp=msg.created_at
        )
        embed.add_field(name="User", value=f"{msg.author.mention} (`{msg.author}`)", inline=True)
        embed.add_field(name="Channel", value=f"<#{msg.channel.id}>", inline=True)
        embed.add_field(name="Score", value=str(score), inline=True)
        embed.add_field(name="Reasons", value="\n".join((f"- {r}" for r in reasons)), inline=False)
        embed.add_field(name="Message", value=f"```\n{snippet}\n```", inline=False)
        if repeat_count > 1:
            embed.add_field(
                name="Repeat Offender",
                value=f"{repeat_count} violations in last {self.violation_window_hours}h",
                inline=False,
            )
        embed.add_field(
            name="Jump to Message",
            value=f"[Click here](https://discord.com/channels/{msg.guild.id}/{msg.channel.id}/{msg.id})",
            inline=False,
        )
        embed.set_footer(text=f"User ID: {msg.author.id}")
        return embed

    def find_alert_channel(self, guild: discord.Guild):
        for ch in guild.text_channels:
            if ch.name.lower() == self.alert_channel:
                return ch
        return None

    def _extract_matched_tiers(self, reasons: List[str]) -> set:
        """Extract which keyword tier names fired from the human-readable reasons list."""
        fired: set = set()
        for r in reasons:
            r_lower = r.lower()
            if "mild aggression" in r_lower:
                fired.add("mild_aggression")
            elif "profanity" in r_lower and "obfuscat" not in r_lower:
                fired.add("profanity")
            elif "threats and violence" in r_lower:
                fired.add("threats_and_violence")
            elif "hinglish" in r_lower:
                fired.add("hinglish")
            elif "obfuscat" in r_lower:
                fired.add("obfuscation")
        return fired

    def should_delete(
        self, content: str, score: int, reasons: List[str], channel_name: str = ""
    ) -> Tuple[bool, str]:
        """
        Apply guardrails to decide if a message should be auto-deleted.
        Returns (should_delete, explanation_if_not).
        """
        if not self.autodel_enabled:
            return (False, "auto-delete disabled")
        if channel_name.lower() in self.autodel_exempt_channels:
            return (False, f"#{channel_name} is exempt from auto-delete")
        word_count = len(content.split())
        if word_count < self.autodel_min_words:
            return (False, f"message too short ({word_count} words < {self.autodel_min_words})")
        fired_tiers = self._extract_matched_tiers(reasons)
        if self.autodel_solo_tiers & fired_tiers:
            return (True, "solo-delete tier matched")
        if score < self.autodel_min_score:
            return (False, f"score {score} below deletion threshold {self.autodel_min_score}")
        if self.autodel_require_keyword and (not fired_tiers & self.keyword_tier_names):
            return (False, "no keyword tier fired (behavioural signals only)")
        if len(reasons) < self.autodel_min_reasons:
            return (False, f"only {len(reasons)} reason(s), need {self.autodel_min_reasons}")
        return (True, "all guardrails passed")

    def _build_deletion_notice_embed(
        self,
        author: discord.Member,
        channel: discord.abc.GuildChannel,
        content: str,
        score: int,
        reasons: List[str],
    ) -> discord.Embed:
        """Embed posted to #mod-alerts explaining why a message was auto-deleted."""
        snippet = redact_secrets(content)[:500]
        if len(content) > 500:
            snippet += "..."
        embed = discord.Embed(
            title="Message Auto-Deleted",
            color=discord.Color.dark_red(),
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="User", value=f"{author.mention} (`{author}`)", inline=True)
        embed.add_field(name="Channel", value=f"<#{channel.id}>", inline=True)
        embed.add_field(name="Score", value=str(score), inline=True)
        embed.add_field(name="Reasons", value="\n".join((f"- {r}" for r in reasons)), inline=False)
        embed.add_field(name="Deleted Message", value=f"```\n{snippet}\n```", inline=False)
        embed.set_footer(text=f"User ID: {author.id} | Auto-delete guardrails passed")
        return embed

    async def moderate(self, msg: discord.Message, alert_ch) -> bool:
        """
        Run moderation on a single message. Only acts on score >= warn threshold (3+).
        Score 1-2: completely ignored (no log, no alert, no record).
        If guardrails pass, deletes the message and posts explanation to #mod-alerts.
        Returns True if the message was deleted.
        """
        if not msg.content or msg.author.bot:
            return False
        score, reasons = self.check(msg.content)
        if score < self.mod_thresh_warn:
            return False
        key = str(msg.id)
        if key in self._audited_msg_ids:
            return False
        self._audited_msg_ids[key] = None
        if len(self._audited_msg_ids) > self.audited_ids_max:
            self._audited_msg_ids.pop(next(iter(self._audited_msg_ids)))
        ch_name = getattr(msg.channel, "name", str(msg.channel.id))
        user_id = str(msg.author.id)
        self._record_violation(user_id, score)
        repeat_count = self._user_recent_violations(user_id)
        do_delete, guardrail_reason = self.should_delete(msg.content, score, reasons, ch_name)
        if do_delete:
            try:
                notice_embed = self._build_deletion_notice_embed(
                    msg.author, msg.channel, msg.content, score, reasons
                )
                await msg.delete()
            except discord.NotFound:
                return True  # already removed; do not try to answer a deleted message
            except discord.HTTPException:
                log.exception("[MOD] Could not delete message %s", msg.id)
                return False
            if alert_ch:
                try:
                    await alert_ch.send(
                        embed=notice_embed, allowed_mentions=discord.AllowedMentions.none()
                    )
                except discord.HTTPException:
                    log.exception("[MOD] Message %s deleted, but its staff notice failed", msg.id)
            return True
        elif alert_ch:
            embed = self._build_mod_alert_embed(msg, score, reasons, repeat_count)
            if not do_delete and guardrail_reason:
                embed.add_field(
                    name="Guardrail", value=f"Auto-delete skipped: {guardrail_reason}", inline=False
                )
            ping = "@here " if score >= self.mod_thresh_crit else ""
            try:
                await alert_ch.send(
                    content=ping,
                    embed=embed,
                    allowed_mentions=discord.AllowedMentions(
                        everyone=bool(ping), users=False, roles=False
                    ),
                )
            except discord.Forbidden:
                log.error("Cannot send to #%s — check bot permissions.", self.alert_channel)
        return False

    async def audit(self, bot):
        """Scan recent messages across all channels for policy violations."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=self.audit_lookback)
        total_scanned = 0
        total_flagged = 0
        total_deleted = 0
        for guild in bot.guilds:
            alert_ch = self.find_alert_channel(guild)
            for ch in guild.text_channels:
                if ch.name.lower() == self.alert_channel:
                    continue
                try:
                    async for msg in ch.history(limit=self.audit_limit, after=cutoff):
                        if msg.author.bot or not msg.content:
                            continue
                        if str(msg.id) in self._audited_msg_ids:
                            continue
                        total_scanned += 1
                        score, reasons = self.check(msg.content)
                        if score >= self.mod_thresh_warn:
                            total_flagged += 1
                            deleted = await self.moderate(msg, alert_ch)
                            if deleted:
                                total_deleted += 1
                except discord.Forbidden:
                    continue
                except discord.HTTPException as exc:
                    log.warning("Audit: HTTP error scanning #%s: %s", ch.name, exc)
        if total_flagged > 0:
            log.info(
                "[AUDIT] Scanned %d messages, flagged %d, deleted %d",
                total_scanned,
                total_flagged,
                total_deleted,
            )
        else:
            log.info("[AUDIT] Scanned %d messages — all clean", total_scanned)
