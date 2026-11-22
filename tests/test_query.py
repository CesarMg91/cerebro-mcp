from __future__ import annotations

import json
from dataclasses import replace

import pytest

from cerebro_mcp import index, query
from cerebro_mcp.query import QueryError

from .conftest import PRIVATE_MARKERS, assert_no_leak


def _search(conn, embedder, text, **kw):
    return query.search(conn, embedder, text, **kw)


def _paths(result):
    return [r["path"] for r in result["results"]]


def test_hybrid_search_finds_by_name_and_returns_fields(indexed, embedder):
    r = _search(indexed, embedder, "Seed catalog")
    assert r["mode"] == "hybrid"
    top = r["results"][0]
    assert top["path"] == "notes:Projects/Seed catalog.md"
    assert set(top) >= {"path", "source", "project", "title", "date", "snippet", "score"}
    assert top["source"] == "notes" and top["scope"] == "personal" and top["date"] == "2025-01-20"
    assert "text" in top["signals"]
    assert len(_paths(r)) == len(set(_paths(r)))  # one result per document


def test_text_mode_without_embedder(indexed):
    r = _search(indexed, None, "watering")
    assert r["mode"] == "text"
    assert all(x["signals"] == ["text"] for x in r["results"])


@pytest.mark.parametrize("marker", PRIVATE_MARKERS)
def test_private_never_returned(indexed, embedder, marker):
    r = _search(indexed, embedder, marker, limit=50)
    assert_no_leak(json.dumps(r, ensure_ascii=False))
    for path in _paths(r):
        assert path not in {"notes:private/Health.md", "notes:People/Ana Torres.md", "notes:Journal/2025-03-14.md"}


def test_filters(indexed, embedder):
    paths = _paths(_search(indexed, embedder, "garden planner", source="memory", limit=20))
    assert paths and all(p.startswith("memory:") for p in paths)
    paths = _paths(_search(indexed, embedder, "garden planner", scope="work", limit=20))
    assert paths and all(p.split(":")[0] in {"memory", "repos"} for p in paths)
    paths = _paths(_search(indexed, embedder, "garden", type="project", limit=20))
    # frontmatter `type`, or `metadata.type` in agent memories
    assert set(paths) == {"notes:Projects/Garden planner.md", "memory:garden-app/memory/pricing.md"}
    paths = _paths(_search(indexed, embedder, "garden tomatoes basil", since="2025-03", limit=20))
    assert paths and "notes:Projects/Seed catalog.md" not in paths
    paths = _paths(_search(indexed, embedder, "garden tomatoes basil", until="2025-01", limit=20))
    assert "notes:Projects/Seed catalog.md" in paths
    assert all(p != "notes:Journal/2025-04-02.md" for p in paths)
    with pytest.raises(QueryError, match="unknown source"):
        _search(indexed, embedder, "x", source="dropbox")
    with pytest.raises(QueryError, match="invalid date"):
        _search(indexed, embedder, "x", since="March")
    with pytest.raises(QueryError, match="empty"):
        _search(indexed, embedder, "   ")


def test_hidden_scopes(indexed, embedder):
    hidden = ("work",)
    paths = _paths(_search(indexed, embedder, "garden planner pricing", hidden_scopes=hidden, limit=30))
    assert paths and all(p.startswith("notes:") for p in paths)
    paths = _paths(_search(indexed, embedder, "garden planner pricing", hidden_scopes=hidden, scope="work", limit=30))
    assert paths and all(p.split(":")[0] in {"memory", "repos"} for p in paths)
    assert query.note(indexed, "memory:garden-app/memory/pricing.md", hidden_scopes=hidden) is None
    assert query.note(indexed, "memory:garden-app/memory/pricing.md", hidden_scopes=hidden, scope="work")


def test_untrusted_clip_flagged(indexed, embedder):
    r = _search(indexed, embedder, "water tomatoes deeply")
    clip = next(x for x in r["results"] if x["path"] == "notes:Clips/Watering article.md")
    assert clip["untrusted"] is True


def test_note_resolution(indexed, cfg):
    by_id = query.note(indexed, "notes:Projects/Garden planner.md")
    assert by_id["title"] == "Garden planner" and "$12/month" in by_id["body"]
    assert by_id["frontmatter"]["status"] == "active"
    assert query.note(indexed, "notes:Projects/Garden planner")["path"] == by_id["path"]
    assert query.note(indexed, "notes:Projects\\Garden planner.md")["path"] == by_id["path"]
    absolute = str(cfg.source("notes").path / "Projects" / "Garden planner.md")
    assert query.note(indexed, absolute)["path"] == by_id["path"]
    assert query.note(indexed, "garden PLANNER")["path"] == by_id["path"]
    assert query.note(indexed, "Pricing")["path"] == "memory:garden-app/memory/pricing.md"
    # private notes answer as not found, whatever the way of asking
    for ref in ("notes:private/Health.md", "Health", "Ana Torres", "notes:Journal/2025-03-14.md",
                str(cfg.source("notes").path / "private" / "Health.md")):
        assert query.note(indexed, ref) is None, ref


def test_links_hide_private_notes(indexed):
    links = query.links(indexed, "Garden planner")
    out = {link["target"]: link for link in links["outgoing"]}
    assert out["Seed catalog"]["path"] == "notes:Projects/Seed catalog.md"
    assert out["Ana Torres"]["path"] is None and out["Ana Torres"]["title"] is None  # private target
    assert out["Ghost note"]["path"] is None  # does not exist
    assert "Not a link" not in out  # inside a code block
    assert links["incoming"] == [{"path": "notes:Projects/Seed catalog.md", "title": "Seed catalog"}]
    assert query.links(indexed, "Ana Torres") is None
    row = indexed.execute("select target_id from links where target = 'Ana Torres'").fetchone()
    assert row[0] is None  # never resolved to the private note


def test_todos(indexed):
    r = query.todos(indexed, "garden planner")
    texts = [t["text"] for t in r["todos"]]
    assert "Ship the frost alert with `FrostWatch.check()`" in texts  # inline code kept
    assert "Garden planner: rename the `beds` table" in texts  # mentioned in another note
    assert "Garden planner: add sync tests" in texts  # from an agent memory
    assert "Garden planner: write the release notes" in texts  # from a glob source
    assert "Draw the bed layout" not in texts and "Garden planner: fix login" not in texts  # done
    assert "this checkbox lives in a code block and is ignored" not in texts
    assert "Buy more compost" not in texts
    assert_no_leak(json.dumps(r))
    first = next(t for t in r["todos"] if t["text"].startswith("Ship the frost"))
    assert first["path"] == "notes:Projects/Garden planner.md" and first["line"] == 16
    with pytest.raises(QueryError):
        query.todos(indexed, " ")


def test_propose_only_writes_inside_its_folder(tmp_path):
    folder = tmp_path / "proposals"
    p1 = query.propose(folder, "../../escape attempt", "body")
    p2 = query.propose(folder, "../../escape attempt", "body")
    assert p1.parent == folder.resolve() and p2.parent == folder.resolve() and p1 != p2
    assert p1.name.endswith("-escape-attempt.md")
    text = p1.read_text(encoding="utf-8")
    assert text.startswith("---\ntype: proposal\n") and "# ../../escape attempt" in text
    with pytest.raises(QueryError):
        query.propose(folder, "  ", "x")
    with pytest.raises(QueryError):
        query.propose(folder, "big", "x" * 60_000)


def test_vector_search_numpy_fallback(cfg, embedder):
    index.run(cfg, embedder)
    conn = index.connect(cfg.db)
    try:
        qv = embedder.query("frost forecast bot")
        where, params = query.egress(None)
        with_vec = query.vector(conn, qv, where, params, limit=1000)
        conn.vec = False
        without = query.vector(conn, qv, where, params, limit=1000)
    finally:
        conn.close()
    assert with_vec[0] == without[0] and set(with_vec) == set(without)


def test_hidden_scope_config_reaches_contradictions(cfg, embedder):
    from cerebro_mcp import contradictions

    index.run(cfg, embedder)
    conn = index.connect(cfg.db)
    try:
        hidden = replace(cfg.privacy, hidden_scopes=("work",)).hidden_scopes
        r = contradictions.find(conn, embedder, "garden planner price", hidden_scopes=hidden)
    finally:
        conn.close()
    for p in r["pairs"]:
        assert p["older"]["scope"] != "work" and p["newer"]["scope"] != "work"
