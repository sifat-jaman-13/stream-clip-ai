from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import autoclip
import post_metadata


class FramingAndMetadataTests(unittest.TestCase):
    def test_new_default_viral_score_floor_is_80(self):
        self.assertEqual(autoclip.clean_cfg({})["min_score"], 80)

    def test_game_capture_region_is_clamped_inside_source(self):
        cfg = autoclip.clean_cfg({
            "game_area_x": 80, "game_area_y": 75,
            "game_area_w": 50, "game_area_h": 50,
        })
        self.assertEqual(cfg["game_area_x"], 80)
        self.assertEqual(cfg["game_area_y"], 75)
        self.assertEqual(cfg["game_area_w"], 20)
        self.assertEqual(cfg["game_area_h"], 25)

    def test_game_capture_filter_uses_saved_rectangle(self):
        cfg = autoclip.clean_cfg({
            "game_area_x": 20, "game_area_y": 10,
            "game_area_w": 60, "game_area_h": 80,
        })
        filt = autoclip.facecam_game_crop_filter(cfg)
        self.assertIn("crop=iw*0.6000:ih*0.8000:iw*0.2000:ih*0.1000", filt)
        self.assertIn("scale=1080:1152", filt)

    def test_caption_positions_have_five_presets_and_render_top_aligned(self):
        self.assertEqual(set(autoclip.CAPTION_POS), {"Top", "Upper third", "Middle", "Lower third", "Bottom"})
        cfg = autoclip.clean_cfg({"position": "Upper third", "subtitle_custom": False})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "captions.ass"
            autoclip.make_ass([(0.0, 1.0, "hello")], 0, 2, path, cfg)
            style = next(line for line in path.read_text(encoding="utf-8").splitlines()
                         if line.startswith("Style: Default,"))
        self.assertRegex(style, r",8,70,70,\d+,1$")
        middle_cfg = autoclip.clean_cfg({"position": "Middle"})
        with tempfile.TemporaryDirectory() as folder:
            middle_path = Path(folder) / "middle.ass"
            autoclip.make_ass([(0.0, 1.0, "center")], 0, 2, middle_path, middle_cfg)
            middle_style = next(line for line in middle_path.read_text(encoding="utf-8").splitlines()
                                if line.startswith("Style: Default,"))
        self.assertRegex(middle_style, r",5,70,70,0,1$")

    def test_clip_metadata_recovers_empty_sql_description_from_sidecar(self):
        import sqlite3
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            out = root / "out"
            out.mkdir()
            clip = out / "creator_clip.mp4"
            clip.write_bytes(b"not-a-real-video")
            sidecar = clip.with_suffix(".txt")
            sidecar.write_text(
                "A Title That Was Previously Saved\n\n"
                "A full description restored from the existing sidecar. #shorts",
                encoding="utf-8",
            )
            database = root / "streamsnip.db"
            with patch.multiple(
                autoclip,
                _data_root=root,
                DATABASE_FILE=database,
                OUT=out,
            ):
                with autoclip._database_connection() as db:
                    db.execute(
                        """INSERT INTO clip_metadata(
                               clip_path,clip_name,title,description,caption,updated_at
                           ) VALUES(?,?,?,?,?,?)""",
                        (str(clip.resolve()), clip.name, "A Title That Was Previously Saved",
                         "", "", 1.0),
                    )
                metadata = autoclip.get_clip_metadata(clip)
                self.assertEqual(metadata["title"], "A Title That Was Previously Saved")
                self.assertIn("full description restored", metadata["description"])
                with autoclip._database_connection() as db:
                    row = db.execute(
                        "SELECT description FROM clip_metadata WHERE clip_path=?",
                        (str(clip.resolve()),),
                    ).fetchone()
                self.assertIn("full description restored", row["description"])

    def test_hook_provider_uses_matched_hook_phrase_as_title(self):
        result = post_metadata.build_hook_word_copy(
            "That was unbelievable, no way bro, I cannot believe it happened.",
            hook_terms=["no way bro", "unbelievable"],
        )
        self.assertEqual(result["title"], "No Way Bro")
        self.assertTrue(result["description"])
        self.assertEqual(result["provider"], "built-in hook words")

    def test_local_virality_scorer_selects_engaging_audio_and_respects_threshold(self):
        import threading
        from unittest.mock import patch
        import numpy as np

        # Broad energy lift plus a few speech events produces a deterministic
        # local score above 80 but below 98.
        rms = np.full(120, 0.01, dtype=float)
        rms[40:80] = 0.015
        words = [
            (40 + index * 8, 40 + index * 8 + 0.2, "hello")
            for index in range(5)
        ]
        engine = object.__new__(autoclip.Engine)
        engine.cfg = autoclip.clean_cfg({
            "chunk_min": 10, "clips_per_chunk": 2, "min_score": 80,
        })
        engine.ai_cfg_for_render = {"provider": "hooks"}
        engine.ai_cancel = threading.Event()
        engine.seg_seconds = 600
        engine.log = lambda _message: None
        engine.status = lambda *_args: None
        engine.rms_per_second = lambda _path: rms

        with patch.object(autoclip, "load_custom", return_value={}):
            picks, duration = engine.find_peaks("synthetic-source.wav", words)
            self.assertEqual(duration, 120)
            self.assertTrue(picks)
            self.assertGreaterEqual(picks[0][1], 80)
            self.assertLess(picks[0][1], 98)
            engine.cfg["min_score"] = 98
            rejected, _ = engine.find_peaks("synthetic-source.wav", words)

        self.assertEqual(rejected, [])
        self.assertGreaterEqual(engine.best_score, 80)
        self.assertLess(engine.best_score, 98)

    def test_ai_virality_scores_are_floored_and_empty_ai_result_does_not_fallback(self):
        import threading
        from unittest.mock import patch
        import numpy as np

        rms = np.full(120, 0.03, dtype=float)
        engine = object.__new__(autoclip.Engine)
        engine.cfg = autoclip.clean_cfg({
            "chunk_min": 10, "clips_per_chunk": 2, "min_score": 90,
        })
        engine.ai_cfg_for_render = {"provider": "gemini", "ai_window_minutes": 10}
        engine.ai_cancel = threading.Event()
        engine.seg_seconds = 600
        engine.log = lambda _message: None
        engine.status = lambda *_args: None
        engine.rms_per_second = lambda _path: rms
        words = [(second, second + 0.2, "ordinary") for second in range(10, 110, 10)]

        with patch.object(autoclip, "load_custom", return_value={}):
            with patch.object(autoclip, "select_moments", return_value=[(60, 88.0)]):
                below_floor, _ = engine.find_peaks("synthetic-source.wav", words)
        self.assertEqual(below_floor, [])
        self.assertTrue(engine.ai_strict_no_clip)
        self.assertEqual(engine.best_score, 88.0)

        with patch.object(autoclip, "load_custom", return_value={}):
            with patch.object(autoclip, "select_moments", return_value=[]):
                no_ai_choice, _ = engine.find_peaks("synthetic-source.wav", words)
        self.assertEqual(no_ai_choice, [])
        self.assertTrue(engine.ai_strict_no_clip)

    def test_output_preview_uses_same_layout_filter_as_clip_renderer(self):
        cfg = autoclip.clean_cfg({
            "layout": "Facecam + game (Twitch)", "output_format": "9:16",
            "cam_x": 12, "cam_y": 8, "cam_w": 30, "cam_h": 35,
            "game_area_x": 18, "game_area_y": 5, "game_area_w": 64, "game_area_h": 90,
        })
        video_filter = autoclip.render_video_filter(cfg, "preview.ass")
        self.assertIn("crop=iw*0.3000:ih*0.3500:iw*0.1200:ih*0.0800", video_filter)
        self.assertIn("crop=iw*0.6400:ih*0.9000:iw*0.1800:ih*0.0500", video_filter)
        self.assertIn("vstack=inputs=2", video_filter)
        self.assertIn("subtitles=preview.ass", video_filter)

    def test_output_preview_respects_selected_crop_and_output_dimensions(self):
        cfg = autoclip.clean_cfg({
            "layout": "Selected crop", "output_format": "4:5",
            "crop_x": 10, "crop_y": 5, "crop_w": 70, "crop_h": 85,
        })
        video_filter = autoclip.render_video_filter(cfg, "preview.ass")
        self.assertIn("crop=iw*0.7000:ih*0.8500:iw*0.1000:ih*0.0500", video_filter)
        self.assertIn("scale=1080:1350:force_original_aspect_ratio=increase", video_filter)
        self.assertIn("subtitles=preview.ass", video_filter)


if __name__ == "__main__":
    unittest.main()
