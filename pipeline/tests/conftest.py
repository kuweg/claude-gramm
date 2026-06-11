"""Shared test fixtures and paths."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"
PARSER_BIN = REPO_ROOT / "target" / "release" / "engram-parse"

# Make `engram` importable without an install step.
sys.path.insert(0, str(REPO_ROOT / "pipeline" / "src"))


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def parser_bin() -> Path:
    if not PARSER_BIN.exists():
        pytest.skip("engram-parse release binary not built (run `cargo build --release`)")
    return PARSER_BIN
