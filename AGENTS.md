# AGENTS.md

## Commands

| Command | What |
|---------|------|
| `uv run pytest` | all tests |
| `uv run pytest -v` | verbose |
| `uv run pytest tests/test_crud.py::test_symbol_crud` | single test |
| `uv run memos index --path . --full` | index project at path |
| `uv add <pkg>` | add dependency |
| `uv add --dev <pkg>` | add dev dependency |
| `uv sync` | reinstall after pyproject.toml changes |

## Layout

```
memos/
  core/
    db.py           # get_connection(WAL+FK), run_migrations, CRUD (all return pydantic models)
    models.py       # Project, File, Symbol, CallEdge, Import, MemoryEntry
    schema.sql      # human-readable DDL copy
    migrations/
      0001_init.sql # authoritative DDL
  indexer/
    base.py         # LanguageIndexer ABC + ParsedSymbol/Call/Import/Result dataclasses
    typescript.py   # TypeScriptIndexer (tree-sitter, handles .ts + .tsx)
    diff.py         # compute_file_hash, should_reindex
  cli/
    main.py         # argparse: "memos index [--path .] [--full]"
tests/
  conftest.py       # fixture: in-memory sqlite with migrations applied
  test_schema.py    # table existence checks
  test_crud.py      # CRUD + cascade delete
  test_migrations.py# idempotent re-run
  test_typescript_indexer.py  # 18 unit tests on TS parsing
  test_cli_index.py           # 4 integration tests: index flow
  fixtures/
    typescript_mini/src/    # 3 .ts files for integration testing
```

## Dependencies

- **pydantic** — all CRUD returns models, not raw rows
- **tree-sitter + tree-sitter-typescript** — AST parsing (.ts, .tsx)
- **stdlib sqlite3** — connection mgmt, WAL journal, FK enforcement
- **pytest** (dev)
- **hatchling** (build)

## Architecture conventions

- `indexer/typescript.py` produces plain dataclasses (`ParseResult`), not pydantic models — conversion happens in CLI when calling CRUD
- `cli/main.py` is a thin argparse wrapper over `indexer/` + `core/db.py`; no business logic in CLI
- `index_file()` in cli/main.py is the unit of change: delete old → parse → insert new
- `memos index` stores DB at `{project_root}/.memos/memory.db`
- call_edges are inserted with `callee_symbol_id=NULL` (first pass); resolution is Task 5
- `export` keyword detection: `export_statement` wraps declarations; the walker passes `exported=True` to children

## What does not exist yet

- `indexer/go.py` — Iteration 1, Task 3
- `query/core.py` (find_symbol, find_calls, get_module) — Iteration 1, Task 4
- Call-edge second-pass resolution — Task 5
- FastAPI service — Iteration 2
- Semantic search (sqlite-vec + sentence-transformers) — Task 7
- MCP server — Iteration 3
- LLM summary generation — Iteration 4
- CI, linting, type checking, codegen — none configured

## Execution order (from spec §6)

1. ✅ `core/db.py` + `models.py` + `schema.sql` + migrations + tests
2. ✅ `indexer/base.py` + `indexer/typescript.py` + CLI `index`
3. `indexer/go.py`
4. `query/core.py` (find_symbol, find_calls, get_module) + CLI `query`
5. Call-edge resolution (second pass) + cross-file tests
6. FastAPI wrapper
7. Semantic search (sqlite-vec + sentence-transformers)
8. MCP server
9. `memory_entries` write-path via `memory_add_note`
10. LLM enrichment: `get_or_generate_summary()` with content_hash check
