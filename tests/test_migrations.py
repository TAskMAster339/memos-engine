from memos.core.db import get_connection, run_migrations


def test_migrations_idempotent():
    conn = get_connection(":memory:")
    run_migrations(conn)

    tables_before = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall()
    }

    v1 = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    run_migrations(conn)

    tables_after = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'",
        ).fetchall()
    }

    v2 = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0]

    assert tables_before == tables_after
    assert v1 == v2 == 3
    conn.close()


def test_fresh_database_gets_schema():
    conn = get_connection(":memory:")
    run_migrations(conn)

    row_count = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    assert row_count == 3

    conn.close()
