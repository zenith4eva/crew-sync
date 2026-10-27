"""ffmpeg helpers. Uses the ffmpeg binary bundled with imageio-ffmpeg, so no system install is needed."""
import re
import subprocess
from pathlib import Path

import imageio_ffmpeg

from backend import config

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()


class MediaError(Exception):
    pass


def probe(path: Path) -> dict:
    """Duration (s), width, height and whether there is audio. Raises MediaError on unreadable files."""
    out = subprocess.run([FFMPEG, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    dur = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", out)
    size = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", out)
    if not dur or not size:
        raise MediaError("Couldn't read this file as a video. Upload an MP4 or MOV from a phone.")
    h, m, s = dur.groups()
    return {"duration": int(h) * 3600 + int(m) * 60 + float(s), "width": int(size[1]), "height": int(size[2]),
            "audio": "Audio:" in out}


def prepare(src: Path, video_out: Path, audio_out: Path) -> None:
    """Re-encode to H.264 at config.FPS, max 720p (SAM bills per frame), and extract mono audio for beats."""
    scale = f"scale=-2:'min({config.MAX_HEIGHT},ih)'"
    if probe(src)["audio"]:
        _run([FFMPEG, "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "22050", str(audio_out)])
    tmp = video_out.with_name("tmp_" + video_out.name)  # rename last, so video_out existing means prepare finished
    _run([FFMPEG, "-y", "-i", str(src), "-vf", f"fps={config.FPS},{scale}", "-c:v", "libx264",
          "-preset", "veryfast", "-pix_fmt", "yuv420p", "-an", str(tmp)])
    tmp.replace(video_out)


def camera_motion(video: Path, width: int = 160, step_s: float = 0.2) -> float:
    """Median camera drift in frame widths per second, from phase correlation of small grayscale frames.
    The static background dominates the correlation, so dancers moving barely register; a tripod reads ~0.
    ponytail: translation only (no zoom/rotation); good enough to catch a handheld phone."""
    import numpy as np
    proc = subprocess.run([FFMPEG, "-i", str(video), "-vf", f"fps={1 / step_s},scale={width}:-2,format=gray",
                           "-f", "rawvideo", "-"], capture_output=True)
    info = probe(video)
    h = round(info["height"] * width / info["width"] / 2) * 2
    frames = np.frombuffer(proc.stdout, np.uint8)[: (len(proc.stdout) // (width * h)) * width * h]
    frames = frames.reshape(-1, h, width).astype(float)
    if len(frames) < 3:
        return 0.0
    win = np.outer(np.hanning(h), np.hanning(width))
    shifts = []
    for a, b in zip(frames, frames[1:]):
        fa, fb = np.fft.fft2((a - a.mean()) * win), np.fft.fft2((b - b.mean()) * win)
        r = fa * np.conj(fb)
        corr = np.fft.ifft2(r / (np.abs(r) + 1e-9)).real
        dy, dx = np.unravel_index(np.argmax(corr), corr.shape)
        dy, dx = (dy if dy <= h // 2 else dy - h), (dx if dx <= width // 2 else dx - width)
        shifts.append(np.hypot(dx, dy) / width / step_s)
    return float(np.median(shifts))


def _run(cmd: list) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg failed: {proc.stderr.strip().splitlines()[-1] if proc.stderr else proc.returncode}")
