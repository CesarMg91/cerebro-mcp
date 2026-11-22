"""Walk the configured sources and list the Markdown documents they hold.

Three kinds:

- `vault`: an Obsidian-style folder; every `.md` file, minus `exclude` globs.
- `claude-code-memory`: `<path>/<project>/memory/*.md`; `MEMORY.md` (the index
  of the others) is skipped; the project is the folder name.
- `glob`: any `.md` matched by the `include` globs; the project is the first
  path segment.

Hidden files and folders are always skipped. Read-only: nothing here writes,
moves or deletes a file.

A document id is `<source name>:<path relative to the source root, with />`.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import Source
from .text import fold, nfc

# Folders that never hold notes and can be huge.
_HEAVY = frozenset({"node_modules", "__pycache__", "site-packages", "venv", "env"})


@dataclass(frozen=True)
class Document:
    id: str
    source: Source
    rel: str  # relative to the source root, with "/"
    file: Path
    project: str | None


def doc_id(source_name: str, rel: str) -> str:
    return nfc(f"{source_name}:{rel}")


def _segments(path: str) -> list[str]:
    return [fold(p) for p in path.strip("/").split("/") if p]


def _match_segments(pat: list[str], parts: list[str]) -> bool:
    if not pat:
        return not parts
    if pat[0] == "**":
        return any(_match_segments(pat[1:], parts[i:]) for i in range(len(parts) + 1))
    if not parts:
        return False
    return fnmatch.fnmatchcase(parts[0], pat[0]) and _match_segments(pat[1:], parts[1:])


def glob_match(rel: str, pattern: str) -> bool:
    """`**` spans folders, `*` and `?` stay inside one; case-insensitive.

    A pattern also matches everything under a folder it matches, so
    `Templates` and `Templates/**` both exclude the whole folder.
    """
    parts = _segments(rel)
    pat = _segments(pattern.replace("\\", "/"))
    if not pat:
        return False
    return any(_match_segments(pat, parts[:n]) for n in range(1, len(parts) + 1))


def _could_match_under(dir_parts: list[str], pat: list[str]) -> bool:
    """Can a file somewhere below `dir_parts` match `pat`? (Prunes the walk.)"""
    if not dir_parts:
        return True
    if not pat:
        return False
    if pat[0] == "**":
        return True
    if not fnmatch.fnmatchcase(dir_parts[0], pat[0]):
        return False
    return _could_match_under(dir_parts[1:], pat[1:])


def _hidden(name: str) -> bool:
    return name.startswith(".")


def _is_md(name: str) -> bool:
    return name.lower().endswith(".md") and not _hidden(name)


def _walk(root: Path, keep_dir) -> Iterator[str]:
    """Relative paths (with /) of the Markdown files under `root`, in a stable order."""
    for current, dirs, files in os.walk(root):
        rel_dir = Path(current).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        dirs[:] = sorted(
            d
            for d in dirs
            if not _hidden(d) and d.lower() not in _HEAVY and keep_dir(f"{rel_dir}/{d}".lstrip("/"))
        )
        for name in sorted(files):
            if _is_md(name):
                yield nfc(f"{rel_dir}/{name}".lstrip("/"))


def _excluded(rel: str, exclude: tuple[str, ...]) -> bool:
    return any(glob_match(rel, p) for p in exclude)


def _vault(src: Source) -> Iterator[Document]:
    def keep(rel_dir: str) -> bool:
        return not _excluded(rel_dir, src.exclude)

    for rel in _walk(src.path, keep):
        if not _excluded(rel, src.exclude):
            yield Document(doc_id(src.name, rel), src, rel, src.path / rel, None)


def _claude_memory(src: Source) -> Iterator[Document]:
    try:
        projects = sorted(p for p in src.path.iterdir() if p.is_dir() and not _hidden(p.name))
    except OSError:
        return
    for project in projects:
        memory = project / "memory"
        if not memory.is_dir():
            continue
        try:
            files = sorted(f for f in memory.iterdir() if f.is_file() and _is_md(f.name))
        except OSError:
            continue
        for f in files:
            if f.name.lower() == "memory.md":
                continue  # the index of the other memories: it would duplicate them
            rel = nfc(f"{project.name}/memory/{f.name}")
            if _excluded(rel, src.exclude):
                continue
            yield Document(doc_id(src.name, rel), src, rel, f, nfc(project.name))


def _glob(src: Source) -> Iterator[Document]:
    patterns = [_segments(p.replace("\\", "/")) for p in src.include]

    def keep(rel_dir: str) -> bool:
        if _excluded(rel_dir, src.exclude):
            return False
        parts = _segments(rel_dir)
        return any(_could_match_under(parts, p) for p in patterns)

    for rel in _walk(src.path, keep):
        if _excluded(rel, src.exclude):
            continue
        if not any(_match_segments(p, _segments(rel)) for p in patterns):
            continue
        parts = PurePosixPath(rel).parts
        project = nfc(parts[0]) if len(parts) > 1 else None
        yield Document(doc_id(src.name, rel), src, rel, src.path / rel, project)


_WALKERS = {"vault": _vault, "claude-code-memory": _claude_memory, "glob": _glob}


def documents(src: Source) -> Iterator[Document]:
    """Every document of one source. A missing folder yields nothing."""
    if not src.path.is_dir():
        return iter(())
    return _WALKERS[src.kind](src)


def count(src: Source) -> int:
    return sum(1 for _ in documents(src))


_ID = re.compile(r"^([^:/\\]+):(.+)$")


def split_id(value: str) -> tuple[str, str] | None:
    m = _ID.match(value)
    return (m.group(1), m.group(2)) if m else None
