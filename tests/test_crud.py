from memos.core.db import (
    delete_file,
    find_symbols_by_name,
    get_calls_for_caller,
    get_file,
    get_file_by_path,
    get_imports_for_file,
    get_memory_entries_for_scope,
    get_project,
    get_symbols_for_file,
    insert_call_edge,
    insert_file,
    insert_import,
    insert_memory_entry,
    insert_project,
    insert_symbol,
)
from memos.core.models import CallEdge, File, Import, MemoryEntry, Project, Symbol


def test_project_crud(conn):
    p = Project(root_path="/test", name="testproj", created_at="2025-01-01T00:00:00")
    p2 = insert_project(conn, p)
    assert p2.id is not None
    assert p2.root_path == "/test"

    fetched = get_project(conn, p2.id)
    assert fetched is not None
    assert fetched.name == "testproj"


def test_file_crud(conn):
    p = insert_project(conn, Project(root_path="/test", name="tp", created_at="now"))

    f = File(
        project_id=p.id, path="src/main.ts", language="typescript",
        content_hash="abc123", mtime=1000.0,
    )
    f2 = insert_file(conn, f)
    assert f2.id is not None

    by_id = get_file(conn, f2.id)
    assert by_id is not None
    assert by_id.path == "src/main.ts"

    by_path = get_file_by_path(conn, p.id, "src/main.ts")
    assert by_path is not None
    assert by_path.content_hash == "abc123"


def test_symbol_crud(conn):
    p = insert_project(conn, Project(root_path="/test", name="tp", created_at="now"))
    f = insert_file(conn, File(
        project_id=p.id, path="lib.ts", language="typescript", content_hash="def",
    ))

    s = Symbol(
        file_id=f.id, name="hello", kind="function",
        start_line=1, end_line=5, exported=True, content_hash="hash1",
        signature="hello(): void",
    )
    s2 = insert_symbol(conn, s)
    assert s2.id is not None

    child = Symbol(
        file_id=f.id, parent_symbol_id=s2.id, name="inner", kind="function",
        start_line=2, end_line=3, exported=False, content_hash="hash2",
    )
    child2 = insert_symbol(conn, child)
    assert child2.parent_symbol_id == s2.id

    found = find_symbols_by_name(conn, "hello")
    assert len(found) == 1
    assert found[0].exported is True

    file_syms = get_symbols_for_file(conn, f.id)
    assert len(file_syms) == 2


def test_call_edge_crud(conn):
    p = insert_project(conn, Project(root_path="/test", name="tp", created_at="now"))
    f = insert_file(conn, File(
        project_id=p.id, path="a.ts", language="typescript", content_hash="h1",
    ))
    caller = insert_symbol(conn, Symbol(
        file_id=f.id, name="caller", kind="function",
        start_line=1, end_line=3, exported=True, content_hash="hc",
    ))
    callee = insert_symbol(conn, Symbol(
        file_id=f.id, name="callee", kind="function",
        start_line=5, end_line=7, exported=True, content_hash="hl",
    ))

    edge = CallEdge(
        caller_symbol_id=caller.id, callee_name="callee",
        callee_symbol_id=callee.id, line=2,
    )
    e2 = insert_call_edge(conn, edge)
    assert e2.id is not None

    edges = get_calls_for_caller(conn, caller.id)
    assert len(edges) == 1
    assert edges[0].callee_name == "callee"


def test_import_crud(conn):
    p = insert_project(conn, Project(root_path="/test", name="tp", created_at="now"))
    f = insert_file(conn, File(
        project_id=p.id, path="main.ts", language="typescript", content_hash="h1",
    ))
    f2 = insert_file(conn, File(
        project_id=p.id, path="utils.ts", language="typescript", content_hash="h2",
    ))

    imp = Import(file_id=f.id, imported_path="./utils", resolved_file_id=f2.id)
    imp2 = insert_import(conn, imp)
    assert imp2.id is not None

    imports = get_imports_for_file(conn, f.id)
    assert len(imports) == 1
    assert imports[0].imported_path == "./utils"


def test_memory_entry_crud(conn):
    p = insert_project(conn, Project(root_path="/test", name="tp", created_at="now"))
    f = insert_file(conn, File(
        project_id=p.id, path="x.ts", language="typescript", content_hash="h",
    ))
    sym = insert_symbol(conn, Symbol(
        file_id=f.id, name="foo", kind="function",
        start_line=1, end_line=2, exported=False, content_hash="hsym",
    ))

    entry = MemoryEntry(
        project_id=p.id, scope_type="symbol", scope_id=sym.id,
        kind="summary", content="does foo", source="llm",
        source_hash="hsym", created_at="now",
    )
    e2 = insert_memory_entry(conn, entry)
    assert e2.id is not None

    by_scope = get_memory_entries_for_scope(conn, "symbol", sym.id)
    assert len(by_scope) == 1
    assert by_scope[0].kind == "summary"

    project_entries = get_memory_entries_for_scope(conn, "project")
    assert len(project_entries) == 0


def test_cascade_delete_file_removes_symbols(conn):
    p = insert_project(conn, Project(root_path="/test", name="tp", created_at="now"))
    f = insert_file(conn, File(
        project_id=p.id, path="del.ts", language="typescript", content_hash="del",
    ))
    sym = insert_symbol(conn, Symbol(
        file_id=f.id, name="goner", kind="function",
        start_line=1, end_line=2, exported=False, content_hash="hg",
    ))
    sym_id = sym.id

    delete_file(conn, f.id)

    assert get_file(conn, f.id) is None
    assert len(find_symbols_by_name(conn, "goner")) == 0
    assert len(get_symbols_for_file(conn, f.id)) == 0

    remaining = conn.execute(
        "SELECT COUNT(*) FROM symbols WHERE id = ?", (sym_id,)
    ).fetchone()[0]
    assert remaining == 0
