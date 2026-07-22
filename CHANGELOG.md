# Changelog

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
