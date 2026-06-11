"""Tests for the Rust↔Python subprocess boundary and schema_version gate (DESIGN §3)."""
from __future__ import annotations

import pytest

from engram import ingest
from engram.ingest import IngestError, UnsupportedSchemaVersion


def test_run_parser_returns_compacted_dict(parser_bin, fixtures_dir):
    result = ingest.run_parser(fixtures_dir / "events.jsonl", parser_bin=parser_bin)
    assert result["schema_version"] == 1
    assert result["session_id"] == "00000000-0000-4000-8000-000000000001"
    assert result["stats"]["tool_calls"] == 2
    assert isinstance(result["events"], list)


def test_run_parser_passes_redact_flag(parser_bin, tmp_path):
    secret = tmp_path / "s.jsonl"
    secret.write_text(
        '{"type":"user","message":{"role":"user","content":"password: hunter2xyz"},'
        '"timestamp":"2026-06-01T10:00:00.000Z","sessionId":"s"}\n'
    )
    redacted = ingest.run_parser(secret, parser_bin=parser_bin, redact=True)
    assert "hunter2xyz" not in redacted["events"][0]["text"]
    assert "[REDACTED]" in redacted["events"][0]["text"]


def test_run_parser_raises_on_zero_message_file(parser_bin, tmp_path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text('{"type":"ai-title","aiTitle":"x","sessionId":"s"}\n')
    with pytest.raises(IngestError):
        ingest.run_parser(empty, parser_bin=parser_bin)


def test_run_parser_raises_on_missing_file(parser_bin, tmp_path):
    with pytest.raises(IngestError):
        ingest.run_parser(tmp_path / "nope.jsonl", parser_bin=parser_bin)


def test_check_schema_version_accepts_known():
    ingest.check_schema_version({"schema_version": 1})  # no raise


def test_check_schema_version_rejects_unknown():
    with pytest.raises(UnsupportedSchemaVersion):
        ingest.check_schema_version({"schema_version": 999})


def test_check_schema_version_rejects_missing():
    with pytest.raises(UnsupportedSchemaVersion):
        ingest.check_schema_version({})
