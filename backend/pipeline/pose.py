"""Body pose (stretch 2): compare each dancer's limb directions with the crew's, from SAM 3D Body 3D keypoints.

Keypoints are MHR70 (sam_3d_body/metadata/mhr70.py). Limbs are expressed in the dancer's own torso frame, so a
dancer facing slightly differently from the crew isn't penalized for it; only the limb shape is compared.
"""
import numpy as np

from backend import config

# MHR70 indices (sam_3d_body/metadata/mhr70.py)
L_SHOULDER, R_SHOULDER, L_ELBOW, R_ELBOW = 5, 6, 7, 8
L_HIP, R_HIP, L_KNEE, R_KNEE, L_ANKLE, R_ANKLE = 9, 10, 11, 12, 13, 14
L_WRIST, R_WRIST = 62, 41

LIMBS = {
    "left upper arm": (L_SHOULDER, L_ELBOW), "right upper arm": (R_SHOULDER, R_ELBOW),
    "left forearm": (L_ELBOW, L_WRIST), "right forearm": (R_ELBOW, R_WRIST),
    "left thigh": (L_HIP, L_KNEE), "right thigh": (R_HIP, R_KNEE),
    "left shin": (L_KNEE, L_ANKLE), "right shin": (R_KNEE, R_ANKLE),
}


def limb_directions(kp: np.ndarray) -> dict | None:
    """kp: (70, 3) keypoints. Returns {limb: unit vector in the torso frame}, or None if the torso is degenerate."""
    kp = np.asarray(kp, float)
    side = (kp[R_SHOULDER] + kp[R_HIP]) / 2 - (kp[L_SHOULDER] + kp[L_HIP]) / 2
    up = (kp[L_SHOULDER] + kp[R_SHOULDER]) / 2 - (kp[L_HIP] + kp[R_HIP]) / 2
    if np.linalg.norm(side) < 1e-6 or np.linalg.norm(up) < 1e-6:
        return None
    x = side / np.linalg.norm(side)
    y = up - (up @ x) * x
    if np.linalg.norm(y) < 1e-6:
        return None
    y /= np.linalg.norm(y)
    frame = np.stack([x, y, np.cross(x, y)])  # rows: right, up, forward
    out = {}
    for name, (a, b) in LIMBS.items():
        v = frame @ (kp[b] - kp[a])
        n = np.linalg.norm(v)
        if n > 1e-6:
            out[name] = v / n
    return out


def compare(beat_kps: dict) -> dict:
    """beat_kps: {dancer: (70, 3) keypoints} on one beat. Returns {dancer: {limb: degrees off the crew}} where the
    crew direction is the median of the other dancers' (leave-one-out, so a dancer can't pull the crew)."""
    dirs = {i: d for i, kp in beat_kps.items() if (d := limb_directions(kp))}
    out = {}
    for i, d in dirs.items():
        others = [o for j, o in dirs.items() if j != i]
        if not others:
            continue
        out[i] = {}
        for limb, v in d.items():
            vs = [o[limb] for o in others if limb in o]
            if not vs:
                continue
            crew = np.median(vs, axis=0)
            if np.linalg.norm(crew) < 1e-6:
                continue
            crew /= np.linalg.norm(crew)
            out[i][limb] = float(np.degrees(np.arccos(np.clip(v @ crew, -1, 1))))
    return out


def scores(per_beat: list[dict], dancers, beats: np.ndarray) -> tuple[dict, list[dict]]:
    """per_beat: compare() output per beat ({} where pose wasn't run). Returns ({dancer: pose score 0-100 or NaN},
    flags: runs of consecutive beats where the same limb of a dancer is more than POSE_TOL_DEG off, worst angle)."""
    score, flags = {}, []
    for i in dancers:
        ok, run = [], None
        for b, beat in enumerate(per_beat):
            limbs = beat.get(i) or {}
            worst = max(limbs, key=limbs.get) if limbs else None
            if worst is not None:
                ok.append(limbs[worst] <= config.POSE_TOL_DEG)
            off = worst is not None and not ok[-1]
            if run and (not off or worst != run["limb"]):
                flags.append(run)
                run = None
            if off:
                if run is None:
                    run = {"dancer": i, "start_beat": b, "end_beat": b, "time_s": float(beats[b]), "limb": worst, "deg": 0}
                run["end_beat"], run["deg"] = b, max(run["deg"], round(limbs[worst]))
        if run:
            flags.append(run)
        score[i] = float(np.mean(ok) * 100) if ok else np.nan
    return score, sorted(flags, key=lambda f: f["time_s"])
