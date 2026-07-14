from __future__ import annotations

import hashlib
import math
from typing import Protocol


class EmbeddingProvider(Protocol):
    provider_id: str
    model_id: str
    dimension: int

    async def embed(self, texts: list[str]) -> list[list[float]]: ...


def validate_embeddings(
    vectors: list[list[float]], *, expected_count: int, expected_dimension: int | None = None
) -> list[list[float]]:
    if len(vectors) != expected_count:
        raise ValueError("embedding response count mismatch")
    normalized: list[list[float]] = []
    dimension = expected_dimension
    for vector in vectors:
        if not vector or len(vector) > 4_096:
            raise ValueError("embedding dimension is outside the safe range")
        if dimension is None:
            dimension = len(vector)
        if len(vector) != dimension:
            raise ValueError("embedding dimension mismatch")
        try:
            converted = [float(value) for value in vector]
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("embedding contains an invalid numeric value") from exc
        if any(not math.isfinite(value) for value in converted):
            raise ValueError("embedding contains a non-finite value")
        normalized.append(converted)
    return normalized


class DeterministicEmbeddingProvider:
    provider_id = "deterministic"
    model_id = "sha256-embedding-v1"

    def __init__(self, dimension: int = 16) -> None:
        if not 4 <= dimension <= 64:
            raise ValueError("deterministic embedding dimension must be between 4 and 64")
        self.dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            digest = hashlib.shake_256(text.encode("utf-8")).digest(self.dimension * 2)
            values = []
            for index in range(self.dimension):
                raw = int.from_bytes(digest[index * 2 : index * 2 + 2], "big")
                values.append((raw - 32_767.5) / 32_767.5)
            magnitude = math.sqrt(sum(value * value for value in values)) or 1.0
            vectors.append([value / magnitude for value in values])
        return validate_embeddings(
            vectors, expected_count=len(texts), expected_dimension=self.dimension
        )
