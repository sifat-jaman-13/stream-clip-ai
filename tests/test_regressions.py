import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import autoclip
import ai_highlights
from selfhost_publishers import PostizPublisher, _HTTP, _auto_publish
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
        self.assertLessEqual(rendered[0][0], 90)
        self.assertGreaterEqual(rendered[0][1], 90)

    def test_peak_centered_window_keeps_peak_and_duration_under_cap(self):
        for peak, duration, before, after in ((90, 180, 90, 90), (5, 120, 90, 90), (175, 180, 90, 90)):
            start, end = autoclip.clip_bounds(peak, duration, before, after, [])
            self.assertLessEqual(start, peak)
            self.assertGreaterEqual(end, peak)
            self.assertLessEqual(end - start, 60)

    def test_auto_post_failures_are_logged(self):
        logs = []
        publisher = MagicMock()
        publisher.name = "Postiz"
        publisher.log = logs.append
        publisher.publish_one.side_effect = RuntimeError("upload failed")
        _auto_publish(publisher, "clip.mp4")
        self.assertIn("Postiz auto-post error", logs[0])
        self.assertIn("upload failed", logs[0])

    def test_windows_reveal_opens_containing_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "clip.mp4"
            clip.touch()
            with patch.object(autoclip.os, "name", "nt"), patch.object(autoclip.subprocess, "Popen") as popen:
                autoclip.reveal(clip)
            self.assertEqual(popen.call_args.args[0], ["explorer.exe", str(Path(directory).resolve())])

    def test_publishing_save_without_account_fields_preserves_channel_ids(self):
        core = object.__new__(autoclip.Core)
        core.publishing = {"provider": "postiz", "postiz": {
            "api_key": "secret", "instagram_id": "ig-saved", "youtube_id": "yt-saved",
        }, "zernio": {}}
        core._make_publisher = MagicMock(return_value=object())
        with patch.object(autoclip, "save_publishing_settings"):
            core.publishing_save({"provider": "postiz", "api_key": "", "auto_post": True})
        self.assertEqual(core.publishing["postiz"]["instagram_id"], "ig-saved")
        self.assertEqual(core.publishing["postiz"]["youtube_id"], "yt-saved")

    def test_render_uses_accurate_output_side_seeking(self):
        engine = autoclip.Engine(autoclip.clean_cfg({"compute_device": "cpu"}), lambda *_: None)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            commands = []
            def fake_run(command, cwd, **_kwargs):
                commands.append(command)
                (Path(cwd) / command[-1]).write_bytes(b"video")
                return types.SimpleNamespace(returncode=0)
            with patch.object(autoclip, "OUT", output), patch.object(autoclip, "make_ass"), \
                 patch.object(autoclip, "run", side_effect=fake_run) as run_mock, \
                 patch.object(autoclip, "ffmpeg_exe", return_value="ffmpeg"):
                engine.render("input.mp4", 4, 12, [], "clip")
            command = commands[0]
            self.assertLess(command.index("-i"), command.index("-ss"))
            self.assertEqual(command[command.index("-ss") + 1], "4.00")

    def test_gemini_quota_exhaustion_falls_back_to_ollama(self):
        logs = []
        with patch.object(ai_highlights, "_gemini", side_effect=ai_highlights.AIProviderError("quota", quota=True)), \
             patch.object(ai_highlights, "_ollama", return_value={"moments": [{"time": 24, "score": 92}]}):
            moments = ai_highlights.select_moments("gemini", [(24, 25, "wow")], 60, {}, logs.append)
        self.assertEqual(moments, [(24, 92.0)])
        self.assertTrue(any("quota/rate limit" in line for line in logs))

    def test_gemini_nonquota_errors_do_not_switch_providers(self):
        with patch.object(ai_highlights, "_gemini", side_effect=ai_highlights.AIProviderError("bad key")), \
             patch.object(ai_highlights, "_ollama") as ollama:
            with self.assertRaisesRegex(ai_highlights.AIProviderError, "bad key"):
                ai_highlights.select_moments("gemini", [], 60, {})
        ollama.assert_not_called()

    def test_ollama_detection_rejects_nonlocal_hosts(self):
        with self.assertRaisesRegex(ai_highlights.AIProviderError, "localhost"):
            ai_highlights.ollama_models("http://example.com:11434")

    def test_ai_provider_json_requests_send_json_content_type(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"models": []}'
        with patch.object(ai_highlights.urllib.request, "urlopen", return_value=response) as urlopen:
            ai_highlights._json_request("http://127.0.0.1:11434/api/tags", {"ok": True})
        self.assertEqual(urlopen.call_args.args[0].get_header("Content-type"), "application/json")

    def test_ai_settings_keep_api_keys_out_of_public_status(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                saved = autoclip.save_ai_settings({"provider": "gemini", "gemini_api_key": "secret"})
                stored = path.read_text(encoding="utf-8")
            self.assertTrue(saved["gemini_key_set"])
            self.assertNotIn("secret", str(saved))
            self.assertIn("secret", stored)

    def test_newer_installed_version_is_not_reported_as_outdated(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"tag_name":"v1.1.5"}'
        with patch.object(autoclip, "APP_VERSION", "1.1.6"), patch.object(
            autoclip.urllib.request, "urlopen", return_value=response
        ):
            result = autoclip.check_app_update()
        self.assertFalse(result["update"])

    def test_large_v3_turbo_cache_uses_its_actual_hugging_face_namespace(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "hub" / "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"
            cache.mkdir(parents=True)
            response = MagicMock()
            response.__enter__.return_value.read.return_value = b'{"info":{"version":"1.0"}}'
            with patch.dict("os.environ", {"HF_HOME": directory}), \
                 patch.object(autoclip, "load_settings", return_value={"model": "large-v3-turbo"}), \
                 patch.object(autoclip, "run", return_value=types.SimpleNamespace(stdout="ffmpeg version 1.0")), \
                 patch.object(autoclip.importlib_metadata, "version", return_value="1.0"), \
                 patch.object(autoclip.urllib.request, "urlopen", return_value=response):
                result = autoclip.check_updates()
        model = next(item for item in result["items"] if item["name"] == "Speech model: large-v3-turbo")
        self.assertEqual(model["current"], "Cached")
        self.assertFalse(model["update"])

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
