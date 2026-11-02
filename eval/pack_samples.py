"""Pack processed jobs as built-in samples for the hosted demo.

    python -m eval.pack_samples out.tar.gz <job_id>=<title> [<job_id>=<title> ...]

Each job contributes video.mp4, reel.mp4 (if rendered), results.json, status.json (with sample=true and the title)
and its cached SAM tracks, so the sample can be rescored, renamed and compared like any upload. input.mp4,
flag_check.mp4 and labels stay out. Extract the archive into data/ (the Dockerfile does this from SAMPLES_URL).
Only use footage you may publish: the four shipped samples are Pexels clips.
"""
import json
import sys
import tarfile
from pathlib import Path

from backend import config

KEEP = ("video.mp4", "reel.mp4", "results.json", "audio.wav")


def main() -> None:
    out, specs = Path(sys.argv[1]), [a.split("=", 1) for a in sys.argv[2:]]
    with tarfile.open(out, "w:gz") as tar:
        for job_id, title in specs:
            d = config.JOBS_DIR / job_id
            st = json.loads((d / "status.json").read_text(encoding="utf-8"))
            st.update(sample=True, title=title, consent=True)
            info = tarfile.TarInfo(f"jobs/{job_id}/status.json")
            data = json.dumps(st, indent=1).encode("utf-8")
            info.size = len(data)
            tar.addfile(info, fileobj=__import__("io").BytesIO(data))
            for name in KEEP:
                if (d / name).exists():
                    tar.add(d / name, arcname=f"jobs/{job_id}/{name}")
            tar.add(config.CACHE_DIR / st["tracks"], arcname=f"cache/{st['tracks']}")
            print(f"{job_id}: {title}")
    print(f"{out} ({out.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
