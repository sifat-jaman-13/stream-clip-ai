import pytest

import zernio_connections as zc
from zernio_poster import ZernioAPIError


def account(account_id, platform, *, enabled=True, active=True, provider_enabled=True):
    return {
        "id": account_id,
        "platform": platform,
        "name": account_id,
        "username": account_id,
        "is_active": active,
        "provider_enabled": provider_enabled,
        "posting_enabled": enabled,
    }


def test_zernio_connections_module_is_in_all_windows_and_python_packages():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    assert '"zernio_connections"' in (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "zernio_connections" in (root / "AutoClip.spec").read_text(encoding="utf-8")
    native_installer = (root / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8")
    assert "zernio_connections.py" in native_installer
    assert "zernio_connections.py" in (root / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")


def test_discovery_keeps_every_supported_account_without_app_defined_slots():
    discovered = [
        *(account(f"fb{index}", "facebook") for index in range(1, 8)),
        *(account(f"ig{index}", "instagram") for index in range(1, 8)),
        *(account(f"yt{index}", "youtube") for index in range(1, 8)),
        account("x1", "twitter"),
        account("tt1", "tiktok"),
    ]

    result = zc.apply_account_slots(discovered)
    by_id = {item["id"]: item for item in result}

    assert len(by_id) == 21
    assert all(item["platform"] in {"facebook", "instagram", "youtube"} for item in result)
    assert all("slot_limit_exceeded" not in item for item in result)
    assert all("slot_capacity" not in item for item in result)


def test_discovery_preserves_provider_account_preferences():
    previous = {"fb2": {"posting_enabled": True}, "fb3": {"posting_enabled": False}}
    result = zc.apply_account_slots(
        [account("fb1", "facebook"), account("fb2", "facebook"), account("fb3", "facebook", enabled=False)],
        previous,
    )

    assert [item["id"] for item in result] == ["fb1", "fb2", "fb3"]
    assert [item["posting_enabled"] for item in result] == [True, True, False]


def test_same_platform_accounts_in_different_workspaces_remain_distinct():
    publisher = zc.ZernioMultiPublisher(
        lambda _message: None,
        [
            {"id": "workspace-1", "label": "Brand A", "api_key": "key-a", "accounts": [account("ig1", "instagram")]},
            {"id": "workspace-2", "label": "Brand B", "api_key": "key-b", "accounts": [account("ig1", "instagram")]},
        ],
    )

    selected = publisher._selected_accounts()

    assert {item["ref"] for item in selected} == {"workspace-1:ig1", "workspace-2:ig1"}


def test_disabled_or_unavailable_accounts_are_not_selected():
    publisher = zc.ZernioMultiPublisher(
        lambda _message: None,
        [{
            "id": "workspace-1", "api_key": "key",
            "accounts": [
                account("ig-enabled", "instagram"),
                account("ig-disabled", "instagram", enabled=False),
                account("ig-disconnected", "instagram", active=False),
            ],
        }],
    )

    selected = publisher._selected_accounts()

    assert [item["id"] for item in selected] == ["ig-enabled"]


def test_selected_account_refs_can_include_multiple_accounts_on_same_platform():
    publisher = zc.ZernioMultiPublisher(
        lambda _message: None,
        [{
            "id": "workspace-1", "api_key": "key",
            "accounts": [
                account("ig1", "instagram"),
                account("ig2", "instagram"),
                account("fb1", "facebook"),
            ],
        }],
    )

    selected = publisher._selected_accounts([
        {"connection_id": "workspace-1", "account_id": "ig1"},
        {"connection_id": "workspace-1", "account_id": "ig2"},
    ])

    assert {item["id"] for item in selected} == {"ig1", "ig2"}


def test_one_account_rate_limit_does_not_stop_other_accounts(monkeypatch, tmp_path):
    calls = []
    errors = []
    successes = []

    class FakePublisher:
        def __init__(self, log, config, on_success=None):
            self.api_key = config["api_key"]

        def publish_one(self, path, schedule_minutes=None, accounts=None, caption_override=None):
            platform, account_id = next(iter(accounts.items()))
            calls.append((self.api_key, platform, account_id))
            if account_id == "ig-rate-limited":
                raise ZernioAPIError(
                    "Instagram daily posting cap reached",
                    status_code=429,
                    method="POST",
                    path="/posts",
                    envelope={
                        "type": "platform_error",
                        "code": "platform_api_error",
                        "platform": "instagram",
                        "platformError": {"message": "Daily posting cap reached for this account"},
                        "details": {"accountId": account_id, "retryAfterSeconds": 86400},
                    },
                    headers={"Retry-After": "86400"},
                )

    monkeypatch.setattr(zc, "ZernioPublisher", FakePublisher)
    publisher = zc.ZernioMultiPublisher(
        lambda _message: None,
        [
            {
                "id": "workspace-a", "api_key": "key-a",
                "accounts": [
                    account("ig-rate-limited", "instagram"),
                    account("fb-continues", "facebook"),
                ],
            },
            {
                "id": "workspace-b", "api_key": "key-b",
                "accounts": [account("yt-continues", "youtube")],
            },
        ],
        on_account_success=lambda item: successes.append(item["id"]),
        on_account_error=lambda item, error: errors.append((item["id"], error)),
    )

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    result = publisher.publish_one(video, schedule_minutes=5)

    assert calls == [
        ("key-a", "instagram", "ig-rate-limited"),
        ("key-a", "facebook", "fb-continues"),
        ("key-b", "youtube", "yt-continues"),
    ]
    assert result["succeeded"] == ["workspace-a:fb-continues", "workspace-b:yt-continues"]
    assert [item["ref"] for item in result["failed"]] == ["workspace-a:ig-rate-limited"]
    assert successes == ["fb-continues", "yt-continues"]
    assert errors[0][0] == "ig-rate-limited"
    assert "daily posting cap" in str(errors[0][1])
    assert publisher.connections[0]["accounts"][0]["posting_enabled"] is False
    assert publisher.connections[0]["accounts"][0]["rate_limited"] is True

    # Reusing the same auto-publisher will skip only the rejected account.
    calls.clear()
    publisher.publish_one(video, schedule_minutes=5)
    assert calls == [
        ("key-a", "facebook", "fb-continues"),
        ("key-b", "youtube", "yt-continues"),
    ]


def test_app_adds_no_platform_or_connection_quotas():
    many_connections = [
        {"id": f"connection-{index}", "api_key": f"key-{index}",
         "accounts": [account(f"ig-{index}", "instagram")]}
        for index in range(1, 12)
    ]
    publisher = zc.ZernioMultiPublisher(lambda _message: None, many_connections)
    assert len(publisher.connections) == 11
    assert len(publisher._selected_accounts()) == 11


def test_account_limit_classification_requires_a_structured_account_scope():
    account_limit = ZernioAPIError(
        "account limit",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={
            "type": "platform_error",
            "platform": "instagram",
            "platformError": {"message": "Posting velocity limit reached"},
            "details": {"accountId": "ig-1"},
        },
    )
    workspace_limit = ZernioAPIError(
        "workspace request limit",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={"type": "rate_limit_error", "code": "rate_limited",
                  "details": {"currentCount": 601, "limit": 600}},
        headers={"X-RateLimit-Remaining": "0"},
    )
    assert zc.is_zernio_rate_limit(account_limit)
    assert zc.is_zernio_workspace_rate_limit(workspace_limit)
    assert not zc.is_zernio_rate_limit(workspace_limit)
    assert not zc.is_zernio_rate_limit(
        ZernioAPIError("presign", status_code=429, method="POST", path="/media/presign")
    )
    assert not zc.is_zernio_rate_limit(
        ZernioAPIError("accounts", status_code=429, method="GET", path="/accounts")
    )
    assert not zc.is_zernio_rate_limit("Zernio API POST /posts 429: daily limit")


def test_retry_after_is_honored_and_missing_reset_is_not_invented():
    from datetime import datetime, timezone
    from email.utils import format_datetime

    now = 1_900_000_000.0
    assert zc.zernio_rate_limit_until(
        ZernioAPIError("limit", status_code=429, method="POST", path="/posts",
                       headers={"Retry-After": "90"}), now=now
    ) == now + 90
    assert zc.zernio_rate_limit_until(
        ZernioAPIError("limit", status_code=429, method="POST", path="/posts"), now=now
    ) is None

    reset_header = format_datetime(datetime.fromtimestamp(now + 300, timezone.utc), usegmt=True)
    assert zc.zernio_rate_limit_until(
        ZernioAPIError("limit", status_code=429, method="POST", path="/posts",
                       headers={"Retry-After": reset_header}), now=now
    ) == now + 300
    assert zc.zernio_rate_limit_until(
        ZernioAPIError("limit", status_code=429, method="POST", path="/posts",
                       envelope={"details": {"retryAfterSeconds": 45}}), now=now
    ) == now + 45


def test_expired_auto_pause_resumes_only_the_auto_paused_account():
    resumed = []
    rate_paused = account("ig-auto", "instagram", enabled=False)
    rate_paused.update({
        "rate_limited": True,
        "rate_limited_auto_paused": True,
        "rate_limit_until": 99,
        "last_error": "Zernio API POST /posts 429",
    })
    manual_off = account("fb-manual", "facebook", enabled=False)
    manual_off.update({
        "rate_limited": False,
        "rate_limited_auto_paused": False,
        "rate_limit_until": 99,
        "last_error": "Disabled by user",
    })
    publisher = zc.ZernioMultiPublisher(
        lambda _message: None,
        [{
            "id": "workspace-1", "api_key": "key",
            "accounts": [rate_paused, manual_off],
        }],
        on_account_resume=lambda item: resumed.append(item),
    )

    publisher.refresh_expired()

    accounts = {item["id"]: item for item in publisher.connections[0]["accounts"]}
    assert accounts["ig-auto"]["posting_enabled"] is True
    assert accounts["ig-auto"]["rate_limited"] is False
    assert accounts["ig-auto"]["rate_limited_auto_paused"] is False
    assert accounts["ig-auto"]["rate_limit_until"] is None
    assert accounts["fb-manual"]["posting_enabled"] is False
    assert [item["id"] for item in resumed] == ["ig-auto"]
    assert resumed[0]["connection_id"] == "workspace-1"


def test_manual_reenable_clears_the_auto_pause_state():
    publisher = zc.ZernioMultiPublisher(
        lambda _message: None,
        [{
            "id": "workspace-1", "api_key": "key",
            "accounts": [{
                **account("ig1", "instagram", enabled=False),
                "rate_limited": True,
                "rate_limited_auto_paused": True,
                "rate_limit_until": 9999999999,
            }],
        }],
    )
    selected = publisher.connections[0]["accounts"][0]
    selected.update({
        "posting_enabled": True,
        "rate_limited": False,
        "rate_limited_auto_paused": False,
        "rate_limit_until": None,
    })

    assert [item["id"] for item in publisher._selected_accounts()] == ["ig1"]


def test_queue_interval_has_no_app_defined_minimum_or_maximum():
    base = [{"id": "workspace-1", "api_key": "key", "accounts": [account("ig1", "instagram")]}]
    assert zc.ZernioMultiPublisher(lambda _message: None, base).schedule_minutes == 0
    assert zc.ZernioMultiPublisher(lambda _message: None, base, schedule_minutes=0).schedule_minutes == 0
    assert zc.ZernioMultiPublisher(lambda _message: None, base, schedule_minutes=1440).schedule_minutes == 1440
    assert zc.ZernioMultiPublisher(lambda _message: None, base, schedule_minutes=999999).schedule_minutes == 999999


def test_identity_comparison_flags_shared_owner_but_never_claims_team_independence():
    status = zc.connection_identity_status([
        {"id": "slot-a", "identity_user_id": "api-owner-1"},
        {"id": "slot-b", "identity_user_id": "api-owner-1"},
        {"id": "slot-c", "identity_user_id": "api-owner-2"},
        {"id": "slot-d"},
    ])

    assert status["slot-a"] == {"identity_verified": True, "identity_shared": True}
    assert status["slot-b"] == {"identity_verified": True, "identity_shared": True}
    assert status["slot-c"] == {"identity_verified": True, "identity_shared": False}
    assert status["slot-d"] == {"identity_verified": False, "identity_shared": False}
