from __future__ import annotations

import json

import pytest

from cerebro_mcp import contradictions
from cerebro_mcp.contradictions import Fragment, differences, extract
from cerebro_mcp.query import QueryError

from .conftest import assert_no_leak


def _values(text, key=None, **kw):
    claims = extract("Header\n" + text, **kw)
    return [(c.key, c.value) for c in claims if key is None or c.key.startswith(key)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Pro is $4.99/month", [("price:month", "4.99")]),
        ("Pro cuesta $5.99 al mes o $39 al año", [("price:month", "5.99"), ("price:year", "39")]),
        ("Pro yearly: $35/year", [("price:year", "35")]),
        ("Annual plan: maybe $35", [("price:year", "35")]),
        ("it costs 12 dollars", [("price", "12")]),
        ("1,200 USD per month", [("price:month", "1200")]),
        ("Free tier: €0", [("price", "0")]),
    ],
)
def test_prices(text, expected):
    assert _values(text, "price") == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Current version: 0.8.5 (beta)", ["0.8.5"]),
        ("Shipped 0.9.2 to the beta channel", ["0.9.2"]),
        ("tag v2.1 today", ["2.1"]),
        ("versión 3.0 lista", ["3.0"]),
        ("Pro is $4.99 and the ratio is 1.5", []),
        ("Ship 0.9.x to beta", []),
        ("server at 10.0.0.12", []),
    ],
)
def test_versions(text, expected):
    assert [v for _, v in _values(text, "version")] == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Launch: 2026-12-01", ["2026-12-01"]),
        ("Launch: December 1, 2026 (2026-12-01)", ["2026-12-01", "2026-12-01"]),
        ("Lanzamos el 12 de enero de 2027", ["2027-01-12"]),
        ("Available January 12", ["--01-12"]),
        ("planned for March 2027", ["2027-03"]),
        ("_Last updated: 2026-07-02._", []),
        ("See [[2026-09-14 Decision]]", []),
    ],
)
def test_dates(text, expected):
    assert sorted(v for _, v in _values(text, "date")) == sorted(expected)


def test_own_date_is_ignored():
    assert _values("Handoff 2025-05-01: shipped", "date", doc_date="2025-05-01") == []


@pytest.mark.parametrize(
    "text, expected",
    [
        ("7-day free trial", [("number:day", "7")]),
        ("Prueba gratis de 14 días", [("number:day", "14")]),
        ("free tier: 3 habits", [("number:habit", "3")]),
        ("el plan gratis: 3 hábitos", [("number:habit", "3")]),
        ("in 2026 roadmap", []),
        ("6 de 9 testers", [("number:tester", "9")]),
    ],
)
def test_numbers_with_units(text, expected):
    assert _values(text, "number") == expected


def test_stances():
    terms = ("ad",)
    assert _values("The free tier shows a banner ad.", "decision", topic_terms=terms) == [("decision:ad", "yes")]
    assert _values("No ads. Ever.", "decision", topic_terms=terms) == [("decision:ad", "no")]
    assert _values("Ads in free; no ads in Pro", "decision", topic_terms=terms) == []  # mixed
    assert _values("No ads.", "decision") == []  # no topic, no stance


def test_stance_negator_stays_in_its_clause():
    # Regression: 'never add ads".\n- Price' was read as "no price".
    text = 'Decision: "never add ads".\n- The banner ad slot stays empty.'
    assert _values(text, "decision", topic_terms=("banner",)) == [("decision:banner", "yes")]
    assert _values("We will never, ever. Ads ship in v2.", "decision", topic_terms=("ad",)) == [("decision:ad", "yes")]


def test_value_topics_have_no_stance():
    assert _values("No price yet.", "decision", topic_terms=("price",)) == []


def _frag(i, text, date=None, source="a"):
    f = Fragment(i, i, f"{source}:{i}.md", source, None, "default", str(i), date, None, "T\n" + text, False)
    f.claims = extract(f.text, date)
    return f


def test_differences_need_disjoint_values():
    a = _frag(1, "Pro is $4.99/month and $35/year")
    b = _frag(2, "Pro is $5.99/month and $35/year")
    d = differences(a, b)
    assert [(x.key, x.older, x.newer) for x in d] == [("price:month", ["$4.99/month"], ["$5.99/month"])]
    c = _frag(3, "Why $5.99/month and not $4.99/month")
    assert differences(a, c) == []  # overlapping values are not a contradiction
    e = _frag(4, "launch in December 2026")
    f = _frag(5, "launch on 2026-12-01")
    assert differences(e, f) == []  # a month and a day inside it agree


def test_find_with_topic(indexed, embedder):
    r = contradictions.find(indexed, embedder, "garden planner Pro price", limit=10)
    assert r["mode"] == "hybrid"
    pair = next(
        p for p in r["pairs"]
        if {p["older"]["path"], p["newer"]["path"]}
        == {"memory:garden-app/memory/pricing.md", "repos:garden-app/docs/dev/handoff-2025-05-01.md"}
    )
    assert pair["older"]["path"] == "memory:garden-app/memory/pricing.md"  # 2025-01-10 < 2025-05-01
    assert pair["older"]["date"] == "2025-01-10" and pair["newer"]["date"] == "2025-05-01"
    price = next(v for v in pair["values"] if v["kind"] == "price")
    assert price["older"] == ["$10/month"] and price["newer"] == ["$12/month"]
    for side in ("older", "newer"):
        assert set(pair[side]) >= {"path", "source", "project", "date", "snippet"}
    assert_no_leak(json.dumps(r))  # the private $99/month never shows up


def test_across_sources_and_text_mode(indexed, embedder):
    for emb in (embedder, None):
        r = contradictions.find(indexed, emb, "garden planner version", across_sources=True, limit=10)
        assert r["mode"] == ("hybrid" if emb else "text")
        assert r["pairs"]
        for p in r["pairs"]:
            assert p["older"]["source"] != p["newer"]["source"]
            assert all(v["kind"] == "version" for v in p["values"] if v["kind"] != "decision")
        versions = {(tuple(v["older"]), tuple(v["newer"])) for p in r["pairs"] for v in p["values"]}
        assert any("1.2.0" in " ".join(o) and "1.4.0" in " ".join(n) for o, n in versions)


def test_same_source_pairs_without_flag(indexed, embedder):
    r = contradictions.find(indexed, embedder, "garden planner price", limit=20)
    r2 = contradictions.find(indexed, embedder, "garden planner price", across_sources=True, limit=20)
    assert len(r2["pairs"]) <= len(r["pairs"])


def test_scan_without_topic(indexed, embedder):
    r = contradictions.find(indexed, embedder, None, limit=30)
    assert r["topic"] is None and r["pairs"]
    assert_no_leak(json.dumps(r))


def test_empty_topic(indexed, embedder):
    with pytest.raises(QueryError):
        contradictions.find(indexed, embedder, "  ")
