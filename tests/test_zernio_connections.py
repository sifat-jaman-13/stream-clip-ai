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



def test_one_clip_reaches_only_explicitly_selected_accounts_across_connections(monkeypatch, tmp_path):
    calls = []

    class FakePublisher:
        def __init__(self, log, config, on_success=None):
            self.api_key = config["api_key"]

        def publish_one(self, path, schedule_minutes=None, accounts=None, caption_override=None):
            platform, account_id = next(iter(accounts.items()))
            calls.append((Path(path), self.api_key, platform, account_id))
            return {"failed_platforms": []}

    from pathlib import Path

    monkeypatch.setattr(zc, "ZernioPublisher", FakePublisher)
    publisher = zc.ZernioMultiPublisher(
        lambda _message: None,
        [
            {
                "id": "workspace-a",
                "api_key": "key-a",
                "accounts": [
                    account("ig-selected", "instagram", enabled=True),
                    account("fb-unselected", "facebook", enabled=True),
                ],
            },
            {
                "id": "workspace-b",
                "api_key": "key-b",
                "accounts": [
                    account("yt-selected", "youtube", enabled=False),
                ],
            },
        ],
    )
    video = tmp_path / "one-video.mp4"
    video.write_bytes(b"same video")

    selected = [
        {"connection_id": "workspace-a", "account_id": "ig-selected"},
        {"connection_id": "workspace-b", "account_id": "yt-selected"},
    ]
    result = publisher.publish_one(video, accounts=selected)

    assert calls == [
        (video, "key-a", "instagram", "ig-selected"),
        (video, "key-b", "youtube", "yt-selected"),
    ]
    assert result["succeeded"] == ["workspace-a:ig-selected", "workspace-b:yt-selected"]
    assert result["failed"] == []



def test_five_connections_preserve_explicit_order_deduplicate_and_share_clip_metadata(monkeypatch, tmp_path):
    calls = []

    class FakePublisher:
        def __init__(self, log, config, on_success=None):
            self.api_key = config["api_key"]

        def publish_one(self, path, schedule_minutes=None, accounts=None, caption_override=None):
            platform, account_id = next(iter(accounts.items()))
            calls.append((Path(path), self.api_key, schedule_minutes, platform, account_id, caption_override))
            return {"failed_platforms": []}

    from pathlib import Path

    monkeypatch.setattr(zc, "ZernioPublisher", FakePublisher)
    connections = []
    for index in range(1, 6):
        connections.append({
            "id": f"workspace-{index}",
            "api_key": f"key-{index}",
            "accounts": [
                account("shared-instagram-id", "instagram", enabled=index != 1),
                account(f"unselected-{index}", "instagram", enabled=True),
            ],
        })
    publisher = zc.ZernioMultiPublisher(lambda _message: None, connections)
    video = tmp_path / "shared.mp4"
    video.write_bytes(b"one source video")
    selected = [
        {"connection_id": "workspace-4", "account_id": "shared-instagram-id"},
        {"connection_id": "workspace-1", "account_id": "shared-instagram-id"},
        {"connection_id": "workspace-5", "account_id": "shared-instagram-id"},
        {"connection_id": "workspace-1", "account_id": "shared-instagram-id"},
        {"connection_id": "workspace-1", "account_id": "unselected-1"},
    ]

    result = publisher.publish_one(video, schedule_minutes=15, accounts=selected,
                                   caption_override="One title\nOne description")

    expected = [
        (video, "key-4", 15, "instagram", "shared-instagram-id", "One title\nOne description"),
        (video, "key-1", 15, "instagram", "shared-instagram-id", "One title\nOne description"),
        (video, "key-5", 15, "instagram", "shared-instagram-id", "One title\nOne description"),
        (video, "key-1", 15, "instagram", "unselected-1", "One title\nOne description"),
    ]
    assert calls == expected
    assert result["succeeded"] == [
        "workspace-4:shared-instagram-id",
        "workspace-1:shared-instagram-id",
        "workspace-5:shared-instagram-id",
        "workspace-1:unselected-1",
    ]
    assert result["failed"] == []


def test_explicit_selection_excludes_unavailable_and_rate_limited_accounts():
    limited = account("rate-limited", "instagram")
    limited.update({"rate_limited": True})
    publisher = zc.ZernioMultiPublisher(lambda _message: None, [{
        "id": "workspace-1", "api_key": "key",
        "accounts": [
            account("inactive", "instagram", active=False),
            account("provider-disabled", "facebook", provider_enabled=False),
            limited,
        ],
    }])

    selected = publisher._selected_accounts([
        {"connection_id": "workspace-1", "account_id": "inactive"},
        {"connection_id": "workspace-1", "account_id": "provider-disabled"},
        {"connection_id": "workspace-1", "account_id": "rate-limited"},
    ])

    assert selected == []
    with pytest.raises(ValueError, match="at least one connected Zernio account"):
        publisher.publish_one("unused.mp4", accounts=[])


def test_failed_destination_does_not_stop_other_selected_accounts(monkeypatch, tmp_path):
    calls = []

    class FakePublisher:
        def __init__(self, log, config, on_success=None):
            self.api_key = config["api_key"]

        def publish_one(self, path, schedule_minutes=None, accounts=None, caption_override=None):
            platform, account_id = next(iter(accounts.items()))
            calls.append((self.api_key, platform, account_id))
            if account_id == "fails":
                raise RuntimeError("destination rejected the post")
            return {"failed_platforms": []}

    monkeypatch.setattr(zc, "ZernioPublisher", FakePublisher)
    publisher = zc.ZernioMultiPublisher(lambda _message: None, [{
        "id": "workspace-1", "api_key": "key",
        "accounts": [account("first", "instagram"), account("fails", "facebook"), account("last", "youtube")],
    }])
    video = tmp_path / "partial.mp4"
    video.write_bytes(b"video")

    result = publisher.publish_one(video)

    assert calls == [
        ("key", "instagram", "first"),
        ("key", "facebook", "fails"),
        ("key", "youtube", "last"),
    ]
    assert result["succeeded"] == ["workspace-1:first", "workspace-1:last"]
    assert [item["ref"] for item in result["failed"]] == ["workspace-1:fails"]

def test_multi_publisher_records_zernio_scheduling_separately(monkeypatch, tmp_path):
    scheduled = []
    posted = []

    class FakePublisher:
        def __init__(self, log, config, on_success=None):
            self.api_key = config["api_key"]

        def publish_one(self, path, schedule_minutes=None, accounts=None, caption_override=None):
            platform, account_id = next(iter(accounts.items()))
            return {
                "failed_platforms": [],
                "scheduled_destinations": [f"{platform}:{account_id}"],
                "delivery_records": [{
                    "account_id": account_id,
                    "platform": platform,
                    "post_id": f"post-{account_id}",
                    "scheduled_for": "2026-11-28T02:20:00Z",
                    "published_at": None,
                    "status": "pending",
                }],
            }

    monkeypatch.setattr(zc, "ZernioPublisher", FakePublisher)
    publisher = zc.ZernioMultiPublisher(
        lambda _message: None,
        [{
            "id": "connection-1",
            "api_key": "test-key",
            "accounts": [account("ig-1", "instagram")],
        }],
        on_success=lambda path, destinations: posted.append((path, destinations)),
        on_scheduled=lambda path, destinations, records=None: scheduled.append((path, destinations, records)),
    )
    video = tmp_path / "scheduled.mp4"
    video.write_bytes(b"video")

    result = publisher.publish_one(video, schedule_minutes=5)

    assert result["succeeded"] == ["connection-1:ig-1"]
    assert result["failed"] == []
    assert scheduled == [(video, ["instagram:ig-1"], [{
        "account_id": "ig-1", "platform": "instagram", "post_id": "post-ig-1",
        "scheduled_for": "2026-11-28T02:20:00Z", "published_at": None,
        "status": "pending", "connection_id": "connection-1",
    }])]
    assert posted == []


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
