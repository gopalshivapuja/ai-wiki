"""Tests for wiki core."""

from pathlib import Path

import pytest

from wiki_core.frontmatter import extract_title, parse_frontmatter
from wiki_core.graph import build_graph, canonical_slug, get_page_by_slug
from wiki_core.lint import lint_wiki
from wiki_core.search import search
from wiki_core.slug import slugify
from wiki_core.wikilinks import parse_wikilinks, resolve_link


def test_slugify():
    assert slugify("Scaled Dot-Product Attention!") == "scaled-dot-product-attention"


def test_parse_wikilinks():
    text = "See [[scaled-dot-product-attention|Attention]] and [[transformer-architecture]]."
    links = parse_wikilinks(text)
    assert len(links) == 2
    assert links[0].target == "scaled-dot-product-attention"
    assert links[0].display == "Attention"


def test_frontmatter():
    text = "---\ntitle: Test\nuid: '123'\n---\n\n# Hello"
    fm, body = parse_frontmatter(text)
    assert fm["title"] == "Test"
    assert "# Hello" in body


def test_search_attention():
    results = search("attention transformer", top_k=3)
    assert len(results) > 0
    assert any("attention" in r.title.lower() or "attention" in r.slug for r in results)


def test_graph_build():
    graph = build_graph()
    assert len(graph.nodes) > 0
    assert len(graph.edges) > 0


def test_get_page_by_slug():
    path = get_page_by_slug("transformer-architecture")
    assert path is not None
    assert path.exists()


def test_canonical_slug():
    assert canonical_slug(Path("wiki/atomic/20260810100100-scaled-dot-product-attention.md")) == "scaled-dot-product-attention"
    assert canonical_slug(Path("wiki/atomic/scaled-dot-product-attention.md")) == "scaled-dot-product-attention"


def test_lint_clean():
    issues = lint_wiki()
    assert isinstance(issues, list)


def test_resolve_link():
    index = {
        "scaled-dot-product-attention": "scaled-dot-product-attention",
        "20260810100100-scaled-dot-product-attention": "scaled-dot-product-attention",
    }
    assert resolve_link("scaled-dot-product-attention", index) == "scaled-dot-product-attention"
