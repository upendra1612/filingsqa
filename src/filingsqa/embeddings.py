"""Embedding models behind one small interface, so experiments can swap them."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """Local ONNX embeddings via fastembed: free, CPU-only, no API key.

    The model (about 70 MB for bge-small) downloads once on first use.
    """

    def __init__(self, model: str = DEFAULT_MODEL, batch_size: int = 64):
        from fastembed import TextEmbedding  # imported lazily: heavy, and optional in tests

        self.name = model
        self.batch_size = batch_size
        self._model = TextEmbedding(model_name=model)
        self.dim = len(next(iter(self._model.embed(["dimension probe"]))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self._model.embed(texts, batch_size=self.batch_size)]

    def embed_query(self, text: str) -> list[float]:
        # bge models expect queries and passages to be embedded differently
        return next(iter(self._model.query_embed(text))).tolist()


class HashEmbedder:
    """Deterministic bag-of-words hashing. For tests only: no model download."""

    def __init__(self, dim: int = 256):
        self.name = f"hash-{dim}"
        self.dim = dim

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * self.dim
        for word in re.findall(r"[a-z0-9]+", text.lower()):
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)
