"""Find the facecam box in a gameplay video, locally, without any online AI.

A streamer's webcam is a rectangle whose border stays in exactly the same place in every frame (usually in a corner) and
that contains a face. Game panels (minimap, HUD, chat) also have static straight borders, so the border alone is not enough:

  1. look at ~14 frames spread through the video,
  2. mark the pixels that carry an edge in (almost) every frame: static borders,
  3. list the best rectangles anchored at a corner whose two inner borders are static,
  4. run the small YuNet face detector (MIT licence, 230 KB, models/face_detection_yunet_2023mar.onnx) inside each candidate:
     the webcam is the candidate that holds a face in most frames; a minimap never does,
  5. if no bordered rectangle holds a face, look for a face that sits in the same spot in most frames (a borderless overlay).

Only a sure answer is returned. With no convincing webcam the answer is "no facecam" and a plain game crop is the right layout.
Needs numpy + OpenCV (both already required by the app). Typically 2-5 seconds per video.
"""
import os
import json
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:      # the app lists opencv-python-headless; without it detection is simply unavailable
    cv2 = None

BW, BH = 640, 360          # frames kept for face detection
W, H = 320, 180            # frames used for the border search
FRAMES = 14
_MODEL_RELATIVE = Path('models') / 'face_detection_yunet_2023mar.onnx'
_MODEL_CANDIDATES = [Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / _MODEL_RELATIVE,
                     Path(__file__).resolve().parent / _MODEL_RELATIVE,
                     Path(sys.executable).resolve().parent / _MODEL_RELATIVE]
MODEL = next((candidate for candidate in _MODEL_CANDIDATES if candidate.is_file()), _MODEL_CANDIDATES[0])


def _media_tool(name):
    """Resolve FFmpeg tools from the app bundle first, then the system PATH."""
    executable = f"{name}.exe" if os.name == "nt" else name
    roots = []
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        roots.append(Path(bundle_root))
    roots.extend((Path(__file__).resolve().parent, Path(sys.executable).resolve().parent))
    for root in roots:
        candidate = root / "vendor" / "ffmpeg" / executable
        if candidate.is_file():
            return str(candidate)

    # Reuse the exact FFmpeg selected by StreamSnip's main engine. In a bundled
    # install, ffprobe is shipped beside ffmpeg; on a developer PC both may be
    # resolved from PATH (or from a third-party FFmpeg distribution).
    app_module = sys.modules.get("autoclip")
    ffmpeg_resolver = getattr(app_module, "ffmpeg_exe", None)
    if callable(ffmpeg_resolver):
        try:
            ffmpeg_path = Path(ffmpeg_resolver()).resolve()
            candidate = ffmpeg_path if name == "ffmpeg" else ffmpeg_path.with_name(executable)
            if candidate.is_file():
                return str(candidate)
        except (OSError, TypeError, ValueError):
            pass
    return shutil.which(name) or executable


def _duration(path):
    r = subprocess.run([_media_tool("ffprobe"), '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(path)], capture_output=True, text=True, timeout=30)
    return float(r.stdout.strip() or 0)


def sample_frames(path, n=FRAMES):
    """n BGR frames (n, BH, BW, 3) from evenly spread moments of the video."""
    dur = _duration(path)
    if dur <= 0:
        raise ValueError('Could not read the video.')
    lo, hi = dur * .06, dur * .94
    times = [lo + (hi - lo) * i / max(1, n - 1) for i in range(n)] if dur > 8 else [dur * (i + .5) / n for i in range(n)]
    frames = []
    with tempfile.TemporaryDirectory() as d:
        for i, t in enumerate(times):
            out = Path(d) / f'f{i}.png'
            app = sys.modules.get("autoclip")
            hwaccel = app.ffmpeg_cuda_decode_args() if callable(getattr(app, "ffmpeg_cuda_decode_args", None)) else []
            subprocess.run([_media_tool("ffmpeg"), '-y', '-v', 'error', *hwaccel, '-ss', f'{t:.2f}', '-i', str(path), '-frames:v', '1', '-vf', f'scale={BW}:{BH}', str(out)],
                           capture_output=True, timeout=60)
            if out.exists():
                img = cv2.imread(str(out), cv2.IMREAD_COLOR)
                if img is not None and img.shape[:2] == (BH, BW):
                    frames.append(img)
    if len(frames) < 6:
        raise ValueError('Not enough frames could be read from this video.')
    return np.stack(frames)


def _gray_small(frames):
    return np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_BGR2GRAY), (W, H), interpolation=cv2.INTER_AREA).astype(np.float32) for f in frames])


def static_edges(gray):
    """(thin, thick): pixels on an edge in at least 75% of the frames; thick is dilated by one pixel so a border that
    shifts by a pixel still counts."""
    freq = np.zeros(gray.shape[1:], np.float32)
    for f in gray:
        g = cv2.GaussianBlur(f, (3, 3), 0)
        gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
        freq += (np.hypot(gx, gy) > 60).astype(np.float32)
    freq /= len(gray)
    thin = (freq >= .75).astype(np.uint8)
    return thin, cv2.dilate(thin, np.ones((3, 3), np.uint8)).astype(np.float32)


def _vseg(cs, x, y0, y1):
    """Mean of the static-edge mask along column x between rows y0 and y1 (cs = cumulative sums down the rows)."""
    if x < 0 or x >= W or y1 <= y0:
        return 0.0
    top = cs[y0 - 1, x] if y0 > 0 else 0.0
    return float((cs[min(y1, H) - 1, x] - top) / (min(y1, H) - y0))


def _hseg(cs, y, x0, x1):
    """Mean of the static-edge mask along row y between columns x0 and x1 (cs = cumulative sums along the columns)."""
    if y < 0 or y >= H or x1 <= x0:
        return 0.0
    left = cs[y, x0 - 1] if x0 > 0 else 0.0
    return float((cs[y, min(x1, W) - 1] - left) / (min(x1, W) - x0))


def _runs(line, min_len, gap=3):
    """(start, end) of runs of non-zero values in a 1-D array, bridging gaps of up to `gap` pixels."""
    idx = np.flatnonzero(line)
    if idx.size == 0:
        return []
    cuts = np.flatnonzero(np.diff(idx) > gap)
    starts = np.r_[idx[0], idx[cuts + 1]]
    ends = np.r_[idx[cuts], idx[-1]]
    return [(int(a), int(b)) for a, b in zip(starts, ends) if b - a + 1 >= min_len]


def _segments(mask, vertical, min_len):
    """Static straight segments as (pos, start, end), one per cluster of neighbouring lines, plus the frame edge itself."""
    raw = []
    n = W if vertical else H
    span = H if vertical else W
    for p in range(n):
        line = mask[:, p] if vertical else mask[p, :]
        for a, b in _runs(line, min_len):
            raw.append((p, a, b))
    clusters = []
    for p, a, b in raw:
        for c in clusters:
            if abs(p - c['last']) <= 1 and min(b, c['b']) - max(a, c['a']) > .6 * min(b - a, c['b'] - c['a']):
                c['pos'].append(p)
                c['last'] = p
                c['a'], c['b'] = min(a, c['a']), max(b, c['b'])
                break
        else:
            clusters.append({'pos': [p], 'last': p, 'a': a, 'b': b})
    out = [(int(np.median(c['pos'])), c['a'], c['b']) for c in clusters]
    out += [(0, 0, span - 1), (n - 1, 0, span - 1)]                      # the frame's own edges
    return out


def candidates(gray, limit=24, min_border=.55):
    """Best distinct rectangles (small-frame pixels) whose four sides are static straight lines or the frame edge."""
    thin, thick = static_edges(gray)
    cs_r, cs_c = np.cumsum(thick, axis=0), np.cumsum(thick, axis=1)
    std = gray.std(axis=0)
    mean = gray.mean(axis=0)
    min_w, max_w = int(W * .09), int(W * .46)
    min_h, max_h = int(H * .12), int(H * .66)
    seen, vs = set(), []
    for seg in _segments(thin, True, int(H * .10)) + _segments(thick, True, int(H * .10)):     # thin lines and bridged lines both count
        key = (seg[0], seg[1] // 3, seg[2] // 3)
        if key not in seen:
            seen.add(key)
            vs.append(seg)
    found = []
    for xl, yl0, yl1 in vs:
        for xr, yr0, yr1 in vs:
            w = xr - xl
            if not min_w <= w <= max_w:
                continue
            y0, y1 = max(yl0, yr0), min(yl1, yr1)
            h = y1 - y0
            if not min_h <= h <= max_h or not .45 <= w / float(h) <= 2.3:
                continue
            # top / bottom sides: static line or frame edge
            top = 1.0 if y0 <= 2 else max(_hseg(cs_c, yy, xl, xr) for yy in (y0 - 1, y0, y0 + 1) if 0 <= yy < H)
            bot = 1.0 if y1 >= H - 3 else max(_hseg(cs_c, yy, xl, xr) for yy in (y1 - 1, y1, y1 + 1) if 0 <= yy < H)
            left = 1.0 if xl <= 1 else max(_vseg(cs_r, xx, y0, y1) for xx in (xl - 1, xl, xl + 1) if 0 <= xx < W)
            right = 1.0 if xr >= W - 2 else max(_vseg(cs_r, xx, y0, y1) for xx in (xr - 1, xr, xr + 1) if 0 <= xx < W)
            border = min(top, bot, left, right)
            if border >= min_border:
                touches = [xl <= 1, xr >= W - 2, y0 <= 2, y1 >= H - 3]
                if sum(touches) >= 3:       # most of the frame, not a webcam
                    continue
                found.append((border, xl, y0, w, h, 'edge' if any(touches) else 'float'))
    found.sort(key=lambda c: (-round(c[0], 2), -c[3] * c[4]))
    picked = []
    for b, x0, y0, w, h, kind in found:
        if any(_iou((x0, y0, w, h), (p['x0'], p['y0'], p['w'], p['h'])) > .7 for p in picked):      # nested boxes are kept on purpose
            continue
        inside = std[y0 + 2:y0 + h - 2, x0 + 2:x0 + w - 2]
        ya, yb, xa, xb = max(0, y0 - 6), min(H, y0 + h + 6), max(0, x0 - 6), min(W, x0 + w + 6)
        outer = mean[ya:yb, xa:xb]
        mask = np.ones_like(outer, bool)
        mask[y0 - ya:y0 - ya + h, x0 - xa:x0 - xa + w] = False
        contrast = abs(float(mean[y0 + 3:y0 + h - 3, x0 + 3:x0 + w - 3].mean()) - float(outer[mask].mean())) if mask.any() else 0.0
        picked.append({'border': float(b), 'x0': x0, 'y0': y0, 'w': w, 'h': h, 'corner': kind,
                       'calm': float(inside.mean()) if inside.size else 99.0, 'contrast': contrast})
        if len(picked) >= limit:
            break
    return picked, float(np.median(std))


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix, iy = max(0, min(ax + aw, bx + bw) - max(ax, bx)), max(0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter + 1e-9)


class Faces:
    """CPU YuNet wrapper used only when no physical GPU is installed."""
    def __init__(self):
        if not MODEL.exists():
            raise FileNotFoundError(f'Face model missing: {MODEL}')
        self.det = cv2.FaceDetectorYN.create(str(MODEL), '', (320, 320), 0.6, 0.3, 500)

    def find(self, img):
        h, w = img.shape[:2]
        self.det.setInputSize((w, h))
        _, out = self.det.detect(img)
        return [] if out is None else [(float(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[14])) for r in out]


def _gpu_helper_path():
    """Find the packaged DirectML YuNet helper in an install or a developer build."""
    root = Path(__file__).resolve().parent
    candidates = [
        root / "facecam-inference" / "FacecamInference.exe",
        root / "tools" / "FacecamInference" / "bin" / "Release" /
        "net10.0-windows10.0.17763.0" / "win-x64" / "FacecamInference.exe",
        root / "dist" / "FacecamInference" / "FacecamInference.exe",
        root.parent / "facecam-inference" / "FacecamInference.exe",
    ]
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _nvidia_gpu_present():
    """Use the engine's shared NVIDIA hardware probe when it is available."""
    app = sys.modules.get("autoclip")
    probe = getattr(app, "nvidia_gpu_present", None)
    if callable(probe):
        return bool(probe())
    executable = shutil.which("nvidia-smi")
    if not executable:
        return False
    try:
        result = subprocess.run(
            [executable, "-L"], capture_output=True, text=True, timeout=6,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0 and "GPU " in (result.stdout or "")
    except (OSError, subprocess.TimeoutExpired):
        return False


_physical_gpu_cache = None


def _physical_gpu_present():
    """Detect any physical PCI graphics adapter so CPU is never chosen on a GPU PC."""
    global _physical_gpu_cache
    if _physical_gpu_cache is not None:
        return _physical_gpu_cache
    if os.name != "nt":
        _physical_gpu_cache = _nvidia_gpu_present()
        return _physical_gpu_cache

    powershell = shutil.which("powershell.exe")
    if not powershell:
        system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        candidate = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        powershell = str(candidate) if candidate.is_file() else None
    if not powershell:
        raise RuntimeError(
            "Could not check for a physical GPU on this Windows PC. CPU fallback is disabled."
        )

    query = (
        "$ErrorActionPreference='Stop'; "
        "$gpus = @(Get-CimInstance -ClassName Win32_VideoController | "
        "Where-Object { $_.PNPDeviceID -like 'PCI\\VEN_*' -and "
        "$_.Name -notmatch 'Microsoft Basic Display|Microsoft Remote Display|Parsec Virtual' }); "
        "if ($gpus.Count -gt 0) { 'true' } else { 'false' }"
    )
    try:
        result = subprocess.run(
            [powershell, "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(
            "Could not determine whether a physical GPU is installed. CPU fallback is disabled."
        ) from exc
    answer = (result.stdout or "").strip().lower()
    if result.returncode != 0 or answer not in {"true", "false"}:
        detail = (result.stderr or result.stdout or "Windows GPU query failed").strip()
        raise RuntimeError(
            "Could not determine whether a physical GPU is installed. CPU fallback is disabled. "
            + detail[-500:]
        )
    _physical_gpu_cache = answer == "true"
    return _physical_gpu_cache


def _run_face_inference_batch(images):
    """Run all YuNet inputs in one helper session; GPU failure never falls back to CPU."""
    helper = _gpu_helper_path()
    if helper is None:
        if _physical_gpu_present():
            raise RuntimeError(
                "A physical GPU is installed, but the DirectML facecam inference helper is missing. "
                "CPU fallback is disabled. Repair or update the StreamSnip AI installation."
            )
        return None

    if not MODEL.is_file():
        raise FileNotFoundError(f"Face model missing: {MODEL}")
    if not images:
        return {"device": "GPU helper · no frames", "faces": []}

    with tempfile.TemporaryDirectory(prefix="streamsnip-facecam-gpu-") as folder:
        manifest_paths = []
        for index, image in enumerate(images):
            if image is None or image.size == 0:
                raise ValueError("A facecam inference frame is empty.")
            output = Path(folder) / f"frame-{index:04d}.png"
            if not cv2.imwrite(str(output), image):
                raise RuntimeError("Could not prepare a frame for GPU facecam inference.")
            manifest_paths.append(str(output))
        manifest = Path(folder) / "frames.json"
        manifest.write_text(json.dumps(manifest_paths), encoding="utf-8")
        try:
            completed = subprocess.run(
                [str(helper), "--model", str(MODEL), "--manifest", str(manifest)],
                capture_output=True, text=True, timeout=max(90, len(images) * 2),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("GPU facecam inference timed out; CPU fallback is disabled.") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "DirectML inference failed").strip()
            raise RuntimeError("GPU facecam inference failed; CPU fallback is disabled. " + detail[-900:])
        try:
            payload = json.loads(completed.stdout)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("The GPU facecam helper returned invalid results.") from exc
        faces = payload.get("faces")
        if not isinstance(faces, list) or len(faces) != len(images):
            raise RuntimeError("The GPU facecam helper returned an incomplete frame batch.")
        normalized = []
        for frame_faces in faces:
            if not isinstance(frame_faces, list):
                raise RuntimeError("The GPU facecam helper returned an invalid detection list.")
            normalized.append([
                tuple(float(value) for value in face[:5])
                for face in frame_faces
                if isinstance(face, list) and len(face) >= 5
            ])
        return {"device": str(payload.get("device") or "GPU (DirectML)"), "faces": normalized}


MIN_LIVE = 0.35      # a channel logo, drawn avatar or still picture does not change between frames; a real webcam always does a little


def is_live(calm):
    """False for a picture that never changes (typical logo or avatar box), True for moving video."""
    return calm >= MIN_LIVE


def face_rate(frames, cand, faces):
    """Share of frames in which a face is found inside the candidate rectangle (candidate in small-frame pixels)."""
    sx, sy = BW / W, BH / H
    x0, y0, w, h = int(cand['x0'] * sx), int(cand['y0'] * sy), int(cand['w'] * sx), int(cand['h'] * sy)
    hits = 0
    for f in frames:
        crop = f[y0:y0 + h, x0:x0 + w]
        if crop.size == 0:
            continue
        scale = max(1.0, 192.0 / min(crop.shape[:2]))
        if scale > 1:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ok = [r for r in faces.find(crop) if r[2] >= .16 * crop.shape[1] and r[3] >= .16 * crop.shape[0]]
        hits += 1 if ok else 0
    return hits / float(len(frames))


def borderless_face(frames, faces):
    """A face that sits in the same corner spot in most frames (webcam overlay without a clear border)."""
    boxes = []
    for f in frames:
        fs = [r for r in faces.find(f) if r[2] >= 36 and r[4] >= .75]
        boxes.append(fs)
    best = None
    for i, fs in enumerate(boxes):
        for r in fs:
            cx, cy = r[0] + r[2] / 2, r[1] + r[3] / 2
            if not (cx < BW * .42 or cx > BW * .58) or not (cy < BH * .45 or cy > BH * .55):
                continue                                   # only faces in a corner area
            same = sum(1 for g in boxes if any(abs((q[0] + q[2] / 2) - cx) < r[2] * .45 and abs((q[1] + q[3] / 2) - cy) < r[3] * .45 for q in g))
            rate = same / float(len(frames))
            if best is None or rate > best[0]:
                best = (rate, r)
    if not best or best[0] < .6:
        return None
    rate, (fx, fy, fw, fh, _) = best
    bw_, bh_ = fw * 2.6, fh * 2.9
    x0 = min(max(0, fx + fw / 2 - bw_ / 2), BW - bw_)
    y0 = min(max(0, fy + fh / 2 - bh_ * .45), BH - bh_)
    return rate, (x0 / BW, y0 / BH, bw_ / BW, bh_ / BH)


def _borderless_face_from_detections(frame_faces):
    """Evaluate face stability from the precomputed full-frame inference results."""
    boxes = [[r for r in fs if r[2] >= 36 and r[4] >= .75] for fs in frame_faces]
    best = None
    total_frames = len(frame_faces)
    for fs in boxes:
        for r in fs:
            cx, cy = r[0] + r[2] / 2, r[1] + r[3] / 2
            if not (cx < BW * .42 or cx > BW * .58) or not (cy < BH * .45 or cy > BH * .55):
                continue
            same = sum(
                1 for other in boxes
                if any(abs((q[0] + q[2] / 2) - cx) < r[2] * .45
                       and abs((q[1] + q[3] / 2) - cy) < r[3] * .45 for q in other)
            )
            rate = same / float(total_frames)
            if best is None or rate > best[0]:
                best = (rate, r)
    if not best or best[0] < .6:
        return None
    rate, (fx, fy, fw, fh, _) = best
    bw_, bh_ = fw * 2.6, fh * 2.9
    x0 = min(max(0, fx + fw / 2 - bw_ / 2), BW - bw_)
    y0 = min(max(0, fy + fh / 2 - bh_ * .45), BH - bh_)
    return rate, (x0 / BW, y0 / BH, bw_ / BW, bh_ / BH)


def _build_gpu_facecam_batch(frames, cands):
    """Return batched crop indices, full-frame indices, and the DirectML results."""
    images = []
    candidate_indices = {}
    candidate_sizes = {}
    for candidate_index, cand in enumerate(cands):
        sx, sy = BW / W, BH / H
        x0, y0 = int(cand["x0"] * sx), int(cand["y0"] * sy)
        width, height = int(cand["w"] * sx), int(cand["h"] * sy)
        for frame_index, frame in enumerate(frames):
            crop = frame[y0:y0 + height, x0:x0 + width]
            if crop.size == 0:
                continue
            min_side = min(crop.shape[:2])
            max_side = max(crop.shape[:2])
            desired_scale = max(1.0, 192.0 / min_side)
            scale = min(desired_scale, 640.0 / max_side)
            if scale > 1:
                crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            candidate_indices[(candidate_index, frame_index)] = len(images)
            candidate_sizes[(candidate_index, frame_index)] = (crop.shape[1], crop.shape[0])
            images.append(crop)

    full_frame_indices = []
    for frame in frames:
        full_frame_indices.append(len(images))
        images.append(frame)

    result = _run_face_inference_batch(images)
    if result is None:
        return None
    return result, candidate_indices, candidate_sizes, full_frame_indices


def detect_from_frames(frames):
    gray = _gray_small(frames)
    cands, game_motion = candidates(gray)
    gpu_batch = _build_gpu_facecam_batch(frames, cands)
    scored = []
    inference_device = "CPU (OpenCV)"

    if gpu_batch is None:
        # No supported NVIDIA GPU: keep the original OpenCV CPU detector.
        faces = Faces()
        for c in cands:
            if not is_live(c['calm']):
                continue
            rate = face_rate(frames, c, faces)
            c['faces'] = rate
            area = c['w'] * c['h'] / float(W * H)
            score = rate * .6 + c['border'] * .3 + min(c['contrast'] / 40.0, 1) * .1 + min(area / .12, 1) * .12
            if rate >= .35 and 0.015 <= area <= 0.32:
                scored.append((score, c))
        bf = borderless_face(frames, faces)
    else:
        batch, candidate_indices, candidate_sizes, full_indices = gpu_batch
        inference_device = batch["device"]
        detections = batch["faces"]
        for candidate_index, c in enumerate(cands):
            if not is_live(c['calm']):
                continue
            hits = 0
            for frame_index in range(len(frames)):
                index = candidate_indices.get((candidate_index, frame_index))
                if index is None:
                    continue
                crop_width, crop_height = candidate_sizes[(candidate_index, frame_index)]
                min_width, min_height = .16 * crop_width, .16 * crop_height
                if any(face[2] >= min_width and face[3] >= min_height
                       for face in detections[index]):
                    hits += 1
            rate = hits / float(len(frames))
            c['faces'] = rate
            area = c['w'] * c['h'] / float(W * H)
            score = rate * .6 + c['border'] * .3 + min(c['contrast'] / 40.0, 1) * .1 + min(area / .12, 1) * .12
            if rate >= .35 and 0.015 <= area <= 0.32:
                scored.append((score, c))
        full_detections = [detections[index] for index in full_indices]
        bf = _borderless_face_from_detections(full_detections)

    if scored:
        score, c = max(scored, key=lambda t: t[0])
        for _, o in sorted(scored, key=lambda t: -t[1]['w'] * t[1]['h']):
            area_o = o['w'] * o['h'] / float(W * H)
            inside = (o['x0'] <= c['x0'] + 2 and o['y0'] <= c['y0'] + 2 and
                      o['x0'] + o['w'] >= c['x0'] + c['w'] - 2 and
                      o['y0'] + o['h'] >= c['y0'] + c['h'] - 2)
            if o is not c and inside and area_o <= .28 and o['border'] >= max(.6, c['border'] - .35) and o['faces'] >= .85 * c['faces'] and o['w'] * o['h'] <= 6 * c['w'] * c['h']:
                c = o
                break
        return {
            'found': True, 'method': 'border+face', 'confidence': round(min(1.0, score), 2),
            'corner': c['corner'], 'inference_device': inference_device,
            'cam': {'x': round(c['x0'] / W, 4), 'y': round(c['y0'] / H, 4),
                    'w': round(c['w'] / W, 4), 'h': round(c['h'] / H, 4)},
            'face_rate': round(c['faces'], 2), 'border': round(c['border'], 2),
            'calm': round(c['calm'], 1), 'game_motion': round(game_motion, 1)
        }
    if bf:
        rate, (x, y, w, h) = bf
        return {
            'found': True, 'method': 'face-only', 'confidence': round(min(.85, rate * .8), 2),
            'inference_device': inference_device,
            'cam': {'x': round(x, 4), 'y': round(y, 4), 'w': round(w, 4), 'h': round(h, 4)},
            'face_rate': round(rate, 2), 'game_motion': round(game_motion, 1)
        }
    return {
        'found': False, 'confidence': 0.0, 'inference_device': inference_device,
        'game_motion': round(game_motion, 1),
        'reason': 'no rectangle with a steady border holds a face, and no face sits in the same corner spot in most frames'
    }


def detect(path):
    """Detect the facecam in a video file. When found the dict also carries a 'game' box (the whole frame)."""
    if cv2 is None:
        return {'found': False, 'reason': 'OpenCV is not installed (pip install opencv-contrib-python-headless)', 'confidence': 0.0}
    res = detect_from_frames(sample_frames(path))
    if res['found']:
        c = res['cam']
        inset = .006                                      # stay just inside the border so no frame line leaks into the clip
        res['cam'] = {'x': round(c['x'] + inset, 4), 'y': round(c['y'] + inset, 4), 'w': round(max(.02, c['w'] - 2 * inset), 4), 'h': round(max(.02, c['h'] - 2 * inset), 4)}
        res['game'] = {'x': 0, 'y': 0, 'w': 1, 'h': 1}
    return res


def attach(app, data):
    from fastapi import HTTPException

    @app.post('/facecam/detect')
    def facecam_detect(b: dict):
        sid = str(b.get('id', ''))
        p = Path(data) / (sid + '.mp4')
        if not sid.isalnum() or not p.exists():
            raise HTTPException(400, 'Add a video first (wait for the download to finish).')
        try:
            return detect(p)
        except (ValueError, FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
            raise HTTPException(400, 'Could not look for a facecam: ' + str(e)[:150])
