import hashlib
import hmac
import os
import secrets
import sqlite3
from dataclasses import dataclass

from triton.paths import ROOT_DIR

WEB_DATABASE = ROOT_DIR / "web.sqlite3"


@dataclass(frozen=True)
class WebAccount:
    id: str
    username: str
    role: str


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(WEB_DATABASE)
    connection.row_factory = sqlite3.Row
    return connection


def _password_hash(password: str, salt: bytes | None = None) -> str:
    actual_salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=actual_salt, n=2**14, r=8, p=1)
    return f"{actual_salt.hex()}:{digest.hex()}"


def _password_matches(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, digest_hex = stored_hash.split(":", maxsplit=1)
        calculated = _password_hash(password, bytes.fromhex(salt_hex))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculated, stored_hash) and bool(digest_hex)


def initialize_web_accounts(admin_username: str, admin_password: str) -> WebAccount:
    WEB_DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with _connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS web_accounts (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS web_session_owners (
                session_id TEXT PRIMARY KEY,
                account_id TEXT NOT NULL REFERENCES web_accounts(id)
            );
            """
        )
        row = connection.execute(
            "SELECT id, password_hash FROM web_accounts WHERE username = ?", (admin_username,)
        ).fetchone()
        if row is None:
            account = WebAccount(id=secrets.token_hex(16), username=admin_username, role="admin")
            connection.execute(
                "INSERT INTO web_accounts (id, username, password_hash, role) VALUES (?, ?, ?, ?)",
                (account.id, account.username, _password_hash(admin_password), account.role),
            )
            return account
        if not _password_matches(admin_password, row["password_hash"]):
            connection.execute(
                "UPDATE web_accounts SET password_hash = ? WHERE id = ?",
                (_password_hash(admin_password), row["id"]),
            )
        return WebAccount(id=row["id"], username=admin_username, role="admin")


def authenticate_web_account(username: str, password: str) -> WebAccount | None:
    if not WEB_DATABASE.exists():
        return None
    with _connection() as connection:
        row = connection.execute(
            "SELECT id, username, password_hash, role FROM web_accounts WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None or not _password_matches(password, row["password_hash"]):
        return None
    return WebAccount(id=row["id"], username=row["username"], role=row["role"])


def assign_session_owner(session_id: str, account_id: str) -> None:
    with _connection() as connection:
        connection.execute(
            "INSERT OR IGNORE INTO web_session_owners (session_id, account_id) VALUES (?, ?)",
            (session_id, account_id),
        )


def session_is_owned_by(session_id: str, account_id: str) -> bool:
    if not WEB_DATABASE.exists():
        return False
    with _connection() as connection:
        row = connection.execute(
            "SELECT 1 FROM web_session_owners WHERE session_id = ? AND account_id = ?",
            (session_id, account_id),
        ).fetchone()
    return row is not None


def owned_session_ids(account_id: str) -> set[str]:
    if not WEB_DATABASE.exists():
        return set()
    with _connection() as connection:
        rows = connection.execute(
            "SELECT session_id FROM web_session_owners WHERE account_id = ?", (account_id,)
        ).fetchall()
    return {row["session_id"] for row in rows}
