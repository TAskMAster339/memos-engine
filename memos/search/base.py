from abc import ABC, abstractmethod

import numpy as np


class EmbeddingModel(ABC):
    @abstractmethod
    def embed(self, texts: list[str]) -> list[np.ndarray]: ...

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray: ...

    @property
    @abstractmethod
    def dimension(self) -> int: ...


class VectorStore(ABC):
    @abstractmethod
    def add(self, symbol_id: int, embedding: np.ndarray) -> None: ...

    @abstractmethod
    def add_batch(self, ids: list[int], embeddings: list[np.ndarray]) -> None: ...

    @abstractmethod
    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
    ) -> list[tuple[int, float]]: ...

    @abstractmethod
    def remove(self, symbol_id: int) -> None: ...

    @abstractmethod
    def remove_batch(self, symbol_ids: list[int]) -> None: ...
