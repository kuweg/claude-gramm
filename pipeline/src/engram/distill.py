"""Distill a compacted session into structured notes via the Anthropic API (DESIGN §3).

Output is forced to strict JSON via ``output_config.format`` (structured outputs).
The Anthropic client is injected so tests can record/replay without a network call.
Sessions that exceed the context budget are split on user-message boundaries,
distilled per chunk, then reduced (arrays merged + deduped, tldrs re-summarized).
"""
from __future__ import annotations

from typing import Any

# chars/4 ≈ tokens; keep a chunk well under the model context budget.
DEFAULT_MAX_CHUNK_CHARS = 600_000
DISTILL_MAX_TOKENS = 4096

DISTILL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "tldr": {"type": "string"},
        "session_type": {
            "type": "string",
            "enum": ["debugging", "feature", "config", "research", "other"],
        },
        "decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"what": {"type": "string"}, "why": {"type": "string"}},
                "required": ["what", "why"],
                "additionalProperties": False,
            },
        },
        "problems_solved": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "problem": {"type": "string"},
                    "solution": {"type": "string"},
                },
                "required": ["problem", "solution"],
                "additionalProperties": False,
            },
        },
        "open_threads": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "title", "tldr", "session_type",
        "decisions", "problems_solved", "open_threads", "entities",
    ],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are distilling a Claude Code engineering session into structured notes "
    "for a personal knowledge base."
)

_RULES = """Extract JSON per the provided schema. Rules:
- title: use the suggested title if it accurately describes the session; otherwise write one (≤60 chars).
- tldr: what was actually accomplished, not what was attempted. Past tense, concrete.
- decisions: only deliberate choices with alternatives (architecture, library, approach). Not routine actions.
- open_threads: anything explicitly deferred, TODO'd, or left broken.
- entities: proper nouns a knowledge graph should link — projects, tools, libraries, services, named concepts. No generic words.
- Empty arrays are fine. Never invent content."""


def render_events(events: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for ev in events:
        kind = ev.get("kind")
        if kind == "user":
            lines.append(f"USER: {ev.get('text', '')}")
        elif kind == "assistant":
            lines.append(f"ASSISTANT: {ev.get('text', '')}")
        elif kind == "tool":
            lines.append(f"TOOL {ev.get('name', '')}: {ev.get('arg', '')}")
    return "\n".join(lines)


def build_prompt(compacted: dict[str, Any], events: list[dict[str, Any]] | None = None) -> str:
    events = compacted["events"] if events is None else events
    title = compacted.get("title") or "none"
    return (
        f"Session metadata: project={compacted.get('project_path')}, "
        f"branch={compacted.get('git_branch')}, date={compacted.get('started_at')}, "
        f"suggested title: {title}.\n\n"
        "Transcript (compacted; tool outputs removed):\n"
        f"{render_events(events)}\n\n"
        f"{_RULES}"
    )


def distill_chunk(
    events: list[dict[str, Any]],
    compacted: dict[str, Any],
    client: Any,
) -> dict[str, Any]:
    """Distill one chunk of events into the structured-output schema."""
    prompt = build_prompt(compacted, events=events)
    return client.complete_json(
        system=SYSTEM_PROMPT,
        prompt=prompt,
        schema=DISTILL_SCHEMA,
        max_tokens=DISTILL_MAX_TOKENS,
    )


def chunk_events(
    events: list[dict[str, Any]], max_chars: int = DEFAULT_MAX_CHUNK_CHARS
) -> list[list[dict[str, Any]]]:
    """Split events into chunks of ≤max_chars, breaking only on user boundaries."""
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for ev in events:
        ev_size = len(ev.get("text", "")) + len(ev.get("name", "")) + len(ev.get("arg", ""))
        if current and ev.get("kind") == "user" and size + ev_size > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(ev)
        size += ev_size
    if current:
        chunks.append(current)
    return chunks


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _dedupe_dicts(items: list[dict[str, Any]], key_field: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in items:
        key = str(item.get(key_field, "")).strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def reduce_distillations(parts: list[dict[str, Any]], client: Any) -> dict[str, Any]:
    """Merge chunk distillations: concat+dedupe arrays, re-summarize tldrs."""
    decisions = _dedupe_dicts([d for p in parts for d in p.get("decisions", [])], "what")
    problems = _dedupe_dicts(
        [pr for p in parts for pr in p.get("problems_solved", [])], "problem"
    )
    threads = _dedupe_strings([t for p in parts for t in p.get("open_threads", [])])
    entities = _dedupe_strings([e for p in parts for e in p.get("entities", [])])

    tldrs = "\n".join(f"- {p.get('tldr', '')}" for p in parts)
    tldr = client.complete_text(
        system=SYSTEM_PROMPT,
        prompt=(
            "Merge these partial session summaries into one concise TL;DR "
            f"(2-4 sentences, past tense, concrete):\n{tldrs}"
        ),
        max_tokens=512,
    )
    return {
        "title": parts[-1].get("title", "untitled"),
        "session_type": parts[-1].get("session_type", "other"),
        "tldr": tldr.strip(),
        "decisions": decisions,
        "problems_solved": problems,
        "open_threads": threads,
        "entities": entities,
    }


def distill_session(
    compacted: dict[str, Any],
    client: Any,
    *,
    max_chunk_chars: int = DEFAULT_MAX_CHUNK_CHARS,
) -> dict[str, Any]:
    """Distill a whole session, chunking + reducing only if it overflows."""
    chunks = chunk_events(compacted.get("events", []), max_chars=max_chunk_chars)
    if len(chunks) <= 1:
        events = chunks[0] if chunks else []
        return distill_chunk(events, compacted, client)
    parts = [distill_chunk(chunk, compacted, client) for chunk in chunks]
    return reduce_distillations(parts, client)
