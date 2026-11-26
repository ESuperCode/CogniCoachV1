# Pose model (Form Check)

Served from this site so the camera feature needs no third-party CDN.

- `vision_bundle.mjs`, `wasm/` - MediaPipe Tasks Vision 1.2.3 (npm `@mediapipe/tasks-vision`), Apache License 2.0, (c) Google LLC.
- `pose_landmarker_lite.task` - MediaPipe Pose Landmarker (lite, float16, v1), Apache License 2.0, (c) Google LLC.
  Source: https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task

Licence text: https://www.apache.org/licenses/LICENSE-2.0 . Runs entirely in the browser; no video or image leaves the device.
Loaded only when the athlete opens Form Check (scripts/form-check.js).
