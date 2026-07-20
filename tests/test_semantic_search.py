import numpy as np

from memos.core.db import (
    get_connection,
    insert_file,
    insert_project,
    insert_symbol,
    run_migrations,
)
from memos.core.models import File, Project, Symbol
from memos.query.core import semantic_search
from memos.search.sqlite_vec_store import SqliteVecStore


def _make_vec(dim: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.random(dim).astype(np.float32)
    v /= np.linalg.norm(v)
    return v


DIM = 384


class TestSqliteVecStore:
    def test_add_and_search(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        store = SqliteVecStore(conn)

        v1 = _make_vec(DIM, 1)
        v2 = _make_vec(DIM, 2)
        store.add(1, v1)
        store.add(2, v2)

        results = store.search(v1, top_k=5)
        assert len(results) == 2
        assert results[0][0] == 1
        assert results[0][1] < 0.01

        conn.close()

    def test_add_batch(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        store = SqliteVecStore(conn)

        vecs = [_make_vec(DIM, i) for i in range(5)]
        store.add_batch([10, 20, 30, 40, 50], vecs)

        results = store.search(vecs[0], top_k=5)
        assert len(results) == 5
        assert results[0][0] == 10

        conn.close()

    def test_remove(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        store = SqliteVecStore(conn)

        v = _make_vec(DIM, 1)
        store.add(1, v)
        store.remove(1)

        results = store.search(v, top_k=5)
        assert len(results) == 0

        conn.close()

    def test_remove_batch(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        store = SqliteVecStore(conn)

        for i in range(3):
            store.add(i, _make_vec(DIM, i))
        store.remove_batch([0, 2])

        results = store.search(_make_vec(DIM, 5), top_k=10)
        assert len(results) == 1
        assert results[0][0] == 1

        conn.close()

    def test_search_empty(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        store = SqliteVecStore(conn)

        results = store.search(_make_vec(DIM, 0), top_k=5)
        assert results == []

        conn.close()


class TestSemanticSearch:
    def _seed_symbols(self, conn, project_id):
        fa = insert_file(
            conn,
            File(
                project_id=project_id,
                path="src/main.ts",
                language="typescript",
                content_hash="h1",
            ),
        )
        fb = insert_file(
            conn,
            File(
                project_id=project_id,
                path="src/utils.ts",
                language="typescript",
                content_hash="h2",
            ),
        )

        s1 = insert_symbol(
            conn,
            Symbol(
                file_id=fa.id,
                name="findUser",
                kind="function",
                signature="(id: string): User",
                start_line=1,
                end_line=10,
                exported=True,
                content_hash="h1",
            ),
        )
        s2 = insert_symbol(
            conn,
            Symbol(
                file_id=fa.id,
                name="deleteUser",
                kind="function",
                signature="(id: string): void",
                start_line=12,
                end_line=20,
                exported=True,
                content_hash="h2",
            ),
        )
        s3 = insert_symbol(
            conn,
            Symbol(
                file_id=fb.id,
                name="formatDate",
                kind="function",
                signature="(date: Date): string",
                start_line=1,
                end_line=5,
                exported=False,
                content_hash="h3",
            ),
        )

        conn.commit()
        return [s1, s2, s3]

    def test_semantic_search_empty_db(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        results = semantic_search(conn, "find user", top_k=5)
        assert results == []
        conn.close()

    def test_semantic_search_returns_scored_results(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        store = SqliteVecStore(conn)

        project = insert_project(
            conn,
            Project(
                root_path="/test/p",
                name="p",
                created_at="2024-01-01T00:00:00",
            ),
        )
        symbols = self._seed_symbols(conn, project.id)

        vecs = [_make_vec(DIM, i) for i in range(len(symbols))]
        store.add_batch([s.id for s in symbols], vecs)

        results = semantic_search(conn, "test query", top_k=5, project_id=project.id)
        assert len(results) == 3
        for r in results:
            assert "score" in r
            assert r["score"] >= 0
            assert "file_path" in r
        assert results[0]["score"] <= results[1]["score"]

        conn.close()

    def test_semantic_search_respects_top_k(self):
        conn = get_connection(":memory:")
        run_migrations(conn)
        store = SqliteVecStore(conn)

        project = insert_project(
            conn,
            Project(
                root_path="/test/p",
                name="p",
                created_at="2024-01-01T00:00:00",
            ),
        )
        symbols = self._seed_symbols(conn, project.id)
        vecs = [_make_vec(DIM, i) for i in range(len(symbols))]
        store.add_batch([s.id for s in symbols], vecs)

        results = semantic_search(conn, "test", top_k=1, project_id=project.id)
        assert len(results) == 1

        conn.close()
