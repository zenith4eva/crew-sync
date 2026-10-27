"""Compare the app's flagged moments with moments a person marked by watching the clip at quarter speed.

Easiest: open the job, turn on "Hand-label this clip" on the results page and mark moments with L / E. Then:
    python -m eval.hand_label_check <job_id>

Or from a file (eval/hand_labels/<anything>.json), using the names shown on the results page:
    [{"dancer": "Mina", "time_s": 42.1, "kind": "late"}, {"dancer": "Dancer 3", "time_s": 50.0, "kind": "early"}]
    python -m eval.hand_label_check <job_id> eval/hand_labels/clip1.json
"""
import json
import sys
from pathlib import Path

from backend import jobs
from backend.pipeline.labels import agreement


def main() -> None:
    job_id = sys.argv[1]
    d = jobs.job_dir(job_id)
    res = json.loads((d / "results.json").read_text(encoding="utf-8"))
    if len(sys.argv) > 2:
        by_name = {n.lower(): i for i, n in jobs.display_names(res, jobs.read_status(job_id)["names"]).items()}
        labels = [{**lab, "dancer": by_name.get(lab["dancer"].strip().lower(), lab["dancer"])}
                  for lab in json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))]
    else:
        labels = json.loads((d / "labels.json").read_text(encoding="utf-8"))
    r = agreement(res["flags"], res["beats"], labels)
    pct = lambda v: "n/a" if v is None else f"{v:.0%}"
    print(f"{r['flags_agreed']}/{r['flags']} app flags match a hand label (precision {pct(r['precision'])})")
    print(f"{r['labels_caught']}/{r['labels']} hand labels caught by the app (recall {pct(r['recall'])})")


if __name__ == "__main__":
    main()
