"""Parse one Markdown file: frontmatter, [[links]], checkboxes, sections and chunks.

Pure functions: nothing here touches the database. Markdown is the truth; this
module only extracts what the index needs.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import yaml

from .text import fold, nfc

_FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# Zero-width characters, direction marks and BOMs: classic carriers of hidden instructions.
_INVISIBLE = re.compile("[​-‏‪-‮⁠-⁤⁦-⁩﻿]")
_CODE_BLOCK = re.compile(r"^(```|~~~).*?^\1[ \t]*$", re.DOTALL | re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_WIKILINK = re.compile(r"!?\[\[([^\]\|#\^\n]+)(?:[#\^][^\]\|\n]*)?(?:\|[^\]\n]*)?\]\]")
_CHECKBOX = re.compile(r"^\s*[-*+]\s+\[([ xX])\]\s+(.*\S)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?")
_DATE_IN_NAME = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
# "_Last updated: 2026-07-02._", "Updated: 2026-07-02", "Última actualización: 2026-07-02"
_UPDATED_LINE = re.compile(
    r"(?im)^[\s>*_\-]*(?:last[ -]updated|updated|last[ -]modified|actualizado|[uú]ltima actualizaci[oó]n)"
    r"[\s*_]*(?::|on)?[\s*_]*(\d{4}-\d{2}-\d{2})"
)

DATE_KEYS = ("date", "updated", "modified", "created", "event_date")
UNTRUSTED_SOURCES = {"web", "email", "mail", "clip", "clipping", "clipper", "web clip", "webclip", "rss"}
UNTRUSTED_TAGS = {"clipping", "clippings", "webclip", "web-clip"}
UNTRUSTED_FOLDERS = {"clippings", "clips", "web clips"}

WORDS_PER_CHUNK = 200
OVERLAP = 40


@dataclass
class ParsedNote:
    title: str
    private: bool
    frontmatter: dict = field(default_factory=dict)
    type: str | None = None
    status: str | None = None
    date: str | None = None
    untrusted: bool = False
    body: str = ""
    links: list[str] = field(default_factory=list)
    todos: list[tuple[int, str, bool]] = field(default_factory=list)  # (line, text, done)
    chunks: list[tuple[str, str]] = field(default_factory=list)  # (section, text)
    project: str | None = None


def truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return fold(value) in {"true", "yes", "si", "1", "on"}
    return False


def iso_date(value) -> str | None:
    """2019-03-14 / 2019-03 / 2019 / date -> comparable ISO string. Empty -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.strftime("%Y-%m-%d")
    m = _DATE.match(str(value).strip())
    if not m:
        return None
    year, month, day = m.groups()
    return "-".join(p for p in (year, month, day) if p)


def sanitize(text: str) -> str:
    """Drop HTML comments and invisible characters (injection carriers), keeping line breaks."""
    no_comments = _HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return _INVISIBLE.sub("", no_comments)


def split_frontmatter(text: str) -> tuple[dict, str]:
    m = _FRONTMATTER.match(text)
    if not m:
        return {}, text
    try:
        data = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return data, text[m.end():]


def frontmatter_span(text: str) -> tuple[int, int] | None:
    """(first, last) 0-based line numbers of the YAML between the `---` fences, if any."""
    m = _FRONTMATTER.match(text)
    if not m:
        return None
    first = 1
    last = text[: m.end(1)].count("\n")
    return first, last


def _without_code(text: str) -> str:
    text = _CODE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return _INLINE_CODE.sub("", text)


def links_of(text: str) -> list[str]:
    seen: dict[str, None] = {}
    for m in _WIKILINK.finditer(_without_code(text)):
        target = nfc(m.group(1).strip())
        if target:
            seen.setdefault(target, None)
    return list(seen)


def todos_of(text: str, offset: int) -> list[tuple[int, str, bool]]:
    """`- [ ]` / `- [x]` outside code blocks. Inline code stays in the text. `offset` = frontmatter lines."""
    no_blocks = _CODE_BLOCK.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    todos = []
    for i, line in enumerate(no_blocks.splitlines(), start=1):
        m = _CHECKBOX.match(line)
        if m:
            todos.append((i + offset, m.group(2).strip(), m.group(1).lower() == "x"))
    return todos


def _windows(words: list[str]) -> list[str]:
    if len(words) <= WORDS_PER_CHUNK + OVERLAP:
        return [" ".join(words)]
    step = WORDS_PER_CHUNK - OVERLAP
    return [" ".join(words[i : i + WORDS_PER_CHUNK]) for i in range(0, len(words) - OVERLAP, step)]


def chunks_of(title: str, body: str) -> list[tuple[str, str]]:
    """Split by headings; long sections in ~200-word windows.

    Each chunk starts with a header line (title and section) so the embedding
    sees the context and lexical search finds the note's name. The header is
    the first line of the chunk text.
    """
    sections: list[tuple[str, list[str]]] = [("", [])]
    in_code = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_code = not in_code
        m = None if in_code else _HEADING.match(line)
        if m:
            sections.append((m.group(2), []))
        else:
            sections[-1][1].append(line)
    out = []
    for section, lines in sections:
        words = " ".join(lines).split()
        if not words:
            continue
        head = f"{title} — {section}" if section and section != title else title
        if len(words) <= WORDS_PER_CHUNK + OVERLAP:
            # Short section: keep its lines, so a list item or a table row stays one line.
            kept = [ln.rstrip() for ln in lines if ln.strip()]
            out.append((section, f"{head}\n" + "\n".join(kept)))
            continue
        for piece in _windows(words):
            out.append((section, f"{head}\n{piece}"))
    if not out:
        out.append(("", title))
    return out


def in_private_folder(rel_path: str, private_folders: tuple[str, ...]) -> bool:
    folders = {fold(f) for f in private_folders}
    return any(fold(part) in folders for part in PurePosixPath(rel_path).parts[:-1])


def _jsonable(value):
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _first_h1(body: str) -> str | None:
    for line in body.splitlines():
        m = _HEADING.match(line)
        if m and len(m.group(1)) == 1:
            return m.group(2).strip()
    return None


def _date_of(fm: dict, body: str, rel_path: str) -> str | None:
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    for key in DATE_KEYS:
        for holder in (fm, meta):
            d = iso_date(holder.get(key))
            if d:
                return d
    m = _UPDATED_LINE.search(body)
    if m:
        return m.group(1)
    m = _DATE_IN_NAME.search(PurePosixPath(rel_path).name)
    if m:
        return m.group(1)
    for part in reversed(PurePosixPath(rel_path).parts[:-1]):
        m = _DATE_IN_NAME.search(part)
        if m:
            return m.group(1)
    return None


def _untrusted(fm: dict, rel_path: str) -> bool:
    src = fm.get("source")
    if isinstance(src, str):
        s = fold(src)
        if s in UNTRUSTED_SOURCES or s.startswith(("http://", "https://")):
            return True
    tags = fm.get("tags")
    tags = [tags] if isinstance(tags, str) else tags if isinstance(tags, list) else []
    if any(isinstance(t, str) and fold(t).lstrip("#") in UNTRUSTED_TAGS for t in tags):
        return True
    return any(fold(p) in UNTRUSTED_FOLDERS for p in PurePosixPath(rel_path).parts[:-1])


def parse(
    rel_path: str,
    text: str,
    *,
    kind: str = "vault",
    private_folders: tuple[str, ...] = (),
    private_key: str = "private",
) -> ParsedNote:
    """Parse already-redacted text. `rel_path` is relative to the source root, with `/`."""
    rel_path = nfc(rel_path)
    text = text.replace("\r\n", "\n")
    fm, raw_body = split_frontmatter(text)
    offset = text[: len(text) - len(raw_body)].count("\n")
    stem = PurePosixPath(rel_path).stem

    private = in_private_folder(rel_path, private_folders) or (
        bool(private_key) and truthy(fm.get(private_key))
    )
    if private:
        # A private note leaves nothing in the index but its id and hash.
        return ParsedNote(title=nfc(stem), private=True)

    body = sanitize(raw_body)
    meta = fm.get("metadata") if isinstance(fm.get("metadata"), dict) else {}
    title = fm.get("title") if isinstance(fm.get("title"), str) else None
    if not title and kind == "claude-code-memory" and isinstance(fm.get("name"), str):
        title = fm["name"]
    if not title and kind == "glob":
        title = _first_h1(body)
    title = nfc((title or stem).strip())

    note_type = fm.get("type") or meta.get("type")
    status = fm.get("status") or meta.get("status")
    project = fm.get("project") if isinstance(fm.get("project"), str) else None
    note = ParsedNote(
        title=title,
        private=False,
        frontmatter={str(k): _jsonable(v) for k, v in fm.items()},
        type=str(note_type).strip() if note_type else None,
        status=str(status).strip() if status else None,
        date=_date_of(fm, body, rel_path),
        untrusted=_untrusted(fm, rel_path),
        body=body,
        project=project,
    )
    note.links = links_of(body)
    note.todos = todos_of(body, offset)
    note.chunks = chunks_of(title, body)
    description = fm.get("description")
    if isinstance(description, str) and description.strip():
        note.chunks.insert(0, ("description", f"{title}\n{description.strip()}"))
    return note
