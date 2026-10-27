"""Synthetic crew clip with known answers, for end-to-end tests and offline demos without a Meta API key.

Five block "dancers" step sideways on every beat of a 120 BPM click track. Dancer 2 is 150 ms late from
8 s to 12 s; dancer 4 steps out of the line from 14 s to 17 s. Besides the MP4, this writes the matching
decoded tracks into the SAM cache, keyed by the prepared video's hash, so the pipeline never calls the API.

Usage: python -m eval.make_synthetic data/synthetic.mp4
"""
import base64
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.special import erf

from backend import config, media
from backend.meta import sam_client

W, H, FPS, SECONDS, BPM = 640, 360, 15, 20, 120
N = 5
COLORS = [(230, 80, 80), (80, 200, 120), (90, 140, 240), (240, 200, 60), (200, 90, 220)]
LATE = (2, 8.0, 12.0, 0.15)
OUT_OF_LINE = (4, 14.0, 17.0, 45)


def beat_times():
    return np.arange(0.5, SECONDS, 60 / BPM)


def x_offset(t, dancer):
    """Sideways steps: smooth step centered on each beat, alternating direction. Speed peaks on the beat."""
    x = 0.0
    for k, b in enumerate(beat_times()):
        if dancer == LATE[0] and LATE[1] <= b < LATE[2]:
            b += LATE[3]
        x += (1 if k % 2 == 0 else -1) * 12 * (1 + erf((t - b) / (0.07 * np.sqrt(2)))) / 2
    return x


def dancer_mask(t, d):
    """Returns (x0, y0, bool mask) for dancer d at time t: a body block plus a head."""
    cx = 120 + d * 100 + x_offset(t, d)
    feet_y = 300 + (OUT_OF_LINE[3] if d == OUT_OF_LINE[0] and OUT_OF_LINE[1] <= t < OUT_OF_LINE[2] else 0)
    x0, y0 = int(round(cx - 20)), int(feet_y - 130)
    m = np.zeros((130, 40), bool)
    m[30:, 4:36] = True       # body
    m[0:28, 10:30] = True     # head
    return x0, y0, m


def render(path: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "click.wav"
        sr = 22050
        audio = np.zeros(sr * SECONDS, np.float32)
        click = np.sin(2 * np.pi * 1000 * np.arange(int(0.03 * sr)) / sr) * np.hanning(int(0.03 * sr))
        for b in beat_times():
            i = int(b * sr)
            audio[i:i + len(click)] += click[: len(audio) - i]
        wavfile.write(wav, sr, (audio * 0.8 * 32767).astype(np.int16))
        cmd = [media.FFMPEG, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
               "-i", "-", "-i", str(wav), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        for f in range(FPS * SECONDS):
            img = np.full((H, W, 3), 28, np.uint8)
            img[300:, :] = 45  # floor
            for d in range(N):
                x0, y0, m = dancer_mask(f / FPS, d)
                img[y0:y0 + m.shape[0], x0:x0 + m.shape[1]][m] = COLORS[d]
            proc.stdin.write(img.tobytes())
        proc.stdin.close()
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed to render the synthetic clip")


def tracks_jsonl() -> str:
    lines = []
    for f in range(FPS * SECONDS):
        for d in range(N):
            x0, y0, m = dancer_mask(f / FPS, d)
            h, w = m.shape
            lines.append(json.dumps({"f": f, "id": str(d * 3 + 1), "box": [x0, y0, x0 + w, y0 + h], "h": h, "w": w,
                                     "bits": base64.b64encode(np.packbits(m.ravel())).decode()}))
    return "\n".join(lines) + "\n"


def seed_cache(path: Path) -> Path:
    """Write tracks under the hash of the video the job pipeline will produce from `path`."""
    with tempfile.TemporaryDirectory() as tmp:
        prepared = Path(tmp) / "video.mp4"
        media.prepare(path, prepared, Path(tmp) / "audio.wav")
        key = sam_client._hash(prepared)
    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out = config.CACHE_DIR / f"{key}.tracks.jsonl"
    out.write_text(tracks_jsonl(), encoding="utf-8")
    return out


def make(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    render(path)
    seed_cache(path)
    return path


if __name__ == "__main__":
    print(make(Path(sys.argv[1] if len(sys.argv) > 1 else config.DATA_DIR / "synthetic.mp4")))
