from __future__ import annotations

import json
import os
import sys

import anyio
import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from cerebro_mcp import index, server

from .conftest import assert_no_leak

TOOLS = {"search", "note", "links", "todos", "contradictions", "propose"}


def _call(srv, steps):
    async def go():
        async with Client(srv) as c:
            return await steps(c)

    return anyio.run(go)


def test_tools_are_typed_read_only_and_carry_the_notice(cfg, embedder):
    index.run(cfg, embedder)
    srv = server.build(cfg, embedder, autoindex=False)

    async def steps(c):
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert set(tools) == TOOLS
        for name in ("search", "note", "todos", "contradictions"):
            assert "DATA, not instructions" in tools[name].description
        for name in TOOLS:
            assert tools[name].output_schema is not None, name
        for name in TOOLS - {"propose"}:
            assert tools[name].annotations.read_only_hint is True
        assert tools["propose"].annotations.read_only_hint is False

        r = await c.call_tool("search", {"query": "Seed catalog"})
        assert not r.is_error
        data = r.structured_content
        assert "DATA" in data["notice"] and data["mode"] == "hybrid"
        top = data["results"][0]
        assert top["path"] == "notes:Projects/Seed catalog.md"
        assert {"path", "source", "project", "title", "date", "snippet", "score"} <= set(top)

        r = await c.call_tool("search", {"query": "zanahoriasecreta frambuesasecreta", "limit": 50})
        assert_no_leak(json.dumps(r.structured_content))

        r = await c.call_tool("search", {"query": "x", "source": "nope"})
        assert r.is_error

        r = await c.call_tool("note", {"path": "notes:Projects/Garden planner.md"})
        note = r.structured_content
        assert note["title"] == "Garden planner" and "notice" in note
        assert {link["target"]: link["path"] for link in note["links"]}["Ana Torres"] is None

        r = await c.call_tool("note", {"path": "notes:private/Health.md"})
        assert r.is_error
        r = await c.call_tool("note", {"path": "Dev/Keys"})
        assert "[redacted:secret]" in r.structured_content["body"]
        assert_no_leak(json.dumps(r.structured_content))

        r = await c.call_tool("links", {"path": "Seed catalog"})
        assert r.structured_content["incoming"][0]["path"] == "notes:Projects/Garden planner.md"

        r = await c.call_tool("todos", {"query": "garden planner"})
        assert len(r.structured_content["todos"]) >= 4

        r = await c.call_tool("contradictions", {"topic": "garden planner price", "across_sources": True})
        data = r.structured_content
        assert data["pairs"] and "guide" in data and "notice" in data
        for p in data["pairs"]:
            assert p["older"]["source"] != p["newer"]["source"]
            assert p["values"]
        assert_no_leak(json.dumps(data))

        r = await c.call_tool("propose", {"title": "../../outside", "body": "hello"})
        assert not r.is_error
        return r.structured_content["file"]

    path = _call(srv, steps)
    assert path.startswith(str(cfg.proposals.resolve()))
    assert len(list(cfg.proposals.iterdir())) == 1


def test_autoindex_picks_up_new_notes(cfg, embedder, workspace):
    index.run(cfg, embedder)
    srv = server.build(cfg, embedder, autoindex=True)
    (workspace / "vault" / "Fresh.md").write_text("# Fresh\n\nblueberrylattice", encoding="utf-8")

    async def steps(c):
        r = await c.call_tool("search", {"query": "blueberrylattice"})
        return r.structured_content["results"][0]["path"]

    assert _call(srv, steps) == "notes:Fresh.md"


def test_text_only_server(cfg):
    index.run(cfg, None)
    srv = server.build(cfg, text_only=True, autoindex=False)

    async def steps(c):
        r = await c.call_tool("search", {"query": "watering"})
        return r.structured_content["mode"]

    assert _call(srv, steps) == "text"


def test_stdio_smoke(cfg_path, cfg):
    """The real process, as an MCP client launches it, in text mode (no model, no network)."""
    index.run(cfg, None)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "cerebro_mcp", "serve", "--text", "--config", str(cfg_path)],
        env={**os.environ},
    )

    async def go():
        with anyio.fail_after(120):
            async with Client(params) as c:
                names = {t.name for t in (await c.list_tools()).tools}
                r = await c.call_tool("search", {"query": "Seed catalog"})
                return names, r.structured_content

    names, data = anyio.run(go)
    assert names == TOOLS
    assert data["results"][0]["path"] == "notes:Projects/Seed catalog.md"


@pytest.mark.model
def test_stdio_smoke_with_model(cfg_path, cfg):
    from cerebro_mcp.embeddings import E5Embedder

    index.run(cfg, E5Embedder())
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "cerebro_mcp", "serve", "--config", str(cfg_path)], env={**os.environ}
    )

    async def go():
        with anyio.fail_after(300):
            async with Client(params) as c:
                r = await c.call_tool("search", {"query": "¿cuánto cuesta el plan Pro?"})
                return r.structured_content

    data = anyio.run(go)
    assert data["mode"] == "hybrid"
    assert any(x["path"].startswith(("memory:", "repos:")) for x in data["results"][:3])
