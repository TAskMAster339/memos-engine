from __future__ import annotations

from functools import cached_property

import numpy as np

from memos.search.base import EmbeddingModel


class FastEmbedEmbedding(EmbeddingModel):
    MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

    def __init__(self) -> None:
        self._model = None

    @cached_property
    def model(self):
        from fastembed import TextEmbedding

        return TextEmbedding(self.MODEL_NAME)

    def embed(self, texts: list[str]) -> list[np.ndarray]:
        return list(self.model.embed(texts))

    def embed_query(self, text: str) -> np.ndarray:
        return next(self.model.query_embed(text))

    @property
    def dimension(self) -> int:
        return 384
