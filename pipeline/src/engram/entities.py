"""Entity normalization and link rendering (DESIGN §4.2).

`entities.yaml` is per-user state and ships empty. Matching is *exact* (against
normalized canonical names and aliases) — there is no fuzzy auto-merge. Fuzzy
matching only *suggests* candidates during `engram entities review`.
"""
from __future__ import annotations

import difflib
import re
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

_WS = re.compile(r"\s+")
_PUNCT = string.punctuation


def normalize(raw: str) -> str:
    """trim → lowercase → collapse whitespace → strip surrounding punctuation."""
    s = _WS.sub(" ", raw.strip().lower())
    return s.strip(_PUNCT).strip()


@dataclass(frozen=True)
class Entity:
    name: str
    type: str
    aliases: tuple[str, ...] = ()


@dataclass
class EntityBook:
    entities: list[Entity] = field(default_factory=list)
    _index: dict[str, Entity] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for entity in self.entities:
            self._index_entity(entity)

    # -- construction -----------------------------------------------------

    @classmethod
    def from_list(cls, entries: Iterable[dict[str, Any]]) -> "EntityBook":
        entities = [
            Entity(
                name=e["name"],
                type=e.get("type", "concept"),
                aliases=tuple(e.get("aliases") or ()),
            )
            for e in entries
        ]
        return cls(entities=entities)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "EntityBook":
        p = Path(path)
        if not p.exists():
            return cls(entities=[])
        data = yaml.safe_load(p.read_text()) or {}
        return cls.from_list(data.get("entities") or [])

    def _index_entity(self, entity: Entity) -> None:
        for key in (entity.name, *entity.aliases):
            self._index[normalize(key)] = entity

    def to_yaml(self, path: str | Path) -> None:
        """Persist the book (used to record auto-approved projects)."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "entities": [
                {
                    "name": e.name,
                    "type": e.type,
                    **({"aliases": list(e.aliases)} if e.aliases else {}),
                }
                for e in self.entities
            ]
        }
        p.write_text(yaml.safe_dump(data, sort_keys=False))

    # -- lookup -----------------------------------------------------------

    def lookup(self, raw: str) -> Entity | None:
        return self._index.get(normalize(raw))

    def add_project(self, cwd: str) -> Entity:
        """Auto-approve a project entity from a cwd path (project name = last segment)."""
        name = Path(cwd).name or cwd
        existing = self.lookup(name)
        if existing is not None and existing.type == "project":
            return existing
        entity = Entity(name=name, type="project")
        self.entities.append(entity)
        self._index_entity(entity)
        return entity

    def fuzzy_suggest(self, raw: str, cutoff: float = 0.85) -> list[str]:
        """Suggest near-matching canonical names (review only — never auto-links)."""
        key = normalize(raw)
        names = [e.name for e in self.entities]
        return difflib.get_close_matches(key, names, n=5, cutoff=cutoff)


def render_entities(
    raws: Iterable[str], book: EntityBook, *, concepts_dir: str
) -> tuple[list[str], list[tuple[str, str]]]:
    """Render entity strings to markdown.

    Returns ``(rendered, pending)`` where rendered is the per-entity markdown
    (wikilink for matches, plain text for misses) and pending is a list of
    ``(normalized_key, display)`` tuples for the unmatched entities so the caller
    can record them in the state DB.
    """
    rendered: list[str] = []
    pending: list[tuple[str, str]] = []
    for raw in raws:
        display = raw.strip()
        match = book.lookup(raw)
        if match is None:
            rendered.append(display)
            pending.append((normalize(raw), display))
        elif match.type == "project":
            rendered.append(f"[[{match.name}]]")
        else:
            rendered.append(f"[[{concepts_dir}/{match.name}|{display}]]")
    return rendered, pending
