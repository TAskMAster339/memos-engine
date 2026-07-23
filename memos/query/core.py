import hashlib
import re
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


TYPE_KINDS = {"class", "interface", "type_alias", "struct", "enum"}


def get_rename_impact(
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

    sym = dict(row)
    callers = find_calls_by_id(conn, symbol_id, direction="callers")

    type_references: list[dict[str, Any]] = []
    if sym["kind"] in TYPE_KINDS:
        refs = conn.execute(
            "SELECT s2.id, s2.name, s2.kind, s2.signature, "
            "f2.path AS file_path "
            "FROM symbols s2 "
            "JOIN files f2 ON f2.id = s2.file_id "
            "WHERE s2.id != ? AND f2.project_id = ? "
            "AND s2.signature IS NOT NULL",
            (symbol_id, sym["project_id"]),
        ).fetchall()
        pattern = re.compile(rf'\b{re.escape(sym["name"])}\b')
        type_references = [
            dict(r) for r in refs if pattern.search(r["signature"])
        ]

    imports: list[dict[str, Any]] = []
    imp_rows = conn.execute(
        "SELECT * FROM imports WHERE resolved_file_id = ?",
        (sym["file_id"],),
    ).fetchall()
    if imp_rows:
        imports = [dict(r) for r in imp_rows]

    return {
        "symbol": {
            "id": sym["id"],
            "name": sym["name"],
            "kind": sym["kind"],
            "file_path": sym["file_path"],
            "start_line": sym["start_line"],
            "end_line": sym["end_line"],
        },
        "callers": callers,
        "type_references": type_references,
        "import_references": imports,
        "warning": (
            "textual heuristic — does not resolve shadowed names or re-exports"
        ),
    }


def get_diff_impact(
    conn,
    file_path: str,
    project_id: int,
) -> dict[str, Any]:
    file_row = conn.execute(
        "SELECT * FROM files WHERE project_id = ? AND path = ?",
        (project_id, file_path),
    ).fetchone()
    if file_row is None:
        return {"error": f"file not found: {file_path}"}

    file_dict = dict(file_row)
    exported = conn.execute(
        "SELECT s.* FROM symbols s WHERE s.file_id = ? AND s.exported = 1 "
        "ORDER BY s.start_line",
        (file_dict["id"],),
    ).fetchall()

    exported_symbols: list[dict[str, Any]] = []
    for sym_row in exported:
        sym = dict(sym_row)
        callers = find_calls_by_id(conn, sym["id"], direction="callers")
        caller_file_counts: dict[str, int] = {}
        for c in callers:
            p = c["file"]
            caller_file_counts[p] = caller_file_counts.get(p, 0) + 1
        caller_files = [
            {"file": p, "count": cnt}
            for p, cnt in sorted(caller_file_counts.items())
        ]
        exported_symbols.append({
            "name": sym["name"],
            "kind": sym["kind"],
            "caller_files": caller_files,
        })

    return {
        "file": {"path": file_dict["path"], "language": file_dict["language"]},
        "exported_symbols": exported_symbols,
    }


def get_diff_range_impact(
    conn,
    project_id: int,
    changed_files: list[str],
) -> dict[str, Any]:
    """Aggregate impact report for a list of changed file paths.

    For each file that exists in the index, calls *get_diff_impact* and
    collects exported symbols and their external callers.
    """
    files: list[dict[str, Any]] = []
    total_exported = 0
    total_external_callers = 0
    for file_path in changed_files:
        impact = get_diff_impact(conn, file_path, project_id)
        if "error" in impact:
            continue
        files.append(impact)
        total_exported += len(impact["exported_symbols"])
        for sym in impact["exported_symbols"]:
            total_external_callers += sum(
                cf["count"] for cf in sym["caller_files"]
            )
    return {
        "files": files,
        "total_exported_symbols": total_exported,
        "total_external_callers": total_external_callers,
    }


def find_unused_symbols(
    conn,
    project_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT s.*, f.path AS file_path, f.language AS file_language "
        "FROM symbols s "
        "JOIN files f ON f.id = s.file_id "
        "WHERE f.project_id = ? "
        "AND s.exported = 0 "
        "AND s.kind IN ('function', 'method') "
        "AND s.id NOT IN ("
        "  SELECT callee_symbol_id FROM call_edges "
        "  WHERE callee_symbol_id IS NOT NULL"
        ") "
        "ORDER BY f.path, s.start_line",
        (project_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_dependency_graph(
    conn,
    project_id: int,
) -> dict[str, Any]:
    files = conn.execute(
        "SELECT id, path FROM files WHERE project_id = ? ORDER BY path",
        (project_id,),
    ).fetchall()
    nodes = [{"id": r["id"], "path": r["path"]} for r in files]

    edge_rows = conn.execute(
        "SELECT i.file_id AS from_id, i.resolved_file_id AS to_id "
        "FROM imports i "
        "JOIN files f ON f.id = i.file_id "
        "WHERE f.project_id = ? AND i.resolved_file_id IS NOT NULL",
        (project_id,),
    ).fetchall()
    edges = [{"from": r["from_id"], "to": r["to_id"]} for r in edge_rows]

    return {"nodes": nodes, "edges": edges}


def _extract_cycle(
    u: int,
    v: int,
    parent: dict[int, int | None],
    node_map: dict[int, str],
) -> list[str]:
    path: list[str] = []
    cur: int | None = u
    while cur is not None:
        path.append(node_map[cur])
        if cur == v:
            break
        cur = parent.get(cur)
    path.reverse()
    return path


def find_import_cycles(
    conn,
    project_id: int,
) -> list[list[str]]:
    graph = get_dependency_graph(conn, project_id)
    adj: dict[int, list[int]] = {}
    for e in graph["edges"]:
        adj.setdefault(e["from"], []).append(e["to"])

    node_map = {n["id"]: n["path"] for n in graph["nodes"]}

    visited: set[int] = set()
    rec_stack: set[int] = set()
    parent: dict[int, int | None] = {}
    cycles: list[list[str]] = []

    def dfs(u: int) -> None:
        visited.add(u)
        rec_stack.add(u)
        for v in adj.get(u, []):
            if v not in visited:
                parent[v] = u
                dfs(v)
            elif v in rec_stack:
                cycles.append(
                    _extract_cycle(u, v, parent, node_map),
                )
        rec_stack.discard(u)

    for nid in list(node_map.keys()):
        if nid not in visited:
            parent[nid] = None
            dfs(nid)

    return cycles


def memory_search(
    conn,
    project_id: int,
    query: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    fts_query = f'"{query}"'
    rows = conn.execute(
        "SELECT me.* "
        "FROM memory_fts f "
        "JOIN memory_entries me ON me.id = f.rowid "
        "WHERE memory_fts MATCH ? AND f.project_id = ? "
        "ORDER BY rank "
        "LIMIT ?",
        (fts_query, project_id, top_k),
    ).fetchall()
    return [dict(r) for r in rows]


def memory_prune(
    conn,
    project_id: int,
    older_than_days: int | None = None,
    kind: str | None = None,
    *,
    apply: bool = False,
) -> int:
    clauses = ["project_id = ?"]
    params: list[Any] = [project_id]
    if older_than_days is not None:
        clauses.append("created_at < datetime('now', ?)")
        params.append(f"-{older_than_days} days")
    if kind is not None:
        clauses.append("kind = ?")
        params.append(kind)
    where = " AND ".join(clauses)

    if apply:
        conn.execute(f"DELETE FROM memory_entries WHERE {where}", params)
        return conn.execute("SELECT changes()").fetchone()[0]

    return conn.execute(
        f"SELECT COUNT(*) FROM memory_entries WHERE {where}",
        params,
    ).fetchone()[0]


def find_dead_imports(
    conn,
    project_id: int,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT i.*, f.path AS file_path, f.language AS file_language "
        "FROM imports i "
        "JOIN files f ON f.id = i.file_id "
        "WHERE f.project_id = ? "
        "AND i.resolved_file_id IS NULL "
        "ORDER BY f.path, i.imported_path",
        (project_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        imp = dict(r)
        path = imp["imported_path"]
        lang = imp["file_language"]
        if lang in ("typescript", "tsx", "javascript", "jsx"):
            is_relative = path.startswith((".", "/"))
            imp["likely_external"] = not is_relative
            imp["broken"] = is_relative
        elif lang == "python":
            is_relative = path.startswith(".")
            imp["likely_external"] = not is_relative
            imp["broken"] = is_relative
        elif lang == "go":
            imp["likely_external"] = "/" not in path
            imp["broken"] = False
        else:
            imp["likely_external"] = False
            imp["broken"] = False
        out.append(imp)
    return out
