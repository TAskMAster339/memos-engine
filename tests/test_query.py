from datetime import datetime, timezone

from memos.core.db import (
    get_connection,
    insert_call_edge,
    insert_file,
    insert_import,
    insert_project,
    insert_symbol,
    run_migrations,
)
from memos.core.models import CallEdge, File, Import, Project, Symbol
from memos.query.core import find_calls, find_symbol, get_module


def _seed(conn):
    project = Project(
        root_path="/test/proj",
        name="proj",
        created_at=datetime.now(timezone.utc).isoformat(),
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

    sym_main = Symbol(
        file_id=file_a.id,
        name="main",
        kind="function",
        signature="(): void",
        start_line=1,
        end_line=5,
        exported=True,
        content_hash="h1",
    )
    sym_main = insert_symbol(conn, sym_main)

    sym_greet = Symbol(
        file_id=file_a.id,
        name="greet",
        kind="function",
        signature="(name: string): string",
        start_line=7,
        end_line=9,
        exported=True,
        content_hash="h2",
    )
    sym_greet = insert_symbol(conn, sym_greet)

    sym_helper = Symbol(
        file_id=file_b.id,
        name="helper",
        kind="function",
        signature="(): void",
        start_line=1,
        end_line=3,
        exported=False,
        content_hash="h3",
    )
    sym_helper = insert_symbol(conn, sym_helper)

    sym_config = Symbol(
        file_id=file_b.id,
        name="CONFIG",
        kind="const",
        exported=True,
        content_hash="h4",
        start_line=5,
        end_line=5,
    )
    sym_config = insert_symbol(conn, sym_config)

    edge1 = CallEdge(
        caller_symbol_id=sym_main.id,
        callee_name="greet",
        callee_symbol_id=sym_greet.id,
        line=2,
    )
    insert_call_edge(conn, edge1)

    edge2 = CallEdge(
        caller_symbol_id=sym_main.id,
        callee_name="console.log",
        line=3,
    )
    insert_call_edge(conn, edge2)

    edge3 = CallEdge(
        caller_symbol_id=sym_greet.id,
        callee_name="helper",
        line=8,
    )
    insert_call_edge(conn, edge3)

    imp1 = Import(file_id=file_a.id, imported_path="./b")
    insert_import(conn, imp1)

    imp2 = Import(file_id=file_b.id, imported_path="lodash")
    insert_import(conn, imp2)

    conn.commit()
    return project, file_a, file_b


class TestFindSymbol:
    def test_by_name(self, conn):
        _seed(conn)
        results = find_symbol(conn, "greet")
        assert len(results) == 1
        assert results[0]["name"] == "greet"
        assert results[0]["kind"] == "function"
        assert results[0]["file_path"] == "src/a.ts"

    def test_with_kind_filter(self, conn):
        _seed(conn)
        results = find_symbol(conn, "main", kind="function")
        assert len(results) == 1
        assert results[0]["name"] == "main"

        results = find_symbol(conn, "main", kind="const")
        assert len(results) == 0

    def test_with_file_filter(self, conn):
        _seed(conn)
        results = find_symbol(conn, "helper", file_path="src/b.ts")
        assert len(results) == 1
        assert results[0]["name"] == "helper"

        results = find_symbol(conn, "helper", file_path="src/a.ts")
        assert len(results) == 0

    def test_not_found(self, conn):
        _seed(conn)
        results = find_symbol(conn, "nonexistent")
        assert len(results) == 0

    def test_returns_multiple_files(self, conn):
        project = Project(
            root_path="/test/p",
            name="p",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        project = insert_project(conn, project)

        f1 = insert_file(
            conn, File(project_id=project.id, path="x.ts", language="typescript", content_hash="h1")
        )
        f2 = insert_file(
            conn, File(project_id=project.id, path="y.ts", language="typescript", content_hash="h2")
        )

        insert_symbol(
            conn,
            Symbol(
                file_id=f1.id, name="foo", kind="function", start_line=1, end_line=1, content_hash="h3"
            ),
        )
        insert_symbol(
            conn,
            Symbol(
                file_id=f2.id, name="foo", kind="function", start_line=1, end_line=1, content_hash="h4"
            ),
        )
        conn.commit()

        results = find_symbol(conn, "foo")
        assert len(results) == 2


class TestFindCalls:
    def test_callers(self, conn):
        _seed(conn)
        results = find_calls(conn, "greet", direction="callers")
        assert len(results) == 1
        assert results[0]["caller_name"] == "main"
        assert results[0]["callee_name"] == "greet"
        assert results[0]["file"] == "src/a.ts"

    def test_callees(self, conn):
        _seed(conn)
        results = find_calls(conn, "main", direction="callees")
        assert len(results) == 2
        names = {r["callee_name"] for r in results}
        assert names == {"greet", "console.log"}
        assert results[0]["caller_name"] == "main"

    def test_callees_greet(self, conn):
        _seed(conn)
        results = find_calls(conn, "greet", direction="callees")
        assert len(results) == 1
        assert results[0]["callee_name"] == "helper"
        assert results[0]["caller_name"] == "greet"

    def test_not_found(self, conn):
        _seed(conn)
        results = find_calls(conn, "nonexistent", direction="callers")
        assert len(results) == 0

        results = find_calls(conn, "nonexistent", direction="callees")
        assert len(results) == 0

    def test_invalid_direction(self, conn):
        _seed(conn)
        import pytest
        with pytest.raises(ValueError, match="invalid direction"):
            find_calls(conn, "main", direction="invalid")


class TestGetModule:
    def test_returns_module(self, conn):
        _, file_a, _ = _seed(conn)
        results = get_module(conn, "src/a.ts", file_a.project_id)
        assert results["file"]["path"] == "src/a.ts"
        assert results["file"]["language"] == "typescript"

        symbol_names = {s["name"] for s in results["symbols"]}
        assert symbol_names == {"main", "greet"}

        assert len(results["calls"]) == 3
        assert len(results["imports"]) == 1
        assert results["imports"][0]["imported_path"] == "./b"

    def test_file_not_found(self, conn):
        results = get_module(conn, "nonexistent.ts", 1)
        assert "error" in results
