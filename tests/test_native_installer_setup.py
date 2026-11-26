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
        self.assertEqual(installer.count("Exec(PowerShellPath"), 1)

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
            setup.index("if ($NativeDesktop)"),
        )


if __name__ == "__main__":
    unittest.main()
