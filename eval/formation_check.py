"""Formation score per DanceTrack clip on cached tracks (no API calls), for comparing formation scoring changes.

Usage: python -m eval.formation_check
"""
import json

import numpy as np

from backend import config
from backend.meta import sam_client
from backend.pipeline import beats, formation, tracks

FPS, BPM = 20, 120


def run() -> dict:
    out = {}
    for row in json.loads((config.DATA_DIR / "eval" / "dancetrack_switches.json").read_text()):
        trk, n = tracks.load(sam_client.track_video(config.DATA_DIR / "eval" / f"{row['clip']}_30s.mp4"), row["dancers"])
        grid = beats.manual(BPM, 0.5, n / FPS)
        form, per_beat = formation.scores(trk, np.round(grid * FPS).astype(int).clip(0, n - 1))
        vals = [v for v in form.values() if not np.isnan(v)]
        out[row["clip"]] = {"crew": float(np.mean(vals)) if vals else float("nan"),
                            "scored_beats": sum(1 for b in per_beat if b) / len(per_beat)}
    return out


if __name__ == "__main__":
    for clip, r in run().items():
        print(f"{clip}: formation {r['crew']:.0f}, {r['scored_beats']:.0%} of beats scored")
