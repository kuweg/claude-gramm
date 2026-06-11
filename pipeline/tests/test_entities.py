"""Tests for entity normalization (DESIGN §4.2)."""
from __future__ import annotations

from engram.entities import EntityBook, normalize, render_entities


def test_normalize_trims_lowercases_collapses_and_strips_punctuation():
    assert normalize("  Tokio  ") == "tokio"
    assert normalize("Foo   Bar") == "foo bar"
    assert normalize("(tokio).") == "tokio"
    assert normalize("Tokio-RS") == "tokio-rs"  # internal punctuation preserved


def test_book_exact_match_by_canonical_name():
    book = EntityBook.from_list([{"name": "tokio", "type": "library", "aliases": []}])
    e = book.lookup("Tokio")
    assert e is not None
    assert e.name == "tokio"
    assert e.type == "library"


def test_book_exact_match_by_alias():
    book = EntityBook.from_list(
        [{"name": "tokio", "type": "library", "aliases": ["tokio-rs"]}]
    )
    e = book.lookup("Tokio-RS")
    assert e is not None
    assert e.name == "tokio"


def test_book_no_match_returns_none():
    book = EntityBook.from_list([{"name": "tokio", "type": "library"}])
    assert book.lookup("kafka") is None


def test_render_concept_as_piped_wikilink_with_original_casing():
    book = EntityBook.from_list([{"name": "tokio", "type": "library"}])
    rendered, pending = render_entities(["Tokio"], book, concepts_dir="Concepts")
    assert rendered == ["[[Concepts/tokio|Tokio]]"]
    assert pending == []


def test_render_project_as_plain_wikilink():
    book = EntityBook.from_list([{"name": "demo-service", "type": "project"}])
    rendered, _ = render_entities(["demo-service"], book, concepts_dir="Concepts")
    assert rendered == ["[[demo-service]]"]


def test_render_unmatched_is_plain_text_and_recorded_pending():
    book = EntityBook.from_list([])
    rendered, pending = render_entities(["Kafka"], book, concepts_dir="Concepts")
    assert rendered == ["Kafka"]  # plain text, no auto-link
    assert pending == [("kafka", "Kafka")]


def test_add_project_makes_it_matchable():
    book = EntityBook.from_list([])
    book.add_project("/home/u/projects/demo")  # path → project name "demo"
    e = book.lookup("demo")
    assert e is not None
    assert e.type == "project"
    assert e.name == "demo"


def test_fuzzy_suggest_finds_near_matches_only_above_cutoff():
    book = EntityBook.from_list(
        [{"name": "tokio", "type": "library"}, {"name": "postgres", "type": "service"}]
    )
    assert "tokio" in book.fuzzy_suggest("tokios")  # one extra char → ~0.91, above cutoff
    assert book.fuzzy_suggest("xylophone") == []  # nothing close
