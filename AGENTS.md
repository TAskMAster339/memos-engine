# AGENTS.md

> Этот репозиторий проиндексирован `memos` — используй MCP-инструменты
> memos для навигации по коду. Это быстрее grep/cat и точнее.

## Code navigation policy (memos)

Этот проект проиндексирован `memos` — структурным индексом кода (symbols,
call edges, imports) с episodic memory. Инструмент доступен через MCP-тулы.
**Прежде чем читать файл целиком или делать grep по коду — используй memos.**
Это быстрее, точнее и не тратит контекст на нерелевантные строки.

### Обязательный порядок действий

1. **В начале сессии**, если ещё не открыт проект — вызови `open_project`
   с абсолютным путём к корню репозитория. Это одноразовое действие на
   сессию, если проект уже открыт — не вызывай повторно.

2. **Чтобы найти определение функции/класса/переменной** — используй
   `find_symbol_tool(name, kind=None, file_path=None)`.
   Не используй `grep`/`cat` для этого — memos даёт точный результат
   (файл, строки, сигнатура, exported) без ложных совпадений по имени
   в комментариях/строках.

3. **Чтобы понять, кто вызывает функцию или что вызывает она** — используй
   `find_calls_tool(symbol_name, direction="callers"|"callees")`.
   Это заменяет ручной grep по имени функции во всём репозитории.

4. **Перед тем как редактировать функцию** — вызови `get_context_tool(symbol_id)`.
   Он возвращает символ + всех callers + callees + episodic memory заметки +
   кэшированный LLM-summary (если есть). **Это заменяет повторное чтение
   всего файла и всех зависимых файлов** — не открывай их вручную, если
   `get_context_tool` уже дал нужную картину.

5. **Чтобы посмотреть всё содержимое файла структурно** (какие символы,
   вызовы, импорты) — используй `get_module_tool(path)` вместо чтения
   файла целиком, если тебе не нужен именно raw-текст (форматирование,
   комментарии, точный синтаксис для правки).

6. **Для поиска по смыслу, а не по точному имени** ("где у нас логика
   авторизации", "функция, которая парсит даты") — используй
   `semantic_search_tool(query, top_k)`.

7. **После значимого решения, вывода или "гочи"**, которое стоит помнить
   в будущих сессиях (архитектурное решение, причина странного кода,
   TODO с контекстом) — сохрани заметку через `memory_add_note(content,
   scope_type, scope_id, kind)`. Не полагайся только на свой ответ в чате —
   он не переживёт сессию, а memory_entries переживают.

8. **Перед началом работы с заметками** — вызови `get_memories(scope_type,
   scope_id)`, чтобы узнать, что уже известно про этот файл/символ/проект
   из прошлых сессий, прежде чем исследовать заново.

### Когда grep/cat/read_file всё-таки уместны

- Файл ещё не проиндексирован (новый, не .ts/.tsx/.go — расширения см. ниже)
  или недавно создан и явно устарел в индексе
- Нужен именно raw-текст: точное форматирование, конкретные комментарии,
  импорты в исходном виде для правки строки
- `find_symbol_tool`/`semantic_search_tool` не нашли ничего релевантного —
  тогда grep как fallback, но перепроверь опечатки в имени символа сначала

### Что НЕ делать

- Не грепай по имени функции, чтобы найти её вызовы — используй
  `find_calls_tool`. Grep даёт ложные совпадения (комментарии, строки,
  похожие имена в других scope) и не различает caller/callee направление.
- Не читай весь файл, чтобы понять один символ — `get_context_tool` уже
  дал тебе минимально достаточный контекст.
- Не забывай `open_project`, если сессия началась с чистого MCP-сервера —
  без этого все остальные тулы вернут ошибку "no project open".
- Не дублируй информацию, которая уже есть в `get_memories` — сначала
  проверь память, потом исследуй заново.

### Available tools cheat sheet

| Tool | Когда использовать |
|------|---------------------|
| `open_project(path)` | В начале сессии, один раз на проект |
| `find_symbol_tool(name, kind?, file_path?)` | Найти определение символа по имени |
| `find_calls_tool(symbol_name, direction)` | Callers или callees символа |
| `get_module_tool(path)` | Всё содержимое файла структурно |
| `get_context_tool(symbol_id)` | Полный контекст перед правкой функции |
| `rename_impact_tool(symbol_id)` | Анализ последствий переименования символа |
| `diff_impact_tool(path)` | Анализ blast radius exported-символов файла |
| `diff_range_impact_tool(since)` | Агрегированный impact-отчёт для PR (git diff) |
| `semantic_search_tool(query, top_k?)` | Поиск по смыслу, не по точному имени |
| `list_files_tool(path_filter?)` | Список индексированных файлов |
| `list_symbols_tool(file_path?, kind?)` | Список индексированных символов |
| `list_projects_tool()` | Инфо и статистика по текущему проекту |
| `memory_add_note(content, scope_type, scope_id?, kind?)` | Сохранить заметку/решение |
| `get_memories(scope_type?, scope_id?)` | Прочитать заметки из прошлых сессий |
| `find_unused_symbols_tool()` | Найти неиспользуемые private функции |
| `find_dead_imports_tool()` | Найти неразрешившиеся импорты |
| `get_dependency_graph_tool()` | Граф зависимостей между файлами |
| `find_import_cycles_tool()` | Найти циклы в импортах |
| `memory_search_tool(query, top_k?)` | Полнотекстовый поиск по memory entries |
| `memory_prune_tool(older_than_days?, kind?, apply?)` | Удаление устаревших записей (dry-run по умолчанию) |
| `reindex_file_tool(path)` | Переиндексировать один файл после правки |

Индексируются файлы с расширениями `.ts`, `.tsx`, `.go`, `.py`, `.js`, `.jsx`. Индекс лежит в
`.memos/memory.db` в корне проекта и обновляется через `memos index --path .`
(инкрементально, по content hash — быстро на повторных запусках). Для
переиндексации одного файла после правки используй `reindex_file_tool(path)`
— это быстрее и дешевле полного прохода.

Если каких-то тулов из таблицы нет в твоём MCP-клиенте — значит memos ещё
не переиндексирован для этого проекта или сервер не запущен: запусти
`memos serve-mcp` и настрой подключение согласно README проекта memos.


## Workflow

After completing each task: `ruff check .` + `pytest` green, then commit with
a short descriptive title and all details in the commit body.

## Commands

| Command | What |
|---------|------|
| `memos --version` | show version |
| `memos tools` | list available MCP tools |
| `uv run pytest` | all tests |
| `uv run pytest -v` | verbose |
| `uv run pytest tests/test_crud.py::test_symbol_crud` | single test |
| `uv run memos index --path . --full` | index project at path |
| `uv run memos query symbol <name> [--kind KIND]` | find symbols by name |
| `uv run memos query calls <name> [--direction callers\|callees]` | find callers/callees |
| `uv run memos query module <path>` | show everything for a file |
| `uv run memos serve --path . --port 8000` | start FastAPI server |
| `uv run memos serve-mcp --path .` | start MCP server (stdio) |
| `uv run memos doctor --path .` | Run project diagnostics |
| `uv run memos watch --path .` | Watch files and auto-reindex |
| `uv run pytest tests/test_mcp.py` | MCP server tests |
| `uv run pytest tests/test_llm_summary.py` | LLM summary tests |
| `uv run pytest tests/test_diff_range.py` | Diff-range impact tests |
| `uv run pytest tests/test_impact.py` | Impact analysis tests |
| `uv run pytest tests/test_hygiene.py` | Dead code / hygiene tests |
| `uv run pytest tests/test_dependency_graph.py` | Dependency graph tests |
| `uv run pytest tests/test_memory_hygiene.py` | Memory search & prune tests |
| `uv run pytest tests/test_javascript_indexer.py` | JavaScript indexer tests |
| `uv run pytest tests/test_query_efficiency.py` | Query N+1 regression guard |
| `uv run pytest tests/test_packaging.py` | Packaging smoke tests |
| `uv run pytest tests/test_reindex.py` | Reindex tool tests |
| `uv run pytest tests/test_import_resolver.py` | Import resolver tests |
| `uv run pytest tests/test_import_resolution_efficiency.py` | Import N+1 regression guard |
| `uv run pytest tests/test_cli_index_incremental.py` | Git-aware incremental index tests |
| `uv run pytest tests/test_cli_doctor.py` | Doctor CLI tests |
| `uv run pytest tests/test_watch.py` | Watch (slow) tests |
| `uv run pytest --cov=memos --cov-report=term-missing -m "not slow"` | Tests with coverage report |
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
       0005_symbol_name_file_index.sql
  indexer/
    base.py         # LanguageIndexer ABC + ParsedSymbol/Call/Import/Result dataclasses
    typescript.py   # TypeScriptIndexer (tree-sitter, handles .ts + .tsx + .js + .jsx via language_override)
    go.py           # GoIndexer (tree-sitter, export by name case)
    python.py       # PythonIndexer (tree-sitter, export by _ prefix)  # NEW
    diff.py         # compute_file_hash, should_reindex
  scripts/
    benchmark_index.py  # performance benchmark harness
  query/
    core.py         # find_symbol, find_calls, get_module, find_calls_by_id, semantic_search,
                    # list_files, list_symbols, get_or_generate_summary, get_context,
                    # get_rename_impact, get_diff_impact, find_unused_symbols, find_dead_imports,
                    # get_dependency_graph, find_import_cycles, memory_search, memory_prune
                    # — pure query layer over db
    import_resolver.py  # resolve_ts_import, resolve_python_import — language-specific resolvers
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
    doctor.py       # run_diagnostics(), DiagnosticResult — pure functions for `memos doctor`
    main.py         # argparse: "memos [--version]"
                    #          "memos index [--path .] [--full] [--no-embed] [--profile]"
                    #          "memos query (symbol|calls|module)"
                    #          "memos serve [--path] [--port]"
                    #          "memos serve-mcp [--path]"
                    #          "memos tools"
                    #          "memos doctor"
                    #          "memos watch"
tests/
  conftest.py       # fixture: in-memory sqlite with migrations applied
  test_schema.py    # table existence checks
  test_crud.py      # CRUD + cascade delete
   test_migrations.py# idempotent re-run
    test_javascript_indexer.py  # 11 unit tests on JS parsing
    test_query_efficiency.py    # 1 query N+1 regression guard
    test_packaging.py           # 1 packaging smoke test
   test_typescript_indexer.py  # 18 unit tests on TS parsing
   test_go_indexer.py          # 18 unit tests on Go parsing
   test_python_indexer.py      # 18 unit tests on Python parsing
   test_cli_index.py           # 11 integration tests: index flow (TS + Go + Python)
   test_resolver.py            # 8 unit tests on call-edge resolution (+ Python)
   test_query.py               # 12 unit tests on query/core.py
   test_cli_query.py           # 10 integration tests: query flow (TS + Go + Python)
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
    python_mini/src/        # 3 .py files for integration testing  # NEW
    import_cycle/src/       # 2 .ts files with circular import
    javascript_mini/src/    # 2 .js files for integration testing
```

## Dependencies

- **pydantic** — all CRUD returns models, not raw rows
- **tree-sitter + tree-sitter-typescript + tree-sitter-go + tree-sitter-python** — AST parsing (.ts, .tsx, .go, .py)
- **stdlib sqlite3** — connection mgmt, WAL journal, FK enforcement
- **fastapi + uvicorn** — HTTP API
- **mcp[cli]** — MCP server (FastMCP, stdio transport)
- **fastembed** — ONNX embeddings (all-MiniLM-L6-v2, 384-dim)
- **sqlite-vec** — vector search extension for sqlite
- **rich** — CLI progress bars
- **watchdog** — file system watcher for `memos watch`
- **pytest** (dev)
- **httpx** (dev, for TestClient)
- **pytest-anyio** (dev, for async MCP tests)
- **ruff** (dev)
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
- Python export: determined by `name[0] != '_'` — convention-based, like Go
- Go methods: `method_declaration` nodes are separate from type declarations; receiver type is extracted from `receiver` field
- Go imports: both single `import "x"` and grouped `import ( "x" "y" )` forms are handled via `import_spec` / `import_spec_list`
- Python imports: `import_statement` (single/as) and `import_from_statement` (from/relative) — resolved via `memos/query/import_resolver.py`
- Go imports: **not resolved** — `resolve_imports` in `core/db.py` skips Go files. Reason: no access to `go.mod` module name to strip import prefix; only full import paths (e.g. `github.com/foo/bar`) are stored, which require module-relative heuristics. This is a known limitation.

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
17. ✅ Section 0 (Phase 3): Packaging hardening — CI smoke-test, migration test, Python 3.13 matrix, README fix
18. ✅ Section 1 (Phase 3): JavaScript .js/.jsx support — require()→import, language_override, fixtures, tests
19. ✅ Section 3 (Phase 3): Performance — batch embedding, profile flag, benchmark script, N+1 fix, migration 0005
20. ✅ Section 6: Import resolution — `resolve_imports` in `core/db.py`, language-specific resolvers in `query/import_resolver.py`, integration in CLI/MCP, `find_dead_imports` `broken` flag, efficiency regression guard
21. ✅ Section 7: Rename impact — regex word-boundary filter instead of SQL `LIKE` in `get_rename_impact`, new collision test `Config` vs `ConfigLoader`
22. ✅ Section 8: Git-aware incremental reindex — `--since` and `--dirty` flags for `memos index`, `find_changed_files` function, deleted file cleanup, non-git error handling
23. ✅ Section 9: `memos query diff-range` — aggregated impact report for PRs, `diff_range_impact_tool` MCP tool, `get_diff_range_impact` in query/core.py
