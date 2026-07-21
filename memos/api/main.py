import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from memos.api.schemas import (
    CallEdgeResponse,
    ContextResponse,
    DeadImportsResponse,
    DependencyGraphResponse,
    DiffImpactResponse,
    ImportCyclesResponse,
    MemoryCreateRequest,
    MemoryEntryResponse,
    ModuleResponse,
    RenameImpactResponse,
    SemanticSearchResponse,
    SymbolResponse,
    UnusedSymbolsResponse,
)
from memos.core.db import get_connection, get_project_by_root, run_migrations
from memos.query.core import (
    add_memory_entry,
    find_calls_by_id,
    find_dead_imports,
    find_import_cycles,
    find_symbol,
    find_unused_symbols,
    get_context,
    get_dependency_graph,
    get_diff_impact,
    get_memory_entries,
    get_module,
    get_rename_impact,
    semantic_search,
)


class SearchRequest(BaseModel):
    query: str
    top_k: int = 10


PROJECT_PATH: str = os.environ.get("MEMOS_PROJECT_PATH", ".")


app = FastAPI(title="Memory OS API")


def _get_conn_and_project():
    root = str(Path(PROJECT_PATH).resolve())
    db_path = str(Path(root) / ".memos" / "memory.db")
    if not Path(db_path).exists():
        raise HTTPException(
            status_code=404,
            detail=f"no .memos/memory.db found at {root} — run 'memos index' first",
        )
    conn = get_connection(db_path)
    run_migrations(conn)
    project = get_project_by_root(conn, root)
    if project is None:
        conn.close()
        raise HTTPException(status_code=404, detail=f"no project found for {root}")
    return conn, project


@app.get("/symbols", response_model=list[SymbolResponse])
def api_find_symbol(
    name: str = Query(...),
    kind: str | None = Query(None),
    file: str | None = Query(None),
):
    conn, project = _get_conn_and_project()
    try:
        return find_symbol(
            conn,
            name,
            kind=kind,
            file_path=file,
            project_id=project.id,
        )
    finally:
        conn.close()


@app.get("/symbols/{symbol_id}/context", response_model=ContextResponse)
def api_get_context(symbol_id: int):
    conn, _ = _get_conn_and_project()
    try:
        result = get_context(conn, symbol_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    finally:
        conn.close()


@app.get("/symbols/{symbol_id}/rename-impact", response_model=RenameImpactResponse)
def api_rename_impact(symbol_id: int):
    conn, _ = _get_conn_and_project()
    try:
        result = get_rename_impact(conn, symbol_id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    finally:
        conn.close()


@app.get("/dependency-graph", response_model=DependencyGraphResponse)
def api_dependency_graph():
    conn, project = _get_conn_and_project()
    try:
        return get_dependency_graph(conn, project.id)
    finally:
        conn.close()


@app.get("/import-cycles", response_model=ImportCyclesResponse)
def api_import_cycles():
    conn, project = _get_conn_and_project()
    try:
        return {"cycles": find_import_cycles(conn, project.id)}
    finally:
        conn.close()


@app.get("/unused-symbols", response_model=UnusedSymbolsResponse)
def api_unused_symbols():
    conn, project = _get_conn_and_project()
    try:
        return {"symbols": find_unused_symbols(conn, project.id)}
    finally:
        conn.close()


@app.get("/dead-imports", response_model=DeadImportsResponse)
def api_dead_imports():
    conn, project = _get_conn_and_project()
    try:
        return {"imports": find_dead_imports(conn, project.id)}
    finally:
        conn.close()


@app.get("/modules/{path:path}/diff-impact", response_model=DiffImpactResponse)
def api_diff_impact(path: str):
    conn, project = _get_conn_and_project()
    try:
        result = get_diff_impact(conn, path, project.id)
        if "error" in result:
            raise HTTPException(status_code=404, detail=result["error"])
        return result
    finally:
        conn.close()


@app.get("/symbols/{symbol_id}/calls", response_model=list[CallEdgeResponse])
def api_find_calls_by_id(
    symbol_id: int,
    direction: str = Query("callers", pattern="^(callers|callees)$"),
):
    conn, _ = _get_conn_and_project()
    try:
        return find_calls_by_id(conn, symbol_id, direction=direction)
    finally:
        conn.close()


@app.get("/modules/{path:path}", response_model=ModuleResponse)
def api_get_module(path: str):
    conn, project = _get_conn_and_project()
    try:
        results = get_module(conn, path, project.id)
        if "error" in results:
            raise HTTPException(status_code=404, detail=results["error"])
        return results
    finally:
        conn.close()


@app.post("/search/semantic", response_model=SemanticSearchResponse)
def api_search_semantic(body: SearchRequest):
    conn, project = _get_conn_and_project()
    try:
        results = semantic_search(
            conn,
            body.query,
            top_k=body.top_k,
            project_id=project.id,
        )
        return {"query": body.query, "top_k": body.top_k, "results": results}
    finally:
        conn.close()


@app.post("/memories", response_model=MemoryEntryResponse)
def api_create_memory(body: MemoryCreateRequest):
    conn, project = _get_conn_and_project()
    try:
        result = add_memory_entry(
            conn,
            project.id,
            body.content,
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            kind=body.kind,
            source=body.source,
        )
        conn.commit()
        return result
    finally:
        conn.close()


@app.get("/memories", response_model=list[MemoryEntryResponse])
def api_get_memories(
    scope_type: str | None = Query(None),
    scope_id: int | None = Query(None),
):
    conn, project = _get_conn_and_project()
    try:
        return get_memory_entries(
            conn,
            project.id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
    finally:
        conn.close()
