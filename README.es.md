# cerebro-memory

**Un índice local, de sólo lectura, de tus notas en Markdown *y* de las memorias de tus agentes de IA, servido por MCP, que te avisa cuando se contradicen.**

<!-- demo gif -->

[English](README.md)

## Por qué

Escribes una decisión en tus notas. Tu agente de código guardó en su memoria
una versión vieja hace tres meses. Un documento de relevo en otro repo dice una
tercera cosa. Nadie se da cuenta hasta que un agente, muy seguro de sí mismo,
publica el precio viejo, la fecha de lanzamiento vieja o la función que ya
habías descartado.

`cerebro` indexa todo eso en tu computadora (tu bóveda de Obsidian, las
memorias de Claude Code, los docs y relevos de tus repos) y te da, a ti y a
cualquier cliente MCP, un solo lugar para buscar y un comando para preguntar:
*¿en qué se contradicen mis fuentes?*

- **Búsqueda híbrida** que funciona en español y en inglés (y en otros
  idiomas): nombres exactos con búsqueda de texto completo, paráfrasis con
  embeddings multilingües.
- **Contradicciones:** pares de fragmentos sobre un tema que dan precios,
  fechas, versiones o respuestas de sí/no distintas, con las dos fuentes y sus
  fechas.
- **Local y de sólo lectura.** Nunca edita tus archivos. Las notas privadas
  nunca salen del índice. Los secretos se tachan antes de guardar nada.

## Arranque rápido (30 segundos)

Necesitas [uv](https://docs.astral.sh/uv/).

```sh
uvx cerebro-memory demo
```

Copia una bóveda ficticia pequeña a una carpeta temporal, la indexa e imprime
las contradicciones que encuentra. La primera vez descarga el modelo de
embeddings; de ahí en adelante todo corre sin conexión.

Luego apúntalo a tus notas:

```sh
uv tool install cerebro-memory        # instala el comando `cerebro`
cerebro init --vault ~/Obsidian    # escribe cerebro.toml; agrega ~/.claude/projects si existe
cerebro index                      # incremental; córrelo cuando quieras
cerebro search "decisión de precio"
cerebro contradictions "fecha de lanzamiento" --across-sources
```

## Qué encuentra

Salida real de `uvx cerebro-memory demo` (muestra el desacuerdo más fuerte de cada par de notas; para un tema en particular usa `cerebro contradictions "<tema>"`):

```text
$ uvx cerebro-memory demo
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

La bóveda de ejemplo está en
[`src/cerebro_mcp/demo_vault/`](src/cerebro_mcp/demo_vault/); su README lista
cada dato que se sembró ahí.

## Conéctalo a tus agentes

`cerebro serve` es un servidor MCP por stdio. Lo lanza tu cliente; tú nunca lo
corres a mano. Si instalaste la herramienta, el comando es `cerebro serve`; sin
instalar, es `uvx cerebro-memory serve`.

**Claude Code**

```sh
claude mcp add cerebro --scope user -- uvx cerebro-memory serve
```

**Codex** (`~/.codex/config.toml`)

```toml
[mcp_servers.cerebro]
command = "uvx"
args = ["cerebro-memory", "serve"]
```

**Cursor** (`~/.cursor/mcp.json`) y **Claude Desktop** (`claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "cerebro": {
      "command": "uvx",
      "args": ["cerebro-memory", "serve"]
    }
  }
}
```

Para usar otro archivo de configuración, agrega
`"env": { "CEREBRO_CONFIG": "/ruta/a/cerebro.toml" }`. Más detalle, dónde vive
cada archivo y notas para Windows: [docs/connect.md](docs/connect.md).

### Herramientas MCP

| Herramienta | Qué hace |
|---|---|
| `search` | Búsqueda híbrida con filtros (`source`, `scope`, `type`, `since`, `until`) |
| `note` | Texto completo, frontmatter y enlaces de una nota (por id, ruta o título) |
| `links` | Enlaces `[[...]]` que salen de una nota y los que llegan a ella |
| `todos` | Casillas abiertas `- [ ]` en las notas que coinciden con una búsqueda |
| `contradictions` | Pares de fragmentos sobre un tema que dan valores distintos |
| `propose` | Escribe una propuesta en Markdown en la carpeta propia de cerebro; nunca toca tus notas |

## Configuración

`cerebro init` escribe un archivo inicial. Un ejemplo completo:

```toml
[[source]]
name = "notes"
kind = "vault"                 # Obsidian/Markdown: frontmatter, [[enlaces]], casillas
path = "~/Obsidian"
scope = "personal"
exclude = ["Templates/**"]

[[source]]
name = "claude-memory"
kind = "claude-code-memory"    # <path>/<proyecto>/memory/*.md
path = "~/.claude/projects"

[[source]]
name = "handoffs"
kind = "glob"                  # cualquier Markdown que coincida con los globs de include
path = "~/code"
include = ["*/docs/**/*.md", "*/AGENTS.md", "*/CLAUDE.md"]
scope = "work"

[privacy]
private_folders = ["private", "people"]
private_frontmatter = "private"
redact = ["secrets", "cards"]
```

La configuración se busca en este orden: `--config RUTA`, `$CEREBRO_CONFIG`,
`./cerebro.toml` y luego la carpeta de configuración de tu usuario. Corre
`cerebro doctor` para ver qué archivo usó, cuántos archivos tiene cada fuente y
si el modelo ya está descargado.

## Privacidad

- **Sólo lectura.** cerebro nunca edita, mueve ni borra un archivo de tus
  fuentes. Lo único que escribe, aparte de su índice, es `propose`, en su
  propia carpeta de propuestas.
- **Local.** Leer, indexar y calcular embeddings ocurre en tu computadora. La
  única llamada a la red es la descarga del modelo, una sola vez. Sólo salen
  del proceso los fragmentos que un cliente pide, y sólo hacia ese cliente.
- **Lo privado se queda privado.** Una nota en una carpeta privada
  (`private/`, `people/` por omisión) o con `private: true` se indexa sólo por
  ruta y hash. Toda consulta filtra las notas privadas en el SQL, así que
  ninguna herramienta puede devolverlas.
- **Se tacha antes de guardar.** Las líneas con llaves de API, tokens, llaves
  privadas o números de tarjeta se tachan antes de leer la nota. Paquetes:
  `secrets`, `cards` y `mx` (CLABE, RFC, CURP e INE).
- **Alcances ocultos.** Las fuentes de un alcance oculto se indexan, pero sólo
  aparecen cuando se pide ese alcance por nombre.
- **El contenido es dato, no instrucciones.** Cada respuesta de las
  herramientas lleva un aviso que lo dice, y los recortes de la web
  (`source: web`) se marcan como no confiables.

Detalle y límites: [docs/privacy.md](docs/privacy.md).

## Cómo funciona

```text
  Fuentes en Markdown                  bóveda · memorias de agentes · docs de repos
        │
        ▼
  tachar líneas sensibles ─► leer frontmatter, [[enlaces]], casillas - [ ]
        │
        ▼
  partir en fragmentos por encabezado ─► saltar lo que no cambió (hash)
        │
        ├──────────────────────────────┐
        ▼                              ▼
  SQLite FTS5 (palabras, BM25)   sqlite-vec (embeddings multilingües, CPU)
        │                              │
        └──────────► fusión RRF ◄──────┘
                         │
                         ▼
        filtro de salida en SQL (sin notas privadas ni alcances ocultos)
                         │
                         ▼
          CLI  ·  herramientas MCP por stdio  ·  contradicciones
```

El Markdown es la verdad; el índice es desechable. Borra `index.db`, vuelve a
correr `cerebro index` y no se pierde nada. Más en
[docs/architecture.md](docs/architecture.md) y
[docs/contradictions.md](docs/contradictions.md) (en inglés).

## Lo que sigue

La v0.1 es el núcleo: índice, búsqueda híbrida, contradicciones, servidor MCP y
demo. Ideas para después, sin orden y sin promesa:

- Formatos de memoria de más agentes y editores.
- Un modelo local que juzgue los candidatos a contradicción (hoy lo hace el
  cliente).
- Un modo que reindexe al cambiar un archivo en vez de cada cierto tiempo.
- Más paquetes de tachado (se aceptan contribuciones).
- `contradictions` acotado a un rango de fechas o a un proyecto.

## Contribuir

Reportes de errores y pull requests son bienvenidos. Lee primero
[CONTRIBUTING.md](CONTRIBUTING.md); los problemas de seguridad van por
[SECURITY.md](SECURITY.md), no en issues públicos.

## Créditos

Hecho por **César Méndez**, cirujano y builder. [cesarmendez.dev](https://cesarmendez.dev)

Publicado bajo la [licencia MIT](LICENSE).
