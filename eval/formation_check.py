"""Formation score per DanceTrack clip on cached tracks (no API calls), for comparing formation scoring changes.

Usage: python -m eval.formation_check
"""
import json

import numpy as np

from backend import config
from backend.meta import sam_client
from backend.pipeline import beats, formation, tracks

FPS, BPM = 20, 120


SHOVE_H, SHOVE_S = 0.3, 4.0  # each dancer in turn is pushed sideways by SHOVE_H dancer heights for SHOVE_S seconds


def run() -> dict:
    """Per clip: crew formation score and share of beats scored. Plus the shove test: a dancer pushed sideways
    while the crew holds a formation should lose the hold on the beats after the push. Shoves that start during a
    transition become the dancer's new spot and aren't counted: without a reference take they're not catchable."""
    rng = np.random.default_rng(0)
    out, catchable, caught = {}, 0, 0
    for row in json.loads((config.DATA_DIR / "eval" / "dancetrack_switches.json").read_text()):
        trk, n = tracks.load(sam_client.track_video(config.DATA_DIR / "eval" / f"{row['clip']}_30s.mp4"), row["dancers"])
        bf = np.round(beats.manual(BPM, 0.5, n / FPS) * FPS).astype(int).clip(0, n - 1)
        height = float(np.nanmedian(np.concatenate([t["box"][:, 3] - t["box"][:, 1] for t in trk.values()])))
        form, per_beat = formation.scores(trk, bf)
        vals = [v for v in form.values() if not np.isnan(v)]
        out[row["clip"]] = {"crew": float(np.mean(vals)) if vals else float("nan"),
                            "scored_beats": sum(1 for b in per_beat if b) / len(per_beat)}
        for i in trk:
            s0 = int(rng.integers(n // 4, 3 * n // 4))
            k0 = max((k for k in range(len(bf)) if bf[k] < s0), default=None)  # last beat before the shove
            if k0 is None or not per_beat[k0] or i not in per_beat[k0]:
                continue  # the crew wasn't holding a formation when the shove started
            after = [k for k in range(k0 + 1, len(bf)) if s0 <= bf[k] < s0 + SHOVE_S * FPS]
            after = after[:next((j for j, k in enumerate(after) if not per_beat[k]), len(after))]  # same hold only
            if not after:
                continue
            catchable += 1
            shoved = {j: dict(t) for j, t in trk.items()}
            feet = trk[i]["feet"].copy()
            feet[s0:s0 + int(SHOVE_S * FPS), 0] += SHOVE_H * height
            shoved[i]["feet"] = feet
            _, pb = formation.scores(shoved, bf)
            caught += any(i in pb[k] and not pb[k][i] for k in after)
    out["shove"] = {"catchable": catchable, "caught": caught}
    return out


if __name__ == "__main__":
    r = run()
    for clip, v in r.items():
        if clip != "shove":
            print(f"{clip}: formation {v['crew']:.0f}, {v['scored_beats']:.0%} of beats scored")
    s = r["shove"]
    print(f"sideways shove of {SHOVE_H} heights inside a hold caught in {s['caught']} of {s['catchable']} "
          f"({s['caught'] / s['catchable']:.0%})")
