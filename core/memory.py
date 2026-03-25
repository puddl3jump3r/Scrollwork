"""Persistent memory system for the agent."""

import json
import logging
import time
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

MEMORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    tags TEXT DEFAULT '[]',
    importance REAL DEFAULT 0.5,
    created_at REAL NOT NULL,
    accessed_at REAL NOT NULL,
    access_count INTEGER DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
"""


class MemoryManager:
    """SQLite-backed persistent memory for the agent."""

    def __init__(self, db_path: str = "data/memory.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize the memory database."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(MEMORY_SCHEMA)
        await self._db.commit()
        logger.info("Memory system initialized at %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    async def store(
        self,
        content: str,
        category: str = "general",
        tags: list[str] | None = None,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Store a new memory."""
        db = await self._ensure_db()
        now = time.time()
        cursor = await db.execute(
            """INSERT INTO memories (content, category, tags, importance, created_at, accessed_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                content,
                category,
                json.dumps(tags or []),
                importance,
                now,
                now,
                json.dumps(metadata or {}),
            ),
        )
        await db.commit()
        memory_id = cursor.lastrowid
        logger.debug("Stored memory #%d: %s", memory_id, content[:80])
        return memory_id  # type: ignore[return-value]

    async def recall(
        self,
        query: str | None = None,
        category: str | None = None,
        tags: list[str] | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Recall memories matching the query/filters."""
        db = await self._ensure_db()
        conditions: list[str] = []
        params: list[Any] = []

        if query:
            conditions.append("content LIKE ?")
            params.append(f"%{query}%")
        if category:
            conditions.append("category = ?")
            params.append(category)
        if tags:
            for tag in tags:
                conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"""SELECT * FROM memories WHERE {where}
                  ORDER BY importance DESC, accessed_at DESC LIMIT ?"""
        params.append(limit)

        rows: list[dict[str, Any]] = []
        async with db.execute(sql, params) as cursor:
            async for row in cursor:
                entry = dict(row)
                entry["tags"] = json.loads(entry["tags"])
                entry["metadata"] = json.loads(entry["metadata"])
                rows.append(entry)

        # Update access timestamps
        now = time.time()
        for row in rows:
            await db.execute(
                "UPDATE memories SET accessed_at = ?, access_count = access_count + 1 WHERE id = ?",
                (now, row["id"]),
            )
        await db.commit()

        return rows

    async def recall_recent(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get the most recent memories."""
        return await self.recall(limit=limit)

    async def update_importance(self, memory_id: int, importance: float) -> None:
        """Update the importance of a memory."""
        db = await self._ensure_db()
        await db.execute(
            "UPDATE memories SET importance = ? WHERE id = ?",
            (importance, memory_id),
        )
        await db.commit()

    async def delete(self, memory_id: int) -> None:
        """Delete a memory."""
        db = await self._ensure_db()
        await db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await db.commit()

    async def store_conversation(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a conversation message."""
        db = await self._ensure_db()
        await db.execute(
            """INSERT INTO conversations (session_id, role, content, timestamp, metadata)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, role, content, time.time(), json.dumps(metadata or {})),
        )
        await db.commit()

    async def get_conversation(
        self, session_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get conversation history for a session."""
        db = await self._ensure_db()
        rows: list[dict[str, Any]] = []
        async with db.execute(
            """SELECT * FROM conversations WHERE session_id = ?
               ORDER BY timestamp ASC LIMIT ?""",
            (session_id, limit),
        ) as cursor:
            async for row in cursor:
                entry = dict(row)
                entry["metadata"] = json.loads(entry["metadata"])
                rows.append(entry)
        return rows

    async def get_stats(self) -> dict[str, Any]:
        """Get memory system statistics."""
        db = await self._ensure_db()
        stats: dict[str, Any] = {}
        async with db.execute("SELECT COUNT(*) as cnt FROM memories") as cur:
            row = await cur.fetchone()
            stats["total_memories"] = row["cnt"] if row else 0
        async with db.execute(
            "SELECT category, COUNT(*) as cnt FROM memories GROUP BY category"
        ) as cur:
            stats["by_category"] = {row["category"]: row["cnt"] async for row in cur}
        async with db.execute("SELECT COUNT(DISTINCT session_id) as cnt FROM conversations") as cur:
            row = await cur.fetchone()
            stats["total_sessions"] = row["cnt"] if row else 0
        return stats
