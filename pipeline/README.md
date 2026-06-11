# engram (pipeline)

Distill Claude Code sessions into an Obsidian knowledge graph.

This package is the **Distill + Weave** half of engram (DESIGN §3–6). It runs the
Rust `engram-parse` compactor as a subprocess, sends the compacted transcript to
the Anthropic API for structured distillation, and renders Obsidian notes with a
normalized entity graph.

## Install

```sh
uv tool install engram        # or: pipx install engram
# from source:
python3 -m venv .venv && .venv/bin/pip install -e .
```

The Rust binary `engram-parse` must be on `PATH` (or set `parser_bin` in config).

## Onboarding

```sh
engram init                   # writes config.toml (asks for your vault path)
engram install-hook           # SessionEnd hook → notes appear after each session
engram backfill --limit 5     # process the 5 oldest existing sessions
```

`ANTHROPIC_API_KEY` must be set in the environment — it is never read from config.

## Commands

| Command | What it does |
|---|---|
| `engram init` | Create `config.toml` |
| `engram install-hook` / `uninstall-hook` | Idempotent SessionEnd hook in `settings.json` |
| `engram process <session.jsonl>` | Process one session (`--dry-run`, `--force`) |
| `engram backfill` | Process all sessions oldest-first (`--limit N`) |
| `engram entities review` | Approve / alias / reject pending concept entities |

## Development

```sh
make build      # cargo build --release + editable install
make test       # cargo test + clippy + pytest
```

Tests use fixtures only and never hit the Anthropic API (the client is faked).
