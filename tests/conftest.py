from __future__ import annotations

import hashlib
import re
import shutil
import textwrap
from pathlib import Path

import numpy as np
import pytest

from cerebro_mcp import config, index
from cerebro_mcp.text import fold

FIXTURES = Path(__file__).parent / "fixtures"

# Words that live only in private or excluded files: they must never come out.
PRIVATE_MARKERS = ("zanahoriasecreta", "frambuesasecreta", "personmarker", "$99", "templatemarker")
FAKE_SECRETS = ("sk-proj-FAKEfakeFAKEfake0000000000", "4111 1111 1111 1111")


class FakeEmbedder:
    """Hashed bag of words -> 384 dims. Deterministic, no model, counts calls."""

    name = "fake-bow-384"
    dims = 384

    def __init__(self, name: str | None = None):
        if name:
            self.name = name
        self.embedded: list[str] = []

    def _vector(self, text: str) -> np.ndarray:
        v = np.zeros(self.dims, dtype=np.float32)
        for word in re.findall(r"\w+", fold(text)):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dims] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def passages(self, texts):
        self.embedded.extend(texts)
        if not texts:
            return np.zeros((0, self.dims), dtype=np.float32)
        return np.stack([self._vector(t) for t in texts])

    def query(self, text):
        return self._vector(text)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Tests never read the real user config or run from a folder with a cerebro.toml."""
    monkeypatch.delenv("CEREBRO_CONFIG", raising=False)
    monkeypatch.setattr(config, "user_config_file", lambda: tmp_path / "_user_config" / "cerebro.toml")
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def workspace(tmp_path) -> Path:
    """A writable copy of the fixtures."""
    dest = tmp_path / "ws"
    shutil.copytree(FIXTURES, dest)
    return dest


def write_config(ws: Path, extra_privacy: str = "", sources: str | None = None) -> Path:
    if sources is None:
        sources = """
            [[source]]
            name = "notes"
            kind = "vault"
            path = "vault"
            scope = "personal"
            exclude = ["Templates/**"]

            [[source]]
            name = "memory"
            kind = "claude-code-memory"
            path = "memory"
            scope = "work"

            [[source]]
            name = "repos"
            kind = "glob"
            path = "repos"
            include = ["*/docs/**/*.md", "*/AGENTS.md"]
            scope = "work"
        """
    text = textwrap.dedent(
        """
        [index]
        db = ".cerebro/index.db"
        proposals = ".cerebro/proposals"
        """
    ) + textwrap.dedent(sources) + textwrap.dedent(
        """
        [privacy]
        private_folders = ["private", "people"]
        private_frontmatter = "private"
        redact = ["secrets", "cards"]
        """
    ) + textwrap.dedent(extra_privacy)
    path = ws / "cerebro.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.fixture
def cfg_path(workspace) -> Path:
    return write_config(workspace)


@pytest.fixture
def cfg(cfg_path) -> config.Config:
    return config.load(cfg_path)


@pytest.fixture
def embedder() -> FakeEmbedder:
    return FakeEmbedder()


@pytest.fixture
def indexed(cfg, embedder):
    index.run(cfg, embedder)
    conn = index.connect(cfg.db)
    yield conn
    conn.close()


def assert_no_leak(blob: str) -> None:
    for marker in PRIVATE_MARKERS + FAKE_SECRETS:
        assert marker not in blob, f"leaked {marker!r}"
