import json
import threading
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from memos.core.db import get_connection, get_project_by_root, run_migrations
from memos.query.core import (
    add_memory_entry,
    find_calls,
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
    list_files,
    list_symbols,
    memory_prune,
    memory_search,
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
def rename_impact_tool(
    symbol_id: int,
    project: str | None = None,
) -> str:
    """Analyse what would break if a symbol were renamed.

    Returns the symbol definition, all callers, type references (textual),
    and import references pointing to the symbol's file.

    Args:
        symbol_id: ID of the symbol to analyse
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, _proj = _ensure_project(project)
        result = get_rename_impact(conn, symbol_id)
        if "error" in result:
            return json.dumps(result)
        return json.dumps(result, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def diff_impact_tool(
    path: str,
    project: str | None = None,
) -> str:
    """Show who depends on exported symbols in a file.

    For each exported symbol lists the unique caller files and call count.
    Use this before modifying a public API to understand blast radius.

    Args:
        path: Relative file path (e.g. 'src/utils.ts')
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        result = get_diff_impact(conn, path, proj.id)
        if "error" in result:
            return json.dumps(result)
        return json.dumps(result, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def get_dependency_graph_tool(
    project: str | None = None,
) -> str:
    """Get the file-level dependency graph for the project.

    Nodes are indexed files; edges are imports with a resolved
    target file (resolved_file_id IS NOT NULL).

    Args:
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        result = get_dependency_graph(conn, proj.id)
        return json.dumps(result, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def find_import_cycles_tool(
    project: str | None = None,
) -> str:
    """Find import cycles in the project's dependency graph.

    Uses DFS with recursion-stack tracking to detect cycles.
    Each cycle is returned as a list of file paths.

    Args:
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = find_import_cycles(conn, proj.id)
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def find_unused_symbols_tool(
    project: str | None = None,
) -> str:
    """Find private functions/methods that are never called (dead code).

    Only considers functions and methods — types and interfaces are excluded
    (they have different usage semantics).

    Args:
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = find_unused_symbols(conn, proj.id)
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def find_dead_imports_tool(
    project: str | None = None,
) -> str:
    """Find imports that could not be resolved to any indexed file.

    These may be external npm/go modules or genuinely missing files.
    Each result includes a 'likely_external' boolean heuristic.

    Args:
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = find_dead_imports(conn, proj.id)
        return json.dumps(results, indent=2, default=str)
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
def reindex_file_tool(
    path: str,
    project: str | None = None,
) -> str:
    """Re-index a single file after editing.

    Parses the file, updates symbols/call edges/imports in the index,
    then resolves any new unresolved call edges.

    Args:
        path: Relative file path (e.g. 'src/utils.ts')
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    from memos.cli.main import EXTENSION_INDEXERS, index_file  # noqa: PLC0415
    from memos.core.db import resolve_call_edges  # noqa: PLC0415

    try:
        conn, proj = _ensure_project(project)
        rel_path = path
        full_path = str(Path(proj.root_path) / rel_path)

        if not Path(full_path).exists():
            return json.dumps({"error": f"file not found: {full_path}"})

        ext = Path(full_path).suffix.lower()
        indexer = EXTENSION_INDEXERS.get(ext)
        if indexer is None:
            return json.dumps({
                "error": f"unsupported extension: {ext} "
                f"(supported: {', '.join(EXTENSION_INDEXERS)})",
            })

        reindexed = index_file(
            conn,
            proj,
            full_path,
            rel_path,
            indexer,
            full=False,
            embed=True,
        )

        if reindexed:
            unresolved = conn.execute(
                "SELECT COUNT(*) FROM call_edges ce "
                "JOIN symbols s ON s.id = ce.caller_symbol_id "
                "JOIN files f ON f.id = s.file_id "
                "WHERE f.project_id = ? AND ce.callee_symbol_id IS NULL",
                (proj.id,),
            ).fetchone()[0]
            if unresolved > 0:
                resolve_call_edges(conn, proj.id)

        conn.commit()

        sym_count = conn.execute(
            "SELECT COUNT(*) FROM symbols s "
            "JOIN files f ON f.id = s.file_id "
            "WHERE f.project_id = ? AND f.path = ?",
            (proj.id, rel_path),
        ).fetchone()[0]

        return json.dumps({
            "path": rel_path,
            "reindexed": reindexed,
            "symbols": sym_count,
        }, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"reindex failed: {e}"})


@mcp.tool()
def memory_search_tool(
    query: str,
    top_k: int = 10,
    project: str | None = None,
) -> str:
    """Full-text search over memory entries using FTS5.

    Args:
        query: Search query (phrase matching via FTS5)
        top_k: Maximum number of results (default 10)
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        results = memory_search(conn, proj.id, query, top_k=top_k)
        return json.dumps(results, indent=2, default=str)
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"query failed: {e}"})


@mcp.tool()
def memory_prune_tool(
    older_than_days: int | None = None,
    kind: str | None = None,
    *,
    apply: bool = False,
    project: str | None = None,
) -> str:
    """Delete stale memory entries.

    By default runs in dry-run mode — returns count without deleting.
    Pass apply=True to actually delete entries matching the filters.

    Args:
        older_than_days: Delete entries older than this many days
        kind: Filter by entry kind ('note', 'summary', 'decision')
        apply: If True, actually delete; if False, dry-run (default)
        project: Project root path (must have been opened via open_project).
            Defaults to the most recently opened project.
    """
    try:
        conn, proj = _ensure_project(project)
        count = memory_prune(
            conn,
            proj.id,
            older_than_days=older_than_days,
            kind=kind,
            apply=apply,
        )
        return json.dumps({
            "count": count,
            "dry_run": not apply,
        }, indent=2, default=str)
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
