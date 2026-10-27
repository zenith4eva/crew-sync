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

    centered = p - p.mean(axis=0)
    normal = np.linalg.svd(centered)[2][1]  # direction of least spread
    dist = np.abs(centered @ normal)
    in_line = np.sqrt(np.mean(dist ** 2)) < config.LINE_FIT_MAX
    line_ok = dist <= config.LINE_TOL if in_line else np.ones(len(ids), bool)
    return {i: bool(s and l) for i, s, l in zip(ids, spacing_ok, line_ok)}


def scores(tracks: dict, beat_frames: np.ndarray) -> tuple[dict, list[dict]]:
    """Returns ({dancer: formation score 0-100 or NaN}, per-beat {dancer: ok} for the formation map)."""
    heights = np.concatenate([t["box"][:, 3] - t["box"][:, 1] for t in tracks.values()])
    height = float(np.nanmedian(heights)) if np.any(~np.isnan(heights)) else 0.0
    per_beat = [beat_ok({i: t["feet"][f] for i, t in tracks.items()}, height) for f in beat_frames]
    out = {}
    for i in tracks:
        vals = [b[i] for b in per_beat if i in b]
        out[i] = float(np.mean(vals) * 100) if vals else np.nan
    return out, per_beat
