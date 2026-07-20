def test_all_tables_exist(conn):
    tables = {
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    expected = {
        "schema_version", "projects", "files", "symbols",
        "call_edges", "imports", "memory_entries",
    }
    assert tables >= expected, f"Missing tables: {expected - tables}"


def test_schema_version(conn):
    version = conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()[0]
    assert version == 1
