from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_single_react_frontend_and_pywebview_host_are_the_packaged_ui():
    app = (ROOT / "dashboard" / "src" / "App.tsx").read_text(encoding="utf-8")
    shell = (ROOT / "desktop_shell.py").read_text(encoding="utf-8")
    installer = (ROOT / "installer" / "StreamSnipAI.iss").read_text(encoding="utf-8")
    assert 'self.base_url + "dashboard/"' in shell
    assert 'gui="edgechromium"' in shell
    assert r'Source: "..\dashboard\dist\*"' in installer
    assert r'Source: "..\dist\StreamSnipAI\*"' in installer
    assert "StreamSnip.Desktop" not in installer
    assert "odysseus-dark" in app
    assert 'label: "Bundled fonts"' in app


def test_fastapi_is_the_only_local_http_server_and_the_embedded_html_is_gone():
    app = (ROOT / "autoclip.py").read_text(encoding="utf-8")
    api = (ROOT / "api_server.py").read_text(encoding="utf-8")
    assert "uvicorn.Server" in app
    assert "create_app(" in app
    assert "http.server" not in app
    assert "BaseHTTPRequestHandler" not in app
    assert "HTML = r" not in app
    assert "class ServiceRequestAdapter" in api
    assert "FastAPI(" in api


def test_no_secondary_compiled_desktop_shell_or_facecam_sidecar_remains():
    assert not (ROOT / "desktop").exists()
    assert not (ROOT / "tools" / "FacecamInference").exists()
    build = (ROOT / "build_installer.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "build-installer.yml").read_text(encoding="utf-8")
    assert "PyInstaller" in build
    assert "dotnet publish" not in build
    assert "setup-dotnet" not in workflow

def test_fastapi_backend_script_invokes_its_main_entry_point():
    app = (ROOT / "autoclip.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in app
    assert "\n    main()" in app
