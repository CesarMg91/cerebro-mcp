"""Command line: init, index, search, contradictions, serve, doctor, demo."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import textwrap
from pathlib import Path

from . import __version__
from . import config as config_mod
from .config import Config, ConfigError


def _utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def _err(msg: str) -> None:
    print(f"cerebro: {msg}", file=sys.stderr)


def _embedder(cfg: Config, text: bool):
    if text:
        return None
    from .embeddings import E5Embedder

    return E5Embedder(cfg.model)


def _load(args) -> Config:
    return config_mod.load(getattr(args, "config", None))


# ---------- init ----------


def cmd_init(args) -> int:
    target = Path(args.config).expanduser() if getattr(args, "config", None) else None
    if target is None:
        import os

        env = os.environ.get("CEREBRO_CONFIG")
        target = Path(env).expanduser() if env else config_mod.user_config_file()
    if target.exists() and not args.force:
        _err(f"{target} already exists; not overwriting it (use --force to replace it)")
        return 1
    vault = Path(args.vault).expanduser().resolve() if args.vault else None
    if vault is not None and not vault.is_dir():
        _err(f"warning: vault folder does not exist yet: {vault}")
    memory = None
    if not args.no_agent_memory:
        candidate = Path.home() / ".claude" / "projects"
        if candidate.is_dir():
            memory = candidate
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(config_mod.starter(vault, memory), encoding="utf-8", newline="\n")
    print(f"wrote {target}")
    if vault:
        print(f"  source notes         -> {vault}")
    if memory:
        print(f"  source claude-memory -> {memory}")
    if not vault and not memory:
        print("  no sources yet: edit the file and add a [[source]]")
    print("next: cerebro index")
    return 0


# ---------- index ----------


def cmd_index(args) -> int:
    from . import index

    cfg = _load(args)
    summary = index.run(cfg, _embedder(cfg, args.text), full=args.full)
    for w in summary.warnings:
        _err(f"warning: {w}")
    print(summary)
    for name, n in summary.by_source.items():
        print(f"  {name:<20} {n:>6} files")
    print(f"index: {cfg.db}")
    return 0


# ---------- search ----------


def _one_line(text: str, width: int = 160) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def cmd_search(args) -> int:
    from . import index, query

    cfg = _load(args)
    if not cfg.db.exists():
        _err("no index yet: run `cerebro index` first")
        return 1
    conn = index.connect(cfg.db)
    try:
        r = query.search(
            conn,
            _embedder(cfg, args.text),
            args.query,
            hidden_scopes=cfg.privacy.hidden_scopes,
            source=args.source,
            scope=args.scope,
            type=args.type,
            since=args.since,
            until=args.until,
            limit=args.limit,
        )
    except query.QueryError as e:
        _err(str(e))
        return 2
    finally:
        conn.close()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print(f"mode: {r['mode']}")
    if not r["results"]:
        print("no results")
    for i, x in enumerate(r["results"], 1):
        where = " · ".join(v for v in (x["source"], x["project"], x["date"]) if v)
        flag = "  [untrusted]" if x["untrusted"] else ""
        print(f"{i:>2}. {x['title']}  [{where}]{flag}")
        print(f"    {x['path']}  ({'+'.join(x['signals'])} {x['score']})")
        print(f"    {_one_line(x['snippet'])}")
    return 0


# ---------- contradictions ----------


def format_pairs(pairs: list[dict]) -> str:
    out = []
    for i, p in enumerate(pairs, 1):
        headline = "; ".join(
            f"{v['kind']}: {' / '.join(v['older'])}  ->  {' / '.join(v['newer'])}" for v in p["values"]
        )
        out.append(f"{i}. {headline}")
        for label in ("older", "newer"):
            s = p[label]
            flag = "  [untrusted]" if s["untrusted"] else ""
            out.append(f"   {label:<5}  {s['date'] or '----------'}  {s['path']}{flag}")
            out.append(textwrap.indent(_one_line(s["snippet"], 150), "                      "))
        out.append("")
    return "\n".join(out).rstrip()


def cmd_contradictions(args) -> int:
    from . import contradictions, index, query

    cfg = _load(args)
    if not cfg.db.exists():
        _err("no index yet: run `cerebro index` first")
        return 1
    conn = index.connect(cfg.db)
    try:
        r = contradictions.find(
            conn,
            _embedder(cfg, args.text),
            args.topic,
            hidden_scopes=cfg.privacy.hidden_scopes,
            scope=args.scope,
            across_sources=args.across_sources,
            limit=args.limit,
        )
    except query.QueryError as e:
        _err(str(e))
        return 2
    finally:
        conn.close()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print(f"mode: {r['mode']}")
    print(format_pairs(r["pairs"]) if r["pairs"] else "no contradictions found on that topic")
    return 0


# ---------- serve ----------


def cmd_serve(args) -> int:
    from .server import serve

    serve(_load(args), text_only=args.text)
    return 0


# ---------- doctor ----------


def _age(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        delta = dt.datetime.now() - dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} h ago"
    return f"{minutes // (60 * 24)} days ago"


def cmd_doctor(args) -> int:
    import platform

    from . import embeddings, index, sources

    ok = True
    print(f"cerebro-mcp {__version__} · Python {platform.python_version()} · {platform.system()}")
    found = config_mod.find(getattr(args, "config", None))
    if found is None or not found.is_file():
        print(f"[!!] config: not found{f' ({found})' if found else ''}. Run `cerebro init`.")
        return 1
    try:
        cfg = config_mod.load(found)
    except ConfigError as e:
        print(f"[!!] config: {e}")
        return 1
    print(f"[ok] config: {cfg.path}")
    if not cfg.sources:
        print("[!!] no sources configured")
        ok = False
    for s in cfg.sources:
        if not s.path.is_dir():
            print(f"[!!] source {s.name} ({s.kind}): folder not found: {s.path}")
            ok = False
            continue
        n = sources.count(s)
        mark = "ok" if n else "--"
        print(f"[{mark}] source {s.name} ({s.kind}, scope {s.scope}): {n} files in {s.path}")
    if cfg.privacy.hidden_scopes:
        print(f"[ok] hidden scopes: {', '.join(cfg.privacy.hidden_scopes)}")
    print(f"[ok] redaction packs: {', '.join(cfg.privacy.redact) or 'none'}")
    if cfg.db.exists():
        conn = index.connect(cfg.db)
        try:
            n_notes = conn.execute("select count(*) from notes").fetchone()[0]
            n_private = conn.execute("select count(*) from notes where private = 1").fetchone()[0]
            vectors = index.has_vectors(conn)
            when = index.get_meta(conn, "indexed_at")
            model = index.get_meta(conn, "model")
            vec = conn.vec
        finally:
            conn.close()
        size = cfg.db.stat().st_size / 1024
        print(
            f"[ok] index: {cfg.db} ({size:.0f} KB) · {n_notes} notes ({n_private} private) · "
            f"updated {_age(when)} · {'vectors: ' + model if vectors and model else 'text only'}"
        )
        print(f"[{'ok' if vec else '--'}] sqlite-vec: {'loaded' if vec else 'not loadable here (numpy fallback)'}")
    else:
        print(f"[--] index: not built yet ({cfg.db}). Run `cerebro index`.")
    spec = embeddings.spec(cfg.model)
    if embeddings.is_cached(cfg.model):
        print(f"[ok] model: {spec.repo} ({spec.file}) cached in {embeddings.cache_dir()}")
    else:
        print(
            f"[--] model: {spec.repo} not cached yet (~{spec.size_mb} MB, downloaded on the first "
            f"`cerebro index`; until then use --text). Cache: {embeddings.cache_dir()}"
        )
    return 0 if ok else 1


# ---------- demo ----------


def cmd_demo(args) -> int:
    from .demo import run_demo

    return run_demo(keep=args.keep, text=args.text)


# ---------- parser ----------


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", default=argparse.SUPPRESS, help="path to cerebro.toml")

    ap = argparse.ArgumentParser(
        prog="cerebro",
        description="A local, read-only index over your Markdown notes and your AI agents' memories, served over MCP.",
    )
    ap.add_argument("--version", action="version", version=f"cerebro-mcp {__version__}")
    ap.add_argument("--config", default=None, help="path to cerebro.toml")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", parents=[common], help="write a starter cerebro.toml")
    p.add_argument("--vault", help="your notes folder (Markdown / Obsidian)")
    p.add_argument("--no-agent-memory", action="store_true", help="do not add ~/.claude/projects")
    p.add_argument("--force", action="store_true", help="overwrite an existing file")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("index", parents=[common], help="update the index (incremental by content hash)")
    p.add_argument("--full", action="store_true", help="delete the index and rebuild it")
    p.add_argument("--text", action="store_true", help="text only (FTS5), no embedding model")
    p.set_defaults(fn=cmd_index)

    p = sub.add_parser("search", parents=[common], help="hybrid search")
    p.add_argument("query")
    p.add_argument("--source")
    p.add_argument("--scope")
    p.add_argument("--type")
    p.add_argument("--since", help="YYYY, YYYY-MM or YYYY-MM-DD")
    p.add_argument("--until", help="YYYY, YYYY-MM or YYYY-MM-DD")
    p.add_argument("--text", action="store_true", help="text only (FTS5), no embedding model")
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("contradictions", parents=[common], help="pairs of fragments that state different values")
    p.add_argument("topic")
    p.add_argument("--across-sources", action="store_true", help="only pairs from different sources")
    p.add_argument("--scope")
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--text", action="store_true", help="text only, no embedding model")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_contradictions)

    p = sub.add_parser("serve", parents=[common], help="MCP server over stdio (clients launch it)")
    p.add_argument("--text", action="store_true", help="text only, no embedding model")
    p.set_defaults(fn=cmd_serve)

    p = sub.add_parser("doctor", parents=[common], help="check config, sources, index and model")
    p.set_defaults(fn=cmd_doctor)

    p = sub.add_parser("demo", help="index the bundled demo vault and show what disagrees")
    p.add_argument("--keep", action="store_true", help="keep the temp copy and print how to explore it")
    p.add_argument("--text", action="store_true", help="text only, no embedding model")
    p.set_defaults(fn=cmd_demo)
    return ap


def main(argv: list[str] | None = None) -> int:
    _utf8()
    args = build_parser().parse_args(argv)
    try:
        return args.fn(args)
    except ConfigError as e:
        _err(str(e))
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
