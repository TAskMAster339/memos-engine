# AGENTS.md

## Workflow

After completing each task: `ruff check .` + `pytest` green, then commit with
a short descriptive title and all details in the commit body.

## Commands

| Command | What |
|---------|------|
| `uv run pytest` | all tests |
| `uv run pytest -v` | verbose |
| `uv run pytest tests/test_crud.py::test_symbol_crud` | single test |
| `uv run memos index --path . --full` | index project at path |
| `uv run memos query symbol <name> [--kind KIND]` | find symbols by name |
| `uv run memos query calls <name> [--direction callers\|callees]` | find callers/callees |
| `uv run memos query module <path>` | show everything for a file |
| `uv run memos serve --path . --port 8000` | start FastAPI server |
| `uv run memos serve-mcp --path .` | start MCP server (stdio) |
| `uv run pytest tests/test_mcp.py` | MCP server tests |
| `uv run pytest tests/test_llm_summary.py` | LLM summary tests |
| `uv run pytest tests/test_impact.py` | Impact analysis tests |
| `uv run pytest tests/test_hygiene.py` | Dead code / hygiene tests |
| `uv run pytest tests/test_dependency_graph.py` | Dependency graph tests |
| `uv run pytest tests/test_memory_hygiene.py` | Memory search & prune tests |
| `uv run pytest tests/test_reindex.py` | Reindex tool tests |
| `curl http://localhost:8000/symbols/{id}/context` | API: get context for symbol |
| `uv add <pkg>` | add dependency |
| `uv add --dev <pkg>` | add dev dependency |
| `uv sync` | reinstall after pyproject.toml changes |

## Layout

```
memos/
  core/
    db.py           # get_connection(WAL+FK), run_migrations, CRUD (all return pydantic models), resolve_call_edges
    models.py       # Project, File, Symbol, CallEdge, Import, MemoryEntry
    schema.sql      # human-readable DDL copy
    migrations/
      0001_init.sql # authoritative DDL
      0002_vec.sql
      0003_prompt_version.sql
      0004_memory_fts.sql
  indexer/
    base.py         # LanguageIndexer ABC + ParsedSymbol/Call/Import/Result dataclasses
    typescript.py   # TypeScriptIndexer (tree-sitter, handles .ts + .tsx)
    go.py           # GoIndexer (tree-sitter, export by name case)
    diff.py         # compute_file_hash, should_reindex
  query/
    core.py         # find_symbol, find_calls, get_module, find_calls_by_id, semantic_search,
                    # list_files, list_symbols, get_or_generate_summary, get_context,
                    # get_rename_impact, get_diff_impact, find_unused_symbols, find_dead_imports,
                    # get_dependency_graph, find_import_cycles, memory_search, memory_prune
                    # — pure query layer over db
  api/
    main.py         # FastAPI app — thin adapter over query/core.py
    schemas.py      # pydantic response models for API
  mcp/
    server.py       # MCP server (FastMCP, stdio) — thin adapter over query/core.py
  search/
    base.py         # EmbeddingModel + VectorStore ABCs
    embeddings.py   # FastEmbedEmbedding (all-MiniLM-L6-v2, 384-dim)
    sqlite_vec_store.py  # SqliteVecStore (sqlite-vec vec0 table)
  cli/
    main.py         # argparse: "memos index [--path .] [--full] [--no-embed]"
                    #          "memos query (symbol|calls|module)"
                    #          "memos serve [--path] [--port]"
                    #          "memos serve-mcp [--path]"
tests/
  conftest.py       # fixture: in-memory sqlite with migrations applied
  test_schema.py    # table existence checks
  test_crud.py      # CRUD + cascade delete
  test_migrations.py# idempotent re-run
  test_typescript_indexer.py  # 18 unit tests on TS parsing
  test_go_indexer.py          # 18 unit tests on Go parsing
  test_cli_index.py           # 8 integration tests: index flow (TS + Go)
  test_resolver.py            # 7 unit tests on call-edge resolution
  test_query.py               # 12 unit tests on query/core.py
  test_cli_query.py           # 7 integration tests: query flow (TS + Go)
  test_api.py                 # 7 integration tests: FastAPI endpoints
  test_mcp.py                 # 15 tests: MCP server tools
  test_semantic_search.py     # 8 tests: VecStore CRUD + semantic_search query
  test_llm_summary.py         # 11 tests: get_or_generate_summary, get_context, source_hash
  test_impact.py              # 8 tests: rename_impact, diff_impact
  test_hygiene.py             # 8 tests: unused symbols, dead imports
  test_dependency_graph.py    # 8 tests: dependency graph + cycle detection
  test_memory_hygiene.py      # 9 tests: memory search + prune
  test_reindex.py             # 3 tests: reindex_file_tool
  test_migrations.py          # 2 tests: idempotent re-run
  fixtures/
    typescript_mini/src/    # 3 .ts files for integration testing
    go_mini/src/            # 3 .go files for integration testing
    import_cycle/src/       # 2 .ts files with circular import
```

## Dependencies

- **pydantic** — all CRUD returns models, not raw rows
- **tree-sitter + tree-sitter-typescript + tree-sitter-go** — AST parsing (.ts, .tsx, .go)
- **stdlib sqlite3** — connection mgmt, WAL journal, FK enforcement
- **fastapi + uvicorn** — HTTP API
- **mcp[cli]** — MCP server (FastMCP, stdio transport)
- **fastembed** — ONNX embeddings (all-MiniLM-L6-v2, 384-dim)
- **sqlite-vec** — vector search extension for sqlite
- **rich** — CLI progress bars
- **pytest** (dev)
- **httpx** (dev, for TestClient)
- **pytest-anyio** (dev, for async MCP tests)
- **hatchling** (build)

## Architecture conventions

- `indexer/typescript.py` produces plain dataclasses (`ParseResult`), not pydantic models — conversion happens in CLI when calling CRUD
- `cli/main.py` is a thin argparse wrapper over `indexer/` + `core/db.py`; no business logic in CLI
- `query/core.py` has no knowledge of CLI, API, or MCP — all three are thin adapters over it
- `mcp/server.py` is a thin FastMCP wrapper over `query/core.py`; same pattern as `api/main.py`
- All MCP tools return JSON strings (parsable by the LLM), never raw text
- `index_file()` in cli/main.py is the unit of change: delete old → parse → insert new
- `memos index` stores DB at `{project_root}/.memos/memory.db`
- call_edges are inserted with `callee_symbol_id=NULL` (first pass); resolution is Task 5
- `callee_symbol_id` and `resolved_file_id` use `ON DELETE SET NULL` — when a callee symbol is deleted (e.g. during reindex), the FK is automatically nulled, then re-resolved in the second pass
- `export` keyword detection (TS): `export_statement` wraps declarations; the walker passes `exported=True` to children
- Go export: determined by `name[0].isupper()` — no `export_statement`
- Go methods: `method_declaration` nodes are separate from type declarations; receiver type is extracted from `receiver` field
- Go imports: both single `import "x"` and grouped `import ( "x" "y" )` forms are handled via `import_spec` / `import_spec_list`

## What does not exist yet

- Type checking, codegen — none configured

## Execution order (from spec §6)

1. ✅ `core/db.py` + `models.py` + `schema.sql` + migrations + tests
2. ✅ `indexer/base.py` + `indexer/typescript.py` + CLI `index`
3. ✅ `indexer/go.py`
4. ✅ `query/core.py` (find_symbol, find_calls, get_module) + CLI `query`
5. ✅ Call-edge resolution (second pass) + cross-file tests
6. ✅ FastAPI wrapper
7. ✅ Semantic search (sqlite-vec + sentence-transformers)
8. ✅ MCP server
9. ✅ `memory_entries` write-path via `memory_add_note`
10. ✅ LLM enrichment: `get_or_generate_summary()` with content_hash check, `get_context()` composite function
11. ✅ Section 0: Technical debt (dedup, batch resolve, SAVEPOINT, threading.Lock)
12. ✅ Section 1: Impact analysis (rename_impact, diff_impact, MCP, API, tests)
13. ✅ Section 2: Dead code / hygiene (unused symbols, dead imports, MCP, API, tests)
14. ✅ Section 3: Dependency graph (graph + cycle detection, MCP, API, tests)
15. ✅ Section 4: Memory search & hygiene (FTS5 search, prune, MCP, API, tests)
16. ✅ Section 5: Reindex file tool (per-file reindex via MCP, tests)
