"""`cerebro.toml`: where it is looked up, what it may contain, and how it is validated.

Lookup order: `--config PATH`, `$CEREBRO_CONFIG`, `./cerebro.toml`, then the
user config dir (`platformdirs`). `~` and environment variables expand in every
path; relative paths resolve against the directory of the loaded file.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import platformdirs

APP = "cerebro"
FILENAME = "cerebro.toml"
KINDS = ("vault", "claude-code-memory", "glob")
DEFAULT_SCOPE = "default"
DEFAULT_PRIVATE_FOLDERS = ("private",)
DEFAULT_REDACT = ("secrets", "cards")
REDACT_PACKS = ("secrets", "cards", "mx")
DEFAULT_GLOB_INCLUDE = ("**/*.md",)


class ConfigError(ValueError):
    """The config file is missing or invalid. The message is meant for a human."""


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    path: Path
    scope: str = DEFAULT_SCOPE
    exclude: tuple[str, ...] = ()
    include: tuple[str, ...] = ()


@dataclass(frozen=True)
class Privacy:
    private_folders: tuple[str, ...] = DEFAULT_PRIVATE_FOLDERS
    private_frontmatter: str = "private"
    redact: tuple[str, ...] = DEFAULT_REDACT
    hidden_scopes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Config:
    db: Path
    proposals: Path
    sources: tuple[Source, ...] = ()
    privacy: Privacy = field(default_factory=Privacy)
    model: str | None = None  # embedding model key; None = the default one
    path: Path | None = None  # the file it was loaded from

    def source(self, name: str) -> Source | None:
        return next((s for s in self.sources if s.name == name), None)


def user_config_file() -> Path:
    return Path(platformdirs.user_config_dir(APP, appauthor=False)) / FILENAME


def default_db() -> Path:
    return Path(platformdirs.user_cache_dir(APP, appauthor=False)) / "index.db"


def default_proposals() -> Path:
    return Path(platformdirs.user_cache_dir(APP, appauthor=False)) / "proposals"


def find(explicit: str | os.PathLike | None = None) -> Path | None:
    """The config file to use, or None when there is none anywhere."""
    if explicit:
        return Path(explicit).expanduser()
    env = os.environ.get("CEREBRO_CONFIG")
    if env:
        return Path(env).expanduser()
    here = Path.cwd() / FILENAME
    if here.is_file():
        return here
    user = user_config_file()
    if user.is_file():
        return user
    return None


def expand(value: str, base: Path) -> Path:
    """`~` and `$VARS` expand; a relative path is relative to `base`."""
    p = Path(os.path.expandvars(os.path.expanduser(value)))
    if not p.is_absolute():
        p = base / p
    return Path(os.path.normpath(p))


def _strings(value, what: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{what} must be a list of strings")
    return tuple(value)


def parse(data: dict, base: Path, path: Path | None = None) -> Config:
    """Validate a parsed TOML document. `base` resolves relative paths."""
    index = data.get("index", {}) or {}
    if not isinstance(index, dict):
        raise ConfigError("[index] must be a table")
    db = expand(index["db"], base) if index.get("db") else default_db()
    proposals = expand(index["proposals"], base) if index.get("proposals") else default_proposals()
    model = index.get("model")
    if model is not None and not isinstance(model, str):
        raise ConfigError("[index] model must be a string")

    raw_sources = data.get("source", [])
    if not isinstance(raw_sources, list):
        raise ConfigError("use [[source]] (an array of tables) for sources")
    sources: list[Source] = []
    seen: set[str] = set()
    for i, s in enumerate(raw_sources, 1):
        if not isinstance(s, dict):
            raise ConfigError(f"source #{i} must be a table")
        name = s.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ConfigError(f"source #{i} needs a name")
        name = name.strip()
        if ":" in name or "/" in name or "\\" in name:
            raise ConfigError(f"source {name!r}: the name cannot contain ':', '/' or '\\'")
        if name in seen:
            raise ConfigError(f"source name {name!r} is used twice")
        seen.add(name)
        kind = s.get("kind", "vault")
        if kind not in KINDS:
            raise ConfigError(f"source {name!r}: kind must be one of {', '.join(KINDS)}")
        if not isinstance(s.get("path"), str) or not s["path"].strip():
            raise ConfigError(f"source {name!r} needs a path")
        scope = s.get("scope", DEFAULT_SCOPE)
        if not isinstance(scope, str) or not scope.strip():
            raise ConfigError(f"source {name!r}: scope must be a non-empty string")
        include = _strings(s.get("include"), f"source {name!r}: include")
        if kind == "glob" and not include:
            include = DEFAULT_GLOB_INCLUDE
        unknown = set(s) - {"name", "kind", "path", "scope", "exclude", "include"}
        if unknown:
            raise ConfigError(f"source {name!r}: unknown keys {', '.join(sorted(unknown))}")
        sources.append(
            Source(
                name=name,
                kind=kind,
                path=expand(s["path"], base),
                scope=scope.strip(),
                exclude=_strings(s.get("exclude"), f"source {name!r}: exclude"),
                include=include,
            )
        )

    p = data.get("privacy", {}) or {}
    if not isinstance(p, dict):
        raise ConfigError("[privacy] must be a table")
    redact = _strings(p.get("redact", list(DEFAULT_REDACT)), "privacy.redact")
    bad = [r for r in redact if r not in REDACT_PACKS]
    if bad:
        raise ConfigError(f"privacy.redact: unknown pack(s) {', '.join(bad)} (known: {', '.join(REDACT_PACKS)})")
    private_fm = p.get("private_frontmatter", "private")
    if not isinstance(private_fm, str):
        raise ConfigError("privacy.private_frontmatter must be a string")
    privacy = Privacy(
        private_folders=_strings(p.get("private_folders", list(DEFAULT_PRIVATE_FOLDERS)), "privacy.private_folders"),
        private_frontmatter=private_fm.strip(),
        redact=redact,
        hidden_scopes=_strings(p.get("hidden_scopes"), "privacy.hidden_scopes"),
    )
    return Config(db=db, proposals=proposals, sources=tuple(sources), privacy=privacy, model=model, path=path)


def load(path: str | os.PathLike | None = None) -> Config:
    """Find and load the config. Raises ConfigError with a readable message."""
    found = find(path)
    if found is None:
        raise ConfigError(
            f"no {FILENAME} found (looked at --config, $CEREBRO_CONFIG, ./{FILENAME} and "
            f"{user_config_file()}). Run `cerebro init` to create one."
        )
    if not found.is_file():
        raise ConfigError(f"config file not found: {found}")
    try:
        data = tomllib.loads(found.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{found}: invalid TOML: {e}") from e
    resolved = found.resolve()
    return parse(data, resolved.parent, resolved)


def _toml_str(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def starter(vault: Path | None, agent_memory: Path | None) -> str:
    """The text of a starter `cerebro.toml`."""
    lines = [
        "# cerebro.toml: what cerebro indexes and what it keeps private.",
        "# Paths accept ~ and $VARS; relative paths are relative to this file.",
        "",
        "[index]",
        f"# db = {_toml_str(str(default_db()))}",
        f"# proposals = {_toml_str(str(default_proposals()))}",
        "",
    ]
    if vault is not None:
        lines += [
            "[[source]]",
            'name = "notes"',
            'kind = "vault"',
            f"path = {_toml_str(str(vault))}",
            'scope = "personal"',
            'exclude = ["Templates/**"]',
            "",
        ]
    if agent_memory is not None:
        lines += [
            "[[source]]",
            'name = "claude-memory"',
            'kind = "claude-code-memory"',
            f"path = {_toml_str(str(agent_memory))}",
            'scope = "work"',
            "",
        ]
    lines += [
        "# Any Markdown matched by globs (project = first path segment):",
        "# [[source]]",
        '# name = "handoffs"',
        '# kind = "glob"',
        '# path = "~/code"',
        '# include = ["*/docs/**/*.md", "*/AGENTS.md", "*/CLAUDE.md"]',
        '# scope = "work"',
        "",
        "[privacy]",
        'private_folders = ["private", "people"]   # any path segment, case-insensitive',
        'private_frontmatter = "private"           # `private: true` in frontmatter',
        'redact = ["secrets", "cards"]             # add "mx" for CLABE/RFC/CURP/INE',
        "hidden_scopes = []                        # indexed, returned only when asked for",
        "",
    ]
    return "\n".join(lines)
