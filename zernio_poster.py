"""Optional Zernio publisher for finished StreamSnip AI clips.

Credentials and account IDs can come from the app's ignored local publishing
settings or environment variables. They must never be logged or committed.
"""
import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid


_IDEMPOTENCY_LOCK = threading.RLock()
_IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


API_ROOT = "https://zernio.com/api/v1"
SUPPORTED_SOCIAL_PLATFORMS = {"instagram", "facebook", "youtube"}


class ZernioAPIError(RuntimeError):
    """Structured API failure with the response envelope and headers intact."""

    def __init__(self, message, *, status_code=None, method="", path="", envelope=None, headers=None):
        super().__init__(str(message))
        self.status_code = int(status_code or 0)
        self.method = str(method).upper()
        self.path = str(path)
        self.envelope = envelope if isinstance(envelope, dict) else {}
        self.headers = {str(key).lower(): str(value) for key, value in (headers or {}).items()}


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class ZernioPublisher:
    """Uploads and publishes clips in background threads when explicitly enabled."""

    def __init__(self, log, config=None, on_success=None, on_scheduled=None):
        self.log = log
        self.on_success = on_success
        self.on_scheduled = on_scheduled
        self.configure(config or {})

    def configure(self, config):
        config = config if isinstance(config, dict) else {}
        self.api_key = str(config.get("api_key", os.environ.get("ZERNIO_API_KEY", ""))).strip()
        self.idempotency_path = pathlib.Path(config["idempotency_path"]) if config.get("idempotency_path") else None
        self.instagram_id = str(config.get("instagram_id", os.environ.get("ZERNIO_INSTAGRAM_ACCOUNT_ID", ""))).strip()
        self.youtube_id = str(config.get("youtube_id", os.environ.get("ZERNIO_YOUTUBE_ACCOUNT_ID", ""))).strip()
        configured_accounts = config.get("accounts", {})
        self.accounts_map = {
            str(platform).strip().lower(): str(account_id).strip()
            for platform, account_id in configured_accounts.items()
            if str(platform).strip().lower() in SUPPORTED_SOCIAL_PLATFORMS and str(account_id).strip()
        } if isinstance(configured_accounts, dict) else {}
        if not self.accounts_map:
            if self.instagram_id:
                self.accounts_map["instagram"] = self.instagram_id
            if self.youtube_id:
                self.accounts_map["youtube"] = self.youtube_id
        self.enabled = bool(config.get("enabled", _truthy(os.environ.get("ZERNIO_ENABLED"))))
        try:
            self.schedule_minutes = max(0, int(config.get("schedule_minutes", os.environ.get("ZERNIO_SCHEDULE_MINUTES", "0"))))
        except (TypeError, ValueError):
            self.schedule_minutes = 0
        self.visibility = str(config.get("visibility", os.environ.get("ZERNIO_YOUTUBE_VISIBILITY", "public"))).strip().lower()
        if self.visibility not in {"public", "private", "unlisted"}:
            self.visibility = "public"

    @property
    def configured(self):
        return self.enabled and bool(self.api_key) and bool(self.accounts_map)

    def submit(self, video_path):
        if not self.configured:
            return
        path = pathlib.Path(video_path)
        threading.Thread(target=self._publish, args=(path,), daemon=True,
                         name="zernio-publisher").start()

    def _headers(self, content_type="application/json"):
        return {
            "Authorization": "Bearer " + self.api_key,
            "Content-Type": content_type,
            "User-Agent": "StreamSnipAI/1.2",
        }

    def _json_request(self, method, url, body=None, headers=None):
        method = str(method).upper()
        data = None if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        request_headers = self._headers()
        request_headers.update({str(key): str(value) for key, value in (headers or {}).items()})
        req = urllib.request.Request(url, data=data, method=method, headers=request_headers)
        raw = None
        endpoint = url.split(API_ROOT, 1)[-1].split("?", 1)[0] or "/"
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as res:
                    raw = res.read()
                break
            except urllib.error.HTTPError as e:
                response_raw = e.read()
                safe_detail = response_raw.decode("utf-8", "replace")[-1200:]
                if self.api_key:
                    safe_detail = safe_detail.replace(self.api_key, "[REDACTED]")
                safe_detail = re.sub(r"(?i)Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", safe_detail)
                try:
                    envelope = json.loads(response_raw.decode("utf-8")) if response_raw else {}
                except (ValueError, UnicodeDecodeError):
                    envelope = {}
                response_headers = dict(e.headers.items()) if e.headers else {}
                # Retry transient server errors only when the exact POST has
                # an Idempotency-Key; the same Request body and key are reused.
                idempotent = bool(req.get_header("Idempotency-key"))
                if e.code >= 500 and idempotent and attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                retry_after = str(e.headers.get("Retry-After", "")).strip() if e.headers else ""
                suffix = f" (Retry-After: {retry_after})" if retry_after else ""
                raise ZernioAPIError(
                    f"Zernio API {method} {endpoint} {e.code}{suffix}: {safe_detail}",
                    status_code=e.code, method=method, path=endpoint,
                    envelope=envelope, headers=response_headers,
                ) from e
            except (urllib.error.URLError, TimeoutError) as e:
                if attempt < 2:
                    time.sleep(0.5 * (attempt + 1))
                    continue
                reason = getattr(e, "reason", e)
                if isinstance(reason, socket.gaierror) or "getaddrinfo" in str(reason).lower():
                    raise RuntimeError(
                        "Zernio DNS lookup failed after 3 attempts. Check your internet connection, "
                        "VPN, firewall, or DNS settings, then try again."
                    ) from e
                raise RuntimeError(f"Zernio connection failed after 3 attempts: {reason}") from e
        if raw is None:
            raise RuntimeError("Zernio returned no response.")
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            if not raw.strip():
                return {}
            raise RuntimeError("Zernio returned invalid JSON.")
        except (ValueError, UnicodeDecodeError) as e:
            raise RuntimeError("Zernio returned invalid JSON.") from e

    def verify_identity(self):
        """Identify the API-key user using Zernio's documented team-users endpoint.

        Zernio exposes currentUserId on GET /v1/users, not a stable billing-team
        identifier. This is useful for noticing keys used by the same API user,
        but it must not be presented as proof of independent workspaces.
        """
        result = self._json_request("GET", f"{API_ROOT}/users")
        if not isinstance(result, dict) or result.get("success") is False:
            raise RuntimeError("Zernio API key identity could not be verified.")
        data = result.get("data") if isinstance(result.get("data"), dict) else result
        user_id = str(
            result.get("currentUserId") or result.get("current_user_id")
            or data.get("currentUserId") or data.get("current_user_id") or ""
        ).strip()
        if not user_id:
            raise RuntimeError("Zernio did not return currentUserId for this API key.")
        return {"user_id": user_id}

    def accounts(self):
        """Discover Facebook, Instagram and YouTube accounts visible to this Zernio team."""
        result = self._json_request("GET", f"{API_ROOT}/accounts")
        data = result.get("accounts", result.get("data", result)) if isinstance(result, dict) else result
        if isinstance(data, dict):
            data = data.get("accounts", data.get("items", data.get("data", [])))
        if not isinstance(data, list):
            raise RuntimeError("Zernio returned an unexpected accounts response.")
        out = []
        for account in data:
            if not isinstance(account, dict) or str(account.get("platform", "")).lower() not in SUPPORTED_SOCIAL_PLATFORMS:
                continue
            aid = account.get("accountId") or account.get("id") or account.get("_id")
            if not aid:
                continue
            profile = account.get("profileId") or account.get("profile") or {}
            if not isinstance(profile, dict):
                profile = {"id": str(profile)}
            out.append({
                "id": str(aid),
                "platform": str(account.get("platform", "")).lower(),
                "name": account.get("displayName") or account.get("username") or str(aid),
                "username": account.get("username", ""),
                "profile_id": str(profile.get("id") or profile.get("_id") or ""),
                "profile_name": str(profile.get("name") or ""),
                "profile_color": str(profile.get("color") or ""),
                "profile_picture": str(account.get("profilePicture") or ""),
                "profile_url": str(account.get("profileUrl") or ""),
                "is_active": bool(account.get("isActive", True)),
                "provider_enabled": bool(account.get("enabled", True)),
                "is_over_limit": bool(profile.get("isOverLimit", account.get("isOverLimit", False))),
            })
        return out

    def _upload(self, path):
        size = path.stat().st_size
        presigned = self._json_request("POST", f"{API_ROOT}/media/presign", {
            "filename": path.name,
            "contentType": "video/mp4",
            "size": size,
        })
        upload_url = presigned.get("uploadUrl")
        public_url = presigned.get("publicUrl")
        if not upload_url or not public_url:
            raise RuntimeError("Zernio did not return upload URLs.")
        video = path.open("rb")
        try:
            req = urllib.request.Request(upload_url, data=video, method="PUT",
                                         headers={"Content-Type": "video/mp4",
                                                  "Content-Length": str(size)})
            try:
                with urllib.request.urlopen(req, timeout=300):
                    pass
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"Zernio media upload failed ({e.code}).") from e
            except urllib.error.URLError as e:
                raise RuntimeError(f"Zernio media upload failed: {e.reason}") from e
        finally:
            video.close()
        return public_url

    def publish_one(self, path, instagram_id=None, youtube_id=None, schedule_minutes=None,
                    accounts=None, caption_override=None, idempotency_key=None, scheduled_for=None):
        old = (self.instagram_id, self.youtube_id, self.schedule_minutes, dict(self.accounts_map))
        if instagram_id is not None:
            self.instagram_id = str(instagram_id).strip()
        if youtube_id is not None:
            self.youtube_id = str(youtube_id).strip()
        if accounts is not None:
            if not isinstance(accounts, dict):
                raise ValueError("Choose at least one connected social account.")
            selected = {
                str(platform).strip().lower(): str(account_id).strip()
                for platform, account_id in accounts.items()
                if str(platform).strip().lower() in SUPPORTED_SOCIAL_PLATFORMS and str(account_id).strip()
            }
            self.accounts_map = selected
            self.instagram_id = selected.get("instagram", "")
            self.youtube_id = selected.get("youtube", "")
        else:
            self.accounts_map = {}
            if self.instagram_id:
                self.accounts_map["instagram"] = self.instagram_id
            if self.youtube_id:
                self.accounts_map["youtube"] = self.youtube_id
        if schedule_minutes is not None:
            self.schedule_minutes = max(0, int(schedule_minutes))
        try:
            return self._publish(
                path, raise_errors=True, caption_override=caption_override,
                idempotency_key=idempotency_key, scheduled_for=scheduled_for,
            )
        finally:
            self.instagram_id, self.youtube_id, self.schedule_minutes, self.accounts_map = old

    def _publish(self, path, raise_errors=False, caption_override=None,
                 idempotency_key=None, scheduled_for=None):
        path = pathlib.Path(path)
        try:
            caption_path = path.with_suffix(".txt")
            caption = (str(caption_override).strip() if caption_override is not None else
                       caption_path.read_text(encoding="utf-8", errors="replace").strip()
                       if caption_path.is_file() else "")
            lines = [line.strip() for line in caption.splitlines() if line.strip()]
            title = (lines[0] if lines else path.stem).replace("#", "").strip()[:100] or "StreamSnip Clip"
            content = caption[:2200] or title
            platforms = []
            for platform, account_id in self.accounts_map.items():
                target = {"platform": platform, "accountId": account_id}
                if platform == "instagram":
                    target["platformSpecificData"] = {"shareToFeed": True}
                elif platform == "youtube":
                    target["platformSpecificData"] = {"title": title, "visibility": self.visibility}
                elif platform == "facebook":
                    target["platformSpecificData"] = {"contentType": "reel", "title": title}
                platforms.append(target)
            if not platforms:
                raise RuntimeError("Select at least one connected Zernio account before publishing.")
            identity_key = None
            identity_record = {}
            if self.idempotency_path and not idempotency_key:
                try:
                    stat = path.stat()
                    identity_material = json.dumps({
                        "path": str(path.resolve()),
                        "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "credential_fingerprint": hashlib.sha256(self.api_key.encode("utf-8")).hexdigest(),
                        "content": content,
                        "platforms": platforms,
                        "schedule_minutes": self.schedule_minutes,
                        "visibility": self.visibility,
                    }, sort_keys=True, separators=(",", ":"))
                    identity_key = hashlib.sha256(identity_material.encode("utf-8")).hexdigest()
                    with _IDEMPOTENCY_LOCK:
                        try:
                            idempotency_state = json.loads(self.idempotency_path.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            idempotency_state = {}
                        if not isinstance(idempotency_state, dict):
                            idempotency_state = {}
                        now = time.time()
                        idempotency_state = {
                            key: value for key, value in idempotency_state.items()
                            if isinstance(value, dict)
                            and now - float(value.get("created_at", 0) or 0) < _IDEMPOTENCY_TTL_SECONDS
                        }
                        identity_record = idempotency_state.get(identity_key, {})
                        if not identity_record:
                            identity_record = {
                                "idempotency_key": str(uuid.uuid4()),
                                "created_at": now,
                                "scheduled_for": (
                                    _dt.datetime.fromtimestamp(now, _dt.timezone.utc)
                                    + _dt.timedelta(minutes=self.schedule_minutes)
                                ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                                if self.schedule_minutes else None,
                                "media_url": "",
                            }
                            idempotency_state[identity_key] = identity_record
                        self.idempotency_path.parent.mkdir(parents=True, exist_ok=True)
                        temp = self.idempotency_path.with_name(
                            f".{self.idempotency_path.name}.{uuid.uuid4().hex}.tmp"
                        )
                        try:
                            temp.write_text(json.dumps(idempotency_state, indent=2), encoding="utf-8")
                            os.replace(temp, self.idempotency_path)
                        finally:
                            temp.unlink(missing_ok=True)
                except OSError as exc:
                    raise RuntimeError(f"Could not persist the Zernio retry identity safely: {exc}") from exc
            stable_key = str(idempotency_key or identity_record.get("idempotency_key") or uuid.uuid4())
            scheduled_for = scheduled_for or identity_record.get("scheduled_for")
            public_url = str(identity_record.get("media_url") or "")
            if not public_url:
                public_url = self._upload(path)
                if identity_key and identity_record:
                    identity_record["media_url"] = public_url
                    with _IDEMPOTENCY_LOCK:
                        try:
                            idempotency_state = json.loads(self.idempotency_path.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            idempotency_state = {}
                        if not isinstance(idempotency_state, dict):
                            idempotency_state = {}
                        idempotency_state[identity_key] = identity_record
                        temp = self.idempotency_path.with_name(
                            f".{self.idempotency_path.name}.{uuid.uuid4().hex}.tmp"
                        )
                        try:
                            temp.write_text(json.dumps(idempotency_state, indent=2), encoding="utf-8")
                            os.replace(temp, self.idempotency_path)
                        finally:
                            temp.unlink(missing_ok=True)
            body = {
                "content": content,
                "mediaItems": [{"url": public_url, "type": "video"}],
                "platforms": platforms,
            }
            if self.schedule_minutes:
                when = scheduled_for or (
                    _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=self.schedule_minutes)
                ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
                body["scheduledFor"] = when
                body["timezone"] = "UTC"
            else:
                body["publishNow"] = True
            result = self._json_request(
                "POST", f"{API_ROOT}/posts", body,
                headers={"Idempotency-Key": stable_key},
            )
            # A response closes this logical operation. Remove the persisted
            # retry identity so a later, deliberate user publish is a new post.
            # Unknown outcomes (timeouts / exhausted 5xx retries) keep the key.
            if identity_key and self.idempotency_path:
                try:
                    with _IDEMPOTENCY_LOCK:
                        try:
                            state = json.loads(self.idempotency_path.read_text(encoding="utf-8"))
                        except (OSError, ValueError):
                            state = {}
                        if isinstance(state, dict):
                            state.pop(identity_key, None)
                            if state:
                                temp = self.idempotency_path.with_name(
                                    f".{self.idempotency_path.name}.{uuid.uuid4().hex}.tmp"
                                )
                                try:
                                    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
                                    os.replace(temp, self.idempotency_path)
                                finally:
                                    temp.unlink(missing_ok=True)
                            else:
                                self.idempotency_path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    self.log(f"Could not clear the completed Zernio retry identity: {cleanup_error}")
            root = result if isinstance(result, dict) else {}
            data = root.get("data") if isinstance(root.get("data"), dict) else root
            post = data.get("post") if isinstance(data.get("post"), dict) else root.get("post", {})
            post = post if isinstance(post, dict) else {}
            state = str(post.get("status") or "").strip().lower()
            destination_rows = post.get("platforms") if isinstance(post.get("platforms"), list) else []
            successful = []
            successful_destinations = []
            scheduled_destinations = []
            failed = []
            for target in platforms:
                match = next((row for row in destination_rows
                              if isinstance(row, dict)
                              and str(row.get("accountId") or row.get("account_id") or "") == target["accountId"]
                              and str(row.get("platform") or "").lower() == target["platform"]), None)
                status = str((match or {}).get("status") or "").strip().lower()
                if state in {"published", "partial"} and status == "published":
                    successful.append(target["platform"])
                    successful_destinations.append(f"{target['platform']}:{target['accountId']}")
                elif state in {"scheduled", "queued", "pending", "draft", "processing", "partial"} and status in {"scheduled", "queued", "pending", "processing", "submitted"}:
                    scheduled_destinations.append(f"{target['platform']}:{target['accountId']}")
                else:
                    detail = (match or {}).get("errorMessage") or (match or {}).get("error") or (match or {}).get("errorCategory") or f"Destination status: {status or 'missing'}; post status: {state or 'missing'}."
                    failed.append({"platform": target["platform"], "account_id": target["accountId"],
                                   "status": status or "unknown", "error": str(detail)[:500]})
            summary = {"post_id": str(post.get("id") or post.get("_id") or ""), "post_status": state,
                       "successful_platforms": successful, "successful_destinations": successful_destinations,
                       "scheduled_destinations": scheduled_destinations,
                       "failed_platforms": failed, "scheduled": bool(self.schedule_minutes)}
            targets = ", ".join(p["platform"] for p in platforms)
            suffix = f" ({self.schedule_minutes} min delay)" if self.schedule_minutes else ""
            self.log(f"Zernio: {path.name} {state or 'unknown'} to {targets}{suffix}.")
            if not self.schedule_minutes and successful and callable(self.on_success):
                try:
                    self.on_success(path, successful_destinations)
                except Exception as callback_error:
                    self.log(f"Zernio Posted status update failed for {path.name}: {callback_error}")
            if self.schedule_minutes and scheduled_destinations and callable(self.on_scheduled):
                try:
                    self.on_scheduled(path, scheduled_destinations)
                except Exception as callback_error:
                    self.log(f"Zernio Scheduled status update failed for {path.name}: {callback_error}")
            if failed:
                details = "; ".join(f"{item['platform']}: {item['error']}" for item in failed)
                raise RuntimeError(f"Zernio post {state or 'unknown'}; destination failure: {details}")
            if not summary["scheduled"] and not successful:
                raise RuntimeError(f"Zernio did not confirm a published destination (post status: {state or 'missing'}).")
            if summary["scheduled"] and not scheduled_destinations:
                raise RuntimeError(f"Zernio did not confirm a scheduled destination (post status: {state or 'missing'}).")
            return summary
        except Exception as e:
            self.log(f"Zernio error for {path.name}: {e}")
            if raise_errors:
                raise
