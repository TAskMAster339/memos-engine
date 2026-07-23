import os
import time
from pathlib import Path

import pytest
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from memos.cli.main import EXTENSION_INDEXERS
from memos.core.db import (
    get_connection,
    get_file_by_path,
    resolve_call_edges,
    run_migrations,
)
from memos.core.models import Project
from memos.indexer.diff import compute_file_hash


@pytest.mark.slow
def test_watch_detects_file_change(tmp_path: Path):
    root = str(tmp_path)
    db_path = str(tmp_path / ".memos" / "memory.db")

    src = tmp_path / "src"
    src.mkdir()
    src_file = src / "a.ts"
    src_file.write_text("export const x = 1;")

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(db_path)
    run_migrations(conn)

    project = Project(root_path=root, name="test", created_at="2026-01-01T00:00:00")
    cur = conn.execute(
        "INSERT INTO projects (root_path, name, created_at) VALUES (?, ?, ?)",
        (project.root_path, project.name, project.created_at),
    )
    project = project.model_copy(update={"id": cur.lastrowid})

    indexer = EXTENSION_INDEXERS[".ts"]
    from memos.cli.main import index_file
    index_file(
        conn, project, str(src_file), "src/a.ts", indexer,
        full=False, embed=False,
    )
    resolve_call_edges(conn, project.id)
    conn.commit()
    pre_hash = compute_file_hash(str(src_file))

    # change the file
    src_file.write_text("export const y = 2;")

    # now simulate what cmd_watch does: detect + reindex
    ext = ".ts"
    indexer = EXTENSION_INDEXERS[ext]
    index_file(
        conn, project, str(src_file), "src/a.ts", indexer,
        full=False, embed=False,
    )
    resolve_call_edges(conn, project.id)
    conn.commit()

    row = get_file_by_path(conn, project.id, "src/a.ts")
    assert row is not None
    assert row.content_hash != pre_hash, "hash should change after reindex"

    conn.close()


@pytest.mark.slow
def test_watchdog_observer_detects_modify(tmp_path: Path):
    root = str(tmp_path)
    src = tmp_path / "src"
    src.mkdir()
    src_file = src / "a.ts"
    src_file.write_text("export const x = 1;")

    changed: list[str] = []

    class _Handler(FileSystemEventHandler):
        def on_modified(self, event):
            if event.is_directory:
                return
            rel = os.path.relpath(event.src_path, root)
            ext = Path(event.src_path).suffix.lower()
            if ext not in EXTENSION_INDEXERS:
                return
            changed.append(rel)

    handler = _Handler()
    observer = Observer()
    observer.schedule(handler, root, recursive=True)
    observer.start()

    try:
        time.sleep(0.3)
        src_file.write_text("export const y = 2;")
        time.sleep(1.0)
        assert "src/a.ts" in changed
    finally:
        observer.stop()
        observer.join()
