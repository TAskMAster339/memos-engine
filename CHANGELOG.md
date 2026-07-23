# Changelog

## 0.4.0 — 2026-07-23

### Import resolution (core)

- Import resolution (`resolve_imports`): resolves `imports.resolved_file_id` for TS/JS/Python
- Language-specific resolvers extracted to `memos/query/import_resolver.py`
- Python absolute intra-package imports resolved (e.g. `memos.core.db` → file)
- TS/JS absolute imports resolved via `tsconfig.json`/`jsconfig.json` — `baseUrl` and `paths` aliases with `*` wildcard support
- Go in-module imports resolved via `go.mod` module prefix
- `find_dead_imports` now distinguishes `broken` relative imports vs truly external packages
- Integration: `resolve_imports` called from `memos index`, MCP `open_project`, MCP `reindex_file_tool`, and `memos watch`

### Git-aware incremental indexing

- `memos index --since <ref>` — only reindex files changed since a git ref
- `memos index --dirty` — reindex uncommitted changes only
- Deleted files cleaned up automatically from the index

### Impact analysis & diagnostics

- Rename impact: word-boundary regex (`\b`) instead of SQL `LIKE` — no false positives (e.g. `Config` ≠ `ConfigLoader`)
- `memos query diff-range --since <ref>` — aggregated PR impact report per file
- MCP `diff_range_impact_tool(since, project)` — same report via MCP
- `memos doctor` — index freshness, schema, embeddings, unresolved edges diagnostics

### Performance

- Batch embedding: single model, chunked by 256 with rich Progress bar
- `--profile` flag on `memos index` prints phase timings (parse/embed/resolve)
- `scripts/benchmark_index.py` — measures parse/embed/resolve/cold-warm query latency
- Migration 0005: composite index `symbols(name, file_id)` for faster resolve
- Fixed N+1 in `resolve_call_edges` (batch SELECT vs per-edge loop)
- Query-efficiency regression guard (N+1 guard test)

### Language support

- JavaScript (.js/.jsx) support: `require()` → import, `module.exports` ignored

### Tooling & DX

- MCP: `_tracked` decorator counts per-session tool usage via `usage_stats_tool`
- File watching: `memos watch` auto-reindexes on file changes (watchdog, 500ms debounce)

### Packaging

- CI smoke-test: build wheel → install in isolated venv → end-to-end
- Migration presence test (guarantees ≥5 migrations)
- Python 3.12 + 3.13 CI matrix
- Release workflow: tag verification, automated PyPI publish, GitHub Release with changelog

## 0.3.0 — 2026-07-22

- JavaScript (.js/.jsx) support: `require()` → import (not call), `module.exports` ignored
- Packaging hardening: CI smoke-test, migration presence test, Python 3.12+3.13 matrix
- Performance: batch embedding (single model, chunked by 256, rich Progress bar)
- Benchmarks: `--profile` flag, `scripts/benchmark_index.py`, query-efficiency regression test
- Migration 0005: composite index `symbols(name, file_id)` for faster resolve
- Fixed N+1 in `resolve_call_edges` (batch SELECT vs per-edge loop)
- Adoption tooling: `memos doctor`, `memos watch`, `usage_stats_tool`
- Diagnostics: `memos doctor` checks index freshness, schema, embeddings, unresolved edges
- MCP: `_tracked` decorator counts per-session tool usage via `usage_stats_tool`
- File watching: `memos watch` auto-reindexes on file changes (watchdog, 500ms debounce)

## 0.2.0 — 2026-07-21

- Python language support (indexer, tests, fixtures)
- Self-indexed: memos-engine uses memos for its own development
- PyPI package `memos-engine` with MIT license
- CI: GitHub Actions release workflow (tag → build → publish)
- GitHub Release automation with changelog categorization

## 0.1.0 — 2026-07-21

- Initial release
- TypeScript/Go structural index via tree-sitter
- MCP server with 20 tools
- FastAPI with 15 endpoints
- Semantic search (fastembed + sqlite-vec)
- Episodic memory (FTS5)
- Impact analysis, dead code, dependency graph, memory hygiene
