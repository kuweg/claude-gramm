"""Tests for end-to-end session processing + idempotency (DESIGN §4, Phase 2 verify)."""
from __future__ import annotations

import pytest

from engram.config import Config
from engram.entities import EntityBook
from engram.process import process_session
from engram.state import State
from tests._fakes import DISTILLED, FakeLLM as FakeClient


@pytest.fixture
def env(tmp_path, parser_bin):
    vault = tmp_path / "vault"
    cfg = Config(
        vault_path=vault,
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
    return cfg


def _run(cfg, fixtures_dir, client, **kw):
    state = State(cfg.state_db)
    book = EntityBook.from_yaml(cfg.entities_file)
    try:
        return process_session(
            fixtures_dir / "events.jsonl", cfg, client, state=state, book=book, **kw
        )
    finally:
        state.close()


def test_process_writes_note_and_marks_woven(env, fixtures_dir):
    client = FakeClient([DISTILLED])
    result = _run(env, fixtures_dir, client)
    assert result.status == "woven"
    note = env.vault_path / "Sessions"
    files = list(note.glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text()
    assert "# add-fetcher-retry-logic" in text
    assert "[[demo]]" in text
    # state updated
    state = State(env.state_db)
    row = state.get_session("00000000-0000-4000-8000-000000000001")
    state.close()
    assert row["status"] == "woven"
    assert row["note_path"] == str(files[0])


def test_process_records_unmatched_entity_as_pending(env, fixtures_dir):
    client = FakeClient([DISTILLED])
    _run(env, fixtures_dir, client)
    state = State(env.state_db)
    pending = {r["name"] for r in state.get_pending_entities()}
    state.close()
    assert "exponential backoff" in pending  # not in entities.yaml → pending + plain text


def test_dry_run_writes_nothing(env, fixtures_dir):
    client = FakeClient([DISTILLED])
    result = _run(env, fixtures_dir, client, dry_run=True)
    assert result.status == "dry_run"
    assert "# add-fetcher-retry-logic" in result.markdown
    assert not (env.vault_path / "Sessions").exists()
    state = State(env.state_db)
    assert state.get_session("00000000-0000-4000-8000-000000000001") is None
    state.close()


def test_second_run_is_idempotent_noop(env, fixtures_dir):
    _run(env, fixtures_dir, FakeClient([DISTILLED]))
    # second run: unchanged file, status already woven → skipped, no LLM call
    client2 = FakeClient([DISTILLED])
    result = _run(env, fixtures_dir, client2)
    assert result.status == "skipped"
    assert client2.json_calls == []  # distill never called
    files = list((env.vault_path / "Sessions").glob("*.md"))
    assert len(files) == 1  # no duplicate note


def test_force_reprocesses(env, fixtures_dir):
    _run(env, fixtures_dir, FakeClient([DISTILLED]))
    client2 = FakeClient([DISTILLED])
    result = _run(env, fixtures_dir, client2, force=True)
    assert result.status == "woven"
    assert len(client2.json_calls) == 1
