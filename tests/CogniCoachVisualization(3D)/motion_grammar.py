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
from typing import Any, Dict, List, Tuple

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
    y = floor_level(drop) + 0.05 if height == "floor" else HAND_HEIGHTS.get(height, 0.32)
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


def infer_reach_posture(target_y: float, lean: float, drop: float, can_lower: bool) -> Tuple[float, float]:
    """Hinge first (up to 70 degrees), then bend the knees, until a low target is reachable."""
    best = (lean, drop)
    for extra_drop in [0.0, 0.08, 0.16, 0.24, 0.32, 0.4] if can_lower else [0.0]:
        d = min(drop, -extra_drop) if extra_drop else drop
        for ln in range(int(lean), 91, 5):
            ty = target_y if target_y is not None else floor_level(d) + 0.05
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
def _new_state(base: str = "standing") -> Dict[str, Any]:
    rf, lf, h, pitch, roll, planted = BASES[base]
    return dict(base=base, feet={"right": list(rf), "left": list(lf)}, base_feet={"right": list(rf), "left": list(lf)},
                planted={"right": planted, "left": planted}, base_planted=planted, height=h, pitch=pitch, roll=roll,
                lean=5.0, twist=0.0, bend=0.0, facing=0.0, hands={"right": HANG_CHEST, "left": HANG_CHEST},
                elbows={"right": "down", "left": "down"}, hand_desc={"right": None, "left": None})


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
    lifted_front, lifted_back, lifted_side = {}, {}, {}
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
        st["feet"][side] = [fwd, out, lift, toe]
        st["planted"][side] = (lift < 0.02) and not horizontal and st["base"] != "airborne"
        if lift >= 0.25:
            (lifted_front if fwd > 0.15 else lifted_back if fwd < -0.15 else lifted_side if out > 0.25 else {})[side] = lift
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
            bend += (-1 if side == "right" else 1) * 10.0
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
            ty = None if h == "floor" else HAND_HEIGHTS[h]
            new_lean, new_drop = infer_reach_posture(ty, lean, drop, can_lower=not airborne)
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
            hands[side], elbows[side] = HANG_CHEST, "down"
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
        elif other in lifted_front or side in lifted_back:
            hands[side], elbows[side] = hand_target({"height": "chest", "direction": "front_out", "reach": "bent"},
                                                    side, lean, twist, bend, drop)
        elif side in lifted_front or other in lifted_back:
            hands[side], elbows[side] = hand_target({"height": "hip", "direction": "back_out", "reach": "bent"},
                                                    side, lean, twist, bend, drop)
            elbows[side] = "back"
        elif lifted_side:
            hands[side], elbows[side] = hand_target({"height": "shoulder", "direction": "side", "reach": "extended"},
                                                    side, lean, twist, bend, drop)
        elif st["base"] in ("athletic", "wide", "split_left_forward", "split_right_forward") or drop < -0.15:
            hands[side], elbows[side] = hand_target({"height": "waist", "direction": "front", "reach": "bent"},
                                                    side, lean, twist, bend, drop)
        else:
            hands[side], elbows[side] = st["hands"][side], st["elbows"][side]
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
            last = copy.deepcopy(keys_abs[-1][1])
            last["phase"] = label
            clock += BEAT_TIME["hold"] / max(0.6, speed)
            keys_abs.append((clock, last))
            continue
        fields, state, n = _resolve_beat(beat, state)
        notes += [f"beat {i + 1} ({label}): {x}" for x in n]
        kf = keyframe(0.0, label, **fields)
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
    total = max(clock, 0.5)
    keys = []
    for t_abs, k in keys_abs:
        k["t"] = t_abs / total
        keys.append(k)
    return {"keys": keys, "duration": total, "loop": loop, "notes": notes}
