"""Beat grid: detected from audio, or built from a manual BPM + first-beat tap."""
import numpy as np


def detect(audio_path: str) -> np.ndarray:
    """Beat times in seconds. Reading audio from MP4/MOV needs ffmpeg on PATH."""
    import librosa
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    # beat_track(y=...) aggregates onsets by median over frequency, which zeroes out narrow-band clicks and
    # sparse percussion; the mean-aggregated envelope works on both.
    env = librosa.onset.onset_strength(y=y, sr=sr)
    _, frames = librosa.beat.beat_track(onset_envelope=env, sr=sr, units="frames")
    return librosa.frames_to_time(frames, sr=sr)


def warm() -> None:
    """Run beat tracking once on noise so librosa's numba kernels compile at startup, not on the first upload
    (11 to 15 s on this machine; a numba cache dir does not help, the cost is ufunc compilation at import)."""
    import librosa
    librosa.beat.beat_track(y=np.random.default_rng(0).standard_normal(22050 * 2), sr=22050)


def manual(bpm: float, first_beat_s: float, duration_s: float) -> np.ndarray:
    return np.arange(first_beat_s, duration_s, 60.0 / bpm)
