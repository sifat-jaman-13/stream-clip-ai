"""Persistent live-stream monitor for StreamSnip AI.

The monitor owns detection and retry timing, while the existing clipping engine
continues to own recording, transcription, rendering, and optional publishing.
Callbacks are injected so this module stays independent of the HTTP server and
is straightforward to test with a fake stream probe.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from pathlib import Path


SUPPORTED_HOSTS = ("twitch.tv", "youtube.com", "youtu.be")


def monitor_id(target: str) -> str:
    return "monitor:" + hashlib.sha256(target.encode("utf-8")).hexdigest()[:20]


def validate_monitor_config(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Monitor settings must be an object.")
    target = str(raw.get("target") or "").strip().strip('"')
    if re.match(r"(?i)^(?:www\.)?(?:twitch\.tv|youtube\.com|youtu\.be)/", target):
        target = "https://" + target
    if not re.match(r"^https?://", target, re.I):
        raise ValueError("Enter a full Twitch or YouTube URL.")
    host = target.split("/", 3)[2].split(":", 1)[0].lower()
    if not any(host == h or host.endswith("." + h) for h in SUPPORTED_HOSTS):
        raise ValueError("Only Twitch and YouTube live URLs are supported.")
    poll = raw.get("poll_interval", 30)
    try:
        poll = max(10, min(3600, int(poll)))
    except (TypeError, ValueError):
        poll = 30
    return {
        "target": target,
        "poll_interval": poll,
        "quality": str(raw.get("quality") or "1080p60,1080p,720p60,720p,best"),
        "enabled": bool(raw.get("enabled", True)),
    }


class _Monitor:
    def __init__(self, mid, config, registry):
        self.id = mid
        self.config = config
        self.registry = registry
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.state = "starting"
        self.message = "Starting live monitor..."
        self.checks = 0
        self.last_check = None
        self.last_live = None
        self.last_error = ""
        self.active_run = False
        self.created = time.time()

    def snapshot(self):
        with self.lock:
            return {
                "id": self.id,
                "target": self.config["target"],
                "poll_interval": self.config["poll_interval"],
                "quality": self.config["quality"],
                "enabled": self.config["enabled"],
                "state": self.state,
                "message": self.message,
                "checks": self.checks,
                "last_check": self.last_check,
                "last_live": self.last_live,
                "last_error": self.last_error,
                "active_run": self.active_run,
            }

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True, name="live-monitor")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        with self.lock:
            self.state = "stopped"
            self.message = "Monitor stopped."
            self.active_run = False

    def _set(self, state, message, error=""):
        with self.lock:
            self.state, self.message, self.last_error = state, message, error
        self.registry._persist()
        self.registry.log(f"Live monitor: {message}")

    def _run(self):
        while not self.stop_event.is_set():
            if not self.config["enabled"]:
                self._set("paused", "Monitor is paused.")
                self.stop_event.wait(self.config["poll_interval"])
                continue
            with self.lock:
                self.checks += 1
                self.last_check = time.time()
            try:
                live = bool(self.registry.probe(self.config["target"], self.config["quality"]))
                with self.lock:
                    self.last_live = time.time() if live else None
                if live:
                    if self.active_run and self.registry.is_busy():
                        self._set("clipping", "Stream is live; clipping is running.")
                    elif not self.active_run and self.registry.is_busy():
                        self._set("queued", "Stream is live; waiting for the current clip run to finish.")
                    elif not self.active_run:
                        self._set("live", "Stream is live; starting clipping.")
                        self.registry.start_capture(self.config["target"])
                        with self.lock:
                            self.active_run = True
                        self._set("clipping", "Stream is live; clipping is running.")
                    else:
                        with self.lock:
                            self.active_run = False
                        self._set("live", "Clip run finished; monitoring the live stream.")
                else:
                    if self.active_run and not self.registry.is_busy():
                        with self.lock:
                            self.active_run = False
                    self._set("waiting", "Stream is offline; checking again automatically.")
            except Exception as exc:
                self._set("error", "Live check failed; retrying automatically.", str(exc))
            self.stop_event.wait(self.config["poll_interval"])


class LiveMonitorRegistry:
    def __init__(self, state_path: Path, probe, start_capture, is_busy, log):
        self.state_path = Path(state_path)
        self.probe = probe
        self.start_capture = start_capture
        self.is_busy = is_busy
        self.log = log
        self.lock = threading.RLock()
        self._monitors = {}
        self._load()

    def start(self, raw):
        config = validate_monitor_config(raw)
        mid = monitor_id(config["target"])
        with self.lock:
            old = self._monitors.get(mid)
            if old and old.thread and old.thread.is_alive():
                raise ValueError("That stream is already being monitored.")
            mon = _Monitor(mid, config, self)
            self._monitors[mid] = mon
            self._persist()
            mon.start()
        return mon.snapshot()

    def stop(self, mid=None):
        with self.lock:
            selected = list(self._monitors.values()) if not mid else [self._monitors.get(mid)]
            selected = [m for m in selected if m]
            if mid and not selected:
                raise ValueError("Live monitor not found.")
            for mon in selected:
                mon.stop()
            self._persist()
            return {"monitors": [m.snapshot() for m in self._monitors.values()]}

    def update(self, mid, partial):
        with self.lock:
            mon = self._monitors.get(mid)
            if not mon:
                raise ValueError("Live monitor not found.")
            if "target" in partial and str(partial["target"]).strip() != mon.config["target"]:
                raise ValueError("The monitored URL cannot change while it is running; stop and start it again.")
            cfg = validate_monitor_config({**mon.config, **partial})
            mon.config.update(cfg)
            self._persist()
            return mon.snapshot()

    def status(self, mid=None):
        with self.lock:
            if mid:
                mon = self._monitors.get(mid)
                if not mon:
                    raise ValueError("Live monitor not found.")
                return mon.snapshot()
            return {"monitors": [m.snapshot() for m in self._monitors.values()]}

    def shutdown(self):
        with self.lock:
            for mon in self._monitors.values():
                mon.stop()
            self._persist()

    def _persist(self):
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            data = {"monitors": {mid: mon.snapshot() for mid, mon in self._monitors.items()}}
            self.state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def _load(self):
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            for mid, snap in (data.get("monitors") or {}).items():
                cfg = validate_monitor_config(snap)
                mon = _Monitor(mid, cfg, self)
                mon.state = "paused"
                mon.message = "Saved monitor; press Start to resume."
                self._monitors[mid] = mon
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass
