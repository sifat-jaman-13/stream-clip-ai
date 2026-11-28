r"""StreamSnip AI  -  a local-first Twitch, YouTube, and VOD clipper.

The default workflow uses Streamlink, FFmpeg, faster-whisper, and hook-word
scoring locally without requiring a cloud AI key. Ollama provides optional
local AI analysis. Gemini and Hugging Face are optional hosted transcript
analysis providers, and Zernio is the optional publishing integration.

Windows/source setup:
    winget install Gyan.FFmpeg
    py -3 -m venv .venv ; .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

Run:
    python autoclip.py                 -> starts the local FastAPI development server
    python autoclip.py live URL        -> headless live-stream mode
    python autoclip.py file video.mp4  -> headless local-file mode

Each finished clip is written as an MP4 plus a matching TXT caption/hashtag
file. Runtime paths, providers, captions, layouts, and custom hook words are
configurable from the local UI.
"""
import os, re, sys, glob, json, time, queue, shutil, secrets, threading, subprocess, pathlib, platform, base64, uuid, shlex, tempfile, hashlib
import math
import sqlite3
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import mimetypes
import urllib.request
from importlib import metadata as importlib_metadata
import urllib.parse, webbrowser
import numpy as np
from ai_highlights import (AIAnalysisCancelled, AIProviderError, DEFAULT_GEMINI_MODEL,
                           DEFAULT_HUGGINGFACE_MODEL, RETIRED_GEMINI_MODELS,
                           ollama_models, select_moments, test_provider)
from post_metadata import (DEFAULT_GEMINI_COPY_MODEL, build_hook_word_copy,
                            build_transcript_fallback, generate_social_copy)
from secret_store import ClosingSQLiteConnection, CredentialStore
APP_VERSION = "4.1.0"
MAX_ACTIVE_CREATOR_MONITORS = 10
PRODUCT_NAME = "StreamSnip AI"
APP_RELEASES_URL = "https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest"
try:
    from zernio_poster import ZernioPublisher
    from zernio_connections import (
        ZernioMultiPublisher, SUPPORTED_ZERNIO_PLATFORMS,
        apply_account_slots, connection_identity_status,
        is_zernio_rate_limit, is_zernio_workspace_rate_limit, zernio_rate_limit_until,
    )
    ZERNIO_AVAILABLE = True
except Exception:
    ZernioPublisher = None
    ZernioMultiPublisher = None
    SUPPORTED_ZERNIO_PLATFORMS = {"facebook", "instagram", "youtube"}
    def is_zernio_workspace_rate_limit(error):
        return False
    def apply_account_slots(accounts, previous_accounts=None):
        return []
    def connection_identity_status(connections):
        return {str(item.get("id") or ""): {
            "identity_verified": bool(item.get("identity_user_id")),
            "identity_shared": False,
        } for item in (connections or []) if isinstance(item, dict)}
    def zernio_rate_limit_until(error, now=None):
        return None
    def is_zernio_rate_limit(error):
        return False
    ZERNIO_AVAILABLE = False

# ------------------------------------------------------------------ setup
def _add_cuda_dlls():
    """Expose CUDA 12 cuBLAS, runtime, cuDNN and NVRTC wheel DLLs on Windows."""
    if os.name != "nt":
        return
    roots = [pathlib.Path(p) for p in sys.path if p]
    for p in (getattr(sys, "_MEIPASS", ""), pathlib.Path(__file__).resolve().parent,
              pathlib.Path(__file__).resolve().parent / "_internal"):
        if p:
            roots.append(pathlib.Path(p))
    seen = set()
    path_entries = [entry for entry in os.environ.get("PATH", "").split(os.pathsep) if entry]
    for base in roots:
        for package in ("cublas", "cuda_runtime", "cudnn", "cuda_nvrtc"):
            d = base / "nvidia" / package / "bin"
            key = str(d).lower()
            if key in seen:
                continue
            seen.add(key)
            if d.is_dir():
                try:
                    os.add_dll_directory(str(d))
                except OSError:
                    pass
                if not any(entry.lower() == key for entry in path_entries):
                    path_entries.insert(0, str(d))
    if path_entries:
        os.environ["PATH"] = os.pathsep.join(path_entries)
_add_cuda_dlls()

def _patch_pyav():
    """PyAV 14+ removed metadata_errors parameter from av.open().
    faster-whisper still calls av.open(..., metadata_errors='ignore').
    This patch intercepts av.open to strip metadata_errors if present."""
    try:
        import av
        _orig_open = av.open
        def _compat_open(*args, **kwargs):
            kwargs.pop("metadata_errors", None)
            return _orig_open(*args, **kwargs)
        av.open = _compat_open
    except Exception:
        pass
_patch_pyav()

HERE = (pathlib.Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else pathlib.Path(__file__).resolve().parent)

def asset_file(name):
    """Find a known UI asset in source, installed, or frozen layouts."""
    if name not in {"app-icon.png", "brand-logo.png"}:
        return None
    roots = [HERE, HERE.parent, pathlib.Path(sys.executable).resolve().parent]
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        roots.insert(0, pathlib.Path(bundle_root))
    seen = set()
    for root in roots:
        candidate = (root / "assets" / name).resolve()
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        if candidate.is_file():
            return candidate
    return None

_in_site_packages = any(part.lower() in {"site-packages", "dist-packages"} for part in HERE.parts)
_data_override = os.environ.get("STREAMSNIP_DATA_DIR")
_data_root = (pathlib.Path(_data_override).expanduser() if _data_override else
              pathlib.Path(os.environ.get("LOCALAPPDATA") or pathlib.Path.home()) / "StreamSnip AI"
              if _in_site_packages else HERE)
OUT = _data_root / "out"
REC = _data_root / "rec"
WHISPER_MODELS = _data_root / "models"
RUNTIME_LOG = _data_root / "streamsnip.log"

def ensure_runtime_dirs():
    """Recreate runtime folders if the user, cleanup software, or an installer removed them."""
    OUT.mkdir(parents=True, exist_ok=True)
    REC.mkdir(parents=True, exist_ok=True)
    WHISPER_MODELS.mkdir(parents=True, exist_ok=True)


_RUNTIME_LOG_SECRET_VALUES = set()
_RUNTIME_LOG_SECRET_LOCK = threading.RLock()
_RUNTIME_LOG_SECRET_ASSIGNMENT = re.compile(
    r"""(?i)(\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|secret|token)\b\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;&]+)"""
)
_RUNTIME_LOG_AUTH_HEADER = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
_RUNTIME_LOG_QUERY_SECRET = re.compile(
    r"(?i)([?&](?:key|api_key|access_token|refresh_token|token|signature)=)[^&#\s]+"
)
_RUNTIME_LOG_TOKEN_SHAPE = re.compile(
    r"(?<![A-Za-z0-9])(?:AIza[0-9A-Za-z_-]{35}|gh[pousr]_[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|sk-(?:proj-)?[A-Za-z0-9_-]{24,}|"
    r"hf_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9-]{10,})(?![A-Za-z0-9])"
)


def _register_runtime_log_secret(value):
    secret = str(value or "").strip()
    if len(secret) >= 6:
        with _RUNTIME_LOG_SECRET_LOCK:
            _RUNTIME_LOG_SECRET_VALUES.add(secret)


def _redact_runtime_log_message(message):
    text = str(message)
    with _RUNTIME_LOG_SECRET_LOCK:
        known_secrets = sorted(_RUNTIME_LOG_SECRET_VALUES, key=len, reverse=True)
    for secret in known_secrets:
        text = text.replace(secret, "[REDACTED]")
    text = _RUNTIME_LOG_SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", text)
    text = _RUNTIME_LOG_AUTH_HEADER.sub(r"\1 [REDACTED]", text)
    text = _RUNTIME_LOG_QUERY_SECRET.sub(r"\1[REDACTED]", text)
    text = _RUNTIME_LOG_TOKEN_SHAPE.sub("[REDACTED]", text)
    return text


def append_runtime_log(timestamp, message):
    """Persist event timestamps only; detailed messages stay in the in-memory UI log."""
    try:
        with RUNTIME_LOG.open("a", encoding="utf-8") as handle:
            # Never persist caller-provided text: it may contain URLs, credentials, or provider errors.
            handle.write(f"{timestamp} [diagnostic event]\n")
    except OSError:
        pass

ensure_runtime_dirs()

def cuda_device_count():
    """Return the number of CUDA devices visible to CTranslate2 (0 if unavailable)."""
    try:
        import ctranslate2
        return int(ctranslate2.get_cuda_device_count())
    except Exception:
        return 0

_nvidia_gpu_cache = None
_cuda_hwaccel_cache = None


def nvidia_gpu_present():
    """Detect a physical NVIDIA adapter independently of CUDA runtime availability."""
    global _nvidia_gpu_cache
    if _nvidia_gpu_cache is not None:
        return _nvidia_gpu_cache

    executable = shutil.which("nvidia-smi")
    if executable:
        try:
            probe = subprocess.run(
                [executable, "-L"], capture_output=True, text=True, timeout=6,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _nvidia_gpu_cache = probe.returncode == 0 and bool(
                re.search(r"(?im)^GPU\s+\d+\s*:", probe.stdout or "")
            )
            if _nvidia_gpu_cache:
                return True
        except (OSError, subprocess.TimeoutExpired):
            pass

    if os.name == "nt":
        powershell = shutil.which("powershell.exe") or str(
            pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) /
            "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        )
        try:
            probe = subprocess.run(
                [powershell, "-NoProfile", "-NonInteractive", "-Command",
                 "(Get-CimInstance Win32_VideoController | Where-Object { $_.PNPDeviceID -match 'VEN_10DE' -and $_.PNPDeviceID -notmatch '^ROOT' }).Count"],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            _nvidia_gpu_cache = probe.returncode == 0 and int((probe.stdout or "0").strip() or "0") > 0
        except (OSError, ValueError, subprocess.TimeoutExpired):
            _nvidia_gpu_cache = False
    else:
        _nvidia_gpu_cache = False
    return _nvidia_gpu_cache


def preferred_speech_device():
    """Prefer CUDA; never use CPU when an NVIDIA GPU exists but CUDA is broken."""
    devices = cuda_device_count()
    if devices > 0:
        return "cuda"
    if nvidia_gpu_present():
        raise RuntimeError(
            "An NVIDIA GPU is installed, but CTranslate2 cannot initialize CUDA. "
            "CPU fallback is disabled while a GPU is available. Repair the NVIDIA CUDA runtime/driver first."
        )
    return "cpu"


def ffmpeg_cuda_decode_args():
    """Enable NVIDIA hardware decode; do not silently software-decode on an NVIDIA PC."""
    global _cuda_hwaccel_cache
    if not nvidia_gpu_present():
        return []
    if _cuda_hwaccel_cache is None:
        probe = run([ffmpeg_exe(), "-hide_banner", "-hwaccels"], capture_output=True, text=True, timeout=15)
        _cuda_hwaccel_cache = (
            probe.returncode == 0 and
            any(line.strip().lower() == "cuda" for line in (probe.stdout or "").splitlines())
        )
    if not _cuda_hwaccel_cache:
        raise RuntimeError(
            "An NVIDIA GPU is installed, but the bundled FFmpeg does not expose CUDA hardware decoding. "
            "CPU video decoding is disabled while a GPU is available."
        )
    return ["-hwaccel", "cuda"]

def whisper_model_cache_dir(name):
    """Return this model's Hugging Face cache directory, never the whole cache root."""
    repos = {
        "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
        "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
        "large-v3": "Systran/faster-whisper-large-v3",
        "medium": "Systran/faster-whisper-medium",
        "small": "Systran/faster-whisper-small",
        "base": "Systran/faster-whisper-base",
    }
    repo_id = repos.get(name)
    if not repo_id:
        return None
    cache_root = (os.environ.get("HF_HUB_CACHE") or
                  str(pathlib.Path(os.environ.get("HF_HOME", pathlib.Path.home() / ".cache" / "huggingface")) / "hub"))
    root = pathlib.Path(cache_root).expanduser().resolve()
    target = (root / ("models--" + repo_id.replace("/", "--"))).resolve()
    return target if target.parent == root else None

def whisper_model_dir(name):
    """Return the app-owned local directory for a downloaded Whisper model."""
    safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(name)).strip(".-")
    return WHISPER_MODELS / safe_name if safe_name else None


def download_whisper_model(name, force=False):
    """Download a complete model into app storage and return its local path."""
    destination = whisper_model_dir(name)
    if destination is None:
        raise RuntimeError("Invalid Whisper model name.")
    model_file = destination / "model.bin"
    if model_file.is_file() and not force:
        return str(destination)
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        from faster_whisper import download_model
        downloaded = pathlib.Path(download_model(name, output_dir=str(destination), local_files_only=False))
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    if not model_file.is_file() and (downloaded / "model.bin").is_file():
        return str(downloaded)
    if not model_file.is_file():
        shutil.rmtree(destination, ignore_errors=True)
        raise RuntimeError(f"Download for speech model '{name}' finished without model.bin.")
    return str(destination)

def apply_huggingface_token():
    """Expose the saved HF credential to huggingface_hub/faster-whisper downloads."""
    try:
        token = str(load_ai_settings().get("huggingface_token", "")).strip()
    except Exception:
        token = ""
    token = token or os.environ.get("HF_TOKEN", "").strip() or os.environ.get("HUGGING_FACE_HUB_TOKEN", "").strip()
    if token:
        # huggingface_hub reads HF_TOKEN when resolving gated/private model files.
        # Never log or return this value to the UI.
        os.environ["HF_TOKEN"] = token
        os.environ["HUGGING_FACE_HUB_TOKEN"] = token  # compatibility with older hub clients
        return True
    return False

def ffmpeg_exe():
    """Use the installer-verified FFmpeg path, then bundled or PATH FFmpeg."""
    configured = os.environ.get("STREAMSNIP_FFMPEG_PATH", "").strip()
    if configured and pathlib.Path(configured).is_file():
        return configured
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    roots = [HERE, pathlib.Path(sys.executable).resolve().parent]
    for root in roots:
        bundled = root / "vendor" / "ffmpeg" / name
        if bundled.is_file():
            return str(bundled)
    return shutil.which("ffmpeg") or "ffmpeg"

def ffmpeg_empty_audio_packets_error(message):
    """Identify FFmpeg's AAC EOF failure when a selected clip range has no audio packets."""
    text = str(message or "").lower()
    return (
        "could not open encoder before eof" in text
        and (
            "received no packets" in text
            or "nothing was written into output file" in text
        )
    )

def check_updates():
    """Check local runtime versions against public release metadata without changing anything."""
    result = []
    def add(name, current, latest="", note=""):
        result.append({"name": name, "current": current or "Not installed", "latest": latest or "Unknown",
                       "update": bool(current and latest and current != latest), "note": note})
    try:
        r = run([ffmpeg_exe(), "-version"], capture_output=True, text=True, timeout=10)
        m = re.search(r"ffmpeg version (\S+)", r.stdout or "")
        add("FFmpeg", m.group(1) if m else "Unknown", "",
            "Use the bundled or system FFmpeg build; its version is not directly comparable to upstream release tags.")
    except Exception as e:
        add("FFmpeg", "Not available", note=str(e))
    for package in ("faster-whisper", "streamlink", "ctranslate2", "numpy"):
        try: current = importlib_metadata.version(package)
        except importlib_metadata.PackageNotFoundError: current = ""
        latest = ""
        try:
            req = urllib.request.Request(f"https://pypi.org/pypi/{package}/json", headers={"User-Agent": "StreamSnip AI updater"})
            with urllib.request.urlopen(req, timeout=8) as response:  # nosec B310
                latest = str(json.loads(response.read()).get("info", {}).get("version", ""))
        except Exception: pass
        add(package, current, latest)
    model = str(load_settings().get("model", "distil-large-v3"))
    repo_cache = whisper_model_cache_dir(model)
    snapshots = (repo_cache / "snapshots") if repo_cache else None
    cached = bool(snapshots and snapshots.is_dir() and any(p.is_file() for p in snapshots.glob("*/model.bin")))
    add("Speech model: " + model, "Cached" if cached else "Not downloaded", "",
        "Selected model is " + ("available locally." if cached else "downloaded on first use."))
    return {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "items": result}

def _installed_app_info():
    """Return the registered StreamSnip install version and pywebview shell path."""
    root = pathlib.Path(os.environ.get("LOCALAPPDATA") or (pathlib.Path.home() / "AppData" / "Local"))
    fallback_dir = root / "Programs" / "StreamSnip AI Native"
    fallback = {
        "version": APP_VERSION,
        "installed": False,
        "install_dir": str(fallback_dir),
        "app_executable": str(fallback_dir / "shell" / "StreamSnipAI.exe"),
    }
    if os.name != "nt":
        return fallback
    try:
        import winreg
        roots = (
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        )
        for hive, key_path in roots:
            try:
                with winreg.OpenKey(hive, key_path) as parent:
                    for index in range(2048):
                        try:
                            name = winreg.EnumKey(parent, index)
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(parent, name) as key:
                                def value(key_name, default=""):
                                    try:
                                        return winreg.QueryValueEx(key, key_name)[0]
                                    except OSError:
                                        return default
                                display = str(value("DisplayName", ""))
                                if not display.casefold().startswith("streamsnip ai"):
                                    continue
                                version = str(value("DisplayVersion", "") or APP_VERSION)
                                location = str(value("InstallLocation", "") or "")
                                icon = re.sub(r",\s*\d+\s*$", "", str(value("DisplayIcon", "") or "")).strip().strip('"')
                                install_dir = pathlib.Path(location) if location else None
                                if install_dir is None and icon:
                                    icon_path = pathlib.Path(os.path.expandvars(icon))
                                    install_dir = icon_path.parent.parent if icon_path.parent.name.casefold() in {"desktop", "shell"} else icon_path.parent
                                install_dir = install_dir or fallback_dir
                                executable = pathlib.Path(os.path.expandvars(icon)) if icon.lower().endswith(".exe") else install_dir / "shell" / "StreamSnipAI.exe"
                                return {
                                    "version": version,
                                    "installed": True,
                                    "install_dir": str(install_dir),
                                    "app_executable": str(executable),
                                }
                        except OSError:
                            continue
            except OSError:
                continue
    except (ImportError, OSError, ValueError):
        pass
    return fallback


def _official_github_release_asset_url(value):
    """Accept only direct HTTPS assets from this repository's GitHub Releases."""
    text = str(value or "").strip()
    try:
        parsed = urllib.parse.urlsplit(text)
        port = parsed.port
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or (parsed.hostname or "").rstrip(".").lower() != "github.com"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or port not in (None, 443)
        or not parsed.path.startswith("/sifat-jaman-13/stream-clip-ai/releases/download/")
    ):
        return ""
    return text


def check_app_update():
    """Check the installed native app against the latest GitHub Release."""
    request = urllib.request.Request(
        "https://api.github.com/repos/sifat-jaman-13/stream-clip-ai/releases/latest",
        headers={"User-Agent": "StreamSnip AI version checker", "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=12) as response:  # nosec B310
        release = json.loads(response.read())
    installed = _installed_app_info()
    current = str(installed.get("version") or APP_VERSION)
    latest = str(release.get("tag_name", "")).lstrip("v") or APP_VERSION
    version_key = lambda value: tuple(int(part) for part in re.findall(r"\d+", str(value)))
    update_available = bool(version_key(latest) and version_key(latest) > version_key(current))
    assets = release.get("assets") if isinstance(release.get("assets"), list) else []
    installer = next((
        asset for asset in assets
        if str(asset.get("name", "")).lower().endswith(".exe")
        and "setup" in str(asset.get("name", "")).lower()
        and asset.get("browser_download_url")
    ), None)
    installer_url = _official_github_release_asset_url(
        installer.get("browser_download_url") if installer else ""
    )
    installer_name = str(installer.get("name", "")) if installer and installer_url else ""
    digest = str(installer.get("digest", "")) if installer and installer_url else ""
    digest = digest.removeprefix("sha256:").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        digest = ""
    checksum = next((
        asset for asset in assets
        if installer_name
        and str(asset.get("name", "")).lower() == (installer_name + ".sha256").lower()
        and asset.get("browser_download_url")
    ), None)
    checksum_url = _official_github_release_asset_url(
        checksum.get("browser_download_url") if checksum else ""
    )
    return {
        "current": current,
        "latest": latest,
        "update": update_available,
        "can_install": bool(update_available and installer_url and (digest or checksum_url)),
        "url": release.get("html_url") or APP_RELEASES_URL,
        "installer_url": installer_url,
        "installer_name": installer_name,
        "installer_sha256": digest,
        "installer_size": int(installer.get("size", 0) or 0) if installer else 0,
        "checksum_url": checksum_url,
        "name": release.get("name") or ("StreamSnip AI v" + latest),
    }


_UPDATE_INSTALLER_HANDOFF = r"""param([int]$ParentPid,[string]$InstallerPath,[string]$AppExecutable,[string]$WorkingDirectory,[string]$LogPath)
$ErrorActionPreference = "Stop"
$scriptPath = $MyInvocation.MyCommand.Path
function Log([string]$Message) {
    try { Add-Content -LiteralPath $LogPath -Value ("[{0}] {1}" -f (Get-Date),$Message) } catch {}
}
try {
    Log "Waiting for StreamSnip AI process $ParentPid to exit."
    $deadline = (Get-Date).AddMinutes(3)
    while ((Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
        Start-Sleep -Milliseconds 350
    }
    if (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue) {
        throw "StreamSnip AI did not shut down. Close it and retry."
    }
    Start-Sleep -Seconds 1
    $setup = Start-Process -FilePath $InstallerPath -ArgumentList @("/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART") -PassThru -Wait
    if ($setup.ExitCode -ne 0) { throw "Installer exited with code $($setup.ExitCode)." }
    if (-not (Test-Path -LiteralPath $AppExecutable -PathType Leaf)) {
        throw "Updated app was not found at $AppExecutable."
    }
    Log "Update installed. Launching the updated app."
    Start-Process -FilePath $AppExecutable -WorkingDirectory $WorkingDirectory
} catch {
    Log ("ERROR: " + $_.Exception.Message)
    try {
        Add-Type -AssemblyName PresentationFramework
        $message = "StreamSnip AI could not finish installing the update." + [Environment]::NewLine +
            $_.Exception.Message + [Environment]::NewLine + "Details: " + $LogPath
        [System.Windows.MessageBox]::Show($message,"StreamSnip AI update","OK","Error") | Out-Null
    } catch {}
} finally {
    Start-Sleep -Seconds 2
    Remove-Item -LiteralPath $InstallerPath -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $scriptPath -Force -ErrorAction SilentlyContinue
}
"""


def install_app_update(parent_pid=None):
    """Download and verify the latest setup, then install it after the native app exits."""
    if os.name != "nt":
        raise RuntimeError("Native in-app updates are available on Windows only.")
    release = check_app_update()
    if not release.get("update"):
        raise RuntimeError("This installation is already up to date (v" + str(release.get("current") or APP_VERSION) + ").")
    installer_url = _official_github_release_asset_url(release.get("installer_url"))
    checksum_url = _official_github_release_asset_url(release.get("checksum_url"))
    if not release.get("can_install") or not installer_url:
        raise RuntimeError("The latest release does not contain an official, verifiable Windows installer.")
    expected_parent = os.getppid()
    parent_pid = expected_parent if parent_pid is None else int(parent_pid)
    if parent_pid <= 1 or parent_pid != expected_parent:
        raise ValueError("Update must be requested by the active StreamSnip AI desktop process.")
    installer_name = pathlib.Path(str(release.get("installer_name") or "")).name
    if installer_name != release.get("installer_name") or not installer_name.lower().endswith(".exe"):
        raise RuntimeError("The published installer filename is invalid.")
    expected_hash = str(release.get("installer_sha256") or "").lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        if not checksum_url:
            raise RuntimeError("GitHub did not publish an official installer SHA-256 checksum.")
        with urllib.request.urlopen(
            urllib.request.Request(checksum_url, headers={"User-Agent": "StreamSnip AI updater"}),
            timeout=20,
        ) as response:  # nosec B310
            checksum_text = response.read().decode("utf-8", errors="replace")
        match = re.search(r"\b([0-9a-fA-F]{64})\b", checksum_text)
        if not match:
            raise RuntimeError("The published installer checksum file is invalid.")
        expected_hash = match.group(1).lower()

    installed = _installed_app_info()
    if not installed.get("installed"):
        raise RuntimeError("No existing native Windows installation was found.")
    app_exe = pathlib.Path(str(installed.get("app_executable") or ""))
    if not app_exe.name:
        raise RuntimeError("The installed app executable path could not be determined.")
    work_dir = app_exe.parent
    update_dir = pathlib.Path(tempfile.mkdtemp(prefix="streamsnip-update-"))
    installer_path = update_dir / installer_name
    helper_path = update_dir / "install-update.ps1"
    log_path = pathlib.Path(tempfile.gettempdir()) / "StreamSnipAI-update.log"
    try:
        request = urllib.request.Request(
            installer_url,
            headers={"User-Agent": "StreamSnip AI updater"},
        )
        with urllib.request.urlopen(request, timeout=180) as response:  # nosec B310
            payload = response.read()
        if not payload:
            raise RuntimeError("The GitHub installer download was empty.")
        expected_size = int(release.get("installer_size") or 0)
        if expected_size and len(payload) != expected_size:
            raise RuntimeError("Downloaded installer size does not match GitHub release metadata.")
        if hashlib.sha256(payload).hexdigest().lower() != expected_hash:
            raise RuntimeError("Installer SHA-256 verification failed. The downloaded file was not run.")
        installer_path.write_bytes(payload)
        helper_path.write_text(_UPDATE_INSTALLER_HANDOFF, encoding="utf-8-sig")
        powershell = pathlib.Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if not powershell.is_file():
            found = shutil.which("powershell.exe")
            if not found:
                raise RuntimeError("Windows PowerShell was not found.")
            powershell = pathlib.Path(found)
        flags = getattr(subprocess, "DETACHED_PROCESS", 8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 512)
        helper_args = [
            str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden", "-File", str(helper_path),
            "-ParentPid", str(parent_pid), "-InstallerPath", str(installer_path),
            "-AppExecutable", str(app_exe), "-WorkingDirectory", str(work_dir),
            "-LogPath", str(log_path),
        ]
        subprocess.Popen(
            helper_args, cwd=str(update_dir), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            close_fds=True, creationflags=flags,
        )
    except Exception:
        shutil.rmtree(update_dir, ignore_errors=True)
        raise
    return {
        "ok": True,
        "pending_restart": True,
        "current": release.get("current", ""),
        "latest": release.get("latest", ""),
        "log_path": str(log_path),
        "message": "The v" + str(release.get("latest")) + " installer is downloaded and SHA-256 verified. StreamSnip AI will close and install it automatically.",
    }


def update_components():
    """Update Python runtime components and download the selected speech model.
    FFmpeg is reported by the checker; bundled FFmpeg is replaced only by a new build.
    """
    if getattr(sys, "frozen", False):
        raise RuntimeError("This packaged app bundles its runtime components. Use the native Windows installer from GitHub Releases to update the installed desktop application.")
    requirements = pathlib.Path(__file__).resolve().parent / "requirements.txt"
    commands = [sys.executable, "-m", "pip", "install", "--upgrade", "-r", str(requirements),
                "streamlink", "numpy"]
    result = run(commands, capture_output=True, text=True, timeout=900)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Package update failed").strip()[-800:])
    model = str(load_settings().get("model", "distil-large-v3"))
    try:
        apply_huggingface_token()
        from faster_whisper import WhisperModel
        device = preferred_speech_device()
        if device == "cuda":
            try:
                WhisperModel(model, device="cuda", compute_type="float16")
            except Exception:
                WhisperModel(model, device="cuda", compute_type="int8_float16")
        else:
            WhisperModel(model, device="cpu", compute_type="int8")
        model_status = model + " ready"
    except Exception as e:
        model_status = model + " download deferred: " + str(e)[:180]
    return {"ok": True, "message": "Runtime packages updated; " + model_status}
SETTINGS_FILE = _data_root / "settings.json"
CUSTOM_FILE = _data_root / "custom_words.txt"
ZERNIO_FILE = _data_root / "zernio.json"
PUBLISHING_FILE = _data_root / "publishing.json"
AI_SETTINGS_FILE = _data_root / "ai_settings.json"
POSTED_FILE = _data_root / "posted.json"
SCHEDULED_FILE = _data_root / "scheduled.json"
ZERNIO_IDEMPOTENCY_FILE = _data_root / "zernio-idempotency.json"
INSTANCE_LOCK_FILE = _data_root / ".autoclip.lock"
_INSTANCE_LOCK_HANDLE = None
STORAGE_PATH_WARNING = ""

DATABASE_FILE = _data_root / "streamsnip.db"
DATABASE_SCHEMA_VERSION = 4


def _database_path(reference_path=None):
    if reference_path is not None:
        reference = pathlib.Path(reference_path)
        if reference.parent.resolve() != _data_root.resolve():
            return reference.parent / "streamsnip.db"
    return DATABASE_FILE


def _database_connection(reference_path=None):
    path = _database_path(reference_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(
        str(path), timeout=15, factory=ClosingSQLiteConnection
    )
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=15000")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=FULL")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS app_settings (
            setting_key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS clip_metadata (
            clip_path TEXT PRIMARY KEY,
            clip_name TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            caption TEXT NOT NULL DEFAULT '',
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_clip_metadata_name ON clip_metadata(clip_name);
        CREATE TABLE IF NOT EXISTS clip_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            clip_path TEXT NOT NULL,
            clip_name TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT 'zernio',
            connection_id TEXT NOT NULL DEFAULT '',
            account_id TEXT NOT NULL DEFAULT '',
            platform TEXT NOT NULL DEFAULT '',
            post_id TEXT NOT NULL DEFAULT '',
            state TEXT NOT NULL,
            scheduled_for TEXT,
            accepted_at REAL,
            published_at REAL,
            error TEXT NOT NULL DEFAULT '',
            extra_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_clip_deliveries_clip ON clip_deliveries(clip_path, state);
        CREATE INDEX IF NOT EXISTS idx_clip_deliveries_schedule ON clip_deliveries(state, scheduled_for);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_clip_deliveries_provider_post
            ON clip_deliveries(provider, connection_id, post_id, account_id)
            WHERE post_id <> '';
        CREATE TABLE IF NOT EXISTS publishing_connections (
            connection_id TEXT PRIMARY KEY,
            label TEXT NOT NULL DEFAULT '',
            credential_name TEXT NOT NULL,
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS publishing_accounts (
            connection_id TEXT NOT NULL REFERENCES publishing_connections(connection_id) ON DELETE CASCADE,
            account_id TEXT NOT NULL,
            platform TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            username TEXT NOT NULL DEFAULT '',
            settings_json TEXT NOT NULL DEFAULT '{}',
            updated_at REAL NOT NULL,
            PRIMARY KEY(connection_id, account_id)
        );
    """)
    db.execute(f"PRAGMA user_version={DATABASE_SCHEMA_VERSION}")
    return db


def _get_sql_setting(setting_key, default=None, reference_path=None):
    with _database_connection(reference_path) as db:
        row = db.execute(
            "SELECT value_json FROM app_settings WHERE setting_key=?",
            (str(setting_key),),
        ).fetchone()
    if row is None:
        return default
    try:
        return json.loads(row["value_json"])
    except (TypeError, ValueError):
        return default


def _set_sql_setting(setting_key, value, reference_path=None):
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    with _database_connection(reference_path) as db:
        db.execute(
            """INSERT INTO app_settings(setting_key,value_json,updated_at) VALUES(?,?,?)
               ON CONFLICT(setting_key) DO UPDATE SET
               value_json=excluded.value_json,updated_at=excluded.updated_at""",
            (str(setting_key), payload, time.time()),
        )


def _legacy_json(path):
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return data if isinstance(data, (dict, list)) else None
    except (OSError, ValueError, TypeError):
        return None


def _sanitize_legacy_json(path, value):
    """Rewrite a migrated JSON source without any credential material."""
    try:
        atomic_json_write(path, value)
    except Exception as exc:
        raise RuntimeError(
            f"Could not remove migrated secrets from legacy file {path.name}: {exc}"
        ) from exc



CF = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0      # no flashing console windows
_CHILD_PROCESS_LOCK = threading.RLock()
_CHILD_PROCESSES = set()
_APP_WINDOW_PROCESSES = set()
_PROCESS_SHUTDOWN = threading.Event()

def _forget_child_process(process):
    with _CHILD_PROCESS_LOCK:
        _CHILD_PROCESSES.discard(process)
        _APP_WINDOW_PROCESSES.discard(process)

def post_close_message_to_process_windows(pid, user32=None):
    """Send WM_CLOSE only to visible top-level windows owned by the app browser PID."""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        import ctypes
        from ctypes import wintypes
        user32 = user32 or ctypes.windll.user32
        closed = []
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def visit_window(hwnd, _):
            owner_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
            if owner_pid.value == pid and user32.IsWindowVisible(hwnd):
                if user32.PostMessageW(hwnd, 0x0010, 0, 0):  # WM_CLOSE
                    closed.append(hwnd)
            return True

        user32.EnumWindows(visit_window, 0)
        return bool(closed)
    except Exception:
        return False

def request_app_window_close(process, timeout=3.0):
    """Ask the app-owned browser window to close normally before force termination."""
    if process is None:
        return True
    try:
        if process.poll() is not None:
            _forget_child_process(process)
            return True
    except Exception:
        pass
    pid = getattr(process, "pid", None)
    if os.name == "nt" and isinstance(pid, int) and pid > 0 and pid != os.getpid():
        posted = post_close_message_to_process_windows(pid)
        if not posted:
            try:
                subprocess.run(["taskkill.exe", "/PID", str(pid), "/T"], capture_output=True,
                               timeout=max(1.0, timeout), creationflags=CF)
            except Exception:
                pass
    try:
        process.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, TimeoutError):
        return False
    except Exception:
        try:
            if process.poll() is None:
                return False
        except Exception:
            return False
    _forget_child_process(process)
    return True

def terminate_process_tree(process, force=True, timeout=2.0):
    """Stop a tracked child and its descendants, escalating when necessary."""
    if process is None:
        return
    try:
        if process.poll() is not None:
            _forget_child_process(process)
            return
    except Exception:
        pass
    pid = getattr(process, "pid", None)
    try:
        if force and os.name == "nt" and isinstance(pid, int) and pid > 0 and pid != os.getpid():
            subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, timeout=max(2.0, timeout), creationflags=CF)
        else:
            process.terminate()
        process.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, TimeoutError):
        try: process.kill()
        except Exception: pass
        try: process.wait(timeout=1)
        except Exception: pass
    except Exception:
        try: process.kill()
        except Exception: pass
    finally:
        _forget_child_process(process)

def shutdown_child_processes():
    """Close the app-owned browser normally, then remove remaining child processes."""
    _PROCESS_SHUTDOWN.set()
    with _CHILD_PROCESS_LOCK:
        app_windows = list(_APP_WINDOW_PROCESSES)
    for process in app_windows:
        request_app_window_close(process, timeout=3.0)
    with _CHILD_PROCESS_LOCK:
        processes = list(_CHILD_PROCESSES)
    for process in processes:
        terminate_process_tree(process, force=True)

def popen(cmd, **kw):
    if _PROCESS_SHUTDOWN.is_set():
        raise RuntimeError("StreamSnip AI is shutting down.")
    process = subprocess.Popen(cmd, creationflags=CF, **kw)
    with _CHILD_PROCESS_LOCK:
        if _PROCESS_SHUTDOWN.is_set():
            terminate_process_tree(process, force=True)
            raise RuntimeError("StreamSnip AI is shutting down.")
        _CHILD_PROCESSES.add(process)
    return process

def run(cmd, **kw):
    if kw.get("text") and "encoding" not in kw:
        kw["encoding"] = "utf-8"
        kw["errors"] = "replace"
    input_data = kw.pop("input", None)
    capture_output = bool(kw.pop("capture_output", False))
    timeout = kw.pop("timeout", None)
    check = bool(kw.pop("check", False))
    if input_data is not None:
        if kw.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used")
        kw["stdin"] = subprocess.PIPE
    if capture_output:
        if kw.get("stdout") is not None or kw.get("stderr") is not None:
            raise ValueError("stdout/stderr and capture_output may not both be used")
        kw["stdout"] = subprocess.PIPE
        kw["stderr"] = subprocess.PIPE
    process = popen(cmd, **kw)
    try:
        stdout, stderr = process.communicate(input_data, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        terminate_process_tree(process, force=True)
        try: stdout, stderr = process.communicate()
        except Exception: stdout, stderr = exc.output, exc.stderr
        exc.output, exc.stderr = stdout, stderr
        raise
    except BaseException:
        terminate_process_tree(process, force=True)
        raise
    finally:
        _forget_child_process(process)
    result = subprocess.CompletedProcess(cmd, process.returncode, stdout, stderr)
    if check:
        result.check_returncode()
    return result

def acquire_instance_lock():
    """Prevent accidentally launching two StreamSnip AI servers in one data folder."""
    global _INSTANCE_LOCK_HANDLE
    h = open(INSTANCE_LOCK_FILE, "a+")
    try:
        h.seek(0); h.write("1"); h.flush(); h.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(h.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(h.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, ImportError):
        h.close()
        raise RuntimeError("StreamSnip AI is already running from this data folder. Quit the other app window or stop its terminal process first.")
    _INSTANCE_LOCK_HANDLE = h

DEFAULTS = {
    "mode": "live", "target": "",
    "rec_dir": "", "out_dir": "",
    "clips_per_chunk": 2, "chunk_min": 3, "clip_duration": 30, "pre": 2, "post": 28, "min_score": 80,
    "model": "distil-large-v3", "compute_device": "gpu",
    "transcriber_provider": "faster-whisper", "transcriber_command": "", "transcriber_language": "auto",
    "color": "Yellow", "position": "Lower third", "caption_size": 82, "words_per_line": 3, "font": "Impact",
    "subtitle_custom": False, "subtitle_mode": "Karaoke", "subtitle_style": "GTA Neon", "subtitle_animation": "highlight",
    "profanity_filter_enabled": True, "profanity_filter_words": "",
    "profanity_audio_mode": "beep",
    "subtitle_font_size": 82, "subtitle_text_color": "#FFFFFF", "subtitle_stroke_color": "#000000",
    "subtitle_position": "Bottom", "subtitle_alignment": "Center", "subtitle_nudge": 0,
    "streamer_tag": "", "show_tag_video": True,
    "capture_bitrate_kbps": 8000,
    "layout": "Facecam + game (Twitch)", "output_format": "9:16", "crop_x": 34.2, "crop_y": 0.0,
    "crop_w": 31.6, "crop_h": 100.0, "delete_rec": True,
    "cam_x": 70, "cam_y": 4, "cam_w": 29, "cam_h": 37, "game_x": 50,
    # Default game region matches the original centered 1080x1152 lower panel on 16:9 input.
    "game_area_x": 23.6, "game_area_y": 0, "game_area_w": 52.8, "game_area_h": 100,
}
# ASS colours are BGR
CAPTION_COLORS = {"Yellow": "00FFFF", "Green": "00FF00", "Cyan": "FFFF00", "Orange": "0080FF", "Pink": "FF40FF"}
# (ASS alignment, vertical margin in 1920px output coordinates). The four presets
# cover top, upper third, lower third, and bottom without requiring custom mode.
CAPTION_POS = {"Top": (8, 110), "Upper third": (8, 520),
               "Middle": (5, 0), "Lower third": (2, 520), "Bottom": (2, 140)}
LAYOUTS = ["Facecam + game (Twitch)", "Blur background", "Fill (crop center)", "Selected crop"]
OUTPUT_FORMATS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
MODELS = ["distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base"]
STREAM_QUALITY = "1080p60,1080p,720p60,720p,best"
SUBTITLE_MODES = ["Karaoke", "Classic"]
SUBTITLE_STYLES = ["GTA Neon", "Classic", "Hormozi", "Neon", "MrBeast", "Minimal", "Fire"]
SUBTITLE_ANIMATIONS = ["highlight", "pop_in", "pop_in_line", "one_by_one", "build_up", "full_line"]
SUBTITLE_POSITIONS = ["Top", "Center", "Bottom"]
SUBTITLE_ALIGNMENTS = ["Left", "Center"]

def clean_cfg(raw):
    """Validate/clamp settings coming from the UI or disk."""
    raw = raw if isinstance(raw, dict) else {}
    c = dict(DEFAULTS)
    def num(k, lo, hi, cast):
        try: v = cast(raw.get(k, c[k]))
        except (TypeError, ValueError, OverflowError): v = c[k]
        if isinstance(v, float) and not math.isfinite(v): v = c[k]
        c[k] = max(lo, min(hi, v))
    num("clips_per_chunk", 0, 10, int); num("chunk_min", 3, 15, int)
    num("clip_duration", 10, 60, int); c["pre"] = 2; c["post"] = c["clip_duration"] - 2
    num("capture_bitrate_kbps", 8000, 50000, int)
    num("min_score", 0, 100, float); num("caption_size", 60, 150, int); num("words_per_line", 1, 4, int)
    num("subtitle_font_size", 60, 180, int); num("subtitle_nudge", -400, 400, int)
    c["min_score"] = round(c["min_score"], 1)
    num("cam_x", 0, 90, float); num("cam_y", 0, 90, float); num("cam_w", 10, 100, float); num("cam_h", 10, 100, float)
    num("game_x", 0, 100, float)  # legacy horizontal alignment, retained for older settings files
    num("game_area_x", 0, 90, float); num("game_area_y", 0, 90, float)
    num("game_area_w", 10, 100, float); num("game_area_h", 10, 100, float)
    num("crop_x", 0, 90, float); num("crop_y", 0, 90, float); num("crop_w", 10, 100, float); num("crop_h", 10, 100, float)
    c["cam_w"] = min(c["cam_w"], 100 - c["cam_x"]); c["cam_h"] = min(c["cam_h"], 100 - c["cam_y"])
    c["game_area_w"] = min(c["game_area_w"], 100 - c["game_area_x"])
    c["game_area_h"] = min(c["game_area_h"], 100 - c["game_area_y"])
    c["crop_w"] = min(c["crop_w"], 100 - c["crop_x"]); c["crop_h"] = min(c["crop_h"], 100 - c["crop_y"])
    for k in ("cam_x", "cam_y", "cam_w", "cam_h", "game_x", "game_area_x", "game_area_y", "game_area_w", "game_area_h", "crop_x", "crop_y", "crop_w", "crop_h"): c[k] = round(c[k], 1)
    if raw.get("mode") in ("live", "file"): c["mode"] = raw["mode"]
    c["target"] = str(raw.get("target", "")).strip()[:1000]
    transcriber = str(raw.get("transcriber_provider", "faster-whisper")).strip().lower()
    c["transcriber_provider"] = transcriber if transcriber in {"faster-whisper", "custom-command"} else "faster-whisper"
    c["transcriber_command"] = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(raw.get("transcriber_command", "")))[:2000]
    c["transcriber_language"] = re.sub(r"[^A-Za-z0-9_-]", "", str(raw.get("transcriber_language", "auto")))[:20] or "auto"
    # Hardware is automatic: CUDA whenever a supported NVIDIA GPU is visible.
    # Keep the setting key for compatibility with existing settings files.
    c["compute_device"] = "gpu"
    for k, opts in (("color", CAPTION_COLORS), ("position", CAPTION_POS), ("layout", LAYOUTS),
                    ("output_format", OUTPUT_FORMATS), ("model", MODELS)):
        if raw.get(k) in opts: c[k] = raw[k]
    for k, opts in (("subtitle_mode", SUBTITLE_MODES), ("subtitle_style", SUBTITLE_STYLES),
                    ("subtitle_animation", SUBTITLE_ANIMATIONS), ("subtitle_position", SUBTITLE_POSITIONS),
                    ("subtitle_alignment", SUBTITLE_ALIGNMENTS)):
        if raw.get(k) in opts: c[k] = raw[k]
    c["subtitle_custom"] = bool(raw.get("subtitle_custom", False))
    c["profanity_filter_enabled"] = bool(raw.get("profanity_filter_enabled", c["profanity_filter_enabled"]))
    audio_mode = str(raw.get("profanity_audio_mode", c["profanity_audio_mode"]) or "beep").strip().lower()
    c["profanity_audio_mode"] = audio_mode if audio_mode in {"beep", "mute"} else "beep"
    extra_profanity = str(raw.get("profanity_filter_words", c["profanity_filter_words"]) or "")
    c["profanity_filter_words"] = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", extra_profanity)[:4000]
    for k, fallback in (("subtitle_text_color", "#FFFFFF"), ("subtitle_stroke_color", "#000000")):
        v = str(raw.get(k, fallback)).strip().upper()
        c[k] = v if re.fullmatch(r"#[0-9A-F]{6}", v) else fallback
    tag = re.sub(r"[\n{}\\]", "", str(raw.get("streamer_tag", c["streamer_tag"]))).strip()[:80]
    c["streamer_tag"] = tag
    c["show_tag_video"] = bool(raw.get("show_tag_video", c["show_tag_video"]))
    f = str(raw.get("font", c["font"])).strip()
    if re.fullmatch(r"[A-Za-z0-9 \-]{1,40}", f): c["font"] = f
    c["delete_rec"] = bool(raw.get("delete_rec", c["delete_rec"]))
    for k in ("rec_dir", "out_dir", "creator_rec_dir", "creator_out_dir"):
        value = str(raw.get(k, "") or "").strip()
        # Keep user-selected paths portable across Windows installs while avoiding
        # control characters or excessively large values in settings.json.
        c[k] = value[:1000] if "\x00" not in value else ""
    creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(raw.get("creator_id", "")))[:48]
    if creator_id:
        c["creator_id"] = creator_id
    return c

# Creator-owned settings are only the source framing and visual caption treatment.
# Speech/caption provider and clipping behavior stay in the shared application defaults.
CREATOR_PROFILE_SETTING_KEYS = (
    # Per-creator visual treatment only: source geometry, subtitles, and profanity.
    "cam_x", "cam_y", "cam_w", "cam_h", "game_x",
    "game_area_x", "game_area_y", "game_area_w", "game_area_h",
    "crop_x", "crop_y", "crop_w", "crop_h",
    "color", "position", "caption_size", "words_per_line", "font",
    "subtitle_custom", "subtitle_mode", "subtitle_style", "subtitle_animation",
    "subtitle_font_size", "subtitle_text_color", "subtitle_stroke_color",
    "subtitle_position", "subtitle_alignment", "subtitle_nudge",
    "streamer_tag", "show_tag_video",
    "profanity_filter_enabled", "profanity_filter_words", "profanity_audio_mode",
)

CREATOR_SHARED_SETTING_KEYS = (
    # AI provider lives in /api/ai/settings. These are shared caption-provider and
    # clipping/rendering defaults, including the output layout and aspect ratio.
    "transcriber_provider", "transcriber_command", "transcriber_language", "model",
    "compute_device", "cpu_threads", "language",
    "clips_per_chunk", "chunk_min", "clip_duration", "min_score",
    "capture_bitrate_kbps", "delete_rec", "layout", "output_format",
)


def creator_profile_values(raw):
    """Return only validated creator-specific framing and caption appearance fields."""
    if not isinstance(raw, dict):
        return {}
    validated = clean_cfg(raw)
    return {key: validated[key] for key in CREATOR_PROFILE_SETTING_KEYS if key in raw}


def apply_storage_paths(cfg):
    """Switch runtime folders to the user-selected locations."""
    global OUT, REC, STORAGE_PATH_WARNING
    STORAGE_PATH_WARNING = ""
    def chosen(key, fallback):
        value = str(cfg.get(key, "") or "").strip()
        try:
            path = pathlib.Path(value).expanduser() if value else fallback
            return path.resolve()
        except (OSError, ValueError):
            return fallback
    OUT = chosen("out_dir", _data_root / "out")
    REC = chosen("rec_dir", _data_root / "rec")
    for name, selected, fallback in (("clips", OUT, _data_root / "out"),
                                     ("recordings", REC, _data_root / "rec")):
        try:
            selected.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            local = fallback.resolve()
            local.mkdir(parents=True, exist_ok=True)
            if name == "clips":
                OUT = local
                cfg["out_dir"] = ""
            else:
                REC = local
                cfg["rec_dir"] = ""
            warning = f"Couldn't use the saved {name} folder '{selected}': {exc}. Using '{local}' instead."
            STORAGE_PATH_WARNING = (STORAGE_PATH_WARNING + " " + warning).strip()

def streamer_credit(cfg):
    """Prefer an explicit credit, then infer public Twitch/YouTube handles from the source URL."""
    override = re.sub(r"[\n{}\\]", "", str(cfg.get("streamer_tag", "")).strip())[:80]
    if override:
        return override
    target = str(cfg.get("target", "")).strip().strip('"')
    if not target:
        return ""
    candidate = target if "://" in target else "https://" + target.lstrip("/")
    try:
        parsed = urllib.parse.urlparse(candidate)
        host = (parsed.hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    segments = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if host == "clips.twitch.tv":
        return ""
    if host == "twitch.tv" or host.endswith(".twitch.tv"):
        handle = segments[0] if segments else ""
        if handle.lower() in {"videos", "directory", "search", "clip", "downloads", "settings", "wallet", "subscriptions"}:
            return ""
        cleaned = re.sub(r"[^A-Za-z0-9_]", "", handle)[:80]
        return "@" + cleaned if cleaned else ""
    if host == "youtube.com" or host.endswith(".youtube.com"):
        if not segments:
            return ""
        if segments[0].startswith("@"):
            handle = segments[0][1:]
        elif segments[0].lower() in {"c", "user"} and len(segments) > 1:
            handle = segments[1]
        else:
            return ""
        cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", handle)[:80]
        return "@" + cleaned if cleaned else ""
    return ""

CLIP_HASHTAGS = "#shorts #fyp #streamer #funny #clips #viral"
_CLIP_MANIFEST_LOCK = threading.Lock()


def _clip_timestamp(seconds):
    """Format source-video timestamps as HH:MM:SS."""
    total = max(0, int(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def build_clip_metadata_text(clip_filename, source_filename, start, end, transcript,
                             creator_credit="", post_title=None, post_description=None,
                             post_hashtags=None, include_provenance=False):
    """Return clean post copy; provenance stays in the local manifest only."""
    transcript = re.sub(r"\s+", " ", str(transcript or "")).strip()
    source_name = pathlib.Path(str(source_filename)).name
    clip_name = pathlib.Path(str(clip_filename)).name

    if post_title:
        title = str(post_title).strip()
    elif transcript:
        title = re.split(r"(?<=[.!?])\s+", transcript, maxsplit=1)[0].strip() or transcript
    else:
        source_title = pathlib.Path(source_name).stem.replace("_", " ").strip()
        title = f"Highlight from {source_title or 'video'}"

    if len(title) > 100:
        shortened = title[:97].rsplit(" ", 1)[0].rstrip(" .,:;!?-")
        title = (shortened or title[:97].rstrip()) + "..."
    title = title[0].upper() + title[1:] if title else "Highlight"

    description = str(post_description or "").strip()
    if not description:
        description = transcript or "A highlight from this video. No speech transcript was detected."
    if creator_credit and creator_credit.lower() not in description.lower():
        description += f"\n\nClip from {creator_credit}"
    tags = post_hashtags if isinstance(post_hashtags, list) else []
    tags = [str(tag).strip() for tag in tags if str(tag).strip()]
    if not tags:
        tags = CLIP_HASHTAGS.split()
    description += f"\n\n{' '.join(tags)}"
    if include_provenance:
        description += (
            f"\n\nClip: {clip_name}"
            f"\nSource: {source_name}"
            f"\nTimestamp: {_clip_timestamp(start)} - {_clip_timestamp(end)}"
        )
    return f"{title}\n\n{description}\n"


def _atomic_text_write(path, content):
    """Write UTF-8 text via a temporary sibling file to avoid partial metadata."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _unlink_clip_pair(clip_path):
    """Remove a clip MP4 and its TXT sidecar, surfacing Windows file-lock guidance."""
    for target in (clip_path, clip_path.with_suffix(".txt")):
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) in (32, 33):
                details = describe_file_lock(target, exc)
                CORE.push_file_lock(details)
                raise RuntimeError(details["message"]) from exc
            raise


def delete_clip_local_media(name, preserve_delivery_history=False):
    """Delete only the local MP4/sidecar, optionally retaining the SQL delivery archive."""
    name = str(name or "")
    if not CLIP_RE.fullmatch(name):
        raise ValueError("Invalid clip name.")
    clip_path = find_clip_path(name)
    if not clip_path:
        raise FileNotFoundError("Clip not found.")
    _unlink_clip_pair(clip_path)
    if not preserve_delivery_history:
        forget_posted_clips([name])
    invalidate_clip_cache()
    return {
        "ok": True,
        "name": name,
        "history_preserved": bool(preserve_delivery_history),
    }


def write_clip_metadata_files(output_dir, clip_filename, source_filename, start, end,
                              transcript, creator_credit="", on_warning=None,
                              post_title=None, post_description=None, post_hashtags=None):
    """Create clean post-ready TXT plus an internal provenance-rich clips index."""
    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    clip_name = pathlib.Path(str(clip_filename)).name
    sidecar = output_dir / f"{pathlib.Path(clip_name).stem}.txt"
    sidecar_text = build_clip_metadata_text(
        clip_name, source_filename, start, end, transcript, creator_credit,
        post_title, post_description, post_hashtags, include_provenance=False
    )
    _atomic_text_write(sidecar, sidecar_text)

    manifest = output_dir / "clips_metadata.txt"
    try:
        manifest_text = build_clip_metadata_text(
            clip_name, source_filename, start, end, transcript, creator_credit,
            post_title, post_description, post_hashtags, include_provenance=True
        )
        with _CLIP_MANIFEST_LOCK:
            existing = manifest.read_text(encoding="utf-8") if manifest.is_file() else ""
            combined = existing.rstrip() + ("\n\n" if existing.strip() else "") + manifest_text
            _atomic_text_write(manifest, combined)
        return sidecar, manifest
    except OSError as exc:
        if on_warning:
            on_warning(
                f"The matching clip TXT was saved, but clips_metadata.txt could not be updated: {exc}"
            )
        return sidecar, None


def normalize_stream_target(value):
    """Accept common pasted Twitch/YouTube links without a scheme."""
    target = str(value or "").strip().strip('"')
    if re.match(r"(?i)^(?:www\.)?(?:twitch\.tv|youtube\.com|youtu\.be)/", target):
        return "https://" + target
    return target

SETTINGS_VERSION = 2

def atomic_json_write(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp.write_text(json.dumps(value, indent=2), encoding="utf-8")
        if os.name != "nt":
            os.chmod(temp, 0o600)
        os.replace(temp, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        temp.unlink(missing_ok=True)

def load_settings():
    raw = _get_sql_setting("global_settings", None, SETTINGS_FILE)
    if not isinstance(raw, dict):
        raw = _legacy_json(SETTINGS_FILE)
        if not isinstance(raw, dict):
            raw = dict(DEFAULTS)
        else:
            _set_sql_setting("global_settings", raw, SETTINGS_FILE)
    # Version 1 stored min_score on a 0-5 scale. Version 2 uses 0-100.
    if int(raw.get("_settings_version", 1)) < SETTINGS_VERSION:
        try:
            old_score = float(raw.get("min_score"))
            if 0 < old_score <= 5:
                raw["min_score"] = round(50 + old_score * 20, 1)
        except (TypeError, ValueError, OverflowError):
            pass
        raw["_settings_version"] = SETTINGS_VERSION
        _set_sql_setting("global_settings", raw, SETTINGS_FILE)
    return clean_cfg(raw)


def save_settings(cfg):
    try:
        stored = dict(cfg)
        stored["_settings_version"] = SETTINGS_VERSION
        _set_sql_setting("global_settings", stored, SETTINGS_FILE)
    except Exception as exc:
        print(f"Could not save settings: {exc}", file=sys.stderr)

def _credential_store_for(path):
    # Credentials share the canonical application database; no parallel credential DB.
    root = pathlib.Path(path).parent
    return CredentialStore(root / "streamsnip.db")


def _migrate_zernio_secrets(cfg, store):
    """Move any legacy plaintext Zernio keys into the encrypted credential DB."""
    if not isinstance(cfg, dict):
        return False
    changed = False
    legacy_key = str(cfg.pop("api_key", "") or "").strip()
    if legacy_key:
        store.set("zernio", "legacy", legacy_key)
        changed = True
    connections = cfg.get("connections")
    if isinstance(connections, list):
        for connection in connections:
            if not isinstance(connection, dict):
                continue
            key = str(connection.pop("api_key", "") or "").strip()
            connection_id = str(connection.get("id", "") or "").strip()
            _register_runtime_log_secret(key)
            if key and connection_id:
                store.set("zernio", f"connection:{connection_id}", key)
                changed = True
    return changed


def _hydrate_zernio_secrets(cfg, store):
    """Expose decrypted keys only to the in-memory engine configuration."""
    if not isinstance(cfg, dict):
        return cfg
    connections = cfg.get("connections")
    if isinstance(connections, list):
        for connection in connections:
            if not isinstance(connection, dict):
                continue
            connection_id = str(connection.get("id", "") or "").strip()
            if connection_id and not connection.get("api_key"):
                key = store.get("zernio", f"connection:{connection_id}")
                if key:
                    connection["api_key"] = key
            _register_runtime_log_secret(connection.get("api_key", ""))
    if not cfg.get("api_key"):
        cfg["api_key"] = store.get("zernio", "legacy")
    _register_runtime_log_secret(cfg.get("api_key", ""))
    return cfg


def _publishing_legacy_snapshot():
    legacy_zernio = _legacy_json(ZERNIO_FILE)
    legacy_publishing = _legacy_json(PUBLISHING_FILE)
    zernio = dict(legacy_zernio) if isinstance(legacy_zernio, dict) else {}
    if isinstance(legacy_publishing, dict):
        saved_zernio = legacy_publishing.get("zernio")
        if isinstance(saved_zernio, dict):
            zernio.update(saved_zernio)
    return {
        "provider": "zernio",
        "zernio": zernio,
    }


def _persist_publishing_relations(zernio):
    now = time.time()
    with _database_connection(PUBLISHING_FILE) as db:
        db.execute("DELETE FROM publishing_connections")
        connections = zernio.get("connections") if isinstance(zernio, dict) else []
        for item in connections if isinstance(connections, list) else []:
            if not isinstance(item, dict):
                continue
            connection_id = str(item.get("id") or "").strip()
            if not connection_id:
                continue
            credential_name = f"connection:{connection_id}"
            non_secret = {
                key: value for key, value in item.items()
                if key not in {"api_key", "accounts"}
            }
            db.execute(
                """INSERT INTO publishing_connections(connection_id,label,credential_name,settings_json,updated_at)
                   VALUES(?,?,?,?,?)""",
                (connection_id, str(item.get("label") or ""), credential_name,
                 json.dumps(non_secret, ensure_ascii=False), now),
            )
            for account in item.get("accounts", []) if isinstance(item.get("accounts"), list) else []:
                if not isinstance(account, dict) or not account.get("id"):
                    continue
                account_settings = {
                    key: value for key, value in account.items()
                    if key not in {"id", "platform", "name", "username"}
                }
                db.execute(
                    """INSERT INTO publishing_accounts(
                           connection_id,account_id,platform,name,username,settings_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?)""",
                    (connection_id, str(account["id"]), str(account.get("platform") or ""),
                     str(account.get("name") or ""), str(account.get("username") or ""),
                     json.dumps(account_settings, ensure_ascii=False), now),
                )


def load_zernio_settings():
    return load_publishing_settings().get("zernio", {})


def save_zernio_settings(cfg):
    current = load_publishing_settings()
    current["zernio"] = dict(cfg) if isinstance(cfg, dict) else {}
    save_publishing_settings(current)


def load_publishing_settings():
    stored = _get_sql_setting("publishing", None, PUBLISHING_FILE)
    store = _credential_store_for(PUBLISHING_FILE)
    if not isinstance(stored, dict):
        stored = _publishing_legacy_snapshot()
        zernio = stored.get("zernio") if isinstance(stored.get("zernio"), dict) else {}
        # Migrate credentials from both old JSON locations before scrubbing them.
        _migrate_zernio_secrets(zernio, store)
        stored["zernio"] = zernio
        _set_sql_setting("publishing", stored, PUBLISHING_FILE)
        _persist_publishing_relations(zernio)

        # These compatibility files are no longer sources of truth. Preserve
        # non-secret settings for rollback, but remove every plaintext key.
        if PUBLISHING_FILE.exists():
            safe = json.loads(json.dumps(stored))
            atomic_json_write(PUBLISHING_FILE, safe)
        if ZERNIO_FILE.exists():
            atomic_json_write(ZERNIO_FILE, {})

    result = json.loads(json.dumps(stored))
    zernio = result.get("zernio")
    if not isinstance(zernio, dict):
        zernio = {}
        result["zernio"] = zernio
    result["zernio"] = _hydrate_zernio_secrets(zernio, store)
    return result


def save_publishing_settings(cfg):
    """Persist publishing preferences in SQLite; DPAPI-encrypt every API key."""
    persisted = json.loads(json.dumps(cfg if isinstance(cfg, dict) else {}))
    zernio = persisted.get("zernio")
    if not isinstance(zernio, dict):
        zernio = {}
        persisted["zernio"] = zernio

    store = _credential_store_for(PUBLISHING_FILE)
    keep = set()
    legacy_key = str(zernio.pop("api_key", "") or "").strip()
    if legacy_key:
        _register_runtime_log_secret(legacy_key)
        store.set("zernio", "legacy", legacy_key)
        keep.add("legacy")

    connections = zernio.get("connections")
    if isinstance(connections, list):
        seen_ids = set()
        for connection in connections:
            if not isinstance(connection, dict):
                continue
            connection_id = str(connection.get("id") or "").strip()
            if not connection_id or connection_id in seen_ids:
                raise ValueError("Every Zernio connection must have a unique connection ID.")
            seen_ids.add(connection_id)
            key = str(connection.pop("api_key", "") or "").strip()
            if key:
                _register_runtime_log_secret(key)
                store.set("zernio", f"connection:{connection_id}", key)
            keep.add(f"connection:{connection_id}")

    store.prune("zernio", keep)
    _set_sql_setting("publishing", persisted, PUBLISHING_FILE)
    _persist_publishing_relations(zernio)

    # Clear old plaintext stores so a disconnected credential cannot be
    # resurrected by a compatibility merge on the next launch.
    if PUBLISHING_FILE.exists():
        atomic_json_write(PUBLISHING_FILE, {})
    if ZERNIO_FILE.exists():
        atomic_json_write(ZERNIO_FILE, {})

def _clip_path_for_delivery_name(name):
    path = find_clip_path(name)
    if path:
        return str(path.resolve())
    with _database_connection() as db:
        row = db.execute(
            """SELECT clip_path FROM (
                   SELECT clip_path,updated_at FROM clip_metadata WHERE clip_name=?
                   UNION ALL
                   SELECT clip_path,updated_at FROM clip_deliveries WHERE clip_name=?
               ) ORDER BY updated_at DESC LIMIT 1""",
            (str(name), str(name)),
        ).fetchone()
    return str(row["clip_path"]) if row else ""


def _delivery_rows_for_state(state):
    with _database_connection() as db:
        rows = db.execute(
            """SELECT clip_path,clip_name,connection_id,account_id,platform,post_id,
                      state,scheduled_for,accepted_at,published_at,error,extra_json
               FROM clip_deliveries WHERE state=? ORDER BY accepted_at DESC,id DESC""",
            (str(state),),
        ).fetchall()
    return rows


def _legacy_delivery_import(state, legacy_path):
    legacy = _legacy_json(legacy_path)
    if not isinstance(legacy, dict):
        return
    # Only import once. The old files do not contain per-post IDs or verified
    # provider schedule timestamps, so those fields intentionally remain empty.
    marker = f"legacy_{state}_registry_imported"
    if _get_sql_setting(marker, False, legacy_path):
        return
    now = time.time()
    with _database_connection(legacy_path) as db:
        for name, item in legacy.items():
            if not isinstance(item, dict):
                continue
            clip_path = _clip_path_for_delivery_name(name)
            account_values = item.get("accounts", [])
            if not isinstance(account_values, list) or not account_values:
                account_values = [""]
            for destination in account_values:
                value = str(destination or "")
                platform, separator, account_id = value.partition(":")
                db.execute(
                    """INSERT INTO clip_deliveries(
                           clip_path,clip_name,provider,connection_id,account_id,platform,
                           post_id,state,scheduled_for,accepted_at,published_at,error,extra_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        clip_path, str(name), "zernio", "", account_id if separator else "",
                        platform if separator else "", "", state,
                        None, float(item.get("scheduled_at", 0) or item.get("posted_at", 0) or now),
                        float(item.get("posted_at", 0) or 0) if state == "posted" else None,
                        "", json.dumps({"migrated_from": legacy_path.name}), now,
                    ),
                )
    _set_sql_setting(marker, True, legacy_path)
    # The old file has been imported into SQL and may contain no secrets.
    atomic_json_write(legacy_path, {})


def _registry_from_sql(state):
    _legacy_delivery_import(state, POSTED_FILE if state == "posted" else SCHEDULED_FILE)
    rows = _delivery_rows_for_state(state)
    registry = {}
    for row in rows:
        name = str(row["clip_name"])
        item = registry.setdefault(name, {
            "platform": "zernio",
            "accounts": [],
            "post_ids": [],
            "connection_ids": [],
        })
        if row["clip_path"]:
            item["clip_path"] = str(row["clip_path"])
        if row["scheduled_for"]:
            previous_schedule = str(item.get("scheduled_for") or "")
            item["scheduled_for"] = max(previous_schedule, str(row["scheduled_for"]))
        if row["platform"] and row["account_id"]:
            item["accounts"].append(f"{row['platform']}:{row['account_id']}")
        if row["post_id"]:
            item["post_ids"].append(row["post_id"])
        if row["connection_id"]:
            item["connection_ids"].append(row["connection_id"])
        if state == "posted":
            item["posted_at"] = max(float(item.get("posted_at", 0) or 0), float(row["published_at"] or row["accepted_at"] or 0))
        else:
            item["scheduled_at"] = max(float(item.get("scheduled_at", 0) or 0), float(row["accepted_at"] or 0))
            if row["scheduled_for"]:
                item.setdefault("scheduled_for", row["scheduled_for"])
    for item in registry.values():
        for key in ("accounts", "post_ids", "connection_ids"):
            item[key] = list(dict.fromkeys(item[key]))
    return registry


def load_posted_registry():
    return _registry_from_sql("posted")


def save_posted_registry(registry):
    now = time.time()
    with _database_connection() as db:
        db.execute("DELETE FROM clip_deliveries WHERE state='posted'")
        for name, item in (registry or {}).items():
            if not isinstance(item, dict):
                continue
            clip_path = _clip_path_for_delivery_name(name)
            accounts = item.get("accounts", []) if isinstance(item.get("accounts"), list) else [""]
            for destination in accounts or [""]:
                platform, separator, account_id = str(destination or "").partition(":")
                db.execute(
                    """INSERT INTO clip_deliveries(
                           clip_path,clip_name,provider,connection_id,account_id,platform,
                           post_id,state,accepted_at,published_at,extra_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (clip_path, str(name), "zernio", "", account_id if separator else "",
                     platform if separator else "", "", "posted",
                     float(item.get("posted_at", now) or now), float(item.get("posted_at", now) or now),
                     "{}", now),
                )
    _set_sql_setting("legacy_posted_registry_imported", True)


def load_scheduled_registry():
    return _registry_from_sql("scheduled")


def save_scheduled_registry(registry):
    now = time.time()
    with _database_connection() as db:
        db.execute("DELETE FROM clip_deliveries WHERE state='scheduled'")
        for name, item in (registry or {}).items():
            if not isinstance(item, dict):
                continue
            clip_path = _clip_path_for_delivery_name(name)
            accounts = item.get("accounts", []) if isinstance(item.get("accounts"), list) else [""]
            for destination in accounts or [""]:
                platform, separator, account_id = str(destination or "").partition(":")
                db.execute(
                    """INSERT INTO clip_deliveries(
                           clip_path,clip_name,provider,connection_id,account_id,platform,
                           post_id,state,scheduled_for,accepted_at,extra_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (clip_path, str(name), "zernio", "", account_id if separator else "",
                     platform if separator else "", "", "scheduled", item.get("scheduled_for"),
                     float(item.get("scheduled_at", now) or now), "{}", now),
                )
    _set_sql_setting("legacy_scheduled_registry_imported", True)


def _merge_registry_accounts(previous, accounts=None):
    return list(dict.fromkeys(
        [str(x)[:150] for x in (previous.get("accounts", []) if isinstance(previous.get("accounts"), list) else [])]
        + [str(x)[:150] for x in (accounts or [])]
    ))[:20]


def _delivery_epoch(value, fallback=None):
    """Convert provider ISO timestamps or numeric epochs into SQLite REAL values."""
    if value in (None, ""):
        return fallback
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        pass
    try:
        parsed = __import__("datetime").datetime.fromisoformat(
            str(value).replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=__import__("datetime").timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError, OverflowError):
        return fallback


def _write_delivery_records(name, state, accounts=None, records=None):
    clip_path = _clip_path_for_delivery_name(name)
    if not clip_path:
        raise ValueError("Clip not found.")
    now = time.time()
    record_rows = []
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            provider_status = str(record.get("status") or "").strip().lower()
            record_state = (
                "posted" if provider_status in {"published", "success", "posted"}
                else "scheduled" if provider_status in {
                    "scheduled", "queued", "pending", "processing", "submitted", "draft"
                }
                else ""
            )
            if record_state not in {"posted", "scheduled"}:
                continue
            record_rows.append({
                "connection_id": str(record.get("connection_id") or ""),
                "account_id": str(record.get("account_id") or ""),
                "platform": str(record.get("platform") or "").lower(),
                "post_id": str(record.get("post_id") or ""),
                "scheduled_for": record.get("scheduled_for"),
                "accepted_at": _delivery_epoch(record.get("accepted_at"), now),
                "published_at": _delivery_epoch(
                    record.get("published_at"), now if record_state == "posted" else None
                ),
                "state": record_state,
                "status": provider_status,
                "extra": record.get("extra") if isinstance(record.get("extra"), dict) else {},
            })
    if records is None and not record_rows:
        for destination in accounts or []:
            platform, separator, account_id = str(destination or "").partition(":")
            if not separator or not platform.strip() or not account_id.strip():
                continue
            record_rows.append({
                "connection_id": "",
                "account_id": account_id if separator else "",
                "platform": platform.lower() if separator else "",
                "post_id": "",
                "scheduled_for": None,
                "accepted_at": now,
                "published_at": now if state == "posted" else None,
                "state": state,
                "status": state,
                "extra": {},
            })
    if not record_rows and state == "posted" and records is None and accounts is None:
        # Keep compatibility only with the legacy callback API that supplies
        # no destination payload at all. An explicit empty/failed provider
        # response must never be converted into a successful delivery.
        record_rows.append({
            "connection_id": "",
            "account_id": "",
            "platform": "",
            "post_id": "",
            "scheduled_for": None,
            "accepted_at": now,
            "published_at": now,
            "state": state,
            "status": state,
            "extra": {},
        })
    if not record_rows:
        raise ValueError("The provider did not confirm any destinations.")

    with _database_connection() as db:
        # Records supplied by current provider callbacks are destination-specific.
        # Upsert them without deleting other successful destinations for the clip.
        # Legacy callbacks without post IDs retain their replace-the-clip behaviour.
        structured = any(record["post_id"] for record in record_rows)
        if not structured:
            db.execute(
                "DELETE FROM clip_deliveries WHERE clip_path=? AND state IN ('posted','scheduled')",
                (clip_path,),
            )
        for record in record_rows:
            values = (
                clip_path, str(name), "zernio", record["connection_id"],
                record["account_id"], record["platform"], record["post_id"],
                record["state"], record["scheduled_for"], record["accepted_at"],
                record["published_at"], "", json.dumps({
                    "provider_status": record["status"], **record["extra"],
                }), now,
            )
            existing = None
            if record["post_id"]:
                # Zernio can expose the same workspace post through more than one
                # saved API key. A remote destination is globally identified by
                # post ID + platform + account, not by the local API-key slot.
                existing = db.execute(
                    """SELECT id FROM clip_deliveries
                       WHERE provider='zernio' AND post_id=? AND account_id=? AND platform=?
                       ORDER BY CASE WHEN connection_id=? THEN 0 ELSE 1 END, id ASC
                       LIMIT 1""",
                    (
                        record["post_id"], record["account_id"], record["platform"],
                        record["connection_id"],
                    ),
                ).fetchone()
            if existing:
                db.execute(
                    """UPDATE clip_deliveries SET clip_path=?,clip_name=?,platform=?,state=?,
                           scheduled_for=?,accepted_at=?,published_at=?,error=?,extra_json=?,updated_at=?
                       WHERE id=?""",
                    (
                        clip_path, str(name), record["platform"], record["state"],
                        record["scheduled_for"], record["accepted_at"], record["published_at"],
                        "", values[12], now, existing["id"],
                    ),
                )
                # Remove only local duplicate rows for this exact confirmed
                # remote destination. No provider action is performed here.
                db.execute(
                    """DELETE FROM clip_deliveries
                       WHERE provider='zernio' AND post_id=? AND account_id=?
                         AND platform=? AND id<>?""",
                    (
                        record["post_id"], record["account_id"], record["platform"],
                        existing["id"],
                    ),
                )
            else:
                db.execute(
                    """INSERT INTO clip_deliveries(
                           clip_path,clip_name,provider,connection_id,account_id,platform,post_id,
                           state,scheduled_for,accepted_at,published_at,error,extra_json,updated_at
                       ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values,
                )
    invalidate_clip_cache()
    if state == "scheduled":
        return load_scheduled_registry().get(str(name), {})
    return load_posted_registry().get(str(name), {})


def record_zernio_posted(name, accounts=None, records=None):
    return _write_delivery_records(name, "posted", accounts, records)


def record_zernio_scheduled(name, accounts=None, records=None):
    return _write_delivery_records(name, "scheduled", accounts, records)


def zernio_posts_to_local_deliveries(posts, connection_id, local_clip_names):
    """Match read-only Zernio post-list results to videos that still exist locally."""
    names = {str(name) for name in (local_clip_names or [])}
    matched = {}
    for post in posts if isinstance(posts, list) else []:
        if not isinstance(post, dict):
            continue
        post_id = str(post.get("_id") or post.get("id") or "")
        post_state = str(post.get("status") or "").strip().lower()
        external_id = str(post.get("externalId") or post.get("external_id") or "")
        media_items = post.get("mediaItems") if isinstance(post.get("mediaItems"), list) else []
        media_urls = [
            urllib.parse.unquote(str(item.get("url") or ""))
            for item in media_items if isinstance(item, dict)
        ]
        matched_names = {
            name for name in names
            if name == external_id or any(name in url for url in media_urls)
        }
        if not matched_names:
            continue

        platform_rows = post.get("platforms") if isinstance(post.get("platforms"), list) else []
        for name in matched_names:
            bucket = matched.setdefault(name, {"posted": [], "scheduled": []})
            for destination in platform_rows:
                if not isinstance(destination, dict):
                    continue
                platform = str(destination.get("platform") or "").strip().lower()
                account_value = destination.get("accountId") or destination.get("account_id")
                if isinstance(account_value, dict):
                    account_id = str(account_value.get("_id") or account_value.get("id") or "").strip()
                else:
                    account_id = str(account_value or "").strip()
                status = str(destination.get("status") or post_state).strip().lower()
                if status in {"published", "success", "posted"}:
                    record_state = "posted"
                elif status in {"scheduled", "queued", "pending", "processing", "submitted", "draft"}:
                    record_state = "scheduled"
                else:
                    continue
                bucket[record_state].append({
                    "connection_id": str(connection_id or ""),
                    "account_id": account_id,
                    "platform": platform,
                    "post_id": post_id,
                    "scheduled_for": (
                        destination.get("scheduledFor")
                        or destination.get("scheduled_for")
                        or post.get("scheduledFor")
                        or post.get("scheduled_for")
                    ),
                    "published_at": (
                        destination.get("publishedAt")
                        or destination.get("published_at")
                        or post.get("publishedAt")
                        or post.get("published_at")
                    ),
                    "status": status,
                    "extra": {
                        "platform_post_id": destination.get("platformPostId") or "",
                        "platform_post_url": destination.get("platformPostUrl") or "",
                        "media_urls": media_urls,
                    },
                })
    return matched


def forget_posted_clips(names):
    now = time.time()
    normalized = [str(name) for name in (names or [])]
    if not normalized:
        return
    placeholders = ",".join("?" for _ in normalized)
    with _database_connection() as db:
        # Only the number of bound placeholders is interpolated; clip names remain parameters.
        db.execute(
            f"""UPDATE clip_deliveries SET state='removed',updated_at=?
                WHERE clip_name IN ({placeholders}) AND state IN ('posted','scheduled')""",  # nosec B608
            [now, *normalized],
        )
        # Keep values parameterized; the generated string contains only '?' placeholders.
        db.execute(
            f"DELETE FROM clip_metadata WHERE clip_name IN ({placeholders})",  # nosec B608
            normalized,
        )
    invalidate_clip_cache()

AI_SECRET_FIELDS = (
    "gemini_api_key",
    "huggingface_token",
    "custom_api_key",
    "openai_api_key",
    "anthropic_api_key",
)


def _safe_ai_settings_payload(cfg):
    """Return preferences only; provider credentials live in the DPAPI store."""
    return {key: value for key, value in cfg.items() if key not in AI_SECRET_FIELDS}


def load_ai_settings():
    defaults = {"provider": "gemini", "ollama_url": os.environ.get("STREAMSNIP_OLLAMA_URL", "http://127.0.0.1:11434"), "ollama_model": "",
                "gemini_model": DEFAULT_GEMINI_COPY_MODEL, "huggingface_model": DEFAULT_HUGGINGFACE_MODEL,
                "custom_api_base": "https://api.openai.com/v1", "custom_api_model": "",
                "custom_api_key": "", "gemini_api_key": "",
                "openai_api_base": "https://api.openai.com/v1", "openai_model": "", "openai_api_key": "",
                "anthropic_api_base": "https://api.anthropic.com", "anthropic_model": "", "anthropic_api_key": "",
                "huggingface_token": "",
                "metadata_copy_enabled": "true", "huggingface_setup_completed": "false"}
    data = {}
    try:
        loaded = json.loads(AI_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
            defaults.update({
                key: str(value) for key, value in data.items()
                if key in defaults and key not in AI_SECRET_FIELDS and value is not None
            })
    except Exception:
        pass

    # Upgrade older settings files in place. A successful DPAPI write must happen
    # before the plaintext value is removed from the legacy JSON file.
    store = _credential_store_for(AI_SETTINGS_FILE)
    migrated_legacy_secret = False
    for key in AI_SECRET_FIELDS:
        legacy_secret = str(data.get(key, "") or "").strip()
        if legacy_secret:
            store.set("ai", key, legacy_secret)
            migrated_legacy_secret = True
        secret = store.get("ai", key)
        if key == "huggingface_token" and not secret:
            secret = os.environ.get("HF_TOKEN", os.environ.get("HUGGING_FACE_HUB_TOKEN", ""))
        defaults[key] = secret
        _register_runtime_log_secret(secret)

    if migrated_legacy_secret:
        atomic_json_write(AI_SETTINGS_FILE, _safe_ai_settings_payload(data))

    # AI-written titles, descriptions, and tags are the normal workflow. Migrate
    # the old local phrase-score mode to the current Gemini default.
    defaults["metadata_copy_enabled"] = "true"
    if defaults["provider"] in {"hooks", "huggingface"}:
        defaults["provider"] = "gemini"
    if defaults["provider"] not in {"ollama", "gemini", "huggingface", "custom", "openai", "anthropic"}:
        defaults["provider"] = "gemini"
    if defaults["gemini_model"] in RETIRED_GEMINI_MODELS:
        defaults["gemini_model"] = DEFAULT_GEMINI_COPY_MODEL
    if defaults["huggingface_model"] == "Qwen/Qwen2.5-7B-Instruct-1M":
        defaults["huggingface_model"] = DEFAULT_HUGGINGFACE_MODEL
    return defaults


def public_ai_settings():
    cfg = load_ai_settings()
    return {"provider": cfg["provider"], "ollama_url": cfg["ollama_url"],
            "ollama_model": cfg["ollama_model"], "gemini_model": cfg["gemini_model"],
            "huggingface_model": cfg["huggingface_model"],
            "custom_api_base": cfg["custom_api_base"], "custom_api_model": cfg["custom_api_model"],
            "custom_api_key_set": bool(cfg["custom_api_key"]),
            "gemini_key_set": bool(cfg["gemini_api_key"]),
            "openai_api_base": cfg["openai_api_base"], "openai_model": cfg["openai_model"],
            "openai_key_set": bool(cfg["openai_api_key"]),
            "anthropic_api_base": cfg["anthropic_api_base"], "anthropic_model": cfg["anthropic_model"],
            "anthropic_key_set": bool(cfg["anthropic_api_key"]),
            "huggingface_token_set": bool(cfg["huggingface_token"]),
            "metadata_copy_enabled": str(cfg.get("metadata_copy_enabled", "true")).strip().lower() not in {"0", "false", "no", "off"}}


def save_ai_settings(body):
    cfg = load_ai_settings()
    store = _credential_store_for(AI_SETTINGS_FILE)
    previous_huggingface_token = str(cfg.get("huggingface_token", "")).strip()
    provider = str(body.get("provider", cfg["provider"]))
    if provider not in {"ollama", "gemini", "huggingface", "custom", "openai", "anthropic"}:
        raise ValueError("Unknown AI provider.")
    cfg["provider"] = provider
    # Retain a true value for compatibility with older settings files and clients.
    cfg["metadata_copy_enabled"] = "true"
    for key in ("ollama_url", "ollama_model", "gemini_model", "huggingface_model",
                "custom_api_base", "custom_api_model", "openai_api_base", "openai_model",
                "anthropic_api_base", "anthropic_model"):
        if key in body:
            cfg[key] = str(body[key]).strip()[:1000]
    for key in AI_SECRET_FIELDS:
        supplied = str(body.get(key, "") or "").strip()
        if supplied:
            cfg[key] = supplied[:4000]
            store.set("ai", key, cfg[key])
        _register_runtime_log_secret(cfg.get(key, ""))
    clear_flags = {
        "gemini_api_key": "clear_gemini_key",
        "huggingface_token": "clear_huggingface_token",
        "custom_api_key": "clear_custom_api_key",
        "openai_api_key": "clear_openai_key",
        "anthropic_api_key": "clear_anthropic_key",
    }
    for key, flag in clear_flags.items():
        if body.get(flag):
            store.delete("ai", key)
            cfg[key] = ""
    if body.get("clear_huggingface_token"):
        for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
            if previous_huggingface_token and os.environ.get(name, "").strip() == previous_huggingface_token:
                os.environ.pop(name, None)

    atomic_json_write(AI_SETTINGS_FILE, _safe_ai_settings_payload(cfg))
    apply_huggingface_token()
    return public_ai_settings()

def test_ai_settings(body):
    """Test entered or saved provider credentials without returning or persisting secrets."""
    body = body if isinstance(body, dict) else {}
    cfg = load_ai_settings()
    provider = str(body.get("provider", cfg["provider"]))
    if provider not in {"ollama", "gemini", "huggingface", "custom", "openai", "anthropic"}:
        raise ValueError("Unknown AI provider.")
    cfg["provider"] = provider
    for key in ("ollama_url", "ollama_model", "gemini_model", "huggingface_model",
                "custom_api_base", "custom_api_model", "openai_api_base", "openai_model",
                "anthropic_api_base", "anthropic_model"):
        if key in body:
            cfg[key] = str(body[key]).strip()[:1000]
    for key in AI_SECRET_FIELDS:
        if body.get(key):
            cfg[key] = str(body[key]).strip()[:4000]
        _register_runtime_log_secret(cfg.get(key, ""))
    return test_provider(provider, cfg)

# ------------------------------------------------------------------ hype words
HYPE_WORDS = {
    # reactions
    "wtf", "omg", "bro", "bruh", "brooo", "bruhhh", "dude", "ayo", "yooo", "yoo", "yo",
    "nahh", "nah", "holy", "jesus", "damn", "dang", "unbelievable", "insane", "crazy",
    "nuts", "mental", "wild", "cracked", "clutch", "clip", "scream", "screaming",
    "dead", "dying", "crying", "cry", "wow", "whoa", "woah", "yikes", "bruv", "fam",
    "madness", "sick", "filthy", "nasty", "disgusting", "unreal",
    "huh", "seriously", "genuinely",
    # laughing
    "lol", "lmao", "lmfao", "haha", "hahaha", "hahahaha", "rofl", "wheezing", "deceased",
    # gen z / streamer slang
    "sheesh", "cooked", "cook", "cooking", "goated", "goat", "rizz", "rizzler", "sigma",
    "skibidi", "gyatt", "fanum", "ohio", "bussin", "slay", "lit", "fire", "sus", "cap",
    "nocap", "bet", "fr", "ong", "deadass", "valid", "based", "ratio", "glazing", "glaze",
    "mid", "banger", "tuff", "crashout", "aura", "mewing", "cringe", "yeet",
    "vibes", "goofy", "ahh", "lowkey", "highkey", "bozo", "npc", "griefing", "trolling",
    "cheating", "hacker", "hacks", "w", "l", "ez", "gg", "pog", "poggers", "kekw", "omegalul",
    "pogchamp", "monkas", "copium", "hopium", "sadge", "pepega", "kappa", "clown",
    "sussy", "drip", "slaps", "chad", "gigachad",
    # UK-streamer style (Lacy / Zerkaa type energy)
    "peng", "safe", "innit", "mandem", "wagwan", "bare", "dench", "banging",
    "proper", "bloody", "bollocks", "mug", "donkey", "melt", "muppet", "legend", "shocking",
    "scammed", "robbed", "rigged", "washed", "gapped", "gap", "diff", "sweaty", "tryhard",
    "jumpscare", "ragequit", "rage", "lagging", "lag", "banned", "ban", "kicked",
    "cleanest", "disrespectful", "outplayed", "demolished", "obliterated",
    "hilarious", "genius", "stupid", "idiot", "embarrassing", "terrifying", "scary",
}
HYPE_PHRASES = {
    "no way", "no way bro", "ain't no way", "aint no way", "no cap", "no shot", "no chance",
    "let him cook", "let's go", "lets go", "let's gooo", "oh my god", "oh my gosh", "oh my days",
    "are you kidding", "you're kidding", "you're joking", "are you joking", "what the",
    "what the hell", "what the heck", "what the fuck", "bro what", "yo what", "wait what",
    "hold on", "hold up", "wait wait", "stop it", "i'm dead", "im dead", "i'm crying",
    "im crying", "i'm screaming", "im screaming", "i can't", "i cant", "that's crazy",
    "thats crazy", "that's insane", "thats insane", "is this real", "chat is this real",
    "clip that", "clip it", "chat clip", "oh no", "he's cooked", "hes cooked", "we're cooked",
    "were cooked", "so cooked", "he cooked", "you're cooked", "bro is cooked", "touch grass",
    "main character", "side quest", "big w", "huge w", "massive w", "take the l", "skill issue",
    "crash out", "crashing out", "aura points", "minus aura", "plus aura", "plus rizz",
    "minus rizz", "nah bro", "nah fr", "not like this", "it's over", "its over", "we're so back",
    "were so back", "we're back", "so back", "down bad", "what is happening", "i love this",
    "that's tuff", "thats tuff", "that's peak", "thats peak", "on god", "for real", "bro is",
    "bro really", "bro thinks", "what was that", "did you see that", "did that just happen",
    "this is insane", "this is crazy",
    # UK / streamer reactions
    "you what", "are you mad", "you're mad", "he's mad", "calm down", "shut up", "get in",
    "bloody hell", "i'm done", "im done", "i'm weak", "im weak", "i'm wheezing", "im wheezing",
    "i'm deceased", "actually insane", "actually crazy", "what a play", "what a shot",
    "what a save", "what a goal", "oh my word", "how is that possible", "how did that happen",
    "that's so bad", "that's so good", "i'm so confused", "i don't believe it", "i dont believe it",
    "behind you", "look out", "watch out", "ban him", "he's lagging", "that's cheating",
    "that's so funny", "i can't breathe", "i cant breathe", "you're done", "you're finished",
    "absolutely not", "never again", "send it", "pull up", "come on", "come on then",
    "are you serious", "you're lying", "stop lying", "i'm crying laughing",
}
_MAX_PHRASE = max(len(p.split()) for p in HYPE_PHRASES)

DEFAULT_CUSTOM = """# Streamer-specific words / phrases - one per line. Re-read for every chunk, so you can edit while recording.
#   word or phrase        -> counts as 2.0
#   word or phrase | 3    -> custom weight (higher = more likely to be clipped)
# Add the exact catchphrases of YOUR streamer here (type them the way they sound; Whisper spells by sound).

calm down | 2.5
oh my days | 3
shut up | 2.5
get in | 2.5
you what | 2.5
are you mad | 3
bloody hell | 2.5
i'm done | 2.5
no chance | 3
what a play | 3
wheezing | 3
i can't breathe | 3
let him cook | 3
"""

def norm(w):
    return re.sub(r"[^a-z0-9']", "", w.lower())

def read_custom_text():
    if not CUSTOM_FILE.exists():
        CUSTOM_FILE.write_text(DEFAULT_CUSTOM, encoding="utf-8")
    return CUSTOM_FILE.read_text(encoding="utf-8")

def parse_custom(text):
    custom = {}
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        phrase, wt = line, 2.0
        if "|" in line:
            phrase, w = line.rsplit("|", 1)
            try: wt = float(w)
            except ValueError: wt = 2.0
        key = " ".join(norm(x) for x in phrase.split() if norm(x))
        if key:
            custom[key] = wt
    return custom

def load_custom():
    return parse_custom(read_custom_text())

# ------------------------------------------------------------------ captions (ASS)
def ts(t):
    cs = int(round(max(0.0, t) * 100))
    return f"{cs // 360000}:{cs % 360000 // 6000:02d}:{cs % 6000 // 100:02d}.{cs % 100:02d}"

def clean_word(w):
    return re.sub(r"[{}\\]", "", w).strip(" .,;:\"").upper()

PROFANITY_FILTER_MASK = "****"
# Broad, token-aware English/UK/American profanity and widely used gaming-chat variants.
# Keep entries as whole words/phrases: filtering never matches harmless substrings.
DEFAULT_PROFANITY_TERMS = (
    # F-word family and common speech-to-text / typed variants
    "fuck", "fucking", "fucked", "fucker", "fuckers", "fucks", "fuckin", "fuckin'",
    "fuckwit", "fuckwits", "fuckface", "fuckfaces", "fuckhead", "fuckheads",
    "fuckboy", "fuckboys", "fuckgirl", "fuckgirls", "fuckup", "fuckups",
    "fucked up", "fuck off", "fuck you", "fuck it", "fuck this", "fuck that",
    "fuck me", "fuck sake", "for fuck sake", "for fuck's sake", "what the fuck",
    "who the fuck", "where the fuck", "why the fuck", "how the fuck",
    "shut the fuck up", "go fuck yourself", "get fucked", "fuck around",
    "motherfucker", "motherfuckers", "motherfucking", "mother fucker",
    "mother fuckers", "muthafucka", "muthafuckas", "muthafucker", "muthafuckers",
    "fuk", "fuking", "fuked", "fuker", "fukker", "fukk", "fukker", "fuk off",
    "fck", "fcking", "fcked", "fcker", "fck off", "fck you", "fvck", "phuck",
    "fucc", "fucced", "fuccing", "fux", "fuxk", "fkin", "effing", "effed",

    # S-word family and compounds
    "shit", "shits", "shitty", "shittier", "shittiest", "shitting", "shitted",
    "shithead", "shitheads", "shitbag", "shitbags", "shitshow", "shitstorm",
    "shit stain", "shitstain", "shitface", "shitfaces", "shit for brains",
    "shitbrain", "shitbrains", "shitbird", "shitbirds", "shitheel", "shitheels",
    "shitbox", "shitboxes", "shitload", "shitloads", "shitless", "shitfaced",
    "dipshit", "dipshits", "dumbshit", "dumbshits", "bullshit", "bullshits",
    "horseshit", "dogshit", "chickenshit", "apeshit", "batshit", "bullsht",
    "horsesht", "dogsht", "dipsht", "weak shit",
    "no shit", "holy shit", "piece of shit", "full of shit", "eat shit",
    "talk shit", "shit talk", "shit talking", "shit happens", "shit hit the fan",
    "oh shit", "what the shit", "shite", "shites", "shitehawk", "shiteater",
    "shiteating", "sheeit", "sheeeit", "shyt", "shitty", "sht", "shtty",
    "shthead", "shtface", "shtshow", "shtbag", "shtstain", "shtforbrains",
    # B-word family and common compounds
    "bitch", "bitches", "bitching", "bitched", "bitchy", "bitchier", "bitchiest",
    "bitchass", "bitch ass", "bitch slap", "bitchslap", "bitchfest",
    "bitchmade", "bitch-made", "son of a bitch", "son of a bitches",
    "little bitch", "basic bitch", "stupid bitch", "crying bitch", "you bitch",
    "biatch", "biatch", "bytch", "btch", "betch", "bich", "b1tch",
    # Ass / arse family
    "ass", "arse", "asshole", "assholes", "arsehole", "arseholes",
    "ass hat", "asshat", "ass wipe", "asswipe", "arse wipe", "arsewipe",
    "ass clown", "assclown", "assface", "assfaces", "assbag", "assbags",
    "asshead", "assheads", "ass kisser", "asskisser", "asslicker", "ass licker",
    "dumbass", "dumbasses", "jackass", "jackasses", "badass", "smartass",
    "smart asses", "hardass", "hardasses", "fatass", "fatasses", "lazyass",
    "shitass", "pain in the ass", "kiss my ass", "my ass", "up your ass",
    "arse about", "arse around", "arsehole", "arsewipe", "arsehat",
    "a-hole", "a hole", "a55", "azz",
    # D-word / C-word and sexual insults
    "dick", "dicks", "dickhead", "dickheads", "dickwad", "dickwads",
    "dickweed", "dickweeds", "dick face", "dickface", "dickbag", "dickbags",
    "dickless", "dick move", "dickish", "dickishness", "dick sucking",
    "dick sucker", "dicksucker", "dicksuckers", "cock", "cocks", "cockhead",
    "cockheads", "cockface", "cockwomble", "cockwombles", "cocksucker",
    "cocksuckers", "cocksucking", "cock sucker", "cock tease", "cocktease",
    "cockup", "cock-up", "cocky bastard", "knob", "knobs", "knobhead",
    "knobheads", "knob end", "knobend", "bellend", "bellends",
    "cunt", "cunts", "cunting", "cunted", "cunty", "cuntish", "cuntface",
    "cuntfaces", "cuntbag", "cuntbags", "cuntfuck", "cuntfucker",
    "cunt punt", "cunt punted", "cuntwaffle", "cunt waffles",
    "pussy", "pussies", "pussyhole", "pussy ass", "pussyass", "pussy whipped",
    "pussywhipped", "prick", "pricks", "prickish",
    "prickhead", "prickheads", "prick face", "prickface", "prickly bastard",
    "twat", "twats", "twatting", "twatted", "twatwaffle", "twat waffle",
    "twathead", "twatface", "twat faces", "slut", "sluts", "slutty", "slutbag",
    "slutbags", "whore", "whores", "whoring", "whored", "whorehouse",
    "whorebag", "whorebags", "skank", "skanks", "skanky", "hoe", "hoes",
    "thot", "thots", "ho", "hos", "hooker", "hookers", "tramp", "tramps",
    "slag", "slags", "slagging", "tart", "tarts",
    # UK / Commonwealth slang and insults
    "wanker", "wankers", "wanking", "wanked", "wank", "tosser", "tossers",
    "tosspot", "bollocks", "bollocking", "bollock", "bollocksed",
    "bugger", "buggers", "buggered", "buggering", "bugger off",
    "bloody hell", "bloody bastard", "bloody idiot", "bloody bollocks",
    "sod", "sod off", "sod it", "sod all", "sod you",
    "minger", "mingers", "munter", "munters", "git", "gits", "plonker",
    "plonkers", "pillock", "pillocks", "muppet", "muppets",
    "bellend", "bellends", "knobhead", "knobheads", "arsehole",
    "piss off", "piss off mate", "piss take", "pisstake", "piss-take",
    "pisshead", "pissheads", "pissed", "pissing", "piss poor", "pissy",
    "piss up", "take the piss", "taking the piss", "on the piss",
    # General vulgar language and expletives
    "damn", "damned", "dammit", "dammit", "goddamn", "goddammit", "god damn",
    "god damn it", "goddamned", "damn it", "damn you", "damn fucking",
    "hell", "hells", "hellish", "what the hell", "to hell", "go to hell",
    "holy hell", "hell no", "hell yeah", "crap", "crappy", "crapped", "crapping",
    "crapper", "crappers", "craphead", "crapload", "crapola", "craptastic",
    "douche", "douches", "douchebag", "douchebags", "douchey", "douchy",
    "scumbag", "scumbags", "dirtbag", "dirtbags", "sleazebag", "sleazebags",
    "jackhole", "jackholes", "dumbfuck", "dumbfucks", "fucktard", "fucktards",
    "shithead", "shitheads", "shit for brains", "asswipe", "asshat",
    "motherless fuck", "son of a whore", "son of a gun", "son of a bitch",
    "piece of crap", "piece of shit", "clusterfuck", "clusterfucks",
    "what a dick", "what a prick", "what an asshole",
    "screw you", "screw off", "screw that", "screw this", "screwed",
    "screwing", "screwed up", "screw-up", "screwup", "screwups",
    "damn straight", "for crying out loud", "jesus christ", "jesus fucking christ",
    "christ almighty", "goddamn it", "god damn it",
    # Internet / gaming chat shorthand and variants
    "wtf", "wth", "stfu", "gtfo", "fml", "lmfao", "lmao", "af",
    "pos", "piece of shit", "p.o.s", "ffs", "smfh", "fml", "smd",
    "suck my dick", "suck my balls", "eat a dick", "eat a bag of dicks",
    "eat shit", "go touch grass", "fuckboy", "dumbass", "dipshit",
    "f u", "fu", "f u c k", "f u c k you", "sh1t", "5hit", "f0ck",
    "fuk", "fck", "fvck", "phuck", "fucc", "fukk", "sht", "shyt",
    "btch", "b1tch", "biatch", "bich", "azz", "a55",
    # Widely recognized non-English profanity frequently heard in global streams
    "puta", "puto", "putas", "putos", "mierda", "mierdas", "joder", "jodido",
    "jodida", "jodete", "cabron", "cabrona", "cabrones", "coño",
    "pendejo", "pendeja", "pendejos", "pendejas", "verga", "vergas",
    "chingar", "chingada", "chingado", "chingate", "chinga", "chingon",
    "hijo de puta", "hija de puta", "hijos de puta", "la puta madre",
    "conchetumare", "concha tu madre", "merde", "putain", "connard",
    "connasse", "bordel", "scheisse", "scheiße", "arschloch", "fick",
    "ficken", "wichser", "verdammt",
    # South Asian stream/chat profanity commonly spoken in Hindi, Urdu, and Bangla.
    "chutiya", "chutya", "chutiye", "chutiyapa", "madarchod", "madarchodd",
    "bhenchod", "behenchod", "benchod", "bhench*d", "banchod", "bonchod",
    "gandu", "ganduu", "gaand", "gand", "gaand mara", "gand mara", "lodu",
    "lodu", "lund", "l*nd", "randi", "randibaaz", "harami", "haraamzada",
    "haramzada", "haramzadi", "bakchod", "bhosdike", "bhosdi", "bhosda",
    "bhosdika", "bhosdike", "chodu", "chod", "choda", "chodna", "chodai",
    "chodon", "maa ki chut", "ma ki chut", "teri maa", "teri ma", "teri behen",
    "teri bahan", "teri gaand", "teri gand", "khanki", "khankir pola",
    "bokachoda", "bal", "baal", "balchal", "shala", "magi", "magibaji",
    # Russian profanity heard in multiplayer voice chat.
    "blyat", "blyad", "blyadi", "suka", "suki", "sukablyat", "ebat",
    "yebat", "nahui", "nahuy", "huy", "hui", "pizda", "pizdec",
    "mudak", "mudaki", "pidor", "pidoras", "zalupa", "zasranets",
)
_PROFANITY_TOKEN_RE = re.compile(r"[\w]+(?:['’][\w]+)?", re.UNICODE)
_PROFANITY_TEXT_TOKEN_RE = re.compile(
    r"[\w]+(?:[*!._#-]+[\w]+)*(?:[$]+)?(?:['’][\w]+)?",
    re.UNICODE,
)

def _profanity_tokens(value):
    """Normalize common typed/ASR obfuscations, then tokenize whole words only."""
    text = str(value or "").casefold().replace("’", "'")
    # Translate symbols only when they appear inside a word, not sentence punctuation.
    text = re.sub(r"(?<=\\w)!(?=\\w)", "i", text)
    # Common keyboard substitutions: sh1t, a$$, f0ck and similar.
    text = text.translate(str.maketrans({"1": "i", "0": "o", "3": "e",
                                         "4": "a", "5": "s", "7": "t",
                                         "@": "a", "$": "s"}))
    # Strip decorative punctuation inserted inside a censored spelling (f*ck, b*tch).
    text = re.sub(r"(?<=\w)[*._#-]+(?=\w)", "", text)
    return [match.group(0) for match in _PROFANITY_TOKEN_RE.finditer(text)]

def _profanity_matches(tokens, terms):
    matched = set()
    for start in range(len(tokens)):
        for term in terms:
            stop = start + len(term)
            if stop <= len(tokens) and tuple(tokens[start:stop]) == term:
                matched.update(range(start, stop))
    return matched

def _profanity_terms(extra_terms=""):
    terms = {tuple(_profanity_tokens(term)) for term in DEFAULT_PROFANITY_TERMS}
    for line in re.split(r"[\n,;]+", str(extra_terms or "")):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tokens = _profanity_tokens(line)
        if tokens and len(tokens) <= 8:
            terms.add(tuple(tokens))
    terms.discard(())
    return sorted(terms, key=lambda term: (-len(term), term))

def censor_transcript_words(words, enabled=True, extra_terms=""):
    """Replace detected profanity in timestamped Whisper words, preserving timing."""
    entries = list(words or [])
    if not enabled or not entries:
        return entries
    token_stream, token_owners = [], []
    for index, entry in enumerate(entries):
        if len(entry) < 3:
            continue
        tokens = _profanity_tokens(entry[2])
        token_stream.extend(tokens)
        token_owners.extend([index] * len(tokens))
    matched_tokens = _profanity_matches(token_stream, _profanity_terms(extra_terms))
    matched_words = {token_owners[index] for index in matched_tokens}
    safe_words = []
    for index, entry in enumerate(entries):
        values = list(entry)
        if index in matched_words and len(values) >= 3:
            values[2] = PROFANITY_FILTER_MASK
        safe_words.append(tuple(values))
    return safe_words

def censor_profanity_text(value, enabled=True, extra_terms=""):
    """Mask profanity in generated titles, descriptions, hashtags, or other text."""
    text = str(value or "")
    if not enabled or not text:
        return text
    matches = list(_PROFANITY_TEXT_TOKEN_RE.finditer(text))
    tokens, owners = [], []
    for index, match in enumerate(matches):
        normalized = _profanity_tokens(match.group(0))
        tokens.extend(normalized)
        owners.extend([index] * len(normalized))
    matched_tokens = _profanity_matches(tokens, _profanity_terms(extra_terms))
    matched_words = {owners[index] for index in matched_tokens}
    for index in sorted(matched_words, reverse=True):
        match = matches[index]
        text = text[:match.start()] + PROFANITY_FILTER_MASK + text[match.end():]
    return text

def profanity_audio_filter(words, start, end, padding=0.02, mode="beep"):
    """Replace only censored word intervals with a tone or silence, using clip-relative timestamps."""
    try:
        clip_start, duration = float(start), max(0.0, float(end) - float(start))
        padding = max(0.0, min(0.08, float(padding)))
    except (TypeError, ValueError, OverflowError):
        return ""
    if duration <= 0:
        return ""
    intervals = []
    for word_start, word_end, word in words or []:
        if str(word).strip() != PROFANITY_FILTER_MASK:
            continue
        try:
            left = max(0.0, float(word_start) - clip_start - padding)
            right = min(duration, float(word_end) - clip_start + padding)
        except (TypeError, ValueError, OverflowError):
            continue
        if right <= left:
            continue
        if intervals and left <= intervals[-1][1] + 0.025:
            intervals[-1] = (intervals[-1][0], max(intervals[-1][1], right))
        else:
            intervals.append((left, right))
    if not intervals:
        return ""
    expression = "+".join(
        f"between(t,{left:.3f},{right:.3f})" for left, right in intervals
    )
    if str(mode or "beep").strip().lower() == "mute":
        return f"volume=0:enable='{expression}'"
    # Explicit stereo output avoids FFmpeg's default mono aeval layout,
    # which the AAC encoder rejected during the live test. Original audio is
    # preserved outside censored intervals; the beep replaces only those words.
    return (
        "aeval=exprs='if("
        + expression
        + ",0.18*sin(2*PI*1000*t),val(ch))':channel_layout=stereo"
    )

def group_words(ws, max_words, max_chars, gap=0.7):
    groups, cur = [], []
    for w in ws:
        chars = sum(len(x[2]) + 1 for x in cur) + len(w[2])
        if cur and (len(cur) >= max_words or chars > max_chars or w[0] - cur[-1][1] > gap):
            groups.append(cur); cur = []
        cur.append(w)
        if w[2][-1:] in ("?", "!"):
            groups.append(cur); cur = []
    if cur:
        groups.append(cur)
    return groups

SUBTITLE_PRESETS = {
    # Original GTA-style neon caption treatment, implemented for StreamSnip AI.
    "GTA Neon": {"font": "Impact", "text": "#EFFF43", "highlight": "#FF45A8", "stroke": "#301045", "outline": 7, "shadow": 5, "pop": True},
    "Classic": {"font": "Impact", "text": "#FFFFFF", "stroke": "#000000", "outline": 9, "shadow": 4, "pop": True},
    "Hormozi": {"font": "Arial Black", "text": "#FFFFFF", "stroke": "#000000", "outline": 10, "shadow": 4, "pop": True},
    "Neon": {"font": "Arial Black", "text": "#FFFFFF", "stroke": "#FF40FF", "outline": 7, "shadow": 3, "pop": True},
    "MrBeast": {"font": "Impact", "text": "#FFFFFF", "stroke": "#000000", "outline": 10, "shadow": 5, "pop": True},
    "Minimal": {"font": "Segoe UI Black", "text": "#FFFFFF", "stroke": "#000000", "outline": 4, "shadow": 1, "pop": False},
    "Fire": {"font": "Impact", "text": "#FFFFFF", "stroke": "#7A1200", "outline": 9, "shadow": 4, "pop": True},
}

def _ass_color(value, fallback):
    value = str(value or fallback).strip().lstrip("#")
    if not re.fullmatch(r"[0-9A-Fa-f]{6}", value):
        value = fallback.lstrip("#")
    return value[4:6] + value[2:4] + value[0:2]

def output_size(cfg):
    return OUTPUT_FORMATS.get(cfg.get("output_format", "9:16"), OUTPUT_FORMATS["9:16"])

def facecam_game_crop_filter(cfg):
    """Build the crop/scale filter for the user-selected game-capture rectangle."""
    x = float(cfg.get("game_area_x", DEFAULTS["game_area_x"])) / 100
    y = float(cfg.get("game_area_y", DEFAULTS["game_area_y"])) / 100
    w = float(cfg.get("game_area_w", DEFAULTS["game_area_w"])) / 100
    h = float(cfg.get("game_area_h", DEFAULTS["game_area_h"])) / 100
    return (
        f"crop=iw*{w:.4f}:ih*{h:.4f}:iw*{x:.4f}:ih*{y:.4f},"
        "scale=1080:1152:force_original_aspect_ratio=increase,crop=1080:1152"
    )


def make_ass(words, start, end, path, cfg):
    ws = []
    for s, e, w in words:
        if e > start and s < end:
            cw = clean_word(w)
            if cw:
                ws.append((max(0.0, s - start), min(end - start, e - start), cw))
    custom = bool(cfg.get("subtitle_custom"))
    out_w, out_h = output_size(cfg)
    preset = SUBTITLE_PRESETS.get(cfg.get("subtitle_style", "GTA Neon"), SUBTITLE_PRESETS["GTA Neon"])
    stroke = (_ass_color(cfg.get("subtitle_stroke_color"), "#000000") if custom
              else _ass_color(preset.get("stroke", "#000000"), "#000000"))
    size = int(cfg.get("subtitle_font_size", cfg["caption_size"])) if custom else int(cfg["caption_size"])
    font = cfg.get("font", "Impact") if custom else preset["font"]
    if custom:
        pos = cfg.get("subtitle_position", "Bottom")
        align = cfg.get("subtitle_alignment", "Center")
        alignment = {"Top": 7 if align == "Left" else 8, "Center": 4 if align == "Left" else 5,
                     "Bottom": 1 if align == "Left" else 2}[pos]
        nudge = round(int(cfg.get("subtitle_nudge", 0)) * out_h / 1920)
        mv = max(0, round(70 * out_h / 1920) + nudge) if pos != "Center" else nudge
        outline, shadow = preset["outline"], preset["shadow"]
    else:
        alignment, preset_margin = CAPTION_POS.get(cfg.get("position"), CAPTION_POS["Lower third"])
        mv, outline, shadow = round(preset_margin * out_h / 1920), preset["outline"], preset["shadow"]
    base_col = (_ass_color(cfg.get("subtitle_text_color"), "#FFFFFF") if custom
                else _ass_color(preset.get("text", "#FFFFFF"), "#FFFFFF"))
    highlight_col = (CAPTION_COLORS.get(cfg["color"], "00FFFF") if custom or not preset.get("highlight")
                     else _ass_color(preset["highlight"], "#FFFF00"))
    animation = cfg.get("subtitle_animation", "highlight")
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {out_w}\nPlayResY: {out_h}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,"
        "Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{size},&H00{base_col},&H00{base_col},&H00{stroke},&H64000000,0,0,0,0,100,100,2,0,1,{outline},{shadow},{alignment},{round(70 * out_w / 1080)},{round(70 * out_w / 1080)},{mv},1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    pop_enabled = cfg.get("subtitle_mode", "Karaoke") == "Karaoke" and bool(preset.get("pop", False))
    max_chars = max(8, int(1750 / size))
    lines = []
    groups = group_words(ws, int(cfg["words_per_line"]), max_chars)
    for gi, grp in enumerate(groups):
        group_end = grp[-1][1] + 0.2
        if gi + 1 < len(groups):
            group_end = min(group_end, groups[gi + 1][0][0])
        if animation == "full_line":
            text = " ".join(w for _, _, w in grp)
            lines.append(f"Dialogue: 0,{ts(grp[0][0])},{ts(max(group_end, grp[0][0] + 0.08))},Default,,0,0,0,,{text}")
            continue
        for j, (s, e, _) in enumerate(grp):
            if j + 1 < len(grp):
                end_t = grp[j + 1][0]
            else:                                   # last word: hold briefly, but never overlap the next line
                end_t = group_end
            if animation == "one_by_one":
                visible = [j]
            elif animation in {"pop_in", "build_up"}:
                visible = list(range(j + 1))
            else:                                   # highlight and pop_in_line keep the phrase visible
                visible = list(range(len(grp)))
            chunks = []
            for k in visible:
                word = grp[k][2]
                if k == j:
                    active_tag = r"{\1c&H" + highlight_col + r"&}"
                    if pop_enabled and animation in {"highlight", "pop_in", "one_by_one"}:
                        active_tag = r"{\1c&H" + highlight_col + r"&\fscx118\fscy118\t(0,100,\fscx100\fscy100)}"
                    chunks.append(active_tag + word + r"{\r}")
                elif animation in {"pop_in", "build_up"}:
                    chunks.append(r"{\1c&H" + base_col + r"&}" + word + r"{\r}")
                else:
                    chunks.append(word)
            text = " ".join(chunks)
            if animation == "pop_in_line" and j == 0:
                text = r"{\fscx82\fscy82\t(0,140,\fscx100\fscy100)\fad(90,0)}" + text
            lines.append(f"Dialogue: 0,{ts(s)},{ts(max(end_t, s + 0.08))},Default,,0,0,0,,{text}")
    tag = streamer_credit(cfg)
    if cfg.get("show_tag_video") and tag:
        tag_size = round(38 * out_w / 1080)
        tag_margin = round(70 * out_w / 1080)
        lines.append(f"Dialogue: 0,{ts(0)},{ts(max(0.08, end - start))},Default,,0,0,0,,"
                     f"{{\\an7\\fs{tag_size}\\bord3\\1c&H00FFFFFF&\\3c&H000000&\\pos({tag_margin},{tag_margin})}}Clip from {tag}")
    pathlib.Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ engine
_model, _model_key, _nvenc = None, None, None

def has_nvenc():
    global _nvenc
    if _nvenc is None:
        r = run([ffmpeg_exe(), "-v", "quiet", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
                 "-frames:v", "1", "-c:v", "h264_nvenc", "-f", "null", "-"], capture_output=True)
        _nvenc = r.returncode == 0
    if not _nvenc and nvidia_gpu_present():
        raise RuntimeError(
            "An NVIDIA GPU is installed, but FFmpeg could not initialize NVENC. "
            "CPU video encoding is disabled while a GPU is available. Check the NVIDIA driver and FFmpeg build."
        )
    return _nvenc

def _find_streamlink_exe():
    # Prefer the console script installed beside this interpreter. PATH can point
    # at another Python installation (for example 3.14 while the app runs on 3.11).
    # Mixing that executable with this process's PYTHONPATH causes SRE module
    # mismatch errors inside Streamlink's Python runtime.
    dirs = [pathlib.Path(sys.prefix) / "Scripts", pathlib.Path(sys.prefix) / "bin",
            pathlib.Path(sys.executable).parent, pathlib.Path(sys.executable).parent / "Scripts"]
    seen = set()
    for directory in dirs:
        key = os.path.normcase(str(directory))
        if key in seen:
            continue
        seen.add(key)
        for name in ("streamlink.exe", "streamlink"):
            candidate = directory / name
            if candidate.is_file():
                return str(candidate)
    return shutil.which("streamlink")

def streamlink_cmd():
    exe = _find_streamlink_exe()
    if exe:
        return [exe]
    # In a PyInstaller build, sys.executable is StreamSnipAI.exe rather than
    # Python. Route the child process through an explicit worker mode so it
    # runs Streamlink's CLI instead of starting a second StreamSnip AI instance.
    if getattr(sys, "frozen", False):
        return [sys.executable, "--streamlink"]
    # last resort: run streamlink's CLI with the SAME packages this script can import
    return [sys.executable, "-c", "from streamlink_cli.main import main; main()"]

def streamlink_env():
    # Do not inject the app interpreter's sys.path into a standalone Streamlink
    # executable found on PATH: it may belong to a different Python version.
    # The current-interpreter fallback already inherits its own import paths.
    return dict(os.environ)

def streamlink_available():
    if _find_streamlink_exe():
        return True
    import importlib.util
    return importlib.util.find_spec("streamlink_cli") is not None

def z(x):
    return (x - x.mean()) / (x.std() + 1e-9)

STALL_SECONDS = 90

class Stopped(Exception):
    pass


class FileBusyError(RuntimeError):
    def __init__(self, details):
        self.details = details
        super().__init__(details["message"])

def clip_bounds(peak, duration, before, after, words, limit=60, *, align_to_speech=True):
    """Choose a bounded clip window that always contains its detected peak."""
    duration = max(0.0, float(duration))
    if duration == 0:
        return 0.0, 0.0
    limit = min(duration, max(0.0, float(limit)))
    peak = min(duration, max(0.0, float(peak)))
    before = max(0.0, float(before))
    after = max(0.0, float(after))
    start = max(0.0, peak - before)
    end = min(duration, peak + after)

    # If requested context exceeds the cap, center the allowed window on the
    # detected peak (shifting at source boundaries). This trims both sides
    # and cannot cut the peak off, even with 90 seconds of pre-roll.
    if end - start > limit:
        start = max(0.0, min(peak - limit / 2, duration - limit))
        end = min(duration, start + limit)

    if align_to_speech:
        starts = [w for w in words if abs(w[0] - start) < 3 and w[0] <= peak]
        if starts:
            start = max(0, min(starts, key=lambda w: abs(w[0] - start))[0] - 0.25)
    start = min(start, peak)
    if peak > start + limit:
        start = peak - limit
    start = max(0.0, min(start, peak))
    max_end = min(duration, start + limit)
    end = min(max(end, peak), max_end)
    # Extend only through speech adjacent to this clip boundary. A later
    # conversation elsewhere in a long recording must not pull the clip out
    # to the 60-second cap and fill it with silence.
    if align_to_speech:
        ends = [w for w in words if abs(w[1] - end) < 3 and w[1] >= peak]
        if ends:
            nearest = min(ends, key=lambda w: abs(w[1] - end))
            end = min(max_end, max(end, nearest[1] + 0.35))
    return start, end


def windows_file_lock_owners(path):
    """Ask Windows Restart Manager which processes currently have a file open."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class RM_UNIQUE_PROCESS(ctypes.Structure):
        _fields_ = [("dwProcessId", wintypes.DWORD), ("ProcessStartTime", FILETIME)]

    class RM_PROCESS_INFO(ctypes.Structure):
        _fields_ = [
            ("Process", RM_UNIQUE_PROCESS), ("strAppName", wintypes.WCHAR * 256),
            ("strServiceShortName", wintypes.WCHAR * 64), ("ApplicationType", ctypes.c_int),
            ("AppStatus", wintypes.ULONG), ("TSSessionId", wintypes.DWORD),
            ("bRestartable", wintypes.BOOL),
        ]

    try:
        rm = ctypes.WinDLL("rstrtmgr", use_last_error=True)
        rm.RmStartSession.argtypes = [ctypes.POINTER(wintypes.DWORD), wintypes.DWORD, wintypes.LPWSTR]
        rm.RmStartSession.restype = wintypes.DWORD
        rm.RmRegisterResources.argtypes = [wintypes.DWORD, wintypes.UINT,
                                           ctypes.POINTER(wintypes.LPCWSTR), wintypes.UINT,
                                           ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p]
        rm.RmRegisterResources.restype = wintypes.DWORD
        rm.RmGetList.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.UINT),
                                 ctypes.POINTER(wintypes.UINT), ctypes.POINTER(RM_PROCESS_INFO),
                                 ctypes.POINTER(wintypes.DWORD)]
        rm.RmGetList.restype = wintypes.DWORD
        rm.RmEndSession.argtypes = [wintypes.DWORD]
        rm.RmEndSession.restype = wintypes.DWORD
        session = wintypes.DWORD()
        session_key = ctypes.create_unicode_buffer(33)
        if rm.RmStartSession(ctypes.byref(session), 0, session_key) != 0:
            return []
        try:
            resources = (wintypes.LPCWSTR * 1)(str(pathlib.Path(path).resolve()))
            if rm.RmRegisterResources(session.value, 1, resources, 0, None, 0, None) != 0:
                return []
            needed, count, reasons = wintypes.UINT(), wintypes.UINT(), wintypes.DWORD()
            result = rm.RmGetList(session.value, ctypes.byref(needed), ctypes.byref(count), None,
                                  ctypes.byref(reasons))
            if result != 234 or needed.value > 512:  # ERROR_MORE_DATA
                return []
            processes = (RM_PROCESS_INFO * needed.value)()
            count.value = needed.value
            result = rm.RmGetList(session.value, ctypes.byref(needed), ctypes.byref(count), processes,
                                  ctypes.byref(reasons))
            if result != 0:
                return []
            owners = []
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                            wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL
            for info in processes[:count.value]:
                pid = int(info.Process.dwProcessId)
                if pid <= 0:
                    continue
                image = ""
                handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                if handle:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                            image = buffer.value
                    finally:
                        kernel32.CloseHandle(handle)
                owners.append({
                    "pid": pid,
                    "name": pathlib.Path(image).name if image else str(info.strAppName or "Unknown application"),
                    "path": image,
                })
            return owners
        finally:
            rm.RmEndSession(session.value)
    except Exception:
        return []


def describe_file_lock(path, error):
    """Build an Activity entry and optional Stop-process actions for a locked file."""
    target = pathlib.Path(path)
    owners = windows_file_lock_owners(target)
    message = f"Windows could not finish using {target.resolve()}: {error}."
    if owners:
        who = "; ".join(
            f"{owner['name']} (PID {owner['pid']})" + (f" at {owner['path']}" if owner.get("path") else "")
            for owner in owners
        )
        message += f" File holder(s): {who}. Use Stop process in Activity to close a holder."
    else:
        message += " Windows did not identify the holder; close the video player or Explorer preview and retry."
    return {"message": message, "file_lock": {"name": target.name, "holders": owners} if owners else None}

PROCESSING_LOCK = threading.Lock()


def render_video_filter(cfg, ass_filename):
    """Return the exact video filter graph used by both final clips and output previews."""
    out_w, out_h = output_size(cfg)
    subtitle_file = pathlib.Path(ass_filename).name
    if cfg["layout"].startswith("Facecam") and cfg.get("output_format", "9:16") == "9:16":
        cx, cy, cw, ch = (float(cfg[k]) / 100 for k in ("cam_x", "cam_y", "cam_w", "cam_h"))
        game_crop = facecam_game_crop_filter(cfg)
        return ("[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
                f"[a]crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f},"
                "scale=1080:768:force_original_aspect_ratio=increase,crop=1080:768[cam];"
                f"[b]{game_crop}[game];"
                f"[cam][game]vstack=inputs=2,setsar=1,subtitles={subtitle_file}[v]")
    if cfg["layout"].startswith("Blur"):
        return ("[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
                f"[a]scale={round(out_w/4)}:{round(out_h/4)}:force_original_aspect_ratio=increase,crop={out_w//4}:{out_h//4},boxblur=8:2,scale={out_w}:{out_h}[bg];"
                f"[b]scale={out_w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                f"setsar=1,subtitles={subtitle_file}[v]")
    if cfg["layout"].startswith("Selected"):
        cx, cy, cw, ch = (float(cfg[k]) / 100 for k in ("crop_x", "crop_y", "crop_w", "crop_h"))
        crop = f"crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f},"
    else:
        crop = ""
    return (f"[0:v]setpts=PTS-STARTPTS,{crop}scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
            f"setsar=1,subtitles={subtitle_file}[v]")


class Engine:
    def __init__(self, cfg, emit):
        self.cfg, self.emit = cfg, emit
        # A creator worker may receive isolated folders; the normal single-stream
        # workflow continues to use the app-wide folders.
        self._out_dir_override = None
        self._rec_dir_override = None
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.rec_dir.mkdir(parents=True, exist_ok=True)
        self.stop_flag = self.abort = False
        self.ai_cancel = threading.Event()
        # Captured on the first highlight-analysis pass and reused for this clip batch.
        self.ai_cfg_for_render = None
        self.procs = []
        self.seg_seconds = int(cfg["chunk_min"]) * 60

    @property
    def out_dir(self):
        override = getattr(self, "_out_dir_override", None)
        if override is not None:
            return pathlib.Path(override)
        cfg = getattr(self, "cfg", {})
        return pathlib.Path(cfg.get("creator_out_dir") or OUT).expanduser().resolve()

    @out_dir.setter
    def out_dir(self, value):
        self._out_dir_override = pathlib.Path(value).expanduser().resolve()

    @property
    def rec_dir(self):
        override = getattr(self, "_rec_dir_override", None)
        if override is not None:
            return pathlib.Path(override)
        cfg = getattr(self, "cfg", {})
        return pathlib.Path(cfg.get("creator_rec_dir") or REC).expanduser().resolve()

    @rec_dir.setter
    def rec_dir(self, value):
        self._rec_dir_override = pathlib.Path(value).expanduser().resolve()

    def log(self, msg):                      self.emit("log", msg)
    def status(self, text, phase="working", progress=None): self.emit("status", (phase, text, progress))

    def stop(self, force=False):
        """Live: graceful (finish what is recorded) unless force. File: always immediate."""
        self.stop_flag = True
        if force or self.cfg["mode"] != "live":
            self.abort = True
            self.ai_cancel.set()
            for p in list(self.procs):
                terminate_process_tree(p, force=True)

    def check(self):
        if self.abort:
            raise Stopped()

    def replace_output(self, source, destination):
        try:
            os.replace(source, destination)
        except OSError as exc:
            if os.name == "nt" and getattr(exc, "winerror", None) in (32, 33):
                raise FileBusyError(describe_file_lock(destination, exc)) from exc
            raise

    # ---- transcription
    def _custom_transcript_words(self, payload):
        if isinstance(payload, dict):
            raw_words = payload.get("words")
            segments = payload.get("segments")
            if not isinstance(segments, list):
                segments = payload.get("transcription")
            if isinstance(raw_words, list) and raw_words:
                segments = None
            else:
                raw_words = None
        elif isinstance(payload, list):
            raw_words, segments = payload, None
        else:
            raw_words, segments = None, None

        words = []

        def append_word(start, end, value):
            value = str(value or "").strip()
            if not value:
                return
            try:
                start, end = float(start), float(end)
            except (TypeError, ValueError, OverflowError):
                return
            if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
                return
            words.append((start, end, value))

        def append_segment(segment):
            if not isinstance(segment, dict):
                return
            segment_words = segment.get("words")
            if isinstance(segment_words, list) and segment_words:
                for item in segment_words:
                    if isinstance(item, dict):
                        append_word(item.get("start", item.get("start_time")),
                                    item.get("end", item.get("end_time")),
                                    item.get("word", item.get("text")))
                    elif isinstance(item, (list, tuple)) and len(item) >= 3:
                        append_word(item[0], item[1], item[2])
                return
            text = str(segment.get("text", segment.get("word", "")) or "").strip()
            tokens = re.findall(r"\S+", text)
            if not tokens:
                return
            offsets = segment.get("offsets", {})
            if isinstance(offsets, dict) and ("from" in offsets or "to" in offsets):
                start = float(offsets.get("from", 0) or 0) / 1000.0
                end = float(offsets.get("to", 0) or 0) / 1000.0
            elif "from" in segment or "to" in segment:
                start = float(segment.get("from", 0) or 0) / 1000.0
                end = float(segment.get("to", 0) or 0) / 1000.0
            else:
                start = segment.get("start", segment.get("start_time", 0))
                end = segment.get("end", segment.get("end_time", start))
                start, end = float(start or 0), float(end or 0)
            if end <= start:
                return
            step = (end - start) / len(tokens)
            for index, token in enumerate(tokens):
                append_word(start + step * index, start + step * (index + 1), token)

        if raw_words is not None:
            for item in raw_words:
                if isinstance(item, dict):
                    append_word(item.get("start", item.get("start_time")),
                                item.get("end", item.get("end_time")),
                                item.get("word", item.get("text")))
                elif isinstance(item, (list, tuple)) and len(item) >= 3:
                    append_word(item[0], item[1], item[2])
        elif isinstance(segments, list):
            for segment in segments:
                append_segment(segment)

        words.sort(key=lambda item: (item[0], item[1]))
        if not words:
            raise RuntimeError(
                "The selected transcriber returned no timestamped words. Return JSON with a words or segments array."
            )
        return words

    def transcribe_custom(self, path):
        template = str(self.cfg.get("transcriber_command", "")).strip()
        if not template:
            raise RuntimeError("Choose Bring your own transcriber and enter its command template in Speech settings.")
        try:
            parts = shlex.split(template, posix=(os.name != "nt"))
        except ValueError as exc:
            raise RuntimeError(f"Could not parse the custom transcriber command: {exc}") from exc
        parts = [part[1:-1] if len(part) >= 2 and part[0] == part[-1] and part[0] in {"'", '"'} else part
                 for part in parts]
        if not parts:
            raise RuntimeError("The custom transcriber command is empty.")
        input_path = str(pathlib.Path(path).resolve())
        language = str(self.cfg.get("transcriber_language", "auto") or "auto")
        self.status("Running your custom transcriber...", "transcribing", 0)
        with tempfile.TemporaryDirectory(prefix="streamsnip-transcriber-") as temp_dir:
            output_path = str(pathlib.Path(temp_dir) / "transcript.json")
            has_input = any("{input}" in part for part in parts)
            args = [part.replace("{input}", input_path).replace("{output}", output_path)
                    .replace("{language}", language) for part in parts]
            if not has_input:
                args.append(input_path)
            self.log("Custom transcriber: launching configured command (no shell execution).")
            process = popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
            started = time.monotonic()
            try:
                while True:
                    try:
                        stdout, _ = process.communicate(timeout=1)
                        break
                    except subprocess.TimeoutExpired:
                        self.check()
                        if time.monotonic() - started > 3600:
                            raise RuntimeError("Custom transcriber exceeded the one-hour timeout.")
                if process.returncode != 0:
                    raise RuntimeError("Custom transcriber failed: " + (stdout or "no diagnostic output")[-700:])
                output_file = pathlib.Path(output_path)
                if not output_file.is_file():
                    appended_json = pathlib.Path(output_path + ".json")
                    alternate_json = output_file.with_suffix(".json")
                    output_file = next((candidate for candidate in (appended_json, alternate_json)
                                        if candidate.is_file()), output_file)
                if output_file.is_file():
                    payload = json.loads(output_file.read_text(encoding="utf-8-sig"))
                else:
                    payload = json.loads(stdout or "")
            except Stopped:
                terminate_process_tree(process, force=True)
                raise
            except BaseException:
                if process.poll() is None:
                    terminate_process_tree(process, force=True)
                raise
            finally:
                _forget_child_process(process)
        words = self._custom_transcript_words(payload)
        self.log(f"Custom transcriber returned {len(words)} timestamped word(s).")
        return words

    def get_model(self, name):
        global _model, _model_key
        device = preferred_speech_device()
        cache_key = (name, device)
        if _model is not None and _model_key == cache_key:
            return _model
        try:
            apply_huggingface_token()
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("faster-whisper isn't installed. Run:  pip install --only-binary=:all: faster-whisper")
        self.status(f"Preparing speech model '{name}'...", "transcribing")
        try:
            model_path = download_whisper_model(name)
        except Exception as exc:
            raise RuntimeError(f"Could not download or verify speech model '{name}': {exc}") from exc
        def load_selected_device():
            if device == "cuda":
                failures = []
                for compute_type in ("float16", "int8_float16"):
                    try:
                        return WhisperModel(model_path, device="cuda", compute_type=compute_type), compute_type
                    except Exception as exc:
                        failures.append(exc)
                        self.log(f"GPU load failed ({compute_type}): {exc}")
                raise failures[-1]
            return WhisperModel(model_path, device="cpu", compute_type="int8"), "INT8 CPU"
        try:
            _model, compute_type = load_selected_device()
        except Exception as first_error:
            try:
                repaired = "model.bin" in str(first_error).lower()
            except OSError as repair_error:
                raise RuntimeError(f"The cached Whisper model is incomplete and could not be cleared: {repair_error}") from first_error
            if not repaired:
                if device == "cuda":
                    raise RuntimeError("A CUDA GPU is available but the speech model could not start on it. Check the NVIDIA driver/CUDA setup. CPU fallback is disabled while a GPU is available. " + str(first_error)[-700:]) from first_error
                raise
            self.log(f"The local '{name}' model is incomplete (model.bin is missing). Downloading a verified fresh copy now.")
            try:
                model_path = download_whisper_model(name, force=True)
                _model, compute_type = load_selected_device()
            except Exception as retry_error:
                raise RuntimeError(f"Fresh download of speech model '{name}' failed: {retry_error}") from retry_error
        _model_key = cache_key
        self.log(f"Speech model ready on {'GPU' if device == 'cuda' else 'CPU'} ({compute_type}).")
        return _model

    def load_audio(self, path):
        """Decode to 16 kHz mono float32 with ffmpeg (bypasses PyAV completely)."""
        r = run([ffmpeg_exe(), "-v", "quiet", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                capture_output=True)
        a = np.frombuffer(r.stdout, dtype=np.float32)
        return a if len(a) > 16000 else None

    def transcribe(self, path):
        global _model, _model_key
        if self.cfg.get("transcriber_provider") == "custom-command":
            self.dur_audio = 0
            return self.transcribe_custom(path)
        lang = "en" if self.cfg["model"].startswith("distil") else None
        audio = self.load_audio(path)
        src = audio if audio is not None else str(path)
        self.dur_audio = (len(audio) / 16000) if audio is not None else 0
        try:
            import onnxruntime  # noqa: F401
            vad_filter = True
        except ImportError:
            # Python 3.15 currently omits the unsupported ONNX Runtime wheel.
            # VAD is an optional preprocessing filter; disable it rather than
            # making the core Whisper transcription path fail entirely.
            vad_filter = False
            self.log("ONNX Runtime is not installed; speech transcription will run without the optional VAD filter.")
        for attempt in range(2):
            try:
                model = self.get_model(self.cfg["model"])
                segs, _ = model.transcribe(src, word_timestamps=True, vad_filter=vad_filter, language=lang)
                words = []
                self.status("Transcribing audio... 0%", "transcribing", 0)
                for s in segs:
                    self.check()
                    for w in (s.words or []):
                        words.append((w.start, w.end, w.word.strip()))
                    if self.dur_audio:
                        self.status(f"Transcribing audio... {min(99, int((s.end / self.dur_audio) * 100))}%",
                                    "transcribing", min(99, int((s.end / self.dur_audio) * 100)))
                return words
            except Stopped:
                raise
            except Exception as e:
                if any(k in str(e).lower() for k in ("cublas", "cuda", "dll", "cudnn")) and cuda_device_count() > 0:
                    self.log(f"GPU transcription failed; not switching to CPU because a CUDA GPU is available: {e}")
                raise
        return []

    # ---- moment detection
    def rms_per_second(self, path):
        cmd = [ffmpeg_exe(), "-v", "quiet", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"]
        a = np.frombuffer(run(cmd, capture_output=True).stdout, dtype=np.float32)
        n = len(a) // 8000
        if n == 0:
            return np.zeros(0)
        return np.sqrt((a[: n * 8000].reshape(n, 8000) ** 2).mean(axis=1))

    def find_peaks(self, path, words):
        self.best_score = 0.0
        self.ai_strict_no_clip = False
        rms = self.rms_per_second(path)
        n = len(rms)
        if n < 10:
            return [], n
        wps, hype = np.zeros(n), np.zeros(n)
        custom = load_custom()
        max_custom = max((len(c.split()) for c in custom), default=0)
        toks = [(s, norm(w), w) for s, e, w in words if norm(w)]
        for k, (s, t, raw) in enumerate(toks):
            i = min(int(s), n - 1)
            wps[i] += 1
            for L in range(1, max_custom + 1):
                if k + L <= len(toks):
                    key = " ".join(x[1] for x in toks[k:k + L])
                    if key in custom:
                        hype[i] += custom[key]
            if t in HYPE_WORDS or raw.endswith("!"):
                hype[i] += 1
            for L in range(2, _MAX_PHRASE + 1):
                if k + L <= len(toks) and " ".join(x[1] for x in toks[k:k + L]) in HYPE_PHRASES:
                    hype[i] += 1.5
        kern = np.ones(5) / 5
        raw_score = z(np.convolve(rms, kern, "same")) + 0.5 * z(np.convolve(wps, kern, "same")) \
                + 0.8 * z(np.convolve(hype, kern, "same"))
        score = np.clip(50 + 20 * raw_score, 0, 100)
        ai_cfg = getattr(self, "ai_cfg_for_render", None)
        if not isinstance(ai_cfg, dict):
            ai_cfg = dict(load_ai_settings())
            self.ai_cfg_for_render = ai_cfg
        provider = ai_cfg["provider"]
        if provider == "hooks":
            self.log("Highlight scoring: built-in/custom hook words + audio energy and speech rate (local, offline; no AI model).")
        if provider != "hooks":
            # An AI provider is an explicit editorial choice: never replace an
            # empty/failed AI decision with unrelated audio or hook-word peaks.
            # This prevents ordinary moments from becoming clips when Gemini or
            # Ollama says the transcript has no viral payoff.
            self.ai_strict_no_clip = True
            mode = {"ollama": "Ollama local model", "gemini": "Gemini cloud model",
                    "huggingface": "Hugging Face hosted model",
                    "custom": "custom OpenAI-compatible API"}.get(provider, provider.title())
            ai_cfg["ai_window_minutes"] = int(self.cfg["chunk_min"])
            self.log(f"Highlight analysis starting with {mode}; analyzing the full transcript in {ai_cfg['ai_window_minutes']}-minute windows.")
            self.status(f"Finding viral moments with {mode}...", "transcribing", 100)
            try:
                ai_picks = select_moments(provider, words, n, ai_cfg, self.log, self.ai_cancel.is_set)
                if ai_picks:
                    ai_score = np.zeros(n, dtype=float)
                    for second, value in ai_picks:
                        if 0 <= int(second) < n:
                            ai_score[int(second)] = max(ai_score[int(second)], float(value))
                    score = ai_score
                    self.log(f"AI highlight analysis returned {len(ai_picks)} transcript highlights; scores were calibrated against nearby transcript engagement before applying the viral-score floor.")
                else:
                    self.log("AI highlight analysis returned no qualifying moments; this segment will produce no clips.")
                    return [], n
            except AIAnalysisCancelled:
                raise Stopped()
            except AIProviderError as exc:
                self.log(f"AI highlight analysis failed: {exc}. This segment will produce no clips.")
                return [], n
            except Exception as exc:
                self.log(f"AI highlight analysis returned an invalid response: {exc}. This segment will produce no clips.")
                return [], n
        self.best_score = float(score.max())
        requested = int(self.cfg["clips_per_chunk"])
        # Zero means unlimited: keep selecting non-overlapping moments while they
        # clear the viral-score floor. A positive value keeps the normal cap.
        n_clips = None if requested == 0 else max(1, round(n / self.seg_seconds * requested))
        picks, s = [], score.copy()
        while n_clips is None or len(picks) < n_clips:
            i = int(s.argmax())
            if s[i] < float(self.cfg["min_score"]) or s[i] <= 0:
                break
            if rms[i] < 0.0025:
                s[i] = -99
                continue
            picks.append((i, float(s[i])))
            s[max(0, i - 40): i + 40] = -99          # never pick overlapping moments
        if not picks:
            self.log("No moment passed the viral-score floor - this segment produced no clips.")
        return picks, n

    # ---- render
    def render(self, src, start, end, words, name, metadata_words=None):
        cfg = self.cfg
        words = censor_transcript_words(
            words, enabled=cfg.get("profanity_filter_enabled", True),
            extra_terms=cfg.get("profanity_filter_words", "")
        )
        # Keep captions and persisted transcript censored, but let the selected
        # copy provider understand the full moment before its output is censored.
        source_words = list(metadata_words if metadata_words is not None else words)
        metadata_transcript = re.sub(
            r"\s+", " ",
            " ".join(
                str(word).strip() for word_start, _word_end, word in source_words
                if start <= word_start <= end
            ),
        ).strip()
        out_w, out_h = output_size(cfg)
        make_ass(words, start, end, self.out_dir / f"{name}.ass", cfg)
        vf = render_video_filter(cfg, f"{name}.ass")
        enc = (["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21", "-b:v", "0"] if has_nvenc()
               else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
        profanity_filter = (
            profanity_audio_filter(
                words, start, end, mode=cfg.get("profanity_audio_mode", "beep")
            ) if cfg.get("profanity_filter_enabled", True) else ""
        )
        audio_filter = ((profanity_filter + ",") if profanity_filter else "") + "loudnorm=I=-14:TP=-1.5:LRA=11,asetpts=PTS-STARTPTS"
        tmp = f"{name}.tmp.mp4"
        render_prefix = [
            ffmpeg_exe(), "-y", "-v", "error", "-fflags", "+genpts",
            *ffmpeg_cuda_decode_args(),
            "-ss", f"{start:.2f}", "-accurate_seek",
            "-t", f"{end - start:.2f}", "-i", str(pathlib.Path(src).resolve()),
            "-filter_complex", vf, "-map", "[v]",
            *enc, "-pix_fmt", "yuv420p",
        ]
        render_suffix = [
            "-r", "30", "-avoid_negative_ts", "make_zero",
            "-movflags", "+faststart", tmp,
        ]
        # Force a named stereo layout for AAC. FFmpeg's aeval output otherwise
        # reports an unspecified "2 channels" layout that the AAC encoder rejects.
        audio_args = ["-map", "0:a?", "-af", audio_filter, "-ac", "2", "-ar", "48000", "-c:a", "aac", "-b:a", "160k"]
        ass_path = self.out_dir / f"{name}.ass"
        cmd = render_prefix + audio_args + render_suffix
        try:
            r = run(cmd, cwd=self.out_dir, capture_output=True, text=True)
            if r.returncode != 0 and ffmpeg_empty_audio_packets_error(r.stderr):
                # TS input seeking can land on a video keyframe while the AAC
                # packet timeline is offset. Retry with accurate output seeking,
                # preserving the source audio instead of silently dropping it.
                self.log("This clip range contains no usable audio packets. Retrying audio with accurate output seeking.")
                (self.out_dir / tmp).unlink(missing_ok=True)
                precise_prefix = [
                    ffmpeg_exe(), "-y", "-v", "error", "-fflags", "+genpts",
                    *ffmpeg_cuda_decode_args(),
                    "-i", str(pathlib.Path(src).resolve()),
                    "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
                    "-filter_complex", vf, "-map", "[v]",
                    *enc, "-pix_fmt", "yuv420p",
                ]
                cmd = precise_prefix + audio_args + render_suffix
                r = run(cmd, cwd=self.out_dir, capture_output=True, text=True)
                if r.returncode != 0 and ffmpeg_empty_audio_packets_error(r.stderr):
                    raise RuntimeError(
                        "No audio packets were available after accurate output seeking; "
                        "the source recording was kept for retry."
                    )
            if r.returncode != 0:
                raise RuntimeError((r.stderr or "ffmpeg failed").strip()[-400:])
        except Exception:
            (self.out_dir / tmp).unlink(missing_ok=True)
            raise
        finally:
            ass_path.unlink(missing_ok=True)
        transcript = " ".join(
            str(word).strip() for word_start, _word_end, word in words
            if start <= word_start <= end
        )
        transcript = re.sub(r"\s+", " ", transcript).strip()
        tag = streamer_credit(self.cfg)
        post_copy = None
        ai_cfg = {}
        try:
            ai_cfg = getattr(self, "ai_cfg_for_render", None)
            if not isinstance(ai_cfg, dict):
                ai_cfg = load_ai_settings()
            # Reuse the exact provider selected for highlight detection; there is no separate copy provider.
            provider = str(ai_cfg.get("provider", "gemini")).strip().lower()
            if metadata_transcript and provider in {"ollama", "gemini", "huggingface", "custom", "openai", "anthropic"}:
                post_copy = generate_social_copy(metadata_transcript, tag, ai_cfg, log=self.log)
            elif metadata_transcript and provider == "hooks":
                self.log("Hook words is selected; the strongest exact hook phrase is used as the title.")
                hook_terms = dict(load_custom())
                hook_terms.update({term: 1.0 for term in HYPE_WORDS | HYPE_PHRASES})
                post_copy = build_hook_word_copy(metadata_transcript, tag, hook_terms)
        except Exception as exc:
            provider = str(ai_cfg.get("provider", "unknown")).lower()
            self.log(
                f"{provider.title()} post copy unavailable or failed validation; "
                f"using concise transcript fallback: {str(exc)[:220]}"
            )
            if transcript:
                post_copy = build_transcript_fallback(transcript, tag)
        if post_copy and post_copy.get("needs_review"):
            self.log("Transcript copy is low-confidence. Review this clip's title and description before posting.")
        if post_copy and cfg.get("profanity_filter_enabled", True):
            post_copy = dict(post_copy)
            extra_terms = cfg.get("profanity_filter_words", "")
            for key in ("title", "description"):
                if post_copy.get(key):
                    post_copy[key] = censor_profanity_text(post_copy[key], extra_terms=extra_terms)
            if isinstance(post_copy.get("hashtags"), (list, tuple)):
                post_copy["hashtags"] = [censor_profanity_text(tag, extra_terms=extra_terms)
                                          for tag in post_copy["hashtags"]]
        final_video = self.out_dir / f"{name}.mp4"
        self.replace_output(self.out_dir / tmp, final_video)
        try:
            write_clip_metadata_files(
                self.out_dir, final_video.name, pathlib.Path(src).name, start, end,
                transcript, tag, on_warning=self.log,
                post_title=post_copy.get("title") if post_copy else None,
                post_description=post_copy.get("description") if post_copy else None,
                post_hashtags=post_copy.get("hashtags") if post_copy else None,
            )
        except Exception:
            final_video.unlink(missing_ok=True)
            raise
        self.emit("clip", final_video.name)

    def process(self, path):
        if self.cfg.get("creator_id"):
            self.status("Waiting for the shared transcription and AI-analysis slot...", "queued")
        while not PROCESSING_LOCK.acquire(timeout=0.5):
            self.check()
        try:
            self.check()
            self._process(path)
        finally:
            PROCESSING_LOCK.release()

    def _process(self, path):
        pth = pathlib.Path(path)
        stem = re.sub(r"[^A-Za-z0-9_-]", "_", pth.stem)[:40] or "stream"
        creator_id = str(self.cfg.get("creator_id", "")).strip()
        if creator_id:
            source_kind = "vod" if self.cfg.get("mode") == "file" else "live"
            stem = f"{creator_id[:8]}_{source_kind}_{stem}"
        self.status(f"Transcribing {pth.name}...", "transcribing", 0)
        self.log(f"Processing {pth.name}")
        raw_words = self.transcribe(path)
        words = censor_transcript_words(
            raw_words, enabled=self.cfg.get("profanity_filter_enabled", True),
            extra_terms=self.cfg.get("profanity_filter_words", "")
        )
        censored_count = sum(1 for _start, _end, word in words if word == PROFANITY_FILTER_MASK)
        if censored_count:
            self.log(f"Profanity filter: muted and masked {censored_count} detected word(s).")
        self.check()
        if words:
            transcript = " ".join(clean_word(word) for _start, _end, word in words).strip()
            if len(transcript) > 6000:
                transcript = transcript[:5997].rstrip() + "..."
            self.log(f"Transcript words ({len(words)}): {transcript}")
        else:
            self.log("Transcript words (0): no speech words detected.")
        self.status("Finding the hype moments...", "transcribing", 100)
        # Score the original transcript so censoring never hides a high-energy or viral moment.
        # The censored copy is still used for captions, audio muting, and public post metadata.
        peaks, dur = self.find_peaks(path, raw_words)
        self.log(f"Heard {len(words)} words in {dur}s of video. Best moment score {getattr(self, 'best_score', 0):.1f} "
                 f"(clips need {self.cfg['min_score']}).")
        if not words:
            self.log("WARNING: no speech was transcribed - check the speech model / GPU messages above.")
        if not peaks:
            self.log("Chunk too short or silent - nothing to clip.")
        rendered_count = 0
        stamp = time.strftime("%H%M%S")
        for i, (p, sc) in enumerate(peaks, 1):
            self.check()
            clip_duration = int(self.cfg.get("clip_duration", DEFAULTS["clip_duration"]))
            # Put the selected high-virality moment at the opening hook:
            # exactly two seconds of lead-in, then the chosen total duration.
            start, end = clip_bounds(
                p, dur, 2, max(1, clip_duration - 2), raw_words,
                limit=clip_duration, align_to_speech=False,
            )
            base_name = f"{stem}_{stamp}_clip{i}"
            name = base_name
            suffix = 2
            while (self.out_dir / f"{name}.mp4").exists() or (self.out_dir / f"{name}.tmp.mp4").exists():
                name = f"{base_name}_{suffix}"
                suffix += 1
            self.status(f"Rendering clip {i} of {len(peaks)} (hype score {sc:.1f})...", "rendering",
                        int((i - 1) / max(1, len(peaks)) * 100))
            try:
                self.render(path, start, end, words, name, raw_words)
                completed_clip = self.out_dir / f"{name}.mp4"
                if not completed_clip.is_file() or completed_clip.stat().st_size <= 0:
                    raise RuntimeError("The renderer returned without creating a complete clip file.")
                rendered_count += 1
                self.status(f"Rendered clip {i} of {len(peaks)}.", "rendering",
                            int(i / max(1, len(peaks)) * 100))
            except FileBusyError as e:
                self.emit("file_lock", e.details)
            except Exception as e:
                self.log(f"Render error: {e}")
        self.emit("chunk", "")
        # Streamlink's .ts segments are disposable live-capture inputs, but only
        # after at least one finished MP4 exists. Keep silent/no-clip/failed sources
        # available for retry, respect the user's storage toggle, and never delete a
        # VOD or another file type from a user-selected recording folder.
        same_recording_dir = os.path.normcase(str(pth.parent.resolve())) == os.path.normcase(str(self.rec_dir.resolve()))
        is_streamlink_segment = pth.suffix.casefold() == ".ts" and pth.name.startswith("seg_")
        delete_live_source = bool(self.cfg.get("delete_rec", DEFAULTS["delete_rec"]))
        if (
            self.cfg.get("mode", "live") == "live"
            and same_recording_dir
            and is_streamlink_segment
            and delete_live_source
            and rendered_count > 0
        ):
            try:
                pth.unlink(missing_ok=True)
                self.log(
                    f"Deleted temporary live source {pth.name} after verifying "
                    f"{rendered_count} completed clip(s)."
                )
            except OSError as exc:
                self.log(f"Could not delete temporary live source {pth.name}: {exc}")

    # ---- live
    def wait_live(self, url):
        first = True
        while not self.stop_flag:
            try:
                r = run(streamlink_cmd() + [url, STREAM_QUALITY, "--stream-url"], capture_output=True, text=True, env=streamlink_env())
            except OSError as e:
                raise RuntimeError(f"Could not start streamlink: {e}")
            if r.returncode == 0:
                return True
            if "No module named" in (r.stderr or ""):
                raise RuntimeError("streamlink isn't installed in this Python environment. "
                                   "Run:  pip install --only-binary=:all: streamlink   (then start StreamSnip AI again)")
            if first:
                err = (r.stderr or "").strip().splitlines()
                self.log("Not live yet" + (f" ({err[-1][:140]})" if err else "") + " - checking every 30 s.")
                first = False
            self.status("Waiting for the stream to go live...", "waiting")
            for _ in range(30):
                if self.stop_flag: return False
                time.sleep(1)
        return False

    def _tail(self, path, n=3):
        try:
            lines = [l.strip() for l in pathlib.Path(path).read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
            return " | ".join(lines[-n:])[:300]
        except Exception:
            return ""

    def live(self, url):
        """Record -> cut into chunks -> clip each chunk. Reconnects automatically if the stream drops."""
        attempt = 0
        while not self.stop_flag:
            if not self.wait_live(url):
                return
            attempt += 1
            self.log("Stream is live - recording." if attempt == 1 else f"Reconnected (#{attempt}) - recording again.")
            self.record_session(url)
            if self.stop_flag or self.abort:
                break
            self.log("The stream ended or dropped - checking again in 10 s.")
            for _ in range(10):
                if self.stop_flag: break
                time.sleep(1)
        self.log("Recording finished.")

    def record_session(self, url):
        # The recording folder can disappear while StreamSnip AI is running (for example,
        # after a manual cleanup or an antivirus/cleanup tool removes an empty dir).
        # Recreate it immediately before opening the stream log and segment files.
        self.rec_dir.mkdir(parents=True, exist_ok=True)
        run_id = time.strftime("%m%d_%H%M%S") + "_" + re.sub(r"[^A-Za-z0-9_-]", "", str(self.cfg.get("creator_id", "")))[:24]
        pattern = str(self.rec_dir / f"seg_{run_id}_%05d.ts")
        slog_path = self.rec_dir / f"streamlink_{run_id}.log"
        try:
            slog = open(slog_path, "wb")
        except FileNotFoundError:
            # Handle a race where the folder vanished between mkdir and open.
            self.rec_dir.mkdir(parents=True, exist_ok=True)
            slog = open(slog_path, "wb")
        try:
            sl = popen(streamlink_cmd() + ["--stdout", url, STREAM_QUALITY], stdout=subprocess.PIPE, stderr=slog, env=streamlink_env())
        except Exception:
            slog.close()
            raise
        bitrate = int(self.cfg.get("capture_bitrate_kbps", 8000))
        if has_nvenc():
            capture_enc = ["-c:v", "h264_nvenc", "-preset", "p5", "-b:v", f"{bitrate}k",
                           "-maxrate", f"{bitrate}k", "-bufsize", f"{bitrate * 2}k"]
        else:
            capture_enc = ["-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{bitrate}k",
                           "-maxrate", f"{bitrate}k", "-bufsize", f"{bitrate * 2}k"]
        ff = popen([ffmpeg_exe(), "-v", "error", "-i", "-", *capture_enc, "-c:a", "aac", "-b:a", "160k",
                    "-f", "segment", "-segment_time", str(self.seg_seconds), "-reset_timestamps", "1", pattern],
                   stdin=sl.stdout)
        sl.stdout.close()
        self.procs = [sl, ff]
        done = set()
        producers_stopped = False
        observed_segment_sizes = {}
        idle = f"Recording - a clip batch is made every {self.cfg['chunk_min']} min."
        self.status(idle, "recording", 0)
        t0 = time.time(); last_beat = t0; last_growth = t0; last_total = -1; warned = False
        try:
            while not self.abort:
                segs = sorted(glob.glob(str(self.rec_dir / f"seg_{run_id}_*.ts")))
                recording = ff.poll() is None and not self.stop_flag
                if self.stop_flag and not producers_stopped:
                    producers_stopped = True
                    self.status("Stopping the live source and closing the final recording...", "stopping")
                    try:
                        sl.terminate()
                    except Exception:
                        pass
                    try:
                        ff.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        try:
                            ff.terminate()
                        except Exception:
                            pass
                        try:
                            ff.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            try:
                                ff.kill()
                            except Exception:
                                pass
                            try:
                                ff.wait(timeout=5)
                            except Exception:
                                pass
                    try:
                        sl.wait(timeout=5)
                    except Exception:
                        pass
                    recording = False
                # progress heartbeat + stall detection
                for segment in segs:
                    try:
                        observed_segment_sizes[segment] = max(
                            observed_segment_sizes.get(segment, 0),
                            os.path.getsize(segment),
                        )
                    except OSError:
                        pass
                total = sum(observed_segment_sizes.values())
                if total > last_total:
                    last_total = total; last_growth = time.time(); warned = False
                if recording and not warned and time.time() - last_growth > STALL_SECONDS:
                    self.log(f"WARNING: no new video data for {STALL_SECONDS} s - the stream may be stuck on ads. "
                             f"streamlink says: {self._tail(slog_path) or '(nothing)'}")
                    warned = True
                if recording:
                    elapsed = int(time.time() - t0)
                    batch_elapsed = elapsed % self.seg_seconds
                    left = max(0, self.seg_seconds - batch_elapsed)
                    self.status(f"Recording... {total / 1048576:.0f} MB captured; next clip batch in about "
                                f"{left // 60}:{left % 60:02d}.", "recording",
                                int(batch_elapsed / max(1, self.seg_seconds) * 100))
                if recording and time.time() - last_beat >= 60:
                    last_beat = time.time()
                    left = max(0, self.seg_seconds - int(time.time() - t0) % self.seg_seconds)
                    self.log(f"Recording... {total / 1048576:.0f} MB captured, next clip batch in about {left // 60}:{left % 60:02d}.")
                finished = segs if not recording else segs[:-1]
                for sg in finished:
                    if sg in done: continue
                    done.add(sg)
                    try:
                        if os.path.getsize(sg) > 200_000:
                            self.process(sg)
                        else:
                            self.log(f"Skipped a tiny recording piece ({os.path.basename(sg)}).")
                            os.remove(sg)
                    except Stopped:
                        return
                    except Exception as e:
                        self.log(f"Error on {os.path.basename(sg)}: {e}")
                    if ff.poll() is None and not self.stop_flag:
                        self.status(idle, "recording", 0)
                    elif not self.abort:
                        self.status("Wrapping up the clips already recorded...", "stopping")
                if not recording and set(segs) <= done:
                    break
                time.sleep(3)
            if time.time() - t0 < 20 and not self.stop_flag:
                self.log(f"Recording stopped after a few seconds. streamlink says: {self._tail(slog_path) or '(nothing)'}")
        finally:
            for pr in (sl, ff):
                terminate_process_tree(pr, force=True)
            try: slog.close()
            except Exception: pass
            for fpath in glob.glob(str(self.rec_dir / f"streamlink_{run_id}.log")):
                try: os.remove(fpath)
                except Exception: pass

    def run(self):
        try:
            if self.cfg["mode"] == "live":
                self.live(self.cfg["target"])
            else:
                self.process(self.cfg["target"])
        except Stopped:
            self.log("Stopped.")
        except Exception as e:
            self.log(f"ERROR: {e}")
        finally:
            for p in list(self.procs):
                terminate_process_tree(p, force=True)
            self.procs = []
            self.emit("done", "")

# ------------------------------------------------------------------ app core (state shared with the UI)
CLIP_RE = re.compile(r"^[A-Za-z0-9_\-]+\.mp4$")
LOCK_FILE_RE = re.compile(r"^[A-Za-z0-9_\-]+(?:\.tmp\.mp4|\.mp4|\.txt)$")
VOD_EXTENSIONS = {".mp4", ".mkv", ".mov", ".ts", ".flv", ".webm", ".avi", ".m4v"}
QUIT = threading.Event()
_WINDOW_CLOSE_LOCK = threading.RLock()
_WINDOW_CLOSE_TIMER = None
_WINDOW_LEASES = set()
# A close request may arrive just before its streaming lease starts. Keep a
# bounded tombstone set so that late requests cannot resurrect a closed window.
_WINDOW_CLOSED_LEASES = set()
_WINDOW_CLOSED_LEASE_LIMIT = 512

def cancel_window_close_shutdown():
    global _WINDOW_CLOSE_TIMER
    with _WINDOW_CLOSE_LOCK:
        timer, _WINDOW_CLOSE_TIMER = _WINDOW_CLOSE_TIMER, None
    if timer:
        timer.cancel()

def schedule_window_close_shutdown(delay=3.0):
    """Quit after the final app window closes, unless a quick reload reconnects."""
    global _WINDOW_CLOSE_TIMER
    cancel_window_close_shutdown()
    def close_if_still_gone():
        global _WINDOW_CLOSE_TIMER
        with _WINDOW_CLOSE_LOCK:
            if _WINDOW_LEASES:
                _WINDOW_CLOSE_TIMER = None
                return
            _WINDOW_CLOSE_TIMER = None
        try:
            CORE.stop(True)
            CORE.stop_all_creators()
        except (NameError, AttributeError):
            pass
        QUIT.set()
    timer = threading.Timer(delay, close_if_still_gone)
    timer.daemon = True
    with _WINDOW_CLOSE_LOCK:
        if _WINDOW_LEASES:
            return
        _WINDOW_CLOSE_TIMER = timer
    timer.start()

def begin_window_lease(lease_id=None):
    """Register one browser window; return None if that window already closed."""
    lease = str(lease_id or secrets.token_urlsafe(18)).strip()[:128]
    if not lease:
        lease = secrets.token_urlsafe(18)
    with _WINDOW_CLOSE_LOCK:
        if lease in _WINDOW_CLOSED_LEASES:
            return None
        _WINDOW_LEASES.add(lease)
    cancel_window_close_shutdown()
    return lease

def end_window_lease(lease):
    """Release a streaming lease. Safe to call after an explicit close request."""
    if lease is None:
        return
    with _WINDOW_CLOSE_LOCK:
        _WINDOW_CLOSED_LEASES.discard(lease)
        _WINDOW_LEASES.discard(lease)
        empty = not _WINDOW_LEASES
    if empty and not QUIT.is_set():
        schedule_window_close_shutdown()

def close_window_lease(lease_id):
    """Release the exact browser window immediately when pagehide is reported."""
    lease = str(lease_id or "").strip()[:128]
    if not lease:
        return False
    with _WINDOW_CLOSE_LOCK:
        was_active = lease in _WINDOW_LEASES
        _WINDOW_LEASES.discard(lease)
        _WINDOW_CLOSED_LEASES.add(lease)
        while len(_WINDOW_CLOSED_LEASES) > _WINDOW_CLOSED_LEASE_LIMIT:
            _WINDOW_CLOSED_LEASES.pop()
        empty = not _WINDOW_LEASES
    if empty and not QUIT.is_set():
        schedule_window_close_shutdown()
    return was_active

class Core:
    def __init__(self):
        self.lock = threading.RLock()
        self.publishing = load_publishing_settings()
        self.zernio = self.publishing["zernio"]
        self.publisher = self._make_publisher(self.publishing["provider"])
        self.engine = None
        self.worker = None
        self.running = False
        self.logs, self.log_id = [], 0
        self.phase, self.status = "idle", "Ready when you are."
        self.progress = 0
        self.posting = {"active": False, "total": 0, "completed": 0, "current": "",
                        "started": None, "done": 0, "last_name": "", "errors": 0}
        self.session = {"clips": 0, "chunks": 0, "started": None, "ended": None}
        self.settings = load_settings()
        self.default_settings = clean_cfg(self.settings)
        self.default_settings.pop("creator_id", None)
        apply_storage_paths(self.settings)
        self._init_creator_database()
        self.creators = self._load_creator_profiles()
        self.creator_workers = {}
        self.creator_engines = {}
        self.creator_status = {}
        self.creator_watchers = {}
        self.creator_watch_events = {}
        self.creator_vod_engines = {}
        if STORAGE_PATH_WARNING:
            save_settings(self.settings)
            self.push(STORAGE_PATH_WARNING)

    def _creator_profiles_path(self):
        # Legacy import source only. Creator records now live in SQLite.
        return _data_root / "creators.json"

    def _creator_default_settings(self):
        return clean_cfg(getattr(self, "default_settings", getattr(self, "settings", {})))

    def _creator_profile_defaults(self):
        # New creator records contain only personal framing and visual caption treatment.
        # Video layout, output aspect, AI/caption providers, and clipping stay global.
        defaults = clean_cfg(DEFAULTS)
        return {key: defaults[key] for key in CREATOR_PROFILE_SETTING_KEYS}
    @contextmanager
    def _creator_db(self):
        _data_root.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(_data_root / "streamsnip.db"), timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            with connection:
                yield connection
        finally:
            connection.close()

    def _init_creator_database(self):
        with self._creator_db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS creators (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, target TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            db.execute("""CREATE TABLE IF NOT EXISTS creator_settings (
                creator_id TEXT PRIMARY KEY REFERENCES creators(id) ON DELETE CASCADE,
                settings_json TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            # One-time, idempotent migration from the old JSON creator registry.
            legacy_path = self._creator_profiles_path()
            remove_legacy = False
            if legacy_path.is_file():
                try:
                    legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
                    remove_legacy = isinstance(legacy, list)
                except (OSError, ValueError, TypeError):
                    legacy = []
                if isinstance(legacy, list):
                    for item in legacy[:100]:
                        if not isinstance(item, dict):
                            continue
                        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(item.get("id", "")))[:48]
                        name = re.sub(r"[\n\x00-\x1f]", "", str(item.get("name", ""))).strip()[:80]
                        target = str(item.get("target", "")).strip()[:1000]
                        if creator_id and name and target:
                            db.execute("INSERT OR IGNORE INTO creators(id,name,target) VALUES(?,?,?)",
                                       (creator_id, name, target))
            default_settings = json.dumps(self._creator_profile_defaults(), ensure_ascii=False)
            db.execute("""INSERT OR IGNORE INTO creator_settings(creator_id,settings_json)
                SELECT id, ? FROM creators""", (default_settings,))

            # Compact legacy full-config profile rows in place. Keep every validated
            # creator-owned visual preference, and discard duplicated shared/default
            # settings so the global provider and clipping defaults remain authoritative.
            rows = db.execute("SELECT creator_id,settings_json FROM creator_settings").fetchall()
            for row in rows:
                try:
                    stored = json.loads(row["settings_json"])
                except (ValueError, TypeError):
                    stored = {}
                profile = creator_profile_values(stored)
                compacted = json.dumps(profile, ensure_ascii=False, sort_keys=True)
                if compacted != row["settings_json"]:
                    db.execute(
                        "UPDATE creator_settings SET settings_json=?,updated_at=CURRENT_TIMESTAMP WHERE creator_id=?",
                        (compacted, row["creator_id"]),
                    )
        # The database is now authoritative; remove the migrated JSON registry.
        if remove_legacy:
            try:
                legacy_path.unlink(missing_ok=True)
            except OSError:
                pass

    def _load_creator_profiles(self):
        with self._creator_db() as db:
            rows = db.execute("SELECT id,name,target FROM creators ORDER BY created_at,id").fetchall()
        return {row["id"]: {"id": row["id"], "name": row["name"], "target": row["target"]}
                for row in rows}

    def _save_creator_profiles(self):
        # Synchronize the in-memory registry transactionally; FK cascade removes settings
        # for deleted creators while preserving every other creator's configuration.
        with self._creator_db() as db:
            current_ids = set(self.creators)
            existing_ids = {row[0] for row in db.execute("SELECT id FROM creators")}
            for creator_id in existing_ids - current_ids:
                db.execute("DELETE FROM creators WHERE id=?", (creator_id,))
            for creator_id, profile in self.creators.items():
                db.execute("""INSERT INTO creators(id,name,target) VALUES(?,?,?)
                    ON CONFLICT(id) DO UPDATE SET name=excluded.name,target=excluded.target""",
                    (creator_id, profile["name"], profile["target"]))
                db.execute("INSERT OR IGNORE INTO creator_settings(creator_id,settings_json) VALUES(?,?)",
                           (creator_id, json.dumps(self._creator_profile_defaults(), ensure_ascii=False)))

    def get_creator_settings(self, creator_id):
        self._init_creator_database()
        if creator_id not in self.creators:
            raise ValueError("Creator monitor not found.")
        with self._creator_db() as db:
            row = db.execute("SELECT settings_json FROM creator_settings WHERE creator_id=?", (creator_id,)).fetchone()
        stored = {}
        if row:
            try:
                stored = json.loads(row["settings_json"])
            except (ValueError, TypeError):
                stored = {}
        profile = {**self._creator_profile_defaults(), **creator_profile_values(stored)}
        shared = self._creator_default_settings()
        merged = {**shared, **profile}
        merged["mode"] = "live"
        merged["target"] = self.creators[creator_id]["target"]
        merged["creator_id"] = creator_id
        return clean_cfg(merged)

    def save_creator_settings(self, creator_id, settings):
        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(creator_id))[:48]
        if creator_id not in self.creators:
            raise ValueError("Creator monitor not found.")
        self._init_creator_database()
        incoming = settings if isinstance(settings, dict) else {}

        # AI provider remains in its separate global AI settings object. Caption/transcription,
        # video layout/aspect, and clipping settings are shared; visual caption/profanity treatment is per creator.
        shared_updates = {key: incoming[key] for key in CREATOR_SHARED_SETTING_KEYS if key in incoming}
        if shared_updates:
            defaults = self._creator_default_settings()
            validated_shared = clean_cfg({**defaults, **shared_updates})
            for key in shared_updates:
                defaults[key] = validated_shared[key]
            self.default_settings = clean_cfg(defaults)
            current = clean_cfg(getattr(self, "settings", defaults))
            for key in shared_updates:
                current[key] = self.default_settings[key]
            self.settings = clean_cfg(current)
            save_settings(self.default_settings)

        with self._creator_db() as db:
            row = db.execute("SELECT settings_json FROM creator_settings WHERE creator_id=?", (creator_id,)).fetchone()
            existing = {}
            if row:
                try:
                    existing = json.loads(row["settings_json"])
                except (ValueError, TypeError):
                    existing = {}
            profile = {**self._creator_profile_defaults(), **creator_profile_values(existing)}
            profile.update(creator_profile_values(incoming))
            # Persist only facecam/game geometry and visual caption/profanity treatment.
            # Legacy full-config rows discard duplicated shared defaults on the next save.
            db.execute("INSERT INTO creators(id,name,target) VALUES(?,?,?) "
                       "ON CONFLICT(id) DO UPDATE SET name=excluded.name,target=excluded.target",
                       (creator_id, self.creators[creator_id]["name"], self.creators[creator_id]["target"]))
            db.execute("""INSERT INTO creator_settings(creator_id,settings_json,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(creator_id) DO UPDATE SET settings_json=excluded.settings_json,updated_at=CURRENT_TIMESTAMP""",
                (creator_id, json.dumps(profile, ensure_ascii=False)))
        result = self.get_creator_settings(creator_id)
        # Runtime output paths are supplied by Core.start, not persisted in a profile.
        for key in ("creator_out_dir", "creator_rec_dir"):
            if key in incoming:
                result[key] = incoming[key]
        return result

    def _creator_paths(self, creator_id):
        profile = getattr(self, "creators", {}).get(creator_id, {})
        slug = re.sub(r"[^A-Za-z0-9_-]+", "_", str(profile.get("name", "creator"))).strip("_")[:40] or "creator"
        root = _data_root / "creators" / f"{slug}_{creator_id}"
        return {
            "root": root,
            "live_clips": root / "live" / "clips",
            "live_recordings": root / "live" / "recordings",
            "vod_inbox": root / "recorded-vods" / "watch",
            "vod_clips": root / "recorded-vods" / "clips",
            "vod_processed": root / "recorded-vods" / "processed",
            "vod_failed": root / "recorded-vods" / "failed",
        }

    def _ensure_creator_paths(self, creator_id):
        paths = self._creator_paths(creator_id)
        # Migrate folders created by the earlier ID-only layout without overwriting data.
        legacy = _data_root / "creators" / creator_id
        for old_name, new_key in (("clips", "live_clips"), ("recordings", "live_recordings")):
            old_folder, new_folder = legacy / old_name, paths[new_key]
            if old_folder.is_dir() and not new_folder.exists():
                new_folder.parent.mkdir(parents=True, exist_ok=True)
                try:
                    os.replace(old_folder, new_folder)
                except OSError:
                    pass
        for folder in paths.values():
            folder.mkdir(parents=True, exist_ok=True)
        return paths

    def list_creators(self):
        with self.lock:
            result = []
            active_engine = getattr(self, "engine", None)
            active_cfg = getattr(active_engine, "cfg", {}) or {}
            capture_running = bool(getattr(self, "running", False) and active_cfg.get("mode") == "live")
            capture_creator_id = str(active_cfg.get("creator_id") or "").strip()
            capture_target = ""
            if capture_running and not capture_creator_id:
                try:
                    capture_target = normalize_stream_target(str(active_cfg.get("target") or ""))
                except (TypeError, ValueError):
                    capture_target = ""
            for creator_id, profile in self.creators.items():
                status = dict(self.creator_status.get(creator_id, {}))
                paths = self._ensure_creator_paths(creator_id)
                try:
                    status["live_clips"] = sum(1 for item in paths["live_clips"].glob("*.mp4") if CLIP_RE.match(item.name))
                    status["vod_clips"] = sum(1 for item in paths["vod_clips"].glob("*.mp4") if CLIP_RE.match(item.name))
                    status["vod_pending"] = sum(1 for item in paths["vod_inbox"].iterdir() if item.is_file() and item.suffix.lower() in VOD_EXTENSIONS)
                except OSError:
                    status.setdefault("live_clips", 0)
                    status.setdefault("vod_clips", 0)
                    status.setdefault("vod_pending", 0)
                watcher = getattr(self, "creator_watchers", {}).get(creator_id)
                capture_active = False
                if capture_running:
                    if capture_creator_id:
                        capture_active = capture_creator_id == creator_id
                    elif capture_target:
                        try:
                            capture_active = normalize_stream_target(profile.get("target", "")) == capture_target
                        except (TypeError, ValueError):
                            capture_active = False
                result.append({**profile, **status,
                               "running": bool(self.creator_workers.get(creator_id) and self.creator_workers[creator_id].is_alive()),
                               "capture_active": bool(capture_active),
                               "capture_stopping": bool(capture_active and getattr(active_engine, "stop_flag", False)),
                               "watching_vods": bool(watcher and watcher.is_alive())})
            return result

    def add_creator(self, body):
        name = re.sub(r"[\n\x00-\x1f]", "", str(body.get("name", ""))).strip()[:80]
        target = normalize_stream_target(str(body.get("target", "")).strip()[:1000])
        if not name:
            raise ValueError("Give this creator a name.")
        if not re.match(r"https?://", target):
            raise ValueError("Enter a Twitch or YouTube stream URL.")
        host = (urllib.parse.urlparse(target).hostname or "").lower()
        if not (host == "twitch.tv" or host.endswith(".twitch.tv")
                or host == "youtube.com" or host.endswith(".youtube.com")
                or host == "youtu.be"):
            raise ValueError("Use a Twitch or YouTube stream URL.")
        if not streamlink_available():
            raise ValueError("streamlink is not installed. Run: pip install streamlink")
        with self.lock:
            if len(self.creators) >= 100:
                raise ValueError("Creator limit reached (100).")
            creator_id = uuid.uuid4().hex[:12]
            self.creators[creator_id] = {"id": creator_id, "name": name, "target": target}
            self.creator_status[creator_id] = {"phase": "offline", "status": "Saved; not monitoring.", "clips": 0}
            self._save_creator_profiles()
        self.push(f"Added creator monitor: {name}.")
        return {"creator": self.list_creators()[-1]}

    def open_creator_folder(self, creator_id, folder_kind="live_clips"):
        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(creator_id))[:48]
        with self.lock:
            if creator_id not in self.creators:
                raise ValueError("Creator monitor not found.")
        paths = self._ensure_creator_paths(creator_id)
        folder = paths.get(str(folder_kind))
        if folder is None:
            raise ValueError("Unknown creator folder.")
        open_folder(folder)
        return {"ok": True}

    def open_creators_folder(self):
        """Open the common parent containing every creator's clips and recordings."""
        folder = _data_root / "creators"
        folder.mkdir(parents=True, exist_ok=True)
        open_folder(folder)
        return {"ok": True, "path": str(folder)}

    def start_vod_watch(self, creator_id):
        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(creator_id))[:48]
        with self.lock:
            if creator_id not in self.creators:
                raise ValueError("Creator monitor not found.")
            current = self.creator_watchers.get(creator_id)
            if current and current.is_alive():
                raise ValueError("This creator's VOD folder is already being watched.")
            paths = self._ensure_creator_paths(creator_id)
            stop_event = threading.Event()
            self.creator_watch_events[creator_id] = stop_event
            self.creator_status.setdefault(creator_id, {})["vod_status"] = "Watching recorded-VOD inbox..."
            worker = threading.Thread(target=self._watch_vod_folder, args=(creator_id, stop_event),
                                      daemon=True, name=f"vod-watch-{creator_id}")
            self.creator_watchers[creator_id] = worker
            worker.start()
        self.push(f"Watching recorded-VOD folder for {self.creators[creator_id]['name']}: {paths['vod_inbox']}")
        return {"ok": True}

    def stop_vod_watch(self, creator_id):
        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(creator_id))[:48]
        with self.lock:
            event = self.creator_watch_events.get(creator_id)
            worker = self.creator_watchers.get(creator_id)
            engine = self.creator_vod_engines.get(creator_id)
            if not event or not worker or not worker.is_alive():
                raise ValueError("This creator's VOD folder is not being watched.")
            event.set()
            if engine:
                engine.stop(force=True)
            self.creator_status.setdefault(creator_id, {})["vod_status"] = "Stopping VOD folder watcher..."
        return {"ok": True}

    def _watch_vod_folder(self, creator_id, stop_event):
        paths = self._ensure_creator_paths(creator_id)
        stable = {}
        try:
            while not stop_event.is_set():
                try:
                    candidates = sorted(p for p in paths["vod_inbox"].iterdir()
                                        if p.is_file() and p.suffix.lower() in VOD_EXTENSIONS)
                except OSError as exc:
                    self.push(f"[{self.creators.get(creator_id, {}).get('name', creator_id)}] VOD folder error: {exc}")
                    stop_event.wait(3)
                    continue
                ready = None
                for item in candidates:
                    try:
                        stat = item.stat()
                        fingerprint = (stat.st_size, stat.st_mtime_ns)
                    except OSError:
                        continue
                    previous, count = stable.get(str(item), (None, 0))
                    count = count + 1 if previous == fingerprint else 0
                    stable[str(item)] = (fingerprint, count)
                    if count >= 2 and stat.st_size > 0:
                        ready = item
                        break
                if ready is None:
                    stop_event.wait(2)
                    continue
                profile = self.creators.get(creator_id, {"name": creator_id})
                self.creator_status.setdefault(creator_id, {})["vod_status"] = f"Processing {ready.name}"
                cfg = clean_cfg({**self.settings, "mode": "file", "target": str(ready),
                                 "creator_id": creator_id,
                                 "creator_out_dir": str(paths["vod_clips"]),
                                 "creator_rec_dir": str(paths["live_recordings"]),
                                 "delete_rec": False})
                engine = Engine(cfg, lambda kind, payload, cid=creator_id: self.emit_vod(cid, kind, payload))
                with self.lock:
                    self.creator_vod_engines[creator_id] = engine
                try:
                    engine.process(str(ready))
                    if stop_event.is_set():
                        break
                    destination = paths["vod_processed"] / ready.name
                    suffix = 2
                    while destination.exists():
                        destination = paths["vod_processed"] / f"{ready.stem}_{suffix}{ready.suffix}"
                        suffix += 1
                    ready.replace(destination)
                    self.push(f"[{profile['name']}] Recorded VOD processed: {destination.name}")
                    self.creator_status.setdefault(creator_id, {})["vod_status"] = "Watching recorded-VOD inbox..."
                except Stopped:
                    break
                except Exception as exc:
                    self.push(f"[{profile['name']}] VOD processing failed for {ready.name}: {exc}")
                    try:
                        destination = paths["vod_failed"] / ready.name
                        suffix = 2
                        while destination.exists():
                            destination = paths["vod_failed"] / f"{ready.stem}_{suffix}{ready.suffix}"
                            suffix += 1
                        ready.replace(destination)
                    except OSError:
                        pass
                    self.creator_status.setdefault(creator_id, {})["vod_status"] = f"Failed: {ready.name}"
                finally:
                    with self.lock:
                        self.creator_vod_engines.pop(creator_id, None)
                    stable.pop(str(ready), None)
        finally:
            self.creator_status.setdefault(creator_id, {})["vod_status"] = "VOD folder watcher stopped."
            self.push(f"[{self.creators.get(creator_id, {}).get('name', creator_id)}] VOD folder watcher stopped.")

    def remove_creator(self, creator_id):
        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(creator_id))[:48]
        with self.lock:
            worker = self.creator_workers.get(creator_id)
            watcher = getattr(self, "creator_watchers", {}).get(creator_id)
            if worker and worker.is_alive():
                raise ValueError("Stop this creator's live monitor before removing it.")
            if watcher and watcher.is_alive():
                raise ValueError("Stop this creator's VOD folder watcher before removing it.")
            profile = self.creators.pop(creator_id, None)
            self.creator_status.pop(creator_id, None)
            self.creator_workers.pop(creator_id, None)
            self.creator_engines.pop(creator_id, None)
            if not profile:
                raise ValueError("Creator monitor not found.")
            self._save_creator_profiles()
        self.push(f"Removed creator monitor: {profile['name']}. Its recordings and clips were kept.")
        return {"ok": True}

    def start_creator(self, creator_id):
        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(creator_id))[:48]
        with self.lock:
            profile = self.creators.get(creator_id)
            worker = self.creator_workers.get(creator_id)
            if not profile:
                raise ValueError("Creator monitor not found.")
            active_engine = getattr(self, "engine", None)
            active_cfg = getattr(active_engine, "cfg", {}) or {}
            if self.running and active_cfg.get("mode") == "live":
                try:
                    same_source = normalize_stream_target(active_cfg.get("target", "")) == normalize_stream_target(profile.get("target", ""))
                except (TypeError, ValueError):
                    same_source = False
                if same_source:
                    raise ValueError("This creator is already being captured in Live Studio. Stop that capture before starting a background monitor.")
            if worker and worker.is_alive():
                raise ValueError("This creator is already being monitored.")
            active = sum(1 for thread in self.creator_workers.values() if thread.is_alive())
            if active >= MAX_ACTIVE_CREATOR_MONITORS:
                raise ValueError(f"All {MAX_ACTIVE_CREATOR_MONITORS} creator monitor slots are active. Stop one before starting another.")
            paths = self._ensure_creator_paths(creator_id)
            creator_settings = self.get_creator_settings(creator_id)
            cfg = clean_cfg({**creator_settings, "mode": "live", "target": profile["target"],
                             "creator_id": creator_id,
                             "creator_out_dir": str(paths["live_clips"]),
                             "creator_rec_dir": str(paths["live_recordings"])})
            engine = Engine(cfg, lambda kind, payload, cid=creator_id: self.emit_creator(cid, kind, payload))
            self.creator_engines[creator_id] = engine
            self.creator_status[creator_id] = {"phase": "waiting", "status": "Starting monitor...", "clips": 0}
            thread = threading.Thread(target=engine.run, daemon=True, name=f"creator-{creator_id}")
            self.creator_workers[creator_id] = thread
            thread.start()
        self.push(f"Started monitoring {profile['name']}.")
        return {"ok": True}

    def stop_creator(self, creator_id, force=False):
        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(creator_id))[:48]
        with self.lock:
            engine = self.creator_engines.get(creator_id)
            worker = self.creator_workers.get(creator_id)
            if not engine or not worker or not worker.is_alive():
                raise ValueError("This creator monitor is not running.")
            if getattr(engine, "stop_flag", False):
                return {"ok": True, "stopping": True}
            engine.stop(force=bool(force))
            self.creator_status[creator_id] = {"phase": "stopping", "status": "Stopping monitor...",
                                               "clips": self.creator_status.get(creator_id, {}).get("clips", 0)}
        return {"ok": True, "stopping": True}

    def stop_creator_capture(self, creator_id, force=False):
        """Stop Live Studio capture only when it belongs to the requested saved creator."""
        creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(creator_id))[:48]
        with self.lock:
            profile = self.creators.get(creator_id)
            if not profile:
                raise ValueError("Creator monitor not found.")
            engine = getattr(self, "engine", None)
            cfg = getattr(engine, "cfg", {}) or {}
            if not engine or not getattr(self, "running", False) or cfg.get("mode") != "live":
                raise ValueError("This creator does not have an active Live Studio capture.")
            active_creator_id = str(cfg.get("creator_id") or "").strip()
            if active_creator_id:
                matches_creator = active_creator_id == creator_id
            else:
                # Older sessions may not have stored creator_id. Match their canonical URL.
                try:
                    def target_key(value):
                        parsed = urllib.parse.urlsplit(normalize_stream_target(str(value or "")))
                        host = (parsed.hostname or "").lower()
                        if host.startswith("www."):
                            host = host[4:]
                        path = parsed.path.rstrip("/")
                        if host.endswith("twitch.tv"):
                            path = path.lower()
                        return parsed.scheme.lower(), host, parsed.port, path, parsed.query

                    matches_creator = target_key(cfg.get("target")) == target_key(profile.get("target"))
                except (TypeError, ValueError):
                    matches_creator = False
            if not matches_creator:
                raise ValueError("This creator is not the active Live Studio capture.")
            if getattr(engine, "stop_flag", False):
                return {"ok": True, "stopping": True}
            engine.stop(force=bool(force))
            self.push(
                f"Stopping the Live Studio capture for {profile['name']}."
                if force else
                f"Stopping the Live Studio capture for {profile['name']} and finishing clips already captured."
            )
        return {"ok": True, "stopping": True}

    def stop_all_creators(self):
        with self.lock:
            active = [(creator_id, engine) for creator_id, engine in self.creator_engines.items()
                      if self.creator_workers.get(creator_id) and self.creator_workers[creator_id].is_alive()]
            for creator_id, engine in active:
                engine.stop(force=True)
                state = self.creator_status.setdefault(creator_id, {})
                state["phase"], state["status"] = "stopping", "Stopping monitor..."
            for creator_id, event in getattr(self, "creator_watch_events", {}).items():
                if event:
                    event.set()
                engine = getattr(self, "creator_vod_engines", {}).get(creator_id)
                if engine:
                    engine.stop(force=True)
        return len(active)

    def emit_vod(self, creator_id, kind, payload):
        with self.lock:
            profile = self.creators.get(creator_id, {"name": creator_id})
            state = self.creator_status.setdefault(creator_id, {})
            if kind == "status":
                state["vod_status"] = payload[1]
                if len(payload) > 2:
                    state["vod_progress"] = payload[2]
            elif kind == "clip":
                state["vod_clips_generated"] = int(state.get("vod_clips_generated", 0)) + 1
            elif kind == "chunk":
                state["vod_chunks"] = int(state.get("vod_chunks", 0)) + 1
        if kind == "log":
            self.push(f"[{profile['name']} · VOD] {payload}")
        elif kind == "clip":
            self.push(f"[{profile['name']} · VOD] Clip ready: {payload}")
            if self.publisher:
                try:
                    clip_path = find_clip_path(payload)
                    if clip_path:
                        self.publisher.submit(clip_path)
                except Exception as exc:
                    self.push(f"[{profile['name']} · VOD] Auto-post error: {exc}")
        elif kind == "file_lock":
            self.push_file_lock(payload)

    def emit_creator(self, creator_id, kind, payload):
        with self.lock:
            profile = self.creators.get(creator_id, {"name": creator_id})
            state = self.creator_status.setdefault(creator_id, {"clips": 0})
            if kind == "status":
                state["phase"], state["status"] = payload[0], payload[1]
                if len(payload) > 2:
                    state["progress"] = payload[2]
            elif kind == "clip":
                state["clips"] = int(state.get("clips", 0)) + 1
                state["last_clip"] = payload
            elif kind == "chunk":
                state["chunks"] = int(state.get("chunks", 0)) + 1
            elif kind == "done":
                state["phase"], state["status"] = "offline", "Monitor stopped."
                state.pop("progress", None)
        if kind == "log":
            self.push(f"[{profile['name']}] {payload}")
        elif kind == "clip":
            self.push(f"[{profile['name']}] Clip ready: {payload}")
            if self.publisher:
                try:
                    clip_path = find_clip_path(payload)
                    if clip_path:
                        self.publisher.submit(clip_path)
                except Exception as exc:
                    self.push(f"[{profile['name']}] Auto-post error: {exc}")
        elif kind == "file_lock":
            self.push_file_lock(payload)
        elif kind == "done":
            self.push(f"[{profile['name']}] Monitor stopped.")

    def _config_for(self, provider=None):
        return self.publishing.get("zernio", {})

    def _make_publisher(self, provider=None, enabled=None):
        provider = "zernio"
        if enabled is None:
            enabled = bool(self._config_for().get("auto_post", False))
        cfg = dict(self._config_for(), enabled=enabled, idempotency_path=str(ZERNIO_IDEMPOTENCY_FILE))
        if not ZERNIO_AVAILABLE:
            return None
        connections = cfg.get("connections")
        if isinstance(connections, list) and connections and ZernioMultiPublisher:
            return ZernioMultiPublisher(
                self.push, connections,
                on_success=lambda path, platforms, records=None: record_zernio_posted(path.name, platforms, records),
                on_scheduled=lambda path, platforms, records=None: record_zernio_scheduled(path.name, platforms, records),
                on_account_success=self._record_zernio_account_success,
                on_account_error=self._record_zernio_account_error,
                on_account_resume=self._record_zernio_account_resume,
                enabled=enabled, visibility=cfg.get("visibility", "public"),
                schedule_minutes=cfg.get("schedule_minutes", 0),
                idempotency_path=ZERNIO_IDEMPOTENCY_FILE,
            )
        return ZernioPublisher(
            self.push, cfg,
            on_success=lambda path, destinations, records=None: record_zernio_posted(path.name, destinations, records),
            on_scheduled=lambda path, destinations, records=None: record_zernio_scheduled(path.name, destinations, records),
        )

    def _record_zernio_account_success(self, account):
        self._update_zernio_account_state(
            account, last_error="", rate_limited=False,
            rate_limited_auto_paused=False, rate_limit_until=None,
        )

    def _record_zernio_account_resume(self, account):
        self._update_zernio_account_state(
            account, posting_enabled=True, rate_limited=False,
            rate_limited_auto_paused=False, rate_limit_until=None, last_error="",
        )

    def _record_zernio_account_error(self, account, error):
        message = str(error)[:400]
        rate_limited = is_zernio_rate_limit(error)
        updates = {"last_error": message, "rate_limited": rate_limited}
        if rate_limited:
            updates.update({
                "posting_enabled": False,
                "rate_limited_auto_paused": True,
                "rate_limit_until": zernio_rate_limit_until(error),
            })
        self._update_zernio_account_state(account, **updates)

    def _update_zernio_account_state(self, account, **updates):
        connection_id = str(account.get("connection_id", ""))
        account_id = str(account.get("id", ""))
        if not connection_id or not account_id:
            return
        with self.lock:
            cfg = dict(self._config_for())
            connections = self._configured_zernio_connections(cfg)
            connection = next((item for item in connections if str(item.get("id")) == connection_id), None)
            if not connection:
                return
            saved = next((item for item in connection.get("accounts", [])
                          if isinstance(item, dict) and str(item.get("id")) == account_id), None)
            if saved is None:
                return
            saved.update(updates)
            cfg["connections"] = connections
            self.publishing["zernio"] = cfg
            self.zernio = cfg
            save_publishing_settings(self.publishing)

    def _provider_status(self, provider):
        cfg = self._config_for()
        connected = bool(cfg.get("api_key")) or any(
            isinstance(item, dict) and str(item.get("api_key", "")).strip()
            for item in cfg.get("connections", [])
        )
        return {"configured": connected, "api_key_set": connected,
                "available": ZERNIO_AVAILABLE, "base_url": "https://zernio.com"}

    def push(self, msg):
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            self.log_id += 1
            message = _redact_runtime_log_message(msg)
            self.logs.append((self.log_id, timestamp, message, None))
            append_runtime_log(timestamp, message)
            if len(self.logs) > 800:
                del self.logs[:200]

    def push_file_lock(self, details):
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            self.log_id += 1
            message = _redact_runtime_log_message(details["message"])
            self.logs.append((self.log_id, timestamp, message,
                              details.get("file_lock")))
            append_runtime_log(timestamp, message)
            if len(self.logs) > 800:
                del self.logs[:200]

    def emit(self, kind, payload):
        if kind == "log":
            self.push(payload)
        elif kind == "status":
            with self.lock:
                self.phase, self.status = payload[0], payload[1]
                if len(payload) > 2 and payload[2] is not None:
                    self.progress = max(0, min(100, int(payload[2])))
        elif kind == "clip":
            with self.lock: self.session["clips"] += 1
            self.push("Clip ready: " + payload)
            if self.publisher:
                try:
                    self.publisher.submit(OUT / payload)
                except Exception as e:
                    self.push(f"{self.publishing.get('provider', 'Publisher').title()} auto-post error: " + str(e))
        elif kind == "file_lock":
            self.push_file_lock(payload)
        elif kind == "chunk":
            with self.lock: self.session["chunks"] += 1
        elif kind == "done":
            with self.lock:
                self.running = False
                self.phase, self.status = "idle", "Ready when you are."
                self.progress = 0
                self.session["ended"] = time.time()

    def start(self, cfg):
        with self.lock:
            if self.running:
                raise ValueError("Already running.")
            if ffmpeg_exe() == "ffmpeg" and not shutil.which("ffmpeg"):
                raise ValueError("ffmpeg not found. Run  winget install Gyan.FFmpeg  then restart StreamSnip AI.")
            t = normalize_stream_target(cfg["target"])
            if cfg["mode"] == "live":
                if not re.match(r"https?://", t):
                    raise ValueError("Enter a Twitch or YouTube stream URL.")
                if not streamlink_available():
                    raise ValueError("streamlink is not installed. Run:  pip install streamlink")
            else:
                if not t or not pathlib.Path(t).is_file():
                    raise ValueError("That video file doesn't exist.")
            cfg = dict(cfg, target=t)
            creator_id = str(cfg.get("creator_id") or "").strip()
            if creator_id:
                profile = getattr(self, "creators", {}).get(creator_id)
                if not profile:
                    raise ValueError("The selected creator is no longer configured. Choose it again.")
                creator_worker = getattr(self, "creator_workers", {}).get(creator_id)
                if creator_worker and creator_worker.is_alive():
                    raise ValueError("This creator already has a background monitor. Stop that monitor before starting a Live Studio capture.")
                if cfg.get("mode") != "live":
                    raise ValueError("Saved creator folders are only available for live streams.")
                if normalize_stream_target(profile.get("target", "")) != t:
                    raise ValueError("The selected creator does not match the live stream URL.")
                paths = self._ensure_creator_paths(creator_id)
                cfg["creator_out_dir"] = str(paths["live_clips"])
                cfg["creator_rec_dir"] = str(paths["live_recordings"])
                cfg = self.save_creator_settings(creator_id, cfg)
            self.settings = cfg
            apply_storage_paths(cfg)
            if not creator_id:
                self.default_settings = clean_cfg(cfg)
                self.default_settings.pop("creator_id", None)
                save_settings(cfg)
            self.engine = Engine(cfg, self.emit)
            self.running = True
            self.phase, self.status = "waiting", "Starting..."
            self.progress = 0
            self.session = {"clips": 0, "chunks": 0, "started": time.time(), "ended": None}
            self.push("Started (" + ("live stream" if cfg["mode"] == "live" else "video file") + ").")
            self.worker = threading.Thread(target=self.engine.run, daemon=True, name="streamsnip-engine")
            self.worker.start()

    def stop(self, force):
        with self.lock:
            if self.engine and self.running:
                if getattr(self.engine, "stop_flag", False):
                    return {"ok": True, "stopping": True}
                self.engine.stop(force=force)
                self.push("Stopping now." if (force or self.engine.cfg["mode"] != "live")
                          else "Stopping the recording - finishing the clips already captured.")
                return {"ok": True, "stopping": True}
        return {"ok": True, "stopping": False}

    def state(self, since, clip_offset=0, clip_tab="clips", include_clips=True, clip_limit=60):
        # Reuse the folder index and SQL delivery maps. Delivery history is
        # independent of local media retention, so counts must include SQL-only rows.
        indexed = _clip_index()
        posted_registry = load_posted_registry()
        scheduled_registry = load_scheduled_registry()
        posted_names = set(posted_registry)
        scheduled_names = set(scheduled_registry)
        indexed_names = {str(item["name"]) for item in indexed}
        ready_total = sum(
            1 for name in indexed_names
            if name not in posted_names and name not in scheduled_names
        )
        posted_total = len(posted_names)
        scheduled_total = len(posted_names | scheduled_names)
        all_total = len(indexed_names | posted_names | scheduled_names)
        clip_total = (
            all_total if clip_tab == "all"
            else posted_total if clip_tab == "posted"
            else scheduled_total if clip_tab == "scheduled"
            else ready_total
        )
        clips = list_clips(
            limit=clip_limit, offset=clip_offset, clip_tab=clip_tab,
            _indexed=indexed, _posted=posted_registry, _scheduled=scheduled_registry,
        ) if include_clips else []
        with self.lock:
            s = self.session
            el = int((s["ended"] or time.time()) - s["started"]) if s["started"] else 0
            eng = self.engine
            return {
                "running": self.running,
                "stopping": bool(eng and self.running and eng.stop_flag),
                "mode": eng.cfg["mode"] if eng else None,
                "phase": self.phase, "status": self.status,
                "progress": self.progress,
                "posting": dict(self.posting),
                "logs": [{"id": i, "t": t, "m": m, **({"file_lock": lock} if lock else {})}
                         for (i, t, m, lock) in self.logs if i > since],
                "last_id": self.log_id,
                "session": {"clips": s["clips"], "chunks": s["chunks"], "elapsed": el},
                "clips": clips,
                "clip_total": clip_total,
                "posted_total": posted_total,
                "scheduled_total": scheduled_total,
            }

    def stop_file_holder(self, name, pid):
        if os.name != "nt":
            raise ValueError("Stopping a file holder from Activity is available on Windows only.")
        name = str(name or "")
        if not LOCK_FILE_RE.fullmatch(name):
            raise ValueError("That output file name is not valid.")
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            raise ValueError("That process ID is not valid.")
        if pid <= 0 or pid == os.getpid():
            raise ValueError("StreamSnip AI cannot stop its own process this way.")
        target = (OUT / name).resolve()
        if target.parent != OUT.resolve():
            raise ValueError("That file is outside the clips folder.")
        holder = next((item for item in windows_file_lock_owners(target) if item["pid"] == pid), None)
        if not holder:
            return {"ok": True, "message": "That process no longer holds the file. Try the clip again."}
        result = run(["taskkill.exe", "/PID", str(pid)], capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "Windows could not close that process.").strip()
            raise RuntimeError(f"Could not stop {holder['name']} (PID {pid}): {detail}")
        message = f"Asked Windows to close {holder['name']} (PID {pid}) because it was using {name}."
        self.push(message)
        return {"ok": True, "message": message}

    def shutdown(self):
        with self.lock:
            engine = self.engine
            worker = self.worker
        if engine:
            engine.stop(force=True)
        shutdown_child_processes()
        if worker and worker is not threading.current_thread() and worker.is_alive():
            worker.join(timeout=6)
        # A worker racing with shutdown may have registered a child just before
        # the shutdown flag was set. A second idempotent pass closes that gap.
        shutdown_child_processes()
        with self.lock:
            self.running = False
            self.phase, self.status = "idle", "StreamSnip AI has closed."
            self.progress = 0

    def _configured_zernio_connections(self, cfg=None):
        cfg = cfg if isinstance(cfg, dict) else self._config_for("zernio")
        connections = cfg.get("connections")
        if isinstance(connections, list) and connections:
            return [dict(item) for item in connections if isinstance(item, dict)]
        legacy_key = str(cfg.get("api_key", "")).strip()
        if not legacy_key:
            return []
        legacy_accounts = []
        account_map = cfg.get("accounts", {})
        if isinstance(account_map, dict):
            for platform, account_id in account_map.items():
                if account_id:
                    legacy_accounts.append({
                        "id": str(account_id), "platform": str(platform), "name": str(platform).title(),
                        "username": "", "is_active": True, "provider_enabled": True,
                        "posting_enabled": True,
                    })
        for platform in ("instagram", "youtube"):
            account_id = cfg.get(platform + "_id")
            if account_id and not any(item["platform"] == platform for item in legacy_accounts):
                legacy_accounts.append({
                    "id": str(account_id), "platform": platform, "name": platform.title(),
                    "username": "", "is_active": True, "provider_enabled": True,
                    "posting_enabled": True,
                })
        return [{"id": "legacy", "label": "Zernio API connection 1", "api_key": legacy_key,
                 "accounts": legacy_accounts}]

    def _public_zernio_connections(self, cfg=None):
        configured_connections = self._configured_zernio_connections(cfg)
        identities = connection_identity_status(configured_connections)
        safe = []
        for connection in configured_connections:
            accounts = []
            for account in connection.get("accounts", []):
                if not isinstance(account, dict):
                    continue
                accounts.append({
                    key: account.get(key) for key in (
                        "id", "platform", "name", "username", "profile_id", "profile_name",
                        "profile_color", "profile_picture", "profile_url", "is_active", "provider_enabled",
                        "is_over_limit", "posting_enabled", "last_error", "rate_limited",
                        "rate_limited_auto_paused", "rate_limit_until",
                    ) if key in account
                })
            safe.append({
                "id": str(connection.get("id", "")),
                "label": str(connection.get("label") or "Zernio workspace"),
                "api_key_set": bool(str(connection.get("api_key", "")).strip()),
                "accounts": accounts,
                "account_count": len(accounts),
                **identities.get(str(connection.get("id", "")), {
                    "identity_verified": False, "identity_shared": False,
                }),
            })
        return safe

    def zernio_status(self):
        cfg = self._config_for("zernio")
        return dict(self._provider_status("zernio"), accounts=dict(cfg.get("accounts", {})) if isinstance(cfg.get("accounts"), dict) else {},
                    workspace_independence_verified=False,
                    workspace_warning="API-key slots are not verified independent billing workspaces. Zernio request limits are shared across a billing team.",
                    auto_post=bool(cfg.get("auto_post")),
                    schedule_minutes=int(cfg.get("schedule_minutes", 0) or 0),
                    visibility=cfg.get("visibility", "public"),
                    instagram_id=cfg.get("instagram_id", ""), youtube_id=cfg.get("youtube_id", ""),
                    connections=self._public_zernio_connections(cfg))

    def sync_zernio_posts(self):
        """Reconcile local clips against Zernio's post list without creating posts."""
        connections = self._configured_zernio_connections(self._config_for())
        if not connections:
            raise ValueError("Connect a Zernio API key before syncing posts.")

        local_names = {item["name"] for item in _clip_index()}
        posted_destinations = 0
        scheduled_destinations = 0
        matched_clips = set()
        errors = []
        seen_remote_destinations = set()
        for connection in connections:
            connection_id = str(connection.get("id") or "")
            api_key = str(connection.get("api_key") or "").strip()
            if not api_key:
                continue
            client = ZernioPublisher(self.push, {"enabled": True, "api_key": api_key})
            page = 1
            page_count = 1
            try:
                while page <= page_count and page <= 25:
                    query = urllib.parse.urlencode({
                        "limit": 100,
                        "page": page,
                        "sortBy": "created-desc",
                    })
                    response = client._json_request("GET", f"https://zernio.com/api/v1/posts?{query}")
                    root = response if isinstance(response, dict) else {}
                    data = root.get("data") if isinstance(root.get("data"), dict) else root
                    posts = data.get("posts") if isinstance(data, dict) else None
                    if not isinstance(posts, list):
                        raise RuntimeError("Zernio returned an unexpected posts list.")
                    pagination = root.get("pagination")
                    if not isinstance(pagination, dict) and isinstance(data, dict):
                        pagination = data.get("pagination")
                    if isinstance(pagination, dict):
                        try:
                            page_count = max(1, min(25, int(pagination.get("pages", page_count) or 1)))
                        except (TypeError, ValueError):
                            page_count = 1

                    matches = zernio_posts_to_local_deliveries(posts, connection_id, local_names)
                    for name, states in matches.items():
                        path = find_clip_path(name)
                        if not path or not path.is_file():
                            continue
                        matched_clips.add(name)
                        unique_posted = []
                        unique_scheduled = []
                        for record in states["posted"]:
                            identity = (
                                name, record.get("post_id"), record.get("platform"),
                                record.get("account_id"),
                            )
                            if identity in seen_remote_destinations:
                                continue
                            seen_remote_destinations.add(identity)
                            unique_posted.append(record)
                        for record in states["scheduled"]:
                            identity = (
                                name, record.get("post_id"), record.get("platform"),
                                record.get("account_id"),
                            )
                            if identity in seen_remote_destinations:
                                continue
                            seen_remote_destinations.add(identity)
                            unique_scheduled.append(record)

                        if unique_posted:
                            record_zernio_posted(name, records=unique_posted)
                            posted_destinations += len(unique_posted)
                        if unique_scheduled:
                            record_zernio_scheduled(name, records=unique_scheduled)
                            scheduled_destinations += len(unique_scheduled)
                    if not posts or len(posts) < 100:
                        break
                    page += 1
            except Exception as exc:
                errors.append({"connection_id": connection_id, "error": str(exc)[:350]})
                self.push(f"Zernio sync error [{connection_id}]: {exc}")

        return {
            "ok": not errors,
            "clips_matched": len(matched_clips),
            "posted_destinations": posted_destinations,
            "scheduled_destinations": scheduled_destinations,
            "errors": errors,
            "message": (
                f"Synced {len(matched_clips)} local clip(s): {posted_destinations} published "
                f"and {scheduled_destinations} still scheduled."
            ),
        }

    def publishing_status(self):
        # Reading connection status must not make provider requests or mutate
        # any of the five saved slots. Discovery and publishing are explicit actions.
        cfg = self._config_for()
        public_connections = self._public_zernio_connections(cfg)
        configured = any(item["api_key_set"] for item in public_connections) or bool(cfg.get("api_key"))
        status = dict(self._provider_status("zernio"), api_key_set=configured, configured=configured,
                      publishing_active=bool(getattr(self, "posting", {}).get("active")),
                      connections=public_connections,
                      schedule_minutes=int(cfg.get("schedule_minutes", 0) or 0),
                      visibility=cfg.get("visibility", "public"),
                      instagram_id=cfg.get("instagram_id", ""),
                      youtube_id=cfg.get("youtube_id", ""),
                      accounts=dict(cfg.get("accounts", {})) if isinstance(cfg.get("accounts"), dict) else {},
                      auto_post=bool(cfg.get("auto_post", False)),
                      workspace_independence_verified=False,
                      workspace_warning="API-key slots are not verified independent billing workspaces. Zernio request limits are shared across a billing team.")
        return {"provider": "zernio", "providers": {"zernio": status}, **status}

    def publishing_connections_save(self, body):
        raw_connections = body.get("connections")
        if not isinstance(raw_connections, list):
            raise ValueError("Zernio connections must be a list.")
        if len(raw_connections) > 5:
            raise ValueError("StreamSnip supports up to five Zernio API connections.")
        cfg = dict(self._config_for())
        existing = {str(item.get("id", "")): item
                    for item in self._configured_zernio_connections(cfg)}
        saved = []
        seen = set()
        seen_api_keys = set()
        for position, raw in enumerate(raw_connections, 1):
            if not isinstance(raw, dict):
                raise ValueError("Each Zernio connection must be an object.")
            connection_id = str(raw.get("id", "")).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", connection_id):
                raise ValueError("Invalid Zernio connection identifier.")
            if connection_id in seen:
                raise ValueError("Duplicate Zernio connection identifier.")
            seen.add(connection_id)
            previous = existing.get(connection_id, {})
            previous_key = str(previous.get("api_key") or "").strip()
            supplied_api_key = str(raw.get("api_key") or "").strip()
            api_key = supplied_api_key or previous_key
            if not api_key:
                raise ValueError(f"Enter the API key for {raw.get('label') or 'Zernio connection ' + str(position)}.")
            if api_key in seen_api_keys:
                raise ValueError("Each API-key connection slot must use a different key. Different keys can still share the same Zernio billing-team request quota.")
            seen_api_keys.add(api_key)
            label = str(raw.get("label") or previous.get("label") or f"Zernio connection {position}").strip()[:80]
            previous_accounts = {
                str(item.get("id")): item for item in previous.get("accounts", [])
                if isinstance(item, dict) and item.get("id")
            }
            requested_accounts = {
                str(item.get("id")): item for item in raw.get("accounts", [])
                if isinstance(item, dict) and item.get("id")
            } if isinstance(raw.get("accounts"), list) else {}

            # Only contact Zernio when a slot receives a new or replacement key.
            # Saving a label or another slot must not make all existing keys a
            # dependency of the operation or erase their last known accounts.
            key_changed = not previous_key or api_key != previous_key
            identity = {"user_id": str(previous.get("identity_user_id") or "")}
            if key_changed:
                identity_publisher = ZernioPublisher(self.push, {"enabled": True, "api_key": api_key})
                try:
                    identity = identity_publisher.verify_identity() or {}
                except Exception:
                    self.push(
                        f"Zernio identity for {label} could not be verified. "
                        "Account discovery will still verify whether the key works."
                    )
                    identity = {"user_id": ""}
                try:
                    discovered = identity_publisher.accounts()
                except Exception as exc:
                    raise ValueError(f"Could not verify {label} or discover its accounts: {exc}") from exc
            else:
                discovered = list(previous_accounts.values())
            accounts = []
            for account in apply_account_slots(discovered, previous_accounts):
                account_id = str(account["id"])
                requested = requested_accounts.get(account_id, {})
                prior = previous_accounts.get(account_id, {})
                active = bool(account.get("is_active", True)) and bool(account.get("provider_enabled", True))
                posting_enabled = bool(requested.get(
                    "posting_enabled",
                    requested.get("enabled", prior.get("posting_enabled", prior.get("enabled", active))),
                )) and active
                accounts.append({
                    **account,
                    "posting_enabled": posting_enabled,
                    "last_error": str(prior.get("last_error", "")),
                    "rate_limited": bool(prior.get("rate_limited", False)),
                    "rate_limited_auto_paused": bool(prior.get("rate_limited_auto_paused", False)),
                    "rate_limit_until": prior.get("rate_limit_until"),
                })
            saved.append({
                "id": connection_id, "label": label, "api_key": api_key,
                "identity_user_id": str(identity.get("user_id") or ""),
                "accounts": accounts, "visibility": cfg.get("visibility", "public"),
            })
        cfg["connections"] = saved
        # The multi-connection list is now authoritative; clear the legacy
        # single-key fields so removing the final slot really disconnects it.
        cfg["api_key"] = ""
        cfg["accounts"] = {}
        cfg["instagram_id"] = ""
        cfg["youtube_id"] = ""
        cfg["auto_post"] = bool(body.get("auto_post", cfg.get("auto_post", False)))
        try:
            cfg["schedule_minutes"] = max(0, int(body.get("schedule_minutes", cfg.get("schedule_minutes", 0))))
        except (TypeError, ValueError):
            cfg["schedule_minutes"] = 0
        visibility = body.get("visibility", cfg.get("visibility", "public"))
        cfg["visibility"] = str(visibility) if visibility in ("public", "private", "unlisted") else "public"
        self.publishing["zernio"] = cfg
        self.publishing["provider"] = "zernio"
        self.zernio = cfg
        save_publishing_settings(self.publishing)
        self.publisher = self._make_publisher("zernio", cfg["auto_post"])
        return self.publishing_status()

    def disconnect_zernio_connection(self, connection_id):
        connection_id = str(connection_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", connection_id):
            raise ValueError("Invalid Zernio connection identifier.")
        with self.lock:
            if getattr(self, "posting", {}).get("active"):
                raise ValueError("A Zernio publishing batch is active. Wait for it to finish before disconnecting.")

            cfg = dict(self._config_for("zernio"))
            connections = self._configured_zernio_connections(cfg)
            remaining = [
                item for item in connections
                if str(item.get("id", "")) != connection_id
            ]
            if len(remaining) == len(connections):
                raise ValueError("Zernio connection was not found.")

            cfg["connections"] = remaining
            # The multi-connection list is authoritative. Clear legacy fields so
            # disconnecting the final (including a migrated legacy) slot is final.
            cfg["api_key"] = ""
            cfg["accounts"] = {}
            cfg["instagram_id"] = ""
            cfg["youtube_id"] = ""
            self.publishing["zernio"] = cfg
            self.publishing["provider"] = "zernio"
            self.zernio = cfg
            save_publishing_settings(self.publishing)
            self.publisher = self._make_publisher("zernio", bool(cfg.get("auto_post", False)))

        self.push(f"Disconnected Zernio connection {connection_id}. Its saved key and discovered account settings were removed from this PC.")
        return self.publishing_status()

    def publishing_account_toggle(self, body):
        connection_id = str(body.get("connection_id", "")).strip()
        account_id = str(body.get("account_id", "")).strip()
        enabled = bool(body.get("enabled", False))
        cfg = dict(self._config_for())
        connections = self._configured_zernio_connections(cfg)
        connection = next((item for item in connections if str(item.get("id")) == connection_id), None)
        if not connection:
            raise ValueError("Zernio connection was not found.")
        account = next((item for item in connection.get("accounts", [])
                        if str(item.get("id")) == account_id), None)
        if not account:
            raise ValueError("Social account was not found. Refresh account discovery.")
        if enabled and (
            not account.get("is_active", True)
            or not account.get("provider_enabled", True)
        ):
            raise ValueError("This account is unavailable for posting. Check its Zernio connection status.")
        account["posting_enabled"] = enabled
        account["rate_limited_auto_paused"] = False
        if enabled:
            account["rate_limited"] = False
            account["rate_limit_until"] = None
            account["last_error"] = ""
        cfg["connections"] = connections
        self.publishing["zernio"] = cfg
        self.zernio = cfg
        save_publishing_settings(self.publishing)
        return self.publishing_status()

    def publishing_accounts(self, provider=None, connection_id=None):
        # This endpoint is called only after an explicit account refresh. Query
        # each selected slot directly, without refreshing unrelated keys first.
        cfg = dict(self._config_for())
        connections = self._configured_zernio_connections(cfg)
        if not connections:
            raise ValueError("Add a Zernio API key to discover connected social accounts.")
        selected = [item for item in connections if connection_id is None or str(item.get("id")) == str(connection_id)]
        if connection_id is not None and not selected:
            raise ValueError("Zernio connection was not found.")
        all_accounts = []
        errors = []
        for connection in selected:
            try:
                discovered = ZernioPublisher(
                    self.push, {"enabled": True, "api_key": connection["api_key"]}
                ).accounts()
                previous = {str(item.get("id")): item for item in connection.get("accounts", [])
                            if isinstance(item, dict) and item.get("id")}
                connection["accounts"] = []
                for account in apply_account_slots(discovered, previous):
                    prior = previous.get(str(account["id"]), {})
                    active = bool(account.get("is_active", True)) and bool(account.get("provider_enabled", True))
                    posting_enabled = bool(prior.get(
                        "posting_enabled", prior.get("enabled", active)
                    )) and active
                    saved_account = {
                        **account,
                        "posting_enabled": posting_enabled,
                        "last_error": str(prior.get("last_error", "")),
                        "rate_limited": bool(prior.get("rate_limited", False)),
                        "rate_limited_auto_paused": bool(prior.get("rate_limited_auto_paused", False)),
                        "rate_limit_until": prior.get("rate_limit_until"),
                    }
                    connection["accounts"].append(saved_account)
                    all_accounts.append({
                        **saved_account, "connection_id": connection["id"],
                        "connection_label": connection.get("label", "Zernio workspace"),
                        "ref": f"{connection['id']}:{account['id']}",
                    })
            except Exception as exc:
                errors.append(f"{connection.get('label', connection.get('id'))}: {exc}")
                self.push(f"Zernio account discovery failed for {connection.get('label')}: {exc}")
        cfg["connections"] = connections
        self.publishing["zernio"] = cfg
        self.zernio = cfg
        save_publishing_settings(self.publishing)
        if errors and not all_accounts:
            raise ValueError("; ".join(errors))
        if errors:
            self.push("Some Zernio workspaces could not refresh: " + "; ".join(errors))
        return all_accounts

    def publishing_save(self, body):
        provider = str(body.get("provider", "zernio")).lower()
        if provider != "zernio": raise ValueError("Only Zernio publishing is supported.")
        if "connections" in body:
            return self.publishing_connections_save(body)
        cfg = dict(self._config_for())
        if isinstance(cfg.get("connections"), list) or ("api_key" not in body and not cfg.get("api_key")):
            cfg["auto_post"] = bool(body.get("auto_post", cfg.get("auto_post", False)))
            try:
                cfg["schedule_minutes"] = max(0, int(body.get("schedule_minutes", cfg.get("schedule_minutes", 0))))
            except (TypeError, ValueError):
                raise ValueError("Schedule interval must be a non-negative whole number of minutes.")
            visibility = body.get("visibility", cfg.get("visibility", "public"))
            cfg["visibility"] = str(visibility) if visibility in ("public", "private", "unlisted") else "public"
            self.publishing["zernio"] = cfg
            self.zernio = cfg
            save_publishing_settings(self.publishing)
            self.publisher = self._make_publisher("zernio", cfg["auto_post"])
            return self.publishing_status()
        for key in ("api_key", "instagram_id", "youtube_id"):
            if key in {"instagram_id", "youtube_id"} and key not in body:
                continue
            value = str(body.get(key, cfg.get(key, ""))).strip()
            if value: cfg[key] = value
            elif key in {"instagram_id", "youtube_id"}: cfg[key] = ""
        if "account_ids" in body:
            raw_accounts = body.get("account_ids")
            if not isinstance(raw_accounts, dict):
                raise ValueError("Connected account selection must be a platform-to-account map.")
            supported = {"instagram", "facebook", "youtube"}
            cfg["accounts"] = {
                str(platform).strip().lower(): str(account_id).strip()
                for platform, account_id in raw_accounts.items()
                if str(platform).strip().lower() in supported and str(account_id).strip()
            }
            cfg["instagram_id"] = cfg["accounts"].get("instagram", "")
            cfg["youtube_id"] = cfg["accounts"].get("youtube", "")
        cfg["auto_post"] = bool(body.get("auto_post", False))
        try: cfg["schedule_minutes"] = max(0, int(body.get("schedule_minutes", 0)))
        except (TypeError, ValueError): cfg["schedule_minutes"] = 0
        cfg["visibility"] = str(body.get("visibility", "public")) if body.get("visibility") in ("public", "private", "unlisted") else "public"
        if not cfg.get("api_key"): raise ValueError("Enter an API key first.")
        self.publishing[provider] = cfg; self.publishing["provider"] = provider
        self.zernio = self.publishing["zernio"]
        save_publishing_settings(self.publishing)
        self.publisher = self._make_publisher(provider, cfg["auto_post"])
        return self.publishing_status()

    def zernio_save(self, body):
        body = dict(body); body["provider"] = "zernio"
        return self.publishing_save(body)

    def zernio_accounts(self):
        return self.publishing_accounts("zernio")

    def publish_clips(self, names, caption_overrides=None, account_ids=None,
                      auto_schedule=False, force_publish_now=False):
        provider = "zernio"
        cfg = self._config_for()
        if isinstance(cfg.get("connections"), list) and ZERNIO_AVAILABLE:
            expiry_publisher = self._make_publisher(provider, False)
            if isinstance(expiry_publisher, ZernioMultiPublisher):
                expiry_publisher.refresh_expired()
            cfg = self._config_for()
        multi_connection = bool(cfg.get("connections")) and bool(ZERNIO_AVAILABLE and ZernioMultiPublisher)
        if multi_connection:
            connections = self._configured_zernio_connections(cfg)
            available_refs = {
                f"{connection.get('id')}:{account.get('id')}"
                for connection in connections
                for account in connection.get("accounts", [])
                if isinstance(account, dict) and account.get("id")
                and account.get("is_active", True)
                and account.get("provider_enabled", True)
                and not account.get("rate_limited", False)
            }
            default_enabled_refs = {
                f"{connection.get('id')}:{account.get('id')}"
                for connection in connections
                for account in connection.get("accounts", [])
                if isinstance(account, dict) and account.get("id")
                and account.get("posting_enabled", account.get("enabled", account.get("is_active", True)))
                and account.get("is_active", True)
                and account.get("provider_enabled", True)
                and not account.get("rate_limited", False)
            }
            if isinstance(account_ids, list):
                selected_accounts = []
                seen_refs = set()
                for item in account_ids:
                    if not isinstance(item, dict):
                        continue
                    connection_id = str(item.get("connection_id", ""))
                    account_id = str(item.get("account_id") or item.get("id") or "")
                    ref = f"{connection_id}:{account_id}"
                    if connection_id and account_id and ref in available_refs and ref not in seen_refs:
                        selected_accounts.append({"connection_id": connection_id, "account_id": account_id})
                        seen_refs.add(ref)
            elif account_ids is None:
                selected_accounts = None
            elif isinstance(account_ids, dict):
                selected_accounts = account_ids
            else:
                selected_accounts = []
            if selected_accounts == [] or (selected_accounts is None and not default_enabled_refs):
                raise ValueError("Select at least one available Zernio account for this publish.")
        else:
            if not cfg.get("api_key"):
                raise ValueError(f"Save and verify a {provider.title()} API key first.")
            selected_accounts = account_ids if isinstance(account_ids, dict) else cfg.get("accounts", {})
            if not isinstance(selected_accounts, dict):
                selected_accounts = {}
            selected_accounts = {
                str(platform).strip().lower(): str(account_id).strip()
                for platform, account_id in selected_accounts.items()
                if str(platform).strip().lower() in SUPPORTED_ZERNIO_PLATFORMS and str(account_id).strip()
            }
            if not selected_accounts:
                for platform in ("instagram", "youtube", "facebook"):
                    if cfg.get(platform + "_id"):
                        selected_accounts[platform] = str(cfg[platform + "_id"])
            if not selected_accounts:
                raise ValueError("Connect and select at least one Zernio social account in Settings.")
        valid = []
        for raw_name in names:
            name = str(raw_name)
            if not CLIP_RE.fullmatch(name):
                continue
            clip_path = find_clip_path(name)
            if clip_path and is_fully_rendered_clip(clip_path):
                valid.append(name)
        if not valid:
            raise ValueError("No fully rendered clips are ready to publish.")
        if not self._make_publisher(provider, False): raise ValueError(f"{provider.title()} posting is unavailable.")
        with self.lock:
            if self.posting["active"]:
                raise ValueError(f"A {provider.title()} posting batch is already in progress.")
            self.posting.update({"active": True, "total": len(valid), "completed": 0, "current": "",
                                 "started": time.time(), "done": 0, "last_name": "", "errors": 0})
        def publish_batch():
            try:
                for index, name in enumerate(valid):
                    try:
                        publisher = self._make_publisher(provider, False)
                        if publisher and not isinstance(publisher, ZernioMultiPublisher):
                            publisher.on_success = lambda path, destinations: record_zernio_posted(path.name, destinations)
                        interval = max(0, int(cfg.get("schedule_minutes", 0) or 0))
                        if auto_schedule and interval <= 0:
                            interval = 5
                        delay = 0 if force_publish_now else interval * (index + 1)
                        with self.lock: self.posting["current"] = name
                        self.push(f"{provider.title()}: uploading {index + 1} of {len(valid)} - {name}.")
                        caption_override = (caption_overrides or {}).get(name) if isinstance(caption_overrides, dict) else None
                        clip_path = find_clip_path(name)
                        if not clip_path or not is_fully_rendered_clip(clip_path):
                            raise FileNotFoundError(
                                f"Clip is no longer a fully rendered, post-ready video: {name}"
                            )
                        publish_result = publisher.publish_one(
                            clip_path, schedule_minutes=delay,
                            accounts=selected_accounts, caption_override=caption_override,
                        )
                        if isinstance(publisher, ZernioMultiPublisher) and isinstance(publish_result, dict):
                            account_failures = publish_result.get("failed", [])
                            account_successes = publish_result.get("succeeded", [])
                            if publish_result.get("workspace_rate_limited"):
                                with self.lock:
                                    self.posting["errors"] += 1
                                self.push(
                                    "Zernio's workspace request limit stopped this publishing batch. "
                                    "No social account was disabled; wait for the request cooldown before retrying."
                                )
                                break
                            if account_failures:
                                with self.lock:
                                    self.posting["errors"] += len(account_failures)
                                self.push(
                                    f"{provider.title()}: {len(account_successes)} account(s) accepted "
                                    f"the post; {len(account_failures)} account(s) failed independently. "
                                    "See the account details in Publishing."
                                )
                            with self.lock:
                                if account_successes:
                                    self.posting["completed"] += 1
                                    self.posting["done"] += 1
                                    self.posting["last_name"] = name
                            if account_successes:
                                self.push(f"{provider.title()} upload complete for {len(account_successes)} account(s): {name}.")
                            else:
                                raise RuntimeError("Zernio did not accept this clip on any enabled account.")
                        else:
                            with self.lock:
                                self.posting["completed"] += 1
                                self.posting["done"] += 1
                                self.posting["last_name"] = name
                            self.push(f"{provider.title()} upload complete: {name}.")
                    except Exception as exc:
                        with self.lock: self.posting["errors"] += 1
                        self.push(f"{provider.title()} error for {name}: {exc}")
            except Exception as exc:
                with self.lock: self.posting["errors"] += 1
                self.push(f"{provider.title()} posting batch stopped unexpectedly: {exc}")
            finally:
                with self.lock:
                    self.posting["active"] = False
                    self.posting["current"] = ""
                    errors = self.posting["errors"]
                    completed = self.posting["completed"]
                self.push(f"{provider.title()} posting complete: {completed} uploaded, {errors} failed.")
        threading.Thread(target=publish_batch, daemon=True, name=f"{provider}-batch").start()
        self.push(f"{provider.title()}: queued {len(valid)} clip(s) for publishing.")
        return {"queued": len(valid)}

_CLIP_CACHE = {"signature": None, "items": []}

def invalidate_clip_cache():
    _CLIP_CACHE["signature"] = None
    _CLIP_CACHE["items"] = []

def _clip_directories():
    directories = [("main", "", "", OUT)]
    core = globals().get("CORE")
    if core is not None:
        try:
            with core.lock:
                creators = [(creator_id, dict(profile)) for creator_id, profile in core.creators.items()]
            for creator_id, profile in creators:
                paths = core._creator_paths(creator_id)
                name = str(profile.get("name", creator_id))
                directories.append(("live", creator_id, name, paths["live_clips"]))
                directories.append(("vod", creator_id, name, paths["vod_clips"]))
        except Exception:
            pass
    return directories

def _clip_index():
    directories = _clip_directories()
    signature = []
    for source, creator_id, creator_name, folder in directories:
        try:
            stamp = folder.stat().st_mtime_ns
        except OSError:
            stamp = None
        signature.append((str(folder), stamp))
    signature = tuple(signature)
    if signature == _CLIP_CACHE["signature"]:
        return _CLIP_CACHE["items"]
    items = []
    for source, creator_id, creator_name, folder in directories:
        try:
            candidates = folder.glob("*.mp4")
        except OSError:
            continue
        for path in candidates:
            if not CLIP_RE.fullmatch(path.name):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            items.append({
                "name": path.name, "mtime": stat.st_mtime, "size_mb": round(stat.st_size / 1048576, 1),
                "source": source, "creator_id": creator_id, "creator_name": creator_name,
                "_path": str(path.resolve()),
            })
    items.sort(key=lambda item: item["mtime"], reverse=True)
    _CLIP_CACHE["signature"] = signature
    _CLIP_CACHE["items"] = items
    return items

def find_clip_path(name):
    """Resolve a clip only from the main gallery or registered creator clip folders."""
    name = str(name or "")
    if not CLIP_RE.fullmatch(name):
        return None
    for item in _clip_index():
        if item["name"] == name:
            path = pathlib.Path(item["_path"])
            return path if path.is_file() else None
    return None


def is_fully_rendered_clip(clip_path):
    """Only expose completed MP4s to publishing after the SQL copy sidecar is committed."""
    path = pathlib.Path(clip_path)
    try:
        if not CLIP_RE.fullmatch(path.name):
            return False
        if not path.is_file() or path.stat().st_size <= 0:
            return False
        sidecar = path.with_suffix(".txt")
        return sidecar.is_file() and sidecar.stat().st_size > 0
    except OSError:
        return False


def _clip_thumbnail_target(clip_path):
    path = pathlib.Path(clip_path).resolve()
    if not path.is_file() or not CLIP_RE.fullmatch(path.name):
        raise FileNotFoundError("Rendered clip not found.")
    stat = path.stat()
    identity = f"{path}|{stat.st_size}|{stat.st_mtime_ns}"
    key = hashlib.sha1(identity.encode("utf-8"), usedforsecurity=False).hexdigest()
    folder = _data_root / "cache" / "clip-thumbnails"
    return path, folder / f"{key}.jpg", key


def cached_clip_thumbnail_path(clip_path):
    """Return a cached thumbnail without starting FFmpeg."""
    try:
        _, thumbnail, _ = _clip_thumbnail_target(clip_path)
    except (OSError, FileNotFoundError):
        return None
    return thumbnail if thumbnail.is_file() and thumbnail.stat().st_size > 1024 else None


def clip_thumbnail_path(clip_path):
    """Generate a cached JPEG frame. Call from a background worker, never the request thread."""
    path, thumbnail, key = _clip_thumbnail_target(clip_path)
    if thumbnail.is_file() and thumbnail.stat().st_size > 1024:
        return thumbnail
    folder = thumbnail.parent
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / f".{key}.{threading.get_ident()}.tmp.jpg"
    result = run([
        ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
        "-ss", "0.15", "-i", str(path),
        "-frames:v", "1",
        "-vf", "scale=480:270:force_original_aspect_ratio=decrease,pad=480:270:(ow-iw)/2:(oh-ih)/2",
        "-q:v", "5", "-y", str(temporary),
    ], capture_output=True, text=True, timeout=25)
    if result.returncode != 0 or not temporary.is_file() or temporary.stat().st_size <= 1024:
        temporary.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or "FFmpeg could not create a clip thumbnail.").strip()[-300:])
    try:
        os.replace(temporary, thumbnail)
    finally:
        temporary.unlink(missing_ok=True)
    return thumbnail


def split_clip_post_copy(text):
    """Split the public clip sidecar into editable title and description fields."""
    value = str(text or "").strip()
    if not value:
        return "", ""
    parts = value.split("\n\n", 1)
    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""


def get_clip_metadata(clip_path):
    """Return SQL-owned clip copy, importing an existing sidecar once."""
    path = pathlib.Path(clip_path).resolve()
    return get_clip_metadata_many([path]).get(str(path), {
        "title": "", "description": "", "caption": "",
    })


def get_clip_metadata_many(clip_paths):
    """Load metadata for a visible page with one SQLite read and one optional batch backfill."""
    paths = list(dict.fromkeys(pathlib.Path(item).resolve() for item in clip_paths))
    if not paths:
        return {}
    placeholders = ",".join("?" for _ in paths)
    keys = [str(path) for path in paths]
    with _database_connection() as db:
        # The IN list interpolates only generated '?' placeholders; every path is bound.
        rows = db.execute(
            f"SELECT clip_path,title,description,caption FROM clip_metadata WHERE clip_path IN ({placeholders})",  # nosec B608
            keys,
        ).fetchall()

    existing = {str(row["clip_path"]): row for row in rows}
    result = {}
    backfill = []
    now = time.time()
    for path in paths:
        row = existing.get(str(path))
        title = str(row["title"] or "").strip() if row is not None else ""
        description = str(row["description"] or "").strip() if row is not None else ""
        caption = str(row["caption"] or "").strip() if row is not None else ""
        if row is None or not title or not description:
            recovered_title, recovered_description = split_clip_post_copy(caption)
            if not recovered_description:
                try:
                    sidecar_caption = path.with_suffix(".txt").read_text(
                        encoding="utf-8", errors="replace"
                    ).strip()
                except OSError:
                    sidecar_caption = ""
                sidecar_title, sidecar_description = split_clip_post_copy(sidecar_caption)
                if sidecar_title or sidecar_description:
                    caption = sidecar_caption
                    recovered_title = sidecar_title
                    recovered_description = sidecar_description
            title = title or recovered_title
            description = description or recovered_description
            caption = caption or title + (("\n\n" + description) if description else "")
            if title:
                backfill.append((str(path), path.name, title, description, caption, now))
        result[str(path)] = {
            "title": title,
            "description": description,
            "caption": caption,
        }

    if backfill:
        with _database_connection() as db:
            db.executemany(
                """INSERT INTO clip_metadata(
                       clip_path,clip_name,title,description,caption,updated_at
                   ) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(clip_path) DO UPDATE SET
                     clip_name=excluded.clip_name,
                     title=CASE WHEN clip_metadata.title='' THEN excluded.title ELSE clip_metadata.title END,
                     description=CASE WHEN clip_metadata.description='' THEN excluded.description ELSE clip_metadata.description END,
                     caption=CASE WHEN clip_metadata.caption='' THEN excluded.caption ELSE clip_metadata.caption END,
                     updated_at=excluded.updated_at""",
                backfill,
            )
    return result


def save_clip_metadata(clip_path, title, description, caption=None, write_sidecar=True):
    path = pathlib.Path(clip_path).resolve()
    title = re.sub(r"[\n]+", " ", str(title or "")).strip()[:100]
    description = str(description or "").replace("\x00", "").strip()[:2200]
    if not title:
        raise ValueError("Add a title before saving clip metadata.")
    caption = str(caption if caption is not None else title + (("\n\n" + description) if description else "")).strip()
    now = time.time()
    with _database_connection() as db:
        db.execute(
            """INSERT INTO clip_metadata(clip_path,clip_name,title,description,caption,updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(clip_path) DO UPDATE SET
                 clip_name=excluded.clip_name,title=excluded.title,
                 description=excluded.description,caption=excluded.caption,
                 updated_at=excluded.updated_at""",
            (str(path), path.name, title, description, caption, now),
        )
    if write_sidecar:
        _atomic_text_write(path.with_suffix(".txt"), caption)
    invalidate_clip_cache()
    return {"name": path.name, "title": title, "description": description, "caption": caption}


def list_clips(
    limit=60, offset=0, clip_tab="clips", *,
    _indexed=None, _posted=None, _scheduled=None,
):
    posted = _posted if _posted is not None else load_posted_registry()
    scheduled = _scheduled if _scheduled is not None else load_scheduled_registry()
    indexed = _indexed if _indexed is not None else _clip_index()
    by_name = {}
    for source_item in indexed:
        name = str(source_item.get("name") or "")
        if name:
            by_name.setdefault(name, dict(source_item))

    if clip_tab in {"all", "posted", "scheduled"}:
        history_names = set(posted)
        if clip_tab in {"all", "scheduled"}:
            history_names.update(scheduled)
        for name in history_names:
            if name in by_name:
                continue
            history = scheduled.get(name) or posted.get(name) or {}
            stored_path = str(history.get("clip_path") or _clip_path_for_delivery_name(name) or "")
            if not stored_path:
                continue
            clip_path = pathlib.Path(stored_path)
            local_exists = clip_path.is_file()
            try:
                stat = clip_path.stat() if local_exists else None
            except OSError:
                stat = None
                local_exists = False
            activity_timestamp = float(
                posted.get(name, {}).get("posted_at", 0)
                or scheduled.get(name, {}).get("scheduled_at", 0)
                or 0
            )
            by_name[name] = {
                "name": name,
                "mtime": float(stat.st_mtime) if stat else activity_timestamp,
                "size_mb": stat.st_size / (1024 * 1024) if stat else 0.0,
                "source": "Zernio history",
                "creator_name": "",
                "_path": str(clip_path.resolve()),
                "local_exists": local_exists,
            }

    if clip_tab == "all":
        selected_names = set(by_name)
    elif clip_tab == "posted":
        selected_names = set(posted)
    elif clip_tab == "scheduled":
        # Scheduled is the provider delivery archive: pending Zernio posts plus
        # destinations already published successfully. It is intentionally
        # independent of whether the local MP4 has been retained.
        selected_names = set(posted) | set(scheduled)
    else:
        selected_names = set(by_name) - set(posted) - set(scheduled)

    filtered = [item for name, item in by_name.items() if name in selected_names]
    if clip_tab == "posted":
        filtered.sort(
            key=lambda item: float(posted.get(item["name"], {}).get("posted_at", item.get("mtime", 0)) or 0),
            reverse=True,
        )
    elif clip_tab == "scheduled":
        filtered.sort(
            key=lambda item: max(
                float(scheduled.get(item["name"], {}).get("scheduled_at", 0) or 0),
                float(posted.get(item["name"], {}).get("posted_at", 0) or 0),
            ),
            reverse=True,
        )
    else:
        filtered.sort(key=lambda item: float(item.get("mtime", 0) or 0), reverse=True)

    start = max(0, int(offset))
    selected = filtered[start:start + max(1, int(limit))]
    metadata_by_path = get_clip_metadata_many([item["_path"] for item in selected])
    items = []
    for source_item in selected:
        item = dict(source_item)
        clip_path = pathlib.Path(item.pop("_path"))
        local_exists = bool(item.get("local_exists", clip_path.is_file()))
        metadata = metadata_by_path.get(str(clip_path.resolve()), {
            "title": "", "description": "", "caption": "",
        })
        posted_entry = posted.get(item["name"], {})
        scheduled_entry = scheduled.get(item["name"], {})
        item["caption"] = metadata["caption"]
        item["title"] = metadata["title"]
        item["description"] = metadata["description"]
        item["local_exists"] = local_exists
        item["posted"] = item["name"] in posted
        item["posted_at"] = posted_entry.get("posted_at")
        # Keep the item in Scheduled while any destination is pending, and
        # preserve the exact provider-supplied publishing time for the UI.
        item["scheduled"] = item["name"] in scheduled
        item["scheduled_at"] = scheduled_entry.get("scheduled_at")
        item["scheduled_for"] = (
            scheduled_entry.get("scheduled_for")
            or posted_entry.get("scheduled_for")
        )
        item["delivery_accounts"] = list(dict.fromkeys(
            list(posted_entry.get("accounts", [])) + list(scheduled_entry.get("accounts", []))
        ))
        item["delivery_state"] = (
            "scheduled" if item["scheduled"] else "posted" if item["posted"] else "ready"
        )
        items.append(item)
    return items


def reveal(path):
    path = pathlib.Path(path).resolve()
    try:
        system = platform.system()
        if system == "Windows":
            subprocess.Popen(["explorer.exe", str(path.parent)], creationflags=CF)
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception as e:
        raise RuntimeError(f"Couldn't open the clip folder: {e}") from e

def open_folder(path):
    path = pathlib.Path(path).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
        system = platform.system()
        if system == "Windows":
            try:
                os.startfile(str(path))
            except (AttributeError, OSError):
                # Some embedded Python builds do not expose os.startfile.
                subprocess.Popen(["explorer.exe", str(path)], creationflags=CF)
        elif system == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        raise RuntimeError(f"Couldn't open the clips folder: {e}") from e

def _browse_dialog(folder=False):
    root = None
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        if folder:
            return filedialog.askdirectory(title="Choose StreamSnip AI folder")
        return filedialog.askopenfilename(title="Choose a stream recording / VOD",
                                          filetypes=[("Video", "*.mp4 *.mkv *.mov *.ts *.flv *.webm *.avi"),
                                                     ("All files", "*.*")])
    except Exception:
        return ""
    finally:
        if root is not None:
            try: root.destroy()
            except Exception: pass

def browse_file():
    return _browse_dialog(False)

def browse_folder():
    return _browse_dialog(True)

def detect_facecam(mode, target):
    """Run local multi-frame YuNet detection on a VOD or a short live sample."""
    import facecam_detect
    target = (target or "").strip().strip('"')
    if mode == "file":
        source = pathlib.Path(target)
        if not source.is_file():
            raise ValueError("Choose an existing video file before detecting its facecam.")
        return facecam_detect.detect(source)
    target = normalize_stream_target(target)
    if not re.match(r"https?://", target):
        raise ValueError("Choose a Twitch or YouTube channel before detecting its facecam.")
    if not streamlink_available():
        raise ValueError("Streamlink is required to sample a live channel.")
    stream = run(streamlink_cmd() + [target, STREAM_QUALITY, "--stream-url"],
                 capture_output=True, text=True, env=streamlink_env(), timeout=45)
    if stream.returncode != 0 or not (stream.stdout or "").strip():
        raise ValueError("The selected creator is not live or the stream is unavailable.")
    stream_url = stream.stdout.strip().splitlines()[-1].strip()
    with tempfile.TemporaryDirectory(prefix="streamsnip-facecam-") as folder:
        sample = pathlib.Path(folder) / "live-sample.mp4"
        sample_encoder = (["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "28", "-b:v", "0"]
                          if has_nvenc() else ["-c:v", "libx264", "-preset", "ultrafast"])
        result = run([ffmpeg_exe(), "-y", "-v", "error", *ffmpeg_cuda_decode_args(), "-i", stream_url,
                      "-t", "22", "-an", *sample_encoder,
                      "-pix_fmt", "yuv420p", str(sample)],
                     capture_output=True, timeout=55)
        if result.returncode != 0 or not sample.is_file() or sample.stat().st_size < 100_000:
            raise ValueError("Could not record a short live sample. Check that the creator is still live.")
        return facecam_detect.detect(sample)


def grab_frame(mode, target):
    """One JPEG frame (as a data URL) from the live stream or a video file - used by the facecam-area picker."""
    import base64
    target = (target or "").strip().strip('"')
    try:
        if mode == "live":
            target = normalize_stream_target(target)
            if not re.match(r"https?://", target):
                raise ValueError("Paste the stream link first.")
            if not streamlink_available():
                raise ValueError("streamlink is not installed.")
            r = run(streamlink_cmd() + [target, STREAM_QUALITY, "--stream-url"], capture_output=True, text=True,
                    env=streamlink_env(), timeout=45)
            if r.returncode != 0 or not (r.stdout or "").strip():
                raise ValueError("The stream isn't live right now. Try again when it is, or pick a video file.")
            attempts = [["-i", r.stdout.strip().splitlines()[-1].strip()]]
        else:
            if not target or not pathlib.Path(target).is_file():
                raise ValueError("Choose a video file first.")
            attempts = [["-ss", "5", "-i", target], ["-i", target]]
        for a in attempts:
            r = run([ffmpeg_exe(), "-v", "error", *a, "-frames:v", "1", "-vf", "scale=960:-2",
                     "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "4", "-"], capture_output=True, timeout=60)
            if r.stdout:
                return "data:image/jpeg;base64," + base64.b64encode(r.stdout).decode("ascii")
    except subprocess.TimeoutExpired:
        raise ValueError("Grabbing a frame took too long.")
    raise ValueError("Couldn't read a frame from that source.")



def grab_output_preview(mode, target, settings=None):
    """Render one real source frame through the final clip's layout and caption filters."""
    import base64

    mode = str(mode or "live").strip().lower()
    target = str(target or "").strip().strip('"')
    if mode not in {"live", "file"}:
        raise ValueError("Choose a live creator or a local video before previewing the clip.")
    if not target:
        raise ValueError("Choose a source before previewing the clip.")

    raw_settings = settings if isinstance(settings, dict) else {}
    cfg = clean_cfg({**raw_settings, "mode": mode, "target": target})

    if mode == "live":
        normalized = normalize_stream_target(target)
        if not re.match(r"https?://", normalized):
            raise ValueError("Paste a Twitch or YouTube creator URL before previewing.")
        if not streamlink_available():
            raise ValueError("Streamlink is required to preview a live creator.")
        stream = run(streamlink_cmd() + [normalized, STREAM_QUALITY, "--stream-url"],
                     capture_output=True, text=True, env=streamlink_env(), timeout=45)
        if stream.returncode != 0 or not (stream.stdout or "").strip():
            raise ValueError("This creator is not live or the stream is unavailable. Try again while they are live.")
        source = stream.stdout.strip().splitlines()[-1].strip()
        input_attempts = [["-i", source]]
    else:
        source_path = pathlib.Path(target)
        if not source_path.is_file():
            raise ValueError("Choose an existing video file before previewing the clip.")
        input_attempts = [["-ss", "5", "-i", str(source_path)], ["-i", str(source_path)]]

    # A short, silent motion sample makes the preview playable without exposing
    # unprocessed source audio. Real clips use detected speech and filtered audio.
    preview_duration = 2.5
    with tempfile.TemporaryDirectory(prefix="streamsnip-output-preview-") as folder:
        ass_path = pathlib.Path(folder) / "preview.ass"
        preview_path = pathlib.Path(folder) / "preview.mp4"
        preview_encoder = (["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "28", "-b:v", "0"]
                           if has_nvenc() else ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"])
        sample_words = [(0.0, 0.78, "THAT"), (0.78, 1.52, "WAS"), (1.52, preview_duration, "INSANE!")]
        make_ass(sample_words, 0.0, preview_duration, ass_path, cfg)
        video_filter = render_video_filter(cfg, ass_path.name)
        last_error = ""
        for input_args in input_attempts:
            preview_path.unlink(missing_ok=True)
            result = run(
                [ffmpeg_exe(), "-y", "-v", "error", *ffmpeg_cuda_decode_args(), *input_args,
                 "-t", f"{preview_duration:.2f}", "-filter_complex", video_filter,
                 "-map", "[v]", "-an", *preview_encoder,
                 "-r", "24", "-pix_fmt", "yuv420p",
                 "-movflags", "+faststart", str(preview_path)],
                cwd=folder, capture_output=True, timeout=60,
            )
            if result.returncode == 0 and preview_path.is_file() and preview_path.stat().st_size > 10_000:
                encoded = base64.b64encode(preview_path.read_bytes()).decode("ascii")
                return "data:video/mp4;base64," + encoded
            last_error = (result.stderr or b"").decode("utf-8", errors="replace")[-300:]
        raise ValueError("Could not render the selected source with the current clip settings. "
                         + (last_error or "Try another source or layout."))

CORE = Core()
TOKEN = secrets.token_urlsafe(24)

# ------------------------------------------------------------------ application route services
def parse_json_object(raw):
    """Parse a JSON request body and reject malformed or non-object payloads."""
    try:
        body = json.loads(raw or b"{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid JSON body") from exc
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


def schedule_quit_after_response(delay=0.8):
    """Signal application shutdown after the API response has been returned to ASGI."""
    timer = threading.Timer(max(0.25, float(delay)), QUIT.set)
    timer.daemon = True
    timer.name = "streamsnip-quit-after-response"
    timer.start()
    return timer


_CLIP_THUMBNAIL_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="clip-thumbnail")
_CLIP_THUMBNAIL_LOCK = threading.Lock()
_CLIP_THUMBNAILS_PENDING = set()


def schedule_clip_thumbnail(clip_path):
    """Queue one thumbnail extraction per source file and return immediately."""
    try:
        path, thumbnail, key = _clip_thumbnail_target(clip_path)
    except (OSError, FileNotFoundError):
        return False
    if thumbnail.is_file() and thumbnail.stat().st_size > 1024:
        return True
    with _CLIP_THUMBNAIL_LOCK:
        if key in _CLIP_THUMBNAILS_PENDING:
            return False
        _CLIP_THUMBNAILS_PENDING.add(key)

    def worker():
        try:
            clip_thumbnail_path(path)
            try:
                CORE.push(f"Clip thumbnail ready: {path.name}")
            except Exception:
                pass
        except Exception as exc:
            try:
                CORE.push(f"Clip thumbnail failed for {path.name}: {exc}")
            except Exception:
                pass
        finally:
            with _CLIP_THUMBNAIL_LOCK:
                _CLIP_THUMBNAILS_PENDING.discard(key)

    try:
        _CLIP_THUMBNAIL_EXECUTOR.submit(worker)
        return False
    except RuntimeError:
        with _CLIP_THUMBNAIL_LOCK:
            _CLIP_THUMBNAILS_PENDING.discard(key)
        return False


class AppRoutes:
    server_version = PRODUCT_NAME
    protocol_version = "HTTP/1.1"

    def log_message(self, *a): pass

    def _host_ok(self):
        host = self.headers.get("Host", "").strip()
        try:
            hostname = urllib.parse.urlsplit("//" + host).hostname or ""
        except ValueError:
            return False
        return hostname.lower().rstrip(".") in ("127.0.0.1", "localhost", "::1")

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra_headers=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _serve_window_lease(self):
        """Keep one socket open so closing the app window is observable server-side."""
        lease = begin_window_lease()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while not QUIT.wait(1.0):
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (OSError, ConnectionError, BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            self.close_connection = True
            end_window_lease(lease)

    def _serve_clip(self, name):
        if CLIP_RE.fullmatch(name):
            p = find_clip_path(name)
        elif re.fullmatch(r"[A-Za-z0-9_\-]+\.txt", name):
            clip_path = find_clip_path(pathlib.Path(name).stem + ".mp4")
            p = clip_path.with_suffix(".txt") if clip_path else None
        else:
            p = None
        if not p or not p.is_file():
            return self._send(404, {"error": "not found"})
        size = p.stat().st_size
        ctype = "video/mp4" if name.endswith(".mp4") else "text/plain; charset=utf-8"
        start, end, code = 0, size - 1, 200
        rng = self.headers.get("Range")
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if m:
                a, b = m.groups()
                if a == "" and b != "":
                    start = max(0, size - int(b))
                elif a != "":
                    start = int(a)
                    if b: end = int(b)
                end = min(end, size - 1)
                if start > end or start >= size:
                    self.send_response(416); self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0"); self.end_headers(); return
                code = 206
        length = end - start + 1
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if code == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        with open(p, "rb") as f:
            f.seek(start)
            left = length
            while left > 0:
                chunk = f.read(min(262144, left))
                if not chunk: break
                self.wfile.write(chunk); left -= len(chunk)

    def do_GET(self):
        try:
            if not self._host_ok():
                return self._send(403, {"error": "bad host"})
            u = urllib.parse.urlparse(self.path)
            path = u.path
            if path == "/api/session":
                origin = self.headers.get("Origin", "").strip()
                if origin:
                    try:
                        origin_host = urllib.parse.urlsplit(origin).hostname or ""
                    except ValueError:
                        origin_host = ""
                    if origin_host.lower().rstrip(".") not in ("127.0.0.1", "localhost", "::1"):
                        return self._send(403, {"error": "forbidden"})
                return self._send(200, {"token": TOKEN})
            if path == "/dashboard":
                self.send_response(302)
                self.send_header("Location", "/dashboard/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path.startswith("/dashboard/"):
                dashboard_root = pathlib.Path(__file__).resolve().parent / "dashboard" / "dist"
                if not dashboard_root.is_dir():
                    return self._send(503, {"error": "React dashboard is not built yet. Run npm run build in dashboard/."})
                relative = urllib.parse.unquote(path[len("/dashboard/"):])
                root_resolved = dashboard_root.resolve()
                requested = (root_resolved / relative).resolve() if relative else root_resolved / "index.html"
                try:
                    requested.relative_to(root_resolved)
                except ValueError:
                    return self._send(404, {"error": "not found"})
                if requested.is_dir():
                    requested = requested / "index.html"
                if not requested.is_file():
                    if pathlib.Path(relative).suffix:
                        return self._send(404, {"error": "not found"})
                    requested = root_resolved / "index.html"
                if requested.name == "index.html":
                    html = requested.read_text(encoding="utf-8-sig")
                    html = html.replace('window.__STREAMSNIP_TOKEN__ = "";',
                                        "window.__STREAMSNIP_TOKEN__ = " + json.dumps(TOKEN) + ";")
                    return self._send(200, html, "text/html; charset=utf-8")
                content_type = mimetypes.guess_type(requested.name)[0] or "application/octet-stream"
                if content_type.startswith("text/") or content_type in ("application/javascript", "application/json"):
                    content_type += "; charset=utf-8"
                return self._send(200, requested.read_bytes(), content_type)
            if path == "/api/window/lease":
                if not secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN):
                    self.close_connection = True
                    return self._send(403, {"error": "forbidden"})
                return self._serve_window_lease()
            if path == "/":
                # The classic embedded dashboard is deprecated. Keep its implementation in the repository,
                # but make the React Creator Studio the only default local interface.
                dashboard_root = pathlib.Path(__file__).resolve().parent / "dashboard" / "dist"
                if not (dashboard_root / "index.html").is_file():
                    return self._send(503, {"error": "Creator Studio is not built yet. Run npm run build in dashboard/."})
                self.send_response(302)
                self.send_header("Location", "/dashboard/")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if path == "/api/clips/names":
                q = urllib.parse.parse_qs(u.query)
                tab = q.get("tab", ["clips"])[0]
                if tab not in {"clips", "posted", "scheduled", "all"}: tab = "clips"
                posted = load_posted_registry()
                scheduled = load_scheduled_registry()
                if tab == "all":
                    names = [item["name"] for item in list_clips(
                        clip_tab="all", _posted=posted, _scheduled=scheduled
                    )]
                else:
                    names = [item["name"] for item in _clip_index()
                             if (
                                 (item["name"] in posted) if tab == "posted"
                                 else (item["name"] in posted or item["name"] in scheduled) if tab == "scheduled"
                                 else (item["name"] not in posted and item["name"] not in scheduled)
                             )]
                return self._send(200, {"names": names})
            if path == "/api/creators":
                return self._send(200, {"creators": CORE.list_creators()})
            if path == "/api/creators/settings":
                q = urllib.parse.parse_qs(u.query)
                creator_id = q.get("id", [""])[0]
                return self._send(200, {"settings": CORE.get_creator_settings(creator_id)})
            if path == "/api/config":
                # Return shared defaults, never the last creator-specific runtime snapshot.
                # Provider credentials remain private and are exposed only as presence flags.
                return self._send(200, {"settings": CORE.default_settings, "ai": public_ai_settings(),
                                        "transcriber_models": MODELS, "layouts": LAYOUTS,
                                        "output_formats": list(OUTPUT_FORMATS.keys())})
            if path == "/api/publishing/status":
                # publishing_status exposes only credential-presence flags, never the API key.
                return self._send(200, CORE.publishing_status())
            if path == "/api/state":
                q = urllib.parse.parse_qs(u.query)
                try: since = int(q.get("since", ["0"])[0])
                except ValueError: since = 0
                try: clip_offset = max(0, int(q.get("clip_offset", ["0"])[0]))
                except ValueError: clip_offset = 0
                clip_tab = q.get("clip_tab", ["clips"])[0]
                if clip_tab not in {"clips", "posted", "scheduled", "all"}: clip_tab = "clips"
                include_clips = q.get("include_clips", ["1"])[0].strip().lower() not in {"0", "false", "no"}
                try: clip_limit = max(1, min(60, int(q.get("clip_limit", ["60"])[0] or 60)))
                except ValueError: clip_limit = 60
                return self._send(200, CORE.state(
                    since, clip_offset, clip_tab, include_clips, clip_limit
                ))
            if path == "/api/log/download":
                if not RUNTIME_LOG.is_file():
                    return self._send(200, b"", "text/plain; charset=utf-8")
                return self._send(200, RUNTIME_LOG.read_bytes(), "text/plain; charset=utf-8",
                                  extra_headers={"Content-Disposition": 'attachment; filename="streamsnip.log"'})
            if path == "/api/words":
                return self._send(200, {"text": read_custom_text(), "words": sorted(HYPE_WORDS), "phrases": sorted(HYPE_PHRASES)})
            if path in ("/assets/brand-logo.png", "/assets/app-icon.png"):
                asset = asset_file(path.rsplit("/", 1)[-1])
                if asset:
                    return self._send(200, asset.read_bytes(), "image/png")
            if path.startswith("/clip-thumbnails/"):
                name = urllib.parse.unquote(path[len("/clip-thumbnails/"):])
                if not CLIP_RE.fullmatch(name):
                    return self._send(404, {"error": "not found"})
                clip_path = find_clip_path(name)
                if not clip_path:
                    return self._send(404, {"error": "not found"})
                thumbnail = cached_clip_thumbnail_path(clip_path)
                if thumbnail is None:
                    schedule_clip_thumbnail(clip_path)
                    # The card keeps its local placeholder; FFmpeg runs on a
                    # bounded background queue and a later page refresh retries.
                    return self._send(
                        404, b"", "image/jpeg",
                        extra_headers={"Cache-Control": "no-store", "Retry-After": "12"},
                    )
                return self._send(
                    200, thumbnail.read_bytes(), "image/jpeg",
                    extra_headers={"Cache-Control": "public, max-age=3600"},
                )
            if path.startswith("/clips/"):
                return self._serve_clip(urllib.parse.unquote(path[7:]))
            self._send(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                request_path = urllib.parse.urlparse(getattr(self, "path", "")).path or "/unknown"
                CORE.push(f"API SERVER ERROR [GET {request_path}]: {type(e).__name__}: {e}")
            except Exception:
                pass
            try: self._send(500, {"error": str(e)})
            except Exception: pass

    def do_POST(self):
        try:
            if not self._host_ok() or not secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN):
                self.close_connection = True
                return self._send(403, {"error": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length", "0") or 0)
            except (TypeError, ValueError):
                self.close_connection = True
                return self._send(400, {"error": "invalid content length"})
            if n < 0:
                self.close_connection = True
                return self._send(400, {"error": "invalid content length"})
            if n > 400_000:
                self.close_connection = True
                return self._send(413, {"error": "too large"})
            try:
                body = parse_json_object(self.rfile.read(n))
            except ValueError as exc:
                return self._send(400, {"error": str(exc)})
            path = urllib.parse.urlparse(self.path).path
            try:
                if path == "/api/client-log":
                    level = str(body.get("level", "info")).lower()
                    if level not in {"info", "error"}:
                        level = "info"
                    action = str(body.get("action", ""))[:120]
                    if not re.fullmatch(r"/api/[A-Za-z0-9_./-]{1,100}", action):
                        action = "/api/unknown"
                    message = str(body.get("message", ""))[:400]
                    message = re.sub(r"(?i)(api[ _-]?key|access[ _-]?token|token|password|secret)\s*[:=]\s*[^\s,;]+", r"\1=[REDACTED]", message)
                    message = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [REDACTED]", message)
                    CORE.push(f"UI {level.upper()} [{action}]: {message or 'Action completed.'}")
                    return self._send(200, {"ok": True})
                if path == "/api/start":
                    CORE.start(clean_cfg(body)); return self._send(200, {"ok": True})
                if path == "/api/creators/settings/save":
                    return self._send(200, {"settings": CORE.save_creator_settings(body.get("id", ""), body.get("settings", {}))})
                if path == "/api/creators/add":
                    return self._send(200, CORE.add_creator(body))
                if path == "/api/creators/remove":
                    return self._send(200, CORE.remove_creator(body.get("id")))
                if path == "/api/creators/open":
                    return self._send(200, CORE.open_creator_folder(body.get("id"), body.get("folder", "live_clips")))
                if path == "/api/creators/open-root":
                    return self._send(200, CORE.open_creators_folder())
                if path == "/api/creators/watch-vods":
                    return self._send(200, CORE.start_vod_watch(body.get("id")))
                if path == "/api/creators/stop-vod-watch":
                    return self._send(200, CORE.stop_vod_watch(body.get("id")))
                if path == "/api/creators/start":
                    return self._send(200, CORE.start_creator(body.get("id")))
                if path == "/api/creators/stop":
                    return self._send(200, CORE.stop_creator(body.get("id"), body.get("force", False)))
                if path == "/api/creators/stop-capture":
                    return self._send(200, CORE.stop_creator_capture(body.get("id"), body.get("force", False)))
                if path == "/api/settings":
                    cfg = clean_cfg(body)
                    if CORE.running and (cfg.get("rec_dir") != CORE.settings.get("rec_dir") or cfg.get("out_dir") != CORE.settings.get("out_dir")):
                        return self._send(400, {"error": "Stop clipping before changing storage folders."})
                    creator_id = str(cfg.get("creator_id") or "")
                    if creator_id and creator_id in CORE.creators:
                        CORE.save_creator_settings(creator_id, cfg)
                    else:
                        CORE.settings = cfg
                        CORE.default_settings = clean_cfg(cfg)
                        CORE.default_settings.pop("creator_id", None)
                        if not CORE.running: apply_storage_paths(cfg)
                        save_settings(cfg)
                    return self._send(200, {"ok": True})
                if path == "/api/stop":
                    CORE.stop(bool(body.get("force"))); return self._send(200, {"ok": True})
                if path == "/api/stop_file_holder":
                    return self._send(200, CORE.stop_file_holder(body.get("name"), body.get("pid")))
                if path == "/api/words":
                    text = str(body.get("text", ""))[:100_000]
                    CUSTOM_FILE.write_text(text, encoding="utf-8")
                    return self._send(200, {"ok": True, "entries": len(parse_custom(text))})
                if path == "/api/zernio":
                    return self._send(200, CORE.zernio_save(body))
                if path == "/api/zernio/accounts":
                    return self._send(200, {"accounts": CORE.zernio_accounts()})
                if path == "/api/zernio/publish":
                    names = body.get("names", [])
                    if not isinstance(names, list): names = []
                    return self._send(200, CORE.publish_clips([str(n) for n in names]))
                if path == "/api/publishing":
                    return self._send(200, CORE.publishing_save(body))
                if path == "/api/publishing/sync-posts":
                    return self._send(200, CORE.sync_zernio_posts())
                if path == "/api/publishing/accounts":
                    return self._send(200, {"accounts": CORE.publishing_accounts(
                        str(body.get("provider", "")).lower() or None,
                        connection_id=str(body.get("connection_id", "")).strip() or None,
                    )})
                if path == "/api/publishing/disconnect":
                    return self._send(200, CORE.disconnect_zernio_connection(body.get("connection_id")))
                if path == "/api/publishing/account":
                    return self._send(200, CORE.publishing_account_toggle(body))
                if path == "/api/publishing/publish":
                    names = body.get("names", [])
                    if body.get("all"):
                        posted_names = load_posted_registry()
                        scheduled_names = load_scheduled_registry()
                        names = [item["name"] for item in _clip_index()
                                 if item["name"] not in posted_names and item["name"] not in scheduled_names]
                    elif not isinstance(names, list): names = []
                    return self._send(200, CORE.publish_clips(
                        [str(n) for n in names],
                        account_ids=body.get("account_refs", body.get("account_ids")),
                        auto_schedule=bool(body.get("auto_schedule", False)),
                    ))
                if path == "/api/publishing/publish-one":
                    name = str(body.get("name", ""))
                    title = str(body.get("title", "")).strip()[:100]
                    description = str(body.get("description", "")).strip()[:2200]
                    if not title:
                        raise ValueError("Add a post title before publishing.")
                    caption = title + (("\n\n" + description) if description else "")
                    schedule_only = bool(body.get("auto_schedule", False))
                    return self._send(200, CORE.publish_clips(
                        [name], caption_overrides={name: caption},
                        account_ids=body.get("account_refs", body.get("account_ids")),
                        auto_schedule=schedule_only,
                        force_publish_now=not schedule_only,
                    ))
                if path == "/api/ai/settings":
                    return self._send(200, save_ai_settings(body))
                if path == "/api/ai/test":
                    return self._send(200, test_ai_settings(body))
                if path == "/api/ai/ollama/models":
                    cfg = load_ai_settings()
                    base = str(body.get("ollama_url", cfg["ollama_url"]))
                    return self._send(200, {"models": ollama_models(base)})
                if path == "/api/window/open":
                    cancel_window_close_shutdown(); return self._send(200, {"ok": True})
                if path == "/api/window/closing":
                    lease_id = str(body.get("id", "")).strip()
                    if lease_id:
                        close_window_lease(lease_id)
                    else:
                        schedule_window_close_shutdown()
                    return self._send(200, {"ok": True})
                if path == "/api/delete_all":
                    tab = str(body.get("clip_tab", "clips"))
                    if tab not in {"clips", "posted", "scheduled"}: tab = "clips"
                    posted = load_posted_registry()
                    scheduled = load_scheduled_registry()
                    names = [item["name"] for item in _clip_index()
                             if (
                                 (item["name"] in posted) if tab == "posted"
                                 else (item["name"] in posted or item["name"] in scheduled) if tab == "scheduled"
                                 else (item["name"] not in posted and item["name"] not in scheduled)
                             )]
                    deleted = []
                    preserve_history = tab in {"posted", "scheduled"}
                    for name in names:
                        try:
                            delete_clip_local_media(
                                name, preserve_delivery_history=preserve_history
                            )
                            deleted.append(name)
                        except FileNotFoundError:
                            continue
                    return self._send(200, {
                        "ok": True, "deleted": len(deleted),
                        "history_preserved": preserve_history,
                    })
                if path == "/api/delete_many":
                    names = body.get("names", [])
                    if not isinstance(names, list): names = []
                    posted = load_posted_registry()
                    scheduled = load_scheduled_registry()
                    requested_preserve = bool(body.get("preserve_delivery_history", False))
                    valid = [
                        str(name) for name in names
                        if CLIP_RE.fullmatch(str(name)) and find_clip_path(str(name))
                    ]
                    if not valid: return self._send(400, {"error": "No valid local clips selected."})
                    deleted = []
                    history_preserved = []
                    for name in valid:
                        preserve = requested_preserve or name in posted or name in scheduled
                        delete_clip_local_media(name, preserve_delivery_history=preserve)
                        deleted.append(name)
                        if preserve:
                            history_preserved.append(name)
                    return self._send(200, {
                        "ok": True, "deleted": len(deleted),
                        "history_preserved": history_preserved,
                    })
                if path in ("/api/delete", "/api/reveal"):
                    name = str(body.get("name", ""))
                    clip_path = find_clip_path(name)
                    if not clip_path:
                        return self._send(404, {"error": "Local video not found."})
                    if path == "/api/reveal":
                        reveal(clip_path)
                        return self._send(200, {"ok": True})
                    posted = load_posted_registry()
                    scheduled = load_scheduled_registry()
                    preserve = (
                        bool(body.get("preserve_delivery_history", False))
                        or name in posted or name in scheduled
                    )
                    result = delete_clip_local_media(
                        name, preserve_delivery_history=preserve
                    )
                    return self._send(200, result)
                if path == "/api/clip-metadata":
                    name = str(body.get("name", ""))
                    clip_path = find_clip_path(name)
                    local_exists = clip_path is not None
                    if clip_path is None:
                        stored_path = _clip_path_for_delivery_name(name)
                        clip_path = pathlib.Path(stored_path) if stored_path else None
                    if clip_path is None:
                        raise ValueError("Clip metadata is no longer available.")
                    title = re.sub(r"[\\r\n]+", " ", str(body.get("title", ""))).strip()[:100]
                    description = str(body.get("description", "")).replace("\\x00", "").strip()[:2200]
                    if not title:
                        raise ValueError("Add a title before saving clip metadata.")
                    sidecar = clip_path.with_suffix(".txt")
                    if local_exists and sidecar.is_symlink():
                        raise ValueError("The metadata sidecar is a symbolic link and cannot be edited.")
                    metadata = title + (("\n\n" + description) if description else "")
                    saved = save_clip_metadata(
                        clip_path, title, description, caption=metadata,
                        write_sidecar=local_exists,
                    )
                    CORE.push(f"Updated SQL clip metadata for {name}")
                    return self._send(200, {"ok": True, **saved})
                if path == "/api/open_folder":
                    open_folder(OUT); return self._send(200, {"ok": True})
                if path == "/api/output-preview":
                    return self._send(200, {"video": grab_output_preview(
                        str(body.get("mode", "live")), str(body.get("target", "")), body.get("settings")
                    )})
                if path == "/api/frame":
                    return self._send(200, {"image": grab_frame(str(body.get("mode", "live")), str(body.get("target", "")))})
                if path == "/api/facecam/detect":
                    return self._send(200, detect_facecam(str(body.get("mode", "live")), str(body.get("target", ""))))
                if path == "/api/browse":
                    return self._send(200, {"path": browse_file()})
                if path == "/api/browse_folder":
                    return self._send(200, {"path": browse_folder()})
                if path == "/api/check_updates":
                    return self._send(200, check_updates())
                if path == "/api/check_app_update":
                    return self._send(200, check_app_update())
                if path == "/api/install_app_update":
                    return self._send(200, install_app_update(body.get("parent_pid") if isinstance(body, dict) else None))
                if path == "/api/update_components":
                    return self._send(200, update_components())
                if path == "/api/quit":
                    CORE.stop(True)
                    CORE.stop_all_creators()
                    cancel_window_close_shutdown()
                    self._send(200, {"ok": True, "shutting_down": True})
                    schedule_quit_after_response()
                    return
            except (ValueError, RuntimeError, AIProviderError) as e:
                CORE.push(f"API VALIDATION ERROR [POST {path}]: {e}")
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
            try:
                request_path = urllib.parse.urlparse(getattr(self, "path", "")).path or "/unknown"
                CORE.push(f"API SERVER ERROR [POST {request_path}]: {type(e).__name__}: {e}")
            except Exception:
                pass
            try: self._send(500, {"error": str(e)})
            except Exception: pass

def open_window(url):
    """Open a dedicated, tracked browser app window without borrowing the user's profile."""
    cands = []
    if os.name == "nt":
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    cands += [shutil.which(x) for x in ("msedge", "google-chrome", "chrome", "chromium")]
    local = pathlib.Path(os.environ.get("LOCALAPPDATA") or (pathlib.Path.home() / "AppData" / "Local"))
    for exe in cands:
        if exe and os.path.exists(exe):
            browser = "msedge" if pathlib.Path(exe).stem.lower() == "msedge" else "chrome"
            profile = local / PRODUCT_NAME / "app-window-profile" / browser
            try:
                profile.mkdir(parents=True, exist_ok=True)
                process = popen([exe, f"--user-data-dir={profile}", "--no-first-run",
                                 "--no-default-browser-check", f"--app={url}", "--start-maximized"])
                with _CHILD_PROCESS_LOCK:
                    _APP_WINDOW_PROCESSES.add(process)
                return
            except Exception:
                pass
    webbrowser.open(url)


def resolve_bind_host(requested_host):
    """Keep the local desktop API bound to loopback, even if the environment is overridden."""
    candidate = str(requested_host or "").strip().lower()
    return candidate if candidate in {"127.0.0.1", "localhost", "::1"} else "127.0.0.1"


def should_open_browser_window(bind_host):
    """Keep browser windows out of native desktop-host launches."""
    if os.environ.get("STREAMSNIP_NATIVE_HOST", "").strip() == "1":
        return False
    return bind_host in ("127.0.0.1", "localhost", "::1")


def main():
    _PROCESS_SHUTDOWN.clear()
    QUIT.clear()
    if len(sys.argv) >= 2 and sys.argv[1] == "--streamlink":
        from streamlink_cli.main import main as streamlink_main
        # The frozen app uses this flag only to select the worker mode. Do not
        # pass our private flag into Streamlink's argument parser.
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        streamlink_main()
        return
    if len(sys.argv) >= 3 and sys.argv[1] in ("live", "file"):      # headless mode
        cfg = clean_cfg(dict(load_settings(), mode=sys.argv[1], target=sys.argv[2].strip('"')))
        if cfg["mode"] == "live" and not streamlink_available():
            sys.exit("streamlink isn't installed in this Python environment. Run:  pip install --only-binary=:all: streamlink")
        eng = Engine(cfg, lambda k, p: print(p) if k in ("log", "clip") else None)
        try: eng.run()
        except KeyboardInterrupt: eng.stop(force=True)
        return
    try:
        acquire_instance_lock()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return
    try:
        import uvicorn
        from api_server import create_app, patch_windows_proactor_connection_reset
    except ImportError as exc:
        print(f"FastAPI server dependencies are missing: {exc}. Run: python -m pip install -r requirements.txt", file=sys.stderr)
        return
    bind_host = resolve_bind_host(os.environ.get("STREAMSNIP_BIND_HOST", "127.0.0.1"))
    bind_port = int(os.environ.get("STREAMSNIP_PORT", "0"))
    app = create_app(
        AppRoutes,
        token=TOKEN,
        quit_event=QUIT,
        begin_window_lease=begin_window_lease,
        end_window_lease=end_window_lease,
        find_clip_path=find_clip_path,
        clip_regex=CLIP_RE,
        product_name=PRODUCT_NAME,
        version=APP_VERSION,
    )
    server = uvicorn.Server(uvicorn.Config(
        app,
        host=bind_host,
        port=bind_port,
        log_level="warning",
        access_log=False,
        server_header=False,
        lifespan="off",
        workers=1,
    ))
    patch_windows_proactor_connection_reset()
    server_thread = threading.Thread(target=server.run, daemon=True, name="streamsnip-api")
    server_thread.start()
    startup_deadline = time.monotonic() + 15.0
    while not server.started and server_thread.is_alive() and time.monotonic() < startup_deadline:
        time.sleep(0.05)
    if not server.started:
        server.should_exit = True
        server_thread.join(timeout=5)
        raise RuntimeError("The local FastAPI server failed to start within 15 seconds.")
    try:
        bound_port = server.servers[0].sockets[0].getsockname()[1]
    except (AttributeError, IndexError, OSError) as exc:
        server.should_exit = True
        server_thread.join(timeout=5)
        raise RuntimeError("The local FastAPI server started but its bound port could not be read.") from exc
    public_host = bind_host
    if ":" in public_host and not public_host.startswith("["):
        public_host = f"[{public_host}]"
    url = f"http://{public_host}:{bound_port}/"
    print(
        f"{PRODUCT_NAME} by ScarZero is running at {url}\n"
        "IMPORTANT: Keep this terminal window OPEN while StreamSnip AI is running.\n"
        "To close the app safely, click Quit inside StreamSnip AI and wait for it to shut down.\n"
        "Do NOT close this terminal directly. Doing so may interrupt active recording, clip processing, or uploads.",
        flush=True,
    )
    if should_open_browser_window(bind_host):
        dashboard_dist = pathlib.Path(__file__).resolve().parent / "dashboard" / "dist" / "index.html"
        # The packaged pywebview shell sets STREAMSNIP_NATIVE_HOST=1 and owns its own window.
        open_window(url.rstrip("/") + "/dashboard/" if dashboard_dist.is_file() else url)
    try:
        while not QUIT.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    cancel_window_close_shutdown()
    CORE.shutdown()
    try:
        time.sleep(0.3)
    except KeyboardInterrupt:
        pass
    server.should_exit = True
    server_thread.join(timeout=10)
    if server_thread.is_alive():
        server.force_exit = True
        server_thread.join(timeout=2)

if __name__ == "__main__":
    main()
