from datetime import UTC, datetime

import pytest

from memos.core.db import (
    insert_call_edge,
    insert_file,
    insert_import,
    insert_project,
    insert_symbol,
)
from memos.core.models import CallEdge, File, Import, Project, Symbol
from memos.mcp.server import _inject_conn, mcp


@pytest.fixture
def seed(conn):
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

    file_b = File(
        project_id=project.id,
        path="src/b.ts",
        language="typescript",
        content_hash="bbb",
    )
    file_b = insert_file(conn, file_b)

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

    sym_helper = Symbol(
        file_id=file_a.id,
        name="helper",
        kind="function",
        signature="(x: number): number",
        start_line=7,
        end_line=10,
        exported=False,
        content_hash="h2",
    )
    sym_helper = insert_symbol(conn, sym_helper)

    sym_config = Symbol(
        file_id=file_b.id,
        name="Config",
        kind="class",
        signature="Config",
        start_line=1,
        end_line=15,
        exported=True,
        content_hash="h3",
    )
    sym_config = insert_symbol(conn, sym_config)

    sym_utils = Symbol(
        file_id=file_b.id,
        name="Utils",
        kind="class",
        signature="Utils",
        start_line=17,
        end_line=30,
        exported=True,
        content_hash="h4",
    )
    sym_utils = insert_symbol(conn, sym_utils)

    call_1 = CallEdge(
        caller_symbol_id=sym_main.id,
        callee_name="helper",
        line=3,
    )
    insert_call_edge(conn, call_1)

    call_2 = CallEdge(
        caller_symbol_id=sym_main.id,
        callee_name="Config",
        line=4,
    )
    insert_call_edge(conn, call_2)

    imp = Import(
        file_id=file_a.id,
        imported_path="./b",
    )
    insert_import(conn, imp)

    conn.commit()
    return project, file_a, file_b, sym_main, sym_helper, sym_config, sym_utils


@pytest.fixture
def mcp_conn(conn, seed):
    _inject_conn(conn, seed[0])
    yield
    _inject_conn(None, None)


@pytest.mark.anyio
async def test_find_symbol_tool(mcp_conn):
    results = await mcp.call_tool("find_symbol_tool", {"name": "main"})
    text = results[0][0].text
    assert '"name": "main"' in text
    assert '"kind": "function"' in text


@pytest.mark.anyio
async def test_find_symbol_tool_with_kind(mcp_conn):
    results = await mcp.call_tool(
        "find_symbol_tool",
        {"name": "Config", "kind": "class"},
    )
    text = results[0][0].text
    assert '"name": "Config"' in text
    assert '"kind": "class"' in text


@pytest.mark.anyio
async def test_find_symbol_tool_no_match(mcp_conn):
    results = await mcp.call_tool("find_symbol_tool", {"name": "Nonexistent"})
    text = results[0][0].text
    assert text == "[]"


@pytest.mark.anyio
async def test_find_calls_tool_callers(mcp_conn):
    results = await mcp.call_tool(
        "find_calls_tool",
        {"symbol_name": "Config", "direction": "callers"},
    )
    text = results[0][0].text
    assert '"callee_name": "Config"' in text
    assert '"caller_name": "main"' in text


@pytest.mark.anyio
async def test_find_calls_tool_callees(mcp_conn):
    results = await mcp.call_tool(
        "find_calls_tool",
        {"symbol_name": "main", "direction": "callees"},
    )
    text = results[0][0].text
    assert '"callee_name": "helper"' in text
    assert '"callee_name": "Config"' in text


@pytest.mark.anyio
async def test_find_calls_tool_invalid_direction(mcp_conn):
    results = await mcp.call_tool(
        "find_calls_tool",
        {"symbol_name": "main", "direction": "invalid"},
    )
    text = results[0][0].text
    assert '"error"' in text


@pytest.mark.anyio
async def test_get_module_tool(mcp_conn):
    results = await mcp.call_tool("get_module_tool", {"path": "src/a.ts"})
    text = results[0][0].text
    assert '"path": "src/a.ts"' in text
    assert '"name": "main"' in text


@pytest.mark.anyio
async def test_get_module_tool_not_found(mcp_conn):
    results = await mcp.call_tool("get_module_tool", {"path": "nonexistent.ts"})
    text = results[0][0].text
    assert '"error"' in text


@pytest.mark.anyio
async def test_list_files_tool(mcp_conn):
    results = await mcp.call_tool("list_files_tool", {})
    text = results[0][0].text
    assert '"path": "src/a.ts"' in text
    assert '"path": "src/b.ts"' in text


@pytest.mark.anyio
async def test_list_files_tool_filtered(mcp_conn):
    results = await mcp.call_tool("list_files_tool", {"path_filter": "a"})
    text = results[0][0].text
    assert '"path": "src/a.ts"' in text
    assert "src/b.ts" not in text


@pytest.mark.anyio
async def test_list_symbols_tool(mcp_conn):
    results = await mcp.call_tool("list_symbols_tool", {})
    text = results[0][0].text
    assert '"name": "main"' in text
    assert '"name": "Config"' in text


@pytest.mark.anyio
async def test_list_symbols_tool_filtered(mcp_conn):
    results = await mcp.call_tool(
        "list_symbols_tool",
        {"file_path": "src/b.ts"},
    )
    text = results[0][0].text
    assert '"name": "Config"' in text
    assert "main" not in text


@pytest.mark.anyio
async def test_list_symbols_tool_kind(mcp_conn):
    results = await mcp.call_tool(
        "list_symbols_tool",
        {"kind": "class"},
    )
    text = results[0][0].text
    assert '"name": "Config"' in text
    assert '"name": "Utils"' in text
    assert "main" not in text


@pytest.mark.anyio
async def test_list_projects_tool(mcp_conn):
    results = await mcp.call_tool("list_projects_tool", {})
    text = results[0][0].text
    assert '"root_path": "/test/proj"' in text
    assert '"files": 2' in text
    assert '"symbols": 4' in text


@pytest.mark.anyio
async def test_tool_registration(mcp_conn):
    results = await mcp.list_tools()
    names = [t.name for t in results]
    assert "find_symbol_tool" in names
    assert "find_calls_tool" in names
    assert "get_module_tool" in names
    assert "semantic_search_tool" in names
    assert "list_files_tool" in names
    assert "list_symbols_tool" in names
    assert "list_projects_tool" in names
    assert "memory_add_note" in names
    assert "get_memories" in names


@pytest.mark.anyio
async def test_memory_add_note(mcp_conn):
    results = await mcp.call_tool(
        "memory_add_note",
        {"content": "test memory", "scope_type": "project", "kind": "note"},
    )
    text = results[0][0].text
    assert '"content": "test memory"' in text
    assert '"scope_type": "project"' in text
    assert '"source": "agent"' in text
    assert '"id"' in text


@pytest.mark.anyio
async def test_get_memories(mcp_conn):
    await mcp.call_tool(
        "memory_add_note",
        {"content": "mem 1", "scope_type": "project"},
    )
    await mcp.call_tool(
        "memory_add_note",
        {"content": "mem 2", "scope_type": "file", "scope_id": 1},
    )
    results = await mcp.call_tool("get_memories", {})
    text = results[0][0].text
    assert '"content": "mem 1"' in text
    assert '"content": "mem 2"' in text
