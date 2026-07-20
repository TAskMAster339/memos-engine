# memos — Structural code index for AI agents

`memos` builds a **structural index** (symbols, call edges, imports) of a
TypeScript/TSX codebase using tree-sitter and stores it in SQLite. It is the
first layer of a larger *Memory OS* for AI coding agents — instead of
grep-ing text, agents query **structure** (definitions, callers, callees).

## Quick start

```bash
uv sync                         # install deps
uv run memos index --path .     # index current project
```

Indexes are stored at `{project}/.memos/memory.db`. Re-run to sync changes
(files are skipped if their content hash hasn't changed).

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
