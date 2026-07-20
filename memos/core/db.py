import sqlite3
from pathlib import Path
from typing import Optional

from memos.core.models import CallEdge, File, Import, MemoryEntry, Project, Symbol

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def run_migrations(conn: sqlite3.Connection) -> None:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
    )
    if cur.fetchone() is None:
        current = 0
    else:
        current = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        ).fetchone()[0]

    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = int(path.stem.split("_")[0])
        if version > current:
            conn.executescript(path.read_text())
            current = version


# ── Project ──────────────────────────────────────────────────────────────────

def insert_project(conn: sqlite3.Connection, project: Project) -> Project:
    cur = conn.execute(
        "INSERT INTO projects (root_path, name, created_at) VALUES (?, ?, ?)",
        (project.root_path, project.name, project.created_at),
    )
    return project.model_copy(update={"id": cur.lastrowid})


def get_project(conn: sqlite3.Connection, project_id: int) -> Optional[Project]:
    row = conn.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        return None
    return Project.model_validate(dict(row))


# ── File ─────────────────────────────────────────────────────────────────────

def insert_file(conn: sqlite3.Connection, file: File) -> File:
    cur = conn.execute(
        "INSERT INTO files (project_id, path, language, content_hash, mtime, last_indexed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (file.project_id, file.path, file.language, file.content_hash,
         file.mtime, file.last_indexed_at),
    )
    return file.model_copy(update={"id": cur.lastrowid})


def get_file(conn: sqlite3.Connection, file_id: int) -> Optional[File]:
    row = conn.execute(
        "SELECT * FROM files WHERE id = ?", (file_id,)
    ).fetchone()
    if row is None:
        return None
    return File.model_validate(dict(row))


def get_file_by_path(conn: sqlite3.Connection, project_id: int, path: str) -> Optional[File]:
    row = conn.execute(
        "SELECT * FROM files WHERE project_id = ? AND path = ?",
        (project_id, path),
    ).fetchone()
    if row is None:
        return None
    return File.model_validate(dict(row))


def delete_file(conn: sqlite3.Connection, file_id: int) -> None:
    conn.execute("DELETE FROM files WHERE id = ?", (file_id,))


# ── Symbol ───────────────────────────────────────────────────────────────────

def insert_symbol(conn: sqlite3.Connection, symbol: Symbol) -> Symbol:
    cur = conn.execute(
        "INSERT INTO symbols (file_id, parent_symbol_id, name, kind, signature, "
        "start_line, end_line, exported, content_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (symbol.file_id, symbol.parent_symbol_id, symbol.name, symbol.kind,
         symbol.signature, symbol.start_line, symbol.end_line,
         int(symbol.exported), symbol.content_hash),
    )
    return symbol.model_copy(update={"id": cur.lastrowid})


def find_symbols_by_name(conn: sqlite3.Connection, name: str) -> list[Symbol]:
    rows = conn.execute(
        "SELECT * FROM symbols WHERE name = ?", (name,)
    ).fetchall()
    return [Symbol.model_validate(dict(r)) for r in rows]


def get_symbols_for_file(conn: sqlite3.Connection, file_id: int) -> list[Symbol]:
    rows = conn.execute(
        "SELECT * FROM symbols WHERE file_id = ?", (file_id,)
    ).fetchall()
    return [Symbol.model_validate(dict(r)) for r in rows]


# ── CallEdge ─────────────────────────────────────────────────────────────────

def insert_call_edge(conn: sqlite3.Connection, edge: CallEdge) -> CallEdge:
    cur = conn.execute(
        "INSERT INTO call_edges (caller_symbol_id, callee_name, callee_symbol_id, line) "
        "VALUES (?, ?, ?, ?)",
        (edge.caller_symbol_id, edge.callee_name, edge.callee_symbol_id, edge.line),
    )
    return edge.model_copy(update={"id": cur.lastrowid})


def get_calls_for_caller(conn: sqlite3.Connection, caller_symbol_id: int) -> list[CallEdge]:
    rows = conn.execute(
        "SELECT * FROM call_edges WHERE caller_symbol_id = ?", (caller_symbol_id,)
    ).fetchall()
    return [CallEdge.model_validate(dict(r)) for r in rows]


def get_calls_for_callee(conn: sqlite3.Connection, callee_symbol_id: int) -> list[CallEdge]:
    rows = conn.execute(
        "SELECT * FROM call_edges WHERE callee_symbol_id = ?", (callee_symbol_id,)
    ).fetchall()
    return [CallEdge.model_validate(dict(r)) for r in rows]


# ── Import ───────────────────────────────────────────────────────────────────

def insert_import(conn: sqlite3.Connection, imp: Import) -> Import:
    cur = conn.execute(
        "INSERT INTO imports (file_id, imported_path, resolved_file_id) VALUES (?, ?, ?)",
        (imp.file_id, imp.imported_path, imp.resolved_file_id),
    )
    return imp.model_copy(update={"id": cur.lastrowid})


def get_imports_for_file(conn: sqlite3.Connection, file_id: int) -> list[Import]:
    rows = conn.execute(
        "SELECT * FROM imports WHERE file_id = ?", (file_id,)
    ).fetchall()
    return [Import.model_validate(dict(r)) for r in rows]


# ── MemoryEntry ──────────────────────────────────────────────────────────────

def insert_memory_entry(conn: sqlite3.Connection, entry: MemoryEntry) -> MemoryEntry:
    cur = conn.execute(
        "INSERT INTO memory_entries (project_id, scope_type, scope_id, kind, content, "
        "source, source_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (entry.project_id, entry.scope_type, entry.scope_id, entry.kind,
         entry.content, entry.source, entry.source_hash, entry.created_at),
    )
    return entry.model_copy(update={"id": cur.lastrowid})


def get_memory_entries_for_scope(
    conn: sqlite3.Connection, scope_type: str, scope_id: Optional[int] = None
) -> list[MemoryEntry]:
    if scope_id is None:
        rows = conn.execute(
            "SELECT * FROM memory_entries WHERE scope_type = ? AND scope_id IS NULL",
            (scope_type,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM memory_entries WHERE scope_type = ? AND scope_id = ?",
            (scope_type, scope_id),
        ).fetchall()
    return [MemoryEntry.model_validate(dict(r)) for r in rows]
