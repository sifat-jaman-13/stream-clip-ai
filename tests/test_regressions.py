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

    def test_render_uses_frame_accurate_input_seeking_for_captions(self):
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
            self.assertLess(command.index("-ss"), command.index("-i"))
            self.assertIn("-accurate_seek", command)
            self.assertEqual(command[command.index("-ss") + 1], "4.00")

    @unittest.skipUnless(autoclip.shutil.which("ffmpeg") or autoclip.ffmpeg_exe() != "ffmpeg", "FFmpeg is not installed")
    def test_render_burns_relative_captions_after_input_seek(self):
        ffmpeg = autoclip.ffmpeg_exe()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            output = root / "out"
            output.mkdir()
            created = autoclip.run([
                ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                "color=c=black:s=320x240:r=25:d=8", "-an", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", str(source),
            ], capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)
            cfg = autoclip.clean_cfg({"layout": "Fill (crop center)", "output_format": "16:9",
                                     "compute_device": "cpu", "caption_size": 150,
                                     "cta_enabled": False, "cta_voice_enabled": False})
            engine = autoclip.Engine(cfg, lambda *_: None)
            with patch.object(autoclip, "OUT", output), patch.dict(autoclip.OUTPUT_FORMATS, {"16:9": (320, 240)}):
                engine.render(source, 5, 8, [(5.1, 6.8, "CAPTION VISIBLE")], "caption-test")
            visible = autoclip.run([ffmpeg, "-v", "error", "-ss", "0.5", "-i",
                                    str(output / "caption-test.mp4"), "-vf", "format=gray",
                                    "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True)
            absent = autoclip.run([ffmpeg, "-v", "error", "-ss", "2.5", "-i",
                                   str(output / "caption-test.mp4"), "-vf", "format=gray",
                                   "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True)
            self.assertGreater(sum(value > 220 for value in visible.stdout), 1000)
            self.assertLess(sum(value > 220 for value in absent.stdout), 100)

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
                ai_highlights.select_moments("gemini", [(1, 2, "hello")], 60, {})
        ollama.assert_not_called()

    def test_ai_analysis_visits_every_transcript_window_and_offsets_results(self):
        prompts = []
        def fake_ollama(prompt, _config):
            prompts.append(prompt)
            return {"moments": [{"time": 10, "score": 80}]}
        words = [(time, time + 1, "highlight") for time in (10, 305, 610)]
        with patch.object(ai_highlights, "_ollama", side_effect=fake_ollama):
            moments = ai_highlights.select_moments("ollama", words, 611, {})
        self.assertEqual(moments, [(10, 80.0), (310, 80.0), (610, 80.0)])
        self.assertEqual(len(prompts), 3)

    def test_zero_score_threshold_does_not_turn_empty_ai_seconds_into_clips(self):
        engine = autoclip.Engine(autoclip.clean_cfg({"clips_per_chunk": 0, "min_score": 0}), lambda *_: None)
        engine.rms_per_second = lambda _path: autoclip.np.ones(120)
        with patch.object(autoclip, "load_ai_settings", return_value={"provider": "ollama"}), \
             patch.object(autoclip, "select_moments", return_value=[(35, 80.0)]):
            picks, duration = engine.find_peaks("clip.mp4", [])
        self.assertEqual(duration, 120)
        self.assertEqual(picks, [(35, 80.0)])

    def test_malformed_moments_string_becomes_provider_error(self):
        with self.assertRaisesRegex(ai_highlights.AIProviderError, "invalid moments JSON"):
            ai_highlights._parse_moments({"moments": "not json"}, 100)

    def test_ollama_requests_receive_a_context_window(self):
        with patch.object(ai_highlights, "ollama_models", return_value=["test-model"]), \
             patch.object(ai_highlights, "_json_request", return_value={"response": '{"moments":[]}'}) as request:
            ai_highlights._ollama("prompt", {"ollama_model": "test-model"})
        self.assertEqual(request.call_args.args[1]["options"]["num_ctx"], 8192)

    def test_ai_backend_calls_can_be_cancelled(self):
        cancel = __import__("threading").Event()
        timer = __import__("threading").Timer(0.05, cancel.set)
        timer.start()
        try:
            with patch.object(ai_highlights, "_ollama", side_effect=lambda *_: __import__("time").sleep(2)):
                with self.assertRaises(ai_highlights.AIAnalysisCancelled):
                    ai_highlights.select_moments("ollama", [(1, 2, "hello")], 60, {}, cancelled=cancel.is_set)
        finally:
            timer.cancel()

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
