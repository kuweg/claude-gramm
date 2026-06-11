"""Configuration loading (DESIGN §5).

Single TOML file at the platform config dir (``platformdirs``), overridable via
``ENGRAM_CONFIG``. Every path is per-user; nothing references a specific machine.
The API key comes from ``ANTHROPIC_API_KEY`` only — never config or DB.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import platformdirs

APP_NAME = "engram"


def _config_dir() -> Path:
    return Path(platformdirs.user_config_dir(APP_NAME))


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines: ignore blanks/comments, strip `export ` and quotes."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def load_dotenv(*, cwd: Path | None = None, environ: dict[str, str] | None = None) -> None:
    """Load API keys / settings from a .env file WITHOUT overriding the real env.

    Search order (first to set a key wins; the real environment always wins):
    ``$ENGRAM_ENV`` → ``./.env`` → ``<config-dir>/.env``.
    """
    env = os.environ if environ is None else environ
    cwd = Path.cwd() if cwd is None else cwd
    candidates: list[Path] = []
    if env.get("ENGRAM_ENV"):
        candidates.append(Path(env["ENGRAM_ENV"]))
    candidates.append(cwd / ".env")
    candidates.append(_config_dir() / ".env")
    for path in candidates:
        if path.is_file():
            for key, value in parse_dotenv(path.read_text()).items():
                env.setdefault(key, value)


def _data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME))


DEFAULTS: dict[str, Any] = {
    "projects_dir": "~/.claude/projects",
    "vault_path": "",
    # Sonnet 4.6 is the default: distillation extracts decisions/problems, where
    # Haiku flattens nuance (DESIGN Q8). Override per-run with ENGRAM_MODEL — e.g.
    # claude-haiku-4-5 for cost, gpt-4o / deepseek-chat for other providers.
    "model": "claude-sonnet-4-6",
    "redact": True,
    "max_text_chars": 4000,
    "parser_bin": "",  # empty → resolve from PATH
}

VAULT_DEFAULTS = {
    "sessions_dir": "Sessions",
    "concepts_dir": "Concepts",
    "projects_dir": "Projects",
}


@dataclass(frozen=True)
class Config:
    vault_path: Path
    projects_dir: Path
    model: str
    redact: bool
    max_text_chars: int
    entities_file: Path
    state_db: Path
    parser_bin: str
    sessions_dir: str
    concepts_dir: str
    projects_dir_notes: str


def _expand(value: str) -> Path:
    return Path(os.path.expanduser(value))


def config_path(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("ENGRAM_CONFIG")
    if env:
        return Path(env)
    return _config_dir() / "config.toml"


def load_config(path: str | Path | None = None) -> Config:
    p = config_path(path)
    raw: dict[str, Any] = {}
    if p.exists():
        raw = tomllib.loads(p.read_text())

    merged = {**DEFAULTS, **{k: v for k, v in raw.items() if k != "vault"}}
    vault = {**VAULT_DEFAULTS, **(raw.get("vault") or {})}

    entities_file = raw.get("entities_file") or str(_config_dir() / "entities.yaml")
    state_db = raw.get("state_db") or str(_data_dir() / "state.db")

    return Config(
        vault_path=_expand(merged["vault_path"]),
        projects_dir=_expand(merged["projects_dir"]),
        model=merged["model"],
        redact=bool(merged["redact"]),
        max_text_chars=int(merged["max_text_chars"]),
        entities_file=_expand(entities_file),
        state_db=_expand(state_db),
        parser_bin=merged["parser_bin"],
        sessions_dir=vault["sessions_dir"],
        concepts_dir=vault["concepts_dir"],
        projects_dir_notes=vault["projects_dir"],
    )


def default_config_toml(vault_path: str) -> str:
    """Render a starter config.toml with sane defaults (written by `engram init`)."""
    return f"""\
projects_dir = "~/.claude/projects"
vault_path   = "{vault_path}"
model        = "{DEFAULTS['model']}"
redact       = true
max_text_chars = {DEFAULTS['max_text_chars']}

[vault]
sessions_dir = "{VAULT_DEFAULTS['sessions_dir']}"
concepts_dir = "{VAULT_DEFAULTS['concepts_dir']}"
projects_dir = "{VAULT_DEFAULTS['projects_dir']}"
"""
