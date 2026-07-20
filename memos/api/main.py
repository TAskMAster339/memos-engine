import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from memos.api.schemas import (
    CallEdgeResponse,
    ModuleResponse,
    SemanticSearchResponse,
    SymbolResponse,
)
from memos.core.db import get_connection, get_project_by_root, run_migrations
from memos.query.core import find_calls_by_id, find_symbol, get_module, semantic_search


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
