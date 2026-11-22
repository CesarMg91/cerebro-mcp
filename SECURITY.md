# Security policy

cerebro indexes personal notes and agent memories, so privacy bugs are security
bugs.

## Reporting a vulnerability

**Please do not open a public issue.** Report it privately through GitHub
Security Advisories: open the repository's **Security** tab and click
**Report a vulnerability**.

Include what you did, what you expected, what happened, your OS, Python version
and cerebro version. Use fictional notes in any reproduction; never send your
real notes or your `index.db`.

You will get an answer within a week. Once a fix is released, the advisory is
published with credit to you, unless you prefer otherwise.

## In scope

- Content of a private note (private folder or `private: true`) appearing in
  any CLI or MCP output, or stored in the index.
- A secret in a common format that survives an enabled redaction pack.
- Content from a hidden scope returned without that scope being requested.
- cerebro writing, moving or deleting anything outside its index and proposals
  folder (path traversal in `note` or `propose`, for example).
- The MCP server reaching the network or executing content from notes.

## Out of scope

- What an MCP client does with fragments it was legitimately given.
- A model being persuaded by a prompt injection inside a note. cerebro marks
  content as data and flags web clips; report it only if those marks are
  missing.
- Secrets in formats no enabled pack claims to cover (a feature request is
  welcome).

## Supported versions

Only the latest release receives security fixes while the project is at 0.x.
