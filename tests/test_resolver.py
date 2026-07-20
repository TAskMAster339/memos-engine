from datetime import UTC, datetime

from memos.core.db import (
    get_connection,
    insert_call_edge,
    insert_file,
    insert_project,
    insert_symbol,
    resolve_call_edges,
    run_migrations,
)
from memos.core.models import CallEdge, File, Project, Symbol


def _seed_two_files(conn):
    project = Project(
        root_path="/test/p",
        name="p",
        created_at=datetime.now(UTC).isoformat(),
    )
    project = insert_project(conn, project)

    fa = insert_file(
        conn,
        File(
            project_id=project.id,
            path="src/a.ts",
            language="typescript",
            content_hash="ha",
        ),
    )
    fb = insert_file(
        conn,
        File(
            project_id=project.id,
            path="src/b.ts",
            language="typescript",
            content_hash="hb",
        ),
    )

    sym_a = insert_symbol(
        conn,
        Symbol(
            file_id=fa.id,
            name="main",
            kind="function",
            start_line=1,
            end_line=5,
            content_hash="h1",
        ),
    )
    sym_b_greet = insert_symbol(
        conn,
        Symbol(
            file_id=fb.id,
            name="greet",
            kind="function",
            exported=True,
            start_line=1,
            end_line=3,
            content_hash="h2",
        ),
    )

    e = CallEdge(caller_symbol_id=sym_a.id, callee_name="greet", line=2)
    insert_call_edge(conn, e)

    e2 = CallEdge(caller_symbol_id=sym_a.id, callee_name="console.log", line=4)
    insert_call_edge(conn, e2)

    conn.commit()
    return project, fa, fb, sym_a, sym_b_greet


def _seed_same_file(conn):
    project = Project(
        root_path="/test/p",
        name="p",
        created_at=datetime.now(UTC).isoformat(),
    )
    project = insert_project(conn, project)

    fa = insert_file(
        conn,
        File(
            project_id=project.id,
            path="src/a.ts",
            language="typescript",
            content_hash="ha",
        ),
    )

    sym_caller = insert_symbol(
        conn,
        Symbol(
            file_id=fa.id,
            name="caller",
            kind="function",
            start_line=1,
            end_line=5,
            content_hash="h1",
        ),
    )
    sym_callee = insert_symbol(
        conn,
        Symbol(
            file_id=fa.id,
            name="callee",
            kind="function",
            start_line=7,
            end_line=9,
            content_hash="h2",
        ),
    )

    e = CallEdge(caller_symbol_id=sym_caller.id, callee_name="callee", line=3)
    insert_call_edge(conn, e)

    conn.commit()
    return project, sym_caller, sym_callee


class TestResolveCallEdges:
    def test_resolve_intra_file(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        project, _caller, callee = _seed_same_file(conn)

        resolved = resolve_call_edges(conn, project.id)

        assert resolved == 1
        row = conn.execute("SELECT callee_symbol_id FROM call_edges").fetchone()
        assert row["callee_symbol_id"] == callee.id

        conn.close()

    def test_resolve_cross_file(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        project, _, _, _, greet = _seed_two_files(conn)

        resolved = resolve_call_edges(conn, project.id)

        assert resolved == 1  # greet resolves, console.log stays NULL
        row = conn.execute(
            "SELECT callee_symbol_id FROM call_edges WHERE callee_name = 'greet'",
        ).fetchone()
        assert row["callee_symbol_id"] == greet.id

        conn.close()

    def test_unresolvable_keeps_null(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        project, _, _, _, _ = _seed_two_files(conn)

        resolve_call_edges(conn, project.id)

        row = conn.execute(
            "SELECT callee_symbol_id FROM call_edges WHERE callee_name = 'console.log'",
        ).fetchone()
        assert row["callee_symbol_id"] is None

        conn.close()

    def test_prefers_exported_over_private(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        project = insert_project(
            conn,
            Project(
                root_path="/test/p",
                name="p",
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        fa = insert_file(
            conn,
            File(
                project_id=project.id,
                path="a.ts",
                language="typescript",
                content_hash="ha",
            ),
        )
        fb = insert_file(
            conn,
            File(
                project_id=project.id,
                path="b.ts",
                language="typescript",
                content_hash="hb",
            ),
        )

        caller = insert_symbol(
            conn,
            Symbol(
                file_id=fa.id,
                name="main",
                kind="function",
                start_line=1,
                end_line=1,
                content_hash="h1",
            ),
        )
        insert_symbol(
            conn,
            Symbol(
                file_id=fa.id,
                name="util",
                kind="function",
                exported=False,
                start_line=1,
                end_line=1,
                content_hash="h2",
            ),
        )
        exported_util = insert_symbol(
            conn,
            Symbol(
                file_id=fb.id,
                name="util",
                kind="function",
                exported=True,
                start_line=1,
                end_line=1,
                content_hash="h3",
            ),
        )

        e = CallEdge(caller_symbol_id=caller.id, callee_name="util", line=1)
        insert_call_edge(conn, e)
        conn.commit()

        resolved = resolve_call_edges(conn, project.id)

        assert resolved == 1
        row = conn.execute("SELECT callee_symbol_id FROM call_edges").fetchone()
        assert row["callee_symbol_id"] == exported_util.id

        conn.close()

    def test_prefers_same_file_when_no_exported(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        project = insert_project(
            conn,
            Project(
                root_path="/test/p",
                name="p",
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        fa = insert_file(
            conn,
            File(
                project_id=project.id,
                path="a.ts",
                language="typescript",
                content_hash="ha",
            ),
        )
        fb = insert_file(
            conn,
            File(
                project_id=project.id,
                path="b.ts",
                language="typescript",
                content_hash="hb",
            ),
        )

        caller = insert_symbol(
            conn,
            Symbol(
                file_id=fa.id,
                name="main",
                kind="function",
                start_line=1,
                end_line=1,
                content_hash="h1",
            ),
        )
        same_file_util = insert_symbol(
            conn,
            Symbol(
                file_id=fa.id,
                name="util",
                kind="function",
                exported=False,
                start_line=1,
                end_line=1,
                content_hash="h2",
            ),
        )
        insert_symbol(
            conn,
            Symbol(
                file_id=fb.id,
                name="util",
                kind="function",
                exported=False,
                start_line=1,
                end_line=1,
                content_hash="h3",
            ),
        )

        e = CallEdge(caller_symbol_id=caller.id, callee_name="util", line=1)
        insert_call_edge(conn, e)
        conn.commit()

        resolved = resolve_call_edges(conn, project.id)
        assert resolved == 1

        row = conn.execute("SELECT callee_symbol_id FROM call_edges").fetchone()
        assert row["callee_symbol_id"] == same_file_util.id

        conn.close()

    def test_go_cross_file_resolves(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        project = insert_project(
            conn,
            Project(
                root_path="/test/go",
                name="go",
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        fmain = insert_file(
            conn,
            File(
                project_id=project.id,
                path="src/main.go",
                language="go",
                content_hash="hm",
            ),
        )
        futils = insert_file(
            conn,
            File(
                project_id=project.id,
                path="src/utils.go",
                language="go",
                content_hash="hu",
            ),
        )

        sym_main = insert_symbol(
            conn,
            Symbol(
                file_id=fmain.id,
                name="main",
                kind="function",
                start_line=1,
                end_line=3,
                content_hash="h1",
            ),
        )
        sym_greet = insert_symbol(
            conn,
            Symbol(
                file_id=futils.id,
                name="greet",
                kind="function",
                exported=False,
                start_line=1,
                end_line=3,
                content_hash="h2",
            ),
        )

        e = CallEdge(caller_symbol_id=sym_main.id, callee_name="greet", line=2)
        insert_call_edge(conn, e)
        conn.commit()

        resolved = resolve_call_edges(conn, project.id)
        assert resolved == 1

        row = conn.execute("SELECT callee_symbol_id FROM call_edges").fetchone()
        assert row["callee_symbol_id"] == sym_greet.id

        conn.close()

    def test_clears_dangling_references(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        project = insert_project(
            conn,
            Project(
                root_path="/test/p",
                name="p",
                created_at=datetime.now(UTC).isoformat(),
            ),
        )
        fa = insert_file(
            conn,
            File(
                project_id=project.id,
                path="a.ts",
                language="typescript",
                content_hash="ha",
            ),
        )

        caller = insert_symbol(
            conn,
            Symbol(
                file_id=fa.id,
                name="caller",
                kind="function",
                start_line=1,
                end_line=1,
                content_hash="h1",
            ),
        )
        callee = insert_symbol(
            conn,
            Symbol(
                file_id=fa.id,
                name="util",
                kind="function",
                start_line=1,
                end_line=1,
                content_hash="h2",
            ),
        )

        e = CallEdge(
            caller_symbol_id=caller.id,
            callee_name="util",
            callee_symbol_id=callee.id,
            line=1,
        )
        insert_call_edge(conn, e)
        conn.commit()

        conn.execute("DELETE FROM symbols WHERE id = ?", (callee.id,))
        conn.commit()

        row = conn.execute("SELECT callee_symbol_id FROM call_edges").fetchone()
        assert row["callee_symbol_id"] is None

        resolved = resolve_call_edges(conn, project.id)
        assert resolved == 0  # no matching symbol, stays NULL

        conn.close()
