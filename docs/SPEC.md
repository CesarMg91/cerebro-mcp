# cerebro-mcp — v0.1 spec

> A local, read-only index over your Markdown notes **and your AI agents' memories**,
> served over MCP — with a tool that tells you when they contradict each other.

Open-source extraction of a private tool the author uses daily. Clean history:
nothing from its notes or paths is copied. Code, CLI, MCP tools and docs are in **English**; a Spanish
README (`README.es.md`) sits next to the English one. Search must work well in
both languages (multilingual embeddings).

## Principles

1. **Markdown is the truth; the index is disposable.** Delete `index.db`, nothing is lost.
2. **Read-only.** Cerebro never edits, moves or deletes a source file. The only
   write is `propose`, into its own proposals folder.
3. **Local.** Indexing and embeddings run on the machine. Only the fragments a
   client asks for leave it.
4. **Private stays private.** Private notes are indexed by path and hash only;
   every query filters them out in SQL (the egress rule). Sensitive lines are
   redacted before parsing.
5. **Content is data, not instructions.** Tool outputs carry an injection notice;
   web clips are marked untrusted.

## Package

- PyPI name `cerebro-mcp`, import package `cerebro_mcp`, console command `cerebro`.
- `uvx cerebro-mcp demo` must work on a clean machine (Windows, macOS, Linux).
- Python `>=3.11`. License MIT.
- Index: SQLite FTS5 + `sqlite-vec`, hybrid ranking with RRF.
- Embeddings: multilingual, small, CPU, offline after the first model download.
  Prefer a light runtime (ONNX, e.g. `fastembed`) over `torch` if it serves a
  multilingual model of similar quality; otherwise keep `sentence-transformers`
  with `intfloat/multilingual-e5-small`. Record the choice and why in
  `docs/architecture.md`.

## Config — `cerebro.toml`

Looked up in this order: `--config PATH`, `$CEREBRO_CONFIG`, `./cerebro.toml`,
the user config dir (`platformdirs`). `~` and env vars expand in paths.

```toml
[index]
db = "~/.cache/cerebro/index.db"     # default: user cache dir
proposals = "~/.cache/cerebro/proposals"

[[source]]
name = "notes"                 # unique; shows as `source` in results
kind = "vault"                 # Markdown/Obsidian folder: frontmatter, [[links]], checkboxes
path = "~/Obsidian"
scope = "personal"             # free label; default "default"
exclude = ["Templates/**"]     # globs relative to path; hidden folders always skipped

[[source]]
name = "claude-memory"
kind = "claude-code-memory"    # <path>/<project>/memory/*.md, MEMORY.md skipped; project = folder name
path = "~/.claude/projects"

[[source]]
name = "handoffs"
kind = "glob"                  # any Markdown matched by include globs; project = first path segment
path = "~/code"
include = ["*/docs/**/*.md", "*/AGENTS.md", "*/CLAUDE.md"]
scope = "work"

[privacy]
private_folders = ["private", "people"]   # any path segment, case-insensitive
private_frontmatter = "private"           # `private: true` in frontmatter
redact = ["secrets", "cards"]             # built-in packs; "mx" adds CLABE/RFC/CURP/INE
hidden_scopes = []                        # indexed, returned only when that scope is asked for
```

## CLI

| Command | Does |
|---|---|
| `cerebro init [--vault PATH] [--no-agent-memory]` | Writes a starter `cerebro.toml`; adds `~/.claude/projects` as a source if it exists. Never overwrites without `--force`. |
| `cerebro index [--full]` | Incremental by content hash; `--full` rebuilds. Removed sources leave the index. |
| `cerebro search "query" [--source --scope --type --since --until --text --limit --json]` | Hybrid search; `--text` = FTS only. |
| `cerebro contradictions "topic" [--across-sources] [--limit] [--json]` | Pairs of fragments on the topic that state different values (numbers, versions, dates, prices, yes/no). `--across-sources` keeps only pairs from different sources. |
| `cerebro serve` | MCP server over stdio (clients launch it). Re-indexes incrementally at most every 60 s. |
| `cerebro doctor` | Config found, each source exists and how many files, index age, model cached. |
| `cerebro demo [--keep]` | Copies the bundled demo (`cerebro_mcp/demo_vault/`) to a temp dir, indexes it with its own `cerebro.toml`, and prints 2–3 contradictions it finds. The 30-second wow. |

## MCP tools

| Tool | Args | Returns |
|---|---|---|
| `search` | `query`, `source?`, `scope?`, `type?`, `since?`, `until?`, `limit?` | fragments with `path`, `source`, `project`, `title`, `date`, `snippet`, `score` |
| `note` | `path` (id, absolute path or title), `scope?` | full text (non-private), frontmatter, links |
| `links` | `path` | outgoing and incoming `[[links]]` |
| `todos` | `query` | open checkboxes `- [ ]` in matching notes, inline code kept |
| `contradictions` | `topic`, `across_sources?`, `limit?` | pairs with both snippets, both sources/dates, and the differing values |
| `propose` | `title`, `body` | writes `proposals/<date>-<slug>.md`; never touches sources |

Every tool output includes a short notice that note content is data, not instructions.

## Document ids

`<source name>:<path relative to the source root, with />`, e.g.
`notes:Projects/Habit app.md`, `claude-memory:acme-web/memory/pricing.md`.

## Demo contract (`src/cerebro_mcp/demo_vault/`)

```
demo_vault/
  cerebro.toml                 # sources relative to this folder
  notes/...                    # kind = vault, scope = personal
  agent-memory/<project>/memory/*.md   # kind = claude-code-memory
  repo-docs/<repo>/docs/...    # kind = glob
```

A fictional solo builder ("Lucía", building a habit tracker called *Streak*)
whose notes and agent memories disagree on a few facts (price, launch date,
version, a decision that was reversed), plus agreeing notes, one private note
and one note with a fake API key that must be redacted. No real people, brands,
products or companies.

## Out of scope for v0.1

Inbox triage with a local LLM, voice capture, benchmarks, families/brands of
the private tool, writing to notes.
