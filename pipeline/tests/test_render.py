"""Tests for the Obsidian note renderer (DESIGN §4.1)."""
from __future__ import annotations

from engram.entities import EntityBook
from engram.render import RenderConfig, local_date, render_note, slugify


def _distilled():
    return {
        "title": "add-fetcher-retry-logic",
        "tldr": "Added exponential backoff to the fetcher. All tests pass.",
        "session_type": "feature",
        "decisions": [{"what": "Chose exponential backoff over fixed delay", "why": "avoids thundering herd"}],
        "problems_solved": [{"problem": "fetcher gave up on first failure", "solution": "retry loop capped at 3"}],
        "open_threads": ["wire up jitter"],
        "entities": ["tokio", "exponential backoff"],
    }


def _compacted():
    return {
        "session_id": "00000000-0000-4000-8000-000000000001",
        "project_path": "/home/user/projects/demo",
        "git_branch": "main",
        "started_at": "2026-06-01T10:00:01.000Z",
        "files_touched": ["src/lib.rs", "src/main.rs"],
    }


CFG = RenderConfig(concepts_dir="Concepts", projects_dir="Projects")


def test_slugify_kebabs_and_truncates():
    assert slugify("Add Fetcher Retry Logic!") == "add-fetcher-retry-logic"
    assert len(slugify("x" * 80)) <= 50


def test_render_includes_frontmatter():
    book = EntityBook.from_list([{"name": "tokio", "type": "library"}])
    out = render_note(_distilled(), _compacted(), book, CFG)
    md = out.markdown
    assert md.startswith("---\n")
    assert f"date: {local_date('2026-06-01T10:00:01.000Z')}" in md
    assert "project: demo" in md
    assert "session_id: 00000000-0000-4000-8000-000000000001" in md
    assert "type: feature" in md
    assert "engram_version: 1" in md


def test_render_title_and_header():
    book = EntityBook.from_list([])
    md = render_note(_distilled(), _compacted(), book, CFG).markdown
    assert "# add-fetcher-retry-logic" in md
    assert "[[demo]]" in md  # project wikilink (auto-approved)
    assert "Branch:** main" in md


def test_render_sections_present():
    book = EntityBook.from_list([])
    md = render_note(_distilled(), _compacted(), book, CFG).markdown
    assert "## TL;DR" in md
    assert "## Decisions" in md
    assert "**Chose exponential backoff over fixed delay** — avoids thundering herd" in md
    assert "## Problems solved" in md
    assert "**fetcher gave up on first failure** — retry loop capped at 3" in md
    assert "## Open threads" in md
    assert "- [ ] wire up jitter" in md


def test_render_files_as_inline_code_not_wikilinks():
    book = EntityBook.from_list([])
    md = render_note(_distilled(), _compacted(), book, CFG).markdown
    assert "`src/lib.rs`" in md
    assert "[[src/lib.rs]]" not in md


def test_render_matched_entity_is_wikilink_unmatched_is_pending():
    book = EntityBook.from_list([{"name": "tokio", "type": "library"}])
    out = render_note(_distilled(), _compacted(), book, CFG)
    assert "[[Concepts/tokio|tokio]]" in out.markdown
    assert "exponential backoff" in out.markdown
    pending_keys = [k for k, _ in out.pending]
    assert "exponential backoff" in pending_keys


def test_render_slug_returned_for_filename():
    book = EntityBook.from_list([])
    out = render_note(_distilled(), _compacted(), book, CFG)
    assert out.slug == "add-fetcher-retry-logic"
