import json
from pathlib import Path

from memos.cli.main import EXTENSION_INDEXERS, find_files, get_or_create_project, index_file
from memos.core.db import get_connection, run_migrations
from memos.query.core import find_calls, find_symbol, get_module

TS_FIXTURE = Path(__file__).parent / "fixtures" / "typescript_mini"
GO_FIXTURE = Path(__file__).parent / "fixtures" / "go_mini"


def _index_fixture(conn, fixture_root):
    run_migrations(conn)
    project = get_or_create_project(conn, str(fixture_root))
    for full, rel in find_files(str(fixture_root)):
        ext = Path(full).suffix
        indexer = EXTENSION_INDEXERS.get(ext)
        if indexer is not None:
            index_file(conn, project, full, rel, indexer, full=True)
    conn.commit()
    return project


class TestQueryIntegration:
    def test_query_ts_symbol(self):
        conn = get_connection(":memory:")
        project = _index_fixture(conn, TS_FIXTURE)

        results = find_symbol(conn, "greet")
        assert len(results) == 1
        assert results[0]["kind"] == "function"
        assert results[0]["exported"] == 1
        assert results[0]["file_path"] == "src/utils.ts"
        assert "signature" in results[0]

        conn.close()

    def test_query_ts_calls(self):
        conn = get_connection(":memory:")
        _index_fixture(conn, TS_FIXTURE)

        callers = find_calls(conn, "greet", direction="callers")
        assert len(callers) == 1
        assert callers[0]["caller_name"] == "main"
        assert callers[0]["file"] == "src/index.ts"

        conn.close()

    def test_query_ts_module(self):
        conn = get_connection(":memory:")
        project = _index_fixture(conn, TS_FIXTURE)

        mod = get_module(conn, "src/index.ts", project.id)
        assert mod["file"]["path"] == "src/index.ts"
        symbol_names = {s["name"] for s in mod["symbols"]}
        assert symbol_names == {"main", "user"}
        assert len(mod["calls"]) == 1
        assert len(mod["imports"]) == 2

        conn.close()

    def test_query_go_symbol(self):
        conn = get_connection(":memory:")
        _index_fixture(conn, GO_FIXTURE)

        results = find_symbol(conn, "GreetPublic")
        assert len(results) == 1
        assert results[0]["kind"] == "function"
        assert results[0]["exported"] == 1
        assert results[0]["file_path"] == "src/utils.go"

        conn.close()

    def test_query_go_calls(self):
        conn = get_connection(":memory:")
        _index_fixture(conn, GO_FIXTURE)

        callees = find_calls(conn, "GreetPublic", direction="callees")
        assert len(callees) == 1
        assert callees[0]["callee_name"] == "greet"

        conn.close()

    def test_query_go_module(self):
        conn = get_connection(":memory:")
        project = _index_fixture(conn, GO_FIXTURE)

        mod = get_module(conn, "src/main.go", project.id)
        assert mod["file"]["path"] == "src/main.go"
        symbol_names = {s["name"] for s in mod["symbols"]}
        assert symbol_names == {"main"}
        assert len(mod["calls"]) == 2  # main calls greet + fmt.Println
        assert len(mod["imports"]) == 2  # fmt + os

        conn.close()

    def test_output_is_json_serializable(self):
        conn = get_connection(":memory:")
        _index_fixture(conn, TS_FIXTURE)

        results = find_symbol(conn, "greet")
        dumped = json.dumps(results, default=str)
        parsed = json.loads(dumped)
        assert len(parsed) == 1
        assert parsed[0]["name"] == "greet"

        conn.close()
