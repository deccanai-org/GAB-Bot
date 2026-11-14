from dataclasses import replace
from types import SimpleNamespace

from gab_faq import discord_answers
from gab_faq.config import load_settings
from gab_faq.qwen import Qwen


def test_qwen_missing_key_does_not_fall_back_to_another_provider(tmp_path, monkeypatch):
    settings = replace(load_settings(), enabled=True, log_dir=tmp_path, dashscope_api_key_set=False)
    monkeypatch.setattr(discord_answers, "load_environment", lambda: None)
    monkeypatch.setattr(discord_answers, "load_settings", lambda: settings)
    assert discord_answers.setup_faq_answers(SimpleNamespace(user=None)) is None


def test_qwen_with_key_initializes_without_network_call(tmp_path, monkeypatch):
    settings = replace(load_settings(), enabled=True, log_dir=tmp_path, dashscope_api_key_set=True)
    monkeypatch.setattr(discord_answers, "load_environment", lambda: None)
    monkeypatch.setattr(discord_answers, "load_settings", lambda: settings)
    answerer = discord_answers.setup_faq_answers(SimpleNamespace(user=None))
    assert answerer is not None and isinstance(answerer.brain.inner, Qwen)
