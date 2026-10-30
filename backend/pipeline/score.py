"""Crew Sync Score: per-dancer blend of timing and formation, crew = mean of dancers."""
import numpy as np

from backend import config
from backend.pipeline import formation, pose, timing


def dancer_score(t: float, f: float, p: float | None = None) -> float:
    """Weighted blend of the parts that were measured; a missing part's weight goes to the others."""
    parts = [(t, config.W_TIMING), (f, config.W_FORMATION)] if p is None else \
        list(zip((t, f, p), config.W_WITH_POSE))
    parts = [(v, w) for v, w in parts if not np.isnan(v)]
    return sum(v * w for v, w in parts) / sum(w for _, w in parts) if parts else np.nan


def _tag_moving(flags: list[dict], tracks: dict, beats: np.ndarray, fps: float) -> list[dict]:
    """flag["moving"]: the crew walked between formations during the flag's beats. Those flags were mostly judged
    wrong by hand (config.FLAG_MOVING); the UI and notes rank still ones first."""
    n = len(next(iter(tracks.values()))["feet"])
    bf = np.round(beats * fps).astype(int).clip(0, n - 1)
    heights = np.concatenate([t["box"][:, 3] - t["box"][:, 1] for t in tracks.values()])
    height = float(np.nanmedian(heights)) if np.any(~np.isnan(heights)) else 0.0
    for f in flags:
        b, e = f["start_beat"], f["end_beat"]
        move = formation._crew_move(tracks, bf[b - 1] if b else bf[b], bf[e]) / height if height else 0.0
        f["moving"] = bool(move >= config.FLAG_MOVING)
    return flags


def run(tracks: dict, beats: np.ndarray, fps: float, ref: dict | None = None, pose_beats: list | None = None) -> dict:
    """ref: optional {dancer: matched reference dancer's {motion, feet} on this clip's timeline}.
    pose_beats: optional per-beat pose.compare() output; turns on the pose part of the score."""
    n_frames = len(next(iter(tracks.values()))["motion"])
    beats = beats[(beats >= 0) & (beats * fps < n_frames)]
    ref = ref or {}
    offs = timing.offsets({i: t["motion"] for i, t in tracks.items()}, beats, fps,
                          refs={i: r["motion"] for i, r in ref.items()})
    form, per_beat = formation.scores(tracks, np.round(beats * fps).astype(int).clip(0, n_frames - 1),
                                      ref_feet={i: r["feet"] for i, r in ref.items()})
    pose_score, pose_flags = pose.scores(pose_beats, tracks, beats) if pose_beats is not None else ({}, [])
    dancers = {}
    for i in tracks:
        t = timing.score(offs[i])
        p = pose_score.get(i) if pose_beats is not None else None
        dancers[i] = {"timing": t, "formation": form[i], "score": dancer_score(t, form[i], p),
                      "offsets_ms": [None if np.isnan(o) else round(o * 1000) for o in offs[i]]}
        if p is not None:
            dancers[i]["pose"] = p
    valid = [d["score"] for d in dancers.values() if not np.isnan(d["score"])]
    crew = float(np.mean(valid)) if valid else np.nan
    lowest = min((i for i in dancers if not np.isnan(dancers[i]["score"])),
                 key=lambda i: dancers[i]["score"], default=None)
    return {"crew_score": crew, "lowest_dancer": lowest, "dancers": dancers,
            "flags": _tag_moving(timing.flags(offs, beats), tracks, beats, fps), "formation_by_beat": per_beat,
            "beats": beats.tolist(),
            "pose_flags": pose_flags if pose_beats is not None else None}
