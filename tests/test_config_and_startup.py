"""config.yaml's gab_faq section, secrets from files, and bot.py starting with FAQ answers on/off."""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from gab_faq.config import load_secret_files, load_settings

from .conftest import ROOT


def test_repo_config_yaml_has_a_valid_gab_faq_section():
    s = load_settings(ROOT / "config.yaml")
    assert s.environment in ("staging", "production")
    assert s.model == "claude-opus-5-5"
    assert s.knowledge_dir == ROOT / "knowledge" / "current"
    assert s.knowledge_dir.is_dir()


def test_missing_section_means_off(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("channel_names: [general]\n")
    assert load_settings(p).enabled is False


def test_bad_environment_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("gab_faq:\n  environment: prod\n")
    with pytest.raises(ValueError, match="staging or production"):
        load_settings(p)


def test_secret_files_become_environment_variables(tmp_path, monkeypatch):
    (tmp_path / "FAQ_TEST_TOKEN").write_text("abc123\n")
    (tmp_path / ".hidden").write_text("x")
    (tmp_path / "..data").mkdir()  # Kubernetes bookkeeping folder
    monkeypatch.delenv("FAQ_TEST_TOKEN", raising=False)
    assert load_secret_files(tmp_path) == ["FAQ_TEST_TOKEN"]
    assert os.environ["FAQ_TEST_TOKEN"] == "abc123"
    monkeypatch.delenv("FAQ_TEST_TOKEN")


def test_real_environment_variable_wins_over_secret_file(tmp_path, monkeypatch):
    (tmp_path / "FAQ_TEST_TOKEN").write_text("from-file")
    monkeypatch.setenv("FAQ_TEST_TOKEN", "from-env")
    assert load_secret_files(tmp_path) == []
    assert os.environ["FAQ_TEST_TOKEN"] == "from-env"


def test_settings_repr_never_contains_platform_tokens():
    from gab_faq.config import Settings

    settings = Settings(
        discord_token="SYNTHETIC_SECRET",
        slack_bot_token="SYNTHETIC_SECRET",
        slack_app_token="SYNTHETIC_SECRET",
    )
    assert "SYNTHETIC_SECRET" not in repr(settings)


def test_production_mode_normalization_cannot_disable_guards(monkeypatch):
    from gab_faq.discord_bot.settings import BotSettings

    monkeypatch.setenv("GAB_ENVIRONMENT", " PRODUCTION ")
    assert BotSettings.load(ROOT / "config.yaml").production
    assert load_settings(ROOT / "config.yaml").environment == "production"
    monkeypatch.setenv("GAB_ENVIRONMENT", "prod")
    with pytest.raises(ValueError):
        BotSettings.load(ROOT / "config.yaml")


def test_zero_history_setting_is_preserved(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("gab_faq:\n  max_history_messages: 0\n")
    assert load_settings(path).max_history_messages == 0


def _start_bot(tmp_path, api_key: str) -> subprocess.CompletedProcess:
    """Load bot.py the way `python bot.py` does, but stop before connecting to Discord."""
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "ANTHROPIC_API_KEY": api_key,
        "SECRETS_DIR": str(tmp_path / "no-secrets"),
        "DISCORD_TOKEN": "",
    }
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio, logging; logging.basicConfig(level=logging.INFO); "
            "from bot import create_bot; from gab_faq.discord_answers import setup_faq_answers; "
            "app=create_bot(); app.faq_answers=setup_faq_answers(app); "
            "print('FAQ_ANSWERER=' + type(app.faq_answers).__name__); asyncio.run(app.close())",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_bot_starts_with_free_search_and_no_api_key(tmp_path):
    result = _start_bot(tmp_path, api_key="")
    assert result.returncode == 0, result.stderr
    assert "FAQ_ANSWERER=FaqAnswerer" in result.stdout
    assert "[FAQ] Answering is ON" in result.stderr and "FAQ search" in result.stderr


def _settings_with(engine, monkeypatch, api_key):
    from dataclasses import replace

    from gab_faq import discord_answers

    monkeypatch.setenv("ANTHROPIC_API_KEY", api_key)
    real = load_settings(ROOT / "config.yaml")
    monkeypatch.setattr(
        discord_answers,
        "load_settings",
        lambda: replace(real, engine=engine, anthropic_api_key_set=bool(api_key)),
    )
    monkeypatch.setattr(discord_answers, "load_environment", lambda: None)
    return discord_answers


def test_claude_engine_without_key_switches_answering_off(monkeypatch):
    discord_answers = _settings_with("claude", monkeypatch, api_key="")
    assert discord_answers.setup_faq_answers(SimpleNamespace(user=None)) is None


def test_claude_engine_with_key_uses_claude(monkeypatch):
    from gab_faq.brain import Brain

    discord_answers = _settings_with("claude", monkeypatch, api_key="sk-ant-test-not-real")
    answerer = discord_answers.setup_faq_answers(SimpleNamespace(user=None))
    from gab_faq.guard import GuardedEngine

    assert isinstance(answerer.brain, GuardedEngine)  # every engine is wrapped in the guard
    assert isinstance(answerer.brain.inner, Brain)


def test_unknown_engine_rejected(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("gab_faq:\n  engine: gpt\n")
    with pytest.raises(ValueError, match="engine"):
        load_settings(p)


def test_followup_settings(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "gab_faq:\n  followup:\n    after_minutes: 30\n    reminder_channel: '#gab-support'\n"
        "    reminder_mention: '<@&555>'\n"
    )
    f = load_settings(p).followup
    assert (
        f.after_minutes == 30
        and f.reminder_channel == "gab-support"
        and f.reminder_mention == "<@&555>"
    )
    assert load_settings(ROOT / "config.yaml").followup.after_minutes == 60


def test_bucketing_watches_gab_sections_and_exports_the_section(tmp_path):
    """Question collection / export: GAB channels are watched by section, since both sections use
    the same channel names; another project's channel of the same name is not."""
    script = (
        "import bot\n"
        "app=bot.create_bot()\n"
        "from gab_faq.discord_bot.queries import section, CSV_FIELDS\n"
        "from gab_faq.discord_bot.views import WhatElseView, FAQPanelView\n"
        "from types import SimpleNamespace as N\n"
        "qc = N(name='Project GAB P5 QC Deployed')\n"
        "other = N(name='Project Maitrix')\n"
        "print('RESULT', app.queries.is_watched(N(name='support', category=qc)),"
        " app.queries.is_watched(N(name='support', category=other)),"
        " app.queries.is_watched(N(name='general', category=None)),"
        " section(N(name='support', category=qc)), 'section' in CSV_FIELDS)\n"
        "import asyncio\n"
        "async def views():\n"
        "    return WhatElseView(app.exports).is_persistent(), FAQPanelView(app.exports).is_persistent()\n"
        "print('PERSISTENT', *asyncio.run(views()))\n"
        "asyncio.run(app.close())\n"
    )
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "SECRETS_DIR": str(tmp_path / "none"),
        "DISCORD_TOKEN": "",
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "RESULT True False True Project GAB P5 QC Deployed True" in result.stdout
    # Buttons under results and on the main panel keep working on old messages / after restarts.
    assert "PERSISTENT True True" in result.stdout
