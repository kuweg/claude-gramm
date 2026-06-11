"""Tests for entity review operations: approve / alias / reject (DESIGN §4.2)."""
from __future__ import annotations

import pytest

from engram import review
from engram.config import Config
from engram.entities import EntityBook
from engram.state import State


@pytest.fixture
def env(tmp_path):
    cfg = Config(
        vault_path=tmp_path / "vault",
        projects_dir=tmp_path / "projects",
        model="m",
        redact=False,
        max_text_chars=4000,
        entities_file=tmp_path / "entities.yaml",
        state_db=tmp_path / "state.db",
        parser_bin="",
        sessions_dir="Sessions",
        concepts_dir="Concepts",
        projects_dir_notes="Projects",
    )
    state = State(cfg.state_db)
    state.add_pending_entity("tokio", display="tokio", session_id="s1")
    state.add_pending_entity("kafka", display="Kafka", session_id="s1")
    book = EntityBook.from_yaml(cfg.entities_file)
    return cfg, state, book


def test_approve_adds_to_yaml_creates_stub_and_marks_status(env):
    cfg, state, book = env
    review.approve(state, book, cfg, "tokio", etype="library", display="tokio")
    # entities.yaml now has it
    reloaded = EntityBook.from_yaml(cfg.entities_file)
    e = reloaded.lookup("tokio")
    assert e is not None and e.type == "library"
    # Concepts stub created
    stub = cfg.vault_path / "Concepts" / "tokio.md"
    assert stub.exists()
    assert "# tokio" in stub.read_text()
    # state status updated
    assert "tokio" not in {r["name"] for r in state.get_pending_entities()}
    assert "tokio" in {r["name"] for r in state.get_pending_entities(status="approved")}


def test_alias_attaches_to_canonical_and_resolves(env):
    cfg, state, book = env
    review.approve(state, book, cfg, "tokio", etype="library", display="tokio")
    review.alias(state, book, cfg, "kafka", canonical="tokio")
    reloaded = EntityBook.from_yaml(cfg.entities_file)
    assert reloaded.lookup("kafka") is not None
    assert reloaded.lookup("kafka").name == "tokio"
    assert "kafka" in {r["name"] for r in state.get_pending_entities(status="aliased")}


def test_reject_blacklists(env):
    cfg, state, book = env
    review.reject(state, "kafka")
    assert "kafka" not in {r["name"] for r in state.get_pending_entities()}
    assert "kafka" in {r["name"] for r in state.get_pending_entities(status="rejected")}
