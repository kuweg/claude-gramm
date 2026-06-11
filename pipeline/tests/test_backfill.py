"""Tests for backfill: discover *.jsonl, process oldest-first, --limit (DESIGN §6)."""
from __future__ import annotations

import json
import os

import pytest

from engram import backfill
from engram.config import Config
from engram.entities import EntityBook
from engram.state import State
from tests._fakes import DISTILLED, FakeLLM as FakeClient


def _session_file(path, session_id, cwd="/p/demo", mtime=None):
    path.write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "do a thing"},
                "timestamp": "2026-06-01T10:00:00.000Z",
                "cwd": cwd,
                "sessionId": session_id,
                "gitBranch": "main",
                "version": "2.1.158",
            }
        )
        + "\n"
    )
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


@pytest.fixture
def cfg(tmp_path, parser_bin):
    return Config(
        vault_path=tmp_path / "vault",
        projects_dir=tmp_path / "projects",
        model="m",
        redact=False,
        max_text_chars=4000,
        entities_file=tmp_path / "entities.yaml",
        state_db=tmp_path / "state.db",
        parser_bin=str(parser_bin),
        sessions_dir="Sessions",
        concepts_dir="Concepts",
        projects_dir_notes="Projects",
    )


def test_discover_finds_nested_jsonl_oldest_first(cfg):
    proj = cfg.projects_dir
    (proj / "a").mkdir(parents=True)
    (proj / "b").mkdir(parents=True)
    _session_file(proj / "a" / "s1.jsonl", "s1", mtime=1000)
    _session_file(proj / "b" / "s2.jsonl", "s2", mtime=500)
    found = backfill.discover_sessions(proj)
    assert [p.name for p in found] == ["s2.jsonl", "s1.jsonl"]  # oldest first


def test_backfill_processes_all_and_writes_notes(cfg):
    proj = cfg.projects_dir
    proj.mkdir(parents=True)
    _session_file(proj / "s1.jsonl", "s1", mtime=100)
    _session_file(proj / "s2.jsonl", "s2", mtime=200)
    client = FakeClient([DISTILLED, DISTILLED])
    with State(cfg.state_db) as state:
        book = EntityBook.from_yaml(cfg.entities_file)
        results = backfill.backfill(cfg, client, state=state, book=book)
    assert [r.status for r in results] == ["woven", "woven"]
    notes = list((cfg.vault_path / "Sessions").glob("*.md"))
    assert len(notes) == 2


def test_backfill_limit_caps_processed(cfg):
    proj = cfg.projects_dir
    proj.mkdir(parents=True)
    for i in range(4):
        _session_file(proj / f"s{i}.jsonl", f"s{i}", mtime=100 + i)
    client = FakeClient([DISTILLED, DISTILLED])
    with State(cfg.state_db) as state:
        book = EntityBook.from_yaml(cfg.entities_file)
        results = backfill.backfill(cfg, client, state=state, book=book, limit=2)
    assert len(results) == 2
    assert all(r.status == "woven" for r in results)


def test_backfill_reports_progress(cfg):
    proj = cfg.projects_dir
    proj.mkdir(parents=True)
    _session_file(proj / "s1.jsonl", "s1", mtime=100)
    _session_file(proj / "s2.jsonl", "s2", mtime=200)
    events = []
    client = FakeClient([DISTILLED, DISTILLED])
    with State(cfg.state_db) as state:
        book = EntityBook.from_yaml(cfg.entities_file)
        backfill.backfill(
            cfg, client, state=state, book=book,
            progress=lambda done, total, label, status: events.append((done, total, status)),
        )
    statuses = [e[2] for e in events]
    assert "start" in statuses          # in-flight notification per item
    assert statuses.count("woven") == 2  # one completion per session
    assert events[-1][0] == events[-1][1] == 2  # final done == total


def test_backfill_rerun_is_noop(cfg):
    proj = cfg.projects_dir
    proj.mkdir(parents=True)
    _session_file(proj / "s1.jsonl", "s1", mtime=100)
    with State(cfg.state_db) as state:
        book = EntityBook.from_yaml(cfg.entities_file)
        backfill.backfill(cfg, FakeClient([DISTILLED]), state=state, book=book)
    # second run: nothing changed → all skipped, no extra LLM calls
    client2 = FakeClient([])
    with State(cfg.state_db) as state:
        book = EntityBook.from_yaml(cfg.entities_file)
        results = backfill.backfill(cfg, client2, state=state, book=book)
    assert all(r.status == "skipped" for r in results)
    assert client2.json_calls == []
