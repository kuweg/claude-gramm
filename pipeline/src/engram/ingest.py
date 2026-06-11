"""Ingest boundary: run the Rust `engram-parse` binary and validate its output.

This is the Rust↔Python contract enforcement point (DESIGN §2.1 / §3): we run the
compactor as a subprocess, parse its JSON, and refuse any ``schema_version`` we
don't understand so a future Rust change can't silently feed us garbage.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})
DEFAULT_PARSER_NAME = "engram-parse"


class IngestError(RuntimeError):
    """The parser failed (unreadable file, zero messages, non-zero exit)."""


class UnsupportedSchemaVersion(IngestError):
    """The compacted JSON declares a schema_version this build doesn't support."""


def resolve_parser_bin(parser_bin: str | Path | None) -> str:
    """Resolve the engram-parse binary: explicit path, else search PATH."""
    if parser_bin is not None:
        return str(parser_bin)
    found = shutil.which(DEFAULT_PARSER_NAME)
    if found is None:
        raise IngestError(
            f"could not find '{DEFAULT_PARSER_NAME}' on PATH; set parser_bin in config"
        )
    return found


def run_parser(
    jsonl_path: str | Path,
    *,
    parser_bin: str | Path | None = None,
    redact: bool = False,
) -> dict[str, Any]:
    """Run engram-parse on ``jsonl_path`` and return the compacted session dict.

    Raises ``IngestError`` on any non-zero exit (missing file, zero messages, …)
    and ``UnsupportedSchemaVersion`` if the output declares an unknown version.
    """
    binary = resolve_parser_bin(parser_bin)
    cmd = [binary, str(jsonl_path)]
    if redact:
        cmd.append("--redact")

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise IngestError(f"failed to execute {binary}: {exc}") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.strip()
        raise IngestError(
            f"engram-parse exited {proc.returncode} for {jsonl_path}: {stderr}"
        )

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise IngestError(f"engram-parse produced invalid JSON: {exc}") from exc

    check_schema_version(data)
    return data


def check_schema_version(data: dict[str, Any]) -> None:
    """Raise ``UnsupportedSchemaVersion`` unless the dict declares a known version."""
    version = data.get("schema_version")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise UnsupportedSchemaVersion(
            f"unsupported schema_version {version!r}; "
            f"this build supports {sorted(SUPPORTED_SCHEMA_VERSIONS)}"
        )
