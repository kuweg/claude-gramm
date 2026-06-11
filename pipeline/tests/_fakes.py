"""Shared test doubles (provider-agnostic LLM client)."""
from __future__ import annotations

from typing import Any


class FakeLLM:
    """Records calls and replays queued responses — no network in CI."""

    def __init__(self, json_responses=None, text_responses=None):
        self.json_responses = list(json_responses or [])
        self.text_responses = list(text_responses or [])
        self.json_calls: list[dict[str, Any]] = []
        self.text_calls: list[dict[str, Any]] = []

    def complete_json(self, *, system, prompt, schema, max_tokens=4096):
        self.json_calls.append({"system": system, "prompt": prompt, "schema": schema})
        return self.json_responses.pop(0)

    def complete_text(self, *, system, prompt, max_tokens=512):
        self.text_calls.append({"system": system, "prompt": prompt})
        return self.text_responses.pop(0)


DISTILLED = {
    "title": "add-fetcher-retry-logic",
    "tldr": "Added exponential backoff to the fetcher.",
    "session_type": "feature",
    "decisions": [],
    "problems_solved": [],
    "open_threads": [],
    "entities": ["tokio", "exponential backoff"],
}
