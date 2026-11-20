import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import autoclip
import ai_highlights
from zernio_poster import ZernioPublisher


class RegressionTests(unittest.TestCase):
    def test_publishing_auto_post_defaults_to_off_and_submit_obeys_toggle(self):
        core = object.__new__(autoclip.Core)
        core.publishing = {
            "provider": "zernio",
            "zernio": {"api_key": "secret", "instagram_id": "account"},
        }
        publisher = core._make_publisher("zernio")
        self.assertFalse(publisher.enabled)
        with patch("zernio_poster.threading.Thread") as thread:
            publisher.submit("clip.mp4")
            thread.assert_not_called()

        core.publishing["zernio"]["auto_post"] = True
        publisher = core._make_publisher("zernio")
        self.assertTrue(publisher.enabled)
        with patch("zernio_poster.threading.Thread") as thread:
            publisher.submit("clip.mp4")
            thread.assert_called_once()

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

    def test_zernio_empty_success_response_is_valid(self):
        publisher = ZernioPublisher(lambda _: None)
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b""
        with patch("zernio_poster.urllib.request.urlopen", return_value=response):
            result = publisher._json_request("POST", "https://example.invalid")
        self.assertEqual(result, {})

    def test_zernio_transient_dns_failure_is_retried(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"data": []}'
        dns_error = __import__("urllib.error").error.URLError(
            __import__("socket").gaierror(11001, "getaddrinfo failed")
        )
        publisher = ZernioPublisher(lambda _: None)
        with patch("zernio_poster.urllib.request.urlopen", side_effect=[dns_error, response]) as urlopen, \
             patch("zernio_poster.time.sleep") as sleep:
            result = publisher._json_request("GET", "https://zernio.com/api/v1/accounts")
        self.assertEqual(result, {"data": []})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once()

    def test_zernio_persistent_dns_failure_is_actionable(self):
        dns_error = __import__("urllib.error").error.URLError(
            __import__("socket").gaierror(11001, "getaddrinfo failed")
        )
        publisher = ZernioPublisher(lambda _: None)
        with patch("zernio_poster.urllib.request.urlopen", side_effect=dns_error), \
             patch("zernio_poster.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "DNS lookup failed after 3 attempts"):
                publisher._json_request("GET", "https://zernio.com/api/v1/accounts")

    def test_gemini_model_filter_excludes_non_text_models(self):
        response = {
            "models": [
                {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-robotics-er-1.5-preview", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-image-preview", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/gemini-embedding-001", "supportedGenerationMethods": ["embedContent"]},
            ]
        }
        with patch.object(ai_highlights, "_json_request", return_value=response):
            models = ai_highlights._gemini_available_models("key")
        self.assertIn("gemini-3.8-flash", models)
        self.assertIn("gemini-2.5-pro", models)
        self.assertNotIn("gemini-image-preview", models)
        self.assertNotIn("gemini-robotics-er-1.5-preview", models)
        self.assertNotIn("gemini-embedding-001", models)

    def test_gemini_model_discovery_does_not_truncate_usable_models(self):
        response = {"models": [
            {"name": f"models/gemini-test-{index}-flash",
             "supportedGenerationMethods": ["generateContent"]}
            for index in range(12)
        ]}
        with patch.object(ai_highlights, "_json_request", return_value=response):
            models = ai_highlights._gemini_available_models("key")
        self.assertEqual(len(models), 12)

    def test_gemini_connection_test_checks_generation(self):
        response = {"candidates": [{"content": {"parts": [{"text": "STREAMSNIP_OK"}]}}]}
        with patch.object(ai_highlights, "_gemini_available_models", return_value=["gemini-2.5-flash"]), \
             patch.object(ai_highlights, "_json_request", return_value=response) as request:
            result = ai_highlights.test_provider("gemini", {
                "gemini_api_key": "secret", "gemini_model": "gemini-3.8-flash",
            })
        self.assertTrue(result["ok"])
        self.assertEqual(result["model"], "gemini-3.8-flash")
        self.assertIn("generateContent", request.call_args.args[0])
        self.assertIn("gemini-3.8-flash", request.call_args.args[0])
        self.assertNotIn("secret", str(result))

    def test_gemini_connection_test_retries_each_model_three_times(self):
        failure = ai_highlights.AIProviderError("HTTP 404: retired", retryable=True)
        success = {"candidates": [{"content": {"parts": [{"text": "STREAMSNIP_OK"}]}}]}
        with patch.object(ai_highlights, "_gemini_available_models",
                          return_value=["gemini-3.8-flash", "gemini-backup-flash"]), \
             patch.object(ai_highlights, "_json_request",
                          side_effect=[failure, failure, failure, success]) as request, \
             patch.object(ai_highlights.time, "sleep"):
            result = ai_highlights.test_provider("gemini", {
                "gemini_api_key": "secret", "gemini_model": "gemini-3.8-flash",
            })
        self.assertEqual(result["model"], "gemini-backup-flash")
        self.assertEqual(request.call_count, 4)
        first_urls = [call.args[0] for call in request.call_args_list[:3]]
        self.assertTrue(all("gemini-3.8-flash" in url for url in first_urls))

    def test_huggingface_connection_test_checks_auth_and_inference(self):
        responses = [
            {"type": "user"},
            {"choices": [{"message": {"content": "STREAMSNIP_OK"}}]},
        ]
        with patch.object(ai_highlights, "_json_request", side_effect=responses) as request:
            result = ai_highlights.test_provider("huggingface", {
                "huggingface_token": "hf_secret",
                "huggingface_model": ai_highlights.DEFAULT_HUGGINGFACE_MODEL,
            })
        self.assertTrue(result["ok"])
        self.assertEqual(request.call_count, 2)
        self.assertIn("whoami-v2", request.call_args_list[0].args[0])
        self.assertIn("chat/completions", request.call_args_list[1].args[0])
        self.assertNotIn("hf_secret", str(result))

    def test_huggingface_connection_test_explains_rejected_token(self):
        with patch.object(ai_highlights, "_json_request",
                          side_effect=ai_highlights.AIProviderError("HTTP 401: invalid token")):
            with self.assertRaisesRegex(ai_highlights.AIProviderError, "Create a new token"):
                ai_highlights.test_provider("huggingface", {
                    "huggingface_token": "hf_invalid",
                    "huggingface_model": ai_highlights.DEFAULT_HUGGINGFACE_MODEL,
                })

    def test_gemini_connection_test_explains_rejected_key(self):
        with patch.object(ai_highlights, "_gemini_available_models",
                          side_effect=ai_highlights.AIProviderError("HTTP 403: forbidden")):
            with self.assertRaisesRegex(ai_highlights.AIProviderError, "Gemini rejected this API key"):
                ai_highlights.test_provider("gemini", {
                    "gemini_api_key": "invalid", "gemini_model": "gemini-3.8-flash",
                })

    def test_retired_huggingface_default_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            path.write_text(__import__("json").dumps({
                "huggingface_model": "Qwen/Qwen2.5-7B-Instruct-1M",
            }), encoding="utf-8")
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                settings = autoclip.load_ai_settings()
        self.assertEqual(settings["huggingface_model"], ai_highlights.DEFAULT_HUGGINGFACE_MODEL)

    def test_retired_gemini_model_is_migrated(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            path.write_text(__import__("json").dumps({
                "gemini_model": "gemini-2.5-flash",
            }), encoding="utf-8")
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                settings = autoclip.load_ai_settings()
        self.assertEqual(settings["gemini_model"], ai_highlights.DEFAULT_GEMINI_MODEL)

    def test_common_hype_words_are_not_scored(self):
        for word in ("what", "actually", "literally", "hello", "stop", "mad", "gas", "clean", "peak", "send"):
            self.assertNotIn(word, autoclip.HYPE_WORDS)

    def test_graceful_live_stop_keeps_producers_running_until_close(self):
        engine = object.__new__(autoclip.Engine)
        engine.cfg = {"mode": "live"}
        engine.stop_flag = False
        engine.abort = False
        engine.ai_cancel = __import__("threading").Event()
        process = MagicMock()
        process.poll.return_value = None
        process.pid = None
        process.wait.return_value = 0
        engine.procs = [process]

        engine.stop(force=False)

        process.terminate.assert_not_called()
        self.assertTrue(engine.stop_flag)
        self.assertFalse(engine.abort)

    def test_graceful_live_stop_force_terminates_producers(self):
        engine = object.__new__(autoclip.Engine)
        engine.cfg = {"mode": "live"}
        engine.stop_flag = False
        engine.abort = False
        engine.ai_cancel = __import__("threading").Event()
        process = MagicMock()
        process.poll.return_value = None
        process.pid = None
        process.wait.return_value = 0
        engine.procs = [process]

        engine.stop(force=True)

        process.terminate.assert_called_once_with()
        self.assertTrue(engine.abort)

    def test_force_shutdown_escalates_a_stuck_child(self):
        process = MagicMock()
        process.poll.return_value = None
        process.pid = None
        process.wait.side_effect = [__import__("subprocess").TimeoutExpired("child", 1), 0]

        autoclip.terminate_process_tree(process, force=True, timeout=0.01)

        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()

    def test_core_shutdown_stops_engine_children_before_waiting(self):
        core = object.__new__(autoclip.Core)
        core.lock = __import__("threading").RLock()
        core.engine = MagicMock()
        core.worker = MagicMock()
        core.worker.is_alive.return_value = True
        core.running = True
        core.phase = "recording"
        core.status = "Recording"
        core.progress = 50

        with patch.object(autoclip, "shutdown_child_processes") as shutdown_children:
            core.shutdown()

        core.engine.stop.assert_called_once_with(force=True)
        core.worker.join.assert_called_once_with(timeout=6)
        self.assertEqual(shutdown_children.call_count, 2)
        self.assertFalse(core.running)

    def test_zernio_upload_streams_file_instead_of_reading_all_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"video-data")
            publisher = ZernioPublisher(lambda _: None)
            publisher._json_request = MagicMock(side_effect=[
                {"uploadUrl": "https://upload.invalid/video", "publicUrl": "https://cdn.invalid/video.mp4"}
            ])
            uploaded = {}
            def fake_urlopen(request, timeout):
                uploaded["header"] = request.get_header("Content-length")
                uploaded["reader"] = request.data.read()
                return __import__("contextlib").nullcontext(MagicMock())

            with patch.object(autoclip.urllib.request, "urlopen", side_effect=fake_urlopen):
                with patch.object(__import__("zernio_poster").urllib.request, "urlopen", side_effect=fake_urlopen):
                    public_url = publisher._upload(video)

            self.assertEqual(public_url, "https://cdn.invalid/video.mp4")
            self.assertEqual(uploaded["header"], "10")
            self.assertEqual(uploaded["reader"], b"video-data")

    def test_gpu_failure_does_not_silently_fall_back_to_cpu(self):
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
            with patch.object(autoclip, "preferred_speech_device", return_value="cuda"), \
                 patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=fake_model)}):
                with self.assertRaisesRegex(RuntimeError, "CPU fallback is disabled"):
                    engine.get_model("distil-large-v3")
            self.assertEqual([device for _, device, _ in attempts], ["cuda", "cuda"])
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

    def test_clip_bounds_do_not_extend_to_unrelated_later_speech(self):
        words = [(33.8, 36.0, "nearby"), (75.0, 76.0, "unrelated")]
        start, end = autoclip.clip_bounds(30, 180, 10, 5, words)
        self.assertEqual(start, 20)
        self.assertLessEqual(end, 36.5)

    def test_quiet_top_ai_candidate_does_not_cancel_lower_candidates(self):
        engine = object.__new__(autoclip.Engine)
        engine.cfg = {"min_score": 70, "clips_per_chunk": 0, "chunk_min": 3}
        engine.ai_cancel = __import__("threading").Event()
        engine.log = MagicMock()
        engine.status = MagicMock()
        engine.rms_per_second = lambda _path: __import__("numpy").ones(201) * 0.01

        def picks(*_args):
            return [(100, 100), (20, 90), (160, 80)]

        engine.rms_per_second = lambda _path: __import__("numpy").where(
            __import__("numpy").arange(201) == 100,
            0.001,
            0.01,
        )
        with patch.object(autoclip, "load_custom", return_value=[]), \
             patch.object(autoclip, "load_ai_settings", return_value={"provider": "gemini"}), \
             patch.object(autoclip, "select_moments", side_effect=picks):
            found, _duration = engine.find_peaks("clip.mp4", [])

        self.assertIn(20, [p for p, _score in found])
        self.assertIn(160, [p for p, _score in found])

    def test_settings_version_migrates_low_score_only_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(autoclip, "SETTINGS_FILE", path):
                path.write_text(__import__("json").dumps({"min_score": 3}), encoding="utf-8")
                migrated = autoclip.load_settings()
                autoclip.save_settings(migrated)
                reloaded = autoclip.load_settings()

        self.assertEqual(migrated["min_score"], 100.0)
        self.assertEqual(reloaded["min_score"], 100.0)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            with patch.object(autoclip, "SETTINGS_FILE", path):
                path.write_text(__import__("json").dumps({"min_score": 3, "_settings_version": 2}), encoding="utf-8")
                unchanged = autoclip.load_settings()
        self.assertEqual(unchanged["min_score"], 3.0)

    def test_clip_bounds_random_windows_always_contain_peak(self):
        random = __import__("random")
        for _ in range(20000):
            duration = random.uniform(60, 500)
            peak = random.uniform(0, duration)
            before = random.uniform(3, 90)
            after = random.uniform(3, 90)
            words = [(s, s + 1, "word") for s in (random.uniform(0, duration),)]
            start, end = autoclip.clip_bounds(peak, duration, before, after, words)
            self.assertLessEqual(start, peak)
            self.assertGreaterEqual(end, peak)
            self.assertLessEqual(end - start, 60.000001)

    def test_ass_keeps_overlapping_first_word_and_highlight_contrast(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "clip.ass"
            cfg = autoclip.clean_cfg({"show_tag_video": True, "target": "https://twitch.tv/channel"})
            autoclip.make_ass([(4.9, 5.5, "first"), (6.0, 6.5, "second")], 5, 10, path, cfg)
            subtitles = path.read_text(encoding="utf-8")
        self.assertIn("FIRST", subtitles)
        self.assertIn("Style: Default,Impact,100,&H00FFFFFF", subtitles)
        self.assertIn(r"{\1c&H00FFFF&", subtitles)
        self.assertIn(r"\1c&H00FFFFFF&", subtitles)

    def test_windows_reveal_opens_containing_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "clip.mp4"
            clip.touch()
            with patch.object(autoclip.os, "name", "nt"), patch.object(autoclip.subprocess, "Popen") as popen:
                autoclip.reveal(clip)
            self.assertEqual(popen.call_args.args[0], ["explorer.exe", str(Path(directory).resolve())])

    def test_publishing_save_without_account_fields_preserves_channel_ids(self):
        core = object.__new__(autoclip.Core)
        core.publishing = {"provider": "zernio", "zernio": {
            "api_key": "secret",
            "instagram_id": "ig-saved", "youtube_id": "yt-saved",
        }}
        core._make_publisher = MagicMock(return_value=object())
        with patch.object(autoclip, "save_publishing_settings"):
            core.publishing_save({"provider": "zernio", "api_key": "", "auto_post": True})
        self.assertEqual(core.publishing["zernio"]["instagram_id"], "ig-saved")
        self.assertEqual(core.publishing["zernio"]["youtube_id"], "yt-saved")

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
            self.assertIn("+genpts", command)
            filter_graph = command[command.index("-filter_complex") + 1]
            self.assertIn("setpts=PTS-STARTPTS", filter_graph)
            self.assertIn("asetpts=PTS-STARTPTS", command[command.index("-af") + 1])

    def test_live_capture_bitrate_defaults_and_clamps_to_6000_kbps(self):
        self.assertEqual(autoclip.clean_cfg({})["capture_bitrate_kbps"], 6000)
        self.assertEqual(autoclip.clean_cfg({"capture_bitrate_kbps": 1000})["capture_bitrate_kbps"], 6000)

    def test_gemini_tries_other_available_models_after_temporary_failure(self):
        calls = []
        def fake_request(url, payload=None, headers=None, timeout=90):
            calls.append(url)
            if url.endswith("/models?" + "pageSize=1000"):
                return {"models": [{"name": "models/gemini-backup-flash",
                                    "supportedGenerationMethods": ["generateContent"]}]}
            if "/gemini-3.8-flash:generateContent" in url:
                raise ai_highlights.AIProviderError("HTTP 503 busy", retryable=True)
            return {"candidates": [{"content": {"parts": [{"text": '{"moments":[]}'}]}}]}

        with patch.object(ai_highlights, "_json_request", side_effect=fake_request), \
             patch.object(ai_highlights.time, "sleep"):
            result = ai_highlights._gemini("transcript", {"gemini_api_key": "test-key",
                                                           "gemini_model": "gemini-3.8-flash"})
        self.assertEqual(result, {"moments": []})
        self.assertTrue(any("gemini-backup-flash:generateContent" in url for url in calls))
        self.assertEqual(sum("gemini-3.8-flash:generateContent" in url for url in calls), 3)

    def test_gemini_exhausts_three_attempts_for_every_model_before_fallback(self):
        generation_urls = []

        def fake_request(url, payload=None, headers=None, timeout=90):
            if "/models?" in url:
                return {"models": [
                    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-backup-flash", "supportedGenerationMethods": ["generateContent"]},
                ]}
            generation_urls.append(url)
            raise ai_highlights.AIProviderError("HTTP 503 busy", retryable=True)

        with patch.object(ai_highlights, "_json_request", side_effect=fake_request), \
             patch.object(ai_highlights.time, "sleep"):
            with self.assertRaisesRegex(ai_highlights.AIProviderError, "6 attempts across 2 model"):
                ai_highlights._gemini("transcript", {
                    "gemini_api_key": "test-key", "gemini_model": "gemini-3.8-flash",
                })
        self.assertEqual(len(generation_urls), 6)
        self.assertEqual(sum("gemini-3.8-flash" in url for url in generation_urls), 3)
        self.assertEqual(sum("gemini-backup-flash" in url for url in generation_urls), 3)

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

    def test_gemini_completes_full_retry_rotation_before_ollama(self):
        generation_urls = []
        logs = []

        def fake_request(url, payload=None, headers=None, timeout=90):
            if "/models?" in url:
                return {"models": [
                    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-backup-flash", "supportedGenerationMethods": ["generateContent"]},
                ]}
            generation_urls.append(url)
            raise ai_highlights.AIProviderError("HTTP 503 busy", retryable=True)

        with patch.object(ai_highlights, "_json_request", side_effect=fake_request), \
             patch.object(ai_highlights.time, "sleep"), \
             patch.object(ai_highlights, "_ollama",
                          return_value={"moments": [{"time": 24, "score": 92}]}) as ollama:
            moments = ai_highlights.select_moments(
                "gemini", [(24, 25, "wow")], 60,
                {"gemini_api_key": "test-key", "gemini_model": "gemini-3.8-flash"},
                logs.append,
            )
        self.assertEqual(moments, [(24, 92.0)])
        self.assertEqual(len(generation_urls), 6)
        self.assertEqual(sum("gemini-3.8-flash" in url for url in generation_urls), 3)
        self.assertEqual(sum("gemini-backup-flash" in url for url in generation_urls), 3)
        ollama.assert_called_once()
        self.assertTrue(any("Switching remaining transcript windows to local Ollama" in line for line in logs))

    def test_gemini_nonquota_errors_do_not_switch_providers(self):
        logs = []
        with patch.object(ai_highlights, "_gemini", side_effect=ai_highlights.AIProviderError("bad key")), \
             patch.object(ai_highlights, "_ollama") as ollama:
            moments = ai_highlights.select_moments("gemini", [(1, 2, "hello")], 60, {}, logs.append)
        self.assertEqual(moments, [])
        ollama.assert_not_called()
        self.assertTrue(any("Skipping this window" in line for line in logs))

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

    def test_extract_json_accepts_a_top_level_array(self):
        self.assertEqual(ai_highlights._extract_json('[{"time": 10, "score": 90}]'),
                         [{"time": 10, "score": 90}])

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
            model_file = cache / "snapshots" / "snapshot-id" / "model.bin"
            model_file.parent.mkdir(parents=True)
            model_file.touch()
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

    def test_window_close_quits_but_page_reload_can_reconnect(self):
        self.assertIn('window.addEventListener("pagehide"', autoclip.HTML)
        self.assertIn('api("/api/window/open")', autoclip.HTML)
        self.assertIn('fetch("/api/window/lease"', autoclip.HTML)
        self.assertIn('fetch("/api/window/closing"', autoclip.HTML)
        self.assertIn('api("/api/quit")', autoclip.HTML)
        self.assertIn('const center=h("button",{class:"btn ghost"},"Center segment")', autoclip.HTML)
        self.assertIn('id="ai-test-provider"', autoclip.HTML)

    def test_window_reload_cancels_pending_close_shutdown(self):
        timer = MagicMock()
        with patch.object(autoclip.threading, "Timer", return_value=timer):
            autoclip.schedule_window_close_shutdown()
            timer.start.assert_called_once_with()
            autoclip.cancel_window_close_shutdown()
        timer.cancel.assert_called_once_with()

    def test_active_window_lease_defers_close_until_socket_ends(self):
        timer = MagicMock()
        with patch.object(autoclip.threading, "Timer", return_value=timer):
            lease = autoclip.begin_window_lease()
            autoclip.schedule_window_close_shutdown()
            timer.start.assert_not_called()
            autoclip.end_window_lease(lease)
            timer.start.assert_called_once_with()
            autoclip.cancel_window_close_shutdown()


if __name__ == "__main__":
    unittest.main()
