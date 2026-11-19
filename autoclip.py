r"""
AutoClip - free live-stream / VOD auto clipper.
Twitch / YouTube live (or a video file)  ->  ready-to-post 9:16 clips with MrBeast-style captions.

Everything runs locally and is 100% free: streamlink + ffmpeg + faster-whisper on your GPU.

Setup (Windows 11, PowerShell):
    winget install Gyan.FFmpeg
    py -3.14 -m venv venv ; .\venv\Scripts\Activate.ps1
    python -m pip install -U pip
    pip install --only-binary=:all: streamlink faster-whisper numpy nvidia-cublas-cu12

Run:
    python autoclip.py                 -> opens the AutoClip app window (a local web UI, no extra installs)
    python autoclip.py live URL        -> headless, no UI
    python autoclip.py file video.mp4  -> headless, no UI

Output: the "out" folder. Each clip = .mp4 (1080x1920) + .txt (caption and hashtags to paste).
Your own hype words: "Hype words" tab in the app (stored in custom_words.txt, re-read for every chunk).
"""
import os, re, sys, glob, json, time, queue, shutil, secrets, threading, subprocess, pathlib, platform
import http.server, urllib.parse, webbrowser
import numpy as np
from zernio_poster import ZernioPublisher

# ------------------------------------------------------------------ setup
def _add_cuda_dlls():
    """Windows: let ctranslate2 find the cuBLAS DLLs installed by the nvidia-cublas-cu12 wheel."""
    if os.name != "nt":
        return
    for base in sys.path:
        d = pathlib.Path(base) / "nvidia" / "cublas" / "bin"
        if d.is_dir():
            os.add_dll_directory(str(d))
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

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "out"; OUT.mkdir(exist_ok=True)
REC = HERE / "rec"; REC.mkdir(exist_ok=True)
SETTINGS_FILE = HERE / "settings.json"
CUSTOM_FILE = HERE / "custom_words.txt"

CF = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0      # no flashing console windows
def run(cmd, **kw):   return subprocess.run(cmd, creationflags=CF, **kw)
def popen(cmd, **kw): return subprocess.Popen(cmd, creationflags=CF, **kw)

DEFAULTS = {
    "mode": "live", "target": "",
    "clips_per_chunk": 2, "chunk_min": 3, "pre": 20, "post": 15, "min_score": 1.5,
    "model": "distil-large-v3",
    "color": "Yellow", "position": "Lower third", "caption_size": 100, "words_per_line": 3, "font": "Impact",
    "layout": "Facecam + game (Twitch)", "delete_rec": False,
    "cam_x": 70, "cam_y": 4, "cam_w": 29, "cam_h": 37, "game_x": 50,
}
# ASS colours are BGR
CAPTION_COLORS = {"Yellow": "00FFFF", "Green": "00FF00", "Cyan": "FFFF00", "Orange": "0080FF", "Pink": "FF40FF"}
CAPTION_POS = {"Lower third": 520, "Middle": 800, "Low": 380}      # MarginV (px from bottom of 1920)
LAYOUTS = ["Facecam + game (Twitch)", "Blur background", "Fill (crop center)"]
MODELS = ["distil-large-v3", "large-v3-turbo", "small", "base"]

def clean_cfg(raw):
    """Validate/clamp settings coming from the UI or disk."""
    raw = raw if isinstance(raw, dict) else {}
    c = dict(DEFAULTS)
    def num(k, lo, hi, cast):
        try: v = cast(raw.get(k, c[k]))
        except (TypeError, ValueError): v = c[k]
        c[k] = max(lo, min(hi, v))
    num("clips_per_chunk", 1, 10, int); num("chunk_min", 1, 30, int)
    num("pre", 3, 90, int); num("post", 3, 90, int)
    num("min_score", 0.3, 5.0, float); num("caption_size", 60, 150, int); num("words_per_line", 1, 4, int)
    c["min_score"] = round(c["min_score"], 2)
    num("cam_x", 0, 90, float); num("cam_y", 0, 90, float); num("cam_w", 10, 100, float); num("cam_h", 10, 100, float)
    num("game_x", 0, 100, float)
    c["cam_w"] = min(c["cam_w"], 100 - c["cam_x"]); c["cam_h"] = min(c["cam_h"], 100 - c["cam_y"])
    for k in ("cam_x", "cam_y", "cam_w", "cam_h", "game_x"): c[k] = round(c[k], 1)
    if raw.get("mode") in ("live", "file"): c["mode"] = raw["mode"]
    c["target"] = str(raw.get("target", "")).strip()[:1000]
    for k, opts in (("color", CAPTION_COLORS), ("position", CAPTION_POS), ("layout", LAYOUTS), ("model", MODELS)):
        if raw.get(k) in opts: c[k] = raw[k]
    f = str(raw.get("font", c["font"])).strip()
    if re.fullmatch(r"[A-Za-z0-9 \-]{1,40}", f): c["font"] = f
    c["delete_rec"] = bool(raw.get("delete_rec", False))
    return c

def load_settings():
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        if raw.get("min_score") == 2.0: raw["min_score"] = 1.5      # old default was too strict
        return clean_cfg(raw)
    except Exception: return dict(DEFAULTS)

def save_settings(cfg):
    try: SETTINGS_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except Exception: pass

# ------------------------------------------------------------------ hype words
HYPE_WORDS = {
    # reactions
    "wtf", "omg", "bro", "bruh", "brooo", "bruhhh", "dude", "ayo", "yooo", "yoo", "yo",
    "nahh", "nah", "holy", "jesus", "damn", "dang", "unbelievable", "insane", "crazy",
    "nuts", "mental", "wild", "cracked", "clutch", "clip", "scream", "screaming",
    "dead", "dying", "crying", "cry", "wow", "whoa", "woah", "yikes", "bruv", "fam",
    "mad", "madness", "sick", "filthy", "nasty", "disgusting", "unreal", "actually",
    "what", "huh", "hello", "stop", "shut", "seriously", "literally", "genuinely",
    # laughing
    "lol", "lmao", "lmfao", "haha", "hahaha", "hahahaha", "rofl", "wheezing", "deceased",
    # gen z / streamer slang
    "sheesh", "cooked", "cook", "cooking", "goated", "goat", "rizz", "rizzler", "sigma",
    "skibidi", "gyatt", "fanum", "ohio", "bussin", "slay", "lit", "fire", "sus", "cap",
    "nocap", "bet", "fr", "ong", "deadass", "valid", "based", "ratio", "glazing", "glaze",
    "mid", "banger", "tuff", "peak", "crashout", "aura", "mewing", "cringe", "yeet",
    "vibes", "goofy", "ahh", "lowkey", "highkey", "bozo", "npc", "griefing", "trolling",
    "cheating", "hacker", "hacks", "w", "l", "ez", "gg", "pog", "poggers", "kekw", "omegalul",
    "pogchamp", "monkas", "copium", "hopium", "sadge", "pepega", "kappa", "clown",
    "sussy", "drip", "slaps", "chad", "gigachad",
    # UK-streamer style (Lacy / Zerkaa type energy)
    "peng", "gassed", "gas", "safe", "innit", "mandem", "wagwan", "bare", "dench", "banging",
    "proper", "bloody", "bollocks", "mug", "donkey", "melt", "muppet", "legend", "shocking",
    "scammed", "robbed", "rigged", "washed", "gapped", "gap", "diff", "sweaty", "tryhard",
    "jumpscare", "ragequit", "rage", "lagging", "lag", "banned", "ban", "kicked", "send",
    "clean", "cleanest", "disrespectful", "outplayed", "demolished", "obliterated",
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

def make_ass(words, start, end, path, cfg):
    ws = []
    for s, e, w in words:
        if s >= start and e <= end:
            cw = clean_word(w)
            if cw:
                ws.append((s - start, e - start, cw))
    col = CAPTION_COLORS.get(cfg["color"], "00FFFF")
    mv = CAPTION_POS.get(cfg["position"], 520)
    size = int(cfg["caption_size"])
    header = (
        "[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\nWrapStyle: 0\n\n"
        "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,"
        "Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,{cfg['font']},{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,0,0,0,0,100,100,2,0,1,9,4,2,70,70,{mv},1\n\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    pop = r"{\1c&H" + col + r"&\fscx120\fscy120\t(0,90,\fscx100\fscy100)}"
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
    pathlib.Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")

# ------------------------------------------------------------------ engine
_model, _model_key, _nvenc = None, None, None

def has_nvenc():
    global _nvenc
    if _nvenc is None:
        r = run(["ffmpeg", "-v", "quiet", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.1",
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

class Engine:
    def __init__(self, cfg, emit):
        self.cfg, self.emit = cfg, emit
        self.stop_flag = self.abort = False
        self.procs = []
        self.seg_seconds = int(cfg["chunk_min"]) * 60

    def log(self, msg):                      self.emit("log", msg)
    def status(self, text, phase="working"): self.emit("status", (phase, text))

    def stop(self, force=False):
        """Live: graceful (finish what is recorded) unless force. File: always immediate."""
        self.stop_flag = True
        if force or self.cfg["mode"] != "live":
            self.abort = True
        for p in list(self.procs):
            try: p.terminate()
            except Exception: pass

    def check(self):
        if self.abort:
            raise Stopped()

    # ---- transcription
    def get_model(self, name):
        global _model, _model_key
        if _model is not None and _model_key == name:
            return _model
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise RuntimeError("faster-whisper isn't installed. Run:  pip install --only-binary=:all: faster-whisper")
        self.status(f"Loading speech model '{name}' (first run downloads it)...", "transcribing")
        for ct in ("float16", "int8_float16"):
            try:
                _model = WhisperModel(name, device="cuda", compute_type=ct); _model_key = name
                self.log(f"Speech model ready on GPU ({ct}).")
                return _model
            except Exception as e:
                self.log(f"GPU load failed ({ct}): {e}")
        _model = WhisperModel("small", device="cpu", compute_type="int8"); _model_key = name
        self.log("Using CPU for speech (slower).")
        return _model

    def load_audio(self, path):
        """Decode to 16 kHz mono float32 with ffmpeg (bypasses PyAV completely)."""
        r = run(["ffmpeg", "-v", "quiet", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
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
                for s in segs:
                    self.check()
                    for w in (s.words or []):
                        words.append((w.start, w.end, w.word.strip()))
                return words
            except Stopped:
                raise
            except Exception as e:
                if attempt == 0 and any(k in str(e).lower() for k in ("cublas", "cuda", "dll", "cudnn")):
                    from faster_whisper import WhisperModel
                    self.log(f"GPU error ({e}) - falling back to CPU.")
                    _model = WhisperModel("small", device="cpu", compute_type="int8"); _model_key = self.cfg["model"]
                    continue
                raise
        return []

    # ---- moment detection
    def rms_per_second(self, path):
        cmd = ["ffmpeg", "-v", "quiet", "-i", str(path), "-vn", "-ac", "1", "-ar", "8000", "-f", "f32le", "-"]
        a = np.frombuffer(run(cmd, capture_output=True).stdout, dtype=np.float32)
        n = len(a) // 8000
        if n == 0:
            return np.zeros(0)
        return np.sqrt((a[: n * 8000].reshape(n, 8000) ** 2).mean(axis=1))

    def find_peaks(self, path, words):
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
        score = z(np.convolve(rms, kern, "same")) + 0.5 * z(np.convolve(wps, kern, "same")) \
                + 0.8 * z(np.convolve(hype, kern, "same"))
        self.best_score = float(score.max())
        n_clips = max(1, round(n / self.seg_seconds * int(self.cfg["clips_per_chunk"])))
        picks, s = [], score.copy()
        for _ in range(n_clips):
            i = int(s.argmax())
            if s[i] < float(self.cfg["min_score"]):
                break
            picks.append((i, float(s[i])))
            s[max(0, i - 40): i + 40] = -99          # never pick overlapping moments
        if not picks and self.best_score > 0:        # nothing passed the bar: still deliver the best moment of the chunk
            picks = [(int(score.argmax()), self.best_score)]
            self.log("No moment passed the threshold - using the best available moment of this chunk instead.")
        return picks, n

    # ---- render
    def render(self, src, start, end, words, name):
        cfg = self.cfg
        make_ass(words, start, end, OUT / f"{name}.ass", cfg)
        if cfg["layout"].startswith("Facecam"):
            # Twitch-style portrait: facecam on the top 40% (1080x768), game on the bottom 60% (1080x1152)
            cx, cy, cw, ch = (float(cfg[k]) / 100 for k in ("cam_x", "cam_y", "cam_w", "cam_h"))
            gx = float(cfg["game_x"]) / 100
            vf = ("[0:v]split=2[a][b];"
                  f"[a]crop=iw*{cw:.4f}:ih*{ch:.4f}:iw*{cx:.4f}:ih*{cy:.4f},"
                  "scale=1080:768:force_original_aspect_ratio=increase,crop=1080:768[cam];"
                  f"[b]crop=min(iw\\,ih*1080/1152):ih:(iw-min(iw\\,ih*1080/1152))*{gx:.4f}:0,"
                  "scale=1080:1152[game];"
                  f"[cam][game]vstack=inputs=2,setsar=1,subtitles={name}.ass[v]")
        elif cfg["layout"].startswith("Blur"):
            vf = ("[0:v]split=2[a][b];"
                  "[a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,scale=1080:1920[bg];"
                  "[b]scale=1080:-2[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
                  f"setsar=1,subtitles={name}.ass[v]")
        else:
            vf = ("[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,"
                  f"setsar=1,subtitles={name}.ass[v]")
        enc = (["-c:v", "h264_nvenc", "-preset", "p5", "-cq", "21", "-b:v", "0"] if has_nvenc()
               else ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
        tmp = f"{name}.tmp.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{end - start:.2f}",
               "-i", str(pathlib.Path(src).resolve()), "-filter_complex", vf, "-map", "[v]", "-map", "0:a?",
               *enc, "-pix_fmt", "yuv420p", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
               "-c:a", "aac", "-b:a", "160k", "-r", "30", "-movflags", "+faststart", tmp]
        r = run(cmd, cwd=OUT, capture_output=True, text=True)
        (OUT / f"{name}.ass").unlink(missing_ok=True)
        if r.returncode != 0:
            (OUT / tmp).unlink(missing_ok=True)
            raise RuntimeError((r.stderr or "ffmpeg failed").strip()[-400:])
        text = " ".join(clean_word(w).lower() for s, e, w in words if start <= s <= end).strip()
        hook = (text[:110].rstrip() + ("..." if len(text) > 110 else "")) or "Clip"
        (OUT / f"{name}.txt").write_text(f"{hook}\n\n#shorts #fyp #streamer #funny #clips #viral\n", encoding="utf-8")
        os.replace(OUT / tmp, OUT / f"{name}.mp4")
        self.emit("clip", f"{name}.mp4")

    def process(self, path):
        pth = pathlib.Path(path)
        stem = re.sub(r"[^A-Za-z0-9_-]", "_", pth.stem)[:40] or "stream"
        self.status(f"Transcribing {pth.name}...", "transcribing")
        self.log(f"Processing {pth.name}")
        words = self.transcribe(path)
        self.check()
        self.status("Finding the hype moments...", "transcribing")
        peaks, dur = self.find_peaks(path, words)
        self.log(f"Heard {len(words)} words in {dur}s of video. Best moment score {getattr(self, 'best_score', 0):.1f} "
                 f"(clips need {self.cfg['min_score']}).")
        if not words:
            self.log("WARNING: no speech was transcribed - check the speech model / GPU messages above.")
        if not peaks:
            self.log("Chunk too short or silent - nothing to clip.")
        stamp = time.strftime("%H%M%S")
        for i, (p, sc) in enumerate(peaks, 1):
            self.check()
            start, end = max(0, p - self.cfg["pre"]), min(dur, p + self.cfg["post"])
            begs = [w for w in words if abs(w[0] - start) < 3]          # snap to word edges: never cut mid-word
            if begs: start = max(0, min(begs, key=lambda w: abs(w[0] - start))[0] - 0.25)
            ends = [w for w in words if w[1] >= end]
            if ends: end = min(dur, ends[0][1] + 0.35)
            self.status(f"Rendering clip {i} of {len(peaks)} (hype score {sc:.1f})...", "rendering")
            try:
                self.render(path, start, end, words, f"{stem}_{stamp}_clip{i}")
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
                r = run(streamlink_cmd() + [url, "best", "--stream-url"], capture_output=True, text=True, env=streamlink_env())
            except OSError as e:
                raise RuntimeError(f"Could not start streamlink: {e}")
            if r.returncode == 0:
                return True
            if "No module named" in (r.stderr or ""):
                raise RuntimeError("streamlink isn't installed in this Python environment. "
                                   "Run:  pip install --only-binary=:all: streamlink   (then start AutoClip again)")
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
        run_id = time.strftime("%m%d_%H%M%S")
        pattern = str(REC / f"seg_{run_id}_%05d.ts")
        slog_path = REC / f"streamlink_{run_id}.log"
        slog = open(slog_path, "wb")
        sl = popen(streamlink_cmd() + ["--stdout", url, "best"], stdout=subprocess.PIPE, stderr=slog, env=streamlink_env())
        ff = popen(["ffmpeg", "-v", "error", "-i", "-", "-c", "copy", "-f", "segment",
                    "-segment_time", str(self.seg_seconds), "-reset_timestamps", "1", pattern],
                   stdin=sl.stdout)
        sl.stdout.close()
        self.procs = [sl, ff]
        done = set()
        idle = f"Recording - a clip batch is made every {self.cfg['chunk_min']} min."
        self.status(idle, "recording")
        t0 = time.time(); last_beat = t0; last_growth = t0; last_total = -1; warned = False
        try:
            while not self.abort:
                segs = sorted(glob.glob(str(REC / f"seg_{run_id}_*.ts")))
                recording = ff.poll() is None and not self.stop_flag
                # progress heartbeat + stall detection
                total = sum(os.path.getsize(x) for x in segs if os.path.exists(x))
                if total > last_total:
                    last_total = total; last_growth = time.time(); warned = False
                if recording and not warned and time.time() - last_growth > STALL_SECONDS:
                    self.log(f"WARNING: no new video data for {STALL_SECONDS} s - the stream may be stuck on ads. "
                             f"streamlink says: {self._tail(slog_path) or '(nothing)'}")
                    warned = True
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
                        self.status(idle, "recording")
                    elif not self.abort:
                        self.status("Wrapping up the clips already recorded...", "stopping")
                if not recording and set(segs) <= done:
                    break
                time.sleep(3)
            if time.time() - t0 < 20 and not self.stop_flag:
                self.log(f"Recording stopped after a few seconds. streamlink says: {self._tail(slog_path) or '(nothing)'}")
        finally:
            for pr in (sl, ff):
                try: pr.terminate()
                except Exception: pass
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
            for p in self.procs:
                try: p.terminate()
                except Exception: pass
            self.emit("done", "")

# ------------------------------------------------------------------ app core (state shared with the UI)
CLIP_RE = re.compile(r"^[A-Za-z0-9_\-]+\.mp4$")
QUIT = threading.Event()

class Core:
    def __init__(self):
        self.lock = threading.RLock()
        self.publisher = ZernioPublisher(self.push)
        self.engine = None
        self.running = False
        self.logs, self.log_id = [], 0
        self.phase, self.status = "idle", "Ready when you are."
        self.session = {"clips": 0, "chunks": 0, "started": None, "ended": None}
        self.settings = load_settings()

    def push(self, msg):
        with self.lock:
            self.log_id += 1
            self.logs.append((self.log_id, time.strftime("%H:%M:%S"), str(msg)))
            if len(self.logs) > 800:
                del self.logs[:200]

    def emit(self, kind, payload):
        if kind == "log":
            self.push(payload)
        elif kind == "status":
            with self.lock: self.phase, self.status = payload
        elif kind == "clip":
            with self.lock: self.session["clips"] += 1
            self.push("Clip ready: " + payload)
            self.publisher.submit(OUT / payload)
        elif kind == "chunk":
            with self.lock: self.session["chunks"] += 1
        elif kind == "done":
            with self.lock:
                self.running = False
                self.phase, self.status = "idle", "Ready when you are."
                self.session["ended"] = time.time()

    def start(self, cfg):
        with self.lock:
            if self.running:
                raise ValueError("Already running.")
            if not shutil.which("ffmpeg"):
                raise ValueError("ffmpeg not found. Run  winget install Gyan.FFmpeg  then restart AutoClip.")
            t = cfg["target"].strip().strip('"')
            if cfg["mode"] == "live":
                if not re.match(r"https?://", t):
                    raise ValueError("Paste the full stream URL (starting with https://).")
                if not streamlink_available():
                    raise ValueError("streamlink is not installed. Run:  pip install streamlink")
            else:
                if not t or not pathlib.Path(t).is_file():
                    raise ValueError("That video file doesn't exist.")
            cfg = dict(cfg, target=t)
            self.settings = cfg
            save_settings(cfg)
            self.engine = Engine(cfg, self.emit)
            self.running = True
            self.phase, self.status = "waiting", "Starting..."
            self.session = {"clips": 0, "chunks": 0, "started": time.time(), "ended": None}
            self.push("Started (" + ("live stream" if cfg["mode"] == "live" else "video file") + ").")
            threading.Thread(target=self.engine.run, daemon=True).start()

    def stop(self, force):
        with self.lock:
            if self.engine and self.running:
                self.engine.stop(force=force)
                self.push("Stopping now." if (force or self.engine.cfg["mode"] != "live")
                          else "Stopping the recording - finishing the clips already captured.")

    def state(self, since):
        clips = list_clips()
        with self.lock:
            s = self.session
            el = int((s["ended"] or time.time()) - s["started"]) if s["started"] else 0
            eng = self.engine
            return {
                "running": self.running,
                "stopping": bool(eng and self.running and eng.stop_flag),
                "mode": eng.cfg["mode"] if eng else None,
                "phase": self.phase, "status": self.status,
                "logs": [{"id": i, "t": t, "m": m} for (i, t, m) in self.logs if i > since],
                "last_id": self.log_id,
                "session": {"clips": s["clips"], "chunks": s["chunks"], "elapsed": el},
                "clips": clips,
            }

    def shutdown(self):
        with self.lock:
            if self.engine and self.running:
                self.engine.stop(force=True)

def list_clips(limit=60):
    items = []
    for p in OUT.glob("*.mp4"):
        if not CLIP_RE.match(p.name):          # skips the *.tmp.mp4 files that are still rendering
            continue
        try: st = p.stat()
        except OSError: continue
        cap = ""
        try: cap = p.with_suffix(".txt").read_text(encoding="utf-8")
        except Exception: pass
        items.append({"name": p.name, "mtime": st.st_mtime, "size_mb": round(st.st_size / 1048576, 1), "caption": cap})
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]

def reveal(path):
    path = pathlib.Path(path).resolve()
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", "/select," + str(path)], creationflags=CF)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except Exception as e:
        raise RuntimeError(f"Couldn't open the clip folder: {e}") from e

def open_folder(path):
    path = pathlib.Path(path).resolve()
    try:
        path.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            try:
                os.startfile(str(path))
            except (AttributeError, OSError):
                # Some embedded Python builds do not expose os.startfile.
                subprocess.Popen(["explorer.exe", str(path)], creationflags=CF)
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as e:
        raise RuntimeError(f"Couldn't open the clips folder: {e}") from e

BROWSE_PY = (
    "import tkinter as tk\nfrom tkinter import filedialog\n"
    "r=tk.Tk();r.withdraw();r.attributes('-topmost',True)\n"
    "print(filedialog.askopenfilename(title='Choose a stream recording / VOD',"
    "filetypes=[('Video','*.mp4 *.mkv *.mov *.ts *.flv *.webm *.avi'),('All files','*.*')]))\n")

def browse_file():
    try:
        r = run([sys.executable, "-c", BROWSE_PY], capture_output=True, text=True)
        return (r.stdout or "").strip().splitlines()[-1].strip() if (r.stdout or "").strip() else ""
    except Exception:
        return ""

def grab_frame(mode, target):
    """One JPEG frame (as a data URL) from the live stream or a video file - used by the facecam-area picker."""
    import base64
    target = (target or "").strip().strip('"')
    try:
        if mode == "live":
            if not re.match(r"https?://", target):
                raise ValueError("Paste the stream link first.")
            if not streamlink_available():
                raise ValueError("streamlink is not installed.")
            r = run(streamlink_cmd() + [target, "best", "--stream-url"], capture_output=True, text=True,
                    env=streamlink_env(), timeout=45)
            if r.returncode != 0 or not (r.stdout or "").strip():
                raise ValueError("The stream isn't live right now. Try again when it is, or pick a video file.")
            attempts = [["-i", r.stdout.strip().splitlines()[-1].strip()]]
        else:
            if not target or not pathlib.Path(target).is_file():
                raise ValueError("Choose a video file first.")
            attempts = [["-ss", "5", "-i", target], ["-i", target]]
        for a in attempts:
            r = run(["ffmpeg", "-v", "error", *a, "-frames:v", "1", "-vf", "scale=960:-2",
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
    server_version = "AutoClip"
    protocol_version = "HTTP/1.1"

    def log_message(self, *a): pass

    def _host_ok(self):
        return self.headers.get("Host", "").split(":")[0] in ("127.0.0.1", "localhost")

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

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
            if path == "/":
                boot = {"settings": CORE.settings, "colors": {k: "#" + v[4:6] + v[2:4] + v[0:2] for k, v in CAPTION_COLORS.items()},
                        "positions": CAPTION_POS, "models": MODELS, "layouts": LAYOUTS}
                html = HTML.replace("__BOOT__", json.dumps(boot).replace("</", "<\\/")).replace("__TOKEN__", TOKEN)
                return self._send(200, html, "text/html; charset=utf-8")
            if path == "/api/state":
                q = urllib.parse.parse_qs(u.query)
                try: since = int(q.get("since", ["0"])[0])
                except ValueError: since = 0
                return self._send(200, CORE.state(since))
            if path == "/api/words":
                return self._send(200, {"text": read_custom_text(), "words": sorted(HYPE_WORDS), "phrases": sorted(HYPE_PHRASES)})
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
                return self._send(403, {"error": "forbidden"})
            n = int(self.headers.get("Content-Length", "0") or 0)
            if n > 400_000:
                return self._send(413, {"error": "too large"})
            try: body = json.loads(self.rfile.read(n) or b"{}")
            except ValueError: body = {}
            if not isinstance(body, dict): body = {}
            path = urllib.parse.urlparse(self.path).path
            try:
                if path == "/api/start":
                    CORE.start(clean_cfg(body)); return self._send(200, {"ok": True})
                if path == "/api/settings":
                    cfg = clean_cfg(body); CORE.settings = cfg; save_settings(cfg); return self._send(200, {"ok": True})
                if path == "/api/stop":
                    CORE.stop(bool(body.get("force"))); return self._send(200, {"ok": True})
                if path == "/api/words":
                    text = str(body.get("text", ""))[:100_000]
                    CUSTOM_FILE.write_text(text, encoding="utf-8")
                    return self._send(200, {"ok": True, "entries": len(parse_custom(text))})
                if path in ("/api/delete", "/api/reveal"):
                    name = str(body.get("name", ""))
                    if not CLIP_RE.match(name) or not (OUT / name).is_file():
                        return self._send(404, {"error": "Clip not found."})
                    if path == "/api/reveal":
                        reveal(OUT / name)
                    else:
                        (OUT / name).unlink()
                        (OUT / name).with_suffix(".txt").unlink(missing_ok=True)
                    return self._send(200, {"ok": True})
                if path == "/api/open_folder":
                    open_folder(OUT); return self._send(200, {"ok": True})
                if path == "/api/frame":
                    return self._send(200, {"image": grab_frame(str(body.get("mode", "live")), str(body.get("target", "")))})
                if path == "/api/browse":
                    return self._send(200, {"path": browse_file()})
                if path == "/api/quit":
                    self._send(200, {"ok": True}); CORE.shutdown(); QUIT.set(); return
            except ValueError as e:
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
                subprocess.Popen([exe, f"--app={url}", "--window-size=1360,880"])
                return
            except Exception:
                pass
    webbrowser.open(url)

def main():
    if len(sys.argv) >= 3 and sys.argv[1] in ("live", "file"):      # headless mode
        cfg = clean_cfg(dict(load_settings(), mode=sys.argv[1], target=sys.argv[2].strip('"')))
        if cfg["mode"] == "live" and not streamlink_available():
            sys.exit("streamlink isn't installed in this Python environment. Run:  pip install --only-binary=:all: streamlink")
        eng = Engine(cfg, lambda k, p: print(p) if k in ("log", "clip") else None)
        try: eng.run()
        except KeyboardInterrupt: eng.stop(force=True)
        return
    class QuietServer(http.server.ThreadingHTTPServer):
        def handle_error(self, request, client_address):      # browser closed a connection: harmless, don't print a traceback
            if isinstance(sys.exc_info()[1], (ConnectionError, BrokenPipeError, TimeoutError)):
                return
            super().handle_error(request, client_address)
    srv = QuietServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    url = f"http://127.0.0.1:{srv.server_address[1]}/"
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print(f"AutoClip is running at {url}\nClose this window (or press Ctrl+C) to quit.")
    open_window(url)
    try:
        while not QUIT.wait(0.5):
            pass
    except KeyboardInterrupt:
        pass
    CORE.shutdown()
    time.sleep(0.3)
    srv.shutdown()


HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AutoClip</title>
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
.mark{width:34px;height:34px;border-radius:11px;background:var(--grad);display:grid;place-items:center;box-shadow:0 6px 22px rgba(139,92,246,.45)}
.mark svg{color:#fff}
.tag{color:var(--dim);font-weight:400;font-size:13px;margin-left:2px}
.sp{flex:1}
.main{position:relative;display:grid;grid-template-columns:430px minmax(0,1fr);gap:18px;padding:0 22px 22px;min-height:0}
.left{display:flex;flex-direction:column;min-height:0;gap:0}
.scroll{flex:1;overflow:auto;padding-right:6px;margin-right:-6px}
.right{display:flex;flex-direction:column;min-height:0;gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:16px;margin-bottom:14px;backdrop-filter:blur(8px)}
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
.btn.danger{background:#dc4452;color:#fff}.btn.danger:hover{background:#ec5a68}
.btn:disabled{opacity:.5;cursor:default}
.row{display:flex;align-items:center;justify-content:space-between;margin:14px 0 8px}
.row:first-child{margin-top:0}
.row label{color:var(--dim);font-size:13px}
.row b{font-weight:600;font-variant-numeric:tabular-nums}
.ends{display:flex;justify-content:space-between;color:var(--mute);font-size:11px;margin-top:5px}
input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:6px;border-radius:6px;outline:0;cursor:pointer;
background:linear-gradient(90deg,var(--a1),var(--a2)) 0/var(--p,50%) 100% no-repeat,rgba(255,255,255,.1)}
input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:#fff;box-shadow:0 2px 8px rgba(0,0,0,.5);border:0}
input[type=range]::-moz-range-thumb{width:18px;height:18px;border-radius:50%;background:#fff;border:0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.two .row{margin-top:14px}
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
.crect{position:absolute;border:2px solid #ff40ff;background:rgba(255,64,255,.12);cursor:move}
.crect span{position:absolute;left:4px;top:3px;font-size:10px;font-weight:700;letter-spacing:.8px;color:#fff;text-shadow:0 1px 3px #000}
.crect.game{border:2px dashed #22d3ee;background:rgba(34,211,238,.07);cursor:default;pointer-events:none}
.crect .hdl{position:absolute;right:-7px;bottom:-7px;width:14px;height:14px;background:#fff;border:2px solid #ff40ff;border-radius:3px;cursor:nwse-resize}
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
.ib{width:28px;height:28px;border-radius:8px;display:grid;place-items:center;color:var(--dim);transition:.15s}
.ib:hover{background:var(--card2);color:var(--tx)}.ib.del:hover{color:var(--bad)}
.empty{height:100%;min-height:300px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:var(--dim);gap:8px;border:1px dashed var(--line2);border-radius:18px;padding:30px}
.empty h4{font-size:17px;color:var(--tx)}.empty p{max-width:44ch;font-size:13px}
.empty .big{width:62px;height:62px;border-radius:20px;background:var(--grad);display:grid;place-items:center;margin-bottom:8px;box-shadow:0 12px 36px rgba(139,92,246,.4)}
#log{font:12px/1.65 "Cascadia Mono",Consolas,monospace;background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:16px;padding:14px 16px;min-height:100%}
#log div{white-space:pre-wrap;word-break:break-word}#log .t{color:var(--mute);margin-right:10px}#log .err{color:var(--bad)}#log .okk{color:var(--ok)}
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
  <div class="logo"><div class="mark"><svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg></div>AutoClip<span class="tag">live stream &rarr; viral Shorts</span></div>
  <div class="sp"></div>
  <button class="btn ghost" id="btn-folder"><span data-ico="folder"></span>Clips folder</button>
  <button class="btn ghost" id="btn-quit" title="Stop everything and close AutoClip"><span data-ico="power"></span>Quit</button>
</header>

<div class="main">
<section class="left">
 <div class="scroll">
  <div class="card">
    <div class="ch"><span class="num">1</span><h3>Source</h3></div>
    <div class="seg" data-key="mode"><button data-v="live">Live stream</button><button data-v="file">Video file / VOD</button></div>
    <div class="field"><input id="target" class="text" type="text" spellcheck="false" autocomplete="off"><button id="btn-browse" class="btn ghost" hidden>Browse</button></div>
    <p class="hint" id="src-hint"></p>
  </div>

  <div class="card">
    <div class="ch"><span class="num">2</span><h3>Moment detection</h3></div>
    <div class="row"><label>Strictness</label><b id="v-sens"></b></div>
    <input type="range" id="r-sens" min="0.5" max="4" step="0.1">
    <div class="ends"><span>More clips</span><span>Only the best</span></div>
    <div class="two">
      <div><div class="row"><label>Clips / chunk</label><b id="v-cpc"></b></div><input type="range" id="r-cpc" min="1" max="10" step="1"></div>
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
  </div>

  <div class="card">
    <div class="ch"><span class="num">4</span><h3>Output</h3></div>
    <div class="row"><label>Layout</label></div>
    <div class="seg" data-key="layout"><button data-v="Facecam + game (Twitch)">Facecam + game</button><button data-v="Blur background">Blurred bg</button><button data-v="Fill (crop center)">Fill</button></div>
    <div id="camrow" hidden>
      <div class="row"><label>Facecam area</label><b id="v-cam"></b></div>
      <button class="btn ghost" id="btn-cam" style="width:100%">Set facecam area on a frame</button>
      <p class="hint">Like Twitch: the facecam fills the top 40% of the clip and the game fills the bottom 60%.</p>
    </div>
    <div class="row"><label>Speech model</label></div>
    <select id="model" class="text"></select>
    <label class="toggle"><span>Delete the raw recording after clipping (saves disk space)</span><input type="checkbox" id="t-del"><i class="sl"></i></label>
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
  <div class="tabs" id="tabs">
    <button class="tab on" data-t="clips">Clips<em id="cnt" hidden></em></button>
    <button class="tab" data-t="log">Activity</button>
    <button class="tab" data-t="words">Hype words</button>
  </div>
  <div class="panel" id="p-clips">
    <div class="grid" id="grid"></div>
    <div class="empty" id="empty"><div class="big"><svg width="28" height="28" viewBox="0 0 24 24" fill="#fff"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg></div><h4>No clips yet</h4><p>Paste a Twitch or YouTube live link (or choose a VOD file) and hit Start. Finished 9:16 clips with captions appear here, ready to post.</p></div>
  </div>
  <div class="panel" id="p-log" hidden><div id="log"></div></div>
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
<div id="toasts"></div>
<div id="offline" hidden>Lost connection to AutoClip - is it still running?</div>

<script>
const BOOT=__BOOT__;
const TOKEN="__TOKEN__";
const S=Object.assign({},BOOT.settings);
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const ICON={
 copy:'<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h9"/>',
 download:'<path d="M12 4v11"/><path d="m7 11 5 5 5-5"/><path d="M5 20h14"/>',
 folder:'<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
 trash:'<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>',
 play:'<path d="M8 5v14l11-7z" fill="currentColor"/>',
 bolt:'<path d="M13 2 4 14h7l-1 8 9-12h-7z" fill="currentColor"/>',
 power:'<path d="M12 3v9"/><path d="M6.4 6.6a8 8 0 1 0 11.2 0"/>',
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
function toast(msg,kind){const t=h("div",{class:"toast "+(kind||"")},msg);$("#toasts").append(t);setTimeout(()=>{t.classList.add("out");setTimeout(()=>t.remove(),300)},3200)}
function confirmBox(title,msg,ok){return new Promise(res=>{
  const done=v=>{m.remove();res(v)};
  const m=h("div",{class:"overlay"},h("div",{class:"dialog"},h("h4",{},title),h("p",{},msg),h("div",{class:"dlg-actions"},h("button",{class:"btn ghost",onclick:()=>done(false)},"Cancel"),h("button",{class:"btn danger",onclick:()=>done(true)},ok||"Delete"))));
  document.body.append(m)})}

/* ---------- settings <-> controls ---------- */
let saveT=null;
function scheduleSave(){clearTimeout(saveT);saveT=setTimeout(()=>{api("/api/settings",S).catch(()=>{})},500)}
function paintRange(el){const p=(el.value-el.min)/(el.max-el.min)*100;el.style.setProperty("--p",p+"%")}
const RANGES=[["r-sens","min_score","v-sens",v=>(+v).toFixed(1),true],["r-cpc","clips_per_chunk","v-cpc",v=>v,true],["r-chunk","chunk_min","v-chunk",v=>v+" min",true],
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
BOOT.models.forEach(m=>$("#model").append(h("option",{value:m},m==="distil-large-v3"?"distil-large-v3 (fast, English)":m==="large-v3-turbo"?"large-v3-turbo (any language)":m==="small"?"small (light)":"base (lightest)")));
$("#model").value=S.model;$("#model").addEventListener("change",e=>{S.model=e.target.value;scheduleSave()});
$("#font").value=S.font;$("#font").addEventListener("input",e=>{const v=e.target.value.trim();if(/^[A-Za-z0-9 \-]{1,40}$/.test(v)){S.font=v;preview();scheduleSave()}});
$("#t-del").checked=!!S.delete_rec;$("#t-del").addEventListener("change",e=>{S.delete_rec=e.target.checked;scheduleSave()});
$("#target").value=S.target||"";$("#target").addEventListener("input",e=>{S.target=e.target.value;scheduleSave()});
function onMode(){
  const live=S.mode==="live";
  $("#camrow").hidden=!S.layout.startsWith("Facecam");$("#v-cam").textContent="x"+S.cam_x+"% y"+S.cam_y+"% size "+S.cam_w+"%";
  $("#target").placeholder=live?"https://www.twitch.tv/channel":"Path to a .mp4 / .mkv recording";
  $("#btn-browse").hidden=live;
  $("#src-hint").textContent=live?"Works with Twitch and YouTube live links. If the stream is offline, AutoClip waits and starts when it goes live.":"Clips are cut from the whole file. Long VODs get more clips automatically.";
  $("#go-label").textContent=live?"Start recording & clipping":"Make clips from this file";
}
onMode();
$("#btn-browse").onclick=async()=>{const b=$("#btn-browse");b.disabled=true;try{const r=await api("/api/browse");if(r.path){$("#target").value=r.path;S.target=r.path;scheduleSave()}}catch(e){toast(e.message,"bad")}b.disabled=false};

/* ---------- caption preview ---------- */
const FLAT="NO WAY BRO THIS IS INSANE LET HIM COOK ARE YOU MAD".split(" ");
let tick=0;
function preview(){
  const ph=$("#phone"),cap=$("#cap");
  ph.classList.toggle("fill",S.layout.startsWith("Fill"));ph.classList.toggle("cam",S.layout.startsWith("Facecam"));
  const k=ph.getBoundingClientRect().width/1080||0.2;
  const col=BOOT.colors[S.color]||"#FFE600",n=S.words_per_line;
  const idx=tick%FLAT.length,g=Math.floor(idx/n),words=FLAT.slice(g*n,Math.min(FLAT.length,g*n+n));
  const o=Math.max(1,9*k),sh=[];for(let a=0;a<12;a++){const r=a/12*Math.PI*2;sh.push((Math.cos(r)*o).toFixed(1)+"px "+(Math.sin(r)*o).toFixed(1)+"px 0 #000")}
  cap.style.cssText="bottom:"+(BOOT.positions[S.position]*k)+"px;padding:0 "+(70*k)+"px;font-size:"+(S.caption_size*k)+"px;font-family:'"+S.font+"',Impact,'Arial Black',sans-serif;--cap:"+col+";text-shadow:"+sh.join(",")+";color:#fff";
  cap.replaceChildren(...words.map((w,i)=>h("span",{class:(g*n+i===idx)?"hot":""},w)));
}
setInterval(()=>{tick++;preview()},430);preview();

/* ---------- facecam area editor ---------- */
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
function openCamEditor(){
  const box={x:+S.cam_x,y:+S.cam_y,w:+S.cam_w,h:+S.cam_h};let gx=+S.game_x,ar=16/9;
  const img=h("img",{class:"cimg",draggable:false});
  const hdl=h("i",{class:"hdl"});
  const rc=h("div",{class:"crect"},h("span",{},"FACECAM"),hdl);
  const rg=h("div",{class:"crect game"},h("span",{},"GAME"));
  const stage=h("div",{class:"cstage"},img,rg,rc);
  const hh=w=>w*ar/(1080/768);                       /* keeps the box the same shape as the top 40% area */
  function paint(){
    rc.style.cssText="left:"+box.x+"%;top:"+box.y+"%;width:"+box.w+"%;height:"+box.h+"%";
    const gw=Math.min(100,(1080/1152)/ar*100);rg.style.cssText="left:"+((100-gw)*gx/100)+"%;top:0;width:"+gw+"%;height:100%";
  }
  function fit(){box.h=hh(box.w);if(box.y+box.h>100){box.h=100-box.y;box.w=box.h*(1080/768)/ar}if(box.x+box.w>100){box.w=100-box.x;box.h=hh(box.w)}}
  fit();
  const drag=(el,mode)=>el.addEventListener("pointerdown",e=>{
    e.preventDefault();e.stopPropagation();el.setPointerCapture(e.pointerId);
    const r=stage.getBoundingClientRect(),s0={x:box.x,y:box.y,w:box.w,px:e.clientX,py:e.clientY};
    const mv=ev=>{const dx=(ev.clientX-s0.px)/r.width*100,dy=(ev.clientY-s0.py)/r.height*100;
      if(mode==="move"){box.x=clamp(s0.x+dx,0,100-box.w);box.y=clamp(s0.y+dy,0,100-box.h)}
      else{let w=clamp(s0.w+dx,8,100-box.x);if(hh(w)>100-box.y)w=(100-box.y)*(1080/768)/ar;box.w=w;box.h=hh(w)}
      paint()};
    const up=()=>{el.removeEventListener("pointermove",mv);el.removeEventListener("pointerup",up)};
    el.addEventListener("pointermove",mv);el.addEventListener("pointerup",up)});
  drag(rc,"move");drag(hdl,"resize");
  img.addEventListener("load",()=>{if(img.naturalWidth){ar=img.naturalWidth/img.naturalHeight;stage.style.aspectRatio=img.naturalWidth+"/"+img.naturalHeight;fit();paint()}});
  const gs=h("input",{type:"range",min:0,max:100,step:1,value:Math.round(gx)});paintRange(gs);
  gs.addEventListener("input",()=>{gx=+gs.value;paintRange(gs);paint()});
  const msg=h("span",{class:"hint",style:"margin:0"},"");
  const grab=h("button",{class:"btn ghost"},"Grab a frame");
  const doGrab=async()=>{grab.disabled=true;msg.textContent="Grabbing a frame...";try{const r=await api("/api/frame",{mode:S.mode,target:S.target});img.src=r.image;msg.textContent="Drag the pink box over the facecam and pull the corner to resize."}catch(e){msg.textContent=e.message}grab.disabled=false};
  grab.onclick=doGrab;
  const close=()=>{m.remove();document.removeEventListener("keydown",esc)};
  const esc=e=>{if(e.key==="Escape")close()};
  const save=()=>{S.cam_x=+box.x.toFixed(1);S.cam_y=+box.y.toFixed(1);S.cam_w=+box.w.toFixed(1);S.cam_h=+box.h.toFixed(1);S.game_x=gx;onMode();scheduleSave();close();toast("Facecam area saved","ok")};
  const m=h("div",{class:"overlay",onclick:e=>{if(e.target===m)close()}},
    h("div",{class:"editor"},h("h4",{},"Set the facecam area"),
      h("div",{class:"sub"},"Pink = the facecam (becomes the top 40% of the clip). Dashed blue = the part of the game that fills the bottom 60%."),
      stage,
      h("div",{class:"erow"},grab,msg),
      h("div",{class:"erow"},h("div",{class:"grow"},h("div",{class:"row",style:"margin:0 0 8px"},h("label",{},"Game crop position (left to right)")),gs)),
      h("div",{class:"erow",style:"justify-content:flex-end"},h("button",{class:"btn ghost",onclick:close},"Cancel"),h("button",{class:"btn danger",style:"background:var(--a1)",onclick:save},"Save area"))));
  document.body.append(m);document.addEventListener("keydown",esc);paint();
  if(S.target&&S.target.trim())doGrab();else msg.textContent="Paste a stream link or pick a file first, then press Grab a frame. You can still drag the box now.";
}
$("#btn-cam").onclick=openCamEditor;

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
$("#btn-folder").onclick=()=>api("/api/open_folder").then(()=>toast("Clips folder opened","ok")).catch(e=>toast(e.message,"bad"));
$("#btn-start").onclick=async()=>{
  if(!S.target.trim()){toast(S.mode==="live"?"Paste a stream link first":"Choose a video file first","bad");$("#target").focus();return}
  const b=$("#btn-start");b.disabled=true;
  try{await api("/api/start",S);await poll(true)}catch(e){toast(e.message,"bad")}
  b.disabled=false;
};
$("#btn-stop").onclick=()=>api("/api/stop",{force:false}).then(()=>poll(true)).catch(e=>toast(e.message,"bad"));
$("#btn-kill").onclick=()=>api("/api/stop",{force:true}).then(()=>poll(true)).catch(e=>toast(e.message,"bad"));
$("#btn-quit").onclick=async()=>{
  if(!(await confirmBox("Quit AutoClip?","Any recording in progress will stop. Finished clips stay in the clips folder.","Quit")))return;
  try{await api("/api/quit")}catch(e){}
  document.body.replaceChildren(h("div",{style:"height:100%;display:grid;place-items:center;text-align:center;color:#9a9fb5"},h("div",{},h("h2",{style:"color:#fff;margin-bottom:8px"},"AutoClip has closed"),h("p",{},"You can close this window."))));
  setTimeout(()=>window.close(),400);
};

/* ---------- state polling ---------- */
const PHASES={idle:"Ready",waiting:"Waiting for the stream",recording:"Recording live",transcribing:"Listening for hype",rendering:"Rendering clips",stopping:"Wrapping up",working:"Working"};
let lastLog=0,fails=0,busy=false,order="",cards=new Map();
const fmtT=s=>{const m=Math.floor(s/60),h2=Math.floor(m/60);return h2?h2+":"+String(m%60).padStart(2,"0")+":"+String(s%60).padStart(2,"0"):m+":"+String(s%60).padStart(2,"0")};
function ago(t){const s=Math.max(0,Date.now()/1000-t);if(s<60)return"just now";if(s<3600)return Math.floor(s/60)+" min ago";if(s<86400)return Math.floor(s/3600)+" h ago";return Math.floor(s/86400)+" d ago"}
function addLogs(list){
  if(!list.length)return;const box=$("#log"),pl=$("#p-log"),stick=pl.scrollHeight-pl.scrollTop-pl.clientHeight<60;
  list.forEach(l=>{const cls=/error|failed/i.test(l.m)?"err":/clip ready|live - rec/i.test(l.m)?"okk":"";box.append(h("div",{class:cls},h("span",{class:"t"},l.t),l.m))});
  while(box.children.length>500)box.firstChild.remove();
  if(stick)pl.scrollTop=pl.scrollHeight;
}
function updateRun(s){
  const hero=$("#hero");hero.dataset.phase=s.phase;
  hero.classList.toggle("live",s.running&&s.phase!=="waiting"||s.phase==="waiting"&&s.running);
  const ph=$("#ph");ph.replaceChildren(...(s.phase==="recording"?[h("span",{class:"rec-dot"})]:[]),PHASES[s.phase]||"Working");
  $("#st").textContent=s.status;$("#st").title=s.status;
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
  const copy=()=>{navigator.clipboard.writeText(c.caption||"").then(()=>toast("Caption copied","ok"),()=>toast("Couldn't copy","bad"))};
  const del=async()=>{if(await confirmBox("Delete this clip?","This permanently removes the video and its caption file.","Delete")){try{await api("/api/delete",{name:c.name});toast("Clip deleted");poll(true)}catch(e){toast(e.message,"bad")}}};
  return h("div",{class:"clip","data-name":c.name,onmouseenter:()=>{v.play().catch(()=>{})},onmouseleave:()=>v.pause()},
    h("div",{class:"thumb",onclick:()=>openClip(c)},v,h("div",{class:"pb"},ico("play",15))),
    h("div",{class:"cm"},h("div",{class:"cc",title:first},first),
      h("div",{class:"cr"},h("span",{},when," · "+c.size_mb+" MB"),
        h("span",{class:"acts"},
          h("button",{class:"ib",title:"Copy caption + hashtags",onclick:copy},ico("copy",15)),
          h("a",{class:"ib",title:"Download",href:"/clips/"+encodeURIComponent(c.name),download:c.name},ico("download",15)),
          h("button",{class:"ib",title:"Show in folder",onclick:()=>api("/api/reveal",{name:c.name}).catch(e=>toast(e.message,"bad"))},ico("folder",15)),
          h("button",{class:"ib del",title:"Delete",onclick:del},ico("trash",15))))));
}
function renderClips(list){
  const sig=list.map(c=>c.name).join("|");
  $("#empty").hidden=list.length>0;$("#grid").hidden=list.length===0;
  const cnt=$("#cnt");cnt.hidden=!list.length;cnt.textContent=list.length;
  if(sig!==order){
    order=sig;const keep=new Set(list.map(c=>c.name));
    for(const [n,el] of cards){if(!keep.has(n)){el.remove();cards.delete(n)}}
    const frag=[];
    list.forEach(c=>{let el=cards.get(c.name);if(!el){el=clipCard(c);cards.set(c.name,el)}frag.push(el)});
    $("#grid").replaceChildren(...frag);
  }
  $$(".when").forEach(w=>w.textContent=ago(+w.dataset.t));
}
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
    const r=await fetch("/api/state?since="+lastLog,{cache:"no-store"});const s=await r.json();
    fails=0;$("#offline").hidden=true;
    lastLog=s.last_id;addLogs(s.logs);updateRun(s);renderClips(s.clips);
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
