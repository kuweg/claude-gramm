"""Tests for the SQLite state DB and re-run policy (DESIGN §4.3)."""
from __future__ import annotations

import stat

import pytest

from engram.state import State


@pytest.fixture
def state(tmp_path):
    return State(tmp_path / "state.db")


def test_init_creates_db_file_0600(tmp_path):
    db = tmp_path / "sub" / "state.db"
    State(db)
    assert db.exists()
    mode = stat.S_IMODE(db.stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_upsert_and_get_session_round_trip(state):
    state.upsert_session("s1", "/p/s1.jsonl", project="/p", mtime=100, size=2048)
    row = state.get_session("s1")
    assert row["session_id"] == "s1"
    assert row["jsonl_path"] == "/p/s1.jsonl"
    assert row["project"] == "/p"
    assert row["mtime"] == 100
    assert row["size"] == 2048
    assert row["status"] == "pending"


def test_get_unknown_session_returns_none(state):
    assert state.get_session("nope") is None


def test_update_session_status_and_note_path(state):
    state.upsert_session("s1", "/p/s1.jsonl", project="/p", mtime=1, size=1)
    state.update_session("s1", status="woven", note_path="/vault/note.md")
    row = state.get_session("s1")
    assert row["status"] == "woven"
    assert row["note_path"] == "/vault/note.md"


def test_needs_processing_new_session(state):
    assert state.needs_processing("new", mtime=1, size=1) is True


def test_needs_processing_unchanged_woven_is_false(state):
    state.upsert_session("s1", "/p/s1.jsonl", project="/p", mtime=100, size=2048)
    state.update_session("s1", status="woven")
    assert state.needs_processing("s1", mtime=100, size=2048) is False


def test_needs_processing_changed_mtime_is_true(state):
    state.upsert_session("s1", "/p/s1.jsonl", project="/p", mtime=100, size=2048)
    state.update_session("s1", status="woven")
    assert state.needs_processing("s1", mtime=200, size=2048) is True


def test_needs_processing_changed_size_is_true(state):
    state.upsert_session("s1", "/p/s1.jsonl", project="/p", mtime=100, size=2048)
    state.update_session("s1", status="woven")
    assert state.needs_processing("s1", mtime=100, size=4096) is True


def test_needs_processing_non_woven_status_is_true(state):
    state.upsert_session("s1", "/p/s1.jsonl", project="/p", mtime=100, size=2048)
    state.update_session("s1", status="error")
    assert state.needs_processing("s1", mtime=100, size=2048) is True


def test_needs_processing_force_overrides(state):
    state.upsert_session("s1", "/p/s1.jsonl", project="/p", mtime=100, size=2048)
    state.update_session("s1", status="woven")
    assert state.needs_processing("s1", mtime=100, size=2048, force=True) is True


def test_pending_entity_upsert_increments_count(state):
    state.add_pending_entity("tokio", display="tokio", session_id="s1")
    state.add_pending_entity("tokio", display="Tokio", session_id="s2")
    rows = {r["name"]: r for r in state.get_pending_entities()}
    assert rows["tokio"]["count"] == 2
    assert rows["tokio"]["first_session"] == "s1"  # first session preserved


def test_get_pending_entities_orders_by_count_desc(state):
    state.add_pending_entity("rare", display="rare", session_id="s1")
    for sid in ("a", "b", "c"):
        state.add_pending_entity("common", display="common", session_id=sid)
    names = [r["name"] for r in state.get_pending_entities()]
    assert names[0] == "common"


def test_set_pending_status_filters(state):
    state.add_pending_entity("tokio", display="tokio", session_id="s1")
    state.set_pending_status("tokio", "rejected")
    pending = [r["name"] for r in state.get_pending_entities(status="pending")]
    assert "tokio" not in pending
    rejected = [r["name"] for r in state.get_pending_entities(status="rejected")]
    assert "tokio" in rejected
