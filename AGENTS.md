# AGENTS.md

## Commands

| Command | What |
|---------|------|
| `uv run pytest` | all tests |
| `uv run pytest -v` | verbose |
| `uv run pytest tests/test_crud.py::test_symbol_crud` | single test |
| `uv add <pkg>` | add dependency |
| `uv add --dev <pkg>` | add dev dependency |

## Layout

```
memos/
  core/
    db.py           # get_connection(WAL+FK), run_migrations, CRUD (all return pydantic models)
    models.py       # Project, File, Symbol, CallEdge, Import, MemoryEntry
    schema.sql      # human-readable DDL copy
    migrations/
      0001_init.sql # authoritative DDL
tests/
  conftest.py       # fixture: in-memory sqlite with migrations applied
  test_schema.py    # table existence checks
  test_crud.py      # CRUD + cascade delete
  test_migrations.py# idempotent re-run
```

## Dependencies

- **pydantic** — all CRUD returns models, not raw rows
- **stdlib sqlite3** — connection mgmt, WAL journal, FK enforcement
- **pytest** (dev)

All tables from the architecture spec are in the initial migration: `projects`, `files`, `symbols`, `call_edges`, `imports`, `memory_entries` (episodic memory — laid down in Iteration 1 per the spec).

## Architecture rules (from spec, enforced in code)

- `query/core.py` (not yet created) must NOT know about CLI, API, or MCP — it's the single business-logic layer
- `memory_entries` unifies LLM-summary (`source='llm'`) and agent notes (`source='agent'`) in one table; `source` is required

## What does not exist yet

- `indexer/` (tree-sitter AST parsing) — Iteration 1, tasks 2-3
- `query/core.py` (find_symbol, find_calls, get_module) — Iteration 1, task 4
- `cli/` (argparse/typer) — Iteration 1
- FastAPI service — Iteration 2
- MCP server — Iteration 3
- LLM summary generation — Iteration 4
- CI, linting, type checking, codegen — none configured

## Execution order (from spec §6)

1. ✅ `core/db.py` + `models.py` + `schema.sql` + migrations + tests (this task)
2. `indexer/base.py` + `indexer/typescript.py` + CLI `index` on test repo
3. `indexer/go.py`
4. `query/core.py` (find_symbol, find_calls, get_module) + CLI `query`
5. Call-edge resolution (second pass) + cross-file tests
6. FastAPI wrapper
7. Semantic search (sqlite-vec + sentence-transformers)
8. MCP server
9. `memory_entries` write-path via `memory_add_note`
10. LLM enrichment: `get_or_generate_summary()` with content_hash check
