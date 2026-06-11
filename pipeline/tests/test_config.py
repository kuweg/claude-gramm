"""Tests for configuration loading (DESIGN §5)."""
from __future__ import annotations

from pathlib import Path

from engram import config as cfg


def _write(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


def test_load_applies_defaults_for_missing_keys(tmp_path):
    f = _write(tmp_path / "c.toml", 'vault_path = "/v"\n')
    c = cfg.load_config(f)
    assert c.vault_path == Path("/v")
    assert c.model == cfg.DEFAULTS["model"]
    assert c.redact is True
    assert c.sessions_dir == "Sessions"


def test_load_expands_user_in_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/home/tester")
    f = _write(tmp_path / "c.toml", 'vault_path = "~/vault"\n')
    c = cfg.load_config(f)
    assert c.vault_path == Path("/home/tester/vault")


def test_load_reads_vault_subdirs(tmp_path):
    f = _write(
        tmp_path / "c.toml",
        'vault_path = "/v"\n[vault]\nsessions_dir = "Logs"\nconcepts_dir = "Topics"\n',
    )
    c = cfg.load_config(f)
    assert c.sessions_dir == "Logs"
    assert c.concepts_dir == "Topics"
    assert c.projects_dir_notes == "Projects"  # vault notes dir default kept


def test_env_override_selects_config_path(tmp_path, monkeypatch):
    f = _write(tmp_path / "custom.toml", 'vault_path = "/from/env"\n')
    monkeypatch.setenv("ENGRAM_CONFIG", str(f))
    c = cfg.load_config()
    assert c.vault_path == Path("/from/env")


def test_default_config_toml_is_parseable_and_has_vault(tmp_path):
    body = cfg.default_config_toml("/my/vault")
    f = _write(tmp_path / "c.toml", body)
    c = cfg.load_config(f)
    assert c.vault_path == Path("/my/vault")
    assert "[vault]" in body
