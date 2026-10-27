"""AI sports-motion planner + kinematic compiler + verifier for the CogniCoach Unity rig.

Single-file local backend. Keep OPENAI_API_KEY on this server, never in browser JavaScript.

Install:
    python -m pip install --upgrade openai fastapi uvicorn numpy pydantic

Run (PowerShell):
    $env:OPENAI_API_KEY="YOUR_KEY"
    $env:OPENAI_MODEL="gpt-6-astra"   # optional; use a model enabled for your API project
    python motion_engine.py

Then open the updated RagdollTest.html in the browser and use "Generate AI Motion".

Important rig assumptions:
- Input anchors and limb lengths use a nominal 1.75 Unity-unit tall human.
- Axes: +X = avatar right, +Y = up, +Z = forward. This may need calibration to your scene.
- The HTML relativityCalculation() composes local joint rotations through the body hierarchy
  with quaternions, then sends world Euler angles in Unity's Z-X-Y convention. This compiler
  emits local joint-angle offsets for that hierarchy. The internal verifier remains a simplified
  model and should not be treated as ground truth for the Unity mesh.
- The internal forward kinematics is a simplified human-ratio model, not a precise model of the
  user's Unity mesh. The output is a research prototype, not a guarantee of biomechanically good form.
"""

from __future__ import annotations

import json
import math
import os
import traceback
from typing import Any, Dict, List, Literal, Sequence, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel, Field

# -----------------------------------------------------------------------------
# Settings and nominal rig proportions (Unity units; nominal height 1.75)
# -----------------------------------------------------------------------------
APIKEY=input("Api Key: \n")
MODEL = os.getenv("OPENAI_MODEL", "gpt-6-astra")
HOST = os.getenv("MOTION_HOST", "127.0.0.1")
PORT = int(os.getenv("MOTION_PORT", "8000"))
BODY_HEIGHT = 1.75
SHOULDER_HALF_WIDTH = 0.195
SHOULDER_Y = 0.445
UPPER_ARM_LENGTH = 0.315
FOREARM_LENGTH = 0.285
HIP_HALF_WIDTH = 0.105
HIP_ANCHOR_Y = -0.035
THIGH_LENGTH = 0.425
SHIN_LENGTH = 0.425
ANKLE_FORWARD_OFFSET = 0.055

# The HTML sample uses 8 FPS. We generate at 12 by default and set the HTML control
# to that rate; each frame is one playback step in the current HTML implementation.
DEFAULT_PLAYBACK_FPS = 12
MAX_FRAMES = 120
IK_ITERATIONS = 45
IK_EPSILON_METERS = 0.012
IK_DAMPING = 0.006
SPARSE_ANGLE_THRESHOLD_DEG = 0.12

ANGLE_KEYS = [
    "hipx", "hipy", "hipz",
    "lefthipx", "lefthipy", "lefthipz",
    "righthipx", "righthipy", "righthipz",
    "leftkneex", "leftkneey", "leftkneez",
    "rightkneex", "rightkneey", "rightkneez",
    "spinex", "spiney", "spinez",
    "neckx", "necky", "neckz",
    "leftshoulderx", "leftshouldery", "leftshoulderz",
    "rightshoulderx", "rightshouldery", "rightshoulderz",
    "leftelbowx", "leftelbowy", "leftelbowz",
    "rightelbowx", "rightelbowy", "rightelbowz",
]
POSITION_KEYS = ["positionx", "positiony", "positionz"]

# -----------------------------------------------------------------------------
# OpenAI structured motion-plan schema
# -----------------------------------------------------------------------------

VECTOR3_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}

WAYPOINT_PROPERTIES = {
    "phase": {"type": "string"},
    "t": {"type": "number"},
    "pelvis_offset_m": VECTOR3_SCHEMA,
    "hip_euler_deg": VECTOR3_SCHEMA,
    "spine_euler_deg": VECTOR3_SCHEMA,
    "neck_euler_deg": VECTOR3_SCHEMA,
    "left_hand_m": VECTOR3_SCHEMA,
    "right_hand_m": VECTOR3_SCHEMA,
    "left_foot_m": VECTOR3_SCHEMA,
    "right_foot_m": VECTOR3_SCHEMA,
    "left_elbow_bend_deg": {"type": "number"},
    "right_elbow_bend_deg": {"type": "number"},
    "left_knee_bend_deg": {"type": "number"},
    "right_knee_bend_deg": {"type": "number"},
    "left_foot_planted": {"type": "boolean"},
    "right_foot_planted": {"type": "boolean"},
}

WAYPOINT_REQUIRED = list(WAYPOINT_PROPERTIES.keys())
WAYPOINT_SCHEMA = {
    "type": "object",
    "properties": WAYPOINT_PROPERTIES,
    "required": WAYPOINT_REQUIRED,
    "additionalProperties": False,
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "movement_summary": {"type": "string"},
        "waypoints": {
            "type": "array",
            "items": WAYPOINT_SCHEMA,
            "minItems": 7,
            "maxItems": 7,
        },
    },
    "required": ["movement_summary", "waypoints"],
    "additionalProperties": False,
}

PLANNER_INSTRUCTIONS = r"""
You are the motion planner in a sports-animation compiler. Do NOT output joint angles or JSON
animation frames. Output a high-level path contract with exactly 7 ordered waypoints. A separate
numerical solver will turn anchor targets into joint rotations.

Coordinate system and scale:
- All anchor coordinates use meters/Unity units relative to the pelvis center at the current frame.
- Avatar nominal height is 1.75 units. +X is the avatar's right, +Y is up, +Z is forward.
- The model is symmetric at rest. In neutral standing, hands are approximately [+/−0.38, -0.10, 0]
  and ankle targets approximately [+/−0.11, -0.82, 0.05]. Those are only starting references.
- pelvis_offset_m is the pelvis/root translation in world Unity units, not an anchor point.
- hip_euler_deg rotates the pelvis/lower-body frame; spine_euler_deg orients the torso;
  neck_euler_deg is a modest local head/neck adjustment. Angles are degrees.
- Hand and foot targets are relative to pelvis center. Keep them reachable for limbs of normal human
  proportions: shoulder-to-hand length is about 0.60, hip-to-ankle length about 0.85.

Make motions useful and visibly distinct, with meaningful preparation, action, and recovery. Do not
repeat nearly identical waypoints. Include useful whole-body coordination, not just moving one hand.
Use the actual requested sport movement rather than forcing a generic movement template. A movement
may be compact, but it must contain the action's important phases. Motion should have an intelligible
weight shift, torso contribution, arm/leg coordination, and follow-through where appropriate.
Keep all limbs anatomically plausible and targets reachable. Avoid extreme body-root jumps.

Output exactly 7 waypoints in chronological order. `t` should increase from 0 to 1. A reasonable
initial progression is approximately 0.00, 0.15, 0.30, 0.47, 0.64, 0.82, 1.00, adjusted to the action.
Each waypoint must specify every field in the schema. Use concise phase names. Feet marked planted
should remain on the same world-space ground point; therefore, if pelvis_offset_m shifts, compensate
by changing that foot's pelvis-relative target. For an airborne or stepping foot, set planted=false.
Elbow/knee bend fields are preferred hinge-flexion magnitudes from 0 to 120-ish degrees; they are
hints, not direct joint outputs. Do not make every numeric value zero. Do not describe these values as
validated sports biomechanics; plan a plausible illustrative demonstration.
""".strip()


# -----------------------------------------------------------------------------
# Request models and FastAPI
# -----------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    movement: str = Field(min_length=3, max_length=240)
    duration_seconds: float = Field(default=2.0, ge=0.6, le=8.0)
    playback_fps: int = Field(default=DEFAULT_PLAYBACK_FPS, ge=6, le=30)
    dominant_side: Literal["left", "right"] = "right"
    extra_instructions: str = Field(default="", max_length=600)
    repair_attempts: int = Field(default=2, ge=0, le=2)


app = FastAPI(title="CogniCoach Motion Engine", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Local prototype only. Restrict this before public deployment.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_client() -> OpenAI:
    
    return OpenAI(api_key=APIKEY)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "model": MODEL, "nominal_body_height": BODY_HEIGHT}


# -----------------------------------------------------------------------------
# Geometry helpers: vectors, Unity-style Euler rotation, and trajectories
# -----------------------------------------------------------------------------

def vec3(value: Any, fallback: Sequence[float] = (0.0, 0.0, 0.0)) -> np.ndarray:
    try:
        arr = np.asarray(value, dtype=float).reshape(-1)
        if arr.size >= 3 and np.all(np.isfinite(arr[:3])):
            return arr[:3].astype(float)
    except Exception:
        pass
    return np.asarray(fallback, dtype=float)


def rot_x(rad: float) -> np.ndarray:
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)


def rot_y(rad: float) -> np.ndarray:
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)


def rot_z(rad: float) -> np.ndarray:
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)


def unity_euler_matrix(degrees: Sequence[float]) -> np.ndarray:
    """Approximate Unity Quaternion.Euler's Z-X-Y application order.

    Unity documents Quaternion.Euler as applying Z, then X, then Y rotations. For column-vector
    math the combined matrix is Ry @ Rx @ Rz. We still use the HTML's per-axis additive convention
    when deriving cumulative Euler triples. Actual rig orientation should be calibrated in Unity.
    """
    x, y, z = np.radians(vec3(degrees))
    return rot_y(y) @ rot_x(x) @ rot_z(z)


def rotate(degrees: Sequence[float], point: Sequence[float]) -> np.ndarray:
    return unity_euler_matrix(degrees) @ np.asarray(point, dtype=float)


def clamp_num(x: float, low: float, high: float) -> float:
    return max(low, min(high, float(x)))


def wrap_deg(x: float) -> float:
    return (float(x) + 180.0) % 360.0 - 180.0


def unwrap_angle_points(points: np.ndarray) -> np.ndarray:
    """Unwrap sequential Euler components along the shortest-angle direction."""
    out = np.asarray(points, dtype=float).copy()
    if len(out) <= 1:
        return out
    for axis in range(out.shape[1]):
        for i in range(1, len(out)):
            out[i, axis] = out[i - 1, axis] + wrap_deg(out[i, axis] - out[i - 1, axis])
    return out


def hermite_slopes(ts: np.ndarray, ys: np.ndarray) -> np.ndarray:
    slopes = np.zeros_like(ys, dtype=float)
    if len(ts) <= 1:
        return slopes
    slopes[0] = (ys[1] - ys[0]) / max(1e-6, ts[1] - ts[0])
    slopes[-1] = (ys[-1] - ys[-2]) / max(1e-6, ts[-1] - ts[-2])
    for i in range(1, len(ts) - 1):
        slopes[i] = (ys[i + 1] - ys[i - 1]) / max(1e-6, ts[i + 1] - ts[i - 1])
    return slopes


def hermite_sample(ts: np.ndarray, ys: np.ndarray, t: float) -> np.ndarray:
    """Cubic Hermite interpolation through values with time-aware tangent estimates."""
    if t <= ts[0]:
        return np.asarray(ys[0], dtype=float).copy()
    if t >= ts[-1]:
        return np.asarray(ys[-1], dtype=float).copy()
    i = int(np.searchsorted(ts, t, side="right") - 1)
    i = max(0, min(i, len(ts) - 2))
    t0, t1 = float(ts[i]), float(ts[i + 1])
    dt = max(1e-6, t1 - t0)
    u = (t - t0) / dt
    slopes = hermite_slopes(ts, ys)
    h00 = 2 * u**3 - 3 * u**2 + 1
    h10 = u**3 - 2 * u**2 + u
    h01 = -2 * u**3 + 3 * u**2
    h11 = u**3 - u**2
    return h00 * ys[i] + h10 * dt * slopes[i] + h01 * ys[i + 1] + h11 * dt * slopes[i + 1]


VECTOR_FIELDS = [
    "pelvis_offset_m", "hip_euler_deg", "spine_euler_deg", "neck_euler_deg",
    "left_hand_m", "right_hand_m", "left_foot_m", "right_foot_m",
]
SCALAR_FIELDS = [
    "left_elbow_bend_deg", "right_elbow_bend_deg", "left_knee_bend_deg", "right_knee_bend_deg",
]


def sample_plan(plan: Dict[str, Any], t: float) -> Dict[str, Any]:
    wps = plan["waypoints"]
    ts = np.array([float(w["t"]) for w in wps], dtype=float)
    ts = np.maximum.accumulate(ts)
    if len(ts) > 1:
        for i in range(1, len(ts)):
            if ts[i] <= ts[i - 1]:
                ts[i] = ts[i - 1] + 1e-3
        ts = (ts - ts[0]) / (ts[-1] - ts[0])
    sample: Dict[str, Any] = {}
    for field in VECTOR_FIELDS:
        arr = np.array([vec3(w[field]) for w in wps], dtype=float)
        if "euler_deg" in field:
            arr = unwrap_angle_points(arr)
        sample[field] = hermite_sample(ts, arr, t).tolist()
    for field in SCALAR_FIELDS:
        arr = np.array([[float(w[field])] for w in wps], dtype=float)
        sample[field] = float(hermite_sample(ts, arr, t)[0])
    nearest = int(np.argmin(np.abs(ts - t)))
    sample["phase"] = wps[nearest]["phase"]
    sample["left_foot_planted"] = bool(wps[nearest]["left_foot_planted"])
    sample["right_foot_planted"] = bool(wps[nearest]["right_foot_planted"])
    return sample


# -----------------------------------------------------------------------------
# Numerical inverse kinematics: two-link limbs, finite-difference Jacobian, DLS
# -----------------------------------------------------------------------------

def arm_origin(spine_euler: Sequence[float], side: str) -> np.ndarray:
    sign = 1.0 if side == "right" else -1.0
    return rotate(spine_euler, [sign * SHOULDER_HALF_WIDTH, SHOULDER_Y, 0.0])


def arm_endpoint(q: Sequence[float], spine_euler: Sequence[float], side: str) -> np.ndarray:
    q = np.asarray(q, dtype=float)
    origin = arm_origin(spine_euler, side)
    upper_euler = vec3(spine_euler) + q[:3]
    lower_euler = vec3(spine_euler) + q[:3] + q[3:6]
    elbow = origin + rotate(upper_euler, [0.0, -UPPER_ARM_LENGTH, 0.0])
    wrist = elbow + rotate(lower_euler, [0.0, -FOREARM_LENGTH, 0.0])
    return wrist


def leg_origin(hip_euler: Sequence[float], side: str) -> np.ndarray:
    sign = 1.0 if side == "right" else -1.0
    return rotate(hip_euler, [sign * HIP_HALF_WIDTH, HIP_ANCHOR_Y, 0.0])


def leg_endpoint(q: Sequence[float], hip_euler: Sequence[float], side: str) -> np.ndarray:
    q = np.asarray(q, dtype=float)
    origin = leg_origin(hip_euler, side)
    thigh_euler = vec3(hip_euler) + q[:3]
    shin_euler = vec3(hip_euler) + q[:3] + q[3:6]
    knee = origin + rotate(thigh_euler, [0.0, -THIGH_LENGTH, 0.0])
    ankle = knee + rotate(shin_euler, [0.0, -SHIN_LENGTH, 0.0])
    # A small forward offset approximates the ankle/foot contact point in this simplified rig.
    return ankle + rotate(shin_euler, [0.0, 0.0, ANKLE_FORWARD_OFFSET])


def numerical_jacobian(func, q: np.ndarray, epsilon_deg: float = 0.5) -> np.ndarray:
    base = np.asarray(func(q), dtype=float)
    jac = np.zeros((3, q.size), dtype=float)
    for i in range(q.size):
        plus = q.copy()
        plus[i] += epsilon_deg
        jac[:, i] = (np.asarray(func(plus), dtype=float) - base) / epsilon_deg
    return jac


def _limit_local_angles(q: np.ndarray, chain: str) -> np.ndarray:
    q = np.asarray(q, dtype=float).copy()
    q[:3] = np.clip(q[:3], -135.0, 135.0)
    q[3] = clamp_num(q[3], -145.0 if chain == "arm" else -125.0,
                     145.0 if chain == "arm" else 125.0)
    # y/z rotations at elbows and knees are allowed but discouraged; the rig axes are not yet calibrated.
    q[4:6] = np.clip(q[4:6], -55.0, 55.0)
    return q


def solve_two_link(
    target: Sequence[float],
    base_euler: Sequence[float],
    side: str,
    seed: Sequence[float] | None,
    chain: Literal["arm", "leg"],
    preferred_hinge_deg: float = 0.0,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """Solve a two-segment endpoint position by damped least squares.

    q[0:3] are first-joint local Euler offsets; q[3:6] second-joint local offsets.
    The hinge axis defaults to local X as a starting rig assumption. This needs calibration.
    """
    target = vec3(target)
    base_euler = vec3(base_euler)
    endpoint_fn = arm_endpoint if chain == "arm" else leg_endpoint
    origin_fn = arm_origin if chain == "arm" else leg_origin
    l1, l2 = (UPPER_ARM_LENGTH, FOREARM_LENGTH) if chain == "arm" else (THIGH_LENGTH, SHIN_LENGTH)
    origin = origin_fn(base_euler, side)
    reach_vector = target - origin
    reach_distance = float(np.linalg.norm(reach_vector))
    max_reach = l1 + l2 - 0.005
    min_reach = abs(l1 - l2) + 0.005
    projected = target.copy()
    if reach_distance > max_reach and reach_distance > 1e-8:
        projected = origin + reach_vector / reach_distance * max_reach
    elif reach_distance < min_reach and reach_distance > 1e-8:
        projected = origin + reach_vector / reach_distance * min_reach
    elif reach_distance <= 1e-8:
        projected = origin + np.array([0.0, -(min_reach + 0.05), 0.0])

    # A two-link chain's target distance strongly constrains its relative bend:
    # d^2 = L1^2 + L2^2 + 2*L1*L2*cos(theta). Initializing from this relation avoids
    # the straight-arm/knee singularity that makes numerical IK get stuck near full extension.
    projected_distance = float(np.linalg.norm(projected - origin))
    cosine = (projected_distance**2 - l1**2 - l2**2) / (2.0 * l1 * l2)
    geometric_bend = math.degrees(math.acos(clamp_num(cosine, -1.0, 1.0)))
    hinted_bend = abs(float(preferred_hinge_deg))
    # Geometry takes priority when the requested target requires it. The model's bend hint helps
    # choose a useful starting posture but cannot violate the limb-length equation.
    geometric_bend = clamp_num(geometric_bend, 0.0, 145.0 if chain == "arm" else 125.0)
    if seed is None:
        q = np.zeros(6, dtype=float)
        # X is a provisional hinge axis; calibrate if the Unity rig flexes about another axis.
        q[3] = -geometric_bend
    else:
        q = np.asarray(seed, dtype=float).reshape(6).copy()
        # Balance frame-to-frame continuity against the bend dictated by the current target distance.
        q[3] = 0.28 * q[3] - 0.72 * geometric_bend
        # A large hinted bend is allowed to influence only when it remains geometrically plausible.
        if geometric_bend > 5.0:
            q[3] = 0.85 * q[3] - 0.15 * min(hinted_bend, geometric_bend)
    q = _limit_local_angles(q, chain)

    # Variable weighting lets shoulder/hip orient in 3D while discouraging non-hinge rotations
    # at the elbow/knee. The preferred solution is the current seed (temporal continuity).
    axis_scales = np.array([1.0, 1.0, 1.0, 1.0, 0.28, 0.28], dtype=float)
    before = float(np.linalg.norm(endpoint_fn(q, base_euler, side) - target))
    for _ in range(IK_ITERATIONS):
        endpoint = endpoint_fn(q, base_euler, side)
        error = projected - endpoint
        if float(np.linalg.norm(error)) < IK_EPSILON_METERS:
            break
        jac = numerical_jacobian(lambda angles: endpoint_fn(angles, base_euler, side), q)
        jac = jac * axis_scales[np.newaxis, :]
        system = jac @ jac.T + (IK_DAMPING**2) * np.eye(3)
        try:
            delta_scaled = jac.T @ np.linalg.solve(system, error)
        except np.linalg.LinAlgError:
            delta_scaled = jac.T @ np.linalg.pinv(system) @ error
        delta = axis_scales * delta_scaled
        delta = np.clip(delta, -18.0, 18.0)
        q = _limit_local_angles(q + delta, chain)

    achieved = endpoint_fn(q, base_euler, side)
    error_original = float(np.linalg.norm(achieved - target))
    error_projected = float(np.linalg.norm(achieved - projected))
    return q, {
        "target_error_m": error_original,
        "projected_error_m": error_projected,
        "requested_reach_m": reach_distance,
        "max_reach_m": max_reach,
        "was_projected": bool(np.linalg.norm(projected - target) > 1e-5),
        "initial_error_m": before,
    }


# -----------------------------------------------------------------------------
# Plan sanitization and initial planning / targeted repair
# -----------------------------------------------------------------------------

def _clamp_vec(v: Any, limits: Sequence[Tuple[float, float]]) -> List[float]:
    arr = vec3(v)
    return [clamp_num(arr[i], limits[i][0], limits[i][1]) for i in range(3)]


def sanitize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(plan, dict) or not isinstance(plan.get("waypoints"), list):
        raise ValueError("Planner output has no waypoint list.")
    raw = plan["waypoints"]
    if len(raw) < 5:
        raise ValueError(f"Planner supplied only {len(raw)} waypoints; expected 7.")
    # Structured output generally gives exactly seven; gracefully reduce/expand malformed outputs.
    if len(raw) > 7:
        idx = np.linspace(0, len(raw) - 1, 7).round().astype(int).tolist()
        raw = [raw[i] for i in idx]
    while len(raw) < 7:
        # Insert a midpoint of the currently longest time interval.
        times = [float(w.get("t", i / max(1, len(raw) - 1))) for i, w in enumerate(raw)]
        i = int(np.argmax(np.diff(times))) if len(times) >= 2 else 0
        a = raw[i]
        b = raw[min(i + 1, len(raw) - 1)]
        mid = {}
        for key in WAYPOINT_REQUIRED:
            if key == "phase":
                mid[key] = "transition"
            elif key == "t":
                mid[key] = (float(a.get("t", 0)) + float(b.get("t", 1))) / 2
            elif key in ("left_foot_planted", "right_foot_planted"):
                mid[key] = bool(a.get(key, False) and b.get(key, False))
            elif isinstance(a.get(key), list) and isinstance(b.get(key), list):
                mid[key] = ((np.asarray(a[key], dtype=float) + np.asarray(b[key], dtype=float)) / 2).tolist()
            elif isinstance(a.get(key), (int, float)) and isinstance(b.get(key), (int, float)):
                mid[key] = (float(a[key]) + float(b[key])) / 2
            else:
                mid[key] = a.get(key, b.get(key, 0))
        raw.insert(i + 1, mid)

    result_wps: List[Dict[str, Any]] = []
    for i, w in enumerate(raw[:7]):
        if not isinstance(w, dict):
            raise ValueError(f"Waypoint {i} is not an object.")
        item: Dict[str, Any] = {}
        item["phase"] = str(w.get("phase", f"phase_{i + 1}"))[:48]
        item["t"] = clamp_num(w.get("t", i / 6), 0.0, 1.0)
        item["pelvis_offset_m"] = _clamp_vec(w.get("pelvis_offset_m"), [(-0.45, 0.45), (-0.25, 0.25), (-0.55, 0.55)])
        item["hip_euler_deg"] = _clamp_vec(w.get("hip_euler_deg"), [(-35, 35), (-85, 85), (-35, 35)])
        item["spine_euler_deg"] = _clamp_vec(w.get("spine_euler_deg"), [(-50, 50), (-120, 120), (-50, 50)])
        item["neck_euler_deg"] = _clamp_vec(w.get("neck_euler_deg"), [(-35, 35), (-45, 45), (-35, 35)])
        item["left_hand_m"] = _clamp_vec(w.get("left_hand_m"), [(-0.72, 0.72), (-0.42, 0.98), (-0.58, 0.70)])
        item["right_hand_m"] = _clamp_vec(w.get("right_hand_m"), [(-0.72, 0.72), (-0.42, 0.98), (-0.58, 0.70)])
        item["left_foot_m"] = _clamp_vec(w.get("left_foot_m"), [(-0.63, 0.63), (-1.00, -0.25), (-0.55, 0.55)])
        item["right_foot_m"] = _clamp_vec(w.get("right_foot_m"), [(-0.63, 0.63), (-1.00, -0.25), (-0.55, 0.55)])
        for key in SCALAR_FIELDS:
            high = 135.0 if "elbow" in key else 115.0
            item[key] = clamp_num(w.get(key, 15.0), 0.0, high)
        item["left_foot_planted"] = bool(w.get("left_foot_planted", False))
        item["right_foot_planted"] = bool(w.get("right_foot_planted", False))
        result_wps.append(item)

    # Enforce strictly ordered times while retaining the planner's timing as much as possible.
    times = np.array([w["t"] for w in result_wps], dtype=float)
    valid = times[0] <= 0.08 and times[-1] >= 0.92 and np.all(np.diff(times) > 0.015)
    if not valid:
        times = np.linspace(0.0, 1.0, 7)
    else:
        times[0], times[-1] = 0.0, 1.0
        times = np.maximum.accumulate(times)
        if np.any(np.diff(times) < 0.015):
            times = np.linspace(0.0, 1.0, 7)
    for i, w in enumerate(result_wps):
        w["t"] = float(times[i])

    return {
        "movement_summary": str(plan.get("movement_summary", "Illustrative sports movement"))[:600],
        "waypoints": result_wps,
    }


def call_planner(req: GenerateRequest, previous_plan: Dict[str, Any] | None = None,
                 report: Dict[str, Any] | None = None) -> Dict[str, Any]:
    client = get_client()
    is_repair = previous_plan is not None
    request_text = {
        "movement": req.movement,
        "duration_seconds": req.duration_seconds,
        "dominant_side": req.dominant_side,
        "extra_instructions": req.extra_instructions,
        "body_model": {
            "height_units": BODY_HEIGHT,
            "upper_arm": UPPER_ARM_LENGTH,
            "forearm": FOREARM_LENGTH,
            "thigh": THIGH_LENGTH,
            "shin": SHIN_LENGTH,
            "shoulder_y": SHOULDER_Y,
            "axes": "+X avatar right, +Y up, +Z forward",
        },
    }
    if not is_repair:
        user_prompt = (
            "Create a motion path contract for this requested illustrative sports movement.\n"
            "Do not output joint rotations or frames; output anchor targets and phase data only.\n"
            + json.dumps(request_text, ensure_ascii=False)
        )
    else:
        user_prompt = (
            "Repair this motion plan using the objective verifier report below. Keep successful parts "
            "of the plan unchanged. Fix only the reported failures; prioritize reachable anchors, "
            "meaningful movement, foot stability, and continuity. Return the complete same-schema plan.\n"
            "REQUEST:\n" + json.dumps(request_text, ensure_ascii=False) +
            "\nCURRENT PLAN:\n" + json.dumps(previous_plan, ensure_ascii=False) +
            "\nVERIFIER REPORT:\n" + json.dumps(report, ensure_ascii=False)
        )
    try:
        response = client.responses.create(
            model=MODEL,
            instructions=PLANNER_INSTRUCTIONS,
            input=user_prompt,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "motion_plan",
                    "strict": True,
                    "schema": PLAN_SCHEMA,
                }
            },
            max_output_tokens=12000,
        )
    except Exception as exc:
        # Keep details server-side in traceback; return a useful error message to browser.
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"OpenAI motion-planning request failed: {exc}") from exc
    try:
        if not response.output_text:
            raise ValueError("The model returned no text output.")
        parsed = json.loads(response.output_text)
        return sanitize_plan(parsed)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=502, detail=f"Could not parse the model's motion plan: {exc}") from exc


# -----------------------------------------------------------------------------
# Compile anchor trajectories into sparse joint frames
# -----------------------------------------------------------------------------

def compile_motion(plan: Dict[str, Any], duration_seconds: float, fps: int) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    frame_count = max(2, min(MAX_FRAMES, int(round(duration_seconds * fps))))
    times = np.linspace(0.0, 1.0, frame_count)

    seed: Dict[str, np.ndarray | None] = {
        "left_arm": None,
        "right_arm": None,
        "left_leg": None,
        "right_leg": None,
    }
    frames: List[Dict[str, float]] = []
    detailed: List[Dict[str, Any]] = []

    for frame_idx, t in enumerate(times):
        p = sample_plan(plan, float(t))
        root = vec3(p["pelvis_offset_m"])
        hip_euler = vec3(p["hip_euler_deg"])
        spine_euler = vec3(p["spine_euler_deg"])

        larm, larm_info = solve_two_link(p["left_hand_m"], spine_euler, "left", seed["left_arm"], "arm", p["left_elbow_bend_deg"])
        rarm, rarm_info = solve_two_link(p["right_hand_m"], spine_euler, "right", seed["right_arm"], "arm", p["right_elbow_bend_deg"])
        lleg, lleg_info = solve_two_link(p["left_foot_m"], hip_euler, "left", seed["left_leg"], "leg", p["left_knee_bend_deg"])
        rleg, rleg_info = solve_two_link(p["right_foot_m"], hip_euler, "right", seed["right_leg"], "leg", p["right_knee_bend_deg"])
        seed["left_arm"], seed["right_arm"] = larm, rarm
        seed["left_leg"], seed["right_leg"] = lleg, rleg

        # Each joint's local offsets are composed through the hierarchy by the HTML transform.
        local_values = {
            "hip": hip_euler,
            "spine": spine_euler,
            "neck": vec3(p["neck_euler_deg"]),
            "lefthip": lleg[:3],
            "righthip": rleg[:3],
            "leftknee": lleg[3:6],
            "rightknee": rleg[3:6],
            "leftshoulder": larm[:3],
            "rightshoulder": rarm[:3],
            "leftelbow": larm[3:6],
            "rightelbow": rarm[3:6],
        }
        frame: Dict[str, float] = {}
        for joint, eulers in local_values.items():
            for axis, axis_name in enumerate("xyz"):
                key = f"{joint}{axis_name}"
                value = wrap_deg(float(eulers[axis]))
                if abs(value) >= SPARSE_ANGLE_THRESHOLD_DEG:
                    frame[key] = round(value, 3)
        for key, value in zip(POSITION_KEYS, root):
            if abs(float(value)) >= 0.001:
                frame[key] = round(float(value), 4)

        frames.append(frame)
        detailed.append({
            "t": float(t),
            "phase": p["phase"],
            "targets": {
                "left_hand": vec3(p["left_hand_m"]).tolist(),
                "right_hand": vec3(p["right_hand_m"]).tolist(),
                "left_foot": vec3(p["left_foot_m"]).tolist(),
                "right_foot": vec3(p["right_foot_m"]).tolist(),
            },
            "root": root.tolist(),
            "spine": spine_euler.tolist(),
            "hip": hip_euler.tolist(),
            "solutions": {
                "left_arm": larm.tolist(), "right_arm": rarm.tolist(),
                "left_leg": lleg.tolist(), "right_leg": rleg.tolist(),
            },
            "ik": {
                "left_arm": larm_info, "right_arm": rarm_info,
                "left_leg": lleg_info, "right_leg": rleg_info,
            },
            "planted": {
                "left": bool(p["left_foot_planted"]),
                "right": bool(p["right_foot_planted"]),
            },
        })

    report = verify_motion(plan, frames, detailed, fps)
    return frames, report


# -----------------------------------------------------------------------------
# Forward kinematics and independent verifier
# -----------------------------------------------------------------------------

def decode_frame_to_local(frame: Dict[str, Any], prefix: str) -> np.ndarray:
    return np.array([float(frame.get(prefix + a, 0.0)) for a in "xyz"], dtype=float)


def forward_kinematics_frame(frame: Dict[str, Any]) -> Dict[str, np.ndarray]:
    """Estimate anchors in pelvis-relative coordinates using the nominal human proportions."""
    hip = decode_frame_to_local(frame, "hip")
    spine = decode_frame_to_local(frame, "spine")
    p: Dict[str, np.ndarray] = {}
    for side in ("left", "right"):
        shoulder = decode_frame_to_local(frame, side + "shoulder")
        elbow = decode_frame_to_local(frame, side + "elbow")
        global_upper = spine + shoulder
        global_lower = spine + shoulder + elbow
        sh_origin = rotate(spine, [(-1 if side == "left" else 1) * SHOULDER_HALF_WIDTH, SHOULDER_Y, 0])
        elbow_pos = sh_origin + rotate(global_upper, [0, -UPPER_ARM_LENGTH, 0])
        hand_pos = elbow_pos + rotate(global_lower, [0, -FOREARM_LENGTH, 0])
        p[side + "_hand"] = hand_pos

        hip_local = decode_frame_to_local(frame, side + "hip")
        knee_local = decode_frame_to_local(frame, side + "knee")
        global_thigh = hip + hip_local
        global_shin = hip + hip_local + knee_local
        hip_origin = rotate(hip, [(-1 if side == "left" else 1) * HIP_HALF_WIDTH, HIP_ANCHOR_Y, 0])
        knee_pos = hip_origin + rotate(global_thigh, [0, -THIGH_LENGTH, 0])
        ankle_pos = knee_pos + rotate(global_shin, [0, -SHIN_LENGTH, 0]) + rotate(global_shin, [0, 0, ANKLE_FORWARD_OFFSET])
        p[side + "_foot"] = ankle_pos
    return p


def verify_motion(plan: Dict[str, Any], frames: List[Dict[str, float]], detailed: List[Dict[str, Any]], fps: int) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    warnings: List[str] = []
    target_errors: Dict[str, List[float]] = {"left_hand": [], "right_hand": [], "left_foot": [], "right_foot": []}
    path_lengths: Dict[str, float] = {k: 0.0 for k in target_errors}
    measured_path_lengths: Dict[str, float] = {k: 0.0 for k in target_errors}
    planted_slip: Dict[str, List[float]] = {"left": [], "right": []}
    planted_drift: Dict[str, List[float]] = {"left": [], "right": []}
    planted_segment_start: Dict[str, np.ndarray] = {}
    previous_planted: Dict[str, bool] = {"left": False, "right": False}
    all_joint_values: List[np.ndarray] = []
    max_frame_delta = 0.0
    max_frame_accel = 0.0

    target_map = {
        "left_hand": "left_hand", "right_hand": "right_hand",
        "left_foot": "left_foot", "right_foot": "right_foot",
    }
    previous_actual: Dict[str, np.ndarray] | None = None
    previous_target: Dict[str, np.ndarray] | None = None
    previous_world_foot: Dict[str, np.ndarray] = {}
    previous_angles: np.ndarray | None = None
    previous_angle_delta: np.ndarray | None = None
    actual_tracks: Dict[str, List[np.ndarray]] = {k: [] for k in target_errors}
    target_tracks: Dict[str, List[np.ndarray]] = {k: [] for k in target_errors}

    for i, (frame, detail) in enumerate(zip(frames, detailed)):
        actual = forward_kinematics_frame(frame)
        root = np.asarray(detail["root"], dtype=float)
        targets = {k: np.asarray(detail["targets"][k], dtype=float) for k in target_map}
        # Foot/hands anchor coordinates in the body model are pelvis-relative; root cancels in target errors.
        for key, actual_key in target_map.items():
            target_errors[key].append(float(np.linalg.norm(actual[actual_key] - targets[key])))
            target_tracks[key].append(targets[key].copy())
            actual_tracks[key].append(actual[actual_key].copy())
            if previous_actual is not None:
                path_lengths[key] += float(np.linalg.norm(targets[key] - previous_target[key]))
                measured_path_lengths[key] += float(np.linalg.norm(actual[actual_key] - previous_actual[actual_key]))
        for side in ("left", "right"):
            world_foot = root + actual[side + "_foot"]
            is_planted = bool(detail["planted"][side])
            if side in previous_world_foot and is_planted and previous_planted[side]:
                planted_slip[side].append(float(np.linalg.norm(world_foot - previous_world_foot[side])))
            if is_planted:
                if not previous_planted[side] or side not in planted_segment_start:
                    planted_segment_start[side] = world_foot.copy()
                planted_drift[side].append(float(np.linalg.norm(world_foot - planted_segment_start[side])))
            else:
                planted_segment_start.pop(side, None)
            previous_world_foot[side] = world_foot
            previous_planted[side] = is_planted

        # Default frame schema is sparse: omitted keys are zero, as intended by the user's HTML.
        vector = np.array([float(frame.get(k, 0.0)) for k in ANGLE_KEYS + POSITION_KEYS], dtype=float)
        all_joint_values.append(vector)
        if previous_angles is not None:
            delta = vector - previous_angles
            max_frame_delta = max(max_frame_delta, float(np.max(np.abs(delta))))
            if previous_angle_delta is not None:
                max_frame_accel = max(max_frame_accel, float(np.max(np.abs(delta - previous_angle_delta))))
            previous_angle_delta = delta
        previous_angles = vector
        previous_actual = actual
        previous_target = targets

    frame_count = len(frames)
    mean_errors = {k: float(np.mean(v)) if v else 0.0 for k, v in target_errors.items()}
    max_errors = {k: float(np.max(v)) if v else 0.0 for k, v in target_errors.items()}
    for k, err in max_errors.items():
        if err > 0.05:
            failures.append({"type": "anchor_tracking", "anchor": k, "max_error_m": round(err, 4),
                             "action": "Move this target closer to the reachable region for the nominal limb length."})

    total_target_path = float(sum(path_lengths.values()))
    total_measured_path = float(sum(measured_path_lengths.values()))
    max_target_excursion = max((float(np.max(np.linalg.norm(np.asarray(track) - np.asarray(track)[0], axis=1))) for track in target_tracks.values()), default=0.0)
    if total_target_path < 0.25 and max_target_excursion < 0.08:
        failures.append({"type": "insufficient_motion", "target_path_length_m": round(total_target_path, 4),
                         "action": "Increase purposeful anchor displacement across the key phases; avoid nearly identical waypoints."})

    for side, slips in planted_slip.items():
        if slips and max(slips) > 0.075:
            failures.append({"type": "planted_foot_step", "side": side, "max_step_m": round(max(slips), 4),
                             "action": f"Keep the {side} foot's world-space position stable during planted phases; compensate its pelvis-relative target for root translation."})
        drift_values = planted_drift[side]
        if drift_values and max(drift_values) > 0.08:
            failures.append({"type": "planted_foot_drift", "side": side, "max_drift_m": round(max(drift_values), 4),
                             "action": f"Reduce cumulative world-space drift of the planted {side} foot below 0.08 m across each continuous planted segment."})

    if max_frame_delta > 75.0:
        warnings.append(f"Large adjacent-frame angle change ({max_frame_delta:.1f} degrees); inspect continuity and rig axis calibration.")
    if max_frame_accel > 60.0:
        warnings.append(f"Large adjacent-frame angular second difference ({max_frame_accel:.1f} degrees/frame^2); inspect timing/smoothing.")

    # Nonzero pose check. Count frames whose posture differs materially from its predecessor.
    distinct_changes = 0
    for i in range(1, len(all_joint_values)):
        if float(np.max(np.abs(all_joint_values[i] - all_joint_values[i - 1]))) > 0.8:
            distinct_changes += 1
    changed_pose_ratio = distinct_changes / max(1, frame_count - 1)
    if changed_pose_ratio < 0.35:
        failures.append({"type": "mostly_static_pose", "changed_pose_ratio": round(changed_pose_ratio, 3),
                         "action": "Ensure the movement produces evolving anchor targets and joint poses, not a few repeated frames."})

    # Verify local joint values don't exceed broad generic limits.
    out_of_range = []
    for i, frame in enumerate(frames):
        for key in ANGLE_KEYS:
            val = float(frame.get(key, 0.0))
            if abs(val) > 165.0:
                out_of_range.append({"frame": i, "joint": key, "degrees": round(val, 2)})
    if out_of_range:
        warnings.append(f"{len(out_of_range)} local joint values exceeded 165 degrees; inspect the rig's conventions.")

    # A rough static/endpoint metric is useful, but not a sports-technique score.
    report = {
        "passed_geometric_checks": len(failures) == 0,
        "failure_count": len(failures),
        "failures": failures[:12],
        "warnings": warnings,
        "frame_count": frame_count,
        "playback_fps": fps,
        "nominal_body_height": BODY_HEIGHT,
        "mean_anchor_error_m": {k: round(v, 4) for k, v in mean_errors.items()},
        "max_anchor_error_m": {k: round(v, 4) for k, v in max_errors.items()},
        "target_path_length_m": round(total_target_path, 4),
        "measured_path_length_m": round(total_measured_path, 4),
        "max_target_excursion_m": round(max_target_excursion, 4),
        "changed_pose_ratio": round(changed_pose_ratio, 3),
        "max_adjacent_joint_delta_deg": round(max_frame_delta, 3),
        "max_joint_second_difference_deg_per_frame2": round(max_frame_accel, 3),
        "max_planted_foot_step_m": {side: round(max(values), 4) if values else 0.0 for side, values in planted_slip.items()},
        "max_planted_foot_drift_m": {side: round(max(values), 4) if values else 0.0 for side, values in planted_drift.items()},
        "interpretation": "These are model-based geometry/continuity checks, not proof of correct sports biomechanics. Calibrate against actual Unity transforms and reference motion.",
    }
    return report


# -----------------------------------------------------------------------------
# End-to-end endpoint: plan -> compile -> verify -> targeted replan
# -----------------------------------------------------------------------------

@app.post("/generate")
def generate(req: GenerateRequest) -> Dict[str, Any]:
    plan = call_planner(req)
    frames, report = compile_motion(plan, req.duration_seconds, req.playback_fps)
    repair_log: List[Dict[str, Any]] = []
    for attempt in range(req.repair_attempts):
        if report.get("passed_geometric_checks", False):
            break
        previous_failure_signature = [(f.get("type"), f.get("anchor"), f.get("side")) for f in report.get("failures", [])]
        repair_log.append({"attempt": attempt + 1, "failure_signature": previous_failure_signature})
        try:
            repaired = call_planner(req, previous_plan=plan, report=report)
            new_frames, new_report = compile_motion(repaired, req.duration_seconds, req.playback_fps)
            # Keep the repair only if it strictly reduces failures, or achieves a pass.
            if new_report["failure_count"] <= report["failure_count"] or new_report["passed_geometric_checks"]:
                plan, frames, report = repaired, new_frames, new_report
            else:
                repair_log[-1]["repair_rejected"] = True
                break
        except Exception as exc:
            repair_log[-1]["repair_error"] = str(exc)
            break

    return {
        "frames": frames,
        "playback_fps": req.playback_fps,
        "duration_seconds_requested": req.duration_seconds,
        "movement_summary": plan.get("movement_summary", ""),
        "plan": plan,
        "report": report,
        "repair_log": repair_log,
        "model": MODEL,
    }


# Simple local debug endpoint accepts a hand-written plan, so solver math can be tested without an API call.
class CompileRequest(BaseModel):
    plan: Dict[str, Any]
    duration_seconds: float = Field(default=2.0, ge=0.6, le=8.0)
    playback_fps: int = Field(default=DEFAULT_PLAYBACK_FPS, ge=6, le=30)


@app.post("/compile")
def compile_endpoint(req: CompileRequest) -> Dict[str, Any]:
    try:
        plan = sanitize_plan(req.plan)
        frames, report = compile_motion(plan, req.duration_seconds, req.playback_fps)
        return {"frames": frames, "playback_fps": req.playback_fps, "plan": plan, "report": report}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not compile supplied plan: {exc}") from exc


if __name__ == "__main__":
    import uvicorn
    print(f"Starting CogniCoach Motion Engine on http://{HOST}:{PORT}")
    print(f"Model: {MODEL}")
    print("Keep OPENAI_API_KEY in this server process; never paste it into browser JavaScript.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
