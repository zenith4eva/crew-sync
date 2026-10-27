"""Shift test: delay one dancer's real motion signal by a known amount and check the measured offset matches.

Uses cached SAM tracks (no API calls), so run eval.dancetrack_switches first. Each dancer of each clip in turn
is shifted by 50, 100 and 200 ms; the measured shift is the median change in that dancer's offset vs the crew.

Usage: python -m eval.shift_test
"""
import json

import numpy as np

from backend import config
from backend.meta import sam_client
from backend.pipeline import beats, timing, tracks

SHIFTS_MS = (30, 50, 75, 100, 130, 200)  # includes sub-frame shifts (1 frame = 50 ms at 20 fps)
BPM = 120  # DanceTrack has no audio; any steady grid works since offsets are measured against the crew


def measure(motion: dict, beat: np.ndarray, fps: int, dancer: str, shift_s: float) -> float:
    n = len(motion[dancer])
    t = np.arange(n) / fps
    shifted = dict(motion)
    shifted[dancer] = np.interp(t - shift_s, t, motion[dancer], left=np.nan)  # NaN propagates gaps
    base = timing.offsets(motion, beat, fps)[dancer]
    moved = timing.offsets(shifted, beat, fps)[dancer]
    return float(np.nanmedian(moved - base))


def main() -> None:
    results = {s: [] for s in SHIFTS_MS}
    for row in json.loads((config.DATA_DIR / "eval" / "dancetrack_switches.json").read_text()):
        video = config.DATA_DIR / "eval" / f"{row['clip']}_30s.mp4"
        trk, n_frames = tracks.load(sam_client.track_video(video), row["dancers"])
        fps = 20
        beat = beats.manual(BPM, 0.5, n_frames / fps)
        motion = {i: t["motion"] for i, t in trk.items()}
        for dancer in motion:
            for s in SHIFTS_MS:
                results[s].append(measure(motion, beat, fps, dancer, s / 1000) * 1000)
    for s, vals in results.items():
        v = np.array([x for x in vals if not np.isnan(x)])
        err = np.abs(v - s)
        print(f"shift {s:3d} ms: measured median {np.median(v):5.0f} ms, median abs error {np.median(err):3.0f} ms, "
              f"within 25 ms on {np.mean(err <= 25):.0%} of {len(v)} dancers")


if __name__ == "__main__":
    main()
