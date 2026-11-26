# Form Check: camera-based coaching with on-device pose + rules + a small text model

Working notes for a write-up. Code: `CogniCoachV1/scripts/form-engine.js` (analysis),
`CogniCoachV1/scripts/form-check.js` (camera + UI), `tests/CogniCoachVisualization(3D)/worker/src/form.js`
(the text-model call), tests in `CogniCoachV1/test/form_engine_test.mjs`.

## The idea in one paragraph

A vision-language model watching video is the obvious way to give form feedback, but it is slow, costs
money per frame, and means uploading video of (often young) athletes. Instead, the browser runs a small
open pose model (MediaPipe Pose Landmarker lite, Apache 2.0) that turns each frame into 33 body points.
Deterministic code turns those points into the things a coach looks at (joint angles, depth, knee
tracking, body line, tempo, left-right balance, fatigue), segments the set into reps, and checks each rep
against a library of form rules. The result is compressed into a short, structured text summary
(~700 characters). Only that text is sent to the cheapest text model, whose only job is to turn verified
numbers into one clear, encouraging coaching message. The rules already coach on their own (live spoken
cues, an offline fallback note), so the language model is optional and cannot see, and so cannot
misjudge, the video.

## Pipeline

1. **Pose (on device).** MediaPipe Pose Landmarker lite, `VIDEO` mode, ~20 analysed frames/s, GPU with CPU
   fallback. Output per frame: 33 image landmarks (x, y, visibility) and 33 "world" landmarks (metres,
   hip-centred 3D). Nothing leaves the device.
2. **Features (code).** Per frame: knee, hip, elbow and shoulder angles from the 3D world landmarks (so
   they depend little on the camera angle; falls back to 2D); trunk lean from vertical; knee-width /
   ankle-width ratio (knee valgus, front view); hip tilt; hip height in torso lengths (jumps); the
   shoulder-hip-ankle body line and whether the hips sit above (pike) or below (sag) it.
   Each feature is smoothed with a One Euro filter (Casiez et al., 2012).
3. **Camera view (code).** Shoulder/hip width divided by torso length classifies front / side / angled.
   Every rule declares which views it can be trusted from (e.g. knee valgus only from the front, chest
   lean only from the side); rules that cannot be checked are reported as "not checked" rather than
   guessed. This is what keeps a single phone camera honest.
4. **Movement pattern (code).** From the drill name (keyword table: squat, lunge, hinge, jump, push-up,
   overhead, plank, wall sit). If the name gives nothing, the first 4 s of motion choose: body
   horizontal -> push-up/plank; large hip-height range -> jump; knee+hip range -> squat; hip only ->
   hinge; shoulder -> overhead; else "general", counting reps on whichever joint moves most.
5. **Rep segmentation (code).** Calibrate the rest value of the pattern's signal (median while still, or
   the straight end of the observed range), then a hysteresis state machine: a rep starts when the signal
   leaves rest by more than max(minimum amplitude, 40% of the athlete's recent rep size) and ends when it
   returns within 30% of that rep's peak. The rest value drifts slowly; reps over 15 s are treated as a
   new position. Per rep: duration, lowering and rising time, peak amplitude, and the extreme value of
   every feature inside the rep.
6. **Rules (code).** 17 rules, each `severity = clamp((value - ok) / (bad - ok), 0, 1)` with
   coach-chosen thresholds, e.g. squat depth (knee angle at bottom > 112 deg), knees caving (ratio < 0.82),
   chest dropping (lean > 50 deg), rushed lowering (< 0.45 s), push-up sag/pike (body-line bend > 12-15 deg),
   stiff landing (knee > 150 deg after the jump's highest point), no lockout overhead, plank sag over time.
   Rep score = 100 - 30 x (sum of severities). Holds are judged frame by frame.
7. **Live cues (code, no AI).** After each rep, the worst fault is spoken if it happened on 2 of the last 3
   reps (or is severe), at most every 6 s and never the same cue twice in 15 s; three clean reps in a row
   earn praise. Holds call out a fault that lasts ~1.5 s.
8. **Compression (code).** The set becomes a short text summary: pattern and how it was found, view,
   tracking quality, reps, tempo, the per-rep extremes (avg/best/worst), fatigue trend (first vs last
   third of reps), faults with rep numbers, rule score, confidence. When no fault was found the summary
   says so and asks for a progression instead (in testing, the model otherwise "found" a fault among the
   things the camera could not see).
9. **Language (one small text model call).** `gpt-5-nano`, minimal reasoning, strict JSON schema
   {headline, praise, fix, cue, next}. Instructions: use only the measurements, one fix, respect what was
   not checked, no medical advice, treat the athlete profile as information only.
10. **Memory.** The fault names (not video, not landmarks) are stored in the athlete's coach profile. A
    fault seen in 2+ of the recent checks of the same movement becomes a coach insight that is added to
    future drill requests ("camera form check shows knees caving inward on squats ...").

## Measured so far (this repo, Nov 2026)

| What | Result |
|---|---|
| Synthetic-skeleton tests (`node CogniCoachV1/test/form_engine_test.mjs`) | 42/42: rep counts exact for squats, push-ups, jumps; valgus found on exactly the reps where it was injected (not reps 1-2); sag found only after it starts; pattern recognised from motion; counts hold with 1.2% landmark noise and in 2D-only mode; no valgus claims from a side view |
| Real pose model in Chromium on a fake webcam (generated photos, standing/squat alternating) | 6/6 squats counted, 0 false faults, live praise cue spoken |
| Text-model cost per check | ~724 input + ~120 output tokens (gpt-5-nano), 1.1-1.5 s |
| Data sent per check | ~0.7 KB of text; 0 bytes of video |

For comparison, sending a 30 s set to a vision model even at 2 frames/s is ~60 images, each costing
tens to hundreds of input tokens depending on resolution and model, plus a vision-capable (usually more
expensive) model and a video upload. The pose model download (~20 MB) happens once and is cached.

## What still needs to be done before claiming accuracy

- **Real data.** Record athletes doing each pattern from front and side, label reps and faults with a
  qualified coach, and report rep-count error and per-fault precision/recall/F1 versus the coach.
  Thresholds in `RULES` were set from coaching norms, not fitted to data yet.
- **Baselines.** Same clips through (a) rules only, (b) rules + text model, (c) a vision-language model
  on sampled frames; compare coach-rated usefulness, factual errors, latency and cost.
- **Robustness.** Lighting, loose clothing, phone on the floor vs hip height, partial occlusion, other
  people in frame, different body types and ages.
- **Hallucination audit.** Score how often the text model states something not in the summary.

## Prior art and the patent question (read before filing anything)

Parts of this are well established: on-device pose estimation (MediaPipe, MoveNet, OpenPose), rule- or
angle-based rep counting and form checks (many fitness apps and research papers), and LLMs that turn
structured pose data into feedback (several recent papers and products). A patent would need a specific,
non-obvious combination, e.g. view-gated rules that report what could not be checked, the
compression format and the "no fault -> progression" control, and feeding repeated faults into future
workout generation. Whether that is patentable is a question for a patent attorney after a prior-art
search. Also note: this code is in a public repository and live on the site, which counts as a public
disclosure. The US allows a one-year grace period from your own disclosure; many other countries do not.
If a patent matters, talk to an attorney soon. A research paper is a realistic goal either way, as long
as it is framed around the measured cost/privacy trade-off and the accuracy study above.
