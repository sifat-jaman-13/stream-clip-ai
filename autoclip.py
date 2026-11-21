r"""StreamSnip AI — a local-first Twitch, YouTube, and VOD clipper.

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
import os, re, sys, glob, json, time, queue, shutil, secrets, threading, subprocess, pathlib, platform, base64, uuid
import math
import urllib.request
from importlib import metadata as importlib_metadata
import http.server, urllib.parse, webbrowser
import numpy as np
from ai_highlights import (AIAnalysisCancelled, AIProviderError, DEFAULT_GEMINI_MODEL,
                           DEFAULT_HUGGINGFACE_MODEL, RETIRED_GEMINI_MODELS,
                           ollama_models, select_moments, test_provider)
from post_metadata import generate_social_copy
APP_VERSION = "2.0.8"
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
    return {"current": APP_VERSION, "latest": latest, "update": latest_key > current_key,
            "url": data.get("html_url") or APP_RELEASES_URL,
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
    "clips_per_chunk": 2, "chunk_min": 3, "pre": 20, "post": 15, "min_score": 70,
    "model": "distil-large-v3", "compute_device": "gpu",
    "color": "Yellow", "position": "Lower third", "caption_size": 100, "words_per_line": 3, "font": "Impact",
    "subtitle_custom": False, "subtitle_mode": "Karaoke", "subtitle_style": "Classic",
    "subtitle_font_size": 100, "subtitle_text_color": "#FFFFFF", "subtitle_stroke_color": "#000000",
    "subtitle_position": "Bottom", "subtitle_alignment": "Center", "subtitle_nudge": 0,
    "streamer_tag": "", "show_tag_video": True,
    "cta_enabled": True, "cta_text": "Subscribe for more clips", "cta_voice_enabled": True,
    "capture_bitrate_kbps": 6000,
    "layout": "Facecam + game (Twitch)", "output_format": "9:16", "crop_x": 34.2, "crop_y": 0.0,
    "crop_w": 31.6, "crop_h": 100.0, "delete_rec": False,
    "cam_x": 70, "cam_y": 4, "cam_w": 29, "cam_h": 37, "game_x": 50,
}
# ASS colours are BGR
CAPTION_COLORS = {"Yellow": "00FFFF", "Green": "00FF00", "Cyan": "FFFF00", "Orange": "0080FF", "Pink": "FF40FF"}
CAPTION_POS = {"Lower third": 520, "Middle": 800, "Low": 380}      # MarginV (px from bottom of 1920)
LAYOUTS = ["Facecam + game (Twitch)", "Blur background", "Fill (crop center)", "Selected crop"]
OUTPUT_FORMATS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
MODELS = ["distil-large-v3", "large-v3-turbo", "medium", "large-v3", "small", "base"]
STREAM_QUALITY = "1080p60,1080p,720p60,720p,best"
SUBTITLE_MODES = ["Karaoke", "Classic"]
SUBTITLE_STYLES = ["Classic", "Hormozi", "Neon", "MrBeast", "Minimal", "Fire"]
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
    num("clips_per_chunk", 0, 10, int); num("chunk_min", 1, 30, int)
    num("pre", 3, 90, int); num("post", 3, 90, int)
    num("capture_bitrate_kbps", 6000, 50000, int)
    num("min_score", 0, 100, float); num("caption_size", 60, 150, int); num("words_per_line", 1, 4, int)
    num("subtitle_font_size", 60, 180, int); num("subtitle_nudge", -400, 400, int)
    c["min_score"] = round(c["min_score"], 1)
    num("cam_x", 0, 90, float); num("cam_y", 0, 90, float); num("cam_w", 10, 100, float); num("cam_h", 10, 100, float)
    num("game_x", 0, 100, float)
    num("crop_x", 0, 90, float); num("crop_y", 0, 90, float); num("crop_w", 10, 100, float); num("crop_h", 10, 100, float)
    c["cam_w"] = min(c["cam_w"], 100 - c["cam_x"]); c["cam_h"] = min(c["cam_h"], 100 - c["cam_y"])
    c["crop_w"] = min(c["crop_w"], 100 - c["crop_x"]); c["crop_h"] = min(c["crop_h"], 100 - c["crop_y"])
    for k in ("cam_x", "cam_y", "cam_w", "cam_h", "game_x", "crop_x", "crop_y", "crop_w", "crop_h"): c[k] = round(c[k], 1)
    if raw.get("mode") in ("live", "file"): c["mode"] = raw["mode"]
    c["target"] = str(raw.get("target", "")).strip()[:1000]
    # Hardware is automatic: CUDA whenever a supported NVIDIA GPU is visible.
    # Keep the setting key for compatibility with existing settings files.
    c["compute_device"] = "gpu"
    for k, opts in (("color", CAPTION_COLORS), ("position", CAPTION_POS), ("layout", LAYOUTS),
                    ("output_format", OUTPUT_FORMATS), ("model", MODELS)):
        if raw.get(k) in opts: c[k] = raw[k]
    for k, opts in (("subtitle_mode", SUBTITLE_MODES), ("subtitle_style", SUBTITLE_STYLES),
                    ("subtitle_position", SUBTITLE_POSITIONS), ("subtitle_alignment", SUBTITLE_ALIGNMENTS)):
        if raw.get(k) in opts: c[k] = raw[k]
    c["subtitle_custom"] = bool(raw.get("subtitle_custom", False))
    for k, fallback in (("subtitle_text_color", "#FFFFFF"), ("subtitle_stroke_color", "#000000")):
        v = str(raw.get(k, fallback)).strip().upper()
        c[k] = v if re.fullmatch(r"#[0-9A-F]{6}", v) else fallback
    tag = re.sub(r"[\r\n{}\\]", "", str(raw.get("streamer_tag", c["streamer_tag"]))).strip()[:80]
    c["streamer_tag"] = tag
    c["show_tag_video"] = bool(raw.get("show_tag_video", c["show_tag_video"]))
    c["cta_enabled"] = bool(raw.get("cta_enabled", c["cta_enabled"]))
    c["cta_voice_enabled"] = bool(raw.get("cta_voice_enabled", c["cta_voice_enabled"]))
    cta = re.sub(r"[\r\n{}\\]", "", str(raw.get("cta_text", c["cta_text"]))).strip()[:100]
    c["cta_text"] = cta or DEFAULTS["cta_text"]
    f = str(raw.get("font", c["font"])).strip()
    if re.fullmatch(r"[A-Za-z0-9 \-]{1,40}", f): c["font"] = f
    c["delete_rec"] = bool(raw.get("delete_rec", False))
    for k in ("rec_dir", "out_dir"):
        value = str(raw.get(k, "") or "").strip()
        # Keep user-selected paths portable across Windows installs while avoiding
        # control characters or excessively large values in settings.json.
        c[k] = value[:1000] if "\x00" not in value else ""
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
    """Use an explicit credit when supplied; otherwise infer common channel handles."""
    override = re.sub(r"[\r\n{}\\]", "", str(cfg.get("streamer_tag", "")).strip())[:80]
    if override:
        return override
    target = str(cfg.get("target", "")).strip().strip('"')
    m = re.search(r"(?:twitch\.tv)/([^/?#]+)", target, re.I)
    if m and m.group(1).lower() not in {"videos", "directory", "search"}:
        return "@" + re.sub(r"[\r\n{}\\]", "", m.group(1))
    m = re.search(r"(?:youtube\.com)/@([^/?#]+)", target, re.I)
    if m:
        return "@" + re.sub(r"[\r\n{}\\]", "", m.group(1))
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
    """Return Scheduler-compatible post copy; provenance stays in the local manifest only."""
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

def load_ai_settings():
    defaults = {"provider": "hooks", "ollama_url": os.environ.get("STREAMSNIP_OLLAMA_URL", "http://127.0.0.1:11434"), "ollama_model": "",
                "gemini_model": DEFAULT_GEMINI_MODEL, "huggingface_model": DEFAULT_HUGGINGFACE_MODEL,
                "gemini_api_key": "", "huggingface_token": os.environ.get("HF_TOKEN", os.environ.get("HUGGING_FACE_HUB_TOKEN", "")),
                "metadata_copy_enabled": "true"}
    try:
        data = json.loads(AI_SETTINGS_FILE.read_text(encoding="utf-8"))
        if isinstance(data, dict): defaults.update({k: str(v) for k, v in data.items() if k in defaults and v is not None})
    except Exception:
        pass
    if defaults["provider"] not in {"hooks", "ollama", "gemini", "huggingface"}:
        defaults["provider"] = "hooks"
    if defaults["gemini_model"] in RETIRED_GEMINI_MODELS:
        defaults["gemini_model"] = DEFAULT_GEMINI_MODEL
    if defaults["huggingface_model"] == "Qwen/Qwen2.5-7B-Instruct-1M":
        defaults["huggingface_model"] = DEFAULT_HUGGINGFACE_MODEL
    return defaults

def public_ai_settings():
    cfg = load_ai_settings()
    return {"provider": cfg["provider"], "ollama_url": cfg["ollama_url"],
            "ollama_model": cfg["ollama_model"], "gemini_model": cfg["gemini_model"],
            "huggingface_model": cfg["huggingface_model"],
            "gemini_key_set": bool(cfg["gemini_api_key"]),
            "huggingface_token_set": bool(cfg["huggingface_token"]),
            "metadata_copy_enabled": str(cfg.get("metadata_copy_enabled", "true")).strip().lower() not in {"0", "false", "no", "off"}}

def save_ai_settings(body):
    cfg = load_ai_settings()
    previous_huggingface_token = str(cfg.get("huggingface_token", "")).strip()
    provider = str(body.get("provider", cfg["provider"]))
    if provider not in {"hooks", "ollama", "gemini", "huggingface"}:
        raise ValueError("Unknown AI highlight provider.")
    cfg["provider"] = provider
    if "metadata_copy_enabled" in body:
        cfg["metadata_copy_enabled"] = "true" if bool(body["metadata_copy_enabled"]) else "false"
    for key in ("ollama_url", "ollama_model", "gemini_model", "huggingface_model"):
        if key in body:
            cfg[key] = str(body[key]).strip()[:500]
    for key in ("gemini_api_key", "huggingface_token"):
        if body.get(key): cfg[key] = str(body[key]).strip()[:1000]
    if body.get("clear_gemini_key"): cfg["gemini_api_key"] = ""
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
    if provider not in {"hooks", "ollama", "gemini", "huggingface"}:
        raise ValueError("Unknown AI highlight provider.")
    cfg["provider"] = provider
    for key in ("ollama_url", "ollama_model", "gemini_model", "huggingface_model"):
        if key in body:
            cfg[key] = str(body[key]).strip()[:500]
    for key in ("gemini_api_key", "huggingface_token"):
        if body.get(key):
            cfg[key] = str(body[key]).strip()[:1000]
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

def make_cta_voice(path, text):
    """Create a soft, slower female CTA with Windows' built-in SAPI voice when available."""
    if os.name != "nt":
        return False
    powershell = shutil.which("powershell.exe") or shutil.which("powershell")
    if not powershell:
        return False
    enc = lambda s: base64.b64encode(str(s).encode("utf-8")).decode("ascii")
    script = (
        "Add-Type -AssemblyName System.Speech; "
        "$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + enc(path) + "')); "
        "$t=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + enc(text) + "')); "
        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$v=$s.GetInstalledVoices() | Where-Object {$_.VoiceInfo.Gender.ToString() -eq 'Female'} | Select-Object -First 1; "
        "if($v){$s.SelectVoice($v.VoiceInfo.Name)}; $s.Rate=-3; $s.Volume=72; "
        "$s.SetOutputToWaveFile($p); $s.Speak($t); $s.Dispose()"
    )
    try:
        r = run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand",
                 base64.b64encode(script.encode("utf-16le")).decode("ascii")],
                capture_output=True, text=True, timeout=30)
        return r.returncode == 0 and pathlib.Path(path).is_file() and pathlib.Path(path).stat().st_size > 1000
    except Exception:
        return False

def has_audio_stream(path):
    ffmpeg = pathlib.Path(ffmpeg_exe())
    candidates = [ffmpeg.with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")]
    found = shutil.which("ffprobe")
    if found: candidates.append(pathlib.Path(found))
    probe = next((str(p) for p in candidates if p.is_file()), None)
    if not probe:
        return None
    try:
        r = run([probe, "-v", "error", "-select_streams", "a:0",
                 "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
                capture_output=True, text=True, timeout=15)
        return bool((r.stdout or "").strip()) if r.returncode == 0 else None
    except Exception:
        return None

def make_ass(words, start, end, path, cfg):
    ws = []
    for s, e, w in words:
        if e > start and s < end:
            cw = clean_word(w)
            if cw:
                ws.append((max(0.0, s - start), min(end - start, e - start), cw))
    custom = bool(cfg.get("subtitle_custom"))
    out_w, out_h = output_size(cfg)
    preset = SUBTITLE_PRESETS.get(cfg.get("subtitle_style", "Classic"), SUBTITLE_PRESETS["Classic"])
    stroke = _ass_color(cfg.get("subtitle_stroke_color"), "#000000") if custom else "000000"
    size = int(cfg.get("subtitle_font_size", cfg["caption_size"])) if custom else int(cfg["caption_size"])
    font = preset["font"] if custom else cfg["font"]
    if custom:
        pos = cfg.get("subtitle_position", "Bottom")
        align = cfg.get("subtitle_alignment", "Center")
        alignment = {"Top": 7 if align == "Left" else 8, "Center": 4 if align == "Left" else 5,
                     "Bottom": 1 if align == "Left" else 2}[pos]
        nudge = round(int(cfg.get("subtitle_nudge", 0)) * out_h / 1920)
        mv = max(0, round(70 * out_h / 1920) + nudge) if pos != "Center" else nudge
        outline, shadow = preset["outline"], preset["shadow"]
    else:
        alignment, mv, outline, shadow = 2, round(CAPTION_POS.get(cfg["position"], 520) * out_h / 1920), 9, 4
    base_col = _ass_color(cfg.get("subtitle_text_color"), "#FFFFFF") if custom else "FFFFFF"
    highlight_col = CAPTION_COLORS.get(cfg["color"], "00FFFF")
    header = (
        f"[Script Info]\nScriptType: v4.00+\nPlayResX: {out_w}\nPlayResY: {out_h}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,"
        "Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{font},{size},&H00{base_col},&H00{base_col},&H00{stroke},&H64000000,0,0,0,0,100,100,2,0,1,{outline},{shadow},{alignment},{round(70 * out_w / 1080)},{round(70 * out_w / 1080)},{mv},1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    pop = (r"{\1c&H" + highlight_col + r"&\fscx120\fscy120\t(0,90,\fscx100\fscy100)}"
           if (not custom or (preset["pop"] and cfg.get("subtitle_mode", "Karaoke") == "Karaoke"))
           else r"{\1c&H" + highlight_col + r"&}")
    max_chars = max(8, int(1750 / size))
    lines = []
    groups = group_words(ws, int(cfg["words_per_line"]), max_chars)
    for gi, grp in enumerate(groups):
        for j, (s, e, _) in enumerate(grp):
            if j + 1 < len(grp):
                end_t = grp[j + 1][0]
            else:                                   # last word: hold briefly, but never overlap the next line
                end_t = e + 0.2
                if gi + 1 < len(groups):
                    end_t = min(end_t, groups[gi + 1][0][0])
            text = " ".join((pop + w + r"{\r}") if k == j else w for k, (_, _, w) in enumerate(grp))
            lines.append(f"Dialogue: 0,{ts(s)},{ts(max(end_t, s + 0.08))},Default,,0,0,0,,{text}")
    tag = streamer_credit(cfg)
    if cfg.get("show_tag_video") and tag:
        tag_size = round(38 * out_w / 1080)
        tag_margin = round(70 * out_w / 1080)
        lines.append(f"Dialogue: 0,{ts(0)},{ts(max(0.08, end - start))},Default,,0,0,0,,"
                     f"{{\\an7\\fs{tag_size}\\bord3\\1c&H00FFFFFF&\\3c&H000000&\\pos({tag_margin},{tag_margin})}}Clip from {tag}")
    if cfg.get("cta_enabled", True) and cfg.get("cta_text"):
        cta_start = max(0, end - start - 2.8)
        cta_size = round(48 * out_w / 1080)
        lines.append(f"Dialogue: 0,{ts(cta_start)},{ts(max(cta_start + 0.08, end - start))},Default,,0,0,0,,"
                     f"{{\\an8\\fs{cta_size}\\bord4\\1c&H00FFFFFF&\\3c&H000000&}}{cfg['cta_text']}")
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
    exe = shutil.which("streamlink")
    if exe:
        return exe
    # venv case: the Scripts/bin folder may not be on PATH (or sys.executable points at the base Python)
    dirs = [pathlib.Path(sys.prefix) / "Scripts", pathlib.Path(sys.prefix) / "bin",
            pathlib.Path(sys.executable).parent, pathlib.Path(sys.executable).parent / "Scripts"]
    for d in dirs:
        for n in ("streamlink.exe", "streamlink"):
            if (d / n).is_file():
                return str(d / n)
    return None

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
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([p for p in sys.path if p] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    return env

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

class Engine:
    def __init__(self, cfg, emit):
        self.cfg, self.emit = cfg, emit
        self.stop_flag = self.abort = False
        self.ai_cancel = threading.Event()
        self.procs = []
        self.seg_seconds = int(cfg["chunk_min"]) * 60

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
        ai_cfg = load_ai_settings()
        provider = ai_cfg["provider"]
        if provider == "hooks":
            self.log("Highlight scoring: built-in/custom hook words + audio energy and speech rate (local, offline; no AI model).")
        if provider != "hooks":
            # An AI provider is an explicit editorial choice: never replace an
            # empty/failed AI decision with unrelated audio or hook-word peaks.
            # This prevents ordinary moments from becoming clips when Gemini or
            # Ollama says the transcript has no viral payoff.
            self.ai_strict_no_clip = True
            mode = {"ollama": "Ollama local model", "gemini": "Gemini cloud model", "huggingface": "Hugging Face hosted model"}.get(provider, provider.title())
            self.log(f"Highlight analysis starting with {mode}; analyzing timestamped transcript windows.")
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
        out_w, out_h = output_size(cfg)
        make_ass(words, start, end, OUT / f"{name}.ass", cfg)
        if cfg["layout"].startswith("Facecam") and cfg.get("output_format", "9:16") == "9:16":
            # Twitch-style portrait: facecam on the top 40% (1080x768), game on the bottom 60% (1080x1152)
            cx, cy, cw, ch = (float(cfg[k]) / 100 for k in ("cam_x", "cam_y", "cam_w", "cam_h"))
            gx = float(cfg["game_x"]) / 100
            vf = ("[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
                  f"[a]crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f},"
                  "scale=1080:768:force_original_aspect_ratio=increase,crop=1080:768[cam];"
                  f"[b]crop=min(iw\\,ih*1080/1152):ih:(iw-min(iw\\,ih*1080/1152))*{gx:.4f}:0,"
                  "scale=1080:1152[game];"
                  f"[cam][game]vstack=inputs=2,setsar=1,subtitles={name}.ass[v]")
        elif cfg["layout"].startswith("Blur"):
            vf = ("[0:v]setpts=PTS-STARTPTS,split=2[a][b];"
                  f"[a]scale={round(out_w/4)}:{round(out_h/4)}:force_original_aspect_ratio=increase,crop={out_w//4}:{out_h//4},boxblur=8:2,scale={out_w}:{out_h}[bg];"
                  f"[b]scale={out_w}:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                  f"setsar=1,subtitles={name}.ass[v]")
        else:
            if cfg["layout"].startswith("Selected"):
                cx, cy, cw, ch = (float(cfg[k]) / 100 for k in ("crop_x", "crop_y", "crop_w", "crop_h"))
                crop = f"crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f},"
            else:
                crop = ""
            vf = (f"[0:v]setpts=PTS-STARTPTS,{crop}scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},"
                  f"setsar=1,subtitles={name}.ass[v]")
        enc = (["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21", "-b:v", "0"] if has_nvenc()
               else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
        tmp = f"{name}.tmp.mp4"
        cmd = [ffmpeg_exe(), "-y", "-v", "error", "-fflags", "+genpts", "-ss", f"{start:.2f}", "-accurate_seek",
               "-t", f"{end - start:.2f}", "-i", str(pathlib.Path(src).resolve()),
               "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
               *enc, "-pix_fmt", "yuv420p", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,asetpts=PTS-STARTPTS",
               "-c:a", "aac", "-b:a", "160k", "-r", "30", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart", tmp]
        r = run(cmd, cwd=OUT, capture_output=True, text=True)
        (OUT / f"{name}.ass").unlink(missing_ok=True)
        if r.returncode != 0:
            (OUT / tmp).unlink(missing_ok=True)
            raise RuntimeError((r.stderr or "ffmpeg failed").strip()[-400:])
        if cfg.get("cta_enabled", True) and cfg.get("cta_voice_enabled", True) and os.name == "nt":
            voice = OUT / f"{name}.cta.wav"
            if make_cta_voice(voice, cfg.get("cta_text", "Subscribe for more clips")):
                mixed = OUT / f"{name}.audio.tmp.mp4"
                delay_ms = max(0, int((end - start - 2.8) * 1000))
                audio_present = has_audio_stream(OUT / tmp)
                if audio_present is None:
                    self.log("FFprobe unavailable; keeping the original clip audio unchanged.")
                    voice.unlink(missing_ok=True)
                elif audio_present:
                    af = f"[1:a]adelay={delay_ms}:all=1[cta];[0:a][cta]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]"
                else:
                    af = f"[1:a]adelay={delay_ms}:all=1[a]"
                if audio_present is not None:
                    mix_cmd = [ffmpeg_exe(), "-y", "-v", "error", "-i", str(OUT / tmp), "-i", str(voice),
                               "-filter_complex", af, "-map", "0:v:0", "-map", "[a]",
                               "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", mixed]
                    mr = run(mix_cmd, cwd=OUT, capture_output=True, text=True)
                    if mr.returncode == 0 and mixed.is_file():
                        self.replace_output(mixed, OUT / tmp)
                    else:
                        self.log("CTA voice unavailable for this clip; keeping the original audio.")
                        mixed.unlink(missing_ok=True)
            else:
                self.log("Soft CTA voice unavailable; the on-screen CTA was kept.")
            voice.unlink(missing_ok=True)
        transcript = " ".join(
            str(word).strip() for word_start, _word_end, word in words
            if start <= word_start <= end
        )
        transcript = re.sub(r"\s+", " ", transcript).strip()
        tag = streamer_credit(self.cfg)
        post_copy = None
        ai_cfg = {}
        try:
            ai_cfg = load_ai_settings()
            copy_enabled = str(ai_cfg.get("metadata_copy_enabled", "true")).strip().lower() not in {
                "0", "false", "no", "off"
            }
            if copy_enabled and transcript and ai_cfg.get("provider") != "hooks":
                post_copy = generate_social_copy(transcript, tag, ai_cfg, log=self.log)
            elif copy_enabled and ai_cfg.get("provider") == "hooks":
                self.log("AI post copy is enabled but Hook words is selected. Choose Gemini, Ollama, or Hugging Face in AI settings; transcript fallback will be used for this clip.")
        except Exception as exc:
            provider = str(ai_cfg.get("provider", "unknown")).lower()
            self.log(
                f"{provider.title()} post copy unavailable or failed validation; "
                f"using transcript fallback: {str(exc)[:220]}"
            )
        final_video = OUT / f"{name}.mp4"
        self.replace_output(OUT / tmp, final_video)
        try:
            write_clip_metadata_files(
                OUT, final_video.name, pathlib.Path(src).name, start, end,
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
        pth = pathlib.Path(path)
        stem = re.sub(r"[^A-Za-z0-9_-]", "_", pth.stem)[:40] or "stream"
        self.status(f"Transcribing {pth.name}...", "transcribing", 0)
        self.log(f"Processing {pth.name}")
        words = self.transcribe(path)
        self.check()
        if words:
            transcript = " ".join(clean_word(word) for _start, _end, word in words).strip()
            if len(transcript) > 6000:
                transcript = transcript[:5997].rstrip() + "..."
            self.log(f"Transcript words ({len(words)}): {transcript}")
        else:
            self.log("Transcript words (0): no speech words detected.")
        self.status("Finding the hype moments...", "transcribing", 100)
        peaks, dur = self.find_peaks(path, words)
        self.log(f"Heard {len(words)} words in {dur}s of video. Best moment score {getattr(self, 'best_score', 0):.1f} "
                 f"(clips need {self.cfg['min_score']}).")
        if not words:
            self.log("WARNING: no speech was transcribed - check the speech model / GPU messages above.")
        if not peaks:
            self.log("Chunk too short or silent - nothing to clip.")
            if pth.parent == REC:
                try:
                    pth.unlink()
                    self.log(f"Deleted {pth.name}: processing produced no clips.")
                except OSError as exc:
                    self.log(f"Could not delete {pth.name}: {exc}")
        stamp = time.strftime("%H%M%S")
        for i, (p, sc) in enumerate(peaks, 1):
            self.check()
            start, end = clip_bounds(p, dur, self.cfg["pre"], self.cfg["post"], words)
            base_name = f"{stem}_{stamp}_clip{i}"
            name = base_name
            suffix = 2
            while (OUT / f"{name}.mp4").exists() or (OUT / f"{name}.tmp.mp4").exists():
                name = f"{base_name}_{suffix}"
                suffix += 1
            self.status(f"Rendering clip {i} of {len(peaks)} (hype score {sc:.1f})...", "rendering",
                        int((i - 1) / max(1, len(peaks)) * 100))
            try:
                self.render(path, start, end, words, name)
                self.status(f"Rendered clip {i} of {len(peaks)}.", "rendering",
                            int(i / max(1, len(peaks)) * 100))
            except FileBusyError as e:
                self.emit("file_lock", e.details)
            except Exception as e:
                self.log(f"Render error: {e}")
        self.emit("chunk", "")
        if self.cfg["delete_rec"] and pth.parent == REC:
            try: pth.unlink()
            except Exception: pass

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
        ensure_runtime_dirs()
        run_id = time.strftime("%m%d_%H%M%S")
        pattern = str(REC / f"seg_{run_id}_%05d.ts")
        slog_path = REC / f"streamlink_{run_id}.log"
        try:
            slog = open(slog_path, "wb")
        except FileNotFoundError:
            # Handle a race where the folder vanished between mkdir and open.
            ensure_runtime_dirs()
            slog = open(slog_path, "wb")
        try:
            sl = popen(streamlink_cmd() + ["--stdout", url, STREAM_QUALITY], stdout=subprocess.PIPE, stderr=slog, env=streamlink_env())
        except Exception:
            slog.close()
            raise
        bitrate = int(self.cfg.get("capture_bitrate_kbps", 6000))
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
                segs = sorted(glob.glob(str(REC / f"seg_{run_id}_*.ts")))
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
            for fpath in glob.glob(str(REC / f"streamlink_{run_id}.log")):
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
QUIT = threading.Event()
_WINDOW_CLOSE_LOCK = threading.RLock()
_WINDOW_CLOSE_TIMER = None
_WINDOW_LEASES = set()

def cancel_window_close_shutdown():
    global _WINDOW_CLOSE_TIMER
    with _WINDOW_CLOSE_LOCK:
        timer, _WINDOW_CLOSE_TIMER = _WINDOW_CLOSE_TIMER, None
    if timer:
        timer.cancel()

def schedule_window_close_shutdown(delay=3.0):
    """Quit after an app-window close, unless a quick page reload reconnects."""
    global _WINDOW_CLOSE_TIMER
    cancel_window_close_shutdown()
    def close_if_still_gone():
        global _WINDOW_CLOSE_TIMER
        with _WINDOW_CLOSE_LOCK:
            if _WINDOW_LEASES:
                _WINDOW_CLOSE_TIMER = None
                return
            _WINDOW_CLOSE_TIMER = None
        QUIT.set()
    timer = threading.Timer(delay, close_if_still_gone)
    timer.daemon = True
    with _WINDOW_CLOSE_LOCK:
        if _WINDOW_LEASES:
            return
        _WINDOW_CLOSE_TIMER = timer
    timer.start()

def begin_window_lease():
    lease = object()
    with _WINDOW_CLOSE_LOCK:
        _WINDOW_LEASES.add(lease)
    cancel_window_close_shutdown()
    return lease

def end_window_lease(lease):
    with _WINDOW_CLOSE_LOCK:
        _WINDOW_LEASES.discard(lease)
        empty = not _WINDOW_LEASES
    if empty and not QUIT.is_set():
        schedule_window_close_shutdown()

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
        if STORAGE_PATH_WARNING:
            save_settings(self.settings)
            self.push(STORAGE_PATH_WARNING)

    def _config_for(self, provider=None):
        return self.publishing.get("zernio", {})

    def _make_publisher(self, provider=None, enabled=None):
        provider = "zernio"
        if enabled is None:
            enabled = bool(self._config_for().get("auto_post", False))
        cfg = dict(self._config_for(), enabled=enabled)
        return ZernioPublisher(self.push, cfg) if ZERNIO_AVAILABLE else None

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

    def state(self, since, clip_offset=0):
        clips = list_clips(offset=clip_offset)
        clip_total = len(_clip_index())
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

    def zernio_status(self):
        cfg = self._config_for("zernio")
        return dict(self._provider_status("zernio"), auto_post=bool(cfg.get("auto_post")),
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

    def publish_clips(self, names):
        provider = "zernio"
        cfg = self._config_for()
        if not cfg.get("api_key"): raise ValueError(f"Save and verify a {provider.title()} API key first.")
        if not any(cfg.get(key) for key in ("instagram_id", "youtube_id")):
            raise ValueError("Select at least one connected channel.")
        valid = [n for n in names if CLIP_RE.match(str(n)) and (OUT / str(n)).is_file()]
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
                        delay = int(cfg.get("schedule_minutes", 0) or 0) * (index + 1)
                        with self.lock: self.posting["current"] = name
                        self.push(f"{provider.title()}: uploading {index + 1} of {len(valid)} - {name}.")
                        publisher.publish_one(OUT / name, cfg.get("instagram_id", ""), cfg.get("youtube_id", ""), delay)
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

_CLIP_CACHE = {"dir_mtime": None, "items": []}

def invalidate_clip_cache():
    _CLIP_CACHE["dir_mtime"] = None
    _CLIP_CACHE["items"] = []

def _clip_index():
    try: dir_mtime = OUT.stat().st_mtime_ns
    except OSError: dir_mtime = None
    if dir_mtime == _CLIP_CACHE["dir_mtime"]:
        return _CLIP_CACHE["items"]
    items = []
    for p in OUT.glob("*.mp4"):
        if not CLIP_RE.match(p.name):          # skips the *.tmp.mp4 files that are still rendering
            continue
        try: st = p.stat()
        except OSError: continue
        items.append({"name": p.name, "mtime": st.st_mtime, "size_mb": round(st.st_size / 1048576, 1)})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    _CLIP_CACHE["dir_mtime"] = dir_mtime
    _CLIP_CACHE["items"] = items
    return items

def list_clips(limit=60, offset=0):
    items = [dict(item) for item in _clip_index()[max(0, int(offset)):max(0, int(offset)) + max(1, int(limit))]]
    for item in items:
        try: item["caption"] = (OUT / item["name"]).with_suffix(".txt").read_text(encoding="utf-8")
        except Exception: item["caption"] = ""
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

CORE = Core()
TOKEN = secrets.token_urlsafe(24)

# ------------------------------------------------------------------ http server
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
        p = OUT / name
        if not (CLIP_RE.match(name) or re.match(r"^[A-Za-z0-9_\-]+\.txt$", name)) or not p.is_file():
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
            if path == "/api/window/lease":
                if not secrets.compare_digest(self.headers.get("X-Token", ""), TOKEN):
                    self.close_connection = True
                    return self._send(403, {"error": "forbidden"})
                return self._serve_window_lease()
            if path == "/":
                boot = {"settings": CORE.settings, "colors": {k: "#" + v[4:6] + v[2:4] + v[0:2] for k, v in CAPTION_COLORS.items()},
                        "positions": CAPTION_POS, "models": MODELS, "layouts": LAYOUTS,
                        "zernio": CORE.zernio_status(), "publishing": CORE.publishing_status(),
                        "ai": public_ai_settings()}
                html = HTML.replace("__BOOT__", json.dumps(boot).replace("</", "<\\/")).replace("__TOKEN__", TOKEN)
                return self._send(200, html, "text/html; charset=utf-8")
            if path == "/api/state":
                q = urllib.parse.parse_qs(u.query)
                try: since = int(q.get("since", ["0"])[0])
                except ValueError: since = 0
                try: clip_offset = max(0, int(q.get("clip_offset", ["0"])[0]))
                except ValueError: clip_offset = 0
                return self._send(200, CORE.state(since, clip_offset))
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
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError: body = {}
            if not isinstance(body, dict): body = {}
            path = urllib.parse.urlparse(self.path).path
            try:
                if path == "/api/start":
                    CORE.start(clean_cfg(body)); return self._send(200, {"ok": True})
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
                if path == "/api/publishing":
                    return self._send(200, CORE.publishing_save(body))
                if path == "/api/publishing/accounts":
                    return self._send(200, {"accounts": CORE.publishing_accounts(str(body.get("provider", "")).lower() or None)})
                if path == "/api/publishing/publish":
                    names = body.get("names", [])
                    if body.get("all"):
                        names = [p.name for p in OUT.glob("*.mp4") if CLIP_RE.match(p.name)]
                    elif not isinstance(names, list): names = []
                    return self._send(200, CORE.publish_clips([str(n) for n in names]))
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
                    schedule_window_close_shutdown(); return self._send(200, {"ok": True})
                if path == "/api/delete_many":
                    names = body.get("names", [])
                    if not isinstance(names, list): names = []
                    valid = [str(n) for n in names if CLIP_RE.match(str(n)) and (OUT / str(n)).is_file()]
                    if not valid: return self._send(400, {"error": "No valid clips selected."})
                    for name in valid:
                        for target in (OUT / name, (OUT / name).with_suffix(".txt")):
                            try:
                                target.unlink(missing_ok=True)
                            except OSError as exc:
                                if os.name == "nt" and getattr(exc, "winerror", None) in (32, 33):
                                    details = describe_file_lock(target, exc)
                                    CORE.push_file_lock(details)
                                    raise RuntimeError(details["message"]) from exc
                                raise
                    return self._send(200, {"ok": True, "deleted": len(valid)})
                if path in ("/api/delete", "/api/reveal"):
                    name = str(body.get("name", ""))
                    if not CLIP_RE.match(name) or not (OUT / name).is_file():
                        return self._send(404, {"error": "Clip not found."})
                    if path == "/api/reveal":
                        reveal(OUT / name)
                    else:
                        for target in (OUT / name, (OUT / name).with_suffix(".txt")):
                            try:
                                target.unlink(missing_ok=True)
                            except OSError as exc:
                                if os.name == "nt" and getattr(exc, "winerror", None) in (32, 33):
                                    details = describe_file_lock(target, exc)
                                    CORE.push_file_lock(details)
                                    raise RuntimeError(details["message"]) from exc
                                raise
                    return self._send(200, {"ok": True})
                if path == "/api/open_folder":
                    open_folder(OUT); return self._send(200, {"ok": True})
                if path == "/api/frame":
                    return self._send(200, {"image": grab_frame(str(body.get("mode", "live")), str(body.get("target", "")))})
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
                    cancel_window_close_shutdown(); self._send(200, {"ok": True}); QUIT.set(); return
            except (ValueError, AIProviderError) as e:
                return self._send(400, {"error": str(e)})
            self._send(404, {"error": "not found"})
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except Exception as e:
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
    class QuietServer(http.server.ThreadingHTTPServer):
        def handle_error(self, request, client_address):      # browser closed a connection: harmless, don't print a traceback
            if isinstance(sys.exc_info()[1], (ConnectionError, BrokenPipeError, TimeoutError)):
                return
            super().handle_error(request, client_address)
    bind_host = os.environ.get("STREAMSNIP_BIND_HOST", "127.0.0.1")
    bind_port = int(os.environ.get("STREAMSNIP_PORT", "0"))
    srv = QuietServer((bind_host, bind_port), Handler)
    srv.daemon_threads = True
    public_host = "127.0.0.1" if bind_host in ("0.0.0.0", "::") else bind_host
    if ":" in public_host and not public_host.startswith("["):
        public_host = f"[{public_host}]"
    url = f"http://{public_host}:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"{PRODUCT_NAME} by ScarZero is running at {url}\nChoose Quit in the app, or keep this terminal open while it runs.")
    if bind_host in ("127.0.0.1", "localhost", "::1"):
        open_window(url)
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
    try:
        srv.shutdown()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            srv.server_close()
        except Exception:
            pass


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
.btn.ghost{background:var(--card2);border:1px solid var(--line)}
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
/* start bar */
.startbar{padding:14px 0 0;display:flex;gap:10px}
.go{flex:1;padding:15px;font-size:16px;border-radius:15px;background:var(--grad);font-weight:700;color:#fff;box-shadow:0 10px 30px rgba(139,92,246,.4);transition:.2s;display:flex;align-items:center;justify-content:center;gap:10px}
.go:hover{transform:translateY(-1px);box-shadow:0 14px 38px rgba(236,72,153,.4)}
.go:disabled{opacity:.6;transform:none}
.stopb{flex:1;padding:15px;font-size:15px;border-radius:15px;background:#dc4452;font-weight:700;color:#fff;transition:.15s}.stopb:hover{background:#ec5a68}.stopb:disabled{opacity:.55}
.stopb.alt{flex:none;background:var(--card2);border:1px solid var(--line);color:var(--tx);padding:15px 20px}.stopb.alt:hover{background:rgba(255,255,255,.12)}
/* overlays */
.overlay{position:fixed;inset:0;background:rgba(4,5,9,.78);backdrop-filter:blur(10px);display:grid;place-items:center;z-index:50;animation:fade .15s}
@keyframes fade{from{opacity:0}}
.dialog{background:#12141d;border:1px solid var(--line2);border-radius:20px;padding:22px;max-width:380px;box-shadow:0 30px 80px rgba(0,0,0,.6)}
.dialog h4{font-size:17px;margin-bottom:6px}.dialog p{color:var(--dim);margin-bottom:18px}.dlg-actions{display:flex;gap:10px;justify-content:flex-end}
.player{display:flex;gap:22px;align-items:stretch;max-height:92vh;max-width:94vw;background:#0d0f17;border:1px solid var(--line2);border-radius:22px;padding:14px;box-shadow:0 30px 90px rgba(0,0,0,.7)}
.player video{height:min(82vh,820px);aspect-ratio:9/16;border-radius:14px;background:#000;display:block}
.pside{width:290px;display:flex;flex-direction:column;gap:12px;padding:6px 6px 2px}
.pside h4{font-size:12px;letter-spacing:.9px;text-transform:uppercase;color:var(--dim)}
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
  <button class="btn ghost" id="btn-folder"><span data-ico="folder"></span>Clips folder</button>
  <button class="btn ghost" id="btn-settings"><span data-ico="settings"></span>Settings</button>
  <button class="btn ghost" id="btn-about"><span data-ico="info"></span>About</button>
  <button class="btn ghost" id="btn-quit" title="Stop everything and close StreamSnip AI"><span data-ico="power"></span>Quit</button>
</header>
<div class="local-note">If buttons do not respond, disable your ad blocker for <b>127.0.0.1</b> / <b>localhost</b>.</div>

<div class="main">
<section class="left">
 <div class="scroll">
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
    </div>
    <select id="ai-provider" class="text" hidden><option value="hooks">Built-in and custom hook words</option><option value="ollama">Ollama local AI</option><option value="huggingface">Hugging Face hosted model</option><option value="gemini">Gemini API</option></select>
    <div id="ollama-ai-fields" hidden>
      <div class="row"><label>Ollama address</label></div><input id="ollama-url" class="text" value="http://127.0.0.1:11434">
      <div class="row"><label>Installed Ollama model</label><button class="btn ghost" id="ai-detect-ollama">Detect models</button></div>
      <select id="ollama-model" class="text"><option value="">Click Detect models</option></select>
      <p class="hint">Install Ollama and at least one model first. Only models already installed and detected by Ollama are available.</p>
    </div>
    <div id="gemini-ai-fields" hidden><div class="row"><label>Gemini API key</label><div class="prow"><b id="gemini-key-state">Not saved</b><button type="button" class="btn ghost" id="gemini-key-clear">Clear saved key</button></div></div><input id="gemini-key" class="text" type="password" placeholder="Enter a Gemini API key"><div class="row"><label>Preferred Gemini model</label></div><input id="gemini-model" class="text" value="gemini-3.8-flash" placeholder="gemini-3.8-flash"><p class="hint">The app checks this model first, tries the other available Gemini models if needed, then falls back to Ollama. Model IDs can change; use one enabled for your API key.</p></div>
    <div id="hf-ai-fields" hidden><div class="row"><label>Hugging Face model</label></div><input id="hf-model" class="text" value="deepseek-ai/DeepSeek-V4.1-Flash:fastest"><div class="row"><label>Hugging Face access token</label><div class="prow"><b id="hf-token-state">Not saved</b><button type="button" class="btn ghost" id="hf-token-clear">Clear saved token</button></div></div><input id="hf-token" class="text" type="password" placeholder="hf_… token with Inference Providers access"><p class="hint">Save your token here. StreamSnip also uses it for authenticated Whisper model downloads. Use a token with Inference Providers access and available provider credits.</p></div>
    <label class="toggle" style="margin-top:12px"><span>AI-write post titles &amp; descriptions for ScarClipScheduler</span><input type="checkbox" id="metadata-copy-enabled"><i class="sl"></i></label>
    <p class="hint">Uses the selected Gemini, Ollama, or Hugging Face provider once per finished clip. If AI is unavailable or its response is unusable, StreamSnip keeps the transcript-based fallback. Gemini/Hugging Face requests may use quota or credits.</p>
    <div class="prow" style="margin-top:12px"><button class="btn ghost" id="ai-settings-save">Save AI settings</button><button class="btn ghost" id="ai-test-provider">Test connection</button><span class="msg" id="ai-settings-msg">Built-in hook detection selected</span></div>
  </div>

  <div class="card">
    <div class="ch"><span class="num">2</span><h3>Moment detection</h3></div>
    <div class="row"><label>Min viral score</label><b id="v-sens"></b></div>
    <input type="range" id="r-sens" min="0" max="100" step="1">
    <div class="ends"><span>More clips</span><span>Only the best</span></div>
    <p class="hint">0 = no limit — selects every non-overlapping moment above the viral-score floor. Weak segments can produce fewer or no clips.</p>
    <div class="two">
      <div><div class="row"><label>Clips / chunk (0 = no limit)</label><b id="v-cpc"></b></div><input type="range" id="r-cpc" min="0" max="10" step="1"></div>
      <div><div class="row"><label>Chunk length</label><b id="v-chunk"></b></div><input type="range" id="r-chunk" min="1" max="30" step="1"></div>
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
    <div class="row"><label>Speech model</label></div>
    <select id="model" class="text"></select>
    <label class="toggle"><span>Delete the raw recording after clipping (saves disk space)</span><input type="checkbox" id="t-del"><i class="sl"></i></label>
    <div class="row"><label>End-card CTA</label></div>
    <input id="cta-text" class="text" type="text" maxlength="100" placeholder="Subscribe for more clips">
    <label class="toggle"><span>Speak CTA with a soft female voice</span><input type="checkbox" id="cta-voice"><i class="sl"></i></label>
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
    <select id="compute-device" class="text"><option value="gpu">Automatic — use NVIDIA GPU when available</option></select>
    <p class="hint">Speech uses CUDA when a supported NVIDIA GPU is detected; video recording and rendering use NVENC whenever FFmpeg provides it. CPU processing is used only when no supported GPU is detected. A GPU initialization failure is shown in Activity instead of silently switching to CPU.</p>
    <div class="row"><label>Live video bitrate target (kbps)</label><b>Full HD</b></div>
    <input id="capture-bitrate" class="text" type="number" min="6000" max="50000" step="500" value="6000" aria-label="Capture video bitrate target in kilobits per second">
    <p class="hint">Default target is 6,000 kbps (minimum setting). Captures at 1080p when available and falls back to 720p. A source below 1080p cannot gain real detail from upscaling.</p>
    <div class="row"><label>App and runtime updates</label></div>
    <p class="hint">Current app version: v2.0.5. Check the published release before updating.</p>
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
    <div class="two">
      <div><div class="row"><label>Instagram</label></div><select id="z-ig" class="text"><option value="">Not selected</option></select></div>
      <div><div class="row"><label>YouTube</label></div><select id="z-yt" class="text"><option value="">Not selected</option></select></div>
    </div>
    <div class="two">
      <div><div class="row"><label>Schedule delay (minutes)</label></div><input id="z-delay" class="text" type="number" min="0" value="0"></div>
      <div><div class="row"><label>YouTube visibility</label></div><select id="z-vis" class="text"><option>public</option><option>unlisted</option><option>private</option></select></div>
    </div>
    <label class="toggle"><span>Auto-post new clips</span><input type="checkbox" id="z-auto"><i class="sl"></i></label>
    <div class="prow" style="margin-top:12px"><button class="btn ghost" id="z-check">Save &amp; identify channels</button><span class="msg" id="z-msg">Not connected</span></div>
  </div>
 </div>
 <div class="startbar" id="startbar">
   <button class="go" id="btn-start"><span data-ico="bolt" data-s="20"></span><span id="go-label">Start clipping</span></button>
 </div>
 <div class="startbar" id="stopbar" hidden>
   <button class="stopb" id="btn-stop">Stop &amp; finish clips</button>
   <button class="stopb alt" id="btn-kill">Stop now</button>
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
    <div class="prow" style="justify-content:flex-end;margin-bottom:10px"><button class="btn ghost" id="btn-select-all">Select all</button><button class="btn ghost" id="btn-publish-selected">Publish selected (0)</button><button class="btn danger" id="btn-delete-selected">Delete selected (0)</button><button class="btn danger" id="btn-publish-all">Publish all clips</button></div>
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
let clipOffset=0;
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
const markWindowOpen=()=>api("/api/window/open").catch(()=>{});
let windowLeaseController=null,windowLeaseActive=false;
function startWindowLease(){if(windowLeaseActive)return;windowLeaseActive=true;windowLeaseController=new AbortController();const controller=windowLeaseController;(async()=>{while(windowLeaseActive&&controller===windowLeaseController){try{const r=await fetch("/api/window/lease",{headers:{"X-Token":TOKEN},cache:"no-store",signal:controller.signal});if(!r.ok)throw new Error("Window lease failed");const reader=r.body.getReader();while(windowLeaseActive){const part=await reader.read();if(part.done)break}}catch(e){}if(windowLeaseActive)await new Promise(resolve=>setTimeout(resolve,350))}})()}
function stopWindowLease(){windowLeaseActive=false;if(windowLeaseController)windowLeaseController.abort();windowLeaseController=null}
markWindowOpen();startWindowLease();window.addEventListener("pageshow",()=>{markWindowOpen();startWindowLease()});
window.addEventListener("pagehide",()=>{stopWindowLease();if(appClosing)return;fetch("/api/window/closing",{method:"POST",headers:{"Content-Type":"application/json","X-Token":TOKEN},body:"{}",keepalive:true}).catch(()=>{})});
const AI=BOOT.ai||{provider:"hooks",ollama_url:"http://127.0.0.1:11434",ollama_model:""};
$("#metadata-copy-enabled").checked=AI.metadata_copy_enabled!==false;
$("#ai-provider").value=AI.provider||"hooks";
$("#ollama-url").value=AI.ollama_url||"http://127.0.0.1:11434";
$("#ollama-model").replaceChildren(h("option",{value:AI.ollama_model||""},AI.ollama_model||"Click Detect models"));
$("#hf-model").value=AI.huggingface_model||"deepseek-ai/DeepSeek-V4.1-Flash:fastest";
$("#gemini-key-state").textContent=AI.gemini_key_set?"Saved locally":"Not saved";
$("#gemini-model").value=AI.gemini_model||"gemini-3.8-flash";
$("#hf-token-state").textContent=AI.huggingface_token_set?"Saved locally":"Not saved";
$("#gemini-key-clear").disabled=!AI.gemini_key_set;$("#hf-token-clear").disabled=!AI.huggingface_token_set;
function showAIFields(updateMessage=false){const p=$("#ai-provider").value;$("#ollama-ai-fields").hidden=p!=="ollama";$("#gemini-ai-fields").hidden=p!=="gemini";$("#hf-ai-fields").hidden=p!=="huggingface";$("#ai-test-provider").hidden=p==="hooks";if(updateMessage){const names={ollama:"Ollama",gemini:"Gemini",huggingface:"Hugging Face"};$("#ai-settings-msg").textContent=p==="hooks"?"Built-in hook detection selected":"Ready to test or save "+names[p]+" settings"}$$(".ai-choice").forEach(b=>{const active=b.dataset.aiProvider===p;b.classList.toggle("on",active);b.setAttribute("aria-pressed",active?"true":"false")})}
$("#ai-provider").onchange=()=>showAIFields(true);$$(".ai-choice").forEach(b=>b.onclick=()=>{$("#ai-provider").value=b.dataset.aiProvider;showAIFields(true)});showAIFields(true);
$("#ai-detect-ollama").onclick=async()=>{const b=$("#ai-detect-ollama");b.disabled=true;try{const r=await api("/api/ai/ollama/models",{ollama_url:$("#ollama-url").value});const select=$("#ollama-model");select.replaceChildren(...(r.models.length?r.models.map(m=>h("option",{value:m},m)):[h("option",{value:""},"No models installed") ]));if(AI.ollama_model&&r.models.includes(AI.ollama_model))select.value=AI.ollama_model;else if(r.models.length)select.value=r.models[0];$("#ai-settings-msg").textContent=r.models.length?"Found "+r.models.length+" installed Ollama model(s)":"Ollama is installed, but no models were found"}catch(e){$("#ai-settings-msg").textContent=e.message}b.disabled=false};
function aiSettingsPayload(){const payload={provider:$("#ai-provider").value,ollama_url:$("#ollama-url").value,ollama_model:$("#ollama-model").value,gemini_model:$("#gemini-model").value.trim()||"gemini-3.8-flash",huggingface_model:$("#hf-model").value.trim()||"deepseek-ai/DeepSeek-V4.1-Flash:fastest",metadata_copy_enabled:$("#metadata-copy-enabled").checked};if($("#gemini-key").value)payload.gemini_api_key=$("#gemini-key").value;if($("#hf-token").value)payload.huggingface_token=$("#hf-token").value;return payload}
function refreshAISecretState(){$("#gemini-key-state").textContent=AI.gemini_key_set?"Saved locally":"Not saved";$("#hf-token-state").textContent=AI.huggingface_token_set?"Saved locally":"Not saved";$("#gemini-key-clear").disabled=!AI.gemini_key_set;$("#hf-token-clear").disabled=!AI.huggingface_token_set}
$("#ai-settings-save").onclick=async()=>{const b=$("#ai-settings-save");b.disabled=true;try{const r=await api("/api/ai/settings",aiSettingsPayload());Object.assign(AI,r);$("#gemini-key").value="";$("#hf-token").value="";refreshAISecretState();$("#ai-settings-msg").textContent="Saved. "+$("#ai-provider option:checked").textContent;toast("AI highlight settings saved","ok")}catch(e){$("#ai-settings-msg").textContent=e.message;toast(e.message,"bad")}b.disabled=false};
async function clearAISecret(kind){const gemini=kind==="gemini";const label=gemini?"Gemini API key":"Hugging Face token";if(!(await confirmBox("Clear saved "+label+"?","The credential will be removed from this computer. Add and save a new one before using this hosted provider again.","Clear credential")))return;const button=$(gemini?"#gemini-key-clear":"#hf-token-clear");button.disabled=true;try{const payload=aiSettingsPayload();payload[gemini?"clear_gemini_key":"clear_huggingface_token"]=true;const r=await api("/api/ai/settings",payload);Object.assign(AI,r);$(gemini?"#gemini-key":"#hf-token").value="";refreshAISecretState();$("#ai-settings-msg").textContent=label+" cleared from this computer";toast(label+" cleared","ok")}catch(e){refreshAISecretState();$("#ai-settings-msg").textContent=e.message;toast(e.message,"bad")}}
$("#gemini-key-clear").onclick=()=>clearAISecret("gemini");$("#hf-token-clear").onclick=()=>clearAISecret("huggingface");
$("#ai-test-provider").onclick=async()=>{const b=$("#ai-test-provider");b.disabled=true;$("#ai-settings-msg").textContent="Testing connection...";try{const r=await api("/api/ai/test",aiSettingsPayload());$("#ai-settings-msg").textContent=r.message;toast(r.message,"ok")}catch(e){$("#ai-settings-msg").textContent=e.message;toast(e.message,"bad")}b.disabled=false};
function setSelectOptions(el,items,chosen){
  el.replaceChildren(h("option",{value:""},"Not selected"));
  items.forEach(a=>el.append(h("option",{value:a.id},a.name+" ("+a.platform+")")));
  if(chosen&&!items.some(a=>String(a.id)===String(chosen)))el.append(h("option",{value:chosen},"Saved channel ("+chosen+")"));
  if(chosen)el.value=chosen;
}
async function loadPublishingAccounts(){
  if(Z.available===false){$("#z-msg").textContent="Posting adapter unavailable";$("#z-msg").classList.add("show");return}
  const provider=activeProvider;
  const r=await api("/api/publishing/accounts",{provider});
  if(provider!==activeProvider)return;
  setSelectOptions($("#z-ig"),r.accounts.filter(a=>a.platform==="instagram"),Z.instagram_id);
  setSelectOptions($("#z-yt"),r.accounts.filter(a=>a.platform==="youtube"),Z.youtube_id);
  accountsLoadedFor=provider;
  $("#z-msg").textContent=r.accounts.length?"Connected channels identified":"No Instagram/YouTube channels found";
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
$("#rec-dir").value=S.rec_dir||""; $("#out-dir").value=S.out_dir||""; $("#capture-bitrate").value=S.capture_bitrate_kbps||6000;
function wireFolderPicker(inputId,buttonId,key){
  const input=$(inputId), button=$(buttonId);
  input.addEventListener("change",()=>{S[key]=input.value.trim();scheduleSave()});
  button.onclick=async()=>{button.disabled=true;try{const r=await api("/api/browse_folder");if(r.path){input.value=r.path;S[key]=r.path;scheduleSave();toast("Folder saved","ok")}}catch(e){toast(e.message,"bad")}button.disabled=false};
}
wireFolderPicker("#rec-dir","#rec-dir-browse","rec_dir");
wireFolderPicker("#out-dir","#out-dir-browse","out_dir");
$("#compute-device").value=S.compute_device||"gpu";
$("#compute-device").addEventListener("change",e=>{S.compute_device=e.target.value;scheduleSave()});
$("#capture-bitrate").addEventListener("change",e=>{S.capture_bitrate_kbps=Math.max(6000,Math.min(50000,+e.target.value||6000));e.target.value=S.capture_bitrate_kbps;scheduleSave()});
$("#btn-settings-save").onclick=async()=>{const b=$("#btn-settings-save");b.disabled=true;try{await api("/api/settings",S);toast("Settings saved","ok")}catch(e){toast(e.message,"bad")}b.disabled=false};
$("#btn-updates").onclick=async()=>{const b=$("#btn-updates");b.disabled=true;$("#updates-msg").textContent="Checking...";try{const r=await api("/api/check_updates");$("#updates-msg").textContent="Checked "+r.checked_at;$("#updates-list").textContent=r.items.map(x=>x.name+": "+x.current+(x.latest!=="Unknown"?" → "+x.latest:"")+(x.update?" (update available)":"")+(x.note?" — "+x.note:"")).join("\n")}catch(e){$("#updates-msg").textContent=e.message}b.disabled=false};
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
$("#output-format").value=S.output_format;function updateFormatUI(){const f=S.output_format;$("#format-hint").textContent=f==="9:16"?"9:16 keeps the facecam + game layout.":f==="16:9"?"16:9 renders a landscape YouTube frame.":f==="1:1"?"1:1 renders a square social frame.":"4:5 renders an Instagram portrait frame."}function resetCropForFormat(){const r=({"9:16":9/16,"16:9":16/9,"1:1":1,"4:5":4/5}[S.output_format]||9/16),w=Math.min(100,100*r/(16/9));S.crop_w=+w.toFixed(1);S.crop_h=100;S.crop_x=+( (100-w)/2 ).toFixed(1);S.crop_y=0}$("#output-format").addEventListener("change",e=>{S.output_format=e.target.value;resetCropForFormat();updateFormatUI();preview();scheduleSave()});updateFormatUI();
$("#font").value=S.font;$("#font").addEventListener("input",e=>{const v=e.target.value.trim();if(/^[A-Za-z0-9 \-]{1,40}$/.test(v)){S.font=v;preview();scheduleSave()}});
$("#t-del").checked=!!S.delete_rec;$("#t-del").addEventListener("change",e=>{S.delete_rec=e.target.checked;scheduleSave()});
$("#cta-text").value=S.cta_text||"Subscribe for more clips";
$("#cta-text").addEventListener("input",e=>{S.cta_text=e.target.value.replace(/[\r\n{}\\]/g,"").slice(0,100)||"Subscribe for more clips";scheduleSave()});
$("#cta-voice").checked=S.cta_voice_enabled!==false;
$("#cta-voice").addEventListener("change",e=>{S.cta_voice_enabled=e.target.checked;scheduleSave()});
$("#show-tag-video").checked=!!S.show_tag_video;
$("#show-tag-video").addEventListener("change",e=>{S.show_tag_video=e.target.checked;scheduleSave()});
$("#t-sub-custom").checked=!!S.subtitle_custom;
$("#sub-custom-fields").hidden=!S.subtitle_custom;
$("#t-sub-custom").addEventListener("change",e=>{S.subtitle_custom=e.target.checked;$("#sub-custom-fields").hidden=!S.subtitle_custom;scheduleSave();preview()});
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
$("#pub-provider").onchange=async e=>{activeProvider="zernio";accountsLoadedFor="";loadProviderForm();["#z-ig","#z-yt"].forEach(id=>$(id).replaceChildren(h("option",{value:""},"Not selected")));if((P.providers.zernio||{}).api_key_set)loadPublishingAccounts().catch(err=>$("#z-msg").textContent=err.message)};loadProviderForm();
$("#z-key-state").textContent=Z.api_key_set?"Saved locally":"Not saved";
$("#z-key-state").style.color=Z.api_key_set?"var(--ok)":"var(--dim)";
$("#z-check").onclick=async()=>{
  const b=$("#z-check");b.disabled=true;
  try{
    const payload={provider:"zernio",api_key:$("#z-api").value,auto_post:$("#z-auto").checked,schedule_minutes:+$("#z-delay").value||0,visibility:$("#z-vis").value};
    if(accountsLoadedFor==="zernio"){payload.instagram_id=$("#z-ig").value;payload.youtube_id=$("#z-yt").value}
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
  const all=cards.size>0&&count===cards.size;$("#btn-select-all").textContent=all?"Clear selection":"Select all";
}
function selectAllClips(){
  const all=cards.size>0&&selectedClips.size===cards.size;
  selectedClips.clear();
  if(!all)for(const name of cards.keys())selectedClips.add(name);
  cards.forEach(card=>{const pick=card.querySelector(".pick");if(pick)pick.checked=selectedClips.has(card.dataset.name)});
  updateSelectedButton();
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
function clipCard(c){
  const v=h("video",{src:"/clips/"+encodeURIComponent(c.name)+"#t=0.1",loop:true,playsinline:true,preload:"metadata"});v.muted=true;
  const first=(c.caption||"").split("\n")[0]||c.name;
  const when=h("span",{class:"when","data-t":c.mtime},ago(c.mtime));
  const pick=h("input",{class:"pick",type:"checkbox",title:"Select this clip for publishing"});pick.checked=selectedClips.has(c.name);pick.onchange=()=>{pick.checked?selectedClips.add(c.name):selectedClips.delete(c.name);updateSelectedButton()};
  const copy=()=>{navigator.clipboard.writeText(c.caption||"").then(()=>toast("Caption copied","ok"),()=>toast("Couldn't copy","bad"))};
  const post=()=>publishNames([c.name]);
  const del=async()=>{if(await confirmBox("Delete this clip?","This permanently removes the video and its caption file.","Delete")){try{await api("/api/delete",{name:c.name});toast("Clip deleted");poll(true)}catch(e){toast(e.message,"bad")}}};
  return h("div",{class:"clip","data-name":c.name,title:"Double-click this clip to select it for publishing",ondblclick:e=>{if(!e.target.closest("button,a,input"))toggleClipSelection(c.name)},onmouseenter:()=>{v.play().catch(()=>{})},onmouseleave:()=>v.pause()},
    h("div",{class:"thumb",onclick:()=>openClip(c)},v,h("div",{class:"pb"},ico("play",15))),
    h("div",{class:"cm"},h("div",{class:"cc",title:first},first),
      h("div",{class:"cr"},h("span",{},pick," ",when," · "+c.size_mb+" MB"),
        h("span",{class:"acts"},
          h("button",{class:"ib post",title:"Publish this clip",onclick:post},"Post"),
          h("button",{class:"ib",title:"Copy caption + hashtags",onclick:copy},ico("copy",15)),
          h("a",{class:"ib",title:"Download",href:"/clips/"+encodeURIComponent(c.name),download:c.name},ico("download",15)),
          h("button",{class:"ib",title:"Show in folder",onclick:()=>api("/api/reveal",{name:c.name}).catch(e=>toast(e.message,"bad"))},ico("folder",15)),
          h("button",{class:"ib del",title:"Delete",onclick:del},ico("trash",15))))));
}
function renderClips(list,total=0){
  if(!list.length&&clipOffset>0){clipOffset=Math.max(0,clipOffset-CLIP_PAGE_SIZE);return}
  const sig=list.map(c=>c.name).join("|");
  $("#empty").hidden=list.length>0;$("#grid").hidden=list.length===0;
  const cnt=$("#cnt");cnt.hidden=!list.length;cnt.textContent=list.length;
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
  try{const r=await api("/api/publishing/publish",{names});toast("Started uploading "+r.queued+" clip(s) to "+activeProvider,"ok");selectedClips.clear();$$('.pick').forEach(x=>x.checked=false);updateSelectedButton();}
  catch(e){toast(e.message,"bad")}
}
$("#btn-publish-selected").onclick=()=>publishNames([...selectedClips]);
$("#btn-select-all").onclick=selectAllClips;
$("#btn-delete-selected").onclick=async()=>{
  const names=[...selectedClips];if(!names.length){toast("Select at least one clip first","bad");return}
  if(!(await confirmBox("Delete selected clips?","This permanently removes "+names.length+" video(s) and their caption files.","Delete")))return;
  try{const r=await api("/api/delete_many",{names});selectedClips.clear();toast("Deleted "+r.deleted+" clip(s)","ok");poll(true)}catch(e){toast(e.message,"bad")}
};
$("#btn-publish-all").onclick=async()=>{if(!(await confirmBox("Publish all clips?","This submits every finished clip in your clips folder to the selected channels. This may publish many videos.","Publish all")))return;try{const r=await api("/api/publishing/publish",{all:true});toast("Started uploading "+r.queued+" clip(s) to "+activeProvider,"ok")}catch(e){toast(e.message,"bad")}};
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
    const r=await fetch("/api/state?since="+lastLog+"&clip_offset="+clipOffset,{cache:"no-store"});const s=await r.json();
    fails=0;$("#offline").hidden=true;
    if(!logPaused){lastLog=s.last_id;addLogs(s.logs)}updateRun(s);renderClips(s.clips,s.clip_total);
  }catch(e){if(++fails>=3)$("#offline").hidden=false}
  busy=false;
}
setInterval(poll,900);poll();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
