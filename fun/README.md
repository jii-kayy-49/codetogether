# CodeTogether

CodeTogether is a private collaboration room for exactly three configured accounts. It uses FastAPI, vanilla HTML/CSS/JavaScript, authenticated WebSockets, browser-to-browser WebRTC, and a local SQLite file for chat history. There is no registration, question bank, or code execution feature.

## Features and limits

- Three predefined accounts, scrypt password verification, and signed eight-hour sessions.
- Protected dashboard and coding room, with logout and session validation.
- HackerRank, GeeksforGeeks, and LeetCode links with an iframe attempt and new-tab fallback.
- SQLite-persisted chat history, limited to the most recent 100 messages. Online presence remains in memory and resets on restart.
- A WebRTC mesh lets each online participant connect to the other two. Tab capture starts only after a click on **Share Coding Tab**.
- Chat permits multiple tabs for an account; screen signaling supports one active room session per account, and a newer session replaces the previous signaling socket.
- Screen capture is accepted only when the browser reports `displaySurface: "browser"`. The browser controls its own source picker; the application cannot force a particular site tab or inspect its contents. Unsupported or unverifiable source types are stopped rather than falling back to a window or monitor.
- Screen media is peer-to-peer. The application server handles signaling only; streams are not recorded or stored by it.

The project is intended for three trusted friends, not as a public multi-tenant service.

## Requirements and local setup

Requires Python 3.12 or newer.

From the `fun` directory, create and activate a virtual environment, install dependencies, and create `.env`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set unique usernames, strong individual passwords, and a fresh random session secret. Generate a secret with:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

For localhost over HTTP, set `COOKIE_SECURE=false`. On Windows, double-click `start_codetogether.bat` or run it from PowerShell. It creates `.venv` and installs dependencies on first use, then starts the local server. If you change `requirements.txt` later, update the venv with `.\.venv\Scripts\python.exe -m pip install -r requirements.txt`.

To start manually from `fun`:

```powershell
python -m uvicorn backend.main:app --reload
```

Open `http://127.0.0.1:8000`. Do not use `--reload` for deployment. `.env` is ignored by Git; do not commit it or share its contents. Changing `SESSION_SECRET` invalidates all existing sessions.

## Environment variables

| Variable | Required | Purpose |
|---|---:|---|
| `CODETOGETHER_USERNAME_1` / `_2` / `_3` | Yes | Three distinct login usernames. |
| `CODETOGETHER_PASSWORD_1` / `_2` / `_3` | Yes | Passwords for the corresponding accounts. They are scrypt-hashed in memory at startup. |
| `SESSION_SECRET` | Yes | Unique random signing secret, at least 32 characters. |
| `COOKIE_SECURE` | Yes in deployment | `true` behind HTTPS; use `false` only for localhost HTTP development. The default is `true`. |
| `TURN_URLS` | Optional | Comma-separated `turn:` or `turns:` relay URLs. |
| `TURN_USERNAME` | Optional with TURN | TURN username; configure all three TURN variables together. |
| `TURN_CREDENTIAL` | Optional with TURN | TURN password/credential; prefer short-lived credentials from the TURN provider. |

The authenticated `/api/webrtc-config` endpoint returns the configured ICE servers to logged-in users so their browsers can connect to TURN. Do not put TURN credentials in frontend files or public repositories.

## Security and session behavior

- Session cookies are signed, `HttpOnly`, `SameSite=Lax`, expire after eight hours, and use `Secure` when `COOKIE_SECURE=true`. Session contents are signed, not encrypted; only the username is stored in them.
- WebSocket endpoints require the signed session and an exact same-origin `Origin` check. A claimed username from the client is never used as identity.
- The HTTP responses include a restrictive Content Security Policy and anti-framing/content-type/referrer headers. Non-static responses are marked `Cache-Control: no-store`.
- Chat message text is validated and rendered using text nodes. Chat WebSocket payloads and signaling payloads are size-limited; SDP and ICE fields are validated before routing.
- SQLite stores only chat message IDs, usernames, text, and timestamps. Passwords, password hashes, sessions, and presence are not stored in the database.
- There is no public registration or persistent account storage. Keep the database file private, keep the service reachable only by the intended users, and use HTTPS outside localhost.

## SQLite chat history

The chat database is `codetogether.sqlite3` in the `fun` directory. It and its SQLite journal files are excluded by `.gitignore`. The file and table are created the first time an authenticated room WebSocket connects. Only accepted chat messages are written; presence join/leave events are still temporary. The database retains the latest 100 chat messages, which are loaded for new room connections and survive application restarts.

Keep this file private because it contains chat text. To permanently erase the chat history, stop the server and delete `codetogether.sqlite3` (and any `codetogether.sqlite3-*` journal files). Do not delete the database while the app is running. SQLite is local; run a single Uvicorn worker/instance as described below.

## Local-network deployment

On the host, run the app bound to the LAN interface:

```powershell
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --ws-max-size 131072
```

Allow inbound TCP port 8000 only on the trusted private network in the host firewall, then users can browse to `http://HOST-LAN-IP:8000`.

**This plain-HTTP option is for temporary trusted-network testing only.** HTTP exposes session cookies to network observers when `COOKIE_SECURE=false`; also, browsers generally do not permit screen capture on a LAN IP over plain HTTP. For reliable screen sharing and protected credentials, terminate HTTPS on the LAN using a trusted local certificate/reverse proxy, set `COOKIE_SECURE=true`, and use the HTTPS hostname from all three devices. Keep the Uvicorn port restricted to the host/reverse proxy.

The Windows `start_codetogether.bat` launcher binds to the LAN interfaces and prints the configured example address `http://10.2.10.21:8000`. Replace that address in the batch file if the host's LAN IP changes. Do not configure router port forwarding for this local-network launcher.

## Public deployment

Do not expose Uvicorn directly to the internet. Use a maintained reverse proxy such as Caddy or Nginx to terminate HTTPS and proxy HTTP and WebSocket upgrade traffic to Uvicorn on loopback. Keep `.env` in a restricted deployment environment, use strong distinct passwords, set `COOKIE_SECURE=true`, and expose only the proxy's HTTPS port. Use a firewall and keep Python dependencies and the host patched.

The application has no multi-factor authentication or login rate limiter. Prefer a private VPN or a reverse-proxy IP allowlist for a three-friend deployment; if the login is reachable from the public internet, restrict access at the network/proxy layer rather than treating the three accounts as public sign-ups.

Example Uvicorn command behind a reverse proxy on the same machine:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --workers 1 --ws-max-size 131072 --proxy-headers --forwarded-allow-ips=127.0.0.1
```

Example minimal Caddy site (replace the hostname with a domain whose DNS points to this host):

```text
codetogether.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

Caddy can obtain and renew a public TLS certificate when the domain and firewall/DNS are configured correctly. Allow inbound TCP 443 (and usually TCP 80 for certificate validation/redirects); do not allow public access to port 8000. Configure the reverse proxy to preserve WebSocket upgrades and forward the original scheme. `--forwarded-allow-ips` must list only the trusted proxy address(es), never `*` on a public interface. If the proxy is on a different host, use its exact trusted address and a private/firewalled upstream.

### Firewall and TURN ports

- Users need HTTPS to the application proxy (normally TCP 443). HTTP TCP 80 may be used for HTTPS redirects or certificate validation.
- Uvicorn TCP 8000 is an internal upstream port and should not be publicly reachable.
- Peer WebRTC media is not sent through Uvicorn. Permit the users' networks to make outbound ICE connectivity attempts; restrictive networks may need a TURN relay.
- TURN commonly uses UDP/TCP 3478, TLS 5349, and a provider/server-configured UDP relay range. Open only the ports and relay range specified by the chosen TURN provider, and configure the corresponding `TURN_*` environment values. Providers differ; STUN alone does not guarantee connectivity.

## Performance and topology

Each user maintains up to two peer connections. A sharer's browser sends its screen stream separately to the other two users; with all three sharing, each browser uploads two outgoing copies and receives two streams. If each stream averages bitrate **B**, a participant's approximate screen-share traffic is about `2B` upload and `2B` download, excluding protocol overhead and retransmissions. Actual bitrate, CPU use, and memory use depend on the browser, source, resolution, content, and network.

Capture requests target an ideal maximum of 1280x720 at 15–20 fps with no audio, but browser implementations may choose different settings. The server relays signaling only; presence is in memory and recent chat is in SQLite. Run exactly one Uvicorn worker/instance: presence and signaling state are process-local. The repository has not been benchmarked with three real simultaneous shares; verify CPU, memory, and network usage on the intended devices and connection before relying on it.

## Manual three-browser checklist

Use three separate browser profiles/devices and distinct configured accounts:

1. Sign in as User 1 in Chrome, User 2 in Edge, and User 3 in an Incognito profile. Confirm all three appear online.
2. Send chat messages from each client; confirm delivery, usernames, timestamps, and safe rendering of text such as `<script>`.
3. Open a separate HackerRank tab for User 1, LeetCode tab for User 2, and GeeksforGeeks tab for User 3.
4. Click **Share Coding Tab** in each room and choose the matching website tab in the browser picker. Confirm each participant sees both other users' streams.
5. Stop one share with the room button and another using the browser's native stop control. Confirm the remaining streams continue independently.
6. Attempt to select a window/monitor if the browser offers one; confirm the app stops it and reports that it will not fall back.
7. Disconnect one client/network briefly, restore it, and confirm presence, signaling, and peer connections recover. Refresh a participant and confirm its prior share ends cleanly.
8. Open two room tabs for one account. Confirm chat presence remains online; confirm the newer tab owns signaling, and that closing it cleans up sharing.
9. Restart the server and confirm the last 100 chat messages remain available while presence resets and clients reconnect after signing in as needed.
10. Repeat on the actual home/office networks. If direct ICE fails, add TURN credentials and verify relay connectivity.

Automated tests cover authentication, protected routes, chat limits/history, signaling validation/routing/cleanup, configuration, and response headers. They do **not** prove real browser-to-browser WebRTC media, three simultaneous streams, or deployment-network connectivity.

## Troubleshooting

- **Cannot sign in / server exits at startup:** verify all three usernames and passwords are present, usernames are distinct, and `SESSION_SECRET` is a fresh value of at least 32 characters.
- **Session not retained over HTTPS:** ensure `COOKIE_SECURE=true`, the browser accesses the HTTPS hostname, and the proxy forwards the original scheme. Clear old cookies after changing the session secret or cookie settings.
- **WebSocket rejected:** use the same host and scheme for the page and WebSocket, allow WebSocket upgrades at the proxy, and preserve the `Origin` header. The app rejects cross-origin WebSocket requests.
- **Tab share unavailable:** use HTTPS (or localhost), a browser with `getDisplayMedia`, and choose a browser tab. If `displaySurface` cannot be verified or reports a window/monitor, the app intentionally stops capture.
- **Peer is connected but video does not arrive:** check outbound UDP/ICE/firewall policies and add a supported TURN relay. A successful signaling connection does not prove media connectivity.
- **External coding page is blank:** the site may disallow embedding. Use **Open in new tab**; the app does not bypass the site's frame policy.
- **Sharing uses too much bandwidth/CPU:** stop unneeded shares, use a lower-resolution browser source, or test a less demanding network/device. The project does not include a media server or central transcoder.
- **Chat history is unavailable:** check that the server can create/write `codetogether.sqlite3` in the `fun` directory and that no other process is locking the file. The app logs database errors rather than silently dropping a message.
- **Presence differs between users or disappears:** keep one application process/worker. Presence is temporary and resets when that process restarts; chat history is retained in SQLite.

## Tests

From the `fun` directory:

```powershell
python -m pytest -q
```
