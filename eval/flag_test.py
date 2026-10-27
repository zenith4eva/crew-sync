"""Flag test: how often the app flags a real delay, and how often it flags dancers who weren't delayed.

On cached DanceTrack tracks (no API calls), each dancer in turn gets a known delay (default 150 ms) for 4 s at a
seeded random point. Detection = a late flag on that dancer overlapping the window. Every other flag on these
professional crews is counted as a false alarm (an upper bound: some may be real).

Usage: python -m eval.flag_test [--delay-ms 150]
"""
import argparse
import json

import numpy as np

from backend import config
from backend.meta import sam_client
from backend.pipeline import beats, timing, tracks

FPS, BPM, WINDOW_S = 20, 120, 4.0


def inject(motion: np.ndarray, start_s: float, delay_s: float) -> np.ndarray:
    """Delay the signal by delay_s inside [start_s, start_s + WINDOW_S)."""
    t = np.arange(len(motion)) / FPS
    out = motion.copy()
    w = (t >= start_s) & (t < start_s + WINDOW_S)
    out[w] = np.interp(t[w] - delay_s, t, motion)
    return out


def run(delay_s: float) -> dict:
    rng = np.random.default_rng(0)
    hits = trials = false = 0
    dancer_minutes = 0.0
    for row in json.loads((config.DATA_DIR / "eval" / "dancetrack_switches.json").read_text()):
        trk, n = tracks.load(sam_client.track_video(config.DATA_DIR / "eval" / f"{row['clip']}_30s.mp4"), row["dancers"])
        grid = beats.manual(BPM, 0.5, n / FPS)
        motion = {i: t["motion"] for i, t in trk.items()}
        for i in motion:
            start = float(rng.uniform(3, n / FPS - WINDOW_S - 3))
            offs = timing.offsets({**motion, i: inject(motion[i], start, delay_s)}, grid, FPS)
            fl = timing.flags(offs, grid)
            trials += 1
            hits += any(f["dancer"] == i and f["offset_ms"] > 0 and grid[f["start_beat"]] < start + WINDOW_S
                        and grid[f["end_beat"]] >= start for f in fl)
            false += sum(1 for f in fl if f["dancer"] != i)
            dancer_minutes += (len(motion) - 1) * n / FPS / 60
    return {"detected": hits / trials, "trials": trials, "false_per_dancer_min": false / dancer_minutes}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay-ms", type=float, default=150)
    r = run(ap.parse_args().delay_ms / 1000)
    print(f"{ap.parse_args().delay_ms:.0f} ms delay detected in {r['detected']:.0%} of {r['trials']} trials; "
          f"{r['false_per_dancer_min']:.1f} other flags per dancer-minute")


if __name__ == "__main__":
    main()
