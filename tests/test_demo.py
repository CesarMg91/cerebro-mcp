"""The bundled demo: read from the installed package, copied to a temp dir, indexed with its own config."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest

from cerebro_mcp import config, contradictions, demo, index, query

DEMO_PRIVATE_MARKERS = ("$7.99", "7 meses de ahorros")
DEMO_FAKE_KEY = "sk_live_DEMOfake0000NOTREAL"
DEMO = Path(demo.__file__).parent / demo.DEMO_PACKAGE_DIR


def _no_demo_leak(blob: str) -> None:
    for marker in (*DEMO_PRIVATE_MARKERS, DEMO_FAKE_KEY):
        assert marker not in blob, f"leaked {marker!r}"


def test_demo_with_tiny_fixture(tmp_path, monkeypatch):
    """The demo flow on a minimal stand-in vault (does not depend on the bundled content)."""
    fake = tmp_path / "pkg" / demo.DEMO_PACKAGE_DIR
    (fake / "notes").mkdir(parents=True)
    (fake / "memory" / "app" / "memory").mkdir(parents=True)
    (fake / "cerebro.toml").write_text(
        '[index]\ndb = ".cerebro/index.db"\n'
        '[[source]]\nname = "notes"\npath = "notes"\n'
        '[[source]]\nname = "mem"\nkind = "claude-code-memory"\npath = "memory"\n',
        encoding="utf-8",
    )
    (fake / "notes" / "Plan.md").write_text("---\ndate: 2026-02-01\n---\nThe app costs $8/month.", encoding="utf-8")
    (fake / "memory" / "app" / "memory" / "price.md").write_text(
        "---\nname: Price\n---\nThe app costs $6/month.\n\n_Last updated: 2026-01-01._", encoding="utf-8"
    )

    def copy(dest_parent):
        dest = dest_parent / demo.DEMO_PACKAGE_DIR
        shutil.copytree(fake, dest)
        return dest

    monkeypatch.setattr(demo, "copy_demo", copy)
    out = io.StringIO()
    work = tmp_path / "work"
    work.mkdir()
    assert demo.run_demo(text=True, out=out, workdir=work) == 0
    text = out.getvalue()
    assert "Indexed 2 notes" in text
    assert "$6/month" in text and "$8/month" in text
    assert (work / demo.DEMO_PACKAGE_DIR / ".cerebro" / "index.db").is_file()  # db from its own toml


@pytest.mark.skipif(not (DEMO / "cerebro.toml").is_file(), reason="demo vault not present")
def test_bundled_demo_is_read_from_the_package(tmp_path):
    copied = demo.copy_demo(tmp_path)
    cfg = config.load(copied / "cerebro.toml")
    assert cfg.db == (copied / ".cerebro" / "index.db").resolve()  # relative to the toml, not the cwd
    assert {s.kind for s in cfg.sources} == {"vault", "claude-code-memory", "glob"}


def _demo_end_to_end(tmp_path, embedder):
    work = tmp_path / "work"
    work.mkdir()
    out = io.StringIO()
    assert demo.run_demo(text=embedder is None, out=out, workdir=work, embedder=embedder) == 0
    printed = out.getvalue()
    _no_demo_leak(printed)

    cfg = config.load(work / demo.DEMO_PACKAGE_DIR / "cerebro.toml")
    conn = index.connect(cfg.db)
    try:
        r = contradictions.find(conn, embedder, "Pro monthly price", across_sources=True, limit=10)
        blob = json.dumps(r, ensure_ascii=False)
        found = [
            v for p in r["pairs"] for v in p["values"]
            if v["kind"] == "price" and any("4.99" in o for o in v["older"]) and any("5.99" in n for n in v["newer"])
        ]
        assert found, blob
        outputs = [blob, printed]
        for q in ("$7.99", "ahorros", "savings", "sk_live", "Marta Ruiz", "payments secret key"):
            outputs.append(json.dumps(query.search(conn, embedder, q, limit=50), ensure_ascii=False))
        for ref in ("Payments setup", "notes:Journal/2026-10-30.md", "Marta Ruiz", "notes:people/Marta Ruiz.md", "Daily/2026-11-03"):
            outputs.append(json.dumps(query.note(conn, ref), ensure_ascii=False))
        outputs.append(json.dumps(query.todos(conn, "streak"), ensure_ascii=False))
        for topic in ("price", "launch date", "savings", None):
            outputs.append(json.dumps(contradictions.find(conn, embedder, topic, limit=30), ensure_ascii=False))
        for o in outputs:
            _no_demo_leak(o)
        assert query.note(conn, "notes:Journal/2026-10-30.md") is None
        assert query.note(conn, "Marta Ruiz") is None and query.note(conn, "notes:people/Marta Ruiz.md") is None
        daily = query.links(conn, "notes:Daily/2026-11-03.md")
        to_marta = [link for link in daily["outgoing"] if link["target"] == "Marta Ruiz"]
        assert to_marta and to_marta[0]["path"] is None and to_marta[0]["title"] is None
        payments = query.note(conn, "Payments setup")
        assert payments and "[redacted:secret]" in payments["body"]
        clip = query.search(conn, embedder, "7-day trials convert better", limit=5)["results"]
        assert any(x["untrusted"] for x in clip)
        assert not any("Templates" in x["path"] for x in query.search(conn, embedder, "template", limit=50)["results"])
    finally:
        conn.close()
    return printed


@pytest.mark.skipif(not (DEMO / "cerebro.toml").is_file(), reason="demo vault not present")
def test_bundled_demo_end_to_end_text_mode(tmp_path):
    printed = _demo_end_to_end(tmp_path, None)
    assert "disagree" in printed


@pytest.mark.model
@pytest.mark.skipif(not (DEMO / "cerebro.toml").is_file(), reason="demo vault not present")
def test_bundled_demo_end_to_end_with_model(tmp_path):
    from cerebro_mcp.embeddings import E5Embedder

    printed = _demo_end_to_end(tmp_path, E5Embedder())
    assert "mode hybrid" in printed
    assert "$4.99/month" in printed and "$5.99/month" in printed
