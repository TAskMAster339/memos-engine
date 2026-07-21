from datetime import UTC, datetime

from memos.core.db import (
    insert_call_edge,
    insert_file,
    insert_memory_entry,
    insert_project,
    insert_symbol,
)
from memos.core.models import CallEdge, File, MemoryEntry, Project, Symbol
from memos.query.core import (
    add_memory_entry,
    get_context,
    get_or_generate_summary,
)


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

    edge = CallEdge(
        caller_symbol_id=sym_main.id,
        callee_name="greet",
        callee_symbol_id=sym_greet.id,
        line=2,
    )
    insert_call_edge(conn, edge)

    conn.commit()
    return project, file_a, sym_main, sym_greet


class TestGetOrGenerateSummary:
    def test_returns_generation_context_when_no_summary(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT s.* FROM symbols s WHERE s.name = ?", ("main",)
        ).fetchone()

        result = get_or_generate_summary(conn, row["id"], row["content_hash"])
        assert result["summary"] is None
        assert result["generation_context"] is not None
        ctx = result["generation_context"]
        assert ctx["name"] == "main"
        assert ctx["kind"] == "function"
        assert ctx["signature"] == "(): void"
        assert ctx["content_hash"] == "h1"
        assert len(ctx["callers"]) == 0

    def test_callers_in_generation_context(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT s.* FROM symbols s WHERE s.name = ?", ("greet",)
        ).fetchone()

        result = get_or_generate_summary(conn, row["id"], row["content_hash"])
        ctx = result["generation_context"]
        assert len(ctx["callers"]) == 1
        assert ctx["callers"][0]["name"] == "main"

    def test_returns_cached_summary_when_hash_matches(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT s.*, f.project_id FROM symbols s "
            "JOIN files f ON f.id = s.file_id WHERE s.name = ?",
            ("main",),
        ).fetchone()

        insert_memory_entry(
            conn,
            MemoryEntry(
                project_id=row["project_id"],
                scope_type="symbol",
                scope_id=row["id"],
                kind="summary",
                content="Main function summary",
                source="agent",
                source_hash=row["content_hash"],
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()

        result = get_or_generate_summary(conn, row["id"], row["content_hash"])
        assert result["summary"] is not None
        assert result["summary"]["content"] == "Main function summary"
        assert result["generation_context"] is None

    def test_returns_generation_context_when_hash_mismatch(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT s.*, f.project_id FROM symbols s "
            "JOIN files f ON f.id = s.file_id WHERE s.name = ?",
            ("main",),
        ).fetchone()

        insert_memory_entry(
            conn,
            MemoryEntry(
                project_id=row["project_id"],
                scope_type="symbol",
                scope_id=row["id"],
                kind="summary",
                content="Old summary",
                source="agent",
                source_hash="old_hash",
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()

        result = get_or_generate_summary(conn, row["id"], row["content_hash"])
        assert result["summary"] is None
        assert result["generation_context"] is not None

    def test_returns_none_when_symbol_not_found(self, conn):
        result = get_or_generate_summary(conn, 99999, "nohash")
        assert result["summary"] is None
        assert result["generation_context"] is None


class TestGetContext:
    def test_returns_full_context(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT s.* FROM symbols s WHERE s.name = ?", ("main",)
        ).fetchone()

        result = get_context(conn, row["id"])
        assert "error" not in result
        assert result["symbol"]["name"] == "main"
        assert len(result["callees"]) == 1
        assert result["callees"][0]["callee_name"] == "greet"
        assert result["memories"] is not None
        assert result["generation_context"] is not None

    def test_returns_context_with_summary(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT s.*, f.project_id FROM symbols s "
            "JOIN files f ON f.id = s.file_id WHERE s.name = ?",
            ("main",),
        ).fetchone()

        insert_memory_entry(
            conn,
            MemoryEntry(
                project_id=row["project_id"],
                scope_type="symbol",
                scope_id=row["id"],
                kind="summary",
                content="Main summary",
                source="agent",
                source_hash=row["content_hash"],
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        conn.commit()

        result = get_context(conn, row["id"])
        assert result["summary"] is not None
        assert result["summary"]["content"] == "Main summary"
        assert result["generation_context"] is None

    def test_returns_error_for_missing_symbol(self, conn):
        result = get_context(conn, 99999)
        assert "error" in result

    def test_includes_memories(self, conn):
        _seed(conn)
        row = conn.execute(
            "SELECT s.*, f.project_id FROM symbols s "
            "JOIN files f ON f.id = s.file_id WHERE s.name = ?",
            ("main",),
        ).fetchone()

        add_memory_entry(
            conn,
            row["project_id"],
            "Important decision",
            scope_type="symbol",
            scope_id=row["id"],
            kind="decision",
        )
        conn.commit()

        result = get_context(conn, row["id"])
        decisions = [m for m in result["memories"] if m["kind"] == "decision"]
        assert len(decisions) == 1
        assert decisions[0]["content"] == "Important decision"


class TestAddMemoryEntryWithSourceHash:
    def test_explicit_source_hash(self, conn):
        p = insert_project(
            conn,
            Project(root_path="/mem", name="mem", created_at="now"),
        )
        entry = add_memory_entry(
            conn,
            p.id,
            "summary text",
            scope_type="symbol",
            scope_id=42,
            kind="summary",
            source="agent",
            source_hash="explicit_hash",
        )
        assert entry["source_hash"] == "explicit_hash"
        assert entry["content"] == "summary text"

    def test_default_source_hash_is_content_hash(self, conn):
        p = insert_project(
            conn,
            Project(root_path="/mem", name="mem", created_at="now"),
        )
        entry = add_memory_entry(
            conn,
            p.id,
            "note text",
            scope_type="project",
            kind="note",
        )
        assert entry["source_hash"] is not None
