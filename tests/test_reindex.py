import json
import tempfile
from pathlib import Path

from memos.core.db import insert_project
from memos.core.models import Project
from memos.mcp.server import _inject_conn, _projects, reindex_file_tool

FIXTURE_CONTENT = """export function greet(name: string): string {
  return "hello " + name;
}
"""

FIXTURE_AFTER = """export function greet(name: string): string {
  return "hello " + name;
}

export function farewell(name: string): string {
  return "goodbye " + name;
}
"""


def _setup(conn):
    tmpdir = tempfile.mkdtemp()
    src = Path(tmpdir) / "src"
    src.mkdir()
    file_path = src / "utils.ts"
    file_path.write_text(FIXTURE_CONTENT)

    project = Project(
        root_path=tmpdir,
        name="test",
        created_at="2024-01-01",
    )
    project = insert_project(conn, project)
    conn.commit()

    _projects[tmpdir] = (conn, project)
    _inject_conn(tmpdir, conn, project)
    return tmpdir, file_path


def test_reindex_file(conn):
    tmpdir, _ = _setup(conn)
    result = json.loads(reindex_file_tool(path="src/utils.ts", project=tmpdir))
    assert result["path"] == "src/utils.ts"
    assert result["reindexed"] is True
    assert result["symbols"] == 1

    symbols = conn.execute(
        "SELECT name FROM symbols s JOIN files f ON f.id = s.file_id "
        "WHERE f.path = 'src/utils.ts'",
    ).fetchall()
    names = [r["name"] for r in symbols]
    assert "greet" in names


def test_reindex_file_skips_unchanged(conn):
    tmpdir, _ = _setup(conn)

    reindex_file_tool(path="src/utils.ts", project=tmpdir)

    result = json.loads(
        reindex_file_tool(path="src/utils.ts", project=tmpdir),
    )
    assert result["reindexed"] is False


def test_reindex_file_updates_symbols(conn):
    tmpdir, file_path = _setup(conn)

    reindex_file_tool(path="src/utils.ts", project=tmpdir)

    file_path.write_text(FIXTURE_AFTER)

    result = json.loads(
        reindex_file_tool(path="src/utils.ts", project=tmpdir),
    )
    assert result["reindexed"] is True
    assert result["symbols"] == 2

    symbols = conn.execute(
        "SELECT name FROM symbols s JOIN files f ON f.id = s.file_id "
        "WHERE f.path = 'src/utils.ts'",
    ).fetchall()
    names = [r["name"] for r in symbols]
    assert "greet" in names
    assert "farewell" in names
