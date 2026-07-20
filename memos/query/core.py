from typing import Any


def find_symbol(
    conn,
    name: str,
    kind: str | None = None,
    file_path: str | None = None,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    clauses = ["s.name = ?"]
    params: list[Any] = [name]

    if kind is not None:
        clauses.append("s.kind = ?")
        params.append(kind)

    sql = """
        SELECT s.*, f.path AS file_path, f.language AS file_language
        FROM symbols s
        JOIN files f ON f.id = s.file_id
    """
    if file_path is not None or project_id is not None:
        clauses.append("1=1")
        if file_path is not None:
            clauses.append("f.path = ?")
            params.append(file_path)
        if project_id is not None:
            clauses.append("f.project_id = ?")
            params.append(project_id)

    sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY s.file_id, s.start_line"

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def find_calls(
    conn,
    symbol_name: str,
    direction: str = "callers",
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    if direction == "callers":
        sql = """
            SELECT
                caller.name AS caller_name,
                caller.kind AS caller_kind,
                caller.id AS caller_symbol_id,
                edge.callee_name,
                edge.line,
                cf.path AS file,
                cf.id AS file_id
            FROM call_edges edge
            JOIN symbols caller ON caller.id = edge.caller_symbol_id
            JOIN files cf ON cf.id = caller.file_id
            WHERE edge.callee_name = ?
        """
        params: list[Any] = [symbol_name]
        if project_id is not None:
            sql += " AND cf.project_id = ?"
            params.append(project_id)
        sql += " ORDER BY cf.path, edge.line"
    elif direction == "callees":
        sql = """
            SELECT
                caller.name AS caller_name,
                caller.kind AS caller_kind,
                caller.id AS caller_symbol_id,
                edge.callee_name,
                COALESCE(callee.name, '') AS callee_resolved_name,
                edge.line,
                cf.path AS file,
                cf.id AS file_id
            FROM call_edges edge
            JOIN symbols caller ON caller.id = edge.caller_symbol_id
            JOIN files cf ON cf.id = caller.file_id
            LEFT JOIN symbols callee ON callee.id = edge.callee_symbol_id
            WHERE caller.name = ?
        """
        params = [symbol_name]
        if project_id is not None:
            sql += " AND cf.project_id = ?"
            params.append(project_id)
        sql += " ORDER BY cf.path, edge.line"
    else:
        raise ValueError(
            f"invalid direction: {direction!r} (expected 'callers' or 'callees')",
        )

    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def find_calls_by_id(
    conn,
    symbol_id: int,
    direction: str = "callers",
) -> list[dict[str, Any]]:
    if direction == "callers":
        sql = """
            SELECT
                caller.name AS caller_name,
                caller.kind AS caller_kind,
                caller.id AS caller_symbol_id,
                edge.callee_name,
                edge.line,
                cf.path AS file,
                cf.id AS file_id
            FROM call_edges edge
            JOIN symbols caller ON caller.id = edge.caller_symbol_id
            JOIN files cf ON cf.id = caller.file_id
            WHERE edge.callee_symbol_id = ?
            ORDER BY cf.path, edge.line
        """
    elif direction == "callees":
        sql = """
            SELECT
                caller.name AS caller_name,
                caller.kind AS caller_kind,
                caller.id AS caller_symbol_id,
                edge.callee_name,
                COALESCE(callee.name, '') AS callee_resolved_name,
                edge.line,
                cf.path AS file,
                cf.id AS file_id
            FROM call_edges edge
            JOIN symbols caller ON caller.id = edge.caller_symbol_id
            JOIN files cf ON cf.id = caller.file_id
            LEFT JOIN symbols callee ON callee.id = edge.callee_symbol_id
            WHERE caller.id = ?
            ORDER BY cf.path, edge.line
        """
    else:
        raise ValueError(
            f"invalid direction: {direction!r} (expected 'callers' or 'callees')",
        )

    rows = conn.execute(sql, [symbol_id]).fetchall()
    return [dict(r) for r in rows]


def semantic_search(
    conn,
    query: str,
    top_k: int = 10,
    project_id: int | None = None,
) -> list[dict[str, Any]]:
    from memos.search.embeddings import FastEmbedEmbedding  # noqa: PLC0415
    from memos.search.sqlite_vec_store import SqliteVecStore  # noqa: PLC0415

    embedder = FastEmbedEmbedding()
    store = SqliteVecStore(conn)

    query_vec = embedder.embed_query(query)
    results = store.search(query_vec, top_k=top_k)

    if not results:
        return []

    symbol_ids = [sid for sid, _ in results]
    score_map = dict(results)
    placeholders = ",".join("?" for _ in symbol_ids)

    sql = f"""
        SELECT s.*, f.path AS file_path, f.language AS file_language
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE s.id IN ({placeholders})
    """
    params: list[Any] = symbol_ids
    if project_id is not None:
        sql += " AND f.project_id = ?"
        params.append(project_id)

    rows = conn.execute(sql, params).fetchall()
    out = [dict(r) for r in rows]
    for item in out:
        item["score"] = score_map[item["id"]]
    out.sort(key=lambda x: x["score"])
    return out


def list_files(
    conn,
    project_id: int,
    path_filter: str | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM files WHERE project_id = ?"
    params: list[Any] = [project_id]
    if path_filter is not None:
        sql += " AND path LIKE ?"
        params.append(f"%{path_filter}%")
    sql += " ORDER BY path"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def list_symbols(
    conn,
    project_id: int,
    file_path: str | None = None,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    sql = """
        SELECT s.*, f.path AS file_path, f.language AS file_language
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE f.project_id = ?
    """
    params: list[Any] = [project_id]
    if file_path is not None:
        sql += " AND f.path = ?"
        params.append(file_path)
    if kind is not None:
        sql += " AND s.kind = ?"
        params.append(kind)
    sql += " ORDER BY f.path, s.start_line"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def get_module(conn, file_path: str, project_id: int) -> dict[str, Any]:
    file_row = conn.execute(
        "SELECT * FROM files WHERE project_id = ? AND path = ?",
        (project_id, file_path),
    ).fetchone()
    if file_row is None:
        return {"error": f"file not found: {file_path}"}

    file_dict = dict(file_row)

    symbols = conn.execute(
        "SELECT * FROM symbols WHERE file_id = ? ORDER BY start_line",
        (file_dict["id"],),
    ).fetchall()
    symbol_list = [dict(s) for s in symbols]

    symbol_ids = [s["id"] for s in symbol_list]
    calls_list = []
    if symbol_ids:
        placeholders = ",".join("?" for _ in symbol_ids)
        call_rows = conn.execute(
            f"""
                SELECT
                    caller.name AS caller_name,
                    caller.kind AS caller_kind,
                    edge.callee_name,
                    COALESCE(callee.name, '') AS callee_resolved_name,
                    edge.line,
                    edge.id AS edge_id
                FROM call_edges edge
                JOIN symbols caller ON caller.id = edge.caller_symbol_id
                LEFT JOIN symbols callee ON callee.id = edge.callee_symbol_id
                WHERE edge.caller_symbol_id IN ({placeholders})
                ORDER BY edge.line
            """,
            symbol_ids,
        ).fetchall()
        calls_list = [dict(r) for r in call_rows]

    import_rows = conn.execute(
        "SELECT * FROM imports WHERE file_id = ?",
        (file_dict["id"],),
    ).fetchall()
    imports_list = [dict(r) for r in import_rows]

    return {
        "file": file_dict,
        "symbols": symbol_list,
        "calls": calls_list,
        "imports": imports_list,
    }
