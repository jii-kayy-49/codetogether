import sqlite3
import threading
from pathlib import Path
from typing import Any


MAX_HISTORY_MESSAGES = 100


class ChatHistoryStore:
    def __init__(
        self,
        database_path: Path,
        max_messages: int = MAX_HISTORY_MESSAGES,
    ) -> None:
        if max_messages < 1:
            raise ValueError("Chat history must retain at least one message.")
        self.database_path = database_path
        self.max_messages = max_messages
        self._connection: sqlite3.Connection | None = None
        self._lock = threading.RLock()

    def load_recent(self) -> list[dict[str, Any]]:
        with self._lock:
            connection = self._get_connection()
            rows = connection.execute(
                """
                SELECT id, username, message, timestamp
                FROM chat_messages
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (self.max_messages,),
            ).fetchall()
            return [
                {
                    "id": row[0],
                    "type": "chat_message",
                    "username": row[1],
                    "message": row[2],
                    "timestamp": row[3],
                }
                for row in reversed(rows)
            ]

    def add_message(self, event: dict[str, Any]) -> None:
        with self._lock:
            connection = self._get_connection()
            with connection:
                connection.execute(
                    """
                    INSERT INTO chat_messages (id, username, message, timestamp)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        event["id"],
                        event["username"],
                        event["message"],
                        event["timestamp"],
                    ),
                )
                connection.execute(
                    """
                    DELETE FROM chat_messages
                    WHERE rowid NOT IN (
                        SELECT rowid
                        FROM chat_messages
                        ORDER BY rowid DESC
                        LIMIT ?
                    )
                    """,
                    (self.max_messages,),
                )

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None

    def _get_connection(self) -> sqlite3.Connection:
        if self._connection is not None:
            return self._connection

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.database_path,
            timeout=5,
            check_same_thread=False,
        )
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            self._create_schema(connection)
            connection.commit()
        except Exception:
            connection.close()
            raise

        self._connection = connection
        return connection

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL CHECK (length(username) > 0),
                message TEXT NOT NULL CHECK (length(message) BETWEEN 1 AND 2000),
                timestamp TEXT NOT NULL
            )
            """
        )
