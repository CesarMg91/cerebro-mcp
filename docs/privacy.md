# Privacy

cerebro reads your most personal files: notes, journals, the memories your
agents keep about you. This page says exactly what it does with them.

## What runs where

| Step | Where |
|---|---|
| Reading files, parsing, redaction | Your machine |
| Embeddings | Your machine (CPU) |
| Index (`index.db`) | Your machine, in your user cache folder by default |
| Model download | Once, from the model's public host. After that, no network |
| Answering a tool call | The fragments the client asked for go to that client |

That last row matters. cerebro is local, but **the MCP client you connect may
not be**. If you connect a cloud-hosted assistant, the fragments it retrieves
are sent to that assistant's provider like anything else you paste into it.
cerebro limits *what* can be retrieved; it cannot control what the client does
after.

## Read-only

cerebro never edits, moves or deletes a file in a source. The only things it
writes are:

- its index (`[index] db`);
- `propose` output, in `[index] proposals`.

## Private notes

A note is private when:

- any folder in its path matches `private_folders` (case-insensitive; default
  `private` and `people`), or
- its frontmatter has the `private_frontmatter` key set to true (default
  `private: true`).

A private note is indexed by **path and content hash only**. No text,
fragments, embeddings, links or checkboxes are stored. Every query filters
private notes out in SQL. `search`, `note`, `links`, `todos` and
`contradictions` cannot return them, and `note` on a private path answers as if
the note were not there.

Note that a *non-private* note can still mention a private one, for example
with a `[[link]]` to a person's note. The linking note's text is not private.

## Redaction

Sensitive lines are redacted **before** a note is parsed, so the original value
never reaches the index. Packs are listed in `[privacy] redact`:

- `secrets`: API keys and tokens in widely used formats (for example strings
  starting with `sk_live_`, `ghp_`, `AKIA`), private key blocks, credential
  fields in pasted JSON;
- `cards`: payment card numbers;
- `mx`: Mexican identifiers (CLABE, RFC, CURP, INE).

Redaction is pattern matching. It will miss formats it does not know and will
sometimes hide things that only look like secrets. Keep real secrets in a
password manager, not in notes.

## Hidden scopes

`hidden_scopes = ["work"]` keeps a scope out of every result unless the caller
asks for that scope by name (`--scope work`, or `scope: "work"` in a tool call).
Use it for sources you want searchable on demand but not mixed into every
answer.

## Prompt injection

Notes can contain text written to manipulate an AI ("ignore your instructions
and..."), especially web clips. cerebro:

- adds a notice to every tool output saying the content is data, not
  instructions;
- marks notes with `source: web` as untrusted, and results from them carry that
  flag.

This lowers the risk; it does not remove it. A client that acts on tool output
without judgment can still be misled.

## The index file

`index.db` holds the text of every non-private, redacted fragment. Treat it like
the notes themselves: do not commit it, sync it to shared folders or attach it
to bug reports. Deleting it loses nothing; `cerebro index` rebuilds it.

## Telemetry

None. cerebro sends no usage data anywhere.

## Reporting a privacy bug

A way to make a private note's content appear in any output, or a secret that
survives redaction in a common format, is a security issue. Report it
privately: see [SECURITY.md](../SECURITY.md).
