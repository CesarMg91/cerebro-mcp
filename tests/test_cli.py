from __future__ import annotations

import json
from pathlib import Path

from cerebro_mcp import cli, config

from .conftest import assert_no_leak


def run(capsys, *argv):
    code = cli.main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_init_writes_and_never_overwrites(capsys, tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    monkeypatch.setattr(Path, "home", lambda: home)
    vault = tmp_path / "Notes"
    vault.mkdir()
    target = tmp_path / "conf" / "cerebro.toml"

    code, out, _ = run(capsys, "init", "--vault", str(vault), "--config", str(target))
    assert code == 0 and "wrote" in out
    cfg = config.load(target)
    assert [s.name for s in cfg.sources] == ["notes", "claude-memory"]
    assert cfg.sources[1].path == home / ".claude" / "projects"

    target.write_text("# mine\n", encoding="utf-8")
    code, _, err = run(capsys, "init", "--vault", str(vault), "--config", str(target))
    assert code == 1 and "already exists" in err
    assert target.read_text(encoding="utf-8") == "# mine\n"

    code, _, _ = run(capsys, "init", "--no-agent-memory", "--force", "--config", str(target))
    assert code == 0
    assert config.load(target).sources == ()


def test_init_defaults_to_user_config_dir(capsys):
    code, out, _ = run(capsys, "init", "--no-agent-memory")
    assert code == 0
    assert config.user_config_file().is_file()


def test_index_search_contradictions(capsys, cfg_path):
    code, out, _ = run(capsys, "index", "--text", "--config", str(cfg_path))
    assert code == 0 and "16 notes" in out and "text" in out

    code, out, _ = run(capsys, "search", "Seed catalog", "--text", "--config", str(cfg_path))
    assert code == 0 and "notes:Projects/Seed catalog.md" in out

    code, out, _ = run(capsys, "search", "garden", "--text", "--json", "--source", "memory", "--config", str(cfg_path))
    data = json.loads(out)
    assert data["mode"] == "text" and all(r["source"] == "memory" for r in data["results"])

    code, out, _ = run(
        capsys, "contradictions", "garden planner price", "--across-sources", "--text", "--json",
        "--config", str(cfg_path),
    )
    data = json.loads(out)
    assert code == 0 and data["pairs"]
    assert_no_leak(out)

    code, out, _ = run(capsys, "contradictions", "garden planner price", "--text", "--config", str(cfg_path))
    assert "price:" in out and "older" in out and "newer" in out

    code, _, err = run(capsys, "search", "x", "--since", "soon", "--text", "--config", str(cfg_path))
    assert code == 2 and "invalid date" in err


def test_search_without_index(capsys, cfg_path):
    code, _, err = run(capsys, "search", "x", "--text", "--config", str(cfg_path))
    assert code == 1 and "cerebro index" in err


def test_missing_config(capsys):
    code, _, err = run(capsys, "index", "--text")
    assert code == 1 and "cerebro init" in err


def test_doctor(capsys, cfg_path, workspace, monkeypatch):
    monkeypatch.setenv("CEREBRO_MODEL_CACHE", str(workspace / "no-model-here"))
    code, out, _ = run(capsys, "doctor", "--config", str(cfg_path))
    assert code == 0
    assert "[ok] config" in out
    assert "source notes (vault, scope personal): 10 files" in out
    assert "source memory (claude-code-memory, scope work): 3 files" in out
    assert "source repos (glob, scope work): 3 files" in out
    assert "index: not built yet" in out
    assert "not cached yet" in out

    run(capsys, "index", "--text", "--config", str(cfg_path))
    code, out, _ = run(capsys, "doctor", "--config", str(cfg_path))
    assert "16 notes (3 private)" in out and "text only" in out and "updated 0 min ago" in out

    text = cfg_path.read_text(encoding="utf-8").replace('path = "repos"', 'path = "missing-repos"')
    cfg_path.write_text(text, encoding="utf-8")
    code, out, _ = run(capsys, "doctor", "--config", str(cfg_path))
    assert code == 1 and "folder not found" in out


def test_doctor_without_config(capsys):
    code, out, _ = run(capsys, "doctor")
    assert code == 1 and "cerebro init" in out
