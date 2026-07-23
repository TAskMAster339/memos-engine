import subprocess
from pathlib import Path

from memos.core.db import (
    get_file_by_path,
    insert_call_edge,
    insert_file,
    insert_import,
    insert_project,
    insert_symbol,
)
from memos.core.models import CallEdge, File, Import, Project, Symbol
from memos.query.core import get_diff_range_impact


def _seed_two_files(conn):
    """Seed a project with two files: a.ts exports greet, b.ts imports+uses greet."""
    project = Project(
        root_path="/test/proj",
        name="proj",
        created_at="2026-01-01T00:00:00",
    )
    project = insert_project(conn, project)

    file_a = File(
        project_id=project.id, path="src/a.ts",
        language="typescript", content_hash="aaa",
    )
    file_a = insert_file(conn, file_a)

    file_b = File(
        project_id=project.id, path="src/b.ts",
        language="typescript", content_hash="bbb",
    )
    file_b = insert_file(conn, file_b)

    sym_greet = Symbol(
        file_id=file_a.id, name="greet", kind="function",
        signature="(name: string): string",
        start_line=1, end_line=5, exported=True, content_hash="h1",
    )
    sym_greet = insert_symbol(conn, sym_greet)

    sym_main = Symbol(
        file_id=file_b.id, name="main", kind="function",
        signature="(): void",
        start_line=1, end_line=10, exported=True, content_hash="h2",
    )
    sym_main = insert_symbol(conn, sym_main)

    edge = CallEdge(
        caller_symbol_id=sym_main.id,
        callee_name="greet",
        callee_symbol_id=sym_greet.id,
        line=3,
    )
    insert_call_edge(conn, edge)

    imp = Import(
        file_id=file_b.id,
        imported_path="./a",
        resolved_file_id=file_a.id,
    )
    insert_import(conn, imp)

    conn.commit()
    return project, file_a, file_b, sym_greet, sym_main


class TestGetDiffRangeImpact:
    def test_aggregates_across_files(self, conn):
        _seed_two_files(conn)
        project = conn.execute(
            "SELECT * FROM projects ORDER BY id DESC LIMIT 1"
        ).fetchone()

        result = get_diff_range_impact(conn, project["id"], ["src/a.ts"])
        assert "error" not in result
        assert result["total_exported_symbols"] == 1
        assert result["total_external_callers"] >= 1
        assert len(result["files"]) == 1
        assert result["files"][0]["file"]["path"] == "src/a.ts"

    def test_skips_nonexistent_file(self, conn):
        _seed_two_files(conn)
        project = conn.execute(
            "SELECT * FROM projects ORDER BY id DESC LIMIT 1"
        ).fetchone()

        result = get_diff_range_impact(
            conn, project["id"], ["src/a.ts", "src/missing.ts"],
        )
        assert len(result["files"]) == 1

    def test_empty_changed_list(self, conn):
        _seed_two_files(conn)
        project = conn.execute(
            "SELECT * FROM projects ORDER BY id DESC LIMIT 1"
        ).fetchone()

        result = get_diff_range_impact(conn, project["id"], [])
        assert result["files"] == []
        assert result["total_exported_symbols"] == 0
        assert result["total_external_callers"] == 0


class TestDiffRangeWithGit:
    def _git(self, cmd, cwd):
        res = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
        assert res.returncode == 0, f"git {' '.join(cmd)} failed: {res.stderr}"
        return res.stdout.strip()

    def test_full_pipeline(self, tmp_path: Path, conn):
        repo = tmp_path / "repo"
        repo.mkdir()
        root = str(repo)
        self._git(["git", "init"], repo)
        self._git(["git", "config", "user.email", "t@t"], repo)
        self._git(["git", "config", "user.name", "t"], repo)

        # commit A: a.ts
        (repo / "a.ts").write_text(
            "export const greet = (name: string): string => name;",
        )
        self._git(["git", "add", "-A"], repo)
        self._git(["git", "commit", "-m", "A: a.ts"], repo)
        ref_a = self._git(["git", "rev-parse", "HEAD"], repo)

        # commit B: modify a.ts, add b.ts
        (repo / "a.ts").write_text(
            "export const greet = (name: string): string => `Hi ${name}`;",
        )
        (repo / "b.ts").write_text(
            "export const main = (): void => { greet('world'); }",
        )
        self._git(["git", "add", "-A"], repo)
        self._git(["git", "commit", "-m", "B: mod a + add b"], repo)

        # manually index files into the in-memory conn
        from memos.cli.main import (
            EXTENSION_INDEXERS,
            find_changed_files,
            get_or_create_project,
            index_file,
        )
        from memos.core.db import resolve_imports

        project = get_or_create_project(conn, root)

        for full, rel in find_changed_files(root, git_ref=ref_a)[0]:
            ext = Path(full).suffix.lower()
            indexer = EXTENSION_INDEXERS[ext]
            index_file(conn, project, full, rel, indexer, full=True, embed=False)

        # also index b.ts (not in diff but needed for caller info)
        for _full, rel in [("b.ts", "b.ts")]:
            full_path = str(repo / rel)
            if Path(full_path).exists() and not get_file_by_path(conn, project.id, rel):
                ext = Path(full_path).suffix.lower()
                indexer = EXTENSION_INDEXERS[ext]
                index_file(
                    conn, project, full_path, rel, indexer, full=True, embed=False,
                )

        resolve_imports(conn, project.id)
        conn.commit()

        # get changed files via find_changed_files
        changed_files, _deleted = find_changed_files(root, git_ref=ref_a)

        changed_in_index: list[str] = []
        for _full, rel in changed_files:
            existing = get_file_by_path(conn, project.id, rel)
            if existing:
                changed_in_index.append(rel)

        result = get_diff_range_impact(conn, project.id, changed_in_index)
        assert result["total_exported_symbols"] >= 1
        assert len(result["files"]) >= 1
        paths = {f["file"]["path"] for f in result["files"]}
        assert "a.ts" in paths
