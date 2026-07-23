from datetime import UTC, datetime

from memos.core.db import (
    insert_file,
    insert_import,
    insert_project,
    resolve_imports,
)
from memos.core.models import File, Import, Project
from memos.query.import_resolver import resolve_go_import


def _make_project(conn, root="/test/p"):
    project = Project(
        root_path=root,
        name="p",
        created_at=datetime.now(UTC).isoformat(),
    )
    return insert_project(conn, project)


def _make_file(conn, project_id, path, language="typescript", content_hash="h"):
    return insert_file(
        conn,
        File(
            project_id=project_id,
            path=path,
            language=language,
            content_hash=content_hash,
        ),
    )


def _make_import(conn, file_id, imported_path):
    return insert_import(
        conn,
        Import(file_id=file_id, imported_path=imported_path),
    )


class TestResolveImports:
    def test_ts_relative_same_dir(self, conn):
        project = _make_project(conn)
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "src/utils.ts")
        imp = _make_import(conn, f1.id, "./utils")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row is not None
        assert row["resolved_file_id"] is not None


class TestResolveGoImports:
    def test_go_import_resolves(self, conn, tmp_path):
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module myapp\n")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.go", language="go")
        _make_file(conn, project.id, "src/utils.go", language="go")
        # src/ is a Go package; import path is myapp/src
        imp = _make_import(conn, f1.id, "myapp/src")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row is not None
        assert row["resolved_file_id"] is not None

    def test_go_stdlib_left_null(self, conn, tmp_path):
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module myapp\n")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.go", language="go")
        imp_fmt = _make_import(conn, f1.id, "fmt")
        imp_os = _make_import(conn, f1.id, "os")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 0

        for imp in (imp_fmt, imp_os):
            row = conn.execute(
                "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
            ).fetchone()
            assert row["resolved_file_id"] is None

    def test_go_external_module_null(self, conn, tmp_path):
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module myapp\n")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.go", language="go")
        imp = _make_import(conn, f1.id, "github.com/foo/bar")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 0

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is None

    def test_go_no_gomod_null(self, conn):
        project = _make_project(conn, root="/tmp/nonexistent")
        f1 = _make_file(conn, project.id, "src/main.go", language="go")
        imp = _make_import(conn, f1.id, "myapp/src/utils")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 0

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is None

    def test_go_prefers_main_go(self, conn, tmp_path):
        go_mod = tmp_path / "go.mod"
        go_mod.write_text("module myapp\n")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.go", language="go")
        _make_file(conn, project.id, "src/mypkg/other.go", language="go")
        _make_file(conn, project.id, "src/mypkg/main.go", language="go")
        imp = _make_import(conn, f1.id, "myapp/src/mypkg")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT i.resolved_file_id, f.path FROM imports i "
            "JOIN files f ON f.id = i.resolved_file_id "
            "WHERE i.id = ?",
            (imp.id,),
        ).fetchone()
        assert row is not None
        assert row["path"] == "src/mypkg/main.go"

    def test_go_resolve_import_unit(self):
        """Unit test for resolve_go_import directly."""
        path_to_id = {"pkg/main.go": 1, "pkg/other.go": 2, "pkg/sub/util.go": 3}
        dir_to_go_paths = {
            "pkg": [("pkg/main.go", 1), ("pkg/other.go", 2)],
            "pkg/sub": [("pkg/sub/util.go", 3)],
        }

        # Resolves to main.go
        fid = resolve_go_import(
            "myapp/pkg", "", path_to_id, dir_to_go_paths, "myapp",
        )
        assert fid == 1

        # Resolves to sub/util.go (no main.go in sub/)
        fid = resolve_go_import(
            "myapp/pkg/sub", "", path_to_id, dir_to_go_paths, "myapp",
        )
        assert fid == 3

        # External module → None
        fid = resolve_go_import(
            "github.com/foo/bar", "", path_to_id, dir_to_go_paths, "myapp",
        )
        assert fid is None

        # No module_prefix → None
        fid = resolve_go_import(
            "myapp/pkg", "", path_to_id, dir_to_go_paths, None,
        )
        assert fid is None

    def test_python_stdlib_left_null(self, conn):
        project = _make_project(conn)
        f1 = _make_file(conn, project.id, "src/main.py", language="python")
        imp = _make_import(conn, f1.id, "os")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 0

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is None

    def test_python_absolute_intra_package(self, conn):
        project = _make_project(conn, root="/test/proj")
        f1 = _make_file(conn, project.id, "tests/test_main.py", language="python")
        _make_file(conn, project.id, "memos/core/db.py", language="python")
        imp = _make_import(conn, f1.id, "memos.core.db")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row is not None
        assert row["resolved_file_id"] is not None

    def test_python_relative_same_package(self, conn):
        project = _make_project(conn)
        f1 = _make_file(conn, project.id, "src/main.py", language="python")
        _make_file(conn, project.id, "src/utils.py", language="python")
        imp = _make_import(conn, f1.id, ".utils")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row is not None
        assert row["resolved_file_id"] is not None

    def test_python_relative_up_package(self, conn):
        project = _make_project(conn)
        f1 = _make_file(conn, project.id, "src/sub/main.py", language="python")
        _make_file(conn, project.id, "src/pkg.py", language="python")
        imp = _make_import(conn, f1.id, "..pkg")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row is not None
        assert row["resolved_file_id"] is not None

    def test_deleted_file_nulled_on_rerun(self, conn):
        project = _make_project(conn)
        f1 = _make_file(conn, project.id, "src/main.ts")
        f2 = _make_file(conn, project.id, "src/utils.ts")
        imp = insert_import(
            conn,
            Import(file_id=f1.id, imported_path="./utils", resolved_file_id=f2.id),
        )
        conn.commit()

        # Delete the resolved file
        conn.execute("DELETE FROM files WHERE id = ?", (f2.id,))
        conn.commit()

        # Re-resolve should NULL the stale resolved_file_id
        count = resolve_imports(conn, project.id)
        # f2 no longer exists, so this import won't resolve
        assert count == 0

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is None
