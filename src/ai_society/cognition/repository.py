from __future__ import annotations

import json
import math
import re
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from threading import RLock

from ai_society.cognition.embeddings import validate_embeddings
from ai_society.cognition.models import BeliefRecord, MemoryRecord, ModelUsageSummary
from ai_society.domain.enums import MemoryLayer
from ai_society.persistence.canonical import canonical_digest, canonical_json


_SAFE_DATABASE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_CURRENT_SCHEMA_VERSION = 1

_MIGRATION_1 = (
    """
    CREATE TABLE memory_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL CHECK(length(run_id) BETWEEN 1 AND 64),
        agent_id TEXT NOT NULL CHECK(length(agent_id) BETWEEN 1 AND 96),
        layer TEXT NOT NULL CHECK(layer IN ('working','episodic','semantic','social')),
        content TEXT NOT NULL CHECK(length(content) BETWEEN 1 AND 4000),
        created_minute INTEGER NOT NULL CHECK(created_minute >= 0),
        last_accessed_minute INTEGER NOT NULL CHECK(last_accessed_minute >= 0),
        last_decay_minute INTEGER NOT NULL CHECK(last_decay_minute >= 0),
        importance_milli INTEGER NOT NULL CHECK(importance_milli BETWEEN 0 AND 1000),
        confidence_milli INTEGER NOT NULL CHECK(confidence_milli BETWEEN 0 AND 1000),
        access_count INTEGER NOT NULL DEFAULT 0 CHECK(access_count >= 0),
        source_kind TEXT NOT NULL CHECK(length(source_kind) BETWEEN 1 AND 64),
        source_actor_id TEXT CHECK(source_actor_id IS NULL OR length(source_actor_id) <= 96),
        source_event_id TEXT CHECK(source_event_id IS NULL OR length(source_event_id) <= 96),
        content_hash TEXT NOT NULL CHECK(length(content_hash) = 64),
        related_agent_id TEXT CHECK(related_agent_id IS NULL OR length(related_agent_id) <= 96),
        parent_memory_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(length(parent_memory_ids_json) <= 2048),
        embedding_model TEXT CHECK(embedding_model IS NULL OR length(embedding_model) <= 128),
        embedding_json TEXT CHECK(embedding_json IS NULL OR length(embedding_json) <= 131072),
        archived INTEGER NOT NULL DEFAULT 0 CHECK(archived IN (0,1)),
        dedupe_key TEXT NOT NULL CHECK(length(dedupe_key) <= 256),
        UNIQUE(run_id, agent_id, dedupe_key)
    )
    """,
    """
    CREATE INDEX memory_scope_idx
    ON memory_entries(run_id, agent_id, archived, layer, created_minute, id)
    """,
    """
    CREATE TABLE beliefs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL CHECK(length(run_id) BETWEEN 1 AND 64),
        agent_id TEXT NOT NULL CHECK(length(agent_id) BETWEEN 1 AND 96),
        subject TEXT NOT NULL CHECK(length(subject) BETWEEN 1 AND 240),
        predicate TEXT NOT NULL CHECK(length(predicate) BETWEEN 1 AND 120),
        object_text TEXT NOT NULL CHECK(length(object_text) BETWEEN 1 AND 1000),
        confidence_milli INTEGER NOT NULL CHECK(confidence_milli BETWEEN 0 AND 1000),
        updated_minute INTEGER NOT NULL CHECK(updated_minute >= 0),
        last_decay_minute INTEGER NOT NULL CHECK(last_decay_minute >= 0),
        source_kind TEXT NOT NULL CHECK(length(source_kind) BETWEEN 1 AND 64),
        source_event_id TEXT CHECK(source_event_id IS NULL OR length(source_event_id) <= 96),
        provenance TEXT NOT NULL CHECK(length(provenance) BETWEEN 1 AND 240),
        UNIQUE(run_id, agent_id, subject, predicate, object_text)
    )
    """,
    """
    CREATE INDEX belief_scope_idx
    ON beliefs(run_id, agent_id, updated_minute, id)
    """,
    """
    CREATE TABLE model_calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL CHECK(length(run_id) BETWEEN 1 AND 64),
        agent_id TEXT NOT NULL CHECK(length(agent_id) BETWEEN 1 AND 96),
        provider TEXT NOT NULL CHECK(length(provider) BETWEEN 1 AND 64),
        model TEXT NOT NULL CHECK(length(model) BETWEEN 1 AND 128),
        binding_revision INTEGER NOT NULL CHECK(binding_revision >= 0),
        attempt INTEGER NOT NULL CHECK(attempt BETWEEN 1 AND 2),
        status TEXT NOT NULL CHECK(status IN ('reserved','completed','failed')),
        estimated_input_tokens INTEGER NOT NULL CHECK(estimated_input_tokens >= 0),
        max_output_tokens INTEGER NOT NULL CHECK(max_output_tokens >= 0),
        reserved_tokens INTEGER NOT NULL CHECK(reserved_tokens >= 0),
        charged_tokens INTEGER NOT NULL DEFAULT 0 CHECK(charged_tokens >= 0),
        input_tokens INTEGER NOT NULL DEFAULT 0 CHECK(input_tokens >= 0),
        output_tokens INTEGER NOT NULL DEFAULT 0 CHECK(output_tokens >= 0),
        latency_ms INTEGER NOT NULL DEFAULT 0 CHECK(latency_ms >= 0),
        error_code TEXT CHECK(error_code IS NULL OR length(error_code) <= 96),
        response_digest TEXT CHECK(response_digest IS NULL OR length(response_digest) = 64)
    )
    """,
    """
    CREATE INDEX model_call_scope_idx
    ON model_calls(run_id, agent_id, id)
    """,
)


class CognitionRepositoryError(RuntimeError):
    pass


class CognitiveBudgetExceeded(CognitionRepositoryError):
    pass


class SQLiteCognitionRepository:
    def __init__(self, root: Path, database_name: str = "cognition") -> None:
        if not _SAFE_DATABASE_NAME.fullmatch(database_name):
            raise CognitionRepositoryError("database name must be a safe slug")
        if root.exists() and root.is_symlink():
            raise CognitionRepositoryError("cognition root cannot be a symbolic link")
        root.mkdir(parents=True, exist_ok=True)
        self.root = root.resolve(strict=True)
        if not self.root.is_dir() or self.root.is_symlink():
            raise CognitionRepositoryError("cognition root must be a regular directory")
        candidate = self.root / f"{database_name}.sqlite3"
        if candidate.is_symlink():
            raise CognitionRepositoryError("database path cannot be a symbolic link")
        path = candidate.resolve(strict=False)
        if path.parent != self.root:
            raise CognitionRepositoryError("database path escapes the configured root")
        self.path = path
        self._lock = RLock()
        self._connection = sqlite3.connect(
            str(path),
            timeout=5.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._connection.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    @property
    def schema_version(self) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
        ).fetchone()
        return int(row["version"])

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> SQLiteCognitionRepository:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _configure(self) -> None:
        for statement in (
            "PRAGMA foreign_keys = ON",
            "PRAGMA trusted_schema = OFF",
            "PRAGMA busy_timeout = 5000",
            "PRAGMA journal_mode = WAL",
            "PRAGMA synchronous = FULL",
        ):
            self._connection.execute(statement)

    def _migrate(self) -> None:
        self._connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                checksum TEXT NOT NULL CHECK(length(checksum) = 64)
            )
            """
        )
        rows = self._connection.execute(
            "SELECT version, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()
        if rows and int(rows[-1]["version"]) > _CURRENT_SCHEMA_VERSION:
            raise CognitionRepositoryError("database schema is newer than this runtime")
        expected_checksum = canonical_digest(list(_MIGRATION_1))
        for row in rows:
            if int(row["version"]) == 1 and row["checksum"] != expected_checksum:
                raise CognitionRepositoryError("migration checksum mismatch")
        if not any(int(row["version"]) == 1 for row in rows):
            with self._transaction():
                for statement in _MIGRATION_1:
                    self._connection.execute(statement)
                self._connection.execute(
                    "INSERT INTO schema_migrations(version, checksum) VALUES (?, ?)",
                    (1, expected_checksum),
                )

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield
            except Exception:
                self._connection.execute("ROLLBACK")
                raise
            else:
                self._connection.execute("COMMIT")

    def add_memory(
        self,
        *,
        run_id: str,
        agent_id: str,
        layer: MemoryLayer,
        content: str,
        game_minute: int,
        importance_milli: int = 500,
        confidence_milli: int = 700,
        source_kind: str,
        source_actor_id: str | None = None,
        source_event_id: str | None = None,
        related_agent_id: str | None = None,
        parent_memory_ids: Sequence[str] = (),
        embedding_model: str | None = None,
        embedding: Sequence[float] | None = None,
        dedupe_key: str | None = None,
    ) -> MemoryRecord:
        content_hash = canonical_digest(content)
        key = dedupe_key or f"{source_kind}:{source_event_id or content_hash}"
        vector = self._validated_vector(embedding)
        with self._transaction():
            row_id = self._insert_memory(
                run_id=run_id,
                agent_id=agent_id,
                layer=layer,
                content=content,
                game_minute=game_minute,
                importance_milli=importance_milli,
                confidence_milli=confidence_milli,
                source_kind=source_kind,
                source_actor_id=source_actor_id,
                source_event_id=source_event_id,
                related_agent_id=related_agent_id,
                parent_memory_ids=parent_memory_ids,
                embedding_model=embedding_model,
                embedding=vector,
                dedupe_key=key,
            )
            row = self._connection.execute(
                "SELECT * FROM memory_entries WHERE id = ?", (row_id,)
            ).fetchone()
        return self._memory_from_row(row)

    def upsert_semantic_memory(
        self,
        *,
        run_id: str,
        agent_id: str,
        content: str,
        game_minute: int,
        importance_milli: int = 500,
        confidence_milli: int = 700,
        source_kind: str,
        source_actor_id: str | None = None,
        source_event_id: str | None = None,
        related_agent_id: str | None = None,
        parent_memory_ids: Sequence[str] = (),
        embedding_model: str | None = None,
        embedding: Sequence[float] | None = None,
        dedupe_key: str,
    ) -> MemoryRecord:
        """Insert or reconfirm one current semantic fact within an agent scope."""
        if len(parent_memory_ids) > 30:
            raise ValueError("memory provenance parent limit exceeded")
        vector = self._validated_vector(embedding)
        parent_json = canonical_json(list(parent_memory_ids))
        embedding_json = None if vector is None else canonical_json(vector)
        content_hash = canonical_digest(content)
        with self._transaction():
            existing = self._connection.execute(
                """
                SELECT id, layer FROM memory_entries
                WHERE run_id = ? AND agent_id = ? AND dedupe_key = ?
                """,
                (run_id, agent_id, dedupe_key),
            ).fetchone()
            if existing is None:
                row_id = self._insert_memory(
                    run_id=run_id,
                    agent_id=agent_id,
                    layer=MemoryLayer.SEMANTIC,
                    content=content,
                    game_minute=game_minute,
                    importance_milli=importance_milli,
                    confidence_milli=confidence_milli,
                    source_kind=source_kind,
                    source_actor_id=source_actor_id,
                    source_event_id=source_event_id,
                    related_agent_id=related_agent_id,
                    parent_memory_ids=parent_memory_ids,
                    embedding_model=embedding_model,
                    embedding=vector,
                    dedupe_key=dedupe_key,
                )
            else:
                if existing["layer"] != MemoryLayer.SEMANTIC.value:
                    raise CognitionRepositoryError(
                        "semantic-memory dedupe key collides with another layer"
                    )
                row_id = int(existing["id"])
                self._connection.execute(
                    """
                    UPDATE memory_entries SET
                        content = ?, created_minute = ?, last_accessed_minute = ?,
                        last_decay_minute = ?, importance_milli = ?,
                        confidence_milli = ?, source_kind = ?, source_actor_id = ?,
                        source_event_id = ?, content_hash = ?, related_agent_id = ?,
                        parent_memory_ids_json = ?, embedding_model = ?,
                        embedding_json = ?, archived = 0
                    WHERE id = ? AND run_id = ? AND agent_id = ?
                    """,
                    (
                        content,
                        game_minute,
                        game_minute,
                        game_minute,
                        importance_milli,
                        confidence_milli,
                        source_kind,
                        source_actor_id,
                        source_event_id,
                        content_hash,
                        related_agent_id,
                        parent_json,
                        embedding_model,
                        embedding_json,
                        row_id,
                        run_id,
                        agent_id,
                    ),
                )
            row = self._connection.execute(
                "SELECT * FROM memory_entries WHERE id = ?", (row_id,)
            ).fetchone()
        return self._memory_from_row(row)

    def _insert_memory(
        self,
        *,
        run_id: str,
        agent_id: str,
        layer: MemoryLayer,
        content: str,
        game_minute: int,
        importance_milli: int,
        confidence_milli: int,
        source_kind: str,
        source_actor_id: str | None,
        source_event_id: str | None,
        related_agent_id: str | None,
        parent_memory_ids: Sequence[str],
        embedding_model: str | None,
        embedding: Sequence[float] | None,
        dedupe_key: str,
    ) -> int:
        if len(parent_memory_ids) > 30:
            raise ValueError("memory provenance parent limit exceeded")
        parent_json = canonical_json(list(parent_memory_ids))
        embedding_json = None if embedding is None else canonical_json(list(embedding))
        content_hash = canonical_digest(content)
        self._connection.execute(
            """
            INSERT OR IGNORE INTO memory_entries(
                run_id, agent_id, layer, content, created_minute,
                last_accessed_minute, last_decay_minute, importance_milli,
                confidence_milli, source_kind, source_actor_id, source_event_id,
                content_hash, related_agent_id, parent_memory_ids_json,
                embedding_model, embedding_json, dedupe_key
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                agent_id,
                layer.value,
                content,
                game_minute,
                game_minute,
                game_minute,
                importance_milli,
                confidence_milli,
                source_kind,
                source_actor_id,
                source_event_id,
                content_hash,
                related_agent_id,
                parent_json,
                embedding_model,
                embedding_json,
                dedupe_key,
            ),
        )
        row = self._connection.execute(
            """
            SELECT id FROM memory_entries
            WHERE run_id = ? AND agent_id = ? AND dedupe_key = ?
            """,
            (run_id, agent_id, dedupe_key),
        ).fetchone()
        if row is None:
            raise CognitionRepositoryError("memory insert failed")
        return int(row["id"])

    def list_memories(
        self,
        *,
        run_id: str,
        agent_id: str,
        layers: Sequence[MemoryLayer] | None = None,
        include_archived: bool = False,
    ) -> list[MemoryRecord]:
        conditions = ["run_id = ?", "agent_id = ?"]
        parameters: list[object] = [run_id, agent_id]
        if not include_archived:
            conditions.append("archived = 0")
        if layers:
            placeholders = ",".join("?" for _ in layers)
            conditions.append(f"layer IN ({placeholders})")
            parameters.extend(layer.value for layer in layers)
        rows = self._connection.execute(
            f"SELECT * FROM memory_entries WHERE {' AND '.join(conditions)} "
            "ORDER BY created_minute, id",
            parameters,
        ).fetchall()
        return [self._memory_from_row(row) for row in rows]

    def retrieve(
        self,
        *,
        run_id: str,
        agent_id: str,
        query: str,
        game_minute: int,
        query_embedding: Sequence[float] | None = None,
        layers: Sequence[MemoryLayer] | None = None,
        limit: int = 8,
        max_characters: int = 12_000,
    ) -> list[MemoryRecord]:
        if not 1 <= limit <= 30:
            raise ValueError("memory retrieval limit must be between 1 and 30")
        vector = self._validated_vector(query_embedding)
        candidates = self.list_memories(
            run_id=run_id, agent_id=agent_id, layers=layers, include_archived=False
        )
        scored: list[tuple[int, MemoryRecord]] = []
        for memory in candidates:
            semantic_milli = self._semantic_score(query, vector, memory)
            age = max(0, game_minute - memory.created_minute)
            recency_milli = (1_000 * 1_440) // (1_440 + age)
            usage_milli = min(1_000, memory.access_count * 100)
            score = (
                semantic_milli * 350
                + recency_milli * 200
                + memory.importance_milli * 200
                + memory.confidence_milli * 200
                + usage_milli * 50
            )
            scored.append((score, memory))
        scored.sort(key=lambda item: (-item[0], item[1].memory_id))
        selected: list[MemoryRecord] = []
        characters = 0
        for _, memory in scored:
            if len(selected) >= limit:
                break
            if characters + len(memory.content) > max_characters:
                continue
            selected.append(memory)
            characters += len(memory.content)
        if selected:
            ids = [int(memory.memory_id.removeprefix("memory-")) for memory in selected]
            with self._transaction():
                self._connection.executemany(
                    """
                    UPDATE memory_entries
                    SET access_count = access_count + 1, last_accessed_minute = ?
                    WHERE id = ? AND run_id = ? AND agent_id = ?
                    """,
                    [(game_minute, row_id, run_id, agent_id) for row_id in ids],
                )
            refreshed = {
                item.memory_id: item
                for item in self.list_memories(run_id=run_id, agent_id=agent_id)
            }
            return [refreshed[memory.memory_id] for memory in selected]
        return []

    def compact_working_memory(
        self,
        *,
        run_id: str,
        agent_id: str,
        game_minute: int,
        max_items: int = 30,
        keep_recent: int = 20,
    ) -> MemoryRecord | None:
        if not 1 <= keep_recent < max_items <= 100:
            raise ValueError("invalid working-memory compaction limits")
        working = self.list_memories(
            run_id=run_id,
            agent_id=agent_id,
            layers=[MemoryLayer.WORKING],
        )
        if len(working) <= max_items:
            return None
        compacted = working[: len(working) - keep_recent]
        parent_ids = [item.memory_id for item in compacted][-30:]
        body = " | ".join(item.content for item in compacted)
        content = f"Compacted working memory: {body}"[:4_000]
        importance = max(item.importance_milli for item in compacted)
        confidence = sum(item.confidence_milli for item in compacted) // len(compacted)
        key = f"working_compaction:{compacted[0].memory_id}:{compacted[-1].memory_id}"
        with self._transaction():
            row_id = self._insert_memory(
                run_id=run_id,
                agent_id=agent_id,
                layer=MemoryLayer.EPISODIC,
                content=content,
                game_minute=game_minute,
                importance_milli=importance,
                confidence_milli=confidence,
                source_kind="working_compaction",
                source_actor_id=agent_id,
                source_event_id=compacted[-1].source_event_id,
                related_agent_id=None,
                parent_memory_ids=parent_ids,
                embedding_model=None,
                embedding=None,
                dedupe_key=key,
            )
            source_ids = [int(item.memory_id.removeprefix("memory-")) for item in compacted]
            self._connection.executemany(
                """
                UPDATE memory_entries SET archived = 1
                WHERE id = ? AND run_id = ? AND agent_id = ? AND layer = 'working'
                """,
                [(row_id_value, run_id, agent_id) for row_id_value in source_ids],
            )
            row = self._connection.execute(
                "SELECT * FROM memory_entries WHERE id = ?", (row_id,)
            ).fetchone()
        return self._memory_from_row(row)

    @staticmethod
    def _decayed_confidence(
        *,
        confidence_milli: int,
        last_decay_minute: int,
        game_minute: int,
        rate_milli_per_day: int,
    ) -> tuple[int, int] | None:
        elapsed = max(0, game_minute - last_decay_minute)
        if elapsed == 0 or confidence_milli == 0:
            return None
        scaled_elapsed = elapsed * rate_milli_per_day
        decrement = scaled_elapsed // 1_440
        if decrement == 0:
            # Preserve the cursor so frequent sub-threshold calls accumulate time.
            return None
        confidence = max(0, confidence_milli - decrement)
        if confidence == 0:
            return confidence, game_minute
        remainder_minutes = (scaled_elapsed % 1_440) // rate_milli_per_day
        return confidence, game_minute - remainder_minutes

    def apply_forgetting(
        self, *, run_id: str, agent_id: str, game_minute: int
    ) -> int:
        rates = {
            MemoryLayer.WORKING.value: 25,
            MemoryLayer.EPISODIC.value: 10,
            MemoryLayer.SEMANTIC.value: 3,
            MemoryLayer.SOCIAL.value: 5,
        }
        rows = self._connection.execute(
            """
            SELECT id, layer, confidence_milli, last_decay_minute
            FROM memory_entries
            WHERE run_id = ? AND agent_id = ? AND archived = 0
            ORDER BY id
            """,
            (run_id, agent_id),
        ).fetchall()
        updates: list[tuple[int, int, int, str, str]] = []
        for row in rows:
            decayed = self._decayed_confidence(
                confidence_milli=int(row["confidence_milli"]),
                last_decay_minute=int(row["last_decay_minute"]),
                game_minute=game_minute,
                rate_milli_per_day=rates[str(row["layer"])],
            )
            if decayed is None:
                continue
            confidence, last_decay_minute = decayed
            updates.append(
                (confidence, last_decay_minute, int(row["id"]), run_id, agent_id)
            )
        if updates:
            with self._transaction():
                self._connection.executemany(
                    """
                    UPDATE memory_entries
                    SET confidence_milli = ?, last_decay_minute = ?
                    WHERE id = ? AND run_id = ? AND agent_id = ?
                    """,
                    updates,
                )
        return len(updates)

    def upsert_belief(
        self,
        *,
        run_id: str,
        agent_id: str,
        subject: str,
        predicate: str,
        object: str,
        confidence_milli: int,
        game_minute: int,
        source_kind: str,
        provenance: str,
        source_event_id: str | None = None,
        supersede_subject_predicate: bool = False,
    ) -> BeliefRecord:
        with self._transaction():
            canonical_id: int | None = None
            if supersede_subject_predicate:
                existing = self._connection.execute(
                    """
                    SELECT id FROM beliefs
                    WHERE run_id = ? AND agent_id = ?
                      AND subject = ? AND predicate = ?
                    ORDER BY updated_minute DESC, id DESC
                    """,
                    (run_id, agent_id, subject, predicate),
                ).fetchall()
                if existing:
                    canonical_id = int(existing[0]["id"])
                    self._connection.execute(
                        """
                        DELETE FROM beliefs
                        WHERE run_id = ? AND agent_id = ?
                          AND subject = ? AND predicate = ? AND id <> ?
                        """,
                        (run_id, agent_id, subject, predicate, canonical_id),
                    )
                    self._connection.execute(
                        """
                        UPDATE beliefs SET
                            object_text = ?, confidence_milli = ?,
                            updated_minute = ?, last_decay_minute = ?,
                            source_kind = ?, source_event_id = ?, provenance = ?
                        WHERE id = ? AND run_id = ? AND agent_id = ?
                        """,
                        (
                            object,
                            confidence_milli,
                            game_minute,
                            game_minute,
                            source_kind,
                            source_event_id,
                            provenance,
                            canonical_id,
                            run_id,
                            agent_id,
                        ),
                    )
            if canonical_id is None:
                self._connection.execute(
                    """
                    INSERT INTO beliefs(
                        run_id, agent_id, subject, predicate, object_text,
                        confidence_milli, updated_minute, last_decay_minute,
                        source_kind, source_event_id, provenance
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(run_id, agent_id, subject, predicate, object_text)
                    DO UPDATE SET
                        confidence_milli = excluded.confidence_milli,
                        updated_minute = excluded.updated_minute,
                        last_decay_minute = excluded.last_decay_minute,
                        source_kind = excluded.source_kind,
                        source_event_id = excluded.source_event_id,
                        provenance = excluded.provenance
                    """,
                    (
                        run_id,
                        agent_id,
                        subject,
                        predicate,
                        object,
                        confidence_milli,
                        game_minute,
                        game_minute,
                        source_kind,
                        source_event_id,
                        provenance,
                    ),
                )
                row = self._connection.execute(
                    """
                    SELECT * FROM beliefs
                    WHERE run_id = ? AND agent_id = ?
                      AND subject = ? AND predicate = ? AND object_text = ?
                    """,
                    (run_id, agent_id, subject, predicate, object),
                ).fetchone()
            else:
                row = self._connection.execute(
                    """
                    SELECT * FROM beliefs
                    WHERE id = ? AND run_id = ? AND agent_id = ?
                    """,
                    (canonical_id, run_id, agent_id),
                ).fetchone()
        return self._belief_from_row(row)

    def list_beliefs(self, *, run_id: str, agent_id: str) -> list[BeliefRecord]:
        rows = self._connection.execute(
            """
            SELECT * FROM beliefs
            WHERE run_id = ? AND agent_id = ?
            ORDER BY updated_minute, id
            """,
            (run_id, agent_id),
        ).fetchall()
        return [self._belief_from_row(row) for row in rows]

    def apply_belief_forgetting(
        self, *, run_id: str, agent_id: str, game_minute: int
    ) -> int:
        rows = self._connection.execute(
            """
            SELECT id, confidence_milli, last_decay_minute FROM beliefs
            WHERE run_id = ? AND agent_id = ? ORDER BY id
            """,
            (run_id, agent_id),
        ).fetchall()
        updates = []
        for row in rows:
            decayed = self._decayed_confidence(
                confidence_milli=int(row["confidence_milli"]),
                last_decay_minute=int(row["last_decay_minute"]),
                game_minute=game_minute,
                rate_milli_per_day=5,
            )
            if decayed is None:
                continue
            confidence, last_decay_minute = decayed
            updates.append(
                (confidence, last_decay_minute, int(row["id"]), run_id, agent_id)
            )
        if updates:
            with self._transaction():
                self._connection.executemany(
                    """
                    UPDATE beliefs SET confidence_milli = ?, last_decay_minute = ?
                    WHERE id = ? AND run_id = ? AND agent_id = ?
                    """,
                    updates,
                )
        return len(updates)

    def reserve_model_call(
        self,
        *,
        run_id: str,
        agent_id: str,
        provider: str,
        model: str,
        binding_revision: int,
        attempt: int,
        request_budget: int,
        token_budget: int,
        estimated_input_tokens: int,
        max_output_tokens: int,
    ) -> int:
        reserved_tokens = estimated_input_tokens + max_output_tokens
        with self._transaction():
            row = self._connection.execute(
                """
                SELECT COUNT(*) AS requests, COALESCE(SUM(
                    CASE WHEN status = 'reserved' THEN reserved_tokens ELSE charged_tokens END
                ), 0) AS tokens
                FROM model_calls WHERE run_id = ? AND agent_id = ?
                """,
                (run_id, agent_id),
            ).fetchone()
            if int(row["requests"]) >= request_budget:
                raise CognitiveBudgetExceeded("request budget exhausted")
            if int(row["tokens"]) + reserved_tokens > token_budget:
                raise CognitiveBudgetExceeded("token budget exhausted")
            cursor = self._connection.execute(
                """
                INSERT INTO model_calls(
                    run_id, agent_id, provider, model, binding_revision, attempt,
                    status, estimated_input_tokens, max_output_tokens, reserved_tokens
                ) VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?, ?, ?)
                """,
                (
                    run_id,
                    agent_id,
                    provider,
                    model,
                    binding_revision,
                    attempt,
                    estimated_input_tokens,
                    max_output_tokens,
                    reserved_tokens,
                ),
            )
            return int(cursor.lastrowid)

    def finish_model_call(
        self,
        call_id: int,
        *,
        success: bool,
        latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        error_code: str | None,
        response_digest: str | None,
    ) -> None:
        with self._transaction():
            row = self._connection.execute(
                "SELECT * FROM model_calls WHERE id = ? AND status = 'reserved'", (call_id,)
            ).fetchone()
            if row is None:
                raise CognitionRepositoryError("model-call reservation is unavailable")
            reported_input = self._safe_token_count(input_tokens)
            reported_output = self._safe_token_count(output_tokens)
            reserved = int(row["reserved_tokens"])
            estimated_input = int(row["estimated_input_tokens"])
            if success and input_tokens is not None and output_tokens is not None:
                charged = max(
                    estimated_input,
                    min(reserved, reported_input + reported_output),
                )
            else:
                charged = reserved
            self._connection.execute(
                """
                UPDATE model_calls SET
                    status = ?, charged_tokens = ?, input_tokens = ?, output_tokens = ?,
                    latency_ms = ?, error_code = ?, response_digest = ?
                WHERE id = ?
                """,
                (
                    "completed" if success else "failed",
                    charged,
                    reported_input,
                    reported_output,
                    max(0, min(int(latency_ms), 24 * 60 * 60 * 1_000)),
                    error_code,
                    response_digest,
                    call_id,
                ),
            )

    def usage_summary(self, *, run_id: str, agent_id: str) -> ModelUsageSummary:
        row = self._connection.execute(
            """
            SELECT
                COUNT(*) AS requests,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS successful,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
                COALESCE(SUM(CASE WHEN status = 'reserved' THEN reserved_tokens ELSE charged_tokens END), 0) AS charged,
                COALESCE(SUM(input_tokens), 0) AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens,
                COALESCE(SUM(latency_ms), 0) AS latency
            FROM model_calls WHERE run_id = ? AND agent_id = ?
            """,
            (run_id, agent_id),
        ).fetchone()
        return ModelUsageSummary(
            requests=int(row["requests"] or 0),
            successful_requests=int(row["successful"] or 0),
            failed_requests=int(row["failed"] or 0),
            charged_tokens=int(row["charged"] or 0),
            input_tokens=int(row["input_tokens"] or 0),
            output_tokens=int(row["output_tokens"] or 0),
            total_latency_ms=int(row["latency"] or 0),
        )

    def export_run(self, run_id: str) -> dict[str, object]:
        memories = self._connection.execute(
            "SELECT * FROM memory_entries WHERE run_id = ? ORDER BY agent_id, id",
            (run_id,),
        ).fetchall()
        beliefs = self._connection.execute(
            "SELECT * FROM beliefs WHERE run_id = ? ORDER BY agent_id, id", (run_id,)
        ).fetchall()
        calls = self._connection.execute(
            "SELECT * FROM model_calls WHERE run_id = ? ORDER BY agent_id, id", (run_id,)
        ).fetchall()
        return {
            "schema_version": self.schema_version,
            "run_id": run_id,
            "memories": [dict(row) for row in memories],
            "beliefs": [dict(row) for row in beliefs],
            "model_calls": [dict(row) for row in calls],
        }

    def run_digest(self, run_id: str) -> str:
        return canonical_digest(self.export_run(run_id))

    @staticmethod
    def _validated_vector(vector: Sequence[float] | None) -> list[float] | None:
        if vector is None:
            return None
        return validate_embeddings([list(vector)], expected_count=1)[0]

    @staticmethod
    def _safe_token_count(value: int | None) -> int:
        if value is None:
            return 0
        if value < 0 or value > 10_000_000:
            return 0
        return int(value)

    @staticmethod
    def _semantic_score(
        query: str, query_vector: Sequence[float] | None, memory: MemoryRecord
    ) -> int:
        if query_vector is not None and memory.embedding is not None:
            if len(query_vector) != len(memory.embedding):
                return 0
            numerator = sum(a * b for a, b in zip(query_vector, memory.embedding, strict=True))
            left = math.sqrt(sum(value * value for value in query_vector))
            right = math.sqrt(sum(value * value for value in memory.embedding))
            similarity = numerator / (left * right) if left and right else 0.0
            return max(0, min(1_000, int((similarity + 1.0) * 500)))
        query_words = set(query.casefold().split())
        memory_words = set(memory.content.casefold().split())
        if not query_words or not memory_words:
            return 0
        return 1_000 * len(query_words & memory_words) // len(query_words | memory_words)

    @staticmethod
    def _memory_from_row(row: sqlite3.Row) -> MemoryRecord:
        embedding = None
        if row["embedding_json"] is not None:
            embedding = tuple(float(value) for value in json.loads(row["embedding_json"]))
        return MemoryRecord(
            memory_id=f"memory-{int(row['id']):012d}",
            run_id=row["run_id"],
            agent_id=row["agent_id"],
            layer=MemoryLayer(row["layer"]),
            content=row["content"],
            created_minute=int(row["created_minute"]),
            last_accessed_minute=int(row["last_accessed_minute"]),
            last_decay_minute=int(row["last_decay_minute"]),
            importance_milli=int(row["importance_milli"]),
            confidence_milli=int(row["confidence_milli"]),
            access_count=int(row["access_count"]),
            source_kind=row["source_kind"],
            source_actor_id=row["source_actor_id"],
            source_event_id=row["source_event_id"],
            content_hash=row["content_hash"],
            related_agent_id=row["related_agent_id"],
            parent_memory_ids=tuple(json.loads(row["parent_memory_ids_json"])),
            embedding_model=row["embedding_model"],
            embedding=embedding,
            archived=bool(row["archived"]),
        )

    @staticmethod
    def _belief_from_row(row: sqlite3.Row) -> BeliefRecord:
        return BeliefRecord(
            belief_id=f"belief-{int(row['id']):012d}",
            run_id=row["run_id"],
            agent_id=row["agent_id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object_text"],
            confidence_milli=int(row["confidence_milli"]),
            updated_minute=int(row["updated_minute"]),
            last_decay_minute=int(row["last_decay_minute"]),
            source_kind=row["source_kind"],
            source_event_id=row["source_event_id"],
            provenance=row["provenance"],
        )
