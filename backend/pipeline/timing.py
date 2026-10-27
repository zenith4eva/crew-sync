"""Per-beat timing offsets against the crew, flags and timing scores.

Offsets come from cross-correlating each dancer's motion signal with the rest of the crew's around each beat.
Picking the motion peak nearest the beat (the PRD's first idea) fails on real tracks: real motion has a peak every
few frames, so a dancer 100-200 ms late just matches a neighboring peak and reads as on time (eval/shift_test.py).
"""
import warnings

import numpy as np

from backend import config


def _zscore(x: np.ndarray) -> np.ndarray:
    v = x[~np.isnan(x)]
    if v.size < 2 or v.std() == 0:
        return np.full_like(x, np.nan)
    return (x - v.mean()) / v.std()


def offsets(motion: dict, beats: np.ndarray, fps: float, refs: dict | None = None) -> dict:
    """{dancer: per-beat offset in s vs the crew}. Positive = late. NaN where untracked, or where the dancer's
    movement doesn't resemble the crew's (different choreography for that dancer, or occlusion).
    refs: optional {dancer: matched reference dancer's motion on this clip's timeline}; those dancers are timed
    against their reference dancer instead of the crew."""
    refs = refs or {}
    ids = list(motion)
    z = np.vstack([_zscore(motion[i]) for i in ids]) if ids else np.empty((0, 0))
    out = {i: np.full(len(beats), np.nan) for i in ids}
    if len(ids) < 2 and not refs:
        return out  # one dancer can't be out of sync with themselves
    n = z.shape[1]
    period = np.median(np.diff(beats)) if len(beats) > 1 else 0.5
    w = max(2, round(config.TIMING_WINDOW_BEATS * period * fps))
    max_lag = max(1, round(config.TIMING_MAX_LAG_S * fps))
    for k, i in enumerate(ids):
        if i in refs:
            ref = _zscore(refs[i])
        elif len(ids) < 2:
            continue
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN frames are expected
                ref = np.nanmedian(np.delete(z, k, axis=0), axis=0)  # leave-one-out, so a dancer can't pull the crew
        x = z[k]
        for b, t in enumerate(beats):
            c = round(t * fps)
            lo, hi = c - w, c + w
            if lo - max_lag < 0 or hi + max_lag > n:
                continue
            r = ref[lo:hi]
            if np.isnan(r).mean() > 0.2:
                continue
            corr = np.full(2 * max_lag + 1, np.nan)
            for j, lag in enumerate(range(-max_lag, max_lag + 1)):
                seg = x[lo + lag:hi + lag]
                ok = ~np.isnan(seg) & ~np.isnan(r)
                if ok.mean() >= 0.8 and seg[ok].std() > 0 and r[ok].std() > 0:
                    corr[j] = np.corrcoef(seg[ok], r[ok])[0, 1]
            if np.all(np.isnan(corr)) or np.nanmax(corr) < config.TIMING_MIN_CORR:
                continue
            j = int(np.nanargmax(corr))
            if j in (0, len(corr) - 1):
                continue  # best match at the edge of the search: the real offset may lie outside it, so don't guess
            shift = 0.0
            if not np.isnan(corr[j - 1]) and not np.isnan(corr[j + 1]):
                denom = corr[j - 1] - 2 * corr[j] + corr[j + 1]
                shift = 0.5 * (corr[j - 1] - corr[j + 1]) / denom if denom else 0.0
            out[i][b] = (j - max_lag + shift) / fps
    return out


def flags(offs: dict, beats: np.ndarray) -> list[dict]:
    """Runs of FLAG_MIN_RUN+ consecutive beats off by more than FLAG_TOL_S."""
    out = []
    for i, o in offs.items():
        off = np.abs(o) > config.FLAG_TOL_S  # NaN -> False, so gaps break runs
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
                            "offset_ms": round(float(np.median(o[b:e + 1])) * 1000)})
            b = e + 1
    return sorted(out, key=lambda x: x["time_s"])


def score(off: np.ndarray) -> float:
    """Share of scored beats within tolerance, 0-100. NaN if no beat was scored."""
    valid = off[~np.isnan(off)]
    return float(np.mean(np.abs(valid) <= config.TIMING_TOL_S) * 100) if valid.size else np.nan
