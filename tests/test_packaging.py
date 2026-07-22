from memos.core.db import MIGRATIONS_DIR


def test_migrations_directory_is_not_empty():
    sql_files = list(MIGRATIONS_DIR.glob("*.sql"))
    assert len(sql_files) >= 4, "migrations missing — check wheel packaging"
