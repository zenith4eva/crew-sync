"""Reference take (stretch 1): align a leader's or official take to the crew's by audio, optionally mirror it,
match crew dancers to reference dancers, and put reference tracks on the crew clip's timeline."""
import numpy as np
from scipy.optimize import linear_sum_assignment
from scipy.signal import correlate, correlation_lags

from backend import config
from backend.pipeline.formation import normalize

SR, HOP = 22050, 512


def _onsets(wav: str) -> np.ndarray:
    import librosa
    y, _ = librosa.load(wav, sr=SR, mono=True)
    env = librosa.onset.onset_strength(y=y, sr=SR, hop_length=HOP)
    return (env - env.mean()) / (env.std() or 1.0)


def align(main_wav: str, ref_wav: str) -> float:
    """Seconds to add to a crew-clip time to get the same moment in the reference (from audio onsets)."""
    a, b = _onsets(main_wav), _onsets(ref_wav)
    corr = correlate(a, b, mode="full")
    lags = correlation_lags(len(a), len(b), mode="full")
    dt = HOP / SR
    keep = np.abs(lags) * dt <= config.REF_MAX_LAG_S
    corr, lags = corr[keep], lags[keep]
    j = int(np.argmax(corr))
    shift = 0.0
    if 0 < j < len(corr) - 1:
        denom = corr[j - 1] - 2 * corr[j] + corr[j + 1]
        shift = 0.5 * (corr[j - 1] - corr[j + 1]) / denom if denom else 0.0
    return float(-(lags[j] + shift) * dt)  # crew time t matches reference time t + lag


def to_timeline(track: dict, lag_s: float, fps: float, n_frames: int, mirror_width: float | None) -> dict:
    """Reference motion and feet resampled onto the crew clip's frames. mirror_width flips x for mirrored takes."""
    t = np.arange(n_frames) / fps + lag_s
    src = np.arange(len(track["motion"])) / fps
    motion = np.interp(t, src, track["motion"], left=np.nan, right=np.nan)
    g = np.round(t * fps).astype(int)
    feet = np.full((n_frames, 2), np.nan)
    ok = (g >= 0) & (g < len(track["feet"]))
    feet[ok] = track["feet"][g[ok]]
    if mirror_width:
        feet[:, 0] = mirror_width - feet[:, 0]
    return {"motion": motion, "feet": feet}


def match(crew: dict, ref: dict) -> tuple[dict, int | None]:
    """{crew dancer: reference dancer} from the opening formation: the first frame where the most dancers of both
    takes are visible, compared after removing shift and scale. Returns (matches, frame used)."""
    n_frames = len(next(iter(crew.values()))["feet"])
    want = min(len(crew), len(ref))
    best, frame = -1, None
    for f in range(n_frames):
        c = sum(not np.isnan(t["feet"][f]).any() for t in crew.values())
        r = sum(not np.isnan(t["feet"][f]).any() for t in ref.values())
        if min(c, r) > best:
            best, frame = min(c, r), f
            if best >= want:
                break
    if frame is None or best < 2:
        return {}, None
    ci = [i for i, t in crew.items() if not np.isnan(t["feet"][frame]).any()]
    ri = [j for j, t in ref.items() if not np.isnan(t["feet"][frame]).any()]
    p = normalize(np.array([crew[i]["feet"][frame] for i in ci]))
    q = normalize(np.array([ref[j]["feet"][frame] for j in ri]))
    if p is None or q is None:
        return {}, None
    rows, cols = linear_sum_assignment(np.linalg.norm(p[:, None] - q[None], axis=2))
    return {ci[r]: ri[c] for r, c in zip(rows, cols)}, frame
