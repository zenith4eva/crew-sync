"""Check clips: is a flag real? For each flag, the flagged dancer next to the dancer closest to the crew on those
beats, cropped, slowed down, with a lime bar on every beat. Watch whether the flagged dancer hits each move after
(late) or before (early) the other. Then mark what you saw in Hand-label mode and run eval.hand_label_check.

    python -m eval.flag_clips <job_id> [--top 10] [--speed 0.25]

Writes data/jobs/<job_id>/flag_check.mp4 (no audio). Uses the original upload when it's there, for its frame rate.
"""
import argparse
import json
import subprocess

import numpy as np
from PIL import Image, ImageDraw

from backend import jobs, media
from backend.reel.render import ACCENT, BG, MUTED, RED, TEXT, _frames, font

W, H, OUT_FPS = 1920, 1080, 30
PANEL_W, PANEL_H, TOP = 900, 820, 150
PAD_S, BEAT_FLASH_S = 0.6, 0.1


def partner(res: dict, flag: dict) -> str | None:
    """The other dancer with the smallest mean offset over the flagged beats."""
    b, e = flag["start_beat"], flag["end_beat"] + 1
    best, best_off = None, np.inf
    for d, v in res["dancers"].items():
        offs = [abs(o) for o in v["offsets_ms"][b:e] if o is not None]
        if d != flag["dancer"] and offs and np.mean(offs) < best_off:
            best, best_off = d, float(np.mean(offs))
    return best


def crop_box(res: dict, dancer: str, f0: int, f1: int, scale: float, size: tuple) -> tuple:
    """One fixed crop for the whole clip: the dancer's boxes over the window, padded, in source pixels."""
    boxes = np.array([b for b in res["overlay"][dancer]["box"][f0:f1] if b], float) * scale
    if not len(boxes):
        return 0, 0, size[0], size[1]
    x0, y0 = boxes[:, :2].min(0)
    x1, y1 = boxes[:, 2:].max(0)
    px, py = (x1 - x0) * 0.15, (y1 - y0) * 0.1
    return int(max(x0 - px, 0)), int(max(y0 - py, 0)), int(min(x1 + px, size[0])), int(min(y1 + py, size[1]))


def fit(img: Image.Image) -> Image.Image:
    s = min(PANEL_W / img.width, PANEL_H / img.height)
    return img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--top", type=int, default=10, help="largest flags to show; 0 = all")
    ap.add_argument("--speed", type=float, default=0.25)
    a = ap.parse_args()

    d = jobs.job_dir(a.job_id)
    res = json.loads((d / "results.json").read_text(encoding="utf-8"))
    name = jobs.display_names(res, jobs.read_status(a.job_id)["names"])
    fps, beats = res["fps"], np.array(res["beats"])
    track, src = media.probe(d / "video.mp4"), d / "video.mp4"
    if (d / "input.mp4").exists():
        up = media.probe(d / "input.mp4")
        if abs(up["width"] / up["height"] - track["width"] / track["height"]) < 0.01:  # skip rotated phone uploads
            src, track = d / "input.mp4", {**track, "scale": up["width"] / track["width"], "size": (up["width"], up["height"])}
    scale, size = track.get("scale", 1.0), track.get("size", (track["width"], track["height"]))

    flags = sorted(res["flags"], key=lambda f: -abs(f["offset_ms"]))[:a.top or None]
    flags.sort(key=lambda f: f["time_s"])
    out = d / "flag_check.mp4"
    enc = subprocess.Popen(
        [media.FFMPEG, "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(OUT_FPS), "-i", "-",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
         str(out)], stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        for n, fl in enumerate(flags, 1):
            other = partner(res, fl)
            t0 = max(beats[fl["start_beat"]] - PAD_S, 0)
            t1 = beats[fl["end_beat"]] + PAD_S
            f0, f1 = int(t0 * fps), int(t1 * fps) + 1
            crops = [(fl["dancer"], RED, f"{name[fl['dancer']]}, flagged")]
            if other:
                crops.append((other, ACCENT, f"{name[other]}, closest to the crew"))
            boxes = [crop_box(res, c[0], f0, f1, scale, size) for c in crops]
            frames = list(_frames(src, t0, t1 - t0, *size))
            word = "late" if fl["offset_ms"] > 0 else "early"
            title = (f"Flag {n} of {len(flags)}   ·   {name[fl['dancer']]}   ·   {abs(fl['offset_ms'])} ms {word}"
                     f"   ·   {int(fl['time_s'] // 60)}:{fl['time_s'] % 60:04.1f}")
            for k in range(round((t1 - t0) / a.speed * OUT_FPS)):
                t = t0 + k / OUT_FPS * a.speed
                frame = Image.fromarray(frames[min(int((t - t0) / (t1 - t0) * len(frames)), len(frames) - 1)])
                on_beat = np.any(np.abs(beats - t) <= BEAT_FLASH_S / 2)
                img = Image.new("RGB", (W, H), BG)
                dr = ImageDraw.Draw(img)
                dr.text((W / 2, 60), title, font=font(40, "SemiBold"), fill=TEXT, anchor="mm")
                dr.text((W / 2, 112), f"{a.speed:g}x speed   ·   lime bar = beat   ·   {t:.2f} s",
                        font=font(28), fill=MUTED, anchor="mm")
                for j, ((dancer, color, label), box) in enumerate(zip(crops, boxes)):
                    panel = fit(frame.crop(box))
                    cx = W / 2 + (j - (len(crops) - 1) / 2) * (PANEL_W + 40)
                    x = int(cx - panel.width / 2)
                    img.paste(panel, (x, TOP))
                    o = res["overlay"][dancer]["outline"][min(int(t * fps), res["n_frames"] - 1)]
                    if o:  # outline the dancer, since the crop also shows neighbors
                        k = panel.width / (box[2] - box[0])
                        dr.polygon([(x + (o[i] * scale - box[0]) * k, TOP + (o[i + 1] * scale - box[1]) * k)
                                    for i in range(0, len(o), 2)], outline=color, width=4)
                    dr.rectangle((x - 3, TOP - 3, x + panel.width + 2, TOP + panel.height + 2), outline=color, width=3)
                    dr.text((cx, TOP + PANEL_H + 40), label, font=font(32, "SemiBold"), fill=color, anchor="mm")
                if on_beat:
                    dr.rectangle((0, H - 30, W, H), fill=ACCENT)
                enc.stdin.write(img.tobytes())
            print(f"flag {n}/{len(flags)}: {name[fl['dancer']]} {fl['offset_ms']:+d} ms at {fl['time_s']:.1f} s"
                  f" vs {name[other] if other else 'nobody'}")
    finally:
        enc.stdin.close()
    if enc.wait() != 0:
        raise media.MediaError("Check clip export failed while encoding.")
    print(out)


if __name__ == "__main__":
    main()
