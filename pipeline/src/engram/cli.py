"""engram command-line interface (DESIGN §5-6).

Subcommands: init, install-hook, uninstall-hook, process, backfill, entities.
The Anthropic client is built lazily (only when a distill call is actually made)
so config/hook commands work without ANTHROPIC_API_KEY.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import backfill as backfill_mod
from . import hook, review
from .config import Config, config_path, default_config_toml, load_config
from .entities import EntityBook
from .process import process_session
from .state import State

DEFAULT_SETTINGS = Path.home() / ".claude" / "settings.json"


def build_client(config: Config) -> Any:
    """Construct the Anthropic client. Patched out in tests."""
    import anthropic

    return anthropic.Anthropic()


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_init(args: argparse.Namespace) -> int:
    path = config_path(args.config)
    if path.exists() and not args.force:
        print(f"config already exists at {path} (use --force to overwrite)")
        return 1
    vault = args.vault or input("Path to your Obsidian vault: ").strip()
    if not vault:
        print("error: a vault path is required")
        return 1
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(default_config_toml(vault))
    print(f"wrote {path}")
    print("next: engram install-hook && engram backfill --limit 5")
    return 0


def cmd_install_hook(args: argparse.Namespace) -> int:
    settings = Path(args.settings)
    added = hook.install_hook(settings)
    print("hook installed" if added else "hook already present")
    return 0


def cmd_uninstall_hook(args: argparse.Namespace) -> int:
    settings = Path(args.settings)
    removed = hook.uninstall_hook(settings)
    print("hook removed" if removed else "hook was not installed")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    if args.hook:
        return _process_hook(args)
    config = load_config(args.config)
    client = build_client(config)
    with State(config.state_db) as state:
        book = EntityBook.from_yaml(config.entities_file)
        result = process_session(
            args.path,
            config,
            client,
            state=state,
            book=book,
            dry_run=args.dry_run,
            force=args.force,
        )
    if args.dry_run and result.markdown:
        print(result.markdown)
    else:
        print(f"{result.status}: {result.note_path or result.session_id or result.error}")
    return 0 if result.status != "error" else 1


def _process_hook(args: argparse.Namespace) -> int:
    payload = hook.read_hook_input(sys.stdin)
    transcript = payload.get("transcript_path")
    if not transcript:
        print("hook input missing transcript_path", file=sys.stderr)
        return 1
    if args.detach:
        # Re-spawn detached so the hook never blocks Claude Code shutdown.
        hook.spawn_detached([sys.executable, "-m", "engram", "process", str(transcript)])
        return 0
    config = load_config(args.config)
    client = build_client(config)
    with State(config.state_db) as state:
        book = EntityBook.from_yaml(config.entities_file)
        process_session(transcript, config, client, state=state, book=book)
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    client = build_client(config)  # dry-run still distills; it only skips the write
    with State(config.state_db) as state:
        book = EntityBook.from_yaml(config.entities_file)
        results = backfill_mod.backfill(
            config,
            client,
            state=state,
            book=book,
            limit=args.limit,
            dry_run=args.dry_run,
            force=args.force,
        )
    woven = sum(r.status in ("woven", "dry_run") for r in results)
    print(f"processed {woven} session(s)")
    return 0


def cmd_entities_review(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    with State(config.state_db) as state:
        book = EntityBook.from_yaml(config.entities_file)
        pending = state.get_pending_entities()
        if not pending:
            print("no pending entities")
            return 0
        for row in pending:
            suggestions = book.fuzzy_suggest(row["name"])
            hint = f" (similar: {', '.join(suggestions)})" if suggestions else ""
            prompt = (
                f"[{row['count']}x] {row['display']}{hint}\n"
                "  (a)pprove / a(l)ias / (r)eject / (s)kip: "
            )
            choice = input(prompt).strip().lower()
            if choice == "a":
                review.approve(state, book, config, row["name"], display=row["display"])
            elif choice == "l":
                canonical = input("  alias to canonical name: ").strip()
                review.alias(state, book, config, row["name"], canonical=canonical)
            elif choice == "r":
                review.reject(state, row["name"])
    return 0


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="engram", description="Distill Claude Code sessions into Obsidian notes")
    p.add_argument("--config", default=None, help="path to config.toml (overrides ENGRAM_CONFIG)")
    sub = p.add_subparsers(dest="command", required=True)

    pi = sub.add_parser("init", help="create config.toml")
    pi.add_argument("--vault", default=None, help="path to your Obsidian vault")
    pi.add_argument("--force", action="store_true")
    pi.set_defaults(func=cmd_init)

    ph = sub.add_parser("install-hook", help="install the SessionEnd hook")
    ph.add_argument("--settings", default=str(DEFAULT_SETTINGS))
    ph.set_defaults(func=cmd_install_hook)

    pu = sub.add_parser("uninstall-hook", help="remove the SessionEnd hook")
    pu.add_argument("--settings", default=str(DEFAULT_SETTINGS))
    pu.set_defaults(func=cmd_uninstall_hook)

    pp = sub.add_parser("process", help="process one session")
    pp.add_argument("path", nargs="?", help="session .jsonl (omit with --hook)")
    pp.add_argument("--dry-run", action="store_true", help="print note, write nothing")
    pp.add_argument("--force", action="store_true")
    pp.add_argument("--hook", action="store_true", help="read hook JSON from stdin")
    pp.add_argument("--detach", action="store_true", help="re-spawn detached (with --hook)")
    pp.set_defaults(func=cmd_process)

    pb = sub.add_parser("backfill", help="process all sessions oldest-first")
    pb.add_argument("--limit", type=int, default=None)
    pb.add_argument("--force", action="store_true")
    pb.add_argument("--dry-run", action="store_true")
    pb.set_defaults(func=cmd_backfill)

    pe = sub.add_parser("entities", help="entity vocabulary management")
    esub = pe.add_subparsers(dest="entities_command", required=True)
    per = esub.add_parser("review", help="review pending entities interactively")
    per.set_defaults(func=cmd_entities_review)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
