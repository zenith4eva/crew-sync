"""Every threshold, weight and env setting lives here. Thresholds are starting values to tune on test clips."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
CACHE_DIR = DATA_DIR / "cache"

# Meta Model API
META_API_KEY = os.getenv("META_API_KEY", "")
META_API_BASE = os.getenv("META_API_BASE", "https://api.meta.ai/v1")
SAM_MODEL = os.getenv("SAM_MODEL", "sam-3.1")
MUSE_MODEL = os.getenv("MUSE_MODEL", "muse-spark-1.2")
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
MOTION_SMOOTH_FRAMES = 3

# Timing
TIMING_TOL_S = 0.100       # within ±100 ms of the crew median counts as in sync
FLAG_MIN_RUN = 2           # flag after this many consecutive off beats

# Formation (distances are in dancer heights, so camera distance doesn't matter)
SPACING_TOL = 0.35         # nearest-neighbor gap may differ from the crew median gap by this fraction
LINE_FIT_MAX = 0.20        # crew counts as "in a line" when RMS distance from the fitted line is below this
LINE_TOL = 0.15            # a dancer this far off the line is out of formation
MIN_DANCERS_FORMATION = 3

# Crew Sync Score
W_TIMING = 0.6
W_FORMATION = 0.4
