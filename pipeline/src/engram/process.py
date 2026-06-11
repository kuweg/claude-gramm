"""Process one session end to end: ingest → distill → weave (DESIGN §3-4).

Idempotency: the note path is derived from ``session_id`` via the state DB, so
re-processing rewrites the same file in place. A session is skipped entirely when
its jsonl is unchanged and already ``woven`` (unless ``force``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import distill, ingest
from .config import Config
from .entities import EntityBook
from .render import RenderConfig, local_date, render_note
from .state import State


@dataclass
class ProcessResult:
    status: str  # woven | skipped | dry_run | error
    session_id: str | None = None
    note_path: str | None = None
    markdown: str | None = None
    pending_count: int = 0
    error: str | None = None


def _unique_note_path(
    sessions_dir: Path, date: str, slug: str, session_id: str, state: State | None
) -> Path:
    if state is not None:
        row = state.get_session(session_id)
        if row and row.get("note_path"):
            return Path(row["note_path"])  # reuse → in-place rewrite
    candidate = sessions_dir / f"{date} {slug}.md"
    i = 2
    while candidate.exists():
        candidate = sessions_dir / f"{date} {slug}-{i}.md"
        i += 1
    return candidate


def process_session(
    jsonl_path: str | Path,
    config: Config,
    client: Any,
    *,
    state: State | None = None,
    book: EntityBook | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> ProcessResult:
    jsonl_path = Path(jsonl_path)
    stat = jsonl_path.stat()
    mtime, size = int(stat.st_mtime), stat.st_size

    try:
        compacted = ingest.run_parser(
            jsonl_path, parser_bin=config.parser_bin or None, redact=config.redact
        )
    except ingest.IngestError as exc:
        return ProcessResult(status="error", error=str(exc))

    session_id = compacted["session_id"]

    if state is not None and not dry_run:
        if not state.needs_processing(session_id, mtime=mtime, size=size, force=force):
            return ProcessResult(status="skipped", session_id=session_id)

    distilled = distill.distill_session(compacted, client, model=config.model)

    if book is None:
        book = EntityBook.from_yaml(config.entities_file)
    rcfg = RenderConfig(
        concepts_dir=config.concepts_dir, projects_dir=config.projects_dir_notes
    )
    rendered = render_note(distilled, compacted, book, rcfg)

    if dry_run:
        return ProcessResult(
            status="dry_run",
            session_id=session_id,
            markdown=rendered.markdown,
            pending_count=len(rendered.pending),
        )

    sessions_dir = config.vault_path / config.sessions_dir
    sessions_dir.mkdir(parents=True, exist_ok=True)
    date = local_date(compacted.get("started_at"))
    note_path = _unique_note_path(sessions_dir, date, rendered.slug, session_id, state)
    note_path.write_text(rendered.markdown)

    # Persist auto-approved project entities for future matching (§4.2).
    book.to_yaml(config.entities_file)

    if state is not None:
        state.upsert_session(
            session_id,
            str(jsonl_path),
            project=compacted.get("project_path"),
            mtime=mtime,
            size=size,
        )
        for key, display in rendered.pending:
            state.add_pending_entity(key, display=display, session_id=session_id)
        state.update_session(
            session_id,
            status="woven",
            note_path=str(note_path),
            schema_version=compacted.get("schema_version"),
            processed_at=datetime.now(timezone.utc).isoformat(),
        )

    return ProcessResult(
        status="woven",
        session_id=session_id,
        note_path=str(note_path),
        markdown=rendered.markdown,
        pending_count=len(rendered.pending),
    )
