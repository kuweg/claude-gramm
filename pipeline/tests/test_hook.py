"""Tests for SessionEnd hook install/uninstall (DESIGN §6)."""
from __future__ import annotations

import io
import json

from engram import hook


def _read(p):
    return json.loads(p.read_text())


def test_install_into_missing_file_creates_entry(tmp_path):
    settings = tmp_path / "settings.json"
    added = hook.install_hook(settings)
    assert added is True
    data = _read(settings)
    cmds = [
        h["command"]
        for entry in data["hooks"]["SessionEnd"]
        for h in entry["hooks"]
    ]
    assert hook.HOOK_COMMAND in cmds


def test_install_is_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    assert hook.install_hook(settings) is True
    assert hook.install_hook(settings) is False  # already present
    data = _read(settings)
    count = sum(
        h["command"] == hook.HOOK_COMMAND
        for entry in data["hooks"]["SessionEnd"]
        for h in entry["hooks"]
    )
    assert count == 1


def test_install_preserves_existing_settings_and_backs_up(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"model": "opus", "hooks": {"SessionEnd": [
        {"hooks": [{"type": "command", "command": "other-tool"}]}
    ]}}))
    hook.install_hook(settings)
    data = _read(settings)
    assert data["model"] == "opus"
    cmds = [h["command"] for e in data["hooks"]["SessionEnd"] for h in e["hooks"]]
    assert "other-tool" in cmds and hook.HOOK_COMMAND in cmds
    backups = list(tmp_path.glob("settings.json.bak*"))
    assert backups, "a timestamped backup should be created"


def test_uninstall_removes_only_our_entry(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {"SessionEnd": [
        {"hooks": [{"type": "command", "command": "other-tool"}]}
    ]}}))
    hook.install_hook(settings)
    removed = hook.uninstall_hook(settings)
    assert removed is True
    cmds = [h["command"] for h in data_entries(settings)]
    assert hook.HOOK_COMMAND not in cmds
    assert "other-tool" in cmds


def data_entries(settings):
    data = json.loads(settings.read_text())
    return [h for e in data["hooks"]["SessionEnd"] for h in e["hooks"]]


def test_uninstall_when_absent_returns_false(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}))
    assert hook.uninstall_hook(settings) is False


def test_read_hook_input_parses_stdin_json():
    payload = {"session_id": "s", "transcript_path": "/p/s.jsonl", "cwd": "/p"}
    stream = io.StringIO(json.dumps(payload))
    assert hook.read_hook_input(stream)["transcript_path"] == "/p/s.jsonl"
