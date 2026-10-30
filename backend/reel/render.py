"""Sync Score Reel: a 20 s, 9:16 MP4 to share. Score reveal, the worst flagged moment, then the crew with overlays.
Shows only the crew number, never names a dancer (PRD: the results page names people, the Reel doesn't)."""
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.io import wavfile

from backend import config, media

W, H = 720, 1280
BG, TEXT, MUTED, ACCENT, RED = (0, 0, 0), (255, 255, 255), (180, 180, 180), (198, 242, 78), (229, 72, 77)
COLORS = ["#ff5d5d", "#3ddc84", "#4c8dff", "#ffc53d", "#ff9ecb", "#2fd3d3", "#ff8a3d", "#a3e635",
          "#f472b6", "#94a3b8", "#facc15", "#7cc4ff", "#34d399", "#fb7185", "#e0b07a", "#fdba74"]
REVEAL_S, MOMENT_S, TOTAL_S = 4, 6, 20
PANEL_MAX_H = 860


FONTS = Path(__file__).parent / "fonts"  # Inter 4.1, SIL Open Font License (fonts/OFL.txt)


@lru_cache(maxsize=None)
def font(size: int, weight: str = "Regular"):
    """weight: Regular, SemiBold or ExtraBold. Falls back to Pillow's default face if the file is missing."""
    try:
        return ImageFont.truetype(str(FONTS / f"Inter-{weight}.ttf"), size)
    except OSError:
        return ImageFont.load_default(size=size)


def render(job: Path, res: dict, out: Path) -> Path:
    fps = res["fps"]
    info = media.probe(job / "video.mp4")
    s = min(W / info["width"], PANEL_MAX_H / info["height"])
    pw, ph = int(info["width"] * s) // 2 * 2, int(info["height"] * s) // 2 * 2
    ids = sorted(res["dancers"], key=lambda i: (len(i), i))
    color = {d: COLORS[k % len(COLORS)] for k, d in enumerate(ids)}
    score = res["crew_score"] or 0
    duration = res["n_frames"] / fps

    worst = min(res["flags"], key=lambda f: (f.get("moving", False), -abs(f["offset_ms"])), default=None)
    segments = []  # (source start s, length s, kind)
    if worst:
        start = min(max(worst["time_s"] - 2, 0), max(duration - MOMENT_S, 0))
        segments.append((start, min(MOMENT_S, duration), "moment"))
    rest = TOTAL_S - REVEAL_S - sum(seg[1] for seg in segments)
    segments.append((0.0, min(rest, duration), "crew"))

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "reel.wav"
        _audio(job / "audio.wav", segments, audio)
        enc = subprocess.Popen(
            [media.FFMPEG, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(fps), "-i", "-",
             "-i", str(audio), "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-c:a", "aac",
             "-shortest", "-movflags", "+faststart", str(out)],
            stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            for k in range(REVEAL_S * fps):
                enc.stdin.write(_reveal(score, k / (REVEAL_S * fps * 0.65)).tobytes())
            for start, length, kind in segments:
                first = round(start * fps)
                for k, frame in enumerate(_frames(job / "video.mp4", start, length, pw, ph)):
                    img = _panel(frame, res, first + k, s, color, kind, worst, score, pw, ph)
                    enc.stdin.write(img.tobytes())
        finally:
            enc.stdin.close()
        if enc.wait() != 0:
            raise media.MediaError("Reel export failed while encoding.")
    return out


def _reveal(score: float, progress: float) -> Image.Image:
    p = min(progress, 1.0)
    shown = round(score * (1 - (1 - p) ** 3))
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.text((W / 2, 470), "Crew Sync Score", font=font(40), fill=MUTED, anchor="mm")
    d.text((W / 2, 640), str(shown), font=font(260, "ExtraBold"), fill=TEXT, anchor="mm")
    d.rounded_rectangle((160, 790, 160 + 400 * p * shown / max(score, 1), 802), 6, fill=ACCENT)
    d.text((W / 2, 1160), "every dancer, in sync", font=font(32), fill=MUTED, anchor="mm")
    return img


def _panel(frame, res, f, s, color, kind, worst, score, pw, ph) -> Image.Image:
    img = Image.new("RGB", (W, H), BG)
    x0, y0 = (W - pw) // 2, (H - ph) // 2 + 40
    img.paste(Image.fromarray(frame), (x0, y0))
    d = ImageDraw.Draw(img)
    f = min(f, res["n_frames"] - 1)
    for dancer, ov in res["overlay"].items():
        b = ov["box"][f]
        if not b:
            continue
        flagged = kind == "moment" and dancer == worst["dancer"]
        line = dict(outline=RED if flagged else color[dancer], width=6 if flagged else 3)
        o = (ov.get("outline") or [None] * (f + 1))[f]
        if o:
            d.polygon([(x0 + o[k] * s, y0 + o[k + 1] * s) for k in range(0, len(o), 2)], **line)
        else:
            d.rectangle((x0 + b[0] * s, y0 + b[1] * s, x0 + b[2] * s, y0 + b[3] * s), **line)
    if kind == "moment":
        d.text((W / 2, 150), "The moment to fix", font=font(48, "SemiBold"), fill=TEXT, anchor="mm")
        word = "late" if worst["offset_ms"] > 0 else "early"
        d.text((W / 2, y0 + ph + 90), f"{abs(worst['offset_ms'])} ms {word}", font=font(64, "ExtraBold"), fill=RED, anchor="mm")
        d.text((W / 2, y0 + ph + 160), "one dancer, out of step with the crew", font=font(28), fill=MUTED, anchor="mm")
    else:
        d.text((W / 2, 130), "Crew Sync Score", font=font(36), fill=MUTED, anchor="mm")
        d.text((W / 2, 230), str(round(score)), font=font(130, "ExtraBold"), fill=TEXT, anchor="mm")
        d.text((W / 2, H - 110), "scored with Crew Sync", font=font(30), fill=MUTED, anchor="mm")
    return img


def _frames(video: Path, start: float, length: float, pw: int, ph: int):
    proc = subprocess.Popen(
        [media.FFMPEG, "-ss", f"{start:.3f}", "-i", str(video), "-t", f"{length:.3f}", "-vf", f"scale={pw}:{ph}",
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    size = pw * ph * 3
    try:
        while len(buf := proc.stdout.read(size)) == size:
            yield np.frombuffer(buf, np.uint8).reshape(ph, pw, 3)
    finally:
        proc.stdout.close()
        proc.wait()


def _audio(src: Path, segments, out: Path) -> None:
    """Silence under the reveal, then the crew's own audio for each video segment."""
    sr = 22050
    parts = [np.zeros(REVEAL_S * sr, np.int16)]
    data = wavfile.read(src)[1] if src.exists() else np.zeros(0, np.int16)
    for start, length, _ in segments:
        a = data[int(start * sr): int((start + length) * sr)]
        parts.append(np.pad(a, (0, max(0, int(length * sr) - len(a)))))
    wavfile.write(out, sr, np.concatenate(parts).astype(np.int16))
