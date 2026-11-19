import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class AccountConfig:
    username: str
    password: str


@dataclass(frozen=True)
class Settings:
    accounts: tuple[AccountConfig, AccountConfig, AccountConfig]
    session_secret: str
    cookie_secure: bool
    turn_urls: tuple[str, ...] = ()
    turn_username: str = ""
    turn_credential: str = ""


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")

    accounts = []
    for account_number in range(1, 4):
        username = os.getenv(f"CODETOGETHER_USERNAME_{account_number}", "").strip()
        password = os.getenv(f"CODETOGETHER_PASSWORD_{account_number}", "")
        if not username or not password:
            raise RuntimeError(
                "Configure all three CODETOGETHER_USERNAME_n and "
                "CODETOGETHER_PASSWORD_n values in .env."
            )
        accounts.append(AccountConfig(username=username, password=password))

    usernames = [account.username for account in accounts]
    if len(set(usernames)) != 3:
        raise RuntimeError("The three configured usernames must be unique.")

    session_secret = os.getenv("SESSION_SECRET", "")
    if len(session_secret) < 32 or session_secret.startswith("replace-"):
        raise RuntimeError(
            "Set SESSION_SECRET to a unique random value of at least 32 characters."
        )

    secure_value = os.getenv("COOKIE_SECURE", "true").strip().lower()
    if secure_value not in {"true", "false"}:
        raise RuntimeError("COOKIE_SECURE must be either true or false.")

    turn_urls = tuple(
        url.strip()
        for url in os.getenv("TURN_URLS", "").split(",")
        if url.strip()
    )
    turn_username = os.getenv("TURN_USERNAME", "").strip()
    turn_credential = os.getenv("TURN_CREDENTIAL", "")
    if any((turn_urls, turn_username, turn_credential)) and not all(
        (turn_urls, turn_username, turn_credential)
    ):
        raise RuntimeError(
            "Configure TURN_URLS, TURN_USERNAME, and TURN_CREDENTIAL together."
        )
    if any(not url.startswith(("turn:", "turns:")) for url in turn_urls):
        raise RuntimeError("TURN_URLS must contain only turn: or turns: URLs.")

    return Settings(
        accounts=tuple(accounts),
        session_secret=session_secret,
        cookie_secure=secure_value == "true",
        turn_urls=turn_urls,
        turn_username=turn_username,
        turn_credential=turn_credential,
    )
