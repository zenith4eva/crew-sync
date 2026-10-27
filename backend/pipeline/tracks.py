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


def load(jsonl: Path, n_dancers: int) -> tuple[dict, int]:
    """Returns ({dancer_id: track}, n_frames). Keeps the n_dancers ids seen in the most frames."""
    by_id = defaultdict(dict)
    n_frames = 0
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rec = json.loads(line)
                by_id[rec["id"]][rec["f"]] = rec
                n_frames = max(n_frames, rec["f"] + 1)
    keep = sorted(by_id, key=lambda i: len(by_id[i]), reverse=True)[:n_dancers]
    return {i: build_track(by_id[i], n_frames) for i in keep}, n_frames


def build_track(frames: dict, n_frames: int) -> dict:
    present = np.zeros(n_frames, bool)
    box = np.full((n_frames, 4), np.nan)
    feet = np.full((n_frames, 2), np.nan)
    motion = np.full(n_frames, np.nan)
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
        cur = (x0, y0, m)
        if prev is not None:
            motion[f] = 1.0 - crop_iou(prev, cur)
        prev = cur
    return {"present": present, "box": box, "feet": feet, "motion": smooth(motion)}


def smooth(signal: np.ndarray) -> np.ndarray:
    """Moving average that leaves gaps (NaN) as gaps."""
    valid = ~np.isnan(signal)
    s = uniform_filter1d(np.where(valid, signal, 0.0), config.MOTION_SMOOTH_FRAMES, mode="nearest")
    w = uniform_filter1d(valid.astype(float), config.MOTION_SMOOTH_FRAMES, mode="nearest")
    out = np.divide(s, w, out=np.full_like(s, np.nan), where=w > 0)
    out[~valid] = np.nan
    return out
