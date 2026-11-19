from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from backend.config import load_settings
from backend.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app(load_settings()))


def login(client: TestClient, account_number: int) -> None:
    response = client.post(
        "/api/auth/login",
        json={
            "username": f"test-friend-{account_number}",
            "password": f"test-password-{account_number}",
        },
    )
    assert response.status_code == 200


def connect_signaling(
    client: TestClient,
    origin: str = "http://testserver",
) -> WebSocketTestSession:
    return client.websocket_connect("/ws/signaling", headers={"origin": origin})


def test_signaling_requires_valid_session_and_same_origin() -> None:
    with make_client() as client:
        with pytest.raises(WebSocketDisconnect) as unauthenticated:
            with connect_signaling(client):
                pass
        assert unauthenticated.value.code == 4401

        client.cookies.set("codetogether_session", "tampered-session-cookie")
        with pytest.raises(WebSocketDisconnect) as invalid_session:
            with connect_signaling(client):
                pass
        assert invalid_session.value.code == 4401

        login(client, 1)
        with pytest.raises(WebSocketDisconnect) as invalid_origin:
            with connect_signaling(client, "https://untrusted.example"):
                pass
        assert invalid_origin.value.code == 4403

        with pytest.raises(WebSocketDisconnect) as missing_origin:
            with client.websocket_connect("/ws/signaling"):
                pass
        assert missing_origin.value.code == 4403


def test_signaling_identity_is_session_derived_and_routes_to_target() -> None:
    app = create_app(load_settings())
    with TestClient(app) as client:
        login(client, 1)
        with connect_signaling(client) as alice:
            alice_state = alice.receive_json()
            assert alice_state["participants"][0] == {
                "username": "test-friend-1",
                "online": True,
            }

            login(client, 2)
            with connect_signaling(client) as bob:
                bob_state = bob.receive_json()
                assert bob_state["participants"][:2] == [
                    {"username": "test-friend-1", "online": True},
                    {"username": "test-friend-2", "online": True},
                ]
                joined = alice.receive_json()
                assert joined["type"] == "peer_joined"
                assert joined["username"] == "test-friend-2"

                alice.send_json(
                    {
                        "type": "webrtc_signal",
                        "target": "test-friend-2",
                        "username": "test-friend-3",
                        "signal": {"type": "offer", "sdp": "v=0\r\n"},
                    }
                )
                routed = bob.receive_json()
                assert routed == {
                    "type": "webrtc_signal",
                    "from": "test-friend-1",
                    "signal": {"type": "offer", "sdp": "v=0\r\n"},
                }


def test_invalid_signaling_payloads_are_rejected() -> None:
    with make_client() as client:
        login(client, 1)
        with connect_signaling(client) as websocket:
            websocket.receive_json()

            websocket.send_json(
                {
                    "type": "webrtc_signal",
                    "target": "not-configured",
                    "signal": {"type": "offer", "sdp": "v=0"},
                }
            )
            assert websocket.receive_json()["code"] == "invalid_target"

            websocket.send_json(
                {
                    "type": "webrtc_signal",
                    "target": "test-friend-2",
                    "signal": {"type": "offer", "sdp": ""},
                }
            )
            assert websocket.receive_json()["code"] == "invalid_signal"

            websocket.send_json({"type": "unsupported_event"})
            assert websocket.receive_json()["code"] == "invalid_event"

            websocket.send_text("{")
            assert websocket.receive_json()["code"] == "invalid_json"

            websocket.send_text(" " * 131_073)
            assert websocket.receive_json()["code"] == "message_too_large"


def test_sharing_broadcast_and_disconnect_cleanup() -> None:
    app = create_app(load_settings())
    with TestClient(app) as client:
        login(client, 1)
        with connect_signaling(client) as alice:
            alice.receive_json()
            login(client, 2)
            with connect_signaling(client) as bob:
                bob.receive_json()
                alice.receive_json()

                bob.send_json({"type": "screen_share_started"})
                started_for_bob = bob.receive_json()
                started_for_alice = alice.receive_json()
                assert started_for_bob == started_for_alice
                assert started_for_alice["type"] == "screen_share_started"
                assert started_for_alice["username"] == "test-friend-2"

            stopped = alice.receive_json()
            left = alice.receive_json()
            assert stopped["type"] == "screen_share_stopped"
            assert stopped["username"] == "test-friend-2"
            assert left["type"] == "peer_left"
            assert left["username"] == "test-friend-2"


def test_duplicate_signaling_connection_replaces_old_socket_without_false_leave() -> None:
    app = create_app(load_settings())
    with TestClient(app) as client:
        login(client, 1)
        with connect_signaling(client) as original:
            original.receive_json()
            login(client, 2)
            with connect_signaling(client) as observer:
                observer.receive_json()
                original.receive_json()

                login(client, 1)
                with connect_signaling(client) as replacement:
                    replacement.receive_json()
                    reconnected = observer.receive_json()
                    assert reconnected["type"] == "peer_reconnected"
                    assert reconnected["username"] == "test-friend-1"
                    with pytest.raises(WebSocketDisconnect) as replaced:
                        original.receive_json()
                    assert replaced.value.code == 4410

                left = observer.receive_json()
                assert left["type"] == "peer_left"
                assert left["username"] == "test-friend-1"


def test_webrtc_config_is_protected() -> None:
    with make_client() as client:
        assert client.get("/api/webrtc-config").status_code == 401
        login(client, 1)
        response = client.get("/api/webrtc-config")
        assert response.status_code == 200
        assert response.json() == {
            "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
        }


def test_http_responses_have_security_headers_and_authenticated_pages_are_not_cached() -> None:
    with make_client() as client:
        response = client.get("/")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["cache-control"] == "no-store"


def test_authenticated_webrtc_config_includes_optional_turn_service() -> None:
    settings = replace(
        load_settings(),
        turn_urls=("turn:relay.example:3478",),
        turn_username="short-lived-user",
        turn_credential="short-lived-credential",
    )
    with TestClient(create_app(settings)) as client:
        login(client, 1)
        response = client.get("/api/webrtc-config")

    assert response.status_code == 200
    assert response.json()["iceServers"] == [
        {"urls": ["stun:stun.l.google.com:19302"]},
        {
            "urls": ["turn:relay.example:3478"],
            "username": "short-lived-user",
            "credential": "short-lived-credential",
        },
    ]
