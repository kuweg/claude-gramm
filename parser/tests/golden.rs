//! Golden test: compacting `fixtures/events.jsonl` must reproduce the
//! hand-written `fixtures/compacted.sample.json` contract document (DESIGN §11).

use engram_parser::compact_session;
use serde_json::Value;

fn fixture(name: &str) -> String {
    let path = format!("{}/../fixtures/{}", env!("CARGO_MANIFEST_DIR"), name);
    std::fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {path}: {e}"))
}

#[test]
fn events_fixture_compacts_to_sample() {
    let input = fixture("events.jsonl");
    let out = compact_session(&input, false);
    let actual: Value = serde_json::to_value(&out.session).expect("serialize");
    let expected: Value =
        serde_json::from_str(&fixture("compacted.sample.json")).expect("parse sample");

    assert_eq!(
        actual,
        expected,
        "\n--- actual ---\n{}\n--- expected ---\n{}",
        serde_json::to_string_pretty(&actual).unwrap(),
        serde_json::to_string_pretty(&expected).unwrap()
    );
}

#[test]
fn malformed_fixture_does_not_panic_and_counts_skips() {
    let input = fixture("malformed.jsonl");
    let out = compact_session(&input, false);
    // 5 physical lines: invalid-json, future-type, blank, no-type, bare-string-assistant.
    assert!(out.session.stats.skipped_lines >= 2, "should skip the 2 unparseable lines");
    // The bare-string assistant line is tolerated and kept.
    assert!(out.session.stats.assistant_messages >= 1);
}
