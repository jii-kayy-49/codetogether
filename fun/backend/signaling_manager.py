import asyncio
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect


ROOM_ID = "CODING-ROOM-001"
MAX_ROOM_USERS = 3
MAX_SIGNAL_MESSAGE_LENGTH = 131_072
MAX_SDP_LENGTH = 65_536
MAX_CANDIDATE_LENGTH = 8_192


class SignalingManager:
    def __init__(self, usernames: tuple[str, ...]) -> None:
        if len(usernames) != MAX_ROOM_USERS or len(set(usernames)) != MAX_ROOM_USERS:
            raise ValueError("The room requires exactly three unique usernames.")

        self.usernames = usernames
        self._connections: dict[str, WebSocket] = {}
        self._socket_users: dict[WebSocket, str] = {}
        self._sharing: set[str] = set()
        self._lock = asyncio.Lock()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _event_id() -> str:
        return uuid4().hex

    def _event(self, event_type: str, username: str) -> dict[str, str]:
        return {
            "id": self._event_id(),
            "type": event_type,
            "username": username,
            "timestamp": self._timestamp(),
        }

    def _room_state(self) -> dict[str, object]:
        return {
            "type": "signaling_state",
            "room_id": ROOM_ID,
            "participants": [
                {"username": username, "online": username in self._connections}
                for username in self.usernames
            ],
            "sharing_users": sorted(self._sharing),
        }

    async def connect(self, websocket: WebSocket, username: str) -> bool:
        if username not in self.usernames:
            await websocket.close(code=4403, reason="Account is not permitted.")
            return False

        failed_connections: list[WebSocket] = []
        async with self._lock:
            previous = self._connections.get(username)
            await websocket.accept()
            self._connections[username] = websocket
            self._socket_users[websocket] = username
            was_sharing = username in self._sharing
            self._sharing.discard(username)

            try:
                await websocket.send_json(self._room_state())
            except (WebSocketDisconnect, RuntimeError, OSError):
                if previous is None:
                    self._connections.pop(username, None)
                else:
                    self._connections[username] = previous
                    if was_sharing:
                        self._sharing.add(username)
                self._socket_users.pop(websocket, None)
                return False

            if previous is not None:
                self._socket_users.pop(previous, None)
                try:
                    await previous.close(
                        code=4410, reason="A newer signaling session replaced this one."
                    )
                except (WebSocketDisconnect, RuntimeError, OSError):
                    pass

            recipients = self._other_connections(websocket)
            if was_sharing:
                stopped = self._event("screen_share_stopped", username)
                failed_connections.extend(
                    await self._send_to_connections_locked(stopped, recipients)
                )

            connection_event = self._event(
                "peer_reconnected" if previous is not None else "peer_joined",
                username,
            )
            failed_connections.extend(
                await self._send_to_connections_locked(connection_event, recipients)
            )

        for failed in failed_connections:
            await self.disconnect(failed)
        return True

    async def disconnect(self, websocket: WebSocket) -> None:
        failed_connections: list[WebSocket] = []
        async with self._lock:
            username = self._socket_users.pop(websocket, None)
            if username is None or self._connections.get(username) is not websocket:
                return

            self._connections.pop(username, None)
            recipients = list(self._connections.values())
            if username in self._sharing:
                self._sharing.remove(username)
                stopped = self._event("screen_share_stopped", username)
                failed_connections.extend(
                    await self._send_to_connections_locked(stopped, recipients)
                )

            left = self._event("peer_left", username)
            failed_connections.extend(
                await self._send_to_connections_locked(left, recipients)
            )

        for failed in failed_connections:
            await self.disconnect(failed)

    async def handle_text(
        self, websocket: WebSocket, username: str, raw_message: str
    ) -> None:
        if len(raw_message) > MAX_SIGNAL_MESSAGE_LENGTH:
            await self._send_error(
                websocket, "message_too_large", "Signaling message is too large."
            )
            return

        try:
            payload = json.loads(raw_message)
        except (json.JSONDecodeError, RecursionError):
            await self._send_error(
                websocket, "invalid_json", "Signaling messages must be valid JSON."
            )
            return

        if not isinstance(payload, dict):
            await self._send_error(
                websocket, "invalid_event", "Signaling event must be a JSON object."
            )
            return

        if payload.get("type") == "webrtc_signal":
            await self._route_signal(websocket, username, payload)
        elif payload.get("type") in {"screen_share_started", "screen_share_stopped"}:
            await self._set_sharing(
                websocket,
                username,
                payload["type"] == "screen_share_started",
            )
        elif payload.get("type") == "peer_restart":
            await self._route_peer_restart(websocket, username, payload)
        else:
            await self._send_error(
                websocket, "invalid_event", "Unsupported signaling event."
            )

    async def _route_signal(
        self, websocket: WebSocket, username: str, payload: dict[str, Any]
    ) -> None:
        target = payload.get("target")
        if not isinstance(target, str) or target not in self.usernames or target == username:
            await self._send_error(
                websocket, "invalid_target", "Choose another configured participant."
            )
            return

        signal = self._validated_signal(payload.get("signal"))
        if signal is None:
            await self._send_error(
                websocket, "invalid_signal", "The WebRTC signal is invalid."
            )
            return

        failed: WebSocket | None = None
        error: tuple[str, str] | None = None
        async with self._lock:
            if (
                self._socket_users.get(websocket) != username
                or self._connections.get(username) is not websocket
            ):
                return
            recipient = self._connections.get(target)
            if recipient is None:
                error = ("peer_offline", "That participant is not connected.")
            else:
                routed_event = {
                    "type": "webrtc_signal",
                    "from": username,
                    "signal": signal,
                }
                if not await self._try_send(recipient, routed_event):
                    failed = recipient
                    error = ("peer_unavailable", "That participant is unavailable.")

        if failed is not None:
            await self.disconnect(failed)
        if error is not None:
            await self._send_error(websocket, error[0], error[1])

    async def _route_peer_restart(
        self, websocket: WebSocket, username: str, payload: dict[str, Any]
    ) -> None:
        target = payload.get("target")
        if (
            not isinstance(target, str)
            or target not in self.usernames
            or target == username
        ):
            await self._send_error(
                websocket, "invalid_target", "Choose another configured participant."
            )
            return

        failed: WebSocket | None = None
        error: tuple[str, str] | None = None
        async with self._lock:
            if (
                self._socket_users.get(websocket) != username
                or self._connections.get(username) is not websocket
            ):
                return
            recipient = self._connections.get(target)
            if recipient is None:
                error = ("peer_offline", "That participant is not connected.")
            else:
                event = self._event("peer_restart", username)
                if not await self._try_send(recipient, event):
                    failed = recipient
                    error = ("peer_unavailable", "That participant is unavailable.")

        if failed is not None:
            await self.disconnect(failed)
        if error is not None:
            await self._send_error(websocket, error[0], error[1])

    async def _set_sharing(
        self, websocket: WebSocket, username: str, sharing: bool
    ) -> None:
        failed_connections: list[WebSocket] = []
        async with self._lock:
            if (
                self._socket_users.get(websocket) != username
                or self._connections.get(username) is not websocket
            ):
                return

            currently_sharing = username in self._sharing
            if sharing == currently_sharing:
                return
            if sharing:
                self._sharing.add(username)
                event = self._event("screen_share_started", username)
            else:
                self._sharing.discard(username)
                event = self._event("screen_share_stopped", username)
            failed_connections = await self._send_to_connections_locked(
                event, list(self._connections.values())
            )

        for failed in failed_connections:
            await self.disconnect(failed)

    def _other_connections(self, websocket: WebSocket) -> list[WebSocket]:
        return [
            connection
            for connection in self._connections.values()
            if connection is not websocket
        ]

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

    @staticmethod
    async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
        await websocket.send_json(
            {"type": "error", "code": code, "message": message}
        )

    @staticmethod
    def _validated_signal(value: object) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        signal_type = value.get("type")
        if signal_type in {"offer", "answer"}:
            sdp = value.get("sdp")
            if not isinstance(sdp, str) or not sdp or len(sdp) > MAX_SDP_LENGTH:
                return None
            return {"type": signal_type, "sdp": sdp}

        if signal_type != "ice_candidate":
            return None

        candidate = value.get("candidate")
        if candidate is None:
            return {"type": "ice_candidate", "candidate": None}
        if not isinstance(candidate, dict):
            return None

        candidate_text = candidate.get("candidate")
        if (
            not isinstance(candidate_text, str)
            or len(candidate_text) > MAX_CANDIDATE_LENGTH
        ):
            return None

        sdp_mid = candidate.get("sdpMid")
        if sdp_mid is not None and (
            not isinstance(sdp_mid, str) or len(sdp_mid) > 128
        ):
            return None

        sdp_mline_index = candidate.get("sdpMLineIndex")
        if sdp_mline_index is not None and (
            isinstance(sdp_mline_index, bool)
            or not isinstance(sdp_mline_index, int)
            or sdp_mline_index < 0
        ):
            return None

        username_fragment = candidate.get("usernameFragment")
        if username_fragment is not None and (
            not isinstance(username_fragment, str) or len(username_fragment) > 128
        ):
            return None

        return {
            "type": "ice_candidate",
            "candidate": {
                "candidate": candidate_text,
                "sdpMid": sdp_mid,
                "sdpMLineIndex": sdp_mline_index,
                "usernameFragment": username_fragment,
            },
        }
