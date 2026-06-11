"""Render a distilled session into an Obsidian note (DESIGN §4.1).

File paths render as inline code (one note per source file would flood the
graph). Entities render as wikilinks only after normalization (§4.2). The
project hub is always a wikilink (projects are auto-approved entities).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .entities import EntityBook, render_entities

ENGRAM_VERSION = 1
SLUG_MAX = 50

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class RenderConfig:
    concepts_dir: str = "Concepts"
    projects_dir: str = "Projects"


@dataclass
class RenderResult:
    markdown: str
    slug: str
    pending: list[tuple[str, str]]


def slugify(title: str) -> str:
    s = _SLUG_STRIP.sub("-", title.strip().lower()).strip("-")
    return s[:SLUG_MAX].strip("-") or "untitled"


def local_date(iso: str | None) -> str:
    """Date portion of an ISO-8601 timestamp, in the user's local timezone (§7.1)."""
    if not iso:
        return "unknown"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:10]
    if dt.tzinfo is not None:
        dt = dt.astimezone()
    return dt.date().isoformat()


def render_note(
    distilled: dict[str, Any],
    compacted: dict[str, Any],
    book: EntityBook,
    config: RenderConfig,
) -> RenderResult:
    project_path = compacted.get("project_path")
    project_name = Path(project_path).name if project_path else "unknown"
    if project_path:
        book.add_project(project_path)

    branch = compacted.get("git_branch") or "—"
    session_type = distilled.get("session_type", "other")
    title = distilled.get("title") or "untitled"
    slug = slugify(title)
    date = local_date(compacted.get("started_at"))

    entity_md, pending = render_entities(
        distilled.get("entities", []), book, concepts_dir=config.concepts_dir
    )

    lines: list[str] = []
    # Front matter
    lines += [
        "---",
        f"date: {date}",
        f"project: {project_name}",
        f"session_id: {compacted.get('session_id', '')}",
        f"type: {session_type}",
        "tags: [session]",
        f"engram_version: {ENGRAM_VERSION}",
        "---",
        "",
        f"# {title}",
        "",
        f"**Project:** [[{project_name}]] · **Branch:** {branch} · **Type:** {session_type}",
        "",
        "## TL;DR",
        distilled.get("tldr", "").strip(),
        "",
        "## Decisions",
    ]
    for d in distilled.get("decisions", []):
        lines.append(f"- **{d.get('what', '').strip()}** — {d.get('why', '').strip()}")
    lines += ["", "## Problems solved"]
    for p in distilled.get("problems_solved", []):
        lines.append(
            f"- **{p.get('problem', '').strip()}** — {p.get('solution', '').strip()}"
        )
    lines += ["", "## Open threads"]
    for t in distilled.get("open_threads", []):
        lines.append(f"- [ ] {str(t).strip()}")

    lines += ["", "## Touched"]
    if entity_md:
        lines.append("- " + ", ".join(entity_md))
    files = compacted.get("files_touched", [])
    if files:
        lines.append("- " + ", ".join(f"`{f}`" for f in files))
    lines.append("")

    return RenderResult(markdown="\n".join(lines), slug=slug, pending=pending)
