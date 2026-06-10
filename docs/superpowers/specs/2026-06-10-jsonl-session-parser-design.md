# claude-gramm: JSONL Session Parser (Step 1) — Design

**Date:** 2026-06-10
**Status:** Approved
**Scope:** First step of a larger project that turns `~/.claude/projects` session
transcripts into an Obsidian vault with graph visualization. This spec covers only
the parser. Teaching context: the user is learning Rust; work is split between
Claude (scaffolding, serde-heavy parts) and the user (fold loop, CLI shell, tests).

## Goal

A CLI binary that takes the path to one Claude Code session transcript
(`.jsonl`, one JSON object per line) and prints a cleaned, session-level JSON
summary to stdout.

The eventual Obsidian graph shows **sessions and topics** (one note per session,
linked to project/topic notes), so the parser extracts session metadata and
conversation text only — not tool calls, file snapshots, or the message DAG.

## Input format (observed)

Each line is a JSON object with a `type` discriminator. Observed types in the
sample file (`fd8e76a8-…jsonl`, 780 lines): `assistant` (335), `user` (217),
`ai-title` (46), `permission-mode` (45), `last-prompt` (44), `attachment` (41),
`agent-name` (25), `file-history-snapshot` (19), `system` (4), `queue-operation` (4).

Key facts:

- `user`/`assistant` records carry a `message` object (Anthropic API shape) plus
  envelope fields: `uuid`, `parentUuid`, `timestamp`, `sessionId`, `cwd`,
  `gitBranch`, `version`, `isSidechain`.
- `message.content` is **either** a plain string **or** an array of content
  blocks (`text`, `tool_use`, `tool_result`, `thinking`, …).
- `ai-title` records carry the session title; titles are refined over time, so
  the **last one wins**.
- Session metadata (`sessionId`, `cwd`, `gitBranch`) is repeated on message
  records; lift it from the first message seen.
- New record types may appear in future Claude Code versions; the parser must
  not break on them.

## Architecture

Binary crate, two files:

- `src/parser.rs` — data types + `parse_session(reader) -> Result<Session>`.
  Takes anything readable; no knowledge of CLI args or stdout.
- `src/main.rs` — thin shell: path from `std::env::args` (no clap), open file,
  call parser, pretty-print JSON to stdout, errors/warnings to stderr.

## Data model

### Input side (mirrors the file format, derives `Deserialize`)

```rust
#[serde(tag = "type")]
enum Record {
    #[serde(rename = "user")]      User(MessageRecord),
    #[serde(rename = "assistant")] Assistant(MessageRecord),
    #[serde(rename = "ai-title")]  AiTitle { title: String },
    #[serde(other)]                Other,   // catch-all: known-but-ignored AND unknown types
}

struct MessageRecord {
    message: ApiMessage,        // { role, content }
    timestamp: Option<String>,  // ISO-8601, kept as string (no chrono yet)
    session_id: Option<String>,
    cwd: Option<String>,
    git_branch: Option<String>,
    is_sidechain: Option<bool>,
}

#[serde(untagged)]
enum MessageContent {
    Text(String),
    Blocks(Vec<ContentBlock>),
}
```

From block arrays, only `text` blocks are kept; `tool_use`, `tool_result`,
`thinking`, and anything else are skipped. Note: `#[serde(other)]` on a unit
variant requires the enum to ignore unknown variants' payloads — if serde's
`other` limitation bites (it only works on unit variants with internally/
adjacently tagged enums), fall back to a manual two-pass parse: peek at `type`
via a small helper struct, then parse fully only for known types.

### Output side (mirrors what the vault needs, derives `Serialize`)

```rust
struct Session {
    session_id: String,
    title: Option<String>,
    project: Option<String>,     // cwd
    git_branch: Option<String>,
    started_at: Option<String>,
    ended_at: Option<String>,
    messages: Vec<Message>,
}

struct Message {
    role: Role,                  // User | Assistant
    text: String,
    timestamp: Option<String>,
}
```

Input and output types are deliberately separate so each can evolve
independently. Messages whose extracted text is empty (e.g. an assistant turn
that was only tool calls) are dropped. Sidechain messages (`isSidechain: true`)
are excluded — they are subagent traffic, not the user's conversation.

## Data flow

`BufReader` over the file → per line `serde_json::from_str::<Record>` → fold
into `Session` (first message seen sets metadata; last `ai-title` sets title;
first/last message timestamps set `started_at`/`ended_at`) →
`serde_json::to_string_pretty` → stdout.

## Error handling

Two tiers:

- **Per-line (lenient):** a line that fails to deserialize is skipped; the
  parser counts skipped lines and reports the count on stderr. One bad line
  must not kill the run.
- **Per-file (strict):** unreadable file, or a file yielding zero messages →
  hard error, non-zero exit.

App-level errors use `anyhow` (`Result` + `?` throughout `main`).

## Dependencies

`serde` (features `derive`), `serde_json`, `anyhow`. Nothing else.

## Testing

- **Unit tests** in `parser.rs` with inline JSON strings:
  - string-content message parses
  - block-content message parses, keeps only text blocks
  - unknown record type lands in `Other` without error
  - malformed line is skipped and counted, not fatal
  - last `ai-title` wins
  - sidechain messages excluded
- **Integration test** parsing the real sample file, asserting expected
  message counts and that metadata fields are populated.

TDD order: write each test first, then implement.

## Division of labor

- **Claude writes:** serde enum skeleton (tagged + untagged attributes), the
  first unit test, and any serde fallback machinery if needed.
- **User writes (with review):** the fold loop building `Session`, `main.rs`,
  remaining tests.

## Out of scope (later steps)

Directory walking of `~/.claude/projects`, Markdown/Obsidian note generation,
topic extraction, graph links, chrono date handling, clap CLI.
