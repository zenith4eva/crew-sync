# Crew Sync

A dance crew films a run-through and gets back who is out of step with the crew, where the formation breaks, and a Crew Sync Score to share.

Built for the Meta Global AI Developer Hackathon (indie track), October 26 to November 4, 2026. All code was written during the hackathon.

## How it works

1. **Track:** SAM 3.1 (Meta Model API) segments every dancer with the prompt "person" and keeps each identity across the clip.
2. **Beat grid:** librosa finds the beats in the audio. You can set the BPM and first beat by hand when rehearsal audio is noisy.
3. **Timing:** each dancer's motion signal (frame-to-frame mask change) is cross-correlated with the rest of the crew's around every beat. The lag is that dancer's offset. A crew that is late together still scores 100.
4. **Formation:** feet points (bottom of each mask) give a top-down map. On each beat where the crew holds a formation (not walking to a new one), it checks spacing to neighbors and, when the crew is in a line, distance from it. The line fit ignores dancers who are off it.
5. **Score:** dancer score = 0.6 timing + 0.4 formation. The crew score is the mean.
6. **Coaching:** Muse Spark turns the numbers into 3 to 5 fixes as structured JSON. If Muse is unavailable, the notes are built from the numbers and labelled as such.
7. **Share:** a 20 s, 9:16 Sync Score Reel with the score reveal, the worst moment and the crew with outlines. It shows only the crew number and never names a dancer.
8. **Before and after:** pick an earlier take on the results page to see the crew score and each named dancer's change.
9. **Reference take (optional):** upload the leader's or the official video to score against it instead of the crew. The two takes are aligned by cross-correlating their audio, a mirror switch handles mirror-mode practice videos, and dancers are matched to reference dancers on the opening formation (editable). Timing is then measured against each dancer's match, and formation is each dancer's distance from their match's spot after removing overall shift and scale. The reference video is deleted as soon as it is tracked and is never shown or put in the Reel.

10. **Body pose (optional):** SAM 3D Body (open weights, run locally on a GPU) estimates each dancer's 3D joints every 0.25 s, using SAM 3.1's boxes. Each limb's direction in the dancer's own torso frame is compared with the crew's, so a dancer facing a little differently isn't penalized. Limbs more than 25° off are flagged, and the score weights become 0.4 timing, 0.3 formation, 0.3 pose.

The app also warns when the camera moves (phase correlation on the background), when more than 9 dancers are in frame, and when fewer dancers are found than expected.

| Meta model | Job |
| --- | --- |
| SAM 3.1 | Find every dancer, masks and boxes, stable identity per dancer |
| Muse Spark 1.3 | Coaching notes as structured JSON |

## Evaluation

All numbers below are from October 27, 2026, on the first 5 clips of the DanceTrack validation split, first 30 s each (4 to 12 dancers). Reproduce with the commands below.

**Identity tracking (SAM 3.1).** We matched SAM tracks to DanceTrack ground truth by box IoU every frame and counted identity switches.

| Clip | Dancers | Raw switches (MOT IDSW) | Lasting ≥ 1 s |
| --- | --- | --- | --- |
| 0004 | 4 | 2 | 0 |
| 0005 | 4 | 3 | 1 |
| 0007 | 8 | 2 | 0 |
| 0010 | 6 | 10 | 0 |
| 0014 | 12 | 18 | 6 |

Most raw switches are flips of 1 to 13 frames while two dancers overlap; they self-correct and need no fix. Counting switches that last at least 1 s, 4 of 5 clips have at most one. We chose the 1 s cutoff after the first run, so both numbers are shown. With 12 dancers, tracking mixes people up often, so the app warns above 9 dancers and offers tap-to-fix.

**Timing accuracy (shift test).** We delayed one dancer's real motion signal by a known amount and measured the offset, for each of the 34 dancers in turn.

| Shift | 30 ms | 50 ms | 75 ms | 100 ms | 130 ms | 200 ms |
| --- | --- | --- | --- | --- | --- | --- |
| Median measured | 36 | 50 | 73 | 100 | 135 | 200 |
| Median error | 6 | 0 | 3 | 0 | 5 | 0 |

Every dancer was within 25 ms at every shift. Our first method, the motion peak nearest each beat, measured 9 ms for a 100 ms shift on these real tracks and was replaced.

**Limits we know about.**
- On these professional crews, 65% of scored beats fall within ±100 ms of the crew. We don't know yet how much of the rest is real and how much is measurement noise; hand-labelled clips will tell.
- 70% of dancer-beats are scored. A beat is skipped when that dancer is untracked or their movement doesn't match the crew's (different choreography, occlusion).
- Formation uses raw screen depth with no perspective correction, so back-row spacing reads smaller than it is.
- Without a reference, formation assumes even spacing. Staggered rows and V shapes score low even when danced well: on DanceTrack, line-based clips score 83 to 90, other clips 53 to 64. Scoring against a reference take avoids this.
- Body pose is tested only against a stand-in for SAM 3D Body, because its weights are gated (see below). The keypoint indices and API come from the sam-3d-body source.
## Run it

Needs Python 3.11 and Node 18+. ffmpeg comes from the `imageio-ffmpeg` package.

```bash
py -3.11 -m venv .venv
.venv/Scripts/pip install -r requirements.txt
(cd backend/meta && npm install)
(cd frontend && npm install && npm run build)
```

Put your key in `.env` (gitignored):

```
META_API_KEY=...
```

```bash
.venv/Scripts/python -m uvicorn backend.api.app:app --port 8000
```

Open http://localhost:8000.

To try it without a key, `.venv/Scripts/python -m eval.make_synthetic data/synthetic.mp4` writes a test clip with known answers and caches its tracks; upload it with 5 dancers.

Tests: `.venv/Scripts/python -m pytest -q`

Evaluation (DanceTrack val unzipped into `data/dancetrack/val`):

```bash
.venv/Scripts/python -m eval.dancetrack_switches data/dancetrack/val --clips 5 --seconds 30
.venv/Scripts/python -m eval.shift_test
```

Hand labels: open a processed clip, expand "Hand-label this clip", play at quarter speed and press `L` or `E` when a dancer is visibly late or early (`1`–`9` picks the dancer). The panel shows agreement live; for the README numbers run:

```bash
.venv/Scripts/python -m eval.hand_label_check <job_id>
```

Body pose (needs an NVIDIA GPU):

1. Request access to [facebook/sam-3d-body-dinov3](https://huggingface.co/facebook/sam-3d-body-dinov3) on Hugging Face and log in with `hf auth login`.
2. Clone [sam-3d-body](https://github.com/facebookresearch/sam-3d-body) and install it in its own Python 3.11 environment per its INSTALL.md (PyTorch with CUDA; the detector, segmentor and MoGe are not needed).
3. Add to `.env`: `POSE_PYTHON=<that env's python>` and `POSE_REPO=<the clone>`. New jobs then run pose after tracking; without these settings, pose is off.

Docker (one image serves the UI and API on :8000):

```bash
docker build -t crew-sync .
docker run -p 8000:8000 -e META_API_KEY=... -e ALLOWED_ORIGIN=https://your.host -v crewsync-data:/app/data crew-sync
```

CI runs the unit tests and the end-to-end test on a synthetic clip on every push (`.github/workflows/test.yml`); no API key needed.

## Privacy

Uploads need a consent box ticked for the whole crew. Videos and results are deleted after 7 days, or right away with Delete. Logs never contain footage, masks or keys.

## Credits

- [DanceTrack](https://github.com/DanceTrack/DanceTrack) (CC BY 4.0) for tracking evaluation. No DanceTrack footage is in this repo.
- Mask decoding uses Meta's [`@meta-sam/parser`](https://www.npmjs.com/package/@meta-sam/parser) under the SAM License.
