"""`cerebro demo`: copy the bundled demo vault to a temp dir, index it, show what disagrees."""

from __future__ import annotations

import importlib.resources
import shutil
import sys
import tempfile
from pathlib import Path

from . import config as config_mod
from . import contradictions, index

DEMO_PACKAGE_DIR = "demo_vault"
SHOWN = 3


def copy_demo(dest_parent: Path) -> Path:
    """Copy the installed demo vault into `dest_parent` and return the copy."""
    src = importlib.resources.files("cerebro_mcp") / DEMO_PACKAGE_DIR
    if not src.is_dir():
        raise FileNotFoundError("the demo vault is not installed with this package")
    dest = dest_parent / DEMO_PACKAGE_DIR
    with importlib.resources.as_file(src) as real:
        shutil.copytree(real, dest, ignore=shutil.ignore_patterns(".cerebro", "__pycache__"))
    return dest


def pick(pairs: list[dict], n: int = SHOWN) -> list[dict]:
    """The best pairs, preferring a different kind of value each time."""
    chosen, kinds = [], set()
    for p in pairs:
        k = p["values"][0]["kind"]
        if k not in kinds:
            chosen.append(p)
            kinds.add(k)
        if len(chosen) == n:
            return chosen
    for p in pairs:
        if p not in chosen:
            chosen.append(p)
        if len(chosen) == n:
            break
    return chosen


def run_demo(*, keep: bool = False, text: bool = False, out=None, embedder=None, workdir: Path | None = None) -> int:
    from .cli import format_pairs

    out = out or sys.stdout
    tmp = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix="cerebro-demo-"))
    try:
        vault = copy_demo(tmp)
        cfg = config_mod.load(vault / config_mod.FILENAME)
        if embedder is None and not text:
            from .embeddings import E5Embedder, is_cached

            embedder = E5Embedder(cfg.model)
            if not is_cached(cfg.model):
                print(f"Downloading the embedding model once ({embedder.spec.repo}, ~{embedder.spec.size_mb} MB)...",
                      file=out, flush=True)
        print(f"Demo vault copied to {vault}", file=out)
        summary = index.run(cfg, None if text else embedder)
        for w in summary.warnings:
            print(f"warning: {w}", file=out)
        print(
            f"Indexed {summary.notes} notes from {len(cfg.sources)} sources "
            f"({', '.join(s.name for s in cfg.sources)}): {summary.private} private (kept out of every "
            f"result), {summary.redacted_lines} line(s) redacted, mode {summary.mode}.",
            file=out,
        )
        conn = index.connect(cfg.db)
        try:
            r = contradictions.find(
                conn,
                None if summary.mode == "text" else embedder,
                None,
                hidden_scopes=cfg.privacy.hidden_scopes,
                across_sources=True,
                limit=25,
            )
        finally:
            conn.close()
        shown = pick(r["pairs"])
        print("", file=out)
        if not shown:
            print("No contradictions found.", file=out)
        else:
            print(f"Your notes and your agents disagree on {len(shown)} things (older -> newer):", file=out)
            print("", file=out)
            print(format_pairs(shown), file=out)
        print("", file=out)
        if keep:
            print("Explore it:", file=out)
            print(f'  cerebro search "precio de Pro" --config "{cfg.path}"', file=out)
            print(f'  cerebro contradictions "launch date" --across-sources --config "{cfg.path}"', file=out)
        else:
            print("Run it on your own notes: cerebro init --vault ~/path/to/notes && cerebro index", file=out)
        return 0
    finally:
        if not keep and workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)
