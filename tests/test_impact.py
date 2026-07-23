from datetime import UTC, datetime

from memos.core.db import (
    insert_call_edge,
    insert_file,
    insert_import,
    insert_project,
    insert_symbol,
)
from memos.core.models import CallEdge, File, Import, Project, Symbol
from memos.query.core import get_diff_impact, get_rename_impact


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
        name="Config",
        kind="interface",
        exported=True,
        content_hash="h4",
        start_line=5,
        end_line=5,
    )
    sym_config = insert_symbol(conn, sym_config)

    sym_user = Symbol(
        file_id=file_b.id,
        name="user",
        kind="function",
        signature="(c: Config): void",
        start_line=7,
        end_line=9,
        exported=True,
        content_hash="h5",
    )
    sym_user = insert_symbol(conn, sym_user)

    edge1 = CallEdge(
        caller_symbol_id=sym_main.id,
        callee_name="greet",
        callee_symbol_id=sym_greet.id,
        line=2,
    )
    insert_call_edge(conn, edge1)

    edge2 = CallEdge(
        caller_symbol_id=sym_user.id,
        callee_name="greet",
        callee_symbol_id=sym_greet.id,
        line=8,
    )
    insert_call_edge(conn, edge2)

    imp = Import(
        file_id=file_a.id,
        imported_path="./b",
        resolved_file_id=file_b.id,
    )
    insert_import(conn, imp)

    conn.commit()
    return (
        project, file_a, file_b,
        sym_main, sym_greet, sym_helper, sym_config, sym_user,
    )


class TestGetRenameImpact:
    def test_returns_empty_lists_when_no_dependents(self, conn):
        _seed(conn)
        result = get_rename_impact(conn, 1)  # main: no type/import refs
        assert "error" not in result
        assert result["type_references"] == []
        assert result["import_references"] == []
        assert result["warning"] is not None

    def test_returns_callers(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT id FROM symbols WHERE name = ?", ("greet",)
        ).fetchone()
        result = get_rename_impact(conn, row["id"])
        assert len(result["callers"]) == 2
        names = {c["caller_name"] for c in result["callers"]}
        assert names == {"main", "user"}

    def test_type_references_for_interface(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT id FROM symbols WHERE name = ?", ("Config",)
        ).fetchone()
        result = get_rename_impact(conn, row["id"])
        assert len(result["type_references"]) >= 1
        ref_names = {r["name"] for r in result["type_references"]}
        assert "user" in ref_names

    def test_function_has_no_type_references(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT id FROM symbols WHERE name = ?", ("main",)
        ).fetchone()
        result = get_rename_impact(conn, row["id"])
        assert result["type_references"] == []

    def test_not_found(self, conn):
        result = get_rename_impact(conn, 99999)
        assert "error" in result

    def test_rename_impact_no_substring_collision(self, conn):
        _, _, fb, _, _, _, sym_config, _ = _seed(conn)
        insert_symbol(conn, Symbol(
            file_id=fb.id, name="ConfigLoader", kind="interface",
            exported=True, content_hash="h6", start_line=10, end_line=10,
        ))
        insert_symbol(conn, Symbol(
            file_id=fb.id, name="useLoader", kind="function",
            signature="(l: ConfigLoader): void",
            exported=True, content_hash="h7", start_line=12, end_line=14,
        ))
        conn.commit()
        result = get_rename_impact(conn, sym_config.id)
        refs = result["type_references"]
        ref_names = {r["name"] for r in refs}
        assert "user" in ref_names, "user (c: Config) should match"
        assert "useLoader" not in ref_names, (
            "useLoader (l: ConfigLoader) should NOT match Config"
        )


class TestGetDiffImpact:
    def test_aggregates_by_caller_file(self, conn):
        _seed(conn)
        result = get_diff_impact(conn, "src/a.ts", 1)
        assert "error" not in result
        assert result["file"]["path"] == "src/a.ts"
        exported = {s["name"]: s for s in result["exported_symbols"]}
        assert "greet" in exported
        greet = exported["greet"]
        assert len(greet["caller_files"]) == 2
        files = {cf["file"] for cf in greet["caller_files"]}
        assert files == {"src/a.ts", "src/b.ts"}

    def test_empty_for_unused_exported(self, conn):
        _seed(conn)
        result = get_diff_impact(conn, "src/b.ts", 1)
        assert "error" not in result
        exported = {s["name"]: s for s in result["exported_symbols"]}
        assert "Config" in exported
        assert exported["Config"]["caller_files"] == []

    def test_not_found(self, conn):
        result = get_diff_impact(conn, "nonexistent.ts", 1)
        assert "error" in result
