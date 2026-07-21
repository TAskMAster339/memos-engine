from datetime import UTC, datetime

from memos.core.db import (
    insert_call_edge,
    insert_file,
    insert_import,
    insert_project,
    insert_symbol,
)
from memos.core.models import CallEdge, File, Import, Project, Symbol
from memos.query.core import find_dead_imports, find_unused_symbols


def _seed(conn):
    project = Project(
        root_path="/test/proj",
        name="proj",
        created_at=datetime.now(UTC).isoformat(),
    )
    project = insert_project(conn, project)

    file_a = File(
        project_id=project.id,
        path="src/a.ts",
        language="typescript",
        content_hash="aaa",
    )
    file_a = insert_file(conn, file_a)

    file_b = File(
        project_id=project.id,
        path="src/b.ts",
        language="typescript",
        content_hash="bbb",
    )
    file_b = insert_file(conn, file_b)

    file_c = File(
        project_id=project.id,
        path="src/c.go",
        language="go",
        content_hash="ccc",
    )
    file_c = insert_file(conn, file_c)

    used_fn = Symbol(
        file_id=file_a.id,
        name="usedFn",
        kind="function",
        start_line=1,
        end_line=3,
        exported=False,
        content_hash="h1",
    )
    used_fn = insert_symbol(conn, used_fn)

    unused_fn = Symbol(
        file_id=file_a.id,
        name="unusedFn",
        kind="function",
        start_line=5,
        end_line=7,
        exported=False,
        content_hash="h2",
    )
    unused_fn = insert_symbol(conn, unused_fn)

    exported_fn = Symbol(
        file_id=file_a.id,
        name="exportedFn",
        kind="function",
        start_line=9,
        end_line=11,
        exported=True,
        content_hash="h3",
    )
    insert_symbol(conn, exported_fn)

    private_type = Symbol(
        file_id=file_a.id,
        name="privateType",
        kind="interface",
        start_line=13,
        end_line=15,
        exported=False,
        content_hash="h4",
    )
    insert_symbol(conn, private_type)

    caller = Symbol(
        file_id=file_b.id,
        name="caller",
        kind="function",
        start_line=1,
        end_line=5,
        exported=True,
        content_hash="h5",
    )
    caller = insert_symbol(conn, caller)

    edge = CallEdge(
        caller_symbol_id=caller.id,
        callee_name="usedFn",
        callee_symbol_id=used_fn.id,
        line=2,
    )
    insert_call_edge(conn, edge)

    imp_relative = Import(
        file_id=file_a.id,
        imported_path="./utils",
    )
    insert_import(conn, imp_relative)

    imp_npm = Import(
        file_id=file_a.id,
        imported_path="lodash",
    )
    insert_import(conn, imp_npm)

    imp_go_stdlib = Import(
        file_id=file_c.id,
        imported_path="fmt",
    )
    insert_import(conn, imp_go_stdlib)

    conn.commit()
    return project, used_fn, unused_fn


class TestFindUnusedSymbols:
    def test_exported_not_unused(self, conn):
        _seed(conn)
        results = find_unused_symbols(conn, 1)
        names = {r["name"] for r in results}
        assert "exportedFn" not in names

    def test_used_private_not_unused(self, conn):
        _seed(conn)
        results = find_unused_symbols(conn, 1)
        names = {r["name"] for r in results}
        assert "usedFn" not in names

    def test_unused_private_is_unused(self, conn):
        _seed(conn)
        results = find_unused_symbols(conn, 1)
        names = {r["name"] for r in results}
        assert "unusedFn" in names

    def test_types_excluded(self, conn):
        _seed(conn)
        results = find_unused_symbols(conn, 1)
        names = {r["name"] for r in results}
        assert "privateType" not in names


class TestFindDeadImports:
    def test_relative_path_not_external(self, conn):
        _seed(conn)
        results = find_dead_imports(conn, 1)
        for r in results:
            if r["imported_path"] == "./utils":
                assert r["likely_external"] is False

    def test_npm_path_is_external(self, conn):
        _seed(conn)
        results = find_dead_imports(conn, 1)
        for r in results:
            if r["imported_path"] == "lodash":
                assert r["likely_external"] is True

    def test_go_stdlib_is_external(self, conn):
        _seed(conn)
        results = find_dead_imports(conn, 1)
        for r in results:
            if r["imported_path"] == "fmt":
                assert r["likely_external"] is True

    def test_unresolved_import_found(self, conn):
        _seed(conn)
        results = find_dead_imports(conn, 1)
        paths = {r["imported_path"] for r in results}
        assert paths == {"./utils", "lodash", "fmt"}
