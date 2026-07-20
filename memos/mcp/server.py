import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from memos.core.db import get_connection, get_project_by_root, run_migrations
from memos.query.core import (
    find_calls,
    find_symbol,
    get_module,
    list_files,
    list_symbols,
    semantic_search,
)

mcp = FastMCP("Memory OS")

_conn = None
_project = None


def _inject_conn(conn, project):
    global _conn, _project  # noqa: PLW0603
    _conn = conn
    _project = project


def _ensure_conn():
    global _conn, _project  # noqa: PLW0603
    if _conn is not None:
        return _conn, _project
    root = str(Path(os.environ.get("MEMOS_PROJECT_PATH", ".")).resolve())
    db_path = str(Path(root) / ".memos" / "memory.db")
    if not Path(db_path).exists():
        raise RuntimeError(
            f"no .memos/memory.db found at {root} — run 'memos index' first",
        )
    _conn = get_connection(db_path)
    run_migrations(_conn)
    _project = get_project_by_root(_conn, root)
    if _project is None:
        raise RuntimeError(f"no project found for {root}")
    return _conn, _project


@mcp.tool()
def find_symbol_tool(
    name: str,
    kind: str | None = None,
    file_path: str | None = None,
) -> str:
    """Search code symbols by name across the project.

    Args:
        name: Symbol name to search for (case-sensitive)
        kind: Filter by kind (function, class, const, variable, interface, type_alias)
        file_path: Only search within a specific file path
    """
    try:
        conn, project = _ensure_conn()
        results = find_symbol(
            conn,
            name,
            kind=kind,
            file_path=file_path,
            project_id=project.id,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def find_calls_tool(symbol_name: str, direction: str = "callers") -> str:
    """Find callers or callees of a symbol.

    Shows which functions call a given symbol (callers) or which
    functions are called by a given symbol (callees).

    Args:
        symbol_name: Name of the symbol to analyze
        direction: 'callers' to find who calls this symbol, or
            'callees' to find what this symbol calls
    """
    try:
        conn, project = _ensure_conn()
        results = find_calls(
            conn,
            symbol_name,
            direction=direction,
            project_id=project.id,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def get_module_tool(path: str) -> str:
    """Show everything known about a file.

    Returns symbols, call edges, and imports for the given file.

    Args:
        path: Relative file path (e.g. 'src/utils.ts')
    """
    try:
        conn, project = _ensure_conn()
        result = get_module(conn, path, project.id)
        return json.dumps(result, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def semantic_search_tool(query: str, top_k: int = 10) -> str:
    """Semantic search over code symbols using natural language.

    Finds symbols whose meaning or intent matches the query,
    not just exact name matches.

    Args:
        query: Natural language description of what to find
        top_k: Maximum number of results (default 10, max 50)
    """
    try:
        conn, project = _ensure_conn()
        results = semantic_search(
            conn,
            query,
            top_k=min(top_k, 50),
            project_id=project.id,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"search failed: {e}"})


@mcp.tool()
def list_files_tool(path_filter: str | None = None) -> str:
    """List all indexed files in the project.

    Args:
        path_filter: Optional substring to filter paths
            (e.g. 'util' to find files with 'util' in the path)
    """
    try:
        conn, project = _ensure_conn()
        results = list_files(conn, project.id, path_filter=path_filter)
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def list_symbols_tool(
    file_path: str | None = None,
    kind: str | None = None,
) -> str:
    """List all indexed symbols in the project.

    Args:
        file_path: Only show symbols from a specific file
            (e.g. 'src/utils.ts')
        kind: Filter by symbol kind (function, class, const,
            variable, interface, type_alias, enum)
    """
    try:
        conn, project = _ensure_conn()
        results = list_symbols(
            conn,
            project.id,
            file_path=file_path,
            kind=kind,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def list_projects_tool() -> str:
    """Show current project info including stats.

    Returns root path, name, creation time, file count, and symbol count.
    """
    try:
        conn, project = _ensure_conn()
        file_count = conn.execute(
            "SELECT COUNT(*) FROM files WHERE project_id = ?",
            (project.id,),
        ).fetchone()[0]
        symbol_count = conn.execute(
            "SELECT COUNT(*) FROM symbols s "
            "JOIN files f ON f.id = s.file_id WHERE f.project_id = ?",
            (project.id,),
        ).fetchone()[0]
        return json.dumps(
            {
                "root_path": project.root_path,
                "name": project.name,
                "created_at": project.created_at,
                "files": file_count,
                "symbols": symbol_count,
            },
            indent=2,
            default=str,
        )
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})
