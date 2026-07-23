import argparse
import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import uvicorn
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from memos.cli.doctor import run_diagnostics
from memos.core.db import (
    delete_file,
    get_connection,
    get_file_by_path,
    get_project_by_root,
    insert_call_edge,
    insert_file,
    insert_import,
    insert_project,
    insert_symbol,
    remove_vec_for_file,
    resolve_call_edges,
    resolve_imports,
    run_migrations,
)
from memos.core.models import CallEdge, File, Import, Project, Symbol
from memos.indexer.diff import compute_file_hash, should_reindex
from memos.indexer.go import GoIndexer
from memos.indexer.python import PythonIndexer
from memos.indexer.typescript import TypeScriptIndexer
from memos.mcp.server import mcp
from memos.query.core import (
    add_memory_entry,
    find_calls,
    find_symbol,
    get_memory_entries,
    get_module,
)
from memos.search.sqlite_vec_store import SqliteVecStore

EXTENSION_INDEXERS = {
    ".ts": TypeScriptIndexer(tsx=False),
    ".tsx": TypeScriptIndexer(tsx=True),
    ".js": TypeScriptIndexer(tsx=False, language_override="javascript"),
    ".jsx": TypeScriptIndexer(tsx=True, language_override="jsx"),
    ".go": GoIndexer(),
    ".py": PythonIndexer(),
}

SKIP_DIRS = {".git", ".memos", "node_modules", "__pycache__", ".venv", "target"}


def get_or_create_project(conn, root_path: str) -> Project:
    existing = get_project_by_root(conn, root_path)
    if existing is not None:
        return existing
    project = Project(
        root_path=root_path,
        name=Path(root_path).name,
        created_at=datetime.now(UTC).isoformat(),
    )
    return insert_project(conn, project)


def find_files(root: str) -> list[tuple[str, str]]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = Path(fn).suffix.lower()
            if ext in EXTENSION_INDEXERS:
                full = str(Path(dirpath) / fn)
                rel = os.path.relpath(full, root)
                files.append((full, rel))
    return sorted(files)


def index_file(  # noqa: PLR0913, PLR0912, PLR0915, C901
    conn,
    project,
    full_path,
    rel_path,
    indexer,
    full,
    *,
    embed=True,
    embed_tasks=None,
):
    current_hash = compute_file_hash(full_path)
    existing = get_file_by_path(conn, project.id, rel_path)

    if not should_reindex(existing, current_hash, full=full):
        return False

    conn.execute("SAVEPOINT index_file")
    try:
        if existing is not None:
            remove_vec_for_file(conn, existing.id)
            delete_file(conn, existing.id)

        with Path(full_path).open(encoding="utf-8", errors="replace") as f:
            source = f.read()

        parse_result = indexer.parse(source, rel_path)

        file = File(
            project_id=project.id,
            path=rel_path,
            language=indexer.language(),
            content_hash=current_hash,
            mtime=Path(full_path).stat().st_mtime,
            last_indexed_at=datetime.now(UTC).isoformat(),
        )
        file = insert_file(conn, file)

        name_to_id = {}
        embed_ids: list[int] = []
        embed_texts: list[str] = []
        for ps in parse_result.symbols:
            sym = Symbol(
                file_id=file.id,
                name=ps.name,
                kind=ps.kind,
                signature=ps.signature,
                start_line=ps.start_line,
                end_line=ps.end_line,
                exported=ps.exported,
                content_hash=ps.content_hash,
            )
            sym = insert_symbol(conn, sym)
            name_to_id[ps.name] = sym.id

            if embed:
                embed_ids.append(sym.id)
                text = f"{ps.name} {ps.kind}"
                if ps.signature:
                    text += f" {ps.signature}"
                embed_texts.append(text)

            if ps.parent_name:
                parent_id = name_to_id.get(ps.parent_name)
                if parent_id:
                    conn.execute(
                        "UPDATE symbols SET parent_symbol_id = ? WHERE id = ?",
                        (parent_id, sym.id),
                    )

        if embed_ids:
            if embed_tasks is not None:
                embed_tasks.append((list(embed_ids), list(embed_texts)))
            else:
                from memos.search.embeddings import FastEmbedEmbedding  # noqa: PLC0415

                embedder = FastEmbedEmbedding()
                vecs = embedder.embed(embed_texts)
                store = SqliteVecStore(conn)
                store.add_batch(embed_ids, vecs)

        for pc in parse_result.calls:
            caller_id = name_to_id.get(pc.caller_name) if pc.caller_name else None
            if caller_id is None:
                continue
            edge = CallEdge(
                caller_symbol_id=caller_id,
                callee_name=pc.callee_name,
                line=pc.line,
            )
            insert_call_edge(conn, edge)

        for pi in parse_result.imports:
            imp = Import(
                file_id=file.id,
                imported_path=pi.imported_path,
            )
            insert_import(conn, imp)

        return True
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT index_file")
        raise
    finally:
        conn.execute("RELEASE SAVEPOINT index_file")


def cmd_index(args):  # noqa: C901, PLR0912, PLR0915
    profile = args.profile
    t_start = time.perf_counter() if profile else None

    root = str(Path(args.path).resolve())

    memos_dir = Path(root) / ".memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memos_dir / "memory.db")

    conn = get_connection(db_path)
    run_migrations(conn)

    project = get_or_create_project(conn, root)
    files = find_files(root)

    indexed = 0
    errors = 0
    do_embed = not args.no_embed
    embed_tasks: list[tuple[list[int], list[str]]] = [] if do_embed else None

    console = Console()

    progress = Progress(
        SpinnerColumn(spinner_name="dots"),
        TextColumn("[bold]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TextColumn("[bright_black]{task.fields[info]}"),
        console=console,
        transient=False,
    )

    with progress:
        task = progress.add_task(
            "[cyan]Indexing[/]",
            total=len(files),
            info="",
        )

        for full_path, rel_path in files:
            ext = Path(full_path).suffix.lower()
            indexer = EXTENSION_INDEXERS.get(ext)
            if indexer is None:
                progress.update(task, advance=1, info=f"[dim]skipped {rel_path}")
                continue
            try:
                progress.update(task, info=f"[yellow]{rel_path}")
                if index_file(
                    conn,
                    project,
                    full_path,
                    rel_path,
                    indexer,
                    args.full,
                    embed=do_embed,
                    embed_tasks=embed_tasks,
                ):
                    indexed += 1
                    progress.update(task, info=f"[green]{rel_path}")
                else:
                    progress.update(task, info=f"[dim]{rel_path} unchanged")
            except Exception as e:
                errors += 1
                progress.update(task, info=f"[red]{rel_path} error: {e}")
            progress.update(task, advance=1)

    if profile:
        t_after_parse = time.perf_counter()

    if args.full:
        conn.execute(
            "UPDATE files SET mtime = ? WHERE project_id = ?",
            (datetime.now(UTC).timestamp(), project.id),
        )

    conn.commit()

    # Batch embedding: one model instance, chunked with progress
    if embed_tasks and do_embed:
        from memos.search.embeddings import FastEmbedEmbedding  # noqa: PLC0415
        from memos.search.sqlite_vec_store import SqliteVecStore  # noqa: PLC0415

        all_ids: list[int] = []
        all_texts: list[str] = []
        for eids, etxts in embed_tasks:
            all_ids.extend(eids)
            all_texts.extend(etxts)

        chunk = 256
        embedder = FastEmbedEmbedding()
        store = SqliteVecStore(conn)
        embed_progress = Progress(
            TextColumn("[bold]Embedding[/]"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=False,
        )
        with embed_progress:
            etask = embed_progress.add_task(
                "[cyan]Embedding[/]",
                total=len(all_ids),
            )
            for i in range(0, len(all_ids), chunk):
                chunk_ids = all_ids[i : i + chunk]
                chunk_texts = all_texts[i : i + chunk]
                vecs = embedder.embed(chunk_texts)
                store.add_batch(chunk_ids, vecs)
                embed_progress.update(etask, advance=len(chunk_ids))

    if profile:
        t_after_embed = time.perf_counter()

    total = conn.execute(
        "SELECT COUNT(*) FROM call_edges ce "
        "JOIN symbols s ON s.id = ce.caller_symbol_id "
        "JOIN files f ON f.id = s.file_id "
        "WHERE f.project_id = ?",
        (project.id,),
    ).fetchone()[0]
    resolved = resolve_call_edges(conn, project.id)
    imports_resolved = resolve_imports(conn, project.id)
    conn.commit()
    conn.close()

    if profile:
        t_end = time.perf_counter()
        db_size = Path(db_path).stat().st_size
        parse_insert = t_after_parse - t_start
        embed_t = t_after_embed - t_after_parse
        resolve_t = t_end - t_after_embed
        print(
            f"PROFILE parse_insert={parse_insert:.2f}s"
            f" embed={embed_t:.2f}s"
            f" resolve={resolve_t:.2f}s"
            f" total={t_end - t_start:.2f}s"
            f" db_size={db_size}",
            file=sys.stderr,
        )

    summary = f"Indexed [green]{indexed}[/] of {len(files)} files"
    if errors:
        summary += f", [red]{errors} error(s)[/]"
    if total:
        summary += f" | resolved [cyan]{resolved}[/] of {total} call edges"
    if imports_resolved:
        summary += f" | imports [cyan]{imports_resolved}[/] resolved"
    console.print(summary)


def _open_db(args):
    root = str(Path(args.path).resolve())
    db_path = str(Path(root) / ".memos" / "memory.db")
    if not Path(db_path).exists():
        print(
            "error: no .memos/memory.db found — run 'memos index' first",
            file=sys.stderr,
        )
        sys.exit(1)
    conn = get_connection(db_path)
    run_migrations(conn)
    project = get_project_by_root(conn, root)
    if project is None:
        print(f"error: no project found for {root}", file=sys.stderr)
        sys.exit(1)
    return conn, project


def cmd_query_symbol(args):
    conn, _project = _open_db(args)
    results = find_symbol(conn, args.name, kind=args.kind)
    print(json.dumps(results, indent=2, default=str))
    conn.close()


def cmd_query_calls(args):
    conn, _project = _open_db(args)
    results = find_calls(conn, args.name, direction=args.direction)
    print(json.dumps(results, indent=2, default=str))
    conn.close()


def cmd_query_module(args):
    conn, project = _open_db(args)
    results = get_module(conn, args.module_path, project.id)
    print(json.dumps(results, indent=2, default=str))
    conn.close()


def cmd_serve(args):
    os.environ["MEMOS_PROJECT_PATH"] = str(Path(args.path).resolve())
    uvicorn.run("memos.api.main:app", host=args.host, port=args.port)


def cmd_serve_mcp(args):
    from memos.mcp.server import mcp  # noqa: PLC0415

    mcp.run(transport="stdio")


def cmd_memory_add(args):
    conn, project = _open_db(args)
    result = add_memory_entry(
        conn,
        project.id,
        args.content,
        scope_type=args.scope_type,
        scope_id=args.scope_id,
        kind=args.kind,
        source=args.source,
    )
    conn.commit()
    conn.close()
    print(json.dumps(result, indent=2, default=str))


def cmd_memory_list(args):
    conn, project = _open_db(args)
    results = get_memory_entries(
        conn,
        project.id,
        scope_type=args.scope_type,
        scope_id=args.scope_id,
    )
    conn.close()
    print(json.dumps(results, indent=2, default=str))


def cmd_doctor(args):
    from rich.table import Table  # noqa: PLC0415

    conn, project = _open_db(args)
    root = str(Path(args.path).resolve())
    results = run_diagnostics(conn, project, root)
    conn.close()

    console = Console()
    table = Table(title="memos doctor")
    table.add_column("Check")
    table.add_column("Status", no_wrap=True)
    table.add_column("Detail")
    icons = {
        "ok": "[green]✅[/]",
        "warn": "[yellow]⚠️[/]",
        "error": "[red]❌[/]",
    }
    for r in results:
        table.add_row(r.check, icons.get(r.status, r.status), r.detail)
    console.print(table)


def cmd_watch(args):  # noqa: C901
    from watchdog.events import FileSystemEventHandler  # noqa: PLC0415
    from watchdog.observers import Observer  # noqa: PLC0415

    root = str(Path(args.path).resolve())
    db_path = str(Path(root) / ".memos" / "memory.db")
    if not Path(db_path).exists():
        print("error: no index found — run 'memos index' first", file=sys.stderr)
        sys.exit(1)

    conn = get_connection(db_path)
    run_migrations(conn)
    project = get_project_by_root(conn, root)
    if project is None:
        print(f"error: no project found for {root}", file=sys.stderr)
        sys.exit(1)

    debounce_sec = 0.5

    console = Console()
    console.print(f"[cyan]Watching[/] {root} for changes...")

    class _Handler(FileSystemEventHandler):
        def __init__(self):
            self.debounce: dict[str, float] = {}

        def on_modified(self, event):
            if event.is_directory:
                return
            rel_path = os.path.relpath(event.src_path, root)
            ext = Path(event.src_path).suffix.lower()
            if ext not in EXTENSION_INDEXERS:
                return

            now = time.time()
            last = self.debounce.get(event.src_path, 0)
            if now - last < debounce_sec:
                return
            self.debounce[event.src_path] = now

            try:
                indexer = EXTENSION_INDEXERS[ext]
                changed = index_file(
                    conn, project, event.src_path, rel_path, indexer,
                    full=False, embed=False,
                )
                if changed:
                    resolve_call_edges(conn, project.id)
                    resolve_imports(conn, project.id)
                    conn.commit()
                    console.print(f"  [green]reindexed[/] {rel_path}")
            except Exception as e:
                console.print(f"  [red]error[/] {rel_path}: {e}")

    handler = _Handler()
    observer = Observer()
    observer.schedule(handler, root, recursive=True)
    observer.start()
    try:
        observer.join()
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    conn.close()


def cmd_tools(args):

    tools = asyncio.run(mcp.list_tools())
    for t in tools:
        print(f"  {t.name}")
        if t.description:
            desc = t.description.strip().split("\n")[0]
            print(f"      {desc}")
    print(f"\nTotal: {len(tools)} tools")


def main():  # noqa: PLR0915
    parser = argparse.ArgumentParser(prog="memos")
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index project files")
    p_index.add_argument("--path", default=".", help="Project root path")
    p_index.add_argument("--full", action="store_true", help="Force full reindex")
    p_index.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding generation",
    )
    p_index.add_argument(
        "--profile",
        action="store_true",
        help="Print phase timing breakdown to stderr",
    )
    p_index.set_defaults(func=cmd_index)

    p_query = sub.add_parser("query", help="Query indexed data")
    qsub = p_query.add_subparsers(dest="query_command", required=True)

    p_sym = qsub.add_parser("symbol", help="Find symbols by name")
    p_sym.add_argument("name", help="Symbol name to search")
    p_sym.add_argument(
        "--kind",
        help="Filter by symbol kind (function, class, const, etc.)",
    )
    p_sym.add_argument("--path", default=".", help="Project root path")
    p_sym.set_defaults(func=cmd_query_symbol)

    p_calls = qsub.add_parser("calls", help="Find callers or callees of a symbol")
    p_calls.add_argument("name", help="Symbol name")
    p_calls.add_argument(
        "--direction",
        default="callers",
        choices=["callers", "callees"],
        help="Direction: callers (who calls this) or callees (what this calls)",
    )
    p_calls.add_argument("--path", default=".", help="Project root path")
    p_calls.set_defaults(func=cmd_query_calls)

    p_mod = qsub.add_parser(
        "module",
        help="Show everything for a file (symbols, calls, imports)",
    )
    p_mod.add_argument("module_path", metavar="path", help="Relative file path")
    p_mod.add_argument("--path", default=".", help="Project root path")
    p_mod.set_defaults(func=cmd_query_module)

    p_memory = sub.add_parser("memory", help="Manage memory entries")
    msub = p_memory.add_subparsers(dest="memory_command", required=True)

    p_mem_add = msub.add_parser("add", help="Add a memory entry")
    p_mem_add.add_argument("content", help="Memory content text")
    p_mem_add.add_argument(
        "--scope-type",
        default="project",
        choices=["project", "file", "symbol"],
        help="Scope type",
    )
    p_mem_add.add_argument("--scope-id", type=int, help="Scope ID (file or symbol id)")
    p_mem_add.add_argument(
        "--kind",
        default="note",
        help="Kind (note, summary, decision)",
    )
    p_mem_add.add_argument("--source", default="agent", help="Source of the memory")
    p_mem_add.add_argument("--path", default=".", help="Project root path")
    p_mem_add.set_defaults(func=cmd_memory_add)

    p_mem_list = msub.add_parser("list", help="List memory entries")
    p_mem_list.add_argument(
        "--scope-type",
        choices=["project", "file", "symbol"],
        help="Filter by scope type",
    )
    p_mem_list.add_argument("--scope-id", type=int, help="Filter by scope ID")
    p_mem_list.add_argument("--path", default=".", help="Project root path")
    p_mem_list.set_defaults(func=cmd_memory_list)

    p_serve = sub.add_parser("serve", help="Start the HTTP API server")
    p_serve.add_argument("--path", default=".", help="Project root path")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind host")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port")
    p_serve.set_defaults(func=cmd_serve)

    p_serve_mcp = sub.add_parser(
        "serve-mcp",
        help=("Start MCP server (stdio). Use open_project tool to select a project."),
    )
    p_serve_mcp.set_defaults(func=cmd_serve_mcp)

    p_tools = sub.add_parser("tools", help="List available MCP tools")
    p_tools.set_defaults(func=cmd_tools)

    p_doctor = sub.add_parser("doctor", help="Run project diagnostics")
    p_doctor.add_argument("--path", default=".", help="Project root path")
    p_doctor.set_defaults(func=cmd_doctor)

    p_watch = sub.add_parser("watch", help="Watch files and auto-reindex on change")
    p_watch.add_argument("--path", default=".", help="Project root path")
    p_watch.set_defaults(func=cmd_watch)

    if "--version" in sys.argv:
        print(f"memos {version('memos-engine')}")
        sys.exit(0)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
