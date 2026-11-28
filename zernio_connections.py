"""Multi-key Zernio publishing with per-account opt-in/out.

A saved connection is an API-key slot, not proof of an independent Zernio
billing workspace. Accounts use (connection_id, account_id) identities.
"""
from __future__ import annotations

import re
import threading
import time
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any

from zernio_poster import ZernioPublisher, _notify_delivery_callback


SUPPORTED_ZERNIO_PLATFORMS = {"facebook", "instagram", "youtube"}


def apply_account_slots(accounts, previous_accounts=None):
    """Keep every Facebook, Instagram and YouTube account Zernio discovers.

    The historical function name is retained for compatibility, but StreamSnip
    no longer imposes per-platform account slots or a connection-count cap.
    Account availability and posting limits come from Zernio.
    """
    return [
        dict(account)
        for account in (accounts or [])
        if isinstance(account, dict)
        and str(account.get("platform", "")).strip().lower() in SUPPORTED_ZERNIO_PLATFORMS
    ]


def account_ref(connection_id: str, account_id: str):
    return f"{connection_id}:{account_id}"


def connection_identity_status(connections):
    """Compare the verified API owner IDs without implying a billing-team identity."""
    counts = {}
    for connection in connections or []:
        if not isinstance(connection, dict):
            continue
        identity = str(connection.get("identity_user_id") or "").strip()
        if identity:
            counts[identity] = counts.get(identity, 0) + 1
    return {
        str(connection.get("id") or ""): {
            "identity_verified": bool(str(connection.get("identity_user_id") or "").strip()),
            "identity_shared": bool(
                str(connection.get("identity_user_id") or "").strip()
                and counts.get(str(connection.get("identity_user_id") or "").strip(), 0) > 1
            ),
        }
        for connection in (connections or [])
        if isinstance(connection, dict)
    }


def _zernio_error_parts(error):
    envelope = getattr(error, "envelope", {})
    headers = getattr(error, "headers", {})
    status = getattr(error, "status_code", 0)
    method = str(getattr(error, "method", "")).upper()
    path = str(getattr(error, "path", ""))
    return (
        envelope if isinstance(envelope, dict) else {},
        {str(key).lower(): str(value) for key, value in (headers or {}).items()},
        int(status or 0),
        method,
        path,
    )


def _has_account_rate_limit_scope(envelope, details):
    scope = str(details.get("scope") or details.get("quotaScope") or details.get("budgetScope") or "").casefold()
    reason = str(details.get("reason") or details.get("limitType") or "").casefold()
    account_scopes = {
        "account", "account_route", "account_posting", "account_rate_limit",
        "account_velocity", "platform_account",
    }
    account_reasons = {
        "posting_velocity_limit", "daily_post_limit", "account_post_limit",
        "account_rate_limit", "account_rate_limited", "account_cooldown",
        "daily_posting_cap", "daily_cap",
    }
    return bool(
        details.get("accountId") or details.get("account_id")
        or scope in account_scopes
        or reason in account_reasons
        or (str(details.get("quotaScope") or "").casefold() == "account")
    )


def is_zernio_workspace_rate_limit(error: Any) -> bool:
    """Identify the shared Zernio request budget; endpoint alone is not enough."""
    envelope, headers, status, method, path = _zernio_error_parts(error)
    if status != 429 or method != "POST" or path.rstrip("/") != "/posts":
        return False

    details = envelope.get("details") if isinstance(envelope.get("details"), dict) else {}
    error_type = str(envelope.get("type") or "").casefold()
    code = str(envelope.get("code") or "").casefold()

    # Explicit account/platform context wins even if the upstream also uses a
    # generic rate-limit code. A platform 429 must not consume the workspace
    # cooldown or be mislabeled as the shared request budget.
    if _has_account_rate_limit_scope(envelope, details) or error_type == "platform_error":
        return False

    # Zernio's documented request-window envelope is {error, details:{currentCount,
    # limit, retryAfterSeconds}}; it often has no type or code field at all.
    try:
        if (
            details.get("currentCount") is not None
            and details.get("limit") is not None
            and float(details["currentCount"]) >= float(details["limit"])
        ):
            return True
    except (TypeError, ValueError, OverflowError):
        pass

    # The X-RateLimit headers apply to the authenticated workspace. Require the
    # limit and a zero remaining count together, rather than interpreting a
    # lone zero header as proof of a team-level throttle.
    try:
        limit = float(headers.get("x-ratelimit-limit", ""))
        remaining = float(headers.get("x-ratelimit-remaining", ""))
        if limit > 0 and remaining <= 0:
            return True
    except (TypeError, ValueError, OverflowError):
        pass

    scope = str(details.get("scope") or details.get("budgetScope") or "").casefold()
    if scope in {"workspace", "team", "billing_workspace", "request"}:
        return True

    # For /posts, an unscoped Zernio rate_limit_error is treated as a request
    # throttle, never as evidence that one social account should be disabled.
    return error_type == "rate_limit_error" or code in {
        "rate_limited", "request_rate_limit_exceeded",
    }


def is_zernio_rate_limit(error: Any) -> bool:
    """Pause an account only when the 429 explicitly identifies its posting cap."""
    envelope, _headers, status, method, path = _zernio_error_parts(error)
    if status != 429 or method != "POST" or path.rstrip("/") != "/posts":
        return False

    details = envelope.get("details") if isinstance(envelope.get("details"), dict) else {}
    code = str(envelope.get("code") or "").casefold()
    platform_error = envelope.get("platformError")
    platform_message = ""
    if isinstance(platform_error, dict):
        platform_message = " ".join(
            str(platform_error.get(key) or "")
            for key in ("code", "message", "error", "error_description")
        ).casefold()
    elif isinstance(platform_error, str):
        platform_message = platform_error.casefold()

    account_codes = {
        "posting_velocity_limit", "daily_post_limit", "account_post_limit",
        "account_rate_limit", "account_rate_limited", "account_cooldown",
    }
    explicit_account_scope = _has_account_rate_limit_scope(envelope, details)
    limit_terms = (
        "posting velocity", "daily posting cap", "daily post limit", "posting cap",
        "daily cap", "posting limit", "post limit", "rate limit", "rate-limit",
        "quota exceeded", "too many posts", "cooldown",
    )
    detail_text = " ".join(
        str(details.get(key) or "")
        for key in ("scope", "reason", "message", "code", "limitType")
    ).casefold().replace("_", " ").replace("-", " ")
    error_text = str(envelope.get("error") or "").casefold().replace("_", " ").replace("-", " ")
    platform_text = platform_message.replace("_", " ").replace("-", " ")
    limit_context = " ".join((detail_text, error_text, platform_text))

    if is_zernio_workspace_rate_limit(error):
        return False
    if code in account_codes and explicit_account_scope:
        return True
    # Some account cooldowns are documented as 429s with the affected
    # accountId and cooldown only in the envelope's human-readable message.
    # Require both account identity and an explicit posting-cap signal.
    if explicit_account_scope and any(term in limit_context for term in limit_terms):
        return True
    # A platform 429 can be an application-wide upstream quota shared across
    # Zernio customers. The platform name alone is not enough to auto-pause a
    # particular social account.
    return False


def zernio_rate_limit_until(error: Any, now: float | None = None) -> float | None:
    """Return a reset time only when Zernio actually supplies one.

    StreamSnip must not invent a cooldown. If the API gives no reset, the
    account remains paused until the user checks it and re-enables posting.
    """
    current = time.time() if now is None else float(now)
    envelope, headers, _status, _method, _path = _zernio_error_parts(error)
    details = envelope.get("details") if isinstance(envelope.get("details"), dict) else {}
    retry_after = headers.get("retry-after")
    if retry_after:
        try:
            return current + max(0.0, float(retry_after.rstrip("sS")))
        except ValueError:
            try:
                reset = parsedate_to_datetime(retry_after)
                if reset.tzinfo is None:
                    reset = reset.replace(tzinfo=timezone.utc)
                return max(current, reset.timestamp())
            except (TypeError, ValueError, OverflowError):
                pass
    for key in ("retryAfterSeconds", "cooldownSeconds", "retry_after_seconds"):
        try:
            if details.get(key) is not None:
                return current + max(0.0, float(details[key]))
        except (TypeError, ValueError, OverflowError):
            pass
    reset_header = headers.get("x-ratelimit-reset")
    if reset_header:
        try:
            return max(current, float(reset_header))
        except (TypeError, ValueError, OverflowError):
            pass
    for source in (
        envelope.get("error"),
        details.get("message"),
        (envelope.get("platformError") or {}).get("message")
        if isinstance(envelope.get("platformError"), dict) else envelope.get("platformError"),
    ):
        match = re.search(r"(?i)(?:retry|reset)(?:\s+after|\s+in)?\s+(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)", str(source or ""))
        if match:
            return current + max(0.0, float(match.group(1)))
    return None


def _is_enabled(account: dict[str, Any]) -> bool:
    return (
        bool(account.get("posting_enabled", account.get("enabled", account.get("is_active", True))))
        and bool(account.get("is_active", True))
        and bool(account.get("provider_enabled", True))
    )


class ZernioMultiPublisher:
    """Publish independently through every selected account's own API key."""

    def __init__(self, log, connections, on_success=None, on_account_success=None,
                 on_account_error=None, on_account_resume=None, enabled=True,
                 visibility="public", schedule_minutes=0, idempotency_path=None, on_scheduled=None):
        self.log = log
        self.on_success = on_success
        self.on_scheduled = on_scheduled
        self.on_account_success = on_account_success
        self.on_account_error = on_account_error
        self.on_account_resume = on_account_resume
        self.enabled = bool(enabled)
        self.visibility = visibility if visibility in {"public", "private", "unlisted"} else "public"
        try:
            self.schedule_minutes = max(0, int(schedule_minutes or 0))
        except (TypeError, ValueError):
            self.schedule_minutes = 0
        self.idempotency_path = str(idempotency_path or "")
        self.connections = [
            dict(item) for item in (connections or [])
            if isinstance(item, dict) and str(item.get("api_key", "")).strip()
        ]
        self._by_id = {str(item.get("id", "")): item for item in self.connections}

    @property
    def configured(self):
        return bool(self.connections)

    def accounts(self):
        """Discover connected accounts across every saved Zernio workspace."""
        discovered = []
        for connection in self.connections:
            connection_id = str(connection.get("id", ""))
            label = str(connection.get("label") or "Zernio API connection")
            publisher = ZernioPublisher(self.log, {
                "enabled": True, "api_key": connection["api_key"],
                "idempotency_path": self.idempotency_path,
            })
            previous = {
                str(row.get("id")): row for row in connection.get("accounts", [])
                if isinstance(row, dict) and row.get("id")
            }
            for item in apply_account_slots(publisher.accounts(), previous):
                item = dict(item)
                item["connection_id"] = connection_id
                item["connection_label"] = label
                item["ref"] = account_ref(connection_id, item["id"])
                saved = previous.get(str(item["id"]), {})
                item["posting_enabled"] = bool(saved.get(
                    "posting_enabled",
                    saved.get("enabled", item.get("is_active", True) and item.get("provider_enabled", True)),
                ))
                item["last_error"] = str(saved.get("last_error", ""))
                item["rate_limited"] = bool(saved.get("rate_limited", False))
                item["rate_limited_auto_paused"] = bool(saved.get("rate_limited_auto_paused", False))
                item["rate_limit_until"] = saved.get("rate_limit_until")
                discovered.append(item)
        return discovered

    def _reactivate_expired_rate_limits(self, now=None):
        current = time.time() if now is None else float(now)
        for connection in self.connections:
            for account in connection.get("accounts", []):
                if not isinstance(account, dict) or not account.get("rate_limited_auto_paused"):
                    continue
                try:
                    reset_at = float(account.get("rate_limit_until", 0) or 0)
                except (TypeError, ValueError):
                    reset_at = 0
                if not reset_at or reset_at > current:
                    continue
                account.update({
                    "posting_enabled": True,
                    "rate_limited": False,
                    "rate_limited_auto_paused": False,
                    "rate_limit_until": None,
                    "last_error": "",
                })
                if callable(self.on_account_resume):
                    try:
                        self.on_account_resume({
                            **account, "connection_id": str(connection.get("id", "")),
                        })
                    except Exception as callback_error:
                        self.log(f"Could not save Zernio account cooldown expiry: {callback_error}")
                self.log(
                    f"Zernio account cooldown ended for {account.get('platform')} "
                    f"@{account.get('username') or account.get('name') or account.get('id')}; posting resumed."
                )

    def refresh_expired(self):
        self._reactivate_expired_rate_limits()

    def _selected_accounts(self, requested=None):
        self._reactivate_expired_rate_limits()
        all_accounts = []
        for connection in self.connections:
            connection_id = str(connection.get("id", ""))
            for account in connection.get("accounts", []):
                if not isinstance(account, dict):
                    continue
                item = dict(account)
                item["connection_id"] = connection_id
                item["connection_label"] = str(connection.get("label") or "Zernio API connection")
                item["ref"] = account_ref(connection_id, str(item.get("id", "")))
                all_accounts.append(item)

        # Persistent posting_enabled controls automatic posts. An explicit list
        # comes from the user's current per-account checkboxes and is authoritative
        # for this manual publish, even before those preferences are saved.
        available = {
            item["ref"]: item for item in all_accounts
            if item.get("id")
            and item.get("platform") in SUPPORTED_ZERNIO_PLATFORMS
            and item.get("is_active", True)
            and item.get("provider_enabled", True)
            and not item.get("rate_limited", False)
        }
        default_enabled = {
            key: item for key, item in available.items() if _is_enabled(item)
        }
        if requested is None:
            return list(default_enabled.values())
        if isinstance(requested, list):
            chosen = []
            seen = set()
            for item in requested:
                ref = ""
                if isinstance(item, dict):
                    conn_id = str(item.get("connection_id", ""))
                    acc_id = str(item.get("account_id") or item.get("id") or "")
                    if conn_id and acc_id:
                        ref = account_ref(conn_id, acc_id)
                elif isinstance(item, str):
                    ref = item
                if ref and ref not in seen:
                    chosen.append(ref)
                    seen.add(ref)
            return [available[key] for key in chosen if key in available]
        if isinstance(requested, dict):
            matches = {}
            for item in all_accounts:
                platform = str(item.get("platform", ""))
                if (item.get("id") and requested.get(platform) == item.get("id")
                        and item["ref"] in available):
                    matches.setdefault(platform, []).append(item)
            # The legacy platform->account map has no connection identity. Refuse
            # ambiguous duplicate IDs rather than sending to multiple API slots.
            return [
                rows[0] for platform, rows in matches.items()
                if len(rows) == 1
            ]
        return []

    def publish_one(self, path, schedule_minutes=None, accounts=None, account_refs=None,
                    caption_override=None):
        requested = account_refs if account_refs is not None else accounts
        if schedule_minutes is None:
            schedule_minutes = self.schedule_minutes
        selected = self._selected_accounts(requested)
        if not selected:
            raise ValueError("Enable at least one connected Zernio account for posting.")

        successes = []
        failures = []
        posted_records = []
        scheduled_records = []
        workspace_throttled = False
        for account_index, account in enumerate(selected):
            connection_id = account["connection_id"]
            connection = self._by_id.get(connection_id)
            if not connection:
                failures.append((account, "Zernio connection is no longer available."))
                continue
            platform = str(account.get("platform", "")).strip().lower()
            account_id = str(account.get("id", "")).strip()
            if not platform or not account_id:
                failures.append((account, "Zernio account identity is incomplete."))
                continue
            config = {
                "enabled": True,
                "api_key": connection["api_key"],
                "visibility": connection.get("visibility", self.visibility),
            }
            config["idempotency_path"] = self.idempotency_path
            publisher = ZernioPublisher(self.log, config)
            try:
                publish_result = publisher.publish_one(
                    Path(path),
                    schedule_minutes=schedule_minutes,
                    accounts={platform: account_id},
                    caption_override=caption_override,
                )
                if isinstance(publish_result, dict) and publish_result.get("failed_platforms"):
                    raise RuntimeError("Zernio reported a failed destination.")

                returned_records = (
                    publish_result.get("delivery_records", [])
                    if isinstance(publish_result, dict) else []
                )
                if isinstance(returned_records, list) and returned_records:
                    for raw_record in returned_records:
                        if not isinstance(raw_record, dict):
                            continue
                        record = dict(raw_record)
                        record["connection_id"] = connection_id
                        record["account_id"] = str(record.get("account_id") or account_id)
                        record["platform"] = str(record.get("platform") or platform).lower()
                        status = str(record.get("status") or "").strip().lower()
                        if status == "published":
                            posted_records.append(record)
                        elif status in {"scheduled", "queued", "pending", "processing", "submitted"}:
                            scheduled_records.append(record)
                else:
                    # Compatibility for older ZernioPublisher adapters and test doubles.
                    scheduled_destinations = (
                        publish_result.get("scheduled_destinations", [])
                        if isinstance(publish_result, dict) else []
                    )
                    if isinstance(scheduled_destinations, list) and scheduled_destinations:
                        scheduled_records.append({
                            "connection_id": connection_id,
                            "account_id": account_id,
                            "platform": platform,
                            "post_id": str(publish_result.get("post_id") or ""),
                            "scheduled_for": publish_result.get("scheduled_for"),
                            "published_at": None,
                            "status": "scheduled",
                        })
                    else:
                        successful_destinations = (
                            publish_result.get("successful_destinations", [])
                            if isinstance(publish_result, dict) else []
                        )
                        status = "published" if (
                            isinstance(successful_destinations, list) and successful_destinations
                        ) or not schedule_minutes else "scheduled"
                        target_record = {
                            "connection_id": connection_id,
                            "account_id": account_id,
                            "platform": platform,
                            "post_id": str(publish_result.get("post_id") or "")
                                if isinstance(publish_result, dict) else "",
                            "scheduled_for": (
                                publish_result.get("scheduled_for")
                                if isinstance(publish_result, dict) else None
                            ),
                            "published_at": (
                                publish_result.get("published_at")
                                if isinstance(publish_result, dict) else None
                            ),
                            "status": status,
                        }
                        (posted_records if status == "published" else scheduled_records).append(target_record)

                successes.append(account)
                if callable(self.on_account_success):
                    try:
                        self.on_account_success(account)
                    except Exception as callback_error:
                        self.log(f"Could not update Zernio account status: {callback_error}")
            except Exception as exc:
                error_text = str(exc)
                failures.append((account, error_text))
                if is_zernio_workspace_rate_limit(exc):
                    workspace_throttled = True
                    self.log(
                        "Zernio workspace request limit reached (429). No social account was paused; "
                        "remaining destinations were skipped to avoid consuming the shared team quota."
                    )
                    for skipped in selected[account_index + 1:]:
                        failures.append((skipped, "Skipped: Zernio team request limit is active; retry after the workspace cooldown."))
                    break
                if is_zernio_rate_limit(exc):
                    # A structured platform-specific 429 is an account posting cap.
                    reset_at = zernio_rate_limit_until(exc)
                    account["posting_enabled"] = False
                    account["rate_limited"] = True
                    account["rate_limited_auto_paused"] = True
                    account["rate_limit_until"] = reset_at
                    for saved_connection in self.connections:
                        if str(saved_connection.get("id")) != connection_id:
                            continue
                        for saved_account in saved_connection.get("accounts", []):
                            if isinstance(saved_account, dict) and str(saved_account.get("id")) == account_id:
                                saved_account["posting_enabled"] = False
                                saved_account["rate_limited"] = True
                                saved_account["rate_limited_auto_paused"] = True
                                saved_account["rate_limit_until"] = reset_at
                                saved_account["last_error"] = error_text[:400]
                                break
                if callable(self.on_account_error):
                    try:
                        self.on_account_error(account, exc)
                    except Exception as callback_error:
                        self.log(f"Could not save Zernio account error state: {callback_error}")
                self.log(
                    f"Zernio account error [{account.get('connection_label')} · "
                    f"{platform} @{account.get('username') or account.get('name') or account_id}]: {exc}"
                )

        self.log(
            f"Zernio multi-account result: {len(successes)} succeeded, "
            f"{len(failures)} failed."
        )
        if posted_records and callable(self.on_success):
            destinations = sorted({
                f"{item['platform']}:{item['account_id']}"
                for item in posted_records
            })
            try:
                _notify_delivery_callback(self.on_success, Path(path), destinations, posted_records)
            except Exception as callback_error:
                self.log(f"Could not update the local posted registry: {callback_error}")

        if scheduled_records and callable(self.on_scheduled):
            destinations = sorted({
                f"{item['platform']}:{item['account_id']}"
                for item in scheduled_records
            })
            try:
                _notify_delivery_callback(self.on_scheduled, Path(path), destinations, scheduled_records)
            except Exception as callback_error:
                self.log(f"Could not update the local scheduled registry: {callback_error}")

        if successes and not posted_records and not scheduled_records:
            # Defensive compatibility for adapters which report success without
            # destination metadata. The provider accepted the request, so keep
            # the account-level outcome visible rather than dropping the clip.
            state = "scheduled" if schedule_minutes else "published"
            records = [{
                "connection_id": item["connection_id"],
                "account_id": str(item.get("id") or ""),
                "platform": str(item.get("platform") or ""),
                "post_id": "",
                "scheduled_for": None,
                "published_at": None,
                "status": state,
            } for item in successes]
            destinations = sorted({
                f"{item['platform']}:{item['account_id']}" for item in records
            })
            callback = self.on_scheduled if state == "scheduled" else self.on_success
            if callable(callback):
                try:
                    _notify_delivery_callback(callback, Path(path), destinations, records)
                except Exception as callback_error:
                    self.log(f"Could not update the local {state} registry: {callback_error}")

        if failures and not successes and not workspace_throttled:
            details = "; ".join(
                f"{item.get('platform')} {item.get('username') or item.get('id')}: {error}"
                for item, error in failures
            )
            raise RuntimeError(details)
        return {
            "succeeded": [item["ref"] for item in successes],
            "failed": [
                {"ref": item["ref"], "platform": item.get("platform"), "error": error}
                for item, error in failures
            ],
            "workspace_rate_limited": workspace_throttled,
            "posted_records": posted_records,
            "scheduled_records": scheduled_records,
        }

    def submit(self, video_path):
        if not self.enabled or not self.configured:
            return
        thread = threading.Thread(
            target=self._submit_worker,
            args=(Path(video_path),),
            daemon=True,
            name="zernio-multi-publisher",
        )
        thread.start()

    def _submit_worker(self, path):
        try:
            self.publish_one(path)
        except Exception as exc:
            self.log(f"Zernio auto-publishing error for {path.name}: {exc}")
