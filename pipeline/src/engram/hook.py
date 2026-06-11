"""SessionEnd hook install/uninstall + detached re-spawn (DESIGN §6).

Users never hand-edit hook JSON. ``install_hook`` idempotently merges the
SessionEnd entry into settings.json (timestamped backup first); ``uninstall_hook``
removes exactly what it added. The installed command is identical on every
platform — detachment is handled inside engram, not in the hook command.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, IO

HOOK_EVENT = "SessionEnd"
HOOK_COMMAND = "engram process --hook --detach"


def _our_entry() -> dict[str, Any]:
    return {"hooks": [{"type": "command", "command": HOOK_COMMAND}]}


def _load(settings_path: Path) -> dict[str, Any]:
    if settings_path.exists():
        return json.loads(settings_path.read_text())
    return {}


def _backup(settings_path: Path) -> None:
    if settings_path.exists():
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(settings_path, settings_path.with_suffix(f".json.bak.{ts}"))


def _write(settings_path: Path, data: dict[str, Any]) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(data, indent=2) + "\n")


def _commands_in(entries: list[dict[str, Any]]) -> set[str]:
    return {h.get("command") for e in entries for h in e.get("hooks", [])}


def install_hook(settings_path: str | Path) -> bool:
    """Merge the SessionEnd entry. Returns True if added, False if already present."""
    settings_path = Path(settings_path)
    data = _load(settings_path)
    hooks = data.setdefault("hooks", {})
    session_end = hooks.setdefault(HOOK_EVENT, [])

    if HOOK_COMMAND in _commands_in(session_end):
        return False

    _backup(settings_path)
    session_end.append(_our_entry())
    _write(settings_path, data)
    return True


def uninstall_hook(settings_path: str | Path) -> bool:
    """Remove our SessionEnd entry. Returns True if anything was removed."""
    settings_path = Path(settings_path)
    if not settings_path.exists():
        return False
    data = _load(settings_path)
    session_end = data.get("hooks", {}).get(HOOK_EVENT, [])
    if HOOK_COMMAND not in _commands_in(session_end):
        return False

    _backup(settings_path)
    kept = []
    for entry in session_end:
        entry["hooks"] = [h for h in entry.get("hooks", []) if h.get("command") != HOOK_COMMAND]
        if entry["hooks"]:
            kept.append(entry)
    if kept:
        data["hooks"][HOOK_EVENT] = kept
    else:
        data["hooks"].pop(HOOK_EVENT, None)
    _write(settings_path, data)
    return True


def read_hook_input(stream: IO[str]) -> dict[str, Any]:
    """Parse the JSON the hook receives on stdin (session_id, transcript_path, …)."""
    return json.load(stream)


def spawn_detached(args: list[str]) -> None:
    """Re-spawn engram fully detached so the hook never blocks Claude Code shutdown.

    Portable: ``start_new_session`` on POSIX, ``DETACHED_PROCESS`` on Windows.
    """
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":  # pragma: no cover - platform specific
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(args, **kwargs)
