"""Backfill: walk projects_dir and process sessions oldest-first (DESIGN §6)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .config import Config
from .entities import EntityBook
from .process import ProcessResult, process_session
from .state import State


def discover_sessions(projects_dir: str | Path) -> list[Path]:
    """All ``*.jsonl`` under projects_dir, oldest mtime first."""
    projects_dir = Path(projects_dir)
    if not projects_dir.exists():
        return []
    files = list(projects_dir.rglob("*.jsonl"))
    files.sort(key=lambda p: p.stat().st_mtime)
    return files


def backfill(
    config: Config,
    client: Any,
    *,
    state: State,
    book: EntityBook,
    limit: int | None = None,
    dry_run: bool = False,
    force: bool = False,
    progress: Callable[[int, int, str, str], None] | None = None,
) -> list[ProcessResult]:
    """Process discovered sessions oldest-first. ``limit`` caps *processed* (non-skipped).

    ``progress(done, total, label, status)`` is invoked with ``status="start"``
    before each session (so a UI can show the in-flight item — the LLM call is the
    slow part) and again with the final status once it completes.
    """
    files = discover_sessions(config.projects_dir)
    total = len(files)
    results: list[ProcessResult] = []
    processed = 0
    for i, jsonl in enumerate(files):
        if progress is not None:
            progress(i, total, jsonl.name, "start")
        result = process_session(
            jsonl, config, client, state=state, book=book, dry_run=dry_run, force=force
        )
        if progress is not None:
            progress(i + 1, total, jsonl.name, result.status)
        if result.status == "skipped":
            continue
        results.append(result)
        processed += 1
        if limit is not None and processed >= limit:
            break
    return results
