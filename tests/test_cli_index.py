import os
import shutil
import tempfile
from pathlib import Path

from memos.core.db import get_connection, run_migrations
from memos.indexer.typescript import TypeScriptIndexer
from memos.indexer.diff import compute_file_hash
from memos.cli.main import find_files, get_or_create_project, index_file

FIXTURE = Path(__file__).parent / "fixtures" / "typescript_mini"


def test_find_files():
    root = str(FIXTURE)
    files = find_files(root)
    rels = {r for _, r in files}
    assert "src/index.ts" in rels
    assert "src/utils.ts" in rels
    assert "src/types.ts" in rels


def test_index_file_adds_symbols():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(FIXTURE))
    src_path = str(FIXTURE / "src" / "utils.ts")

    indexer = TypeScriptIndexer()
    changed = index_file(conn, project, src_path, "src/utils.ts", indexer, full=True)

    assert changed is True

    rows = conn.execute(
        "SELECT name, kind, exported FROM symbols ORDER BY name"
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "greet" in names
    assert "helper" in names

    greet = [r for r in rows if r["name"] == "greet"][0]
    assert greet["exported"] == 1

    helper = [r for r in rows if r["name"] == "helper"][0]
    assert helper["exported"] == 0

    conn.close()


def test_index_file_skips_unchanged():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(FIXTURE))
    src_path = str(FIXTURE / "src" / "types.ts")
    indexer = TypeScriptIndexer()

    index_file(conn, project, src_path, "src/types.ts", indexer, full=True)

    # Second pass without --full should skip
    changed = index_file(conn, project, src_path, "src/types.ts", indexer, full=False)
    assert changed is False

    conn.close()


def test_index_full_project():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(FIXTURE))

    indexer_ts = TypeScriptIndexer()
    for full, rel in find_files(str(FIXTURE)):
        ext = os.path.splitext(full)[1]
        if ext == ".ts":
            index_file(conn, project, full, rel, indexer_ts, full=True)

    symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    assert symbol_count == 6

    call_count = conn.execute("SELECT COUNT(*) FROM call_edges").fetchone()[0]
    assert call_count >= 1

    import_count = conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
    assert import_count == 3

    conn.close()
