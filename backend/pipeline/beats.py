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


def manual(bpm: float, first_beat_s: float, duration_s: float) -> np.ndarray:
    return np.arange(first_beat_s, duration_s, 60.0 / bpm)
