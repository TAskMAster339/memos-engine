import argparse
import json
import os
import sys
from datetime import UTC, datetime
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
    run_migrations,
)
from memos.core.models import CallEdge, File, Import, Project, Symbol
from memos.indexer.diff import compute_file_hash, should_reindex
from memos.indexer.go import GoIndexer
from memos.indexer.typescript import TypeScriptIndexer
from memos.query.core import find_calls, find_symbol, get_module
from memos.search.sqlite_vec_store import SqliteVecStore

EXTENSION_INDEXERS = {
    ".ts": TypeScriptIndexer(tsx=False),
    ".tsx": TypeScriptIndexer(tsx=True),
    ".go": GoIndexer(),
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


def index_file(conn, project, full_path, rel_path, indexer, full, *, embed=True):  # noqa: PLR0913, C901
    current_hash = compute_file_hash(full_path)
    existing = get_file_by_path(conn, project.id, rel_path)

    if not should_reindex(existing, current_hash, full=full):
        return False

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

    if embed and embed_ids:
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


def cmd_index(args):
    root = str(Path(args.path).resolve())

    memos_dir = Path(root) / ".memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memos_dir / "memory.db")

    conn = get_connection(db_path)
    run_migrations(conn)

    project = get_or_create_project(conn, root)
    files = find_files(root)

    console = Console()
    indexed = 0
    errors = 0
    embed_label = "[bright_black]no-embed[/]" if args.no_embed else ""

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
            f"[cyan]Indexing[/] {embed_label}",
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
                    embed=not args.no_embed,
                ):
                    indexed += 1
                    progress.update(task, info=f"[green]{rel_path}")
                else:
                    progress.update(task, info=f"[dim]{rel_path} unchanged")
            except Exception as e:
                errors += 1
                progress.update(task, info=f"[red]{rel_path} error: {e}")
            progress.update(task, advance=1)

    if args.full:
        conn.execute(
            "UPDATE files SET mtime = ? WHERE project_id = ?",
            (datetime.now(UTC).timestamp(), project.id),
        )

    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) FROM call_edges ce "
        "JOIN symbols s ON s.id = ce.caller_symbol_id "
        "JOIN files f ON f.id = s.file_id "
        "WHERE f.project_id = ?",
        (project.id,),
    ).fetchone()[0]
    resolved = resolve_call_edges(conn, project.id)
    conn.commit()
    conn.close()

    summary = f"Indexed [green]{indexed}[/] of {len(files)} files"
    if errors:
        summary += f", [red]{errors} error(s)[/]"
    if total:
        summary += f" | resolved [cyan]{resolved}[/] of {total} call edges"
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


def main():
    parser = argparse.ArgumentParser(prog="memos")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index project files")
    p_index.add_argument("--path", default=".", help="Project root path")
    p_index.add_argument("--full", action="store_true", help="Force full reindex")
    p_index.add_argument(
        "--no-embed",
        action="store_true",
        help="Skip embedding generation",
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

    p_serve = sub.add_parser("serve", help="Start the HTTP API server")
    p_serve.add_argument("--path", default=".", help="Project root path")
    p_serve.add_argument("--host", default="0.0.0.0", help="Bind host")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port")
    p_serve.set_defaults(func=cmd_serve)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
