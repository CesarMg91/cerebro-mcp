# cerebro-mcp

**A local, read-only index over your Markdown notes *and* your AI agents' memories, served over MCP, that tells you when they contradict each other.**

<!-- demo gif -->

[Español](README.es.md)

## Why

You write a decision in your notes. Your coding agent saved an older version of
it in its memory three months ago. A handoff doc in another repo says a third
thing. Nobody notices until an agent confidently ships the old price, the old
launch date or the feature you already killed.

`cerebro` indexes all of it on your machine (your Obsidian vault, Claude Code
memories, repo docs and handoffs) and gives you, and any MCP client, one place
to search it and one command to ask: *where do my sources disagree?*

- **Hybrid search** that works in English and Spanish (and other languages):
  exact names via full-text search, paraphrases via multilingual embeddings.
- **Contradictions**: pairs of fragments on a topic that state different
  prices, dates, versions or yes/no answers, with both sources and dates.
- **Local and read-only.** Your files are never edited. Private notes never
  leave the index. Secrets are redacted before anything is stored.

## Quickstart (30 seconds)

You need [uv](https://docs.astral.sh/uv/).

```sh
uvx cerebro-mcp demo
```

That copies a small fictional vault to a temp folder, indexes it and prints the
contradictions it finds. The first run downloads the embedding model once;
after that everything runs offline.

Then point it at your own notes:

```sh
uv tool install cerebro-mcp        # installs the `cerebro` command
cerebro init --vault ~/Obsidian    # writes cerebro.toml; adds ~/.claude/projects if it exists
cerebro index                      # incremental; re-run any time
cerebro search "pricing decision"
cerebro contradictions "launch date" --across-sources
```

## What it finds

Real output of `uvx cerebro-mcp demo` (it prints the strongest disagreement per pair of notes; ask about one topic with `cerebro contradictions "<topic>"`):

```text
$ uvx cerebro-mcp demo
Demo vault copied to /tmp/cerebro-demo-x1y2z3/demo_vault
Indexed 26 notes from 3 sources (notes, agent-memory, repo-docs): 2 private (kept out of every result), 1 line(s) redacted, mode hybrid.

Your notes and your agents disagree on 3 things (older -> newer):

1. price: $4.99/month  ->  $5.99/month; price: $35/year  ->  $39/year; number: 7-day  ->  14 days
   older  2026-07-02  agent-memory:streak-web/memory/pricing.md
                      - Pro monthly: $4.99/month - Pro yearly: $35/year - 7-day free trial on both plans. Why: set when the pricing page was first built, from Lucía's brai…
   newer  2026-09-15  repo-docs:streak-web/docs/pricing-page.md
                      …Price | Free trial | |---|---|---| | Free | $0, up to 3 habits | none | | Pro monthly | $5.99/month | 14 days | | Pro yearly | $39/year | 14 days | …

2. version: 0.8.5  ->  0.9.3 / 0.9.0; date: December 1, 2026  ->  2027-01-12 / 2026-12-15
   older  2026-08-21  agent-memory:streak-app/memory/project-overview.md
                      …SQLite file is the source of truth; sync is optional and Pro-only. - Current version: 0.8.5 (beta channel). - Launch date: December 1, 2026. - Free …
   newer  2026-11-18  repo-docs:streak-app/docs/handoff-2026-11-18.md
                      - Current version: 0.9.3, in the beta channel since this morning. It fixes the midnight rollover in StreakClock.rollover() for UTC+9 and UTC-10. - La…

3. number: 7-day  ->  14 días
   older  2026-07-02  agent-memory:streak-web/memory/pricing.md
                      - Pro monthly: $4.99/month - Pro yearly: $35/year - 7-day free trial on both plans. Why: set when the pricing page was first built, from Lucía's brai…
   newer  2026-11-17  notes:Daily/2026-11-17.md
                      Martes tranquilo. Revisé las conversiones del beta: con la prueba de 14 días, 4 de 11 testers activaron Pro al terminarla. Me quedo con 14 días aunqu…

Run it on your own notes: cerebro init --vault ~/path/to/notes && cerebro index
```

The demo vault is in [`src/cerebro_mcp/demo_vault/`](src/cerebro_mcp/demo_vault/);
its README lists every fact planted in it.

## Connect it to your agents

`cerebro serve` is an MCP server over stdio. Your client launches it; you never
run it by hand. If you installed the tool, the command is `cerebro serve`;
without installing, it is `uvx cerebro-mcp serve`.

**Claude Code**

```sh
claude mcp add cerebro --scope user -- uvx cerebro-mcp serve
```

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.cerebro]
command = "uvx"
args = ["cerebro-mcp", "serve"]
```

**Cursor** (`~/.cursor/mcp.json`) and **Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "cerebro": {
      "command": "uvx",
      "args": ["cerebro-mcp", "serve"]
    }
  }
}
```

To use a config file other than the default, add
`"env": { "CEREBRO_CONFIG": "/path/to/cerebro.toml" }`. More detail, file
locations and Windows notes: [docs/connect.md](docs/connect.md).

### MCP tools

| Tool | What it does |
|---|---|
| `search` | Hybrid search with filters (`source`, `scope`, `type`, `since`, `until`) |
| `note` | Full text, frontmatter and links of one note (by id, path or title) |
| `links` | Outgoing and incoming `[[links]]` |
| `todos` | Open checkboxes `- [ ]` in the notes that match a query |
| `contradictions` | Pairs of fragments on a topic that state different values |
| `propose` | Writes a Markdown proposal into cerebro's own folder; never touches your notes |

## Configuration

`cerebro init` writes a starter file. A full example:

```toml
[[source]]
name = "notes"
kind = "vault"                 # Obsidian/Markdown: frontmatter, [[links]], checkboxes
path = "~/Obsidian"
scope = "personal"
exclude = ["Templates/**"]

[[source]]
name = "claude-memory"
kind = "claude-code-memory"    # <path>/<project>/memory/*.md
path = "~/.claude/projects"

[[source]]
name = "handoffs"
kind = "glob"                  # any Markdown matched by the include globs
path = "~/code"
include = ["*/docs/**/*.md", "*/AGENTS.md", "*/CLAUDE.md"]
scope = "work"

[privacy]
private_folders = ["private", "people"]
private_frontmatter = "private"
redact = ["secrets", "cards"]
```

The config is looked up in this order: `--config PATH`, `$CEREBRO_CONFIG`,
`./cerebro.toml`, then your user config folder. Run `cerebro doctor` to see
which file was used, how many files each source has and whether the model is
cached.

## Privacy model

- **Read-only.** cerebro never edits, moves or deletes a source file. The only
  thing it writes besides its index is `propose`, into its own proposals folder.
- **Local.** Parsing, indexing and embeddings run on your machine. The only
  network call is the one-time model download. Only the fragments a client asks
  for leave the process, and only to that client.
- **Private notes stay private.** A note in a private folder (`private/`,
  `people/` by default) or with `private: true` is indexed by path and hash
  only. Every query filters private notes out in SQL, so no tool can return them.
- **Redaction before storage.** Lines with API keys, tokens, private keys or
  card numbers are redacted before the note is parsed. Packs: `secrets`,
  `cards`, and `mx` (Mexican IDs and bank numbers).
- **Hidden scopes.** Sources in a hidden scope are indexed but only returned
  when that scope is asked for by name.
- **Content is data, not instructions.** Every tool output carries a short
  notice saying so, and web clips (`source: web`) are marked untrusted.

Details and limits: [docs/privacy.md](docs/privacy.md).

## How it works

```text
  Markdown sources                     vault · agent memories · repo docs
        │
        ▼
  redact sensitive lines ─► parse frontmatter, [[links]], - [ ] checkboxes
        │
        ▼
  split into fragments by heading ─► skip unchanged files (content hash)
        │
        ├──────────────────────────────┐
        ▼                              ▼
  SQLite FTS5 (keywords, BM25)   sqlite-vec (multilingual embeddings, CPU)
        │                              │
        └──────────► RRF fusion ◄──────┘
                         │
                         ▼
        egress filter in SQL (no private notes, no hidden scopes)
                         │
                         ▼
          CLI  ·  MCP tools over stdio  ·  contradictions
```

Markdown is the truth; the index is disposable. Delete `index.db` and run
`cerebro index` again: nothing is lost. More in
[docs/architecture.md](docs/architecture.md) and
[docs/contradictions.md](docs/contradictions.md).

## Roadmap

v0.1 is the core: index, hybrid search, contradictions, MCP server, demo.
Ideas for later, in no particular order and not promised:

- Memory formats of more agents and editors.
- A local model to judge contradiction candidates (today the client does).
- A watch mode that re-indexes on file change instead of on a timer.
- More redaction packs (contributions welcome).
- `contradictions` limited to a date range or a project.

## Contributing

Bug reports and pull requests are welcome. Read
[CONTRIBUTING.md](CONTRIBUTING.md) first; security issues go through
[SECURITY.md](SECURITY.md), not public issues.

## Credits

Built by **César Méndez** — surgeon and builder. [cesarmendez.dev](https://cesarmendez.dev)

Released under the [MIT License](LICENSE).
