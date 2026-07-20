import shutil
import tempfile
from pathlib import Path

from starlette.testclient import TestClient

import memos.api.main as api_mod
from memos.api.main import app
from memos.cli.main import (
    EXTENSION_INDEXERS,
    find_files,
    get_or_create_project,
    index_file,
)
from memos.core.db import get_connection, resolve_call_edges, run_migrations

TS_FIXTURE = Path(__file__).parent / "fixtures" / "typescript_mini"

client = TestClient(app)


def _index_into(temp_dir: str, fixture_root: Path):
    memos_dir = Path(temp_dir) / ".memos"
    memos_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(memos_dir / "memory.db")
    conn = get_connection(db_path)
    run_migrations(conn)
    project = get_or_create_project(conn, temp_dir)
    for full, rel in find_files(str(fixture_root)):
        ext = Path(full).suffix
        indexer = EXTENSION_INDEXERS.get(ext)
        if indexer is not None:
            index_file(conn, project, full, rel, indexer, full=True)

    resolve_call_edges(conn, project.id)
    conn.commit()
    conn.close()


class TestApi:
    def setup_method(self):
        self._tmp = tempfile.mkdtemp()
        _index_into(self._tmp, TS_FIXTURE)
        # point the API app at our temp project
        api_mod.PROJECT_PATH = self._tmp

    def teardown_method(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_find_symbol(self):
        resp = client.get("/symbols", params={"name": "greet"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "greet"
        assert data[0]["kind"] == "function"

    def test_find_symbol_with_kind(self):
        resp = client.get("/symbols", params={"name": "main", "kind": "function"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "main"

    def test_find_symbol_not_found(self):
        resp = client.get("/symbols", params={"name": "nonexistent"})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_find_calls_by_id_callees(self):
        resp = client.get("/symbols", params={"name": "main"})
        main_id = resp.json()[0]["id"]

        resp = client.get(f"/symbols/{main_id}/calls", params={"direction": "callees"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["caller_name"] == "main"

    def test_find_calls_by_id_callers(self):
        resp = client.get("/symbols", params={"name": "greet"})
        greet_id = resp.json()[0]["id"]

        resp = client.get(f"/symbols/{greet_id}/calls", params={"direction": "callers"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["callee_name"] == "greet"

    def test_find_calls_invalid_direction(self):
        resp = client.get("/symbols", params={"name": "main"})
        main_id = resp.json()[0]["id"]

        resp = client.get(f"/symbols/{main_id}/calls", params={"direction": "invalid"})
        assert resp.status_code == 422

    def test_get_module(self):
        resp = client.get("/modules/src/index.ts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["file"]["path"] == "src/index.ts"
        symbol_names = {s["name"] for s in data["symbols"]}
        assert "main" in symbol_names
