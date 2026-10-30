"""Every threshold, weight and env setting lives here. Thresholds are starting values to tune on test clips."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Load KEY=VALUE lines from the gitignored .env; real environment variables win.
if (ROOT / ".env").exists():
    for _line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        _key, _sep, _value = _line.partition("=")
        if _sep and not _line.lstrip().startswith("#"):
            os.environ.setdefault(_key.strip(), _value.strip())
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"
JOBS_DIR = DATA_DIR / "jobs"

# Meta Model API
META_API_KEY = os.getenv("META_API_KEY", "")
META_API_BASE = os.getenv("META_API_BASE", "https://api.meta.ai/v1")
SAM_MODEL = os.getenv("SAM_MODEL", "sam-3.1")
MUSE_MODEL = os.getenv("MUSE_MODEL", "muse-spark-1.3")
SAM_PROMPT = "person"
SAM_MASK_ENCODING = "one_bit"  # smaller and faster than "lossless"; outlines don't need lossless
API_RETRIES = 4
API_TIMEOUT_S = 600

# Upload limits and ops
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", 500))
MAX_CLIP_SECONDS = int(os.getenv("MAX_CLIP_SECONDS", 90))
RETENTION_DAYS = int(os.getenv("RETENTION_DAYS", 7))
MAX_JOBS_PER_DAY = int(os.getenv("MAX_JOBS_PER_DAY", 50))
ALLOWED_ORIGIN = os.getenv("ALLOWED_ORIGIN", "http://localhost:5173")

# Processing
FPS = 15
MAX_HEIGHT = 720           # downscale before SAM; boxes come back in these pixels
ALLOWED_EXTS = {".mp4", ".mov"}
CAMERA_MOTION_MAX = 0.08   # frame widths/s of drift before we warn; tripod clips read <= 0.031 (1 px rounding), handheld ~0.2
MOTION_SMOOTH_FRAMES = 3       # on the mask-change signal, before differencing (tracks.motion_signal)
MOTION_DIFF_SMOOTH_FRAMES = 2  # on the differenced signal; 3 caught more delays but doubled the other flags

# Timing
TIMING_TOL_S = 0.100       # within ±100 ms of the crew median counts as in sync
FLAG_MIN_RUN = 2           # flag after this many consecutive off beats
                           # Oct 30: a per-dancer threshold (max(FLAG_TOL_S, K x that dancer's offset MAD)) was tried
                           # and dropped: K=1 68% caught / 3.9 false, K=2 32% / 2.9, vs fixed 71% / 4.1. The false
                           # flags aren't dancer-specific jitter.
FLAG_TOL_S = 0.120         # flag only beyond this (scoring keeps TIMING_TOL_S); eval.flag_test Oct 27:
                           # 0.10 -> 71% caught, 6.3 false/dancer-min; 0.12 -> 68%, 4.4
TIMING_MAX_LAG_S = 0.35    # largest offset we search for; a dancer further off reads as different choreography
TIMING_MIN_CORR = 0.5      # below this a dancer's movement doesn't match the crew's; that beat isn't scored
TIMING_WINDOW_BEATS = 2    # correlate over this many beats either side; DanceTrack sweep (Oct 27): 1 was too noisy
TIMING_MIN_VALID = 0.5     # share of a beat's window that must be tracked (and not overlapped) to time that beat
OVERLAP_MAX = 0.7          # don't time frames where another dancer's box covers more than this of a dancer's box.
                           # Oct 30, vs off: flag_test 150 ms caught 71% -> 71%, 250 ms 68% -> 62%, other flags
                           # 4.4 -> 4.1/dancer-min; shift_test unchanged; I.O.I 44 -> 31 flags, 8 of the 10 largest
                           # (all judged false by eye) gone, the one judged real kept

# Formation (distances are in dancer heights, so camera distance doesn't matter)
HOLD_TOL = 0.20            # max drift from a dancer's own spot during a held formation, in dancer heights.
                           # Oct 30 sweep on DanceTrack (5 clips): 0.10 scored pro crews 54-93, 0.15 65-96, 0.20 76-97;
                           # a 0.3-height sideways shove for 4 s was caught about equally (32-38%). The old even-spacing
                           # check (tol 0.35) caught 56% of those shoves but scored the same pros 52-86; relaxing it
                           # to 1.0 gave 73-94 and 35%, no better than none. Dropped.
LINE_FIT_MAX = 0.20        # crew counts as "in a line" when 3 of 4 dancers are closer than this to the fitted line
LINE_TOL = 0.15            # a dancer this far off the line is out of formation
MIN_DANCERS_FORMATION = 3
HOLD_MAX_MOVE = 0.12       # crew feet moving more than this (dancer heights per beat) = transition, not scored
MAX_RELIABLE_DANCERS = 9   # DanceTrack gate (Oct 27): 12 dancers gave 6 lasting identity switches in 30 s

# Reference take (stretch 1)
REF_FORMATION_TOL = 0.25   # max distance from the matched reference dancer's spot, in dancer heights
REF_MAX_LAG_S = 30         # search this far either way when aligning the two audio tracks

# Body pose (stretch 2): SAM 3D Body runs in its own Python env (torch + CUDA); unset POSE_PYTHON to turn it off
POSE_PYTHON = os.getenv("POSE_PYTHON", "")          # e.g. C:/envs/sam3d/python.exe
POSE_REPO = os.getenv("POSE_REPO", "")              # clone of github.com/facebookresearch/sam-3d-body
POSE_HF_REPO = os.getenv("POSE_HF_REPO", "facebook/sam-3d-body-dinov3")  # gated: request access on Hugging Face
POSE_SAMPLE_S = 0.25       # run pose on a frame this often; beats use the nearest, so a BPM change needs no rerun
POSE_TOL_DEG = 25          # a limb more than this far from the crew's is flagged
W_WITH_POSE = (0.4, 0.3, 0.3)  # timing, formation, pose weights when pose is on (PRD)

# Crew Sync Score
W_TIMING = 0.6
W_FORMATION = 0.4
