"""Crew Sync Score: per-dancer blend of timing and formation, crew = mean of dancers."""
import numpy as np

from backend import config
from backend.pipeline import formation, timing


def dancer_score(t: float, f: float) -> float:
    if np.isnan(t) and np.isnan(f):
        return np.nan
    if np.isnan(f):
        return t
    if np.isnan(t):
        return f
    return config.W_TIMING * t + config.W_FORMATION * f


def run(tracks: dict, beats: np.ndarray, fps: float) -> dict:
    n_frames = len(next(iter(tracks.values()))["motion"])
    beats = beats[(beats >= 0) & (beats * fps < n_frames)]
    hits = {i: timing.hit_times(t["motion"], beats, fps) for i, t in tracks.items()}
    offs = timing.offsets(hits)
    form, per_beat = formation.scores(tracks, np.round(beats * fps).astype(int).clip(0, n_frames - 1))
    dancers = {}
    for i in tracks:
        t = timing.score(offs[i])
        dancers[i] = {"timing": t, "formation": form[i], "score": dancer_score(t, form[i]),
                      "offsets_ms": [None if np.isnan(o) else round(o * 1000) for o in offs[i]]}
    valid = [d["score"] for d in dancers.values() if not np.isnan(d["score"])]
    crew = float(np.mean(valid)) if valid else np.nan
    lowest = min((i for i in dancers if not np.isnan(dancers[i]["score"])),
                 key=lambda i: dancers[i]["score"], default=None)
    return {"crew_score": crew, "lowest_dancer": lowest, "dancers": dancers,
            "flags": timing.flags(offs, beats), "formation_by_beat": per_beat, "beats": beats.tolist()}
