from datetime import UTC, datetime

from memos.core.db import (
    insert_file,
    insert_import,
    insert_project,
)
from memos.core.models import File, Import, Project
from memos.query.core import (
    find_import_cycles,
    get_dependency_graph,
)


def _noop_seed(conn):
    project = Project(
        root_path="/test/empty",
        name="empty",
        created_at=datetime.now(UTC).isoformat(),
    )
    project = insert_project(conn, project)
    conn.commit()
    return project


def _cycle_seed(conn):
    project = Project(
        root_path="/test/cycle",
        name="cycle",
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

    imp_a_to_b = Import(
        file_id=file_a.id,
        imported_path="./b",
        resolved_file_id=file_b.id,
    )
    insert_import(conn, imp_a_to_b)

    imp_b_to_a = Import(
        file_id=file_b.id,
        imported_path="./a",
        resolved_file_id=file_a.id,
    )
    insert_import(conn, imp_b_to_a)

    conn.commit()
    return project, file_a, file_b


def _no_cycle_seed(conn):
    project = Project(
        root_path="/test/nocycle",
        name="nocycle",
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
        path="src/c.ts",
        language="typescript",
        content_hash="ccc",
    )
    file_c = insert_file(conn, file_c)

    imp_a_to_b = Import(
        file_id=file_a.id,
        imported_path="./b",
        resolved_file_id=file_b.id,
    )
    insert_import(conn, imp_a_to_b)

    imp_a_to_c = Import(
        file_id=file_a.id,
        imported_path="./c",
        resolved_file_id=file_c.id,
    )
    insert_import(conn, imp_a_to_c)

    conn.commit()
    return project, file_a, file_b, file_c


def _no_imports_seed(conn):
    project = Project(
        root_path="/test/noimports",
        name="noimports",
        created_at=datetime.now(UTC).isoformat(),
    )
    project = insert_project(conn, project)

    file_a = File(
        project_id=project.id,
        path="src/a.ts",
        language="typescript",
        content_hash="aaa",
    )
    insert_file(conn, file_a)

    file_b = File(
        project_id=project.id,
        path="src/b.ts",
        language="typescript",
        content_hash="bbb",
    )
    insert_file(conn, file_b)

    conn.commit()
    return project


def _self_loop_seed(conn):
    project = Project(
        root_path="/test/selfloop",
        name="selfloop",
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

    imp_a_to_a = Import(
        file_id=file_a.id,
        imported_path="./a",
        resolved_file_id=file_a.id,
    )
    insert_import(conn, imp_a_to_a)

    conn.commit()
    return project


class TestGetDependencyGraph:
    def test_empty_project(self, conn):
        project = _noop_seed(conn)
        result = get_dependency_graph(conn, project.id)
        assert result == {"nodes": [], "edges": []}

    def test_no_imports(self, conn):
        project = _no_imports_seed(conn)
        result = get_dependency_graph(conn, project.id)
        assert len(result["nodes"]) == 2
        assert result["edges"] == []

    def test_normal_graph(self, conn):
        project, _, _, _ = _no_cycle_seed(conn)
        result = get_dependency_graph(conn, project.id)
        assert len(result["nodes"]) == 3
        assert len(result["edges"]) == 2


class TestFindImportCycles:
    def test_no_cycle(self, conn):
        project = _noop_seed(conn)
        cycles = find_import_cycles(conn, project.id)
        assert cycles == []

    def test_no_cycle_in_graph(self, conn):
        project, _, _, _ = _no_cycle_seed(conn)
        cycles = find_import_cycles(conn, project.id)
        assert cycles == []

    def test_cycle_detected(self, conn):
        project, _file_a, _file_b = _cycle_seed(conn)
        cycles = find_import_cycles(conn, project.id)
        assert len(cycles) == 1
        cycle_paths = cycles[0]
        assert len(cycle_paths) == 2
        assert "src/a.ts" in cycle_paths
        assert "src/b.ts" in cycle_paths

    def test_self_loop_detected(self, conn):
        project = _self_loop_seed(conn)
        cycles = find_import_cycles(conn, project.id)
        assert len(cycles) == 1
        assert cycles[0] == ["src/a.ts"]
