"""Tests for the CLI dispatch, init, hook commands, and --dry-run (DESIGN §5-6)."""
from __future__ import annotations

import json

from engram import cli
from tests.test_process import FakeClient, DISTILLED


def test_init_writes_config(tmp_path, capsys):
    cfgpath = tmp_path / "config.toml"
    rc = cli.main(["--config", str(cfgpath), "init", "--vault", "/my/vault"])
    assert rc == 0
    assert cfgpath.exists()
    assert 'vault_path   = "/my/vault"' in cfgpath.read_text()


def test_init_refuses_overwrite_without_force(tmp_path):
    cfgpath = tmp_path / "config.toml"
    cfgpath.write_text("existing = true\n")
    rc = cli.main(["--config", str(cfgpath), "init", "--vault", "/v"])
    assert rc == 1


def test_install_and_uninstall_hook_via_cli(tmp_path, capsys):
    settings = tmp_path / "settings.json"
    assert cli.main(["install-hook", "--settings", str(settings)]) == 0
    data = json.loads(settings.read_text())
    cmds = [h["command"] for e in data["hooks"]["SessionEnd"] for h in e["hooks"]]
    assert cli.hook.HOOK_COMMAND in cmds
    assert cli.main(["uninstall-hook", "--settings", str(settings)]) == 0


def test_process_dry_run_prints_note(tmp_path, fixtures_dir, parser_bin, monkeypatch, capsys):
    cfgpath = tmp_path / "config.toml"
    cfgpath.write_text(
        f'vault_path = "{tmp_path / "vault"}"\n'
        f'parser_bin = "{parser_bin}"\n'
        "redact = false\n"
        f'state_db = "{tmp_path / "state.db"}"\n'
        f'entities_file = "{tmp_path / "entities.yaml"}"\n'
    )
    monkeypatch.setattr(cli, "build_client", lambda config: FakeClient([DISTILLED]))
    rc = cli.main(
        ["--config", str(cfgpath), "process", str(fixtures_dir / "events.jsonl"), "--dry-run"]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "# add-fetcher-retry-logic" in out
    # dry-run wrote nothing
    assert not (tmp_path / "vault").exists()


def test_build_parser_has_all_subcommands():
    parser = cli.build_parser()
    # argparse exits on missing subcommand; just ensure choices exist
    actions = [a for a in parser._actions if a.dest == "command"]
    assert actions
    choices = set(actions[0].choices)
    assert {"init", "install-hook", "uninstall-hook", "process", "backfill", "entities"} <= choices
