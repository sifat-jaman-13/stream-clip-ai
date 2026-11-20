import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import autoclip
from selfhost_publishers import PostizPublisher, _HTTP
from zernio_poster import ZernioPublisher


class RegressionTests(unittest.TestCase):
    def test_publishing_auto_post_defaults_to_off_and_submit_obeys_toggle(self):
        core = object.__new__(autoclip.Core)
        core.publishing = {
            "provider": "postiz",
            "postiz": {"api_key": "secret", "instagram_id": "account"},
        }
        publisher = core._make_publisher("postiz")
        self.assertFalse(publisher.enabled)
        with patch("selfhost_publishers.threading.Thread") as thread:
            publisher.submit("clip.mp4")
            thread.assert_not_called()

        core.publishing["postiz"]["auto_post"] = True
        publisher = core._make_publisher("postiz")
        self.assertTrue(publisher.enabled)
        with patch("selfhost_publishers.threading.Thread") as thread:
            publisher.submit("clip.mp4")
            thread.assert_called_once()

    def test_self_hosted_json_requests_set_content_type(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with patch("selfhost_publishers.urllib.request.urlopen", return_value=response) as urlopen:
            _HTTP(lambda _: None, {}).request("POST", "https://example.invalid/api", {"ok": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Content-type"), "application/json")

    def test_zernio_manual_publish_propagates_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"video")
            logs = []
            publisher = ZernioPublisher(logs.append, {"instagram_id": "account"})
            publisher._upload = MagicMock(side_effect=RuntimeError("upload failed"))
            with self.assertRaisesRegex(RuntimeError, "upload failed"):
                publisher.publish_one(video)
            self.assertTrue(any("Zernio error" in line for line in logs))

    def test_cpu_model_fallback_is_reused_for_gpu_preference(self):
        attempts = []

        def fake_model(name, device, compute_type):
            attempts.append((name, device, compute_type))
            if device == "cuda":
                raise RuntimeError("CUDA unavailable")
            return object()

        old_model, old_key = autoclip._model, autoclip._model_key
        autoclip._model = autoclip._model_key = None
        try:
            engine = autoclip.Engine(autoclip.clean_cfg({}), lambda *_: None)
            with patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=fake_model)}):
                first = engine.get_model("distil-large-v3")
                second = engine.get_model("distil-large-v3")
            self.assertIs(first, second)
            self.assertEqual(sum(device == "cpu" for _, device, _ in attempts), 1)
        finally:
            autoclip._model, autoclip._model_key = old_model, old_key

    def test_clip_duration_is_capped_at_sixty_seconds(self):
        engine = autoclip.Engine(
            autoclip.clean_cfg({"mode": "file", "pre": 90, "post": 90}),
            lambda *_: None,
        )
        engine.transcribe = lambda _: [(0.0, 1.0, "hello"), (60.0, 61.0, "again")]
        engine.find_peaks = lambda *_: ([(90, 99.0)], 180)
        rendered = []
        engine.render = lambda _src, start, end, *_: rendered.append((start, end))
        engine.process("long-video.mp4")
        self.assertEqual(len(rendered), 1)
        self.assertLessEqual(rendered[0][1] - rendered[0][0], 60)

    def test_nonfinite_settings_use_defaults(self):
        cfg = autoclip.clean_cfg({"min_score": float("inf"), "cam_x": float("nan")})
        self.assertEqual(cfg["min_score"], autoclip.DEFAULTS["min_score"])
        self.assertEqual(cfg["cam_x"], autoclip.DEFAULTS["cam_x"])

    def test_missing_ffprobe_does_not_claim_audio_is_absent(self):
        with tempfile.TemporaryDirectory() as directory:
            ffmpeg = Path(directory) / "ffmpeg.exe"
            ffmpeg.touch()
            with patch.object(autoclip, "ffmpeg_exe", return_value=str(ffmpeg)), patch.object(
                autoclip.shutil, "which", return_value=None
            ):
                self.assertIsNone(autoclip.has_audio_stream(ffmpeg))

    def test_frozen_app_finds_ffmpeg_next_to_its_executable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            internal = root / "_internal"
            internal.mkdir()
            ffmpeg_dir = root / "vendor" / "ffmpeg"
            ffmpeg_dir.mkdir(parents=True)
            ffmpeg = ffmpeg_dir / ("ffmpeg.exe" if autoclip.os.name == "nt" else "ffmpeg")
            ffmpeg.touch()
            with patch.object(autoclip, "HERE", internal), patch.object(
                autoclip.sys, "executable", str(root / ("AutoClip.exe" if autoclip.os.name == "nt" else "AutoClip"))
            ):
                self.assertEqual(autoclip.ffmpeg_exe(), str(ffmpeg))

    def test_page_reload_does_not_quit_application(self):
        self.assertNotIn('window.addEventListener("pagehide"', autoclip.HTML)
        self.assertIn('api("/api/quit")', autoclip.HTML)
        self.assertIn('const center=h("button",{class:"btn ghost"},"Center segment")', autoclip.HTML)


if __name__ == "__main__":
    unittest.main()
