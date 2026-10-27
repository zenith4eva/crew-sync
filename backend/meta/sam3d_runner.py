"""SAM 3D Body on sampled frames, one person per SAM 3.1 box. Runs in its own Python env (torch, CUDA and the
sam-3d-body repo, per its INSTALL.md), not the app's: the app calls it with POSE_PYTHON. Standalone on purpose.

Input JSON: {"video": path, "repo": sam-3d-body clone, "hf_repo": "facebook/sam-3d-body-dinov3",
             "frames": {"<frame>": {"<SAM id>": [x1, y1, x2, y2], ...}, ...}}
Output JSON: {"<frame>": {"<SAM id>": [[x, y, z] * 70 MHR70 keypoints], ...}, ...}

Usage: <pose python> sam3d_runner.py in.json out.json
"""
import json
import sys

import cv2
import numpy as np


def main() -> None:
    job = json.load(open(sys.argv[1], encoding="utf-8"))
    sys.path.insert(0, job["repo"])
    from notebook.utils import setup_sam_3d_body  # from the sam-3d-body repo

    # No detector, segmentor or FOV model: SAM 3.1 already found every dancer.
    est = setup_sam_3d_body(hf_repo_id=job["hf_repo"], detector_name="", segmentor_name="", fov_name="")
    cap = cv2.VideoCapture(job["video"])
    out = {}
    for f in sorted(job["frames"], key=int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        ok, bgr = cap.read()
        if not ok:
            continue
        ids = list(job["frames"][f])
        boxes = np.array([job["frames"][f][i] for i in ids], dtype=np.float32)
        people = est.process_one_image(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), bboxes=boxes)
        out[f] = {i: np.asarray(p["pred_keypoints_3d"]).round(4).tolist() for i, p in zip(ids, people)}
    json.dump(out, open(sys.argv[2], "w", encoding="utf-8"))


if __name__ == "__main__":
    main()
