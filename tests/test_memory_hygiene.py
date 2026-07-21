from datetime import UTC, datetime, timedelta

from memos.core.db import insert_memory_entry, insert_project
from memos.core.models import MemoryEntry, Project
from memos.query.core import memory_prune, memory_search


def _seed(conn):
    project = Project(
        root_path="/test",
        name="test",
        created_at=datetime.now(UTC).isoformat(),
    )
    project = insert_project(conn, project)

    now = datetime.now(UTC)
    entries = [
        MemoryEntry(
            project_id=project.id,
            scope_type="project",
            kind="note",
            content="hello world",
            source="agent",
            created_at=now.isoformat(),
        ),
        MemoryEntry(
            project_id=project.id,
            scope_type="project",
            kind="note",
            content="python programming",
            source="agent",
            created_at=now.isoformat(),
        ),
        MemoryEntry(
            project_id=project.id,
            scope_type="project",
            kind="summary",
            content="summary of foo",
            source="agent",
            created_at=(now - timedelta(days=10)).isoformat(),
        ),
        MemoryEntry(
            project_id=project.id,
            scope_type="project",
            kind="decision",
            content="use bar library",
            source="agent",
            created_at=(now - timedelta(days=30)).isoformat(),
        ),
    ]
    for e in entries:
        insert_memory_entry(conn, e)

    conn.commit()
    return project


class TestMemorySearch:
    def test_exact_match(self, conn):
        project = _seed(conn)
        results = memory_search(conn, project.id, "hello world")
        assert len(results) == 1
        assert results[0]["content"] == "hello world"

    def test_partial_match(self, conn):
        project = _seed(conn)
        results = memory_search(conn, project.id, "world")
        assert len(results) >= 1

    def test_no_match(self, conn):
        project = _seed(conn)
        results = memory_search(conn, project.id, "zzzzzznonexistent")
        assert len(results) == 0

    def test_top_k(self, conn):
        project = _seed(conn)
        results = memory_search(conn, project.id, "programming", top_k=1)
        assert len(results) <= 1


class TestMemoryPrune:
    def test_dry_run_returns_count(self, conn):
        project = _seed(conn)
        count = memory_prune(conn, project.id, kind="note", apply=False)
        assert count == 2

    def test_dry_run_does_not_delete(self, conn):
        project = _seed(conn)
        memory_prune(conn, project.id, kind="note", apply=False)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE project_id = ?",
            (project.id,),
        ).fetchone()[0]
        assert remaining == 4

    def test_apply_deletes(self, conn):
        project = _seed(conn)
        memory_prune(conn, project.id, kind="note", apply=True)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE project_id = ?",
            (project.id,),
        ).fetchone()[0]
        assert remaining == 2

    def test_older_than_days_filter(self, conn):
        project = _seed(conn)
        count = memory_prune(conn, project.id, older_than_days=20, apply=False)
        assert count == 1

    def test_older_than_days_apply(self, conn):
        project = _seed(conn)
        memory_prune(conn, project.id, older_than_days=20, apply=True)
        remaining = conn.execute(
            "SELECT COUNT(*) FROM memory_entries WHERE project_id = ?",
            (project.id,),
        ).fetchone()[0]
        assert remaining == 3
