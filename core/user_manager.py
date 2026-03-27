"""User management system for multi-user support."""

import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    created_at REAL NOT NULL,
    last_login REAL,
    settings TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
"""

# Session tokens expire after 30 days
SESSION_DURATION = 30 * 24 * 60 * 60


def _hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    """Hash a password with a salt using SHA-256.

    Returns (hash, salt) tuple.
    Uses hashlib so no extra dependencies are needed.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    combined = f"{salt}:{password}".encode("utf-8")
    password_hash = hashlib.sha256(combined).hexdigest()
    return f"{salt}${password_hash}", salt


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash."""
    try:
        salt, expected_hash = stored_hash.split("$", 1)
        combined = f"{salt}:{password}".encode("utf-8")
        actual_hash = hashlib.sha256(combined).hexdigest()
        return secrets.compare_digest(actual_hash, expected_hash)
    except (ValueError, AttributeError):
        return False


class UserManager:
    """Manages user accounts, authentication, and per-user data directories."""

    def __init__(self, data_dir: str = "data") -> None:
        self.data_dir = os.path.abspath(data_dir)
        self.db_path = os.path.join(self.data_dir, "users.db")
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Initialize the user database."""
        os.makedirs(self.data_dir, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(USERS_SCHEMA)
        await self._db.commit()
        logger.info("User manager initialized at %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._db:
            await self._db.close()

    async def _ensure_db(self) -> aiosqlite.Connection:
        if self._db is None:
            await self.initialize()
        assert self._db is not None
        return self._db

    async def register(
        self, username: str, password: str, display_name: str | None = None
    ) -> dict[str, Any]:
        """Register a new user.

        Returns dict with success status and user info or error.
        """
        db = await self._ensure_db()

        # Validate input
        username = username.strip().lower()
        if not username or len(username) < 2:
            return {"success": False, "error": "Username must be at least 2 characters"}
        if len(username) > 32:
            return {"success": False, "error": "Username must be 32 characters or less"}
        if not username.isalnum() and not all(c.isalnum() or c in "-_" for c in username):
            return {
                "success": False,
                "error": "Username can only contain letters, numbers, hyphens, and underscores",
            }
        if not password or len(password) < 4:
            return {"success": False, "error": "Password must be at least 4 characters"}

        # Check if username exists
        async with db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ) as cursor:
            if await cursor.fetchone():
                return {"success": False, "error": "Username already taken"}

        # Create user
        password_hash, _ = _hash_password(password)
        now = time.time()
        display = display_name or username.title()

        await db.execute(
            "INSERT INTO users (username, password_hash, display_name, created_at) VALUES (?, ?, ?, ?)",
            (username, password_hash, display, now),
        )
        await db.commit()

        # Get the new user ID
        async with db.execute(
            "SELECT id FROM users WHERE username = ?", (username,)
        ) as cursor:
            row = await cursor.fetchone()
            user_id = row["id"]

        # Create user directories
        self._ensure_user_dirs(username)

        logger.info("Registered new user: %s (id=%d)", username, user_id)
        return {
            "success": True,
            "user": {
                "id": user_id,
                "username": username,
                "display_name": display,
            },
        }

    async def login(self, username: str, password: str) -> dict[str, Any]:
        """Authenticate a user and create a session token.

        Returns dict with success status, token, and user info or error.
        """
        db = await self._ensure_db()
        username = username.strip().lower()

        # Find user
        async with db.execute(
            "SELECT id, username, password_hash, display_name, settings FROM users WHERE username = ?",
            (username,),
        ) as cursor:
            user = await cursor.fetchone()

        if not user:
            return {"success": False, "error": "Invalid username or password"}

        # Verify password
        if not _verify_password(password, user["password_hash"]):
            return {"success": False, "error": "Invalid username or password"}

        # Create session token
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires = now + SESSION_DURATION

        await db.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user["id"], now, expires),
        )

        # Update last login
        await db.execute(
            "UPDATE users SET last_login = ? WHERE id = ?", (now, user["id"])
        )
        await db.commit()

        # Ensure user directories exist
        self._ensure_user_dirs(user["username"])

        logger.info("User logged in: %s", username)
        return {
            "success": True,
            "token": token,
            "user": {
                "id": user["id"],
                "username": user["username"],
                "display_name": user["display_name"],
                "settings": json.loads(user["settings"] or "{}"),
            },
        }

    async def validate_token(self, token: str) -> dict[str, Any] | None:
        """Validate a session token and return user info if valid.

        Returns user dict or None if invalid/expired.
        """
        db = await self._ensure_db()
        now = time.time()

        async with db.execute(
            """SELECT s.user_id, u.username, u.display_name, u.settings
               FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.token = ? AND s.expires_at > ?""",
            (token, now),
        ) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return {
            "id": row["user_id"],
            "username": row["username"],
            "display_name": row["display_name"],
            "settings": json.loads(row["settings"] or "{}"),
        }

    async def logout(self, token: str) -> None:
        """Invalidate a session token."""
        db = await self._ensure_db()
        await db.execute("DELETE FROM sessions WHERE token = ?", (token,))
        await db.commit()

    async def update_settings(
        self, user_id: int, settings: dict[str, Any]
    ) -> None:
        """Update user settings."""
        db = await self._ensure_db()
        await db.execute(
            "UPDATE users SET settings = ? WHERE id = ?",
            (json.dumps(settings), user_id),
        )
        await db.commit()

    async def list_users(self) -> list[dict[str, Any]]:
        """List all registered users (admin use)."""
        db = await self._ensure_db()
        users: list[dict[str, Any]] = []
        async with db.execute(
            "SELECT id, username, display_name, created_at, last_login FROM users ORDER BY username"
        ) as cursor:
            async for row in cursor:
                users.append(dict(row))
        return users

    async def cleanup_expired_sessions(self) -> int:
        """Remove expired sessions. Returns count of removed sessions."""
        db = await self._ensure_db()
        now = time.time()
        cursor = await db.execute(
            "DELETE FROM sessions WHERE expires_at < ?", (now,)
        )
        await db.commit()
        return cursor.rowcount

    def _ensure_user_dirs(self, username: str) -> None:
        """Create per-user data and workspace directories."""
        user_data = os.path.join(self.data_dir, "users", username)
        os.makedirs(user_data, exist_ok=True)
        # Workspace is at project level, not inside data
        workspace = os.path.join(
            os.path.dirname(self.data_dir), "workspace", username
        )
        os.makedirs(workspace, exist_ok=True)

    def get_user_data_dir(self, username: str) -> str:
        """Get the data directory path for a specific user."""
        return os.path.join(self.data_dir, "users", username)

    def get_user_workspace_dir(self, username: str) -> str:
        """Get the workspace directory path for a specific user."""
        return os.path.join(
            os.path.dirname(self.data_dir), "workspace", username
        )
