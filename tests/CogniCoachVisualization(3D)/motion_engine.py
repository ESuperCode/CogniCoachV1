"""CogniCoach Motion Engine: text prompt -> high-quality animation frames for the Unity ragdoll rig.

Pipeline
--------
1. PLAN    A cheap text model (default gpt-5-mini) writes keyframes in coach terms: where each hand
           is relative to the chest, where each foot is, hip height, trunk lean/twist, elbow
           direction, planted feet, two-handed grip. Cheap models are bad at joint angles and raw
           3D coordinates but good at "left fist 0.6 m in front at shoulder height".
2. CHECK   Keyframes are clamped, sign-convention mistakes are auto-corrected, and objective solver
           findings (unreachable targets, crossed feet...) trigger one cheap review call.
3. SOLVE   Overshoot-free cubic splines between keys, then hierarchical FK/IK on the rig measured
           from the Unity build: arm/leg IK with elbow/knee direction control, planted-foot locking,
           two-handed grips, torso collision avoidance, rotation-space smoothing.
4. EMIT    Unity local Euler angles (Z-X-Y) per joint, in the sparse frame format that
           RagdollTest_AI.html sends to WebBridge.UpdateMotion.

Rig facts (verified by rendering the WebGL build):
- Unity axes: +X avatar right, +Y up, +Z avatar forward. Rotations compose parent * local.
- Hierarchy: body -> {hip -> {lefthip -> leftknee, righthip -> rightknee},
                      spine -> {leftshoulder -> leftelbow, rightshoulder -> rightelbow, neck}}.
- Knee flexion = +X local, elbow flexion = -X local, spine +X = lean forward, +Y = twist right.
- positionx/y/z are NOT translations: they are the whole-body rotation (pitch/yaw/roll).
  The rig has no root translation; frames carry "rooty" (metres) which the HTML shows by sliding
  the canvas and which a future WebBridge can apply to the hips.

Run:
    python -m pip install --upgrade openai fastapi uvicorn numpy pydantic
    python motion_engine.py              (OPENAI_API_KEY from the environment or a .env file)
    python motion_engine.py --selftest   (offline solver check)
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
import math
import os
import re
import threading
import time
import traceback
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple

import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

try:  # The compiler works without the SDK (e.g. /compile), only /generate needs it.
    from openai import OpenAI
except Exception:  # pragma: no cover
    OpenAI = None  # type: ignore

# -----------------------------------------------------------------------------
# Settings
# -----------------------------------------------------------------------------

def _load_dotenv(path: Path) -> None:
    """Minimal .env support (KEY=VALUE lines) so the API key only has to be saved once.

    Existing environment variables always win. The repository's .gitignore excludes .env files.
    """
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


_load_dotenv(Path(__file__).with_name(".env"))

MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
REASONING_EFFORT = os.getenv("MOTION_REASONING_EFFORT", "low")
HOST = os.getenv("MOTION_HOST", "127.0.0.1")
PORT = int(os.getenv("MOTION_PORT", "8000"))
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("MOTION_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
CACHE_SIZE = int(os.getenv("MOTION_CACHE_SIZE", "256"))
CACHE_DIR = os.getenv("MOTION_CACHE_DIR", "")  # optional on-disk cache of plans
RIG_INFO_PATH = Path(__file__).with_name("rig_info.md")

DEFAULT_FPS = 24
HIP_DROP_SCALE = 0.85  # the rig's legs are ~15% shorter than a real 1.75 m athlete's
MAX_FRAMES = 360
SPARSE_EPS_DEG = 0.05

# -----------------------------------------------------------------------------
# Rig geometry, in rig units (1 unit ~ 2.1 cm; the avatar is ~82 units tall).
# Measured from the Unity WebGL build (T-pose and side renders) and rig_info.md.
# -----------------------------------------------------------------------------
UNIT_TO_M = 1.75 / 82.0
SHOULDER_OFFSET = (14.0, 22.5, 0.0)   # from spine base, +x for right
HIP_OFFSET = (6.0, -1.0, 0.0)         # from hip joint
NECK_OFFSET = (0.0, 30.0, 0.0)
UPPER_ARM = 15.0
FOREARM = 16.0
THIGH = 16.5
SHIN = 17.0
LIMB_RADIUS = 3.75
TORSO_HALF = (10.0, 15.0, 5.0)        # torso box half extents, centre at (0,15,0) in spine frame
PELVIS_HALF = (10.0, 5.0, 5.0)        # pelvis box, centre at origin of hip frame
SOLE_DROP = 3.0                       # ankle pivot to sole

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
# Keyframe parameter model (what the language model writes)
# -----------------------------------------------------------------------------
# name: (min, max, neutral)
GROUP_PARAMS: Dict[str, Dict[str, Tuple[float, float, float]]] = {
    "body": {"pitch": (-200, 200, 0), "turn": (-1080, 1080, 0), "roll": (-200, 200, 0)},
    # pelvis.height: metres the hips are lowered (-) or raised (+) versus standing tall.
    "pelvis": {"tilt": (-25, 35, 0), "twist": (-60, 60, 0), "side": (-25, 25, 0), "height": (-0.6, 0.8, 0)},
    "torso": {"lean": (-35, 95, 0), "twist": (-65, 65, 0), "side_bend": (-40, 40, 0)},
    "head": {"nod": (-45, 55, 0), "turn": (-75, 75, 0), "tilt": (-35, 35, 0)},
    # Hands: metres in the chest frame. Origin = middle of the shoulder line; +forward out of the
    # chest, +up toward the head, +side = outward toward that hand's own side, - = across the body.
    "right_hand": {"forward": (-0.7, 0.8, 0.05), "up": (-0.75, 0.75, -0.6), "out": (-0.65, 1.0, 0.33)},
    "left_hand": {"forward": (-0.7, 0.8, 0.05), "up": (-0.75, 0.75, -0.6), "out": (-0.65, 1.0, 0.33)},
    # Feet: metres in the body frame (does not turn with pelvis/torso twist). forward/out are
    # measured from the point under the pelvis centre; lift = sole height above the floor.
    "right_foot": {"forward": (-0.8, 0.9, 0.0), "out": (-0.25, 0.8, 0.12), "lift": (0.0, 1.0, 0.0), "toe_out": (-30, 70, 10)},
    "left_foot": {"forward": (-0.8, 0.9, 0.0), "out": (-0.25, 0.8, 0.12), "lift": (0.0, 1.0, 0.0), "toe_out": (-30, 70, 10)},
}
GROUP_ORDER = list(GROUP_PARAMS.keys())
FLAG_KEYS = ["left_foot_planted", "right_foot_planted", "hands_together"]
ELBOW_CHOICES = ["down", "out", "back", "up", "forward"]
ELBOW_KEYS = ["right_elbow_points", "left_elbow_points"]
PARAM_PATHS: List[Tuple[str, str]] = [(g, p) for g in GROUP_ORDER for p in GROUP_PARAMS[g]]
CIRCULAR_PATHS = {("body", "turn")}


def _num(v: Any, default: float) -> float:
    try:
        f = float(v)
        return f if math.isfinite(f) else default
    except Exception:
        return default


def neutral_keyframe(t: float = 0.0) -> Dict[str, Any]:
    kf: Dict[str, Any] = {"t": t, "phase": "neutral"}
    for g in GROUP_ORDER:
        kf[g] = {p: spec[2] for p, spec in GROUP_PARAMS[g].items()}
    kf["left_foot_planted"] = True
    kf["right_foot_planted"] = True
    kf["hands_together"] = False
    kf["right_elbow_points"] = "down"
    kf["left_elbow_points"] = "down"
    return kf


def sanitize_keyframe(raw: Dict[str, Any], t_default: float) -> Dict[str, Any]:
    kf = neutral_keyframe(t_default)
    if not isinstance(raw, dict):
        return kf
    kf["t"] = _num(raw.get("t", t_default), t_default)
    kf["phase"] = str(raw.get("phase", "phase"))[:48]
    for g in GROUP_ORDER:
        src = raw.get(g) if isinstance(raw.get(g), dict) else {}
        for p, (lo, hi, neutral) in GROUP_PARAMS[g].items():
            kf[g][p] = max(lo, min(hi, _num(src.get(p, neutral), neutral)))
    reach = (UPPER_ARM + FOREARM) * UNIT_TO_M + 0.05
    sh = SHOULDER_OFFSET[0] * UNIT_TO_M
    for hk in ("right_hand", "left_hand"):
        h = kf[hk]
        far = math.dist((h["out"], h["up"], h["forward"]), (sh, 0.0, 0.0))
        near = math.dist((-h["out"], h["up"], h["forward"]), (sh, 0.0, 0.0))
        if far > reach and near <= reach:
            h["out"] = -h["out"]  # the planner used the opposite sign convention for this hand
    # torso.lean is relative to the body; a planner that writes "plank" into both body.pitch and
    # torso.lean would fold the athlete head-down. Cap the combined forward bend.
    pitch = kf["body"]["pitch"]
    if pitch > 40:
        kf["torso"]["lean"] = min(kf["torso"]["lean"], max(0.0, 100.0 - pitch))
    elif pitch < -40:
        kf["torso"]["lean"] = max(kf["torso"]["lean"], min(0.0, -100.0 - pitch))
    for k in ELBOW_KEYS:
        v = str(raw.get(k, "down")).lower()
        kf[k] = v if v in ELBOW_CHOICES else "down"
    for k in FLAG_KEYS:
        kf[k] = bool(raw.get(k, k != "hands_together"))
    return kf


def fix_mirrored_left_side(kfs: List[Dict[str, Any]]) -> None:
    """Detect a plan that used signed X (left = negative) instead of the 'outward' rule and fix it.

    If most keyframes put the LEFT foot/hand across the body exactly where a mirrored right one
    would be, the planner meant "out to the left": flip the sign for the whole plan.
    """
    for part, thresh in (("foot", 0.05), ("hand", 0.1)):
        votes = 0
        usable = 0
        for kf in kfs:
            if part == "hand" and kf.get("hands_together"):
                continue
            usable += 1
            lo, ro = kf[f"left_{part}"]["out"], kf[f"right_{part}"]["out"]
            if lo < -thresh and ro > thresh:
                votes += 1
        if usable and votes / usable >= 0.6:
            for kf in kfs:
                kf[f"left_{part}"]["out"] = -kf[f"left_{part}"]["out"]


def sanitize_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("Plan must be an object.")
    raw = plan.get("keyframes")
    if not isinstance(raw, list) or len(raw) < 2:
        raise ValueError("Plan needs at least two keyframes.")
    n = len(raw)
    kfs = [sanitize_keyframe(k, i / max(1, n - 1)) for i, k in enumerate(raw)]
    kfs.sort(key=lambda k: k["t"])
    ts = np.array([k["t"] for k in kfs], dtype=float)
    if ts[-1] - ts[0] < 1e-6:
        ts = np.linspace(0, 1, n)
    ts = (ts - ts[0]) / (ts[-1] - ts[0])
    # Enforce a minimum spacing so splines stay well behaved.
    for i in range(1, n):
        ts[i] = max(ts[i], ts[i - 1] + 0.012)
    ts = ts / ts[-1]
    for k, t in zip(kfs, ts):
        k["t"] = float(t)
    fix_mirrored_left_side(kfs)
    loop = bool(plan.get("loop", False))
    duration = _num(plan.get("duration_seconds", 2.0), 2.0)
    view = str(plan.get("camera_view", "three_quarter"))
    if view not in ("front", "side", "three_quarter", "back"):
        view = "three_quarter"
    cues = plan.get("coaching_cues") if isinstance(plan.get("coaching_cues"), list) else []
    return {
        "title": str(plan.get("title", ""))[:80],
        "movement_summary": str(plan.get("movement_summary", ""))[:800],
        "coaching_cues": [str(c)[:160] for c in cues[:6]],
        "loop": loop,
        "duration_seconds": max(0.6, min(8.0, duration)),
        "camera_view": view,
        "keyframes": kfs,
    }


def mirror_text(text: str) -> str:
    """Swap left/right wording (keeps capitalisation) for left-handed athletes."""
    def swap(m: "re.Match[str]") -> str:
        word = m.group(0)
        out = {"left": "right", "right": "left"}[word.lower()]
        if word.isupper():
            return out.upper()
        return out.capitalize() if word[0].isupper() else out
    return re.sub(r"\b(left|right)\b", swap, text, flags=re.IGNORECASE)


def mirror_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Mirror a right-handed plan into a left-handed one (swap sides, negate lateral/axial values)."""
    out = copy.deepcopy(plan)
    out["dominant_side"] = "left" if plan.get("dominant_side", "right") == "right" else "right"
    for kf in out["keyframes"]:
        kf["right_hand"], kf["left_hand"] = kf["left_hand"], kf["right_hand"]
        kf["right_elbow_points"], kf["left_elbow_points"] = kf["left_elbow_points"], kf["right_elbow_points"]
        kf["right_foot"], kf["left_foot"] = kf["left_foot"], kf["right_foot"]
        kf["left_foot_planted"], kf["right_foot_planted"] = kf["right_foot_planted"], kf["left_foot_planted"]
        kf["body"]["turn"] *= -1
        kf["body"]["roll"] *= -1
        kf["pelvis"]["twist"] *= -1
        kf["pelvis"]["side"] *= -1
        kf["torso"]["twist"] *= -1
        kf["torso"]["side_bend"] *= -1
        kf["head"]["turn"] *= -1
        kf["head"]["tilt"] *= -1
    return out


# -----------------------------------------------------------------------------
# Rotation math (Unity conventions: Quaternion.Euler applies Z, then X, then Y)
# -----------------------------------------------------------------------------

def rx(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=float)


def ry(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=float)


def rz(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=float)


def euler_to_matrix(x: float, y: float, z: float) -> np.ndarray:
    return ry(y) @ rx(x) @ rz(z)


def matrix_to_euler(m: np.ndarray) -> Tuple[float, float, float]:
    """Inverse of euler_to_matrix (matches quaternionToEuler in the HTML)."""
    x = math.asin(max(-1.0, min(1.0, -m[1, 2])))
    if abs(math.cos(x)) > 1e-6:
        y = math.atan2(m[0, 2], m[2, 2])
        z = math.atan2(m[1, 0], m[1, 1])
    else:
        y = math.atan2(-m[2, 0], m[0, 0])
        z = 0.0
    return math.degrees(x), math.degrees(y), math.degrees(z)


def axis_angle(axis: np.ndarray, deg: float) -> np.ndarray:
    a = np.asarray(axis, dtype=float)
    n = np.linalg.norm(a)
    if n < 1e-9 or abs(deg) < 1e-9:
        return np.eye(3)
    a = a / n
    th = math.radians(deg)
    k = np.array([[0, -a[2], a[1]], [a[2], 0, -a[0]], [-a[1], a[0], 0]], dtype=float)
    return np.eye(3) + math.sin(th) * k + (1 - math.cos(th)) * (k @ k)


def orthonormalize(m: np.ndarray) -> np.ndarray:
    u, _, vt = np.linalg.svd(m)
    r = u @ vt
    if np.linalg.det(r) < 0:
        u[:, -1] *= -1
        r = u @ vt
    return r


DOWN = np.array([0.0, -1.0, 0.0])


def limb_local_rotation(raise_deg: float, direction_deg: float, twist_deg: float, side_sign: float) -> np.ndarray:
    """Swing a limb hanging straight down by `raise` within the vertical plane `direction`.

    direction 0 = forward, 90 = out to the limb's own side, 180 = backward, negative = across the body.
    side_sign is +1 for right limbs (+X), -1 for left limbs.
    """
    d = math.radians(direction_deg)
    horizontal = np.array([side_sign * math.sin(d), 0.0, math.cos(d)])
    axis = np.cross(DOWN, horizontal)
    swing = axis_angle(axis, raise_deg)
    return swing @ ry(side_sign * twist_deg)


# -----------------------------------------------------------------------------
# Pose -> local joint rotations -> forward kinematics
# -----------------------------------------------------------------------------

def pose_local_rotations(kf: Dict[str, Any]) -> Dict[str, np.ndarray]:
    b, pv, to, hd = kf["body"], kf["pelvis"], kf["torso"], kf["head"]
    rot: Dict[str, np.ndarray] = {
        "body": euler_to_matrix(b["pitch"], b["turn"], -b["roll"]),
        "hip": euler_to_matrix(pv["tilt"], pv["twist"], -pv["side"]),
        # Torso twist is the shoulder-line rotation relative to the body's facing (the rig parents
        # spine and pelvis both to the body, so hips and shoulders rotate independently).
        "spine": euler_to_matrix(to["lean"], to["twist"], -to["side_bend"]),
        "neck": euler_to_matrix(hd["nod"], hd["turn"], -hd["tilt"]),
    }
    for side, sign in (("right", 1.0), ("left", -1.0)):
        # Arms start hanging; they are solved by IK onto the hand targets in compile_motion.
        rot[f"{side}shoulder"] = limb_local_rotation(5.0, 90.0, 0.0, sign)
        rot[f"{side}elbow"] = rx(-10.0)
        # Legs start straight; they are solved by IK onto the foot targets in compile_motion.
        rot[f"{side}hip"] = np.eye(3)
        rot[f"{side}knee"] = rx(5.0)
    return rot


def world_rotations(local: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    w: Dict[str, np.ndarray] = {"body": local["body"]}
    w["hip"] = w["body"] @ local["hip"]
    w["spine"] = w["body"] @ local["spine"]
    w["neck"] = w["spine"] @ local["neck"]
    for s in ("left", "right"):
        w[s + "hip"] = w["hip"] @ local[s + "hip"]
        w[s + "knee"] = w[s + "hip"] @ local[s + "knee"]
        w[s + "shoulder"] = w["spine"] @ local[s + "shoulder"]
        w[s + "elbow"] = w[s + "shoulder"] @ local[s + "elbow"]
    return w


def forward_kinematics(world: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    p: Dict[str, np.ndarray] = {"pelvis": np.zeros(3)}
    p["neck"] = world["spine"] @ np.array(NECK_OFFSET)
    p["head"] = p["neck"] + world["neck"] @ np.array([0.0, 8.0, 0.0])
    p["chest"] = world["spine"] @ np.array([0.0, 15.0, 0.0])
    for s, sign in (("right", 1.0), ("left", -1.0)):
        sh = world["spine"] @ np.array([sign * SHOULDER_OFFSET[0], SHOULDER_OFFSET[1], 0.0])
        el = sh + world[s + "shoulder"] @ np.array([0.0, -UPPER_ARM, 0.0])
        ha = el + world[s + "elbow"] @ np.array([0.0, -FOREARM, 0.0])
        hp = world["hip"] @ np.array([sign * HIP_OFFSET[0], HIP_OFFSET[1], 0.0])
        kn = hp + world[s + "hip"] @ np.array([0.0, -THIGH, 0.0])
        an = kn + world[s + "knee"] @ np.array([0.0, -SHIN, 0.0])
        p.update({s + "_shoulder": sh, s + "_elbow": el, s + "_hand": ha,
                  s + "_hip": hp, s + "_knee": kn, s + "_foot": an})
    return p


# -----------------------------------------------------------------------------
# Two-bone IK in world space
# -----------------------------------------------------------------------------

def two_bone_ik(root: np.ndarray, target: np.ndarray, pole: np.ndarray, l1: float, l2: float,
                parent_world: np.ndarray, chain: str, memory: Optional[Dict[str, np.ndarray]] = None,
                key: str = "") -> Tuple[np.ndarray, np.ndarray, float]:
    """Return (upper_local, lower_local, residual) so the chain end reaches target.

    `pole` is the world direction the middle joint (knee/elbow) should point towards.
    Knees bend with +X (cap points local +Z); elbows bend with -X (point local -Z).
    """
    v = target - root
    dist = float(np.linalg.norm(v))
    dist_c = max(abs(l1 - l2) + 0.5, min(l1 + l2 - 0.05, dist))
    if dist < 1e-6:
        v = DOWN.copy()
        dist = 1.0
    vdir = v / max(dist, 1e-9)
    cos_mid = (l1 * l1 + l2 * l2 - dist_c * dist_c) / (2 * l1 * l2)
    bend = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos_mid))))
    cos_a = (l1 * l1 + dist_c * dist_c - l2 * l2) / (2 * l1 * dist_c)
    alpha = math.acos(max(-1.0, min(1.0, cos_a)))
    pole_len = float(np.linalg.norm(pole))
    pole = pole / max(1e-9, pole_len) * min(1.0, pole_len)
    pole_perp = pole - np.dot(pole, vdir) * vdir
    strength = float(np.linalg.norm(pole_perp))
    prev = memory.get(key) if memory is not None else None
    if prev is not None:
        prev_perp = prev - np.dot(prev, vdir) * vdir
        if np.linalg.norm(prev_perp) > 1e-6:
            prev_perp /= np.linalg.norm(prev_perp)
            # When the hint is nearly parallel to the limb it carries no information: keep the
            # previous bend plane instead (prevents the limb from flipping/rolling between frames).
            w = min(1.0, strength / 0.45)
            pole_perp = (pole_perp / max(strength, 1e-9)) * w + prev_perp * (1.0 - w) if strength > 1e-9 else prev_perp
    if np.linalg.norm(pole_perp) < 1e-6:
        alt = np.array([0.0, 0.0, 1.0]) if abs(vdir[2]) < 0.9 else np.array([1.0, 0.0, 0.0])
        pole_perp = alt - np.dot(alt, vdir) * vdir
    pole_perp /= np.linalg.norm(pole_perp)
    if memory is not None:
        memory[key] = pole_perp.copy()
    mid_dir = math.cos(alpha) * vdir + math.sin(alpha) * pole_perp  # root -> middle joint
    y_axis = -mid_dir
    hinge_out = pole_perp - np.dot(pole_perp, y_axis) * y_axis
    hinge_out /= max(1e-9, np.linalg.norm(hinge_out))
    z_axis = hinge_out if chain == "leg" else -hinge_out
    x_axis = np.cross(y_axis, z_axis)
    upper_world = np.column_stack([x_axis, y_axis, z_axis])
    lower_local = rx(bend) if chain == "leg" else rx(-bend)
    upper_local = parent_world.T @ upper_world
    mid = root + mid_dir * l1
    end = mid + (upper_world @ lower_local) @ np.array([0.0, -l2, 0.0])
    return upper_local, lower_local, float(np.linalg.norm(end - target))


# -----------------------------------------------------------------------------
# Spline interpolation of keyframes (monotone cubic: smooth, no overshoot)
# -----------------------------------------------------------------------------

def pchip_slopes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    n = len(x)
    h = np.diff(x)
    delta = np.diff(y) / h
    m = np.zeros(n)
    if n == 2:
        m[:] = delta[0]
        return m
    for i in range(1, n - 1):
        if delta[i - 1] * delta[i] <= 0:
            m[i] = 0.0
        else:
            w1 = 2 * h[i] + h[i - 1]
            w2 = h[i] + 2 * h[i - 1]
            m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i])
    # End slopes: one-sided three-point, limited.
    def end(h0, h1, d0, d1):
        s = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1)
        if np.sign(s) != np.sign(d0):
            return 0.0
        if np.sign(d0) != np.sign(d1) and abs(s) > abs(3 * d0):
            return 3 * d0
        return s
    m[0] = end(h[0], h[1], delta[0], delta[1])
    m[-1] = end(h[-1], h[-2], delta[-1], delta[-2])
    return m


def hermite(x: np.ndarray, y: np.ndarray, m: np.ndarray, t: np.ndarray) -> np.ndarray:
    idx = np.clip(np.searchsorted(x, t, side="right") - 1, 0, len(x) - 2)
    x0, x1 = x[idx], x[idx + 1]
    h = x1 - x0
    u = np.clip((t - x0) / h, 0.0, 1.0)
    h00 = 2 * u**3 - 3 * u**2 + 1
    h10 = u**3 - 2 * u**2 + u
    h01 = -2 * u**3 + 3 * u**2
    h11 = u**3 - u**2
    return h00 * y[idx] + h10 * h * m[idx] + h01 * y[idx + 1] + h11 * h * m[idx + 1]


def interpolate_channel(ts: np.ndarray, vals: np.ndarray, samples: np.ndarray, loop: bool) -> np.ndarray:
    if loop:
        # Pad one key on each side from the neighbouring cycles for periodic tangents.
        x = np.concatenate([[ts[-2] - 1.0], ts, [1.0 + ts[1]]])
        y = np.concatenate([[vals[-2]], vals, [vals[1]]])
    else:
        x, y = ts, vals
    m = pchip_slopes(x, y)
    return hermite(x, y, m, samples)


# -----------------------------------------------------------------------------
# Compiler
# -----------------------------------------------------------------------------

def _elbow_pole(world: Dict[str, np.ndarray], side: str) -> np.ndarray:
    return -world[side + "shoulder"][:, 2]


def _segment_box_penetration(a: np.ndarray, b: np.ndarray, frame_rot: np.ndarray, centre: np.ndarray,
                             half: Sequence[float], radius: float) -> Tuple[float, np.ndarray]:
    """Max penetration depth of segment a-b (with radius) into an oriented box, plus push dir (world)."""
    best, push = 0.0, np.zeros(3)
    hx, hy, hz = half
    for u in np.linspace(0.0, 1.0, 7):
        p = a + (b - a) * u
        q = frame_rot.T @ (p - centre)
        gaps = np.array([hx + radius - abs(q[0]), hy + radius - abs(q[1]), hz + radius - abs(q[2])])
        if np.all(gaps > 0):
            depth = float(np.min(gaps))
            if depth > best:
                axis = int(np.argmin(gaps))
                local = np.zeros(3)
                local[axis] = math.copysign(1.0, q[axis] if abs(q[axis]) > 1e-6 else 1.0)
                best, push = depth, frame_rot @ local
    return best, push


def _resolve_arm_collisions(kf: Dict[str, Any], local: Dict[str, np.ndarray], world: Dict[str, np.ndarray],
                            pos: Dict[str, np.ndarray], side: str) -> int:
    """Push an arm out of the torso by re-solving IK on a hand target moved out of the body."""
    torso_centre = world["spine"] @ np.array([0.0, TORSO_HALF[1], 0.0])
    fixes = 0
    for _ in range(4):
        d1, p1 = _segment_box_penetration(pos[side + "_shoulder"] + (pos[side + "_elbow"] - pos[side + "_shoulder"]) * 0.35,
                                          pos[side + "_elbow"], world["spine"], torso_centre, TORSO_HALF, LIMB_RADIUS * 0.8)
        d2, p2 = _segment_box_penetration(pos[side + "_elbow"], pos[side + "_hand"], world["spine"], torso_centre,
                                          TORSO_HALF, LIMB_RADIUS * 0.8)
        depth, push = (d1, p1) if d1 >= d2 else (d2, p2)
        if depth < 0.05:
            break
        # Prefer pushing forwards (in front of the chest) unless the limb is clearly behind.
        fwd = world["spine"][:, 2]
        if np.dot(push, fwd) < -0.5:
            direction = push
        elif abs(np.dot(push, world["spine"][:, 0])) > 0.7:
            direction = push
        else:
            direction = fwd
        target = pos[side + "_hand"] + direction * depth
        root = pos[side + "_shoulder"]
        upper, lower, _ = two_bone_ik(root, target, _elbow_pole(world, side), UPPER_ARM, FOREARM, world["spine"], "arm")
        local[side + "shoulder"], local[side + "elbow"] = upper, lower
        world.update(world_rotations(local))
        pos.update(forward_kinematics(world))
        fixes += 1
    return fixes


def keep_hand_outside_torso(p: np.ndarray, own_side: float = 0.0) -> np.ndarray:
    """Continuously push a chest-frame hand target (metres, x = athlete right) out of the torso.

    The hand leaves through the nearest of three exits - in front of the body, behind it, or past
    its own side (how real hands swing past the hips). Exits are blended with a soft-min, so a hand
    travelling through the torso region slides around it instead of teleporting.
    """
    side, up, fwd = float(p[0]), float(p[1]), float(p[2])
    half_w = TORSO_HALF[0] * UNIT_TO_M + 0.07
    top = (2 * TORSO_HALF[1] - SHOULDER_OFFSET[1]) * UNIT_TO_M + 0.05
    bottom = -SHOULDER_OFFSET[1] * UNIT_TO_M - 0.12          # includes the pelvis
    face = TORSO_HALF[2] * UNIT_TO_M + 0.08

    def ramp(x: float, edge: float, soft: float = 0.06) -> float:
        return max(0.0, min(1.0, (edge - x) / soft))

    w = ramp(abs(side), half_w) * ramp(up, top) * ramp(-up, -bottom) * ramp(abs(fwd), face, 0.04)
    if w <= 0.0:
        return p
    sgn = own_side if own_side else (1.0 if side >= 0 else -1.0)
    candidates = [
        (np.array([side, up, face]), face - fwd),                     # front
        (np.array([side, up, -face]), face + fwd + 0.15),             # back (strongly disfavoured)
        (np.array([sgn * half_w, up, fwd]), half_w - sgn * side),     # past its own side
    ]
    tau = 0.035
    weights = np.array([math.exp(-max(0.0, d) / tau) for _, d in candidates])
    target = sum(wt * c for wt, (c, _) in zip(weights, candidates)) / weights.sum()
    return p + (target - p) * w


def elbow_pole_vector(choice: str, sign: float) -> np.ndarray:
    """Direction (chest frame) the elbow should point for each hint."""
    table = {
        "down": (0.35, -1.0, -0.25),
        "out": (1.0, -0.25, -0.1),
        "back": (0.3, -0.35, -1.0),
        "up": (0.45, 1.0, -0.1),
        "forward": (0.1, -0.35, 1.0),
    }
    x, y, z = table.get(choice, table["down"])
    v = np.array([sign * x, y, z], dtype=float)
    return v / np.linalg.norm(v)


def compile_motion(plan: Dict[str, Any], duration_seconds: Optional[float] = None, fps: int = DEFAULT_FPS,
                   return_to_start: bool = True) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
    kfs = plan["keyframes"]
    loop = bool(plan.get("loop", False))
    duration = float(duration_seconds or plan.get("duration_seconds", 2.0))
    ts = np.array([k["t"] for k in kfs], dtype=float)

    if loop:
        # Close the cycle: the final key must equal the first.
        last = copy.deepcopy(kfs[0])
        last["t"] = 1.0
        if ts[-1] >= 0.999:
            kfs = kfs[:-1] + [last]
        else:
            kfs = kfs + [last]
        ts = np.array([k["t"] for k in kfs], dtype=float)
        if len(kfs) < 3:
            mid = copy.deepcopy(kfs[0]); mid["t"] = 0.5
            kfs = [kfs[0], mid, kfs[-1]]
            ts = np.array([0.0, 0.5, 1.0])

    n_frames = max(2, min(MAX_FRAMES, int(round(duration * fps))))
    if loop:
        samples = np.arange(n_frames) / n_frames  # exclude t=1 (same as t=0)
    else:
        samples = np.linspace(0.0, 1.0, n_frames)

    # Continuous params via monotone splines.
    channels: Dict[Tuple[str, str], np.ndarray] = {}
    for g, p in PARAM_PATHS:
        vals = np.array([k[g][p] for k in kfs], dtype=float)
        channels[(g, p)] = interpolate_channel(ts, vals, samples, loop)

    # Discrete flags: take the value of the segment we are in, but treat a flag as true only if
    # both bounding keys agree (feet lift off/land exactly at keys).
    def flag_at(name: str, t: float) -> Tuple[bool, float]:
        i = int(np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(ts) - 2))
        a, b = kfs[i][name], kfs[i + 1][name]
        u = (t - ts[i]) / max(1e-9, ts[i + 1] - ts[i])
        if a and b:
            return True, 1.0
        if a and not b:
            return u < 0.5, max(0.0, 1.0 - u * 2.0)
        if b and not a:
            return u > 0.5, max(0.0, u * 2.0 - 1.0)
        return False, 0.0

    # Elbow direction hints become pole vectors (chest frame) that blend smoothly between keys.
    pole_channels: Dict[str, np.ndarray] = {}
    for s, sign in (("right", 1.0), ("left", -1.0)):
        vecs = np.array([elbow_pole_vector(k[f"{s}_elbow_points"], sign) for k in kfs])
        pole_channels[s] = np.stack([interpolate_channel(ts, vecs[:, a], samples, loop) for a in range(3)], axis=1)

    poses: List[Dict[str, Any]] = []
    for si, t in enumerate(samples):
        kf = {"t": float(t)}
        for g in GROUP_ORDER:
            kf[g] = {p: float(channels[(g, p)][si]) for p in GROUP_PARAMS[g]}
        for s in ("left", "right"):
            # Not normalised: a short blended vector (between opposite hints) means "weak hint".
            kf[f"{s}_elbow_pole"] = pole_channels[s][si]
            kf[f"{s}_foot"]["lift"] = max(0.0, kf[f"{s}_foot"]["lift"])
        kf["flags"] = {name: flag_at(name, float(t)) for name in FLAG_KEYS}
        poses.append(kf)

    # Foot locking: while a foot is planted it stays where it was at touchdown (world space; the
    # pelvis is the fixed origin because the rig cannot translate).
    locks: Dict[str, Optional[np.ndarray]] = {"left": None, "right": None}
    if loop:
        # Seed locks from the end of the cycle so the loop seam does not pop.
        pass
    frames: List[Dict[str, float]] = []
    stats = {"foot_lock_frames": 0, "grip_frames": 0, "collision_fixes": 0, "ik_residual_max": 0.0}
    track: List[Dict[str, np.ndarray]] = []
    rot_track: List[Dict[str, np.ndarray]] = []
    body_track: List[Dict[str, float]] = []
    ik_memory: Dict[str, np.ndarray] = {}
    root_y: List[float] = []
    dominant = "left" if plan.get("dominant_side") == "left" else "right"
    off = "right" if dominant == "left" else "left"
    for kf in poses:
        local = pose_local_rotations(kf)
        world = world_rotations(local)
        pos = forward_kinematics(world)
        for side in ("left", "right"):
            hand = kf[f"{side}_hand"]
            sgn = 1.0 if side == "right" else -1.0
            point_m = np.array([sgn * hand["out"], hand["up"], hand["forward"]])
            grip_w = kf["flags"]["hands_together"][1]
            if side == dominant and grip_w > 0.0:
                # Two hands on one implement: the grip point must be reachable by BOTH arms, so pull
                # it toward the off-hand shoulder until it is (the model never has to get this right).
                off_sh = np.array([(-sgn) * SHOULDER_OFFSET[0] * UNIT_TO_M, 0.0, 0.0])
                d = float(np.linalg.norm(point_m - off_sh))
                limit = 0.58
                if d > limit:
                    fixed = off_sh + (point_m - off_sh) * (limit / d)
                    point_m = point_m + (fixed - point_m) * grip_w
            chest_point = keep_hand_outside_torso(point_m, sgn) / UNIT_TO_M
            target = world["spine"] @ (chest_point + np.array([0.0, SHOULDER_OFFSET[1], 0.0]))
            upper, lower, _ = two_bone_ik(pos[side + "_shoulder"], target, world["spine"] @ kf[f"{side}_elbow_pole"],
                                          UPPER_ARM, FOREARM, world["spine"], "arm", ik_memory, side + "_arm")
            local[side + "shoulder"], local[side + "elbow"] = upper, lower
        world = world_rotations(local)
        pos = forward_kinematics(world)

        # Feet: targets come from the planner (body frame). The floor sits below the pelvis by the
        # standing leg length minus the hip drop, so lowering the hips bends the knees naturally.
        # While a foot is planted its horizontal position is locked at touchdown (no skating, and
        # the hips can twist over planted feet).
        ankle_standing = HIP_OFFSET[1] - THIGH - SHIN  # ankle height below the pelvis when standing
        # Negative height lowers the hips (bends the legs; scaled to this rig's shorter legs).
        # Positive height means the whole body is airborne: legs stay as they are, the root rises.
        hip_drop = min(0.0, kf["pelvis"]["height"]) * HIP_DROP_SCALE / UNIT_TO_M
        for side, sign in (("left", -1.0), ("right", 1.0)):
            foot = kf[f"{side}_foot"]
            local_target = np.array([sign * foot["out"] / UNIT_TO_M,
                                     ankle_standing - hip_drop + foot["lift"] / UNIT_TO_M,
                                     foot["forward"] / UNIT_TO_M])
            target = world["body"] @ local_target
            planted, weight = kf["flags"][f"{side}_foot_planted"]
            if planted and locks[side] is None:
                locks[side] = target.copy()
            if not planted:
                locks[side] = None
            if locks[side] is not None and weight > 0.0:
                anchor = locks[side].copy()
                anchor[1] = target[1]
                target = target + (anchor - target) * weight
                stats["foot_lock_frames"] += 1
            toe = math.radians(sign * foot["toe_out"])
            knee_dir = world["body"] @ np.array([math.sin(toe) + sign * 0.15, -0.15, math.cos(toe)])
            upper, lower, res = two_bone_ik(pos[side + "_hip"], target, knee_dir,
                                            THIGH, SHIN, world["hip"], "leg", ik_memory, side + "_leg")
            local[side + "hip"], local[side + "knee"] = upper, lower
            stats["ik_residual_max"] = max(stats["ik_residual_max"], res * UNIT_TO_M)
        world = world_rotations(local)
        pos = forward_kinematics(world)

        together, w_grip = kf["flags"]["hands_together"]
        if w_grip > 0.0:
            # The dominant hand leads; the other hand grips just next to it on the same handle.
            lead = pos[f"{dominant}_hand"]
            to_shoulder = pos[f"{off}_shoulder"] - lead
            n = np.linalg.norm(to_shoulder)
            grip = lead + (to_shoulder / n) * min(4.0, n * 0.5) if n > 1e-6 else lead
            free = pos[f"{off}_hand"]
            target = free + (grip - free) * w_grip
            upper, lower, _ = two_bone_ik(pos[f"{off}_shoulder"], target, _elbow_pole(world, off),
                                          UPPER_ARM, FOREARM, world["spine"], "arm", ik_memory, off + "_grip")
            local[off + "shoulder"], local[off + "elbow"] = upper, lower
            world = world_rotations(local)
            pos = forward_kinematics(world)
            stats["grip_frames"] += 1

        for side in ("left", "right"):
            if side == off and w_grip > 0.5:
                continue
            stats["collision_fixes"] += _resolve_arm_collisions(kf, local, world, pos, side)

        track.append({k: v.copy() for k, v in pos.items()})
        root_y.append(kf["pelvis"]["height"])
        rot_track.append({k: orthonormalize(v) for k, v in local.items()})
        body_track.append(dict(kf["body"]))

    frames = frames_from_rotations(smooth_rotations(rot_track, loop), body_track)

    # Vertical root translation in metres (hip drop / jump height). Unity ignores it today; it is
    # here so a future WebBridge can move the pelvis for squats and jumps.
    for fr, ry_m in zip(frames, root_y):
        fr["rooty"] = round(float(ry_m), 4)

    if not loop and return_to_start and len(frames) > 4:
        frames = append_return(frames, fps)

    report = verify(plan, frames, track, fps, stats, loop)
    return frames, report


JOINT_NAMES = ["hip", "spine", "neck", "lefthip", "righthip", "leftknee", "rightknee",
               "leftshoulder", "rightshoulder", "leftelbow", "rightelbow"]


def smooth_rotations(rot_track: List[Dict[str, np.ndarray]], loop: bool) -> List[Dict[str, np.ndarray]]:
    """Light temporal smoothing done on rotation matrices (no Euler wrap/gimbal artefacts)."""
    n = len(rot_track)
    if n < 5:
        return rot_track
    out = []
    for i in range(n):
        if loop:
            ia, ib = (i - 1) % n, (i + 1) % n
        else:
            ia, ib = max(0, i - 1), min(n - 1, i + 1)
        frame = {}
        for j in rot_track[i]:
            m = 0.2 * rot_track[ia][j] + 0.6 * rot_track[i][j] + 0.2 * rot_track[ib][j]
            frame[j] = orthonormalize(m)
        out.append(frame)
    return out


def _closest_euler(m: np.ndarray, prev: Optional[Tuple[float, float, float]]) -> Tuple[float, float, float]:
    """Pick the Euler triple (of the two equivalent ZXY solutions) closest to the previous frame."""
    x, y, z = matrix_to_euler(m)
    if prev is None:
        return x, y, z
    alt = (180.0 - x, y + 180.0, z + 180.0)
    def wrap(v: float, ref: float) -> float:
        return ref + ((v - ref + 180.0) % 360.0 - 180.0)
    c1 = tuple(wrap(v, r) for v, r in zip((x, y, z), prev))
    c2 = tuple(wrap(v, r) for v, r in zip(alt, prev))
    d1 = sum(abs(v - r) for v, r in zip(c1, prev))
    d2 = sum(abs(v - r) for v, r in zip(c2, prev))
    return c1 if d1 <= d2 else c2


def frames_from_rotations(rot_track: List[Dict[str, np.ndarray]], body_track: List[Dict[str, float]]) -> List[Dict[str, float]]:
    frames: List[Dict[str, float]] = []
    prev: Dict[str, Tuple[float, float, float]] = {}
    for rots, body in zip(rot_track, body_track):
        f: Dict[str, float] = {}
        for j in JOINT_NAMES:
            e = _closest_euler(rots[j], prev.get(j))
            prev[j] = e
            f[j + "x"], f[j + "y"], f[j + "z"] = (round(v, 2) for v in e)
        # Body rotation is sent raw so multi-turn spins stay continuous.
        f["positionx"], f["positiony"], f["positionz"] = (round(body["pitch"], 2), round(body["turn"], 2),
                                                          round(-body["roll"], 2))
        frames.append(f)
    return frames


def frame_rotation(frame: Dict[str, float], joint: str) -> np.ndarray:
    return euler_to_matrix(frame.get(joint + "x", 0.0), frame.get(joint + "y", 0.0), frame.get(joint + "z", 0.0))


def rotation_angle_between(a: np.ndarray, b: np.ndarray) -> float:
    c = (np.trace(a.T @ b) - 1.0) / 2.0
    return math.degrees(math.acos(max(-1.0, min(1.0, c))))


def matrix_to_quat(m: np.ndarray) -> np.ndarray:
    w = math.sqrt(max(0.0, 1.0 + m[0, 0] + m[1, 1] + m[2, 2])) / 2.0
    x = math.copysign(math.sqrt(max(0.0, 1.0 + m[0, 0] - m[1, 1] - m[2, 2])) / 2.0, m[2, 1] - m[1, 2])
    y = math.copysign(math.sqrt(max(0.0, 1.0 - m[0, 0] + m[1, 1] - m[2, 2])) / 2.0, m[0, 2] - m[2, 0])
    z = math.copysign(math.sqrt(max(0.0, 1.0 - m[0, 0] - m[1, 1] + m[2, 2])) / 2.0, m[1, 0] - m[0, 1])
    q = np.array([w, x, y, z])
    return q / np.linalg.norm(q)


def quat_to_matrix(q: np.ndarray) -> np.ndarray:
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def slerp(qa: np.ndarray, qb: np.ndarray, u: float) -> np.ndarray:
    d = float(np.dot(qa, qb))
    if d < 0:
        qb, d = -qb, -d
    if d > 0.9995:
        q = qa + (qb - qa) * u
        return q / np.linalg.norm(q)
    th = math.acos(d)
    return (math.sin((1 - u) * th) * qa + math.sin(u * th) * qb) / math.sin(th)


def append_return(frames: List[Dict[str, float]], fps: int) -> List[Dict[str, float]]:
    """For one-shot actions: hold the finish, then ease back to the start pose so playback loops cleanly."""
    hold = max(2, int(round(0.3 * fps)))
    back = max(5, int(round(0.6 * fps)))
    last, first = frames[-1], frames[0]
    out = frames + [dict(last) for _ in range(hold)]
    qa = {j: matrix_to_quat(frame_rotation(last, j)) for j in JOINT_NAMES}
    qb = {j: matrix_to_quat(frame_rotation(first, j)) for j in JOINT_NAMES}
    prev = {j: (last[j + "x"], last[j + "y"], last[j + "z"]) for j in JOINT_NAMES}
    for i in range(1, back):
        u = i / back
        e = u * u * (3 - 2 * u)
        f: Dict[str, float] = {}
        for j in JOINT_NAMES:
            ex = _closest_euler(quat_to_matrix(slerp(qa[j], qb[j], e)), prev[j])
            prev[j] = ex
            f[j + "x"], f[j + "y"], f[j + "z"] = (round(v, 2) for v in ex)
        for k in POSITION_KEYS + ["rooty"]:
            a, b = float(last.get(k, 0.0)), float(first.get(k, 0.0))
            f[k] = round(a + (b - a) * e, 4)
        f["_return"] = 1
        out.append(f)
    return out


def sparse(frames: List[Dict[str, float]]) -> List[Dict[str, float]]:
    out = []
    for f in frames:
        s = {}
        for k, v in f.items():
            if k.startswith("_"):
                continue
            if abs(v) >= SPARSE_EPS_DEG or k == "rooty" and abs(v) >= 0.001:
                s[k] = v
        out.append(s)
    return out


# -----------------------------------------------------------------------------
# Verification (objective, cheap checks)
# -----------------------------------------------------------------------------

def verify(plan: Dict[str, Any], frames: List[Dict[str, float]], track: List[Dict[str, np.ndarray]], fps: int,
           stats: Dict[str, Any], loop: bool) -> Dict[str, Any]:
    issues: List[str] = []
    n = len(track)
    # Motion amount
    end_effectors = ["left_hand", "right_hand", "left_foot", "right_foot", "head"]
    travel = {k: float(sum(np.linalg.norm(track[i][k] - track[i - 1][k]) for i in range(1, n))) * UNIT_TO_M
              for k in end_effectors}
    if sum(travel.values()) < 0.25:
        issues.append("Very little visible motion.")
    # Peak joint speed (deg/frame) after compile
    max_delta = 0.0
    for i in range(1, len(frames)):
        for j in JOINT_NAMES:
            d = rotation_angle_between(frame_rotation(frames[i - 1], j), frame_rotation(frames[i], j))
            max_delta = max(max_delta, d)
    # Visible pops: an elbow/hand/knee/foot jumping much further in one frame than its neighbours.
    pop = 0.0
    for i in range(2, n - 1):
        for k in ("left_hand", "right_hand", "left_elbow", "right_elbow", "left_foot", "right_foot", "left_knee", "right_knee"):
            d_before = np.linalg.norm(track[i - 1][k] - track[i - 2][k])
            d_prev = np.linalg.norm(track[i][k] - track[i - 1][k])
            d_next = np.linalg.norm(track[i + 1][k] - track[i][k])
            # A teleport: one step much bigger than the steps on BOTH sides.
            spike = d_prev - 3.0 * max(d_before, d_next, 1.0)
            pop = max(pop, spike * UNIT_TO_M)
    if pop > 0.05:
        issues.append(f"Possible visual pop: a joint jumps {pop:.2f} m in one frame.")
    # Leg/leg interpenetration (crossing legs through each other)
    leg_clash = 0
    for p in track:
        for a, b in (("left_knee", "right_knee"), ("left_foot", "right_foot")):
            if np.linalg.norm(p[a] - p[b]) < LIMB_RADIUS * 1.6:
                leg_clash += 1
    if leg_clash:
        issues.append(f"Legs touch/overlap in {leg_clash} samples.")
    return {
        "passed": not issues,
        "issues": issues,
        "frame_count": len(frames),
        "fps": fps,
        "loop": loop,
        "end_effector_travel_m": {k: round(v, 3) for k, v in travel.items()},
        "max_joint_delta_deg_per_frame": round(max_delta, 2),
        "max_pop_m": round(pop, 3),
        **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()},
    }


# -----------------------------------------------------------------------------
# Language model: schema + prompt
# -----------------------------------------------------------------------------

def _obj(props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props.keys()), "additionalProperties": False}


NUM = {"type": "number"}
KEYFRAME_SCHEMA = _obj({
    "t": NUM,
    "phase": {"type": "string"},
    **{g: _obj({p: NUM for p in GROUP_PARAMS[g]}) for g in GROUP_ORDER},
    "left_foot_planted": {"type": "boolean"},
    "right_foot_planted": {"type": "boolean"},
    "hands_together": {"type": "boolean"},
    "right_elbow_points": {"type": "string", "enum": ELBOW_CHOICES},
    "left_elbow_points": {"type": "string", "enum": ELBOW_CHOICES},
})
PLAN_SCHEMA = _obj({
    "title": {"type": "string"},
    "movement_summary": {"type": "string"},
    "biomechanics_breakdown": {"type": "string"},
    "coaching_cues": {"type": "array", "items": {"type": "string"}},
    "loop": {"type": "boolean"},
    "duration_seconds": NUM,
    "camera_view": {"type": "string", "enum": ["front", "side", "three_quarter", "back"]},
    "keyframes": {"type": "array", "items": KEYFRAME_SCHEMA},
})

PLANNER_INSTRUCTIONS = r"""
You are an elite sports biomechanist and 3D animator. You turn a requested movement (any sport, drill,
exercise, dance or everyday action, including drills you have never heard of) into precise KEYFRAMES
for a humanoid avatar (1.75 m tall). You say WHERE the hands and feet are and how the trunk is
oriented; a physics solver computes every joint angle (elbows, knees, shoulders, hips) for you.

THE AVATAR
- It performs in place: it cannot travel across the floor. Show runs, shuffles, steps and jumps in
  place (like on a treadmill / with a camera following the athlete).
- Always describe a RIGHT-HANDED athlete (the server mirrors for left-handers). "Right" = athlete's right.

PARAMETERS. Every keyframe lists every field. Angles in degrees, distances in metres.
body   whole avatar rotation: pitch + tips forward (90 = horizontal face-down: swimming, push-up,
       plank; -90 face-up), turn + spins to its right (360 = full spin; ONLY for real spins or a
       change of facing, keep 0 for swings/throws/kicks), roll + rolls to its right (cartwheel).
pelvis height: metres the hips are LOWERED (negative) from standing tall: standing 0, athletic
         stance -0.08, quarter squat -0.18, lunge -0.30, parallel squat -0.40, deep squat -0.50.
         Keep it between 0 and -0.12 for most sport actions (swings, throws, kicks, punches).
         POSITIVE height = the whole athlete is AIRBORNE that high (jump height; the legs keep
         their shape, so a straight-legged jump is height +0.3 with feet lift 0).
       twist: + hips turn to face the athlete's RIGHT (right hip goes back); - hips face LEFT.
       tilt: + anterior tilt (small), side: + right hip drops (small).
torso  lean: + bend forward at the waist (90 = chest horizontal), - arch back. It is RELATIVE to
       body.pitch: in a plank/push-up (body pitch 80) torso lean is ~0 (straight body), not 80.
       twist: + chest turns to face the athlete's RIGHT (right shoulder goes back = a right-hander's
              backswing/coil/wind-up for forehand, golf, baseball, throw, cross-punch load);
              - chest turns LEFT (right shoulder comes through = contact/release/follow-through).
              Measured from the athlete's facing, NOT added to pelvis twist. Max about +-70.
              X-factor = torso.twist - pelvis.twist (20-45 at the top of a backswing).
       side_bend: + lean toward the right side.
head   nod + look down / - look up, turn + look right, tilt + ear toward right shoulder.

right_hand / left_hand: where each hand is, in the CHEST frame (moves and turns with the torso).
  Origin = INSIDE the chest, midway between the shoulder joints (the chest's front surface is at
  forward +0.11, the back at -0.11). Hands touching the chest/holding a ball at the chest: forward 0.2.
  forward: + in front of the chest, - behind the back
  up     : + above shoulder height, - below (belt level about -0.5 when standing straight)
  out    : + OUTWARD toward that hand's own side, - ACROSS the body to the other side, 0 = centre
           line. Same rule for both hands, so a symmetric pose has IDENTICAL numbers for both
           hands (a left hand hanging at the left hip is out +0.33, never negative).
  Each shoulder joint is at (out +0.30, up 0, forward 0) for its own hand. Arm length 0.66 m: a hand
  is at most 0.66 m from its own shoulder (= straight arm).
  Examples: hanging relaxed = (out 0.33, up -0.6, fwd 0.05). Straight forward at shoulder height =
  (out 0.25, up 0, fwd 0.64). Straight overhead = (out 0.3, up 0.65, fwd 0.05). T-pose = (out 0.95,
  up 0, fwd 0). Boxing guard = (out 0.12, up 0.06, fwd 0.28). Across to the other hip = (out -0.3,
  up -0.5, fwd 0.25). Hands clasped in front of belly = (out 0, up -0.4, fwd 0.3).
right_elbow_points / left_elbow_points: which way the bent elbow points: "down" (default: punches,
  curls, push-ups), "out" (to the side: hands on hips, breaststroke, chicken wing), "back" (rowing
  pull, sprint back-swing), "up" (hands behind head, throwing/serving cock, overhead), "forward".
hands_together: true while both hands hold one implement (bat, club, racket two-handed, stick, oar,
  ball in a two-handed pass/shot). The left hand is then attached to the right hand automatically;
  only the right hand position matters (copy it to the left).

right_foot / left_foot: where each foot (ankle) is, in the BODY frame (does NOT turn with
  pelvis/torso twist). forward/out are measured on the floor from the point under the pelvis.
  forward: + in front, - behind.  out: + outward to that foot's own side, - across (same rule for
  both feet). lift: how far the foot is raised from where a straight standing leg would put it,
  i.e. sole height above the floor (0 = on the floor). Lift bends the knee: use it for knee raises,
  kicks, tucks, a foot leaving the floor, NOT for the whole body jumping (use pelvis height > 0).
  toe_out: degrees the foot/knee turns outward (10 natural, 30-45 for squats/sumo, 0 for sprint).
  Standing: both (forward 0, out 0.12, lift 0). Hip width ~0.13 m from centre; leg length 0.72 m
  (a foot can be at most ~0.72 m from its hip joint, which sits 0.78 m above the floor minus the
  hip drop). With pelvis.height -0.4 a foot can only be ~0.65 m in front/behind while on the floor.
left_foot_planted / right_foot_planted: true while that foot is on the floor bearing weight
  (its lift must then be 0). The solver locks planted feet in place, so you can twist hips and
  torso freely. A lifting, swinging, kicking or airborne foot must be false.

CALIBRATED REFERENCE POSES (anchor on these, then adapt)
- Athletic ready stance: pelvis height -0.12, torso lean 20; feet out 0.25 fwd 0; hands
  (out 0.25 up -0.35 fwd 0.35).
- Squat (parallel): pelvis height -0.42, torso lean 40, feet out 0.22 toe_out 25; arms straight
  forward for balance (out 0.25 up 0 fwd 0.6).
- Forward lunge (right leg front): pelvis height -0.32, right foot fwd 0.45 out 0.12, left foot
  fwd -0.5 out 0.12 lift 0.03; torso upright.
- Boxing orthodox stance: left foot fwd 0.25 out 0.12, right foot fwd -0.2 out 0.18, pelvis height
  -0.06, pelvis twist +20, torso twist +25; both hands in guard. Jab: left hand (out 0.05 up 0.03
  fwd 0.64). Cross: torso twist -35, pelvis twist -15, right hand (out 0.0 up 0.03 fwd 0.64), right
  heel pivots (foot stays planted).
- Sprint (in place): drive leg foot fwd 0.2 lift 0.45 (knee high); push-off leg foot fwd -0.45
  lift 0.05..0.25; arms (elbows ~90): front hand (out 0.2 up -0.15 fwd 0.35, elbow down), back hand
  (out 0.3 up -0.45 fwd -0.3, elbow back). Torso lean 10, body pitch 5. Both feet mostly unplanted.
- Jump: load with pelvis height -0.25 and arms back (fwd -0.3); airborne pelvis height +0.3 with
  feet lift 0..0.08 and planted false (tuck jump: feet lift 0.4 fwd 0.1); land pelvis height -0.2.
- Jumping jack: feet out 0.12 -> 0.45 (lift 0.03 while airborne, pelvis height +0.1), hands from
  the sides (out 0.33 up -0.6) to overhead (out 0.25 up 0.62); one cycle, loop=true.
- Throw/serve cocked arm: right hand (out 0.45 up 0.25 fwd -0.15) elbow "up", torso twist +45,
  pelvis twist +25. Release: right hand (out 0.15 up 0.35 fwd 0.55). Follow-through across the body:
  right hand (out -0.35 up -0.3 fwd 0.35), torso twist -55, pelvis twist -40.
- Tennis forehand: backswing right hand (out 0.55 up 0.05 fwd -0.15), torso twist +55, pelvis +30;
  contact right hand (out 0.45 up -0.25 fwd 0.45), torso twist -5; finish right hand over left
  shoulder (out -0.35 up 0.1 fwd 0.3), torso twist -60. Left hand points at the ball in the backswing
  (out 0.0 up 0.0 fwd 0.5).
- Golf (hands_together=true, right hand = grip): address (out 0 up -0.55 fwd 0.3), pelvis height
  -0.06, torso lean 35, feet out 0.22; top of backswing (out 0.35 up 0.3 fwd 0.2) torso twist +80
  pelvis twist +40; impact (out 0.05 up -0.55 fwd 0.3) torso twist -10 pelvis twist -35; finish
  (out -0.35 up 0.25 fwd 0.2) torso twist -85 pelvis twist -45, torso lean 5, right foot lift 0.03.
- Instep kick (right leg): plant left foot (fwd 0.1 out 0.2); backswing right foot (fwd -0.35 out
  0.1 lift 0.4); contact right foot (fwd 0.3 out 0.05 lift 0.12); follow-through (fwd 0.6 lift 0.55);
  arms out for balance; right_foot_planted false during the swing.
- Push-up/plank: body pitch 78, feet neutral (fwd 0, out 0.12, lift 0); straight arms: hands (out
  0.32 up -0.6 fwd 0); bottom: hands (out 0.4 up -0.3 fwd 0.05), elbows "back". Feet planted false
  (the solver's floor is vertical for a pitched body).
- Freestyle swimming: body pitch 85; hand entry overhead (out 0.25 up 0.62 fwd 0.2), pull under the
  chest (out 0.05 up -0.1 fwd 0.45), push to the hip (out 0.3 up -0.6 fwd -0.05), recovery above
  the back (out 0.4 up 0.05 fwd -0.3, elbow "up"); flutter kick: feet lift alternate 0..0.15.

ANIMATION CRAFT (this is what makes it look professional)
1. Break the action into its real phases (ready -> load/backswing -> acceleration -> contact/peak
   -> follow-through -> recovery). Use 6-10 keyframes; add keys where motion changes direction fast.
2. Timing: t runs 0..1 and must reflect real rhythm: preparation slower, the power phase FAST (often
   10-15% of the time), follow-through decelerating. Do NOT space keys evenly.
3. Kinetic chain: legs and hips start the power, then torso, then arm (pelvis twist leads torso twist
   by one key). Counter-balance with the non-dominant arm. Sports stances keep knees soft
   (pelvis height -0.05 to -0.15).
4. Anticipation and follow-through: small opposite move before a big action; overshoot after it;
   weight shifts (one foot lighter/lifting) where real athletes do it.
5. Repeating actions (running, jumping jacks, skipping, swimming, dribbling, jump rope, shuffles...):
   loop=true and describe exactly ONE cycle; the cycle closes automatically, so do NOT repeat the
   first keyframe at the end. Alternate left/right limbs half a cycle apart.
   One-shot actions (swing, throw, jump, lift): loop=false, start and end in a natural ready pose.
6. Every limb does something purposeful in every phase; avoid identical copies between keys.
   Floor positions (plank, push-up, burpee bottom, crawling, mountain climbers) need body pitch
   70-85 so the body is near horizontal; lying on the back needs body pitch -80..-90.
   Lateral shuffles/slides: in place, show the steps with the feet alternating wide (out 0.4) and
   narrow (out 0.15), the hips low, a lean toward the travel direction and active hands.
7. Anatomy: hands within 0.66 m of their shoulder, feet within 0.72 m of their hip; a hand passing
   across the body goes in front of it (forward >= 0.2), never through the torso.
8. duration_seconds: realistic real-time length of the action or one cycle (tennis forehand 1.6,
   golf swing 2.2, running cycle 0.7, jumping jack 1.0, squat 2.5, push-up 2.0). Range 0.6-6.
9. camera_view: best viewpoint (side for running/squats/push-ups/sagittal moves, front for jumping
   jacks/lateral moves, three_quarter for rotational swings/throws/kicks).
10. biomechanics_breakdown: BRIEF notes (max ~120 words) on each phase, written before the numbers.
11. coaching_cues: 3-5 short, practical cues a coach would say for this movement.
""".strip()


def build_user_prompt(movement: str, extra: str, duration: Optional[float]) -> str:
    parts = [f"Movement to animate: {movement.strip()}"]
    if duration:
        parts.append(f"Requested duration: about {duration:.1f} s (use it unless clearly wrong for the action).")
    if extra.strip():
        parts.append(f"Extra notes from the user: {extra.strip()}")
    parts.append("Return the full JSON plan.")
    return "\n".join(parts)


REVIEW_INSTRUCTIONS = r"""
You are reviewing and correcting an animation plan for a sports-coaching avatar. The parameter
conventions are given below. Return the COMPLETE corrected plan in the same JSON schema.

Check, keyframe by keyframe:
- Every item in "SOLVER FINDINGS" (objective geometry problems found by the physics solver). Fix each.
- Signs: right-hander's backswing/coil = torso/pelvis twist POSITIVE; contact/follow-through = NEGATIVE.
  hand out + = outward to that hand's own side, - = across the body (same rule for both hands). hand forward - = behind the back.
- Each hand within 0.66 m of its shoulder (right shoulder side +0.30, left -0.30, both up 0 fwd 0).
- Hands never inside the torso; crossing hands pass in front (forward >= 0.2).
- Real phases present, realistic timing (fast power phase, not evenly spaced), anticipation and
  follow-through, kinetic chain (hips lead shoulders), non-dominant arm doing something useful.
- Feet: planted only when truly on the ground; loop cycles do not repeat the first key at the end.
Keep everything that is already correct. Do not shorten the plan.
""".strip()


def diagnose_plan(plan: Dict[str, Any]) -> List[str]:
    """Objective per-keyframe problems the planner can fix (reachability, hands in torso, grips...)."""
    findings: List[str] = []
    reach = (UPPER_ARM + FOREARM) * UNIT_TO_M
    for i, kf in enumerate(plan["keyframes"]):
        tag = f"keyframe {i} (t={kf['t']:.2f}, {kf['phase']})"
        hands = {}
        for side, sign in (("right", 1.0), ("left", -1.0)):
            h = kf[f"{side}_hand"]
            p = np.array([sign * h["out"], h["up"], h["forward"]])
            hands[side] = p
            shoulder = np.array([sign * SHOULDER_OFFSET[0] * UNIT_TO_M, 0.0, 0.0])
            d = float(np.linalg.norm(p - shoulder))
            if d > reach + 0.06 and not (side == "left" and kf["hands_together"]):
                findings.append(f"{tag}: {side} hand is {d:.2f} m from its shoulder (max {reach:.2f}); "
                                f"the arm cannot reach it. Bring it closer.")
            moved = float(np.linalg.norm(keep_hand_outside_torso(p, sign) - p))
            if side == "left" and kf["hands_together"]:
                continue
            if moved > 0.06:
                findings.append(f"(minor) {tag}: {side} hand target is inside the torso; put it in front "
                                f"(forward >= 0.2) or clearly to the side.")
        leg_len = (THIGH + SHIN) * UNIT_TO_M
        for side, sign in (("right", 1.0), ("left", -1.0)):
            f = kf[f"{side}_foot"]
            hip = np.array([sign * HIP_OFFSET[0] * UNIT_TO_M, HIP_OFFSET[1] * UNIT_TO_M, 0.0])
            ankle = np.array([sign * f["out"], (HIP_OFFSET[1] - THIGH - SHIN) * UNIT_TO_M
                              - min(0.0, kf["pelvis"]["height"]) * HIP_DROP_SCALE + f["lift"], f["forward"]])
            d = float(np.linalg.norm(ankle - hip))
            if d > leg_len + 0.05:
                findings.append(f"{tag}: {side} foot is {d:.2f} m from its hip (leg length {leg_len:.2f}); "
                                f"bring it closer or lower the hips less.")
        lf, rf = kf["left_foot"], kf["right_foot"]
        if lf["out"] + rf["out"] < 0.08 and abs(lf["forward"] - rf["forward"]) < 0.12 and abs(lf["lift"] - rf["lift"]) < 0.15:
            findings.append(f"{tag}: the feet overlap/cross; separate them (out >= 0.08 each or stagger forward).")
    if plan.get("loop") and len(plan["keyframes"]) >= 3:
        first, last = plan["keyframes"][0], plan["keyframes"][-1]
        same = all(abs(first[g][p] - last[g][p]) < 3 for g, p in PARAM_PATHS)
        if same:
            findings.append("(minor) loop=true but the last keyframe repeats the first; remove the duplicate.")
    ts = [k["t"] for k in plan["keyframes"]]
    if len(ts) >= 5 and np.std(np.diff(ts)) < 0.01 and not plan.get("loop"):
        findings.append("Keyframes are evenly spaced in time; make the power phase faster and the "
                        "preparation/follow-through slower.")
    return findings[:20]


def _openai_client():
    if OpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed on the server.")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured for the motion service.")
    return OpenAI(max_retries=2, timeout=120)


def _call_model(instructions: str, user_input: str, effort: str, schema: Optional[Dict[str, Any]] = None,
                name: str = "motion_plan", max_tokens: int = 16000) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    client = _openai_client()
    t0 = time.time()
    resp = client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=user_input,
        reasoning={"effort": effort},
        store=False,
        text={"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema or PLAN_SCHEMA}},
        max_output_tokens=max_tokens,
    )
    if getattr(resp, "status", None) == "incomplete":
        raise ValueError(f"Model output incomplete: {getattr(resp, 'incomplete_details', None)}")
    text = (getattr(resp, "output_text", "") or "").strip()
    usage = getattr(resp, "usage", None)
    meta = {
        "seconds": round(time.time() - t0, 1),
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
    }
    return json.loads(text), meta


def plan_freeform(movement: str, extra: str = "", duration: Optional[float] = None,
                  refine: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Last-resort planner (free-form keyframes). fast: one planning call (+ one repair call only if the solver finds objective problems).
    high: planning call + a review call that fixes solver findings and technique."""
    calls: List[Dict[str, Any]] = []
    raw, meta = _call_model(PLANNER_INSTRUCTIONS, build_user_prompt(movement, extra, duration), REASONING_EFFORT)
    calls.append({"stage": "plan", **meta})
    plan = sanitize_plan(raw)
    plan["biomechanics_breakdown"] = str(raw.get("biomechanics_breakdown", ""))[:3000]
    findings = diagnose_plan(plan)
    calls[-1]["findings"] = findings
    major = [f for f in findings if not f.startswith("(minor)")]
    if refine or len(major) >= 2:
        review_input = (
            "PARAMETER CONVENTIONS:\n" + PLANNER_INSTRUCTIONS +
            "\n\nREQUESTED MOVEMENT: " + movement +
            ("\nEXTRA NOTES: " + extra if extra.strip() else "") +
            "\n\nSOLVER FINDINGS:\n" + ("\n".join("- " + f for f in findings) if findings else "- none") +
            "\n\nPLAN TO REVIEW:\n" + json.dumps(raw)
        )
        try:
            raw2, meta2 = _call_model(REVIEW_INSTRUCTIONS, review_input, REASONING_EFFORT)
            plan2 = sanitize_plan(raw2)
            plan2["biomechanics_breakdown"] = str(raw2.get("biomechanics_breakdown", ""))[:3000]
            findings2 = diagnose_plan(plan2)
            calls.append({"stage": "review", **meta2, "findings": findings2})
            major2 = [f for f in findings2 if not f.startswith("(minor)")]
            if len(major2) <= len(major) + 1:
                plan = plan2
        except Exception as exc:  # the review is best-effort; keep the first plan
            calls.append({"stage": "review", "error": str(exc)})
    return plan, calls


# -----------------------------------------------------------------------------
# Library pipeline: the model only interprets and selects; code builds every number
# -----------------------------------------------------------------------------
import motion_library as ml  # noqa: E402

TEMPO = {"slow": 1.35, "normal": 1.0, "fast": 0.8}
INTENSITY = {"low": 0.8, "medium": 1.0, "high": 1.15}
VIEWS = ["front", "side", "three_quarter", "back"]

LIBRARY_CHOICES = [f"{t}:{v}" for t, v in ml.all_choices()]

NORMALIZE_SCHEMA = _obj({
    "canonical_name": {"type": "string"},
    "simplified_description": {"type": "string"},
    "key_details": {"type": "array", "items": {"type": "string"}},
    "library_match": {"type": "string", "enum": LIBRARY_CHOICES + ["none"]},
    "match_quality": {"type": "string", "enum": ["exact", "close", "none"]},
    "title": {"type": "string"},
    "movement_summary": {"type": "string"},
    "sport_or_context": {"type": "string"},
    "implement": {"type": "string", "enum": ["none", "racket", "club", "bat", "stick", "ball", "weights", "other"]},
    "body_orientation": {"type": "string", "enum": ["upright", "face_down", "face_up", "changes"]},
    "repeating_cycle": {"type": "boolean"},
    "phases": {"type": "array", "items": {"type": "string"}},
    "closest_standard_movements": {"type": "array", "items": {"type": "string"}},
    "tempo": {"type": "string", "enum": list(TEMPO)},
    "intensity": {"type": "string", "enum": list(INTENSITY)},
    "coaching_cues": {"type": "array", "items": {"type": "string"}},
})

NORMALIZE_INSTRUCTIONS = """
You are a sports biomechanics coach preparing a request for an animation system that can only show
ONE clear movement at a time. Users often write long, chatty or over-detailed requests; your job is
to SIMPLIFY them into the single core movement, so the animation stays clean and consistent.

- canonical_name: the standard name of the core movement, 2-6 words (e.g. "soccer instep shot",
  "butterfly swim stroke", "single-leg Romanian deadlift"). Drop setting, story, equipment brands,
  emotions and coaching chatter. If several movements are requested, name the main sequence briefly.
- simplified_description: one plain sentence (max 25 words) of what the body does.
- key_details: at most 3 details that change the BODY MOTION (side, tempo, stance, repetitions).
  Ignore everything else.
- library_match: the library entry that IS this movement ("template:variant"), or "none".
  match_quality: "exact" only if that entry is the same movement (synonyms count: "soccer shot",
  "striking a football" -> kick:soccer_instep; "fly stroke" -> swim:butterfly); "close" if similar
  but not the same; "none" otherwise. Prefer an exact library entry whenever one fits.
- phases: 2-8 short ordered steps naming body parts and actions (for movements not in the library).
- closest_standard_movements: 1-4 well-known movements that look most like it.
- repeating_cycle: true for continuous cyclic actions (running, swimming, shuffling, skipping...).
- coaching_cues: 3-5 short practical cues. Assume a right-handed athlete.
""".strip()

COMPOSE_SCHEMA = _obj({
    "segments": {"type": "array", "items": _obj({
        "template": {"type": "string", "enum": list(ml.TEMPLATES)},
        "variant": {"type": "string"},
        "reps": {"type": "integer"},
        "tempo": {"type": "string", "enum": list(TEMPO)},
        "intensity": {"type": "string", "enum": list(INTENSITY)},
    })},
    "camera_view": {"type": "string", "enum": VIEWS},
})

COMPOSE_INSTRUCTIONS = """
You build an animation from a FIXED LIBRARY of professionally animated movement templates.
You cannot invent motion data: you only choose library entries, in order, as "segments".

Rules:
1. If one template variant matches the movement, use exactly that one segment.
2. Combine several segments in order for combos and multi-part drills (e.g. a sprint into a jump,
   a squat followed by an overhead press). ALWAYS use a real template for every part that has one
   (high knees -> run:high_knees, squat jump -> jump:squat_jump, push-up -> floor:push_up); "poses"
   is only for the parts no template covers. Example: "3 high knees then squat and jump" ->
   [run high_knees reps 2] + [jump squat_jump reps 1].
3. For movements that no template covers (stretches, holds, novel coach drills, reaching patterns),
   use template "poses" with variant = pose names joined by ">", e.g.
   "athletic_stance>reach_right_hand_to_left_foot>low_crouch_hands_down>reach_left_hand_to_right_foot".
   For a REPEATING drill give exactly ONE cycle (it loops automatically); for a one-off sequence start
   and end in a neutral pose. Pick only poses the drill really contains. Examples:
   - zigzag spider drill: "low_crouch_hands_down>reach_right_hand_to_left_foot>low_crouch_hands_down>reach_left_hand_to_right_foot"
   - toe touch to overhead reach: "standing>toe_touch>overhead_reach>standing"
   - cone touch to the front-right: "athletic_stance>reach_low_right>athletic_stance"
   - sun salutation: "standing>overhead_reach>toe_touch>lunge_right_forward>plank>push_up_bottom>lean_back_arch>plank>toe_touch>overhead_reach>standing"
   You may mix "poses" segments with other templates.
4. variant must be copied EXACTLY from the catalog list for that template (punch: shots joined
   with "-"; poses: pose names joined with ">").
5. reps: 1-4 (cycles for repeating templates; repetitions for one-shot actions). Use 1 unless the
   drill asks for repetitions or a combination needs it.
6. camera_view: side for running/squats/push-ups/swimming/sagittal motion, front for lateral or
   symmetric motion (jumping jacks, shuffles, golf), three_quarter for rotational swings and throws.

LIBRARY CATALOG:
""".strip() + "\n" + ml.catalog_text()


def _compose_input(movement: str, extra: str, brief: Dict[str, Any], errors: Optional[List[str]] = None,
                   previous: Optional[Dict[str, Any]] = None) -> str:
    # The raw (possibly long, chatty) request is deliberately NOT passed on: only the simplified
    # brief, which keeps the composition consistent.
    _ = (movement, extra)
    parts = [f"MOVEMENT: {brief.get('canonical_name') or movement[:80]}",
             f"WHAT THE BODY DOES: {brief.get('simplified_description', '')}"]
    if brief.get("key_details"):
        parts.append("KEY DETAILS: " + "; ".join(str(x) for x in brief["key_details"][:3]))
    parts.append("COACH BRIEF:\n" + json.dumps({k: brief.get(k) for k in (
        "sport_or_context", "implement", "body_orientation", "repeating_cycle", "phases",
        "closest_standard_movements", "library_match", "tempo", "intensity")}, ensure_ascii=False))
    if errors:
        parts.append("YOUR PREVIOUS ANSWER:\n" + json.dumps(previous))
        parts.append("PROBLEMS FOUND BY THE VALIDATOR (fix them):\n" + "\n".join("- " + e for e in errors))
    return "\n\n".join(parts)


def validate_segments(segments: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str], List[str]]:
    """Map model choices onto the library. Returns (resolved, errors, notes)."""
    resolved, errors, notes = [], [], []
    if not segments:
        errors.append("No segments were given.")
    for i, seg in enumerate(segments[:8]):
        try:
            t, v, n = ml.resolve(str(seg.get("template", "")), str(seg.get("variant", "")))
            if t == "poses":
                names = [x.strip() for x in v.split(">") if x.strip()]
                bad = [x for x in names if not difflib.get_close_matches(
                    x.lower().replace(" ", "_").replace("-", "_"), list(ml.POSES), 1, 0.45)]
                if bad or not names:
                    raise KeyError(f"unknown pose name(s) {bad or v!r}; choose from the pose list")
            notes += [f"segment {i}: {x}" for x in n]
            resolved.append({
                "template": t, "variant": v,
                "reps": int(max(1, min(4, int(seg.get("reps", 1) or 1)))),
                "tempo": seg.get("tempo", "normal") if seg.get("tempo") in TEMPO else "normal",
                "intensity": seg.get("intensity", "medium") if seg.get("intensity") in INTENSITY else "medium",
            })
        except Exception as exc:
            errors.append(f"segment {i} ({seg.get('template')}/{seg.get('variant')}): {exc}")
    return resolved, errors, notes


def compose_plan(segments: List[Dict[str, Any]], brief: Dict[str, Any], view: Optional[str],
                 duration: Optional[float]) -> Dict[str, Any]:
    """Glue library segments into one keyframe plan (absolute timing, transitions, repetitions)."""
    built = []
    for seg in segments:
        out = ml.build_segment(seg["template"], seg["variant"], INTENSITY[seg["intensity"]])
        out["duration"] *= TEMPO[seg["tempo"]]
        built.append((seg, out))
    # A single pose sequence describing a repeating drill becomes a seamless loop.
    if len(built) == 1 and built[0][0]["template"] == "poses" and brief.get("repeating_cycle"):
        keys = built[0][1]["keys"]
        if len(keys) >= 3 and keys[-1]["phase"] == keys[0]["phase"]:
            keys.pop()
            n = len(keys)
            for i, k in enumerate(keys):
                k["t"] = i / n
            built[0][1]["duration"] *= n / (n + 1)
        built[0][1]["loop"] = True
    # Keep the whole clip under ~8 s by trimming repetitions.
    def total_len() -> float:
        return sum((s["reps"] if not o["loop"] or len(built) > 1 else 1) * o["duration"] for s, o in built)
    while total_len() > 8.0 and any(s["reps"] > 1 for s, _ in built):
        max(built, key=lambda b: b[0]["reps"] * b[1]["duration"])[0]["reps"] -= 1
    single_loop = len(built) == 1 and built[0][1]["loop"]
    keys_abs: List[Tuple[float, Dict[str, Any]]] = []
    clock = 0.0
    if single_loop:
        seg, out = built[0]
        for k in out["keys"]:
            keys_abs.append((k["t"] * out["duration"], copy.deepcopy(k)))
        clock = out["duration"]
    else:
        for si, (seg, out) in enumerate(built):
            reps = seg["reps"] if not out["loop"] else max(2, seg["reps"])
            if keys_abs:
                clock += 0.3  # transition between segments
            for r in range(reps):
                cycle = [copy.deepcopy(k) for k in out["keys"]]
                if out["loop"]:
                    close = copy.deepcopy(out["keys"][0]); close["t"] = 1.0
                    cycle.append(close)
                for j, k in enumerate(cycle):
                    if (r > 0 or keys_abs) and j == 0 and keys_abs and abs(clock - keys_abs[-1][0]) < 1e-6:
                        continue  # identical boundary key between repetitions
                    keys_abs.append((clock + k["t"] * out["duration"], k))
                clock += out["duration"]
    total = max(clock, 1e-3)
    keyframes = []
    for t_abs, k in keys_abs:
        k["t"] = t_abs / total
        keyframes.append(k)
    # Enforce strictly increasing times.
    keyframes.sort(key=lambda k: k["t"])
    first_view = built[0][1]["view"] if built else "three_quarter"
    plan = sanitize_plan({
        "title": brief.get("title", ""),
        "movement_summary": brief.get("movement_summary", ""),
        "coaching_cues": brief.get("coaching_cues", []),
        "loop": single_loop,
        "duration_seconds": min(8.0, total) if not duration else duration,
        "camera_view": view if view in VIEWS else first_view,
        "keyframes": keyframes,
    })
    if any(abs(k["body"]["pitch"]) > 45 for k in plan["keyframes"]):
        plan["camera_view"] = "side"  # horizontal bodies read best from the side
    plan["segments"] = segments
    plan["brief"] = {k: brief.get(k) for k in ("sport_or_context", "phases", "closest_standard_movements")}
    return plan


def plan_movement(movement: str, extra: str = "", duration: Optional[float] = None,
                  refine: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Multi-call pipeline.

    1. normalize: simplify the request into one canonical movement + brief + exact library match.
    2. exact match -> code builds it directly (no further model freedom: most consistent).
       otherwise   -> compose (enum-constrained segments from the simplified brief only)
                      -> validate -> repair call with the validator's errors -> build.
    """
    calls: List[Dict[str, Any]] = []
    request = f"Movement request: {movement.strip()}"
    if extra.strip():
        request += f"\nNotes: {extra.strip()}"
    brief, meta = _call_model(NORMALIZE_INSTRUCTIONS, request, "low", NORMALIZE_SCHEMA, "movement_brief", 5000)
    calls.append({"stage": "normalize", **meta, "canonical_name": brief.get("canonical_name"),
                  "library_match": brief.get("library_match"), "match_quality": brief.get("match_quality")})
    match = brief.get("library_match", "none")
    if match != "none" and brief.get("match_quality") == "exact" and not refine:
        template, variant = match.split(":", 1)
        seg = {"template": template, "variant": variant, "reps": 1,
               "tempo": brief.get("tempo", "normal") if brief.get("tempo") in TEMPO else "normal",
               "intensity": brief.get("intensity", "medium") if brief.get("intensity") in INTENSITY else "medium"}
        segments, errors, _ = validate_segments([seg])
        if segments and not errors:
            return compose_plan(segments, brief, None, duration), calls
    compose_in = _compose_input(movement, extra, brief)
    raw, meta = _call_model(COMPOSE_INSTRUCTIONS, compose_in, "medium" if refine else "low",
                            COMPOSE_SCHEMA, "segment_plan", 6000)
    segments, errors, notes = validate_segments(raw.get("segments", []))
    calls.append({"stage": "compose", **meta, "segments": raw.get("segments"), "errors": errors, "notes": notes})
    if errors:
        raw2, meta2 = _call_model(COMPOSE_INSTRUCTIONS, _compose_input(movement, extra, brief, errors, raw),
                                  "medium", COMPOSE_SCHEMA, "segment_plan", 6000)
        segments2, errors2, _ = validate_segments(raw2.get("segments", []))
        calls.append({"stage": "repair", **meta2, "segments": raw2.get("segments"), "errors": errors2})
        if segments2 and len(errors2) <= len(errors):
            segments, raw = segments2, raw2
    if not segments:
        plan, more = plan_freeform(brief.get("canonical_name") or movement, extra, duration, refine)
        return plan, calls + more
    return compose_plan(segments, brief, raw.get("camera_view"), duration), calls


# -----------------------------------------------------------------------------
# Cache (same prompt -> same animation, no extra API cost)
# -----------------------------------------------------------------------------
_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
_cache_lock = threading.Lock()


def _cache_key(*parts: Any) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()[:32]


def cache_get(key: str) -> Optional[Dict[str, Any]]:
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return copy.deepcopy(_cache[key])
    if CACHE_DIR:
        f = Path(CACHE_DIR) / f"{key}.json"
        if f.exists():
            try:
                return json.loads(f.read_text())
            except Exception:
                return None
    return None


def cache_put(key: str, plan: Dict[str, Any]) -> None:
    with _cache_lock:
        _cache[key] = copy.deepcopy(plan)
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    if CACHE_DIR:
        try:
            Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
            (Path(CACHE_DIR) / f"{key}.json").write_text(json.dumps(plan))
        except Exception:
            pass


# -----------------------------------------------------------------------------
# API
# -----------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    movement: str = Field(min_length=3, max_length=400)
    duration_seconds: Optional[float] = Field(default=None, ge=0.6, le=8.0,
                                              description="Omit/null to let the planner choose a realistic duration.")
    playback_fps: int = Field(default=DEFAULT_FPS, ge=6, le=60)
    dominant_side: Literal["left", "right"] = "right"
    extra_instructions: str = Field(default="", max_length=800)
    quality: Literal["fast", "high"] = "high"
    use_cache: bool = True
    repair_attempts: int = Field(default=0, ge=0, le=1)  # kept for backwards compatibility (ignored)


class CompileRequest(BaseModel):
    plan: Dict[str, Any]
    duration_seconds: Optional[float] = Field(default=None, ge=0.6, le=8.0)
    playback_fps: int = Field(default=DEFAULT_FPS, ge=6, le=60)
    dominant_side: Literal["left", "right"] = "right"


app = FastAPI(title="CogniCoach Motion Engine", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "model": MODEL, "api_key_configured": bool(os.getenv("OPENAI_API_KEY"))}


@app.get("/rig")
def get_rig() -> Dict[str, Any]:
    return {
        "rig_info_path": str(RIG_INFO_PATH),
        "units": "rig units (~2.1 cm)",
        "segments": {
            "shoulder_offset": SHOULDER_OFFSET, "hip_offset": HIP_OFFSET, "neck_offset": NECK_OFFSET,
            "upper_arm": UPPER_ARM, "forearm": FOREARM, "thigh": THIGH, "shin": SHIN,
        },
        "parameters": {g: {p: {"min": s[0], "max": s[1], "neutral": s[2]} for p, s in GROUP_PARAMS[g].items()}
                       for g in GROUP_ORDER},
    }


def _build_response(plan: Dict[str, Any], duration: Optional[float], fps: int, side: str,
                    calls: List[Dict[str, Any]], cached: bool) -> Dict[str, Any]:
    solved = mirror_plan(plan) if side == "left" else plan
    frames, report = compile_motion(solved, duration, fps)
    text = mirror_text if side == "left" else (lambda t: t)
    return {
        "frames": sparse(frames),
        "playback_fps": fps,
        "duration_seconds": float(duration or plan["duration_seconds"]),
        "loop": plan["loop"],
        "camera_view": plan["camera_view"],
        "dominant_side": side,
        "title": text(plan.get("title", "")),
        "movement_summary": text(plan.get("movement_summary", "")),
        "coaching_cues": [text(c) for c in plan.get("coaching_cues", [])],
        "plan": plan,
        "report": report,
        "model": MODEL,
        "llm_calls": calls,
        "cached": cached,
    }


@app.post("/generate")
def generate(req: GenerateRequest) -> Dict[str, Any]:
    key = _cache_key("v4", req.movement.strip().lower(), req.extra_instructions.strip(), req.duration_seconds,
                     req.quality, MODEL)
    plan = cache_get(key) if req.use_cache else None
    calls: List[Dict[str, Any]] = []
    cached = plan is not None
    if plan is None:
        try:
            plan, calls = plan_movement(req.movement, req.extra_instructions, req.duration_seconds,
                                        refine=req.quality == "high")
        except HTTPException:
            raise
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=502, detail=f"Motion planning failed: {exc}") from exc
        cache_put(key, plan)
    try:
        return _build_response(plan, req.duration_seconds, req.playback_fps, req.dominant_side, calls, cached)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Motion compile failed: {exc}") from exc


@app.post("/compile")
def compile_endpoint(req: CompileRequest) -> Dict[str, Any]:
    try:
        plan = sanitize_plan(req.plan)
        return _build_response(plan, req.duration_seconds, req.playback_fps, req.dominant_side, [], False)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Could not compile supplied plan: {exc}") from exc


SELFTEST_PLAN: Dict[str, Any] = {
    "title": "Jumping jack (built-in self-test)",
    "loop": True,
    "duration_seconds": 1.0,
    "camera_view": "front",
    "keyframes": [
        {"t": 0.0, "phase": "closed", "pelvis": {"height": -0.04},
         "right_hand": {"forward": 0.05, "up": -0.6, "out": 0.33}, "left_hand": {"forward": 0.05, "up": -0.6, "out": 0.33},
         "right_foot": {"out": 0.12}, "left_foot": {"out": 0.12}},
        {"t": 0.25, "phase": "takeoff", "pelvis": {"height": 0.08},
         "right_hand": {"forward": 0.05, "up": -0.1, "out": 0.8}, "left_hand": {"forward": 0.05, "up": -0.1, "out": 0.8},
         "right_foot": {"out": 0.3, "lift": 0.03}, "left_foot": {"out": 0.3, "lift": 0.03},
         "left_foot_planted": False, "right_foot_planted": False},
        {"t": 0.5, "phase": "open", "pelvis": {"height": -0.06},
         "right_hand": {"forward": 0.05, "up": 0.62, "out": 0.25}, "left_hand": {"forward": 0.05, "up": 0.62, "out": 0.25},
         "right_foot": {"out": 0.45}, "left_foot": {"out": 0.45}},
        {"t": 0.75, "phase": "return", "pelvis": {"height": 0.08},
         "right_hand": {"forward": 0.05, "up": -0.1, "out": 0.8}, "left_hand": {"forward": 0.05, "up": -0.1, "out": 0.8},
         "right_foot": {"out": 0.3, "lift": 0.03}, "left_foot": {"out": 0.3, "lift": 0.03},
         "left_foot_planted": False, "right_foot_planted": False},
    ],
}


def selftest() -> int:
    """Offline check of the solver (no API key needed): python motion_engine.py --selftest"""
    plan = sanitize_plan(SELFTEST_PLAN)
    ok = True
    for side in ("right", "left"):
        solved = mirror_plan(plan) if side == "left" else plan
        frames, report = compile_motion(solved, None, DEFAULT_FPS)
        print(f"[{side}-handed] frames={len(frames)} issues={report['issues']} "
              f"travel={report['end_effector_travel_m']}")
        ok = ok and len(frames) == 24 and not report["issues"]
    print("SELFTEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import uvicorn
    print(f"CogniCoach Motion Engine on http://{HOST}:{PORT}  (model: {MODEL})")
    if not os.getenv("OPENAI_API_KEY"):
        print("WARNING: OPENAI_API_KEY is not set; /generate will fail until it is.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
