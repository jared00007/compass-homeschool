"""API key management -- writing a new key into .env must never clobber
other lines already there, and the running process's own environment has
to pick up the change immediately so a freshly-saved key works without
restarting the background service.
"""

from __future__ import annotations

import os

import pytest

from compass import apikey


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    monkeypatch.setattr(apikey, "ENV_PATH", tmp_path / ".env")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield


def test_masked_key_is_none_when_unset():
    assert apikey.masked_key() is None


def test_masked_key_shows_only_the_last_six_characters():
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-api03-abcdef123456"
    assert apikey.masked_key() == "…123456"


def test_save_key_creates_env_file_when_none_exists():
    apikey.save_key("sk-ant-api03-newkey")
    assert apikey.ENV_PATH.read_text() == "ANTHROPIC_API_KEY=sk-ant-api03-newkey\n"


def test_save_key_updates_the_running_process_environment():
    apikey.save_key("sk-ant-api03-newkey")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-api03-newkey"


def test_save_key_is_readable_back_via_masked_key():
    apikey.save_key("sk-ant-api03-abcdef123456")
    assert apikey.masked_key() == "…123456"


def test_save_key_replaces_an_existing_line_without_touching_others():
    apikey.ENV_PATH.write_text("SOME_OTHER_VAR=keep-me\nANTHROPIC_API_KEY=old-expired-key\n")
    apikey.save_key("sk-ant-api03-freshkey")
    text = apikey.ENV_PATH.read_text()
    assert "SOME_OTHER_VAR=keep-me" in text
    assert "ANTHROPIC_API_KEY=sk-ant-api03-freshkey" in text
    assert "old-expired-key" not in text


def test_save_key_appends_when_env_file_has_content_but_no_key_line():
    apikey.ENV_PATH.write_text("SOME_OTHER_VAR=keep-me\n")
    apikey.save_key("sk-ant-api03-freshkey")
    text = apikey.ENV_PATH.read_text()
    assert "SOME_OTHER_VAR=keep-me" in text
    assert "ANTHROPIC_API_KEY=sk-ant-api03-freshkey" in text


def test_save_key_strips_surrounding_whitespace():
    apikey.save_key("  sk-ant-api03-freshkey  \n")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-api03-freshkey"


def test_save_key_sets_restrictive_permissions():
    apikey.save_key("sk-ant-api03-freshkey")
    mode = apikey.ENV_PATH.stat().st_mode & 0o777
    assert mode == 0o600
