from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from backend.config import load_settings
from backend.main import create_app


def make_client(chat_database_path: Path) -> TestClient:
    return TestClient(
        create_app(load_settings(), chat_database_path=chat_database_path)
    )


def login(client: TestClient, account_number: int) -> None:
    response = client.post(
        "/api/auth/login",
        json={
            "username": f"test-friend-{account_number}",
            "password": f"test-password-{account_number}",
        },
    )
    assert response.status_code == 200


def websocket_connect(
    client: TestClient,
    path: str = "/ws/room",
    origin: str = "http://testserver",
) -> WebSocketTestSession:
    return client.websocket_connect(path, headers={"origin": origin})


def test_authenticated_websocket_receives_room_state_and_join_event(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path / "chat.sqlite3") as client:
        login(client, 1)
        with websocket_connect(client) as websocket:
            state = websocket.receive_json()
            joined = websocket.receive_json()

            assert state["room_id"] == "CODING-ROOM-001"
            assert state["users"] == [
                {"username": "test-friend-1", "online": True},
                {"username": "test-friend-2", "online": False},
                {"username": "test-friend-3", "online": False},
            ]
            assert joined["type"] == "member_joined"
            assert joined["username"] == "test-friend-1"
            assert joined["id"]
            assert joined["timestamp"]


def test_unauthenticated_and_invalid_session_websockets_are_rejected(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path / "chat.sqlite3") as client:
        with pytest.raises(WebSocketDisconnect) as unauthenticated:
            with websocket_connect(client):
                pass
        assert unauthenticated.value.code == 4401

        client.cookies.set("codetogether_session", "tampered-session-cookie")
        with pytest.raises(WebSocketDisconnect) as invalid_session:
            with websocket_connect(client):
                pass
        assert invalid_session.value.code == 4401

        login(client, 1)
        with pytest.raises(WebSocketDisconnect) as invalid_origin:
            with websocket_connect(
                client, origin="https://untrusted.example"
            ):
                pass
        assert invalid_origin.value.code == 4403


def test_chat_broadcast_uses_authenticated_username_not_client_claim(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path / "chat.sqlite3") as client:
        login(client, 1)
        with websocket_connect(client) as first:
            first.receive_json()
            first.receive_json()

            login(client, 2)
            with websocket_connect(
                client,
                "/ws/room?username=test-friend-3"
            ) as second:
                second.receive_json()
                assert second.receive_json()["type"] == "member_joined"
                assert first.receive_json()["username"] == "test-friend-2"

                second.send_json(
                    {
                        "type": "chat_message",
                        "username": "test-friend-3",
                        "message": "Let's solve Two Sum",
                    }
                )
                first_message = first.receive_json()
                second_message = second.receive_json()

                assert first_message == second_message
                assert first_message["type"] == "chat_message"
                assert first_message["username"] == "test-friend-2"
                assert first_message["message"] == "Let's solve Two Sum"
                assert first_message["id"]
                assert first_message["timestamp"]


def test_empty_and_overlong_messages_are_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path / "chat.sqlite3") as client:
        login(client, 1)
        with websocket_connect(client) as websocket:
            websocket.receive_json()
            websocket.receive_json()

            websocket.send_json({"type": "chat_message", "message": "  \n "})
            empty_error = websocket.receive_json()
            assert empty_error["type"] == "error"
            assert empty_error["code"] == "empty_message"

            websocket.send_json({"type": "chat_message", "message": "x" * 2000})
            accepted = websocket.receive_json()
            assert accepted["type"] == "chat_message"
            assert len(accepted["message"]) == 2000

            websocket.send_json({"type": "chat_message", "message": "x" * 2001})
            length_error = websocket.receive_json()
            assert length_error["type"] == "error"
            assert length_error["code"] == "message_too_long"

            websocket.send_text("{")
            malformed_error = websocket.receive_json()
            assert malformed_error["type"] == "error"
            assert malformed_error["code"] == "invalid_json"

            websocket.send_text(" " * 8193 + '{"type":"chat_message"}')
            payload_error = websocket.receive_json()
            assert payload_error["type"] == "error"
            assert payload_error["code"] == "message_too_large"


def test_join_and_leave_notifications_and_duplicate_connection_presence(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path / "chat.sqlite3") as client:
        login(client, 1)
        with websocket_connect(client) as first:
            first.receive_json()
            first.receive_json()

            with websocket_connect(client) as duplicate:
                duplicate_state = duplicate.receive_json()
                assert duplicate_state["users"][0]["online"] is True
                duplicate.close()

            login(client, 2)
            with websocket_connect(client) as second:
                second_state = second.receive_json()
                assert second_state["users"] == [
                    {"username": "test-friend-1", "online": True},
                    {"username": "test-friend-2", "online": True},
                    {"username": "test-friend-3", "online": False},
                ]
                second_join = second.receive_json()
                first_join = first.receive_json()
                assert second_join["type"] == "member_joined"
                assert first_join["type"] == "member_joined"
                assert first_join["username"] == "test-friend-2"

            left = first.receive_json()
            assert left["type"] == "member_left"
            assert left["username"] == "test-friend-2"


def test_only_three_configured_accounts_are_listed_in_room_presence(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path / "chat.sqlite3") as client:
        login(client, 1)
        with websocket_connect(client) as first:
            first.receive_json()
            first.receive_json()
            login(client, 2)
            with websocket_connect(client) as second:
                second.receive_json()
                second.receive_json()
                first.receive_json()
                login(client, 3)
                with websocket_connect(client) as third:
                    state = third.receive_json()
                    assert [user["username"] for user in state["users"]] == [
                        "test-friend-1",
                        "test-friend-2",
                        "test-friend-3",
                    ]
                    assert all(user["online"] for user in state["users"])
                    rejected_account = client.post(
                        "/api/auth/login",
                        json={
                            "username": "not-configured",
                            "password": "not-a-password",
                        },
                    )
                    assert rejected_account.status_code == 401


def test_recent_chat_history_is_limited_to_100_and_persisted(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "chat.sqlite3"
    with make_client(database_path) as client:
        login(client, 1)
        with websocket_connect(client) as first:
            first.receive_json()
            first.receive_json()
            for index in range(101):
                first.send_json(
                    {"type": "chat_message", "message": f"message {index}"}
                )
                assert first.receive_json()["message"] == f"message {index}"

            login(client, 2)
            with websocket_connect(client) as second:
                state = second.receive_json()
                history = state["history"]
                assert len(history) == 100
                assert history[0]["message"] == "message 1"
                assert history[-1]["message"] == "message 100"
                second.receive_json()

    restarted_app_client = make_client(database_path)
    with restarted_app_client:
        login(restarted_app_client, 1)
        with websocket_connect(restarted_app_client) as websocket:
            state = websocket.receive_json()
            assert len(state["history"]) == 100
            assert state["history"][0]["message"] == "message 1"
            assert state["history"][-1]["message"] == "message 100"
