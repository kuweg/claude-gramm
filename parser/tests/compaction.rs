//! Behavior tests for the engram Ingest compactor (DESIGN §2).
//! Each test drives `compact_session` and inspects the serialized §2.1 contract.

use engram_parser::compact_session;
use serde_json::{json, Value};

/// Compact one or more raw JSONL lines and return the session as a JSON Value.
fn compact(lines: &[&str]) -> Value {
    let input = lines.join("\n");
    let out = compact_session(&input, false);
    serde_json::to_value(&out.session).expect("session serializes")
}

fn events(v: &Value) -> &Vec<Value> {
    v["events"].as_array().expect("events array")
}

#[test]
fn user_string_content_becomes_user_event() {
    let v = compact(&[
        r#"{"type":"user","message":{"role":"user","content":"hello there"},"timestamp":"2026-06-01T10:00:00.000Z","cwd":"/p","sessionId":"s1","gitBranch":"main","version":"2.1.158"}"#,
    ]);
    assert_eq!(events(&v).len(), 1);
    assert_eq!(events(&v)[0]["kind"], "user");
    assert_eq!(events(&v)[0]["text"], "hello there");
    assert_eq!(v["stats"]["user_messages"], 1);
}

#[test]
fn user_text_block_becomes_user_event() {
    let v = compact(&[
        r#"{"type":"user","message":{"role":"user","content":[{"type":"text","text":"a block"}]},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}"#,
    ]);
    assert_eq!(events(&v).len(), 1);
    assert_eq!(events(&v)[0]["text"], "a block");
}

#[test]
fn user_with_only_tool_result_produces_no_event() {
    let v = compact(&[
        r#"{"type":"user","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"t1","content":"big output dropped"}]},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}"#,
    ]);
    assert_eq!(events(&v).len(), 0);
    assert_eq!(v["stats"]["user_messages"], 0);
}

#[test]
fn user_image_renders_placeholder_with_text() {
    let v = compact(&[
        r#"{"type":"user","message":{"role":"user","content":[{"type":"image","source":{"type":"base64","media_type":"image/png","data":"iVBORw0KGgoAAAANSUhEUg=="}},{"type":"text","text":"see this"}]},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}"#,
    ]);
    assert_eq!(events(&v).len(), 1);
    assert_eq!(events(&v)[0]["text"], "[image image/png 0KB] see this");
}

#[test]
fn assistant_drops_thinking_keeps_text_and_extracts_tool_use() {
    let v = compact(&[
        r#"{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"secret reasoning","signature":"x"},{"type":"text","text":"final answer"},{"type":"tool_use","id":"t1","name":"Read","input":{"file_path":"/a/b.rs"}}]},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}"#,
    ]);
    let e = events(&v);
    assert_eq!(e.len(), 2, "text event + tool event, thinking dropped");
    assert_eq!(e[0]["kind"], "assistant");
    assert_eq!(e[0]["text"], "final answer");
    assert_eq!(e[1]["kind"], "tool");
    assert_eq!(e[1]["name"], "Read");
    assert_eq!(e[1]["arg"], "/a/b.rs");
    assert_eq!(v["stats"]["assistant_messages"], 1);
    assert_eq!(v["stats"]["tool_calls"], 1);
}

#[test]
fn tool_arg_extraction_per_tool() {
    let cases = [
        (r#"{"name":"Bash","input":{"command":"cargo test","description":"x"}}"#, "Bash", "cargo test"),
        (r#"{"name":"Write","input":{"file_path":"/x.rs","content":"y"}}"#, "Write", "/x.rs"),
        (r#"{"name":"Agent","input":{"description":"do a thing"}}"#, "Agent", "do a thing"),
        (r#"{"name":"Grep","input":{"pattern":"TODO"}}"#, "Grep", "TODO"),
        (r#"{"name":"WebFetch","input":{"url":"http://x"}}"#, "WebFetch", "http://x"),
        (r#"{"name":"Skill","input":{"skill":"brainstorming"}}"#, "Skill", "brainstorming"),
        (r#"{"name":"MysteryTool","input":{"foo":"firststring"}}"#, "MysteryTool", "firststring"),
    ];
    for (block, name, arg) in cases {
        // splice the block's inner fields (sans outer braces) after the id field
        let inner = &block[1..block.len() - 1];
        let full = format!(
            r#"{{"type":"assistant","message":{{"role":"assistant","content":[{{"type":"tool_use","id":"t",{inner}}}]}},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}}"#
        );
        let v = compact(&[&full]);
        let e = events(&v);
        assert_eq!(e[0]["name"], name);
        assert_eq!(e[0]["arg"], arg, "arg for {name}");
    }
}

#[test]
fn last_ai_title_wins() {
    let v = compact(&[
        r#"{"type":"ai-title","aiTitle":"first","sessionId":"s1"}"#,
        r#"{"type":"ai-title","aiTitle":"second","sessionId":"s1"}"#,
    ]);
    assert_eq!(v["title"], "second");
}

#[test]
fn agent_name_is_title_fallback_when_no_ai_title() {
    let v = compact(&[
        r#"{"type":"agent-name","agentName":"helper-bot","sessionId":"s1"}"#,
    ]);
    assert_eq!(v["title"], "helper-bot");
}

#[test]
fn files_touched_is_sorted_union_of_snapshot_keys() {
    let v = compact(&[
        r#"{"type":"file-history-snapshot","snapshot":{"trackedFileBackups":{"src/z.rs":{},"src/a.rs":{}}}}"#,
        r#"{"type":"file-history-snapshot","snapshot":{"trackedFileBackups":{"src/a.rs":{},"src/m.rs":{}}}}"#,
    ]);
    assert_eq!(v["files_touched"], json!(["src/a.rs", "src/m.rs", "src/z.rs"]));
}

#[test]
fn compact_boundary_counted_summary_dropped() {
    let v = compact(&[
        r#"{"type":"system","subtype":"compact_boundary","compactMetadata":{"trigger":"auto"},"timestamp":"2026-06-01T11:00:00.000Z","sessionId":"s1"}"#,
        r#"{"type":"user","isCompactSummary":true,"message":{"role":"user","content":"recap of earlier"},"timestamp":"2026-06-01T11:00:01.000Z","sessionId":"s1"}"#,
    ]);
    assert_eq!(v["stats"]["compact_boundaries"], 1);
    assert_eq!(events(&v).len(), 0, "compact summary dropped");
    assert_eq!(v["stats"]["user_messages"], 0);
}

#[test]
fn is_meta_events_dropped() {
    let v = compact(&[
        r#"{"type":"user","isMeta":true,"message":{"role":"user","content":"meta noise"},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}"#,
    ]);
    assert_eq!(events(&v).len(), 0);
}

#[test]
fn malformed_lines_skipped_and_counted_blank_not_counted() {
    let v = compact(&[
        r#"{"type":"user","message":{"role":"user","content":"truncated"#, // invalid JSON
        "", // blank line — skipped, NOT counted
        r#"{"no_type_field":true}"#, // valid JSON, no type tag → skip + count
        r#"{"type":"some-future-type","x":1}"#, // unknown type → ignored, not skipped
        r#"{"type":"user","message":{"role":"user","content":"ok"},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}"#,
    ]);
    assert_eq!(v["stats"]["total_lines"], 5);
    assert_eq!(v["stats"]["skipped_lines"], 2);
    assert_eq!(events(&v).len(), 1);
}

#[test]
fn metadata_taken_from_first_message_event() {
    let v = compact(&[
        r#"{"type":"permission-mode","permissionMode":"default"}"#,
        r#"{"type":"user","message":{"role":"user","content":"hi"},"timestamp":"2026-06-01T10:00:00.000Z","cwd":"/home/user/projects/demo","sessionId":"sess-1","gitBranch":"feature","version":"2.1.158"}"#,
    ]);
    assert_eq!(v["session_id"], "sess-1");
    assert_eq!(v["project_path"], "/home/user/projects/demo");
    assert_eq!(v["git_branch"], "feature");
    assert_eq!(v["cc_version"], "2.1.158");
}

#[test]
fn started_and_ended_at_span_kept_events() {
    let v = compact(&[
        r#"{"type":"user","message":{"role":"user","content":"first"},"timestamp":"2026-06-01T10:00:01.000Z","sessionId":"s1"}"#,
        r#"{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"last"}]},"timestamp":"2026-06-01T10:00:30.000Z","sessionId":"s1"}"#,
    ]);
    assert_eq!(v["started_at"], "2026-06-01T10:00:01.000Z");
    assert_eq!(v["ended_at"], "2026-06-01T10:00:30.000Z");
}

#[test]
fn long_text_truncated_at_4000_chars() {
    let big = "x".repeat(5000);
    let line = format!(
        r#"{{"type":"user","message":{{"role":"user","content":"{big}"}},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}}"#
    );
    let v = compact(&[&line]);
    let text = events(&v)[0]["text"].as_str().unwrap();
    assert!(text.ends_with("…[truncated]"));
    assert_eq!(text.chars().count(), 4000 + "…[truncated]".chars().count());
}

#[test]
fn long_tool_arg_truncated_at_300_chars() {
    let big = "y".repeat(500);
    let line = format!(
        r#"{{"type":"assistant","message":{{"role":"assistant","content":[{{"type":"tool_use","id":"t","name":"Bash","input":{{"command":"{big}"}}}}]}},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}}"#
    );
    let v = compact(&[&line]);
    let arg = events(&v)[0]["arg"].as_str().unwrap();
    assert!(arg.ends_with("…[truncated]"));
    assert_eq!(arg.chars().count(), 300 + "…[truncated]".chars().count());
}

#[test]
fn schema_version_is_one() {
    let v = compact(&[r#"{"type":"ai-title","aiTitle":"t","sessionId":"s1"}"#]);
    assert_eq!(v["schema_version"], 1);
}

#[test]
fn redaction_removes_secret_values_when_enabled() {
    let input = r#"{"type":"user","message":{"role":"user","content":"my password: hunter2 and token=ghp_abcdefghijklmnopqrstuvwxyz0123456789"},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}"#;
    let out = compact_session(input, true);
    let v = serde_json::to_value(&out.session).unwrap();
    let text = v["events"][0]["text"].as_str().unwrap();
    assert!(text.contains("[REDACTED]"), "got: {text}");
    assert!(!text.contains("hunter2"), "secret leaked: {text}");
    assert!(!text.contains("ghp_abcdefghijklmnopqrstuvwxyz0123456789"));
}

#[test]
fn redaction_does_not_eat_long_file_paths() {
    // Regression: a long Unix path (slashes + alnum) must not look like a base64 secret.
    let path = "/home/kuweg/Projects/yapoc/app/backend/telegram_bot.py";
    let input = format!(
        r#"{{"type":"assistant","message":{{"role":"assistant","content":[{{"type":"tool_use","id":"t","name":"Read","input":{{"file_path":"{path}"}}}}]}},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}}"#
    );
    let out = compact_session(&input, true);
    let v = serde_json::to_value(&out.session).unwrap();
    assert_eq!(v["events"][0]["arg"], path, "file path must survive redaction");
}

#[test]
fn redaction_still_catches_bare_base64_token() {
    let secret = "abcDEF1234567890abcDEF1234567890abcDEF1234567890XY"; // 50 chars, no slashes
    let input = format!(
        r#"{{"type":"user","message":{{"role":"user","content":"here is the blob {secret} ok"}},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}}"#
    );
    let out = compact_session(&input, true);
    let v = serde_json::to_value(&out.session).unwrap();
    let text = v["events"][0]["text"].as_str().unwrap();
    assert!(!text.contains(secret), "bare base64 token should be redacted: {text}");
    assert!(text.contains("[REDACTED]"));
}

#[test]
fn redaction_off_by_default_keeps_text() {
    let v = compact(&[
        r#"{"type":"user","message":{"role":"user","content":"password: hunter2"},"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s1"}"#,
    ]);
    assert_eq!(events(&v)[0]["text"], "password: hunter2");
}
