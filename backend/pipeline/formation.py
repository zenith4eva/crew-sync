"""Formation within the crew: even spacing and straight lines, measured on feet points in dancer heights."""
import numpy as np

from backend import config


def beat_ok(points: dict, height: float) -> dict:
    """points: {dancer: (x, y) feet in px} on one beat. Returns {dancer: in formation?}; empty if too few dancers.
    ponytail: feet y is raw screen depth (no perspective correction); add a floor homography if back rows score badly."""
    ids = [i for i, p in points.items() if not np.isnan(p).any()]
    if len(ids) < config.MIN_DANCERS_FORMATION or not height > 0:
        return {}
    p = np.array([points[i] for i in ids]) / height
    d = np.linalg.norm(p[:, None] - p[None], axis=2)
    np.fill_diagonal(d, np.inf)
    nn = d.min(axis=1)
    med = np.median(nn)
    spacing_ok = np.abs(nn - med) <= config.SPACING_TOL * med

    dist = _robust_line_dist(p)
    in_line = np.median(dist) < config.LINE_FIT_MAX
    line_ok = dist <= config.LINE_TOL if in_line else np.ones(len(ids), bool)
    return {i: bool(s and l) for i, s, l in zip(ids, spacing_ok, line_ok)}


def _line_dist(p: np.ndarray, fit: np.ndarray) -> np.ndarray:
    mean = fit.mean(axis=0)
    normal = np.linalg.svd(fit - mean)[2][1]  # direction of least spread
    return np.abs((p - mean) @ normal)


def _robust_line_dist(p: np.ndarray) -> np.ndarray:
    """Distance of each dancer from the crew's line, robust to a few dancers off it (least median of squares
    over lines through pairs, then a least-squares refit on the inliers). Plain least squares lets one
    dancer off the end of a line tilt the fit toward themselves. ponytail: O(n^3), fine for n <= 16."""
    n = len(p)
    best = min((_line_dist(p, p[[a, b]]) for a in range(n) for b in range(a + 1, n)), key=np.median)
    inliers = p[best <= config.LINE_TOL]
    return _line_dist(p, inliers) if len(inliers) >= 2 else best


def _crew_move(tracks: dict, f0: int, f1: int) -> float:
    """Median distance (px) dancers' feet moved between two frames; 0 if nobody is tracked in both."""
    d = [np.linalg.norm(t["feet"][f1] - t["feet"][f0]) for t in tracks.values()]
    d = [x for x in d if not np.isnan(x)]
    return float(np.median(d)) if d else 0.0


def scores(tracks: dict, beat_frames: np.ndarray) -> tuple[dict, list[dict]]:
    """Returns ({dancer: formation score 0-100 or NaN}, per-beat {dancer: ok} for the formation map)."""
    heights = np.concatenate([t["box"][:, 3] - t["box"][:, 1] for t in tracks.values()])
    height = float(np.nanmedian(heights)) if np.any(~np.isnan(heights)) else 0.0
    per_beat = []
    for k, f in enumerate(beat_frames):
        # Skip beats where the crew is moving between formations; only held formations are scored.
        if k and height and _crew_move(tracks, beat_frames[k - 1], f) / height >= config.HOLD_MAX_MOVE:
            per_beat.append({})
        else:
            per_beat.append(beat_ok({i: t["feet"][f] for i, t in tracks.items()}, height))
    out = {}
    for i in tracks:
        vals = [b[i] for b in per_beat if i in b]
        out[i] = float(np.mean(vals) * 100) if vals else np.nan
    return out, per_beat
