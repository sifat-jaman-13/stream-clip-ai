"""Optional Zernio publisher for finished AutoClip videos.

Credentials and account IDs come from environment variables so they never
need to be stored in settings.json or committed to the repository.
"""
import datetime as _dt
import json
import os
import pathlib
import threading
import urllib.error
import urllib.request


API_ROOT = "https://zernio.com/api/v1"


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class ZernioPublisher:
    """Uploads and publishes clips in background threads when explicitly enabled."""

    def __init__(self, log, config=None):
        self.log = log
        self.configure(config or {})

    def configure(self, config):
        config = config if isinstance(config, dict) else {}
        self.api_key = str(config.get("api_key", os.environ.get("ZERNIO_API_KEY", ""))).strip()
        self.instagram_id = str(config.get("instagram_id", os.environ.get("ZERNIO_INSTAGRAM_ACCOUNT_ID", ""))).strip()
        self.youtube_id = str(config.get("youtube_id", os.environ.get("ZERNIO_YOUTUBE_ACCOUNT_ID", ""))).strip()
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
        return self.enabled and bool(self.api_key) and bool(self.instagram_id or self.youtube_id)

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
            "User-Agent": "StreamClipAI/1.0",
        }

    def _json_request(self, method, url, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                raw = res.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[-500:]
            raise RuntimeError(f"Zernio API {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Zernio connection failed: {e.reason}") from e
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            raise RuntimeError("Zernio returned invalid JSON.") from e

    def accounts(self):
        """Return connected Instagram/YouTube accounts visible to this API key."""
        result = self._json_request("GET", f"{API_ROOT}/accounts?status=connected")
        data = result.get("data", result) if isinstance(result, dict) else result
        if isinstance(data, dict):
            data = data.get("accounts", data.get("items", data.get("data", [])))
        if not isinstance(data, list):
            raise RuntimeError("Zernio returned an unexpected accounts response.")
        out = []
        for account in data:
            if not isinstance(account, dict) or account.get("platform") not in ("instagram", "youtube"):
                continue
            aid = account.get("accountId") or account.get("id") or account.get("_id")
            if aid:
                out.append({"id": str(aid), "platform": account.get("platform"),
                            "name": account.get("displayName") or account.get("username") or str(aid),
                            "username": account.get("username", "")})
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
        req = urllib.request.Request(upload_url, data=path.read_bytes(), method="PUT",
                                     headers={"Content-Type": "video/mp4",
                                              "Content-Length": str(size)})
        try:
            with urllib.request.urlopen(req, timeout=300):
                pass
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Zernio media upload failed ({e.code}).") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Zernio media upload failed: {e.reason}") from e
        return public_url

    def publish_one(self, path, instagram_id=None, youtube_id=None, schedule_minutes=None):
        old = (self.instagram_id, self.youtube_id, self.schedule_minutes)
        self.instagram_id = (instagram_id if instagram_id is not None else self.instagram_id).strip()
        self.youtube_id = (youtube_id if youtube_id is not None else self.youtube_id).strip()
        if schedule_minutes is not None:
            self.schedule_minutes = max(0, int(schedule_minutes))
        try:
            self._publish(path)
        finally:
            self.instagram_id, self.youtube_id, self.schedule_minutes = old

    def _publish(self, path):
        path = pathlib.Path(path)
        try:
            caption_path = path.with_suffix(".txt")
            caption = caption_path.read_text(encoding="utf-8", errors="replace").strip() if caption_path.is_file() else ""
            lines = [line.strip() for line in caption.splitlines() if line.strip()]
            title = (lines[0] if lines else path.stem).replace("#", "").strip()[:100] or "AutoClip Short"
            content = caption[:2200] or title
            platforms = []
            if self.instagram_id:
                platforms.append({
                    "platform": "instagram",
                    "accountId": self.instagram_id,
                    "platformSpecificData": {"shareToFeed": True},
                })
            if self.youtube_id:
                platforms.append({
                    "platform": "youtube",
                    "accountId": self.youtube_id,
                    "platformSpecificData": {
                        "title": title,
                        "visibility": self.visibility,
                    },
                })
            public_url = self._upload(path)
            body = {
                "content": content,
                "mediaItems": [{"url": public_url, "type": "video"}],
                "platforms": platforms,
            }
            if self.schedule_minutes:
                when = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=self.schedule_minutes)
                body["scheduledFor"] = when.replace(microsecond=0).isoformat().replace("+00:00", "Z")
                body["timezone"] = "UTC"
            else:
                body["publishNow"] = True
            result = self._json_request("POST", f"{API_ROOT}/posts", body)
            post = (result.get("data") or result).get("post", {})
            state = post.get("status", "submitted")
            targets = ", ".join(p["platform"] for p in platforms)
            suffix = f" ({self.schedule_minutes} min delay)" if self.schedule_minutes else ""
            self.log(f"Zernio: {path.name} {state} to {targets}{suffix}.")
        except Exception as e:
            self.log(f"Zernio error for {path.name}: {e}")
