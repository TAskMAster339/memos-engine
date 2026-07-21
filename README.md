# memos — Structural code index for AI agents

[GitHub: TAskMAster339/memos-engine](https://github.com/TAskMAster339/memos-engine.git)

`memos` builds a **structural index** (symbols, call edges, imports) of a
TypeScript/TSX / Go codebase using tree-sitter and stores it in SQLite. It is the
first layer of a larger *Memory OS* for AI coding agents — instead of
grep-ing text, agents query **structure** (definitions, callers, callees).

## Quick start

```bash
# Clone and install globally
git clone https://github.com/TAskMAster339/memos-engine.git
cd memos-engine
uv tool install -e .

# Index a project
memos index --path /path/to/your/project

# Start the MCP server for AI agents
memos serve-mcp
```

Indexes are stored at `{project}/.memos/memory.db`. Re-run to sync changes
(files are skipped if their content hash hasn't changed).

Or using `uv run` without global install:

```bash
uv sync                            # install deps
uv run memos index --path .        # index current project
uv run memos index --path . --full # force reindex (ignore hashes)
```

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
| GET | `/symbols/{id}/context` | Full context (symbol + callers + callees + memories + summary) |
| GET | `/symbols/{id}/rename-impact` | Analyse rename blast radius |
| GET | `/modules/{path}` | Show everything for a file |
| GET | `/modules/{path}/diff-impact` | Analyse diff blast radius for exported symbols |
| GET | `/unused-symbols` | Find private functions never called |
| GET | `/dead-imports` | Find unresolved imports |
| GET | `/dependency-graph` | File-level dependency graph |
| GET | `/import-cycles` | Find import cycles |
| POST | `/search/semantic` | Semantic search by natural language |
| POST | `/memories` | Add memory entry |
| GET | `/memories` | List memory entries |
| GET | `/memories/search?query=...` | Full-text search over memory entries |
| POST | `/memories/prune` | Delete stale memory entries (dry-run by default) |

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

The MCP server exposes the indexed codebase to AI agents. Install globally:

```bash
uv tool install -e ~/memos-engine
memos serve-mcp
```

Or without global install:

```bash
uv run memos serve-mcp
```

The server starts without a project. Use the `open_project` tool to select a project:

```json
{
  "tool": "open_project",
  "arguments": {
    "path": "/path/to/your/project"
  }
}
```

The server auto-indexes the project if it hasn't been indexed yet. Multiple projects can be opened and queried in the same session without restarting the server.

Available tools:

| Tool | Description |
|------|-------------|
| `open_project` | Open a project by path (auto-indexes if needed) |
| `find_symbol_tool` | Search symbols by name (+ kind, file filter) |
| `find_calls_tool` | Find callers or callees of a symbol |
| `get_module_tool` | Full file info (symbols, calls, imports) |
| `get_context_tool` | Full context before editing (symbol + callers + callees + memories + summary) |
| `semantic_search_tool` | Natural language search over code |
| `list_files_tool` | List all indexed files |
| `list_symbols_tool` | List all indexed symbols |
| `list_projects_tool` | Current project info with stats |
| `memory_add_note` | Add a note to episodic memory |
| `get_memories` | Retrieve memory entries |
| `rename_impact_tool` | Analyse what breaks if a symbol is renamed |
| `diff_impact_tool` | Analyse blast radius for a file's exported symbols |
| `find_unused_symbols_tool` | Find private functions never called |
| `find_dead_imports_tool` | Find unresolved imports |
| `get_dependency_graph_tool` | File-level dependency graph |
| `find_import_cycles_tool` | Find import cycles |
| `memory_search_tool` | Full-text search over memory entries |
| `memory_prune_tool` | Delete stale memory entries (dry-run by default) |
| `reindex_file_tool` | Re-index a single file after editing |

Each query tool accepts an optional `project` parameter to target a specific opened project (defaults to the most recently opened one).

### Integration with OpenCode

Add to your OpenCode MCP configuration:

```json
{
  "mcpServers": {
    "memos": {
      "command": [
        "memos",
        "serve-mcp"
      ]
    }
  }
}
```

Then use `open_project` within OpenCode to select your project.

### Integration with Claude Desktop

Configure in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "memos": {
      "command": "memos",
      "args": ["serve-mcp"]
    }
  }
}

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
