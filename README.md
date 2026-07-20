# memos — Structural code index for AI agents

`memos` builds a **structural index** (symbols, call edges, imports) of a
TypeScript/TSX / Go codebase using tree-sitter and stores it in SQLite. It is the
first layer of a larger *Memory OS* for AI coding agents — instead of
grep-ing text, agents query **structure** (definitions, callers, callees).

## Quick start

```bash
uv sync                            # install deps
uv run memos index --path .        # index current project
uv run memos index --path . --full # force reindex (ignore hashes)
```

Indexes are stored at `{project}/.memos/memory.db`. Re-run to sync changes
(files are skipped if their content hash hasn't changed).

## Query

```bash
# Find a symbol by name
uv run memos query symbol greet

# Filter by kind
uv run memos query symbol greet --kind function

# Find who calls a symbol (callers)
uv run memos query calls greet --direction callers

# Find what a symbol calls (callees)
uv run memos query calls main --direction callees

# Show everything for a file (symbols + calls + imports)
uv run memos query module src/index.ts
```

All query commands output JSON and accept `--path <project_root>` to point at
an indexed project (defaults to current directory).

## HTTP API

Start the FastAPI server on an indexed project:

```bash
# via CLI
uv run memos serve --path /project --port 8000

# or via uvicorn directly
MEMOS_PROJECT_PATH=/project uv run uvicorn memos.api.main:app
```

Endpoints:

| Method | Path | Description |
|--------|------|-------------|
| GET | `/symbols?name=greet&kind=function` | Find symbols by name |
| GET | `/symbols/{id}/calls?direction=callers\|callees` | Find callers/callees of a symbol |
| GET | `/modules/{path}` | Show everything for a file |

All endpoints return JSON. Set `MEMOS_PROJECT_PATH` (defaults to `.`).

## Semantic Search

```bash
# Via HTTP API
curl -X POST http://localhost:8000/search/semantic \
  -H "Content-Type: application/json" \
  -d '{"query": "user authentication", "top_k": 5}'
```

Uses `all-MiniLM-L6-v2` embeddings via fastembed (ONNX, no GPU required).

## MCP Server

Start the Memory OS MCP server for AI agents:

```bash
uv run memos serve-mcp --path /project
```

Available tools:

| Tool | Description |
|------|-------------|
| `find_symbol_tool` | Search symbols by name (+ kind, file filter) |
| `find_calls_tool` | Find callers or callees of a symbol |
| `get_module_tool` | Full file info (symbols, calls, imports) |
| `semantic_search_tool` | Natural language search over code |
| `list_files_tool` | List all indexed files |
| `list_symbols_tool` | List all indexed symbols |
| `list_projects_tool` | Current project info with stats |

Configure in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "memory-os": {
      "command": "uv",
      "args": ["run", "memos", "serve-mcp", "--path", "/ABSOLUTE/PATH/TO/PROJECT"],
      "env": {}
    }
  }
}
```

## Test

```bash
uv run pytest -v
```

## Architecture notes

- **Two memory types**: *derived* (AST, summaries — reproducible, keyed by
  content hash) and *episodic* (agent notes — append-only, survives refactors).
- **Indexer** produces plain dataclasses (`ParseResult`); CLI converts them to
  pydantic models for DB insertion.
- **Call edges** and **imports** are stored unresolved (FK = NULL) on first
  pass; second-pass resolution is a separate task.
- The CLI (`memos index`) is a thin adapter over `indexer/` + `core/db.py` —
  no business logic.
- Semantic search: sqlite-vec vec0 table, lazy-loaded fastembed model, cascade
  cleanup on reindex (`--no-embed` flag to skip).
- MCP server (`memos serve-mcp`) is a thin FastMCP adapter over `query/core.py`
  — same pattern as the FastAPI adapter.
