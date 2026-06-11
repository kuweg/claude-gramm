//! CLI contract for the `engram-parse` binary (DESIGN §2):
//! `engram-parse <session.jsonl> [--redact]` → compacted JSON on stdout,
//! warnings on stderr, exit 0 on success, non-zero on unreadable / zero-message.

use std::process::Command;

fn bin() -> Command {
    Command::new(env!("CARGO_BIN_EXE_engram-parse"))
}

fn fixture(name: &str) -> String {
    format!("{}/../fixtures/{}", env!("CARGO_MANIFEST_DIR"), name)
}

#[test]
fn good_session_exits_zero_with_json_stdout() {
    let out = bin().arg(fixture("events.jsonl")).output().unwrap();
    assert!(out.status.success(), "stderr: {}", String::from_utf8_lossy(&out.stderr));
    let v: serde_json::Value = serde_json::from_slice(&out.stdout).expect("stdout is JSON");
    assert_eq!(v["schema_version"], 1);
    assert_eq!(v["session_id"], "00000000-0000-4000-8000-000000000001");
}

#[test]
fn unreadable_file_exits_nonzero() {
    let out = bin().arg("/no/such/file.jsonl").output().unwrap();
    assert!(!out.status.success());
    assert!(out.stdout.is_empty(), "no JSON on error");
}

#[test]
fn no_path_argument_exits_nonzero() {
    let out = bin().output().unwrap();
    assert!(!out.status.success());
}

#[test]
fn zero_message_session_exits_nonzero() {
    // A file with only non-message events has no user/assistant messages.
    let tmp = std::env::temp_dir().join("engram_zero_msg_test.jsonl");
    std::fs::write(&tmp, "{\"type\":\"ai-title\",\"aiTitle\":\"x\",\"sessionId\":\"s\"}\n").unwrap();
    let out = bin().arg(&tmp).output().unwrap();
    let _ = std::fs::remove_file(&tmp);
    assert!(!out.status.success(), "zero-message session should be an error");
}

#[test]
fn redact_flag_scrubs_secrets() {
    let tmp = std::env::temp_dir().join("engram_redact_test.jsonl");
    std::fs::write(
        &tmp,
        "{\"type\":\"user\",\"message\":{\"role\":\"user\",\"content\":\"password: hunter2xyz\"},\"timestamp\":\"2026-06-01T10:00:00.000Z\",\"sessionId\":\"s\"}\n",
    )
    .unwrap();
    let out = bin().arg(&tmp).arg("--redact").output().unwrap();
    let _ = std::fs::remove_file(&tmp);
    assert!(out.status.success());
    let text = String::from_utf8_lossy(&out.stdout);
    assert!(text.contains("[REDACTED]"));
    assert!(!text.contains("hunter2xyz"), "secret leaked: {text}");
}
