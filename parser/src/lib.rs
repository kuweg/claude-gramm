//! engram Ingest — tolerant Claude Code JSONL parser + compactor (DESIGN §2).
//!
//! `compact_session` reads raw JSONL session text and produces the versioned
//! §2.1 compacted-session contract. Parsing is deliberately tolerant: unknown
//! event/block types fall through to `Unknown`, and any line that fails to
//! deserialize is skipped and counted rather than aborting the run.

use std::collections::{BTreeMap, BTreeSet};

use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::Value;

const MAX_TEXT_CHARS: usize = 4000;
const MAX_ARG_CHARS: usize = 300;
const TRUNCATION_SUFFIX: &str = "…[truncated]";

// ---------------------------------------------------------------------------
// Output contract (§2.1)
// ---------------------------------------------------------------------------

/// The §2.1 compacted-session contract. Field order mirrors the JSON Schema.
#[derive(Debug, Serialize, Default)]
pub struct CompactedSession {
    pub schema_version: u32,
    pub session_id: String,
    pub project_path: Option<String>,
    pub git_branch: Option<String>,
    pub cc_version: Option<String>,
    pub title: Option<String>,
    pub started_at: Option<String>,
    pub ended_at: Option<String>,
    pub files_touched: Vec<String>,
    pub stats: Stats,
    pub events: Vec<Event>,
}

#[derive(Debug, Serialize, Default)]
pub struct Stats {
    pub total_lines: u64,
    pub skipped_lines: u64,
    pub user_messages: u64,
    pub assistant_messages: u64,
    pub tool_calls: u64,
    pub compact_boundaries: u64,
}

/// A compacted event. `user`/`assistant` carry `text`; `tool` carries `name`+`arg`.
#[derive(Debug, Serialize)]
pub struct Event {
    pub kind: &'static str,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ts: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub arg: Option<String>,
}

/// Result of compaction: the session plus human-readable warnings.
pub struct Compacted {
    pub session: CompactedSession,
    pub warnings: Vec<String>,
}

// ---------------------------------------------------------------------------
// Tolerant input model
// ---------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
enum RawEvent {
    #[serde(rename = "user")]
    User(Box<MessageEvent>),
    #[serde(rename = "assistant")]
    Assistant(Box<MessageEvent>),
    #[serde(rename = "ai-title")]
    AiTitle(AiTitleEvent),
    #[serde(rename = "agent-name")]
    AgentName(AgentNameEvent),
    #[serde(rename = "file-history-snapshot")]
    FileHistorySnapshot(FileHistoryEvent),
    #[serde(rename = "system")]
    System(SystemEvent),
    /// Any other event type (`permission-mode`, `mode`, `last-prompt`,
    /// `attachment`, `queue-operation`, future types …) — ignored.
    #[serde(other)]
    Unknown,
}

#[derive(Debug, Deserialize)]
struct MessageEvent {
    #[serde(default)]
    timestamp: Option<String>,
    #[serde(default)]
    cwd: Option<String>,
    #[serde(default, rename = "gitBranch")]
    git_branch: Option<String>,
    #[serde(default)]
    version: Option<String>,
    #[serde(default, rename = "sessionId")]
    session_id: Option<String>,
    #[serde(default, rename = "isMeta")]
    is_meta: bool,
    #[serde(default, rename = "isCompactSummary")]
    is_compact_summary: bool,
    #[serde(default)]
    message: Option<Message>,
}

#[derive(Debug, Deserialize)]
struct Message {
    content: Content,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
enum Content {
    Text(String),
    Blocks(Vec<Block>),
}

#[derive(Debug, Deserialize)]
#[serde(tag = "type")]
enum Block {
    #[serde(rename = "text")]
    Text {
        #[serde(default)]
        text: String,
    },
    #[serde(rename = "tool_use")]
    ToolUse {
        #[serde(default)]
        name: String,
        #[serde(default)]
        input: Value,
    },
    #[serde(rename = "image")]
    Image {
        #[serde(default)]
        source: Option<ImageSource>,
    },
    /// `thinking`, `tool_result`, and any unknown block type — all dropped.
    #[serde(other)]
    Other,
}

#[derive(Debug, Deserialize)]
struct ImageSource {
    #[serde(default)]
    media_type: Option<String>,
    #[serde(default)]
    data: Option<String>,
}

#[derive(Debug, Deserialize)]
struct AiTitleEvent {
    #[serde(default, rename = "aiTitle")]
    ai_title: Option<String>,
}

#[derive(Debug, Deserialize)]
struct AgentNameEvent {
    #[serde(default, rename = "agentName")]
    agent_name: Option<String>,
}

#[derive(Debug, Deserialize)]
struct FileHistoryEvent {
    #[serde(default)]
    snapshot: Option<Snapshot>,
}

#[derive(Debug, Deserialize)]
struct Snapshot {
    #[serde(default, rename = "trackedFileBackups")]
    tracked_file_backups: BTreeMap<String, Value>,
}

#[derive(Debug, Deserialize)]
struct SystemEvent {
    #[serde(default)]
    subtype: Option<String>,
}

// ---------------------------------------------------------------------------
// Compaction
// ---------------------------------------------------------------------------

pub fn compact_session(input: &str, redact: bool) -> Compacted {
    let redactor = if redact { Some(Redactor::new()) } else { None };

    let mut session = CompactedSession {
        schema_version: 1,
        ..Default::default()
    };
    let mut warnings = Vec::new();
    let mut files: BTreeSet<String> = BTreeSet::new();
    let mut title_ai: Option<String> = None;
    let mut title_agent: Option<String> = None;
    let mut meta_captured = false;

    for (idx, line) in input.lines().enumerate() {
        session.stats.total_lines += 1;
        if line.trim().is_empty() {
            continue; // blank line: counted in total, but not a parse failure
        }

        let event: RawEvent = match serde_json::from_str(line) {
            Ok(ev) => ev,
            Err(_) => {
                session.stats.skipped_lines += 1;
                warnings.push(format!("line {}: skipped (failed to parse)", idx + 1));
                continue;
            }
        };

        match event {
            RawEvent::User(m) => {
                if !meta_captured {
                    capture_meta(&mut session, &m);
                    meta_captured = true;
                }
                handle_user(&m, &mut session, redactor.as_ref());
            }
            RawEvent::Assistant(m) => {
                if !meta_captured {
                    capture_meta(&mut session, &m);
                    meta_captured = true;
                }
                handle_assistant(&m, &mut session, redactor.as_ref());
            }
            RawEvent::AiTitle(t) => {
                if let Some(title) = t.ai_title {
                    title_ai = Some(title);
                }
            }
            RawEvent::AgentName(a) => {
                if let Some(name) = a.agent_name {
                    title_agent = Some(name);
                }
            }
            RawEvent::FileHistorySnapshot(f) => {
                if let Some(snap) = f.snapshot {
                    files.extend(snap.tracked_file_backups.into_keys());
                }
            }
            RawEvent::System(s) => {
                if s.subtype.as_deref() == Some("compact_boundary") {
                    session.stats.compact_boundaries += 1;
                }
            }
            RawEvent::Unknown => {}
        }
    }

    session.title = title_ai.or(title_agent);
    session.files_touched = files.into_iter().collect();
    (session.started_at, session.ended_at) = span(&session.events);

    Compacted { session, warnings }
}

fn capture_meta(session: &mut CompactedSession, m: &MessageEvent) {
    if let Some(sid) = &m.session_id {
        session.session_id = sid.clone();
    }
    session.project_path = m.cwd.clone();
    session.git_branch = m.git_branch.clone();
    session.cc_version = m.version.clone();
}

fn handle_user(m: &MessageEvent, session: &mut CompactedSession, redactor: Option<&Redactor>) {
    if m.is_meta || m.is_compact_summary {
        return;
    }
    let Some(message) = &m.message else { return };

    let text = match &message.content {
        Content::Text(s) => s.clone(),
        Content::Blocks(blocks) => {
            let parts: Vec<String> = blocks.iter().filter_map(render_user_block).collect();
            parts.join(" ")
        }
    };
    if text.is_empty() {
        return; // pure tool_result carrier — nothing to keep
    }

    session.stats.user_messages += 1;
    session.events.push(Event {
        kind: "user",
        ts: m.timestamp.clone(),
        text: Some(finalize_text(&text, redactor)),
        name: None,
        arg: None,
    });
}

fn render_user_block(block: &Block) -> Option<String> {
    match block {
        Block::Text { text } if !text.is_empty() => Some(text.clone()),
        Block::Image { source } => Some(image_placeholder(source.as_ref())),
        _ => None, // tool_result, thinking, tool_use, unknown
    }
}

fn handle_assistant(m: &MessageEvent, session: &mut CompactedSession, redactor: Option<&Redactor>) {
    if m.is_meta {
        return;
    }
    let Some(message) = &m.message else { return };

    session.stats.assistant_messages += 1;

    let blocks = match &message.content {
        Content::Blocks(blocks) => blocks.as_slice(),
        // A bare string on an assistant event is unusual but tolerated as text.
        Content::Text(s) => {
            if !s.is_empty() {
                session.events.push(Event {
                    kind: "assistant",
                    ts: m.timestamp.clone(),
                    text: Some(finalize_text(s, redactor)),
                    name: None,
                    arg: None,
                });
            }
            return;
        }
    };

    for block in blocks {
        match block {
            Block::Text { text } if !text.is_empty() => {
                session.events.push(Event {
                    kind: "assistant",
                    ts: m.timestamp.clone(),
                    text: Some(finalize_text(text, redactor)),
                    name: None,
                    arg: None,
                });
            }
            Block::ToolUse { name, input } => {
                session.stats.tool_calls += 1;
                let arg = extract_tool_arg(name, input);
                session.events.push(Event {
                    kind: "tool",
                    ts: m.timestamp.clone(),
                    text: None,
                    name: Some(name.clone()),
                    arg: Some(finalize_arg(&arg, redactor)),
                });
            }
            _ => {} // thinking, image, tool_result, unknown
        }
    }
}

/// DESIGN §2 tool key-arg extraction map.
fn extract_tool_arg(name: &str, input: &Value) -> String {
    let get = |key: &str| input.get(key).and_then(Value::as_str).map(str::to_owned);
    let arg = match name {
        "Bash" => get("command"),
        "Read" | "Edit" | "Write" | "NotebookEdit" => get("file_path"),
        "Agent" | "Task" => get("description"),
        "WebFetch" | "WebSearch" => get("url").or_else(|| get("query")),
        "Grep" | "Glob" => get("pattern"),
        "Skill" => get("skill"),
        _ => None,
    };
    arg.or_else(|| first_string_value(input))
        .unwrap_or_default()
}

fn first_string_value(input: &Value) -> Option<String> {
    input
        .as_object()?
        .values()
        .find_map(|v| v.as_str())
        .map(str::to_owned)
}

fn image_placeholder(source: Option<&ImageSource>) -> String {
    let media = source
        .and_then(|s| s.media_type.as_deref())
        .unwrap_or("application/octet-stream");
    let bytes = source
        .and_then(|s| s.data.as_deref())
        .map(base64_decoded_len)
        .unwrap_or(0);
    format!("[image {} {}KB]", media, bytes / 1024)
}

fn base64_decoded_len(data: &str) -> usize {
    let len = data.trim_end_matches('=').len();
    len * 3 / 4
}

/// First/last timestamp across kept events (file order is chronological; min/max
/// is used defensively in case it is not).
fn span(events: &[Event]) -> (Option<String>, Option<String>) {
    let mut min: Option<&str> = None;
    let mut max: Option<&str> = None;
    for ev in events {
        if let Some(ts) = ev.ts.as_deref() {
            if min.is_none_or(|m| ts < m) {
                min = Some(ts);
            }
            if max.is_none_or(|m| ts > m) {
                max = Some(ts);
            }
        }
    }
    (min.map(str::to_owned), max.map(str::to_owned))
}

fn finalize_text(text: &str, redactor: Option<&Redactor>) -> String {
    let redacted = match redactor {
        Some(r) => r.redact(text),
        None => text.to_owned(),
    };
    truncate(&redacted, MAX_TEXT_CHARS)
}

fn finalize_arg(arg: &str, redactor: Option<&Redactor>) -> String {
    let redacted = match redactor {
        Some(r) => r.redact(arg),
        None => arg.to_owned(),
    };
    truncate(&redacted, MAX_ARG_CHARS)
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        return s.to_owned();
    }
    let head: String = s.chars().take(max).collect();
    format!("{head}{TRUNCATION_SUFFIX}")
}

// ---------------------------------------------------------------------------
// Redaction (§8) — imperfect by design; lowers, not eliminates, leak risk.
// ---------------------------------------------------------------------------

struct Redactor {
    keyword: Regex,
    shapes: Vec<Regex>,
}

impl Redactor {
    fn new() -> Self {
        let keyword =
            Regex::new(r"(?i)\b(password|passwd|token|secret|api[_-]?key|bearer)\b\s*[:=]?\s*\S+")
                .expect("valid keyword regex");
        let shapes = [
            r"gh[posru]_[A-Za-z0-9]{20,}",         // GitHub tokens
            r"AKIA[0-9A-Z]{16}",                   // AWS access key id
            r"sk-[A-Za-z0-9_\-]{20,}",             // OpenAI / Anthropic style
            // Long contiguous base64-ish run. Deliberately excludes '/' so that
            // ordinary Unix file paths are not mistaken for secrets.
            r"\b[A-Za-z0-9+]{40,}={0,2}",
        ]
        .iter()
        .map(|p| Regex::new(p).expect("valid shape regex"))
        .collect();
        Self { keyword, shapes }
    }

    fn redact(&self, text: &str) -> String {
        let mut out = self
            .keyword
            .replace_all(text, |caps: &regex::Captures| format!("{} [REDACTED]", &caps[1]))
            .into_owned();
        for re in &self.shapes {
            out = re.replace_all(&out, "[REDACTED]").into_owned();
        }
        out
    }
}
