# Connecting MCP clients

`cerebro serve` is an MCP server over **stdio**: the client starts it as a child
process and talks to it through stdin/stdout. You never run it by hand, and it
never opens a network port.

Two ways to launch it:

| You have | Command |
|---|---|
| Nothing installed (just uv) | `uvx cerebro-mcp serve` |
| `uv tool install cerebro-mcp` | `cerebro serve` |

`uvx` caches the package after the first run, so later starts are fast. The
installed command starts a little faster and does not check for new versions.

## Which config file the server uses

In order: `--config PATH`, `$CEREBRO_CONFIG`, `./cerebro.toml` (relative to the
directory the client starts the server in, which is often not what you expect),
then your user config folder. The safest choice for MCP is to pass it
explicitly:

```json
"env": { "CEREBRO_CONFIG": "/home/you/.config/cerebro/cerebro.toml" }
```

Run `cerebro doctor` in a terminal to see the path of the config it finds.

## Claude Code

```sh
claude mcp add cerebro --scope user -- uvx cerebro-mcp serve
```

With a specific config:

```sh
claude mcp add cerebro --scope user -e CEREBRO_CONFIG=/path/to/cerebro.toml -- uvx cerebro-mcp serve
```

`--scope user` makes it available in every project. Check with `claude mcp list`.

## Codex

`~/.codex/config.toml`:

```toml
[mcp_servers.cerebro]
command = "uvx"
args = ["cerebro-mcp", "serve"]
# env = { CEREBRO_CONFIG = "/path/to/cerebro.toml" }
```

## Cursor

`~/.cursor/mcp.json` (all projects) or `.cursor/mcp.json` (one project):

```json
{
  "mcpServers": {
    "cerebro": {
      "command": "uvx",
      "args": ["cerebro-mcp", "serve"],
      "env": { "CEREBRO_CONFIG": "/path/to/cerebro.toml" }
    }
  }
}
```

## Claude Desktop

Edit `claude_desktop_config.json`:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "cerebro": {
      "command": "uvx",
      "args": ["cerebro-mcp", "serve"],
      "env": { "CEREBRO_CONFIG": "/path/to/cerebro.toml" }
    }
  }
}
```

Restart the app after editing.

## Any other MCP client

Anything that can launch a stdio server works. The command is `uvx` with
arguments `cerebro-mcp serve`, or `cerebro` with argument `serve`.

## Windows notes

- Desktop apps do not always inherit your shell's `PATH`. If the client says it
  cannot find `uvx`, use the full path (find it with `where uvx` in a terminal,
  usually `C:\Users\<you>\.local\bin\uvx.exe`).
- In JSON, escape backslashes: `"C:\\Users\\you\\cerebro.toml"`, or use forward
  slashes, which work too.

## Checking it works

1. `cerebro doctor`: config found, sources exist, index age, model cached.
2. `cerebro index` once in a terminal, so the first tool call does not wait for
   a full index and the model download.
3. In the client, ask something only your notes know, then ask for
   contradictions on a topic you know has changed.

The server re-indexes incrementally at most every 60 seconds, so edits show up
without restarting the client.

## Tools the client gets

| Tool | Args |
|---|---|
| `search` | `query`, `source?`, `scope?`, `type?`, `since?`, `until?`, `limit?` |
| `note` | `path` (id, absolute path or title), `scope?` |
| `links` | `path` |
| `todos` | `query` |
| `contradictions` | `topic`, `across_sources?`, `limit?` |
| `propose` | `title`, `body` |

Every output starts with a notice that note content is data, not instructions.
