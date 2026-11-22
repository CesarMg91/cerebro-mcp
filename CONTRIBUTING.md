# Contributing

Thanks for helping. cerebro is small on purpose; the best contributions keep it
that way.

## Setup

You need [uv](https://docs.astral.sh/uv/) and Python 3.11 or newer.

```sh
git clone <your fork>
cd cerebro-mcp
uv sync
uv run pytest                  # fast tests, no embedding model needed
uv run pytest -m model         # tests that need the model (downloads it on first run)
uv run cerebro demo            # end-to-end check
```

Tests that need the embedding model are marked `@pytest.mark.model`. CI runs the
fast suite on Linux and Windows with Python 3.11 and 3.12, and the model tests
plus the demo on Linux.

## Ground rules

- **Never commit real notes.** Fixtures and the demo vault are fictional: no
  real people, companies, products or personal data. If you need a new
  fixture, invent it.
- **Read-only stays read-only.** No code path may write to a source folder.
  The only writes are the index and `propose` output.
- **Privacy changes need tests.** Anything touching private notes, redaction,
  hidden scopes or the egress filter needs a test proving private content does
  not come out. Add the case to the demo vault if it helps others see it.
- **Cross-platform.** Paths, globs and ids must behave the same on Windows,
  macOS and Linux. Ids always use `/`.
- **English** in code, CLI output, MCP tools and docs. If you change
  `README.md`, update `README.es.md` too (or say in the PR that you could not).

## Pull requests

- One concern per PR. Small is easier to review.
- Describe what changed, why, and how you tested it, including what you did
  not test.
- If the change alters the CLI, the MCP tools or the config format, update
  `docs/SPEC.md` and the README in the same PR.
- New dependencies need a reason. cerebro should stay quick to `uvx`.

## Adding a source kind

A new kind (another agent's memory format, for example) needs: a parser, the
`project` rule, an id example in `docs/architecture.md`, fixtures, and tests for
private folders and redaction on that kind.

## Adding a redaction pack

Include the patterns, positive and negative test cases (things that look
similar but must not be redacted), and a line in `docs/privacy.md`. Use
obviously fake values in tests.

## Reporting bugs and ideas

Use the issue templates. For anything that could expose private notes or
secrets, do not open a public issue: see [SECURITY.md](SECURITY.md).
