from __future__ import annotations

from dataclasses import replace

from cerebro_mcp import config, index

from .conftest import FAKE_SECRETS, PRIVATE_MARKERS, FakeEmbedder, write_config


def _count(conn, sql, *params):
    return conn.execute(sql, params).fetchone()[0]


def test_first_index(cfg, embedder):
    s = index.run(cfg, embedder)
    assert s.mode == "hybrid" and s.added == s.notes and s.removed == 0
    assert s.by_source == {"notes": 10, "memory": 3, "repos": 3}
    assert s.private == 3  # private/Health, People/Ana Torres, Journal/2025-03-14
    assert s.redacted_lines == 2
    conn = index.connect(cfg.db)
    try:
        assert _count(conn, "select count(*) from notes where doc_id like 'notes:Templates/%'") == 0
        assert _count(conn, "select count(*) from chunks where embedding is null") == 0
        row = conn.execute("select * from notes where doc_id = 'memory:garden-app/memory/pricing.md'").fetchone()
        assert row["project"] == "garden-app" and row["scope"] == "work" and row["date"] == "2025-01-10"
        assert row["type"] == "project" and row["title"] == "Pricing"
    finally:
        conn.close()


def test_private_notes_keep_only_id_and_hash(indexed, cfg):
    rows = indexed.execute("select * from notes where private = 1 order by doc_id").fetchall()
    assert [r["doc_id"] for r in rows] == [
        "notes:Journal/2025-03-14.md",
        "notes:People/Ana Torres.md",
        "notes:private/Health.md",
    ]
    for r in rows:
        assert r["body"] is None and r["frontmatter"] is None and r["title"] == "" and r["hash"]
        assert _count(indexed, "select count(*) from chunks where note_id = ?", r["id"]) == 0
        assert _count(indexed, "select count(*) from todos where note_id = ?", r["id"]) == 0
        assert _count(indexed, "select count(*) from links where note_id = ?", r["id"]) == 0
    indexed.execute("pragma wal_checkpoint(truncate)")
    raw = cfg.db.read_bytes().decode("utf-8", errors="ignore")
    for marker in PRIVATE_MARKERS + FAKE_SECRETS:
        assert marker not in raw, marker


def test_redacted_lines_in_index(indexed):
    body = indexed.execute("select body from notes where doc_id = 'notes:Dev/Keys.md'").fetchone()[0]
    assert "[redacted:secret]" in body and "[redacted:card]" in body
    assert "webhook" in body


def test_incremental_add_change_delete(cfg, embedder, workspace):
    index.run(cfg, embedder)
    embedder.embedded.clear()
    s = index.run(cfg, embedder)
    assert (s.added, s.updated, s.removed) == (0, 0, 0) and s.unchanged == 16
    assert embedder.embedded == []

    vault = workspace / "vault"
    (vault / "New idea.md").write_text("# New idea\n\nkiwi trellis", encoding="utf-8")
    (vault / "Projects" / "Seed catalog.md").write_text("# Seed catalog\n\nonly chili seeds now", encoding="utf-8")
    (vault / "Inbox.md").unlink()
    s = index.run(cfg, embedder)
    assert (s.added, s.updated, s.removed) == (1, 1, 1)
    assert any("kiwi trellis" in t for t in embedder.embedded)
    conn = index.connect(cfg.db)
    try:
        body = conn.execute("select body from notes where doc_id = 'notes:Projects/Seed catalog.md'").fetchone()[0]
        assert "chili" in body
        assert _count(conn, "select count(*) from notes where doc_id = 'notes:Inbox.md'") == 0
        assert _count(conn, "select count(*) from chunks_fts where chunks_fts match 'tomatoes'") >= 1
        assert _count(
            conn, "select count(*) from chunks_fts where chunks_fts match 'peppers' and title = 'Seed catalog'"
        ) == 0
    finally:
        conn.close()


def test_removed_source_leaves_the_index(cfg, embedder):
    index.run(cfg, embedder)
    smaller = replace(cfg, sources=tuple(s for s in cfg.sources if s.name != "repos"))
    s = index.run(smaller, embedder)
    assert s.removed == 3
    conn = index.connect(cfg.db)
    try:
        assert _count(conn, "select count(*) from notes where source = 'repos'") == 0
    finally:
        conn.close()


def test_settings_change_reindexes(workspace, embedder):
    cfg = config.load(write_config(workspace))
    index.run(cfg, embedder)
    # Mark Clips as private: same files, new privacy rules -> re-parsed, now private.
    cfg2 = config.load(
        write_config(workspace).parent / "cerebro.toml"
    )
    cfg2 = replace(cfg2, privacy=replace(cfg2.privacy, private_folders=("private", "people", "clips")))
    s = index.run(cfg2, embedder)
    assert s.updated == 16 and s.private == 4


def test_text_only_then_backfill_then_model_change(cfg):
    s = index.run(cfg, None)
    assert s.mode == "text" and s.embedded_chunks == 0
    conn = index.connect(cfg.db)
    try:
        assert not index.has_vectors(conn)
    finally:
        conn.close()
    first = FakeEmbedder()
    s = index.run(cfg, first)
    assert s.unchanged == 16 and s.embedded_chunks > 0  # backfilled without re-parsing
    other = FakeEmbedder(name="another-model")
    s = index.run(cfg, other)
    assert s.embedded_chunks == len(first.embedded)  # vectors of another model are redone
    conn = index.connect(cfg.db)
    try:
        assert index.get_meta(conn, "model") == "another-model"
    finally:
        conn.close()


def test_full_rebuild_and_missing_source(cfg, embedder, tmp_path):
    index.run(cfg, embedder)
    s = index.run(cfg, embedder, full=True)
    assert s.added == s.notes == 16
    broken = replace(cfg, sources=cfg.sources + (replace(cfg.sources[0], name="gone", path=tmp_path / "nope"),))
    s = index.run(broken, embedder)
    assert any("gone" in w for w in s.warnings)


def test_unavailable_model_falls_back_to_text(cfg):
    from cerebro_mcp.embeddings import ModelUnavailable

    class Broken(FakeEmbedder):
        def load(self):
            raise ModelUnavailable("offline")

    s = index.run(cfg, Broken())
    assert s.mode == "text" and s.notes == 16 and "offline" in s.warnings[0]
