import subprocess
from pathlib import Path

import pytest

from memos.cli.main import (
    EXTENSION_INDEXERS,
    find_changed_files,
    find_files,
    index_file,
)
from memos.core.db import (
    delete_file,
    get_connection,
    get_file_by_path,
    resolve_imports,
    run_migrations,
)
from memos.core.models import Project


def _git(cmd, cwd):
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, check=False)
    assert result.returncode == 0, f"git cmd {' '.join(cmd)} failed: {result.stderr}"
    return result.stdout.strip()


def _init_repo(tmp_path: Path):
    _git(["git", "init"], tmp_path)
    _git(["git", "config", "user.email", "test@test"], tmp_path)
    _git(["git", "config", "user.name", "test"], tmp_path)
    return tmp_path


def _commit_all(repo: Path, msg: str):
    _git(["git", "add", "-A"], repo)
    _git(["git", "commit", "-m", msg], repo)


@pytest.fixture
def repo(tmp_path: Path):
    return _init_repo(tmp_path)


@pytest.fixture
def conn_for_repo(repo: Path):
    memos_dir = repo / ".memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memos_dir / "memory.db")
    c = get_connection(db_path)
    run_migrations(c)
    yield c
    c.close()


@pytest.fixture
def project_for_conn(conn_for_repo, repo: Path):
    root = str(repo)
    c = conn_for_repo
    proj = Project(root_path=root, name="test", created_at="2026-01-01T00:00:00")
    cur = c.execute(
        "INSERT INTO projects (root_path, name, created_at) VALUES (?, ?, ?)",
        (proj.root_path, proj.name, proj.created_at),
    )
    return proj.model_copy(update={"id": cur.lastrowid})


class TestFindChangedFiles:
    def test_since_returns_only_changed(self, repo: Path):
        root = str(repo)
        (repo / "a.ts").write_text("export const a = 1;")
        (repo / "b.ts").write_text("export const b = 1;")
        _commit_all(repo, "commit A: a + b")

        ref_a = _git(["git", "rev-parse", "HEAD"], repo)

        (repo / "a.ts").write_text("export const a = 2;")
        (repo / "c.ts").write_text("export const c = 1;")
        _commit_all(repo, "commit B: mod a + add c")

        files, deleted = find_changed_files(root, git_ref=ref_a)
        rels = {rel for _, rel in files}
        assert rels == {"a.ts", "c.ts"}
        assert deleted == []

    def test_since_detects_deleted(self, repo: Path):
        root = str(repo)
        (repo / "a.ts").write_text("export const a = 1;")
        (repo / "b.ts").write_text("export const b = 1;")
        _commit_all(repo, "commit A: a + b")

        ref_a = _git(["git", "rev-parse", "HEAD"], repo)

        (repo / "a.ts").unlink()
        _commit_all(repo, "commit B: delete a")

        files, deleted = find_changed_files(root, git_ref=ref_a)
        assert files == []
        assert deleted == ["a.ts"]

    def test_dirty_returns_modified_and_untracked(self, repo: Path):
        root = str(repo)
        (repo / "a.ts").write_text("export const a = 1;")
        (repo / "b.ts").write_text("export const b = 1;")
        _commit_all(repo, "initial")

        # modify a.ts, add c.ts, delete b.ts
        (repo / "a.ts").write_text("export const a = 2;")
        (repo / "c.ts").write_text("export const c = 1;")
        (repo / "b.ts").unlink()


        files, deleted = find_changed_files(root, dirty=True)
        rels = {rel for _, rel in files}
        assert rels == {"a.ts", "c.ts"}
        assert deleted == ["b.ts"]

    def test_no_flags_delegates_to_find_files(self, repo: Path):
        root = str(repo)
        (repo / "a.ts").write_text("export const a = 1;")
        (repo / "b.ts").write_text("export const b = 1;")
        _commit_all(repo, "initial")

        files, deleted = find_changed_files(root)
        rels = {rel for _, rel in files}
        assert rels == {"a.ts", "b.ts"}
        assert deleted == []

    def test_not_a_git_repo(self, tmp_path: Path):
        root = str(tmp_path)
        with pytest.raises(SystemExit) as exc:
            find_changed_files(root, git_ref="HEAD")
        assert exc.value.code == 1

    def test_dirty_not_a_git_repo(self, tmp_path: Path):
        root = str(tmp_path)
        with pytest.raises(SystemExit) as exc:
            find_changed_files(root, dirty=True)
        assert exc.value.code == 1


class TestIncrementalReindex:
    def test_since_indexes_only_changed(
        self, repo: Path, conn_for_repo, project_for_conn,
    ):
        c = conn_for_repo
        proj = project_for_conn
        root = str(repo)

        (repo / "a.ts").write_text("export const a = 1;")
        (repo / "b.ts").write_text("export const b = 1;")
        _commit_all(repo, "A: a + b")
        ref_a = _git(["git", "rev-parse", "HEAD"], repo)

        for full, rel in find_files(root):
            ext = Path(full).suffix.lower()
            indexer = EXTENSION_INDEXERS[ext]
            index_file(c, proj, full, rel, indexer, full=True, embed=False)
        c.commit()
        assert get_file_by_path(c, proj.id, "a.ts") is not None

        # delete a.ts in commit B
        (repo / "a.ts").unlink()
        _commit_all(repo, "B: delete a")

        files, deleted = find_changed_files(root, git_ref=ref_a)
        assert files == []
        assert deleted == ["a.ts"]

        for rel in deleted:
            existing = get_file_by_path(c, proj.id, rel)
            if existing:
                delete_file(c, existing.id)
        c.commit()

        assert get_file_by_path(c, proj.id, "a.ts") is None
        assert get_file_by_path(c, proj.id, "b.ts") is not None

    def test_deleted_file_removed_from_index(
        self, repo: Path, conn_for_repo, project_for_conn,
    ):
        c = conn_for_repo
        proj = project_for_conn
        root = str(repo)

        (repo / "a.ts").write_text("export const a = 1;")
        (repo / "b.ts").write_text("export const b = 1;")
        _commit_all(repo, "A: a + b")
        ref_a = _git(["git", "rev-parse", "HEAD"], repo)
        # index commit A fully
        for full, rel in find_files(root):
            ext = Path(full).suffix.lower()
            indexer = EXTENSION_INDEXERS[ext]
            index_file(c, proj, full, rel, indexer, full=True, embed=False)
        c.commit()

        assert get_file_by_path(c, proj.id, "a.ts") is not None
        assert get_file_by_path(c, proj.id, "b.ts") is not None

        # delete b.ts in commit B
        (repo / "b.ts").unlink()
        _commit_all(repo, "B: delete b")

        _files, deleted = find_changed_files(root, git_ref=ref_a)
        for rel in deleted:
            existing = get_file_by_path(c, proj.id, rel)
            if existing:
                delete_file(c, existing.id)
        c.commit()

        assert get_file_by_path(c, proj.id, "a.ts") is not None
        assert get_file_by_path(c, proj.id, "b.ts") is None

    def test_dirty_indexes_uncommitted(
        self, repo: Path, conn_for_repo, project_for_conn,
    ):
        c = conn_for_repo
        proj = project_for_conn
        root = str(repo)

        (repo / "a.ts").write_text("export const a = 1;")
        (repo / "b.ts").write_text("export const b = 1;")
        _commit_all(repo, "initial")
        # index all
        for full, rel in find_files(root):
            ext = Path(full).suffix.lower()
            indexer = EXTENSION_INDEXERS[ext]
            index_file(c, proj, full, rel, indexer, full=True, embed=False)
        c.commit()

        # now dirty changes
        (repo / "a.ts").write_text("export const a = 2;")
        (repo / "c.ts").write_text("export const c = 1;")
        (repo / "b.ts").unlink()

        files, deleted = find_changed_files(root, dirty=True)
        for rel in deleted:
            existing = get_file_by_path(c, proj.id, rel)
            if existing:
                delete_file(c, existing.id)
        for full, rel in files:
            ext = Path(full).suffix.lower()
            if ext not in EXTENSION_INDEXERS:
                continue
            indexer = EXTENSION_INDEXERS[ext]
            index_file(c, proj, full, rel, indexer, full=True, embed=False)
        resolve_imports(c, proj.id)
        c.commit()

        symbols = c.execute(
            "SELECT s.name, f.path FROM symbols s JOIN files f ON f.id = s.file_id "
            "WHERE f.project_id = ? ORDER BY s.name",
            (proj.id,),
        ).fetchall()
        names = {r["name"] for r in symbols}
        assert names == {"a", "c"}, f"expected a, c but got {names}"
