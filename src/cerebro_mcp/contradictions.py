"""Find pairs of fragments that talk about the same thing but state different values.

Step 1 (SQL, with the egress rule): fetch the fragments on the topic.
Step 2 (here): pull typed values out of each fragment (prices, versions, dates,
numbers with a unit, and a yes/no stance on the topic words) and pair fragments
from different documents whose values of the same kind do not overlap.

This is a heuristic. It finds *candidates*; deciding whether a pair is a real
contradiction or just something that changed over time is the caller's job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from . import query as q
from .embeddings import Embedder, ModelUnavailable
from .notes import _UPDATED_LINE  # noqa: PLC2701 - same package
from .text import STOPWORDS, WORD, content_tokens, fold, stem

CANDIDATE_CHUNKS = 30  # fragments on the topic considered for pairing
SCAN_CHUNKS = 600  # fragments considered when there is no topic

# ---------- value extraction ----------

_MONTHS = {
    "january": 1, "jan": 1, "enero": 1, "february": 2, "feb": 2, "febrero": 2, "march": 3, "mar": 3,
    "marzo": 3, "april": 4, "apr": 4, "abril": 4, "may": 5, "mayo": 5, "june": 6, "jun": 6, "junio": 6,
    "july": 7, "jul": 7, "julio": 7, "august": 8, "aug": 8, "agosto": 8, "september": 9, "sep": 9,
    "sept": 9, "septiembre": 9, "setiembre": 9, "october": 10, "oct": 10, "octubre": 10,
    "november": 11, "nov": 11, "noviembre": 11, "december": 12, "dec": 12, "diciembre": 12,
}
_MONTH = r"(?P<month>" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"

_DATE_PATTERNS = [
    re.compile(r"(?<![\d-])(?P<year>\d{4})-(?P<mnum>\d{2})-(?P<day>\d{2})(?![\d-])"),
    re.compile(rf"(?i)\b{_MONTH}\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>\d{{4}})\b"),
    re.compile(rf"(?i)\b(?P<day>\d{{1,2}})\s+(?:de\s+)?{_MONTH}(?:,?\s+(?:de\s+|del\s+)?(?P<year>\d{{4}}))?\b"),
    re.compile(rf"(?i)\b{_MONTH}\s+(?P<day>\d{{1,2}})(?:st|nd|rd|th)?\b(?!\s*,?\s*\d{{4}})"),
    re.compile(rf"(?i)\b{_MONTH}\s+(?:de\s+|del\s+)?(?P<year>\d{{4}})\b"),
    re.compile(r"(?<![\d-])(?P<year>\d{4})-(?P<mnum>\d{2})(?![\d-])"),
]

_CURRENCY_WORDS = r"USD|EUR|MXN|GBP|CAD|AUD|dollars?|d[oó]lares|euros?|pesos|bucks"
_PRICE = re.compile(
    r"(?i)(?:(?P<sym>US\$|MX\$|[$€£¥])\s?(?P<amt>\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    rf"|(?<![\d,.])(?P<amt2>\d{{1,3}}(?:,\d{{3}})+(?:\.\d{{1,2}})?|\d+(?:[.,]\d{{1,2}})?)\s?(?P<word>{_CURRENCY_WORDS})\b)"
)
_PERIOD_AFTER = re.compile(
    r"(?i)^\s*(?:usd|mxn|eur)?\s*(?:/|per|a|al|por|each|cada|every)?\s*(?:the\s+|un\s+)?"
    r"(?P<p>month|mo|mes|monthly|mensual(?:es)?|year|yr|año|ano|annual|annually|anual(?:es)?|yearly|week|semana|day|d[ií]a)\b"
)
_PERIOD_BEFORE = re.compile(r"(?i)\b(?P<p>monthly|mensual|yearly|annual|anual|weekly|semanal)\b[^.\n$€£]{0,20}$")
_PERIODS = {
    "month": "month", "mo": "month", "mes": "month", "monthly": "month", "mensual": "month", "mensuales": "month",
    "year": "year", "yr": "year", "año": "year", "ano": "year", "annual": "year", "annually": "year",
    "anual": "year", "anuales": "year", "yearly": "year", "week": "week", "semana": "week", "weekly": "week",
    "semanal": "week", "day": "day", "dia": "day", "día": "day",
}

_VERSION = re.compile(
    r"(?i)(?:\b(?:version|versi[oó]n|release|build)\b[\s:*_]*v?(?P<a>\d+\.\d+(?:\.\d+)?)"
    r"|(?<![\w.])v(?P<b>\d+\.\d+(?:\.\d+)?)"
    r"|(?<![\w.])(?P<c>\d+\.\d+\.\d+))(?![\w]|\.\d)"
)
_NUMBER_UNIT = re.compile(r"(?<![\w.,$€£+/:-])(?P<n>\d{1,7}(?:[.,]\d+)?)(?:[ \-]|\s*-\s*)(?P<u>[^\W\d_]{2,})")
_PERCENT = re.compile(r"(?<![\w.])(?P<n>\d{1,3}(?:[.,]\d+)?)\s?%\s+(?:de\s+|of\s+)?(?P<u>[^\W\d_]{3,})")

_UNIT_ALIASES = {
    "dia": "day", "semana": "week", "mes": "month", "ano": "year", "hora": "hour", "hr": "hour",
    "minuto": "minute", "min": "minute", "segundo": "second", "sec": "second", "usuario": "user",
    "habito": "habit", "persona": "person", "people": "person", "cliente": "customer",
    "dispositivo": "device", "plataforma": "platform",
}
_NOT_UNITS = STOPWORDS | set(_MONTHS) | {
    "am", "pm", "utc", "gmt", "x", "usd", "mxn", "eur", "gbp", "dollar", "dolar", "dolare", "euro",
    "peso", "buck", "st", "nd", "rd", "th", "and", "or", "to", "y", "o", "of", "de", "del",
}

_NEGATORS = {"no", "not", "without", "never", "sin", "nunca", "ni", "zero", "cero", "none", "ningun",
             "ninguna", "ninguno", "nor", "dont", "don", "doesnt", "won", "wont", "removed", "deleted",
             "dropped", "eliminado", "eliminada", "quitamos", "quitado"}

_TOPIC_KINDS = {
    "price": "price", "pricing": "price", "cost": "price", "precio": "price", "costo": "price",
    "plan": "price", "subscription": "price", "suscripcion": "price", "pro": "price",
    "version": "version", "release": "version", "build": "version",
    "launch": "date", "lanzamiento": "date", "date": "date", "fecha": "date", "deadline": "date",
    "when": "date", "cuando": "date", "ship": "date",
    "trial": "number", "prueba": "number",
}

_CLAUSE_BREAK = re.compile(r"[\n.;:!?\"“”|()]")

_DONE_TASK = re.compile(r"(?m)^\s*[-*+]\s+\[[xX]\].*$")

STRONG = {"price", "version", "number", "decision"}
KIND_ORDER = {"price": 0, "version": 1, "date": 2, "decision": 3, "number": 4, "percent": 4}


@dataclass(frozen=True)
class Claim:
    key: str  # what is compared: "price:month", "version", "date", "number:day", "decision:ad"
    kind: str  # shown to people: price, version, date, number, decision
    value: str  # normalized
    text: str  # as written


@dataclass
class Fragment:
    chunk_id: int
    note_id: int
    doc_id: str
    source: str
    project: str | None
    scope: str
    title: str
    date: str | None
    section: str | None
    text: str
    untrusted: bool
    vector: np.ndarray | None = None
    claims: list[Claim] = field(default_factory=list)


def _clean(text: str, display: bool = False) -> str:
    """Body of a chunk ready for extraction: no header, no 'last updated' lines, no markup.

    For extraction, inline code and [[links]] are dropped (identifiers and note
    names, not claims); for display they are kept as plain text.
    """
    body = text.split("\n", 1)[1] if "\n" in text else ""
    if display:
        body = body.replace("`", "")
        body = re.sub(r"\[\[([^\]|]*)(?:\|([^\]]*))?\]\]", lambda m: m.group(2) or m.group(1), body)
    else:
        body = _UPDATED_LINE.sub(" ", body)
        body = _DONE_TASK.sub(" ", body)  # a finished task is history, not a current claim
        body = re.sub(r"`[^`\n]*`", " ", body)
        body = re.sub(r"\[\[[^\]]*\]\]", " ", body)
    return re.sub(r"(\*\*|__|\*|~~)", "", body)


def _mask(text: str, spans: list[tuple[int, int]]) -> str:
    chars = list(text)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


def _amount(raw: str) -> str:
    raw = raw.replace(",", "") if re.search(r",\d{3}", raw) else raw.replace(",", ".")
    value = float(raw)
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _unit(word: str) -> str | None:
    w = stem(fold(word))
    if w in _NOT_UNITS or len(w) < 2:
        return None
    return _UNIT_ALIASES.get(w, w)


def extract(text: str, doc_date: str | None = None, topic_terms: tuple[str, ...] = ()) -> list[Claim]:
    """Typed values stated in a fragment."""
    body = _clean(text)
    claims: list[Claim] = []
    spans: list[tuple[int, int]] = []

    for m in _PRICE.finditer(body):
        amt = m.group("amt") or m.group("amt2")
        if not amt:
            continue
        after = _PERIOD_AFTER.match(body[m.end() : m.end() + 24])
        before = _PERIOD_BEFORE.search(body[max(0, m.start() - 30) : m.start()])
        period = _PERIODS.get(fold((after or before).group("p"))) if (after or before) else None
        end = m.end() + (after.end() if after else 0)
        written = body[m.start() : end].strip()
        claims.append(Claim(f"price:{period}" if period else "price", "price", _amount(amt), written))
        spans.append((m.start(), end))
    body = _mask(body, spans)
    spans = []

    for m in _VERSION.finditer(body):
        v = m.group("a") or m.group("b") or m.group("c")
        norm = v
        while norm.count(".") > 1 and norm.endswith(".0"):
            norm = norm[:-2]  # 2.0.0 == 2.0
        claims.append(Claim("version", "version", norm, ("v" if m.group("b") else "") + v))
        spans.append(m.span())
    body = _mask(body, spans)
    spans = []

    for pattern in _DATE_PATTERNS:
        for m in pattern.finditer(body):
            g = m.groupdict()
            if g.get("mnum"):
                month = int(g["mnum"])
            else:
                month = _MONTHS.get(fold(g["month"]).rstrip("."))
            if not month or not 1 <= month <= 12:
                continue
            day = int(g["day"]) if g.get("day") else None
            if day is not None and not 1 <= day <= 31:
                continue
            year = g.get("year")
            if year and day:
                value = f"{year}-{month:02d}-{day:02d}"
            elif year:
                value = f"{year}-{month:02d}"
            else:
                value = f"--{month:02d}-{day:02d}"
            if doc_date and value == doc_date:
                continue  # the note's own date (a journal heading, a handoff title)
            claims.append(Claim("date", "date", value, m.group(0).strip()))
            spans.append(m.span())
        body = _mask(body, spans)
        spans = []

    for m in _PERCENT.finditer(body):
        unit = _unit(m.group("u"))
        if unit:
            claims.append(Claim(f"percent:{unit}", "number", _amount(m.group("n")) + "%", m.group(0).strip()))
            spans.append(m.span())
    body = _mask(body, spans)

    for m in _NUMBER_UNIT.finditer(body):
        n = m.group("n")
        if re.fullmatch(r"(19|20)\d\d", n):
            continue  # a year, not a quantity
        unit = _unit(m.group("u"))
        if unit:
            claims.append(Claim(f"number:{unit}", "number", _amount(n), m.group(0).strip()))

    claims.extend(_stances(_clean(text), topic_terms))
    return claims


def _stances(body: str, terms: tuple[str, ...]) -> list[Claim]:
    """Yes/no on each topic word: `no ads` / `sin anuncios` vs `a banner ad`."""
    if not terms:
        return []
    tokens = [(m.group(0), fold(m.group(0)), m.start(), m.end()) for m in WORD.finditer(body)]
    out = []
    for term in terms:
        if term in _TOPIC_KINDS:
            continue  # "price", "version", "launch": compared by value, a yes/no on them means nothing
        hits = []
        for i, (_, folded, start, end) in enumerate(tokens):
            if stem(folded) != term:
                continue
            window = tokens[max(0, i - 3) : i]
            # A negator only counts inside the same clause: "never add ads".\n- Price is not "no price".
            window = [t for t in window if not _CLAUSE_BREAK.search(body[t[3] : start])]
            negators = [t for t in window if t[1].replace("'", "") in _NEGATORS]
            negated = bool(negators)
            first = negators[-1][2] if negated else start
            hits.append((negated, body[first:end]))
        if not hits:
            continue
        negs = {h[0] for h in hits}
        if len(negs) != 1:
            continue  # mixed: no clear stance
        negated = negs.pop()
        written = hits[0][1].strip()
        out.append(Claim(f"decision:{term}", "decision", "no" if negated else "yes", written))
    return out


def _compatible(kind: str, a: str, b: str) -> bool:
    if a == b:
        return True
    if kind == "date":
        if a.startswith("--") or b.startswith("--"):
            short, full = (a, b) if a.startswith("--") else (b, a)
            return full.endswith(short[1:]) if not full.startswith("--") else False
        return a.startswith(b) or b.startswith(a)
    return False


@dataclass
class Difference:
    kind: str
    key: str
    older: list[str]
    newer: list[str]


def differences(a: Fragment, b: Fragment, kinds: set[str] | None = None) -> list[Difference]:
    """Keys stated by both fragments whose values never agree."""
    by_a: dict[str, list[Claim]] = {}
    by_b: dict[str, list[Claim]] = {}
    for c in a.claims:
        by_a.setdefault(c.key, []).append(c)
    for c in b.claims:
        by_b.setdefault(c.key, []).append(c)
    out = []
    for key in sorted(set(by_a) & set(by_b), key=lambda k: (KIND_ORDER.get(k.split(":")[0], 9), k)):
        ca, cb = by_a[key], by_b[key]
        kind = ca[0].kind
        if kinds and kind not in kinds and kind != "decision":
            continue
        if any(_compatible(kind, x.value, y.value) for x in ca for y in cb):
            continue
        out.append(
            Difference(
                kind=kind,
                key=key,
                older=list(dict.fromkeys(c.text for c in ca)),
                newer=list(dict.fromkeys(c.text for c in cb)),
            )
        )
    return out


# ---------- pairing ----------


def _topic_terms(topic: str | None) -> tuple[str, ...]:
    if not topic:
        return ()
    return tuple(dict.fromkeys(stem(t) for t in content_tokens(topic)))


def _topic_kinds(terms: tuple[str, ...]) -> set[str] | None:
    kinds = {_TOPIC_KINDS[t] for t in terms if t in _TOPIC_KINDS}
    return kinds or None


def _fragments(conn, ids: list[int] | None, where: str, params: list, limit: int) -> list[Fragment]:
    cols = """c.id, c.section, c.text, c.embedding, n.id as note_id, n.doc_id, n.source, n.project,
              n.scope, n.title, n.date, n.untrusted"""
    if ids is not None:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        sql = f"select {cols} from chunks c join notes n on n.id = c.note_id where c.id in ({marks}) and {where}"
        rows = conn.execute(sql, [*ids, *params]).fetchall()
    else:
        sql = (
            f"select {cols} from chunks c join notes n on n.id = c.note_id where {where} "
            f"order by n.date desc, c.id limit {int(limit)}"
        )
        rows = conn.execute(sql, params).fetchall()
    out = []
    for r in rows:
        out.append(
            Fragment(
                chunk_id=r["id"],
                note_id=r["note_id"],
                doc_id=r["doc_id"],
                source=r["source"],
                project=r["project"],
                scope=r["scope"],
                title=r["title"],
                date=r["date"],
                section=r["section"] or None,
                text=r["text"],
                untrusted=bool(r["untrusted"]),
                vector=np.frombuffer(r["embedding"], dtype=np.float32) if r["embedding"] else None,
            )
        )
    return out


def _similarity(a: Fragment, b: Fragment, tokens: dict[int, set[str]]) -> float:
    if a.vector is not None and b.vector is not None:
        return float(np.dot(a.vector, b.vector))
    ta, tb = tokens[a.chunk_id], tokens[b.chunk_id]
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def focus(text: str, wanted: list[str], before: int = 90, after: int = 230) -> str:
    """A readable window of the fragment around the first value that differs."""
    body = " ".join(_clean(text, display=True).split())
    pos = min((p for p in (body.find(w) for w in wanted) if p >= 0), default=0)
    start = max(0, pos - before)
    end = min(len(body), pos + after)
    if start > 0:
        space = body.find(" ", start)
        start = space + 1 if 0 <= space < pos else start
    if end < len(body):
        space = body.rfind(" ", pos, end)
        end = space if space > pos else end
    return ("…" if start > 0 else "") + body[start:end].strip() + ("…" if end < len(body) else "")


def _side(f: Fragment, wanted: list[str]) -> dict:
    return {
        "path": f.doc_id,
        "source": f.source,
        "project": f.project,
        "scope": f.scope,
        "title": f.title,
        "date": f.date,
        "section": f.section,
        "snippet": focus(f.text, wanted),
        "untrusted": f.untrusted,
    }


def find(
    conn,
    embedder: Embedder | None,
    topic: str | None,
    *,
    hidden_scopes: tuple[str, ...] = (),
    scope: str | None = None,
    across_sources: bool = False,
    limit: int = 5,
) -> dict:
    """Candidate contradictions on `topic` (or across everything when `topic` is None)."""
    if topic is not None and not topic.strip():
        raise q.QueryError("the topic is empty")
    limit = max(1, min(int(limit), 30))
    where, params = q.egress(scope, hidden_scopes)
    terms = _topic_terms(topic)
    use_vectors = embedder is not None and q._has_vectors(conn)

    if topic:
        lex = q.lexical(conn, topic, where, params, limit=CANDIDATE_CHUNKS * 2)
        vec = []
        if use_vectors:
            try:
                vec = q.vector(conn, embedder.query(topic), where, params, limit=CANDIDATE_CHUNKS)
            except ModelUnavailable:
                use_vectors = False
        scores = q.rrf(lex, vec)
        chosen = sorted(scores, key=lambda i: (-scores[i], i))[:CANDIDATE_CHUNKS]
        if chosen:
            # A note found by its title or summary states its values further down:
            # take the other fragments of the same notes too (bounded).
            marks = ",".join("?" * len(chosen))
            siblings = [
                r[0]
                for r in conn.execute(
                    f"""select c.id from chunks c where c.note_id in
                        (select note_id from chunks where id in ({marks})) order by c.note_id, c.ord""",
                    chosen,
                )
            ]
            chosen = list(dict.fromkeys(chosen + siblings))[: CANDIDATE_CHUNKS * 2]
        frags = _fragments(conn, chosen, where, params, 0)
    else:
        frags = _fragments(conn, None, where, params, SCAN_CHUNKS)
    if not use_vectors:
        for f in frags:
            f.vector = None

    kinds = _topic_kinds(terms)
    for f in frags:
        f.claims = extract(f.text, f.date, terms)
    frags = [f for f in frags if f.claims]
    tokens = {f.chunk_id: set(content_tokens(f.text.split("\n", 1)[-1])) for f in frags}

    candidates = []
    for i, a in enumerate(frags):
        for b in frags[i + 1 :]:
            if a.note_id == b.note_id:
                continue
            if across_sources and a.source == b.source:
                continue
            older, newer = sorted((a, b), key=lambda f: (f.date or "", f.doc_id))
            diffs = differences(older, newer, kinds)
            if not diffs:
                continue
            if terms:
                diffs.sort(key=lambda d: d.kind != "decision")  # the stance on the topic itself first
            sim = _similarity(a, b, tokens)
            strong = sum(1 for d in diffs if d.kind in STRONG)
            decided = sum(1 for d in diffs if d.kind == "decision")  # only with a topic: it is about it
            score = sim + 0.1 * strong + 0.03 * (len(diffs) - strong) + 0.15 * decided
            candidates.append((score, sim, older, newer, diffs))
    candidates.sort(key=lambda c: (-c[0], c[2].chunk_id, c[3].chunk_id))

    pairs, seen = [], set()
    for score, sim, older, newer, diffs in candidates:
        key = frozenset((older.note_id, newer.note_id))
        if key in seen:
            continue  # one pair per pair of notes: the best one
        seen.add(key)
        pairs.append(
            {
                "older": _side(older, diffs[0].older),
                "newer": _side(newer, diffs[0].newer),
                "values": [{"kind": d.kind, "older": d.older, "newer": d.newer} for d in diffs],
                "similarity": round(sim, 4),
                "score": round(score, 4),
            }
        )
        if len(pairs) >= limit:
            break
    return {"topic": topic, "mode": "hybrid" if use_vectors else "text", "pairs": pairs}
