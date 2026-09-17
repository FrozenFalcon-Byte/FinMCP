# FinMCP

Personal finance copilot, MCP-native. The "brain" is an MCP server that owns your
financial data and exposes it as tools, resources and prompts. Any MCP client
(Claude Desktop, the bundled agent, Claude Code) can query it in natural language.

Status and roadmap live in the build console: `python progress/build.py` renders
`progress/index.html`.

## Layout

| Path        | What                                                      |
|-------------|-----------------------------------------------------------|
| `finmcp/`   | MCP server (mcp SDK 2.x), SQLite, categorizer, text-to-SQL |
| `finmcp/ingestion/` | Receipt OCR, statement PDF/CSV, UPI SMS parsers    |
| `agent/`    | MCP client + Claude agent loop, CLI REPL                   |
| `api/`      | FastAPI backend wrapping the agent                         |
| `web/`      | React + Vite frontend                                      |
| `tests/`    | pytest suite                                               |
| `progress/` | Build console (plan, generator, page)                      |

Full documentation is written as each phase lands.
