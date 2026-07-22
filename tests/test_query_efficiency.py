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


def _count_queries(conn):
    counter = [0]

    def count(_):
        counter[0] += 1

    conn.set_trace_callback(count)
    return counter


def test_resolve_call_edges_does_not_n_plus_one_on_reads():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = Project(
        root_path="/test/p",
        name="p",
        created_at=datetime.now(UTC).isoformat(),
    )
    project = insert_project(conn, project)

    files = []
    for i in range(3):
        f = insert_file(
            conn,
            File(
                project_id=project.id,
                path=f"src/file{i}.ts",
                language="typescript",
                content_hash=f"h{i}",
            ),
        )
        files.append(f)

    # Seed 50 symbols across 3 files (mix of exported and private)
    for i in range(50):
        insert_symbol(
            conn,
            Symbol(
                file_id=files[i % 3].id,
                name=f"func{i}" if i < 30 else f"helper{i}",
                kind="function",
                start_line=1,
                end_line=5,
                exported=1 if i < 30 else 0,
                content_hash=f"sym{i}",
            ),
        )

    # Seed 50 call edges — some matching, some not (unresolvable)
    for i in range(50):
        caller_sym_id = i + 1  # symbol IDs are 1..50
        callee = f"func{i}" if i < 30 else f"nonexistent{i}"
        insert_call_edge(
            conn,
            CallEdge(
                caller_symbol_id=caller_sym_id,
                callee_name=callee,
                line=1,
            ),
        )

    conn.commit()

    counter = _count_queries(conn)
    resolved = resolve_call_edges(conn, project.id)
    conn.set_trace_callback(None)

    assert resolved >= 30  # at least the 30 valid func names resolve
    # Allow up to 35: 1 cleanup + 1 edge SELECT + 1 batch SELECT + ~30 executemany
    # Before the batch fix this was ~80 (50 SELECTs + 30 executemany)
    assert counter[0] < 40, (
        f"resolve_call_edges issued {counter[0]} queries, "
        f"expected < 40 (would be ~80 with N+1)"
    )

    conn.close()
