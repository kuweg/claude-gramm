//! Thin binary wrapper around the engram Ingest library.
//!
//! Usage: `engram-parse <session.jsonl> [--redact]`
//!   stdout  — compacted §2.1 JSON
//!   stderr  — warnings (line numbers / counts only; never transcript content)
//!   exit 0  — success
//!   exit 2  — usage error / unreadable file
//!   exit 3  — file parsed but contained zero user/assistant messages

use std::process::ExitCode;

use engram_parser::compact_session;

fn main() -> ExitCode {
    let mut path: Option<String> = None;
    let mut redact = false;

    for arg in std::env::args().skip(1) {
        match arg.as_str() {
            "--redact" => redact = true,
            "-h" | "--help" => {
                eprintln!("usage: engram-parse <session.jsonl> [--redact]");
                return ExitCode::from(2);
            }
            other if other.starts_with('-') => {
                eprintln!("error: unknown flag '{other}'");
                return ExitCode::from(2);
            }
            other => {
                if path.is_some() {
                    eprintln!("error: unexpected extra argument '{other}'");
                    return ExitCode::from(2);
                }
                path = Some(other.to_owned());
            }
        }
    }

    let Some(path) = path else {
        eprintln!("usage: engram-parse <session.jsonl> [--redact]");
        return ExitCode::from(2);
    };

    let input = match std::fs::read_to_string(&path) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("error: cannot read {path}: {e}");
            return ExitCode::from(2);
        }
    };

    let out = compact_session(&input, redact);

    for warning in &out.warnings {
        eprintln!("warning: {warning}");
    }

    let msgs = out.session.stats.user_messages + out.session.stats.assistant_messages;
    if msgs == 0 {
        eprintln!("error: {path}: no user/assistant messages found");
        return ExitCode::from(3);
    }

    match serde_json::to_string(&out.session) {
        Ok(json) => {
            println!("{json}");
            ExitCode::SUCCESS
        }
        Err(e) => {
            eprintln!("error: failed to serialize: {e}");
            ExitCode::from(2)
        }
    }
}
