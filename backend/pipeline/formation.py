"""Formation from feet points, in dancer heights. Within the crew: straight lines, and each dancer holding their spot
in the shape the crew took at the start of a hold (shift and scale removed, so a V or staggered rows score as well
as a line). Against a reference take: each dancer's position vs their matched reference dancer, same normalization."""
import numpy as np

from backend import config


def beat_ok(points: dict, height: float) -> dict:
    """points: {dancer: (x, y) feet in px} on one beat. Returns {dancer: on the crew's line?} when the crew is in a
    line, all True otherwise; empty if too few dancers. An even-spacing check was dropped Oct 30: on DanceTrack
    it failed 30% of professional dancer-beats (pairs and asymmetric shapes are choreography, not errors).
    ponytail: feet y is raw screen depth (no perspective correction); add a floor homography if back rows score badly."""
    ids = [i for i, p in points.items() if not np.isnan(p).any()]
    if len(ids) < config.MIN_DANCERS_FORMATION or not height > 0:
        return {}
    p = np.array([points[i] for i in ids]) / height
    dist = _robust_line_dist(p)
    in_line = np.percentile(dist, 75) < config.LINE_FIT_MAX  # 3 of 4 on it; a V is two lines, not one with outliers
    ok = dist <= config.LINE_TOL if in_line else np.ones(len(ids), bool)
    return {i: bool(l) for i, l in zip(ids, ok)}


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
    """How far (px) the crew's feet moved between two frames: the upper median, so it stays near 0 unless more
    than half the dancers moved (a plain median of 4 with one mover averages them in and reads as a transition).
    0 if nobody is tracked in both."""
    d = sorted(np.linalg.norm(t["feet"][f1] - t["feet"][f0]) for t in tracks.values())
    d = [x for x in d if not np.isnan(x)]
    return float(d[len(d) // 2]) if d else 0.0


def normalize(p: np.ndarray) -> np.ndarray | None:
    """Remove overall shift and scale: centroid at 0, RMS distance from it 1."""
    c = p - p.mean(axis=0)
    s = np.sqrt(np.mean(np.sum(c ** 2, axis=1)))
    return c / s if s > 0 else None


def reference_beat_ok(points: dict, ref_points: dict, height: float, tol: float = config.REF_FORMATION_TOL) -> dict:
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
    return {i: bool(e <= tol) for i, e in zip(ids, err)}


def hold_ok(points: dict, anchor: dict, height: float) -> dict:
    """Each dancer vs their own spot on the hold's first beat. The crew's shift since then is the median move of the
    OTHER dancers (so the one who moved can't hide in the centroid); no scale change, the camera doesn't zoom."""
    ids = [i for i in points if i in anchor and not np.isnan(points[i]).any() and not np.isnan(anchor[i]).any()]
    if len(ids) < config.MIN_DANCERS_FORMATION or not height > 0:
        return {}
    move = np.array([points[i] - anchor[i] for i in ids])
    out = {}
    for k, i in enumerate(ids):
        crew = np.median(np.delete(move, k, axis=0), axis=0)
        out[i] = bool(np.linalg.norm(move[k] - crew) / height <= config.HOLD_TOL)
    return out


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
    per_beat, anchor = [], None
    for k, f in enumerate(beat_frames):
        # Skip beats where the crew is moving between formations; only held formations are scored.
        if k and height and _crew_move(tracks, beat_frames[k - 1], f) / height >= config.HOLD_MAX_MOVE:
            per_beat.append({})
            anchor = None
            continue
        points = {i: t["feet"][f] for i, t in tracks.items()}
        ok = beat_ok(points, height)
        if ok and anchor:
            # Shape stability: each dancer vs their own spot on the first beat of this hold.
            held = hold_ok(points, anchor, height)
            ok = {i: v and held.get(i, True) for i, v in ok.items()}
        anchor = anchor or (points if ok else None)
        per_beat.append(ok)
    return _per_dancer(tracks, per_beat), per_beat


def _per_dancer(tracks: dict, per_beat: list[dict]) -> dict:
    out = {}
    for i in tracks:
        vals = [b[i] for b in per_beat if i in b]
        out[i] = float(np.mean(vals) * 100) if vals else np.nan
    return out
