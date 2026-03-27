"""Database manager for agent working storage."""

import json
import logging
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)


class DatabaseManager:
    """SQLite database that the agent can fully control."""

    def __init__(self, db_path: str = "data/agent.db"):
        self.db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize the database connection."""
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        # Store schema knowledge
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS _schema_notes (
                table_name TEXT PRIMARY KEY,
                description TEXT,
                created_by TEXT DEFAULT 'agent',
                notes TEXT DEFAULT ''
            )
        """)
        await self._db.commit()
        logger.info("Database initialized at %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    async def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return results as dicts."""
        db = await self._ensure_db()
        try:
            async with db.execute(sql, params or ()) as cursor:
                if cursor.description:
                    columns = [d[0] for d in cursor.description]
                    rows = await cursor.fetchall()
                    return [dict(zip(columns, row)) for row in rows]
                return []
        except Exception as e:
            logger.error("SQL error: %s | Query: %s", e, sql)
            raise

    async def execute_write(self, sql: str, params: tuple[Any, ...] | None = None) -> int:
        """Execute a write query (INSERT/UPDATE/DELETE) and return affected rows."""
        db = await self._ensure_db()
        try:
            cursor = await db.execute(sql, params or ())
            await db.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error("SQL write error: %s | Query: %s", e, sql)
            raise

    async def create_table(self, name: str, columns: dict[str, str], description: str = "") -> str:
        """Create a new table with the given columns.

        Args:
            name: Table name
            columns: Dict of column_name -> column_type (e.g. {"id": "INTEGER PRIMARY KEY", "name": "TEXT"})
            description: Human-readable description of the table's purpose
        """
        db = await self._ensure_db()
        col_defs = ", ".join(f"{col} {ctype}" for col, ctype in columns.items())
        sql = f"CREATE TABLE IF NOT EXISTS {name} ({col_defs})"
        await db.execute(sql)
        # Record schema note
        await db.execute(
            "INSERT OR REPLACE INTO _schema_notes (table_name, description) VALUES (?, ?)",
            (name, description),
        )
        await db.commit()
        logger.info("Created table: %s", name)
        return f"Table '{name}' created successfully"

    async def drop_table(self, name: str) -> str:
        """Drop a table."""
        db = await self._ensure_db()
        await db.execute(f"DROP TABLE IF EXISTS {name}")
        await db.execute("DELETE FROM _schema_notes WHERE table_name = ?", (name,))
        await db.commit()
        logger.info("Dropped table: %s", name)
        return f"Table '{name}' dropped"

    async def list_tables(self) -> list[dict[str, Any]]:
        """List all tables with their descriptions."""
        db = await self._ensure_db()
        tables: list[dict[str, Any]] = []
        async with db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ) as cursor:
            async for row in cursor:
                table_name = row[0]
                info: dict[str, Any] = {"name": table_name, "columns": []}
                # Get column info
                async with db.execute(f"PRAGMA table_info({table_name})") as col_cur:
                    async for col in col_cur:
                        info["columns"].append({
                            "name": col[1],
                            "type": col[2],
                            "notnull": bool(col[3]),
                            "pk": bool(col[5]),
                        })
                # Get description
                async with db.execute(
                    "SELECT description, notes FROM _schema_notes WHERE table_name = ?",
                    (table_name,),
                ) as note_cur:
                    note_row = await note_cur.fetchone()
                    if note_row:
                        info["description"] = note_row[0]
                        info["notes"] = note_row[1]
                tables.append(info)
        return tables

    async def describe_table(self, name: str) -> dict[str, Any]:
        """Get detailed schema for a specific table."""
        db = await self._ensure_db()
        info: dict[str, Any] = {"name": name, "columns": [], "row_count": 0}
        async with db.execute(f"PRAGMA table_info({name})") as cursor:
            async for col in cursor:
                info["columns"].append({
                    "name": col[1],
                    "type": col[2],
                    "notnull": bool(col[3]),
                    "default": col[4],
                    "pk": bool(col[5]),
                })
        async with db.execute(f"SELECT COUNT(*) FROM {name}") as cursor:
            row = await cursor.fetchone()
            info["row_count"] = row[0] if row else 0
        return info

    async def add_schema_note(self, table_name: str, notes: str) -> None:
        """Add notes about how to use a table."""
        db = await self._ensure_db()
        await db.execute(
            "UPDATE _schema_notes SET notes = ? WHERE table_name = ?",
            (notes, table_name),
        )
        await db.commit()

    async def get_full_schema(self) -> str:
        """Get a text representation of the full database schema."""
        tables = await self.list_tables()
        if not tables:
            return "Database is empty - no tables exist."

        lines: list[str] = ["Database Schema:", ""]
        for table in tables:
            desc = table.get("description", "")
            lines.append(f"Table: {table['name']}" + (f" - {desc}" if desc else ""))
            for col in table["columns"]:
                pk = " [PK]" if col["pk"] else ""
                nn = " NOT NULL" if col["notnull"] else ""
                lines.append(f"  {col['name']} {col['type']}{pk}{nn}")
            if table.get("notes"):
                lines.append(f"  Notes: {table['notes']}")
            lines.append("")
        return "\n".join(lines)
