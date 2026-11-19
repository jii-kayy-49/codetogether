import hashlib
import hmac
import os
from dataclasses import dataclass

from .config import AccountConfig


SCRYPT_COST = 2**14
SCRYPT_BLOCK_SIZE = 8
SCRYPT_PARALLELIZATION = 1
SCRYPT_KEY_LENGTH = 64


@dataclass(frozen=True)
class PasswordRecord:
    salt: bytes
    digest: bytes


class AccountStore:
    def __init__(self, accounts: tuple[AccountConfig, ...]) -> None:
        self._accounts = {
            account.username: self._hash_password(account.password)
            for account in accounts
        }
        self._dummy_record = self._hash_password(os.urandom(32).hex())

    @staticmethod
    def _derive(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=SCRYPT_COST,
            r=SCRYPT_BLOCK_SIZE,
            p=SCRYPT_PARALLELIZATION,
            dklen=SCRYPT_KEY_LENGTH,
        )

    @classmethod
    def _hash_password(cls, password: str) -> PasswordRecord:
        salt = os.urandom(16)
        return PasswordRecord(salt=salt, digest=cls._derive(password, salt))

    def authenticate(self, username: str, password: str) -> bool:
        record = self._accounts.get(username, self._dummy_record)
        candidate = self._derive(password, record.salt)
        is_valid = hmac.compare_digest(candidate, record.digest)
        return username in self._accounts and is_valid

    @property
    def usernames(self) -> tuple[str, ...]:
        return tuple(self._accounts)
