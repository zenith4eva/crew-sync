"""Day-2 gate: SAM 3.1 identity switches per clip on DanceTrack (CC BY 4.0).

Download a DanceTrack split (val is fine) so it looks like <split>/dancetrackXXXX/{img1/,gt/gt.txt,seqinfo.ini}.
Each clip's first --seconds are encoded to MP4, tracked with SAM (cached by video hash, so reruns are free),
and matched to ground truth per frame by box IoU. A switch is a ground-truth dancer whose matched SAM id
changes (the standard MOT IDSW count). We keep the N longest SAM tracks, N = dancers in ground truth, like the app.

Usage: python -m eval.dancetrack_switches path/to/dancetrack/val --clips 5 --seconds 30
Pass: at most 1 switch per clip on at least 4 of 5 clips.
"""
import argparse
import configparser
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from backend import config, media
from backend.meta import sam_client

IOU_MATCH = 0.5


def iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Pairwise IoU of [x1, y1, x2, y2] boxes, shapes (n, 4) and (m, 4)."""
    x1 = np.maximum(a[:, None, 0], b[None, :, 0])
    y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2])
    y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    area = lambda r: (r[:, 2] - r[:, 0]) * (r[:, 3] - r[:, 1])
    return inter / (area(a)[:, None] + area(b)[None, :] - inter)


def count_switches(gt: dict, pred: dict) -> dict:
    """gt, pred: {frame: {id: [x1, y1, x2, y2]}}. Returns switches, matched share and per-switch detail."""
    last = {}
    switches, matched, total = [], 0, 0
    for f in sorted(gt):
        g_ids, p_ids = list(gt[f]), list(pred.get(f, {}))
        total += len(g_ids)
        if not g_ids or not p_ids:
            continue
        m = iou(np.array([gt[f][i] for i in g_ids], float), np.array([pred[f][i] for i in p_ids], float))
        rows, cols = linear_sum_assignment(-m)
        for r, c in zip(rows, cols):
            if m[r, c] < IOU_MATCH:
                continue
            matched += 1
            g, p = g_ids[r], p_ids[c]
            if g in last and last[g] != p:
                switches.append({"frame": f, "gt": g, "from": last[g], "to": p})
            last[g] = p
    return {"switches": len(switches), "matched": matched / total if total else 0.0, "detail": switches}


def load_gt(seq: Path, n_frames: int) -> dict:
    gt = defaultdict(dict)
    for line in (seq / "gt" / "gt.txt").read_text().splitlines():
        f, i, x, y, w, h = (float(v) for v in line.split(",")[:6])
        if f <= n_frames:
            gt[int(f) - 1][str(int(i))] = [x, y, x + w, y + h]
    return gt


def load_pred(jsonl: Path, n_keep: int) -> dict:
    by_id = defaultdict(dict)
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            by_id[rec["id"]][rec["f"]] = rec["box"]
    keep = sorted(by_id, key=lambda i: len(by_id[i]), reverse=True)[:n_keep]
    pred = defaultdict(dict)
    for i in keep:
        for f, box in by_id[i].items():
            pred[f][i] = box
    return pred


def encode(seq: Path, fps: int, n_frames: int, out: Path) -> None:
    if out.exists():
        return
    subprocess.run([media.FFMPEG, "-y", "-loglevel", "error", "-framerate", str(fps), "-i", str(seq / "img1" / "%08d.jpg"),
                    "-frames:v", str(n_frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("split", type=Path)
    ap.add_argument("--clips", type=int, default=5)
    ap.add_argument("--seconds", type=int, default=30)
    args = ap.parse_args()

    out_dir = config.DATA_DIR / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for seq in sorted(p for p in args.split.iterdir() if (p / "gt" / "gt.txt").exists())[: args.clips]:
        ini = configparser.ConfigParser()
        ini.read(seq / "seqinfo.ini")
        fps = int(ini["Sequence"]["frameRate"])
        n_frames = min(int(ini["Sequence"]["seqLength"]), fps * args.seconds)
        video = out_dir / f"{seq.name}_{args.seconds}s.mp4"
        encode(seq, fps, n_frames, video)
        gt = load_gt(seq, n_frames)
        n_dancers = len({i for f in gt.values() for i in f})
        res = count_switches(gt, load_pred(sam_client.track_video(video), n_dancers))
        rows.append({"clip": seq.name, "dancers": n_dancers, **res})
        print(f"{seq.name}: {res['switches']} switches, {res['matched']:.0%} of dancer-frames matched, {n_dancers} dancers")

    passed = sum(r["switches"] <= 1 for r in rows)
    print(f"\n{passed}/{len(rows)} clips with at most 1 switch. Gate: at least 4 of 5.")
    (out_dir / "dancetrack_switches.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
