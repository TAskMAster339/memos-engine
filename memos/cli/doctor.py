from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from memos.core.db import MIGRATIONS_DIR, get_connection
from memos.indexer.diff import compute_file_hash

Status = Literal["ok", "warn", "error"]
_WARN_PCT_UNRESOLVED = 50
_WARN_PCT_EMBEDDING = 80


@dataclass
class DiagnosticResult:
    check: str
    status: Status
    detail: str


def _get_schema_version(conn) -> int:
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'",
    )
    if cur.fetchone() is None:
        return 0
    return conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM schema_version",
    ).fetchone()[0]


def run_diagnostics(  # noqa: C901, PLR0912, PLR0915
    conn, project, root_path: str,
) -> list[DiagnosticResult]:
    results: list[DiagnosticResult] = []

    db_path = str(Path(root_path) / ".memos" / "memory.db")
    if not Path(db_path).exists():
        results.append(DiagnosticResult(
            check="Index file exists",
            status="error",
            detail=f".memos/memory.db not found at {root_path}"
            " — run 'memos index --path .'",
        ))
    else:
        results.append(DiagnosticResult(
            check="Index file exists",
            status="ok",
            detail=".memos/memory.db found",
        ))

    try:
        test_conn = get_connection(db_path)
        test_conn.close()
        vec_ok = True
    except Exception as e:
        vec_ok = False
        results.append(DiagnosticResult(
            check="sqlite-vec extension",
            status="error",
            detail=f"sqlite_vec failed to load: {e}",
        ))
    if vec_ok:
        results.append(DiagnosticResult(
            check="sqlite-vec extension",
            status="ok",
            detail="sqlite_vec loaded successfully",
        ))

    latest_migration = sorted(MIGRATIONS_DIR.glob("*.sql"))
    expected = int(latest_migration[-1].stem.split("_")[0]) if latest_migration else 0
    current = _get_schema_version(conn)
    if current < expected:
        results.append(DiagnosticResult(
            check="Schema version",
            status="warn",
            detail=f"schema version {current} < expected {expected}"
            " — run any memos command to auto-migrate",
        ))
    else:
        results.append(DiagnosticResult(
            check="Schema version",
            status="ok",
            detail=f"schema version {current} (latest)",
        ))

    files = conn.execute(
        "SELECT f.id, f.path, f.content_hash FROM files f WHERE f.project_id = ?",
        (project.id,),
    ).fetchall()
    stale = 0
    for f in files:
        full_path = str(Path(root_path) / f["path"])
        if not Path(full_path).exists():
            stale += 1
            continue
        current_hash = compute_file_hash(full_path)
        if current_hash != f["content_hash"]:
            stale += 1
    if stale > 0:
        results.append(DiagnosticResult(
            check="Index freshness",
            status="warn",
            detail=f"{stale} of {len(files)} files stale"
            " — run 'memos index --path .'",
        ))
    else:
        results.append(DiagnosticResult(
            check="Index freshness",
            status="ok",
            detail=f"all {len(files)} files up to date",
        ))

    total_edges = conn.execute(
        "SELECT COUNT(*) FROM call_edges ce "
        "JOIN symbols s ON s.id = ce.caller_symbol_id "
        "JOIN files f ON f.id = s.file_id WHERE f.project_id = ?",
        (project.id,),
    ).fetchone()[0]
    unresolved = conn.execute(
        "SELECT COUNT(*) FROM call_edges ce "
        "JOIN symbols s ON s.id = ce.caller_symbol_id "
        "JOIN files f ON f.id = s.file_id "
        "WHERE f.project_id = ? AND ce.callee_symbol_id IS NULL",
        (project.id,),
    ).fetchone()[0]
    if total_edges > 0:
        pct = unresolved / total_edges * 100
        if pct > _WARN_PCT_UNRESOLVED:
            results.append(DiagnosticResult(
                check="Unresolved call edges",
                status="warn",
                detail=f"{unresolved}/{total_edges} ({pct:.0f}%) unresolved"
                " — run 'memos index' to trigger resolution",
            ))
        else:
            results.append(DiagnosticResult(
                check="Unresolved call edges",
                status="ok",
                detail=f"{unresolved}/{total_edges} ({pct:.0f}%) unresolved",
            ))
    else:
        results.append(DiagnosticResult(
            check="Unresolved call edges",
            status="ok",
            detail="no call edges",
        ))

    sym_count = conn.execute(
        "SELECT COUNT(*) FROM symbols s "
        "JOIN files f ON f.id = s.file_id WHERE f.project_id = ?",
        (project.id,),
    ).fetchone()[0]
    vec_count = conn.execute(
        "SELECT COUNT(*) FROM vec_symbols vs "
        "JOIN symbols s ON s.id = vs.rowid "
        "JOIN files f ON f.id = s.file_id WHERE f.project_id = ?",
        (project.id,),
    ).fetchone()[0]
    if sym_count > 0 and vec_count / sym_count * 100 < _WARN_PCT_EMBEDDING:
        results.append(DiagnosticResult(
            check="Embedding coverage",
            status="warn",
            detail=f"{vec_count}/{sym_count} symbols have embeddings (<80%)"
            " — reindex without --no-embed",
        ))
    else:
        results.append(DiagnosticResult(
            check="Embedding coverage",
            status="ok",
            detail=f"{vec_count}/{sym_count} symbols have embeddings",
        ))

    return results
