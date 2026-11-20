import tempfile
import time
from pathlib import Path

from live_monitor import LiveMonitorRegistry, _Monitor, validate_monitor_config


def test_monitor_validates_hosts_and_normalizes_scheme():
    cfg = validate_monitor_config({"target": "www.twitch.tv/Example", "poll_interval": 1})
    assert cfg["target"] == "https://www.twitch.tv/Example"
    assert cfg["poll_interval"] == 10


def test_monitor_rejects_unrelated_host():
    try:
        validate_monitor_config({"target": "https://example.com/live"})
    except ValueError as exc:
        assert "Twitch and YouTube" in str(exc)
    else:
        raise AssertionError("unrelated host was accepted")


def test_monitor_starts_capture_once_when_stream_goes_live():
    with tempfile.TemporaryDirectory() as folder:
        online = [False]
        busy = [False]
        captures = []
        registry = LiveMonitorRegistry(
            Path(folder) / "live_monitors.json",
            probe=lambda target, quality: online[0],
            start_capture=lambda target: (captures.append(target), busy.__setitem__(0, True)),
            is_busy=lambda: busy[0],
            log=lambda message: None,
        )
        monitor = _Monitor(
            "monitor:test",
            {"target": "https://www.twitch.tv/test", "poll_interval": 0.01,
             "quality": "best", "enabled": True},
            registry,
        )
        registry._monitors[monitor.id] = monitor
        monitor.start()
        time.sleep(0.05)
        assert monitor.state in {"waiting", "starting"}
        online[0] = True
        time.sleep(0.08)
        assert captures == ["https://www.twitch.tv/test"]
        assert monitor.state == "clipping"
        monitor.stop()
        registry.shutdown()
