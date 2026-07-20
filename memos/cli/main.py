import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from memos.core.db import (
    get_connection,
    run_migrations,
    insert_call_edge,
    insert_file,
    insert_import,
    insert_project,
    insert_symbol,
    delete_file,
    get_file_by_path,
    get_project,
    resolve_call_edges,
)
from memos.core.models import Project, File, Symbol, CallEdge, Import
from memos.indexer.diff import compute_file_hash, should_reindex
from memos.indexer.go import GoIndexer
from memos.indexer.typescript import TypeScriptIndexer
from memos.query.core import find_calls, find_symbol, get_module

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
        name=os.path.basename(root_path),
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    return insert_project(conn, project)


def get_project_by_root(conn, root_path: str):
    cur = conn.execute(
        "SELECT * FROM projects WHERE root_path = ?", (root_path,)
    )
    row = cur.fetchone()
    if row is None:
        return None
    return Project.model_validate(dict(row))


def find_files(root: str) -> list[tuple[str, str]]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in EXTENSION_INDEXERS:
                full = os.path.join(dirpath, fn)
                rel = os.path.relpath(full, root)
                files.append((full, rel))
    return sorted(files)


def index_file(conn, project, full_path, rel_path, indexer, full):
    current_hash = compute_file_hash(full_path)
    existing = get_file_by_path(conn, project.id, rel_path)

    if not should_reindex(existing, current_hash, full):
        return False

    if existing is not None:
        delete_file(conn, existing.id)

    with open(full_path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()

    parse_result = indexer.parse(source, rel_path)

    file = File(
        project_id=project.id,
        path=rel_path,
        language=indexer.language(),
        content_hash=current_hash,
        mtime=os.path.getmtime(full_path),
    )
    file = insert_file(conn, file)

    name_to_id = {}
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

        if ps.parent_name:
            parent_id = name_to_id.get(ps.parent_name)
            if parent_id:
                conn.execute(
                    "UPDATE symbols SET parent_symbol_id = ? WHERE id = ?",
                    (parent_id, sym.id),
                )

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
    root = os.path.abspath(args.path)

    memos_dir = Path(root) / ".memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memos_dir / "memory.db")

    conn = get_connection(db_path)
    run_migrations(conn)

    project = get_or_create_project(conn, root)
    files = find_files(root)

    indexed = 0
    for full_path, rel_path in files:
        ext = os.path.splitext(full_path)[1].lower()
        indexer = EXTENSION_INDEXERS.get(ext)
        if indexer is None:
            continue
        try:
            if index_file(conn, project, full_path, rel_path, indexer, args.full):
                indexed += 1
        except Exception as e:
            print(f"  error: {rel_path}: {e}", file=sys.stderr)

    if args.full:
        conn.execute(
            "UPDATE files SET mtime = ? WHERE project_id = ?",
            (datetime.now(timezone.utc).timestamp(), project.id),
        )

    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) FROM call_edges ce "
        "JOIN symbols s ON s.id = ce.caller_symbol_id "
        "JOIN files f ON f.id = s.file_id "
        "WHERE f.project_id = ?", (project.id,)
    ).fetchone()[0]
    resolved = resolve_call_edges(conn, project.id)
    conn.commit()
    conn.close()
    print(f"Indexed {indexed} of {len(files)} files")
    if total:
        print(f"Resolved {resolved} of {total} call edges")


def _open_db(args):
    root = os.path.abspath(args.path)
    db_path = str(Path(root) / ".memos" / "memory.db")
    if not os.path.exists(db_path):
        print("error: no .memos/memory.db found — run 'memos index' first", file=sys.stderr)
        sys.exit(1)
    conn = get_connection(db_path)
    run_migrations(conn)
    project = get_project_by_root(conn, root)
    if project is None:
        print(f"error: no project found for {root}", file=sys.stderr)
        sys.exit(1)
    return conn, project


def cmd_query_symbol(args):
    conn, project = _open_db(args)
    results = find_symbol(conn, args.name, kind=args.kind)
    print(json.dumps(results, indent=2, default=str))
    conn.close()


def cmd_query_calls(args):
    conn, project = _open_db(args)
    results = find_calls(conn, args.name, direction=args.direction)
    print(json.dumps(results, indent=2, default=str))
    conn.close()


def cmd_query_module(args):
    conn, project = _open_db(args)
    results = get_module(conn, args.module_path, project.id)
    print(json.dumps(results, indent=2, default=str))
    conn.close()


def main():
    parser = argparse.ArgumentParser(prog="memos")
    sub = parser.add_subparsers(dest="command", required=True)

    p_index = sub.add_parser("index", help="Index project files")
    p_index.add_argument("--path", default=".", help="Project root path")
    p_index.add_argument("--full", action="store_true", help="Force full reindex")
    p_index.set_defaults(func=cmd_index)

    p_query = sub.add_parser("query", help="Query indexed data")
    qsub = p_query.add_subparsers(dest="query_command", required=True)

    p_sym = qsub.add_parser("symbol", help="Find symbols by name")
    p_sym.add_argument("name", help="Symbol name to search")
    p_sym.add_argument("--kind", help="Filter by symbol kind (function, class, const, etc.)")
    p_sym.add_argument("--path", default=".", help="Project root path")
    p_sym.set_defaults(func=cmd_query_symbol)

    p_calls = qsub.add_parser("calls", help="Find callers or callees of a symbol")
    p_calls.add_argument("name", help="Symbol name")
    p_calls.add_argument("--direction", default="callers", choices=["callers", "callees"],
                         help="Direction: callers (who calls this) or callees (what this calls)")
    p_calls.add_argument("--path", default=".", help="Project root path")
    p_calls.set_defaults(func=cmd_query_calls)

    p_mod = qsub.add_parser("module", help="Show everything for a file (symbols, calls, imports)")
    p_mod.add_argument("module_path", metavar="path", help="Relative file path")
    p_mod.add_argument("--path", default=".", help="Project root path")
    p_mod.set_defaults(func=cmd_query_module)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
