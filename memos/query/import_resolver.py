import posixpath

_TS_CANDIDATES = (
    "",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    "/index.ts",
    "/index.tsx",
    "/index.js",
    "/index.jsx",
)

_PY_CANDIDATES = (
    ".py",
    "/__init__.py",
)


def _try_ts_candidates(base: str, path_to_id: dict[str, int]) -> int | None:
    """Try all TS/JS candidate suffixes for a base path."""
    for suffix in _TS_CANDIDATES:
        candidate = base + suffix
        fid = path_to_id.get(candidate)
        if fid is not None:
            return fid
    return None


def resolve_ts_import(
    imported_path: str,
    src_path: str,
    path_to_id: dict[str, int],
    base_url: str | None = None,
    paths: dict[str, list[str]] | None = None,
) -> int | None:
    """Resolve a TypeScript/JavaScript/JSX/TSX import path.

    * Relative imports (./ or ../) — resolved relative to source file.
    * Non-relative imports — first tries tsconfig paths aliases, then
      baseUrl resolution. Falls back to None (npm/external).

    Arguments:
        base_url: value of compilerOptions.baseUrl from tsconfig (or None)
        paths: value of compilerOptions.paths from tsconfig (or None)

    Candidates: path, +.ts, +.tsx, +.js, +.jsx, +/index.ts, +/index.tsx,
    +/index.js, +/index.jsx
    """
    if imported_path.startswith(("./", "../")):
        src_dir = posixpath.dirname(src_path)
        base = posixpath.normpath(posixpath.join(src_dir, imported_path))
        return _try_ts_candidates(base, path_to_id)

    # Non-relative: try paths aliases first, then baseUrl
    if paths:
        for pattern, replacements in paths.items():
            fid = _match_ts_paths_pattern(
                imported_path, pattern, replacements, path_to_id,
            )
            if fid is not None:
                return fid

    if base_url is not None:
        base = posixpath.normpath(posixpath.join(base_url, imported_path))
        fid = _try_ts_candidates(base, path_to_id)
        if fid is not None:
            return fid

    return None


def _match_ts_paths_pattern(
    imported_path: str,
    pattern: str,
    replacements: list[str],
    path_to_id: dict[str, int],
) -> int | None:
    """Try a single tsconfig paths entry against an import path."""
    if "*" in pattern:
        prefix, suffix = pattern.split("*", 1)
        if imported_path.startswith(prefix) and imported_path.endswith(suffix):
            middle = imported_path[len(prefix):len(imported_path) - len(suffix)]
            for replacement in replacements:
                resolved = replacement.replace("*", middle)
                fid = _try_ts_candidates(resolved, path_to_id)
                if fid is not None:
                    return fid
    elif imported_path == pattern:
        for replacement in replacements:
            fid = _try_ts_candidates(replacement, path_to_id)
            if fid is not None:
                return fid
    return None


def resolve_python_import(
    imported_path: str,
    src_path: str,
    path_to_id: dict[str, int],
) -> int | None:
    """Resolve a Python import path.

    * Relative imports (starting with dots) — resolved relative to source file.
    * Absolute imports (no leading dots) — dots are converted to path separators
      and looked up in the index; stdlib/external packages not found in the index
      return None.

    One dot = same package dir, two dots = parent package, etc.
    Candidates: +.py, +/__init__.py
    """
    if imported_path.startswith("."):
        src_dir = posixpath.dirname(src_path)

        n_dots = 0
        while n_dots < len(imported_path) and imported_path[n_dots] == ".":
            n_dots += 1

        rest = imported_path[n_dots:]
        if rest:
            rest = rest.replace(".", "/")

        up_count = n_dots - 1
        base_dir = src_dir
        for _ in range(up_count):
            base_dir = posixpath.dirname(base_dir)

        prefix = posixpath.join(base_dir, rest) if rest else base_dir

        for suffix in _PY_CANDIDATES:
            candidate = prefix + suffix
            fid = path_to_id.get(candidate)
            if fid is not None:
                return fid
        return None

    # Absolute import — try matching against indexed files
    rel_path = imported_path.replace(".", "/")
    for suffix in _PY_CANDIDATES:
        candidate = rel_path + suffix
        fid = path_to_id.get(candidate)
        if fid is not None:
            return fid
    return None


def resolve_go_import(
    imported_path: str,
    src_path: str,
    path_to_id: dict[str, int],
    dir_to_go_paths: dict[str, list[tuple[str, int]]],
    module_prefix: str | None,
) -> int | None:
    """Resolve a Go import path using the module prefix from go.mod.

    Strips the module prefix to get a relative package path, then:
    1. Tries <rel_path>/main.go (convention for cmd packages)
    2. Falls back to the first .go file in the directory alphabetically

    Imports that don't start with module_prefix (stdlib, external modules)
    return None.
    """
    if module_prefix is None:
        return None
    if not imported_path.startswith(module_prefix + "/"):
        return None

    rel_path = imported_path[len(module_prefix) + 1 :]  # strip "module/"

    main_candidate = rel_path + "/main.go"
    fid = path_to_id.get(main_candidate)
    if fid is not None:
        return fid

    entries = sorted(dir_to_go_paths.get(rel_path, []), key=lambda x: x[0])
    if entries:
        return entries[0][1]

    return None
