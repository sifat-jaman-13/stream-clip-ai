"""Per-Windows-user encrypted credential storage.

Secret values are encrypted with Windows DPAPI before being written to SQLite.
The database contains ciphertext only; settings JSON files store non-secret preferences.
"""
from __future__ import annotations

import ctypes
import os
import sqlite3
import time
from pathlib import Path
from ctypes import wintypes


class CredentialStoreError(RuntimeError):
    """Raised when credentials cannot be protected or read safely."""


class ClosingSQLiteConnection(sqlite3.Connection):
    """SQLite transaction context that also releases the database file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


_ENTROPY = b"StreamSnip AI local credential store v1"
_UI_FORBIDDEN = 0x1


def _blob(value: bytes):
    buffer = ctypes.create_string_buffer(value)
    blob = _DataBlob(
        len(value),
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)),
    )
    return blob, buffer


def protect_secret(value: str) -> bytes:
    """Encrypt a UTF-8 secret with DPAPI for the current Windows user."""
    if os.name != "nt":
        raise CredentialStoreError(
            "Encrypted credential storage currently requires Windows DPAPI."
        )
    if not isinstance(value, str) or not value:
        raise ValueError("A non-empty credential is required.")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    source, source_buffer = _blob(value.encode("utf-8"))
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(source), "StreamSnip AI credential",
        ctypes.byref(entropy), None, None, _UI_FORBIDDEN,
        ctypes.byref(output),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.pbData, output.cbData)
    finally:
        if output.pbData:
            kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
        del source_buffer, entropy_buffer


def unprotect_secret(value: bytes) -> str:
    """Decrypt a DPAPI value for the same Windows user that protected it."""
    if os.name != "nt":
        raise CredentialStoreError(
            "Encrypted credential storage currently requires Windows DPAPI."
        )

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    description_type = ctypes.POINTER(wintypes.LPWSTR)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), description_type,
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    source, source_buffer = _blob(bytes(value))
    entropy, entropy_buffer = _blob(_ENTROPY)
    output = _DataBlob()
    description = wintypes.LPWSTR()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(source), ctypes.byref(description),
        ctypes.byref(entropy), None, None, _UI_FORBIDDEN,
        ctypes.byref(output),
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output.pbData, output.cbData).decode("utf-8")
    finally:
        if output.pbData:
            kernel32.LocalFree(ctypes.cast(output.pbData, ctypes.c_void_p))
        if description:
            kernel32.LocalFree(ctypes.cast(description, ctypes.c_void_p))
        del source_buffer, entropy_buffer


class CredentialStore:
    """Small SQLite index whose secret payloads are DPAPI ciphertext."""

    def __init__(self, database_path: str | Path):
        self.path = Path(database_path)

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(self.path), timeout=10, factory=ClosingSQLiteConnection
        )
        connection.execute("PRAGMA secure_delete=ON")
        # Keep the application database in WAL mode; changing journal mode here
        # can lock the shared database when the engine and credential store overlap.
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS credentials (
                provider TEXT NOT NULL,
                name TEXT NOT NULL,
                encrypted_value BLOB NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY(provider, name)
            )
            """
        )
        return connection

    def get(self, provider: str, name: str) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT encrypted_value FROM credentials WHERE provider=? AND name=?",
                (str(provider), str(name)),
            ).fetchone()
        if row is None:
            return ""
        try:
            return unprotect_secret(bytes(row[0]))
        except Exception as exc:
            raise CredentialStoreError(
                f"Could not decrypt the saved {provider} credential '{name}'. "
                "The key may belong to a different Windows user profile."
            ) from exc

    def set(self, provider: str, name: str, value: str) -> None:
        provider = str(provider).strip()
        name = str(name).strip()
        value = str(value).strip()
        if not provider or not name:
            raise ValueError("Credential provider and name are required.")
        if not value:
            self.delete(provider, name)
            return
        encrypted = protect_secret(value)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO credentials(provider, name, encrypted_value, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(provider, name) DO UPDATE SET
                    encrypted_value=excluded.encrypted_value,
                    updated_at=excluded.updated_at
                """,
                (provider, name, sqlite3.Binary(encrypted), time.time()),
            )

    def delete(self, provider: str, name: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM credentials WHERE provider=? AND name=?",
                (str(provider), str(name)),
            )
            removed = cursor.rowcount > 0
            connection.commit()
            if removed:
                connection.execute("VACUUM")
            return removed

    def prune(self, provider: str, keep_names) -> int:
        keep = {str(item) for item in (keep_names or []) if str(item)}
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM credentials WHERE provider=?",
                (str(provider),),
            ).fetchall()
            stale = [row[0] for row in rows if row[0] not in keep]
            if stale:
                connection.executemany(
                    "DELETE FROM credentials WHERE provider=? AND name=?",
                    [(str(provider), name) for name in stale],
                )
                connection.commit()
                connection.execute("VACUUM")
            return len(stale)

    def names(self, provider: str) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT name FROM credentials WHERE provider=? ORDER BY name",
                (str(provider),),
            ).fetchall()
        return [row[0] for row in rows]
