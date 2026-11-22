"""Queries over the index. The egress rule lives HERE, in the SQL.

Every query goes through `egress()`: `private = 0` always, and a hidden scope
only when that scope is asked for explicitly (and then only that scope). A
WHERE clause is a guarantee; an instruction in a prompt is a suggestion.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

import numpy as np

from .embeddings import Embedder, ModelUnavailable
from .text import STOPWORDS, WORD, fold

RRF_K = 60
CANDIDATES = 50  # per signal, before fusion
MAX_SNIPPET = 700
MAX_LIMIT = 50


class QueryError(ValueError):
    """Invalid argument: returned to the agent as a readable error."""


def egress(scope: str | None, hidden_scopes: tuple[str, ...] = (), alias: str = "n") -> tuple[str, list]:
    """The WHERE that is never missing."""
    where = [f"{alias}.private = 0"]
    params: list = []
    if scope:
        where.append(f"{alias}.scope = ?")
        params.append(scope.strip())
    elif hidden_scopes:
        where.append(f"{alias}.scope not in ({','.join('?' * len(hidden_scopes))})")
        params.extend(hidden_scopes)
    return " and ".join(where), params


def date_bound(value: str | None, end: bool) -> str | None:
    """'2019' -> '2019-01-01' (since) or '2019-12-31' (until). Also '2019-03'."""
    if not value:
        return None
    value = value.strip()
    if re.fullmatch(r"\d{4}", value):
        return f"{value}-12-31" if end else f"{value}-01-01"
    if re.fullmatch(r"\d{4}-\d{2}", value):
        return f"{value}-31" if end else f"{value}-01"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    raise QueryError(f"invalid date {value!r} (use YYYY, YYYY-MM or YYYY-MM-DD)")


def _known(conn, column: str) -> list[str]:
    return [r[0] for r in conn.execute(f"select distinct {column} from notes order by 1")]


def filters(
    conn,
    hidden_scopes: tuple[str, ...],
    *,
    source: str | None = None,
    scope: str | None = None,
    type: str | None = None,
    since: str | None = None,
    until: str | None = None,
) -> tuple[str, list]:
    where, params = egress(scope, hidden_scopes)
    if source:
        source = source.strip()
        known = _known(conn, "source")
        if source not in known:
            raise QueryError(f"unknown source {source!r} (indexed: {', '.join(known) or 'none'})")
        where += " and n.source = ?"
        params.append(source)
    if scope:
        known = _known(conn, "scope")
        if scope.strip() not in known:
            raise QueryError(f"unknown scope {scope!r} (indexed: {', '.join(known) or 'none'})")
    s, u = date_bound(since, False), date_bound(until, True)
    if s:
        where += " and n.date >= ?"
        params.append(s)
    if u:
        where += " and n.date <= ?"
        params.append(u)
    if type:
        where += " and lower(n.type) = lower(?)"
        params.append(type.strip())
    return where, params


def fts_query(text: str) -> str | None:
    """Free text -> a safe FTS5 query: every word quoted, joined with OR."""
    tokens = [t for t in WORD.findall(text) if fold(t) not in STOPWORDS]
    if not tokens:
        tokens = WORD.findall(text)
    if not tokens:
        return None
    return " OR ".join(f'"{t}"' for t in dict.fromkeys(tokens))


def rrf(*rankings: list[int], k: int = RRF_K) -> dict[int, float]:
    """Reciprocal Rank Fusion: sum of 1/(k + rank) over rankings (rank from 1)."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for pos, ident in enumerate(ranking, start=1):
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (k + pos)
    return scores


def lexical(conn, text: str, where: str, params: list, limit: int = CANDIDATES) -> list[int]:
    q = fts_query(text)
    if not q:
        return []
    rows = conn.execute(
        f"""select c.id from chunks_fts
            join chunks c on c.id = chunks_fts.rowid
            join notes n on n.id = c.note_id
            where chunks_fts match ? and {where}
            order by bm25(chunks_fts, 2.0, 1.0) limit {int(limit)}""",
        [q, *params],
    ).fetchall()
    return [r[0] for r in rows]


def vector(conn, query_vec: np.ndarray, where: str, params: list, limit: int = CANDIDATES) -> list[int]:
    blob = query_vec.astype(np.float32).tobytes()
    if getattr(conn, "vec", False):
        rows = conn.execute(
            f"""select c.id from chunks c join notes n on n.id = c.note_id
                where c.embedding is not null and {where}
                order by vec_distance_cosine(c.embedding, ?) limit {int(limit)}""",
            [*params, blob],
        ).fetchall()
        return [r[0] for r in rows]
    rows = conn.execute(
        f"""select c.id, c.embedding from chunks c join notes n on n.id = c.note_id
            where c.embedding is not null and {where}""",
        params,
    ).fetchall()
    if not rows:
        return []
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    order = np.argsort(-(matrix @ query_vec.astype(np.float32)))[:limit]
    return [rows[i][0] for i in order]


def _snippet(chunk_text: str) -> str:
    """The chunk without its header line (title — section), trimmed."""
    body = chunk_text.split("\n", 1)[1] if "\n" in chunk_text else chunk_text
    body = body.strip()
    return body if len(body) <= MAX_SNIPPET else body[: MAX_SNIPPET - 1].rstrip() + "…"


def search(
    conn,
    embedder: Embedder | None,
    query: str,
    *,
    hidden_scopes: tuple[str, ...] = (),
    source: str | None = None,
    scope: str | None = None,
    type: str | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 8,
) -> dict:
    """Hybrid: FTS5 (exact names) + vectors (paraphrases), fused with RRF.

    Returns the best chunk of each document, up to `limit` documents.
    """
    if not query or not query.strip():
        raise QueryError("the query is empty")
    limit = max(1, min(int(limit), MAX_LIMIT))
    where, params = filters(
        conn, hidden_scopes, source=source, scope=scope, type=type, since=since, until=until
    )
    lex = lexical(conn, query, where, params)
    vec: list[int] = []
    mode = "text"
    if embedder is not None and _has_vectors(conn):
        try:
            vec = vector(conn, embedder.query(query), where, params)
            mode = "hybrid"
        except ModelUnavailable:
            mode = "text (embedding model unavailable)"
    scores = rrf(lex, vec)
    if not scores:
        return {"mode": mode, "results": []}
    in_lex, in_vec = set(lex), set(vec)
    marks = ",".join("?" * len(scores))
    rows = conn.execute(
        f"""select c.id, c.section, c.text, n.doc_id, n.source, n.project, n.scope, n.title, n.type,
                   n.date, n.untrusted
            from chunks c join notes n on n.id = c.note_id
            where c.id in ({marks}) and {where}""",
        [*scores, *params],
    ).fetchall()
    best: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (-scores[r["id"]], r["id"])):
        if r["doc_id"] in best:
            continue
        best[r["doc_id"]] = {
            "path": r["doc_id"],
            "source": r["source"],
            "project": r["project"],
            "scope": r["scope"],
            "title": r["title"],
            "type": r["type"],
            "date": r["date"],
            "section": r["section"] or None,
            "snippet": _snippet(r["text"]),
            "score": round(scores[r["id"]], 5),
            "signals": [s for s, hits in (("text", in_lex), ("vector", in_vec)) if r["id"] in hits],
            "untrusted": bool(r["untrusted"]),
        }
    return {"mode": mode, "results": list(best.values())[:limit]}


def _has_vectors(conn) -> bool:
    return conn.execute("select 1 from chunks where embedding is not null limit 1").fetchone() is not None


def resolve(conn, ref: str, hidden_scopes: tuple[str, ...] = (), scope: str | None = None) -> sqlite3.Row | None:
    """A visible note by id (`source:rel/path.md`, with or without .md, / or \\),
    absolute file path, path relative to its source, or title."""
    where, params = egress(scope, hidden_scopes)
    raw = (ref or "").strip()
    if not raw:
        return None
    key = raw.replace("\\", "/").strip("/")
    for candidate in (key, key + ".md"):
        row = conn.execute(f"select * from notes n where n.doc_id = ? and {where}", [candidate, *params]).fetchone()
        if row:
            return row
    if re.match(r"^[A-Za-z]:[\\/]|^/|^~", raw):
        wanted = fold(str(Path(raw).expanduser()).replace("\\", "/"))
        for row in conn.execute(f"select * from notes n where {where}", params):
            if fold(row["file"].replace("\\", "/")) == wanted:
                return row
    no_ext = fold(key.removesuffix(".md"))
    rows = conn.execute(f"select * from notes n where {where} order by n.date desc, n.doc_id", params).fetchall()
    for row in rows:
        if fold(row["rel_path"].removesuffix(".md")) == no_ext:
            return row
    last = no_ext.rsplit("/", 1)[-1]
    for row in rows:
        if fold(row["title"]) in (no_ext, last):
            return row
    for row in rows:
        if fold(row["rel_path"].removesuffix(".md").rsplit("/", 1)[-1]) == last:
            return row
    return None


def _outgoing(conn, note_id: int, hidden_scopes: tuple[str, ...]) -> list[dict]:
    where, params = egress(None, hidden_scopes, alias="t")
    out = []
    for r in conn.execute(
        f"""select l.target, t.doc_id, t.title from links l
            left join notes t on t.doc_id = l.target_id and {where}
            where l.note_id = ? order by l.rowid""",
        [*params, note_id],
    ):
        out.append({"target": r["target"], "path": r["doc_id"], "title": r["title"]})
    return out


def note(conn, ref: str, *, hidden_scopes: tuple[str, ...] = (), scope: str | None = None) -> dict | None:
    row = resolve(conn, ref, hidden_scopes, scope)
    if row is None:
        return None
    return {
        "path": row["doc_id"],
        "source": row["source"],
        "project": row["project"],
        "scope": row["scope"],
        "title": row["title"],
        "type": row["type"],
        "status": row["status"],
        "date": row["date"],
        "untrusted": bool(row["untrusted"]),
        "file": row["file"],
        "frontmatter": json.loads(row["frontmatter"] or "{}"),
        "body": row["body"] or "",
        "links": _outgoing(conn, row["id"], hidden_scopes),
    }


def links(conn, ref: str, *, hidden_scopes: tuple[str, ...] = ()) -> dict | None:
    row = resolve(conn, ref, hidden_scopes)
    if row is None:
        return None
    where, params = egress(None, hidden_scopes, alias="o")
    incoming = [
        {"path": r["doc_id"], "title": r["title"]}
        for r in conn.execute(
            f"""select distinct o.doc_id, o.title from links l
                join notes o on o.id = l.note_id
                where l.target_id = ? and {where} order by o.doc_id""",
            [row["doc_id"], *params],
        )
    ]
    return {
        "path": row["doc_id"],
        "title": row["title"],
        "outgoing": _outgoing(conn, row["id"], hidden_scopes),
        "incoming": incoming,
    }


def todos(conn, query: str, *, hidden_scopes: tuple[str, ...] = (), limit: int = 200) -> dict:
    """Open `- [ ]` items of notes whose title, path or project matches `query`,
    plus any open item whose own text mentions it."""
    wanted = fold(query or "")
    if not wanted:
        raise QueryError("the query is empty")
    where, params = egress(None, hidden_scopes)
    rows = conn.execute(
        f"""select n.doc_id, n.title, n.source, n.project, n.date, t.line, t.text from todos t
            join notes n on n.id = t.note_id
            where t.done = 0 and {where} order by n.date desc, n.doc_id, t.line""",
        params,
    ).fetchall()
    items = []
    for r in rows:
        haystacks = (r["title"], r["doc_id"], r["project"] or "", r["text"])
        if any(wanted in fold(h) for h in haystacks):
            items.append(
                {
                    "path": r["doc_id"],
                    "title": r["title"],
                    "source": r["source"],
                    "project": r["project"],
                    "date": r["date"],
                    "line": r["line"],
                    "text": r["text"],
                }
            )
    return {"query": query, "todos": items[:limit]}


_SLUG = re.compile(r"[^a-z0-9]+")
MAX_PROPOSAL = 50_000


def propose(folder: Path, title: str, body: str, *, today: dt.date | None = None) -> Path:
    """The ONLY write: a new file inside the proposals folder, never in a source.

    The file name comes from the sanitized title (a-z, 0-9 and dashes only), so
    it cannot escape the folder; the final path is checked anyway.
    """
    title = " ".join((title or "").split())[:200]
    if not title:
        raise QueryError("the title is empty")
    if len(body or "") > MAX_PROPOSAL:
        raise QueryError(f"the body is longer than {MAX_PROPOSAL} characters")
    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    slug = _SLUG.sub("-", fold(title)).strip("-")[:60].strip("-") or "proposal"
    day = (today or dt.date.today()).isoformat()
    target = (folder / f"{day}-{slug}.md").resolve()
    n = 1
    while target.exists():
        n += 1
        target = (folder / f"{day}-{slug}-{n}.md").resolve()
    if target.parent != folder:
        raise QueryError("proposal path outside the proposals folder")
    content = (
        "---\n"
        "type: proposal\n"
        "status: pending\n"
        "source: agent\n"
        f"date: {day}\n"
        f"title: {json.dumps(title, ensure_ascii=False)}\n"
        "---\n\n"
        f"# {title}\n\n{(body or '').strip()}\n"
    )
    with open(target, "x", encoding="utf-8", newline="\n") as f:
        f.write(content)
    return target
