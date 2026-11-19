import asyncio
import json
import logging
import sqlite3
from collections import deque
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from .chat_store import MAX_HISTORY_MESSAGES, ChatHistoryStore


ROOM_ID = "CODING-ROOM-001"
MAX_ROOM_USERS = 3
MAX_MESSAGE_LENGTH = 2000
MAX_CHAT_PAYLOAD_LENGTH = 8192
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(
        self,
        usernames: tuple[str, ...],
        history_store: ChatHistoryStore,
    ) -> None:
        if len(usernames) != MAX_ROOM_USERS or len(set(usernames)) != MAX_ROOM_USERS:
            raise ValueError("The room requires exactly three unique usernames.")

        self.usernames = usernames
        self._history_store = history_store
        self._history_loaded = False
        self._connections: dict[str, set[WebSocket]] = {
            username: set() for username in usernames
        }
        self._socket_users: dict[WebSocket, str] = {}
        self._history: deque[dict[str, Any]] = deque(maxlen=MAX_HISTORY_MESSAGES)
        self._lock = asyncio.Lock()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @classmethod
    def _event_id(cls) -> str:
        return uuid4().hex

    def _presence(self) -> list[dict[str, object]]:
        return [
            {"username": username, "online": bool(self._connections[username])}
            for username in self.usernames
        ]

    async def connect(self, websocket: WebSocket, username: str) -> bool:
        if username not in self._connections:
            await websocket.close(code=4403, reason="Account is not permitted.")
            return False

        if not self._history_loaded:
            try:
                self._history = deque(
                    self._history_store.load_recent(),
                    maxlen=MAX_HISTORY_MESSAGES,
                )
                self._history_loaded = True
            except sqlite3.Error:
                logger.exception("Could not load persisted chat history.")
                await websocket.accept()
                await self._send_error(
                    websocket,
                    "chat_storage_unavailable",
                    "Chat history is temporarily unavailable.",
                )
                await websocket.close(
                    code=1011, reason="Chat history is unavailable."
                )
                return False

        rejected = False
        async with self._lock:
            already_online = bool(self._connections[username])
            online_user_count = sum(bool(sockets) for sockets in self._connections.values())
            if not already_online and online_user_count >= MAX_ROOM_USERS:
                rejected = True
            else:
                await websocket.accept()
                self._connections[username].add(websocket)
                self._socket_users[websocket] = username
                state = {
                    "type": "room_state",
                    "room_id": ROOM_ID,
                    "users": self._presence(),
                    "history": list(self._history),
                }
                try:
                    await websocket.send_json(state)
                except (WebSocketDisconnect, RuntimeError, OSError):
                    self._connections[username].discard(websocket)
                    self._socket_users.pop(websocket, None)
                    return False

                failed_connections = []
                if not already_online:
                    joined_event = self._presence_event("member_joined", username)
                    recipients = self._all_connections()
                    failed_connections = await self._send_to_connections_locked(
                        joined_event, recipients
                    )

        if rejected:
            await websocket.close(code=4429, reason="The room is full.")
            return False

        for failed in failed_connections:
            await self.disconnect(failed)
        return True

    async def disconnect(self, websocket: WebSocket, announce: bool = True) -> None:
        failed_connections = []
        async with self._lock:
            username = self._socket_users.pop(websocket, None)
            if username is None:
                return

            user_connections = self._connections[username]
            user_connections.discard(websocket)
            if announce and not user_connections:
                left_event = self._presence_event("member_left", username)
                failed_connections = await self._send_to_connections_locked(
                    left_event, self._all_connections()
                )

        for failed in failed_connections:
            await self.disconnect(failed)

    async def handle_message(
        self, websocket: WebSocket, username: str, payload: object
    ) -> None:
        if not isinstance(payload, dict) or payload.get("type") != "chat_message":
            await self._send_error(
                websocket, "invalid_event", "Send a chat_message event."
            )
            return

        message = payload.get("message")
        if not isinstance(message, str):
            await self._send_error(
                websocket, "invalid_message", "Message text must be a string."
            )
            return
        if len(message) > MAX_MESSAGE_LENGTH:
            await self._send_error(
                websocket,
                "message_too_long",
                f"Messages must be {MAX_MESSAGE_LENGTH} characters or fewer.",
            )
            return

        message = message.strip()
        if not message:
            await self._send_error(
                websocket, "empty_message", "Messages cannot be empty."
            )
            return

        failed_connections = []
        async with self._lock:
            if self._socket_users.get(websocket) != username:
                return
            event: dict[str, Any] = {
                "id": self._event_id(),
                "type": "chat_message",
                "username": username,
                "message": message,
                "timestamp": self._timestamp(),
            }
            try:
                self._history_store.add_message(event)
            except sqlite3.Error:
                logger.exception("Could not persist a chat message.")
                await self._send_error(
                    websocket,
                    "chat_storage_unavailable",
                    "Your message could not be saved or sent.",
                )
                return

            self._history.append(event)
            failed_connections = await self._send_to_connections_locked(
                event, self._all_connections()
            )

        for failed in failed_connections:
            await self.disconnect(failed)

    async def handle_text(
        self, websocket: WebSocket, username: str, raw_message: str
    ) -> None:
        if len(raw_message) > MAX_CHAT_PAYLOAD_LENGTH:
            await self._send_error(
                websocket, "message_too_large", "Chat payload is too large."
            )
            return

        try:
            payload = json.loads(raw_message)
        except (json.JSONDecodeError, RecursionError):
            await self._send_error(
                websocket, "invalid_json", "Messages must be valid JSON."
            )
            return
        await self.handle_message(websocket, username, payload)

    def _presence_event(self, event_type: str, username: str) -> dict[str, str]:
        return {
            "id": self._event_id(),
            "type": event_type,
            "username": username,
            "timestamp": self._timestamp(),
        }

    def _all_connections(self) -> list[WebSocket]:
        return [
            connection
            for user_connections in self._connections.values()
            for connection in user_connections
        ]

    async def _send_error(
        self, websocket: WebSocket, code: str, message: str
    ) -> None:
        await websocket.send_json(
            {"type": "error", "code": code, "message": message}
        )

    async def _send_to_connections_locked(
        self, payload: dict[str, Any], recipients: list[WebSocket]
    ) -> list[WebSocket]:
        results = await asyncio.gather(
            *(self._try_send(websocket, payload) for websocket in recipients)
        )
        return [
            websocket
            for websocket, succeeded in zip(recipients, results)
            if not succeeded
        ]

    @staticmethod
    async def _try_send(websocket: WebSocket, payload: dict[str, Any]) -> bool:
        try:
            await websocket.send_json(payload)
        except (WebSocketDisconnect, RuntimeError, OSError):
            return False
        return True
