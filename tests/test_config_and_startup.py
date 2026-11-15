"""config.yaml's gab_faq section, secrets from files, and bot.py starting with FAQ answers on/off."""

import os
import subprocess
import sys

import pytest

from gab_faq.config import load_secret_files, load_settings

from .conftest import ROOT


def test_repo_config_yaml_has_a_valid_gab_faq_section():
    s = load_settings(ROOT / "config.yaml")
    assert s.environment in ("staging", "production")
    assert s.engine == "qwen"
    assert s.model == "qwen3-omni-flash"
    assert s.search.model == "BAAI/bge-small-en-v1.5"
    assert s.knowledge_dir == ROOT / "knowledge" / "current"
    assert s.knowledge_dir.is_dir()


def test_missing_section_means_off(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("channel_names: [general]\n")
    assert load_settings(p).enabled is False


def test_omitted_engine_and_model_default_to_qwen(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("gab_faq:\n  enabled: true\n")
    settings = load_settings(p)
    assert settings.engine == "qwen"
    assert settings.model == "qwen3-omni-flash"


@pytest.mark.parametrize("model", ["claude-sonnet", "gpt-4o", "qwen-plus", ""])
def test_wrong_llm_model_rejected(tmp_path, model):
    p = tmp_path / "config.yaml"
    p.write_text(f'gab_faq:\n  model: "{model}"\n')
    with pytest.raises(ValueError, match="gab_faq.model must be 'qwen3-omni-flash'"):
        load_settings(p)


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


def _start_bot(tmp_path, api_key: str, faq_config=None) -> subprocess.CompletedProcess:
    """Load bot.py the way `python bot.py` does, but stop before connecting to Discord.
    `faq_config`: a config.yaml for the FAQ part (default: the project's own config.yaml)."""
    env = {
        **os.environ,
        "PYTHONPATH": str(ROOT),
        "DASHSCOPE_API_KEY": api_key,
        "SECRETS_DIR": str(tmp_path / "no-secrets"),
        "DISCORD_TOKEN": "",
    }
    setup_call = (
        f"setup_faq_answers(app, {str(faq_config)!r})" if faq_config else ("setup_faq_answers(app)")
    )
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import asyncio, logging; logging.basicConfig(level=logging.INFO); "
            "from bot import create_bot; from gab_faq.discord_answers import setup_faq_answers; "
            f"app=create_bot(); app.faq_answers={setup_call}; "
            "print('FAQ_ANSWERER=' + type(app.faq_answers).__name__); asyncio.run(app.close())",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_bot_starts_with_free_search_and_no_api_key(tmp_path):
    # Explicit local search needs no model API key.
    faq_config = tmp_path / "search-only.yaml"
    faq_config.write_text("gab_faq:\n  enabled: true\n  engine: search\n")
    result = _start_bot(tmp_path, api_key="", faq_config=faq_config)
    assert result.returncode == 0, result.stderr
    assert "FAQ_ANSWERER=FaqAnswerer" in result.stdout
    assert "[FAQ] Answering is ON" in result.stderr and "FAQ search" in result.stderr


@pytest.mark.parametrize("api_key", ["", "SYNTHETIC_ALIBABA_KEY"])
def test_bot_startup_uses_qwen_by_default_without_provider_fallback(tmp_path, api_key):
    faq_config = tmp_path / "qwen-default.yaml"
    faq_config.write_text("gab_faq:\n  enabled: true\n")
    result = _start_bot(tmp_path, api_key=api_key, faq_config=faq_config)
    assert result.returncode == 0, result.stderr
    if api_key:
        assert "FAQ_ANSWERER=FaqAnswerer" in result.stdout
        assert "Qwen3-Omni-Flash" in result.stderr
    else:
        assert "FAQ_ANSWERER=NoneType" in result.stdout
        assert "Qwen requires DASHSCOPE_API_KEY" in result.stderr


@pytest.mark.parametrize("engine", ["claude", "openai"])
def test_external_model_engines_are_disabled(tmp_path, engine):
    config = tmp_path / "config.yaml"
    config.write_text(f"gab_faq:\n  engine: {engine}\n")
    with pytest.raises(ValueError, match="engine"):
        load_settings(config)


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
        "qc = N(name='Project GAB P6 QC Deployed')\n"
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
    assert "RESULT True False True Project GAB P6 QC Deployed True" in result.stdout
    # Buttons under results and on the main panel keep working on old messages / after restarts.
    assert "PERSISTENT True True" in result.stdout
