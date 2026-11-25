r"""StreamSnip AI  -  a local-first Twitch, YouTube, and VOD clipper.

The default workflow uses Streamlink, FFmpeg, faster-whisper, and hook-word
scoring locally without requiring a cloud AI key. Ollama provides optional
local AI analysis. Gemini and Hugging Face are optional hosted transcript
analysis providers, and Zernio is the optional publishing integration.

Windows/source setup:
    winget install Gyan.FFmpeg
    py -3.12 -m venv .venv ; .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt

Run:
    python autoclip.py                 -> opens the local StreamSnip AI window
    python autoclip.py live URL        -> headless live-stream mode
    python autoclip.py file video.mp4  -> headless local-file mode

Each finished clip is written as an MP4 plus a matching TXT caption/hashtag
file. Runtime paths, providers, captions, layouts, and custom hook words are
configurable from the local UI.
"""
import os, re, sys, glob, json, time, queue, shutil, secrets, threading, subprocess, pathlib, platform, base64, uuid, shlex, tempfile
import math
import mimetypes
import urllib.request
from importlib import metadata as importlib_metadata
import http.server, urllib.parse, webbrowser
import numpy as np
from ai_highlights import (AIAnalysisCancelled, AIProviderError, DEFAULT_GEMINI_MODEL,
                           DEFAULT_HUGGINGFACE_MODEL, RETIRED_GEMINI_MODELS,
                           ollama_models, select_moments, test_provider)
from post_metadata import (DEFAULT_GEMINI_COPY_MODEL, build_hook_word_copy,
                            build_transcript_fallback, generate_social_copy)
from browser_automation import BrowserAutomationManager, BrowserAutomationError
APP_VERSION = "4.0.1"
MAX_ACTIVE_CREATOR_MONITORS = 10
PRODUCT_NAME = "StreamSnip AI"
APP_RELEASES_URL = "https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest"
try:
    from zernio_poster import ZernioPublisher
    ZERNIO_AVAILABLE = True
except Exception:
    ZernioPublisher = None
    ZERNIO_AVAILABLE = False

# ------------------------------------------------------------------ setup
def _add_cuda_dlls():
    """Windows: let ctranslate2 find the cuBLAS DLLs installed by the nvidia-cublas-cu12 wheel."""
    if os.name != "nt":
        return
    roots = [pathlib.Path(p) for p in sys.path if p]
    for p in (getattr(sys, "_MEIPASS", ""), pathlib.Path(__file__).resolve().parent,
              pathlib.Path(__file__).resolve().parent / "_internal"):
        if p:
            roots.append(pathlib.Path(p))
    seen = set()
    for base in roots:
        d = base / "nvidia" / "cublas" / "bin"
        if str(d).lower() in seen:
            continue
        seen.add(str(d).lower())
        if d.is_dir():
            try: os.add_dll_directory(str(d))
            except OSError: pass
            os.environ["PATH"] = str(d) + os.pathsep + os.environ["PATH"]
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


def append_runtime_log(timestamp, message):
    """Persist a plain-text diagnostic trail in the app data directory."""
    try:
        with RUNTIME_LOG.open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} {message}\n")
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

def preferred_speech_device():
    return "cuda" if cuda_device_count() > 0 else "cpu"

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
    """Prefer a bundled FFmpeg in portable builds, then fall back to system PATH."""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    roots = [HERE, pathlib.Path(sys.executable).resolve().parent]
    for root in roots:
        bundled = root / "vendor" / "ffmpeg" / name
        if bundled.is_file():
            return str(bundled)
    return shutil.which("ffmpeg") or "ffmpeg"

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
            with urllib.request.urlopen(req, timeout=8) as response:
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

def check_app_update():
    """Check the published StreamSnip AI release without changing the local install."""
    req = urllib.request.Request(
        "https://api.github.com/repos/sifat-jaman-13/stream-clip-ai/releases/latest",
        headers={"User-Agent": "StreamSnip AI version checker"},
    )
    with urllib.request.urlopen(req, timeout=8) as response:
        data = json.loads(response.read())
    latest = str(data.get("tag_name", "")).lstrip("v") or APP_VERSION
    current_key = tuple(int(part) for part in re.findall(r"\d+", APP_VERSION))
    latest_key = tuple(int(part) for part in re.findall(r"\d+", latest))
    assets = data.get("assets") if isinstance(data.get("assets"), list) else []
    installer = next((asset for asset in assets
                     if str(asset.get("name", "")).lower().endswith(".exe")
                     and "setup" in str(asset.get("name", "")).lower()
                     and asset.get("browser_download_url")), None)
    return {"current": APP_VERSION, "latest": latest, "update": latest_key > current_key,
            "url": data.get("html_url") or APP_RELEASES_URL,
            "installer_url": installer.get("browser_download_url") if installer else "",
            "installer_name": installer.get("name", "") if installer else "",
            "name": data.get("name") or ("StreamSnip AI v" + latest)}

def update_components():
    """Update Python runtime components and download the selected speech model.
    FFmpeg is reported by the checker; bundled FFmpeg is replaced only by a new build.
    """
    if getattr(sys, "frozen", False):
        raise RuntimeError("This app bundles its runtime components. Download and install the latest StreamSnipAI-Setup.exe to update them.")
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
INSTANCE_LOCK_FILE = _data_root / ".autoclip.lock"
_INSTANCE_LOCK_HANDLE = None
STORAGE_PATH_WARNING = ""

CF = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0      # no flashing console windows
_CHILD_PROCESS_LOCK = threading.RLock()
_CHILD_PROCESSES = set()
_PROCESS_SHUTDOWN = threading.Event()

def _forget_child_process(process):
    with _CHILD_PROCESS_LOCK:
        _CHILD_PROCESSES.discard(process)

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
    """Prevent new children and synchronously remove every tracked app process."""
    _PROCESS_SHUTDOWN.set()
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
    "clips_per_chunk": 2, "chunk_min": 3, "pre": 20, "post": 15, "min_score": 80,
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
    "crop_w": 31.6, "crop_h": 100.0, "delete_rec": False,
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
    num("pre", 3, 90, int); num("post", 3, 90, int)
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
    tag = re.sub(r"[\r\n{}\\]", "", str(raw.get("streamer_tag", c["streamer_tag"]))).strip()[:80]
    c["streamer_tag"] = tag
    c["show_tag_video"] = bool(raw.get("show_tag_video", c["show_tag_video"]))
    f = str(raw.get("font", c["font"])).strip()
    if re.fullmatch(r"[A-Za-z0-9 \-]{1,40}", f): c["font"] = f
    c["delete_rec"] = bool(raw.get("delete_rec", False))
    for k in ("rec_dir", "out_dir", "creator_rec_dir", "creator_out_dir"):
        value = str(raw.get(k, "") or "").strip()
        # Keep user-selected paths portable across Windows installs while avoiding
        # control characters or excessively large values in settings.json.
        c[k] = value[:1000] if "\x00" not in value else ""
    creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(raw.get("creator_id", "")))[:48]
    if creator_id:
        c["creator_id"] = creator_id
    return c

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
    override = re.sub(r"[\r\n{}\\]", "", str(cfg.get("streamer_tag", "")).strip())[:80]
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
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return dict(DEFAULTS)
        # Version 1 stored min_score on a 0-5 scale. Version 2 uses 0-100.
        if int(raw.get("_settings_version", 1)) < SETTINGS_VERSION:
            try:
                old_score = float(raw.get("min_score"))
                if 0 < old_score <= 5:
                    raw["min_score"] = round(50 + old_score * 20, 1)
            except (TypeError, ValueError, OverflowError):
                pass
        return clean_cfg(raw)
    except Exception:
        return dict(DEFAULTS)

def save_settings(cfg):
    try:
        cfg = dict(cfg)
        cfg["_settings_version"] = SETTINGS_VERSION
        atomic_json_write(SETTINGS_FILE, cfg)
    except Exception as exc:
        print(f"Could not save settings: {exc}", file=sys.stderr)

def load_zernio_settings():
    try:
        raw = json.loads(ZERNIO_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def save_zernio_settings(cfg):
    # This file is local-only and ignored by Git. Never send the API key to the browser.
    atomic_json_write(ZERNIO_FILE, cfg)

def load_publishing_settings():
    defaults = {"provider": "zernio", "zernio": load_zernio_settings()}
    try:
        raw = json.loads(PUBLISHING_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            zernio = raw.get("zernio")
            if isinstance(zernio, dict):
                defaults["zernio"].update(zernio)
    except Exception:
        pass
    return defaults

def save_publishing_settings(cfg):
    atomic_json_write(PUBLISHING_FILE, cfg)

def load_posted_registry():
    try:
        raw = json.loads(POSTED_FILE.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}

def save_posted_registry(registry):
    atomic_json_write(POSTED_FILE, registry)

def mark_clip_posted(name, platform="manual", accounts=None):
    path = find_clip_path(name)
    if not path:
        raise ValueError("Clip not found.")
    registry = load_posted_registry()
    registry[name] = {
        "posted_at": time.time(), "platform": str(platform or "manual")[:40],
        "accounts": [str(x)[:100] for x in (accounts or [])][:20],
    }
    save_posted_registry(registry)
    invalidate_clip_cache()
    return registry[name]

def forget_posted_clips(names):
    registry = load_posted_registry()
    changed = False
    for name in names:
        if name in registry:
            registry.pop(name, None)
            changed = True
    if changed:
        save_posted_registry(registry)
    invalidate_clip_cache()

def load_ai_settings():
    defaults = {"provider": "gemini", "ollama_url": os.environ.get("STREAMSNIP_OLLAMA_URL", "http://127.0.0.1:11434"), "ollama_model": "",
                "gemini_model": DEFAULT_GEMINI_COPY_MODEL, "huggingface_model": DEFAULT_HUGGINGFACE_MODEL,
                "custom_api_base": "https://api.openai.com/v1", "custom_api_model": "",
                "custom_api_key": "", "gemini_api_key": "",
                "huggingface_token": os.environ.get("HF_TOKEN", os.environ.get("HUGGING_FACE_HUB_TOKEN", "")),
                "metadata_copy_enabled": "true", "huggingface_setup_completed": "false"}
    try:
        data = json.loads(AI_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict): defaults.update({k: str(v) for k, v in data.items() if k in defaults and v is not None})
    except Exception:
        pass
    # AI-written titles and descriptions are always enabled; ignore legacy opt-out values.
    defaults["metadata_copy_enabled"] = "true"
    if defaults["provider"] not in {"hooks", "ollama", "gemini", "huggingface", "custom"}:
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
            "huggingface_token_set": bool(cfg["huggingface_token"]),
            "metadata_copy_enabled": str(cfg.get("metadata_copy_enabled", "true")).strip().lower() not in {"0", "false", "no", "off"}}

def save_ai_settings(body):
    cfg = load_ai_settings()
    previous_huggingface_token = str(cfg.get("huggingface_token", "")).strip()
    provider = str(body.get("provider", cfg["provider"]))
    if provider not in {"hooks", "ollama", "gemini", "huggingface", "custom"}:
        raise ValueError("Unknown AI highlight provider.")
    cfg["provider"] = provider
    # Retain a true value for compatibility with older settings files and clients.
    cfg["metadata_copy_enabled"] = "true"
    for key in ("ollama_url", "ollama_model", "gemini_model", "huggingface_model",
                "custom_api_base", "custom_api_model"):
        if key in body:
            cfg[key] = str(body[key]).strip()[:1000]
    for key in ("gemini_api_key", "huggingface_token", "custom_api_key"):
        if body.get(key): cfg[key] = str(body[key]).strip()[:2000]
    if body.get("clear_gemini_key"): cfg["gemini_api_key"] = ""
    if body.get("clear_custom_api_key"): cfg["custom_api_key"] = ""
    if body.get("clear_huggingface_token"):
        cfg["huggingface_token"] = ""
        for name in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
            if previous_huggingface_token and os.environ.get(name, "").strip() == previous_huggingface_token:
                os.environ.pop(name, None)
    atomic_json_write(AI_SETTINGS_FILE, cfg)
    apply_huggingface_token()
    return public_ai_settings()

def test_ai_settings(body):
    """Test entered or saved provider credentials without returning or persisting secrets."""
    body = body if isinstance(body, dict) else {}
    cfg = load_ai_settings()
    provider = str(body.get("provider", cfg["provider"]))
    if provider not in {"hooks", "ollama", "gemini", "huggingface", "custom"}:
        raise ValueError("Unknown AI highlight provider.")
    cfg["provider"] = provider
    for key in ("ollama_url", "ollama_model", "gemini_model", "huggingface_model",
                "custom_api_base", "custom_api_model"):
        if key in body:
            cfg[key] = str(body[key]).strip()[:1000]
    for key in ("gemini_api_key", "huggingface_token", "custom_api_key"):
        if body.get(key):
            cfg[key] = str(body[key]).strip()[:2000]
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
    for line in re.split(r"[\r\n,;]+", str(extra_terms or "")):
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
    # aeval preserves the incoming channel layout and original audio outside
    # the censored word intervals. The beep replaces, rather than overlays,
    # the speech inside those exact intervals.
    return (
        "aeval=exprs='if("
        + expression
        + ",0.18*sin(2*PI*1000*t),val(ch))'"
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
    # NeonClipping-inspired GTA look, independently implemented for StreamSnip.
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

def clip_bounds(peak, duration, before, after, words, limit=60):
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
        for attempt in range(2):
            try:
                model = self.get_model(self.cfg["model"])
                segs, _ = model.transcribe(src, word_timestamps=True, vad_filter=True, language=lang)
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
    def render(self, src, start, end, words, name):
        cfg = self.cfg
        words = censor_transcript_words(
            words, enabled=cfg.get("profanity_filter_enabled", True),
            extra_terms=cfg.get("profanity_filter_words", "")
        )
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
        cmd = [ffmpeg_exe(), "-y", "-v", "error", "-fflags", "+genpts", "-ss", f"{start:.2f}", "-accurate_seek",
               "-t", f"{end - start:.2f}", "-i", str(pathlib.Path(src).resolve()),
               "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
               *enc, "-pix_fmt", "yuv420p", "-af", audio_filter,
               "-c:a", "aac", "-b:a", "160k", "-r", "30", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", tmp]
        r = run(cmd, cwd=self.out_dir, capture_output=True, text=True)
        (self.out_dir / f"{name}.ass").unlink(missing_ok=True)
        if r.returncode != 0:
            (self.out_dir / tmp).unlink(missing_ok=True)
            raise RuntimeError((r.stderr or "ffmpeg failed").strip()[-400:])
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
            if transcript and provider in {"ollama", "gemini", "huggingface", "custom"}:
                post_copy = generate_social_copy(transcript, tag, ai_cfg, log=self.log)
            elif transcript and provider == "hooks":
                self.log("Hook words is selected; the strongest exact hook phrase is used as the title.")
                hook_terms = dict(load_custom())
                hook_terms.update({term: 1.0 for term in HYPE_WORDS | HYPE_PHRASES})
                post_copy = build_hook_word_copy(transcript, tag, hook_terms)
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
            start, end = clip_bounds(p, dur, self.cfg["pre"], self.cfg["post"], raw_words)
            base_name = f"{stem}_{stamp}_clip{i}"
            name = base_name
            suffix = 2
            while (self.out_dir / f"{name}.mp4").exists() or (self.out_dir / f"{name}.tmp.mp4").exists():
                name = f"{base_name}_{suffix}"
                suffix += 1
            self.status(f"Rendering clip {i} of {len(peaks)} (hype score {sc:.1f})...", "rendering",
                        int((i - 1) / max(1, len(peaks)) * 100))
            try:
                self.render(path, start, end, words, name)
                rendered_count += 1
                self.status(f"Rendered clip {i} of {len(peaks)}.", "rendering",
                            int(i / max(1, len(peaks)) * 100))
            except FileBusyError as e:
                self.emit("file_lock", e.details)
            except Exception as e:
                self.log(f"Render error: {e}")
        self.emit("chunk", "")
        # Live capture chunks are temporary working files, not user-owned VODs.
        # Free disk space after a completed analysis that produced clips or no worthwhile moments.
        # Keep the source if every render failed so the user can retry it.
        same_recording_dir = os.path.normcase(str(pth.parent.resolve())) == os.path.normcase(str(self.rec_dir.resolve()))
        if self.cfg.get("mode", "live") == "live" and same_recording_dir and (not peaks or rendered_count > 0):
            try:
                pth.unlink(missing_ok=True)
                reason = "no worthwhile clips" if not peaks else f"{rendered_count} clip(s) rendered"
                self.log(f"Deleted temporary live recording {pth.name} after processing ({reason}).")
            except OSError as exc:
                self.log(f"Could not delete temporary live recording {pth.name}: {exc}")

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
        apply_storage_paths(self.settings)
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
        return _data_root / "creators.json"

    def _load_creator_profiles(self):
        try:
            raw = json.loads(self._creator_profiles_path().read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return {}
            profiles = {}
            for item in raw[:100]:
                if not isinstance(item, dict):
                    continue
                creator_id = re.sub(r"[^A-Za-z0-9_-]", "", str(item.get("id", "")))[:48]
                name = re.sub(r"[\r\n\x00-\x1f]", "", str(item.get("name", ""))).strip()[:80]
                target = str(item.get("target", "")).strip()[:1000]
                if creator_id and name and target:
                    profiles[creator_id] = {"id": creator_id, "name": name, "target": target}
            return profiles
        except (OSError, ValueError, TypeError):
            return {}

    def _save_creator_profiles(self):
        atomic_json_write(self._creator_profiles_path(), list(self.creators.values()))

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
                result.append({**profile, **status,
                               "running": bool(self.creator_workers.get(creator_id) and self.creator_workers[creator_id].is_alive()),
                               "watching_vods": bool(watcher and watcher.is_alive())})
            return result

    def add_creator(self, body):
        name = re.sub(r"[\r\n\x00-\x1f]", "", str(body.get("name", ""))).strip()[:80]
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
            if worker and worker.is_alive():
                raise ValueError("This creator is already being monitored.")
            active = sum(1 for thread in self.creator_workers.values() if thread.is_alive())
            if active >= MAX_ACTIVE_CREATOR_MONITORS:
                raise ValueError(f"All {MAX_ACTIVE_CREATOR_MONITORS} creator monitor slots are active. Stop one before starting another.")
            paths = self._ensure_creator_paths(creator_id)
            cfg = clean_cfg({**self.settings, "mode": "live", "target": profile["target"],
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
            engine.stop(force=bool(force))
            self.creator_status[creator_id] = {"phase": "stopping", "status": "Stopping monitor...",
                                               "clips": self.creator_status.get(creator_id, {}).get("clips", 0)}
        return {"ok": True}

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
        cfg = dict(self._config_for(), enabled=enabled)
        return ZernioPublisher(
            self.push, cfg,
            on_success=lambda path: mark_clip_posted(path.name, "zernio", list(cfg.get("accounts", {}).keys()) or
                                                     [key for key in ("instagram", "youtube") if cfg.get(key + "_id")]),
        ) if ZERNIO_AVAILABLE else None

    def _provider_status(self, provider):
        cfg = self._config_for()
        return {"configured": bool(cfg.get("api_key")), "api_key_set": bool(cfg.get("api_key")),
                "available": ZERNIO_AVAILABLE, "base_url": "https://zernio.com"}

    def push(self, msg):
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            self.log_id += 1
            message = str(msg)
            self.logs.append((self.log_id, timestamp, message, None))
            append_runtime_log(timestamp, message)
            if len(self.logs) > 800:
                del self.logs[:200]

    def push_file_lock(self, details):
        with self.lock:
            timestamp = time.strftime("%H:%M:%S")
            self.log_id += 1
            message = str(details["message"])
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
            self.settings = cfg
            apply_storage_paths(cfg)
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
                self.engine.stop(force=force)
                self.push("Stopping now." if (force or self.engine.cfg["mode"] != "live")
                          else "Stopping the recording - finishing the clips already captured.")

    def state(self, since, clip_offset=0, clip_tab="clips"):
        clips = list_clips(offset=clip_offset, clip_tab=clip_tab)
        clip_total = len(list_clips(limit=1_000_000, clip_tab=clip_tab))
        posted_registry = load_posted_registry()
        posted_total = sum(1 for item in _clip_index() if item["name"] in posted_registry)
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
        try:
            BROWSER_AUTOMATION.stop()
        except Exception:
            pass
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

    def zernio_status(self):
        cfg = self._config_for("zernio")
        return dict(self._provider_status("zernio"), accounts=dict(cfg.get("accounts", {})) if isinstance(cfg.get("accounts"), dict) else {}, auto_post=bool(cfg.get("auto_post")),
                    schedule_minutes=int(cfg.get("schedule_minutes", 0) or 0),
                    visibility=cfg.get("visibility", "public"),
                    instagram_id=cfg.get("instagram_id", ""), youtube_id=cfg.get("youtube_id", ""))

    def publishing_status(self):
        cfg = self._config_for()
        return {"provider": "zernio", "providers": {"zernio": dict(self._provider_status("zernio"),
                schedule_minutes=int(cfg.get("schedule_minutes", 0) or 0),
                visibility=cfg.get("visibility", "public"),
                instagram_id=cfg.get("instagram_id", ""),
                youtube_id=cfg.get("youtube_id", ""),
                accounts=dict(cfg.get("accounts", {})) if isinstance(cfg.get("accounts"), dict) else {},
                auto_post=bool(cfg.get("auto_post", False)))},
                **self._provider_status("zernio")}

    def publishing_save(self, body):
        provider = str(body.get("provider", "zernio")).lower()
        if provider != "zernio": raise ValueError("Only Zernio publishing is supported.")
        cfg = dict(self._config_for())
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
            supported = {"twitter", "instagram", "facebook", "linkedin", "tiktok", "youtube",
                         "pinterest", "reddit", "bluesky", "threads", "googlebusiness"}
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

    def publishing_accounts(self, provider=None):
        pub = self._make_publisher("zernio", False)
        if not pub: raise ValueError("Zernio posting is unavailable.")
        return pub.accounts()

    def zernio_save(self, body):
        body = dict(body); body["provider"] = "zernio"
        return self.publishing_save(body)

    def zernio_accounts(self):
        return self.publishing_accounts("zernio")

    def publish_clips(self, names, caption_overrides=None, account_ids=None):
        provider = "zernio"
        cfg = self._config_for()
        if not cfg.get("api_key"): raise ValueError(f"Save and verify a {provider.title()} API key first.")
        selected_accounts = account_ids if isinstance(account_ids, dict) else cfg.get("accounts", {})
        if not isinstance(selected_accounts, dict):
            selected_accounts = {}
        selected_accounts = {
            str(platform).strip().lower(): str(account_id).strip()
            for platform, account_id in selected_accounts.items()
            if str(platform).strip().lower() in {"twitter", "instagram", "facebook", "linkedin", "tiktok",
                                                  "youtube", "pinterest", "reddit", "bluesky", "threads",
                                                  "googlebusiness"} and str(account_id).strip()
        }
        if not selected_accounts:
            for platform in ("instagram", "youtube"):
                if cfg.get(platform + "_id"):
                    selected_accounts[platform] = str(cfg[platform + "_id"])
        if not selected_accounts:
            raise ValueError("Connect and select at least one Zernio social account in Settings.")
        valid = [str(n) for n in names if CLIP_RE.fullmatch(str(n)) and find_clip_path(str(n))]
        if not valid: raise ValueError("No valid clips selected.")
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
                        if publisher:
                            publisher.on_success = lambda path: mark_clip_posted(path.name, "zernio", list(selected_accounts.keys()))
                        delay = int(cfg.get("schedule_minutes", 0) or 0) * (index + 1)
                        with self.lock: self.posting["current"] = name
                        self.push(f"{provider.title()}: uploading {index + 1} of {len(valid)} - {name}.")
                        caption_override = (caption_overrides or {}).get(name) if isinstance(caption_overrides, dict) else None
                        clip_path = find_clip_path(name)
                        if not clip_path:
                            raise FileNotFoundError(f"Clip is no longer available: {name}")
                        publisher.publish_one(clip_path, schedule_minutes=delay,
                                              accounts=selected_accounts, caption_override=caption_override)
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

def split_clip_post_copy(text):
    """Split the public clip sidecar into editable title and description fields."""
    value = str(text or "").strip()
    if not value:
        return "", ""
    parts = value.split("\n\n", 1)
    return parts[0].strip(), parts[1].strip() if len(parts) > 1 else ""


def list_clips(limit=60, offset=0, clip_tab="clips"):
    posted = load_posted_registry()
    indexed = _clip_index()
    if clip_tab == "posted":
        indexed = [item for item in indexed if item["name"] in posted]
        indexed.sort(key=lambda item: float(posted[item["name"]].get("posted_at", item["mtime"])), reverse=True)
    else:
        indexed = [item for item in indexed if item["name"] not in posted]
    items = [dict(item) for item in indexed[max(0, int(offset)):max(0, int(offset)) + max(1, int(limit))]]
    for item in items:
        clip_path = pathlib.Path(item.pop("_path"))
        try:
            item["caption"] = clip_path.with_suffix(".txt").read_text(encoding="utf-8")
        except Exception:
            item["caption"] = ""
        item["title"], item["description"] = split_clip_post_copy(item["caption"])
        item["posted"] = item["name"] in posted
        item["posted_at"] = posted.get(item["name"], {}).get("posted_at")
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
        result = run([ffmpeg_exe(), "-y", "-v", "error", "-i", stream_url,
                      "-t", "22", "-an", "-c:v", "libx264", "-preset", "ultrafast",
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
        sample_words = [(0.0, 0.78, "THAT"), (0.78, 1.52, "WAS"), (1.52, preview_duration, "INSANE!")]
        make_ass(sample_words, 0.0, preview_duration, ass_path, cfg)
        video_filter = render_video_filter(cfg, ass_path.name)
        last_error = ""
        for input_args in input_attempts:
            preview_path.unlink(missing_ok=True)
            result = run(
                [ffmpeg_exe(), "-y", "-v", "error", *input_args,
                 "-t", f"{preview_duration:.2f}", "-filter_complex", video_filter,
                 "-map", "[v]", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                 "-crf", "28", "-r", "24", "-pix_fmt", "yuv420p",
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
BROWSER_AUTOMATION = BrowserAutomationManager()
TOKEN = secrets.token_urlsafe(24)

# ------------------------------------------------------------------ http server
def parse_json_object(raw):
    """Parse a JSON request body and reject malformed or non-object payloads."""
    try:
        body = json.loads(raw or b"{}")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("invalid JSON body") from exc
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


class Handler(http.server.BaseHTTPRequestHandler):
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
                if tab not in {"clips", "posted"}: tab = "clips"
                registry = load_posted_registry()
                names = [item["name"] for item in _clip_index()
                         if (item["name"] in registry) == (tab == "posted")]
                return self._send(200, {"names": names})
            if path == "/api/creators":
                return self._send(200, {"creators": CORE.list_creators()})
            if path == "/api/config":
                # Public UI configuration only: never expose provider credentials.
                return self._send(200, {"settings": CORE.settings, "ai": public_ai_settings(),
                                        "transcriber_models": MODELS, "layouts": LAYOUTS,
                                        "output_formats": list(OUTPUT_FORMATS.keys())})
            if path == "/api/browser/status":
                return self._send(200, BROWSER_AUTOMATION.status())
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
                if clip_tab not in {"clips", "posted"}: clip_tab = "clips"
                return self._send(200, CORE.state(since, clip_offset, clip_tab))
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
                if path == "/api/creators/add":
                    return self._send(200, CORE.add_creator(body))
                if path == "/api/creators/remove":
                    return self._send(200, CORE.remove_creator(body.get("id")))
                if path == "/api/creators/open":
                    return self._send(200, CORE.open_creator_folder(body.get("id"), body.get("folder", "live_clips")))
                if path == "/api/creators/watch-vods":
                    return self._send(200, CORE.start_vod_watch(body.get("id")))
                if path == "/api/creators/stop-vod-watch":
                    return self._send(200, CORE.stop_vod_watch(body.get("id")))
                if path == "/api/creators/start":
                    return self._send(200, CORE.start_creator(body.get("id")))
                if path == "/api/creators/stop":
                    return self._send(200, CORE.stop_creator(body.get("id"), body.get("force", False)))
                if path == "/api/settings":
                    cfg = clean_cfg(body)
                    if CORE.running and (cfg.get("rec_dir") != CORE.settings.get("rec_dir") or cfg.get("out_dir") != CORE.settings.get("out_dir")):
                        return self._send(400, {"error": "Stop clipping before changing storage folders."})
                    CORE.settings = cfg
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
                if path == "/api/browser/prepare":
                    name = str(body.get("name", ""))
                    clip_path = find_clip_path(name)
                    if not clip_path:
                        return self._send(404, {"error": "Clip not found."})
                    result = BROWSER_AUTOMATION.prepare(
                        video_path=clip_path,
                        platform=str(body.get("platform", "")),
                        title=str(body.get("title", "")),
                        description=str(body.get("description", "")),
                        browser=str(body.get("browser", "default")).lower(),
                    )
                    return self._send(200, result)
                if path == "/api/browser/close":
                    BROWSER_AUTOMATION.close()
                    return self._send(200, {"ok": True})
                if path == "/api/publishing":
                    return self._send(200, CORE.publishing_save(body))
                if path == "/api/publishing/accounts":
                    return self._send(200, {"accounts": CORE.publishing_accounts(str(body.get("provider", "")).lower() or None)})
                if path == "/api/publishing/publish":
                    names = body.get("names", [])
                    if body.get("all"):
                        posted_names = load_posted_registry()
                        names = [item["name"] for item in _clip_index()
                                 if item["name"] not in posted_names]
                    elif not isinstance(names, list): names = []
                    return self._send(200, CORE.publish_clips([str(n) for n in names],
                                                               account_ids=body.get("account_ids")))
                if path == "/api/publishing/publish-one":
                    name = str(body.get("name", ""))
                    title = str(body.get("title", "")).strip()[:100]
                    description = str(body.get("description", "")).strip()[:2200]
                    if not title:
                        raise ValueError("Add a post title before publishing.")
                    caption = title + (("\n\n" + description) if description else "")
                    return self._send(200, CORE.publish_clips([name], caption_overrides={name: caption},
                                                               account_ids=body.get("account_ids")))
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
                    if tab not in {"clips", "posted"}: tab = "clips"
                    registry = load_posted_registry()
                    names = [item["name"] for item in _clip_index()
                             if (item["name"] in registry) == (tab == "posted")]
                    deleted = []
                    for name in names:
                        clip_path = find_clip_path(name)
                        if not clip_path: continue
                        for target in (clip_path, clip_path.with_suffix(".txt")):
                            target.unlink(missing_ok=True)
                        deleted.append(name)
                    forget_posted_clips(deleted)
                    return self._send(200, {"ok": True, "deleted": len(deleted)})
                if path == "/api/delete_many":
                    names = body.get("names", [])
                    if not isinstance(names, list): names = []
                    valid = [str(n) for n in names if CLIP_RE.fullmatch(str(n)) and find_clip_path(str(n))]
                    if not valid: return self._send(400, {"error": "No valid clips selected."})
                    for name in valid:
                        clip_path = find_clip_path(name)
                        if not clip_path:
                            continue
                        for target in (clip_path, clip_path.with_suffix(".txt")):
                            try:
                                target.unlink(missing_ok=True)
                            except OSError as exc:
                                if os.name == "nt" and getattr(exc, "winerror", None) in (32, 33):
                                    details = describe_file_lock(target, exc)
                                    CORE.push_file_lock(details)
                                    raise RuntimeError(details["message"]) from exc
                                raise
                    forget_posted_clips(valid)
                    return self._send(200, {"ok": True, "deleted": len(valid)})
                if path in ("/api/delete", "/api/reveal"):
                    name = str(body.get("name", ""))
                    clip_path = find_clip_path(name)
                    if not clip_path:
                        return self._send(404, {"error": "Clip not found."})
                    if path == "/api/reveal":
                        reveal(clip_path)
                    else:
                        for target in (clip_path, clip_path.with_suffix(".txt")):
                            try:
                                target.unlink(missing_ok=True)
                            except OSError as exc:
                                if os.name == "nt" and getattr(exc, "winerror", None) in (32, 33):
                                    details = describe_file_lock(target, exc)
                                    CORE.push_file_lock(details)
                                    raise RuntimeError(details["message"]) from exc
                                raise
                    if path == "/api/delete":
                        forget_posted_clips([name])
                    return self._send(200, {"ok": True})
                if path == "/api/clip-metadata":
                    name = str(body.get("name", ""))
                    clip_path = find_clip_path(name)
                    if not clip_path:
                        raise ValueError("Clip not found.")
                    title = re.sub(r"[\r\n]+", " ", str(body.get("title", ""))).strip()[:100]
                    description = str(body.get("description", "")).replace("\x00", "").strip()[:2200]
                    if not title:
                        raise ValueError("Add a title before saving clip metadata.")
                    sidecar = clip_path.with_suffix(".txt")
                    if sidecar.is_symlink():
                        raise ValueError("The metadata sidecar is a symbolic link and cannot be edited.")
                    metadata = title + (("\n\n" + description) if description else "")
                    sidecar.write_text(metadata, encoding="utf-8")
                    CORE.push(f"Updated TXT metadata for {name}")
                    return self._send(200, {"ok": True, "name": name, "caption": metadata})
                if path == "/api/posted/mark":
                    name = str(body.get("name", ""))
                    posted = mark_clip_posted(name, body.get("platform", "manual"), body.get("accounts", []))
                    return self._send(200, {"ok": True, "posted": posted})
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
                if path == "/api/update_components":
                    return self._send(200, update_components())
                if path == "/api/quit":
                    CORE.stop(True)
                    CORE.stop_all_creators()
                    cancel_window_close_shutdown(); self._send(200, {"ok": True}); QUIT.set(); return
            except (ValueError, AIProviderError) as e:
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
    """Open as a clean app window (Edge/Chrome --app) when possible, else the default browser."""
    cands = []
    if os.name == "nt":
        for env in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
            base = os.environ.get(env)
            if base:
                cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                          os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    cands += [shutil.which(x) for x in ("msedge", "google-chrome", "chrome", "chromium")]
    for exe in cands:
        if exe and os.path.exists(exe):
            try:
                subprocess.Popen([exe, f"--app={url}", "--start-maximized"])
                return
            except Exception:
                pass
    webbrowser.open(url)

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
        from api_server import create_app
    except ImportError as exc:
        print(f"FastAPI server dependencies are missing: {exc}. Run: python -m pip install -r requirements.txt", file=sys.stderr)
        return
    bind_host = os.environ.get("STREAMSNIP_BIND_HOST", "127.0.0.1")
    bind_port = int(os.environ.get("STREAMSNIP_PORT", "0"))
    app = create_app(
        Handler,
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
    public_host = "127.0.0.1" if bind_host in ("0.0.0.0", "::") else bind_host
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
    if bind_host in ("127.0.0.1", "localhost", "::1"):
        dashboard_dist = pathlib.Path(__file__).resolve().parent / "dashboard" / "dist" / "index.html"
        # Launch the new workspace by default; keep the classic interface at / for legacy controls.
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


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" type="image/png" href="/assets/app-icon.png">
<title>StreamSnip AI</title>
<style>
:root{--bg:#07080d;--card:rgba(255,255,255,.035);--card2:rgba(255,255,255,.07);--line:rgba(255,255,255,.08);--line2:rgba(255,255,255,.16);
--tx:#eef0f7;--dim:#9a9fb5;--mute:#646a82;--a1:#8b5cf6;--a2:#ec4899;--ok:#34d399;--warn:#fbbf24;--bad:#f87171;--grad:linear-gradient(135deg,var(--a1),var(--a2))}
*{box-sizing:border-box;margin:0;padding:0}
[hidden]{display:none!important}
html,body{height:100%}
body{background:var(--bg);color:var(--tx);font:14px/1.45 "Segoe UI Variable Text","Segoe UI",Inter,system-ui,-apple-system,sans-serif;overflow:hidden;-webkit-font-smoothing:antialiased}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:radial-gradient(900px 520px at 6% -12%,rgba(139,92,246,.24),transparent 60%),radial-gradient(800px 480px at 100% -5%,rgba(236,72,153,.15),transparent 60%)}
::-webkit-scrollbar{width:10px;height:10px}::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1);border-radius:10px;border:2px solid transparent;background-clip:padding-box}::-webkit-scrollbar-thumb:hover{background:rgba(255,255,255,.2);background-clip:padding-box;border:2px solid transparent}
button{font:inherit;color:inherit;cursor:pointer;border:0;background:none}
.app{position:relative;height:100%;display:grid;grid-template-rows:auto 1fr}
header{display:flex;align-items:center;gap:14px;padding:16px 22px}
.logo{display:flex;align-items:center;gap:11px;font-weight:700;font-size:18px;letter-spacing:-.2px}
.mark{width:34px;height:34px;flex:0 0 34px;border-radius:11px;background:#0b0000;display:grid;place-items:center;overflow:hidden;box-shadow:0 6px 22px rgba(139,92,246,.45);border:1px solid rgba(255,255,255,.12)}
.mark img{width:100%;height:100%;object-fit:cover}
.tag{color:var(--dim);font-weight:400;font-size:13px;margin-left:2px}
.sp{flex:1}
.main{position:relative;display:grid;grid-template-columns:430px minmax(0,1fr);gap:18px;padding:0 22px 22px;min-height:0}
.left{display:flex;flex-direction:column;min-height:0;gap:0}
.scroll{display:flex;flex-direction:column;flex:1;overflow:auto;padding-right:6px;margin-right:-6px}
.right{display:flex;flex-direction:column;min-height:0;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin-bottom:14px;backdrop-filter:blur(8px)}
.ai-card{order:-1;border-color:rgba(139,92,246,.48);background:radial-gradient(520px 180px at 0 0,rgba(139,92,246,.14),transparent 72%),var(--card)}
.ai-card .num{width:24px;font-size:9px;letter-spacing:-.5px}
.ai-choices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:12px}
.ai-choice{display:flex;flex-direction:column;align-items:flex-start;gap:4px;padding:12px;border:1px solid var(--line);border-radius:12px;background:rgba(0,0,0,.2);color:var(--tx);text-align:left;transition:.15s}
.ai-choice:hover{border-color:rgba(139,92,246,.65);transform:translateY(-1px)}
.ai-choice.on{border-color:var(--a1);background:rgba(139,92,246,.16);box-shadow:0 0 0 1px rgba(139,92,246,.2) inset}
.ai-choice b{font-size:13px}.ai-choice small{font-size:11px;color:var(--mute)}
.ch{display:flex;align-items:center;gap:10px;margin-bottom:14px}
.ch h3{font-size:12px;letter-spacing:.9px;text-transform:uppercase;color:var(--dim);font-weight:600}
.num{width:20px;height:20px;border-radius:7px;background:var(--grad);font-size:11px;font-weight:700;display:grid;place-items:center}
.seg{display:flex;background:rgba(0,0,0,.35);border:1px solid var(--line);border-radius:12px;padding:3px;gap:2px}
.seg button{flex:1;padding:8px 10px;border-radius:9px;color:var(--dim);font-weight:500;transition:.15s;white-space:nowrap}
.seg button:hover{color:var(--tx)}
.seg button.on{background:var(--card2);color:var(--tx);box-shadow:0 1px 0 rgba(255,255,255,.08) inset,0 4px 12px rgba(0,0,0,.35)}
.field{display:flex;gap:8px;margin-top:12px}
.text{width:100%;background:rgba(0,0,0,.35);border:1px solid var(--line);border-radius:12px;padding:11px 14px;color:var(--tx);font:inherit;outline:0;transition:.15s}
.text:focus{border-color:var(--a1);box-shadow:0 0 0 3px rgba(139,92,246,.2)}
.text::placeholder{color:var(--mute)}
.hint{color:var(--mute);font-size:12px;margin-top:9px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:10px 16px;border-radius:12px;font-weight:600;transition:.15s;white-space:nowrap}
.btn.ghost{background:var(--card2);border:1px solid var(--line)}.prow .btn.on{border-color:var(--a1);color:var(--a1)}
.btn.ghost:hover{background:rgba(255,255,255,.11);border-color:var(--line2)}
.btn.lock-stop{font-size:11px;padding:4px 9px;margin:5px 0 2px 8px;border-color:rgba(248,113,113,.45);color:#ffd7db}
.btn.danger{background:#dc4452;color:#fff}.btn.danger:hover{background:#ec5a68}
.btn:disabled{opacity:.5;cursor:default}
.settings-dialog{width:min(620px,calc(100vw - 32px));max-height:calc(100vh - 32px);overflow:auto;background:#12141d;border:1px solid var(--line2);border-radius:20px;padding:18px;box-shadow:0 30px 80px rgba(0,0,0,.6)}
.settings-dialog .card{margin:0;background:transparent;border:0;padding:0;backdrop-filter:none}
.settings-head{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:14px}.settings-head h2{font-size:18px;letter-spacing:-.2px}.settings-head p{color:var(--dim);font-size:12px;margin-top:2px}
.row{display:flex;align-items:center;justify-content:space-between;margin:14px 0 8px}
.row:first-child{margin-top:0}
.row label{color:var(--dim);font-size:13px}
.row b{font-weight:600;font-variant-numeric:tabular-nums}
.subhead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:18px;padding-top:16px;border-top:1px solid var(--line);font-weight:600}
.toggle.compact{margin-top:0;gap:8px}.toggle.compact span{font-size:11px}.color-text{width:100%;height:42px;padding:4px;background:rgba(0,0,0,.35);border:1px solid var(--line);border-radius:10px;cursor:pointer}
.ends{display:flex;justify-content:space-between;color:var(--mute);font-size:11px;margin-top:5px}
input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:6px;border-radius:6px;outline:0;cursor:pointer;
background:linear-gradient(90deg,var(--a1),var(--a2)) 0/var(--p,50%) 100% no-repeat,rgba(255,255,255,.1)}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.5);border:0}
input[type=range]::-moz-range-thumb{width:18px;height:18px;border-radius:50%;background:#fff;border:0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.two .row{margin-top:14px}
.folder-pick{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;align-items:center}
.update-list{line-height:1.7;white-space:pre-line}
.about-links{display:flex;flex-wrap:wrap;gap:8px;margin-top:18px}.about-links a{color:var(--tx);background:rgba(139,92,246,.12);border-color:rgba(139,92,246,.28)}.about-links a:hover{color:#fff;background:rgba(236,72,153,.2);border-color:rgba(236,72,153,.48)}
.about-dialog{width:min(680px,calc(100vw - 32px));background:linear-gradient(145deg,#151522,#11131c)}.about-hero{padding:18px;border:1px solid rgba(139,92,246,.24);border-radius:16px;background:radial-gradient(420px 180px at 0 0,rgba(139,92,246,.2),transparent 70%),rgba(255,255,255,.025)}.about-title{display:flex;align-items:center;gap:12px}.about-title h3{font-size:18px;letter-spacing:-.2px}.about-title .hint{margin-top:3px}.small-mark{width:42px;height:42px;border-radius:13px}.small-mark img{width:100%;height:100%;object-fit:cover;border-radius:inherit}.about-copy{color:var(--dim);font-size:13px;line-height:1.6;margin-top:16px}
.sw{display:flex;gap:10px}
.sw button{width:30px;height:30px;border-radius:50%;border:2px solid transparent;box-shadow:0 0 0 2px rgba(0,0,0,.5) inset;transition:.15s}
.sw button.on{border-color:#fff;transform:scale(1.12)}
.toggle{display:flex;align-items:center;justify-content:space-between;gap:12px;cursor:pointer;margin-top:16px}
.toggle span{color:var(--dim);font-size:13px}
.toggle input{display:none}
.sl{width:42px;height:24px;border-radius:24px;background:rgba(255,255,255,.12);position:relative;transition:.2s;flex:none}
.sl:after{content:"";position:absolute;left:3px;top:3px;width:18px;height:18px;border-radius:50%;background:#fff;transition:.2s}
.toggle input:checked+.sl{background:var(--grad)}.toggle input:checked+.sl:after{left:21px}
select.text{appearance:none;background-image:linear-gradient(45deg,transparent 50%,var(--dim) 50%),linear-gradient(135deg,var(--dim) 50%,transparent 50%);background-position:calc(100% - 18px) 50%,calc(100% - 13px) 50%;background-size:5px 5px;background-repeat:no-repeat;padding-right:34px}
select.text option{background:#14161f}
/* phone preview */
.pv{display:flex;justify-content:center;margin:2px 0 6px}
.phone{width:216px;aspect-ratio:9/16;border-radius:28px;border:6px solid #1c1f2d;background:#000;position:relative;overflow:hidden;box-shadow:0 24px 60px rgba(0,0,0,.55),0 0 0 1px rgba(255,255,255,.06)}
.phone .bg{position:absolute;inset:-25%;background:radial-gradient(circle at 28% 30%,#7c5cff,transparent 52%),radial-gradient(circle at 72% 72%,#ff4d9d,transparent 52%),#1a1030;filter:blur(16px)}
.phone .vid{position:absolute;left:0;right:0;top:50%;transform:translateY(-50%);aspect-ratio:16/9;background:linear-gradient(135deg,#2c3150,#12141f);display:grid;place-items:center;color:rgba(255,255,255,.18)}
.phone.fill .vid{aspect-ratio:auto;height:100%;top:0;transform:none;background:linear-gradient(160deg,#323863,#141725)}
.cap{position:absolute;left:0;right:0;text-align:center;line-height:1.08;text-transform:uppercase;display:flex;flex-wrap:wrap;justify-content:center;gap:0 .26em;pointer-events:none}
.cap span{display:inline-block}
.cap .hot{color:var(--cap);animation:pop .16s ease-out}
@keyframes pop{from{transform:scale(1.22)}to{transform:scale(1)}}
.camv{display:none}
.phone.cam .bg,.phone.cam .vid{display:none}
.phone.cam .camv{display:block;position:absolute;inset:0}
.camv .ct{position:absolute;left:0;right:0;top:0;height:40%;background:linear-gradient(160deg,#5b3ea8,#2a1c52);display:grid;place-items:center;color:rgba(255,255,255,.35);border-bottom:2px solid #000}
.camv .cb{position:absolute;left:0;right:0;top:40%;bottom:0;background:linear-gradient(160deg,#323863,#141725)}
.pvl{text-align:center;color:var(--mute);font-size:11px;margin:8px 0 4px}
.editor{width:min(940px,95vw);max-height:94vh;overflow:auto;background:#12141d;border:1px solid var(--line2);border-radius:20px;padding:20px;box-shadow:0 30px 80px rgba(0,0,0,.6)}
.editor h4{font-size:17px;margin-bottom:4px}.editor .sub{color:var(--dim);font-size:13px;margin-bottom:14px}
.cstage{position:relative;width:100%;aspect-ratio:16/9;background:linear-gradient(135deg,#2c3150,#12141f);border-radius:12px;overflow:hidden;touch-action:none;user-select:none}
.cstage .cimg{position:absolute;inset:0;width:100%;height:100%;object-fit:fill;display:block;pointer-events:none}
.crect{position:absolute;border:2px solid #ff40ff;background:rgba(255,64,255,.12);pointer-events:auto}
.crect .move-hit{position:absolute;inset:12px;cursor:move;pointer-events:auto;touch-action:none;z-index:1}
.crect span{position:absolute;left:4px;top:3px;font-size:10px;font-weight:700;letter-spacing:.8px;color:#fff;text-shadow:0 1px 3px #000;z-index:2}
.crect.game{border:2px dashed #22d3ee;background:rgba(34,211,238,.07);cursor:default;pointer-events:none}
.crect .hdl{position:absolute;width:14px;height:14px;background:#fff;border:2px solid #ff40ff;border-radius:3px;pointer-events:auto;touch-action:none;z-index:3}
.crect .hdl.nw{left:-7px;top:-7px;cursor:nwse-resize}.crect .hdl.ne{right:-7px;top:-7px;cursor:nesw-resize}
.crect .hdl.sw{left:-7px;bottom:-7px;cursor:nesw-resize}.crect .hdl.se{right:-7px;bottom:-7px;cursor:nwse-resize}
.erow{display:flex;gap:12px;align-items:center;margin-top:14px;flex-wrap:wrap}
.erow .grow{flex:1;min-width:220px}
/* hero */
.hero{display:flex;align-items:center;gap:18px;padding:18px 20px;margin:0;background:var(--card);border:1px solid var(--line);border-radius:18px;position:relative;overflow:hidden}
.hero:before{content:"";position:absolute;inset:0;background:radial-gradient(500px 120px at 0 0,var(--hc,transparent),transparent 70%);opacity:.18;pointer-events:none;transition:.4s}
.eq{display:flex;align-items:center;gap:4px;height:38px;width:46px;flex:none}
.eq i{flex:1;height:18%;border-radius:3px;background:var(--hc,var(--mute));transition:background .4s}
.hero.live .eq i{animation:eq 1s ease-in-out infinite}
.eq i:nth-child(2){animation-delay:.15s!important}.eq i:nth-child(3){animation-delay:.3s!important}.eq i:nth-child(4){animation-delay:.45s!important}.eq i:nth-child(5){animation-delay:.6s!important}
@keyframes eq{0%,100%{height:18%}50%{height:100%}}
.ph{font-size:19px;font-weight:700;letter-spacing:-.3px}
.st{color:var(--dim);font-size:13px;margin-top:1px;max-width:48ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stats{margin-left:auto;display:flex;gap:22px}
.stat{text-align:right}.stat b{display:block;font-size:20px;font-weight:700;font-variant-numeric:tabular-nums}.stat span{font-size:11px;color:var(--mute);text-transform:uppercase;letter-spacing:.8px}
.hero[data-phase=idle]{--hc:#646a82}.hero[data-phase=waiting]{--hc:#fbbf24}.hero[data-phase=recording]{--hc:#f87171}
.hero[data-phase=transcribing]{--hc:#8b5cf6}.hero[data-phase=rendering]{--hc:#ec4899}.hero[data-phase=stopping]{--hc:#fbbf24}.hero[data-phase=working]{--hc:#8b5cf6}
.progress-wrap{padding:11px 14px 12px;background:var(--card);border:1px solid var(--line);border-radius:12px}.progress-meta{display:flex;justify-content:space-between;color:var(--dim);font-size:12px;font-weight:600;margin-bottom:7px}.progress-track{height:10px;background:rgba(255,255,255,.1);border-radius:8px;overflow:hidden;box-shadow:inset 0 1px 2px rgba(0,0,0,.35)}.progress-fill{height:100%;width:0;background:var(--grad);border-radius:8px;transition:width .25s ease;box-shadow:0 0 14px rgba(139,92,246,.55)}
.post-progress{margin-bottom:12px;padding:11px 14px;background:rgba(139,92,246,.08);border:1px solid rgba(139,92,246,.3);border-radius:12px}.post-progress .progress-meta{margin-bottom:7px}.post-progress .progress-track{height:9px}
.local-note{color:var(--mute);font-size:11px;padding:0 22px 8px}.local-note b{color:var(--dim)}
.rec-dot{display:inline-block;width:9px;height:9px;border-radius:50%;background:var(--bad);margin-right:8px;animation:blink 1.2s infinite;vertical-align:1px}
@keyframes blink{50%{opacity:.25}}
/* tabs */
.tabs{display:flex;align-items:center;gap:6px}
.tab{padding:8px 14px;border-radius:10px;color:var(--dim);font-weight:600;transition:.15s}
.tab:hover{color:var(--tx)}.tab.on{background:var(--card2);color:var(--tx)}
.tab em{font-style:normal;background:var(--grad);color:#fff;font-size:11px;padding:1px 7px;border-radius:20px;margin-left:6px}
.panel{flex:1;min-height:0;overflow:auto;padding-right:6px;margin-right:-6px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(176px,1fr));gap:14px;padding-bottom:6px}
.clip{background:var(--card);border:1px solid var(--line);border-radius:16px;overflow:hidden;transition:.2s}
.clip:hover{border-color:var(--line2);transform:translateY(-2px);box-shadow:0 14px 36px rgba(0,0,0,.4)}
.thumb{position:relative;aspect-ratio:9/16;background:#000;cursor:pointer}
.thumb video{width:100%;height:100%;object-fit:cover;display:block}
.pb{position:absolute;right:10px;bottom:10px;width:34px;height:34px;border-radius:50%;background:rgba(0,0,0,.55);backdrop-filter:blur(6px);display:grid;place-items:center;transition:.2s}
.clip:hover .pb{background:var(--grad)}
.cm{padding:10px 12px 8px}
.cc{font-size:12.5px;line-height:1.35;height:34px;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.cr{display:flex;align-items:center;justify-content:space-between;margin-top:8px;color:var(--mute);font-size:11.5px}
.acts{display:flex;gap:2px;margin-right:-6px}
.ib{width:28px;height:28px;border-radius:8px;display:grid;place-items:center;color:var(--dim);transition:.15s}.ib.post{width:auto;min-width:34px;padding:0 7px;font-size:11px;font-weight:600}
.ib:hover{background:var(--card2);color:var(--tx)}.ib.del:hover{color:var(--bad)}
.empty{height:100%;min-height:300px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:var(--dim);gap:8px;border:1px dashed var(--line2);border-radius:18px;padding:30px}
.empty h4{font-size:17px;color:var(--tx)}.empty p{max-width:44ch;font-size:13px}
.empty .big{width:62px;height:62px;border-radius:20px;background:var(--grad);display:grid;place-items:center;margin-bottom:8px;box-shadow:0 12px 36px rgba(139,92,246,.4)}
#log{font:12px/1.65 "Cascadia Mono",Consolas,monospace;background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:16px;padding:14px 16px;min-height:100%}
#log div{white-space:pre-wrap;word-break:break-word}#log .t{color:var(--mute);margin-right:10px}#log .err{color:var(--bad)}#log .okk{color:var(--ok)}
.creator-list{display:flex;flex-direction:column;gap:8px;margin-top:12px}.creator-item{border:1px solid var(--line);background:rgba(0,0,0,.2);border-radius:12px;padding:10px}.creator-top{display:flex;align-items:center;justify-content:space-between;gap:8px}.creator-name{font-weight:700;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.creator-state{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--dim)}.creator-state.live{color:var(--ok)}.creator-detail{font-size:11px;color:var(--mute);margin-top:4px;overflow-wrap:anywhere}.creator-actions{display:flex;gap:6px;margin-top:9px;flex-wrap:wrap}.creator-actions .btn{padding:6px 9px;font-size:11px}.z-account-picks{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px;margin:8px 0}.z-account-pick{display:flex;align-items:center;gap:8px;min-width:0;padding:9px;border:1px solid var(--line);border-radius:10px;background:rgba(0,0,0,.16);font-size:12px}.z-account-pick input{accent-color:var(--a1)}.z-account-pick span{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.log-head{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:10px}.log-title{display:flex;align-items:center;gap:9px;font-weight:700}.log-live{font-size:10px;letter-spacing:.7px;text-transform:uppercase;color:var(--ok);border:1px solid rgba(52,211,153,.35);border-radius:999px;padding:3px 8px}.log-live.paused{color:var(--warn);border-color:rgba(251,191,36,.35)}.log-actions{display:flex;gap:7px}.log-actions .btn{padding:7px 10px;font-size:11px}
.hw{display:flex;flex-direction:column;gap:12px;min-height:100%}
.hw textarea{flex:1;min-height:260px;resize:none;background:rgba(0,0,0,.35);border:1px solid var(--line);border-radius:16px;padding:14px 16px;color:var(--tx);font:13px/1.6 "Cascadia Mono",Consolas,monospace;outline:0}
.hw textarea:focus{border-color:var(--a1);box-shadow:0 0 0 3px rgba(139,92,246,.2)}
.hwb{display:flex;align-items:center;gap:12px}.hwb .msg{color:var(--ok);font-size:13px;opacity:0;transition:.3s}.hwb .msg.show{opacity:1}
.help{color:var(--dim);font-size:13px;line-height:1.55}.help code{background:rgba(255,255,255,.08);padding:1px 6px;border-radius:6px;font-size:12px;color:var(--tx)}
details{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
summary{cursor:pointer;color:var(--dim);font-weight:600}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:12px;max-height:200px;overflow:auto}
.chips span{background:rgba(255,255,255,.06);border-radius:8px;padding:2px 9px;font-size:12px;color:var(--dim)}
/* primary live capture controls stay visible above the dashboard */
.capture-top{padding:0 22px 12px}
.capture-top .startbar{padding:0;max-width:1600px;margin:0 auto}
.capture-top .go{min-height:54px}
.capture-top .stopb{min-height:54px}
/* start bar */
.startbar{padding:14px 0 0;display:flex;gap:10px}
.go{flex:1;padding:15px;font-size:16px;border-radius:15px;background:var(--grad);font-weight:700;color:#fff;box-shadow:0 10px 30px rgba(139,92,246,.4);transition:.2s;display:flex;align-items:center;justify-content:center;gap:10px}
.go:hover{transform:translateY(-1px);box-shadow:0 14px 38px rgba(236,72,153,.4)}
.go:disabled{opacity:.6;transform:none}
.stopb{flex:1;padding:15px;font-size:15px;border-radius:15px;background:#dc4452;font-weight:700;color:#fff;transition:.15s}.stopb:hover{background:#ec5a68}.stopb:disabled{opacity:.55}
.stopb.alt{flex:none;background:var(--card2);border:1px solid var(--line);color:var(--tx);padding:15px 20px}.stopb.alt:hover{background:rgba(255,255,255,.12)}
/* StreamSnip 4.x  -  refined commercial dashboard */
:root{
 --bg:#090d16;--card:#111827;--card2:#182235;--line:rgba(148,163,184,.14);--line2:rgba(148,163,184,.27);
 --tx:#f1f5fb;--dim:#a6b2c5;--mute:#718096;--a1:#6d8cff;--a2:#28c7b7;
 --ok:#35d6a0;--warn:#f6c66b;--bad:#fb7185;
 --grad:linear-gradient(115deg,#5478ed,#27b8aa);
}
body{background:var(--bg);font-size:13px}
body:before{background:radial-gradient(900px 520px at 8% -15%,rgba(84,120,237,.15),transparent 62%),radial-gradient(760px 420px at 100% 0,rgba(39,184,170,.09),transparent 62%)}
header{padding:16px 26px;border-bottom:1px solid var(--line);background:rgba(9,13,22,.88);backdrop-filter:blur(18px)}
.logo{font-size:17px;letter-spacing:-.35px}.mark{border-radius:10px;box-shadow:0 5px 18px rgba(84,120,237,.2)}
.tag{font-size:12px;color:#8292aa}
.local-note{padding:7px 26px 5px;color:#65748b}
.capture-top{padding:8px 26px 16px}
.capture-top .startbar{max-width:none}
.go{background:linear-gradient(110deg,#5478ed,#3867d8);box-shadow:0 8px 22px rgba(55,99,214,.22);border-radius:12px;font-size:14px;min-height:48px}
.go:hover{box-shadow:0 10px 26px rgba(55,99,214,.3)}
.stopb{border-radius:12px;font-size:14px;min-height:48px}
.main{grid-template-columns:minmax(330px,370px) minmax(0,1fr);gap:18px;padding:0 26px 24px}
.left{min-height:0}.scroll{gap:0;padding-right:5px}
.right{gap:12px}
.card{background:linear-gradient(160deg,rgba(20,30,47,.96),rgba(15,23,37,.96));border:1px solid var(--line);border-radius:14px;padding:15px;margin-bottom:11px;backdrop-filter:none;box-shadow:0 5px 18px rgba(0,0,0,.12)}
.ai-card{border-color:rgba(109,140,255,.24);background:linear-gradient(155deg,rgba(25,37,61,.98),rgba(15,23,37,.98))}
.ch{margin-bottom:11px;gap:9px}.ch h3{font-size:11px;letter-spacing:1.05px;color:#aab8cc}
.num{background:rgba(109,140,255,.16);color:#a9bcff;border:1px solid rgba(109,140,255,.2);border-radius:6px}
.creator-card{border-color:rgba(39,184,170,.3);background:linear-gradient(155deg,rgba(15,42,48,.75),rgba(15,23,37,.98))}
.creator-card .num{background:rgba(39,184,170,.14);color:#62ddce;border-color:rgba(39,184,170,.25)}
.text{background:#0b1321;border:1px solid rgba(148,163,184,.17);border-radius:9px;padding:10px 12px}
.text:focus{border-color:#6d8cff;box-shadow:0 0 0 3px rgba(109,140,255,.13)}
.btn{border-radius:9px;font-size:12px;padding:9px 12px}
.btn.ghost{background:#1a2639;border-color:rgba(148,163,184,.16)}
.btn.ghost:hover{background:#24334b;border-color:rgba(148,163,184,.3)}
.seg{background:#0b1321;border-color:var(--line);border-radius:9px}
.seg button{padding:7px 9px;font-size:12px}.seg button.on{background:#253653;box-shadow:none;color:#eaf0ff}
.ai-choices{gap:7px}.ai-choice{background:#0d1727;border-radius:9px;padding:10px;border-color:rgba(148,163,184,.13)}
.ai-choice.on{border-color:#6d8cff;background:rgba(109,140,255,.12);box-shadow:0 0 0 1px rgba(109,140,255,.12) inset}
.row{margin:11px 0 7px}.row label{font-size:12px;color:#9eacc0}
.hint{font-size:11.5px;line-height:1.55;color:#8190a6}
.creator-item{background:#0c1725;border-color:rgba(148,163,184,.13);border-radius:10px;padding:11px}
.creator-state{font-size:9px;letter-spacing:.8px}
.hero{border-radius:14px;background:linear-gradient(120deg,#15233a,#111a2a);border-color:var(--line);padding:17px 19px}
.ph{font-size:17px}.stats{gap:18px}.stat b{font-size:19px}
.progress-wrap{border-radius:10px;background:#111b2b;border-color:var(--line)}
.tabs{padding:4px;background:#0c1422;border:1px solid var(--line);border-radius:11px;width:max-content}
.tab{padding:8px 13px;border-radius:8px;font-size:12px}.tab.on{background:#243552;color:#f3f6ff}
.grid{gap:12px;grid-template-columns:repeat(auto-fill,minmax(190px,1fr))}
.clip{background:#111b2a;border-color:var(--line);border-radius:12px}
.clip:hover{border-color:rgba(109,140,255,.42);box-shadow:0 10px 28px rgba(0,0,0,.24)}
.cm{padding:11px 12px}.cc{font-size:12px}
.empty{border-radius:14px;background:rgba(17,27,42,.35)}
#log{background:#0b1321;border-color:var(--line);border-radius:12px}
.details,details{background:#111b2a;border-color:var(--line);border-radius:11px}
@media(min-width:1500px){.main{grid-template-columns:390px minmax(0,1fr);gap:22px;padding-left:32px;padding-right:32px}.capture-top{padding-left:32px;padding-right:32px}.grid{grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}}
@media(max-width:1080px){.main{grid-template-columns:minmax(0,1fr);padding:0 16px 20px}.capture-top{padding-left:16px;padding-right:16px}header{padding:13px 16px}}
@media(max-width:650px){header{flex-wrap:wrap}.tag{display:none}.stats{width:100%;justify-content:space-between}.grid{grid-template-columns:repeat(auto-fill,minmax(150px,1fr))}}
/* overlays */
.overlay{position:fixed;inset:0;background:rgba(4,5,9,.78);backdrop-filter:blur(10px);display:grid;place-items:center;z-index:50;animation:fade .15s}
@keyframes fade{from{opacity:0}}
.dialog{background:#12141d;border:1px solid var(--line2);border-radius:20px;padding:22px;max-width:380px;box-shadow:0 30px 80px rgba(0,0,0,.6)}
.dialog h4{font-size:17px;margin-bottom:6px}.dialog p{color:var(--dim);margin-bottom:18px}.dlg-actions{display:flex;gap:10px;justify-content:flex-end}
.player{display:flex;gap:22px;align-items:stretch;max-height:92vh;max-width:94vw;background:#0d0f17;border:1px solid var(--line2);border-radius:22px;padding:14px;box-shadow:0 30px 90px rgba(0,0,0,.7)}
.player video{height:min(82vh,820px);aspect-ratio:9/16;border-radius:14px;background:#000;display:block}
.pside{width:290px;display:flex;flex-direction:column;gap:12px;padding:6px 6px 2px}
.pside h4{font-size:12px;letter-spacing:.9px;text-transform:uppercase;color:var(--dim)}
.post-dialog{width:min(680px,calc(100vw - 28px));max-height:92vh;overflow:auto;background:#12141d;border:1px solid var(--line2);border-radius:20px;padding:20px;box-shadow:0 30px 80px rgba(0,0,0,.65)}
.post-dialog h3{font-size:18px;margin-bottom:5px}.post-dialog .sub{font-size:12px;color:var(--dim);margin-bottom:16px}
.post-dialog label{display:block;color:var(--dim);font-size:12px;margin:12px 0 6px}
.post-dialog label.platform-pick{display:flex;align-items:center;margin:0}
.post-dialog textarea{min-height:145px;resize:vertical;line-height:1.5}
.platform-picks{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin:14px 0}
.platform-pick{display:flex;align-items:center;gap:8px;padding:11px;border:1px solid var(--line);border-radius:11px;background:rgba(0,0,0,.2);font-size:12px;color:var(--tx);cursor:pointer}
.platform-pick:has(input:checked){border-color:var(--a1);background:rgba(139,92,246,.15)}
.post-note{font-size:11px;color:var(--mute);line-height:1.5;margin:10px 0 16px}
@media(max-width:650px){.platform-picks{grid-template-columns:repeat(2,minmax(0,1fr))}}
.pcap{white-space:pre-wrap;font:13px/1.55 inherit;font-family:inherit;color:var(--tx);background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:12px;padding:12px;flex:1;overflow:auto}
.prow{display:flex;gap:8px;flex-wrap:wrap}
#toasts{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);display:flex;flex-direction:column;gap:8px;align-items:center;z-index:99;pointer-events:none}
.toast{background:#1b1e2b;border:1px solid var(--line2);padding:10px 18px;border-radius:12px;box-shadow:0 12px 40px rgba(0,0,0,.5);animation:up .25s;transition:.3s}
.toast.bad{border-color:rgba(248,113,113,.6)}.toast.ok{border-color:rgba(52,211,153,.5)}.toast.out{opacity:0;transform:translateY(8px)}
@keyframes up{from{opacity:0;transform:translateY(10px)}}
#offline{position:fixed;top:14px;left:50%;transform:translateX(-50%);background:#3a1d22;border:1px solid var(--bad);color:#ffd7db;padding:9px 18px;border-radius:12px;z-index:90}
@media(max-width:1080px){body{overflow:auto}.app{height:auto}.main{grid-template-columns:1fr}.scroll,.panel{overflow:visible}.hero{flex-wrap:wrap}.stats{margin-left:0}}
</style>
</head>
<body>
<div class="app">
<header>
  <div class="logo"><div class="mark"><img src="/assets/app-icon.png" alt="StreamSnip AI" onerror="this.style.display='none';this.parentElement.textContent='⚡'"></div>StreamSnip AI<span class="tag">by ScarZero &middot; live stream &rarr; viral Shorts</span></div>
  <div class="sp"></div>
  <a class="btn ghost" href="/dashboard/" title="Open the React creator workspace">React dashboard</a>
  <button class="btn ghost" id="btn-folder"><span data-ico="folder"></span>Clips folder</button>
  <button class="btn ghost" id="btn-settings"><span data-ico="settings"></span>Settings</button>
  <button class="btn ghost" id="btn-about"><span data-ico="info"></span>About</button>
  <button class="btn ghost" id="btn-quit" title="Stop everything and close StreamSnip AI"><span data-ico="power"></span>Quit</button>
</header>
<div class="local-note">If buttons do not respond, disable your ad blocker for <b>127.0.0.1</b> / <b>localhost</b>.</div>
<div class="capture-top">
  <div class="startbar" id="startbar"><button class="go" id="btn-start"><span data-ico="bolt" data-s="20"></span><span id="go-label">Start recording &amp; clipping</span></button></div>
  <div class="startbar" id="stopbar" hidden><button class="stopb" id="btn-stop">Stop &amp; finish clips</button><button class="stopb alt" id="btn-kill">Stop now</button></div>
</div>

<div class="main">
<section class="left">
 <div class="scroll">
  <div class="card creator-card">
    <div class="ch"><span class="num">LIVE</span><h3>Creator monitors</h3></div>
    <p class="hint" style="margin:0 0 10px">Track up to 10 creators simultaneously. Each creator gets separate recordings and clips. Ten concurrent streams can be demanding on CPU, GPU, and network resources.</p>
    <input id="creator-name" class="text" type="text" maxlength="80" placeholder="Creator name">
    <div class="field"><input id="creator-target" class="text" type="url" spellcheck="false" placeholder="Twitch or YouTube live URL"><button class="btn ghost" id="creator-add">Add</button></div>
    <p class="hint">Each creator has separate Live recordings/clips and a Recorded VOD inbox. Turn on Watch VOD folder, then drop full VOD files into that creator's inbox. VOD clips and processed originals stay separate from Live.</p>
    <div id="creator-list" class="creator-list"><p class="hint">Loading creator monitors...</p></div>
  </div>
  <div class="card">
    <div class="ch"><span class="num">1</span><h3>Source</h3></div>
    <div class="seg" data-key="mode"><button data-v="live">Live stream</button><button data-v="file">Video file / VOD</button></div>
    <div class="field"><input id="target" class="text" type="text" spellcheck="false" autocomplete="off"><button id="btn-browse" class="btn ghost" hidden>Browse</button></div>
    <p class="hint" id="src-hint"></p>
  </div>

  <div class="card ai-card" id="ai-card">
    <div class="ch"><span class="num">AI</span><h3>Choose your highlight engine</h3></div>
    <p class="hint" style="margin-top:0">Hook words and Ollama run locally and use no hosted AI quota. Gemini and Hugging Face send transcript windows to hosted services and can consume your account quota or credits. Whisper creates the transcript separately.</p>
    <div class="ai-choices" role="group" aria-label="AI highlight provider">
      <button type="button" class="ai-choice" data-ai-provider="hooks"><b>Hook words</b><small>Free · offline · default</small></button>
      <button type="button" class="ai-choice" data-ai-provider="ollama"><b>Ollama local AI</b><small>Free · private · local model</small></button>
      <button type="button" class="ai-choice" data-ai-provider="gemini"><b>Gemini API</b><small>Hosted · uses Google quota</small></button>
      <button type="button" class="ai-choice" data-ai-provider="huggingface"><b>Hugging Face</b><small>Hosted · may use provider credits</small></button>
      <button type="button" class="ai-choice" data-ai-provider="custom"><b>Free / Custom API</b><small>OpenAI-compatible endpoint</small></button>
    </div>
    <select id="ai-provider" class="text" hidden><option value="hooks">Built-in and custom hook words</option><option value="ollama">Ollama local AI</option><option value="huggingface">Hugging Face hosted model</option><option value="gemini">Gemini API</option><option value="custom">Free / custom OpenAI-compatible API</option></select>
    <div id="ollama-ai-fields" hidden>
      <div class="row"><label>Ollama address</label></div><input id="ollama-url" class="text" value="http://127.0.0.1:11434">
      <div class="row"><label>Installed Ollama model</label><button class="btn ghost" id="ai-detect-ollama">Detect models</button></div>
      <select id="ollama-model" class="text"><option value="">Click Detect models</option></select>
      <p class="hint">Install Ollama and at least one model first. Only models already installed and detected by Ollama are available.</p>
    </div>
    <div id="gemini-ai-fields" hidden><div class="row"><label>Gemini API key</label><div class="prow"><b id="gemini-key-state">Not saved</b><button type="button" class="btn ghost" id="gemini-key-clear">Clear saved key</button></div></div><input id="gemini-key" class="text" type="password" placeholder="Enter a Gemini API key"><div class="row"><label>Preferred Gemini model</label></div><input id="gemini-model" class="text" value="gemini-3.8-flash" placeholder="gemini-3.8-flash"><p class="hint">The app checks this model first, tries the other available Gemini models if needed, then falls back to Ollama. Model IDs can change; use one enabled for your API key.</p></div>
    <div id="hf-ai-fields" hidden><div class="row"><label>Hugging Face model</label></div><input id="hf-model" class="text" value="deepseek-ai/DeepSeek-V4.1-Flash:fastest"><div class="row"><label>Hugging Face access token</label><div class="prow"><b id="hf-token-state">Not saved</b><button type="button" class="btn ghost" id="hf-token-clear">Clear saved token</button></div></div><input id="hf-token" class="text" type="password" placeholder="hf_… token with Inference Providers access"><p class="hint">Save your token here. StreamSnip also uses it for authenticated Whisper model downloads. Use a token with Inference Providers access and available provider credits.</p></div>
    <div id="custom-ai-fields" hidden>
      <div class="row"><label>OpenAI-compatible API base URL</label></div>
      <input id="custom-api-base" class="text" type="url" value="https://api.openai.com/v1" placeholder="https://your-provider.example/v1">
      <div class="row"><label>Model name</label></div>
      <input id="custom-api-model" class="text" type="text" placeholder="Enter the exact model ID">
      <div class="row"><label>API key (optional for local/free endpoints)</label><div class="prow"><b id="custom-api-key-state">Not saved</b><button type="button" class="btn ghost" id="custom-api-key-clear">Clear saved key</button></div></div>
      <input id="custom-api-key" class="text" type="password" placeholder="Paste API key if your provider requires one">
      <p class="hint">Works with OpenAI-compatible chat-completions APIs, including providers that offer free model tiers. Enter the provider's base URL, exact model ID, and key if required. Provider quotas, rate limits, and terms still apply.</p>
    </div>

    <p class="hint" style="margin-top:12px">Titles and descriptions are generated automatically for each clip using the same provider selected above for highlight detection. Hook words mode uses transcript-based copy because it does not include a text-generating model. Gemini, local Ollama, Hugging Face, and custom compatible APIs follow the same creator-style format: catchy Title Case titles, fitting emojis, a quote-led caption with context, creator credit, and ready-to-post hashtags. Invalid or incomplete AI responses use the transcript fallback.</p>
    <div class="prow" style="margin-top:12px"><button class="btn ghost" id="ai-settings-save">Save AI settings</button><button class="btn ghost" id="ai-test-provider">Test connection</button><span class="msg" id="ai-settings-msg">Built-in hook detection selected</span></div>
  </div>

  <div class="card">
    <div class="ch"><span class="num">2</span><h3>Moment detection</h3></div>
    <div class="row"><label>Min viral score</label><b id="v-sens"></b></div>
    <input type="range" id="r-sens" min="0" max="100" step="1">
    <div class="ends"><span>More clips</span><span>Only the best</span></div>
    <p class="hint">0 = no limit  -  selects every non-overlapping moment above the viral-score floor. Weak segments can produce fewer or no clips.</p>
    <div class="two">
      <div><div class="row"><label>Clips / chunk (0 = no limit)</label><b id="v-cpc"></b></div><input type="range" id="r-cpc" min="0" max="10" step="1"></div>
      <div><div class="row"><label>Analysis window</label><b id="v-chunk"></b></div><input type="range" id="r-chunk" min="3" max="15" step="1"><p class="hint">3 min = faster AI reviews; 15 min = deeper context. The full local video is still transcribed and analyzed.</p></div>
      <div><div class="row"><label>Before peak</label><b id="v-pre"></b></div><input type="range" id="r-pre" min="5" max="60" step="1"></div>
      <div><div class="row"><label>After peak</label><b id="v-post"></b></div><input type="range" id="r-post" min="5" max="60" step="1"></div>
    </div>
  </div>

  <div class="card">
    <div class="ch"><span class="num">3</span><h3>Captions</h3></div>
    <div class="pv"><div class="phone" id="phone"><div class="bg"></div><div class="vid"><svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor"><path d="M8 5v14l11-7z"/></svg></div><div class="camv"><div class="ct"><svg width="30" height="30" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0z"/></svg></div><div class="cb"></div></div><div class="cap" id="cap"></div></div></div>
    <div class="pvl">Live preview of your caption style</div>
    <div class="row"><label>Highlight colour</label><div class="sw" id="sw"></div></div>
    <div class="row"><label>Position</label></div>
    <div class="seg" data-key="position"><button data-v="Low">Low</button><button data-v="Lower third">Lower third</button><button data-v="Middle">Middle</button></div>
    <div class="row"><label>Words per line</label></div>
    <div class="seg" data-key="words_per_line" data-num="1"><button data-v="1">1</button><button data-v="2">2</button><button data-v="3">3</button><button data-v="4">4</button></div>
    <div class="row"><label>Text size</label><b id="v-size"></b></div>
    <input type="range" id="r-size" min="60" max="150" step="2">
    <div class="row"><label>Font</label></div>
    <input id="font" class="text" list="fonts" spellcheck="false" autocomplete="off">
    <datalist id="fonts"><option value="Impact"><option value="Arial Black"><option value="Segoe UI Black"><option value="Bahnschrift"><option value="Franklin Gothic Heavy"><option value="Verdana"></datalist>
    <p class="hint">Impact is the classic MrBeast look. Any font installed on your PC works.</p>
    <div class="subhead"><span>Subtitles (customize)</span><label class="toggle compact"><span>Leave off to use server defaults</span><input type="checkbox" id="t-sub-custom"><i class="sl"></i></label></div>
    <div id="sub-custom-fields" hidden>
      <div class="two">
        <div><div class="row"><label>Mode</label></div><select id="sub-mode" class="text"><option>Karaoke</option><option>Classic</option></select></div>
        <div><div class="row"><label>Style preset</label></div><select id="sub-style" class="text"><option>Classic</option><option>Hormozi</option><option>Neon</option><option>MrBeast</option><option>Minimal</option><option>Fire</option></select></div>
      </div>
      <div class="two">
        <div><div class="row"><label>Font size</label><b id="v-sub-size"></b></div><input type="range" id="r-sub-size" min="60" max="180" step="2"></div>
        <div><div class="row"><label>Vertical nudge</label><b id="v-sub-nudge"></b></div><input type="range" id="r-sub-nudge" min="-400" max="400" step="1"></div>
      </div>
      <div class="two">
        <div><div class="row"><label>Text color</label></div><input id="sub-text-color" class="color-text" type="color" value="#FFFFFF"></div>
        <div><div class="row"><label>Stroke color</label></div><input id="sub-stroke-color" class="color-text" type="color" value="#000000"></div>
      </div>
      <div class="two">
        <div><div class="row"><label>Position</label></div><div class="seg" data-key="subtitle_position"><button data-v="Top">Top</button><button data-v="Center">Center</button><button data-v="Bottom">Bottom</button></div></div>
        <div><div class="row"><label>Alignment</label></div><div class="seg" data-key="subtitle_alignment"><button data-v="Left">Left</button><button data-v="Center">Center</button></div></div>
      </div>
      <p class="hint">Presets control the font and animation. Text/stroke colors, position, alignment, and size remain yours to tune.</p>
    </div>
    <div class="subhead"><span>Profanity censor</span><label class="toggle compact"><span>Censor audio + captions</span><input type="checkbox" id="t-profanity"><i class="sl"></i></label></div>
    <textarea id="profanity-words" class="text" rows="3" spellcheck="false" placeholder="Add extra words or phrases, one per line"></textarea>
    <p class="hint">Censoring only changes the rendered audio, captions and generated post text. It never removes a clip, lowers its viral score, or blocks publishing. You can still publish clips containing profanity; turn censoring off before rendering when you want the original audio and words. Existing clips must be re-rendered to apply a changed setting. Speech recognition can miss words, so review before posting.</p>
  </div>

  <div class="card">
    <div class="ch"><span class="num">4</span><h3>Output</h3></div>
    <div class="row"><label>Video format</label></div>
    <select id="output-format" class="text">
      <option value="9:16">9:16 Portrait (Shorts / Reels)</option>
      <option value="16:9">16:9 Landscape (YouTube)</option>
      <option value="1:1">1:1 Square</option>
      <option value="4:5">4:5 Portrait (Instagram)</option>
    </select>
    <p class="hint" id="format-hint">9:16 keeps the facecam + game layout.</p>
    <div class="row"><label>Layout</label></div>
    <div class="seg" data-key="layout"><button data-v="Facecam + game (Twitch)">Facecam + game</button><button data-v="Blur background">Blurred bg</button><button data-v="Fill (crop center)">Fill</button><button data-v="Selected crop">Selected crop</button></div>
    <div id="camrow" hidden>
      <div class="row" id="cam-area-row"><label>Facecam area</label><b id="v-cam"></b></div>
      <button class="btn ghost" id="btn-cam" style="width:100%">Set facecam area on a frame</button>
      <p class="hint" id="cam-hint">Like Twitch: the facecam fills the top 40% of the clip and the game fills the bottom 60%.</p>
    </div>
    <div class="row"><label>Transcription engine</label></div>
    <select id="transcriber-provider" class="text">
      <option value="faster-whisper">Built-in faster-whisper · local, no API key</option>
      <option value="custom-command">Bring your own transcriber · CLI / script</option>
    </select>
    <div id="faster-whisper-fields"><div class="row"><label>Speech model</label></div><select id="model" class="text"></select></div>
    <div id="transcriber-custom-fields" hidden>
      <div class="row"><label>Your transcriber command</label></div>
      <input id="transcriber-command" class="text" type="text" spellcheck="false" placeholder='whisper-cli -f "{input}" -oj -of "{output}"'>
      <div class="row"><label>Language placeholder</label></div>
      <input id="transcriber-language" class="text" type="text" value="auto" maxlength="20" placeholder="auto">
      <p class="hint">No StreamSnip API key is needed. Use your own local executable or script. Placeholders: {input}, {output}, {language}. Return JSON to {output} or stdout with timestamped words: {"words":[{"start":0.1,"end":0.5,"word":"hello"}]}. Segment JSON with start/end/text is also accepted. Your own transcriber handles any credentials it needs. Do not paste secrets in this command field; use environment variables or its secure local config.</p>
    </div>
    <p class="hint">Temporary live recordings are automatically deleted after clips render or when no worthwhile moments are found. Original VOD files are kept and archived.</p>
    <div class="row"><label>Tag / credit</label></div>
    <input id="streamer-tag" class="text" type="text" maxlength="80" placeholder="Auto-detect from stream URL">
    <p class="hint">Leave blank to tag the Twitch or YouTube handle from the source URL. Enter a value to override it.</p>
    <label class="toggle"><span>Show credit on the video</span><input type="checkbox" id="show-tag-video"><i class="sl"></i></label>
  </div>

  <div class="card" id="settings-card">
    <div class="ch"><span class="num">5</span><h3>App settings</h3></div>
    <div class="row"><label>Storage folders</label></div>
    <p class="hint">Choose where recordings and finished clips are saved. Changes apply after clipping is stopped.</p>
    <div class="row"><label>Recording folder</label></div>
    <div class="folder-pick"><input id="rec-dir" class="text" type="text" placeholder="Default: app folder\rec"><button class="btn ghost" id="rec-dir-browse">Browse</button></div>
    <div class="row"><label>Output / clips folder</label></div>
    <div class="folder-pick"><input id="out-dir" class="text" type="text" placeholder="Default: app folder\out"><button class="btn ghost" id="out-dir-browse">Browse</button></div>
    <div class="row"><label>Processing hardware</label></div>
    <select id="compute-device" class="text"><option value="gpu">Automatic  -  use NVIDIA GPU when available</option></select>
    <p class="hint">Speech uses CUDA when a supported NVIDIA GPU is detected; video recording and rendering use NVENC whenever FFmpeg provides it. CPU processing is used only when no supported GPU is detected. A GPU initialization failure is shown in Activity instead of silently switching to CPU.</p>
    <div class="row"><label>Live video bitrate target (kbps)</label><b>Full HD</b></div>
    <input id="capture-bitrate" class="text" type="number" min="8000" max="50000" step="500" value="8000" aria-label="Capture video bitrate target in kilobits per second">
    <p class="hint">Default target is 6,000 kbps (minimum setting). Captures at 1080p when available and falls back to 720p. A source below 1080p cannot gain real detail from upscaling.</p>
    <div class="row"><label>App and runtime updates</label></div>
    <p class="hint">Current app version: __APP_VERSION__. Check the published release before updating.</p>
    <div class="prow"><button class="btn ghost" id="btn-app-version">Check app version</button><button class="btn ghost" id="btn-app-update" disabled>Open update</button><span class="msg" id="app-version-msg">Not checked</span></div>
    <p class="hint">Check FFmpeg, speech packages, Streamlink, NumPy, CTranslate2, and the selected speech-model cache.</p>
    <div class="prow"><button class="btn ghost" id="btn-updates">Check for updates</button><button class="btn ghost" id="btn-update-components">Update components</button><span class="msg" id="updates-msg">Not checked</span></div>
    <div class="hint update-list" id="updates-list"></div>
    <div class="row"><label>Publishing provider</label></div>
    <select id="pub-provider" class="text" disabled><option value="zernio">Zernio hosted</option></select>
    <p class="hint">Zernio is the supported posting provider. Zernio service and platform limits may apply. Auto-post stays off until you turn it on.</p>
    <div class="row"><label>API key</label><b id="z-key-state">Not saved</b></div>
    <input id="z-api" class="text" type="password" placeholder="Enter a new key to replace the saved key">
    <p class="hint">Credentials are stored locally in this app folder and never sent to the browser.</p>
    <div class="row"><label>Connected social accounts</label></div>
    <div id="z-account-picks" class="z-account-picks"><p class="hint">Save your Zernio key, then identify connected accounts.</p></div>
    <p class="hint">Choose one connected account per platform. StreamSnip can publish a clip to several selected platforms in one Zernio request.</p>
    <div class="two">
      <div><div class="row"><label>Schedule delay (minutes)</label></div><input id="z-delay" class="text" type="number" min="0" value="0"></div>
      <div><div class="row"><label>YouTube visibility</label></div><select id="z-vis" class="text"><option>public</option><option>unlisted</option><option>private</option></select></div>
    </div>
    <label class="toggle"><span>Auto-post new clips</span><input type="checkbox" id="z-auto"><i class="sl"></i></label>
    <div class="prow" style="margin-top:12px"><button class="btn ghost" id="z-check">Save &amp; identify channels</button><span class="msg" id="z-msg">Not connected</span></div>
  </div>
 </div>
</section>

<section class="right">
  <div class="hero" id="hero" data-phase="idle">
    <div class="eq"><i></i><i></i><i></i><i></i><i></i></div>
    <div><div class="ph" id="ph">Ready</div><div class="st" id="st">Ready when you are.</div></div>
    <div class="stats">
      <div class="stat"><b id="s-time">0:00</b><span>Elapsed</span></div>
      <div class="stat"><b id="s-chunks">0</b><span>Chunks</span></div>
      <div class="stat"><b id="s-clips">0</b><span>New clips</span></div>
    </div>
  </div>
  <div class="progress-wrap" id="progress-wrap" hidden><div class="progress-meta"><span id="progress-label">Preparing...</span><span id="progress-value">0%</span></div><div class="progress-track"><div class="progress-fill" id="progress-fill"></div></div></div>
  <div class="tabs" id="tabs">
    <button class="tab on" data-t="clips">Clips<em id="cnt" hidden></em></button>
    <button class="tab" data-t="log">Live log</button>
    <button class="tab" data-t="words">Hype words</button>
  </div>
  <div class="panel" id="p-clips">
    <div class="post-progress" id="post-progress" hidden><div class="progress-meta"><span id="post-label">Preparing uploads...</span><span><span id="post-value">0%</span> · <span id="post-time">0:00</span></span></div><div class="progress-track"><div class="progress-fill" id="post-fill"></div></div></div>
    <div class="prow" style="justify-content:space-between;margin-bottom:10px"><div class="prow"><button class="btn ghost on" id="btn-view-clips">Clips</button><button class="btn ghost" id="btn-view-posted">Posted</button></div><div class="prow"><button class="btn ghost" id="btn-select-all">Select all</button><button class="btn ghost" id="btn-publish-selected">Publish selected (0)</button><button class="btn danger" id="btn-delete-selected">Delete selected (0)</button><button class="btn danger" id="btn-delete-all">Delete all</button><button class="btn danger" id="btn-publish-all">Publish all clips</button></div></div>
    <div class="grid" id="grid"></div>
    <div class="prow" id="clip-pages" style="justify-content:center;margin-top:12px"><button class="btn ghost" id="btn-clips-newer">Newer</button><span class="hint" id="clip-page-label"></span><button class="btn ghost" id="btn-clips-older">Older</button></div>
    <div class="empty" id="empty"><div class="big"><svg width="28" height="28" viewBox="0 0 24 24" fill="#fff"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg></div><h4>No clips yet</h4><p>Paste a Twitch or YouTube live link (or choose a VOD file) and hit Start. Finished 9:16 clips with captions appear here, ready to post.</p></div>
  </div>
  <div class="panel" id="p-log" hidden><div class="log-head"><div class="log-title">Live diagnostic log <span id="log-live" class="log-live">Live</span></div><div class="log-actions"><button class="btn ghost" id="log-pause" type="button">Pause</button><button class="btn ghost" id="log-clear" type="button">Clear view</button><a class="btn ghost" href="/api/log/download" download="streamsnip.log">Download</a></div></div><div id="log"></div></div>
  <div class="panel" id="p-words" hidden>
    <div class="hw">
      <p class="help">One word or phrase per line. Add what <b>your</b> streamer actually says - e.g. <code>oh my days</code> or <code>no chance | 3</code> (the number is the weight, default 2). Lines starting with <code>#</code> are comments. Saved changes apply to the next chunk, even mid-stream.</p>
      <textarea id="words" spellcheck="false"></textarea>
      <div class="hwb"><button class="btn ghost" id="btn-words-save"><span data-ico="check"></span>Save hype words</button><span class="msg" id="words-msg">Saved</span></div>
      <details><summary id="builtin-sum">Built-in hype words</summary><div class="chips" id="chips"></div></details>
    </div>
  </div>
</section>
</div>
</div>
<div class="overlay" id="settings-overlay" hidden>
 <div class="settings-dialog">
   <div class="settings-head"><div><h2>App settings</h2><p>Configure clipping defaults and publishing providers.</p></div><div class="prow"><button class="btn ghost" id="btn-settings-save">Save settings</button><button class="btn ghost" id="btn-settings-close">Close</button></div></div>
  <div id="settings-slot"></div>
 </div>
</div>
<div class="overlay" id="about-overlay" hidden>
 <div class="settings-dialog about-dialog">
  <div class="settings-head"><div><h2>About StreamSnip AI</h2><p>Local-first clipping tools for creators, by ScarZero.</p></div><button class="btn ghost" id="btn-about-close">Close</button></div>
  <div class="about-hero">
   <div class="about-title"><div class="mark small-mark"><img src="/assets/app-icon.png" alt="StreamSnip AI"></div><div><h3>StreamSnip AI by ScarZero</h3><p class="hint">Turn Twitch, YouTube, and video files into captioned clips for Shorts, Reels, TikTok, and YouTube.</p></div></div>
   <p class="about-copy">StreamSnip AI keeps capture, transcription, rendering, settings, and generated clips local by default. Hook words and Ollama work locally; Gemini, Hugging Face, and Zernio are optional hosted integrations.</p>
   <p class="about-copy">Built for flexible framing, animated captions, creator credit, local clip review, and deliberate publishing workflows.</p>
   <p class="about-copy"><strong>Created and maintained by Sifat Jaman / ScarZero.</strong> Development has included assistance from OpenAI, Anthropic, and Google AI tools.</p>
   <div class="about-links"><a class="btn ghost" href="https://github.com/sifat-jaman-13/stream-clip-ai" target="_blank" rel="noopener">GitHub · Source</a><a class="btn ghost" href="https://github.com/sifat-jaman-13/stream-clip-ai/releases/latest" target="_blank" rel="noopener">Latest release</a><a class="btn ghost" href="https://youtube.com/@scarclipfarm" target="_blank" rel="noopener">YouTube · Scar Clip Farm</a><a class="btn ghost" href="https://www.youtube.com/@scarzeroyt" target="_blank" rel="noopener">YouTube · Scarzero</a><a class="btn ghost" href="https://www.instagram.com/scarzero13/" target="_blank" rel="noopener">Instagram · @scarzero13</a><a class="btn ghost" href="https://www.facebook.com/ScarZero13" target="_blank" rel="noopener">Facebook · ScarZero13</a><a class="btn ghost" href="https://www.twitch.tv/scarzero13" target="_blank" rel="noopener">Twitch · scarzero13</a><a class="btn ghost" href="https://www.tiktok.com/@scarzero13" target="_blank" rel="noopener">TikTok · @scarzero13</a></div>
  </div>
 </div>
</div>
<div id="toasts"></div>
<div id="offline" hidden>Lost connection to StreamSnip AI - is it still running?</div>

<script>
const BOOT=__BOOT__;
const TOKEN="__TOKEN__";
let appClosing=false;
const S=Object.assign({},BOOT.settings);
const P=Object.assign({provider:"zernio",providers:{}},BOOT.publishing||{});
let activeProvider="zernio";
let Z=Object.assign({},(P.providers&&P.providers[activeProvider])||{});
let accountsLoadedFor="";
let clipOffset=0,clipTab="clips",tabClipNames=[];
const CLIP_PAGE_SIZE=60;
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const ICON={
 copy:'<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
 download:'<path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/>',
 folder:'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
 trash:'<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
 play:'<path d="M8 5v14l11-7z" fill="currentColor"/>',
 bolt:'<path d="M13 2 4 14h7l-1 8 9-12h-7z" fill="currentColor"/>',
 power:'<path d="M12 3v9"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/>',
 info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
 settings:'<path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Z"/><path d="m4.9 4.9 1.4 1.4M17.7 17.7l1.4 1.4M4 12H2M22 12h-2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4M12 4V2M12 22v-2"/>',
 check:'<path d="m5 12 5 5 9-10"/>'
};
function ico(n,s){const e=document.createElementNS("http://www.w3.org/2000/svg","svg");e.setAttribute("viewBox","0 0 24 24");e.setAttribute("width",s||16);e.setAttribute("height",s||16);e.setAttribute("fill","none");e.setAttribute("stroke","currentColor");e.setAttribute("stroke-width","2");e.setAttribute("stroke-linecap","round");e.setAttribute("stroke-linejoin","round");e.innerHTML=ICON[n];return e}
$$("[data-ico]").forEach(el=>el.append(ico(el.dataset.ico,+el.dataset.s||16)));
function h(tag,attrs,...kids){const e=document.createElement(tag);for(const [k,v] of Object.entries(attrs||{})){if(k==="class")e.className=v;else if(k.startsWith("on"))e.addEventListener(k.slice(2),v);else if(v===true)e.setAttribute(k,"");else if(v!==false&&v!=null)e.setAttribute(k,v)}for(const c of kids.flat()){if(c==null||c===false)continue;e.append(c.nodeType?c:document.createTextNode(String(c)))}return e}
async function api(path,body){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json","X-Token":TOKEN},body:JSON.stringify(body||{})});
  let j={};try{j=await r.json()}catch(e){}
  if(!r.ok)throw new Error(j.error||("Request failed ("+r.status+")"));
  return j;
}
async function refreshCreators(){
  const host=$("#creator-list");if(!host)return;
  try{
    const response=await fetch("/api/creators",{cache:"no-store"});
    if(!response.ok)throw new Error("Could not load creator monitors");
    const data=await response.json(),items=data.creators||[];
    if(!items.length){host.replaceChildren(h("p",{class:"hint"},"No creator monitors yet. Add a Twitch or YouTube channel above."));return}
    host.replaceChildren(...items.map(c=>{
      const running=!!c.running,phase=c.phase||"offline";
      const watching=!!c.watching_vods;
      const actions=h("div",{class:"creator-actions"},
        h("button",{class:"btn ghost",onclick:async()=>{try{await api(running?"/api/creators/stop":"/api/creators/start",{id:c.id});await refreshCreators()}catch(e){toast(e.message,"bad")}}},running?"Stop live":"Start live"),
        h("button",{class:"btn ghost",onclick:async()=>{try{await api("/api/creators/open",{id:c.id,folder:"root"})}catch(e){toast(e.message,"bad")}}},"Creator folder"),
        h("button",{class:"btn ghost",onclick:async()=>{try{await api("/api/creators/open",{id:c.id,folder:"live_clips"})}catch(e){toast(e.message,"bad")}}},"Live clips"),
        h("button",{class:"btn ghost",onclick:async()=>{try{await api("/api/creators/open",{id:c.id,folder:"vod_inbox"})}catch(e){toast(e.message,"bad")}}},"VOD inbox"),
        h("button",{class:"btn ghost",onclick:async()=>{try{await api("/api/creators/open",{id:c.id,folder:"vod_clips"})}catch(e){toast(e.message,"bad")}}},"VOD clips"),
        h("button",{class:"btn "+(watching?"danger":"primary"),onclick:async()=>{try{await api(watching?"/api/creators/stop-vod-watch":"/api/creators/watch-vods",{id:c.id});await refreshCreators()}catch(e){toast(e.message,"bad")}}},watching?"Stop folder watch":"Watch VOD folder"),
        h("button",{class:"btn ghost",onclick:async()=>{if(!(await confirmBox("Remove "+c.name+"?","Stop both monitors first. Existing recordings and clips are kept.","Remove")))return;try{await api("/api/creators/remove",{id:c.id});await refreshCreators()}catch(e){toast(e.message,"bad")}}},"Remove"));
      return h("div",{class:"creator-item"},
        h("div",{class:"creator-top"},h("div",{class:"creator-name"},c.name),h("span",{class:"creator-state "+(running?"live":"")},running?(phase==="recording"?"LIVE":phase):"OFFLINE")),
        h("div",{class:"creator-detail"},c.status||c.target),
        h("div",{class:"creator-detail"},"Live clips: "+(Number(c.live_clips)||0)+" · Recorded-VOD clips: "+(Number(c.vod_clips)||0)+" · VODs waiting: "+(Number(c.vod_pending)||0)),
        h("div",{class:"creator-detail"},c.vod_status||"Recorded-VOD folder is not being watched."),
        actions);
    }));
  }catch(e){host.replaceChildren(h("p",{class:"hint"},e.message))}
}
$("#creator-add").onclick=async()=>{
  const name=$("#creator-name").value.trim(),target=$("#creator-target").value.trim();
  if(!name||!target){toast("Enter a creator name and Twitch/YouTube URL.","bad");return}
  const button=$("#creator-add");button.disabled=true;
  try{await api("/api/creators/add",{name,target});$("#creator-name").value="";$("#creator-target").value="";await refreshCreators();toast("Creator monitor added.","ok")}
  catch(e){toast(e.message,"bad")}
  button.disabled=false;
};
const markWindowOpen=()=>api("/api/window/open").catch(()=>{});
const createWindowLeaseId=()=>window.crypto&&typeof window.crypto.randomUUID==="function"?window.crypto.randomUUID():"window-"+Date.now()+"-"+Math.random().toString(36).slice(2);
let windowLeaseId=createWindowLeaseId(),windowLeaseController=null,windowLeaseActive=false;
function startWindowLease(){if(windowLeaseActive)return;windowLeaseActive=true;windowLeaseController=new AbortController();const controller=windowLeaseController;(async()=>{while(windowLeaseActive&&controller===windowLeaseController){try{const r=await fetch("/api/window/lease?id="+encodeURIComponent(windowLeaseId),{headers:{"X-Token":TOKEN},cache:"no-store",signal:controller.signal});if(!r.ok)throw new Error("Window lease failed");const reader=r.body.getReader();while(windowLeaseActive){const part=await reader.read();if(part.done)break}}catch(e){}if(windowLeaseActive)await new Promise(resolve=>setTimeout(resolve,350))}})()}
function stopWindowLease(){windowLeaseActive=false;if(windowLeaseController)windowLeaseController.abort();windowLeaseController=null}
markWindowOpen();startWindowLease();window.addEventListener("pageshow",()=>{if(!windowLeaseActive)windowLeaseId=createWindowLeaseId();markWindowOpen();startWindowLease()});
window.addEventListener("pagehide",()=>{const closingLeaseId=windowLeaseId;stopWindowLease();if(appClosing)return;fetch("/api/window/closing?id="+encodeURIComponent(closingLeaseId),{method:"POST",headers:{"Content-Type":"application/json","X-Token":TOKEN},body:JSON.stringify({id:closingLeaseId}),keepalive:true}).catch(()=>{})});
const AI=BOOT.ai||{provider:"gemini",ollama_url:"http://127.0.0.1:11434",ollama_model:""};
$("#ai-provider").value=AI.provider||"gemini";
$("#ollama-url").value=AI.ollama_url||"http://127.0.0.1:11434";
$("#ollama-model").replaceChildren(h("option",{value:AI.ollama_model||""},AI.ollama_model||"Click Detect models"));
$("#hf-model").value=AI.huggingface_model||"deepseek-ai/DeepSeek-V4.1-Flash:fastest";
$("#custom-api-base").value=AI.custom_api_base||"https://api.openai.com/v1";
$("#custom-api-model").value=AI.custom_api_model||"";
$("#custom-api-key-state").textContent=AI.custom_api_key_set?"Saved locally":"Not saved";
$("#custom-api-key-clear").disabled=!AI.custom_api_key_set;
$("#gemini-key-state").textContent=AI.gemini_key_set?"Saved locally":"Not saved";
$("#gemini-model").value=AI.gemini_model||"gemini-3.8-flash";
$("#hf-token-state").textContent=AI.huggingface_token_set?"Saved locally":"Not saved";
$("#gemini-key-clear").disabled=!AI.gemini_key_set;$("#hf-token-clear").disabled=!AI.huggingface_token_set;
function showAIFields(updateMessage=false){
  const p=$("#ai-provider").value;
  $("#ollama-ai-fields").hidden=p!=="ollama";
  $("#gemini-ai-fields").hidden=p!=="gemini";
  $("#hf-ai-fields").hidden=p!=="huggingface";
  $("#custom-ai-fields").hidden=p!=="custom";
  $("#ai-test-provider").hidden=p==="hooks";
  if(updateMessage){
    const names={ollama:"Ollama",gemini:"Gemini",huggingface:"Hugging Face",custom:"custom OpenAI-compatible API"};
    $("#ai-settings-msg").textContent=p==="hooks"?"Built-in hook detection selected":"Ready to test or save "+names[p]+" settings";
  }
  $$(".ai-choice").forEach(b=>{const active=b.dataset.aiProvider===p;b.classList.toggle("on",active);b.setAttribute("aria-pressed",active?"true":"false")});
}
$("#ai-provider").onchange=()=>showAIFields(true);$$(".ai-choice").forEach(b=>b.onclick=()=>{$("#ai-provider").value=b.dataset.aiProvider;showAIFields(true)});showAIFields(true);
$("#ai-detect-ollama").onclick=async()=>{const b=$("#ai-detect-ollama");b.disabled=true;try{const r=await api("/api/ai/ollama/models",{ollama_url:$("#ollama-url").value});const select=$("#ollama-model");select.replaceChildren(...(r.models.length?r.models.map(m=>h("option",{value:m},m)):[h("option",{value:""},"No models installed") ]));if(AI.ollama_model&&r.models.includes(AI.ollama_model))select.value=AI.ollama_model;else if(r.models.length)select.value=r.models[0];$("#ai-settings-msg").textContent=r.models.length?"Found "+r.models.length+" installed Ollama model(s)":"Ollama is installed, but no models were found"}catch(e){$("#ai-settings-msg").textContent=e.message}b.disabled=false};
function aiSettingsPayload(){const payload={provider:$("#ai-provider").value,ollama_url:$("#ollama-url").value,ollama_model:$("#ollama-model").value,gemini_model:$("#gemini-model").value.trim()||"gemini-3.8-flash",huggingface_model:$("#hf-model").value.trim()||"deepseek-ai/DeepSeek-V4.1-Flash:fastest",custom_api_base:$("#custom-api-base").value.trim(),custom_api_model:$("#custom-api-model").value.trim()};if($("#gemini-key").value)payload.gemini_api_key=$("#gemini-key").value;if($("#hf-token").value)payload.huggingface_token=$("#hf-token").value;if($("#custom-api-key").value)payload.custom_api_key=$("#custom-api-key").value;return payload}
function refreshAISecretState(){$("#gemini-key-state").textContent=AI.gemini_key_set?"Saved locally":"Not saved";$("#hf-token-state").textContent=AI.huggingface_token_set?"Saved locally":"Not saved";$("#custom-api-key-state").textContent=AI.custom_api_key_set?"Saved locally":"Not saved";$("#gemini-key-clear").disabled=!AI.gemini_key_set;$("#hf-token-clear").disabled=!AI.huggingface_token_set;$("#custom-api-key-clear").disabled=!AI.custom_api_key_set}
$("#ai-settings-save").onclick=async()=>{const b=$("#ai-settings-save");b.disabled=true;try{const r=await api("/api/ai/settings",aiSettingsPayload());Object.assign(AI,r);$("#gemini-key").value="";$("#hf-token").value="";$("#custom-api-key").value="";refreshAISecretState();$("#ai-settings-msg").textContent="Saved. "+$("#ai-provider option:checked").textContent;toast("AI highlight settings saved","ok")}catch(e){$("#ai-settings-msg").textContent=e.message;toast(e.message,"bad")}b.disabled=false};
async function clearAISecret(kind){
  const configs={
    gemini:{label:"Gemini API key",button:"#gemini-key-clear",input:"#gemini-key",flag:"clear_gemini_key"},
    huggingface:{label:"Hugging Face token",button:"#hf-token-clear",input:"#hf-token",flag:"clear_huggingface_token"},
    custom:{label:"Custom API key",button:"#custom-api-key-clear",input:"#custom-api-key",flag:"clear_custom_api_key"}
  };
  const item=configs[kind];
  if(!item)return;
  if(!(await confirmBox("Clear saved "+item.label+"?","The credential will be removed from this computer. Add and save a new one before using this hosted provider again.","Clear credential")))return;
  const button=$(item.button);button.disabled=true;
  try{
    const payload=aiSettingsPayload();payload[item.flag]=true;
    const r=await api("/api/ai/settings",payload);Object.assign(AI,r);
    $(item.input).value="";refreshAISecretState();
    $("#ai-settings-msg").textContent=item.label+" cleared from this computer";toast(item.label+" cleared","ok");
  }catch(e){refreshAISecretState();$("#ai-settings-msg").textContent=e.message;toast(e.message,"bad")}
}
$("#gemini-key-clear").onclick=()=>clearAISecret("gemini");
$("#hf-token-clear").onclick=()=>clearAISecret("huggingface");
$("#custom-api-key-clear").onclick=()=>clearAISecret("custom");
$("#ai-test-provider").onclick=async()=>{const b=$("#ai-test-provider");b.disabled=true;$("#ai-settings-msg").textContent="Testing connection...";try{const r=await api("/api/ai/test",aiSettingsPayload());$("#ai-settings-msg").textContent=r.message;toast(r.message,"ok")}catch(e){$("#ai-settings-msg").textContent=e.message;toast(e.message,"bad")}b.disabled=false};
function selectedZernioAccounts(){
  const selected={};
  $$("#z-account-picks input:checked").forEach(input=>{selected[input.dataset.platform]=input.value});
  return selected;
}
async function loadPublishingAccounts(){
  if(Z.available===false){$("#z-msg").textContent="Posting adapter unavailable";$("#z-msg").classList.add("show");return}
  const provider=activeProvider;
  const r=await api("/api/publishing/accounts",{provider});
  if(provider!==activeProvider)return;
  const saved=Object.assign({},Z.accounts||{});
  if(!Object.keys(saved).length){
    if(Z.instagram_id)saved.instagram=Z.instagram_id;
    if(Z.youtube_id)saved.youtube=Z.youtube_id;
  }
  const host=$("#z-account-picks");host.replaceChildren();
  const groups={};
  r.accounts.forEach(account=>{
    const platform=String(account.platform||"").toLowerCase();
    if(!groups[platform])groups[platform]=[];
    groups[platform].push(account);
  });
  const labels={twitter:"X / Twitter",instagram:"Instagram",facebook:"Facebook",linkedin:"LinkedIn",tiktok:"TikTok",youtube:"YouTube",pinterest:"Pinterest",reddit:"Reddit",bluesky:"Bluesky",threads:"Threads",googlebusiness:"Google Business"};
  const defaults={};
  Object.entries(groups).forEach(([platform,items])=>{
    if(items.length)defaults[platform]=String(items[0].id);
    items.forEach(account=>{
      const input=h("input",{type:"radio",name:"z-account-"+platform,value:account.id,"data-platform":platform});
      input.checked=String(saved[platform]||(!Object.keys(saved).length?defaults[platform]:""))===String(account.id);
      host.append(h("label",{class:"z-account-pick"},input,h("span",{},(labels[platform]||platform)+" · "+(account.name||account.username||account.id))));
    });
  });
  if(!Object.keys(saved).length)Z.accounts=defaults;
  Z.connected_accounts=r.accounts;
  if(!r.accounts.length)host.append(h("p",{class:"hint"},"No connected social accounts were found for this Zernio key."));
  accountsLoadedFor=provider;
  $("#z-msg").textContent=r.accounts.length?r.accounts.length+" connected account(s) identified":"No supported social accounts found";
  $("#z-msg").classList.add("show");
}
function toast(msg,kind){if($$(".toast").some(x=>x.textContent===msg))return;const t=h("div",{class:"toast "+(kind||"")},msg);$("#toasts").append(t);setTimeout(()=>{t.classList.add("out");setTimeout(()=>t.remove(),300)},3200)}
const settingsOverlay=$("#settings-overlay");
const aboutOverlay=$("#about-overlay");
$("#settings-slot").append($("#settings-card"));
function closeSettings(){settingsOverlay.hidden=true}
function openSettings(){settingsOverlay.hidden=false;$("#z-api").focus()}
function closeAbout(){aboutOverlay.hidden=true}
function openAbout(){aboutOverlay.hidden=false}
$("#btn-settings").onclick=openSettings;
$("#btn-settings-close").onclick=closeSettings;
settingsOverlay.onclick=e=>{if(e.target===settingsOverlay)closeSettings()};
$("#btn-about").onclick=openAbout;
$("#btn-about-close").onclick=closeAbout;
aboutOverlay.onclick=e=>{if(e.target===aboutOverlay)closeAbout()};
document.addEventListener("keydown",e=>{if(e.key!=="Escape")return;if(!settingsOverlay.hidden)closeSettings();if(!aboutOverlay.hidden)closeAbout()});
$("#rec-dir").value=S.rec_dir||""; $("#out-dir").value=S.out_dir||""; $("#capture-bitrate").value=S.capture_bitrate_kbps||8000;
function wireFolderPicker(inputId,buttonId,key){
  const input=$(inputId), button=$(buttonId);
  input.addEventListener("change",()=>{S[key]=input.value.trim();scheduleSave()});
  button.onclick=async()=>{button.disabled=true;try{const r=await api("/api/browse_folder");if(r.path){input.value=r.path;S[key]=r.path;scheduleSave();toast("Folder saved","ok")}}catch(e){toast(e.message,"bad")}button.disabled=false};
}
wireFolderPicker("#rec-dir","#rec-dir-browse","rec_dir");
wireFolderPicker("#out-dir","#out-dir-browse","out_dir");
$("#compute-device").value=S.compute_device||"gpu";
$("#compute-device").addEventListener("change",e=>{S.compute_device=e.target.value;scheduleSave()});
$("#capture-bitrate").addEventListener("change",e=>{S.capture_bitrate_kbps=Math.max(8000,Math.min(50000,+e.target.value||8000));e.target.value=S.capture_bitrate_kbps;scheduleSave()});
$("#btn-settings-save").onclick=async()=>{const b=$("#btn-settings-save");b.disabled=true;try{await api("/api/settings",S);toast("Settings saved","ok")}catch(e){toast(e.message,"bad")}b.disabled=false};
$("#btn-updates").onclick=async()=>{const b=$("#btn-updates");b.disabled=true;$("#updates-msg").textContent="Checking...";try{const r=await api("/api/check_updates");$("#updates-msg").textContent="Checked "+r.checked_at;$("#updates-list").textContent=r.items.map(x=>x.name+": "+x.current+(x.latest!=="Unknown"?" → "+x.latest:"")+(x.update?" (update available)":"")+(x.note?"  -  "+x.note:"")).join("\n")}catch(e){$("#updates-msg").textContent=e.message}b.disabled=false};
$("#btn-app-version").onclick=async()=>{const b=$("#btn-app-version"),u=$("#btn-app-update");b.disabled=true;$("#app-version-msg").textContent="Checking...";try{const r=await api("/api/check_app_update");$("#app-version-msg").textContent=r.update?"Update available: v"+r.latest:"You are up to date (v"+r.current+")";u.disabled=!r.update;u.onclick=()=>window.open(r.url,"_blank","noopener");if(r.update)toast("A new StreamSnip AI version is available","ok")}catch(e){$("#app-version-msg").textContent=e.message;u.disabled=true}b.disabled=false};
$("#btn-update-components").onclick=async()=>{if(!(await confirmBox("Update components?","This updates Python packages and downloads the selected speech model. FFmpeg is bundled into the next installer build.","Update")))return;const b=$("#btn-update-components");b.disabled=true;$("#updates-msg").textContent="Updating...";try{const r=await api("/api/update_components");$("#updates-msg").textContent=r.message;toast("Components updated","ok")}catch(e){$("#updates-msg").textContent=e.message;toast(e.message,"bad")}b.disabled=false};
function confirmBox(title,msg,ok){return new Promise(res=>{
  const done=v=>{m.remove();res(v)};
  const m=h("div",{class:"overlay"},h("div",{class:"dialog"},h("h4",{},title),h("p",{},msg),h("div",{class:"dlg-actions"},h("button",{class:"btn ghost",onclick:()=>done(false)},"Cancel"),h("button",{class:"btn danger",onclick:()=>done(true)},ok||"Delete"))));
  document.body.append(m)})}

/* ---------- settings <-> controls ---------- */
let saveT=null;
function scheduleSave(){clearTimeout(saveT);saveT=setTimeout(()=>{api("/api/settings",S).catch(()=>{})},500)}
function paintRange(el){const p=(el.value-el.min)/(el.max-el.min)*100;el.style.setProperty("--p",p+"%")}
const RANGES=[["r-sens","min_score","v-sens",v=>Math.round(+v),true],["r-cpc","clips_per_chunk","v-cpc",v=>v,true],["r-chunk","chunk_min","v-chunk",v=>v+" min",true],
 ["r-pre","pre","v-pre",v=>v+" s",true],["r-post","post","v-post",v=>v+" s",true],["r-size","caption_size","v-size",v=>v,true]];
RANGES.forEach(([id,key,lab,fmt])=>{
  const el=$("#"+id);el.value=S[key];
  const upd=()=>{S[key]=+el.value;$("#"+lab).textContent=fmt(el.value);paintRange(el)};
  el.addEventListener("input",()=>{upd();preview();scheduleSave()});upd();
});
$$(".seg[data-key]").forEach(sg=>{
  const key=sg.dataset.key,num=!!sg.dataset.num;
  const paint=()=>$$("button",sg).forEach(b=>b.classList.toggle("on",b.dataset.v===String(S[key])));
  sg.addEventListener("click",e=>{const b=e.target.closest("button");if(!b)return;S[key]=num?+b.dataset.v:b.dataset.v;paint();onMode();preview();scheduleSave()});
  paint();
});
const sw=$("#sw");
Object.entries(BOOT.colors).forEach(([name,css])=>{sw.append(h("button",{title:name,style:"background:"+css,"data-v":name,onclick:()=>{S.color=name;paintSw();preview();scheduleSave()}}))});
function paintSw(){$$("button",sw).forEach(b=>b.classList.toggle("on",b.dataset.v===S.color))}paintSw();
BOOT.models.forEach(m=>$("#model").append(h("option",{value:m},m==="distil-large-v3"?"distil-large-v3 (fast, English)":m==="large-v3-turbo"?"large-v3-turbo (fast, any language)":m==="medium"?"medium (balanced)":m==="large-v3"?"large-v3 (highest accuracy)":m==="small"?"small (light)":"base (lightest)")));
$("#model").value=S.model;$("#model").addEventListener("change",e=>{S.model=e.target.value;scheduleSave()});
$("#transcriber-provider").value=S.transcriber_provider||"faster-whisper";
$("#transcriber-command").value=S.transcriber_command||"";
$("#transcriber-language").value=S.transcriber_language||"auto";
function updateTranscriberFields(){
  const custom=$("#transcriber-provider").value==="custom-command";
  $("#transcriber-custom-fields").hidden=!custom;
  $("#faster-whisper-fields").hidden=custom;
}
$("#transcriber-provider").addEventListener("change",e=>{S.transcriber_provider=e.target.value;updateTranscriberFields();scheduleSave()});
$("#transcriber-command").addEventListener("change",e=>{S.transcriber_command=e.target.value.slice(0,2000);scheduleSave()});
$("#transcriber-language").addEventListener("change",e=>{S.transcriber_language=e.target.value.trim().slice(0,20)||"auto";scheduleSave()});
updateTranscriberFields();
$("#output-format").value=S.output_format;function updateFormatUI(){const f=S.output_format;$("#format-hint").textContent=f==="9:16"?"9:16 keeps the facecam + game layout.":f==="16:9"?"16:9 renders a landscape YouTube frame.":f==="1:1"?"1:1 renders a square social frame.":"4:5 renders an Instagram portrait frame."}function resetCropForFormat(){const r=({"9:16":9/16,"16:9":16/9,"1:1":1,"4:5":4/5}[S.output_format]||9/16),w=Math.min(100,100*r/(16/9));S.crop_w=+w.toFixed(1);S.crop_h=100;S.crop_x=+( (100-w)/2 ).toFixed(1);S.crop_y=0}$("#output-format").addEventListener("change",e=>{S.output_format=e.target.value;resetCropForFormat();updateFormatUI();preview();scheduleSave()});updateFormatUI();
$("#font").value=S.font;$("#font").addEventListener("input",e=>{const v=e.target.value.trim();if(/^[A-Za-z0-9 \-]{1,40}$/.test(v)){S.font=v;preview();scheduleSave()}});
// Temporary live capture cleanup is automatic; original VOD files are preserved.
$("#show-tag-video").checked=!!S.show_tag_video;
$("#show-tag-video").addEventListener("change",e=>{S.show_tag_video=e.target.checked;scheduleSave()});
$("#t-sub-custom").checked=!!S.subtitle_custom;
$("#sub-custom-fields").hidden=!S.subtitle_custom;
$("#t-sub-custom").addEventListener("change",e=>{S.subtitle_custom=e.target.checked;$("#sub-custom-fields").hidden=!S.subtitle_custom;scheduleSave();preview()});
 $("#t-profanity").checked=S.profanity_filter_enabled!==false;
 $("#t-profanity").addEventListener("change",e=>{S.profanity_filter_enabled=e.target.checked;scheduleSave()});
 $("#profanity-words").value=S.profanity_filter_words||"";
 $("#profanity-words").addEventListener("input",e=>{S.profanity_filter_words=e.target.value.slice(0,4000);scheduleSave()});
$("#sub-mode").value=S.subtitle_mode;$("#sub-mode").addEventListener("change",e=>{S.subtitle_mode=e.target.value;scheduleSave()});
$("#sub-style").value=S.subtitle_style;$("#sub-style").addEventListener("change",e=>{S.subtitle_style=e.target.value;scheduleSave();preview()});
$("#sub-text-color").value=S.subtitle_text_color;$("#sub-text-color").addEventListener("input",e=>{S.subtitle_text_color=e.target.value.toUpperCase();scheduleSave();preview()});
$("#sub-stroke-color").value=S.subtitle_stroke_color;$("#sub-stroke-color").addEventListener("input",e=>{S.subtitle_stroke_color=e.target.value.toUpperCase();scheduleSave();preview()});
for(const [id,key,lab,fmt] of [["r-sub-size","subtitle_font_size","v-sub-size",v=>v+" px"],["r-sub-nudge","subtitle_nudge","v-sub-nudge",v=>v+" px"]]){
  const el=$("#"+id);el.value=S[key];const upd=()=>{S[key]=+el.value;$("#"+lab).textContent=fmt(el.value);paintRange(el)};
  el.addEventListener("input",()=>{upd();preview();scheduleSave()});upd();
}
function inferStreamerTag(url){
  let m=String(url||"").match(/twitch\.tv\/([^/?#]+)/i);
  if(m&&!/^(videos|directory|search)$/i.test(m[1]))return "@"+m[1];
  m=String(url||"").match(/youtube\.com\/@([^/?#]+)/i);
  return m?"@"+m[1]:"";
}
let tagManual=!!S.streamer_tag&&S.streamer_tag!==inferStreamerTag(S.target);
function syncStreamerTag(){
  if(tagManual)return;
  S.streamer_tag=inferStreamerTag(S.target);
  $("#streamer-tag").value=S.streamer_tag;
}
$("#target").value=S.target||"";syncStreamerTag();
$("#target").addEventListener("input",e=>{S.target=e.target.value;syncStreamerTag();scheduleSave()});
$("#streamer-tag").addEventListener("input",e=>{tagManual=true;S.streamer_tag=e.target.value.replace(/[\r\n{}\\]/g,"").slice(0,80);scheduleSave()});
function onMode(){
  const live=S.mode==="live";
  const facecam=S.layout.startsWith("Facecam"),selected=S.layout.startsWith("Selected");
  $("#camrow").hidden=!(facecam||selected);
  $("#cam-area-row").hidden=!facecam;
  $("#v-cam").textContent="x"+S.cam_x+"% y"+S.cam_y+"% size "+S.cam_w+"%";
  $("#btn-cam").textContent=facecam?"Set facecam area on a frame":"Select source segment on a frame";
  $("#cam-hint").textContent=facecam?"Like Twitch: the facecam fills the top 40% of the clip and the game fills the bottom 60%.":"Uses the original source frame (normally 16:9). The selected format box captures exactly the segment you choose.";
  $("#btn-cam").onclick=facecam?openCamEditor:openCropEditor;
  $("#target").placeholder=live?"https://www.twitch.tv/channel":"Path to a .mp4 / .mkv recording";
  $("#btn-browse").hidden=live;
  $("#src-hint").textContent=live?"Works with Twitch and YouTube live links. If the stream is offline, StreamSnip AI waits and starts when it goes live.":"Clips are cut from the whole file. Long VODs get more clips automatically.";
  $("#go-label").textContent=live?"Start recording & clipping":"Make clips from this file";
}
onMode();
$("#btn-browse").onclick=async()=>{const b=$("#btn-browse");b.disabled=true;try{const r=await api("/api/browse");if(r.path){$("#target").value=r.path;S.target=r.path;scheduleSave()}}catch(e){toast(e.message,"bad")}b.disabled=false};

/* ---------- caption preview ---------- */
const FLAT="NO WAY BRO THIS IS INSANE LET HIM COOK ARE YOU MAD".split(" ");
let tick=0;
function preview(){
  const ph=$("#phone"),cap=$("#cap");
  const formatRatio={"9:16":"9/16","16:9":"16/9","1:1":"1/1","4:5":"4/5"}[S.output_format]||"9/16";
  ph.style.aspectRatio=formatRatio;
  ph.classList.toggle("fill",S.layout.startsWith("Fill"));ph.classList.toggle("cam",S.layout.startsWith("Facecam"));
  const k=ph.getBoundingClientRect().width/1080||0.2;
  const custom=!!S.subtitle_custom;
  const n=S.words_per_line;
  const subFont=custom?({Classic:"Impact",Hormozi:"Arial Black",Neon:"Arial Black",MrBeast:"Impact",Minimal:"Segoe UI Black",Fire:"Impact"}[S.subtitle_style]||"Impact"):S.font;
  const subPos=custom?S.subtitle_position:"Bottom";
  const bottom=custom?(subPos==="Bottom"?70:subPos==="Center"?760:null):(BOOT.positions[S.position]||520);
  const idx=tick%FLAT.length,g=Math.floor(idx/n),words=FLAT.slice(g*n,Math.min(FLAT.length,g*n+n));
  const o=Math.max(1,9*k),sh=[];for(let a=0;a<12;a++){const r=a/12*Math.PI*2;sh.push((Math.cos(r)*o).toFixed(1)+"px "+(Math.sin(r)*o).toFixed(1)+"px 0 #000")}
  const baseCol=custom?(S.subtitle_text_color||"#FFFFFF"):"#FFFFFF";
  const highlightCol=BOOT.colors[S.color]||"#FFE600";
  cap.style.cssText=(bottom==null?"top:"+(70+S.subtitle_nudge)*k+"px;":"bottom:"+((bottom+S.subtitle_nudge)*k)+"px;")+"padding:0 "+(70*k)+"px;font-size:"+((custom?S.subtitle_font_size:S.caption_size)*k)+"px;font-family:'"+subFont+"',Impact,'Arial Black',sans-serif;--cap:"+highlightCol+";text-shadow:"+sh.join(",")+";color:"+baseCol;
  cap.replaceChildren(...words.map((w,i)=>h("span",{class:(g*n+i===idx)?"hot":""},w)));
}
setInterval(()=>{tick++;preview()},430);preview();

/* ---------- facecam area editor ---------- */
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function openCamEditor(){
  const box={x:+S.cam_x,y:+S.cam_y,w:+S.cam_w,h:+S.cam_h};let gx=+S.game_x,ar=16/9;
  const img=h("img",{class:"cimg",draggable:false});
  const handles=["nw","ne","sw","se"].map(pos=>h("i",{class:"hdl "+pos}));
  const moveHit=h("i",{class:"move-hit",title:"Drag to move the facecam"});
  const rc=h("div",{class:"crect"},moveHit,h("span",{},"FACECAM"),handles);
  const rg=h("div",{class:"crect game"},h("span",{},"GAME"));
  const stage=h("div",{class:"cstage"},img,rg,rc);
  const hh=w=>w*ar/(1080/768);                       /* keeps the box the same shape as the top 40% area */
  function paint(){
    rc.style.cssText="left:"+box.x+"%;top:"+box.y+"%;width:"+box.w+"%;height:"+box.h+"%";
    const gw=Math.min(100,(1080/1152)/ar*100);rg.style.cssText="left:"+((100-gw)*gx/100)+"%;top:0;width:"+gw+"%;height:100%";
  }
  function fit(){box.h=hh(box.w);if(box.y+box.h>100){box.h=100-box.y;box.w=box.h*(1080/768)/ar}if(box.x+box.w>100){box.w=100-box.x;box.h=hh(box.w)}}
  fit();
  const drag=(el,mode,corner)=>el.addEventListener("pointerdown",e=>{
    e.preventDefault();e.stopPropagation();
    const r=stage.getBoundingClientRect(),s0={x:box.x,y:box.y,w:box.w,h:box.h,px:e.clientX,py:e.clientY};
    const mv=ev=>{if(ev.pointerId!==e.pointerId)return;const dx=(ev.clientX-s0.px)/r.width*100,dy=(ev.clientY-s0.py)/r.height*100;
      if(mode==="move"){box.x=clamp(s0.x+dx,0,100-s0.w);box.y=clamp(s0.y+dy,0,100-s0.h)}
      else{
        const left=corner.includes("w"),top=corner.includes("n"),right=s0.x+s0.w,bottom=s0.y+s0.h;
        /* Use the dominant movement axis. The old code only used dx, so
           dragging the upper-right/lower-left handle vertically did nothing
           and made the facecam look stuck at the top edge. */
        const ratio=hh(1), horizontal= Math.abs(dx) >= Math.abs(dy)/ratio;
        const deltaW=horizontal ? (left?-dx:dx) : (top?-dy:dy)/ratio;
        let w=clamp(s0.w+deltaW,8,100),h=hh(w),x=left?right-w:s0.x,y=top?bottom-h:s0.y;
        if(x<0){x=0;w=right;h=hh(w);y=top?bottom-h:y}
        if(x+w>100){x=left?0:s0.x;w=100-x;h=hh(w);y=top?bottom-h:y}
        if(y<0){y=0;h=bottom;w=h*(1080/768)/ar;x=left?right-w:x}
        if(y+h>100){y=top?0:s0.y;h=100-y;w=h*(1080/768)/ar;x=left?right-w:x}
        box.x=clamp(x,0,100-w);box.y=clamp(y,0,100-h);box.w=w;box.h=h
      }
      paint()};
    const up=()=>{window.removeEventListener("pointermove",mv);window.removeEventListener("pointerup",up);window.removeEventListener("pointercancel",up)};
    window.addEventListener("pointermove",mv);window.addEventListener("pointerup",up,{once:true});window.addEventListener("pointercancel",up,{once:true})});
  drag(moveHit,"move");handles.forEach(hdl=>drag(hdl,"resize",hdl.classList[1]));
  img.addEventListener("load",()=>{if(img.naturalWidth){ar=img.naturalWidth/img.naturalHeight;stage.style.aspectRatio=img.naturalWidth+"/"+img.naturalHeight;fit();paint()}});
  const gs=h("input",{type:"range",min:0,max:100,step:1,value:Math.round(gx)});paintRange(gs);
  gs.addEventListener("input",()=>{gx=+gs.value;paintRange(gs);paint()});
  const msg=h("span",{class:"hint",style:"margin:0"},"");
  const grab=h("button",{class:"btn ghost"},"Grab a frame");
  const center=h("button",{class:"btn ghost"},"Center game frame");
  const centerCrop=()=>{gx=50;gs.value=50;paintRange(gs);paint();msg.textContent="Game frame centered."};
  center.onclick=centerCrop;
  const doGrab=async()=>{grab.disabled=true;msg.textContent="Grabbing a frame...";try{const r=await api("/api/frame",{mode:S.mode,target:S.target});img.src=r.image;msg.textContent="Drag the pink box over the facecam and pull the corner to resize."}catch(e){msg.textContent=e.message}grab.disabled=false};
  grab.onclick=doGrab;
  const close=()=>{m.remove();document.removeEventListener("keydown",esc)};
  const esc=e=>{if(e.key==="Escape")close()};
  const save=()=>{S.cam_x=+box.x.toFixed(1);S.cam_y=+box.y.toFixed(1);S.cam_w=+box.w.toFixed(1);S.cam_h=+box.h.toFixed(1);S.game_x=gx;onMode();scheduleSave();close();toast("Facecam area saved","ok")};
  const m=h("div",{class:"overlay",onclick:e=>{if(e.target===m)close()}},
    h("div",{class:"editor"},h("h4",{},"Set the facecam area"),
      h("div",{class:"sub"},"Pink = the facecam (becomes the top 40% of the clip). Dashed blue = the part of the game that fills the bottom 60%."),
      stage,
       h("div",{class:"erow"},grab,center,msg),
      h("div",{class:"erow"},h("div",{class:"grow"},h("div",{class:"row",style:"margin:0 0 8px"},h("label",{},"Game crop position (left to right)")),gs)),
      h("div",{class:"erow",style:"justify-content:flex-end"},h("button",{class:"btn ghost",onclick:close},"Cancel"),h("button",{class:"btn danger",style:"background:var(--a1)",onclick:save},"Save area"))));
  document.body.append(m);document.addEventListener("keydown",esc);paint();
  if(S.target&&S.target.trim())doGrab();else msg.textContent="Paste a stream link or pick a file first, then press Grab a frame. You can still drag the box now.";
}
function openCropEditor(){
  const box={x:+S.crop_x,y:+S.crop_y,w:+S.crop_w,h:+S.crop_h};let sourceAr=16/9;
  const img=h("img",{class:"cimg",draggable:false}),hdl=h("i",{class:"hdl"});
  const rc=h("div",{class:"crect"},h("span",{},"OUTPUT SEGMENT"),hdl);
  const stage=h("div",{class:"cstage"},img,rc);
  const targetAr=({"9:16":9/16,"16:9":16/9,"1:1":1,"4:5":4/5}[S.output_format]||9/16);
  const boxH=w=>w*sourceAr/targetAr;
  function fit(){
    box.h=boxH(box.w);
    if(box.h>100){box.h=100;box.w=box.h*targetAr/sourceAr}
    box.x=clamp(box.x,0,100-box.w);box.y=clamp(box.y,0,100-box.h);
  }
  function paint(){rc.style.cssText="left:"+box.x+"%;top:"+box.y+"%;width:"+box.w+"%;height:"+box.h+"%"}
  fit();
  const drag=(el,mode)=>el.addEventListener("pointerdown",e=>{
    e.preventDefault();e.stopPropagation();el.setPointerCapture(e.pointerId);
    const r=stage.getBoundingClientRect(),s0={x:box.x,y:box.y,w:box.w,px:e.clientX,py:e.clientY};
    const mv=ev=>{const dx=(ev.clientX-s0.px)/r.width*100,dy=(ev.clientY-s0.py)/r.height*100;
      if(mode==="move"){box.x=clamp(s0.x+dx,0,100-box.w);box.y=clamp(s0.y+dy,0,100-box.h)}
      else{let w=clamp(s0.w+dx,8,100-box.x);let hh=boxH(w);if(hh>100-box.y){hh=100-box.y;w=hh*targetAr/sourceAr}box.w=w;box.h=hh}
      paint()};
    const up=()=>{el.removeEventListener("pointermove",mv);el.removeEventListener("pointerup",up)};
    el.addEventListener("pointermove",mv);el.addEventListener("pointerup",up)});
  drag(rc,"move");drag(hdl,"resize");
  img.addEventListener("load",()=>{if(img.naturalWidth){sourceAr=img.naturalWidth/img.naturalHeight;stage.style.aspectRatio=img.naturalWidth+"/"+img.naturalHeight;fit();paint()}});
  const msg=h("span",{class:"hint",style:"margin:0"},"");
  const grab=h("button",{class:"btn ghost"},"Grab a frame");
  const center=h("button",{class:"btn ghost"},"Center segment");
  center.onclick=()=>{box.x=(100-box.w)/2;box.y=(100-box.h)/2;paint();msg.textContent="Source segment centered."};
  const doGrab=async()=>{grab.disabled=true;msg.textContent="Grabbing a frame...";try{const r=await api("/api/frame",{mode:S.mode,target:S.target});img.src=r.image;msg.textContent="Drag the fixed-aspect box to choose the exact source segment."}catch(e){msg.textContent=e.message}grab.disabled=false};
  grab.onclick=doGrab;
  const close=()=>{m.remove();document.removeEventListener("keydown",esc)};
  const esc=e=>{if(e.key==="Escape")close()};
  const save=()=>{S.crop_x=+box.x.toFixed(1);S.crop_y=+box.y.toFixed(1);S.crop_w=+box.w.toFixed(1);S.crop_h=+box.h.toFixed(1);scheduleSave();close();toast("Source segment saved","ok")};
  const m=h("div",{class:"overlay",onclick:e=>{if(e.target===m)close()}},
    h("div",{class:"editor"},h("h4",{},"Select the source segment"),
      h("div",{class:"sub"},"The frame stays in its original aspect ratio. The fixed box matches your selected output format: "+S.output_format+"."),
      stage,h("div",{class:"erow"},grab,center,msg),
      h("div",{class:"erow",style:"justify-content:flex-end"},h("button",{class:"btn ghost",onclick:close},"Cancel"),h("button",{class:"btn danger",style:"background:var(--a1)",onclick:save},"Save segment"))));
  document.body.append(m);document.addEventListener("keydown",esc);paint();
  if(S.target&&S.target.trim())doGrab();else msg.textContent="Paste a stream link or choose a file first, then press Grab a frame.";
}

/* ---------- tabs ---------- */
let wordsLoaded=false;
$$(".tab").forEach(t=>t.onclick=()=>{
  $$(".tab").forEach(x=>x.classList.toggle("on",x===t));
  ["clips","log","words"].forEach(n=>$("#p-"+n).hidden=(n!==t.dataset.t));
  if(t.dataset.t==="words"&&!wordsLoaded)loadWords();
  if(t.dataset.t==="log"){const l=$("#p-log");l.scrollTop=l.scrollHeight}
});
async function loadWords(){
  try{const r=await (await fetch("/api/words",{cache:"no-store"})).json();
   $("#words").value=r.text;wordsLoaded=true;
   $("#builtin-sum").textContent="Built-in hype words ("+r.words.length+" words, "+r.phrases.length+" phrases)";
   $("#chips").replaceChildren(...r.phrases.map(p=>h("span",{},p)),...r.words.map(w=>h("span",{},w)));
  }catch(e){toast("Couldn't load hype words","bad")}
}
async function saveWords(){
  try{const r=await api("/api/words",{text:$("#words").value});const m=$("#words-msg");m.textContent="Saved ("+r.entries+" custom entries)";m.classList.add("show");setTimeout(()=>m.classList.remove("show"),2200)}
  catch(e){toast(e.message,"bad")}
}
$("#btn-words-save").onclick=saveWords;
$("#words").addEventListener("keydown",e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==="s"){e.preventDefault();saveWords()}});

/* ---------- actions ---------- */
function loadProviderForm(){const cfg=(P.providers&&P.providers.zernio)||{};Z=Object.assign({},cfg);$("#pub-provider").value="zernio";$("#z-api").value="";$("#z-key-state").textContent=cfg.api_key_set?"Saved locally":"Not saved";$("#z-delay").value=cfg.schedule_minutes||0;$("#z-vis").value=cfg.visibility||"public";$("#z-auto").checked=!!cfg.auto_post}
$("#pub-provider").onchange=async e=>{activeProvider="zernio";accountsLoadedFor="";loadProviderForm();$("#z-account-picks").replaceChildren();if((P.providers.zernio||{}).api_key_set)loadPublishingAccounts().catch(err=>$("#z-msg").textContent=err.message)};loadProviderForm();
$("#z-key-state").textContent=Z.api_key_set?"Saved locally":"Not saved";
$("#z-key-state").style.color=Z.api_key_set?"var(--ok)":"var(--dim)";
$("#z-check").onclick=async()=>{
  const b=$("#z-check");b.disabled=true;
  try{
    const payload={provider:"zernio",api_key:$("#z-api").value,auto_post:$("#z-auto").checked,schedule_minutes:+$("#z-delay").value||0,visibility:$("#z-vis").value};
    if(accountsLoadedFor==="zernio")payload.account_ids=selectedZernioAccounts();
    const r=await api("/api/publishing",payload);
    Object.assign(P,r);Object.assign(Z,(r.providers||{})[activeProvider]||{});$("#z-api").value="";$("#z-key-state").textContent="Saved locally";$("#z-key-state").style.color="var(--ok)";await loadPublishingAccounts();toast(activeProvider+" settings saved locally","ok");
  }catch(e){$("#z-msg").textContent=e.message;$("#z-msg").classList.add("show");toast(e.message,"bad")}
  b.disabled=false;
};
if(Z.api_key_set)loadPublishingAccounts().catch(e=>{$("#z-msg").textContent=e.message});
$("#btn-folder").onclick=()=>api("/api/open_folder").then(()=>toast("Clips folder opened","ok")).catch(e=>toast(e.message,"bad"));
function normalizeLiveUrl(v){const t=v.trim().replace(/^"|"$/g,"");return /^(www\.)?(twitch\.tv|youtube\.com|youtu\.be)\//i.test(t)?"https://"+t:t}
$("#btn-start").onclick=async()=>{
  if(!S.target.trim()){toast(S.mode==="live"?"Paste a stream link first":"Choose a video file first","bad");$("#target").focus();return}
  if(S.mode==="live"){S.target=normalizeLiveUrl(S.target);$("#target").value=S.target;scheduleSave()}
  const b=$("#btn-start");b.disabled=true;
  try{await api("/api/start",S);await poll(true)}catch(e){toast(e.message,"bad")}
  b.disabled=false;
};
$("#btn-stop").onclick=()=>api("/api/stop",{force:false}).then(()=>poll(true)).catch(e=>toast(e.message,"bad"));
$("#btn-kill").onclick=()=>api("/api/stop",{force:true}).then(()=>poll(true)).catch(e=>toast(e.message,"bad"));
$("#btn-quit").onclick=async()=>{
  if(!(await confirmBox("Quit StreamSnip AI?","Any recording in progress will stop. Finished clips stay in the clips folder.","Quit")))return;
  appClosing=true;
  try{await api("/api/quit")}catch(e){}
  document.body.replaceChildren(h("div",{style:"height:100%;display:grid;place-items:center;text-align:center;color:#9a9fb5"},h("div",{},h("h2",{style:"color:#fff;margin-bottom:8px"},"StreamSnip AI has closed"),h("p",{},"You can close this window."))));
  setTimeout(()=>window.close(),400);
};

/* ---------- state polling ---------- */
const PHASES={idle:"Ready",waiting:"Waiting for the stream",recording:"Recording live",transcribing:"Listening for hype",rendering:"Rendering clips",stopping:"Wrapping up",working:"Working"};
let lastLog=0,fails=0,busy=false,order="",cards=new Map(),selectedClips=new Set(),lastPostDone=0,lastPostStarted=null;
let logPaused=false;
const fmtT=s=>{const m=Math.floor(s/60),h2=Math.floor(m/60);return h2?h2+":"+String(m%60).padStart(2,"0")+":"+String(s%60).padStart(2,"0"):m+":"+String(s%60).padStart(2,"0")};
function ago(t){const s=Math.max(0,Date.now()/1000-t);if(s<60)return"just now";if(s<3600)return Math.floor(s/60)+" min ago";if(s<86400)return Math.floor(s/3600)+" h ago";return Math.floor(s/86400)+" d ago"}
function addLogs(list){
  if(!list.length)return;const box=$("#log"),pl=$("#p-log"),stick=pl.scrollHeight-pl.scrollTop-pl.clientHeight<60;
  list.forEach(l=>{
    const cls=/error|failed|could not finish using/i.test(l.m)?"err":/clip ready|live - rec/i.test(l.m)?"okk":"";
    const row=h("div",{class:cls},h("span",{class:"t"},l.t),l.m);
    (l.file_lock&&l.file_lock.holders||[]).forEach(holder=>{
      const stop=h("button",{class:"btn ghost lock-stop",onclick:async e=>{
        const button=e.currentTarget;
        const detail=(holder.path?"\n"+holder.path:"")+"\nPID "+holder.pid+"\n\nWindows will close this process to release the clip. Save any work in it first.";
        if(!(await confirmBox("Stop "+holder.name+"?",detail,"Stop process")))return;
        button.disabled=true;
        try{const result=await api("/api/stop_file_holder",{name:l.file_lock.name,pid:holder.pid});button.textContent="Stop requested";toast(result.message,"ok");poll(true)}
        catch(error){button.disabled=false;toast(error.message,"bad")}
      }},"Stop "+holder.name+" (PID "+holder.pid+")");
      row.append(document.createElement("br"),stop);
    });
    box.append(row);
  });
  while(box.children.length>500)box.firstChild.remove();
  if(stick)pl.scrollTop=pl.scrollHeight;
}
$("#log-pause").onclick=()=>{
  logPaused=!logPaused;
  const button=$("#log-pause"), badge=$("#log-live");
  button.textContent=logPaused?"Resume":"Pause";
  badge.textContent=logPaused?"Paused":"Live";
  badge.classList.toggle("paused",logPaused);
};
$("#log-clear").onclick=()=>$("#log").replaceChildren();
function updateSelectedButton(){
  const count=selectedClips.size;
  const b=$("#btn-publish-selected");b.textContent="Publish selected ("+count+")";b.disabled=count===0;
  const d=$("#btn-delete-selected");d.textContent="Delete selected ("+count+")";d.disabled=count===0;
  const all=tabClipNames.length>0&&tabClipNames.every(name=>selectedClips.has(name));$("#btn-select-all").textContent=all?"Clear selection":"Select all";
}
async function selectAllClips(){
  try{
    const all=tabClipNames.length>0&&tabClipNames.every(name=>selectedClips.has(name));
    if(all){selectedClips.clear()}else{tabClipNames.forEach(name=>selectedClips.add(name))}
    cards.forEach(card=>{const pick=card.querySelector(".pick");if(pick)pick.checked=selectedClips.has(card.dataset.name)});
    updateSelectedButton();
  }catch(e){toast(e.message,"bad")}
}
function toggleClipSelection(name){
  if(selectedClips.has(name))selectedClips.delete(name);else selectedClips.add(name);
  const card=cards.get(name),pick=card&&card.querySelector(".pick");
  if(pick)pick.checked=selectedClips.has(name);
  updateSelectedButton();
  toast(selectedClips.has(name)?"Clip selected for publishing":"Clip removed from selection","ok");
}
function updatePosting(p){
  if(!p)return;
  if(p.started!==lastPostStarted){lastPostStarted=p.started;lastPostDone=0}
  const total=Number(p.total)||0,done=Number(p.completed)||0,active=!!p.active;
  const visible=active||total>0;
  $("#post-progress").hidden=!visible;
  const pct=total?Math.round(done/total*100):0;
  $("#post-fill").style.width=pct+"%";$("#post-value").textContent=pct+"%";
  $("#post-time").textContent=p.started?fmtT(Math.max(0,Math.floor(Date.now()/1000-p.started))):"0:00";
  $("#post-label").textContent=active?(p.current?"Uploading "+done+" of "+total+": "+p.current:"Preparing uploads...")
    :(p.errors?"Posting complete with "+p.errors+" failure(s).":"All uploads complete.");
  $("#btn-publish-all").disabled=active;updateSelectedButton();
  if(Number(p.done)>lastPostDone){toast("Upload complete: "+p.last_name,"ok");lastPostDone=Number(p.done)}
}
function updateRun(s){
  const hero=$("#hero");hero.dataset.phase=s.phase;
  hero.classList.toggle("live",s.running&&s.phase!=="waiting"||s.phase==="waiting"&&s.running);
  const ph=$("#ph");ph.replaceChildren(...(s.phase==="recording"?[h("span",{class:"rec-dot"})]:[]),PHASES[s.phase]||"Working");
  $("#st").textContent=s.status;$("#st").title=s.status;
  const showProgress=s.running&&(s.phase==="recording"||s.phase==="transcribing"||s.phase==="rendering");
  $("#progress-wrap").hidden=!showProgress;
  const progress=Math.max(0,Math.min(100,Number(s.progress)||0));
  $("#progress-fill").style.width=progress+"%";$("#progress-value").textContent=progress+"%";
  $("#progress-label").textContent=s.phase==="recording"?"Next clip batch":"";
  if(s.phase==="transcribing")$("#progress-label").textContent="Transcribing video";
  if(s.phase==="rendering")$("#progress-label").textContent="Rendering clips";
  updatePosting(s.posting);
  $("#s-time").textContent=fmtT(s.session.elapsed);$("#s-chunks").textContent=s.session.chunks;$("#s-clips").textContent=s.session.clips;
  $("#startbar").hidden=s.running;$("#stopbar").hidden=!s.running;
  const live=s.mode==="live";
  $("#btn-kill").hidden=!live;
  const stop=$("#btn-stop");stop.textContent=live?(s.stopping?"Wrapping up...":"Stop & finish clips"):"Cancel";stop.disabled=!!s.stopping&&live;
  $$(".left .scroll input,.left .scroll select,.left .scroll .seg button,.left .scroll .sw button").forEach(el=>{});
}
function openSocialPost(c){
  const titleText=c.title||((c.caption||"").split("\n")[0]||c.name);
  const descText=c.description||((c.caption||"").split("\n\n").slice(1).join("\n\n"));
  const platforms=[
    {id:"instagram",label:"Instagram",url:"https://www.instagram.com/create/select/"},
    {id:"tiktok",label:"TikTok",url:"https://www.tiktok.com/upload"},
    {id:"facebook",label:"Facebook",url:"https://www.facebook.com/reels/create/"},
    {id:"youtube",label:"YouTube",url:"https://www.youtube.com/upload"}
  ];
  const title=h("input",{class:"text",type:"text",maxlength:"100"});
  title.value=titleText;
  const description=h("textarea",{class:"text"});
  description.value=descText;
  const directChecks={},manualChecks={};
  const savedAccounts=Object.assign({},Z.accounts||{});
  if(!Object.keys(savedAccounts).length){
    if(Z.instagram_id)savedAccounts.instagram=Z.instagram_id;
    if(Z.youtube_id)savedAccounts.youtube=Z.youtube_id;
  }
  const platformLabels={twitter:"X / Twitter",instagram:"Instagram",facebook:"Facebook",linkedin:"LinkedIn",tiktok:"TikTok",youtube:"YouTube",pinterest:"Pinterest",reddit:"Reddit",bluesky:"Bluesky",threads:"Threads",googlebusiness:"Google Business"};
  const connected=Object.entries(savedAccounts);
  const choices=h("div",{class:"platform-picks"},...connected.map(([id,accountId])=>{
    const input=h("input",{type:"checkbox"});
    input.checked=true;
    directChecks[id]=input;
    return h("label",{class:"platform-pick"},input,platformLabels[id]||id);
  }));
  const manualChoices=h("div",{class:"platform-picks"},...platforms.map(platform=>{
    const input=h("input",{type:"checkbox"});input.checked=true;manualChecks[platform.id]=input;
    return h("label",{class:"platform-pick"},input,platform.label);
  }));
  const selectedAccounts=()=>Object.fromEntries(connected.filter(([id])=>directChecks[id]&&directChecks[id].checked));
  const close=()=>{overlay.remove();document.removeEventListener("keydown",onKey)};
  const onKey=e=>{if(e.key==="Escape")close()};
  const overlay=h("div",{class:"overlay",onclick:e=>{if(e.target===overlay)close()}});
  const copyValue=(value,label)=>{
    navigator.clipboard.writeText(value).then(
      ()=>toast(label+" copied. Paste it into the platform form.","ok"),
      ()=>toast("Clipboard access blocked; select and copy the text manually.","bad")
    );
  };
  const copyTitle=h("button",{class:"btn ghost",onclick:()=>copyValue(title.value.trim(),"Title")},"Copy title");
  const copyDescription=h("button",{class:"btn ghost",onclick:()=>copyValue(description.value.trim(),"Description")},"Copy description");
  const publish=h("button",{class:"btn primary",disabled:!connected.length||!Z.api_key_set,onclick:async()=>{
    const accounts=selectedAccounts();
    if(!Object.keys(accounts).length){toast("Select at least one connected Zernio account","bad");return}
    if(!title.value.trim()){toast("Add a post title first","bad");return}
    publish.disabled=true;publish.textContent="Queueing publish...";
    try{
      const result=await api("/api/publishing/publish-one",{name:c.name,title:title.value.trim(),description:description.value.trim(),account_ids:accounts});
      toast("Clip queued for direct publishing to "+Object.keys(accounts).join(", "), "ok");
      close();
    }catch(error){toast(error.message,"bad");publish.disabled=false;publish.textContent="Publish via Zernio"}
  }},"Publish via Zernio");
  const open=h("button",{class:"btn ghost",onclick:()=>{
    const selected=platforms.filter(p=>manualChecks[p.id]&&manualChecks[p.id].checked);
    if(!selected.length){toast("Select at least one platform","bad");return}
    if(!title.value.trim()){toast("Add a post title first","bad");return}
    let opened=0;
    for(const platform of selected){
      const tab=window.open(platform.url,"_blank");
      if(tab)opened++;
    }
    if(opened<selected.length)toast("Some tabs were blocked. Allow pop-ups for StreamSnip AI and try again.","bad");
    else toast("Opened "+opened+" platform page(s). Upload the clip, copy its title/description, and publish.","ok");
    close();
  }},"Open selected platforms");
  const markPosted=h("button",{class:"btn ghost",onclick:async()=>{try{await api("/api/posted/mark",{name:c.name,platform:"manual"});toast("Moved to Posted","ok");close();selectedClips.delete(c.name);order="";poll(true)}catch(e){toast(e.message,"bad")}}},"Mark as posted");
  const cancel=h("button",{class:"btn ghost",onclick:close},"Cancel");
  overlay.append(h("div",{class:"post-dialog"},
    h("h3",{},"Prepare social post"),
    h("p",{class:"sub"},"Clip: "+c.name+" · Select one or more destinations"),
    h("label",{},"Post title"),
    title,
    h("label",{},"Description and hashtags"),
    description,
    h("label",{},"Publish directly through your connected Zernio accounts"),
    choices,
    h("p",{class:"post-note"},connected.length?"Direct publishing uploads this clip and sends your edited caption to the selected connected accounts. Curse words do not block publishing; the clip uses whatever censoring was applied during rendering.":"Connect Zernio and select social accounts in Settings to publish directly."),
    h("label",{},"Manual upload fallback"),
    manualChoices,
    h("p",{class:"post-note"},"Manual upload opens the selected native upload pages. Download the clip, attach it yourself, and paste the copied title and description; platform security prevents silent form filling or local-file attachment."),
    h("div",{class:"prow",style:"justify-content:flex-end"},cancel,h("a",{class:"btn ghost",href:"/clips/"+encodeURIComponent(c.name),download:c.name},"Download clip"),copyTitle,copyDescription,markPosted,publish,open)
  ));
  document.body.append(overlay);
  document.addEventListener("keydown",onKey);
}
function clipCard(c){
  const v=h("video",{src:"/clips/"+encodeURIComponent(c.name)+"#t=0.1",loop:true,playsinline:true,preload:"metadata"});v.muted=true;
  const first=(c.caption||"").split("\n")[0]||c.name;
  const when=h("span",{class:"when","data-t":c.mtime},ago(c.mtime));
  const origin=c.creator_name?c.creator_name+" · "+(c.source==="vod"?"Recorded VOD":"Live"):"Local recording";
  const pick=h("input",{class:"pick",type:"checkbox",title:"Select this clip"});pick.checked=selectedClips.has(c.name);pick.onchange=()=>{pick.checked?selectedClips.add(c.name):selectedClips.delete(c.name);updateSelectedButton()};
  const copy=()=>{navigator.clipboard.writeText(c.caption||"").then(()=>toast("Caption copied","ok"),()=>toast("Couldn't copy","bad"))};
  const post=()=>openSocialPost(c);
  const del=async()=>{if(await confirmBox("Delete this clip?","This permanently removes the video and its caption file.","Delete")){try{await api("/api/delete",{name:c.name});toast("Clip deleted");poll(true)}catch(e){toast(e.message,"bad")}}};
  return h("div",{class:"clip","data-name":c.name,title:"Double-click this clip to select it for publishing",ondblclick:e=>{if(!e.target.closest("button,a,input"))toggleClipSelection(c.name)},onmouseenter:()=>{v.play().catch(()=>{})},onmouseleave:()=>v.pause()},
    h("div",{class:"thumb",onclick:()=>openClip(c)},v,h("div",{class:"pb"},ico("play",15))),
    h("div",{class:"cm"},h("div",{class:"cc",title:first},first),
      h("div",{class:"cr"},h("span",{},pick," ",when," · "+c.size_mb+" MB · "+origin),
        h("span",{class:"acts"},
          h("button",{class:"ib post",title:"Prepare a post for Instagram, TikTok, Facebook, or YouTube",onclick:post},"Post"),
          ...(!c.posted?[h("button",{class:"ib",title:"Move this clip to Posted after you publish it manually",onclick:async()=>{try{await api("/api/posted/mark",{name:c.name,platform:"manual"});selectedClips.delete(c.name);toast("Moved to Posted","ok");order="";poll(true)}catch(e){toast(e.message,"bad")}}},"Mark posted")]:[]),
          h("button",{class:"ib",title:"Copy caption + hashtags",onclick:copy},ico("copy",15)),
          h("a",{class:"ib",title:"Download",href:"/clips/"+encodeURIComponent(c.name),download:c.name},ico("download",15)),
          h("button",{class:"ib",title:"Show in folder",onclick:()=>api("/api/reveal",{name:c.name}).catch(e=>toast(e.message,"bad"))},ico("folder",15)),
          h("button",{class:"ib del",title:"Delete",onclick:del},ico("trash",15))))));
}
function renderClips(list,total=0){
  $("#btn-publish-all").hidden=clipTab==="posted";

  if(!list.length&&clipOffset>0){clipOffset=Math.max(0,clipOffset-CLIP_PAGE_SIZE);return}
  const sig=list.map(c=>c.name).join("|");
  $("#empty").hidden=list.length>0;$("#grid").hidden=list.length===0;
  const cnt=$("#cnt");cnt.hidden=!list.length;cnt.textContent=list.length;
  $("#empty h4").textContent=clipTab==="posted"?"No posted clips yet":"No clips yet";
  $("#empty p").textContent=clipTab==="posted"?"Clips appear here after a successful Zernio post or when you mark a manual upload as posted.":"Paste a Twitch or YouTube live link (or choose a video file) and hit Start. Finished clips appear here, ready to review and post.";
  $("#clip-page-label").textContent=list.length?`${clipOffset+1}-${clipOffset+list.length} of ${total} clips`:"0 clips";
  $("#btn-clips-newer").disabled=clipOffset===0;
  $("#btn-clips-older").disabled=clipOffset+list.length>=total;
  if(sig!==order){
    order=sig;const keep=new Set(list.map(c=>c.name));
    for(const [n,el] of cards){if(!keep.has(n)){el.remove();cards.delete(n)}}
    const frag=[];
    list.forEach(c=>{let el=cards.get(c.name);if(!el){el=clipCard(c);cards.set(c.name,el)}frag.push(el)});
    $("#grid").replaceChildren(...frag);
  }
  $$(".when").forEach(w=>w.textContent=ago(+w.dataset.t));
}
async function publishNames(names){
  if(!names.length){toast("Select at least one clip first","bad");return}
  const accounts=Object.assign({},Z.accounts||{});
  if(!Object.keys(accounts).length){if(Z.instagram_id)accounts.instagram=Z.instagram_id;if(Z.youtube_id)accounts.youtube=Z.youtube_id}
  try{const r=await api("/api/publishing/publish",{names,account_ids:accounts});toast("Started uploading "+r.queued+" clip(s) to "+Object.keys(accounts).join(", "),"ok");selectedClips.clear();$$('.pick').forEach(x=>x.checked=false);updateSelectedButton();}
  catch(e){toast(e.message,"bad")}
}
$("#btn-publish-selected").onclick=()=>publishNames([...selectedClips]);
$("#btn-select-all").onclick=selectAllClips;
$("#btn-view-clips").onclick=()=>{clipTab="clips";clipOffset=0;selectedClips.clear();order="";$("#btn-view-clips").classList.add("on");$("#btn-view-posted").classList.remove("on");poll(true)};
$("#btn-view-posted").onclick=()=>{clipTab="posted";clipOffset=0;selectedClips.clear();order="";$("#btn-view-posted").classList.add("on");$("#btn-view-clips").classList.remove("on");poll(true)};
$("#btn-delete-all").onclick=async()=>{const count=tabClipNames.length;if(!count){toast("Nothing to delete in this tab","bad");return}if(!(await confirmBox("Delete all "+(clipTab==="posted"?"posted":"unposted")+" clips?","This permanently removes all "+count+" video(s) and their caption files from this tab.","Delete all")))return;try{const r=await api("/api/delete_all",{clip_tab:clipTab});selectedClips.clear();toast("Deleted "+r.deleted+" clip(s)","ok");order="";poll(true)}catch(e){toast(e.message,"bad")}};
$("#btn-delete-selected").onclick=async()=>{
  const names=[...selectedClips];if(!names.length){toast("Select at least one clip first","bad");return}
  if(!(await confirmBox("Delete selected clips?","This permanently removes "+names.length+" video(s) and their caption files.","Delete")))return;
  try{const r=await api("/api/delete_many",{names});selectedClips.clear();toast("Deleted "+r.deleted+" clip(s)","ok");poll(true)}catch(e){toast(e.message,"bad")}
};
$("#btn-publish-all").onclick=async()=>{if(!(await confirmBox("Publish all clips?","This submits every unposted clip in the clips tab to the connected Zernio accounts. This may publish many videos.","Publish all")))return;const accounts=Object.assign({},Z.accounts||{});if(!Object.keys(accounts).length){if(Z.instagram_id)accounts.instagram=Z.instagram_id;if(Z.youtube_id)accounts.youtube=Z.youtube_id}try{const r=await api("/api/publishing/publish",{all:true,account_ids:accounts});toast("Started uploading "+r.queued+" clip(s) to "+Object.keys(accounts).join(", "),"ok")}catch(e){toast(e.message,"bad")}};
$("#btn-clips-newer").onclick=()=>{clipOffset=Math.max(0,clipOffset-CLIP_PAGE_SIZE);poll()};
$("#btn-clips-older").onclick=()=>{clipOffset+=CLIP_PAGE_SIZE;poll()};
function openClip(c){
  const v=h("video",{src:"/clips/"+encodeURIComponent(c.name),controls:true,autoplay:true,loop:true,playsinline:true});
  const close=()=>{v.pause();m.remove();document.removeEventListener("keydown",esc)};
  const esc=e=>{if(e.key==="Escape")close()};
  const m=h("div",{class:"overlay",onclick:e=>{if(e.target===m)close()}},
    h("div",{class:"player"},v,
      h("div",{class:"pside"},h("h4",{},"Caption & hashtags"),h("pre",{class:"pcap"},c.caption||"(none)"),
        h("div",{class:"prow"},
          h("button",{class:"btn ghost",onclick:()=>navigator.clipboard.writeText(c.caption||"").then(()=>toast("Caption copied","ok"),()=>toast("Couldn't copy","bad"))},ico("copy",15),"Copy caption"),
          h("a",{class:"btn ghost",href:"/clips/"+encodeURIComponent(c.name),download:c.name},ico("download",15),"Download")),
        h("button",{class:"btn ghost",onclick:close},"Close"))));
  document.body.append(m);document.addEventListener("keydown",esc);
}
async function poll(){
  if(busy)return;busy=true;
  try{
    const r=await fetch("/api/state?since="+lastLog+"&clip_offset="+clipOffset+"&clip_tab="+clipTab,{cache:"no-store"});const s=await r.json();
    const namesResponse=await fetch("/api/clips/names?tab="+clipTab,{cache:"no-store"});const namesData=await namesResponse.json();tabClipNames=namesData.names||[];updateSelectedButton();
    $("#btn-view-posted").textContent="Posted ("+(s.posted_total||0)+")";
    fails=0;$("#offline").hidden=true;
    if(!logPaused){lastLog=s.last_id;addLogs(s.logs)}updateRun(s);renderClips(s.clips,s.clip_total);
  }catch(e){if(++fails>=3)$("#offline").hidden=false}
  busy=false;
}
setInterval(poll,900);poll();
refreshCreators();setInterval(refreshCreators,2500);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
