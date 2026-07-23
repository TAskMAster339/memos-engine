from datetime import UTC, datetime

from memos.core.db import (
    get_connection,
    insert_file,
    insert_import,
    insert_project,
    resolve_imports,
    run_migrations,
)
from memos.core.models import File, Import, Project


def _count_queries(conn):
    counter = [0]

    def count(_):
        counter[0] += 1

    conn.set_trace_callback(count)
    return counter


def test_resolve_imports_does_not_n_plus_one_on_reads():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = Project(
        root_path="/test/p",
        name="p",
        created_at=datetime.now(UTC).isoformat(),
    )
    project = insert_project(conn, project)

    files = []
    for i in range(2):
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

    # Seed 50 imports: half resolvable (./utils), half not (lodash)
    for _i in range(25):
        insert_import(
            conn,
            Import(
                file_id=files[0].id,
                imported_path="./utils",
            ),
        )
        insert_import(
            conn,
            Import(
                file_id=files[0].id,
                imported_path="lodash",
            ),
        )

    # Create a target file for ./utils imports to resolve to
    insert_file(
        conn,
        File(
            project_id=project.id,
            path="src/utils.ts",
            language="typescript",
            content_hash="hutils",
        ),
    )

    conn.commit()

    counter = _count_queries(conn)
    resolved = resolve_imports(conn, project.id)
    conn.set_trace_callback(None)

    assert resolved == 25  # all ./utils imports resolve

    # Batch pattern: 1 cleanup + 1 load files + 1 select imports + 25 executemany = 28
    # Allow margin for tiny overhead
    assert counter[0] < 35, (
        f"resolve_imports issued {counter[0]} queries, "
        f"expected < 35 (would be ~80 with N+1)"
    )

    conn.close()
