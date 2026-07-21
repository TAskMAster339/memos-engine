import json
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from memos.core.db import get_connection, get_project_by_root, run_migrations
from memos.query.core import (
    add_memory_entry,
    find_calls,
    find_symbol,
    get_context,
    get_memory_entries,
    get_module,
    list_files,
    list_symbols,
    semantic_search,
)

mcp = FastMCP("Memory OS")

_projects: dict[str, tuple] = {}
_active_project: str | None = None
_lock = threading.Lock()


def _inject_conn(path, conn, project):
    with _lock:
        _projects[path] = (conn, project)


def _ensure_project(path: str | None = None):
    resolved = path
    if resolved is None:
        with _lock:
            resolved = _active_project
    if resolved is None:
        raise RuntimeError(
            "no project open — call open_project first, e.g. "
            'open_project(path="/path/to/project")',
        )
    with _lock:
        entry = _projects.get(resolved)
    if entry is None:
        raise RuntimeError(
            f"project {resolved} is not open — call open_project first",
        )
    return entry


def _open_project(root_path: str):
    resolved = str(Path(root_path).resolve())
    memos_dir = Path(resolved) / ".memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memos_dir / "memory.db")

    conn = get_connection(db_path)
    run_migrations(conn)

    project = get_project_by_root(conn, resolved)
    if project is None:
        from memos.cli.main import (  # noqa: PLC0415
            EXTENSION_INDEXERS,
            find_files,
            get_or_create_project,
            index_file,
        )

        project = get_or_create_project(conn, resolved)
        files = find_files(resolved)
        for full_path, rel_path in files:
            ext = Path(full_path).suffix.lower()
            indexer = EXTENSION_INDEXERS.get(ext)
            if indexer is None:
                continue
            index_file(
                conn,
                project,
                full_path,
                rel_path,
                indexer,
                full=True,
                embed=True,
            )
        from memos.core.db import resolve_call_edges  # noqa: PLC0415

        resolve_call_edges(conn, project.id)
        conn.commit()

    _projects[resolved] = (conn, project)
    return conn, project


@mcp.tool()
def open_project(path: str) -> str:
    """Open a project by path. Builds the index if none exists yet.

    Must be called before any other tool that queries a project.
    Multiple projects can be opened and queried in the same session.

    Args:
        path: Absolute path to the project root directory
    """
    global _active_project  # noqa: PLW0603
    try:
        resolved = str(Path(path).resolve())
        conn, project = _open_project(resolved)
        with _lock:
            _active_project = resolved

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
                "files": file_count,
                "symbols": symbol_count,
            },
            indent=2,
            default=str,
        )
    except Exception as e:
        return json.dumps({"error": f"failed to open project: {e}"})


@mcp.tool()
def find_symbol_tool(
    name: str,
    kind: str | None = None,
    file_path: str | None = None,
    project: str | None = None,
) -> str:
    """Search code symbols by name across an opened project.

    Args:
        name: Symbol name to search for (case-sensitive)
        kind: Filter by kind (function, class, const, variable, interface, type_alias)
        file_path: Only search within a specific file path
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = find_symbol(
            conn,
            name,
            kind=kind,
            file_path=file_path,
            project_id=proj.id,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def find_calls_tool(
    symbol_name: str,
    direction: str = "callers",
    project: str | None = None,
) -> str:
    """Find callers or callees of a symbol.

    Shows which functions call a given symbol (callers) or which
    functions are called by a given symbol (callees).

    Args:
        symbol_name: Name of the symbol to analyze
        direction: 'callers' to find who calls this symbol, or
            'callees' to find what this symbol calls
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = find_calls(
            conn,
            symbol_name,
            direction=direction,
            project_id=proj.id,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def get_module_tool(path: str, project: str | None = None) -> str:
    """Show everything known about a file.

    Returns symbols, call edges, and imports for the given file.

    Args:
        path: Relative file path (e.g. 'src/utils.ts')
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        result = get_module(conn, path, proj.id)
        return json.dumps(result, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def get_context_tool(
    symbol_id: int,
    project: str | None = None,
) -> str:
    """Composite call: returns symbol + callers + callees + memory entries
    + LLM summary (if cached) or generation context (if not yet generated).

    This is the primary tool to call before modifying a function — it replaces
    re-reading the whole file and its dependents.

    Args:
        symbol_id: ID of the symbol to get full context for
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, _proj = _ensure_project(project)
        result = get_context(conn, symbol_id)
        if "error" in result:
            return json.dumps(result)
        return json.dumps(result, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def semantic_search_tool(
    query: str,
    top_k: int = 10,
    project: str | None = None,
) -> str:
    """Semantic search over code symbols using natural language.

    Finds symbols whose meaning or intent matches the query,
    not just exact name matches.

    Args:
        query: Natural language description of what to find
        top_k: Maximum number of results (default 10, max 50)
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = semantic_search(
            conn,
            query,
            top_k=min(top_k, 50),
            project_id=proj.id,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"search failed: {e}"})


@mcp.tool()
def list_files_tool(
    path_filter: str | None = None,
    project: str | None = None,
) -> str:
    """List all indexed files in an opened project.

    Args:
        path_filter: Optional substring to filter paths
            (e.g. 'util' to find files with 'util' in the path)
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = list_files(conn, proj.id, path_filter=path_filter)
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def list_symbols_tool(
    file_path: str | None = None,
    kind: str | None = None,
    project: str | None = None,
) -> str:
    """List all indexed symbols in an opened project.

    Args:
        file_path: Only show symbols from a specific file
            (e.g. 'src/utils.ts')
        kind: Filter by symbol kind (function, class, const,
            variable, interface, type_alias, enum)
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = list_symbols(
            conn,
            proj.id,
            file_path=file_path,
            kind=kind,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def memory_add_note(  # noqa: PLR0913
    content: str,
    scope_type: str = "project",
    scope_id: int | None = None,
    kind: str = "note",
    source_hash: str | None = None,
    project: str | None = None,
) -> str:
    """Add a note to the project's episodic memory. Notes persist across reindexing.

    Args:
        content: The text content of the memory note
        scope_type: Scope type — 'project' (project-wide), 'file' (for a
            specific file), or 'symbol' (for a specific symbol)
        scope_id: ID of the file or symbol this memory belongs to
            (required when scope_type is file or symbol)
        kind: Kind of memory — 'note', 'summary', or 'decision'
        source_hash: Optional explicit source_hash (e.g. symbol content_hash
            for kind='summary'). Defaults to sha256 of content.
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        result = add_memory_entry(
            conn,
            proj.id,
            content,
            scope_type=scope_type,
            scope_id=scope_id,
            kind=kind,
            source="agent",
            source_hash=source_hash,
        )
        conn.commit()
        return json.dumps(result, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def get_memories(
    scope_type: str | None = None,
    scope_id: int | None = None,
    project: str | None = None,
) -> str:
    """Retrieve memory entries for a project.

    Args:
        scope_type: Filter by scope — 'project', 'file', or 'symbol'
        scope_id: Filter by scope ID (file or symbol id)
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = get_memory_entries(
            conn,
            proj.id,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def list_projects_tool(project: str | None = None) -> str:
    """Show opened project info including stats.

    Args:
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        file_count = conn.execute(
            "SELECT COUNT(*) FROM files WHERE project_id = ?",
            (proj.id,),
        ).fetchone()[0]
        symbol_count = conn.execute(
            "SELECT COUNT(*) FROM symbols s "
            "JOIN files f ON f.id = s.file_id WHERE f.project_id = ?",
            (proj.id,),
        ).fetchone()[0]
        return json.dumps(
            {
                "root_path": proj.root_path,
                "name": proj.name,
                "created_at": proj.created_at,
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
