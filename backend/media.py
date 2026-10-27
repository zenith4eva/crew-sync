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


def _run(cmd: list) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg failed: {proc.stderr.strip().splitlines()[-1] if proc.stderr else proc.returncode}")
