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

The API key must be set in the environment — never read from config.

## Model / provider selection

The distillation model is chosen via the environment (falls back to `config.model`,
default `claude-sonnet-4-6`). The provider is inferred from the model id:

```sh
export ENGRAM_MODEL=claude-sonnet-4-6   ANTHROPIC_API_KEY=sk-ant-...   # Anthropic (default)
export ENGRAM_MODEL=claude-haiku-4-5    ANTHROPIC_API_KEY=sk-ant-...   # cheaper
export ENGRAM_MODEL=gpt-4o              OPENAI_API_KEY=sk-...          # OpenAI / ChatGPT
export ENGRAM_MODEL=deepseek-chat       DEEPSEEK_API_KEY=sk-...        # DeepSeek
```

Set `ENGRAM_PROVIDER=anthropic|openai|deepseek` to force a provider for a non-standard
model id. See `.env.example`.

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
