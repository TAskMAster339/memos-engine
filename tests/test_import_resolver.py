import json
from datetime import UTC, datetime
from pathlib import Path

from memos.core.db import (
    insert_file,
    insert_import,
    insert_project,
    resolve_imports,
)
from memos.core.models import File, Import, Project
from memos.query.import_resolver import resolve_go_import, resolve_ts_import


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


class TestResolveTsAbsoluteImports:
    """Tests for TS/JS absolute import resolution via tsconfig baseUrl and paths."""

    def _make_tsconfig(self, root, base_url=None, paths=None):
        cfg = {"compilerOptions": {}}
        if base_url is not None:
            cfg["compilerOptions"]["baseUrl"] = base_url
        if paths is not None:
            cfg["compilerOptions"]["paths"] = paths
        p = Path(root) / "tsconfig.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")

    def test_absolute_with_base_url(self, conn, tmp_path):
        self._make_tsconfig(tmp_path, base_url="src")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "src/components/Button.tsx")
        imp = _make_import(conn, f1.id, "components/Button")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1
        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is not None

    def test_absolute_with_paths_alias(self, conn, tmp_path):
        self._make_tsconfig(tmp_path, paths={"@app/*": ["src/*"]})
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "src/utils.ts")
        imp = _make_import(conn, f1.id, "@app/utils")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1
        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is not None

    def test_absolute_paths_with_deep_wildcard(self, conn, tmp_path):
        self._make_tsconfig(tmp_path, paths={"@lib/*": ["lib/*"]})
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "lib/deep/nested/util.ts")
        imp = _make_import(conn, f1.id, "@lib/deep/nested/util")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1
        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is not None

    def test_absolute_paths_multiple_replacements(self, conn, tmp_path):
        self._make_tsconfig(tmp_path, paths={"@app/*": ["fallback/*", "src/*"]})
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "src/utils.ts")
        imp = _make_import(conn, f1.id, "@app/utils")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1
        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is not None

    def test_absolute_paths_exact_match(self, conn, tmp_path):
        self._make_tsconfig(tmp_path, paths={"@app": ["src/app.ts"]})
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "src/app.ts")
        imp = _make_import(conn, f1.id, "@app")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1
        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is not None

    def test_npm_still_null(self, conn, tmp_path):
        self._make_tsconfig(tmp_path, base_url=".")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        imp = _make_import(conn, f1.id, "lodash")
        imp_react = _make_import(conn, f1.id, "react")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 0
        for imp_id in (imp.id, imp_react.id):
            row = conn.execute(
                "SELECT resolved_file_id FROM imports WHERE id = ?", (imp_id,),
            ).fetchone()
            assert row["resolved_file_id"] is None

    def test_no_tsconfig_unchanged(self, conn, tmp_path):
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "src/utils.ts")
        imp = _make_import(conn, f1.id, "utils")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 0

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is None

    def test_relative_import_still_works_with_tsconfig(self, conn, tmp_path):
        self._make_tsconfig(tmp_path, base_url="src")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "src/utils.ts")
        imp = _make_import(conn, f1.id, "./utils")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is not None

    def test_base_url_as_dot_relative(self, conn, tmp_path):
        self._make_tsconfig(tmp_path, base_url=".")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "src/main.ts")
        _make_file(conn, project.id, "src/utils.ts")
        imp = _make_import(conn, f1.id, "src/utils")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is not None

    def test_jsconfig_works_too(self, conn, tmp_path):
        cfg = {"compilerOptions": {"baseUrl": "lib"}}
        p = Path(tmp_path) / "jsconfig.json"
        p.write_text(json.dumps(cfg), encoding="utf-8")
        project = _make_project(conn, root=str(tmp_path))
        f1 = _make_file(conn, project.id, "index.js", language="javascript")
        _make_file(conn, project.id, "lib/helper.js", language="javascript")
        imp = _make_import(conn, f1.id, "helper")
        conn.commit()

        count = resolve_imports(conn, project.id)
        assert count == 1

        row = conn.execute(
            "SELECT resolved_file_id FROM imports WHERE id = ?", (imp.id,),
        ).fetchone()
        assert row["resolved_file_id"] is not None

    # ── Direct unit tests ──────────────────────────────────────────────

    def test_direct_base_url(self):
        path_to_id = {"src/components/Button.tsx": 10}
        fid = resolve_ts_import(
            "components/Button", "src/main.ts", path_to_id,
            base_url="src",
        )
        assert fid == 10

    def test_direct_paths_alias(self):
        path_to_id = {"src/utils.ts": 20}
        fid = resolve_ts_import(
            "@app/utils", "src/main.ts", path_to_id,
            base_url="src", paths={"@app/*": ["src/*"]},
        )
        assert fid == 20

    def test_direct_relative_still_works(self):
        path_to_id = {"src/utils.ts": 30}
        fid = resolve_ts_import(
            "./utils", "src/main.ts", path_to_id,
            base_url="whatever",
        )
        assert fid == 30

    def test_direct_npm_still_null(self):
        path_to_id = {"src/main.ts": 40}
        fid = resolve_ts_import(
            "lodash", "src/main.ts", path_to_id,
            base_url="src",
        )
        assert fid is None

    def test_direct_no_base_url_no_paths(self):
        path_to_id = {"utils.ts": 50}
        fid = resolve_ts_import("utils", "src/main.ts", path_to_id)
        assert fid is None


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
