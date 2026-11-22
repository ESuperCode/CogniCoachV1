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

# Bump on every engine change. The viewer page checks this and warns when the running server is stale.
ENGINE_VERSION = "17-fast-script"
MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")
HOST = os.getenv("MOTION_HOST", "127.0.0.1")
PORT = int(os.getenv("MOTION_PORT", "8000"))
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("MOTION_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
CACHE_SIZE = int(os.getenv("MOTION_CACHE_SIZE", "256"))
CACHE_DIR = os.getenv("MOTION_CACHE_DIR", "")  # optional on-disk cache of plans
RIG_INFO_PATH = Path(__file__).with_name("rig_info.md")

DEFAULT_FPS = 24
HIP_DROP_SCALE = 0.85
MAX_COLLISION_PASSES = 4
SWIVEL_MAX_DEG_PER_FRAME = 9.0  # elbow/knee bend-plane rotation limit at 24 fps  # the rig's legs are ~15% shorter than a real 1.75 m athlete's
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
HEAD_HALF = (6.0, 8.0, 7.5)           # head box (12,16,15), centre 8 above the neck joint
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


def sanitize_keyframe(raw: Dict[str, Any], t_default: float, freeform: bool = False) -> Dict[str, Any]:
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
        if freeform and far > reach and near <= reach:
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
    freeform = plan.get("source") == "freeform"
    kfs = [sanitize_keyframe(k, i / max(1, n - 1), freeform) for i, k in enumerate(raw)]
    kfs.sort(key=lambda k: k["t"])
    ts = np.array([k["t"] for k in kfs], dtype=float)
    loop_plan = bool(plan.get("loop", False))
    if ts[-1] - ts[0] < 1e-6:
        ts = np.linspace(0, 1, n) if not loop_plan else np.arange(n) / n
    if loop_plan and ts[0] >= 0 and ts[-1] < 1.0 - 1e-6:
        # A cycle: keys live in [0, 1) and the solver closes the loop back to the first key.
        # Stretching them to end at 1.0 would make the last key a duplicate of the first.
        ts = ts - ts[0]
        for i in range(1, n):
            ts[i] = max(ts[i], ts[i - 1] + 0.012)
        if ts[-1] > 0.985:
            ts = ts * (0.985 / ts[-1])
    else:
        ts = (ts - ts[0]) / (ts[-1] - ts[0])
        # Enforce a minimum spacing so splines stay well behaved.
        for i in range(1, n):
            ts[i] = max(ts[i], ts[i - 1] + 0.012)
        ts = ts / ts[-1]
    for k, t in zip(kfs, ts):
        k["t"] = float(t)
    if freeform:
        fix_mirrored_left_side(kfs)  # only free-form plans can mix up the 'out' sign convention
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
    if prev is not None and chain == "arm":
        # Swivel limiter (arms only - leg swivel follows the continuous sagittal knee rule): the elbow/knee bend plane may only rotate a limited amount per frame
        # around the shoulder->hand axis. This removes "elbow whipping" when targets or hints change
        # quickly, while real motion (hand/foot position) is untouched.
        prev_perp = prev - np.dot(prev, vdir) * vdir
        if np.linalg.norm(prev_perp) > 1e-6:
            prev_perp /= np.linalg.norm(prev_perp)
            cosang = float(np.clip(np.dot(prev_perp, pole_perp), -1.0, 1.0))
            ang = math.degrees(math.acos(cosang))
            max_step = SWIVEL_MAX_DEG_PER_FRAME
            if ang > max_step:
                axis = np.cross(prev_perp, pole_perp)
                if np.linalg.norm(axis) < 1e-9:
                    axis = vdir
                pole_perp = axis_angle(axis, max_step) @ prev_perp
                pole_perp -= np.dot(pole_perp, vdir) * vdir
                pole_perp /= max(1e-9, np.linalg.norm(pole_perp))
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


def _arm_penetration(world: Dict[str, np.ndarray], pos: Dict[str, np.ndarray], side: str):
    """Deepest penetration of this arm (upper arm or forearm) into the torso or pelvis boxes."""
    sh_y = SHOULDER_OFFSET[1]
    top_y = 2 * TORSO_HALF[1]
    boxes = [
        # Chest up to the shoulder line (full width) ...
        (world["spine"], world["spine"] @ np.array([0.0, sh_y / 2, 0.0]), (TORSO_HALF[0], sh_y / 2, TORSO_HALF[2])),
        # ... then the narrower shoulder-top / neck block (the capsule is rounded there, so arms
        # raised overhead beside the head - a streamline, a block, a two-hand overhead reach - are legal).
        (world["spine"], world["spine"] @ np.array([0.0, (sh_y + top_y) / 2, 0.0]),
         (HEAD_HALF[0], (top_y - sh_y) / 2, TORSO_HALF[2])),
        (world["neck"], world["spine"] @ np.array(NECK_OFFSET) + world["neck"] @ np.array([0.0, HEAD_HALF[1], 0.0]),
         HEAD_HALF),
        (world["hip"], np.zeros(3), PELVIS_HALF),
    ]
    best = (0.0, np.zeros(3), "none")
    sh, el, ha = pos[side + "_shoulder"], pos[side + "_elbow"], pos[side + "_hand"]
    for rot, centre, half in boxes:
        d1, p1 = _segment_box_penetration(sh + (el - sh) * 0.35, el, rot, centre, half, LIMB_RADIUS * 0.8)
        d2, p2 = _segment_box_penetration(el, ha, rot, centre, half, LIMB_RADIUS * 0.8)
        if d1 > best[0]:
            best = (d1, p1, "upper")
        if d2 > best[0]:
            best = (d2, p2, "fore")
    return best


def _resolve_arm_collisions(kf: Dict[str, Any], local: Dict[str, np.ndarray], world: Dict[str, np.ndarray],
                            pos: Dict[str, np.ndarray], side: str, keep_hand: bool = False) -> int:
    """Hard constraint: an arm may never pass through the torso or hips.

    Contact is cleared WITHOUT changing the arm's intended posture: the elbow keeps pointing the way
    the motion asked for (down for guards/punches, etc.) and the hand eases forward away from the
    body. Only an elbow trapped inside the body is steered - forward/down along its intended
    direction, never flared sideways.
    """
    fixes = 0
    hint = world["spine"] @ kf.get(f"{side}_elbow_pole", np.array([0.3, -1.0, -0.25]))
    fwd = world["spine"][:, 2]
    chest = world["spine"] @ np.array([0.0, TORSO_HALF[1], 0.0])
    for it in range(10):
        depth, push, part = _arm_penetration(world, pos, side)
        if depth < 0.05:
            break
        hand_behind = float(np.dot(pos[side + "_hand"] - chest, fwd)) < -TORSO_HALF[2]
        direction = push if (hand_behind and np.dot(push, fwd) < 0) else fwd
        root = pos[side + "_shoulder"]
        if part == "upper" and (keep_hand or it < 3):
            # Elbow inside the body: keep the intended elbow direction, biased forward.
            pole = hint / max(1e-9, np.linalg.norm(hint)) + fwd * 0.6
            target = pos[side + "_hand"]
        else:
            pole = hint
            target = pos[side + "_hand"] + direction * (depth + 0.3)
        upper, lower, _ = two_bone_ik(root, target, pole, UPPER_ARM, FOREARM, world["spine"], "arm")
        local[side + "shoulder"], local[side + "elbow"] = upper, lower
        world.update(world_rotations(local))
        pos.update(forward_kinematics(world))
        fixes += 1
    return fixes


def enforce_elbow_posture(kf: Dict[str, Any], local: Dict[str, np.ndarray], world: Dict[str, np.ndarray],
                          pos: Dict[str, np.ndarray], side: str) -> bool:
    """No 'chicken wings': when the hand is at or below shoulder height and the elbow is meant to
    point down, the elbow may not rise to shoulder height or flare out. The correction is
    proportional to how far the elbow strays (no on/off switching), and raised arms are untouched.
    """
    hint_local = kf.get(f"{side}_elbow_pole", np.array([0.3, -1.0, -0.25]))
    hl = hint_local / max(1e-9, float(np.linalg.norm(hint_local)))
    if hl[1] > 0.6 or abs(hl[0]) > 0.75:
        return False  # elbows deliberately pointing up (throw cock) or out (hands on hips) are left alone
    sh, el, ha = pos[side + "_shoulder"], pos[side + "_elbow"], pos[side + "_hand"]
    up = np.array([0.0, 1.0, 0.0])  # world vertical: what the viewer sees
    hand_h = float(np.dot(ha - sh, up))
    if hand_h > 4.0:
        return False  # hand raised (overhead, high catch): a high elbow is natural
    elbow_h = float(np.dot(el - sh, up))
    limit = -5.0  # elbow should hang at least ~10 cm below the shoulder
    excess = elbow_h - limit
    if excess <= 0.0:
        return False
    w = min(1.0, excess / 6.0)
    sign = 1.0 if side == "right" else -1.0
    down = np.array([0.0, -1.0, 0.0]) + world["spine"] @ np.array([0.15 * sign, 0.0, 0.1])
    current = el - (sh + ha) * 0.5
    current = current / max(1e-9, float(np.linalg.norm(current)))
    pole = current * (1.0 - w) + down * w
    upper, lower, _ = two_bone_ik(sh, ha, pole, UPPER_ARM, FOREARM, world["spine"], "arm")
    local[side + "shoulder"], local[side + "elbow"] = upper, lower
    world.update(world_rotations(local))
    pos.update(forward_kinematics(world))
    return True


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
                   return_to_start: bool = True,
                   _collision_offsets: Optional[List[Dict[str, Any]]] = None,
                   _pass: int = 1) -> Tuple[List[Dict[str, float]], Dict[str, Any]]:
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
    # Kinetic chain: the hips start rotating ~60 ms before the chest (proximal-to-distal sequencing).
    lead = min(0.06 / max(duration, 1e-3), 0.08)
    vals = np.array([k["pelvis"]["twist"] for k in kfs], dtype=float)
    lead_samples = (samples + lead) % 1.0 if loop else np.clip(samples + lead, 0.0, 1.0)
    channels[("pelvis", "twist")] = interpolate_channel(ts, vals, lead_samples, loop)
    # Arm reach (hand distance from its shoulder) is interpolated on its own, so a hand travelling
    # between two far-apart positions sweeps an arc at full arm length instead of cutting a straight
    # line past the shoulder (which made the elbow fold up mid-swing).
    shoulder_out = SHOULDER_OFFSET[0] * UNIT_TO_M
    # Arm-swing waypoints: if a hand's direction from its shoulder turns by more than 120 degrees
    # between two keys, insert a waypoint so the arm swings through a natural arc (down past the
    # hip for back<->front swings) instead of whipping through the shoulder.
    for side in ("right", "left"):
        g = f"{side}_hand"
        key_t, key_v = [], []
        for i, k in enumerate(kfs):
            key_t.append(float(ts[i]))
            key_v.append(np.array([k[g]["out"] - shoulder_out, k[g]["up"], k[g]["forward"]]))
        new_t, new_v = list(key_t), list(key_v)
        for _ in range(4):  # subdivide until no segment turns more than ~90 degrees
            changed = False
            out_t, out_v = [new_t[0]], [new_v[0]]
            for i in range(1, len(new_t)):
                a_v, b_v = new_v[i - 1], new_v[i]
                la, lb = float(np.linalg.norm(a_v)), float(np.linalg.norm(b_v))
                if la > 0.15 and lb > 0.15 and float(np.dot(a_v, b_v) / (la * lb)) < 0.0:
                    mid = a_v / la + b_v / lb
                    if np.linalg.norm(mid) < 0.3:
                        mid = np.array([0.15, -1.0, 0.25])  # opposite directions: swing through the bottom
                    mid = mid / np.linalg.norm(mid) * (0.5 * (la + lb))
                    out_t.append(0.5 * (new_t[i - 1] + new_t[i]))
                    out_v.append(mid)
                    changed = True
                out_t.append(new_t[i])
                out_v.append(b_v)
            new_t, new_v = out_t, out_v
            if not changed:
                break
        if len(new_t) != len(key_t):
            arr = np.array(new_v)
            tt = np.array(new_t)
            channels[(g, "out")] = interpolate_channel(tt, arr[:, 0] + shoulder_out, samples, loop)
            channels[(g, "up")] = interpolate_channel(tt, arr[:, 1], samples, loop)
            channels[(g, "forward")] = interpolate_channel(tt, arr[:, 2], samples, loop)
    # Leg swings: same idea as the arms - the foot travels on an arc around the hip (pendulum)
    # instead of a straight line that could pass through the hip joint and collapse the leg.
    hip_out = HIP_OFFSET[0] * UNIT_TO_M
    for side in ("right", "left"):
        g = f"{side}_foot"
        hip_h = np.array([(-(HIP_OFFSET[1] - THIGH - SHIN) * UNIT_TO_M) + HIP_DROP_SCALE * min(0.0, k["pelvis"]["height"])
                          for k in kfs])  # hip height above the floor at each key
        vecs = [np.array([k[g]["out"] - hip_out, k[g]["lift"] - hh, k[g]["forward"]]) for k, hh in zip(kfs, hip_h)]
        new_t, new_v, new_h = list(ts), list(vecs), list(hip_h)
        for _ in range(4):
            changed = False
            out_t, out_v, out_h = [new_t[0]], [new_v[0]], [new_h[0]]
            for i in range(1, len(new_t)):
                a_v, b_v = new_v[i - 1], new_v[i]
                la, lb = float(np.linalg.norm(a_v)), float(np.linalg.norm(b_v))
                if la > 0.1 and lb > 0.1 and float(np.dot(a_v, b_v) / (la * lb)) < 0.3:
                    mid = a_v / la + b_v / lb
                    if np.linalg.norm(mid) < 0.3 or mid[1] > 0.0:
                        mid = np.array([0.0, -1.0, 0.1])  # swing through underneath the hip
                    mid = mid / np.linalg.norm(mid) * max(0.5 * (la + lb), 0.55)
                    out_t.append(0.5 * (new_t[i - 1] + new_t[i]))
                    out_v.append(mid)
                    out_h.append(0.5 * (new_h[i - 1] + new_h[i]))
                    changed = True
                out_t.append(new_t[i])
                out_v.append(b_v)
                out_h.append(new_h[i])
            new_t, new_v, new_h = out_t, out_v, out_h
            if not changed:
                break
        if len(new_t) != len(ts):
            tt, arr, hh = np.array(new_t), np.array(new_v), np.array(new_h)
            channels[(g, "out")] = interpolate_channel(tt, arr[:, 0] + hip_out, samples, loop)
            channels[(g, "lift")] = interpolate_channel(tt, arr[:, 1] + hh, samples, loop)
            channels[(g, "forward")] = interpolate_channel(tt, arr[:, 2], samples, loop)
    reach_channels: Dict[str, np.ndarray] = {}
    for side in ("right", "left"):
        g = f"{side}_hand"
        radii = np.array([math.dist((k[g]["out"], k[g]["up"], k[g]["forward"]), (shoulder_out, 0.0, 0.0))
                          for k in kfs], dtype=float)
        reach_channels[side] = interpolate_channel(ts, radii, samples, loop)

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
            kf[f"{s}_reach"] = float(reach_channels[s][si])
            kf[f"{s}_foot"]["lift"] = max(0.0, kf[f"{s}_foot"]["lift"])
        kf["flags"] = {name: flag_at(name, float(t)) for name in FLAG_KEYS}
        poses.append(kf)

    # Foot locking: while a foot is planted it stays where it was at touchdown (world space; the
    # pelvis is the fixed origin because the rig cannot translate).
    locks: Dict[str, Optional[np.ndarray]] = {"left": None, "right": None}
    lock_done: Dict[str, bool] = {"left": False, "right": False}
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
    wing_samples = 0
    dominant = "left" if plan.get("dominant_side") == "left" else "right"
    off = "right" if dominant == "left" else "left"
    recorded_offsets: List[Dict[str, np.ndarray]] = []
    for fi, kf in enumerate(poses):
        local = pose_local_rotations(kf)
        world = world_rotations(local)
        pos = forward_kinematics(world)
        for side in (dominant, off):
            hand = kf[f"{side}_hand"]
            sgn = 1.0 if side == "right" else -1.0
            rel = np.array([hand["out"] - shoulder_out, hand["up"], hand["forward"]])
            rel_len = float(np.linalg.norm(rel))
            # Near the shoulder the straight path's direction is unstable: steer it out-and-forward
            # (a natural front/side raise arc) and don't let the arm fold past a moderate bend.
            steer = max(0.0, 1.0 - rel_len / 0.3)
            rel = rel + np.array([0.6, 0.0, 0.8]) * 0.15 * steer
            rel_len2 = float(np.linalg.norm(rel))
            if rel_len2 > 1e-6:
                rel = rel / rel_len2 * max(rel_len, 0.72 * kf[f"{side}_reach"])
            point_m = np.array([sgn * (rel[0] + shoulder_out), rel[1], rel[2]])
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
            pole_world = world["spine"] @ kf[f"{side}_elbow_pole"]
            if _collision_offsets is not None:
                corr = _collision_offsets[fi]
                chest_point = chest_point + corr[side]
                w_el = corr[side + "_pole_w"]
                if w_el > 0:
                    # Smoothly steer the elbow the way earlier passes found keeps it out of the body.
                    pole_world = pole_world * (1.0 - w_el) + (world["spine"] @ corr[side + "_pole"]) * w_el * 2.0
            target = world["spine"] @ (chest_point + np.array([0.0, SHOULDER_OFFSET[1], 0.0]))
            if side == off and grip_w > 0.0:
                # Two hands on one ball/handle: aim the off hand beside the lead hand (solved just
                # before), blended by the grip weight - ONE solve per arm keeps the elbow stable.
                lead_world = forward_kinematics(world_rotations(local))[f"{dominant}_hand"]
                off_dir = world["spine"][:, 0] * (-1.0 if dominant == "right" else 1.0)
                target = target + (lead_world + off_dir * 4.0 - target) * grip_w
                stats["grip_frames"] += 1
            upper, lower, _ = two_bone_ik(pos[side + "_shoulder"], target, pole_world,
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
        local_feet = {}
        # Hips sit BACK when the knees bend (like sitting into a chair): the pelvis is fixed in this
        # rig, so the feet move forward relative to it in proportion to the hip drop.
        sit_back = 0.45 * min(0.0, kf["pelvis"]["height"]) * -1.0 if abs(kf["body"]["pitch"]) < 30 else 0.0
        for side, sign in (("left", -1.0), ("right", 1.0)):
            foot = kf[f"{side}_foot"]
            local_feet[side] = np.array([sign * foot["out"] / UNIT_TO_M,
                                         ankle_standing - hip_drop + foot["lift"] / UNIT_TO_M,
                                         (foot["forward"] + sit_back) / UNIT_TO_M])
        # Feet never pass through each other: keep a minimum spacing (smoothly), pushing sideways.
        gap = local_feet["right"] - local_feet["left"]
        dist = float(np.linalg.norm(gap))
        min_gap = 2.2 * LIMB_RADIUS
        if dist < min_gap:
            push = (min_gap - dist) / 2.0
            local_feet["right"][0] += push
            local_feet["left"][0] -= push
        sit_vec = world["body"] @ np.array([0.0, 0.0, sit_back / UNIT_TO_M])
        for side, sign in (("left", -1.0), ("right", 1.0)):
            target = world["body"] @ local_feet[side]
            planted, weight = kf["flags"][f"{side}_foot_planted"]
            landing = planted and not lock_done[side]
            if weight >= 1.0 and planted:
                lock_done[side] = True
            if not planted:
                lock_done[side] = False
            if landing or (planted and locks[side] is None):
                # Keep tracking the foot while it is still landing; lock only once it has arrived
                # (lift-off then eases away from the frozen spot - no jump).
                # Lock the foot's floor position WITHOUT the hips-back offset; the current offset is
                # re-applied every frame, so squatting before a jump can't leave a stale lock.
                locks[side] = target - sit_vec
            if not planted:
                locks[side] = None
            if locks[side] is not None and weight > 0.0:
                anchor = locks[side] + sit_vec
                anchor[1] = target[1]
                target = target + (anchor - target) * weight
                stats["foot_lock_frames"] += 1
            toe = math.radians(sign * foot["toe_out"])
            # Knee points where the foot points (toe_out); no extra outward bias, so kicks and
            # strides swing straight instead of bowing sideways.
            # Knee direction = the anatomical front of the hip->foot line in the sagittal plane: foot
            # below -> knee forward, foot in front -> knee up, foot behind -> knee down. This keeps the
            # knee hinge well defined for every leg position (no sideways bowing), plus toe-out.
            rel_b = world["body"].T @ (target - pos[side + "_hip"])
            d = rel_b / max(1e-6, float(np.linalg.norm(rel_b)))
            sag = np.array([0.0, d[2], -d[1]])
            sag_len = float(np.linalg.norm(sag))
            sag = sag / sag_len if sag_len > 1e-6 else np.array([0.0, 0.0, 1.0])
            w_sag = min(1.0, sag_len / 0.5)
            pole_b = sag * w_sag + np.array([0.0, 0.0, 1.0]) * (1.0 - w_sag) + np.array([math.sin(toe), 0.0, 0.0])
            knee_dir = world["body"] @ pole_b
            upper, lower, res = two_bone_ik(pos[side + "_hip"], target, knee_dir,
                                            THIGH, SHIN, world["hip"], "leg", ik_memory, side + "_leg")
            local[side + "hip"], local[side + "knee"] = upper, lower
            stats["ik_residual_max"] = max(stats["ik_residual_max"], res * UNIT_TO_M)
        world = world_rotations(local)
        pos = forward_kinematics(world)

        frame_offsets: Dict[str, Any] = {}
        for side in (dominant, off):
            before = pos[side + "_hand"].copy()
            gripping = side == off and kf["flags"]["hands_together"][1] > 0.5
            fixes = _resolve_arm_collisions(kf, local, world, pos, side, keep_hand=gripping)
            if enforce_elbow_posture(kf, local, world, pos, side):
                stats["elbow_posture_fixes"] = stats.get("elbow_posture_fixes", 0) + 1
                # Re-check the body after lowering the elbow (hand stays put, so this rarely fires).
                fixes += 1 + _resolve_arm_collisions(kf, local, world, pos, side, keep_hand=True)
            stats["collision_fixes"] += fixes
            depth_after = _arm_penetration(world, pos, side)[0]
            if gripping and depth_after > 1.0:
                # The gripping arm can't clear the body on its own: next pass moves the whole grip
                # (lead hand, and the off hand with it) forward, away from the chest.
                frame_offsets[dominant] = frame_offsets.get(dominant, np.zeros(3)) + np.array([0.0, 0.0, depth_after + 1.0])
                frame_offsets[dominant + "_pole_w"] = max(frame_offsets.get(dominant + "_pole_w", 0.0), 1e-3)
            stats["max_arm_penetration_m"] = max(stats.get("max_arm_penetration_m", 0.0), depth_after * UNIT_TO_M)
            frame_offsets[side] = world["spine"].T @ (pos[side + "_hand"] - before) if fixes else np.zeros(3)
            el = pos[side + "_elbow"] - pos[side + "_shoulder"]
            frame_offsets[side + "_pole"] = world["spine"].T @ (el / max(1e-9, np.linalg.norm(el)))
            frame_offsets[side + "_pole_w"] = 1.0 if fixes else 0.0
        recorded_offsets.append(frame_offsets)

        for sd in ("left", "right"):
            hl = kf.get(f"{sd}_elbow_pole", np.array([0.3, -1.0, -0.25]))
            hl = hl / max(1e-9, float(np.linalg.norm(hl)))
            intended_high = hl[1] > 0.6 or abs(hl[0]) > 0.75
            sh_, el_, ha_ = pos[sd + "_shoulder"], pos[sd + "_elbow"], pos[sd + "_hand"]
            if (not intended_high and float(np.linalg.norm(ha_ - sh_)) < 0.65 * (UPPER_ARM + FOREARM)
                    and ha_[1] - sh_[1] < 4.0 and el_[1] - sh_[1] > -1.0):
                wing_samples += 1
        track.append({k: v.copy() for k, v in pos.items()})
        root_y.append(kf["pelvis"]["height"])
        rot_track.append({k: orthonormalize(v) for k, v in local.items()})
        body_track.append(dict(kf["body"]))

    if _pass < MAX_COLLISION_PASSES and any(o[side + "_pole_w"] > 0 for o in recorded_offsets for side in ("left", "right")):
        # Collision corrections found this pass are spread in time (applied a few frames early and
        # released late), smoothed, and fed back as inputs to the next pass - so the arm eases
        # around the body. The per-frame hard check remains as a last-resort safety net.
        new = smooth_collision_corrections(recorded_offsets, _collision_offsets, loop)
        return compile_motion(plan, duration_seconds, fps, return_to_start, new, _pass + 1)

    stats["swivel_despikes"] = despike_swivel(rot_track, track, loop)
    stats["unintended_wing_samples"] = wing_samples
    frames = frames_from_rotations(smooth_rotations(rot_track, loop), body_track)

    # Vertical root translation in metres (hip drop / jump height). Unity ignores it today; it is
    # here so a future WebBridge can move the pelvis for squats and jumps.
    for fr, ry_m in zip(frames, root_y):
        fr["rooty"] = round(float(ry_m), 4)

    if not loop and return_to_start and len(frames) > 4:
        frames = append_return(frames, fps)

    report = verify(plan, frames, track, fps, stats, loop)
    return frames, report


SWIVEL_CHAINS = [
    # (name, root, middle, end, upper bone, lower bone, parent, l1, l2, chain type)
    ("right_arm", "right_shoulder", "right_elbow", "right_hand", "rightshoulder", "rightelbow", "spine", UPPER_ARM, FOREARM, "arm"),
    ("left_arm", "left_shoulder", "left_elbow", "left_hand", "leftshoulder", "leftelbow", "spine", UPPER_ARM, FOREARM, "arm"),
    ("right_leg", "right_hip", "right_knee", "right_foot", "righthip", "rightknee", "hip", THIGH, SHIN, "leg"),
    ("left_leg", "left_hip", "left_knee", "left_foot", "lefthip", "leftknee", "hip", THIGH, SHIN, "leg"),
]


def despike_swivel(rot_track: List[Dict[str, np.ndarray]], track: List[Dict[str, np.ndarray]], loop: bool) -> int:
    """Final guarantee against one-frame elbow/knee flips.

    For each limb, the swivel direction (elbow/knee offset from the root->end line) is compared with
    its neighbours. A frame that deviates sharply from both neighbours while the neighbours agree is
    re-solved with the neighbours' swivel, keeping the hand/foot exactly where it was. The result is
    only kept if it does not push an arm into the body.
    """
    n = len(track)
    if n < 3:
        return 0
    fixed = 0

    def swivel(i: int, root: str, mid: str, end: str) -> np.ndarray:
        r, m, e = track[i][root], track[i][mid], track[i][end]
        axis = e - r
        al = float(np.linalg.norm(axis))
        if al < 1e-6:
            return np.zeros(3)
        axis /= al
        off = (m - r) - np.dot(m - r, axis) * axis
        ol = float(np.linalg.norm(off))
        # A nearly straight limb has no meaningful swivel (and can't visibly flip): ignore it.
        return off / ol if ol > 3.0 else np.zeros(3)

    for name, root, mid, end, ub, lb, parent, l1, l2, chain in SWIVEL_CHAINS:
        for _ in range(2):
            changed = False
            for i in range(n):
                ia, ib = i - 1, i + 1
                if not loop and (ia < 0 or ib >= n):
                    continue
                ia, ib = ia % n, ib % n
                s0, sa, sb = swivel(i, root, mid, end), swivel(ia, root, mid, end), swivel(ib, root, mid, end)
                if not (np.any(s0) and np.any(sa) and np.any(sb)):
                    continue
                neighbours_agree = float(np.dot(sa, sb)) > 0.7
                spike = float(np.dot(s0, sa)) < 0.5 and float(np.dot(s0, sb)) < 0.5
                if not (neighbours_agree and spike):
                    continue
                local = {k: v.copy() for k, v in rot_track[i].items()}
                world = world_rotations(local)
                pos = forward_kinematics(world)
                pole = sa + sb
                upper, lower, _ = two_bone_ik(pos[root], track[i][end], pole, l1, l2, world[parent], chain)
                local[ub], local[lb] = upper, lower
                world2 = world_rotations(local)
                pos2 = forward_kinematics(world2)
                if chain == "arm":
                    side = name.split("_")[0]
                    if _arm_penetration(world2, pos2, side)[0] > _arm_penetration(world, pos, side)[0] + 0.5:
                        continue
                rot_track[i] = local
                track[i] = {k: v.copy() for k, v in pos2.items()}
                fixed += 1
                changed = True
            if not changed:
                break
        # Steps: the swivel flips in one frame and stays flipped. Spread the change over the
        # surrounding frames instead (hand/foot positions unchanged).
        for _ in range(3):
            sw = [swivel(i, root, mid, end) for i in range(n)]
            steps = [i for i in range(1, n) if np.any(sw[i]) and np.any(sw[i - 1])
                     and float(np.dot(sw[i], sw[i - 1])) < 0.64]
            if not steps:
                break
            for i in steps:
                a_i, b_i = max(0, i - 4), min(n - 1, i + 3)
                if not (np.any(sw[a_i]) and np.any(sw[b_i])):
                    continue
                # Choose ONE route for the whole transition (straight blend, around the outside, or
                # underneath) - the one that stays clearest of the body - then sweep along it.
                local_a = world_rotations({k: v.copy() for k, v in rot_track[a_i].items()})
                outward = local_a[parent][:, 0] * (1.0 if name.startswith("right") else -1.0)
                routes = [np.zeros(3), outward, np.array([0.0, -1.0, 0.2])]
                best_pen, best_frames = None, None
                for bias in routes:
                    trial, worst = [], 0.0
                    for j in range(a_i + 1, b_i):
                        u = (j - a_i) / (b_i - a_i)
                        pole = sw[a_i] * (1.0 - u) + sw[b_i] * u + bias * math.sin(math.pi * u) * 1.2
                        if np.linalg.norm(pole) < 0.15:
                            pole = pole + np.array([0.0, -0.5, 0.3])
                        local = {k: v.copy() for k, v in rot_track[j].items()}
                        world = world_rotations(local)
                        pos = forward_kinematics(world)
                        upper, lower, _ = two_bone_ik(pos[root], track[j][end], pole, l1, l2, world[parent], chain)
                        local[ub], local[lb] = upper, lower
                        world2 = world_rotations(local)
                        pos2 = forward_kinematics(world2)
                        pen = _arm_penetration(world2, pos2, name.split("_")[0])[0] if chain == "arm" else 0.0
                        worst = max(worst, pen)
                        trial.append((j, local, pos2))
                    if best_pen is None or worst < best_pen - 1e-6:
                        best_pen, best_frames = worst, trial
                if best_frames is None or best_pen > 2.0:
                    continue
                for j, local, pos2 in best_frames:
                    rot_track[j] = local
                    track[j] = {k: v.copy() for k, v in pos2.items()}
                    fixed += 1
    return fixed


def smooth_collision_corrections(recorded: List[Dict[str, Any]], previous: Optional[List[Dict[str, Any]]],
                                 loop: bool) -> List[Dict[str, Any]]:
    n = len(recorded)
    kernel = np.exp(-0.5 * (np.arange(-4, 5) / 2.0) ** 2)

    def idx(j: int) -> int:
        return j % n if loop else min(max(j, 0), n - 1)

    out: List[Dict[str, Any]] = [{} for _ in range(n)]
    for side in ("left", "right"):
        hand = np.array([r[side] for r in recorded])
        poles = np.array([r[side + "_pole"] for r in recorded])
        wts = np.array([r[side + "_pole_w"] for r in recorded])
        # Dilate: each frame takes the largest correction within +-3 frames (start early, end late).
        dil_hand = np.zeros_like(hand)
        for i in range(n):
            window = [idx(j) for j in range(i - 3, i + 4)]
            dil_hand[i] = hand[max(window, key=lambda j: float(np.linalg.norm(hand[j])))]
        dil_w = np.array([max(wts[idx(j)] for j in range(i - 3, i + 4)) for i in range(n)])
        for i in range(n):
            acc_h, acc_p, acc_w, ws = np.zeros(3), np.zeros(3), 0.0, 0.0
            for j, k in zip(range(i - 4, i + 5), kernel):
                jj = idx(j)
                acc_h += k * dil_hand[jj]
                acc_w += k * dil_w[jj]
                acc_p += k * wts[jj] * poles[jj]
                ws += k
            prev_h = previous[i][side] if previous else np.zeros(3)
            prev_w = previous[i][side + "_pole_w"] if previous else 0.0
            prev_p = previous[i][side + "_pole"] if previous else np.zeros(3)
            p = acc_p + prev_p * prev_w
            out[i][side] = prev_h + acc_h / ws
            out[i][side + "_pole_w"] = min(1.0, max(prev_w, acc_w / ws))
            out[i][side + "_pole"] = p / max(1e-9, np.linalg.norm(p)) if np.linalg.norm(p) > 1e-9 else poles[i]
    return out


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
    # Posture checks (what looks "weird" to a coach even without pops or pass-through).
    max_toe_out = max(max(k["right_foot"]["toe_out"], k["left_foot"]["toe_out"]) for k in plan["keyframes"])
    knee_bow = 0.0
    wing = int(stats.get("unintended_wing_samples", 0))
    for fi, t in enumerate(track):
        # Measure "sideways" relative to the body's own facing (not world x).
        fr = frames[fi] if fi < len(frames) else {}
        body_rot = euler_to_matrix(fr.get("positionx", 0.0), fr.get("positiony", 0.0), fr.get("positionz", 0.0))
        side_axis = body_rot[:, 0]
        for sd in ("left", "right"):
            hip, knee, foot = t[sd + "_hip"], t[sd + "_knee"], t[sd + "_foot"]
            line = foot - hip
            ll = float(np.dot(line, line))
            if ll > 1e-6:
                u = float(np.clip(np.dot(knee - hip, line) / ll, 0.0, 1.0))
                off = knee - (hip + line * u)
                knee_bow = max(knee_bow, abs(float(np.dot(off, side_axis))) * UNIT_TO_M)
    # True sideways bending comes from the plan (torso side bend + pelvis drop), not camera-like
    # projections of forward leans.
    side_lean = max(abs(k["torso"]["side_bend"]) + abs(k["pelvis"]["side"]) for k in plan["keyframes"])
    if wing > 2:
        issues.append(f"Elbows raised while hands are low (chicken wing) in {wing} samples.")
    if knee_bow > 0.12 and max_toe_out < 30:
        issues.append(f"Knee bows sideways off the leg line by {knee_bow:.2f} m.")
    if side_lean > 40:
        issues.append(f"Trunk bends {side_lean:.0f} degrees sideways.")

    # Typical limb speed while actually moving (holds/pauses excluded), for playback-speed tuning.
    eff = ["left_hand", "right_hand", "left_foot", "right_foot", "head"]
    if n > 2:
        spd = np.max([np.linalg.norm(np.diff(np.array([t[k] for t in track]), axis=0), axis=1) * UNIT_TO_M * fps
                      for k in eff], axis=0)
        moving = spd[spd > 0.25]
        speed_median = float(np.median(moving)) if len(moving) else 0.0
        moving_frac = float(len(moving) / len(spd))
    else:
        speed_median, moving_frac = 0.0, 0.0
    return {
        "passed": not issues,
        "speed_median_moving_mps": round(speed_median, 3),
        "moving_fraction": round(moving_frac, 3),
        "issues": issues,
        "frame_count": len(frames),
        "fps": fps,
        "loop": loop,
        "end_effector_travel_m": {k: round(v, 3) for k, v in travel.items()},
        "max_joint_delta_deg_per_frame": round(max_delta, 2),
        "max_pop_m": round(pop, 3),
        "posture": {"chicken_wing_samples": wing, "max_knee_bow_m": round(knee_bow, 3),
                    "max_side_lean_deg": round(side_lean, 1)},
        **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()},
    }


# -----------------------------------------------------------------------------
# Language model: enum-only movement grammar (no pre-programmed movements anywhere)
# -----------------------------------------------------------------------------
import motion_grammar as mg  # noqa: E402

TEMPO = {"slow": 1.35, "normal": 1.0, "fast": 0.8}
INTENSITY = {"low": 0.8, "medium": 1.0, "high": 1.15}
VIEWS = ["front", "side", "three_quarter", "back"]


def _obj(props: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(props.keys()), "additionalProperties": False}


def _enum(values: List[str]) -> Dict[str, Any]:
    return {"type": "string", "enum": list(values)}


HAND_SCHEMA = _obj({
    "height": _enum(mg.HAND_SPECIAL + list(mg.HAND_HEIGHTS)),
    "direction": _enum(list(mg.HAND_DIRECTIONS)),
    "reach": _enum(list(mg.HAND_REACH)),
    "elbow": _enum(mg.ELBOWS),
})
FOOT_SCHEMA = _obj({
    "position": _enum(mg.FOOT_SPECIAL + list(mg.FOOT_POSITIONS)),
    "height": _enum(list(mg.FOOT_HEIGHTS)),
    "leg": _enum(list(mg.LEG_SHAPES)),
})
LIMBS = ["right_hand", "left_hand", "right_foot", "left_foot"]
BEAT_SCHEMA = _obj({
    "label": {"type": "string"},
    "timing": _enum(list(mg.BEAT_TIME)),
    "base": _enum(["keep"] + list(mg.BASES)),
    "level": _enum(list(mg.LEVELS)),
    "trunk": _enum(["keep"] + list(mg.TRUNKS)),
    "facing": _enum(["keep"] + list(mg.FACINGS)),
    "right_hand": HAND_SCHEMA,
    "left_hand": HAND_SCHEMA,
    "right_foot": FOOT_SCHEMA,
    "left_foot": FOOT_SCHEMA,
    "hands_together": {"type": "boolean"},
})
PLAN_SCHEMA = _obj({
    # Stage 1: understand and simplify (generated first, so it conditions the beats).
    "canonical_name": {"type": "string"},
    "simplified_description": {"type": "string"},
    "key_details": {"type": "array", "items": {"type": "string"}},
    "implement": _enum(["none", "racket", "club", "bat", "stick", "ball", "weights", "other"]),
    "repeating_cycle": {"type": "boolean"},
    "phases": {"type": "array", "items": {"type": "string"}},
    "skill_limbs": {"type": "array", "items": _enum(LIMBS)},
    "title": {"type": "string"},
    "movement_summary": {"type": "string"},
    "coaching_cues": {"type": "array", "items": {"type": "string"}},
    "tempo": _enum(list(TEMPO)),
    "intensity": _enum(list(INTENSITY)),
    # Stage 2: encode the phases in the grammar.
    "camera_view": _enum(VIEWS),
    "loop": {"type": "boolean"},
    "beats": {"type": "array", "items": BEAT_SCHEMA},
})

PLANNER_INSTRUCTIONS = """
You are a sports biomechanist. You describe human movements (sport skills, exercises, drills,
including brand-new drills invented by a coach) so that an animation engine can play them. The
engine has NO built-in movements: it only knows the spatial vocabulary below. You decide where each
body part is at each key moment; the engine computes every joint angle and handles physics.

Work in two stages and fill the JSON fields in order.

STAGE 1 - UNDERSTAND AND SIMPLIFY
- canonical_name: the core movement in 2-6 words. Long or chatty requests: drop setting, story,
  people, emotions and coaching chatter; keep only what changes the body's motion.
- simplified_description: one plain sentence (max 25 words) of what the body does.
- key_details: at most 3 details that change the motion (side, stance, tempo, repetitions).
- phases: the movement broken into its real phases, in order. For EACH phase write one line that
  says where the hands, the feet and the trunk are and what they are doing (e.g. "contact: kicking
  leg nearly straight with the foot low in front, trunk over the ball, left arm out for balance").
  This is where you think - be biomechanically precise.
- skill_limbs: the limbs that PERFORM the skill or are placed deliberately by the technique (the
  striking hand, the kicking foot, both hands on a racket/ball, guard hands, arms held in a set
  position). Leave out limbs that only swing, balance or follow along: the engine animates those
  with natural counter-swing and balance, which looks better than hand-placing them.
- repeating_cycle: true for continuous cyclic actions (running, swimming, skipping, shuffling...).
- coaching_cues: 3-5 short practical cues. Assume a RIGHT-handed / right-footed athlete.

STAGE 2 - ENCODE EACH PHASE AS A BEAT
Each beat says what the body looks like at the END of that beat. The engine moves smoothly between
beats. Use 4-12 beats for one repetition or one cycle. Set "keep" for anything that does not change.

Body
- base: the support and body orientation. standing, athletic (feet wide, knees soft), wide, narrow,
  split_left_forward / split_right_forward (staggered feet), kneeling, half_kneeling_*_forward,
  face_down_horizontal (swimming, lying face down), face_down_on_hands (plank / push-up position),
  face_up_horizontal (lying on the back, backstroke), face_up_on_hands (crab position), seated,
  lying_on_left_side / lying_on_right_side, airborne (whole body in the air).
- level: hip height: tall, normal, slightly_bent, half_squat, deep_squat.
- trunk: upright (~5 deg), lean_forward (~25 deg: running, leaning into a ball or a throw),
  hinge (~55 deg: chest well forward, a bent-over / hip-hinge exercise), deep_hinge (~80 deg: chest
  near horizontal, toe touch), lean_back (~-20 deg), turn_left/turn_right (chest rotated ~45),
  full_turn_left/full_turn_right (~70, e.g. full backswing), side_bend_left/right.
  Choose the SMALLEST lean that matches the phase; hinge/deep_hinge only for real bending.
  "turn_right" = chest faces the athlete's RIGHT (a right-hander's wind-up/backswing).
- facing: the whole athlete's facing relative to the start (for real turns/pivots only).
- timing: how long the move INTO this beat takes: instant (explosive, ~0.15 s), quick, normal,
  slow, hold (stay in the previous pose for a pause).

Hands (right_hand / left_hand) - described like a coach points at a spot. Hands that are not in
skill_limbs are animated by the engine (you may write "auto" for them):
- height: floor, shin, knee, hip, waist, chest, shoulder, chin, head, overhead - always measured on
  the athlete's OWN body (a punch or throw aimed at someone's head travels at shoulder/chin height).
  Special: "auto" (engine picks a natural arm: counter-swing, balance, ready hands, floor support),
  "at_side" (arm hanging relaxed), "keep".
- direction: from the chest: front, front_out (45 deg to that hand's side), side, back_out, back,
  across (in front of the body toward the other side), center (in front of the body's centre line).
  Directions follow the chest when the trunk turns.
- reach: tucked (hand close to the body), bent (elbow ~90), extended (arm nearly straight).
- elbow: auto, down, out, back, up, forward (which way the bent elbow points).
- For a horizontal body the same words apply relative to the body as if standing: "overhead" is
  beyond the head (e.g. a swimmer's streamline), "front" points toward the floor/pool bottom,
  "back" points over the back toward the sky, "hip" is beside the hips.
- hands_together: both hands holding one ball/bat/club/stick (give the right hand's position).

Feet (right_foot / left_foot):
- height: how high the sole is ABOVE THE FLOOR: floor (planted, bearing weight), ankle (~10 cm),
  shin (~25 cm), knee, hip, high. An object lying on the ground is touched/struck at ankle height.
- position: on the floor, where the foot stands: under_hip, front, far_front, back, far_back, side,
  wide, front_side, back_side, cross_front, cross_back; "base" (back to the base position); "keep".
  For a RAISED foot, position is the direction the leg points from the hip.
- leg (raised feet only; ignored on the floor):
    straight = knee almost straight (leg swings, kicks at and after contact, leg raises),
    bent     = knee about 90 deg (heel kicked up behind, a loaded leg before it swings),
    tucked   = knee folded tight (knee drive, tuck, foot pulled to the buttock).
  The engine guarantees this knee bend: a straight leg at hip height in front is a high leg swing;
  a tucked foot under the hip at knee height is a knee drive.
- A foot at "floor" stays fixed on the ground while the body moves over it. Both feet off the floor
  = the athlete is in the air.
- Horizontal bodies (swimming, lying, planks): feet are described relative to the body as if it
  were standing. Legs extended in line with the body = height floor. "front" = toward the belly
  side, "back" = toward the back side, height = how far the foot is drawn up toward the hips.
  Heels folded up behind with the thighs near the body line = position back, leg tucked; thighs
  bent forward toward the belly side = position under_hip or front.

What the engine does for you (do NOT try to fake these):
- If a hand must reach low (knee, shin, floor) it hinges and bends the knees as much as needed.
- A hand reaching across rotates the chest toward it; a hand wound back high rotates the chest away.
- A leg lifted in front leans the trunk back slightly for balance (behind: leans forward).
- Arms not in skill_limbs (or set to "auto") swing in opposition to the legs, hold a balance arm out
  while a straight leg swings, or support on the floor.
- Planted feet never slide; the hips can rotate over them.

Craft
1. Real phases in order: preparation / load, the action, follow-through, recovery.
2. Timing matters: the power phase is fast (instant/quick); preparation and recovery slower; use
   "hold" for pauses, stuck landings and held positions.
3. Kinetic chain: hips and trunk rotate before the arm strikes. Wind-ups turn away first.
4. Follow-through: the striking limb keeps travelling past the contact point in the same
   direction (usually higher), then recovers. It does not stop at contact or veer sideways.
5. Repeating cycles: describe ONE cycle (do not repeat the first beat at the end), loop=true.
   One-off actions: loop=false and finish in a balanced position.
6. camera_view: side for forward/back and horizontal motion, front for lateral motion,
   three_quarter for rotation.
""".strip()


def _openai_client():
    if OpenAI is None:
        raise HTTPException(status_code=500, detail="openai package is not installed on the server.")
    if not os.getenv("OPENAI_API_KEY"):
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured for the motion service.")
    return OpenAI(max_retries=2, timeout=120)


PLANNER_EFFORT = os.getenv("MOTION_PLANNER_EFFORT", "low")


def _call_model(instructions: str, user_input: str, effort: str, schema: Dict[str, Any],
                name: str = "movement_plan", max_tokens: int = 12000,
                timeout: Optional[float] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    client = _openai_client()
    if timeout:
        client = client.with_options(timeout=timeout, max_retries=0)
    t0 = time.time()
    resp = client.responses.create(
        model=MODEL,
        instructions=instructions,
        input=user_input,
        reasoning={"effort": effort},
        store=False,
        text={"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
        max_output_tokens=max_tokens,
    )
    if getattr(resp, "status", None) == "incomplete":
        raise ValueError(f"Model output incomplete: {getattr(resp, 'incomplete_details', None)}")
    text = (getattr(resp, "output_text", "") or "").strip()
    usage = getattr(resp, "usage", None)
    meta = {"seconds": round(time.time() - t0, 1), "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None)}
    return json.loads(text), meta


TOUCH_HEIGHTS = ("floor", "shin", "knee")


def apply_skill_limbs(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Hands that do not perform the skill are handed to the engine's synergy rules (counter-swing,
    balance arm, floor support) instead of being hand-placed beat by beat by the model."""
    limbs = raw.get("skill_limbs")
    if not isinstance(limbs, list) or not limbs:
        return raw  # older descriptions: use the beats as written
    beats = []
    for b in raw.get("beats") or []:
        b = copy.deepcopy(b)
        for hand in ("right_hand", "left_hand"):
            d = b.get(hand) or {}
            if hand in limbs or b.get("hands_together") or d.get("height") in TOUCH_HEIGHTS + ("at_side",):
                continue
            b[hand] = {**d, "height": "auto"}
        beats.append(b)
    return {**raw, "beats": beats}


def plan_from_beats(raw: Dict[str, Any], duration: Optional[float] = None) -> Dict[str, Any]:
    """Deterministically build an engine plan from a grammar description (no model involved)."""
    speed = INTENSITY.get(raw.get("intensity", "medium"), 1.0) / TEMPO.get(raw.get("tempo", "normal"), 1.0)
    raw = apply_skill_limbs(raw)
    built = mg.build_beats(raw.get("beats") or [], bool(raw.get("loop")), speed)
    plan = sanitize_plan({
        "title": raw.get("title", ""),
        "movement_summary": raw.get("movement_summary", ""),
        "coaching_cues": raw.get("coaching_cues", []),
        "loop": built["loop"],
        "duration_seconds": duration or min(8.0, built["duration"]),
        "camera_view": raw.get("camera_view") if raw.get("camera_view") in VIEWS else "three_quarter",
        "keyframes": built["keys"],
    })
    if any(abs(k["body"]["roll"]) > 45 for k in plan["keyframes"]):
        plan["camera_view"] = "front"
    elif any(abs(k["body"]["pitch"]) > 65 for k in plan["keyframes"]):
        plan["camera_view"] = "side"
    plan["description"] = {k: raw.get(k) for k in ("canonical_name", "simplified_description", "phases",
                                                   "repeating_cycle", "tempo", "intensity", "implement",
                                                   "loop", "camera_view", "title", "movement_summary",
                                                   "coaching_cues", "skill_limbs")}
    plan["beats"] = raw.get("beats")
    plan["grammar_notes"] = built["notes"]
    return plan


def _raised(b: Dict[str, Any], min_height: Tuple[str, ...] = ("shin", "knee", "hip", "high")) -> List[Dict[str, Any]]:
    return [b.get(k) or {} for k in ("right_foot", "left_foot") if (b.get(k) or {}).get("height", "floor") in min_height]


PREP_OR_RECOVERY = ("load", "chamber", "wind", "cock", "back swing", "backswing", "prep", "ready", "set",
                    "guard", "return", "retract", "recover", "reset", "finish", "land", "together", "glide",
                    "to plank", "kickback", "kick back", "back to")
HORIZONTAL_BASES = ("face_down_horizontal", "face_down_on_hands", "face_up_horizontal", "face_up_on_hands",
                    "seated", "lying_on_left_side", "lying_on_right_side")
KICK_CONTEXT = ("kick", "shot", "shoot", "punt", "volley", "strike the ball")

# (words in the model's own beat label, words that exempt it, needs kick context, limb kind, test, feedback)
CONSISTENCY_RULES = [
    (("kick", "knee drive", "knee up", "knee raise", "high knee"), PREP_OR_RECOVERY, False, "foot",
     lambda b: bool(_raised(b)),
     "is labelled as a kick/knee drive but no foot is raised to shin height or above"),
    (("kick", "contact", "strike", "impact", "follow", "shot", "shoot"), ("knee",) + PREP_OR_RECOVERY, True, "foot",
     lambda b: not any(f.get("leg") == "tucked" for f in _raised(b)),
     "is a kick/strike/follow-through but the raised leg is 'tucked' (that is a knee lift): use leg "
     "'straight' for contact and follow-through"),
    (("knee drive", "high knee", "knee up", "knee raise", "knee lift", "march"), (), False, "foot",
     lambda b: any(f.get("leg") in ("tucked", "bent") for f in _raised(b, ("knee", "hip", "high"))),
     "is a knee drive but no raised leg is 'tucked' or 'bent' (a straight leg is a leg swing, not a knee drive)"),
    (("touch the floor", "touch floor", "hands to floor", "hand to floor", "touch the ground", "touch ground",
      "touch the cone", "touch cone", "hands down"), (), False, "hand",
     lambda b: any((b.get(k) or {}).get("height") in ("floor", "shin") for k in ("right_hand", "left_hand"))
     or b.get("base") in ("face_down_on_hands", "face_up_on_hands"),
     "is labelled as touching the floor/cone but no hand goes to floor or shin height"),
    (("punch", "jab", "cross", "throw", "release", "reach"), ("kick", "foot", "leg") + PREP_OR_RECOVERY, False, "hand",
     lambda b: any((b.get(k) or {}).get("reach") == "extended" and (b.get(k) or {}).get("height") not in ("keep", "auto", "at_side")
                   for k in ("right_hand", "left_hand")),
     "is labelled as a punch/throw/reach but no hand is extended (hands not listed in skill_limbs are "
     "animated automatically - list the hand in skill_limbs if it performs the action)"),
]


def consistency_problems(beats: List[Dict[str, Any]], context: str = "",
                         skill_limbs: Optional[List[str]] = None) -> List[str]:
    """Check that each beat's encoding matches the model's own description of it."""
    out = []
    context = context.lower()
    kick_context = any(w in context for w in KICK_CONTEXT)
    hands_act = not skill_limbs or any(l.endswith("hand") for l in skill_limbs)

    def airborne(b: Dict[str, Any]) -> bool:
        return b.get("base") == "airborne" or all((b.get(k) or {}).get("height", "floor") != "floor"
                                                   for k in ("right_foot", "left_foot"))
    jump_words = ("jump", "hop", "leap", "bound", "airborne", "explode up")
    transition_words = ("feet", "foot", "land", "back to", "into", "to plank", "to squat")
    def has_word(text: str, words: Tuple[str, ...]) -> bool:
        text = " " + re.sub(r"[^a-z]+", " ", text.lower()) + " "
        return any(re.search(r"\b" + re.escape(w), text) for w in words)  # "hop" must not match "choppy"
    body_jumps = [i for i, b in enumerate(beats)
                  if has_word(str(b.get("label", "")), jump_words)
                  and not has_word(str(b.get("label", "")), transition_words)]
    if body_jumps and not any(airborne(b) for b in beats):
        i = body_jumps[0]
        out.append(f"Beat {i + 1} ('{beats[i].get('label', '')}') describes a jump but no beat leaves the ground: "
                   "lift both feet (base airborne) at the top of the jump, then land.")
    base = "standing"
    for i, b in enumerate(beats):
        label = str(b.get("label", "")).lower().replace("_", " ").replace("-", " ")
        base = b.get("base") if b.get("base") not in (None, "keep") else base
        if b.get("timing") == "hold":
            continue
        for words, exempt, needs_kick, kind, test, msg in CONSISTENCY_RULES:
            if kind == "foot" and base in HORIZONTAL_BASES:
                continue  # swimming/lying "kicks" are small leg beats, not standing kicks
            if needs_kick and not (kick_context or any(w in label for w in KICK_CONTEXT)):
                continue
            if kind == "hand" and not hands_act:
                continue
            if any(w in label for w in words) and not any(w in label for w in exempt) and not test(b):
                out.append(f"Beat {i + 1} ('{b.get('label', '')}') {msg}.")
                break
    return out[:6]


def balance_problems(beats: List[Dict[str, Any]]) -> List[str]:
    """Static-balance check in words the model understands: a big forward hinge while standing on
    one leg with the free leg forward (or under the body) puts the centre of mass far outside the
    support foot - only a free leg reaching BACK counterbalances it."""
    out, trunk, base = [], "upright", "standing"
    for i, b in enumerate(beats):
        trunk = b.get("trunk") if b.get("trunk") not in (None, "keep") else trunk
        base = b.get("base") if b.get("base") not in (None, "keep") else base
        if base in ("face_down_horizontal", "face_down_on_hands", "face_up_horizontal", "face_up_on_hands",
                    "seated", "lying_on_left_side", "lying_on_right_side", "airborne"):
            continue
        feet = [b.get(k) or {} for k in ("right_foot", "left_foot")]
        down = [f for f in feet if f.get("height", "floor") == "floor"]
        up = [f for f in feet if f.get("height", "floor") in ("shin", "knee", "hip", "high")]
        hands_low = any((b.get(k) or {}).get("height") in TOUCH_HEIGHTS for k in ("right_hand", "left_hand"))
        if trunk in ("hinge", "deep_hinge") and len(down) == 1 and len(up) == 1 and not hands_low \
                and up[0].get("position") not in mg.BACK_POSITIONS:
            out.append(f"Beat {i + 1} ('{b.get('label', '')}'): trunk '{trunk}' while balancing on one leg with the "
                       "free leg forward/under the body is off-balance. Use upright or lean_forward (lean_back for "
                       "a high leg in front).")
    return out[:3]


def critique_plan(raw: Dict[str, Any], plan: Dict[str, Any], report: Dict[str, Any]) -> List[str]:
    """Objective feedback from the rigid mechanism back to the model (drives one repair call)."""
    raw = apply_skill_limbs(raw)
    beats = raw.get("beats") or []
    problems: List[str] = []
    if len(beats) < 3:
        problems.append("Too few beats: describe each real phase (4-12 beats).")
    changing = 0
    for b in beats:
        if any(b.get(k, "keep") not in ("keep",) for k in ("base", "trunk", "facing")) or b.get("level") not in ("keep", None):
            changing += 1
            continue
        if any((b.get(k) or {}).get("height") not in ("keep", None) for k in ("right_hand", "left_hand")):
            changing += 1
            continue
        if any((b.get(k) or {}).get("position") not in ("keep", None) or (b.get(k) or {}).get("height") != "floor"
               for k in ("right_foot", "left_foot")):
            changing += 1
    if changing < 2:
        problems.append("The beats barely change the body: describe the actual positions of each phase.")
    if raw.get("repeating_cycle") and not raw.get("loop"):
        problems.append("The movement is a repeating cycle but loop=false: describe one cycle and set loop=true.")
    airborne_run = 0
    for b in ([] if raw.get("loop") else beats):  # running/skipping cycles chain several flight beats
        up = all((b.get(k) or {}).get("height", "floor") != "floor" for k in ("right_foot", "left_foot"))
        airborne_run = airborne_run + 1 if up and b.get("base") not in ("face_down_horizontal", "face_up_horizontal") else 0
        if airborne_run >= 3:
            problems.append("Both feet stay off the floor for 3+ beats in a row: is the athlete really in the air?")
            break
    context = " ".join(str(raw.get(k) or "") for k in ("canonical_name", "simplified_description"))
    problems += consistency_problems(beats, context, raw.get("skill_limbs"))
    problems += balance_problems(beats)
    if any(w in context.lower() for w in ("single-leg", "single leg", "one-leg", "one leg", "single-legged")):
        both_down = [i + 1 for i, b in enumerate(beats[1:-1], start=1)
                     if all((b.get(k) or {}).get("height", "floor") == "floor" for k in ("right_foot", "left_foot"))]
        if len(both_down) > max(1, (len(beats) - 2) // 2):
            problems.append(f"This is a single-leg movement but beats {both_down} keep both feet on the floor: the free "
                            "foot must stay off the floor (raised, e.g. reaching back as the trunk hinges forward).")
    limbs = raw.get("skill_limbs") or []
    words = " ".join([str(b.get("label", "")) for b in beats] + [str(x) for x in raw.get("phases") or []]).lower()
    if limbs and "guard" in words:
        loose = [h for h in ("right_hand", "left_hand") if h not in limbs]
        if loose:
            problems.append(f"The movement holds a guard but {' and '.join(loose)} is not in skill_limbs, so the engine "
                            "would let it swing freely: list it in skill_limbs and give its guard position in every beat.")
    if beats and not raw.get("loop"):
        last = beats[-1]
        feet_down = any((last.get(k) or {}).get("height", "floor") == "floor" for k in ("right_foot", "left_foot"))
        if last.get("base") == "airborne" or not feet_down:
            problems.append("The movement ends in the air: add a landing/recovery beat that finishes balanced on the feet.")
    for i, b in enumerate(beats):
        if b.get("base") in ("face_down_horizontal", "face_up_horizontal", "seated", "face_up_on_hands"):
            continue
        high = [k for k in ("right_foot", "left_foot") if (b.get(k) or {}).get("height") in ("hip", "high")]
        tucked = all((b.get(k) or {}).get("leg") in ("tucked", "bent") for k in high)
        if len(high) == 2 and not tucked:  # knees pulled up (tuck/box jump) is fine; straight legs = straddle/pike
            problems.append(f"Beat {i + 1} ({b.get('label', '')}): both feet at hip height or higher (a straddle/pike "
                            "in the air). Keep this only if the movement really is a straddle/pike jump; a normal "
                            "jump keeps the feet below the knees.")
    for issue in report.get("issues", []):
        if "little visible motion" in issue:
            problems.append("The motion is almost static: make each phase's positions clearly different.")
        elif "chicken wing" in issue:
            problems.append("An elbow sits high while its hand is low: use elbow 'down' or raise the hand.")
        elif "sideways" in issue:
            problems.append("The trunk bends too far sideways: reduce side bends.")
    return problems


def _repair_input(movement: str, raw: Dict[str, Any], problems: List[str]) -> str:
    return ("MOVEMENT REQUEST: " + movement.strip() + "\n\nYOUR PREVIOUS ANSWER:\n" + json.dumps(raw) +
            "\n\nPROBLEMS FOUND BY THE ENGINE (fix them, keep everything else):\n" +
            "\n".join("- " + p for p in problems))


def plan_movement(movement: str, extra: str = "", duration: Optional[float] = None,
                  refine: bool = False) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Text -> grammar description (one model call) -> deterministic build -> engine checks ->
    (only if the engine finds problems) one repair call with its exact findings."""
    calls: List[Dict[str, Any]] = []
    request = f"Movement request: {movement.strip()}"
    if extra.strip():
        request += f"\nNotes: {extra.strip()}"
    raw, meta = _call_model(PLANNER_INSTRUCTIONS, request, "medium" if refine else PLANNER_EFFORT, PLAN_SCHEMA)
    plan = plan_from_beats(raw, duration)
    _, report = compile_motion(plan, None, DEFAULT_FPS, return_to_start=False)
    problems = critique_plan(raw, plan, report)
    calls.append({"stage": "describe", **meta, "canonical_name": raw.get("canonical_name"),
                  "beats": len(raw.get("beats") or []), "problems": problems})
    if problems:
        try:
            raw2, meta2 = _call_model(PLANNER_INSTRUCTIONS, _repair_input(movement, raw, problems), PLANNER_EFFORT,
                                      PLAN_SCHEMA)
            plan2 = plan_from_beats(raw2, duration)
            _, report2 = compile_motion(plan2, None, DEFAULT_FPS, return_to_start=False)
            problems2 = critique_plan(raw2, plan2, report2)
            calls.append({"stage": "repair", **meta2, "problems": problems2})
            if len(problems2) <= len(problems):
                plan = plan2
        except Exception as exc:  # repair is best effort
            calls.append({"stage": "repair", "error": str(exc)})
    return plan, calls


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
    speed: Literal["auto", "realtime"] = "auto"  # auto = playback FPS tuned for natural on-screen speed
    use_cache: bool = True
    repair_attempts: int = Field(default=0, ge=0, le=1)  # kept for backwards compatibility (ignored)
    # "script": the model composes stored motions from motion_database.py in the motion language
    # (motion_script.py). "grammar": the older beat-grammar pipeline.
    engine: Literal["script", "grammar"] = "script"


class ScriptRequest(BaseModel):
    script: str = Field(min_length=2, max_length=4000)
    dominant_side: Literal["left", "right"] = "right"
    title: str = ""


class CompileRequest(BaseModel):
    plan: Dict[str, Any]
    duration_seconds: Optional[float] = Field(default=None, ge=0.6, le=8.0)
    playback_fps: int = Field(default=DEFAULT_FPS, ge=6, le=60)
    dominant_side: Literal["left", "right"] = "right"
    speed: Literal["auto", "realtime"] = "auto"


app = FastAPI(title="CogniCoach Motion Engine", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


STARTED_AT = time.strftime("%Y-%m-%d %H:%M:%S")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "engine_version": ENGINE_VERSION, "engine_file": str(Path(__file__).resolve()),
            "started_at": STARTED_AT, "model": MODEL, "api_key_configured": bool(os.getenv("OPENAI_API_KEY"))}


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


TARGET_VIEW_SPEED_MPS = float(os.getenv("MOTION_TARGET_SPEED", "1.6"))


def auto_playback_fps(report: Dict[str, Any], fps: int) -> Tuple[int, float]:
    """Choose a playback FPS so the clip's typical limb speed looks natural on screen.

    Frames are unchanged; only the rate they are played at. A compressed curve keeps relative
    rhythm (sprints still look faster than stretches) while pulling extremes into a watchable band.
    Returns (playback_fps, time_scale) where time_scale > 1 means slowed down.
    """
    speed = report.get("speed_median_moving_mps", 0.0)
    if speed <= 0.3 or report.get("moving_fraction", 0.0) < 0.15:
        return fps, 1.0  # holds / very slow controlled drills: play as generated
    scale = (speed / TARGET_VIEW_SPEED_MPS) ** 0.6
    scale = max(1 / 1.3, min(1.8, scale))
    if abs(scale - 1.0) < 0.1:
        return fps, 1.0
    return int(round(fps / scale)), scale


def _build_response(plan: Dict[str, Any], duration: Optional[float], fps: int, side: str,
                    calls: List[Dict[str, Any]], cached: bool, speed_mode: str = "auto") -> Dict[str, Any]:
    solved = mirror_plan(plan) if side == "left" else plan
    frames, report = compile_motion(solved, duration, fps)
    playback_fps, time_scale = auto_playback_fps(report, fps) if speed_mode == "auto" else (fps, 1.0)
    report["generated_fps"] = fps
    report["playback_time_scale"] = round(time_scale, 2)
    text = mirror_text if side == "left" else (lambda t: t)
    return {
        "frames": sparse(frames),
        "playback_fps": playback_fps,
        "duration_seconds": round(len(frames) / playback_fps, 2),
        "loop": plan["loop"],
        "camera_view": plan["camera_view"],
        # Upright movements stand on a floor (the viewer draws a contact shadow); horizontal ones
        # (swimming, lying, planks) pivot about the pelvis, so no floor is shown for them.
        "ground": not any(abs(k["body"]["pitch"]) > 45 or abs(k["body"]["roll"]) > 45 for k in plan["keyframes"]),
        "dominant_side": side,
        "title": text(plan.get("title", "")),
        "movement_summary": text(plan.get("movement_summary", "")),
        "coaching_cues": [text(c) for c in plan.get("coaching_cues", [])],
        "plan": plan,
        "report": report,
        "model": MODEL,
        "llm_calls": calls,
        "cached": cached,
        "engine_version": ENGINE_VERSION,
    }


# -----------------------------------------------------------------------------
# Motion-script pipeline: the model composes stored motions; the compiler merges them.
# -----------------------------------------------------------------------------
SCRIPT_SCHEMA = _obj({
    "canonical_name": {"type": "string"},
    "steps": {"type": "array", "items": {"type": "string"}},
    "title": {"type": "string"},
    "coaching_cues": {"type": "array", "items": {"type": "string"}},
    "camera_view": _enum(VIEWS),
    "script": {"type": "string"},
})


def script_instructions() -> str:
    import motion_database as mdb
    return f"""
You turn a coaching request into a short animation script for a 3D athlete, built from a database
of stored, high-quality motions. You decide WHAT the athlete does; the motions already know HOW.

Fill the fields in order:
1. canonical_name: the core movement or drill in 2-6 words.
2. steps: what the athlete does, in order, as 1-8 plain steps (e.g. "sprint forward", "touch the cone
   with the right hand", "backpedal to the start"). Drop story, setting and chatter.
3. title, coaching_cues (3-5 short cues for a right-handed athlete), camera_view (side for forward/back
   motion and swimming, front for side-to-side motion, three_quarter otherwise).
4. script: the steps written in the motion language below.

THE MOTION LANGUAGE
- Each line lists motions from the CATALOG: name or name(param=value, ...). Use ONLY exact catalog
  names. A FULL BODY motion needs nothing else on its line.
- Motions joined with + on ONE line play at the SAME time. The next line starts when the line before
  it ends (the engine blends between lines).
- Each motion drives only some body parts (listed in the catalog). Build a full-body skill by putting
  a lower-body motion (stance, fighting_stance, run, stride_step, jump ...) on the same line as an
  upper-body motion (forehand, guard, jab, shoot ...). Two motions that both DRIVE the same part
  cannot share a line; "soft" parts simply give way.
- Parts that nothing drives on a line keep their previous pose, but it is clearer to repeat held
  motions (e.g. fighting_stance + guard) on every line where they apply.
- Every motion also accepts: side=left (mirror it: shuffle(side=left) moves left, jab is already the
  left hand), speed=0.5..2, times=N (repeat), hold=seconds (hold the end), delay=seconds (start later
  than the rest of its line - e.g. jump + shoot(delay=0.35)).
- Add " x3" at the end of a line to repeat the whole line. A final line "loop" makes the clip loop
  (continuous drills: running, swimming, skipping, shuffles).
- The athlete is right-handed (the engine mirrors everything for left-handers).
- Motions already contain their natural supporting action as SOFT parts: soccer_kick has calm balance
  arms, run pumps the arms, jump swings the arms, stance leans the trunk. Do NOT add an arm motion on
  top of a kick, run or jump unless the request needs a specific arm action (guard, dribble, shoot,
  carrying, hands high). Never add arms_out / arms_overhead just for balance.
- Start straight into the movement (a short ready stance is fine before a sport skill). Never insert
  a pose from a different activity (no plank before swimming, no stance before a swim stroke).
- Use the fewest motions that show the request; usually 1-5 lines and under 8 seconds. For a drill
  that is not in the catalog, chain catalog motions that match its steps.

Syntax examples:
stance(width=wide, depth=0.5) + ready_arms
stance(width=wide, depth=0.5) + forehand
run(pace=sprint, times=2)

CATALOG (name(params) [kind; parts it drives; soft parts] description):
{mdb.catalog_text()}
""".strip()


def _compile_script(script: str, side: str) -> Dict[str, Any]:
    import motion_database as mdb
    import motion_script as ms
    return ms.compile_script(script, mdb.DB, dominant_side=side)


SCRIPT_EFFORT = os.getenv("MOTION_SCRIPT_EFFORT", "minimal")   # minimal: ~3-5 s per request
SCRIPT_TIMEOUT = float(os.getenv("MOTION_SCRIPT_TIMEOUT", "9"))  # seconds before the local fallback


def _words(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 2]


def local_script(movement: str) -> Optional[Dict[str, Any]]:
    """Instant script without the model: the request names a motion (or a known alias), or - as a
    fallback - the motion whose name, aliases and description best match the request's words."""
    import motion_database as mdb
    text = " ".join(_words(movement))
    alias = mdb.ALIASES.get(text) or mdb.ALIASES.get(text.rstrip("s"))
    if alias:
        return {"canonical_name": text, "steps": [], "title": text.title(), "coaching_cues": [],
                "camera_view": "three_quarter", "script": alias, "exact": True}
    best, score = None, 0.0
    for name, m in mdb.DB.items():
        names = [name.replace("_", " ")] + list(m.get("aliases", []))
        if text in names:
            best, score = name, 99.0
            break
        sc = 0.0
        for nm in names:
            nw = nm.split()
            sc = max(sc, 3.0 * sum(w in text.split() or w.rstrip("s") in text for w in nw) / len(nw))
        sc += 0.5 * len(set(_words(m["comment"])) & set(text.split())) / max(3, len(text.split()))
        if sc > score:
            best, score = name, sc
    if best is None or score < 1.5:
        return None
    m = mdb.DB[best]
    lower = {"right_leg", "left_leg", "body"} & set(m["parts"])
    item = best + ("(times=2)" if m["kind"] == "cycle" else "")
    if lower:
        script = item
    elif {"right_arm", "left_arm"} & set(m["parts"]) and best in ("jab", "cross", "hook", "uppercut"):
        script = f"fighting_stance + guard\nfighting_stance + guard + {item}"
    else:
        script = f"stance(depth=0.3) + ready_arms\nstance(depth=0.3) + {item}"
    return {"canonical_name": best.replace("_", " "), "steps": [m["comment"]], "title": best.replace("_", " ").title(),
            "coaching_cues": [], "camera_view": "side" if m["parts"] and "body" in m["parts"] and best in
            ("freestyle", "breaststroke", "butterfly", "backstroke", "push_up", "plank", "mountain_climbers") else
            "three_quarter", "script": script, "exact": score >= 99.0}


def plan_script(movement: str, extra: str = "") -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Text -> motion script in ONE fast model call. The compiler repairs problems itself (no repair
    round trip); if the model is slow or fails, a local database match answers instead."""
    t0 = time.time()
    local = local_script(movement)
    if local and local.get("exact") and not extra.strip():
        return local, [{"stage": "local", "seconds": round(time.time() - t0, 2), "script": local["script"]}]
    request = f"Request: {movement.strip()}" + (f"\nNotes: {extra.strip()}" if extra.strip() else "")
    try:
        raw, meta = _call_model(script_instructions(), request, SCRIPT_EFFORT, SCRIPT_SCHEMA, name="motion_script",
                                max_tokens=3000, timeout=SCRIPT_TIMEOUT)
        _compile_script(raw.get("script", ""), "right")   # lenient: only fails if nothing usable is left
        return raw, [{"stage": "script", **meta, "script": raw.get("script")}]
    except HTTPException:
        raise
    except Exception as exc:
        fallback = local or {"canonical_name": "stance", "steps": [], "title": movement.strip()[:60], "coaching_cues": [],
                             "camera_view": "three_quarter", "script": "stance(depth=0.3) + ready_arms"}
        return fallback, [{"stage": "local-fallback", "seconds": round(time.time() - t0, 1),
                           "reason": f"{type(exc).__name__}: {str(exc)[:120]}", "script": fallback["script"]}]


def script_response(raw: Dict[str, Any], side: str, calls: List[Dict[str, Any]], cached: bool) -> Dict[str, Any]:
    compiled = _compile_script(raw.get("script", ""), side)
    text = mirror_text if side == "left" else (lambda t: t)
    return {
        "frames": sparse(compiled["frames"]),
        "playback_fps": compiled["fps"],
        "duration_seconds": compiled["duration_seconds"],
        "loop": compiled["loop"],
        "camera_view": raw.get("camera_view") if raw.get("camera_view") in VIEWS else "three_quarter",
        "ground": compiled["ground"],
        "dominant_side": side,
        "title": text(raw.get("title", "")),
        "movement_summary": "; ".join(raw.get("steps") or []),
        "coaching_cues": [text(c) for c in raw.get("coaching_cues", [])],
        "script": raw.get("script", ""),
        "plan": {"script": raw.get("script", ""), "steps": raw.get("steps"), "lines": compiled["lines"]},
        "report": {**compiled["report"], "playback_time_scale": 1.0},
        "model": MODEL,
        "llm_calls": calls,
        "cached": cached,
        "engine_version": ENGINE_VERSION,
    }


@app.get("/motions")
def list_motions() -> Dict[str, Any]:
    import motion_database as mdb
    return {"motions": [{"name": n, "comment": m["comment"], "kind": m["kind"], "parts": m["parts"],
                         "soft_parts": m["soft_parts"], "params": {k: list(v[1]) if isinstance(v[1], tuple) else v[1]
                                                                    for k, v in m["params"].items()}}
                        for n, m in mdb.DB.items()]}


@app.post("/script")
def run_script(req: ScriptRequest) -> Dict[str, Any]:
    import motion_script as ms
    try:
        t0 = time.time()
        resp = script_response({"script": req.script, "title": req.title or "Motion script"}, req.dominant_side, [], False)
        print(f"[motion] script: {time.time() - t0:.2f} s compile -> {resp['duration_seconds']} s clip", flush=True)
        return resp
    except ms.ScriptError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@app.post("/generate")
def generate(req: GenerateRequest) -> Dict[str, Any]:
    if req.engine == "script":
        import motion_script as ms
        t_start = time.time()
        key = _cache_key("script", ENGINE_VERSION, req.movement.strip().lower(), req.extra_instructions.strip(), MODEL)
        raw = cache_get(key) if req.use_cache else None
        cached, calls = raw is not None, []
        if raw is None:
            try:
                raw, calls = plan_script(req.movement, req.extra_instructions)
            except ms.ScriptError as err:
                raise HTTPException(status_code=502, detail=f"The model wrote a script that does not compile: {err}") from err
            except HTTPException:
                raise
            except Exception as exc:
                traceback.print_exc()
                raise HTTPException(status_code=502, detail=f"Motion planning failed: {exc}") from exc
            cache_put(key, raw)
        t_model = time.time() - t_start
        resp = script_response(raw, req.dominant_side, calls, cached)
        import motion_database as mdb
        mdb.save_solved()   # keep any newly solved pose for next time
        total = time.time() - t_start
        source = "cache" if cached else (calls[0]["stage"] if calls else "?")
        resp["timing"] = {"total_seconds": round(total, 2), "planning_seconds": round(t_model, 2),
                          "compile_seconds": round(total - t_model, 2), "source": source}
        print(f"[motion] {req.movement.strip()[:50]!r}: {total:.1f} s total (planning {t_model:.1f} s via {source}, "
              f"compile {total - t_model:.2f} s) -> {resp['duration_seconds']} s clip", flush=True)
        if calls and calls[0].get("reason"):
            print(f"[motion]   model not used: {calls[0]['reason']}", flush=True)
        for w in resp["report"].get("warnings", []):
            print(f"[motion]   fixed: {w}", flush=True)
        return resp
    key = _cache_key(ENGINE_VERSION, req.movement.strip().lower(), req.extra_instructions.strip(), req.duration_seconds,
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
        return _build_response(plan, req.duration_seconds, req.playback_fps, req.dominant_side, calls, cached,
                               req.speed)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Motion compile failed: {exc}") from exc


@app.post("/compile")
def compile_endpoint(req: CompileRequest) -> Dict[str, Any]:
    try:
        plan = sanitize_plan(req.plan)
        return _build_response(plan, req.duration_seconds, req.playback_fps, req.dominant_side, [], False,
                               req.speed)
    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=400, detail=f"Could not compile supplied plan: {exc}") from exc


def _hand(height: str, direction: str = "front", reach: str = "bent", elbow: str = "auto") -> Dict[str, str]:
    return {"height": height, "direction": direction, "reach": reach, "elbow": elbow}


def _foot(position: str = "keep", height: str = "floor") -> Dict[str, str]:
    return {"position": position, "height": height}


# Offline test description written in the grammar (a test fixture, not a library movement).
SELFTEST_DESCRIPTION: Dict[str, Any] = {
    "title": "Grammar self-test", "loop": True, "tempo": "normal", "intensity": "medium", "camera_view": "front",
    "beats": [
        {"label": "feet together, arms down", "timing": "normal", "base": "narrow", "level": "normal", "trunk": "upright",
         "facing": "keep", "right_hand": _hand("at_side"), "left_hand": _hand("at_side"),
         "right_foot": _foot(), "left_foot": _foot(), "hands_together": False},
        {"label": "hop out, arms up", "timing": "quick", "base": "keep", "level": "keep", "trunk": "keep",
         "facing": "keep", "right_hand": _hand("overhead", "side", "extended"),
         "left_hand": _hand("overhead", "side", "extended"),
         "right_foot": _foot("wide", "ankle"), "left_foot": _foot("wide", "ankle"), "hands_together": False},
        {"label": "land wide", "timing": "quick", "base": "keep", "level": "slightly_bent", "trunk": "keep",
         "facing": "keep", "right_hand": _hand("keep"), "left_hand": _hand("keep"),
         "right_foot": _foot("wide", "floor"), "left_foot": _foot("wide", "floor"), "hands_together": False},
        {"label": "touch the floor (reach inference)", "timing": "normal", "base": "keep", "level": "keep",
         "trunk": "keep", "facing": "keep", "right_hand": _hand("floor", "front", "extended"),
         "left_hand": _hand("auto"), "right_foot": _foot(), "left_foot": _foot(), "hands_together": False},
    ],
}


def selftest() -> int:
    """Offline check of grammar + solver (no API key needed): python motion_engine.py --selftest"""
    ok = (abs(mg.SHOULDER_X - SHOULDER_OFFSET[0] * UNIT_TO_M) < 1e-9 and abs(mg.SHOULDER_Y - SHOULDER_OFFSET[1] * UNIT_TO_M) < 1e-9
          and abs(mg.HIP_DROP_SCALE - HIP_DROP_SCALE) < 1e-9 and abs(mg.UNIT_TO_M - UNIT_TO_M) < 1e-12)
    print("grammar/engine geometry consistent:", ok)
    plan = plan_from_beats(SELFTEST_DESCRIPTION)
    for side in ("right", "left"):
        solved = mirror_plan(plan) if side == "left" else plan
        frames, report = compile_motion(solved, None, DEFAULT_FPS, return_to_start=False)
        print(f"[{side}-handed] frames={len(frames)} issues={report['issues']} notes={plan['grammar_notes'][:2]}")
        ok = ok and len(frames) > 10 and not report["issues"]
    touch = [k for k in plan["keyframes"] if "touch the floor" in k["phase"]][0]
    ok = ok and touch["torso"]["lean"] >= 50  # reach inference must have hinged the trunk
    # Anatomical leg construction: a straight leg is straight, a bent leg behind keeps its knee
    # behind the hip, a tucked leg in front is a knee drive (thigh forward).
    leg = mg.LEG_LEN
    f, o, l, kf_ = mg.leg_target(*mg.FOOT_POSITIONS["front"], mg.FOOT_HEIGHTS["hip"], "straight", 0.0)
    straight_ok = math.hypot(f, leg - l) > 0.95 * leg
    f, o, l, kb = mg.leg_target(*mg.FOOT_POSITIONS["back"], mg.FOOT_HEIGHTS["shin"], "bent", 0.0)
    bent_ok = kb < 0.0 and f < -0.2
    f, o, l, kd = mg.leg_target(*mg.FOOT_POSITIONS["under_hip"], mg.FOOT_HEIGHTS["knee"], "tucked", 0.0)
    drive_ok = kd > 0.2
    print(f"leg anatomy: straight={straight_ok} bent-behind={bent_ok} knee-drive={drive_ok}")
    ok = ok and straight_ok and bent_ok and drive_ok
    # Ballistic flight: a long flight rises more than a short one; a running stride barely rises.
    keys = [(0.0, {"left_foot_planted": True, "right_foot_planted": True, "left_foot": {"lift": 0.0, "forward": 0.0},
                   "right_foot": {"lift": 0.0, "forward": 0.0}, "body": {"pitch": 0, "roll": 0}, "pelvis": {"height": 0.0}})]
    for t in (0.3, 0.6):
        keys.append((t, {"left_foot_planted": False, "right_foot_planted": False, "left_foot": {"lift": 0.1, "forward": 0.0},
                         "right_foot": {"lift": 0.1, "forward": 0.0}, "body": {"pitch": 0, "roll": 0}, "pelvis": {"height": 0.3}}))
    keys.append((0.9, copy.deepcopy(keys[0][1])))
    mg._ballistic_flight(keys, False, 0.9)
    flight_ok = 0.25 < max(k["pelvis"]["height"] for _, k in keys) <= mg.FLIGHT_MAX_RISE
    print("ballistic flight:", flight_ok)
    ok = ok and flight_ok
    # Motion-script pipeline: scripts compile, conflicts are reported, mirroring works.
    import motion_database as mdb
    import motion_script as ms
    r = ms.compile_script("stance(width=wide, depth=0.5) + forehand\nfighting_stance + guard + jab", mdb.DB)
    rl = ms.compile_script("stance(width=wide, depth=0.5) + forehand", mdb.DB, dominant_side="left")
    script_ok = len(r["frames"]) > 30 and not r["report"]["issues"] and len(rl["frames"]) > 30
    try:
        ms.compile_script("stance + run", mdb.DB, strict=True)
        script_ok = False  # both drive the legs: strict mode must refuse
    except ms.ScriptError:
        pass
    split = ms.compile_script("stance + run", mdb.DB)     # lenient: plays one after the other
    script_ok = script_ok and len(split["lines"]) == 2
    print("motion script:", script_ok, f"({len(mdb.DB)} motions in the database)")
    ok = ok and script_ok
    print("SELFTEST", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        raise SystemExit(selftest())
    import uvicorn
    import motion_database as _mdb
    _t = time.time()
    for _m in _mdb.DB.values():   # warm every stored motion (pre-solved; well under a second)
        _m["build"]()
    _mdb.save_solved()
    print(f"Motion database: {len(_mdb.DB)} motions ready in {time.time() - _t:.1f} s")
    print(f"CogniCoach Motion Engine v{ENGINE_VERSION} on http://{HOST}:{PORT}  (model: {MODEL})")
    print(f"Running file: {Path(__file__).resolve()}")
    print("Restart this server (Ctrl+C, then run again) after every git pull - a running server keeps old code.")
    if not os.getenv("OPENAI_API_KEY"):
        print("WARNING: OPENAI_API_KEY is not set; /generate will fail until it is.")
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
