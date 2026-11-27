import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import autoclip
import json
import ai_highlights
from zernio_poster import ZernioPublisher


class RegressionTests(unittest.TestCase):
    def test_clip_post_copy_splits_title_and_description(self):
        title, description = autoclip.split_clip_post_copy(
            "The clutch save surprised everyone\n\nWhat a finish!\n\n#gaming #shorts"
        )
        self.assertEqual(title, "The clutch save surprised everyone")
        self.assertEqual(description, "What a finish!\n\n#gaming #shorts")

    def test_clip_post_copy_handles_missing_description(self):
        self.assertEqual(autoclip.split_clip_post_copy("Just a title"), ("Just a title", ""))
        self.assertEqual(autoclip.split_clip_post_copy(""), ("", ""))

    def test_live_recording_is_deleted_after_rendered_clip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rec = root / "rec"
            out = root / "out"
            rec.mkdir()
            out.mkdir()
            recording = rec / "live_chunk.ts"
            recording.write_bytes(b"temporary capture")
            engine = object.__new__(autoclip.Engine)
            engine.cfg = {"mode": "live", "min_score": 70, "pre": 2, "post": 2, "delete_rec": False}
            engine.rec_dir, engine.out_dir = rec, out
            engine.transcribe = lambda _path: [(4.0, 5.0, "hello")]
            engine.find_peaks = lambda *_args: ([(5, 90.0)], 12)
            engine.status = lambda *_args: None
            engine.log = lambda *_args: None
            engine.check = lambda: None
            engine.render = lambda *_args: None
            engine.emit = lambda *_args: None
            engine._process(str(recording))
            self.assertFalse(recording.exists())

    def test_live_recording_is_deleted_when_no_clip_is_worthwhile(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rec, out = root / "rec", root / "out"
            rec.mkdir()
            out.mkdir()
            recording = rec / "quiet_chunk.ts"
            recording.write_bytes(b"temporary capture")
            engine = object.__new__(autoclip.Engine)
            engine.cfg = {"mode": "live", "min_score": 70, "pre": 2, "post": 2, "delete_rec": False}
            engine.rec_dir, engine.out_dir = rec, out
            engine.transcribe = lambda _path: []
            engine.find_peaks = lambda *_args: ([], 12)
            engine.status = lambda *_args: None
            engine.log = lambda *_args: None
            engine.check = lambda: None
            engine.emit = lambda *_args: None
            engine._process(str(recording))
            self.assertFalse(recording.exists())

    def test_live_recording_is_kept_if_every_clip_render_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rec, out = root / "rec", root / "out"
            rec.mkdir()
            out.mkdir()
            recording = rec / "retry_chunk.ts"
            recording.write_bytes(b"temporary capture")
            engine = object.__new__(autoclip.Engine)
            engine.cfg = {"mode": "live", "min_score": 70, "pre": 2, "post": 2, "delete_rec": False}
            engine.rec_dir, engine.out_dir = rec, out
            engine.transcribe = lambda _path: [(4.0, 5.0, "hello")]
            engine.find_peaks = lambda *_args: ([(5, 90.0)], 12)
            engine.status = lambda *_args: None
            engine.log = lambda *_args: None
            engine.check = lambda: None
            engine.render = lambda *_args: (_ for _ in ()).throw(RuntimeError("render failed"))
            engine.emit = lambda *_args: None
            engine._process(str(recording))
            self.assertTrue(recording.exists())

    def test_posted_registry_moves_clips_between_tabs_and_can_be_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "out"
            output.mkdir()
            clip = output / "finished_clip.mp4"
            clip.write_bytes(b"video")
            with patch.object(autoclip, "OUT", output), patch.object(autoclip, "POSTED_FILE", root / "posted.json"), patch.object(autoclip, "SCHEDULED_FILE", root / "scheduled.json"), patch.object(autoclip, "CORE", None):
                autoclip.invalidate_clip_cache()
                self.assertEqual(len(autoclip.list_clips(clip_tab="clips")), 1)
                autoclip.record_zernio_scheduled(clip.name, ["instagram:account"])
                self.assertEqual(autoclip.list_clips(clip_tab="clips"), [])
                scheduled = autoclip.list_clips(clip_tab="scheduled")
                self.assertEqual([item["name"] for item in scheduled], [clip.name])
                self.assertTrue(scheduled[0]["scheduled"])
                self.assertFalse(scheduled[0]["posted"])
                self.assertEqual(autoclip.load_scheduled_registry()[clip.name]["accounts"], ["instagram:account"])
                autoclip.record_zernio_posted(clip.name)
                scheduled = autoclip.list_clips(clip_tab="scheduled")
                self.assertEqual([item["name"] for item in scheduled], [clip.name])
                self.assertTrue(scheduled[0]["posted"])
                self.assertFalse(scheduled[0]["scheduled"])
                self.assertEqual(autoclip.list_clips(clip_tab="posted")[0]["name"], clip.name)
                self.assertEqual(autoclip.load_posted_registry()[clip.name]["platform"], "zernio")
                autoclip.forget_posted_clips([clip.name])
                self.assertEqual(len(autoclip.list_clips(clip_tab="clips")), 1)
                self.assertEqual(autoclip.list_clips(clip_tab="scheduled"), [])

    def test_publishing_connections_reject_more_than_five_slots(self):
        core = object.__new__(autoclip.Core)
        with self.assertRaisesRegex(ValueError, "up to five"):
            core.publishing_connections_save({"connections": [{"id": f"slot-{index}"} for index in range(6)]})

    def test_custom_openai_compatible_highlight_provider_uses_chat_completions(self):
        config = {
            "custom_api_base": "https://free-provider.example/v1",
            "custom_api_model": "free-chat-model",
            "custom_api_key": "test-secret",
        }
        response = {"choices": [{"message": {"content": '{"moments":[{"time":45,"score":88,"reason":"strong payoff"}]}'}}]}
        with patch.object(ai_highlights, "_json_request", return_value=response) as request:
            result = ai_highlights._openai_compatible("transcript prompt", config)
        self.assertEqual(result["moments"][0]["score"], 88)
        self.assertEqual(request.call_args.args[0], "https://free-provider.example/v1/chat/completions")
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer test-secret")

    def test_custom_api_connection_test_returns_secret_free_success(self):
        config = {
            "custom_api_base": "https://provider.example/v1",
            "custom_api_model": "test-model",
            "custom_api_key": "private-test-key",
        }
        response = {"choices": [{"message": {"content": "STREAMSNIP_OK"}}]}
        with patch.object(ai_highlights, "_json_request", return_value=response):
            result = ai_highlights.test_provider("custom", config)
        self.assertTrue(result["ok"])
        self.assertEqual(result["provider"], "custom")
        self.assertNotIn("private-test-key", str(result))

    def test_custom_ai_analysis_uses_selected_three_minute_windows(self):
        words = [(0, 1, "wow"), (180, 181, "insane"), (360, 361, "no way")]
        config = {"ai_window_minutes": 3}
        with patch.object(ai_highlights, "_openai_compatible", return_value={"moments": []}) as backend:
            result = ai_highlights.select_moments("custom", words, 400, config)
        self.assertEqual(result, [])
        self.assertEqual(backend.call_count, 3)
        self.assertEqual(config["_ai_window"], (360, 400))

    def test_openai_highlight_provider_uses_the_selected_chatgpt_model(self):
        config = {
            "openai_api_base": "https://api.openai.com/v1",
            "openai_model": "gpt-test-model",
            "openai_api_key": "openai-private-key",
        }
        response = {"choices": [{"message": {"content": json.dumps(
            {"moments": [{"time": 12, "score": 88}]}
        )}}]}
        with patch.object(ai_highlights, "_json_request", return_value=response) as request:
            result = ai_highlights._openai("transcript prompt", config)

        self.assertEqual(result["moments"][0]["time"], 12)
        self.assertEqual(request.call_args.args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(request.call_args.args[1]["model"], "gpt-test-model")
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer openai-private-key")

    def test_anthropic_highlight_provider_uses_the_messages_api(self):
        config = {
            "anthropic_api_base": "https://api.anthropic.com",
            "anthropic_model": "claude-test-model",
            "anthropic_api_key": "anthropic-private-key",
        }
        response = {"content": [{"type": "text", "text": json.dumps(
            {"moments": [{"time": 14, "score": 91}]}
        )}]}
        with patch.object(ai_highlights, "_json_request", return_value=response) as request:
            result = ai_highlights._anthropic("transcript prompt", config)

        self.assertEqual(result["moments"][0]["time"], 14)
        self.assertEqual(request.call_args.args[0], "https://api.anthropic.com/v1/messages")
        self.assertEqual(request.call_args.args[1]["model"], "claude-test-model")
        self.assertEqual(request.call_args.kwargs["headers"]["x-api-key"], "anthropic-private-key")
        self.assertEqual(request.call_args.kwargs["headers"]["anthropic-version"], "2023-06-01")

    def test_ai_settings_migrate_legacy_hook_scoring_to_gemini(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            path.write_text(json.dumps({"provider": "hooks"}), encoding="utf-8")
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                settings = autoclip.load_ai_settings()
        self.assertEqual(settings["provider"], "gemini")

    def test_ai_settings_store_openai_and_anthropic_keys_as_private_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                saved = autoclip.save_ai_settings({
                    "provider": "anthropic",
                    "openai_api_base": "https://api.openai.com/v1",
                    "openai_model": "gpt-test",
                    "openai_api_key": "openai-private-key",
                    "anthropic_api_base": "https://api.anthropic.com",
                    "anthropic_model": "claude-test",
                    "anthropic_api_key": "anthropic-private-key",
                })
                loaded = autoclip.load_ai_settings()
                stored = path.read_text(encoding="utf-8")
        self.assertTrue(saved["openai_key_set"])
        self.assertTrue(saved["anthropic_key_set"])
        self.assertEqual(saved["provider"], "anthropic")
        self.assertEqual(loaded["openai_model"], "gpt-test")
        self.assertEqual(loaded["anthropic_model"], "claude-test")
        self.assertNotIn("openai-private-key", str(saved))
        self.assertNotIn("anthropic-private-key", str(saved))
        self.assertIn("openai-private-key", stored)
        self.assertIn("anthropic-private-key", stored)

    def test_creator_monitor_accepts_twitch_and_youtube_but_rejects_lookalike_hosts(self):
        core = object.__new__(autoclip.Core)
        core.lock = autoclip.threading.RLock()
        core.creators = {}
        core.creator_status = {}
        core.creator_workers = {}
        core.creator_engines = {}
        core.push = MagicMock()
        core._save_creator_profiles = MagicMock()
        with patch.object(autoclip, "streamlink_available", return_value=True):
            added = core.add_creator({"name": "Test creator", "target": "https://www.twitch.tv/test_channel"})
            self.assertEqual(added["creator"]["name"], "Test creator")
            with self.assertRaisesRegex(ValueError, "Twitch or YouTube"):
                core.add_creator({"name": "Impostor", "target": "https://twitch.tv.evil.example/live"})

    def test_live_studio_capture_for_saved_creator_uses_creator_owned_folders(self):
        core = object.__new__(autoclip.Core)
        core.lock = threading.RLock()
        core.creators = {
            "creator_a": {
                "id": "creator_a",
                "name": "angryginge13",
                "target": "https://www.twitch.tv/angryginge13",
            }
        }
        core.running = False
        core.settings = {}
        core.phase = "idle"
        core.status = "Ready when you are."
        core.progress = 0
        core.session = {"clips": 0, "chunks": 0, "started": None, "ended": None}
        core.push = MagicMock()
        paths = {
            "live_clips": Path(tempfile.gettempdir()) / "creator-a-live-clips",
            "live_recordings": Path(tempfile.gettempdir()) / "creator-a-live-recordings",
        }
        fake_engine = MagicMock()
        fake_worker = MagicMock()

        with (
            patch.object(autoclip, "ffmpeg_exe", return_value="ffmpeg.exe"),
            patch.object(autoclip, "streamlink_available", return_value=True),
            patch.object(autoclip, "apply_storage_paths"),
            patch.object(autoclip, "save_settings"),
            patch.object(autoclip, "Engine", return_value=fake_engine) as engine_factory,
            patch.object(autoclip.threading, "Thread", return_value=fake_worker),
            patch.object(core, "_ensure_creator_paths", return_value=paths),
        ):
            core.start({
                "mode": "live",
                "target": "https://www.twitch.tv/angryginge13",
                "creator_id": "creator_a",
            })

        engine_cfg = engine_factory.call_args.args[0]
        self.assertEqual(engine_cfg["creator_id"], "creator_a")
        self.assertEqual(engine_cfg["creator_out_dir"], str(paths["live_clips"]))
        self.assertEqual(engine_cfg["creator_rec_dir"], str(paths["live_recordings"]))
        fake_worker.start.assert_called_once()

    def test_live_studio_capture_blocks_duplicate_background_monitor_for_same_creator(self):
        core = object.__new__(autoclip.Core)
        core.lock = threading.RLock()
        core.creators = {
            "creator_a": {
                "id": "creator_a",
                "name": "angryginge13",
                "target": "https://www.twitch.tv/angryginge13",
            }
        }
        core.creator_workers = {}
        core.creator_engines = {}
        core.creator_status = {}
        core.engine = types.SimpleNamespace(cfg={
            "mode": "live",
            "target": "https://www.twitch.tv/angryginge13",
        })
        core.running = True

        with self.assertRaisesRegex(ValueError, "already being captured in Live Studio"):
            core.start_creator("creator_a")

    def test_background_monitor_blocks_duplicate_live_studio_capture_for_same_creator(self):
        core = object.__new__(autoclip.Core)
        core.lock = threading.RLock()
        core.creators = {
            "creator_a": {
                "id": "creator_a",
                "name": "angryginge13",
                "target": "https://www.twitch.tv/angryginge13",
            }
        }
        core.creator_workers = {
            "creator_a": types.SimpleNamespace(is_alive=lambda: True)
        }
        core.running = False

        with patch.object(autoclip, "ffmpeg_exe", return_value="ffmpeg.exe"):
            with patch.object(autoclip, "streamlink_available", return_value=True):
                with self.assertRaisesRegex(ValueError, "already has a background monitor"):
                    core.start({
                        "mode": "live",
                        "target": "https://www.twitch.tv/angryginge13",
                        "creator_id": "creator_a",
                    })

    def test_live_capture_stop_is_idempotent_while_finishing(self):
        core = object.__new__(autoclip.Core)
        core.lock = threading.RLock()
        engine = MagicMock()
        engine.cfg = {"mode": "live"}
        engine.stop_flag = False
        engine.stop_calls = []

        def stop_once(force=False):
            engine.stop_flag = True
            engine.stop_calls.append(force)

        engine.stop.side_effect = stop_once
        core.engine = engine
        core.running = True
        core.push = MagicMock()

        self.assertEqual(core.stop(False), {"ok": True, "stopping": True})
        self.assertEqual(core.stop(False), {"ok": True, "stopping": True})
        self.assertEqual(engine.stop_calls, [False])
        core.push.assert_called_once()

    def test_selected_gemini_model_precedes_cached_successful_alternate(self):
        selected = "gemini-3.1-flash-lite"
        alternate = "gemini-3.8-flash"
        key = "selected-model-order-test"
        cache_id = __import__("hashlib").sha256(key.encode("utf-8")).hexdigest()
        calls = []

        def fake_request(url, payload=None, headers=None, timeout=90):
            calls.append(url)
            return {"candidates": [{"content": {"parts": [{"text": '{"moments": []}'}]}}]}

        with patch.dict(ai_highlights._GEMINI_ACTIVE_CACHE,
                        {cache_id: (selected, alternate)}, clear=True), \
             patch.object(ai_highlights, "_gemini_available_models", return_value=[alternate, selected]), \
             patch.object(ai_highlights, "_json_request", side_effect=fake_request):
            result = ai_highlights._gemini("transcript", {
                "gemini_api_key": key,
                "gemini_model": selected,
                "_gemini_active_model": alternate,
            })

        self.assertEqual(result, {"moments": []})
        self.assertEqual(len(calls), 1)
        self.assertIn("/" + selected + ":generateContent", calls[0])
        self.assertNotIn("/" + alternate + ":generateContent", calls[0])

    def test_creator_capture_can_be_stopped_without_stopping_another_creator(self):
        core = object.__new__(autoclip.Core)
        core.lock = threading.RLock()
        core.creators = {
            "creator_a": {"id": "creator_a", "name": "Creator A", "target": "https://twitch.tv/creator_a"},
            "creator_b": {"id": "creator_b", "name": "Creator B", "target": "https://twitch.tv/creator_b"},
        }
        engine = MagicMock()
        engine.cfg = {"mode": "live", "creator_id": "creator_a", "target": "https://twitch.tv/creator_a"}
        engine.stop_flag = False
        engine.stop.side_effect = lambda force=False: setattr(engine, "stop_flag", True)
        core.engine = engine
        core.running = True
        core.push = MagicMock()

        self.assertEqual(core.stop_creator_capture("creator_a"), {"ok": True, "stopping": True})
        self.assertEqual(core.stop_creator_capture("creator_a"), {"ok": True, "stopping": True})
        engine.stop.assert_called_once_with(force=False)
        self.assertTrue(any("Creator A" in str(call) for call in core.push.call_args_list))
        with self.assertRaisesRegex(ValueError, "not the active Live Studio capture"):
            core.stop_creator_capture("creator_b")
        engine.stop.assert_called_once_with(force=False)

    def test_creator_capture_stop_matches_legacy_sessions_by_stream_target(self):
        core = object.__new__(autoclip.Core)
        core.lock = threading.RLock()
        core.creators = {
            "creator_a": {"id": "creator_a", "name": "Creator A", "target": "https://www.twitch.tv/creator_a"},
        }
        engine = MagicMock()
        engine.cfg = {"mode": "live", "target": "https://twitch.tv/creator_a"}
        engine.stop_flag = False
        engine.stop.side_effect = lambda force=False: setattr(engine, "stop_flag", True)
        core.engine = engine
        core.running = True
        core.push = MagicMock()

        self.assertEqual(core.stop_creator_capture("creator_a"), {"ok": True, "stopping": True})
        engine.stop.assert_called_once_with(force=False)

    def test_creator_capture_stop_endpoint_and_ui_are_exposed_per_creator(self):
        root = Path(__file__).resolve().parents[1]
        api_source = (root / "autoclip.py").read_text(encoding="utf-8")
        app_source = (root / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        client_source = (root / "dashboard" / "src" / "api.ts").read_text(encoding="utf-8")
        self.assertIn('path == "/api/creators/stop-capture"', api_source)
        self.assertIn('"/api/creators/stop-capture"', client_source)
        self.assertIn("Stop capture", app_source)
        self.assertIn('"/api/creators/stop-capture"', app_source)

    def test_creator_list_marks_matching_live_studio_capture_without_claiming_monitor_is_running(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(autoclip, "_data_root", Path(directory)):
            core = object.__new__(autoclip.Core)
            core.lock = threading.RLock()
            core.creators = {
                "creator_a": {
                    "id": "creator_a",
                    "name": "angryginge13",
                    "target": "https://www.twitch.tv/angryginge13",
                }
            }
            core.creator_status = {"creator_a": {"phase": "offline", "status": "Monitor stopped."}}
            core.creator_workers = {}
            core.creator_watchers = {}
            core.engine = types.SimpleNamespace(cfg={
                "mode": "live",
                "target": "https://www.twitch.tv/angryginge13",
            })
            core.running = True

            creator = core.list_creators()[0]

            self.assertFalse(creator["running"], "A Live Studio capture is not a background monitor.")
            self.assertTrue(creator["capture_active"])
            self.assertEqual(creator["status"], "Monitor stopped.")

    def test_quit_stops_all_active_creator_engines(self):
        core = object.__new__(autoclip.Core)
        core.lock = autoclip.threading.RLock()
        engine = MagicMock()
        core.creator_engines = {"creator_a": engine}
        core.creator_workers = {"creator_a": types.SimpleNamespace(is_alive=lambda: True)}
        core.creator_status = {"creator_a": {"phase": "recording", "clips": 2}}
        self.assertEqual(core.stop_all_creators(), 1)
        engine.stop.assert_called_once_with(force=True)
        self.assertEqual(core.creator_status["creator_a"]["phase"], "stopping")

    def test_engine_uses_isolated_creator_recording_and_output_folders(self):
        cfg = autoclip.clean_cfg({
            "creator_id": "creator_one",
            "creator_out_dir": str(Path(tempfile.gettempdir()) / "streamsnip-test-out-one"),
            "creator_rec_dir": str(Path(tempfile.gettempdir()) / "streamsnip-test-rec-one"),
        })
        engine = autoclip.Engine(cfg, lambda *_: None)
        self.assertEqual(engine.out_dir, Path(cfg["creator_out_dir"]).resolve())
        self.assertEqual(engine.rec_dir, Path(cfg["creator_rec_dir"]).resolve())
        self.assertTrue(engine.out_dir.is_dir())
        self.assertTrue(engine.rec_dir.is_dir())

    def test_creator_profiles_isolate_framing_and_caption_style_but_share_providers_and_clipping_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.multiple(
                autoclip, _data_root=Path(directory),
                load_settings=MagicMock(return_value=autoclip.clean_cfg({})),
                apply_storage_paths=MagicMock(),
                streamlink_available=MagicMock(return_value=True),
            ):
                core = autoclip.Core()
                core.push = MagicMock()
                first = core.add_creator({"name": "Creator One", "target": "https://twitch.tv/creatorone"})["creator"]["id"]
                second = core.add_creator({"name": "Creator Two", "target": "https://twitch.tv/creatortwo"})["creator"]["id"]

                core.save_creator_settings(first, {
                    "cam_x": 14, "cam_y": 9, "cam_w": 31, "cam_h": 44,
                    "game_area_x": 4, "game_area_y": 8, "game_area_w": 80, "game_area_h": 90,
                    "crop_x": 7, "crop_y": 2, "crop_w": 60, "crop_h": 95,
                    "subtitle_style": "Neon", "subtitle_animation": "pop_in",
                    "subtitle_custom": True, "subtitle_text_color": "#00FF00",
                    "caption_size": 111, "font": "Poppins", "streamer_tag": "@creatorone",
                    "transcriber_provider": "custom-command", "transcriber_command": "caption-engine",
                    "transcriber_language": "en", "model": "medium",
                    "clips_per_chunk": 5, "chunk_min": 12, "pre": 31, "post": 22,
                    "min_score": 91, "capture_bitrate_kbps": 12000,
                    "layout": "Blur background", "output_format": "16:9", "delete_rec": True,
                    "profanity_filter_enabled": False, "profanity_audio_mode": "mute",
                })

                one = core.get_creator_settings(first)
                two = core.get_creator_settings(second)
                self.assertEqual((one["cam_x"], one["cam_y"], one["subtitle_style"], one["caption_size"]),
                                 (14, 9, "Neon", 111))
                self.assertEqual((two["cam_x"], two["cam_y"], two["subtitle_style"], two["caption_size"]),
                                 (autoclip.DEFAULTS["cam_x"], autoclip.DEFAULTS["cam_y"],
                                  autoclip.DEFAULTS["subtitle_style"], autoclip.DEFAULTS["caption_size"]))
                self.assertEqual((two["transcriber_provider"], two["transcriber_command"],
                                  two["transcriber_language"], two["model"]),
                                 ("custom-command", "caption-engine", "en", "medium"))
                self.assertEqual((one["layout"], one["output_format"]), ("Blur background", "16:9"))
                self.assertEqual((two["layout"], two["output_format"]), ("Blur background", "16:9"))
                self.assertEqual((two["clips_per_chunk"], two["chunk_min"], two["pre"], two["post"],
                                  two["min_score"], two["capture_bitrate_kbps"], two["delete_rec"]),
                                 (5, 12, 31, 22, 91, 12000, True))
                self.assertEqual((one["profanity_filter_enabled"], one["profanity_audio_mode"]), (False, "mute"))
                self.assertEqual((two["profanity_filter_enabled"], two["profanity_audio_mode"]),
                                 (autoclip.DEFAULTS["profanity_filter_enabled"], autoclip.DEFAULTS["profanity_audio_mode"]))
                self.assertEqual(two["streamer_tag"], autoclip.DEFAULTS["streamer_tag"])

                with core._creator_db() as db:
                    stored = json.loads(db.execute(
                        "SELECT settings_json FROM creator_settings WHERE creator_id=?", (first,)
                    ).fetchone()["settings_json"])
                for shared_key in ("transcriber_provider", "transcriber_command", "transcriber_language",
                                   "model", "clips_per_chunk", "chunk_min", "pre", "post",
                                   "min_score", "capture_bitrate_kbps", "delete_rec", "cpu_threads", "language",
                                   "layout", "output_format"):
                    self.assertNotIn(shared_key, stored)
                for profile_key in ("profanity_filter_enabled", "profanity_filter_words", "profanity_audio_mode"):
                    self.assertIn(profile_key, stored)
                self.assertEqual(stored["cam_x"], 14)
                self.assertEqual(stored["subtitle_style"], "Neon")
                self.assertEqual(core.default_settings["transcriber_provider"], "custom-command")

    def test_legacy_full_creator_rows_keep_visual_preferences_but_ignore_duplicated_shared_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            shared = autoclip.clean_cfg({
                "min_score": 73, "transcriber_provider": "faster-whisper",
                "transcriber_language": "en", "model": "medium",
                "clips_per_chunk": 1, "chunk_min": 6,
                "layout": "Fill (crop center)", "output_format": "4:5",
            })
            with patch.multiple(
                autoclip, _data_root=Path(directory),
                load_settings=MagicMock(return_value=shared),
                save_settings=MagicMock(), apply_storage_paths=MagicMock(),
                streamlink_available=MagicMock(return_value=True),
            ):
                core = autoclip.Core()
                core.push = MagicMock()
                creator_id = core.add_creator({"name": "Legacy creator", "target": "https://twitch.tv/legacy"})["creator"]["id"]
                legacy = autoclip.clean_cfg({
                    "cam_x": 17, "subtitle_style": "Neon", "subtitle_animation": "pop_in",
                    "transcriber_provider": "custom-command", "transcriber_command": "old-command",
                    "transcriber_language": "fr", "model": "small", "min_score": 99,
                    "clips_per_chunk": 8, "chunk_min": 15,
                    "layout": "Blur background", "output_format": "16:9",
                })
                with core._creator_db() as db:
                    db.execute("UPDATE creator_settings SET settings_json=? WHERE creator_id=?",
                               (json.dumps(legacy), creator_id))

                # Startup migration compacts old full-config rows without losing
                # creator-specific framing/subtitle values.
                core._init_creator_database()
                with core._creator_db() as db:
                    migrated = json.loads(db.execute(
                        "SELECT settings_json FROM creator_settings WHERE creator_id=?", (creator_id,)
                    ).fetchone()["settings_json"])
                for shared_key in ("transcriber_provider", "transcriber_command", "transcriber_language",
                                   "model", "min_score", "clips_per_chunk", "chunk_min", "layout", "output_format"):
                    self.assertNotIn(shared_key, migrated)
                self.assertEqual(migrated["cam_x"], 17)
                self.assertEqual(migrated["subtitle_style"], "Neon")
                self.assertEqual(migrated["subtitle_animation"], "pop_in")
                self.assertIn("profanity_filter_enabled", migrated)

                effective = core.get_creator_settings(creator_id)
                self.assertEqual((effective["cam_x"], effective["subtitle_style"], effective["subtitle_animation"]),
                                 (17, "Neon", "pop_in"))
                self.assertEqual((effective["transcriber_provider"], effective["transcriber_language"], effective["model"]),
                                 ("faster-whisper", "en", "medium"))
                self.assertEqual((effective["min_score"], effective["clips_per_chunk"], effective["chunk_min"]),
                                 (73, 1, 6))
                self.assertEqual((effective["layout"], effective["output_format"]), ("Fill (crop center)", "4:5"))

                core.save_creator_settings(creator_id, effective)
                with core._creator_db() as db:
                    compacted = json.loads(db.execute(
                        "SELECT settings_json FROM creator_settings WHERE creator_id=?", (creator_id,)
                    ).fetchone()["settings_json"])
                for shared_key in ("transcriber_provider", "transcriber_command", "transcriber_language",
                                   "model", "min_score", "clips_per_chunk", "chunk_min", "layout", "output_format"):
                    self.assertNotIn(shared_key, compacted)
                for profile_key in ("profanity_filter_enabled", "profanity_filter_words", "profanity_audio_mode"):
                    self.assertIn(profile_key, compacted)
                self.assertEqual(compacted["cam_x"], 17)
                self.assertEqual(compacted["subtitle_style"], "Neon")

    def test_new_creator_uses_fresh_profile_defaults_not_previous_creator_framing_or_caption_style(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.multiple(
                autoclip, _data_root=Path(directory),
                load_settings=MagicMock(return_value=autoclip.clean_cfg({"layout": "Fill (crop center)", "output_format": "4:5"})),
                apply_storage_paths=MagicMock(),
                streamlink_available=MagicMock(return_value=True),
            ):
                core = autoclip.Core()
                core.push = MagicMock()
                first = core.add_creator({"name": "Creator One", "target": "https://twitch.tv/creatorone"})["creator"]["id"]
                second = core.add_creator({"name": "Creator Two", "target": "https://twitch.tv/creatortwo"})["creator"]["id"]
                core.save_creator_settings(first, {"cam_x": 11, "subtitle_style": "MrBeast", "font": "Lato",
                                                   "layout": "Blur background", "output_format": "9:16"})
                first_profile = core.get_creator_settings(first)
                new_profile = core.get_creator_settings(second)
                self.assertEqual(new_profile["cam_x"], autoclip.DEFAULTS["cam_x"])
                self.assertEqual(new_profile["subtitle_style"], autoclip.DEFAULTS["subtitle_style"])
                self.assertEqual(new_profile["font"], autoclip.DEFAULTS["font"])
                self.assertEqual((first_profile["layout"], first_profile["output_format"]),
                                 ("Blur background", "9:16"))
                self.assertEqual((new_profile["layout"], new_profile["output_format"]), ("Blur background", "9:16"))

    def test_creator_profiles_are_validated_and_persisted_locally(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.multiple(
                autoclip, _data_root=Path(directory),
                load_settings=MagicMock(return_value=autoclip.clean_cfg({})),
                apply_storage_paths=MagicMock(),
                streamlink_available=MagicMock(return_value=True),
            ):
                core = autoclip.Core()
                core.push = MagicMock()
                result = core.add_creator({"name": "Creator One\n", "target": "https://twitch.tv/example"})
                creator_id = result["creator"]["id"]
                self.assertEqual(result["creator"]["name"], "Creator One")
                self.assertEqual(result["creator"]["phase"], "offline")
                reloaded = autoclip.Core()
                self.assertIn(creator_id, reloaded.creators)
                self.assertEqual(reloaded.creators[creator_id]["target"], "https://twitch.tv/example")
                with self.assertRaisesRegex(ValueError, "Stop this creator's live monitor"):
                    core.creator_workers[creator_id] = types.SimpleNamespace(is_alive=lambda: True)
                    core.remove_creator(creator_id)

    def test_creator_monitor_rejects_non_stream_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.multiple(
                autoclip, _data_root=Path(directory),
                load_settings=MagicMock(return_value=autoclip.clean_cfg({})),
                apply_storage_paths=MagicMock(),
                streamlink_available=MagicMock(return_value=True),
            ):
                core = autoclip.Core()
                with self.assertRaisesRegex(ValueError, "Twitch or YouTube"):
                    core.add_creator({"name": "Invalid", "target": "https://example.com/live"})

    def test_creator_monitors_use_separate_folders_and_limit_workers(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.multiple(
                autoclip, _data_root=Path(directory),
                load_settings=MagicMock(return_value=autoclip.clean_cfg({})),
                apply_storage_paths=MagicMock(),
                streamlink_available=MagicMock(return_value=True),
            ):
                class FakeEngine:
                    def __init__(self, cfg, emit):
                        self.cfg = cfg
                        self.done = threading.Event()
                    def run(self):
                        self.done.wait(3)
                    def stop(self, force=False):
                        self.done.set()

                core = autoclip.Core()
                core.push = MagicMock()
                ids = [
                    core.add_creator({"name": f"Creator {i}", "target": f"https://twitch.tv/channel{i}"})["creator"]["id"]
                    for i in range(autoclip.MAX_ACTIVE_CREATOR_MONITORS + 1)
                ]
                with patch.object(autoclip, "Engine", FakeEngine):
                    try:
                        for creator_id in ids[:-1]:
                            core.start_creator(creator_id)
                        first = core.creator_engines[ids[0]].cfg
                        second = core.creator_engines[ids[1]].cfg
                        self.assertNotEqual(first["creator_out_dir"], second["creator_out_dir"])
                        self.assertNotEqual(first["creator_rec_dir"], second["creator_rec_dir"])
                        self.assertEqual(
                            sum(worker.is_alive() for worker in core.creator_workers.values()),
                            autoclip.MAX_ACTIVE_CREATOR_MONITORS,
                        )
                        with self.assertRaisesRegex(
                            ValueError, f"All {autoclip.MAX_ACTIVE_CREATOR_MONITORS} creator monitor slots"
                        ):
                            core.start_creator(ids[-1])
                    finally:
                        for creator_id in ids:
                            if creator_id in core.creator_engines:
                                core.stop_creator(creator_id, force=True)
                        for worker in core.creator_workers.values():
                            worker.join(timeout=1)

    def test_creator_live_and_recorded_vod_folders_are_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(autoclip, "_data_root", Path(directory)):
                core = object.__new__(autoclip.Core)
                core.creators = {"creator_x": {"id": "creator_x", "name": "Creator X"}}
                core.lock = threading.RLock()
                legacy_clip_dir = Path(directory) / "creators" / "creator_x" / "clips"
                legacy_clip_dir.mkdir(parents=True)
                (legacy_clip_dir / "old_live_clip.mp4").write_bytes(b"keep")
                paths = core._ensure_creator_paths("creator_x")
                self.assertTrue(paths["root"].name.startswith("Creator_X_"))
                self.assertTrue((paths["live_clips"] / "old_live_clip.mp4").exists())
                self.assertNotEqual(paths["live_clips"], paths["vod_clips"])
                self.assertNotEqual(paths["live_recordings"], paths["vod_inbox"])
                self.assertTrue(paths["live_clips"].is_dir())
                self.assertTrue(paths["vod_inbox"].is_dir())
                self.assertTrue(paths["vod_clips"].is_dir())

    def test_main_clip_gallery_indexes_creator_live_and_vod_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core = object.__new__(autoclip.Core)
            core.lock = threading.RLock()
            core.creators = {"creator_gallery": {"id": "creator_gallery", "name": "Gallery Creator"}}
            with patch.object(autoclip, "_data_root", root / "data"), patch.object(autoclip, "OUT", root / "main"), patch.object(autoclip, "CORE", core):
                autoclip.OUT.mkdir(parents=True)
                paths = core._ensure_creator_paths("creator_gallery")
                files = [
                    (autoclip.OUT / "local_clip.mp4", "Local title"),
                    (paths["live_clips"] / "creator_g_live_stream_clip1.mp4", "Live title"),
                    (paths["vod_clips"] / "creator_g_vod_recorded_clip1.mp4", "VOD title"),
                ]
                for video, title in files:
                    video.write_bytes(b"clip")
                    video.with_suffix(".txt").write_text(title + "\n\nCaption", encoding="utf-8")
                autoclip.invalidate_clip_cache()
                items = autoclip.list_clips(limit=10)
                self.assertEqual({item["source"] for item in items}, {"main", "live", "vod"})
                live = next(item for item in items if item["source"] == "live")
                vod = next(item for item in items if item["source"] == "vod")
                self.assertEqual(live["creator_name"], "Gallery Creator")
                self.assertEqual(vod["title"], "VOD title")
                self.assertEqual(autoclip.find_clip_path(live["name"]), files[1][0].resolve())
                self.assertEqual(autoclip.find_clip_path(vod["name"]), files[2][0].resolve())

    def test_creator_vod_folder_watcher_processes_and_archives_stable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.multiple(
                autoclip, _data_root=Path(directory),
                load_settings=MagicMock(return_value=autoclip.clean_cfg({})),
                apply_storage_paths=MagicMock(),
            ):
                class FakeEngine:
                    seen = []
                    def __init__(self, cfg, emit):
                        self.cfg, self.emit = cfg, emit
                    def process(self, filename):
                        self.seen.append((filename, self.cfg["creator_out_dir"]))
                    def stop(self, force=False):
                        pass

                core = autoclip.Core()
                core.push = MagicMock()
                creator_id = "creator_watch"
                core.creators[creator_id] = {"id": creator_id, "name": "Watched"}
                paths = core._ensure_creator_paths(creator_id)
                with patch.object(autoclip, "Engine", FakeEngine):
                    core.start_vod_watch(creator_id)
                    source = paths["vod_inbox"] / "session.mp4"
                    source.write_bytes(b"sample vod")
                    deadline = time.time() + 12
                    while time.time() < deadline and not (paths["vod_processed"] / source.name).exists():
                        time.sleep(0.05)
                    core.stop_vod_watch(creator_id)
                    core.creator_watchers[creator_id].join(timeout=2)
                self.assertTrue((paths["vod_processed"] / source.name).exists())
                self.assertEqual(FakeEngine.seen[0][1], str(paths["vod_clips"]))
                self.assertFalse(source.exists())

    def test_vod_processing_status_does_not_overwrite_live_status(self):
        core = object.__new__(autoclip.Core)
        core.lock = threading.RLock()
        core.creators = {"creator_x": {"name": "Creator X"}}
        core.creator_status = {"creator_x": {"phase": "recording", "status": "Live capture active"}}
        core.push = MagicMock()
        core.emit_vod("creator_x", "status", ("transcribing", "Transcribing recorded VOD...", 20))
        self.assertEqual(core.creator_status["creator_x"]["phase"], "recording")
        self.assertEqual(core.creator_status["creator_x"]["vod_status"], "Transcribing recorded VOD...")

    def test_custom_transcriber_config_defaults_to_local_and_accepts_cli_provider(self):
        defaults = autoclip.clean_cfg({})
        self.assertEqual(defaults["transcriber_provider"], "faster-whisper")
        custom = autoclip.clean_cfg({
            "transcriber_provider": "custom-command",
            "transcriber_command": "whisper-cli -f {input} -oj -of {output}",
            "transcriber_language": "en-US",
        })
        self.assertEqual(custom["transcriber_provider"], "custom-command")
        self.assertEqual(custom["transcriber_language"], "en-US")

    def test_custom_transcriber_parses_word_and_segment_json(self):
        engine = autoclip.Engine(autoclip.clean_cfg({"transcriber_provider": "custom-command"}), lambda *_: None)
        word_result = engine._custom_transcript_words({
            "words": [{"start": 0.1, "end": 0.5, "word": "hello"}]
        })
        self.assertEqual(word_result, [(0.1, 0.5, "hello")])
        segment_result = engine._custom_transcript_words({
            "transcription": [{"from": 1000, "to": 3000, "text": "hello there"}]
        })
        self.assertEqual(segment_result, [(1.0, 2.0, "hello"), (2.0, 3.0, "there")])
        whisper_cpp_result = engine._custom_transcript_words({
            "transcription": [{"offsets": {"from": 2000, "to": 4000}, "text": "nested offsets"}]
        })
        self.assertEqual(whisper_cpp_result, [(2.0, 3.0, "nested"), (3.0, 4.0, "offsets")])

    def test_custom_transcriber_cli_runs_without_streamsnip_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "input.mp4"
            source.write_bytes(b"placeholder")
            script = root / "transcribe.py"
            script.write_text(
                "import json,sys\n"
                "json.dump({'words':[{'start':0.2,'end':0.7,'word':'custom'}]},"
                "open(sys.argv[2]+'.json','w',encoding='utf-8'))\n",
                encoding="utf-8",
            )
            command = f'"{sys.executable}" "{script}" "{{input}}" "{{output}}" "{{language}}"'
            cfg = autoclip.clean_cfg({
                "transcriber_provider": "custom-command",
                "transcriber_command": command,
                "transcriber_language": "en",
            })
            engine = autoclip.Engine(cfg, lambda *_: None)
            result = engine.transcribe(str(source))
        self.assertEqual(result, [(0.2, 0.7, "custom")])

    def test_profanity_censor_does_not_hide_words_from_viral_scoring(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.ts"
            raw_words = [(1.0, 1.4, "that"), (1.5, 1.9, "was"), (2.0, 2.4, "damn")]
            engine = autoclip.Engine(autoclip.clean_cfg({"profanity_filter_enabled": True}), lambda *_: None)
            engine.transcribe = MagicMock(return_value=raw_words)
            engine.find_peaks = MagicMock(return_value=([], 10))
            engine.check = MagicMock()
            engine._process(str(source))
            self.assertEqual(engine.find_peaks.call_args.args[1], raw_words)
            censored = autoclip.censor_transcript_words(raw_words, enabled=True)
            self.assertEqual(censored[-1][2], autoclip.PROFANITY_FILTER_MASK)

    def test_creator_processing_waits_for_shared_transcription_slot(self):
        engine = autoclip.Engine(autoclip.clean_cfg({}), lambda *_: None)
        entered = threading.Event()
        engine._process = lambda _path: entered.set()
        autoclip.PROCESSING_LOCK.acquire()
        worker = threading.Thread(target=engine.process, args=("queued-segment.ts",))
        try:
            worker.start()
            self.assertFalse(entered.wait(0.1))
        finally:
            autoclip.PROCESSING_LOCK.release()
        self.assertTrue(entered.wait(1))
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())

    def test_analysis_window_is_limited_to_three_through_fifteen_minutes(self):
        self.assertEqual(autoclip.clean_cfg({"chunk_min": 1})["chunk_min"], 3)
        self.assertEqual(autoclip.clean_cfg({"chunk_min": 3})["chunk_min"], 3)
        self.assertEqual(autoclip.clean_cfg({"chunk_min": 15})["chunk_min"], 15)
        self.assertEqual(autoclip.clean_cfg({"chunk_min": 30})["chunk_min"], 15)

    def test_streamsnip_terminal_warns_about_safe_shutdown(self):
        source = Path(__file__).resolve().parents[1] / "autoclip.py"
        content = source.read_text(encoding="utf-8")
        self.assertIn("Keep this terminal window OPEN while StreamSnip AI is running.", content)
        self.assertIn("click Quit inside StreamSnip AI and wait for it to shut down.", content)
        self.assertIn("Do NOT close this terminal directly.", content)
        self.assertIn("active recording, clip processing, or uploads.", content)

    def test_render_creates_matching_title_description_txt_and_combined_index(self):
        cfg = autoclip.clean_cfg({
            "compute_device": "cpu",
        })
        engine = autoclip.Engine(cfg, lambda *_: None)
        engine.ai_cfg_for_render = {"provider": "gemini", "metadata_copy_enabled": "false"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def fake_run(command, cwd, **_kwargs):
                (Path(cwd) / command[-1]).write_bytes(b"test video")
                return types.SimpleNamespace(returncode=0, stderr="")

            with patch.object(autoclip, "OUT", output), \
                 patch.object(autoclip, "make_ass"), \
                 patch.object(autoclip, "run", side_effect=fake_run) as render_run, \
                 patch.object(autoclip, "has_nvenc", return_value=False), \
                 patch.object(autoclip, "ffmpeg_exe", return_value="ffmpeg"), \
                 patch.object(autoclip, "load_ai_settings", return_value={
                     "provider": "gemini", "metadata_copy_enabled": "false"
                 }), \
                 patch.object(autoclip, "generate_social_copy", return_value={
                     "title": "The chat could not believe what happened",
                     "description": "A sudden turn leaves the streamer stunned and the chat reacting.",
                     "hashtags": ["#Shorts", "#Gaming"],
                 }) as copy:
                engine.out_dir = output
                engine.render(
                    "source_recording.mp4", 10, 18,
                    [(10.1, 10.5, "That"), (10.5, 11.0, "was"),
                     (11.0, 11.5, "unbelievable!")],
                    "rendered_clip"
                )

            self.assertTrue((output / "rendered_clip.mp4").is_file())
            self.assertEqual(render_run.call_count, 1, "Rendering must not run a separate CTA audio-mix pass.")
            self.assertFalse((output / "rendered_clip.cta.wav").exists())
            self.assertEqual(copy.call_args.args[2]["provider"], "gemini")
            sidecar = (output / "rendered_clip.txt").read_text(encoding="utf-8")
            manifest = (output / "clips_metadata.txt").read_text(encoding="utf-8")
            self.assertEqual(sidecar.splitlines()[0], "The chat could not believe what happened")
            self.assertIn("A sudden turn leaves the streamer stunned", sidecar)
            self.assertIn("#Shorts #Gaming", sidecar)
            self.assertNotIn("Source: source_recording.mp4", sidecar)
            self.assertNotIn("Timestamp:", sidecar)
            self.assertIn("Clip: rendered_clip.mp4", manifest)
            self.assertIn("Source: source_recording.mp4", manifest)
            self.assertIn("Timestamp: 00:00:10 - 00:00:18", manifest)

    def test_find_peaks_snapshots_the_selected_highlight_provider_for_clip_copy(self):
        cfg = autoclip.clean_cfg({"compute_device": "cpu", "clips_per_chunk": 1})
        selected = {"provider": "gemini", "gemini_api_key": "test-key"}
        engine = autoclip.Engine(cfg, lambda *_: None)
        with patch.object(engine, "rms_per_second", return_value=autoclip.np.ones(12)), \
             patch.object(autoclip, "load_ai_settings", return_value=selected), \
             patch.object(autoclip, "select_moments", return_value=[]):
            picks, duration = engine.find_peaks("source.mp4", [])
        self.assertEqual((picks, duration), ([], 12))
        self.assertEqual(engine.ai_cfg_for_render["provider"], "gemini")
        self.assertEqual(engine.ai_cfg_for_render["gemini_api_key"], "test-key")
        with patch.object(engine, "rms_per_second", return_value=autoclip.np.ones(12)), \
             patch.object(autoclip, "load_ai_settings", return_value={"provider": "ollama"}) as reload_settings, \
             patch.object(autoclip, "select_moments", return_value=[]):
            engine.find_peaks("second-source.mp4", [])
        reload_settings.assert_not_called()

    def test_renderer_keeps_clip_and_uses_transcript_fallback_when_ai_copy_fails(self):
        cfg = autoclip.clean_cfg({
            "compute_device": "cpu",
        })
        logs = []
        engine = autoclip.Engine(cfg, lambda kind, value: logs.append((kind, value)))
        engine.ai_cfg_for_render = {"provider": "gemini"}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def fake_run(command, cwd, **_kwargs):
                (Path(cwd) / command[-1]).write_bytes(b"test video")
                return types.SimpleNamespace(returncode=0, stderr="")

            with patch.object(autoclip, "OUT", output), \
                 patch.object(autoclip, "make_ass"), \
                 patch.object(autoclip, "run", side_effect=fake_run), \
                 patch.object(autoclip, "has_nvenc", return_value=False), \
                 patch.object(autoclip, "ffmpeg_exe", return_value="ffmpeg"), \
                 patch.object(autoclip, "load_ai_settings", return_value={
                     "provider": "gemini", "metadata_copy_enabled": "true"
                 }), \
                 patch.object(autoclip, "generate_social_copy",
                              side_effect=RuntimeError("Gemini timeout")) as copy:
                engine.render(
                    "source_recording.mp4", 10, 18,
                    [(10.1, 10.5, "That"), (10.5, 11.0, "was"),
                     (11.0, 11.5, "unbelievable!")],
                    "fallback_clip"
                )

            self.assertTrue((output / "fallback_clip.mp4").is_file())
            sidecar = (output / "fallback_clip.txt").read_text(encoding="utf-8")
            self.assertEqual(sidecar.splitlines()[0], "That Was Unbelievable!")
            self.assertIn("That was unbelievable!", sidecar)
            self.assertEqual(copy.call_count, 1)
            self.assertTrue(any("using concise transcript fallback" in str(value).lower()
                                for _kind, value in logs))

    def test_legacy_cta_settings_are_ignored_and_no_cta_overlay_is_written(self):
        cfg = autoclip.clean_cfg({
            "cta_enabled": True,
            "cta_text": "Subscribe for more clips",
            "cta_voice_enabled": True,
        })
        self.assertNotIn("cta_enabled", cfg)
        self.assertNotIn("cta_text", cfg)
        self.assertNotIn("cta_voice_enabled", cfg)
        with tempfile.TemporaryDirectory() as directory:
            ass_file = Path(directory) / "no-cta.ass"
            autoclip.make_ass([(0.0, 1.0, "Keep the original clip clean")], 0, 2,
                              ass_file, cfg)
            self.assertNotIn("Subscribe for more clips", ass_file.read_text(encoding="utf-8"))

    def test_clip_metadata_sidecar_and_combined_index(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            sidecar, manifest = autoclip.write_clip_metadata_files(
                output, "stream_clip1.mp4", "stream_recording.mp4", 12.8, 47.2,
                "That was unbelievable! The whole chat went crazy.",
                "@streamer"
            )
            self.assertEqual(sidecar, output / "stream_clip1.txt")
            self.assertEqual(manifest, output / "clips_metadata.txt")
            metadata = sidecar.read_text(encoding="utf-8")
            self.assertEqual(metadata.splitlines()[0], "That was unbelievable!")
            self.assertIn("\n\nThat was unbelievable! The whole chat went crazy.", metadata)
            self.assertIn("Clip from @streamer", metadata)
            self.assertIn("#shorts", metadata)
            self.assertNotIn("Clip: stream_clip1.mp4", metadata)
            self.assertNotIn("Source: stream_recording.mp4", metadata)
            self.assertNotIn("Timestamp:", metadata)
            index_before = manifest.read_text(encoding="utf-8")
            self.assertIn("Clip: stream_clip1.mp4", index_before)
            self.assertIn("Source: stream_recording.mp4", index_before)
            self.assertIn("Timestamp: 00:00:12 - 00:00:47", index_before)
            autoclip.write_clip_metadata_files(
                output, "stream_clip2.mp4", "stream_recording.mp4", 65, 91,
                "Another great moment.", "@streamer"
            )
            index = manifest.read_text(encoding="utf-8")
            self.assertIn("Clip: stream_clip1.mp4", index)
            self.assertIn("Clip: stream_clip2.mp4", index)

    def test_clip_metadata_fallback_when_no_speech_is_detected(self):
        metadata = autoclip.build_clip_metadata_text(
            "gameplay_clip1.mp4", "my_gameplay_recording.mp4", 0, 8, ""
        )
        self.assertEqual(metadata.splitlines()[0], "Highlight from my gameplay recording")
        self.assertIn("No speech transcript was detected.", metadata)


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

    def test_publish_queue_accepts_creator_live_and_vod_clip_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            core = object.__new__(autoclip.Core)
            core.lock = threading.RLock()
            core.creators = {"creator_publish": {"id": "creator_publish", "name": "Publish Creator"}}
            core.publishing = {"zernio": {"api_key": "test-key", "accounts": {"instagram": "ig-account"}}}
            core.posting = {"active": False, "total": 0, "completed": 0, "current": "", "started": 0,
                            "done": 0, "last_name": "", "errors": 0}
            core.push = MagicMock()
            publisher = MagicMock()
            core._make_publisher = MagicMock(return_value=publisher)

            class InlineThread:
                def __init__(self, target, **_kwargs):
                    self.target = target
                def start(self):
                    self.target()

            with patch.object(autoclip, "_data_root", root / "data"), patch.object(autoclip, "OUT", root / "main"), patch.object(autoclip, "CORE", core), patch.object(autoclip.threading, "Thread", InlineThread):
                paths = core._ensure_creator_paths("creator_publish")
                clip = paths["live_clips"] / "creator_p_live_clip1.mp4"
                clip.write_bytes(b"video")
                autoclip.invalidate_clip_cache()
                result = core.publish_clips(
                    [clip.name],
                    caption_overrides={clip.name: "Edited title\n\nEdited description"},
                    account_ids={"instagram": "ig-account"},
                )
            self.assertEqual(result["queued"], 1)
            self.assertEqual(publisher.publish_one.call_args.args[0], clip.resolve())
            self.assertEqual(publisher.publish_one.call_args.kwargs["caption_override"], "Edited title\n\nEdited description")
            self.assertEqual(publisher.publish_one.call_args.kwargs["accounts"], {"instagram": "ig-account"})
            self.assertEqual(core.posting["completed"], 1)

    def test_zernio_direct_publish_supports_multiple_platforms_and_keeps_profanity_postable(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"video")
            publisher = ZernioPublisher(lambda _: None, {"api_key": "test-key"})
            publisher._upload = MagicMock(return_value="https://media.example/clip.mp4")
            publisher._json_request = MagicMock(return_value={"data": {"post": {
                "status": "published",
                "platforms": [
                    {"platform": "instagram", "accountId": "ig-account", "status": "published"},
                    {"platform": "facebook", "accountId": "fb-account", "status": "published"},
                ],
            }}})
            publisher.publish_one(
                video,
                accounts={"instagram": "ig-account", "facebook": "fb-account"},
                caption_override="That was damn wild!\n\nThe streamer could not believe it.",
            )
            body = publisher._json_request.call_args.args[2]
            self.assertEqual(body["content"], "That was damn wild!\n\nThe streamer could not believe it.")
            self.assertEqual({item["platform"] for item in body["platforms"]}, {"instagram", "facebook"})
            facebook = next(item for item in body["platforms"] if item["platform"] == "facebook")
            self.assertEqual(facebook["platformSpecificData"]["contentType"], "reel")

    def test_zernio_accounts_returns_supported_video_social_platforms(self):
        publisher = ZernioPublisher(lambda _: None)
        publisher._json_request = MagicMock(return_value={"data": {"accounts": [
            {"platform": "tiktok", "accountId": "tt1", "username": "creator"},
            {"platform": "facebook", "accountId": "fb1", "displayName": "Page"},
            {"platform": "whatsapp", "accountId": "wa1"},
            {"platform": "youtube", "accountId": "yt1"},
        ]}})
        accounts = publisher.accounts()
        self.assertEqual({item["platform"] for item in accounts}, {"facebook", "youtube"})

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
        self.assertEqual(settings["gemini_model"], "gemini-3.1-flash-lite")

    def test_ai_settings_default_to_free_gemini_flash_lite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                settings = autoclip.load_ai_settings()
        self.assertEqual(settings["provider"], "gemini")
        self.assertEqual(settings["gemini_model"], "gemini-3.1-flash-lite")

    def test_ai_settings_preserve_an_explicit_saved_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            path.write_text('{"provider": "openai"}', encoding="utf-8")
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                settings = autoclip.load_ai_settings()
        self.assertEqual(settings["provider"], "openai")

    def test_streamer_credit_infers_supported_channel_handles(self):
        for target, expected in (
            ("https://www.twitch.tv/Ninja/live", "@Ninja"),
            ("https://www.youtube.com/@MrBeast/streams", "@MrBeast"),
            ("https://youtube.com/c/CreatorName", "@CreatorName"),
            ("https://m.youtube.com/user/LegacyCreator", "@LegacyCreator"),
        ):
            with self.subTest(target=target):
                self.assertEqual(
                    autoclip.streamer_credit({"target": target, "streamer_tag": ""}),
                    expected,
                )
        self.assertEqual(
            autoclip.streamer_credit({"target": "https://twitch.tv/Ninja", "streamer_tag": "My channel"}),
            "My channel",
        )

    def test_ai_settings_preserve_explicit_gemini_31_flash_lite_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            path.write_text(__import__("json").dumps({
                "provider": "gemini",
                "gemini_model": "gemini-3.1-flash-lite",
            }), encoding="utf-8")
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                settings = autoclip.load_ai_settings()
        self.assertEqual(settings["gemini_model"], "gemini-3.1-flash-lite")

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

    def test_zernio_immediate_success_moves_clip_to_posted_callback(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"video")
            callback = MagicMock()
            publisher = ZernioPublisher(lambda *_: None, {"api_key": "test", "enabled": True},
                                        on_success=callback)
            publisher.accounts_map = {"instagram": "account"}
            publisher._upload = MagicMock(return_value="https://cdn.invalid/clip.mp4")
            publisher._json_request = MagicMock(return_value={"data": {"post": {
                "status": "published",
                "platforms": [
                    {"platform": "instagram", "accountId": "account", "status": "published"}
                ],
            }}})
            publisher._publish(video, raise_errors=True)
            callback.assert_called_once_with(video, ["instagram:account"])

    def test_zernio_scheduled_post_does_not_claim_it_is_already_posted(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "clip.mp4"
            video.write_bytes(b"video")
            callback = MagicMock()
            scheduled_callback = MagicMock()
            publisher = ZernioPublisher(lambda *_: None, {"api_key": "test", "enabled": True},
                                        on_success=callback, on_scheduled=scheduled_callback)
            publisher.accounts_map = {"instagram": "account"}
            publisher.schedule_minutes = 10
            publisher._upload = MagicMock(return_value="https://cdn.invalid/clip.mp4")
            publisher._json_request = MagicMock(return_value={"data": {"post": {
                "status": "scheduled",
                "platforms": [
                    {"platform": "instagram", "accountId": "account", "status": "scheduled"}
                ],
            }}})
            publisher._publish(video, raise_errors=True)
            callback.assert_not_called()
            scheduled_callback.assert_called_once_with(video, ["instagram:account"])

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
                 patch.object(autoclip, "download_whisper_model", return_value="C:/models/distil-large-v3"), \
                 patch.dict(sys.modules, {"faster_whisper": types.SimpleNamespace(WhisperModel=fake_model)}):
                with self.assertRaisesRegex(RuntimeError, "CPU fallback is disabled"):
                    engine.get_model("distil-large-v3")
            self.assertEqual([device for _, device, _ in attempts], ["cuda", "cuda"])
        finally:
            autoclip._model, autoclip._model_key = old_model, old_key

    def test_transcriber_disables_vad_when_onnxruntime_is_not_installed(self):
        engine = autoclip.Engine(autoclip.clean_cfg({"model": "distil-large-v3"}), lambda *_: None)
        engine.load_audio = lambda _path: autoclip.np.zeros(32000, dtype=autoclip.np.float32)
        word = types.SimpleNamespace(start=0.2, end=0.8, word=" hello")
        segment = types.SimpleNamespace(words=[word], start=0.0, end=1.0)
        model = MagicMock()
        model.transcribe.return_value = (iter([segment]), None)
        engine.get_model = MagicMock(return_value=model)
        with patch.dict(sys.modules, {"onnxruntime": None}):
            result = engine.transcribe("synthetic.wav")
        self.assertEqual(result, [(0.2, 0.8, "hello")])
        self.assertFalse(model.transcribe.call_args.kwargs["vad_filter"])

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
        self.assertIn("Style: Default,Impact,82,&H0043FFEF", subtitles)
        self.assertIn(r"{\1c&HA845FF&", subtitles)
        self.assertIn("Clip from @channel", subtitles)

    def test_capture_bitrate_defaults_to_eight_megabits_and_clamps_below_it(self):
        self.assertEqual(autoclip.clean_cfg({})["capture_bitrate_kbps"], 8000)
        self.assertEqual(autoclip.clean_cfg({"capture_bitrate_kbps": 6000})["capture_bitrate_kbps"], 8000)
        self.assertEqual(autoclip.clean_cfg({"capture_bitrate_kbps": 12000})["capture_bitrate_kbps"], 12000)

    def test_middle_caption_location_preset_is_centered_in_rendered_ass(self):
        cfg = autoclip.clean_cfg({"position": "Middle"})
        self.assertEqual(cfg["position"], "Middle")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "middle.ass"
            autoclip.make_ass([(0.1, 0.5, "CENTERED"), (0.6, 1.0, "CAPTION")], 0, 2, path, cfg)
            script = path.read_text(encoding="utf-8")
        self.assertIn("Style: Default,Impact,82,&H0043FFEF", script)
        self.assertIn(",5,70,70,0,1", script)

    def test_gta_neon_is_a_real_caption_preset_with_distinct_brand_colors(self):
        self.assertIn("GTA Neon", autoclip.SUBTITLE_STYLES)
        cfg = autoclip.clean_cfg({"subtitle_style": "GTA Neon"})
        self.assertEqual(cfg["subtitle_style"], "GTA Neon")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gta-neon.ass"
            autoclip.make_ass([(0.1, 0.5, "no"), (0.6, 1.0, "way")], 0, 2, path, cfg)
            script = path.read_text(encoding="utf-8")
        self.assertIn("Style: Default,Impact,82,&H0043FFEF", script)
        self.assertIn(r"{\1c&HA845FF&", script)
        self.assertIn("&H00451030", script)

    def test_caption_animation_presets_change_word_reveal_behavior(self):
        expected = {"highlight", "pop_in", "pop_in_line", "one_by_one", "build_up", "full_line"}
        self.assertEqual(set(autoclip.SUBTITLE_ANIMATIONS), expected)
        words = [(0.1, 0.4, "NO"), (0.5, 0.8, "WAY"), (0.9, 1.2, "THAT"), (1.3, 1.6, "WAS")]
        scripts = {}
        with tempfile.TemporaryDirectory() as directory:
            for animation in sorted(expected):
                cfg = autoclip.clean_cfg({"subtitle_style": "GTA Neon", "subtitle_animation": animation,
                                          "words_per_line": 4})
                path = Path(directory) / (animation + ".ass")
                autoclip.make_ass(words, 0, 2, path, cfg)
                scripts[animation] = path.read_text(encoding="utf-8")
        self.assertEqual(scripts["full_line"].count("Dialogue:"), 1)
        self.assertIn("NO", scripts["pop_in"])
        self.assertIn("WAS", scripts["pop_in"])
        self.assertIn(r"\1c&H43FFEF&", scripts["build_up"])
        self.assertNotIn(r"\fscx118", scripts["build_up"])
        self.assertEqual(scripts["one_by_one"].count("}NO{"), 1)
        self.assertIn(r"\fscx82\fscy82", scripts["pop_in_line"])

    def test_windows_reveal_opens_containing_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = Path(directory) / "clip.mp4"
            clip.touch()
            with patch.object(autoclip.platform, "system", return_value="Windows"), \
                 patch.object(autoclip.subprocess, "Popen") as popen:
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

    def test_publishing_save_persists_multi_platform_account_selection(self):
        core = object.__new__(autoclip.Core)
        core.publishing = {"provider": "zernio", "zernio": {"api_key": "secret"}}
        core._make_publisher = MagicMock(return_value=object())
        with patch.object(autoclip, "save_publishing_settings"):
            result = core.publishing_save({
                "provider": "zernio", "api_key": "", "account_ids": {
                    "tiktok": "tt-account", "instagram": "ig-account", "facebook": "fb-account"
                }
            })
        self.assertEqual(core.publishing["zernio"]["accounts"], {
            "instagram": "ig-account", "facebook": "fb-account"
        })
        self.assertEqual(result["providers"]["zernio"]["accounts"], {
            "instagram": "ig-account", "facebook": "fb-account"
        })

    def test_render_retries_video_only_when_aac_has_no_packets(self):
        engine = autoclip.Engine(autoclip.clean_cfg({"compute_device": "cpu"}), lambda *_: None)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.mp4"
            source.write_bytes(b"test source")
            output = root / "out"
            output.mkdir()
            commands = []

            ass_path = output / "audio-empty-fallback.ass"

            def write_ass(_words, _start, _end, path, _cfg):
                Path(path).write_text("[Script Info]\\n", encoding="utf-8")

            def fake_run(command, cwd, **_kwargs):
                commands.append(command)
                if len(commands) == 1:
                    return types.SimpleNamespace(
                        returncode=1,
                        stderr="[aac] Could not open encoder before EOF; Nothing was written into output file, because at least one of its streams received no packets.",
                    )
                self.assertTrue(ass_path.is_file(), "The subtitle sidecar must remain available for the retry.")
                (Path(cwd) / command[-1]).write_bytes(b"video")
                return types.SimpleNamespace(returncode=0, stderr="")

            with patch.object(autoclip, "OUT", output), patch.object(autoclip, "make_ass", side_effect=write_ass), \
                 patch.object(autoclip, "run", side_effect=fake_run), \
                 patch.object(autoclip, "has_nvenc", return_value=False), \
                 patch.object(autoclip, "ffmpeg_exe", return_value="ffmpeg"):
                engine.render(source, 5, 8, [], "audio-empty-fallback")

            self.assertFalse(ass_path.exists())
            self.assertEqual(len(commands), 2)
            self.assertIn("0:a?", commands[0])
            self.assertIn("-an", commands[1])
            self.assertNotIn("0:a?", commands[1])
            self.assertTrue((output / "audio-empty-fallback.mp4").is_file())

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
                 patch.object(autoclip, "has_nvenc", return_value=False), \
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

    def test_live_capture_bitrate_defaults_and_clamps_to_8000_kbps(self):
        self.assertEqual(autoclip.clean_cfg({})["capture_bitrate_kbps"], 8000)
        self.assertEqual(autoclip.clean_cfg({"capture_bitrate_kbps": 6000})["capture_bitrate_kbps"], 8000)

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

        with patch.dict(ai_highlights._GEMINI_ACTIVE_CACHE, {}, clear=True), \
             patch.object(ai_highlights, "_json_request", side_effect=fake_request), \
             patch.object(ai_highlights.time, "sleep"):
            result = ai_highlights._gemini("transcript", {"gemini_api_key": "test-key",
                                                           "gemini_model": "gemini-3.8-flash"})
        self.assertEqual(result, {"moments": []})
        self.assertTrue(any("gemini-backup-flash:generateContent" in url for url in calls))
        self.assertEqual(sum("gemini-3.8-flash:generateContent" in url for url in calls), 3)

    def test_gemini_quota_error_rotates_without_repeating_same_model(self):
        calls = []
        def fake_request(url, payload=None, headers=None, timeout=90):
            if "/models?" in url:
                return {"models": [
                    {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/gemini-backup-flash", "supportedGenerationMethods": ["generateContent"]},
                ]}
            calls.append(url)
            if "gemini-3.8-flash" in url:
                raise ai_highlights.AIProviderError("HTTP 429 quota", quota=True, retryable=True)
            return {"candidates": [{"content": {"parts": [{"text": '{"moments": []}'}]}}]}

        with patch.object(ai_highlights, "_json_request", side_effect=fake_request):
            result = ai_highlights._gemini("transcript", {
                "gemini_api_key": "test-key", "gemini_model": "gemini-3.8-flash",
            })
        self.assertEqual(result, {"moments": []})
        self.assertEqual(sum("gemini-3.8-flash" in url for url in calls), 3)
        self.assertEqual(sum("gemini-backup-flash" in url for url in calls), 1)

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
                                     })
            engine = autoclip.Engine(cfg, lambda *_: None)
            with patch.object(autoclip, "OUT", output), patch.dict(autoclip.OUTPUT_FORMATS, {"16:9": (320, 240)}):
                engine.render(source, 5, 8, [(5.1, 6.8, "CAPTION VISIBLE")], "caption-test")
            visible = autoclip.run([ffmpeg, "-v", "error", "-ss", "0.5", "-i",
                                    str(output / "caption-test.mp4"), "-vf", "format=gray",
                                    "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True)
            absent = autoclip.run([ffmpeg, "-v", "error", "-ss", "2.5", "-i",
                                   str(output / "caption-test.mp4"), "-vf", "format=gray",
                                   "-frames:v", "1", "-f", "rawvideo", "-"], capture_output=True)
            self.assertGreater(sum(value > 60 for value in visible.stdout), 1000)
            self.assertLess(sum(value > 220 for value in absent.stdout), 100)

    @unittest.skipUnless(autoclip.shutil.which("ffmpeg") or autoclip.ffmpeg_exe() != "ffmpeg", "FFmpeg is not installed")
    def test_render_audio_eof_fallback_keeps_subtitles_and_outputs_video(self):
        ffmpeg = autoclip.ffmpeg_exe()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "video-with-short-audio.mp4"
            output = root / "out"
            output.mkdir()
            created = autoclip.run([
                ffmpeg, "-y", "-v", "error",
                "-f", "lavfi", "-i", "color=c=black:s=320x240:r=25:d=8",
                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-t", "8", str(source),
            ], capture_output=True, text=True)
            self.assertEqual(created.returncode, 0, created.stderr)

            logs = []
            attempts = []
            cfg = autoclip.clean_cfg({
                "compute_device": "cpu", "layout": "Fill (crop center)",
                "output_format": "16:9", "caption_size": 150,
            })
            with patch.object(autoclip, "OUT", output), \
                 patch.dict(autoclip.OUTPUT_FORMATS, {"16:9": (320, 240)}):
                engine = autoclip.Engine(cfg, lambda kind, payload: logs.append((kind, payload)))
                real_run = autoclip.run

                def fail_first_audio_attempt(command, **kwargs):
                    # Let has_nvenc() run its independent FFmpeg probe normally.
                    if "cwd" not in kwargs:
                        return real_run(command, **kwargs)
                    attempts.append(command)
                    if "-an" not in command:
                        return types.SimpleNamespace(
                            returncode=1,
                            stderr="[aac] Could not open encoder before EOF; Nothing was written into output file, because at least one of its streams received no packets.",
                        )
                    self.assertTrue((output / "audio-eof-recovery.ass").is_file())
                    return real_run(command, **kwargs)

                with patch.object(autoclip, "run", side_effect=fail_first_audio_attempt):
                    engine.render(source, 5, 8, [(5.1, 6.8, "CAPTION VISIBLE")], "audio-eof-recovery")

            rendered = output / "audio-eof-recovery.mp4"
            self.assertTrue(rendered.is_file())
            self.assertGreater(rendered.stat().st_size, 1000)
            self.assertFalse((output / "audio-eof-recovery.ass").exists())
            self.assertEqual(len(attempts), 2)
            self.assertIn("0:a?", attempts[0])
            self.assertIn("-an", attempts[1])
            self.assertTrue(any("Retrying the render without an audio stream" in str(payload)
                                for _kind, payload in logs))

    def test_gemini_quota_exhaustion_falls_back_to_ollama(self):
        logs = []
        with patch.object(ai_highlights, "_gemini", side_effect=ai_highlights.AIProviderError("quota", quota=True)), \
             patch.object(ai_highlights, "_ollama", return_value={"moments": [{"time": 24, "score": 92}]}):
            moments = ai_highlights.select_moments("gemini", [(24, 25, "wow")], 60, {}, logs.append)
        self.assertEqual(moments, [(24, 85.8)])
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

        with patch.dict(ai_highlights._GEMINI_ACTIVE_CACHE, {}, clear=True), \
             patch.object(ai_highlights, "_json_request", side_effect=fake_request), \
             patch.object(ai_highlights.time, "sleep"), \
             patch.object(ai_highlights, "_ollama",
                          return_value={"moments": [{"time": 24, "score": 92}]}) as ollama:
            moments = ai_highlights.select_moments(
                "gemini", [(24, 25, "wow")], 60,
                {"gemini_api_key": "test-key", "gemini_model": "gemini-3.8-flash"},
                logs.append,
            )
        self.assertEqual(moments, [(24, 85.8)])
        self.assertEqual(len(generation_urls), 6)
        self.assertEqual(sum("gemini-3.8-flash" in url for url in generation_urls), 3)
        self.assertEqual(sum("gemini-backup-flash" in url for url in generation_urls), 3)
        ollama.assert_called_once()
        self.assertTrue(any("Remaining transcript windows were analyzed with Ollama" in line for line in logs))

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
        self.assertEqual(moments, [(10, 74.3), (310, 74.3), (610, 74.3)])
        self.assertEqual(len(prompts), 3)

    def test_zero_score_threshold_does_not_turn_empty_ai_seconds_into_clips(self):
        engine = autoclip.Engine(autoclip.clean_cfg({"clips_per_chunk": 0, "min_score": 0}), lambda *_: None)
        engine.rms_per_second = lambda _path: autoclip.np.ones(120)
        with patch.object(autoclip, "load_ai_settings", return_value={"provider": "ollama"}), \
             patch.object(autoclip, "select_moments", return_value=[(35, 80.0)]):
            picks, duration = engine.find_peaks("clip.mp4", [])
        self.assertEqual(duration, 120)
        self.assertEqual(picks, [(35, 80.0)])

    def test_ai_provider_empty_result_does_not_fallback_to_local_peaks(self):
        engine = object.__new__(autoclip.Engine)
        engine.cfg = {"min_score": 70, "clips_per_chunk": 0, "chunk_min": 3}
        engine.ai_cancel = __import__("threading").Event()
        engine.log = MagicMock()
        engine.status = MagicMock()
        engine.rms_per_second = lambda _path: autoclip.np.ones(120)
        with patch.object(autoclip, "load_custom", return_value=[]), \
             patch.object(autoclip, "load_ai_settings", return_value={"provider": "gemini"}), \
             patch.object(autoclip, "select_moments", return_value=[]):
            picks, duration = engine.find_peaks("clip.mp4", [])
        self.assertEqual(duration, 120)
        self.assertEqual(picks, [])
        self.assertTrue(engine.ai_strict_no_clip)

    def test_process_logs_transcribed_words(self):
        engine = object.__new__(autoclip.Engine)
        engine.cfg = {"min_score": 70, "pre": 20, "post": 15, "delete_rec": False}
        engine.log = MagicMock()
        engine.status = MagicMock()
        engine.check = MagicMock()
        engine.transcribe = lambda _path: [(0.0, 0.5, "Hello"), (0.6, 1.0, "world!")]
        engine.find_peaks = lambda _path, _words: ([], 10)
        engine.emit = MagicMock()
        engine.process("clip.ts")
        engine.log.assert_any_call("Transcript words (2): HELLO WORLD!")

    def test_rejected_recording_chunk_is_deleted_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            recording = Path(directory).resolve() / "segment.ts"
            recording.touch()
            engine = object.__new__(autoclip.Engine)
            engine.cfg = {"min_score": 70, "pre": 20, "post": 15, "delete_rec": False}
            engine.log = MagicMock()
            engine.status = MagicMock()
            engine.check = MagicMock()
            engine.transcribe = lambda _path: []
            engine.find_peaks = lambda _path, _words: ([], 10)
            engine.emit = MagicMock()
            with patch.object(autoclip, "REC", Path(directory)):
                engine.process(recording)
            self.assertFalse(recording.exists())

    def test_runtime_log_is_persisted_for_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "streamsnip.log"
            with patch.object(autoclip, "RUNTIME_LOG", log_path):
                autoclip.append_runtime_log("12:34:56", "GPU load failed")
            self.assertEqual(log_path.read_text(encoding="utf-8"), "12:34:56 GPU load failed\n")

    def test_ai_moment_without_explicit_score_is_rejected(self):
        self.assertEqual(ai_highlights._parse_moments(
            {"moments": [{"time": 10, "reason": "ordinary chat"}]}, 60), [])

    def test_ai_prompt_uses_human_viral_scoring_rubric(self):
        prompt = ai_highlights._prompt([(10, 11, "oh my god this is insane")], 60)
        self.assertIn("emotion", prompt)
        self.assertIn("absurdity", prompt)
        self.assertIn("80 = strong clip candidate", prompt)
        self.assertIn("Return strong candidates even when they score below 80", prompt)

    def test_generic_ai_suggestion_stays_below_an_eighty_floor(self):
        # A model's uncorroborated 80 should not automatically clear an 80 setting.
        with patch.object(ai_highlights, "_ollama",
                          return_value={"moments": [{"time": 10, "score": 80}]}):
            moments = ai_highlights.select_moments(
                "ollama", [(10, 11, "just walking to the next room")], 60, {})
        self.assertEqual(moments, [(10, 74.9)])
        self.assertLess(moments[0][1], 80)

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
                saved = autoclip.save_ai_settings({
                    "provider": "gemini", "gemini_api_key": "secret",
                    "custom_api_base": "https://free-provider.example/v1",
                    "custom_api_model": "free-model", "custom_api_key": "custom-secret",
                    "metadata_copy_enabled": False,
                })
                stored = path.read_text(encoding="utf-8")
                self.assertTrue(saved["metadata_copy_enabled"])
                self.assertEqual(autoclip.load_ai_settings()["metadata_copy_enabled"], "true")
                disabled = autoclip.save_ai_settings({"metadata_copy_enabled": False})
                self.assertTrue(disabled["metadata_copy_enabled"])
                self.assertEqual(autoclip.load_ai_settings()["metadata_copy_enabled"], "true")
            self.assertTrue(saved["gemini_key_set"])
            self.assertTrue(saved["custom_api_key_set"])
            self.assertEqual(saved["custom_api_base"], "https://free-provider.example/v1")
            self.assertEqual(saved["custom_api_model"], "free-model")
            self.assertNotIn("secret", str(saved))
            self.assertIn("secret", stored)
            self.assertIn("custom-secret", stored)

    def test_native_installer_tracks_owned_dependencies_and_keeps_user_python(self):
        root = Path(__file__).resolve().parents[1]
        setup_script = (root / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        uninstall_script = (root / "installer" / "uninstall_windows.ps1").read_text(encoding="utf-8")
        installer_script = (root / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8")
        self.assertIn("api_server.py", setup_script)
        self.assertIn("[switch]$NativeDesktop", setup_script)
        self.assertIn("native-engine.json", setup_script)
        self.assertIn("source_root = $source", setup_script)
        self.assertIn("python_executable = $runtimePython", setup_script)
        self.assertIn("data_root = $dataRoot", setup_script)
        self.assertIn("-NativeDesktop", installer_script)
        self.assertIn("CurStepChanged(CurStep: TSetupStep)", installer_script)
        self.assertIn("ewWaitUntilTerminated", installer_script)
        self.assertIn("ResultCode <> 0", installer_script)
        self.assertNotIn("setup_native_windows.ps1", installer_script)
        self.assertFalse((root / "installer" / "setup_native_windows.ps1").exists())
        self.assertEqual(installer_script.count("ShowCommand, ewWaitUntilTerminated, ResultCode"), 1)
        self.assertEqual(installer_script.count("SW_HIDE, ewWaitUntilTerminated, ResultCode"), 1)
        self.assertIn("function InitializeUninstall(): Boolean;", installer_script)
        self.assertIn("procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);", installer_script)
        self.assertIn("zernio_connections.py", installer_script)
        self.assertIn("StreamSnip.Desktop.exe", installer_script)
        self.assertNotIn("custom_words.txt", installer_script)
        self.assertNotIn('Mark-DependencyInstalled "python"', setup_script)
        self.assertIn('Mark-DependencyInstalled "ffmpeg"', setup_script)
        self.assertIn('Remove-PathSafely (Join-Path $AppDir "python-base") "app-local Python base"', uninstall_script)
        self.assertIn('Remove-PathSafely (Join-Path $AppDir "runtime") "isolated Python runtime"', uninstall_script)
        self.assertIn('Remove-PathSafely $localRoot "StreamSnip AI app data"', uninstall_script)
        self.assertIn('python_installed_by_streamsnip', uninstall_script)
        self.assertIn('ffmpeg_installed_by_streamsnip', uninstall_script)
        self.assertIn('Python.Python.3.12', uninstall_script)
        self.assertIn('Gyan.FFmpeg', uninstall_script)
        self.assertIn('source\\models', uninstall_script)
        self.assertIn('uninstall_windows.ps1', installer_script)
        self.assertIn('CurUninstallStepChanged(CurUninstallStep: TUninstallStep)', installer_script)
        self.assertIn('[UninstallDelete]', installer_script)
        self.assertIn('filesandordirs; Name: "{app}\\source"', installer_script)

    def test_installer_accepts_python_310_plus_and_installs_only_when_none_exists(self):
        root = Path(__file__).resolve().parents[1]
        setup_script = (root / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        uninstall_script = (root / "installer" / "uninstall_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("sys.version_info[:2] >= (3,10)", setup_script)
        self.assertIn("sys.version_info.releaselevel == 'final'", setup_script)
        self.assertIn("$launcher.Source -0p", setup_script)
        self.assertIn("Sort-Object", setup_script)
        self.assertIn("Install-PythonStable", setup_script)
        self.assertIn("python-base", setup_script)
        self.assertIn("if (-not $python -and -not $CheckOnly) { $python = Install-PythonStable $requirements }", setup_script)
        self.assertIn("Test-PythonDependencyCompatibility", setup_script)
        self.assertIn("--dry-run", setup_script)
        self.assertIn("Sort-Object -Property @{ Expression = { [version]$_.Version }; Descending = $true }", setup_script)
        self.assertIn("python-3.14.10-amd64.exe", setup_script)
        self.assertNotIn("python-3.15.2-amd64.exe", setup_script)
        self.assertNotIn('Mark-DependencyInstalled "python"', setup_script)
        self.assertIn('Remove-PathSafely (Join-Path $AppDir "python-base") "app-local Python base"', uninstall_script)
        self.assertIn('Remove-PathSafely (Join-Path $AppDir "runtime") "isolated Python runtime"', uninstall_script)
        self.assertIn('Remove-PathSafely $localRoot "StreamSnip AI app data"', uninstall_script)
        self.assertNotIn("Install-Python312", setup_script)
        self.assertIn('runtime.previous', setup_script)
        self.assertIn('Runtime migration failed. The previous working Python runtime was restored.', setup_script)
        self.assertIn('The new Python runtime does not match the selected Python', setup_script)

    def test_ai_settings_preserve_one_time_huggingface_setup_choice(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            path.write_text(__import__("json").dumps({
                "provider": "hooks",
                "huggingface_setup_completed": True,
            }), encoding="utf-8")
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                loaded = autoclip.load_ai_settings()
                self.assertEqual(loaded["huggingface_setup_completed"], "True")
                autoclip.save_ai_settings({"provider": "gemini"})
                stored = __import__("json").loads(path.read_text(encoding="utf-8"))
                self.assertTrue(stored["huggingface_setup_completed"])
                self.assertNotIn("huggingface_setup_completed", autoclip.public_ai_settings())

    def test_ai_settings_default_huggingface_setup_choice_is_incomplete(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                self.assertEqual(autoclip.load_ai_settings()["huggingface_setup_completed"], "false")

    def test_ai_settings_can_clear_saved_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ai_settings.json"
            with patch.object(autoclip, "AI_SETTINGS_FILE", path):
                autoclip.save_ai_settings({
                    "provider": "gemini",
                    "gemini_api_key": "gemini-secret",
                    "huggingface_token": "hf-secret",
                })
                cleared = autoclip.save_ai_settings({
                    "clear_gemini_key": True,
                    "clear_huggingface_token": True,
                })
                stored = path.read_text(encoding="utf-8")
            self.assertFalse(cleared["gemini_key_set"])
            self.assertFalse(cleared["huggingface_token_set"])
            self.assertNotIn("gemini-secret", stored)
            self.assertNotIn("hf-secret", stored)
            self.assertNotEqual(__import__("os").environ.get("HF_TOKEN"), "hf-secret")
            self.assertNotEqual(__import__("os").environ.get("HUGGING_FACE_HUB_TOKEN"), "hf-secret")

    def test_app_update_uses_registered_install_version_and_release_checksum(self):
        digest = "a" * 64
        release = {
            "tag_name": "v4.0.10",
            "name": "StreamSnip AI 4.0.10",
            "html_url": "https://github.com/sifat-jaman-13/stream-clip-ai/releases/tag/v4.0.10",
            "assets": [{
                "name": "StreamSnipAI-Native-Setup.exe",
                "browser_download_url": "https://example.invalid/StreamSnipAI-Native-Setup.exe",
                "digest": "sha256:" + digest,
                "size": 12345,
            }],
        }
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(release).encode("utf-8")
        installed = {
            "version": "4.0.6",
            "installed": True,
            "install_dir": r"C:\Apps\StreamSnip AI Native",
            "app_executable": r"C:\Apps\StreamSnip AI Native\desktop\StreamSnip.Desktop.exe",
        }
        with patch.object(autoclip, "_installed_app_info", return_value=installed, create=True), \
             patch.object(autoclip.urllib.request, "urlopen", return_value=response):
            result = autoclip.check_app_update()

        self.assertEqual(result["current"], "4.0.6")
        self.assertEqual(result["latest"], "4.0.10")
        self.assertTrue(result["update"])
        self.assertTrue(result["can_install"])
        self.assertEqual(result["installer_sha256"], digest)
        self.assertEqual(result["installer_size"], 12345)
        self.assertEqual(result["installer_url"], release["assets"][0]["browser_download_url"])

    @unittest.skipUnless(autoclip.os.name == "nt", "Windows-only native installer handoff")
    def test_install_app_update_downloads_verifies_and_schedules_installer(self):
        payload = b"test-installer-payload"
        digest = __import__("hashlib").sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = payload
            release = {
                "current": "4.0.6",
                "latest": "4.0.10",
                "update": True,
                "installer_url": "https://example.invalid/setup.exe",
                "installer_name": "StreamSnipAI-Native-Setup.exe",
                "installer_sha256": digest,
                "installer_size": len(payload),
                "can_install": True,
            }
            installed = {
                "version": "4.0.6",
                "installed": True,
                "install_dir": directory,
                "app_executable": str(Path(directory) / "desktop" / "StreamSnip.Desktop.exe"),
            }
            with patch.object(autoclip, "check_app_update", return_value=release), \
                 patch.object(autoclip, "_installed_app_info", return_value=installed, create=True), \
                 patch.object(autoclip.urllib.request, "urlopen", return_value=response), \
                 patch.object(autoclip.tempfile, "mkdtemp", return_value=directory), \
                 patch.object(autoclip.os, "getppid", return_value=4321), \
                 patch.object(autoclip.subprocess, "Popen") as launch_helper:
                result = autoclip.install_app_update(parent_pid=4321)

            self.assertTrue(result["ok"])
            self.assertTrue(result["pending_restart"])
            self.assertEqual(result["latest"], "4.0.10")
            downloaded = Path(directory) / "StreamSnipAI-Native-Setup.exe"
            self.assertEqual(downloaded.read_bytes(), payload)
            helper = Path(directory) / "install-update.ps1"
            self.assertTrue(helper.is_file())
            self.assertIn("ParentPid", helper.read_text(encoding="utf-8-sig"))
            helper_args = launch_helper.call_args.args[0]
            installer_index = helper_args.index("-InstallerPath")
            self.assertEqual(helper_args[installer_index + 1], str(downloaded))
            self.assertIn("4321", str(launch_helper.call_args))

    @unittest.skipUnless(autoclip.os.name == "nt", "Windows-only native installer handoff")
    def test_install_app_update_rejects_a_bad_checksum_before_launching(self):
        payload = b"tampered-installer"
        with tempfile.TemporaryDirectory() as directory:
            response = MagicMock()
            response.__enter__.return_value.read.return_value = payload
            release = {
                "current": "4.0.6",
                "latest": "4.0.10",
                "update": True,
                "installer_url": "https://example.invalid/setup.exe",
                "installer_name": "StreamSnipAI-Native-Setup.exe",
                "installer_sha256": "0" * 64,
                "installer_size": len(payload),
                "can_install": True,
            }
            with patch.object(autoclip, "check_app_update", return_value=release), \
                 patch.object(autoclip, "_installed_app_info", return_value={"version": "4.0.6", "installed": True, "install_dir": directory,
                     "app_executable": str(Path(directory) / "desktop" / "StreamSnip.Desktop.exe")}, create=True), \
                 patch.object(autoclip.urllib.request, "urlopen", return_value=response), \
                 patch.object(autoclip.tempfile, "mkdtemp", return_value=directory), \
                 patch.object(autoclip.os, "getppid", return_value=4321), \
                 patch.object(autoclip.subprocess, "Popen") as launch_helper:
                with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                    autoclip.install_app_update(parent_pid=4321)
            launch_helper.assert_not_called()
    def test_newer_installed_version_is_not_reported_as_outdated(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"tag_name":"v1.1.5"}'
        with patch.object(autoclip, "APP_VERSION", "1.1.6"), patch.object(
            autoclip, "_installed_app_info", return_value={"version": "1.1.6", "installed": False}
        ), patch.object(autoclip.urllib.request, "urlopen", return_value=response):
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

    def test_verified_app_owned_whisper_model_is_reused_without_hub_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            model_file = Path(directory) / "distil-large-v3" / "model.bin"
            model_file.parent.mkdir(parents=True)
            model_file.touch()
            with patch.object(autoclip, "WHISPER_MODELS", Path(directory)):
                self.assertEqual(autoclip.download_whisper_model("distil-large-v3"),
                                 str(model_file.parent))

    def test_nonfinite_settings_use_defaults(self):
        cfg = autoclip.clean_cfg({"min_score": float("inf"), "cam_x": float("nan")})
        self.assertEqual(cfg["min_score"], autoclip.DEFAULTS["min_score"])
        self.assertEqual(cfg["cam_x"], autoclip.DEFAULTS["cam_x"])

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
                autoclip.sys, "executable", str(root / ("StreamSnipAI.exe" if autoclip.os.name == "nt" else "StreamSnipAI"))
            ):
                self.assertEqual(Path(autoclip.ffmpeg_exe()).resolve(), ffmpeg.resolve())

    def test_installed_source_finds_assets_in_parent_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            assets = root / "assets"
            source.mkdir()
            assets.mkdir()
            icon = assets / "app-icon.png"
            logo = assets / "brand-logo.png"
            icon.write_bytes(b"icon")
            logo.write_bytes(b"logo")
            with patch.object(autoclip, "HERE", source):
                self.assertEqual(autoclip.asset_file("app-icon.png"), icon.resolve())
                self.assertEqual(autoclip.asset_file("brand-logo.png"), logo.resolve())
                self.assertIsNone(autoclip.asset_file("../settings.json"))

    @unittest.skipUnless(autoclip.os.name == "nt", "Windows-only window API")
    def test_post_close_message_targets_only_the_visible_owned_app_window(self):
        import ctypes
        from ctypes import wintypes

        class User32:
            def __init__(self):
                self.messages = []
            def EnumWindows(self, callback, _):
                callback(101, 0)
                callback(202, 0)
            def GetWindowThreadProcessId(self, hwnd, target):
                ctypes.cast(target, ctypes.POINTER(wintypes.DWORD)).contents.value = (
                    4321 if hwnd == 101 else 9999
                )
                return 1
            def IsWindowVisible(self, hwnd):
                return True
            def PostMessageW(self, hwnd, message, wparam, lparam):
                self.messages.append((hwnd, message, wparam, lparam))
                return True

        user32 = User32()
        self.assertTrue(autoclip.post_close_message_to_process_windows(4321, user32))
        self.assertEqual(user32.messages, [(101, 0x0010, 0, 0)])

    @unittest.skipUnless(autoclip.os.name == "nt", "Windows-only process shutdown")
    def test_app_window_close_requests_graceful_process_tree_exit(self):
        process = MagicMock()
        process.poll.return_value = None
        process.pid = 4321
        with patch.object(autoclip.subprocess, "run") as run:
            self.assertTrue(autoclip.request_app_window_close(process, timeout=0.1))
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["taskkill.exe", "/PID", "4321"])
        self.assertNotIn("/F", command)
        process.wait.assert_called_once_with(timeout=0.1)

    @unittest.skipUnless(autoclip.os.name == "nt", "Windows-only browser app launch")
    def test_open_window_launches_an_isolated_tracked_browser_app(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            profile = root / "StreamSnip AI" / "app-window-profile" / "msedge"
            child = MagicMock()
            exists = lambda candidate: str(candidate).lower().endswith("msedge.exe")
            with patch.dict(autoclip.os.environ, {
                "PROGRAMFILES(X86)": str(root),
                "PROGRAMFILES": str(root),
                "LOCALAPPDATA": str(root),
            }), patch.object(autoclip.os.path, "exists", side_effect=exists), \
                 patch.object(autoclip.shutil, "which", return_value=None), \
                 patch.object(autoclip, "popen", return_value=child) as launch, \
                 patch.object(autoclip, "_data_root", root):
                autoclip.open_window("http://127.0.0.1:45678/dashboard/")

            launch.assert_called_once()
            arguments = launch.call_args.args[0]
            self.assertIn("--app=http://127.0.0.1:45678/dashboard/", arguments)
            self.assertIn("--user-data-dir=" + str(profile), arguments)
            self.assertTrue(profile.is_dir())

    def test_creator_studio_quit_shows_a_shutdown_overlay(self):
        root = Path(__file__).resolve().parents[1]
        app_source = (root / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("shutdown-overlay", app_source)
        self.assertIn("Closing StreamSnip AI", app_source)
        self.assertIn("Your finished clips stay safe.", app_source)

    def test_react_creator_studio_owns_a_named_server_window_lease(self):
        root = Path(__file__).resolve().parents[1]
        api_source = (root / "dashboard" / "src" / "api.ts").read_text(encoding="utf-8")
        app_source = (root / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
        self.assertIn("installWindowLeaseLifecycle", api_source)
        self.assertIn("installWindowLeaseLifecycle()", app_source)
        self.assertIn("/api/window/lease?id=", api_source)
        self.assertIn("/api/window/closing?id=", api_source)

    def test_window_close_quits_but_page_reload_can_reconnect(self):
        self.assertIn('window.addEventListener("pagehide"', autoclip.HTML)
        self.assertIn('api("/api/window/open")', autoclip.HTML)
        self.assertIn('windowLeaseId', autoclip.HTML)
        self.assertIn('/api/window/lease?id=', autoclip.HTML)
        self.assertIn('/api/window/closing?id=', autoclip.HTML)
        self.assertIn('api("/api/quit")', autoclip.HTML)
        self.assertIn('const center=h("button",{class:"btn ghost"},"Center segment")', autoclip.HTML)
        self.assertIn('id="ai-test-provider"', autoclip.HTML)
        self.assertIn('id="gemini-key-clear"', autoclip.HTML)
        self.assertIn('id="hf-token-clear"', autoclip.HTML)

    def test_pagehide_releases_its_named_lease_without_waiting_for_sse_disconnect(self):
        timer = MagicMock()
        original_leases = set(autoclip._WINDOW_LEASES)
        try:
            autoclip._WINDOW_LEASES.clear()
            with patch.object(autoclip.threading, "Timer", return_value=timer):
                lease = autoclip.begin_window_lease("test-window-close")
                self.assertEqual(lease, "test-window-close")
                self.assertTrue(autoclip.close_window_lease("test-window-close"))
                self.assertNotIn("test-window-close", autoclip._WINDOW_LEASES)
                timer.start.assert_called_once_with()
                # The late SSE finally callback must be harmless and idempotent.
                autoclip.end_window_lease(lease)
        finally:
            autoclip.cancel_window_close_shutdown()
            autoclip._WINDOW_LEASES.clear()
            autoclip._WINDOW_LEASES.update(original_leases)

    def test_closing_one_window_does_not_close_other_window_leases(self):
        timer = MagicMock()
        original_leases = set(autoclip._WINDOW_LEASES)
        original_closed = set(autoclip._WINDOW_CLOSED_LEASES)
        was_quit = autoclip.QUIT.is_set()
        try:
            autoclip._WINDOW_LEASES.clear()
            autoclip._WINDOW_CLOSED_LEASES.clear()
            autoclip.QUIT.clear()
            with patch.object(autoclip.threading, "Timer", return_value=timer):
                first = autoclip.begin_window_lease("window-one")
                second = autoclip.begin_window_lease("window-two")
                self.assertTrue(autoclip.close_window_lease(first))
                self.assertNotIn(first, autoclip._WINDOW_LEASES)
                self.assertIn(second, autoclip._WINDOW_LEASES)
                timer.start.assert_not_called()
                autoclip.end_window_lease(second)
                timer.start.assert_called_once_with()
        finally:
            autoclip.cancel_window_close_shutdown()
            autoclip._WINDOW_LEASES.clear()
            autoclip._WINDOW_LEASES.update(original_leases)
            autoclip._WINDOW_CLOSED_LEASES.clear()
            autoclip._WINDOW_CLOSED_LEASES.update(original_closed)
            if was_quit:
                autoclip.QUIT.set()

    def test_close_received_before_stream_start_cannot_resurrect_window(self):
        timer = MagicMock()
        original_leases = set(autoclip._WINDOW_LEASES)
        original_closed = set(autoclip._WINDOW_CLOSED_LEASES)
        was_quit = autoclip.QUIT.is_set()
        try:
            autoclip._WINDOW_LEASES.clear()
            autoclip._WINDOW_CLOSED_LEASES.clear()
            autoclip.QUIT.clear()
            with patch.object(autoclip.threading, "Timer", return_value=timer):
                self.assertFalse(autoclip.close_window_lease("late-window"))
                self.assertIsNone(autoclip.begin_window_lease("late-window"))
                self.assertNotIn("late-window", autoclip._WINDOW_LEASES)
                timer.start.assert_called_once_with()
        finally:
            autoclip.cancel_window_close_shutdown()
            autoclip._WINDOW_LEASES.clear()
            autoclip._WINDOW_LEASES.update(original_leases)
            autoclip._WINDOW_CLOSED_LEASES.clear()
            autoclip._WINDOW_CLOSED_LEASES.update(original_closed)
            if was_quit:
                autoclip.QUIT.set()

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


    def test_clip_metadata_title_stays_within_youtube_limit_and_keeps_full_text(self):
        transcript = (
            "This is a deliberately long first sentence that exceeds the YouTube title limit "
            "while preserving the complete spoken words in the description for upload."
        )
        metadata = autoclip.build_clip_metadata_text(
            "long_clip.mp4", "source_recording.ts", 4, 38, transcript
        )
        title, description = metadata.split("\n", 1)
        self.assertLessEqual(len(title), 100)
        self.assertTrue(title.endswith("..."))
        self.assertIn(transcript, description)


    def test_profanity_filter_masks_words_without_substring_false_positives(self):
        words = [
            (1.0, 1.2, "The"),
            (1.2, 1.6, "Fucking"),
            (1.6, 1.9, "game"),
            (1.9, 2.2, "shit!"),
            (2.2, 2.5, "is"),
            (2.5, 2.8, "over."),
        ]
        filtered = autoclip.censor_transcript_words(words)
        self.assertEqual(filtered[1][2], "****")
        self.assertEqual(filtered[3][2], "****")
        jesus = autoclip.censor_transcript_words([(0.0, 0.2, "Jesus"), (0.2, 0.5, "Christ!")])
        self.assertEqual([word[2] for word in jesus], ["****", "****"])
        self.assertEqual(filtered[2][2], "game")
        self.assertEqual(filtered[1][:2], words[1][:2])
        self.assertEqual(filtered[2], words[2])

        # Whole-token matching must not censor innocent words containing "ass".
        safe_text = autoclip.censor_profanity_text("The assistant passed the class.")
        self.assertEqual(safe_text, "The assistant passed the class.")

    def test_profanity_filter_detects_common_variants_and_avoids_substring_matches(self):
        words = [
            (0.0, 0.2, "fuk"),
            (0.2, 0.4, "sh1t"),
            (0.4, 0.6, "bullsh*t"),
            (0.6, 0.8, "dipshit"),
            (0.8, 1.0, "shite"),
            (1.0, 1.2, "assistant"),
            (1.2, 1.4, "classic"),
            (1.4, 1.6, "passionate"),
        ]
        filtered = autoclip.censor_transcript_words(words)
        self.assertEqual([entry[2] for entry in filtered],
                         ["****", "****", "****", "****", "****", "assistant", "classic", "passionate"])
        self.assertEqual(
            autoclip.censor_profanity_text("That was f*cked, bullsh*t, and a$$! The assistant passed."),
            "That was ****, ****, and ****! The assistant passed."
        )
        multilingual = autoclip.censor_transcript_words([
            (0.0, 0.2, "chutiya"), (0.2, 0.4, "blyat"), (0.4, 0.6, "coño")
        ])
        self.assertEqual([entry[2] for entry in multilingual], ["****", "****", "****"])

    def test_profanity_filter_supports_multiword_and_custom_terms(self):
        words = [
            (0.0, 0.2, "You"),
            (0.2, 0.4, "son"),
            (0.4, 0.6, "of"),
            (0.6, 0.8, "a"),
            (0.8, 1.0, "bitch!"),
            (1.0, 1.2, "you"),
            (1.2, 1.4, "absolute"),
            (1.4, 1.6, "clown"),
        ]
        filtered = autoclip.censor_transcript_words(words, extra_terms="absolute clown")
        self.assertEqual([entry[2] for entry in filtered],
                         ["You", "****", "****", "****", "****", "you", "****", "****"])
        self.assertEqual(
            autoclip.censor_profanity_text("You absolute clown!", extra_terms="absolute clown"),
            "You **** ****!"
        )

    def test_profanity_filter_can_be_disabled_and_defaults_to_enabled(self):
        self.assertTrue(autoclip.clean_cfg({})["profanity_filter_enabled"])
        self.assertEqual(autoclip.clean_cfg({})["profanity_audio_mode"], "beep")
        self.assertEqual(autoclip.clean_cfg({"profanity_audio_mode": "mute"})["profanity_audio_mode"], "mute")
        self.assertEqual(autoclip.clean_cfg({"profanity_audio_mode": "unknown"})["profanity_audio_mode"], "beep")
        self.assertFalse(autoclip.clean_cfg({
            "profanity_filter_enabled": False
        })["profanity_filter_enabled"])
        words = [(0.0, 0.5, "fuck")]
        self.assertEqual(
            autoclip.censor_transcript_words(words, enabled=False),
            words
        )
        self.assertEqual(
            autoclip.censor_profanity_text("fuck you", enabled=False),
            "fuck you"
        )

    def test_profanity_audio_filter_beeps_only_at_detected_word_timestamps(self):
        words = [
            (12.1, 12.4, "****"),
            (12.45, 12.8, "****"),
            (15.0, 15.3, "****"),
            (16.0, 16.4, "clean"),
        ]
        audio_filter = autoclip.profanity_audio_filter(words, 10.0, 18.0, mode="beep")
        self.assertIn("aeval=exprs=", audio_filter)
        self.assertIn("sin(2*PI*1000*t)", audio_filter)
        self.assertIn("between(t,2.080,2.820)", audio_filter)
        self.assertIn("between(t,4.980,5.320)", audio_filter)
        self.assertNotIn("between(t,6.000", audio_filter)

    def test_profanity_audio_filter_can_mute_instead_of_beeping(self):
        words = [(12.1, 12.4, "****")]
        audio_filter = autoclip.profanity_audio_filter(words, 10.0, 18.0, mode="mute")
        self.assertIn("volume=0:enable=", audio_filter)
        self.assertIn("between(t,2.080,2.420)", audio_filter)



    def test_renderer_beeps_profanity_and_sanitizes_ai_generated_metadata(self):
        cfg = autoclip.clean_cfg({})
        engine = autoclip.Engine(cfg, lambda *_: None)
        engine.ai_cfg_for_render = {"provider": "gemini"}
        words = [
            (10.2, 10.6, "This"),
            (10.6, 11.2, "fucking"),
            (11.2, 11.7, "worked!"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)

            def fake_run(command, cwd, **_kwargs):
                (Path(cwd) / command[-1]).write_bytes(b"test video")
                return types.SimpleNamespace(returncode=0, stderr="")

            with patch.object(autoclip, "OUT", output), \
                 patch.object(autoclip, "make_ass") as make_ass, \
                 patch.object(autoclip, "run", side_effect=fake_run) as render_run, \
                 patch.object(autoclip, "has_nvenc", return_value=False), \
                 patch.object(autoclip, "ffmpeg_exe", return_value="ffmpeg"), \
                 patch.object(autoclip, "generate_social_copy", return_value={
                     "title": "This fucking worked!",
                     "description": "That was a shit moment.",
                     "hashtags": ["#gaming", "#bullshit"],
                 }) as copy:
                engine.render("source_recording.mp4", 10, 18, words, "filtered_clip")

            filtered_words = make_ass.call_args.args[0]
            self.assertEqual(filtered_words[1][2], "****")
            self.assertEqual(copy.call_args.args[0], "This **** worked!")
            command = render_run.call_args.args[0]
            audio_filter = command[command.index("-af") + 1]
            self.assertIn("aeval=exprs=", audio_filter)
            self.assertIn("between(t,0.580,1.220)", audio_filter)

            metadata = (output / "filtered_clip.txt").read_text(encoding="utf-8").lower()
            self.assertIn("****", metadata)
            self.assertNotIn("fucking", metadata)
            self.assertNotIn("bullshit", metadata)


    def test_streamlink_prefers_the_current_python_install_over_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            local_scripts = root / "Scripts"
            local_scripts.mkdir()
            local_exe = local_scripts / "streamlink.exe"
            local_exe.write_bytes(b"local entry point")
            foreign_exe = str(root / "Python314" / "Scripts" / "streamlink.exe")
            with patch.object(autoclip.sys, "prefix", str(root)), \
                 patch.object(autoclip.sys, "executable", str(root / "python.exe")), \
                 patch.object(autoclip.shutil, "which", return_value=foreign_exe):
                self.assertEqual(autoclip._find_streamlink_exe(), str(local_exe))

    def test_streamlink_environment_does_not_inject_foreign_python_paths(self):
        with patch.dict(autoclip.os.environ, {"PYTHONPATH": r"C:\\Python314\\Lib"}, clear=False):
            env = autoclip.streamlink_env()
        self.assertEqual(env["PYTHONPATH"], r"C:\\Python314\\Lib")


    def test_api_json_body_parser_accepts_empty_object(self):
        self.assertEqual(autoclip.parse_json_object(b""), {})
        self.assertEqual(autoclip.parse_json_object(b'{"ok": true}'), {"ok": True})

    def test_api_json_body_parser_rejects_malformed_json(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON body"):
            autoclip.parse_json_object(b'{"settings":')

    def test_api_json_body_parser_rejects_non_object_payloads(self):
        for raw in (b"[]", b"null", b'"settings"', b"123"):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, "JSON body must be an object"):
                    autoclip.parse_json_object(raw)

    def test_api_json_body_parser_rejects_invalid_utf8(self):
        with self.assertRaisesRegex(ValueError, "invalid JSON body"):
            autoclip.parse_json_object(b"\xff")


    def test_installer_reuses_python_315_without_unsupported_vad_runtime_dependency(self):
        root = Path(__file__).resolve().parents[1]
        setup_script = (root / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        python_support = (root / "installer" / "python315_support.ps1").read_text(encoding="utf-8")
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("New-StreamSnipRequirementsProfile", setup_script)
        self.assertIn("Install-StreamSnipDependencies", setup_script)
        self.assertIn("faster-whisper==1.2.1", python_support)
        self.assertIn("--no-deps", python_support)
        self.assertIn("onnxruntime", python_support)
        self.assertIn("3.15", python_support)
        self.assertIn('RuntimeSchema = "5"', setup_script)
        self.assertIn("Python 3.15", readme)
        self.assertIn("ONNX Runtime-backed VAD dependency", readme)
        self.assertIn("Python 3.14.10 runtime", readme)


if __name__ == "__main__":
    unittest.main()

class SharedCreatorSettingsApiTests(unittest.TestCase):
    def test_api_config_returns_shared_defaults_not_last_creator_runtime_snapshot(self):
        import http.client
        import http.server
        import json
        import threading

        previous_runtime = autoclip.CORE.settings
        previous_defaults = autoclip.CORE.default_settings
        server = None
        worker = None
        try:
            runtime = {"layout": "Creator A layout", "output_format": "9:16", "min_score": 92}
            shared = {"layout": "Local default layout", "output_format": "16:9", "min_score": 75}
            autoclip.CORE.settings = runtime
            autoclip.CORE.default_settings = shared
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), autoclip.Handler)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
            connection.request("GET", "/api/config")
            response = connection.getresponse()
            payload = json.loads(response.read().decode("utf-8"))
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(payload["settings"], shared)
            self.assertNotEqual(payload["settings"], runtime)
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            if worker is not None:
                worker.join(timeout=2)
            autoclip.CORE.settings = previous_runtime
            autoclip.CORE.default_settings = previous_defaults
