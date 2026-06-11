"""Tests for distillation: prompt build, Anthropic call (faked), chunking (DESIGN §3)."""
from __future__ import annotations

import json

import pytest

from engram import distill


class FakeBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class FakeResponse:
    def __init__(self, payload):
        self.content = [FakeBlock(payload if isinstance(payload, str) else json.dumps(payload))]


class FakeMessages:
    def __init__(self, outer):
        self._outer = outer

    def create(self, **kwargs):
        self._outer.calls.append(kwargs)
        return FakeResponse(self._outer.queue.pop(0))


class FakeClient:
    """Record/replay stand-in for anthropic.Anthropic (no network in CI)."""

    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []
        self.messages = FakeMessages(self)


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


def test_distill_chunk_calls_client_and_parses_json():
    client = FakeClient([_payload()])
    result = distill.distill_chunk(_compacted()["events"], _compacted(), client, model="m")
    assert result["title"] == "add-fetcher-retry-logic"
    assert result["entities"] == ["tokio"]
    # structured output requested
    kwargs = client.calls[0]
    assert kwargs["model"] == "m"
    assert "output_config" in kwargs
    assert kwargs["output_config"]["format"]["type"] == "json_schema"


def test_chunk_events_splits_on_user_boundaries():
    events = [
        {"kind": "user", "text": "a" * 100},
        {"kind": "assistant", "text": "b" * 100},
        {"kind": "user", "text": "c" * 100},
        {"kind": "assistant", "text": "d" * 100},
    ]
    chunks = distill.chunk_events(events, max_chars=150)
    assert len(chunks) == 2
    # each chunk starts at a user message
    assert chunks[0][0]["kind"] == "user"
    assert chunks[1][0]["kind"] == "user"


def test_chunk_events_single_chunk_when_small():
    events = [{"kind": "user", "text": "hi"}, {"kind": "assistant", "text": "yo"}]
    assert len(distill.chunk_events(events, max_chars=10_000)) == 1


def test_distill_session_single_chunk_one_call():
    client = FakeClient([_payload()])
    out = distill.distill_session(_compacted(), client, model="m", max_chunk_chars=10_000)
    assert out["tldr"] == "Added backoff."
    assert len(client.calls) == 1  # no reduce call


def test_distill_session_multi_chunk_maps_and_reduces():
    big = _compacted(
        events=[
            {"kind": "user", "text": "x" * 200},
            {"kind": "assistant", "text": "y" * 200},
            {"kind": "user", "text": "z" * 200},
            {"kind": "assistant", "text": "w" * 200},
        ]
    )
    # two map responses + one reduce (tldr merge) response
    client = FakeClient(
        [
            _payload(decisions=[{"what": "use backoff", "why": "resilience"}], entities=["tokio"]),
            _payload(decisions=[{"what": "use backoff", "why": "resilience"}], entities=["serde"]),
            "Merged summary of both chunks.",
        ]
    )
    out = distill.distill_session(big, client, model="m", max_chunk_chars=300)
    assert len(client.calls) == 3  # 2 maps + 1 reduce
    # arrays merged + deduped (one decision, not two)
    assert len(out["decisions"]) == 1
    assert set(out["entities"]) == {"tokio", "serde"}
    assert out["tldr"] == "Merged summary of both chunks."
