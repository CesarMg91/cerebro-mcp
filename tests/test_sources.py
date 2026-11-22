from __future__ import annotations

import pytest

from cerebro_mcp import sources
from cerebro_mcp.sources import glob_match


def _ids(cfg, name):
    return [d.id for d in sources.documents(cfg.source(name))]


def test_vault_lists_markdown_skips_hidden_and_excluded(cfg):
    ids = _ids(cfg, "notes")
    assert "notes:Projects/Garden planner.md" in ids
    assert "notes:Inbox.md" in ids
    assert "notes:private/Health.md" in ids  # listed; privacy is decided when parsing
    assert not any(i.startswith("notes:Templates/") for i in ids)
    assert not any(".obsidian" in i for i in ids)
    assert all(i.endswith(".md") for i in ids)
    assert len(ids) == len(set(ids))


def test_claude_code_memory(cfg):
    docs = list(sources.documents(cfg.source("memory")))
    ids = [d.id for d in docs]
    assert ids == [
        "memory:garden-app/memory/pricing.md",
        "memory:garden-app/memory/stack.md",
        "memory:weather-bot/memory/notes.md",
    ]  # MEMORY.md and hidden project folders skipped
    assert {d.project for d in docs} == {"garden-app", "weather-bot"}


def test_glob_kind(cfg):
    docs = list(sources.documents(cfg.source("repos")))
    ids = [d.id for d in docs]
    assert set(ids) == {
        "repos:garden-app/AGENTS.md",
        "repos:garden-app/docs/dev/handoff-2025-05-01.md",
        "repos:weather-bot/docs/setup.md",
    }
    assert {d.project for d in docs} == {"garden-app", "weather-bot"}


def test_missing_folder_yields_nothing(cfg, tmp_path):
    from dataclasses import replace

    src = replace(cfg.source("notes"), path=tmp_path / "nope")
    assert list(sources.documents(src)) == []


@pytest.mark.parametrize(
    "rel, pattern, expected",
    [
        ("Templates/Daily.md", "Templates/**", True),
        ("Templates/Daily.md", "templates", True),
        ("Projects/Templates.md", "Templates/**", False),
        ("a/docs/x.md", "*/docs/**/*.md", True),
        ("a/docs/deep/er/x.md", "*/docs/**/*.md", True),
        ("a/b/docs/x.md", "*/docs/**/*.md", False),
        ("a/AGENTS.md", "*/AGENTS.md", True),
        ("AGENTS.md", "*/AGENTS.md", False),
        ("x.md", "**/*.md", True),
    ],
)
def test_glob_match(rel, pattern, expected):
    assert glob_match(rel, pattern) is expected


def test_split_id():
    assert sources.split_id("notes:Projects/A.md") == ("notes", "Projects/A.md")
    assert sources.split_id("no id here") is None
