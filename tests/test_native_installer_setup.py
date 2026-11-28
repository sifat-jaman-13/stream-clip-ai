from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DesktopShellInstallerTests(unittest.TestCase):
    def test_installer_launches_the_pywebview_shell_after_engine_setup(self):
        installer = (ROOT / "installer" / "StreamSnipAI.iss").read_text(encoding="utf-8")
        self.assertIn("Exec(PowerShellPath, Parameters", installer)
        self.assertIn("ShowCommand, ewWaitUntilTerminated, ResultCode", installer)
        self.assertIn("if WizardSilent then", installer)
        self.assertIn("-NonInteractive", installer)
        self.assertIn("-DesktopShell", installer)
        self.assertIn("ResultCode <> 0", installer)
        self.assertIn('Filename: "{app}\\shell\\{#MyShellExe}"', installer)
        self.assertNotIn("StreamSnip.Desktop", installer)

    def test_setup_writes_shell_config_only_after_models_are_verified(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        shell = (ROOT / "desktop_shell.py").read_text(encoding="utf-8")
        self.assertIn("[switch]$DesktopShell", setup)
        self.assertNotIn("[switch]$NativeDesktop", setup)
        self.assertIn("desktop-shell.json", setup)
        self.assertIn("desktop-shell.json", shell)
        self.assertIn("source_root = $source", setup)
        self.assertIn("python_executable = $runtimePython", setup)
        self.assertIn("data_root = $dataRoot", setup)
        self.assertIn("ffmpeg_executable = $ffmpeg", setup)
        self.assertLess(
            setup.index("Ensure-SpeechModels $runtimePython $speechModelRoot"),
            setup.index("# The pywebview shell reads this config"),
        )

    def test_shell_starts_only_fastapi_and_hosts_the_react_dashboard(self):
        shell = (ROOT / "desktop_shell.py").read_text(encoding="utf-8")
        app = (ROOT / "autoclip.py").read_text(encoding="utf-8")
        api = (ROOT / "api_server.py").read_text(encoding="utf-8")
        self.assertIn('"autoclip.py"', shell)
        self.assertIn('self.base_url + "dashboard/"', shell)
        self.assertIn('gui="edgechromium"', shell)
        self.assertIn('private_mode=False', shell)
        self.assertIn('storage_path=str(LOCAL_ROOT / "WebView2")', shell)
        self.assertIn("create_app(", app)
        self.assertIn("uvicorn.Server", app)
        self.assertIn("class ServiceRequestAdapter", api)
        self.assertNotIn("http.server", app)
        self.assertNotIn("BaseHTTPRequestHandler", app)
        self.assertNotIn("HTML = r", app)

    def test_installer_bundles_the_single_engine_and_react_payload(self):
        installer = (ROOT / "installer" / "StreamSnipAI.iss").read_text(encoding="utf-8")
        for source in (
            'Source: "..\\autoclip.py"',
            'Source: "..\\api_server.py"',
            'Source: "..\\secret_store.py"',
            'Source: "..\\requirements.txt"',
            'Source: "setup_windows.ps1"',
            'Source: "python315_support.ps1"',
            'Source: "..\\dashboard\\dist\\*"',
            'Source: "..\\dist\\StreamSnipAI\\*"',
        ):
            self.assertIn(source, installer)
        self.assertIn('Filename: "{app}\\shell\\{#MyShellExe}"', installer)
        self.assertIn('Name: "{app}\\desktop"', installer)

    def test_installer_includes_existing_product_screenshots(self):
        installer = (ROOT / "installer" / "StreamSnipAI.iss").read_text(encoding="utf-8")
        self.assertIn('Source: "..\\docs\\assets\\product\\*.png"', installer)
        for image in ("dashboard.png", "live-studio.png", "creator-monitoring.png", "clip-library.png", "publishing.png"):
            self.assertTrue((ROOT / "docs" / "assets" / "product" / image).is_file(), image)

    def test_engine_setup_repairs_dependencies_and_verifies_whisper_models(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("Install-StreamSnipDependencies $runtimePython $requirements $python.Version", setup)
        self.assertIn("Test-StreamSnipDependencyConsistency $runtimePython $python.Version", setup)
        self.assertIn("Ensure-SpeechModels $runtimePython $speechModelRoot", setup)
        self.assertIn('$speechModelRoot = if ($DesktopShell)', setup)
        self.assertIn('Join-Path $logRoot "Library\\models"', setup)
        self.assertIn("is_valid_model(destination)", setup)
        self.assertIn("ctranslate2.get_cuda_device_count()", setup)
        self.assertIn("CUDA runtime is ready for Whisper inference.", setup)
        self.assertIn("An NVIDIA GPU is installed, but CTranslate2 cannot initialize CUDA.", setup)
        self.assertIn("nvidia-cublas-cu12", requirements)
        self.assertIn("nvidia-cuda-runtime-cu12", requirements)
        self.assertIn("function Test-CudaWheelFiles", setup)
        self.assertIn("function Repair-CudaWheelDependencies", setup)
        self.assertIn("WHISPER_RUNTIME_SMOKE_PASS", setup)
        self.assertIn("ENGINE_TRANSCRIPTION_SMOKE_PASS", setup)
        self.assertIn("CAPTURE_RUNTIME_SMOKE_PASS", setup)
        self.assertIn("RENDER_RUNTIME_SMOKE_PASS", setup)

    def test_user_python_and_ffmpeg_are_never_claimed_or_removed_without_ownership(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        cleanup = (ROOT / "installer" / "uninstall_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("sys.version_info[:2] >= (3,10)", setup)
        self.assertIn("sys.version_info.releaselevel == 'final'", setup)
        self.assertIn("Sort-Object", setup)
        self.assertNotIn('Mark-DependencyInstalled "python"', setup)
        self.assertIn('Mark-DependencyInstalled "ffmpeg"', setup)
        self.assertIn('if ($null -eq $ownership)', cleanup)
        self.assertIn("shared global Python/FFmpeg packages were left untouched", cleanup)
        self.assertIn("python_installed_by_streamsnip", cleanup)
        self.assertIn("ffmpeg_installed_by_streamsnip", cleanup)

    def test_uninstaller_defaults_to_keep_config_and_continues_after_cleanup_failure(self):
        installer = (ROOT / "installer" / "StreamSnipAI.iss").read_text(encoding="utf-8")
        cleanup = (ROOT / "installer" / "uninstall_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("function InitializeUninstall(): Boolean;", installer)
        self.assertIn("Keep settings and configuration", installer)
        self.assertIn("MB_DEFBUTTON1", installer)
        self.assertIn("IDYES", installer)
        self.assertIn("IDNO", installer)
        self.assertIn("usUninstall", installer)
        self.assertIn("-KeepConfig", installer)
        self.assertIn("-RemoveAllData", installer)
        self.assertIn("Configuration backup retained for retry", cleanup)
        self.assertIn("Remove-PathSafely $localRoot", cleanup)
        self.assertIn("desktop-shell.json", installer)

    def test_repair_preserves_model_cache_and_shared_library_paths(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        shell = (ROOT / "desktop_shell.py").read_text(encoding="utf-8")
        self.assertIn('Join-Path $logRoot "Library\\models"', setup)
        self.assertIn('Path(os.environ.get("LOCALAPPDATA"', shell)
        self.assertIn('LOCAL_ROOT / "Library"', shell)
        self.assertIn("data_root", shell)
        self.assertIn("STREAMSNIP_DATA_DIR", shell)

    def test_mobile_menu_escape_restores_focus_to_its_toggle(self):
        script = (ROOT / "docs" / "assets" / "site.js").read_text(encoding="utf-8")
        self.assertIn('if (event.key === "Escape" && !menu.hidden)', script)
        self.assertIn("closeMenu();" + chr(10) + "        menuToggle.focus();", script)


if __name__ == "__main__":
    unittest.main()
