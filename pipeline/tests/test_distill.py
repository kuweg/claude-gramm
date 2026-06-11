"""Tests for distillation: prompt build, LLM call (faked), chunking (DESIGN §3)."""
from __future__ import annotations

from engram import distill
from tests._fakes import FakeLLM


def _compacted(events=None):
    return {
        "session_id": "s1",
        "project_path": "/p/demo",
        "git_branch": "main",
        "started_at": "2026-06-01T10:00:01.000Z",
        "title": "add-fetcher-retry-logic",
        "files_touched": [],
        "events": events
        or [
            {"kind": "user", "text": "add retry logic"},
            {"kind": "assistant", "text": "I'll add backoff"},
            {"kind": "tool", "name": "Bash", "arg": "cargo test"},
        ],
    }


def _payload(**over):
    base = {
        "title": "add-fetcher-retry-logic",
        "tldr": "Added backoff.",
        "session_type": "feature",
        "decisions": [],
        "problems_solved": [],
        "open_threads": [],
        "entities": ["tokio"],
    }
    base.update(over)
    return base


def test_build_prompt_renders_events():
    prompt = distill.build_prompt(_compacted())
    assert "USER: add retry logic" in prompt
    assert "ASSISTANT: I'll add backoff" in prompt
    assert "TOOL Bash: cargo test" in prompt
    assert "project=/p/demo" in prompt


def test_distill_chunk_requests_structured_json():
    client = FakeLLM(json_responses=[_payload()])
    result = distill.distill_chunk(_compacted()["events"], _compacted(), client)
    assert result["title"] == "add-fetcher-retry-logic"
    assert client.json_calls[0]["schema"] == distill.DISTILL_SCHEMA


def test_chunk_events_splits_on_user_boundaries():
    events = [
        {"kind": "user", "text": "a" * 100},
        {"kind": "assistant", "text": "b" * 100},
        {"kind": "user", "text": "c" * 100},
        {"kind": "assistant", "text": "d" * 100},
    ]
    chunks = distill.chunk_events(events, max_chars=150)
    assert len(chunks) == 2
    assert chunks[0][0]["kind"] == "user"
    assert chunks[1][0]["kind"] == "user"


def test_chunk_events_single_chunk_when_small():
    events = [{"kind": "user", "text": "hi"}, {"kind": "assistant", "text": "yo"}]
    assert len(distill.chunk_events(events, max_chars=10_000)) == 1


def test_distill_session_single_chunk_one_call():
    client = FakeLLM(json_responses=[_payload()])
    out = distill.distill_session(_compacted(), client, max_chunk_chars=10_000)
    assert out["tldr"] == "Added backoff."
    assert len(client.json_calls) == 1
    assert client.text_calls == []  # no reduce


def test_distill_session_multi_chunk_maps_and_reduces():
    big = _compacted(
        events=[
            {"kind": "user", "text": "x" * 200},
            {"kind": "assistant", "text": "y" * 200},
            {"kind": "user", "text": "z" * 200},
            {"kind": "assistant", "text": "w" * 200},
        ]
    )
    client = FakeLLM(
        json_responses=[
            _payload(decisions=[{"what": "use backoff", "why": "resilience"}], entities=["tokio"]),
            _payload(decisions=[{"what": "use backoff", "why": "resilience"}], entities=["serde"]),
        ],
        text_responses=["Merged summary of both chunks."],
    )
    out = distill.distill_session(big, client, max_chunk_chars=300)
    assert len(client.json_calls) == 2  # one per chunk
    assert len(client.text_calls) == 1  # reduce
    assert len(out["decisions"]) == 1  # deduped
    assert set(out["entities"]) == {"tokio", "serde"}
    assert out["tldr"] == "Merged summary of both chunks."
