import unittest
from unittest.mock import patch
from types import SimpleNamespace

import autoclip


class GpuFirstPolicyTests(unittest.TestCase):
    def test_cuda_is_selected_when_a_supported_nvidia_cuda_device_is_available(self):
        with patch.object(autoclip, "nvidia_gpu_present", return_value=True), \
             patch.object(autoclip, "cuda_device_count", return_value=1):
            self.assertEqual(autoclip.preferred_speech_device(), "cuda")

    def test_nvidia_gpu_without_working_cuda_never_silently_uses_cpu(self):
        with patch.object(autoclip, "nvidia_gpu_present", return_value=True), \
             patch.object(autoclip, "cuda_device_count", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "CPU fallback is disabled"):
                autoclip.preferred_speech_device()

    def test_cpu_is_selected_only_when_no_nvidia_gpu_is_present(self):
        with patch.object(autoclip, "nvidia_gpu_present", return_value=False), \
             patch.object(autoclip, "cuda_device_count", return_value=0):
            self.assertEqual(autoclip.preferred_speech_device(), "cpu")

    def test_nvenc_failure_on_a_detected_nvidia_gpu_is_an_error_not_cpu_fallback(self):
        old_nvenc = autoclip._nvenc
        autoclip._nvenc = None
        try:
            with patch.object(autoclip, "nvidia_gpu_present", return_value=True), \
                 patch.object(autoclip, "run", return_value=SimpleNamespace(returncode=1)):
                with self.assertRaisesRegex(RuntimeError, "CPU video encoding is disabled"):
                    autoclip.has_nvenc()
        finally:
            autoclip._nvenc = old_nvenc


if __name__ == "__main__":
    unittest.main()
