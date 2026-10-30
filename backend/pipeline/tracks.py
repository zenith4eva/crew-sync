"""Turn decoded SAM records into per-dancer arrays: presence, box, feet point and motion signal."""
import base64
import json
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d

from backend import config


def _mask(rec: dict) -> np.ndarray:
    h, w = rec["h"], rec["w"]
    m = np.unpackbits(np.frombuffer(base64.b64decode(rec["bits"]), np.uint8))[: h * w].reshape(h, w).astype(bool)
    x0, y0, x1, y1 = rec["box"]
    bh, bw = y1 - y0, x1 - x0
    if (h, w) != (bh, bw):  # mask may be coarser than its box; stretch to box size (nearest)
        m = m[np.arange(bh) * h // bh][:, np.arange(bw) * w // bw]
    return m


def crop_iou(a: tuple, b: tuple) -> float:
    """IoU of two masks given as (x0, y0, bool[h, w]) in frame pixels."""
    (ax, ay, am), (bx, by, bm) = a, b
    x0, y0 = max(ax, bx), max(ay, by)
    x1, y1 = min(ax + am.shape[1], bx + bm.shape[1]), min(ay + am.shape[0], by + bm.shape[0])
    inter = 0
    if x1 > x0 and y1 > y0:
        inter = np.count_nonzero(am[y0 - ay:y1 - ay, x0 - ax:x1 - ax] & bm[y0 - by:y1 - by, x0 - bx:x1 - bx])
    union = np.count_nonzero(am) + np.count_nonzero(bm) - inter
    return inter / union if union else 1.0


def relabel(dancer: str, frame: int, swaps) -> str:
    """Apply tap-to-fix swaps: each {frame, a, b} exchanges a and b from that frame to the end of the clip."""
    for s in swaps:
        if frame >= s["frame"] and dancer in (s["a"], s["b"]):
            dancer = s["b"] if dancer == s["a"] else s["a"]
    return dancer


def load(jsonl: Path, n_dancers: int, swaps=()) -> tuple[dict, int]:
    """Returns ({dancer_id: track}, n_frames). Keeps the n_dancers ids seen in the most frames."""
    by_id = defaultdict(dict)
    n_frames = 0
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                by_id[relabel(rec["id"], rec["f"], swaps)][rec["f"]] = rec
                n_frames = max(n_frames, rec["f"] + 1)
    keep = sorted(by_id, key=lambda i: len(by_id[i]), reverse=True)[:n_dancers]
    trk = {i: build_track(by_id[i], n_frames) for i in keep}
    for i, hidden in overlapped(trk).items():
        trk[i]["motion"][hidden] = np.nan  # a mask that overlaps a neighbor moves with them; don't time it
        trk[i]["motion"] = motion_signal(trk[i]["motion"])
    return trk, n_frames


def overlapped(trk: dict) -> dict:
    """{dancer: bool per frame}, True where another dancer's box covers more than OVERLAP_MAX of this one's.
    Checking flags by eye (I.O.I, Oct 29), 4 of the 10 largest came from masks merging with a neighbor's."""
    ids = list(trk)
    if len(ids) < 2:
        return {i: np.zeros(len(trk[i]["motion"]), bool) for i in ids}
    b = np.stack([trk[i]["box"] for i in ids])  # (dancers, frames, 4)
    w = np.minimum(b[:, None, :, 2], b[None, :, :, 2]) - np.maximum(b[:, None, :, 0], b[None, :, :, 0])
    h = np.minimum(b[:, None, :, 3], b[None, :, :, 3]) - np.maximum(b[:, None, :, 1], b[None, :, :, 1])
    area = (b[..., 2] - b[..., 0]) * (b[..., 3] - b[..., 1])
    with np.errstate(invalid="ignore", divide="ignore"):
        cover = np.clip(w, 0, None) * np.clip(h, 0, None) / area[:, None, :]
    cover[np.arange(len(ids)), np.arange(len(ids))] = 0
    return {i: np.nan_to_num(cover[k]).max(axis=0) > config.OVERLAP_MAX for k, i in enumerate(ids)}


def build_track(frames: dict, n_frames: int) -> dict:
    present = np.zeros(n_frames, bool)
    box = np.full((n_frames, 4), np.nan)
    feet = np.full((n_frames, 2), np.nan)
    motion = np.full(n_frames, np.nan)
    outline = [None] * n_frames
    prev = None
    for f in range(n_frames):
        rec = frames.get(f)
        if rec is None:
            prev = None
            continue
        m = _mask(rec)
        x0, y0 = rec["box"][:2]
        present[f] = True
        box[f] = rec["box"]
        rows = np.flatnonzero(m.any(axis=1))
        if rows.size:
            bottom = rows[-1]
            cols = np.flatnonzero(m[bottom])
            feet[f] = (x0 + cols.mean(), y0 + bottom)
            outline[f] = silhouette(m, rows, x0, y0)
        cur = (x0, y0, m)
        if prev is not None:
            motion[f] = 1.0 - crop_iou(prev, cur)
        prev = cur
    return {"present": present, "box": box, "feet": feet, "motion": motion, "outline": outline}


def motion_signal(change: np.ndarray) -> np.ndarray:
    """Per-frame motion signal from mask change (1 - IoU with the previous frame, NaN where untracked or overlapped):
    sqrt, smooth, then the frame-to-frame difference, smoothed again. Correlating the change in motion rather than
    motion itself sharpens the beat peaks. Hide overlapped frames before this, not after: the difference then also
    drops the first frame after each gap, which is a step, not motion. eval.flag_test, Oct 30, 150 ms delay: plain 71% caught / 4.1 false per dancer-min; sqrt alone 71% / 3.3;
    difference alone 79% / 3.6; this 76% / 1.6 (250 ms: 62% / 4.1 -> 82% / 1.6; shift test error <= 1 ms).
    Smoothing the difference over 3 frames instead of 2 gave 82% / 2.6. Scored dancer-beats 70% -> 63%; of those
    within 100 ms of the crew 65% -> 85%."""
    d = np.diff(smooth(np.sqrt(change), config.MOTION_SMOOTH_FRAMES), prepend=np.nan)
    return smooth(d, config.MOTION_DIFF_SMOOTH_FRAMES)


def silhouette(m: np.ndarray, rows: np.ndarray, x0: int, y0: int, samples: int = 24) -> list[int]:
    """Outline polygon as flat [x, y, ...] in frame pixels: left edge down, right edge up, on sampled rows.
    ponytail: outer silhouette only (gaps between arm and body fill in); trace real contours if outlines look blobby."""
    ys = [int(y) for y in np.unique(np.linspace(rows[0], rows[-1], min(samples, rows.size)).astype(int)) if m[y].any()]
    left = [(x0 + int(np.argmax(m[y])), y0 + y) for y in ys]
    right = [(x0 + m.shape[1] - 1 - int(np.argmax(m[y][::-1])), y0 + y) for y in reversed(ys)]
    return [v for p in left + right for v in p]


def smooth(signal: np.ndarray, frames: int) -> np.ndarray:
    """Moving average over this many frames that leaves gaps (NaN) as gaps."""
    valid = ~np.isnan(signal)
    s = uniform_filter1d(np.where(valid, signal, 0.0), frames, mode="nearest")
    w = uniform_filter1d(valid.astype(float), frames, mode="nearest")
    out = np.divide(s, w, out=np.full_like(s, np.nan), where=w > 0)
    out[~valid] = np.nan
    return out
