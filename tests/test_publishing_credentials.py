import base64
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import autoclip


def _fake_protect(value: str) -> bytes:
    return base64.b64encode(value.encode("utf-8"))


def _fake_unprotect(value: bytes) -> str:
    return base64.b64decode(bytes(value)).decode("utf-8")


def test_legacy_zernio_keys_move_to_encrypted_shared_sqlite_and_json_is_scrubbed(tmp_path):
    publishing_file = tmp_path / "publishing.json"
    zernio_file = tmp_path / "zernio.json"
    database_file = tmp_path / "streamsnip.db"
    source = {
        "provider": "zernio",
        "zernio": {
            "connections": [
                {
                    "id": f"streamsnip-zernio-slot-{slot}",
                    "label": f"Brand {slot}",
                    "api_key": f"private-zernio-key-{slot}",
                    "accounts": [
                        {
                            "id": f"account-{slot}",
                            "platform": "instagram",
                            "name": f"Brand {slot}",
                            "posting_enabled": slot != 3,
                        }
                    ],
                }
                for slot in (3, 4, 5)
            ],
            "auto_post": True,
            "schedule_minutes": 15,
            "visibility": "unlisted",
        },
    }
    publishing_file.write_text(json.dumps(source), encoding="utf-8")

    with patch.multiple(
        autoclip,
        _data_root=tmp_path,
        DATABASE_FILE=database_file,
        PUBLISHING_FILE=publishing_file,
        ZERNIO_FILE=zernio_file,
    ), patch("secret_store.protect_secret", side_effect=_fake_protect), patch(
        "secret_store.unprotect_secret", side_effect=_fake_unprotect
    ):
        loaded = autoclip.load_publishing_settings()
        assert [item["id"] for item in loaded["zernio"]["connections"]] == [
            "streamsnip-zernio-slot-3",
            "streamsnip-zernio-slot-4",
            "streamsnip-zernio-slot-5",
        ]
        assert [item["api_key"] for item in loaded["zernio"]["connections"]] == [
            "private-zernio-key-3",
            "private-zernio-key-4",
            "private-zernio-key-5",
        ]

        safe_json = publishing_file.read_text(encoding="utf-8")
        for slot in (3, 4, 5):
            assert f"private-zernio-key-{slot}" not in safe_json

        with sqlite3.connect(database_file) as database:
            credentials = database.execute(
                "SELECT name,encrypted_value FROM credentials WHERE provider='zernio' ORDER BY name"
            ).fetchall()
            settings_json = database.execute(
                "SELECT value_json FROM app_settings WHERE setting_key='publishing'"
            ).fetchone()[0]
            connections = database.execute(
                "SELECT connection_id,label,credential_name FROM publishing_connections ORDER BY connection_id"
            ).fetchall()
            accounts = database.execute(
                "SELECT connection_id,account_id,platform,name FROM publishing_accounts ORDER BY connection_id"
            ).fetchall()

        assert [row[0] for row in credentials] == [
            "connection:streamsnip-zernio-slot-3",
            "connection:streamsnip-zernio-slot-4",
            "connection:streamsnip-zernio-slot-5",
        ]
        for slot, (_name, encrypted) in zip((3, 4, 5), credentials):
            assert f"private-zernio-key-{slot}".encode() not in bytes(encrypted)
        assert all(f"private-zernio-key-{slot}" not in settings_json for slot in (3, 4, 5))
        assert [row[0] for row in connections] == [
            "streamsnip-zernio-slot-3",
            "streamsnip-zernio-slot-4",
            "streamsnip-zernio-slot-5",
        ]
        assert [row[1] for row in accounts] == ["account-3", "account-4", "account-5"]


def test_disconnect_prunes_only_that_encrypted_key_and_retains_other_slots(tmp_path):
    publishing_file = tmp_path / "publishing.json"
    zernio_file = tmp_path / "zernio.json"
    database_file = tmp_path / "streamsnip.db"
    publishing_file.write_text(json.dumps({
        "provider": "zernio",
        "zernio": {
            "connections": [
                {
                    "id": f"streamsnip-zernio-slot-{slot}",
                    "label": f"Brand {slot}",
                    "api_key": f"private-zernio-key-{slot}",
                    "accounts": [{"id": f"account-{slot}", "platform": "instagram"}],
                }
                for slot in (3, 4, 5)
            ],
        },
    }), encoding="utf-8")

    with patch.multiple(
        autoclip,
        _data_root=tmp_path,
        DATABASE_FILE=database_file,
        PUBLISHING_FILE=publishing_file,
        ZERNIO_FILE=zernio_file,
    ), patch("secret_store.protect_secret", side_effect=_fake_protect), patch(
        "secret_store.unprotect_secret", side_effect=_fake_unprotect
    ):
        config = autoclip.load_publishing_settings()
        core = object.__new__(autoclip.Core)
        core.lock = __import__("threading").RLock()
        core.posting = {"active": False}
        core.push = lambda _message: None
        core.publishing = config
        core.zernio = config["zernio"]
        core._make_publisher = lambda *_args, **_kwargs: None
        core.publishing_status = lambda: {"configured": True}

        core.disconnect_zernio_connection("streamsnip-zernio-slot-4")

        remaining = core.publishing["zernio"]["connections"]
        assert [item["id"] for item in remaining] == [
            "streamsnip-zernio-slot-3",
            "streamsnip-zernio-slot-5",
        ]
        assert [item["api_key"] for item in remaining] == [
            "private-zernio-key-3",
            "private-zernio-key-5",
        ]
        with sqlite3.connect(database_file) as database:
            saved_names = [
                row[0] for row in database.execute(
                    "SELECT name FROM credentials WHERE provider='zernio' ORDER BY name"
                )
            ]
        assert saved_names == [
            "connection:streamsnip-zernio-slot-3",
            "connection:streamsnip-zernio-slot-5",
        ]
        assert "private-zernio-key-4" not in publishing_file.read_text(encoding="utf-8")
