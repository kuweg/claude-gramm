# ENGRAM — Design Document

**Status:** Phase 0 complete — awaiting review before any implementation.
**Date:** 2026-06-11
**Architecture (agreed):** Ingest (Rust) → Distill (Python + Anthropic API) → Weave (Python → Obsidian vault).

---

## 1. Verified data schema (recon, 2026-06-11)

Probed sessions across 4 projects and 5 Claude Code versions (2.1.143 → 2.1.167),
~15,000 events total. Read-only; no session files were modified.

### 1.1 Event types (union across all sessions)

| `type` | Count | Notes |
|---|---|---|
| `assistant` | 9,665 | signal |
| `user` | 5,674 | signal (but mostly tool_result carriers) |
| `ai-title` | 1,304 | signal — session title |
| `permission-mode` | 1,297 | ignore |
| `last-prompt` | 1,263 | ignore (duplicates user content) |
| `attachment` | 907 | ignore (deferred-tools deltas, system plumbing) |
| `agent-name` | 803 | ignore for v1 (see open question Q2) |
| `file-history-snapshot` | 693 | **signal — touched files** |
| `mode` | 451 | ignore; **only exists in v2.1.156+** (schema drift is real) |
| `system` | 311 | mostly `subtype:"turn_duration"`; also `subtype:"compact_boundary"` |
| `queue-operation` | 84 | ignore; **contains raw queued user input — see §8 privacy finding** |

New types appear between versions (`mode` arrived ~2.1.156; `agent-name` and
`queue-operation` only in some sessions). The `Unknown` catch-all variant is mandatory.

### 1.2 `user` / `assistant` envelope (fields verified present on every message event)

`uuid`, `parentUuid`, `type`, `timestamp` (ISO-8601), `sessionId`, `cwd`,
`gitBranch`, `version`, `isSidechain`, `message`. Frequently also:
`toolUseResult` (rich result object, p90 ≈ 5.7 KB, max ≈ 35 KB — **drop**),
`slug`, `sourceToolAssistantUUID`, `promptId`, `isMeta`, `isCompactSummary`.

`isSidechain` was `false` on all 15,339 message events observed — subagent
transcripts evidently no longer inline (see Q2).

### 1.3 `message` shapes

**user:** `{role: "user", content: string | Block[]}`. Content kinds observed:
`tool_result` (4,838 — dominant), `string` (plain prompts), `text` blocks, `image` blocks.

**assistant:** `{id, role, model, content: Block[], stop_reason, stop_details,
stop_sequence, usage, diagnostics, type}`. Content block types observed:
`text`, `thinking` (`{thinking, signature, type}`), `tool_use` (`{id, name, input, type}`).

**Block payload facts:**
- `tool_result`: `{tool_use_id, content: string | Block[], is_error?}` — content is a
  *string* 97% of the time but **can be an array** of text blocks. p50 174 B, max 24 KB.
- `image`: `{source: {type: "base64", media_type, data}}` — data up to 650 KB. **Drop, keep placeholder.**
- Longest lines in a file are `user` events carrying `toolUseResult` + `tool_result` (111 KB observed) — confirms compaction priority.

### 1.4 Other signal events

- `ai-title`: `{type, aiTitle, sessionId}` — multiple per session (title refined over time); **last wins**.
- `file-history-snapshot`: `{messageId, snapshot: {trackedFileBackups: {<repo-relative-path>: …}}}` —
  keys are literal file paths Claude touched. **Union of keys across the session = `files_touched`,
  no LLM needed.**
- `system` / `subtype:"compact_boundary"`: `{compactMetadata: {trigger, preTokens, …}, logicalParentUuid}` —
  marks in-session compaction. The following `user` event with `isCompactSummary: true` is an
  LLM-generated recap of content *already present earlier in the same file* → **drop summary, count boundary**.

### 1.5 Session file location

`~/.claude/projects/<path-encoded-project>/<session-uuid>.jsonl`. The directory name
encodes `/` as `-`, which is **ambiguous** for paths containing dashes
(`-home-kuweg-Projects-claude-gramm`). Never decode the directory name: take the
real project path from the `cwd` field of the first message event.

---

## 2. Ingest — Rust crate `parser/`

`lib.rs` holds all logic (PyO3-ready); `main.rs` is a thin binary:
`engram-parse <session.jsonl> [--redact]` → compacted JSON on stdout, warnings on stderr,
exit 0 on success, non-zero on unreadable file / zero messages.

**Tolerant parsing rules (mandatory):**
- `#[serde(tag = "type")]` enum with `#[serde(other)] Unknown` catch-all; every field beyond
  `type` is `Option<T>` or defaulted.
- A line that fails to deserialize: skip, count, log line number to stderr. Never panic.
- `message.content` is an untagged enum `String | Vec<Block>`; `Block` itself has an
  unknown-type fallback. `tool_result.content` likewise `String | Vec<Block>`.

**Compaction rules:**
- Keep: user prose (string content + `text` blocks), assistant `text` blocks,
  `tool_use` name + extracted key arg, last `aiTitle`, union of `trackedFileBackups` keys,
  envelope metadata from first message event.
- Drop: `tool_result` bodies, `toolUseResult`, `thinking` blocks (Q3), `image` data
  (emit `[image image/png 110KB]` placeholder), events with `isMeta: true`,
  `isCompactSummary` recaps, `usage`/`diagnostics`, all non-signal event types.
- Truncate: user/assistant text at 4,000 chars (append `…[truncated]`), tool key-arg at 300 chars.
- Tool key-arg extraction map: `Bash→command`, `Read/Edit/Write/NotebookEdit→file_path`,
  `Agent/Task→description`, `WebFetch/WebSearch→url|query`, `Grep/Glob→pattern`,
  `Skill→skill`; fallback: first string value in `input`, else `""`.

### 2.1 Compacted-JSON contract (versioned; the Rust↔Python boundary)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "engram compacted session",
  "type": "object",
  "required": ["schema_version", "session_id", "events", "stats"],
  "properties": {
    "schema_version": { "const": 1 },
    "session_id":     { "type": "string" },
    "project_path":   { "type": ["string", "null"] },
    "git_branch":     { "type": ["string", "null"] },
    "cc_version":     { "type": ["string", "null"] },
    "title":          { "type": ["string", "null"] },
    "started_at":     { "type": ["string", "null"], "format": "date-time" },
    "ended_at":       { "type": ["string", "null"], "format": "date-time" },
    "files_touched":  { "type": "array", "items": { "type": "string" } },
    "stats": {
      "type": "object",
      "required": ["total_lines", "skipped_lines", "user_messages",
                   "assistant_messages", "tool_calls", "compact_boundaries"],
      "properties": {
        "total_lines":        { "type": "integer" },
        "skipped_lines":      { "type": "integer" },
        "user_messages":      { "type": "integer" },
        "assistant_messages": { "type": "integer" },
        "tool_calls":         { "type": "integer" },
        "compact_boundaries": { "type": "integer" }
      }
    },
    "events": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["kind"],
        "properties": {
          "kind": { "enum": ["user", "assistant", "tool"] },
          "ts":   { "type": ["string", "null"] },
          "text": { "type": "string" },
          "name": { "type": "string" },
          "arg":  { "type": "string" }
        }
      }
    }
  }
}
```

`user`/`assistant` events carry `text`; `tool` events carry `name` + `arg`.
Any breaking change to this shape bumps `schema_version`; the Python side refuses
versions it doesn't know.

---

## 3. Distill — Python `pipeline/`

Runs `engram-parse`, validates `schema_version`, sends the compacted transcript to
the Anthropic API. Model: `claude-haiku-4-5-20251001` (configurable). Output forced
to strict JSON (tool-use/structured-output mode, not free text).

### 3.1 Output schema

```json
{
  "title": "string — prefer the transcript's ai-title verbatim when present",
  "tldr": "2-4 sentences, past tense, concrete",
  "session_type": "debugging | feature | config | research | other",
  "decisions": [{ "what": "string", "why": "string" }],
  "problems_solved": [{ "problem": "string", "solution": "string" }],
  "open_threads": ["string — unfinished work, deferred items, known bugs"],
  "entities": ["string — technologies, libraries, project names, concepts"]
}
```

> **Flagged deviation:** added `other` to `session_type` — forcing a 4-way choice on
> mixed sessions produces garbage classifications. Remove if you disagree.

`files_touched` comes from Ingest (ground truth), not the LLM. The LLM may *add*
paths it saw in tool args; Weave unions them with Ingest's list marked authoritative.

### 3.2 Prompt draft

```
You are distilling a Claude Code engineering session into structured notes
for a personal knowledge base.

Session metadata: project={project_path}, branch={git_branch}, date={started_at},
suggested title: {title or "none"}.

Transcript (compacted; tool outputs removed):
{events rendered as "USER: …", "ASSISTANT: …", "TOOL Bash: cargo test"}

Extract JSON per the provided schema. Rules:
- title: use the suggested title if it accurately describes the session; otherwise write one (≤60 chars, kebab-or-plain).
- tldr: what was actually accomplished, not what was attempted.
- decisions: only deliberate choices with alternatives (architecture, library, approach). Not routine actions.
- open_threads: anything explicitly deferred, TODO'd, or left broken.
- entities: proper nouns a knowledge graph should link — projects, tools, libraries, services, named concepts. No generic words ("code", "file", "bug").
- Empty arrays are fine. Never invent content.
```

### 3.3 Chunking (sessions exceeding context)

Compaction gives ~10–30× reduction, but the 28 MB outlier session will still overflow.
Map-reduce: split `events` into chunks of ≤150k estimated tokens (chars/4) on user-message
boundaries → distill each chunk with the same schema → reduce step merges: concatenate
arrays, dedupe near-identical items, re-summarize `tldr`s into one, last chunk's title
preference wins. Single-chunk sessions skip the reduce call.

---

## 4. Weave — note rendering & graph maintenance

### 4.1 Note template

Path: `<vault>/Sessions/YYYY-MM-DD <slug>.md` (slug from title, ≤50 chars; collision → append `-2`).

```markdown
---
date: 2026-06-11
project: yapoc
session_id: fd8e76a8-41ba-4587-8191-d8618bf13072
type: debugging
tags: [session]
engram_version: 1
---

# fix-execute-dag-silent-error

**Project:** [[yapoc]] · **Branch:** main · **Type:** debugging

## TL;DR
…

## Decisions
- **Chose X over Y** — because …

## Problems solved
- **problem** — solution

## Open threads
- [ ] …

## Touched
- [[Concepts/asyncio|asyncio]], [[Concepts/DAG|DAG]]
- `app/agents/base/runner.py`, `app/agents/master/agent.py`
```

File paths render as inline code, not wikilinks (one note per source file would
flood the graph). Entities render as wikilinks **only after normalization** (§4.2).
Project MOC notes under `Projects/` are Dataview queries over frontmatter — the
pipeline writes session notes and `Concepts/` stubs only.

Idempotency: note path is derived from `session_id` via the state DB — re-processing
rewrites the same file in place (frontmatter `session_id` is the join key; never
create a second note for a known session).

### 4.2 Entity normalization (load-bearing)

`entities.yaml`:

```yaml
entities:
  - name: yapoc
    type: project
    aliases: [YAPOC, yapoc-agents]
  - name: asyncio
    type: library
    aliases: [async-io, python asyncio]
```

Algorithm, per LLM-extracted entity string:
1. **Normalize key:** trim, lowercase, collapse whitespace, strip surrounding punctuation.
2. **Exact match** against every canonical name and alias (also normalized) → use canonical name, render `[[Concepts/<name>|<original casing>]]` (projects → `[[<name>]]`).
3. **No match →** insert into `pending_entities` (state DB) with session provenance and count; render as *plain text* in the note. No auto-created links, no fuzzy auto-merge — fuzzy matching (difflib ≥ 0.85) only *suggests* candidates during review.
4. **`engram entities review`:** interactive CLI lists pending entities by frequency; approve (append to `entities.yaml` + create `Concepts/<name>.md` stub + re-render affected notes), alias-to-existing, or reject (blacklist table so it never resurfaces).

### 4.3 State DB (SQLite, `~/.local/share/engram/state.db`)

```sql
CREATE TABLE sessions (
  session_id  TEXT PRIMARY KEY,
  jsonl_path  TEXT NOT NULL,
  project     TEXT,
  mtime       INTEGER NOT NULL,        -- of jsonl at last processing
  size        INTEGER NOT NULL,
  status      TEXT NOT NULL CHECK (status IN
              ('pending','compacted','distilled','woven','error')),
  note_path   TEXT,
  schema_version INTEGER,
  error       TEXT,
  processed_at TEXT
);
CREATE TABLE pending_entities (
  name        TEXT PRIMARY KEY,        -- normalized key
  display     TEXT,
  count       INTEGER DEFAULT 1,
  first_session TEXT,
  status      TEXT DEFAULT 'pending' CHECK (status IN ('pending','approved','aliased','rejected'))
);
```

Re-run policy: reprocess when `mtime` or `size` changed, or `status != 'woven'`,
or `--force`. Everything else is skipped — that plus in-place note rewrite gives idempotency.

---

## 5. Configuration

Single file `~/.config/engram/config.toml` (path overridable via `ENGRAM_CONFIG`):

```toml
projects_dir = "~/.claude/projects"
vault_path   = "~/Documents/vault"
model        = "claude-haiku-4-5-20251001"
entities_file = "~/Projects/engram/entities.yaml"
state_db     = "~/.local/share/engram/state.db"
redact       = true
max_text_chars = 4000
```

API key from `ANTHROPIC_API_KEY` env only — never in config or DB.

---

## 6. Trigger — SessionEnd hook + backfill

`~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionEnd": [
      { "hooks": [ { "type": "command",
          "command": "systemd-run --user --collect ~/.local/bin/engram process --hook" } ] }
    ]
  }
}
```

The hook receives JSON on stdin (`session_id`, `transcript_path`, `cwd`, …);
`engram process --hook` reads it, enqueues, and exits immediately —
`systemd-run` detaches the real work so the hook never blocks Claude Code shutdown
(fallback if systemd unavailable: `setsid … &`). `engram backfill` walks
`projects_dir`, upserts every `*.jsonl` into the state DB, and processes pending
ones oldest-first (`--limit N` for testing).

---

## 7. Repo layout & build glue

As specified in the brief: `parser/` (Rust), `pipeline/` (Python, uv), `fixtures/`,
`entities.yaml`, `Makefile` (`build` → cargo build --release + uv sync; `test` →
cargo test + clippy -D warnings + pytest; `backfill`, `process`, `dry-run`).
Note: this repo is currently `claude-gramm` with an exploratory hand-rolled JSON
tokenizer/parser in `src/` (learning kata) — see Q6 for migration.

---

## 8. Privacy & security

- Session content goes to the Anthropic API and nowhere else. No telemetry, no logging
  of transcript content (stderr logs carry line *numbers* and event *types* only).
- **Recon finding (real, verified):** a `queue-operation` event in the bloodwork session
  contains a literal sudo password typed into the prompt queue. Secrets *do* live in
  these files. Consequences:
  1. Engram never processes `queue-operation`/`last-prompt` events (already non-signal).
  2. **Flagged addition:** Ingest gets a `--redact` pass (on by default) over kept text:
     regexes for `password|passwd|token|secret|api[_-]?key|bearer` followed by a value,
     AWS/GitHub/OpenAI/Anthropic key shapes, long base64 runs → `[REDACTED]`. Imperfect
     by design; it lowers, not eliminates, leak risk to the summarization API.
  3. Fixtures are hand-sanitized; CI greps fixtures for key-shaped strings.
- DB and notes inherit vault/file permissions; nothing world-readable is created (0600 for state DB).

---

## 9. Implementation plan

**Phase 1 — Rust parser (`parser/`)**
Tolerant serde model → compactor → contract serializer → `--redact`.
*Verify:* `cargo test` green on fixtures (every event/block type + malformed + unknown-type lines);
clippy clean; run against all 23 real local sessions: zero panics, zero hard errors,
compacted output validates against the JSON Schema (`check-jsonschema`), spot-check
one session's output by eye; 28 MB session parses in < 5 s.

**Phase 2 — distill + weave with `--dry-run`**
Python package, subprocess boundary, schema_version gate, Anthropic call, chunking,
note renderer, entity normalization, state DB. `--dry-run` prints the note to stdout
and writes nothing.
*Verify:* pytest green against canned compacted JSON (no API in CI — record/replay the
LLM response); `engram process --dry-run <session>` on 3 real sessions produces sane
notes; run twice → second run no-ops (idempotency); a fake "new entity" lands in
`pending_entities` and renders as plain text.

**Phase 3 — hook + backfill + entity review**
SessionEnd hook, detached execution, `engram backfill`, `engram entities review`.
*Verify:* end a real Claude Code session → note exists in vault within 60 s and Claude Code
exit was not delayed; `backfill --limit 5` processes 5 oldest sessions and is re-runnable;
approve a pending entity → `entities.yaml` updated, stub created, affected note re-rendered
with the wikilink; graph view shows session notes clustered around project hubs.

Each phase ends with: update this document where reality diverged.

---

## 10. Open questions (with recommendations)

| # | Question | Recommendation |
|---|---|---|
| Q1 | `tool_result` bodies sometimes contain the only record of *what went wrong* (errors). Keep `is_error` flag as a one-line `TOOL … → ERROR` marker? | Yes — keep the flag only (zero bytes of body). Cheap, helps the LLM classify debugging sessions. |
| Q2 | `isSidechain` is false on 100% of events; `agent-name` events suggest subagents, but their transcripts aren't inline. Where are they? | Ignore for v1. Main transcript already contains Task tool args + summaries. Revisit if notes feel hollow for agent-heavy sessions. |
| Q3 | Include assistant `thinking` blocks in compacted output? They contain reasoning behind decisions but are bulky and rambling. | Drop in v1. `text` blocks state final decisions; thinking would double payload for marginal gain. Schema has room to add later (`kind:"thinking"`). |
| Q4 | Are in-session compact summaries (`isCompactSummary`) ever the *only* record (e.g., session resumed from another file)? | Drop them in v1; `--keep-compact-summaries` escape hatch if cross-session resumes prove lossy. |
| Q5 | `ai-title` vs `agent-name` for titles — yapoc sessions have both, sometimes differing. | Prefer last `ai-title`; fall back to last `agent-name`; else LLM writes one. |
| Q6 | This repo is `claude-gramm` with a learning-kata JSON parser in `src/`. Adopt the `engram/` layout here, or fresh repo? | Restructure this repo in place (git mv kata to `experiments/json-kata/`); keep history, rename repo to `engram`. |
| Q7 | The found sudo password predates engram. | Out of engram's scope, but: rotate that password, and consider pruning old sessions. |
| Q8 | Haiku quality on `decisions[]` extraction is unproven. | Build with model configurable; Phase 2 verification includes one side-by-side Haiku vs Sonnet comparison on the same session. |

---

## 11. Fixtures

`fixtures/events.jsonl` — 18 hand-sanitized lines covering every observed event type and
content-block shape (string/blocks/tool_result-string/tool_result-array/image/thinking/
tool_use/compact-boundary/compact-summary), plus `fixtures/malformed.jsonl` (truncated JSON,
empty line, unknown `type`) and `fixtures/compacted.sample.json` (a hand-written document
conforming to §2.1, used by Python tests). All UUIDs, paths, and content are fabricated;
no real session text is committed.
