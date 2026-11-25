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

    def test_hook_provider_uses_matched_hook_phrase_as_title(self):
        result = post_metadata.build_hook_word_copy(
            "That was unbelievable, no way bro, I cannot believe it happened.",
            hook_terms=["no way bro", "unbelievable"],
        )
        self.assertEqual(result["title"], "No Way Bro")
        self.assertTrue(result["description"])
        self.assertEqual(result["provider"], "built-in hook words")

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
