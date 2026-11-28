from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import autoclip
import facecam_detect


class FacecamDetectionTests(unittest.TestCase):
    def test_yunet_model_is_packaged_and_loadable(self):
        self.assertTrue(facecam_detect.MODEL.is_file())
        self.assertTrue(hasattr(facecam_detect.cv2, "FaceDetectorYN"))
        detector = facecam_detect.Faces()
        self.assertIsNotNone(detector.det)

    def test_media_tools_reuse_the_app_selected_ffmpeg_distribution(self):
        executable = ".exe" if os.name == "nt" else ""
        with tempfile.TemporaryDirectory() as folder:
            ffmpeg = Path(folder) / f"ffmpeg{executable}"
            ffprobe = Path(folder) / f"ffprobe{executable}"
            ffmpeg.touch()
            ffprobe.touch()
            app = SimpleNamespace(ffmpeg_exe=lambda: str(ffmpeg))
            with patch.dict(sys.modules, {"autoclip": app}):
                self.assertTrue(Path(facecam_detect._media_tool("ffmpeg")).samefile(ffmpeg))
                self.assertTrue(Path(facecam_detect._media_tool("ffprobe")).samefile(ffprobe))

    def test_static_avatar_is_not_considered_live_camera(self):
        self.assertFalse(facecam_detect.is_live(0.10))
        self.assertTrue(facecam_detect.is_live(0.50))

    def test_iou_for_overlapping_and_separate_regions(self):
        self.assertGreater(facecam_detect._iou((0, 0, 20, 20), (10, 10, 20, 20)), 0)
        self.assertEqual(facecam_detect._iou((0, 0, 10, 10), (20, 20, 10, 10)), 0)

    def test_file_detection_delegates_to_multiframe_detector(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4") as video:
            expected = {"found": False, "confidence": 0.0}
            with patch("facecam_detect.detect", return_value=expected) as detect:
                self.assertEqual(autoclip.detect_facecam("file", video.name), expected)
                detect.assert_called_once_with(Path(video.name))

    def test_file_detection_rejects_missing_source(self):
        with self.assertRaisesRegex(ValueError, "existing video file"):
            autoclip.detect_facecam("file", "missing-facecam-test.mp4")

    def test_live_detection_samples_stream_then_runs_detector(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if "--stream-url" in command:
                return subprocess.CompletedProcess(command, 0, stdout="https://example.invalid/live\n", stderr="")
            Path(command[-1]).write_bytes(b"sample-video" * 10000)
            return subprocess.CompletedProcess(command, 0, stdout=b"", stderr=b"")

        expected = {"found": True, "method": "border+face", "confidence": 0.9,
                    "cam": {"x": 0.2, "y": 0.1, "w": 0.3, "h": 0.4}}
        with (patch.object(autoclip, "streamlink_available", return_value=True),
              patch.object(autoclip, "streamlink_cmd", return_value=["streamlink"]),
              patch.object(autoclip, "streamlink_env", return_value={}),
              patch.object(autoclip, "ffmpeg_exe", return_value="ffmpeg"),
              patch.object(autoclip, "ffmpeg_cuda_decode_args", return_value=[]),
              patch.object(autoclip, "has_nvenc", return_value=False),
              patch.object(autoclip, "run", side_effect=fake_run),
              patch("facecam_detect.detect", return_value=expected) as detect):
            result = autoclip.detect_facecam("live", "https://www.twitch.tv/testchannel")
        self.assertEqual(result, expected)
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][calls[1].index("-t") + 1], "22")
        detect.assert_called_once()



    def test_facecam_detection_uses_opencv_yunet_without_a_compiled_sidecar(self):
        frames = [
            facecam_detect.np.zeros((facecam_detect.BH, facecam_detect.BW, 3), dtype=facecam_detect.np.uint8),
            facecam_detect.np.zeros((facecam_detect.BH, facecam_detect.BW, 3), dtype=facecam_detect.np.uint8),
        ]
        with (
            patch.object(facecam_detect, "candidates", return_value=([], 0.0)),
            patch.object(facecam_detect, "borderless_face", return_value=None),
        ):
            result = facecam_detect.detect_from_frames(frames)
        self.assertFalse(result["found"])
        self.assertEqual(result["inference_device"], "CPU (OpenCV YuNet)")
        self.assertNotIn("DirectML", str(result))


if __name__ == "__main__":
    unittest.main()
