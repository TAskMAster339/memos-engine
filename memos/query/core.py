import hashlib
from datetime import UTC, datetime
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


def add_memory_entry(  # noqa: PLR0913
    conn,
    project_id: int,
    content: str,
    scope_type: str = "project",
    scope_id: int | None = None,
    kind: str = "note",
    source: str = "agent",
    source_hash: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC).isoformat()
    if source_hash is None:
        source_hash = hashlib.sha256(content.encode()).hexdigest()
    cur = conn.execute(
        "INSERT INTO memory_entries "
        "(project_id, scope_type, scope_id, kind, content, "
        "source, source_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (project_id, scope_type, scope_id, kind, content, source, source_hash, now),
    )
    row = conn.execute(
        "SELECT * FROM memory_entries WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return dict(row)


def get_memory_entries(
    conn,
    project_id: int,
    scope_type: str | None = None,
    scope_id: int | None = None,
) -> list[dict[str, Any]]:
    sql = "SELECT * FROM memory_entries WHERE project_id = ?"
    params: list[Any] = [project_id]
    if scope_type is not None and scope_id is not None:
        sql += " AND scope_type = ? AND scope_id = ?"
        params.extend([scope_type, scope_id])
    elif scope_type is not None:
        sql += " AND scope_type = ? AND scope_id IS NULL"
        params.append(scope_type)
    sql += " ORDER BY created_at DESC"
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


CURRENT_PROMPT_VERSION = "1"


CURRENT_PROMPT_VERSION = "1"


def get_or_generate_summary(
    conn,
    symbol_id: int,
    content_hash: str,
) -> dict[str, Any]:
    summary = conn.execute(
        "SELECT * FROM memory_entries "
        "WHERE scope_type = 'symbol' AND scope_id = ? "
        "AND kind = 'summary' AND source_hash = ? "
        "AND (prompt_version IS NULL OR prompt_version = ?)",
        (symbol_id, content_hash, CURRENT_PROMPT_VERSION),
    ).fetchone()

    if summary is not None:
        return {"summary": dict(summary), "generation_context": None}

    row = conn.execute(
        "SELECT s.*, f.path AS file_path, f.language AS file_language, "
        "f.project_id AS project_id "
        "FROM symbols s JOIN files f ON f.id = s.file_id "
        "WHERE s.id = ?",
        (symbol_id,),
    ).fetchone()
    if row is None:
        return {"summary": None, "generation_context": None}

    sym = dict(row)
    callers = find_calls_by_id(conn, symbol_id, direction="callers")
    return {
        "summary": None,
        "generation_context": {
            "symbol_id": sym["id"],
            "name": sym["name"],
            "kind": sym["kind"],
            "signature": sym["signature"],
            "file_path": sym["file_path"],
            "file_language": sym["file_language"],
            "start_line": sym["start_line"],
            "end_line": sym["end_line"],
            "exported": bool(sym["exported"]),
            "content_hash": sym["content_hash"],
            "callers": [
                {
                    "name": c["caller_name"],
                    "kind": c["caller_kind"],
                    "file": c["file"],
                    "line": c["line"],
                }
                for c in callers
            ],
        },
    }


def get_context(
    conn,
    symbol_id: int,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT s.*, f.path AS file_path, f.language AS file_language, "
        "f.project_id AS project_id "
        "FROM symbols s JOIN files f ON f.id = s.file_id "
        "WHERE s.id = ?",
        (symbol_id,),
    ).fetchone()
    if row is None:
        return {"error": f"symbol not found: {symbol_id}"}

    symbol = dict(row)
    callers = find_calls_by_id(conn, symbol_id, direction="callers")
    callees = find_calls_by_id(conn, symbol_id, direction="callees")
    memories = get_memory_entries(
        conn,
        symbol["project_id"],
        scope_type="symbol",
        scope_id=symbol_id,
    )
    summary_info = get_or_generate_summary(
        conn,
        symbol_id,
        symbol["content_hash"],
    )

    return {
        "symbol": symbol,
        "callers": callers,
        "callees": callees,
        "memories": memories,
        "summary": summary_info["summary"],
        "generation_context": summary_info["generation_context"],
    }
