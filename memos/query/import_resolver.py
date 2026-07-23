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


def resolve_ts_import(
    imported_path: str,
    src_path: str,
    path_to_id: dict[str, int],
) -> int | None:
    """Resolve a TypeScript/JavaScript/JSX/TSX import path.

    Only resolves relative imports (./ or ../). Non-relative paths
    (npm packages, aliases) return None.

    Candidates: path, +.ts, +.tsx, +.js, +.jsx, +/index.ts, +/index.tsx,
    +/index.js, +/index.jsx
    """
    if not imported_path.startswith(("./", "../")):
        return None

    src_dir = posixpath.dirname(src_path)
    base = posixpath.normpath(posixpath.join(src_dir, imported_path))
    for suffix in _TS_CANDIDATES:
        candidate = base + suffix
        fid = path_to_id.get(candidate)
        if fid is not None:
            return fid
    return None


def resolve_python_import(
    imported_path: str,
    src_path: str,
    path_to_id: dict[str, int],
) -> int | None:
    """Resolve a Python import path.

    Only resolves relative imports (starting with one or more dots).
    Non-relative paths (stdlib, external packages) return None.

    One dot = same package dir, two dots = parent package, etc.
    Candidates: +.py, +/__init__.py
    """
    if not imported_path.startswith("."):
        return None

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
