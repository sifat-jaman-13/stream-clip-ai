import io
import json
import urllib.error

import pytest

from zernio_poster import ZernioAPIError, ZernioPublisher
from zernio_connections import (
    ZernioMultiPublisher,
    is_zernio_rate_limit,
    is_zernio_workspace_rate_limit,
    zernio_rate_limit_until,
)


def publisher_for(path, accounts, *, callback=None):
    publisher = ZernioPublisher(
        lambda _message: None,
        {"enabled": True, "api_key": "test-key", "accounts": accounts},
        on_success=callback,
    )
    publisher._upload = lambda _path: "https://media.example/clip.mp4"
    return publisher


def test_207_partial_registers_only_platforms_that_published(monkeypatch, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    posted = []
    publisher = publisher_for(
        video,
        {"instagram": "ig-1", "facebook": "fb-1"},
        callback=lambda path, platforms: posted.append((path.name, platforms)),
    )
    publisher._json_request = lambda *_args, **_kwargs: {
        "data": {
            "post": {
                "id": "post-1",
                "status": "partial",
                "platforms": [
                    {"platform": "instagram", "accountId": "ig-1", "status": "published"},
                    {"platform": "facebook", "accountId": "fb-1", "status": "failed",
                     "errorMessage": "The Page rejected the video."},
                ],
            }
        }
    }

    with pytest.raises(RuntimeError, match="facebook"):
        publisher.publish_one(video, accounts={"instagram": "ig-1", "facebook": "fb-1"})

    assert posted == [("clip.mp4", ["instagram:ig-1"])]


def test_207_all_failed_is_not_a_success_or_posted_registry_entry(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    posted = []
    publisher = publisher_for(
        video,
        {"facebook": "fb-1"},
        callback=lambda path, platforms: posted.append((path.name, platforms)),
    )
    publisher._json_request = lambda *_args, **_kwargs: {
        "post": {
            "id": "post-2",
            "status": "failed",
            "platforms": [
                {"platform": "facebook", "accountId": "fb-1", "status": "failed",
                 "errorMessage": "Page permissions missing."}
            ],
        }
    }

    with pytest.raises(RuntimeError, match="facebook"):
        publisher.publish_one(video, accounts={"facebook": "fb-1"})

    assert posted == []


def test_published_overall_status_does_not_override_failed_destination(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    posted = []
    publisher = publisher_for(
        video,
        {"instagram": "ig-1"},
        callback=lambda path, platforms: posted.append(platforms),
    )
    publisher._json_request = lambda *_args, **_kwargs: {
        "post": {
            "id": "post-3",
            "status": "published",
            "platforms": [
                {"platform": "instagram", "accountId": "ig-1", "status": "failed",
                 "errorMessage": "Upstream destination failed."}
            ],
        }
    }

    with pytest.raises(RuntimeError):
        publisher.publish_one(video, accounts={"instagram": "ig-1"})

    assert posted == []


def test_post_idempotency_key_is_attached_and_kept_stable_for_retry(monkeypatch, tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    publisher = publisher_for(video, {"youtube": "yt-1"})
    captured = []

    def fake_request(method, url, body=None, headers=None):
        if url.endswith("/media/presign"):
            return {"uploadUrl": "unused", "publicUrl": "https://media.example/clip.mp4"}
        captured.append((method, dict(headers or {}), body))
        return {"post": {
            "id": "post-4", "status": "published",
            "platforms": [{"platform": "youtube", "accountId": "yt-1", "status": "published"}],
        }}

    publisher._json_request = fake_request
    key = "8cfa90dd-63d5-4a4b-aec9-eadf79d8f0d2"
    publisher.publish_one(video, accounts={"youtube": "yt-1"}, idempotency_key=key)
    publisher.publish_one(video, accounts={"youtube": "yt-1"}, idempotency_key=key)

    assert [item[1].get("Idempotency-Key") for item in captured] == [key, key]
    assert captured[0][2] == captured[1][2]


def test_json_request_reuses_idempotency_header_after_timeout(monkeypatch):
    publisher = ZernioPublisher(lambda _message: None, {"enabled": True, "api_key": "test-key"})
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout):
        requests.append(request.get_header("Idempotency-key"))
        if len(requests) == 1:
            raise urllib.error.URLError("timed out after request was sent")
        return Response()

    monkeypatch.setattr("zernio_poster.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("zernio_poster.time.sleep", lambda _seconds: None)

    result = publisher._json_request(
        "POST", "https://zernio.com/api/v1/posts",
        {"content": "same logical post"},
        headers={"Idempotency-Key": "7a12ab6e-5a9b-4df7-a2a5-5cdeea4f9d0e"},
    )

    assert result == {"ok": True}
    assert requests == [
        "7a12ab6e-5a9b-4df7-a2a5-5cdeea4f9d0e",
        "7a12ab6e-5a9b-4df7-a2a5-5cdeea4f9d0e",
    ]


def test_429_workspace_rate_limit_is_not_an_account_posting_limit():
    error = ZernioAPIError(
        "workspace request rate limit",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={
            "error": "Rate limit exceeded",
            "type": "rate_limit_error",
            "code": "rate_limited",
            "details": {"currentCount": 601, "limit": 600, "retryAfterSeconds": 12},
        },
        headers={
            "Retry-After": "12",
            "X-RateLimit-Limit": "600",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1900000012",
        },
    )

    assert is_zernio_workspace_rate_limit(error) is True
    assert is_zernio_rate_limit(error) is False
    assert zernio_rate_limit_until(error, now=1_900_000_000) == 1_900_000_012


def test_429_account_posting_cap_requires_platform_specific_envelope():
    error = ZernioAPIError(
        "Instagram posting velocity cap",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={
            "error": "Instagram daily posting cap reached",
            "type": "platform_error",
            "code": "platform_api_error",
            "platform": "instagram",
            "platformError": {
                "code": 4,
                "message": "Posting velocity limit reached for this Instagram account",
            },
            "details": {"accountId": "ig-1", "retryAfterSeconds": 3600},
        },
        headers={"Retry-After": "3600"},
    )

    assert is_zernio_workspace_rate_limit(error) is False
    assert is_zernio_rate_limit(error) is True
    assert zernio_rate_limit_until(error, now=1_900_000_000) == 1_900_003_600


def test_429_plain_post_endpoint_does_not_pause_selected_account():
    error = ZernioAPIError(
        "Unclassified request limit",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={"error": "Too many requests"},
        headers={"Retry-After": "30"},
    )

    assert is_zernio_rate_limit(error) is False


def test_account_scope_overrides_generic_rate_limit_code():
    error = ZernioAPIError(
        "Instagram daily cap reached",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={
            "type": "rate_limit_error",
            "code": "rate_limited",
            "platform": "instagram",
            "details": {
                "accountId": "ig-1",
                "scope": "account",
                "reason": "daily_post_limit",
                "retryAfterSeconds": 7200,
            },
        },
        headers={
            "Retry-After": "7200",
            "X-RateLimit-Limit": "600",
            "X-RateLimit-Remaining": "0",
        },
    )

    assert is_zernio_workspace_rate_limit(error) is False
    assert is_zernio_rate_limit(error) is True
    assert zernio_rate_limit_until(error, now=1_900_000_000) == 1_900_007_200


def test_workspace_rate_limit_uses_documented_headers_and_details_only():
    error = ZernioAPIError(
        "Rate limit exceeded",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={"error": "Rate limit exceeded", "details": {
            "currentCount": 601, "limit": 600, "retryAfterSeconds": 12,
        }},
        headers={
            "Retry-After": "12",
            "X-RateLimit-Limit": "600",
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "1900000012",
        },
    )

    assert is_zernio_workspace_rate_limit(error) is True
    assert is_zernio_rate_limit(error) is False


def test_generic_rate_limit_code_without_account_scope_is_never_account_paused():
    error = ZernioAPIError(
        "Rate limit exceeded",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={"type": "rate_limit_error", "code": "rate_limited"},
        headers={"Retry-After": "12"},
    )

    assert is_zernio_workspace_rate_limit(error) is True
    assert is_zernio_rate_limit(error) is False


def test_account_cooldown_message_with_account_id_is_account_scoped():
    error = ZernioAPIError(
        "Account posting cooldown. Retry in 30 minutes.",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={
            "error": "Account posting cooldown. Retry in 30 minutes.",
            "type": "rate_limit_error",
            "code": "rate_limited",
            "details": {"accountId": "fb-1"},
        },
        headers={
            "Retry-After": "1800",
            "X-RateLimit-Limit": "600",
            "X-RateLimit-Remaining": "412",
            "X-RateLimit-Reset": "1900000600",
        },
    )

    assert is_zernio_workspace_rate_limit(error) is False
    assert is_zernio_rate_limit(error) is True
    assert zernio_rate_limit_until(error, now=1_900_000_000) == 1_900_001_800


def test_platform_429_without_account_scope_is_not_auto_paused():
    error = ZernioAPIError(
        "Instagram API rate limit reached",
        status_code=429,
        method="POST",
        path="/posts",
        envelope={
            "type": "platform_error",
            "code": "platform_api_error",
            "platform": "instagram",
            "platformError": {"message": "Instagram API rate limit reached"},
        },
        headers={"Retry-After": "60"},
    )

    assert is_zernio_workspace_rate_limit(error) is False
    assert is_zernio_rate_limit(error) is False


def test_users_endpoint_exposes_current_api_user_identity(monkeypatch):
    publisher = ZernioPublisher(lambda _message: None, {"enabled": True, "api_key": "test-key"})
    calls = []
    publisher._json_request = lambda method, url, body=None, headers=None: (
        calls.append((method, url)) or {
            "success": True,
            "currentUserId": "user-123",
            "users": [{"id": "user-123", "role": "owner"}],
        }
    )

    identity = publisher.verify_identity()

    assert identity["user_id"] == "user-123"
    assert calls == [("GET", "https://zernio.com/api/v1/users")]


def test_workspace_rate_limit_stops_other_account_attempts_without_auto_pausing(monkeypatch, tmp_path):
    calls = []
    account_errors = []

    class FakePublisher:
        def __init__(self, log, config, on_success=None):
            self.api_key = config["api_key"]

        def publish_one(self, path, schedule_minutes=None, accounts=None, caption_override=None,
                        idempotency_key=None, scheduled_for=None):
            platform, account_id = next(iter(accounts.items()))
            calls.append(account_id)
            if account_id == "ig-1":
                raise ZernioAPIError(
                    "workspace request rate limit",
                    status_code=429,
                    method="POST",
                    path="/posts",
                    envelope={"type": "rate_limit_error", "code": "rate_limited",
                              "details": {"retryAfterSeconds": 30, "currentCount": 601, "limit": 600}},
                    headers={"Retry-After": "30"},
                )
            return {"successful_platforms": [platform], "failed_platforms": []}

    monkeypatch.setattr("zernio_connections.ZernioPublisher", FakePublisher)
    publisher = ZernioMultiPublisher(
        lambda _message: None,
        [{
            "id": "workspace-1",
            "api_key": "key",
            "accounts": [
                {"id": "ig-1", "platform": "instagram", "posting_enabled": True},
                {"id": "fb-1", "platform": "facebook", "posting_enabled": True},
            ],
        }],
        on_account_error=lambda account, error: account_errors.append(account["id"]),
    )
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")

    result = publisher.publish_one(video, schedule_minutes=5)

    assert calls == ["ig-1"]
    assert result["workspace_rate_limited"] is True
    assert result["succeeded"] == []
    assert len(result["failed"]) == 2
    assert account_errors == []
    assert publisher.connections[0]["accounts"][0]["posting_enabled"] is True
    assert publisher.connections[0]["accounts"][0].get("rate_limited") is not True


def test_persistent_idempotency_reuses_uuid_schedule_and_uploaded_media(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    state_file = tmp_path / "zernio-idempotency.json"
    publisher = publisher_for(video, {"youtube": "yt-1"})
    publisher.idempotency_path = state_file
    upload_calls = []
    requests = []
    publisher._upload = lambda path: upload_calls.append(path.name) or "https://media.example/stable.mp4"

    def fake_request(method, url, body=None, headers=None):
        requests.append((dict(headers or {}), dict(body or {})))
        if len(requests) == 1:
            raise RuntimeError("timeout after dispatch; outcome is unknown")
        return {"post": {
            "id": "scheduled-1", "status": "scheduled",
            "platforms": [{"platform": "youtube", "accountId": "yt-1", "status": "scheduled"}],
        }}

    publisher._json_request = fake_request
    with pytest.raises(RuntimeError, match="outcome is unknown"):
        publisher.publish_one(video, accounts={"youtube": "yt-1"}, schedule_minutes=5)
    publisher.publish_one(video, accounts={"youtube": "yt-1"}, schedule_minutes=5)

    assert len(upload_calls) == 1
    import uuid

    key = requests[0][0]["Idempotency-Key"]
    assert str(uuid.UUID(key)) == key
    assert requests[1][0]["Idempotency-Key"] == key
    assert requests[0][1] == requests[1][1]
    assert requests[0][1]["scheduledFor"] == requests[1][1]["scheduledFor"]
    assert requests[0][1]["mediaItems"][0]["url"] == "https://media.example/stable.mp4"
    assert not state_file.exists(), "a confirmed Zernio response closes the logical post"


def test_json_request_preserves_429_response_envelope_and_headers(monkeypatch):
    from email.message import Message

    publisher = ZernioPublisher(lambda _message: None, {"enabled": True, "api_key": "test-key"})
    url = "https://zernio.com/api/v1/posts"
    payload = json.dumps({
        "error": "Rate limit exceeded",
        "type": "rate_limit_error",
        "code": "rate_limited",
        "details": {"currentCount": 601, "limit": 600, "retryAfterSeconds": 17},
    }).encode("utf-8")
    headers = Message()
    headers["Retry-After"] = "17"
    headers["X-RateLimit-Limit"] = "600"
    headers["X-RateLimit-Remaining"] = "0"
    headers["X-RateLimit-Reset"] = "1900000017"
    response_error = urllib.error.HTTPError(url, 429, "Too Many Requests", headers, io.BytesIO(payload))

    def fail_request(_request, timeout):
        raise response_error

    monkeypatch.setattr("zernio_poster.urllib.request.urlopen", fail_request)
    with pytest.raises(ZernioAPIError) as raised:
        publisher._json_request(
            "POST", url, {"content": "test"},
            headers={"Idempotency-Key": "bc935d54-3187-470b-a5a9-8e66e6cb6c99"},
        )

    assert raised.value.status_code == 429
    assert raised.value.method == "POST"
    assert raised.value.path == "/posts"
    assert raised.value.envelope["type"] == "rate_limit_error"
    assert raised.value.headers["retry-after"] == "17"
    assert raised.value.headers["x-ratelimit-remaining"] == "0"


def test_scheduled_post_requires_a_matching_destination_status(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    posted = []
    publisher = publisher_for(
        video,
        {"youtube": "yt-1"},
        callback=lambda path, destinations: posted.append(destinations),
    )
    publisher._json_request = lambda *_args, **_kwargs: {
        "data": {"post": {"id": "scheduled-without-destination", "status": "scheduled"}}
    }

    with pytest.raises(RuntimeError, match="missing"):
        publisher.publish_one(
            video, accounts={"youtube": "yt-1"}, schedule_minutes=5,
        )

    assert posted == []
