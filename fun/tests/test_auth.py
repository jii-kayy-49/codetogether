from dataclasses import replace

from fastapi.testclient import TestClient

from backend.config import load_settings
from backend.main import create_app


def make_client() -> TestClient:
    return TestClient(create_app(load_settings()))


def test_private_dashboard_requires_authentication() -> None:
    with make_client() as client:
        response = client.get("/dashboard", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        room_response = client.get("/room", follow_redirects=False)
        assert room_response.status_code == 303
        assert room_response.headers["location"] == "/"
        assert client.get("/api/session").status_code == 401


def test_authenticated_user_can_open_room() -> None:
    with make_client() as client:
        login = client.post(
            "/api/auth/login",
            json={
                "username": "test-friend-1",
                "password": "test-password-1",
            },
        )
        assert login.status_code == 200

        room = client.get("/room")
        assert room.status_code == 200
        assert "CODING-ROOM-001" in room.text
        assert "Shared screens" in room.text
        assert "Share Browser Tab" in room.text
        assert "HackerRank" not in room.text
        assert "GeeksforGeeks" not in room.text
        assert "LeetCode" not in room.text
        assert "platform-frame" not in room.text
        assert "<iframe" not in room.text
        assert "Connect to the room chat" in room.text


def test_room_html_is_not_exposed_as_a_static_file() -> None:
    with make_client() as client:
        assert client.get("/static/room.html").status_code == 404


def test_login_session_and_logout() -> None:
    with make_client() as client:
        response = client.post(
            "/api/auth/login",
            json={
                "username": "test-friend-1",
                "password": "test-password-1",
            },
        )
        assert response.status_code == 200
        cookie = response.headers["set-cookie"]
        assert "httponly" in cookie.lower()
        assert "samesite=lax" in cookie.lower()
        assert "max-age=28800" in cookie.lower()
        assert client.get("/dashboard").status_code == 200

        session = client.get("/api/session")
        assert session.status_code == 200
        assert session.json() == {
            "authenticated": True,
            "username": "test-friend-1",
            "users": ["test-friend-1", "test-friend-2", "test-friend-3"],
        }

        logout = client.post("/api/auth/logout")
        assert logout.status_code == 200
        assert client.get("/api/session").status_code == 401
        assert client.get("/dashboard", follow_redirects=False).status_code == 303


def test_secure_session_cookie_sets_secure_attribute() -> None:
    settings = replace(load_settings(), cookie_secure=True)
    with TestClient(create_app(settings)) as client:
        response = client.post(
            "/api/auth/login",
            json={
                "username": "test-friend-1",
                "password": "test-password-1",
            },
        )

    assert response.status_code == 200
    assert "secure" in response.headers["set-cookie"].lower()


def test_invalid_credentials_do_not_create_a_session() -> None:
    with make_client() as client:
        response = client.post(
            "/api/auth/login",
            json={"username": "test-friend-1", "password": "wrong-password"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "Invalid username or password."
        assert client.get("/api/session").status_code == 401


def test_registration_route_does_not_exist() -> None:
    with make_client() as client:
        assert client.post("/api/auth/register").status_code == 404


def test_dashboard_html_is_not_exposed_as_a_static_file() -> None:
    with make_client() as client:
        assert client.get("/static/dashboard.html").status_code == 404
