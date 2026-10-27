"""Per-beat hit times, offsets against the crew median, flags and timing scores."""
import warnings

import numpy as np

from backend import config


def hit_times(motion: np.ndarray, beats: np.ndarray, fps: float) -> np.ndarray:
    """Motion peak nearest each beat, refined between frames with a parabola. NaN where untracked or no peak."""
    hits = np.full(len(beats), np.nan)
    half = np.median(np.diff(beats)) / 2 if len(beats) > 1 else 0.25
    n = len(motion)
    for b, t in enumerate(beats):
        lo, hi = max(int(np.ceil((t - half) * fps)), 1), min(int(np.floor((t + half) * fps)), n - 2)
        peaks = [f for f in range(lo, hi + 1)
                 if motion[f] >= motion[f - 1] and motion[f] > motion[f + 1]]  # NaN compares False
        if not peaks:
            continue
        f = min(peaks, key=lambda p: abs(p / fps - t))
        y0, y1, y2 = motion[f - 1], motion[f], motion[f + 1]
        denom = y0 - 2 * y1 + y2
        shift = 0.5 * (y0 - y2) / denom if denom else 0.0
        hits[b] = (f + shift) / fps
    return hits


def offsets(hits: dict) -> dict:
    """Each dancer's hit minus the crew median hit on that beat (s). Positive = late."""
    ids = list(hits)
    m = np.vstack([hits[i] for i in ids])
    counts = np.sum(~np.isnan(m), axis=0)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN beats are expected; masked below
        med = np.nanmedian(m, axis=0)
    med[counts < 2] = np.nan  # one dancer can't be out of sync with themselves
    return {i: m[k] - med for k, i in enumerate(ids)}


def flags(offs: dict, beats: np.ndarray) -> list[dict]:
    """Runs of FLAG_MIN_RUN+ consecutive beats off by more than TIMING_TOL_S."""
    out = []
    for i, o in offs.items():
        off = np.abs(o) > config.TIMING_TOL_S  # NaN -> False, so gaps break runs
        b = 0
        while b < len(off):
            if not off[b]:
                b += 1
                continue
            e = b
            while e + 1 < len(off) and off[e + 1]:
                e += 1
            if e - b + 1 >= config.FLAG_MIN_RUN:
                out.append({"dancer": i, "start_beat": b, "end_beat": e, "time_s": float(beats[b]),
                            "offset_ms": round(float(np.mean(o[b:e + 1])) * 1000)})
            b = e + 1
    return sorted(out, key=lambda x: x["time_s"])


def score(off: np.ndarray) -> float:
    """Share of scored beats within tolerance, 0-100. NaN if no beat was scored."""
    valid = off[~np.isnan(off)]
    return float(np.mean(np.abs(valid) <= config.TIMING_TOL_S) * 100) if valid.size else np.nan
