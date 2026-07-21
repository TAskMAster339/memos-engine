from pathlib import Path

from memos.cli.main import (
    EXTENSION_INDEXERS,
    find_files,
    get_or_create_project,
    index_file,
)
from memos.core.db import get_connection, resolve_call_edges, run_migrations
from memos.indexer.typescript import TypeScriptIndexer

TS_FIXTURE = Path(__file__).parent / "fixtures" / "typescript_mini"
GO_FIXTURE = Path(__file__).parent / "fixtures" / "go_mini"
PY_FIXTURE = Path(__file__).parent / "fixtures" / "python_mini"


def test_find_files():
    root = str(TS_FIXTURE)
    files = find_files(root)
    rels = {r for _, r in files}
    assert "src/index.ts" in rels
    assert "src/utils.ts" in rels
    assert "src/types.ts" in rels


def test_find_go_files():
    root = str(GO_FIXTURE)
    files = find_files(root)
    rels = {r for _, r in files}
    assert "src/main.go" in rels
    assert "src/utils.go" in rels
    assert "src/types.go" in rels


def test_index_file_adds_symbols():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(TS_FIXTURE))
    src_path = str(TS_FIXTURE / "src" / "utils.ts")

    indexer = TypeScriptIndexer()
    changed = index_file(conn, project, src_path, "src/utils.ts", indexer, full=True)

    assert changed is True

    rows = conn.execute(
        "SELECT name, kind, exported FROM symbols ORDER BY name",
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

    project = get_or_create_project(conn, str(TS_FIXTURE))
    src_path = str(TS_FIXTURE / "src" / "types.ts")
    indexer = TypeScriptIndexer()

    index_file(conn, project, src_path, "src/types.ts", indexer, full=True)

    changed = index_file(conn, project, src_path, "src/types.ts", indexer, full=False)
    assert changed is False

    conn.close()


def test_index_go_file():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(GO_FIXTURE))
    src_path = str(GO_FIXTURE / "src" / "utils.go")

    indexer = EXTENSION_INDEXERS[".go"]
    changed = index_file(conn, project, src_path, "src/utils.go", indexer, full=True)

    assert changed is True

    rows = conn.execute(
        "SELECT name, kind, exported FROM symbols ORDER BY name",
    ).fetchall()
    names = [r["name"] for r in rows]
    assert "defaultName" in names
    assert "greet" in names
    assert "GreetPublic" in names

    greet = [r for r in rows if r["name"] == "greet"][0]
    assert greet["exported"] == 0

    pub = [r for r in rows if r["name"] == "GreetPublic"][0]
    assert pub["exported"] == 1

    conn.close()


def test_find_py_files():
    root = str(PY_FIXTURE)
    files = find_files(root)
    rels = {r for _, r in files}
    assert "src/utils.py" in rels
    assert "src/main.py" in rels
    assert "src/types.py" in rels


def test_index_py_project():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(PY_FIXTURE))

    for full, rel in find_files(str(PY_FIXTURE)):
        ext = Path(full).suffix
        if ext == ".py":
            indexer = EXTENSION_INDEXERS.get(ext)
            index_file(conn, project, full, rel, indexer, full=True)

    symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    assert symbol_count == 8

    call_count = conn.execute("SELECT COUNT(*) FROM call_edges").fetchone()[0]
    assert call_count >= 1

    import_count = conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
    assert import_count == 1

    conn.close()


def test_index_py_project_resolves_calls():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(PY_FIXTURE))
    for full, rel in find_files(str(PY_FIXTURE)):
        ext = Path(full).suffix
        if ext == ".py":
            indexer = EXTENSION_INDEXERS.get(ext)
            index_file(conn, project, full, rel, indexer, full=True)

    resolved = resolve_call_edges(conn, project.id)

    assert resolved >= 1

    row = conn.execute(
        "SELECT callee_symbol_id FROM call_edges WHERE callee_name = 'greet'",
    ).fetchone()
    assert row is not None
    assert row["callee_symbol_id"] is not None

    conn.close()


def test_index_py_skip_unchanged():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(PY_FIXTURE))
    src_path = str(PY_FIXTURE / "src" / "types.py")
    indexer = EXTENSION_INDEXERS[".py"]

    index_file(conn, project, src_path, "src/types.py", indexer, full=True)
    changed = index_file(conn, project, src_path, "src/types.py", indexer, full=False)
    assert changed is False

    conn.close()


def test_index_go_skip_unchanged():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(GO_FIXTURE))
    src_path = str(GO_FIXTURE / "src" / "types.go")
    indexer = EXTENSION_INDEXERS[".go"]

    index_file(conn, project, src_path, "src/types.go", indexer, full=True)
    changed = index_file(conn, project, src_path, "src/types.go", indexer, full=False)
    assert changed is False

    conn.close()


def test_index_ts_project():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(TS_FIXTURE))

    for full, rel in find_files(str(TS_FIXTURE)):
        ext = Path(full).suffix
        if ext == ".ts":
            indexer = EXTENSION_INDEXERS.get(ext)
            index_file(conn, project, full, rel, indexer, full=True)

    symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    assert symbol_count == 6

    call_count = conn.execute("SELECT COUNT(*) FROM call_edges").fetchone()[0]
    assert call_count >= 1

    import_count = conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
    assert import_count == 3

    conn.close()


def test_index_ts_project_resolves_calls():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(TS_FIXTURE))
    for full, rel in find_files(str(TS_FIXTURE)):
        ext = Path(full).suffix
        if ext == ".ts":
            indexer = EXTENSION_INDEXERS.get(ext)
            index_file(conn, project, full, rel, indexer, full=True)

    resolved = resolve_call_edges(conn, project.id)

    assert resolved >= 1

    row = conn.execute(
        "SELECT callee_symbol_id FROM call_edges WHERE callee_name = 'greet'",
    ).fetchone()
    assert row is not None
    assert row["callee_symbol_id"] is not None

    conn.close()


def test_index_go_project():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(GO_FIXTURE))

    for full, rel in find_files(str(GO_FIXTURE)):
        ext = Path(full).suffix
        if ext == ".go":
            indexer = EXTENSION_INDEXERS.get(ext)
            index_file(conn, project, full, rel, indexer, full=True)

    symbol_count = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    assert symbol_count == 7

    call_count = conn.execute("SELECT COUNT(*) FROM call_edges").fetchone()[0]
    assert call_count >= 1

    import_count = conn.execute("SELECT COUNT(*) FROM imports").fetchone()[0]
    assert import_count == 3

    conn.close()


def test_index_go_project_resolves_calls():
    conn = get_connection(":memory:")
    run_migrations(conn)

    project = get_or_create_project(conn, str(GO_FIXTURE))
    for full, rel in find_files(str(GO_FIXTURE)):
        ext = Path(full).suffix
        if ext == ".go":
            indexer = EXTENSION_INDEXERS.get(ext)
            index_file(conn, project, full, rel, indexer, full=True)

    resolved = resolve_call_edges(conn, project.id)

    assert resolved >= 2

    row = conn.execute(
        "SELECT callee_symbol_id FROM call_edges WHERE callee_name = 'greet'",
    ).fetchone()
    assert row is not None
    assert row["callee_symbol_id"] is not None

    conn.close()
