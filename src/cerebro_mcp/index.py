"""The index: one disposable SQLite file with FTS5 and sqlite-vec.

Delete it and nothing is lost: the Markdown files are the truth. Indexing is
incremental by content hash; a source removed from the config leaves the index
on the next run.

Private notes are stored as id + hash only (no title, no text, no vectors).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import notes, redact, sources
from .config import Config, Source
from .embeddings import Embedder, ModelUnavailable
from .text import fold, sha256

log = logging.getLogger("cerebro")

# Bump when parsing changes in a way that should re-parse every file.
PARSER_VERSION = "2"
# Bump when the tables or the FTS tokenizer change: the index is rebuilt.
SCHEMA_VERSION = "1"

SCHEMA = """
create table if not exists meta (
    key   text primary key,
    value text
);
create table if not exists notes (
    id             integer primary key,
    doc_id         text unique not null,   -- "<source>:<relative path>"
    source         text not null,
    kind           text not null,
    scope          text not null,
    project        text,
    rel_path       text not null,
    file           text not null,          -- absolute path on disk
    title          text not null,          -- '' for private notes
    type           text,
    status         text,
    date           text,
    private        integer not null,
    untrusted      integer not null default 0,
    frontmatter    text,                   -- null for private notes
    body           text,                   -- null for private notes
    hash           text not null,
    settings       text not null,
    redacted_lines integer not null default 0
);
create index if not exists notes_filters on notes (private, scope, source, type, date);
create table if not exists chunks (
    id        integer primary key,
    note_id   integer not null references notes(id) on delete cascade,
    ord       integer not null,
    section   text,
    text      text not null,
    embedding blob                         -- float32[384], normalized
);
create index if not exists chunks_note on chunks (note_id);
create virtual table if not exists chunks_fts using fts5 (
    title, text,
    tokenize = 'porter unicode61 remove_diacritics 2'
);
create table if not exists links (
    note_id   integer not null references notes(id) on delete cascade,
    target    text not null,               -- as written inside [[...]]
    target_id text                         -- doc_id of the resolved note, or null
);
create index if not exists links_note on links (note_id);
create index if not exists links_target on links (target_id);
create table if not exists todos (
    note_id integer not null references notes(id) on delete cascade,
    line    integer not null,
    text    text not null,
    done    integer not null
);
create index if not exists todos_note on todos (note_id);
"""


class Connection(sqlite3.Connection):
    """A connection that remembers whether sqlite-vec could be loaded."""

    vec = False


def connect(db: Path) -> Connection:
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db, timeout=30, check_same_thread=False, factory=Connection)
    conn.row_factory = sqlite3.Row
    try:
        import sqlite_vec

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.vec = True
    except Exception as e:  # some Python builds cannot load extensions: numpy fallback
        log.debug("sqlite-vec not available (%s); vector search falls back to numpy", e)
    conn.execute("pragma foreign_keys = on")
    conn.execute("pragma journal_mode = wal")
    conn.execute("pragma busy_timeout = 30000")
    conn.executescript(SCHEMA)
    return conn


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("select value from meta where key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "insert into meta (key, value) values (?, ?) on conflict(key) do update set value = excluded.value",
        (key, value),
    )


def delete_index(db: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)


@dataclass
class Summary:
    notes: int = 0
    private: int = 0
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0
    embedded_chunks: int = 0
    redacted_lines: int = 0
    by_source: dict[str, int] = field(default_factory=dict)
    mode: str = "hybrid"
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def __str__(self) -> str:
        line = (
            f"{self.notes} notes ({self.private} private, stored without text) · {self.added} added · "
            f"{self.updated} updated · {self.unchanged} unchanged · {self.removed} removed · "
            f"{self.embedded_chunks} chunks embedded · {self.redacted_lines} lines redacted · "
            f"{self.mode} · {self.seconds:.1f} s"
        )
        return line


def _settings(src: Source, cfg: Config, project: str | None) -> str:
    p = cfg.privacy
    return sha256(
        json.dumps(
            [PARSER_VERSION, src.kind, src.scope, project, sorted(fold(f) for f in p.private_folders),
             p.private_frontmatter, sorted(p.redact)],
            ensure_ascii=False,
        ).encode("utf-8")
    )


def _mtime_date(path: Path) -> str | None:
    try:
        return dt.date.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


@dataclass
class Prepared:
    parsed: notes.ParsedNote
    redacted_lines: int


def prepare(doc: sources.Document, data: bytes, cfg: Config) -> Prepared:
    """Redact, then parse. A file with many redacted lines becomes private."""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    clean, n, why = redact.redact(text, cfg.privacy.redact)
    if n:
        log.info("%s: %d line(s) redacted (%s)", doc.id, n, ", ".join(why))
    parsed = notes.parse(
        doc.rel,
        clean,
        kind=doc.source.kind,
        private_folders=cfg.privacy.private_folders,
        private_key=cfg.privacy.private_frontmatter,
    )
    if n >= redact.LINES_TO_MAKE_PRIVATE and not parsed.private:
        parsed = notes.ParsedNote(title=parsed.title, private=True)
    if not parsed.private and parsed.date is None:
        parsed.date = _mtime_date(doc.file)
    return Prepared(parsed, n)


def _delete_note(conn: sqlite3.Connection, note_id: int) -> None:
    conn.execute("delete from chunks_fts where rowid in (select id from chunks where note_id = ?)", (note_id,))
    conn.execute("delete from notes where id = ?", (note_id,))  # cascades to the rest


def _save(
    conn: sqlite3.Connection,
    doc: sources.Document,
    prep: Prepared,
    digest: str,
    settings: str,
    vectors: np.ndarray | None,
) -> None:
    n = prep.parsed
    private = n.private
    cur = conn.execute(
        """insert into notes (doc_id, source, kind, scope, project, rel_path, file, title, type, status,
               date, private, untrusted, frontmatter, body, hash, settings, redacted_lines)
           values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            doc.id,
            doc.source.name,
            doc.source.kind,
            doc.source.scope,
            doc.project or n.project,
            doc.rel,
            str(doc.file),
            "" if private else n.title,
            None if private else n.type,
            None if private else n.status,
            None if private else n.date,
            int(private),
            int(n.untrusted),
            None if private else json.dumps(n.frontmatter, ensure_ascii=False),
            None if private else n.body,
            digest,
            settings,
            prep.redacted_lines,
        ),
    )
    note_id = cur.lastrowid
    if private:
        return
    for i, (section, text) in enumerate(n.chunks):
        blob = vectors[i].astype(np.float32).tobytes() if vectors is not None else None
        cid = conn.execute(
            "insert into chunks (note_id, ord, section, text, embedding) values (?,?,?,?,?)",
            (note_id, i, section, text, blob),
        ).lastrowid
        conn.execute("insert into chunks_fts (rowid, title, text) values (?,?,?)", (cid, n.title, text))
    conn.executemany("insert into links (note_id, target) values (?, ?)", [(note_id, t) for t in n.links])
    conn.executemany(
        "insert into todos (note_id, line, text, done) values (?,?,?,?)",
        [(note_id, line, text, int(done)) for line, text, done in n.todos],
    )


def _resolve_links(conn: sqlite3.Connection) -> None:
    """[[Target]] -> doc id, the Obsidian way (by name or by path); same source first.

    Private notes are never link targets: a link to one stays unresolved.
    """
    by_key: dict[tuple[str, str], str] = {}
    by_title: dict[str, str] = {}
    for r in conn.execute("select doc_id, source, rel_path, title from notes where private = 0 order by doc_id"):
        rel = fold(r["rel_path"])
        no_ext = rel[:-3] if rel.endswith(".md") else rel
        for key in (rel, no_ext, no_ext.rsplit("/", 1)[-1], fold(r["title"])):
            by_key.setdefault((r["source"], key), r["doc_id"])
        by_title.setdefault(no_ext.rsplit("/", 1)[-1], r["doc_id"])
        by_title.setdefault(fold(r["title"]), r["doc_id"])
    changes = []
    for r in conn.execute(
        "select l.rowid, l.target, n.source from links l join notes n on n.id = l.note_id"
    ).fetchall():
        key = fold(r["target"]).removesuffix(".md")
        target = by_key.get((r["source"], key)) or by_title.get(key) or by_title.get(key.rsplit("/", 1)[-1])
        changes.append((target, r["rowid"]))
    conn.executemany("update links set target_id = ? where rowid = ?", changes)


def _backfill(conn: sqlite3.Connection, embedder: Embedder, batch: int = 64) -> int:
    rows = conn.execute(
        """select c.id, c.text from chunks c join notes n on n.id = c.note_id
           where c.embedding is null and n.private = 0 order by c.id"""
    ).fetchall()
    for i in range(0, len(rows), batch):
        part = rows[i : i + batch]
        vectors = embedder.passages([r["text"] for r in part])
        with conn:
            conn.executemany(
                "update chunks set embedding = ? where id = ?",
                [(v.astype(np.float32).tobytes(), r["id"]) for v, r in zip(vectors, part, strict=True)],
            )
    return len(rows)


def run(cfg: Config, embedder: Embedder | None, *, full: bool = False) -> Summary:
    """Bring the index up to date. `embedder=None` indexes text only (FTS5)."""
    start = time.perf_counter()
    summary = Summary()
    if full:
        delete_index(cfg.db)
    if embedder is not None:
        try:
            load = getattr(embedder, "load", None)
            if load:
                load()
        except ModelUnavailable as e:
            summary.warnings.append(str(e))
            embedder = None
    summary.mode = "hybrid" if embedder is not None else "text"

    conn = connect(cfg.db)
    if get_meta(conn, "schema") not in (None, SCHEMA_VERSION):
        conn.close()  # built by another version: rebuild from the Markdown
        delete_index(cfg.db)
        conn = connect(cfg.db)
    try:
        if embedder is not None and get_meta(conn, "model") not in (None, embedder.name):
            with conn:  # another model: its vectors are useless now
                conn.execute("update chunks set embedding = null")
        existing = {
            r["doc_id"]: (r["id"], r["hash"], r["settings"])
            for r in conn.execute("select id, doc_id, hash, settings from notes")
        }
        seen: set[str] = set()
        for src in cfg.sources:
            if not src.path.is_dir():
                summary.warnings.append(f"source {src.name!r}: folder not found: {src.path}")
                continue
            n_src = 0
            for doc in sources.documents(src):
                if doc.id in seen:
                    continue
                seen.add(doc.id)
                n_src += 1
                try:
                    data = doc.file.read_bytes()
                except OSError as e:
                    # Someone may be writing it right now: keep the previous version.
                    log.warning("could not read %s: %s", doc.file, e)
                    continue
                digest = sha256(data)
                settings = _settings(src, cfg, doc.project)
                previous = existing.get(doc.id)
                if previous and previous[1] == digest and previous[2] == settings:
                    summary.unchanged += 1
                    continue
                prep = prepare(doc, data, cfg)
                summary.redacted_lines += prep.redacted_lines
                vectors = None
                if embedder is not None and not prep.parsed.private:
                    vectors = embedder.passages([t for _, t in prep.parsed.chunks])
                    summary.embedded_chunks += len(prep.parsed.chunks)
                with conn:
                    if previous:
                        _delete_note(conn, previous[0])
                    _save(conn, doc, prep, digest, settings, vectors)
                if previous:
                    summary.updated += 1
                else:
                    summary.added += 1
            summary.by_source[src.name] = n_src

        with conn:
            for did, (note_id, _, _) in existing.items():
                if did not in seen:
                    _delete_note(conn, note_id)
                    summary.removed += 1
            _resolve_links(conn)
        if embedder is not None:
            summary.embedded_chunks += _backfill(conn, embedder)
        with conn:
            if embedder is not None:
                set_meta(conn, "model", embedder.name)
            set_meta(conn, "indexed_at", dt.datetime.now().isoformat(timespec="seconds"))
            set_meta(conn, "schema", SCHEMA_VERSION)
            set_meta(conn, "config", str(cfg.path) if cfg.path else "")
        summary.notes = conn.execute("select count(*) from notes").fetchone()[0]
        summary.private = conn.execute("select count(*) from notes where private = 1").fetchone()[0]
        summary.seconds = time.perf_counter() - start
        return summary
    finally:
        conn.close()


def has_vectors(conn: sqlite3.Connection) -> bool:
    return conn.execute("select 1 from chunks where embedding is not null limit 1").fetchone() is not None
