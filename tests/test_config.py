from __future__ import annotations

from pathlib import Path

import pytest

from cerebro_mcp import config
from cerebro_mcp.config import ConfigError


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_full_schema_and_relative_paths(tmp_path):
    p = _write(
        tmp_path / "conf" / "cerebro.toml",
        """
[index]
db = "data/index.db"
proposals = "data/proposals"

[[source]]
name = "notes"
kind = "vault"
path = "../Notes"
scope = "personal"
exclude = ["Templates/**"]

[[source]]
name = "claude-memory"
kind = "claude-code-memory"
path = "~/somewhere"

[[source]]
name = "handoffs"
kind = "glob"
path = "$CODE_ROOT/repos"
include = ["*/docs/**/*.md", "*/AGENTS.md"]
scope = "work"

[privacy]
private_folders = ["private", "people"]
private_frontmatter = "secret"
redact = ["secrets", "cards", "mx"]
hidden_scopes = ["work"]
""",
    )
    import os

    os.environ["CODE_ROOT"] = str(tmp_path / "code")
    try:
        cfg = config.load(p)
    finally:
        del os.environ["CODE_ROOT"]
    base = (tmp_path / "conf").resolve()
    assert cfg.path == p.resolve()
    assert cfg.db == base / "data" / "index.db"
    assert cfg.proposals == base / "data" / "proposals"
    notes, memory, handoffs = cfg.sources
    assert notes.path == (tmp_path / "Notes").resolve()
    assert notes.scope == "personal" and notes.exclude == ("Templates/**",)
    assert memory.kind == "claude-code-memory" and memory.scope == "default"
    assert memory.path == Path.home() / "somewhere"
    assert handoffs.path == (tmp_path / "code" / "repos").resolve()
    assert handoffs.include == ("*/docs/**/*.md", "*/AGENTS.md")
    assert cfg.privacy.private_frontmatter == "secret"
    assert cfg.privacy.redact == ("secrets", "cards", "mx")
    assert cfg.privacy.hidden_scopes == ("work",)


def test_defaults(tmp_path):
    p = _write(tmp_path / "cerebro.toml", '[[source]]\nname = "n"\npath = "notes"\n')
    cfg = config.load(p)
    assert cfg.db == config.default_db()
    assert cfg.proposals == config.default_proposals()
    assert cfg.sources[0].kind == "vault"
    assert cfg.privacy.private_folders == ("private",)
    assert cfg.privacy.redact == ("secrets", "cards")
    assert cfg.privacy.hidden_scopes == ()


def test_glob_default_include(tmp_path):
    p = _write(tmp_path / "cerebro.toml", '[[source]]\nname = "g"\nkind = "glob"\npath = "x"\n')
    assert config.load(p).sources[0].include == ("**/*.md",)


@pytest.mark.parametrize(
    "body, message",
    [
        ('[[source]]\nname = "a"\npath = "x"\n[[source]]\nname = "a"\npath = "y"\n', "used twice"),
        ('[[source]]\nname = "a"\nkind = "dropbox"\npath = "x"\n', "kind must be one of"),
        ('[[source]]\nname = "a"\n', "needs a path"),
        ('[[source]]\npath = "x"\n', "needs a name"),
        ('[[source]]\nname = "a:b"\npath = "x"\n', "cannot contain"),
        ('[[source]]\nname = "a"\npath = "x"\nfolder = "y"\n', "unknown keys"),
        ('[privacy]\nredact = ["klingon"]\n', "unknown pack"),
        ("this is = = not toml", "invalid TOML"),
    ],
)
def test_invalid(tmp_path, body, message):
    p = _write(tmp_path / "cerebro.toml", body)
    with pytest.raises(ConfigError, match=message):
        config.load(p)


def test_lookup_order(tmp_path, monkeypatch):
    user = _write(tmp_path / "_user_config" / "cerebro.toml", "")
    assert config.find() == user  # only the user config dir has one

    here = _write(tmp_path / "cerebro.toml", "")
    assert config.find() == here  # ./cerebro.toml wins over the user dir

    env = _write(tmp_path / "env" / "cerebro.toml", "")
    monkeypatch.setenv("CEREBRO_CONFIG", str(env))
    assert config.find() == env  # $CEREBRO_CONFIG wins over ./

    explicit = _write(tmp_path / "explicit.toml", "")
    assert config.find(explicit) == explicit  # --config wins over everything


def test_missing_config_message(tmp_path):
    with pytest.raises(ConfigError, match="cerebro init"):
        config.load()


def test_starter_is_valid_toml(tmp_path):
    text = config.starter(tmp_path / "My Notes", tmp_path / ".claude" / "projects")
    p = _write(tmp_path / "cerebro.toml", text)
    cfg = config.load(p)
    assert [s.name for s in cfg.sources] == ["notes", "claude-memory"]
    assert cfg.sources[0].path == tmp_path / "My Notes"
    assert cfg.privacy.private_folders == ("private", "people")
