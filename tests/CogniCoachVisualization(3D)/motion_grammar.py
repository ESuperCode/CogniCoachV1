"""CogniCoach movement grammar: the rigid mechanism that turns enum-only descriptors into motion.

There are NO pre-programmed movements in this file (no sport skills, no exercises, no poses of
named moves). A movement is described by a language model as an ordered list of BEATS; every beat
chooses, from small fixed menus, a spatial description of each body part:

    hand  = height x direction x reach x elbow     (e.g. chest / across / extended / down)
    foot  = position x height                      (e.g. far_front / knee)
    body  = base (support/orientation) x level x trunk x facing, plus timing

Deterministic code then supplies everything a cheap model cannot: exact coordinates on the measured
rig, reachability, biomechanical inference (hinging/squatting to reach low targets, trunk rotation
when a hand reaches across or winds back, counter-balance for lifted legs, counter-swinging arms,
support and airborne logic), physically plausible timing, and the solver constraints downstream.

The model is the flexible part (it can describe any movement it can reason about); this module is
the rigid part (it can only produce anatomically valid, internally consistent targets).
"""

from __future__ import annotations

import copy
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# -----------------------------------------------------------------------------
# Rig geometry (metres, body frame: origin = pelvis, +x athlete right, +y up, +z forward).
# Must match motion_engine.py (checked by its self-test).
# -----------------------------------------------------------------------------
UNIT_TO_M = 1.75 / 82.0
SHOULDER_X = 14.0 * UNIT_TO_M          # 0.30
SHOULDER_Y = 22.5 * UNIT_TO_M          # 0.48 above the pelvis
ARM_LEN = 31.0 * UNIT_TO_M             # 0.66
LEG_LEN = 33.5 * UNIT_TO_M             # 0.715
FLOOR_Y = -(1.0 + 33.5 + 3.0) * UNIT_TO_M   # sole height below the pelvis when standing (-0.80)
HIP_DROP_SCALE = 0.85

# -----------------------------------------------------------------------------
# Menus (the whole vocabulary the model may use)
# -----------------------------------------------------------------------------
BEAT_TIME = {"instant": 0.16, "quick": 0.3, "normal": 0.5, "slow": 0.9, "hold": 0.7}

# Support base: (right foot, left foot, hip height, body pitch, body roll, feet planted)
# foot = (forward, out, lift, toe_out) in metres/degrees; out = toward that foot's own side.
BASES = {
    "standing": ((0, 0.12, 0, 10), (0, 0.12, 0, 10), 0.0, 0, 0, True),
    "athletic": ((0, 0.24, 0, 12), (0, 0.24, 0, 12), -0.08, 0, 0, True),
    "wide": ((0, 0.38, 0, 20), (0, 0.38, 0, 20), -0.1, 0, 0, True),
    "narrow": ((0, 0.07, 0, 5), (0, 0.07, 0, 5), 0.0, 0, 0, True),
    "split_left_forward": ((-0.25, 0.14, 0, 15), (0.25, 0.12, 0, 10), -0.06, 0, 0, True),
    "split_right_forward": ((0.25, 0.12, 0, 10), (-0.25, 0.14, 0, 15), -0.06, 0, 0, True),
    "kneeling": ((-0.35, 0.12, 0.05, 5), (-0.35, 0.12, 0.05, 5), -0.4, 0, 0, False),
    "half_kneeling_left_forward": ((-0.4, 0.12, 0.08, 5), (0.35, 0.12, 0, 10), -0.42, 0, 0, True),
    "half_kneeling_right_forward": ((0.35, 0.12, 0, 10), (-0.4, 0.12, 0.08, 5), -0.42, 0, 0, True),
    "face_down_horizontal": ((0, 0.1, 0, 5), (0, 0.1, 0, 5), 0.0, 88, 0, False),
    "face_down_on_hands": ((0, 0.12, 0, 5), (0, 0.12, 0, 5), 0.0, 76, 0, False),
    "face_up_horizontal": ((0, 0.1, 0, 5), (0, 0.1, 0, 5), 0.0, -88, 0, False),
    "face_up_on_hands": ((-0.35, 0.16, 0.4, 10), (-0.35, 0.16, 0.4, 10), 0.0, -80, 0, False),
    "seated": ((0.3, 0.14, 0.38, 10), (0.3, 0.14, 0.38, 10), 0.0, -45, 0, False),
    "lying_on_left_side": ((0, 0.2, 0, 5), (0, 0.1, 0, 5), 0.0, 0, -80, False),
    "lying_on_right_side": ((0, 0.1, 0, 5), (0, 0.2, 0, 5), 0.0, 0, 80, False),
    "airborne": ((0, 0.14, 0.05, 10), (0, 0.14, 0.05, 10), 0.3, 0, 0, False),
}
LEVELS = {"keep": None, "tall": 0.02, "normal": None, "slightly_bent": -0.1, "half_squat": -0.22,
          "deep_squat": -0.42}
# trunk: (lean, twist, side_bend) ; twist + = chest turns to the athlete's RIGHT
TRUNKS = {
    "upright": (5, 0, 0), "lean_forward": (25, 0, 0), "hinge": (55, 0, 0), "deep_hinge": (80, 0, 0),
    "lean_back": (-20, 0, 0), "turn_left": (8, -45, 0), "turn_right": (8, 45, 0),
    "full_turn_left": (10, -70, 0), "full_turn_right": (10, 70, 0),
    "side_bend_left": (0, 0, -25), "side_bend_right": (0, 0, 25),
}
FACINGS = {"front": 0, "left_45": -45, "right_45": 45, "left_90": -90, "right_90": 90, "back": 180}

# Hand heights in the body frame (metres above the pelvis; for a horizontal body "overhead" means
# beyond the head, "floor" means on the supporting surface).
HAND_HEIGHTS = {"floor": None, "shin": -0.58, "knee": -0.37, "hip": -0.05, "waist": 0.12, "chest": 0.32,
                "shoulder": 0.48, "chin": 0.64, "head": 0.8, "overhead": 1.08}
HAND_SPECIAL = ["keep", "auto", "at_side"]
# Low targets are things on or near the ground (a cone, a ball, the shins), so they are measured
# from the FLOOR: when the hips drop, these targets get closer to the hands.
LOW_HAND_ABOVE_FLOOR = {"floor": 0.05, "shin": 0.22, "knee": 0.43}


def hand_height(height: str, drop: float) -> float:
    """Body-frame height (metres above the pelvis) of a hand-height word at this hip drop."""
    if height in LOW_HAND_ABOVE_FLOOR:
        return floor_level(drop) + LOW_HAND_ABOVE_FLOOR[height]
    return HAND_HEIGHTS.get(height, 0.32)
# Directions around the chest (degrees from where the chest faces, + toward that hand's own side).
HAND_DIRECTIONS = {"front": 0, "front_out": 45, "side": 90, "back_out": 135, "back": 180,
                   "across": -45, "center": None}
HAND_REACH = {"tucked": 0.3, "bent": 0.46, "extended": 0.63}
ELBOWS = ["auto", "down", "out", "back", "up", "forward"]

# Foot positions in the body frame: (forward, out) metres; out = toward that foot's own side.
FOOT_POSITIONS = {"under_hip": (0.0, 0.12), "front": (0.3, 0.12), "far_front": (0.55, 0.12),
                  "back": (-0.3, 0.12), "far_back": (-0.5, 0.12), "side": (0.0, 0.3), "wide": (0.0, 0.45),
                  "front_side": (0.25, 0.3), "back_side": (-0.25, 0.3), "cross_front": (0.15, -0.08),
                  "cross_back": (-0.15, -0.08)}
FOOT_SPECIAL = ["keep", "base"]
FOOT_HEIGHTS = {"floor": 0.0, "ankle": 0.1, "shin": 0.25, "knee": 0.45, "hip": 0.65, "high": 0.8}
# Leg shape for a raised foot. With a shape, "position" is the DIRECTION the leg points from the
# hip and "height" how high the foot should be; the leg is built from joint angles inside the
# anatomical range, so a straight leg stays straight (a kick can't collapse into a knee lift) and
# a bent leg behind keeps its knee under/behind the hip (never a kneeling pose in mid-air).
LEG_SHAPES = ["straight", "bent", "tucked"]
HIP_OUT = 6.0 * UNIT_TO_M                # hip joint offset from the pelvis centre
FRONT_POSITIONS = ("front", "far_front", "front_side", "cross_front", "side", "wide")
BACK_POSITIONS = ("back", "far_back", "back_side", "cross_back")


# -----------------------------------------------------------------------------
# Small math helpers (same rotation convention as the engine: R = Ry * Rx * Rz)
# -----------------------------------------------------------------------------
def _rx(d: float) -> np.ndarray:
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _ry(d: float) -> np.ndarray:
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rz(d: float) -> np.ndarray:
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def trunk_matrix(lean: float, twist: float, bend: float) -> np.ndarray:
    return _ry(twist) @ _rx(lean) @ _rz(-bend)


HANG_CHEST = (0.05, -0.6, 0.33)  # (forward, up, out) chest frame: arm hanging relaxed
G = 9.81
FLIGHT_MAX_RISE = 0.45           # m, apex of the highest jump the rig shows
STRIDE_MAX_RISE = 0.08           # m, running/bounding strides: flight comes from forward speed


def hang_hand(side: str, lean: float, twist: float, bend: float) -> Tuple[float, float, float]:
    """Chest-frame target for a relaxed arm: it hangs toward the GROUND from the shoulder, so when
    the trunk leans the arm stays vertical instead of being glued to the chest."""
    sgn = 1.0 if side == "right" else -1.0
    R = trunk_matrix(lean, twist, bend)
    sh = R @ np.array([sgn * SHOULDER_X, SHOULDER_Y, 0.0])
    target = sh + np.array([sgn * 0.04, -0.6, 0.05])
    rel = R.T @ (target - R @ np.array([0.0, SHOULDER_Y, 0.0]))
    return float(rel[2]), float(rel[1]), float(sgn * rel[0])


def floor_hand(tilt_deg: float, reach: float = 0.6, out: float = 0.32, toward_head: float = 0.0) -> Tuple[float, float, float]:
    """Chest-frame hand pointing straight down to the supporting surface for a trunk tilted tilt_deg."""
    a = math.radians(tilt_deg)
    return (reach * math.sin(a), -reach * math.cos(a) + toward_head, out)


def floor_level(drop: float) -> float:
    return FLOOR_Y + HIP_DROP_SCALE * max(0.0, -drop)


# -----------------------------------------------------------------------------
# Hand descriptor -> chest-frame target (with reach guarantee)
# -----------------------------------------------------------------------------
def hand_target(desc: Dict[str, str], side: str, lean: float, twist: float, bend: float,
                drop: float) -> Tuple[Tuple[float, float, float], str]:
    """Return ((forward, up, out) chest-frame metres, elbow hint) for one hand descriptor."""
    sgn = 1.0 if side == "right" else -1.0
    R = trunk_matrix(lean, twist, bend)
    sh_mid = R @ np.array([0.0, SHOULDER_Y, 0.0])
    sh = R @ np.array([sgn * SHOULDER_X, SHOULDER_Y, 0.0])
    height = desc.get("height", "chest")
    direction = desc.get("direction", "front")
    reach = HAND_REACH.get(desc.get("reach", "bent"), 0.46)
    y = hand_height(height, drop)
    dy = y - sh[1]
    if abs(dy) >= reach * 0.97:
        dy = math.copysign(reach * 0.97, dy)
    horiz = math.sqrt(max(0.0, reach * reach - dy * dy))
    chest_fwd = np.array([math.sin(math.radians(twist)), 0.0, math.cos(math.radians(twist))])
    if direction == "center":
        # In front of the body's centre line at this distance.
        target = np.array([sh_mid[0], sh[1] + dy, sh_mid[2]]) + chest_fwd * max(0.18, horiz)
    else:
        ang = math.radians(twist + sgn * HAND_DIRECTIONS.get(direction, 0))
        d = np.array([math.sin(ang), 0.0, math.cos(ang)])
        target = np.array([sh[0], sh[1] + dy, sh[2]]) + d * horiz
    rel = R.T @ (target - sh_mid)
    elbow = desc.get("elbow", "auto")
    if elbow == "auto":
        if direction in ("back", "back_out") and height in ("shoulder", "chin", "head", "overhead"):
            elbow = "up"
        elif direction in ("back", "back_out"):
            elbow = "back"
        elif height == "overhead":
            elbow = "out"
        else:
            elbow = "down"
    return (float(rel[2]), float(rel[1]), float(sgn * rel[0])), elbow


def lowest_reachable(lean: float, drop: float, reach: float = 0.63) -> float:
    """Lowest hand height (body frame) reachable with this trunk lean and hip drop."""
    return SHOULDER_Y * math.cos(math.radians(lean)) - reach


def infer_reach_posture(height: str, lean: float, drop: float, can_lower: bool) -> Tuple[float, float]:
    """Hinge first (up to 70 degrees), then bend the knees, until a low target is reachable."""
    best = (lean, drop)
    for extra_drop in [0.0, 0.08, 0.16, 0.24, 0.32, 0.4] if can_lower else [0.0]:
        d = min(drop, -extra_drop) if extra_drop else drop
        for ln in range(int(lean), 91, 5):
            ty = hand_height(height, d)
            if lowest_reachable(ln, d) <= ty + 0.01:
                return float(ln), float(d)
            best = (float(ln), float(d))
            if ln >= 70 and extra_drop < 0.4 and can_lower:
                break
    return best


# -----------------------------------------------------------------------------
# Keyframe helper (engine format)
# -----------------------------------------------------------------------------
def keyframe(t: float, phase: str, *, rh, lh, rf, lf, pel, tor, body, head=(0, 0, 0), plant=("both"),
             grip=False, re="down", le="down") -> Dict[str, Any]:
    names = {"rh": ("right_hand", ("forward", "up", "out")), "lh": ("left_hand", ("forward", "up", "out")),
             "rf": ("right_foot", ("forward", "out", "lift", "toe_out")),
             "lf": ("left_foot", ("forward", "out", "lift", "toe_out")),
             "pel": ("pelvis", ("height", "twist", "tilt", "side")), "tor": ("torso", ("lean", "twist", "side_bend")),
             "head": ("head", ("nod", "turn", "tilt")), "body": ("body", ("pitch", "turn", "roll"))}
    kf: Dict[str, Any] = {"t": float(t), "phase": phase}
    for key, vals in (("rh", rh), ("lh", lh), ("rf", rf), ("lf", lf), ("pel", pel), ("tor", tor), ("head", head),
                      ("body", body)):
        group, fields = names[key]
        kf[group] = {f: float(v) for f, v in zip(fields, vals)}
    kf["left_foot_planted"] = plant in ("both", "left")
    kf["right_foot_planted"] = plant in ("both", "right")
    kf["hands_together"] = bool(grip)
    kf["right_elbow_points"] = re
    kf["left_elbow_points"] = le
    return kf


def _pose_points(kf: Dict[str, Any]) -> List[Tuple[float, ...]]:
    pts = []
    for grp in ("right_hand", "left_hand"):
        h = kf[grp]
        pts.append((h["forward"], h["up"], h["out"]))
    for grp in ("right_foot", "left_foot"):
        f = kf[grp]
        pts.append((f["forward"], f["out"], f["lift"]))
    return pts


def min_transition_time(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Shortest believable time to move from pose a to pose b (seconds)."""
    travel = max(math.dist(p, q) for p, q in zip(_pose_points(a), _pose_points(b)))
    hip = abs(a["pelvis"]["height"] - b["pelvis"]["height"])
    rot = 0.0
    for g, f in (("body", "pitch"), ("body", "turn"), ("body", "roll"), ("torso", "twist"), ("torso", "lean")):
        rot = max(rot, abs(a[g][f] - b[g][f]))
    return max(0.12, travel / 3.5 + 0.06, hip / 1.5 + 0.06, rot / 330.0 + 0.06)


# -----------------------------------------------------------------------------
# Beat -> keyframe (with biomechanical inference)
# -----------------------------------------------------------------------------
def leg_shape(fd: Dict[str, str], pos: str, hgt: str) -> Optional[str]:
    """The leg shape for a raised foot: the model's choice, else inferred from where the foot is."""
    shape = fd.get("leg", "auto")
    if shape in LEG_SHAPES:
        return shape
    if pos in FRONT_POSITIONS:
        return "straight"  # a foot raised in front / to the side = leg swung there
    if pos in BACK_POSITIONS:
        return "straight" if hgt in ("hip", "high") else "bent"  # leg swung back / heel kicked up
    return None  # under the hip etc.: absolute spot (knee drive)


# Anatomical hip ranges (degrees from hanging straight down) used to build raised legs.
HIP_FLEX_MAX = 110.0       # thigh forward
HIP_EXT_MAX = 30.0         # thigh backward (more only by tilting the trunk forward)
HIP_ABD_MAX = 70.0         # thigh out to the side
KNEE_FLEX = {"straight": 5.0, "bent": 90.0, "tucked": 125.0}


def _leg_foot(alpha: float, knee: float) -> Tuple[float, float]:
    """Sagittal (forward, down) foot offset from the hip for a thigh at `alpha` degrees from vertical
    (+ forward) and a knee flexed `knee` degrees (the shin folds backward from the thigh)."""
    a, s = math.radians(alpha), math.radians(alpha - knee)
    t, sh = LEG_LEN * 16.5 / 33.5, LEG_LEN * 17.0 / 33.5
    return t * math.sin(a) + sh * math.sin(s), -(t * math.cos(a) + sh * math.cos(s))


def side_tilt_needed(lift: float, level: float) -> float:
    """Trunk tilt (deg, away from the leg) needed for a STRAIGHT leg raised sideways to this height:
    the hip only abducts ~70 degrees, the rest comes from tilting the trunk/pelvis the other way."""
    hip_h = LEG_LEN + HIP_DROP_SCALE * min(0.0, level)
    radius = LEG_LEN * math.cos(math.radians(KNEE_FLEX["straight"] / 2))
    c = max(-1.0, min(1.0, (hip_h - lift) / radius))
    return max(0.0, min(35.0, math.degrees(math.acos(c)) - HIP_ABD_MAX))


def leg_target(fwd: float, out: float, lift: float, shape: str, level: float,
               lean: float = 5.0, abd_bonus: float = 0.0) -> Tuple[float, float, float, float]:
    """Foot (forward, out, lift) for a raised leg built from joint angles inside the anatomical
    range: `shape` fixes the knee bend, (fwd, out) the direction the leg points, and the thigh
    angle is chosen so the foot is as close as possible to height `lift` above the floor."""
    hip_h = LEG_LEN + HIP_DROP_SCALE * min(0.0, level)  # hip joint above the floor
    knee = KNEE_FLEX[shape]
    v = np.array([fwd, out - HIP_OUT])
    n = float(np.linalg.norm(v))
    v = v / n if n > 0.06 else np.array([1.0, 0.0])
    ext_max = HIP_EXT_MAX + max(0.0, lean - 5.0)  # leaning forward lets the leg go further back
    backward = v[0] < -0.5
    if backward:        # leg pointing back: thigh at or behind vertical (heel up behind / leg swung back)
        lo, hi, sign = (0.0 if shape == "straight" else 15.0), ext_max, -1.0  # "back" = thigh behind the body line
    elif abs(v[1]) > abs(v[0]) and shape == "straight":
        lo, hi, sign = 0.0, HIP_ABD_MAX + abd_bonus, 1.0   # straight leg out to the side
    else:               # forward / under the body: hip flexion (knee drive family for bent legs)
        lo, hi, sign = {"straight": 0.0, "bent": 30.0, "tucked": 45.0}[shape], HIP_FLEX_MAX, 1.0
    best = None
    for i in range(0, 81):
        theta = lo + (hi - lo) * i / 80.0   # thigh angle from vertical toward v (or away, if backward)
        if backward:
            f, d = _leg_foot(-theta, knee)   # thigh back; the shin still folds backward (up behind)
            f = -f                           # distance along v, which points back
        else:
            f, d = _leg_foot(theta, knee)
        foot_h = hip_h + d
        err = abs(foot_h - lift) + 0.0003 * theta  # prefer the smaller hip angle on ties
        if best is None or err < best[0]:
            best = (err, f, foot_h, theta)
    _, horiz, foot_h, theta = best   # horiz: distance along v (negative = behind the hip for a knee drive)
    knee_along = LEG_LEN * 16.5 / 33.5 * math.sin(math.radians(theta))  # knee distance along v
    return (float(v[0] * horiz), float(HIP_OUT + v[1] * horiz), float(max(0.0, foot_h)),
            float(v[0] * knee_along))


def _new_state(base: str = "standing") -> Dict[str, Any]:
    rf, lf, h, pitch, roll, planted = BASES[base]
    return dict(base=base, feet={"right": list(rf), "left": list(lf)}, base_feet={"right": list(rf), "left": list(lf)},
                planted={"right": planted, "left": planted}, base_planted=planted, height=h, pitch=pitch, roll=roll,
                lean=5.0, twist=0.0, bend=0.0, facing=0.0, hands={"right": HANG_CHEST, "left": HANG_CHEST},
                elbows={"right": "down", "left": "down"}, hand_desc={"right": None, "left": None},
                straight_legs=set(), knee_fwd={"right": 0.5 * rf[0], "left": 0.5 * lf[0]})


def _resolve_beat(beat: Dict[str, Any], prev: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """Resolve one beat against the previous state. Returns (keyframe fields, new state, notes)."""
    st = copy.deepcopy(prev)
    notes: List[str] = []
    base = beat.get("base", "keep")
    if base in BASES:
        rf, lf, h, pitch, roll, planted = BASES[base]
        st.update(base=base, height=h, pitch=pitch, roll=roll, base_planted=planted)
        st["base_feet"] = {"right": list(rf), "left": list(lf)}
        st["feet"] = {"right": list(rf), "left": list(lf)}
        st["planted"] = {"right": planted, "left": planted}
        st["knee_fwd"] = {"right": 0.5 * rf[0], "left": 0.5 * lf[0]}
    lv = LEVELS.get(beat.get("level", "keep"))
    if lv is not None and st["pitch"] == 0 and st["roll"] == 0:
        st["height"] = lv
    trunk = beat.get("trunk", "keep")
    trunk_explicit = trunk in TRUNKS
    if trunk_explicit:
        st["lean"], st["twist"], st["bend"] = (float(v) for v in TRUNKS[trunk])
    fac = beat.get("facing", "keep")
    turning = fac in FACINGS and abs(FACINGS[fac] - st["facing"]) > 1
    if fac in FACINGS:
        st["facing"] = float(FACINGS[fac])

    # ---- feet -------------------------------------------------------------------------------
    horizontal = abs(st["pitch"]) > 45 or abs(st["roll"]) > 45
    st["straight_legs"] = {s for s in st.get("straight_legs", set()) if st["feet"][s][2] >= 0.05}
    lifted_front, lifted_back, lifted_side = {}, {}, {}
    side_tilt: Dict[str, float] = {}
    for side in ("right", "left"):
        fd = beat.get(f"{side}_foot") or {}
        pos, hgt = fd.get("position", "keep"), fd.get("height", "floor")
        if pos == "keep" and hgt == "floor":
            continue
        if pos == "base":
            fwd, out = st["base_feet"][side][0], st["base_feet"][side][1]
        elif pos in FOOT_POSITIONS:
            fwd, out = FOOT_POSITIONS[pos]
        else:
            fwd, out = st["feet"][side][0], st["feet"][side][1]
        lift = FOOT_HEIGHTS.get(hgt, 0.0)
        toe = 20 if pos in ("side", "wide", "front_side", "back_side") else 0 if pos.startswith("cross") else 10
        # Joint-angle construction works in the body's own frame, so it is equally valid for a
        # swimmer or a plank (hip flexion = thigh toward the body's front, heels fold toward its back).
        shape = leg_shape(fd, pos, hgt) if lift >= 0.05 else None
        if shape is not None:
            level = 0.0 if horizontal or st["base"] == "airborne" else st["height"]
            v_out = out - HIP_OUT
            tilt = side_tilt_needed(lift, level) if (shape == "straight" and not horizontal
                                                     and abs(v_out) > abs(fwd) and v_out > 0) else 0.0
            if tilt > 0:
                side_tilt[side] = tilt
            fwd, out, lift, knee_fwd = leg_target(fwd, out, lift, shape, level, 5.0 if horizontal else st["lean"],
                                                  abd_bonus=tilt)
            if shape == "straight":
                st["straight_legs"].add(side)
        else:
            knee_fwd = 0.5 * fwd
            st["straight_legs"].discard(side)
        st["feet"][side] = [fwd, out, lift, toe]
        st["knee_fwd"][side] = knee_fwd
        st["planted"][side] = (lift < 0.02) and not horizontal and st["base"] != "airborne"
        if lift >= 0.25 or (shape in ("bent", "tucked") and lift >= 0.15):
            # Classify by where the THIGH points (a knee drive's foot is under the hip, its knee in front).
            (lifted_front if knee_fwd > 0.12 or fwd > 0.15 else lifted_back if fwd < -0.15
             else lifted_side if out > 0.25 else {})[side] = lift
    airborne = st["base"] == "airborne" or not (st["planted"]["right"] or st["planted"]["left"])
    drop = st["height"]
    if airborne and not horizontal and st["base"] != "airborne":
        drop = max(drop, 0.12)  # both feet up while upright = a hop/jump (not carried to the next beat)
        notes.append("both feet off the floor: treated as airborne")
    if turning and not horizontal:
        st["planted"] = {"right": False, "left": False}  # feet pivot through a facing change

    lean, twist, bend = st["lean"], st["twist"], st["bend"]
    # Counter-balance (only when the trunk was not specified explicitly).
    if not trunk_explicit and not horizontal:
        if lifted_front:
            lean = min(lean, 5.0 - 6.0 * max(lifted_front.values()) / 0.45)
        if lifted_back and not lifted_front:
            lean = max(lean, 5.0 + 20.0 * max(lifted_back.values()) / 0.45)
        for side in lifted_side:
            if side not in side_tilt:
                bend += (-1 if side == "right" else 1) * 10.0
    for side, tilt in side_tilt.items():   # a high side leg needs the trunk tilted away (any trunk)
        bend += (-1 if side == "right" else 1) * tilt
        notes.append(f"{side} leg raised high to the side: trunk tilted {tilt:.0f} deg away")
    # Deeper knee bend keeps the chest over the feet.
    if not horizontal and trunk != "lean_back":
        lean = max(lean, 75.0 * max(0.0, -drop - 0.05))

    # ---- hands ------------------------------------------------------------------------------
    descs = {s: (beat.get(f"{s}_hand") or {}) for s in ("right", "left")}
    # Trunk rotation implied by the arms (reaching across rotates the chest toward the target;
    # winding a hand back high rotates it away) - only when the trunk wasn't specified.
    if not trunk_explicit and not horizontal:
        implied = []
        for side, d in descs.items():
            h = d.get("height", "auto")
            if h in HAND_SPECIAL or h == "floor":
                continue
            sgn = 1.0 if side == "right" else -1.0
            if d.get("direction") in ("across", "center") and d.get("reach") == "extended":
                implied.append(-sgn * 28.0)
            elif d.get("direction") in ("back", "back_out") and h in ("shoulder", "chin", "head", "overhead"):
                implied.append(sgn * 40.0)
        if len(implied) == 1:
            twist = implied[0]
    # Reach inference: hinge, then squat, until every low target is reachable.
    for side, d in descs.items():
        h = d.get("height", "auto")
        if h in ("floor", "shin", "knee") and not horizontal:
            new_lean, new_drop = infer_reach_posture(h, lean, drop, can_lower=not airborne)
            if new_lean > lean + 1 or new_drop < drop - 0.01:
                notes.append(f"{side} hand to {h}: trunk hinged to {new_lean:.0f} deg, hips {new_drop:+.2f} m")
            lean, drop = max(lean, new_lean), min(drop, new_drop)
    hands, elbows = {}, {}
    tilt = st["pitch"] + lean
    for side, d in descs.items():
        h = d.get("height", "auto")
        if h == "keep":
            hands[side], elbows[side] = st["hands"][side], st["elbows"][side]
        elif h == "at_side":
            hands[side] = HANG_CHEST if horizontal else hang_hand(side, lean, twist, bend)
            elbows[side] = "down"
        elif h == "floor" and horizontal and st["pitch"] > 45:
            hands[side], elbows[side] = floor_hand(tilt), "down"
        elif h == "auto":
            continue
        else:
            hands[side], elbows[side] = hand_target(d, side, lean, twist, bend, drop)
            if d.get("elbow", "auto") != "auto":
                elbows[side] = d["elbow"]
    # Automatic arms: support on the floor, counter-swing against the legs, balance, ready hands.
    for side, other in (("right", "left"), ("left", "right")):
        if side in hands:
            continue
        if st["pitch"] > 45:
            hands[side], elbows[side] = floor_hand(tilt), "down"
        elif st["pitch"] < -45:
            hands[side], elbows[side] = (-0.55, -0.05, 0.3), "down"
        elif abs(st["roll"]) > 45:
            hands[side], elbows[side] = hand_target({"height": "overhead", "direction": "front", "reach": "extended"},
                                                    side, lean, twist, bend, drop)
        elif other in st["straight_legs"] and not st["planted"][other] and st["planted"][side]:
            # Standing on this side's leg while the other leg swings straight (kicks, leg swings):
            # this arm is the balance arm, held out wide and slightly forward.
            hands[side], elbows[side] = hand_target({"height": "chest", "direction": "front_out", "reach": "extended"},
                                                    side, lean, twist, bend, drop)
            elbows[side] = "down"
        elif side in st["straight_legs"] and not st["planted"][side] and st["planted"][other]:
            # Arm on the swinging leg's side: low counter-swing, opposite to the leg.
            leg_fwd = st["feet"][side][0]
            desc = ({"height": "hip", "direction": "back", "reach": "extended"} if leg_fwd > 0.1 else
                    {"height": "waist", "direction": "front", "reach": "bent"})
            hands[side], elbows[side] = hand_target(desc, side, lean, twist, bend, drop)
            elbows[side] = "down"
        elif not horizontal and any(st["feet"][s_][2] >= 0.2 for s_ in ("right", "left")) \
                and abs(st["knee_fwd"][side] - st["knee_fwd"][other]) > 0.15:
            # Gait synergy: in stepping, running and skipping (a foot really off the ground, not a
            # heel pivot) the arm swings opposite to its own side's thigh, in the sagittal plane.
            if st["knee_fwd"][side] > st["knee_fwd"][other]:
                hands[side] = hand_target({"height": "hip", "direction": "back", "reach": "extended"},
                                          side, lean, twist, bend, drop)[0]
            else:
                hands[side] = hand_target({"height": "chest", "direction": "front", "reach": "bent"},
                                          side, lean, twist, bend, drop)[0]
            elbows[side] = "down"
        elif other in lifted_front or side in lifted_back:
            # Counter-swing forward in the sagittal plane (arms swing along the body, never flared out).
            hands[side], elbows[side] = hand_target({"height": "chest", "direction": "front", "reach": "bent"},
                                                    side, lean, twist, bend, drop)
            elbows[side] = "down"
        elif side in lifted_front or other in lifted_back:
            # Natural counter-swing back: a nearly straight arm (a 90-degree elbow reads as akimbo).
            hands[side], elbows[side] = hand_target({"height": "hip", "direction": "back", "reach": "extended"},
                                                    side, lean, twist, bend, drop)
            elbows[side] = "down"
        elif lifted_side:
            hands[side], elbows[side] = hand_target({"height": "shoulder", "direction": "side", "reach": "extended"},
                                                    side, lean, twist, bend, drop)
        elif st["base"] in ("athletic", "wide", "split_left_forward", "split_right_forward") or drop < -0.15:
            hands[side], elbows[side] = hand_target({"height": "waist", "direction": "front", "reach": "bent"},
                                                    side, lean, twist, bend, drop)
        elif any(st["feet"][s_][2] >= 0.05 for s_ in ("right", "left")) or airborne:
            hands[side], elbows[side] = st["hands"][side], st["elbows"][side]  # mid-action: carry on
        else:
            # Both feet down and nothing for this arm to do: it relaxes (an automatic arm never
            # freezes in the balance/counter-swing pose of an earlier phase).
            hands[side] = HANG_CHEST if horizontal else hang_hand(side, lean, twist, bend)
            elbows[side] = "down"
    if beat.get("hands_together") and not horizontal:
        # Two hands on one implement: the grip cannot pass behind the chest plane (both arms would
        # have to reach behind the back); the trunk rotation carries it around the side instead.
        # Both elbows point down along the shaft unless the grip is overhead.
        for side in ("right", "left"):
            f_, u_, o_ = hands[side]
            if f_ < GRIP_MIN_FORWARD:
                hands[side] = (GRIP_MIN_FORWARD, u_, o_)
                if side == "right":
                    notes.append("two-hand grip kept in front of the chest (moved round to the side)")
            if u_ < 0.55:
                elbows[side] = "down"
    st.update(hands=hands, elbows=elbows)
    if horizontal:
        lean = max(-15.0, min(15.0, lean))
    plant = ("both" if st["planted"]["right"] and st["planted"]["left"] else "right" if st["planted"]["right"]
             else "left" if st["planted"]["left"] else "none")
    fields = dict(rh=hands["right"], lh=hands["left"], rf=st["feet"]["right"], lf=st["feet"]["left"],
                  pel=(drop, 0.45 * twist, 6 if lean > 20 else 2, 0), tor=(lean, twist, bend),
                  body=(st["pitch"], st["facing"], st["roll"]),
                  head=(15 if st["pitch"] > 45 else -20 if st["pitch"] < -45 else 0, 0, 0),
                  plant=plant, grip=bool(beat.get("hands_together")), re=elbows["right"], le=elbows["left"])
    return fields, st, notes


BALLISTIC_MAX_TURN = 20.0  # degrees a fast-swinging foot can redirect during its follow-through


def _ballistic_follow_through(before: Dict[str, Any], contact: Dict[str, Any], kf: Dict[str, Any],
                              state: Dict[str, Any]) -> List[str]:
    """After an explosive beat, a foot that was swinging fast stays in its swing plane: the
    follow-through may continue, rise, slow down or swing back, but its sideways drift out of the
    plane is limited to BALLISTIC_MAX_TURN degrees (a limb at peak speed cannot redirect)."""
    notes = []
    for side in ("right", "left"):
        g = f"{side}_foot"
        a, c, f = before[g], contact[g], kf[g]
        if f["lift"] < 0.05 or c["lift"] < 0.03:
            continue
        d = np.array([c["forward"] - a["forward"], c["out"] - a["out"]])
        e = np.array([f["forward"] - c["forward"], f["out"] - c["out"]])
        nd, ne = float(np.linalg.norm(d)), float(np.linalg.norm(e))
        if nd < 0.25 or ne < 0.04:
            continue
        u = d / nd                                   # swing direction (horizontal)
        par = float(e @ u)
        perp = float(e[1] * u[0] - e[0] * u[1])      # sideways component, out of the swing plane
        limit = max(0.05, math.tan(math.radians(BALLISTIC_MAX_TURN)) * abs(par))
        if abs(perp) <= limit:
            continue
        perp_new = math.copysign(limit, perp)
        ang = math.degrees(math.atan2(perp, par))
        e_new = u * par + np.array([-u[1], u[0]]) * perp_new
        f["forward"] = c["forward"] + float(e_new[0])
        f["out"] = c["out"] + float(e_new[1])
        state["feet"][side][0], state["feet"][side][1] = f["forward"], f["out"]
        notes.append(f"{side} foot follow-through kept within {BALLISTIC_MAX_TURN:.0f} deg of its swing (was {ang:.0f})")
    return notes


GRIP_MIN_FORWARD = 0.12   # m in front of the chest for a two-handed grip
STEP_MIN = 0.08   # m: a planted foot asked to move further than this has to STEP there
# The model's own beat label says whether a stance change is footwork. Without such a word, planted
# feet stay locked (a golfer or a pitcher does not step just because a foot position was nudged).
FOOTWORK_WORDS = ("step", "shuffle", "stride", "walk", "jog", "lunge", "plant", "approach", "skip", "slide",
                  "stance", "spread", "widen", "split", "cross over", "crossover", "drop step", "back pedal",
                  "backpedal", "carioca", "gather")


def _blend_keys(a: Dict[str, Any], b: Dict[str, Any], u: float) -> Dict[str, Any]:
    k = copy.deepcopy(b)
    for g, vals in b.items():
        if isinstance(vals, dict) and isinstance(a.get(g), dict):
            for f, v in vals.items():
                if isinstance(v, (int, float)) and isinstance(a[g].get(f), (int, float)):
                    k[g][f] = a[g][f] + (v - a[g][f]) * u
    return k


def _insert_steps(keys_abs: List[Tuple[float, Dict[str, Any]]], loop: bool, cycle: float) -> List[str]:
    """Feet relocate only by stepping: when a foot is planted at both ends of a transition but asked
    to stand somewhere else, the engine lifts it, carries it there and re-plants it. Two moving feet
    step one after the other (largest move first), so stance changes look like real footwork."""
    notes: List[str] = []
    n = len(keys_abs)
    pairs = [(i - 1, i) for i in range(1, n)] + ([(n - 1, 0)] if loop and n > 1 else [])
    inserts: List[Tuple[float, Dict[str, Any]]] = []
    for ia, ib in pairs:
        (ta, a), (tb, b) = keys_abs[ia], keys_abs[ib]
        if ib == 0:
            tb = cycle
        if any(abs(k["body"]["pitch"]) > 45 or abs(k["body"]["roll"]) > 45 for k in (a, b)):
            continue
        label = str(b.get("phase", "")).lower().replace("_", " ").replace("-", " ")
        if not any(w in label for w in FOOTWORK_WORDS):
            continue
        movers = []
        for side in ("right", "left"):
            g = f"{side}_foot"
            if a[f"{side}_foot_planted"] and b[f"{side}_foot_planted"]:
                d = math.hypot(b[g]["forward"] - a[g]["forward"], b[g]["out"] - a[g]["out"])
                if d > STEP_MIN:
                    movers.append((d, side))
        if not movers:
            continue
        movers.sort(reverse=True)
        m = len(movers)
        for j, (d, side) in enumerate(movers):
            u = (j + 0.5) / m
            k = _blend_keys(a, b, u)
            for jj, (_, other) in enumerate(movers):   # feet not yet stepped stay put; stepped ones arrived
                if jj != j:
                    src = b if jj < j else a
                    k[f"{other}_foot"] = copy.deepcopy(src[f"{other}_foot"])
                    k[f"{other}_foot_planted"] = True
            g = f"{side}_foot"
            k[g]["forward"] = 0.5 * (a[g]["forward"] + b[g]["forward"])
            k[g]["out"] = 0.5 * (a[g]["out"] + b[g]["out"])
            k[g]["lift"] = 0.06 + 0.12 * min(1.0, d / 0.5)
            k[f"{side}_foot_planted"] = False
            k["phase"] = f"{b['phase']} ({side} step)"
            inserts.append((ta + (tb - ta) * u, k))
        notes.append(f"'{b['phase']}': {' then '.join(sd for _, sd in movers)} foot step{'s' if m > 1 else ''} to the new stance")
    if inserts:
        keys_abs.extend(inserts)
        keys_abs.sort(key=lambda tk: tk[0])
    return notes


def _airborne(k: Dict[str, Any]) -> bool:
    # Both feet unplanted AND off the floor (feet released to pivot through a turn are not a flight).
    return (not k["left_foot_planted"] and not k["right_foot_planted"]
            and k["left_foot"]["lift"] >= 0.02 and k["right_foot"]["lift"] >= 0.02
            and abs(k["body"]["pitch"]) < 45 and abs(k["body"]["roll"]) < 45)


def _ballistic_flight(keys_abs: List[Tuple[float, Dict[str, Any]]], loop: bool, cycle: float) -> List[str]:
    """Rise of the body during a flight follows from how long it is in the air (h = g*T^2/8, a
    parabola peaking mid-flight), so a brief running flight barely rises and a long jump rises a lot."""
    notes = []
    n = len(keys_abs)
    flags = [_airborne(k) for _, k in keys_abs]
    if not any(flags) or all(flags):
        return notes
    i = 0
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and flags[j + 1]:
            j += 1
        # Lift-off half-way into the transition before the first airborne key, touchdown half-way
        # into the one after the last (matches how the solver switches foot contacts).
        if i > 0:
            t_off = 0.5 * (keys_abs[i - 1][0] + keys_abs[i][0])
        elif loop:
            t_off = 0.5 * (keys_abs[-1][0] - cycle + keys_abs[0][0])
        else:
            t_off = keys_abs[0][0]
        if j + 1 < n:
            t_on = 0.5 * (keys_abs[j][0] + keys_abs[j + 1][0])
        elif loop:
            t_on = 0.5 * (keys_abs[j][0] + keys_abs[0][0] + cycle)
        else:
            t_on = keys_abs[j][0]
        T = max(0.05, t_on - t_off)
        h = min(FLIGHT_MAX_RISE, G * T * T / 8.0)
        stride = loop and any(abs(keys_abs[m][1]["right_foot"]["forward"] - keys_abs[m][1]["left_foot"]["forward"]) > 0.3
                              for m in range(i, j + 1))
        if stride:
            h = min(h, STRIDE_MAX_RISE)  # legs split front/back in a repeating cycle = a running stride
        mid = 0.5 * (t_off + t_on)
        for m in range(i, j + 1):
            t, k = keys_abs[m]
            u = (t - mid) / (0.5 * T)
            k["pelvis"]["height"] = max(0.01, h * (1.0 - u * u))
        notes.append(f"flight of {T:.2f} s: body rises {h * 100:.0f} cm (ballistic)")
        i = j + 1
    return notes


STEADY_TRUNK_RANGE = 10.0  # deg: trunk lean swing allowed around its mean in rhythmic locomotion


def _steady_trunk(keys_abs: List[Tuple[float, Dict[str, Any]]]) -> List[str]:
    """In a rhythmic cycle that keeps the hips at one height (running, skipping, high knees,
    shuffles) the trunk is held steady: lean oscillation is limited around the cycle's mean."""
    ks = [k for _, k in keys_abs]
    if any(abs(k["body"]["pitch"]) > 30 or abs(k["body"]["roll"]) > 30 for k in ks):
        return []
    grounded = [k["pelvis"]["height"] for k in ks if not _airborne(k)]
    if not grounded or max(grounded) - min(grounded) > 0.12:
        return []  # hips go up and down a lot (squats, burpees): trunk lean follows the hips
    leans = [k["torso"]["lean"] for k in ks]
    mean = sum(leans) / len(leans)
    if max(abs(x - mean) for x in leans) <= STEADY_TRUNK_RANGE:
        return []
    for k in ks:
        k["torso"]["lean"] = mean + max(-STEADY_TRUNK_RANGE, min(STEADY_TRUNK_RANGE, k["torso"]["lean"] - mean))
    return [f"rhythmic cycle: trunk lean held within {STEADY_TRUNK_RANGE:.0f} deg of {mean:.0f} deg"]


def build_beats(beats: List[Dict[str, Any]], loop: bool, speed: float = 1.0) -> Dict[str, Any]:
    """Turn a beat list into engine keyframes. Returns keys, duration, loop, notes."""
    first_base = next((b.get("base") for b in beats if b.get("base") in BASES), "standing")
    state = _new_state(first_base)
    fields, state, _ = _resolve_beat({"base": first_base}, state)
    keys_abs: List[Tuple[float, Dict[str, Any]]] = [(0.0, keyframe(0.0, "start", **fields))]
    notes: List[str] = []
    clock = 0.0
    for i, beat in enumerate(beats[:24]):
        label = str(beat.get("label", f"beat {i + 1}"))[:48]
        if beat.get("timing") == "hold":
            fields_h, state_h, _ = _resolve_beat(beat, state)
            kf_h = keyframe(0.0, label, **fields_h)
            if max(math.dist(p, q) for p, q in zip(_pose_points(keys_abs[-1][1]), _pose_points(kf_h))) < 0.03 and \
                    abs(kf_h["torso"]["lean"] - keys_abs[-1][1]["torso"]["lean"]) < 3 and \
                    abs(kf_h["torso"]["twist"] - keys_abs[-1][1]["torso"]["twist"]) < 3:
                last = copy.deepcopy(keys_abs[-1][1])  # a true pause in the previous pose
                last["phase"] = label
                clock += BEAT_TIME["hold"] / max(0.6, speed)
                keys_abs.append((clock, last))
                continue
            # "hold" on a beat that changes the pose: move there calmly, then pause in it.
            state = state_h
            dt = max(BEAT_TIME["slow"] / max(0.6, speed), min_transition_time(keys_abs[-1][1], kf_h))
            clock += dt
            keys_abs.append((clock, kf_h))
            pause = copy.deepcopy(kf_h)
            pause["phase"] = label + " (hold)"
            clock += BEAT_TIME["hold"] / max(0.6, speed)
            keys_abs.append((clock, pause))
            continue
        fields, state, n = _resolve_beat(beat, state)
        kf = keyframe(0.0, label, **fields)
        if i > 0 and beats[i - 1].get("timing") == "instant" and len(keys_abs) >= 2:
            n = n + _ballistic_follow_through(keys_abs[-2][1], keys_abs[-1][1], kf, state)
        notes += [f"beat {i + 1} ({label}): {x}" for x in n]
        dt = BEAT_TIME.get(beat.get("timing", "normal"), 0.5) / max(0.6, speed)
        dt = max(dt, min_transition_time(keys_abs[-1][1], kf))
        clock += dt
        keys_abs.append((clock, kf))
    if loop and len(keys_abs) > 2:
        keys_abs = keys_abs[1:]
        t0 = keys_abs[0][0]
        keys_abs = [(t - t0, k) for t, k in keys_abs]
        clock = keys_abs[-1][0] + max(0.3, min_transition_time(keys_abs[-1][1], keys_abs[0][1]))
    else:
        loop = False
        end = copy.deepcopy(keys_abs[-1][1])
        end["phase"] = "finish (hold)"
        clock += 0.45
        keys_abs.append((clock, end))
    notes += _insert_steps(keys_abs, loop, clock)
    notes += _ballistic_flight(keys_abs, loop, clock)
    if loop:
        notes += _steady_trunk(keys_abs)
    total = max(clock, 0.5)
    keys = []
    for t_abs, k in keys_abs:
        k["t"] = t_abs / total
        keys.append(k)
    return {"keys": keys, "duration": total, "loop": loop, "notes": notes}
