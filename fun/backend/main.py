from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware

from .auth import AccountStore
from .chat_store import ChatHistoryStore
from .config import PROJECT_ROOT, Settings, load_settings
from .signaling_manager import SignalingManager
from .websocket_manager import ConnectionManager


FRONTEND_ROOT = PROJECT_ROOT / "frontend"
SESSION_MAX_AGE_SECONDS = 8 * 60 * 60
logger = logging.getLogger(__name__)


class LoginRequest(BaseModel):
    username: Annotated[str, Field(min_length=1, max_length=80)]
    password: Annotated[str, Field(min_length=1, max_length=1024)]


def is_same_origin_websocket(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("host")
    if not origin or not host:
        return False

    scheme = "https" if websocket.scope.get("scheme") == "wss" else "http"
    try:
        origin_parts = urlsplit(origin)
        host_parts = urlsplit(f"//{host}")
        origin_port = origin_parts.port or (443 if scheme == "https" else 80)
        host_port = host_parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        return False

    return (
        origin_parts.scheme.lower() == scheme
        and origin_parts.hostname is not None
        and origin_parts.hostname.lower() == (host_parts.hostname or "").lower()
        and origin_port == host_port
        and not origin_parts.username
        and not origin_parts.password
        and origin_parts.path in ("", "/")
        and not origin_parts.query
        and not origin_parts.fragment
    )


def create_app(
    settings: Settings | None = None,
    *,
    chat_database_path: Path | None = None,
) -> FastAPI:
    configured_settings = settings or load_settings()
    accounts = AccountStore(configured_settings.accounts)
    history_store = ChatHistoryStore(
        chat_database_path or PROJECT_ROOT / "codetogether.sqlite3"
    )
    connections = ConnectionManager(accounts.usernames, history_store)
    signaling = SignalingManager(accounts.usernames)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            history_store.close()

    app = FastAPI(title="CodeTogether", lifespan=lifespan)
    app.state.accounts = accounts
    app.state.chat_history_store = history_store
    app.state.websocket_manager = connections
    app.state.signaling_manager = signaling

    @app.middleware("http")
    async def add_security_headers(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), display-capture=(self)",
        )
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'self'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; script-src 'self'; "
            "style-src 'self'; img-src 'self' data:; "
            "connect-src 'self' ws: wss:; frame-src https:",
        )
        if not request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    app.add_middleware(
        SessionMiddleware,
        secret_key=configured_settings.session_secret,
        session_cookie="codetogether_session",
        max_age=SESSION_MAX_AGE_SECONDS,
        same_site="lax",
        https_only=configured_settings.cookie_secure,
    )
    app.mount(
        "/static/css",
        StaticFiles(directory=FRONTEND_ROOT / "css"),
        name="css",
    )
    app.mount(
        "/static/js",
        StaticFiles(directory=FRONTEND_ROOT / "js"),
        name="js",
    )

    def authenticated_username(request: Request) -> str:
        username = request.session.get("username")
        if not isinstance(username, str) or username not in accounts.usernames:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required.",
            )
        return username

    @app.get("/", response_class=HTMLResponse)
    async def login_page(request: Request) -> Response:
        if request.session.get("username") in accounts.usernames:
            return RedirectResponse("/dashboard", status_code=status.HTTP_303_SEE_OTHER)
        return FileResponse(FRONTEND_ROOT / "login.html")

    @app.get("/dashboard", response_class=HTMLResponse)
    async def dashboard_page(request: Request) -> Response:
        try:
            authenticated_username(request)
        except HTTPException:
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        return FileResponse(FRONTEND_ROOT / "dashboard.html")

    @app.get("/room", response_class=HTMLResponse)
    async def room_page(request: Request) -> Response:
        try:
            authenticated_username(request)
        except HTTPException:
            return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)
        return FileResponse(FRONTEND_ROOT / "room.html")

    @app.get("/api/session")
    async def get_session(request: Request) -> dict[str, object]:
        username = authenticated_username(request)
        return {
            "authenticated": True,
            "username": username,
            "users": accounts.usernames,
        }

    @app.get("/api/webrtc-config")
    async def get_webrtc_config(request: Request) -> dict[str, object]:
        authenticated_username(request)
        ice_servers: list[dict[str, object]] = [
            {"urls": ["stun:stun.l.google.com:19302"]}
        ]
        if configured_settings.turn_urls:
            ice_servers.append(
                {
                    "urls": list(configured_settings.turn_urls),
                    "username": configured_settings.turn_username,
                    "credential": configured_settings.turn_credential,
                }
            )
        return {"iceServers": ice_servers}

    @app.post("/api/auth/login")
    async def login(payload: LoginRequest, request: Request) -> dict[str, str]:
        if not accounts.authenticate(payload.username, payload.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid username or password.",
            )
        request.session.clear()
        request.session["username"] = payload.username
        return {"username": payload.username}

    @app.post("/api/auth/logout")
    async def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"logged_out": True}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.websocket("/ws/room")
    async def room_websocket(websocket: WebSocket) -> None:
        if not is_same_origin_websocket(websocket):
            await websocket.close(code=4403, reason="Invalid origin.")
            return

        session = websocket.scope.get("session")
        username = session.get("username") if isinstance(session, dict) else None
        if not isinstance(username, str):
            await websocket.close(code=4401, reason="Authentication required.")
            return
        if username not in accounts.usernames:
            await websocket.close(code=4403, reason="Account is not permitted.")
            return

        if not await connections.connect(websocket, username):
            return

        try:
            while True:
                raw_message = await websocket.receive_text()
                await connections.handle_text(websocket, username, raw_message)
        except WebSocketDisconnect:
            pass
        except (RuntimeError, OSError):
            logger.debug("WebSocket transport ended for %s.", username, exc_info=True)
        finally:
            await connections.disconnect(websocket)

    @app.websocket("/ws/signaling")
    async def signaling_websocket(websocket: WebSocket) -> None:
        if not is_same_origin_websocket(websocket):
            await websocket.close(code=4403, reason="Invalid origin.")
            return

        session = websocket.scope.get("session")
        username = session.get("username") if isinstance(session, dict) else None
        if not isinstance(username, str):
            await websocket.close(code=4401, reason="Authentication required.")
            return
        if username not in accounts.usernames:
            await websocket.close(code=4403, reason="Account is not permitted.")
            return

        if not await signaling.connect(websocket, username):
            return

        try:
            while True:
                raw_message = await websocket.receive_text()
                await signaling.handle_text(websocket, username, raw_message)
        except WebSocketDisconnect:
            pass
        except (RuntimeError, OSError):
            logger.debug(
                "Signaling WebSocket transport ended for %s.", username, exc_info=True
            )
        finally:
            await signaling.disconnect(websocket)

    return app


app = create_app()
