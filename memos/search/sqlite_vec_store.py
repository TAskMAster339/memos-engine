from __future__ import annotations

import sqlite3

import numpy as np
import sqlite_vec

from memos.search.base import VectorStore


class SqliteVecStore(VectorStore):
    TABLE = "vec_symbols"

    def __init__(self, conn: sqlite3.Connection) -> None:
        conn.enable_load_extension(True)  # noqa: FBT003
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)  # noqa: FBT003
        self._conn = conn

    def add(self, symbol_id: int, embedding: np.ndarray) -> None:
        self._conn.execute(
            f"INSERT INTO {self.TABLE}(rowid, embedding) VALUES (?, ?)",
            (symbol_id, sqlite_vec.serialize_float32(embedding)),
        )

    def add_batch(self, ids: list[int], embeddings: list[np.ndarray]) -> None:
        self._conn.executemany(
            f"INSERT INTO {self.TABLE}(rowid, embedding) VALUES (?, ?)",
            [
                (sid, sqlite_vec.serialize_float32(emb))
                for sid, emb in zip(ids, embeddings, strict=False)
            ],
        )

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
    ) -> list[tuple[int, float]]:
        rows = self._conn.execute(
            f"SELECT rowid, distance FROM {self.TABLE} "
            "WHERE embedding MATCH ? ORDER BY distance LIMIT ?",
            (sqlite_vec.serialize_float32(query_embedding), top_k),
        ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def remove(self, symbol_id: int) -> None:
        self._conn.execute(
            f"DELETE FROM {self.TABLE} WHERE rowid = ?",
            (symbol_id,),
        )

    def remove_batch(self, symbol_ids: list[int]) -> None:
        self._conn.executemany(
            f"DELETE FROM {self.TABLE} WHERE rowid = ?",
            [(sid,) for sid in symbol_ids],
        )
