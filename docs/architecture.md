# Architecture

This page explains how cerebro turns folders of Markdown into a searchable,
privacy-filtered index. The contract (CLI, MCP tools, config) lives in
[SPEC.md](SPEC.md); if this page and the code disagree, the code wins and this
page has a bug.

## Principles

1. **Markdown is the truth; the index is disposable.** `index.db` can be
   deleted at any time. `cerebro index` rebuilds it from the files.
2. **Read-only.** Sources are never edited, moved or deleted. The only write
   outside the index is `propose`, into cerebro's own proposals folder.
3. **Local.** Parsing, indexing and embeddings run on the machine.
4. **Private stays private**, enforced in SQL, not in the client.
5. **Content is data, not instructions.**

## Pipeline

```text
  sources (cerebro.toml)
     │  walk files: include/exclude globs, hidden folders skipped
     ▼
  read file ─► content hash ─► unchanged? skip
     │
     ▼
  privacy check: private folder or private frontmatter?
     │   yes ─► store path + hash only, stop here
     ▼
  redact sensitive lines (enabled packs)
     │
     ▼
  parse: frontmatter, title, [[links]], checkboxes, source kind metadata
     │
     ▼
  split into fragments (by heading, bounded size)
     │
     ├─► FTS5 table (text)
     └─► sqlite-vec table (embedding per fragment)
```

## Sources and document ids

Each `[[source]]` in `cerebro.toml` has a unique `name`, a `kind`, a `path` and
an optional `scope` (a free label, `"default"` if omitted).

| Kind | What is read | `project` |
|---|---|---|
| `vault` | Every `.md` under `path`, minus `exclude` globs | none |
| `claude-code-memory` | `<path>/<project>/memory/*.md`; `MEMORY.md` (the index file) is skipped | the project folder name |
| `glob` | Markdown matched by the `include` globs | first path segment |

Hidden folders (starting with `.`) are always skipped.

A document id is `<source name>:<path relative to the source root, with />`:

```text
notes:Projects/Launch plan.md
agent-memory:streak-app/memory/pricing.md
repo-docs:streak-app/docs/handoff-2026-11-18.md
```

Ids use forward slashes on every OS, so the same vault gives the same ids on
Windows, macOS and Linux. `note` also accepts an absolute path or a title.

## Parsing

- **Frontmatter** (YAML). `type`, `date`, `tags`, `source` and the private flag
  are read; everything else is kept as-is for `note`. Claude Code memories use
  `name`, `description` and `metadata.type`.
- **Title**: the first `# heading`, else the frontmatter `name`/`title`, else
  the file name.
- **Links**: `[[Target]]`, `[[Target|alias]]` and `[[Target#heading]]` are
  resolved by title within the same source. `links` returns both directions.
- **Checkboxes**: `- [ ]` is open, `- [x]` is done. `todos` returns open ones
  with inline code kept intact, because a todo like ``fix `rollover()` `` loses
  its meaning without it.
- **Web clips**: `source: web` in frontmatter marks the note untrusted. Results
  from it carry that flag.

## Index

One SQLite file holds everything:

- a notes table: id, source, project, scope, path, title, type, date, hash,
  private flag, untrusted flag;
- a fragments table: note id, heading, text;
- an FTS5 virtual table over fragment text;
- a `sqlite-vec` table with one embedding per fragment;
- link and checkbox tables for `links` and `todos`.

Private notes have a row in the notes table (path and hash, so the indexer
knows they exist and when they change) and **nothing else**: no fragments, no
FTS rows, no vectors, no links.

## Ranking

Search runs two retrievers and fuses them with Reciprocal Rank Fusion (RRF):

```text
  query ──► FTS5 / BM25 ──► ranked list A   (exact names, code, ids)
        └─► embedding  ──► ranked list B   (paraphrases, other language)

  score(fragment) = Σ over lists  1 / (k + rank in that list)
```

RRF uses ranks, not raw scores, so BM25 and cosine similarity never have to be
put on the same scale. A fragment found by both retrievers rises to the top.
Results are grouped so each note appears once, with its best fragment.

`--text` skips the vector side (useful for exact strings, or when the model is
not available). If the model fails to load, search falls back to text only and
says so in the result.

## Privacy and egress

The **egress rule**: every query that returns content joins the notes table
and filters, in the same SQL statement:

- private notes out, always;
- notes whose scope is in `hidden_scopes` out, unless the caller asked for that
  scope by name.

Because the rule sits in the query and private notes have no fragments, a bug
in a tool handler cannot leak a private note's text: there is no text to leak.
See [privacy.md](privacy.md).

## Redaction packs

Before a note is parsed, each line is checked against the enabled packs. A
matching span is replaced with a placeholder such as `[redacted:secret]` and
the original never reaches the index.

| Pack | Aims at |
|---|---|
| `secrets` | API keys and tokens in common formats, private key blocks, credential-looking JSON fields |
| `cards` | Payment card numbers |
| `mx` | Mexican identifiers: CLABE, RFC, CURP, INE |

Redaction is pattern-based and errs on the side of hiding. It is a safety net,
not a reason to keep secrets in notes.

## Incremental indexing

- Each file's content hash is stored. On `cerebro index`, unchanged files are
  skipped; changed files are re-parsed and re-embedded; deleted files leave the
  index.
- A source removed from `cerebro.toml` leaves the index on the next run.
- `--full` drops everything and rebuilds.
- Changing the embedding model or the redaction packs requires `--full` (the
  stored vectors and texts were made with the old settings).
- `cerebro serve` re-indexes incrementally at most every 60 seconds, so a client
  sees edits without a manual step.

## Contradictions

`contradictions` finds candidate pairs; the human or the client judges them.
How it works and where it fails: [contradictions.md](contradictions.md).

## MCP server

`cerebro serve` speaks MCP over stdio. Tools: `search`, `note`, `links`,
`todos`, `contradictions`, `propose`. Every tool output includes a notice that
note content is data, not instructions. `propose` writes
`proposals/<date>-<slug>.md` in cerebro's own folder and nothing else.

## Embeddings: choice and why

**Runtime:** [`fastembed`](https://github.com/qdrant/fastembed) on ONNX Runtime, no
`torch`. **Model:** `multilingual-e5-small` (384 dimensions, mean pooling,
normalized, with the e5 `query:` / `passage:` prefixes), registered as a custom
fastembed model because its built-in list has no small multilingual e5.

| Option | Download | Recall@2 (16 relevant, ES + EN + cross-language) | Same vectors as torch | Encode 12 passages |
|---|---|---|---|---|
| torch + sentence-transformers | ~500 MB of torch alone | 15/16 | reference | 0.37 s |
| ONNX full precision (`e5-small`) | 470 MB | 15/16 | identical (cosine 1.0000) | 0.21 s |
| **ONNX int8 (`e5-small-int8`, default)** | **118 MB** | **16/16** | cosine ≥ 0.9947, mean 0.9966 | **0.17 s** |

- The whole environment (fastembed, onnxruntime, tokenizers, mcp) is about
  186 MB; with torch it would be over 700 MB.
- The int8 model peaks at about 500 MB of RAM. It is the default because the
  first run of `uvx cerebro-mcp demo` downloads less and starts faster.
- Pick the full-precision export with `[index] model = "e5-small"` or
  `CEREBRO_MODEL=e5-small`. Changing the model drops old vectors and re-embeds
  on the next `cerebro index`.
- **Cache:** fastembed's default cache, or `FASTEMBED_CACHE_PATH`;
  `CEREBRO_MODEL_CACHE` forces a folder. Pre-download on a machine with network
  by running `cerebro index` once, then copy that folder.
- **Without the model:** `--text` on `index`, `search`, `contradictions`,
  `serve` and `demo` uses full-text search only. If the model cannot load,
  indexing falls back to text with a warning, and a later normal run adds the
  missing vectors.
- The quality check was small (12 passages, 8 queries); it rules out a clear
  regression, it is not a benchmark.
