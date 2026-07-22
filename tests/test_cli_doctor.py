from pathlib import Path

from memos.cli.doctor import run_diagnostics
from memos.core.db import (
    insert_call_edge,
    insert_file,
    insert_project,
    insert_symbol,
)
from memos.core.models import CallEdge, File, Project, Symbol


def test_diagnostics_ok(conn):
    project = Project(
        root_path="/tmp/nonexistent",
        name="test",
        created_at="2026-01-01T00:00:00",
    )
    project = insert_project(conn, project)

    results = run_diagnostics(conn, project, "/tmp/nonexistent")
    statuses = {r.check: r.status for r in results}
    assert statuses["Index file exists"] == "error"  # no db file
    assert statuses["Schema version"] == "ok"
    assert statuses["Index freshness"] == "ok"  # no files


def test_diagnostics_stale_files(conn, tmp_path: Path):
    project = Project(
        root_path=str(tmp_path),
        name="test",
        created_at="2026-01-01T00:00:00",
    )
    project = insert_project(conn, project)

    src = tmp_path / "src"
    src.mkdir()
    src_file = src / "a.ts"
    src_file.write_text("export const x = 1;")

    file_row = File(
        project_id=project.id,
        path="src/a.ts",
        language="typescript",
        content_hash="stalehash",
    )
    insert_file(conn, file_row)

    results = run_diagnostics(conn, project, str(tmp_path))
    freshness = next(r for r in results if r.check == "Index freshness")
    assert freshness.status == "warn"
    assert "stale" in freshness.detail.lower()


def test_diagnostics_unresolved_edges(conn):
    project = Project(
        root_path="/tmp/nonexistent",
        name="test",
        created_at="2026-01-01T00:00:00",
    )
    project = insert_project(conn, project)

    file_row = File(
        project_id=project.id,
        path="src/a.ts",
        language="typescript",
        content_hash="h1",
    )
    file_row = insert_file(conn, file_row)

    sym = Symbol(
        file_id=file_row.id,
        name="main",
        kind="function",
        start_line=1,
        end_line=5,
        exported=True,
        content_hash="h1",
    )
    sym = insert_symbol(conn, sym)

    insert_call_edge(conn, CallEdge(
        caller_symbol_id=sym.id,
        callee_name="missing_func",
        line=1,
    ))

    results = run_diagnostics(conn, project, "/tmp/nonexistent")
    unresolved = next(r for r in results if r.check == "Unresolved call edges")
    assert unresolved.status == "warn"
    assert "100%" in unresolved.detail or "1/1" in unresolved.detail


def test_diagnostics_missing_vec(conn):
    project = Project(
        root_path="/tmp/nonexistent",
        name="test",
        created_at="2026-01-01T00:00:00",
    )
    project = insert_project(conn, project)

    file_row = File(
        project_id=project.id,
        path="src/a.ts",
        language="typescript",
        content_hash="h1",
    )
    file_row = insert_file(conn, file_row)

    Symbol(
        file_id=file_row.id,
        name="main",
        kind="function",
        start_line=1,
        end_line=5,
        exported=True,
        content_hash="h1",
    )
    insert_symbol(conn, Symbol(
        file_id=file_row.id,
        name="helper",
        kind="function",
        start_line=10,
        end_line=15,
        exported=False,
        content_hash="h2",
    ))

    conn.commit()

    results = run_diagnostics(conn, project, "/tmp/nonexistent")
    coverage = next(r for r in results if r.check == "Embedding coverage")
    assert coverage.status == "warn"
    assert "0/" in coverage.detail
