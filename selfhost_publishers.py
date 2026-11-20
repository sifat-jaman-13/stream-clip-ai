"""Self-hosted Postiz and Mixpost publishers.

The adapters deliberately use the vendors' documented REST APIs. Credentials are
read from the local publishing configuration and are never returned to the UI.
"""
import datetime as _dt
import json
import mimetypes
import pathlib
import threading
import uuid
import urllib.error
import urllib.request


def _url(base, path):
    return str(base or "").rstrip("/") + "/" + path.lstrip("/")


def _json(result):
    try:
        return json.loads(result.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("Publisher returned invalid JSON.") from exc


class _HTTP:
    def __init__(self, log, headers):
        self.log = log
        self.headers = dict(headers)

    def request(self, method, url, body=None, headers=None, timeout=120):
        data = None if body is None else json.dumps(body).encode("utf-8")
        h = dict(self.headers)
        h.update(headers or {})
        if data is not None:
            h.setdefault("Content-Type", "application/json")
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return _json(res.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[-800:]
            raise RuntimeError(f"Publisher API {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Publisher connection failed: {exc.reason}") from exc

    def multipart(self, url, field, path, timeout=600):
        path = pathlib.Path(path)
        boundary = "----StreamSnip" + uuid.uuid4().hex
        payload = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
                f"filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
        data = head + payload + f"\r\n--{boundary}--\r\n".encode()
        headers = dict(self.headers)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        headers["Content-Length"] = str(len(data))
        req = urllib.request.Request(url, data=data, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return _json(res.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[-800:]
            raise RuntimeError(f"Publisher media upload {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Publisher media upload failed: {exc.reason}") from exc


def _caption(path):
    txt = pathlib.Path(path).with_suffix(".txt")
    caption = txt.read_text(encoding="utf-8", errors="replace").strip() if txt.is_file() else ""
    lines = [line.strip() for line in caption.splitlines() if line.strip()]
    title = (lines[0] if lines else pathlib.Path(path).stem).replace("#", "").strip()[:100]
    return caption[:2200] or title or "StreamSnip AI clip", title or "StreamSnip AI clip"


def _platform(value):
    value = str(value or "").strip().lower().replace("-", "_")
    if value.startswith("instagram"):
        return "instagram"
    if value in {"youtube", "youtube_shorts"}:
        return "youtube"
    if value in {"facebook", "facebook_page", "facebook_pages"}:
        return "facebook"
    if value in {"tiktok", "tik_tok"}:
        return "tiktok"
    return ""

def _auto_publish(publisher, path):
    try:
        publisher.publish_one(path)
    except Exception as exc:
        publisher.log(f"{publisher.name} auto-post error for {pathlib.Path(path).name}: {exc}")


class PostizPublisher:
    name = "Postiz"

    def __init__(self, log, config=None):
        self.log = log
        self.configure(config or {})

    def configure(self, config):
        self.enabled = bool(config.get("enabled", config.get("auto_post", False)))
        self.base = str(config.get("base_url", "")).strip().rstrip("/")
        self.key = str(config.get("api_key", "")).strip()
        self.instagram_id = str(config.get("instagram_id", "")).strip()
        self.youtube_id = str(config.get("youtube_id", "")).strip()
        self.facebook_id = str(config.get("facebook_id", "")).strip()
        self.tiktok_id = str(config.get("tiktok_id", "")).strip()
        self.tiktok_consent = bool(config.get("tiktok_consent", False))
        self.visibility = str(config.get("visibility", "public")).lower()
        self.delay = max(0, int(config.get("schedule_minutes", 0) or 0))
        self.http = _HTTP(self.log, {"Authorization": self.key, "User-Agent": "StreamSnipAI/1.1"})

    def accounts(self):
        if not self.base:
            raise RuntimeError("Enter the URL of your self-hosted Postiz instance. StreamSnip will not connect to paid Postiz Cloud by default.")
        result = self.http.request("GET", _url(self.base, "/public/v1/integrations"))
        rows = result.get("integrations", result.get("data", result)) if isinstance(result, dict) else result
        out = []
        for row in rows if isinstance(rows, list) else []:
            platform = _platform(row.get("providerIdentifier", row.get("platform", "")))
            if not platform:
                continue
            out.append({"id": str(row.get("id", "")), "platform": platform,
                        "name": row.get("name") or row.get("profile", {}).get("username") or row.get("id", "")})
        return [x for x in out if x["id"]]

    def submit(self, video_path):
        if not (self.enabled and self.key and (self.instagram_id or self.youtube_id or self.facebook_id or self.tiktok_id)):
            return
        threading.Thread(target=_auto_publish, args=(self, video_path), daemon=True, name="postiz-publisher").start()

    def _upload(self, path):
        result = self.http.multipart(_url(self.base, "/public/v1/upload"), "file", path)
        if not result.get("id") or not result.get("path"):
            raise RuntimeError("Postiz did not return uploaded media details.")
        return {"id": result["id"], "path": result["path"]}

    def publish_one(self, path, instagram_id=None, youtube_id=None, schedule_minutes=None,
                    facebook_id=None, tiktok_id=None, tiktok_consent=None):
        caption, title = _caption(path)
        ig = str(self.instagram_id if instagram_id is None else instagram_id).strip()
        yt = str(self.youtube_id if youtube_id is None else youtube_id).strip()
        fb = str(self.facebook_id if facebook_id is None else facebook_id).strip()
        tt = str(self.tiktok_id if tiktok_id is None else tiktok_id).strip()
        consent = self.tiktok_consent if tiktok_consent is None else bool(tiktok_consent)
        delay = self.delay if schedule_minutes is None else max(0, int(schedule_minutes))
        if tt and not consent:
            raise RuntimeError("TikTok publishing is paused until you confirm in Publishing settings that StreamSnip may directly publish these videos.")
        media = self._upload(path)
        posts = []
        if ig:
            posts.append({"integration": {"id": ig}, "value": [{"content": caption, "image": [media]}],
                          "settings": {"__type": "instagram", "post_type": "post"}})
        if yt:
            posts.append({"integration": {"id": yt}, "value": [{"content": caption, "image": [media]}],
                          "settings": {"__type": "youtube", "title": title[:100], "type": self.visibility,
                                       "selfDeclaredMadeForKids": "no", "tags": []}})
        if fb:
            posts.append({"integration": {"id": fb}, "value": [{"content": caption, "image": [media]}],
                          "settings": {"__type": "facebook", "post_type": "post", "title": title[:100]}})
        if tt:
            posts.append({"integration": {"id": tt}, "value": [{"content": caption, "image": [media]}],
                          "settings": {"__type": "tiktok", "title": title[:90],
                                       "privacy_level": "PUBLIC_TO_EVERYONE", "duet": False,
                                       "stitch": False, "comment": False, "autoAddMusic": "no",
                                       "brand_content_toggle": False, "brand_organic_toggle": False,
                                       "video_made_with_ai": False, "content_posting_method": "DIRECT_POST"}})
        if not posts:
            raise RuntimeError("Select at least one Postiz integration.")
        body = {"type": "schedule" if delay else "now", "date": (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=delay)).isoformat(),
                "shortLink": False, "tags": [], "posts": posts}
        self.http.request("POST", _url(self.base, "/public/v1/posts"), body)
        self.log(f"Postiz: {pathlib.Path(path).name} submitted to {len(posts)} channel(s).")


class MixpostPublisher:
    name = "Mixpost"

    def __init__(self, log, config=None):
        self.log = log
        self.configure(config or {})

    def configure(self, config):
        self.enabled = bool(config.get("enabled", config.get("auto_post", False)))
        self.base = str(config.get("base_url", "")).strip().rstrip("/")
        self.workspace = str(config.get("workspace", "")).strip()
        self.key = str(config.get("api_key", "")).strip()
        self.instagram_id = str(config.get("instagram_id", "")).strip()
        self.youtube_id = str(config.get("youtube_id", "")).strip()
        self.facebook_id = str(config.get("facebook_id", "")).strip()
        self.tiktok_id = str(config.get("tiktok_id", "")).strip()
        self.visibility = str(config.get("visibility", "public")).lower()
        self.delay = max(0, int(config.get("schedule_minutes", 0) or 0))
        self.http = _HTTP(self.log, {"Authorization": "Bearer " + self.key, "Accept": "application/json", "User-Agent": "StreamSnipAI/1.1"})

    def _path(self, suffix):
        if not self.base or not self.workspace:
            raise RuntimeError("Enter the Mixpost base URL and workspace UUID first.")
        return _url(self.base, f"api/{self.workspace}/{suffix.lstrip('/')}")

    def accounts(self):
        result = self.http.request("GET", self._path("accounts"))
        rows = result.get("data", result) if isinstance(result, dict) else result
        out = []
        for row in rows if isinstance(rows, list) else []:
            platform = _platform(row.get("provider", row.get("platform", row.get("name", ""))))
            if not platform or platform == "tiktok":
                continue
            out.append({"id": str(row.get("id", row.get("uuid", ""))), "platform": platform,
                        "name": row.get("name") or row.get("username") or row.get("id", "")})
        return [x for x in out if x["id"]]

    def submit(self, video_path):
        if not (self.enabled and self.key and self.base and self.workspace and
                (self.instagram_id or self.youtube_id or self.facebook_id or self.tiktok_id)):
            return
        threading.Thread(target=_auto_publish, args=(self, video_path), daemon=True, name="mixpost-publisher").start()

    def _upload(self, path):
        result = self.http.multipart(self._path("media"), "file", path)
        data = result.get("data", result) if isinstance(result, dict) else {}
        media_id = data.get("id") or data.get("uuid")
        if not media_id:
            raise RuntimeError("Mixpost did not return uploaded media details. Files over 10 MB may require the chunked upload flow on your instance.")
        return media_id

    def publish_one(self, path, instagram_id=None, youtube_id=None, schedule_minutes=None,
                    facebook_id=None, tiktok_id=None, tiktok_consent=None):
        caption, title = _caption(path)
        ig = str(self.instagram_id if instagram_id is None else instagram_id).strip()
        yt = str(self.youtube_id if youtube_id is None else youtube_id).strip()
        fb = str(self.facebook_id if facebook_id is None else facebook_id).strip()
        tt = str(self.tiktok_id if tiktok_id is None else tiktok_id).strip()
        if tt:
            raise RuntimeError("Mixpost Lite does not support TikTok. Use a compatible self-hosted Postiz instance; Mixpost TikTok requires its paid editions and platform app approval.")
        delay = self.delay if schedule_minutes is None else max(0, int(schedule_minutes))
        media_id = self._upload(path)
        accounts = [int(x) if x.isdigit() else x for x in (ig, yt, fb) if x]
        if not accounts:
            raise RuntimeError("Select at least one Mixpost account.")
        versions = [{"account_id": 0, "is_original": True, "content": [{"body": caption, "media": [media_id]}]}]
        body = {"accounts": accounts, "versions": versions, "queue": not bool(delay), "schedule": bool(delay), "schedule_now": not bool(delay)}
        if delay:
            when = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=delay)
            body.update({"date": when.date().isoformat(), "time": when.strftime("%H:%M"), "timezone": "UTC"})
        self.http.request("POST", self._path("posts"), body)
        self.log(f"Mixpost: {pathlib.Path(path).name} submitted to {len(accounts)} channel(s).")


def publisher_for(provider, log, config):
    if provider == "postiz":
        return PostizPublisher(log, config)
    if provider == "mixpost":
        return MixpostPublisher(log, config)
    return None
