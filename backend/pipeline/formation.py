"""Formation from feet points. Within the crew: even spacing and straight lines, in dancer heights.
Against a reference take: each dancer's position vs their matched reference dancer, after removing shift and scale."""
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


def normalize(p: np.ndarray) -> np.ndarray | None:
    """Remove overall shift and scale: centroid at 0, RMS distance from it 1."""
    c = p - p.mean(axis=0)
    s = np.sqrt(np.mean(np.sum(c ** 2, axis=1)))
    return c / s if s > 0 else None


def reference_beat_ok(points: dict, ref_points: dict, height: float) -> dict:
    """Each dancer vs their matched reference dancer on one beat. The reference formation is shifted and scaled
    onto the crew's, then each dancer's distance from their spot is measured in the crew's dancer heights."""
    ids = [i for i in points if i in ref_points and not np.isnan(points[i]).any() and not np.isnan(ref_points[i]).any()]
    if len(ids) < config.MIN_DANCERS_FORMATION or not height > 0:
        return {}
    p, q = np.array([points[i] for i in ids]), np.array([ref_points[i] for i in ids])
    p, q = p - p.mean(axis=0), q - q.mean(axis=0)
    q_rms = np.sqrt(np.mean(np.sum(q ** 2, axis=1)))
    if q_rms == 0:
        return {}
    q *= np.sqrt(np.mean(np.sum(p ** 2, axis=1))) / q_rms
    err = np.linalg.norm(p - q, axis=1) / height
    return {i: bool(e <= config.REF_FORMATION_TOL) for i, e in zip(ids, err)}


def scores(tracks: dict, beat_frames: np.ndarray, ref_feet: dict | None = None) -> tuple[dict, list[dict]]:
    """Returns ({dancer: formation score 0-100 or NaN}, per-beat {dancer: ok} for the formation map).
    ref_feet: optional {dancer: matched reference dancer's feet on this clip's timeline}. With it, every beat is
    scored against the reference, transitions included; without it, held formations are scored within the crew."""
    heights = np.concatenate([t["box"][:, 3] - t["box"][:, 1] for t in tracks.values()])
    height = float(np.nanmedian(heights)) if np.any(~np.isnan(heights)) else 0.0
    if ref_feet:
        per_beat = [reference_beat_ok({i: tracks[i]["feet"][f] for i in ref_feet},
                                      {i: ref_feet[i][f] for i in ref_feet}, height) for f in beat_frames]
        return _per_dancer(tracks, per_beat), per_beat
    per_beat = []
    for k, f in enumerate(beat_frames):
        # Skip beats where the crew is moving between formations; only held formations are scored.
        if k and height and _crew_move(tracks, beat_frames[k - 1], f) / height >= config.HOLD_MAX_MOVE:
            per_beat.append({})
        else:
            per_beat.append(beat_ok({i: t["feet"][f] for i, t in tracks.items()}, height))
    return _per_dancer(tracks, per_beat), per_beat


def _per_dancer(tracks: dict, per_beat: list[dict]) -> dict:
    out = {}
    for i in tracks:
        vals = [b[i] for b in per_beat if i in b]
        out[i] = float(np.mean(vals) * 100) if vals else np.nan
    return out
