from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class NativeInstallerSetupTests(unittest.TestCase):
    def test_native_installer_runs_setup_in_one_visible_console(self):
        installer = (ROOT / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8")
        self.assertIn("Exec(PowerShellPath, Parameters", installer)
        self.assertIn("ShowCommand, ewWaitUntilTerminated, ResultCode", installer)
        self.assertIn("if WizardSilent then", installer)
        self.assertIn("-NonInteractive", installer)
        self.assertIn("ResultCode <> 0", installer)
        self.assertNotIn("setup_native_windows.ps1", installer)
        self.assertEqual(installer.count("ShowCommand, ewWaitUntilTerminated, ResultCode"), 1)

    def test_silent_engine_setup_skips_optional_hugging_face_prompt(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$NonInteractive", setup)
        self.assertIn("if ($NonInteractive)", setup)
        self.assertIn("Skipping the optional Hugging Face token prompt", setup)

    def test_engine_setup_serializes_install_and_repair_runs(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        self.assertIn('New-Object System.Threading.Mutex($false, "Local\\StreamSnipAI.Setup")', setup)
        self.assertIn("$setupMutex.WaitOne(0)", setup)
        self.assertIn("$setupMutex.ReleaseMutex()", setup)

    def test_installed_engine_config_has_priority_over_package_local_state(self):
        supervisor = (ROOT / "desktop" / "StreamSnip.Desktop" / "EngineSupervisor.cs").read_text(encoding="utf-8")
        self.assertIn('Path.Combine(localAppData, "StreamSnip AI", "native-engine.json")', supervisor)
        self.assertIn('configPaths.Add(Path.Combine(packageLocalState, "native-engine.json"))', supervisor)
        self.assertNotIn('configPaths.Insert(0, Path.Combine(packageLocalState', supervisor)

    def test_native_engine_configuration_is_written_after_model_verification(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$NativeDesktop", setup)
        self.assertIn("if ($NativeDesktop)", setup)
        self.assertIn("native-engine.json", setup)
        self.assertLess(
            setup.index("Ensure-SpeechModels $runtimePython $speechModelRoot"),
            setup.index("# The native host reads this config"),
        )

    def test_setup_repairs_missing_dependencies_and_checks_whisper_models(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("Install-StreamSnipDependencies $runtimePython $requirements $python.Version", setup)
        self.assertIn("Test-StreamSnipDependencyConsistency $runtimePython $python.Version", setup)
        self.assertIn("Ensure-SpeechModels $runtimePython $speechModelRoot", setup)
        self.assertIn('$speechModelRoot = if ($NativeDesktop)', setup)
        self.assertIn('Join-Path $logRoot "Library\\models"', setup)
        self.assertIn("Move-Item -LiteralPath $legacyModelPath -Destination $modelDestination", setup)
        self.assertIn("model_file.is_file()", setup)
        self.assertIn("is_valid_model(destination)", setup)
        self.assertIn('folder / "tokenizer.json"', setup)
        self.assertIn("ctranslate2.get_cuda_device_count()", setup)
        self.assertIn("CUDA runtime is ready for Whisper inference.", setup)
        self.assertIn("An NVIDIA GPU is installed, but CTranslate2 cannot initialize CUDA.", setup)
        self.assertIn("nvidia-cublas-cu12", requirements)
        self.assertIn("nvidia-cuda-runtime-cu12", requirements)
        self.assertIn("nvidia-cudnn-cu12>=9,<10", requirements)
        self.assertIn("function Test-CudaWheelFiles", setup)
        self.assertIn('package_root / "bin" / name).is_file()', setup)
        self.assertIn("$probeOutput | ForEach-Object { Write-Host $_ }", setup)
        self.assertIn("function Repair-CudaWheelDependencies", setup)
        self.assertIn("--force-reinstall", setup)
        self.assertIn("WHISPER_RUNTIME_SMOKE_PASS", setup)
        self.assertIn("ENGINE_TRANSCRIPTION_SMOKE_PASS", setup)
        self.assertIn("CAPTURE_RUNTIME_SMOKE_PASS", setup)
        self.assertIn("RENDER_RUNTIME_SMOKE_PASS", setup)
        self.assertIn("FFmpeg decode/encode smoke test passed.", setup)

    def test_native_installer_bundles_engine_files_for_repair(self):
        installer = (ROOT / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8")
        for source in (
            'Source: "..\\autoclip.py"',
            'Source: "..\\secret_store.py"',
            'Source: "..\\requirements.txt"',
            'Source: "setup_windows.ps1"',
            'Source: "python315_support.ps1"',
            'Source: "..\\dashboard\\dist\\*"',
        ):
            self.assertIn(source, installer)

    def test_native_installer_bundles_readme_screenshots(self):
        installer = (ROOT / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8")
        self.assertIn('Source: "..\\docs\\assets\\product\\*.png"', installer)
        self.assertIn('DestDir: "{app}\\docs\\assets\\product"', installer)
        for image in ("dashboard.png", "live-studio.png", "creator-monitoring.png", "clip-library.png", "publishing.png"):
            self.assertTrue((ROOT / "docs" / "assets" / "product" / image).is_file(), image)

    def test_native_installer_persists_the_verified_ffmpeg_executable(self):
        setup = (ROOT / "installer" / "setup_windows.ps1").read_text(encoding="utf-8")
        supervisor = (ROOT / "desktop" / "StreamSnip.Desktop" / "EngineSupervisor.cs").read_text(encoding="utf-8")
        engine = (ROOT / "autoclip.py").read_text(encoding="utf-8")
        self.assertIn("ffmpeg_executable = $ffmpeg", setup)
        self.assertIn('config?["ffmpeg_executable"]?.GetValue<string>()', supervisor)
        self.assertIn('start.Environment["STREAMSNIP_FFMPEG_PATH"] = ffmpegPath', supervisor)
        self.assertIn('os.environ.get("STREAMSNIP_FFMPEG_PATH", "")', engine)

    def test_live_studio_offers_terminal_runtime_repair(self):
        live = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.Live.cs").read_text(encoding="utf-8")
        self.assertIn('CreateButton("Repair runtime"', live)
        self.assertIn("-NativeDesktop -NonInteractive -SkipLaunch -NoPause", live)

    def test_dashboard_session_details_are_present_and_updated_during_polling(self):
        dashboard = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.Dashboard.cs").read_text(encoding="utf-8")
        self.assertIn("_dashboardClipDetail", dashboard)
        self.assertIn("_dashboardChunkDetail", dashboard)
        self.assertIn("_dashboardProgressStatus", dashboard)
        self.assertIn("_dashboardProgressPercent", dashboard)
        self.assertIn("Visibility = state.Running ? Visibility.Visible : Visibility.Collapsed", dashboard)
        self.assertIn("_dashboardProgressRow.Visibility = _state.Running ? Visibility.Visible : Visibility.Collapsed", dashboard)
        self.assertIn("_dashboardProgress.Value = Math.Clamp(_state.Progress, 0, 100)", dashboard)
        self.assertIn("_dashboardClipDetail.Text = $\"Clips", dashboard)
        self.assertIn("_dashboardChunkDetail.Text = $\"Chunks", dashboard)

    def test_engine_recovery_notice_survives_page_renders(self):
        page = (ROOT / "desktop" / "StreamSnip.Desktop" / "MainPage.xaml.cs").read_text(encoding="utf-8")
        render = page[page.index("private void RenderCurrentPage()") : page.index("private async Task CopyDiagnosticTextAsync")]
        self.assertIn("RestoreEngineNotice();", render)
        self.assertIn("if (_engineNotice is null)", render)
        self.assertIn("PageHost.Children.Insert(0, _engineNotice)", render)

    def test_uninstaller_is_retry_safe_and_never_deletes_programs_parent(self):
        cleanup = (ROOT / "installer" / "uninstall_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("$localRoot = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA \"StreamSnip AI\" } else { $null }", cleanup)
        self.assertNotIn("else { Split-Path -Parent $AppDir }", cleanup)
        self.assertIn("StreamSnipAI-config-$backupKey", cleanup)
        self.assertIn("if (-not (Test-Path -LiteralPath $backupPath -PathType Leaf))", cleanup)
        self.assertLess(cleanup.index("Invoke-OwnedDependencyCleanup"), cleanup.index('Remove-PathSafely $localRoot'))
        self.assertIn("Save-DependencyOwnership", cleanup)
        self.assertIn("$ownership.python_installed_by_streamsnip = $false", cleanup)
        self.assertIn("$ownership.ffmpeg_installed_by_streamsnip = $false", cleanup)
        self.assertIn("Configuration backup retained for retry", cleanup)

    def test_mobile_menu_escape_restores_focus_to_its_toggle(self):
        script = (ROOT / "docs" / "assets" / "site.js").read_text(encoding="utf-8")
        self.assertIn('if (event.key === "Escape" && !menu.hidden)', script)
        self.assertIn("closeMenu();\n        menuToggle.focus();", script)

    def test_uninstaller_prompts_keep_config_or_remove_all_data(self):
        installer = (ROOT / "installer" / "StreamSnipNative.iss").read_text(encoding="utf-8")
        self.assertIn("function InitializeUninstall(): Boolean;", installer)
        self.assertIn("Keep only settings and configuration", installer)
        self.assertIn("Remove all app data, clips, recordings, models, runtime and configuration", installer)
        self.assertIn("IDYES", installer)
        self.assertIn("IDNO", installer)
        self.assertIn("usUninstall", installer)
        self.assertIn("-KeepConfig", installer)
        self.assertIn("-RemoveAllData", installer)

    def test_uninstaller_removes_all_app_data_and_only_whitelisted_config_can_survive(self):
        cleanup = (ROOT / "installer" / "uninstall_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("[switch]$KeepConfig", cleanup)
        self.assertIn("[switch]$RemoveAllData", cleanup)
        self.assertIn("desktop-preferences.json", cleanup)
        self.assertIn("settings.json", cleanup)
        self.assertIn("ai_settings.json", cleanup)
        self.assertIn("custom_words.txt", cleanup)
        self.assertIn("Remove-Item -LiteralPath $Path -Recurse -Force -ErrorAction Stop", cleanup)
        self.assertIn("Remove-PathSafely $localRoot", cleanup)
        self.assertIn("native-engine.json", cleanup)
        self.assertIn("streamsnip.db", cleanup)
        self.assertIn("Could not uninstall the Python package installed by StreamSnip AI", cleanup)
        self.assertIn("WinGet is unavailable, so StreamSnip AI cannot remove its app-owned global dependencies", cleanup)


if __name__ == "__main__":
    unittest.main()
