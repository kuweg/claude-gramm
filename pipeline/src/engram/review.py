"""Entity review operations (DESIGN §4.2 step 4).

Grows the concept vocabulary over time: approve (→ entities.yaml + Concepts stub),
alias-to-existing, or reject (blacklist so it never resurfaces). The interactive
CLI in ``cli.py`` wraps these primitives.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .config import Config
from .entities import Entity, EntityBook
from .state import State

_STUB = """\
---
tags: [concept]
engram_version: 1
---

# {title}
"""


def _create_stub(config: Config, name: str, display: str) -> Path:
    concepts = config.vault_path / config.concepts_dir
    concepts.mkdir(parents=True, exist_ok=True)
    stub = concepts / f"{name}.md"
    if not stub.exists():
        stub.write_text(_STUB.format(title=display or name))
    return stub


def approve(
    state: State,
    book: EntityBook,
    config: Config,
    name: str,
    *,
    etype: str = "concept",
    display: str | None = None,
) -> Path:
    """Append to entities.yaml, create a Concepts stub, mark pending → approved."""
    if book.lookup(name) is None:
        entity = Entity(name=name, type=etype)
        book.entities.append(entity)
        book._index_entity(entity)
        book.to_yaml(config.entities_file)
    stub = _create_stub(config, name, display or name)
    state.set_pending_status(name, "approved")
    return stub


def alias(
    state: State, book: EntityBook, config: Config, name: str, *, canonical: str
) -> None:
    """Attach ``name`` as an alias of an existing canonical entity."""
    target = book.lookup(canonical)
    if target is None:
        raise ValueError(f"unknown canonical entity: {canonical!r}")
    updated = replace(target, aliases=tuple({*target.aliases, name}))
    book.entities = [updated if e is target else e for e in book.entities]
    book._index.clear()
    for e in book.entities:
        book._index_entity(e)
    book.to_yaml(config.entities_file)
    state.set_pending_status(name, "aliased")


def reject(state: State, name: str) -> None:
    """Blacklist a pending entity so it never resurfaces."""
    state.set_pending_status(name, "rejected")
