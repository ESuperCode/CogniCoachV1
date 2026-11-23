"""
CogniCoach MOTION DATABASE
==========================

Every athletic motion the animation language (motion_script.py) can use. Each entry has:

    name        what scripts call it, e.g.  stance(width=wide) + forehand
    comment     one-line description (also shown to the language model)
    kind        action (one-shot), cycle (repeats seamlessly), pose (held position)
    parts       body parts the motion DRIVES (hard): body, pelvis, spine, neck, right_arm, left_arm,
                right_leg, left_leg.  Only what the skill needs: a soccer kick drives the legs and
                hips, a forehand drives the arms and trunk.
    soft        parts the motion OFFERS but gives up if another motion on the same line drives them
                (a kick's balance arms, a stance's trunk lean)
    params      motion-specific options (stance width/depth/stagger, run pace, jump height ...)
    keys        the motion itself: keyframes [(seconds, {part: anatomical angles})]. Frame count =
                duration x 30 fps. Angles are anatomical and parent-relative:

        arm  raise  0 = hanging, 90 = horizontal, 180 = straight up
             dir    direction of the raise: 0 front, 90 out to its own side, 180 back, <0 across
             twist  which way the forearm folds: 0 forward/up, - inward (toward the chin), + outward
             elbow  elbow bend (0 = straight)
        leg  raise / dir / twist (relative to the body, not the hips) + knee bend; twist + = toes out
        spine lean (+ forward), twist (+ chest turns to the athlete's RIGHT), side (+ bend right)
        pelvis tilt, twist (+ hips turn right), side;  neck nod (+ chin down), turn, tilt
        body pitch (+ face down), turn, roll; root (metres up) and air (1 = in the air, no floor
             contact; 0 = the lowest contact point is kept on the floor automatically)

All motions are authored for a RIGHT-handed / right-footed athlete; side=left mirrors them.
Helper functions at the top turn foot/hand positions into these angles at build time (solved once,
never at playback, so playback cannot jitter).
"""

from __future__ import annotations

import functools
import math
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

import motion_engine as me

U = me.UNIT_TO_M
HIP_OUT = me.HIP_OFFSET[0] * U          # 0.128 m
LEG_DROP0 = (me.THIGH + me.SHIN) * U    # hip joint -> ankle, standing (0.715 m)

DB: Dict[str, Dict[str, Any]] = {}

# Every solved foot/hand placement is stored here (committed with the repo), so building motions
# never runs a solver at request time. Rebuild with:  python motion_database.py --bake
import json as _json
import os as _os
_SOLVED_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "motion_database_solved.json")
try:
    with open(_SOLVED_PATH) as _f:
        _SOLVED: Dict[str, List[float]] = _json.load(_f)
except (OSError, ValueError):
    _SOLVED = {}
_SOLVED_DIRTY = [False]


def save_solved() -> None:
    if _SOLVED_DIRTY[0]:
        with open(_SOLVED_PATH, "w") as f:
            _json.dump(_SOLVED, f, separators=(",", ":"), sort_keys=True)
        _SOLVED_DIRTY[0] = False


def _solved_key(kind: str, *args: Any) -> str:
    return kind + "|" + "|".join(f"{a:.3f}" if isinstance(a, float) else str(a) for a in args)


# =============================================================================
# Authoring helpers
# =============================================================================
def A(r: float, d: float = 0.0, tw: float = 0.0, el: float = 10.0) -> Dict[str, float]:
    """Arm: raise, direction, twist, elbow bend."""
    return {"raise": r, "dir": d, "twist": tw, "elbow": el}


def Lg(r: float, d: float = 0.0, tw: float = 8.0, kn: float = 4.0) -> Dict[str, float]:
    """Leg: raise, direction, twist (toe-out), knee bend."""
    return {"raise": r, "dir": d, "twist": tw, "knee": kn}


def S(lean: float = 3.0, twist: float = 0.0, side: float = 0.0) -> Dict[str, float]:
    return {"lean": lean, "twist": twist, "side": side}


def P(tilt: float = 0.0, twist: float = 0.0, side: float = 0.0) -> Dict[str, float]:
    return {"tilt": tilt, "twist": twist, "side": side}


def N(nod: float = 0.0, turn: float = 0.0, tilt: float = 0.0) -> Dict[str, float]:
    return {"nod": nod, "turn": turn, "tilt": tilt}


def B(pitch: float = 0.0, turn: float = 0.0, roll: float = 0.0, root: float = 0.0, air: float = 0.0) -> Dict[str, float]:
    return {"pitch": pitch, "turn": turn, "roll": roll, "root": root, "air": air}


def k(t: float, hold: bool = False, **parts: Dict[str, float]) -> Tuple[float, Dict[str, Dict[str, float]]]:
    """A keyframe at time t (seconds). Each part moves smoothly between the keys that mention it;
    hold=True pins EVERY part where it is at time t (a pause)."""
    if hold:
        parts = dict(parts, _hold=True)
    return (t, parts)


def kk(t: float, *presets: Dict[str, Dict[str, float]], hold: bool = False, **parts: Dict[str, float]):
    """Keyframe from preset dicts merged left to right, then explicit parts (later ones win) - use
    when a preset (e.g. a running pose) and explicit parts mention the same body part."""
    merged: Dict[str, Dict[str, float]] = {}
    for pr in presets:
        merged.update(pr)
    merged.update(parts)
    return k(t, hold=hold, **merged)


def grip_keys(points: List[Tuple[float, float, float, float, str]], step: float = 0.06) -> List[Tuple[float, Dict]]:
    """Two hands on one implement (club, bat, racket, ball): the shared grip follows a smooth path
    through (t, x, y, z, elbow) points and BOTH arms are solved for it every `step` seconds, so the
    hands stay together the whole way (independent arm interpolation would let them drift apart)."""
    ts = np.array([p[0] for p in points])
    xyz = np.array([p[1:4] for p in points])
    m = [me.pchip_slopes(ts, xyz[:, c]) for c in range(3)]
    out = []
    prev = None
    samples = sorted(set([round(float(x), 3) for x in np.arange(ts[0], ts[-1], step)] + [float(x) for x in ts]))
    for t in samples:
        x, y, z = (round(float(me.hermite(ts, xyz[:, c], m[c], np.array([t]))[0]), 3) for c in range(3))
        i = int(np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(ts) - 1))
        j = min(i + 1, len(ts) - 1)
        el = points[i][4] if i == j or (t - ts[i]) < (ts[j] - t) else points[j][4]
        r = arm_at(x, y, z, el, "right", seed=prev[0] if prev else None)
        lft = arm_at(-x, y, z, el, "left", seed=prev[1] if prev else None)
        prev = (r, lft)
        out.append(k(t, right_arm=r, left_arm=lft))
    return out


def _nelder_mead(f: Callable[[np.ndarray], float], x0: np.ndarray, step: float = 15.0, iters: int = 160) -> np.ndarray:
    n = len(x0)
    pts = [x0] + [x0 + np.eye(n)[i] * step for i in range(n)]
    vals = [f(p) for p in pts]
    for _ in range(iters):
        order = np.argsort(vals)
        pts, vals = [pts[i] for i in order], [vals[i] for i in order]
        c = np.mean(pts[:-1], axis=0)
        xr = c + (c - pts[-1])
        fr = f(xr)
        if fr < vals[0]:
            xe = c + 2 * (c - pts[-1])
            fe = f(xe)
            pts[-1], vals[-1] = (xe, fe) if fe < fr else (xr, fr)
        elif fr < vals[-2]:
            pts[-1], vals[-1] = xr, fr
        else:
            xc = c + 0.5 * (pts[-1] - c)
            fc = f(xc)
            if fc < vals[-1]:
                pts[-1], vals[-1] = xc, fc
            else:
                pts = [pts[0]] + [pts[0] + 0.5 * (p - pts[0]) for p in pts[1:]]
                vals = [vals[0]] + [f(p) for p in pts[1:]]
    return pts[int(np.argmin(vals))]


def _leg_fk(r: float, d: float, tw: float, kn: float, sign: float) -> Tuple[np.ndarray, np.ndarray]:
    hip = me.limb_local_rotation(r, d, tw, sign)
    knee_p = hip @ np.array([0.0, -me.THIGH, 0.0])
    foot_p = knee_p + hip @ me.rx(kn) @ np.array([0.0, -me.SHIN, 0.0])
    return knee_p * U, foot_p * U


def leg_at(fwd: float, out: float, drop: float = 0.0, lift: float = 0.0, toe: float = 8.0,
           side: str = "right") -> Dict[str, float]:
    key = _solved_key("leg", float(fwd), float(out), float(drop), float(lift), float(toe), side)
    if key not in _SOLVED:
        r = _leg_solve(float(fwd), float(out), float(drop), float(lift), float(toe), side)
        _SOLVED[key] = [r["raise"], r["dir"], r["twist"], r["knee"]]
        _SOLVED_DIRTY[0] = True
    v = _SOLVED[key]
    return Lg(v[0], v[1], v[2], v[3])


def _leg_solve(fwd: float, out: float, drop: float = 0.0, lift: float = 0.0, toe: float = 8.0,
               side: str = "right") -> Dict[str, float]:
    """Leg angles that put the ankle at (fwd, out) metres from the pelvis centre (out = toward its own
    side) with the hips lowered by `drop` and the foot raised by `lift`; knee bends forward."""
    sign = 1.0 if side == "right" else -1.0
    target = np.array([out - HIP_OUT, -LEG_DROP0 + drop + lift, fwd])
    dist = float(np.linalg.norm(target))
    t, s = me.THIGH * U, me.SHIN * U
    dist = min(dist, t + s - 1e-4)
    cos_k = (t * t + s * s - dist * dist) / (2 * t * s)
    kn0 = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos_k))))

    def cost(x: np.ndarray) -> float:
        knee, foot = _leg_fk(x[0], x[1], toe, x[2], 1.0)
        return float(np.sum((foot - target) ** 2)) * 1e4 + (0.0 if knee[2] >= -0.02 else 50.0 * knee[2] ** 2) \
            + 1e-4 * x[2] ** 2
    v = target / max(1e-6, np.linalg.norm(target))
    r0 = math.degrees(math.acos(max(-1.0, min(1.0, -v[1])))) + kn0 / 2
    d0 = math.degrees(math.atan2(v[0], max(1e-3, v[2] + 0.05)))
    x = _nelder_mead(cost, np.array([r0, d0, kn0]))
    x = _nelder_mead(cost, x, step=4.0)
    return Lg(round(float(x[0]), 2), round(float(x[1]), 2), toe, round(max(0.0, float(x[2])), 2))


def _arm_fk(x: np.ndarray, sign: float) -> Tuple[np.ndarray, np.ndarray]:
    sh = me.limb_local_rotation(x[0], x[1], x[2], sign)
    el = sh @ np.array([0.0, -me.UPPER_ARM, 0.0])
    ha = el + sh @ me.rx(-x[3]) @ np.array([0.0, -me.FOREARM, 0.0])
    return el * U, ha * U


def _arm_body_depth(p: np.ndarray, side: str) -> float:
    """How deep (m) this arm pose cuts into the torso/pelvis with the trunk upright."""
    import motion_script as ms
    pose = {q: dict(v) for q, v in ms.NEUTRAL.items()}
    pose[f"{side}_arm"].update({"raise": p[0], "dir": p[1], "twist": p[2], "elbow": p[3]})
    w = me.world_rotations(ms.part_rotations(pose))
    return ms.body_penetration(w, me.forward_kinematics(w), side)


ELBOW_HINT = {"down": (0.0, -1.0, 0.0), "out": (1.0, -0.4, 0.0), "back": (0.2, -0.5, -1.0),
              "up": (0.6, 1.0, 0.0), "forward": (0.0, -0.3, 1.0)}


def arm_at(x: float, y: float, z: float, elbow: str = "down", side: str = "right",
           seed: Optional[Dict[str, float]] = None) -> Dict[str, float]:
    """Arm angles that put the hand at (x across->out, y up, z forward) metres measured from the
    MIDDLE of the shoulder line (x + = toward the arm's own side), elbow pointing `elbow`.
    seed = a nearby solution to start from (grip paths), which makes the solve ~10x faster."""
    key = _solved_key("arm", float(x), float(y), float(z), elbow, side)
    if key not in _SOLVED:
        r = _arm_solve(float(x), float(y), float(z), elbow, side, seed)
        _SOLVED[key] = [r["raise"], r["dir"], r["twist"], r["elbow"]]
        _SOLVED_DIRTY[0] = True
    v = _SOLVED[key]
    return A(v[0], v[1], v[2], v[3])


def _arm_solve(x: float, y: float, z: float, elbow: str, side: str,
               seed: Optional[Dict[str, float]]) -> Dict[str, float]:
    sign = 1.0 if side == "right" else -1.0
    sh_x = me.SHOULDER_OFFSET[0] * U
    target = np.array([x - sh_x, y, z])        # relative to this shoulder, own-side positive
    hint = np.array(ELBOW_HINT[elbow], dtype=float)

    def cost(p: np.ndarray) -> float:
        el, ha = _arm_fk(p, 1.0)
        c = float(np.sum((ha - target) ** 2)) * 1e4 + 3e4 * _arm_body_depth(p, "right") ** 2
        c += 4.0 * float(np.sum((el / max(1e-6, np.linalg.norm(el)) - hint / np.linalg.norm(hint)) ** 2))
        return c + 1e-4 * (p[3] ** 2) + (0.0 if 0 <= p[3] <= 150 else 10.0 * min(abs(p[3]), abs(p[3] - 150)) ** 2)
    best = None
    if seed is not None:
        p = _nelder_mead(cost, np.array([seed["raise"], seed["dir"], seed["twist"], seed["elbow"]]), step=6.0, iters=120)
        if cost(p) < 2.0:   # hand within ~1 cm of the target with the elbow as asked: done
            return A(round(float(p[0]), 2), round(float(p[1]), 2), round(float(p[2]), 2),
                     round(float(np.clip(p[3], 0, 150)), 2))
        best = p
    for r0, d0, t0 in ((60, 0, 0), (60, 60, -40), (100, 30, 40), (30, -30, -60), (140, 20, 0)):
        p = _nelder_mead(cost, np.array([r0, d0, t0, 60.0]), step=20.0)
        p = _nelder_mead(cost, p, step=5.0)
        if best is None or cost(p) < cost(best):
            best = p
    p = best
    return A(round(float(p[0]), 2), round(float(p[1]), 2), round(float(p[2]), 2), round(float(np.clip(p[3], 0, 150)), 2))


def motion(name: str, comment: str, kind: str, parts: List[str], soft: Optional[List[str]] = None,
           params: Optional[Dict[str, Tuple[Any, Any]]] = None, period: Optional[float] = None,
           loop_pose: bool = False):
    """Register a motion. The decorated function returns its keyframes (it receives the params)."""
    def deco(fn):
        DB[name] = {"name": name, "comment": comment, "kind": kind, "parts": parts, "soft_parts": soft or [],
                    "params": params or {}, "build": functools.lru_cache(maxsize=64)(fn), "loop_pose": loop_pose}
        if period:
            DB[name]["period"] = period
        return fn
    return deco


ARMS = ["right_arm", "left_arm"]
LEGS = ["right_leg", "left_leg"]
TRUNK = ["spine", "neck"]

def support_arms(pitch: float, lean: float = 0.0, elbow: str = "down", spread: float = 0.30) -> Dict[str, Dict[str, float]]:
    """Both arms planted on the floor directly under the shoulders for a body tilted `pitch` degrees
    face-down (90 = horizontal) with straight legs and the toes on the floor: the hands land exactly
    where the floor is, so hands and feet touch together (planks, push-ups, mountain climbers).
    Bend comes out by itself: high pitch (chest low) -> bent elbows pointing back toward the hips."""
    import motion_script as ms
    pose = {q: dict(v) for q, v in ms.NEUTRAL.items()}
    pose["body"]["pitch"] = pitch
    pose["spine"].update(lean=lean, twist=0.0, side=0.0)
    for leg in ("right_leg", "left_leg"):
        pose[leg].update({"raise": 0.0, "dir": 0.0, "twist": 0.0, "knee": 0.0})
    w = me.world_rotations(ms.part_rotations(pose))
    pos = me.forward_kinematics(w)
    sole = min(pos["right_foot"][1], pos["left_foot"][1]) - me.SOLE_DROP
    sh_mid = w["spine"] @ np.array([0.0, me.SHOULDER_OFFSET[1], 0.0])
    h = (sh_mid[1] - sole - me.LIMB_RADIUS) * U           # shoulder line height above the floor (m)
    down = w["spine"].T @ np.array([0.0, -1.0, 0.0])      # world "down" in the chest frame
    reach = min(h, 0.97 * (me.UPPER_ARM + me.FOREARM) * U)
    tgt = down * reach
    x, y, z = round(spread, 2), round(float(tgt[1]), 2), round(float(tgt[2]), 2)
    return {"right_arm": arm_at(x, y, z, elbow, "right"), "left_arm": arm_at(x, y, z, elbow, "left")}


FLOOR_Y = -(1.0 + me.THIGH + me.SHIN + me.SOLE_DROP) * U       # floor height below the standing pelvis (m)
CONTACT_R = {"head": 0.17, "right_foot": 0.065, "left_foot": 0.065}  # point -> its distance from the floor at contact


def fit_pose(name: str, free: Dict[str, float], fixed: Dict[str, Dict[str, float]],
             goals: List[Tuple[str, str, float, float]]) -> Dict[str, Dict[str, float]]:
    """Solve a floor pose once (cached in the solved-pose file). free: {"part.param": start value};
    fixed: part values that do not change; goals: (point, kind, value, weight) where kind is "floor"
    (that point rests on the floor), "y" (height above the floor, m), "z" / "x" (body-frame forward /
    sideways position relative to the pelvis, m). Ground contact is resolved like playback does it."""
    import motion_script as ms
    keys = list(free)
    key = _solved_key("pose", name)
    if key not in _SOLVED:
        def build(x):
            pose = {q: dict(v) for q, v in ms.NEUTRAL.items()}
            for part, vals in fixed.items():
                for p2 in GROUPS.get(part, [part]):
                    pose[p2].update(vals)
            for kname, v in zip(keys, x):
                part, prm = kname.split(".")
                for p2 in GROUPS.get(part, [part]):
                    pose[p2][prm] = float(v)
            return pose

        def cost(x):
            pose = build(x)
            w = me.world_rotations(ms.part_rotations(pose))
            pos = me.forward_kinematics(w)
            g = ms.ground_offset(pos, w)
            c = 0.0
            for point, kind, value, weight in goals:
                pt = pos[point] * U + np.array([0.0, g, 0.0])
                if kind == "floor":
                    r = CONTACT_R.get(point, me.LIMB_RADIUS * U)
                    c += weight * (pt[1] - r - FLOOR_Y) ** 2 * 100
                elif kind == "y":
                    c += weight * (pt[1] - FLOOR_Y - value) ** 2 * 100
                elif kind == "z":
                    c += weight * (pt[2] - value) ** 2 * 100
                elif kind == "x":
                    c += weight * (pt[0] - value) ** 2 * 100
            return c + 1e-6 * float(np.sum(np.square(x)))
        x = np.array([free[kk] for kk in keys], dtype=float)
        x = _nelder_mead(cost, x, step=15.0, iters=500)
        x = _nelder_mead(cost, x, step=4.0, iters=500)
        _SOLVED[key] = [round(float(v), 2) for v in x]
        _SOLVED_DIRTY[0] = True
    out: Dict[str, Dict[str, float]] = {part: dict(vals) for part, vals in fixed.items()}
    for kname, v in zip(keys, _SOLVED[key]):
        part, prm = kname.split(".")
        for p2 in GROUPS_DB.get(part, [part]):
            out.setdefault(p2, {})[prm] = v
    return out


GROUPS_DB = {"legs": ["right_leg", "left_leg"], "arms": ["right_arm", "left_arm"]}
GROUPS = GROUPS_DB


def full(part: str, **vals: float) -> Dict[str, float]:
    """Complete parameter dict for a part (fit_pose results only set what was solved)."""
    import motion_script as ms
    d = dict(ms.NEUTRAL[part])
    d.update(vals)
    return d


PLANK_PITCH = 57.0        # straight arms reach the floor at this body angle on this rig
PUSHUP_LOW_PITCH = 75.0   # chest a hand's width off the floor


# ---- reusable poses ---------------------------------------------------------
HANG = A(6, 80, 0, 10)
READY_R = A(32, 12, -35, 80)                    # athletic ready: forearms forward in front of the waist
GUARD_R = A(38, 8, -62, 132)                    # rear hand at the chin, elbow down
GUARD_L = A(50, 4, -55, 120)                    # lead hand a little higher and further forward

STANCE_WIDTH = {"narrow": 0.10, "normal": 0.17, "wide": 0.27, "very_wide": 0.36}


def stance_legs(width: str = "normal", depth: float = 0.4, stagger: str = "none", toe: float = 10.0
                ) -> Dict[str, Dict[str, float]]:
    """Both legs of a standing stance. depth 0 = tall, 1 = deep (thighs near parallel)."""
    w = STANCE_WIDTH[width]
    depth = round(float(depth) * 20) / 20.0          # 0.05 steps: shared, pre-solved leg poses
    drop = 0.03 + 0.30 * depth
    st = {"none": (0.0, 0.0), "left": (-0.17, 0.17), "right": (0.17, -0.17)}[stagger]
    return {"right_leg": leg_at(round(st[0] + 0.06 * depth, 3), w, round(drop, 3), 0.0, toe, "right"),
            "left_leg": leg_at(round(st[1] + 0.06 * depth, 3), w, round(drop, 3), 0.0, toe, "left")}


# =============================================================================
# 1. STANCES AND POSES
# =============================================================================
@motion("stand", "Relaxed standing posture, arms hanging.", "pose", LEGS + ["pelvis"], ARMS + TRUNK)
def _stand():
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 4), pelvis=P(), spine=S(3), neck=N(),
              right_arm=HANG, left_arm=HANG)]


@motion("stance", "Athletic ready stance (legs + hips). Customize width, knee depth, which foot is forward, "
        "and an optional light bounce.", "pose", LEGS, ["pelvis", "spine"],
        params={"width": ("normal", ("narrow", "normal", "wide", "very_wide")),
                "depth": (0.4, (0.0, 1.0)), "stagger": ("none", ("none", "left", "right")),
                "bounce": ("off", ("off", "on"))}, loop_pose=True)
def _stance(width="normal", depth=0.4, stagger="none", bounce="off"):
    lean = 4 + 22 * depth
    base = stance_legs(width, depth, stagger)
    keys = [k(0.0, **base, pelvis=P(4 * depth), spine=S(lean))]
    if bounce == "on":
        low = stance_legs(width, min(1.0, depth + 0.15), stagger)
        keys += [k(0.2, **low), k(0.4, **base)]
    return keys


@motion("ready_arms", "Hands up in front of the waist, elbows bent - the athletic ready position.", "pose", [], ARMS)
def _ready_arms():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R)]


@motion("arms_hang", "Arms relaxed at the sides.", "pose", [], ARMS)
def _arms_hang():
    return [k(0.0, right_arm=HANG, left_arm=HANG)]


@motion("guard", "Boxing / fighting guard: both fists at the chin, elbows down and in.", "pose", [], ARMS + ["neck"])
def _guard():
    return [k(0.0, right_arm=GUARD_R, left_arm=GUARD_L, neck=N(8))]


@motion("fighting_stance", "Boxing / martial-arts stance: lead (left) foot forward, knees soft, hips bladed. "
        "Optional bounce.", "pose", LEGS, ["pelvis", "spine"],
        params={"bounce": ("off", ("off", "on"))}, loop_pose=True)
def _fighting_stance(bounce="off"):
    legs = stance_legs("normal", 0.3, "left", toe=20)
    keys = [k(0.0, **legs, pelvis=P(2, 20), spine=S(8, 12))]
    if bounce == "on":
        keys += [k(0.18, **stance_legs("normal", 0.42, "left", toe=20)), k(0.36, **legs)]
    return keys


@motion("plank", "Plank / push-up position held on straight arms.", "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _plank():
    return [k(0.0, body=B(PLANK_PITCH), spine=S(0), pelvis=P(), **support_arms(PLANK_PITCH),
              right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), neck=N(-25))]


@motion("arms_overhead", "Both arms straight up overhead (celebration, stretch, block).", "pose", ARMS)
def _arms_overhead():
    return [k(0.0, right_arm=A(168, 8, 0, 5), left_arm=A(168, 8, 0, 5))]


@motion("arms_out", "Arms held out to the sides at shoulder height (balance).", "pose", ARMS)
def _arms_out():
    return [k(0.0, right_arm=A(85, 85, 0, 8), left_arm=A(85, 85, 0, 8))]


@motion("hands_on_hips", "Hands resting on the hips.", "pose", ARMS)
def _hands_on_hips():
    return [k(0.0, right_arm=arm_at(0.26, -0.47, 0.02, "out", "right"), left_arm=arm_at(0.26, -0.47, 0.02, "out", "left"))]


# =============================================================================
# 2. LOCOMOTION
# =============================================================================
RUN_PACE = {  # period (s), thigh drive, heel kick, push-off extension, trunk lean, arm swing, bounce
    "jog": (0.78, 38, 85, 18, 6, 30, 0.03),
    "run": (0.66, 52, 105, 22, 9, 42, 0.04),
    "sprint": (0.56, 68, 125, 26, 13, 58, 0.05),
}


def _run_keys(pace: str):
    T, drive, heel, push, lean, swing, bounce = RUN_PACE[pace]
    contact = Lg(drive * 0.35, 0, 6, 14)          # foot landing under / slightly ahead of the hips
    mid = Lg(4, 0, 6, 26)                          # mid-stance, knee absorbing
    toe_off = Lg(push, 180, 6, 22)                 # pushed back behind the hips
    swing_up = Lg(drive * 0.55, 0, 6, heel)        # heel tucked under the hips, thigh coming through
    knee_hi = Lg(drive, 0, 6, heel * 0.7)          # thigh at its highest, shin hanging
    arm_f = A(swing + 20, 6, -18, 88)              # hand forward to chin/chest
    arm_b = A(swing * 0.7, 175, 10, 75)            # elbow back past the hip (forearm clears the hip)
    q = T / 4
    return [
        k(0.0, right_leg=contact, left_leg=toe_off, right_arm=arm_b, left_arm=arm_f, spine=S(lean, -4),
          pelvis=P(3, 6), body=B(root=0.0)),
        k(q, right_leg=mid, left_leg=swing_up, right_arm=A(18, 90, -10, 80), left_arm=A(18, 90, -10, 80),
          spine=S(lean, 0), pelvis=P(3, 0), body=B(root=-bounce * 0.5)),
        k(2 * q, right_leg=toe_off, left_leg=contact, right_arm=arm_f, left_arm=arm_b, spine=S(lean, 4),
          pelvis=P(3, -6), body=B(root=bounce)),
        k(3 * q, right_leg=swing_up, left_leg=mid, right_arm=A(18, 90, -10, 80), left_arm=A(18, 90, -10, 80),
          spine=S(lean, 0), pelvis=P(3, 0), body=B(root=-bounce * 0.5)),
    ]


@motion("run", "Running in place, one full stride cycle (both legs). pace = jog, run or sprint. Arms pump "
        "unless another motion drives them.", "cycle", LEGS + ["pelvis"], ARMS + ["spine", "body"],
        params={"pace": ("run", ("jog", "run", "sprint"))})
def _run(pace="run"):
    return {"keys": _run_keys(pace), "period": RUN_PACE[pace][0]}


@motion("walk", "Walking in place, one full step cycle with natural arm swing.", "cycle", LEGS + ["pelvis"],
        ARMS + ["spine"], period=1.1)
def _walk():
    T = 1.1
    return [
        k(0.0, right_leg=Lg(22, 0, 6, 6), left_leg=Lg(16, 180, 6, 18), right_arm=A(16, 180, 0, 15),
          left_arm=A(22, 8, -10, 25), pelvis=P(0, 5), spine=S(3, -3)),
        k(T * 0.25, right_leg=Lg(2, 0, 6, 10), left_leg=Lg(18, 0, 6, 55), right_arm=A(6, 80, 0, 12),
          left_arm=A(6, 80, 0, 12), pelvis=P(0, 0), spine=S(3, 0)),
        k(T * 0.5, right_leg=Lg(16, 180, 6, 18), left_leg=Lg(22, 0, 6, 6), right_arm=A(22, 8, -10, 25),
          left_arm=A(16, 180, 0, 15), pelvis=P(0, -5), spine=S(3, 3)),
        k(T * 0.75, right_leg=Lg(18, 0, 6, 55), left_leg=Lg(2, 0, 6, 10), right_arm=A(6, 80, 0, 12),
          left_arm=A(6, 80, 0, 12), pelvis=P(0, 0), spine=S(3, 0)),
    ]


@motion("backpedal", "Backpedal in place: short quick steps backward on the balls of the feet, low hips.",
        "cycle", LEGS + ["pelvis"], ARMS + ["spine"], period=0.5)
def _backpedal():
    T = 0.5
    a = leg_at(-0.05, 0.16, 0.12, 0.0, 10, "right")
    b = leg_at(-0.18, 0.16, 0.12, 0.10, 10, "right")
    al = leg_at(-0.05, 0.16, 0.12, 0.0, 10, "left")
    bl = leg_at(-0.18, 0.16, 0.12, 0.10, 10, "left")
    return [k(0.0, right_leg=a, left_leg=bl, right_arm=A(30, 170, 10, 85), left_arm=A(40, 5, -20, 85),
              spine=S(14), pelvis=P(3)),
            k(T / 2, right_leg=b, left_leg=al, right_arm=A(40, 5, -20, 85), left_arm=A(30, 170, 10, 85))]


@motion("shuffle", "Lateral defensive shuffle to the athlete's right (side=left shuffles left): low "
        "stance, feet push apart and snap back together without crossing.", "cycle", LEGS + ["pelvis"],
        ARMS + ["spine"], period=0.46)
def _shuffle():
    T = 0.46
    wide = {"right_leg": leg_at(0.02, 0.36, 0.2, 0.06, 15, "right"), "left_leg": leg_at(0.02, 0.30, 0.2, 0.0, 15, "left")}
    land = {"right_leg": leg_at(0.02, 0.34, 0.22, 0.0, 15, "right"), "left_leg": leg_at(0.02, 0.30, 0.22, 0.0, 15, "left")}
    close = {"right_leg": leg_at(0.02, 0.24, 0.2, 0.0, 15, "right"), "left_leg": leg_at(0.02, 0.16, 0.2, 0.07, 15, "left")}
    arms = {"right_arm": A(40, 45, -20, 70), "left_arm": A(40, 45, -20, 70)}
    return [k(0.0, **land, **arms, spine=S(22), pelvis=P(6)), k(T * 0.45, **close), k(T * 0.75, **wide)]


@motion("high_knees", "High knees drill: knees driven to hip height alternately with quick arm pumps.",
        "cycle", LEGS + ["pelvis"], ARMS + ["spine", "body"], period=0.5)
def _high_knees():
    T = 0.5
    up = Lg(88, 0, 6, 105)
    down = Lg(2, 0, 6, 12)
    return [k(0.0, right_leg=up, left_leg=down, right_arm=A(30, 175, 10, 85), left_arm=A(65, 6, -20, 90),
              spine=S(2), pelvis=P(-2), body=B(root=0.03)),
            k(T / 4, right_leg=Lg(40, 0, 6, 60), left_leg=Lg(40, 0, 6, 60), right_arm=A(15, 90, 0, 80),
              left_arm=A(15, 90, 0, 80), body=B(root=0.0)),
            k(T / 2, right_leg=down, left_leg=up, right_arm=A(65, 6, -20, 90), left_arm=A(30, 175, 10, 85),
              body=B(root=0.03)),
            k(3 * T / 4, right_leg=Lg(40, 0, 6, 60), left_leg=Lg(40, 0, 6, 60), right_arm=A(15, 90, 0, 80),
              left_arm=A(15, 90, 0, 80), body=B(root=0.0))]


@motion("butt_kicks", "Butt kicks drill: heels flick up to the glutes alternately, quick light steps.",
        "cycle", LEGS, ARMS + ["spine"], period=0.46)
def _butt_kicks():
    T = 0.46
    up = Lg(12, 0, 6, 140)
    down = Lg(2, 0, 6, 10)
    return [k(0.0, right_leg=up, left_leg=down, right_arm=A(25, 175, 10, 85), left_arm=A(45, 6, -20, 90), spine=S(6)),
            k(T / 2, right_leg=down, left_leg=up, right_arm=A(45, 6, -20, 90), left_arm=A(25, 175, 10, 85))]


@motion("carioca", "Carioca / grapevine footwork moving right: trail leg crosses in front, then behind, "
        "hips rotating.", "cycle", LEGS + ["pelvis"], ARMS + ["spine"], period=1.0)
def _carioca():
    arms = {"right_arm": A(60, 85, 0, 30), "left_arm": A(60, 85, 0, 30)}
    return [k(0.0, right_leg=leg_at(0, 0.22, 0.1, 0, 10, "right"), left_leg=leg_at(0, 0.22, 0.1, 0, 10, "left"),
              pelvis=P(3, 0), spine=S(6, 0), **arms),
            k(0.25, right_leg=leg_at(0, 0.24, 0.1, 0, 10, "right"), left_leg=leg_at(0.12, -0.12, 0.1, 0.06, -5, "left"),
              pelvis=P(3, -30), spine=S(6, 12)),
            k(0.5, right_leg=leg_at(0, 0.22, 0.1, 0, 10, "right"), left_leg=leg_at(0, 0.22, 0.1, 0, 10, "left"),
              pelvis=P(3, 0), spine=S(6, 0)),
            k(0.75, right_leg=leg_at(0, 0.24, 0.1, 0, 10, "right"), left_leg=leg_at(-0.12, -0.12, 0.1, 0.06, -5, "left"),
              pelvis=P(3, 30), spine=S(6, -12))]


@motion("turn", "Turn the whole body to face a new direction (degrees, + = turn right).", "action", ["body"],
        params={"deg": (90, (-360, 360))})
def _turn(deg=90):
    return [k(0.0, body=B(turn=0)), k(0.25 + abs(deg) / 600.0, body=B(turn=deg))]


# =============================================================================
# 3. JUMPS AND PLYOMETRICS
# =============================================================================
JUMP_HEIGHT = {"low": 0.12, "normal": 0.26, "high": 0.40}


def _flight(t0: float, h: float, n: int = 4) -> List[Tuple[float, float]]:
    """Ballistic root curve: lift-off at t0, apex h (time from physics), landing."""
    T = math.sqrt(8 * h / 9.81)
    return [(t0 + T * i / n, 4 * h * (i / n) * (1 - i / n)) for i in range(n + 1)], T


@motion("jump", "Vertical jump: load (hips back, arms swing back), explode up with arms overhead, land "
        "softly. Combine with arm motions (e.g. jump + shoot) to replace the arm swing.", "action",
        LEGS + ["body"], ARMS + ["spine", "pelvis"], params={"height": ("normal", ("low", "normal", "high"))})
def _jump(height="normal"):
    h = JUMP_HEIGHT[height]
    load = stance_legs("normal", 0.9)
    ext = {"right_leg": Lg(3, 0, 8, 2), "left_leg": Lg(3, 0, 8, 2)}
    pts, T = _flight(0.55, h)
    keys = [k(0.0, **stance_legs("normal", 0.15), body=B(), right_arm=HANG, left_arm=HANG, spine=S(4), pelvis=P()),
            k(0.38, **load, right_arm=A(45, 175, 10, 12), left_arm=A(45, 175, 10, 12), spine=S(32), pelvis=P(8)),
            k(0.47, right_arm=A(25, 0, 0, 10), left_arm=A(25, 0, 0, 10)),
            k(0.55, **ext, right_arm=A(150, 6, 0, 10), left_arm=A(150, 6, 0, 10), spine=S(4), pelvis=P(),
              body=B(air=1.0, root=0.0))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r), right_leg=Lg(12, 0, 8, 25), left_leg=Lg(12, 0, 8, 25)))
    t_land = pts[-1][0]
    keys += [k(t_land, body=B(air=1.0, root=0.0), **ext, right_arm=A(70, 10, 0, 20), left_arm=A(70, 10, 0, 20)),
             k(t_land + 0.04, body=B(air=0.0)),
             k(t_land + 0.24, **stance_legs("normal", 0.6), spine=S(22), right_arm=A(40, 15, -10, 40),
               left_arm=A(40, 15, -10, 40)),
             k(t_land + 0.6, **stance_legs("normal", 0.15), spine=S(4), right_arm=HANG, left_arm=HANG)]
    return keys


@motion("tuck_jump", "Tuck jump: explode up and pull both knees to the chest at the top, land softly.",
        "action", LEGS + ["body"], ARMS + ["spine", "pelvis"])
def _tuck_jump():
    keys = list(_jump("high"))
    apex = max(keys, key=lambda kv: kv[1].get("body", {}).get("root", 0.0))
    t = apex[0]
    keys = [kk for kk in keys if not (abs(kk[0] - t) < 1e-6)]
    keys.append(k(t, body=B(air=1.0, root=apex[1]["body"]["root"]), right_leg=Lg(105, 0, 8, 125),
                  left_leg=Lg(105, 0, 8, 125), right_arm=A(60, 5, -20, 60), left_arm=A(60, 5, -20, 60), spine=S(18)))
    keys.sort(key=lambda kv: kv[0])
    return keys


@motion("lateral_bound", "Lateral bound to the right: push off the left leg, fly sideways, stick the landing "
        "on the right leg.", "action", LEGS + ["body", "pelvis"], ARMS + ["spine"])
def _lateral_bound():
    pts, T = _flight(0.45, 0.18)
    keys = [k(0.0, **stance_legs("normal", 0.3), body=B(), pelvis=P(), spine=S(10), right_arm=HANG, left_arm=HANG),
            k(0.32, right_leg=leg_at(0.0, 0.10, 0.18, 0.12, 10, "right"), left_leg=leg_at(0.0, 0.26, 0.22, 0.0, 10, "left"),
              spine=S(28, 0, -8), pelvis=P(6, 0, -6), right_arm=A(30, 150, 0, 20), left_arm=A(30, 170, 0, 20)),
            k(0.45, left_leg=Lg(30, 90, 8, 5), right_leg=Lg(15, 60, 8, 20), body=B(air=1.0), spine=S(10, 0, 8),
              right_arm=A(80, 70, 0, 20), left_arm=A(60, 20, 0, 30))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), right_leg=Lg(18, 70, 8, 15), left_leg=Lg(28, 140, 8, 60)),
             k(tl + 0.03, body=B(air=0.0)),
             k(tl + 0.3, right_leg=leg_at(0.02, 0.12, 0.22, 0.0, 10, "right"), left_leg=Lg(25, 160, 8, 75),
               spine=S(30, 0, 6), pelvis=P(8, 0, 6), right_arm=A(45, 20, -10, 40), left_arm=A(55, 60, 0, 30)),
             k(tl + 1.0, right_leg=leg_at(0.02, 0.12, 0.16, 0.0, 10, "right"), left_leg=Lg(22, 160, 8, 70))]
    return keys


@motion("skater_hop", "Skater hops side to side, landing on one leg with the other sweeping behind.",
        "cycle", LEGS + ["body", "pelvis"], ARMS + ["spine"], period=1.2)
def _skater():
    T = 1.2
    land_r = {"right_leg": leg_at(0.0, 0.14, 0.24, 0.0, 10, "right"), "left_leg": Lg(30, -150, 8, 50)}
    land_l = {"left_leg": leg_at(0.0, 0.14, 0.24, 0.0, 10, "left"), "right_leg": Lg(30, -150, 8, 50)}
    return [k(0.0, **land_r, body=B(air=0.0, root=0.0), spine=S(32, -15, 0), pelvis=P(8, -10),
              right_arm=A(30, 160, 0, 20), left_arm=A(55, -30, -10, 30)),
            k(T * 0.22, body=B(air=0.0)),
            k(T * 0.3, body=B(air=1.0, root=0.06), right_leg=Lg(25, 100, 8, 25), left_leg=Lg(25, 80, 8, 25), spine=S(15, 0),
              pelvis=P(4, 0), right_arm=A(30, 60, 0, 30), left_arm=A(30, 60, 0, 30)),
            k(T * 0.42, body=B(air=1.0, root=0.0)),
            k(T * 0.47, **land_l, body=B(air=0.0, root=0.0), spine=S(32, 15, 0), pelvis=P(8, 10),
              left_arm=A(30, 160, 0, 20), right_arm=A(55, -30, -10, 30)),
            k(T * 0.72, body=B(air=0.0)),
            k(T * 0.8, body=B(air=1.0, root=0.06), right_leg=Lg(25, 80, 8, 25), left_leg=Lg(25, 100, 8, 25), spine=S(15, 0),
              pelvis=P(4, 0), right_arm=A(30, 60, 0, 30), left_arm=A(30, 60, 0, 30)),
            k(T * 0.92, body=B(air=1.0, root=0.0))]


@motion("jumping_jack", "Jumping jack: hop feet apart while the arms sweep overhead, hop back together.",
        "cycle", LEGS + ARMS + ["body"], ["spine"], period=0.9)
def _jumping_jack():
    T = 0.9
    closed = {"right_leg": Lg(2, 90, 8, 6), "left_leg": Lg(2, 90, 8, 6), "right_arm": A(8, 85, 0, 8),
              "left_arm": A(8, 85, 0, 8)}
    opened = {"right_leg": Lg(17, 90, 15, 6), "left_leg": Lg(17, 90, 15, 6), "right_arm": A(165, 85, 0, 8),
              "left_arm": A(165, 85, 0, 8)}
    return [k(0.0, **closed, body=B(air=0.0, root=0.0), spine=S(3)),
            k(T * 0.1, body=B(air=1.0, root=0.0)),
            k(T * 0.25, body=B(air=1.0, root=0.07), right_leg=Lg(10, 90, 12, 6), left_leg=Lg(10, 90, 12, 6),
              right_arm=A(90, 85, 0, 8), left_arm=A(90, 85, 0, 8)),
            k(T * 0.4, **opened, body=B(air=1.0, root=0.0)),
            k(T * 0.5, body=B(air=0.0, root=0.0)),
            k(T * 0.6, body=B(air=1.0, root=0.0)),
            k(T * 0.75, body=B(air=1.0, root=0.07), right_leg=Lg(10, 90, 12, 6), left_leg=Lg(10, 90, 12, 6),
              right_arm=A(90, 85, 0, 8), left_arm=A(90, 85, 0, 8)),
            k(T * 0.9, body=B(air=1.0, root=0.0), **{p: v for p, v in closed.items()})]


# =============================================================================
# 4. STRENGTH / CONDITIONING
# =============================================================================
@motion("squat", "Bodyweight squat: sit the hips back and down to thigh-parallel with the chest up and arms "
        "reaching forward for balance, then stand.", "action", LEGS + ["pelvis", "spine"], ARMS,
        params={"depth": (1.0, (0.4, 1.3))})
def _squat(depth=1.0):
    down = stance_legs("normal", depth)
    return [k(0.0, **stance_legs("normal", 0.05), pelvis=P(), spine=S(4), right_arm=HANG, left_arm=HANG),
            k(1.0, **down, pelvis=P(12), spine=S(18 + 22 * depth), right_arm=A(85, 6, 0, 6), left_arm=A(85, 6, 0, 6)),
            k(1.25, hold=True),
            k(2.1, **stance_legs("normal", 0.05), pelvis=P(), spine=S(4), right_arm=HANG, left_arm=HANG)]


@motion("lunge", "Forward lunge on the right leg: step forward, lower until both knees are near 90 degrees, "
        "push back to standing.", "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _lunge():
    stand = stance_legs("normal", 0.05)
    low = {"right_leg": leg_at(0.42, 0.14, 0.36, 0.0, 6, "right"), "left_leg": Lg(26, 180, 4, 100)}
    return [k(0.0, **stand, pelvis=P(), spine=S(3), right_arm=HANG, left_arm=HANG),
            k(0.45, right_leg=leg_at(0.42, 0.14, 0.06, 0.0, 6, "right"), left_leg=Lg(18, 180, 4, 20)),
            k(1.15, **low, spine=S(5), right_arm=A(10, 60, 30, 20), left_arm=A(10, 60, 30, 20)),
            k(1.45, hold=True),
            k(2.1, right_leg=leg_at(0.42, 0.14, 0.06, 0.0, 6, "right"), left_leg=Lg(18, 180, 4, 20)),
            k(2.5, **stand, right_arm=HANG, left_arm=HANG)]


@motion("hinge", "Hip hinge / Romanian deadlift: hips back, flat back to ~70 degrees, hands slide down the "
        "thighs to the shins, stand tall.", "action", LEGS + ["spine", "pelvis"], ARMS)
def _hinge():
    up = stance_legs("normal", 0.05)
    down = stance_legs("normal", 0.35)
    return [k(0.0, **up, spine=S(4), pelvis=P(), right_arm=A(6, -10, 0, 5), left_arm=A(6, -10, 0, 5)),
            k(1.2, **down, spine=S(60), pelvis=P(18), right_arm=A(66, -8, 0, 5), left_arm=A(66, -8, 0, 5)),
            k(1.4, hold=True),
            k(2.4, **up, spine=S(4), pelvis=P(), right_arm=A(6, -10, 0, 5), left_arm=A(6, -10, 0, 5))]


@motion("single_leg_rdl", "Single-leg Romanian deadlift on the left leg: hinge forward as the right leg "
        "reaches straight back until body and leg form a T, then return.", "action",
        LEGS + ["spine", "pelvis"], ARMS)
def _sl_rdl():
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), spine=S(4), pelvis=P(), right_arm=HANG, left_arm=HANG),
            k(0.4, right_leg=Lg(12, 180, 8, 15), left_leg=Lg(4, 0, 8, 14)),
            k(1.4, right_leg=Lg(78, 180, 8, 6), left_leg=Lg(16, 0, 8, 16), spine=S(62), pelvis=P(14),
              right_arm=A(70, 5, 0, 5), left_arm=A(70, 5, 0, 5)),
            k(1.7, hold=True),
            k(2.7, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), spine=S(4), pelvis=P(), right_arm=HANG, left_arm=HANG)]


@motion("knee_drive", "Drive the right knee up to hip height and hold briefly (a march / high-knee step).",
        "action", ["right_leg"], ["left_leg", "left_arm", "right_arm", "spine"])
def _knee_drive():
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), right_arm=HANG, left_arm=HANG, spine=S(3)),
            k(0.35, right_leg=Lg(90, 0, 6, 100), left_leg=Lg(2, 0, 8, 10), right_arm=A(30, 175, 10, 80),
              left_arm=A(60, 6, -20, 90), spine=S(1)),
            k(0.7, hold=True),
            k(1.05, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), right_arm=HANG, left_arm=HANG, spine=S(3))]


@motion("leg_swing", "Dynamic leg swing: the straight right leg swings forward and back like a pendulum.",
        "cycle", ["right_leg"], ["left_leg", "right_arm", "left_arm", "spine"], period=1.2)
def _leg_swing():
    return [k(0.0, right_leg=Lg(70, 0, 8, 6), left_leg=Lg(2, 0, 8, 8), spine=S(-4), right_arm=A(70, 80, 0, 15),
              left_arm=A(70, 80, 0, 15)),
            k(0.6, right_leg=Lg(35, 180, 8, 10), spine=S(10))]


@motion("push_up", "Push-up: from the plank, bend the elbows back to lower the chest near the floor, press up.",
        "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"], period=1.6)
def _push_up():
    legs = {"right_leg": Lg(0, 0, 0, 0), "left_leg": Lg(0, 0, 0, 0)}
    return [k(0.0, body=B(PLANK_PITCH), spine=S(0), pelvis=P(), **support_arms(PLANK_PITCH), **legs, neck=N(-25)),
            k(0.4, body=B(66), **support_arms(66)),
            k(0.75, body=B(PUSHUP_LOW_PITCH), **support_arms(PUSHUP_LOW_PITCH), neck=N(-30)), k(0.9, hold=True),
            k(1.25, body=B(66), **support_arms(66), neck=N(-25))]


@motion("mountain_climbers", "Mountain climbers: in a plank, drive the knees to the chest alternately and fast.",
        "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"], period=0.6)
def _mountain():
    arms = support_arms(PLANK_PITCH)
    return [k(0.0, body=B(PLANK_PITCH), spine=S(0), pelvis=P(), **arms, right_leg=Lg(95, 0, 4, 120), left_leg=Lg(0, 0, 4, 0),
              neck=N(-25)),
            k(0.3, right_leg=Lg(0, 0, 4, 0), left_leg=Lg(95, 0, 4, 120))]


@motion("burpee", "Burpee: squat and place the hands, jump the feet back to a plank, jump them back in, "
        "explode up with the arms overhead, land.", "action", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _burpee():
    stand = stance_legs("normal", 0.05)
    crouch_legs = stance_legs("normal", 1.25)
    pts, T = _flight(2.25, 0.18)
    keys = [k(0.0, **stand, body=B(), spine=S(4), pelvis=P(), right_arm=HANG, left_arm=HANG, neck=N()),
            k(0.55, **crouch_legs, spine=S(55), pelvis=P(15), right_arm=A(55, 8, 0, 5), left_arm=A(55, 8, 0, 5)),
            k(0.75, body=B(10), spine=S(60)),
            k(1.05, body=B(PLANK_PITCH), spine=S(0), pelvis=P(), **support_arms(PLANK_PITCH),
              right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), neck=N(-25)),
            k(1.35, hold=True),
            k(1.75, body=B(10), **crouch_legs, spine=S(60), pelvis=P(15), right_arm=A(55, 8, 0, 5),
              left_arm=A(55, 8, 0, 5), neck=N()),
            k(2.1, body=B(0), **stance_legs("normal", 0.8), spine=S(25), pelvis=P(6), right_arm=A(30, 170, 10, 10),
              left_arm=A(30, 170, 10, 10)),
            k(2.18, right_arm=A(25, 0, 0, 10), left_arm=A(25, 0, 0, 10)),
            k(2.25, body=B(air=1.0), right_leg=Lg(3, 0, 8, 2), left_leg=Lg(3, 0, 8, 2), spine=S(2), pelvis=P(),
              right_arm=A(165, 8, 0, 5), left_arm=A(165, 8, 0, 5))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0)), k(tl + 0.04, body=B(air=0.0)),
             k(tl + 0.3, **stance_legs("normal", 0.5), spine=S(18), right_arm=A(40, 20, 0, 30), left_arm=A(40, 20, 0, 30)),
             k(tl + 0.7, **stand, spine=S(4), right_arm=HANG, left_arm=HANG)]
    return keys


@motion("jump_rope", "Jump rope: small quick two-foot hops on the balls of the feet, elbows by the sides, "
        "hands turning small circles at hip height.", "cycle", LEGS + ARMS + ["body"], ["spine"], period=0.5)
def _jump_rope():
    down = {"right_leg": Lg(4, 0, 8, 14), "left_leg": Lg(4, 0, 8, 14)}
    up = {"right_leg": Lg(6, 0, 8, 10), "left_leg": Lg(6, 0, 8, 10)}
    return [k(0.0, **down, body=B(air=0.0, root=0.0), right_arm=A(22, 70, 40, 55), left_arm=A(22, 70, 40, 55), spine=S(4)),
            k(0.12, body=B(air=1.0, root=0.0)),
            k(0.25, **up, body=B(air=1.0, root=0.06), right_arm=A(28, 50, 40, 45), left_arm=A(28, 50, 40, 45)),
            k(0.38, body=B(air=1.0, root=0.0)),
            k(0.45, body=B(air=0.0, root=0.0), **down)]


@motion("lateral_lunge", "Lateral (side) lunge to the right: step wide, sit the hips back over the bent right "
        "leg with the left leg straight, push back to standing.", "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _lateral_lunge():
    stand = stance_legs("normal", 0.05)
    low = {"right_leg": leg_at(0.08, 0.50, 0.34, 0.0, 20, "right"), "left_leg": leg_at(0.0, 0.42, 0.0, 0.0, 15, "left")}
    return [k(0.0, **stand, pelvis=P(), spine=S(3), right_arm=HANG, left_arm=HANG),
            k(1.0, **low, pelvis=P(12, 0, 6), spine=S(32, 0, 0), right_arm=A(70, 10, 0, 20), left_arm=A(70, 10, 0, 20)),
            k(1.3, hold=True),
            k(2.2, **stand, pelvis=P(), spine=S(3), right_arm=HANG, left_arm=HANG)]


@motion("overhead_press", "Overhead press: hands start at the shoulders with the elbows down and forward, "
        "press straight overhead, lower back.", "action", ARMS, ["spine"])
def _overhead_press():
    rack = {"right_arm": arm_at(0.24, 0.04, 0.16, "down", "right"), "left_arm": arm_at(0.24, 0.04, 0.16, "down", "left")}
    top = {"right_arm": A(170, 15, 0, 5), "left_arm": A(170, 15, 0, 5)}
    return [k(0.0, **rack, spine=S(3)), k(0.8, **top, spine=S(-3)), k(1.0, hold=True), k(1.9, **rack, spine=S(3))]


@motion("deadlift", "Deadlift (two hands on a bar): hips back and knees bent, flat back, arms hanging straight "
        "to the bar at the shins; stand up by driving the hips forward; lower under control.", "action",
        LEGS + ARMS + ["spine", "pelvis"], ["neck"])
def _deadlift():
    up = stance_legs("normal", 0.05)
    down = stance_legs("normal", 0.6)
    return [k(0.0, **up, spine=S(4), pelvis=P(), right_arm=A(6, -5, 0, 4), left_arm=A(6, -5, 0, 4), neck=N()),
            k(1.0, **down, spine=S(55), pelvis=P(16), right_arm=A(55, -5, 0, 4), left_arm=A(55, -5, 0, 4), neck=N(-15)),
            k(1.3, hold=True),
            k(2.3, **up, spine=S(4), pelvis=P(), right_arm=A(6, -5, 0, 4), left_arm=A(6, -5, 0, 4), neck=N())]


# =============================================================================
# 5. KICKING
# =============================================================================
@motion("soccer_kick", "Right-foot instep shot: plant the left foot, right leg swings back with the knee bent, "
        "whips through to a straight-leg strike and a high follow-through, lands forward. Calm balance arms "
        "unless another motion drives the arms.", "action", LEGS + ["pelvis"], ARMS + ["spine"],
        params={"power": ("full", ("pass", "full"))})
def _soccer_kick(power="full"):
    f = 1.0 if power == "full" else 0.55
    plant = leg_at(0.10, 0.15, 0.07, 0.0, 15, "left")
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), pelvis=P(), spine=S(4), right_arm=HANG,
              left_arm=HANG),
            k(0.28, right_leg=Lg(22 * f, 180, 8, 100 * f), left_leg=plant, pelvis=P(2, 10 * f), spine=S(8, -4),
              right_arm=A(25, 20, -10, 25), left_arm=A(45, 70, 0, 18)),
            k(0.44, right_leg=Lg(30 * f, 180, 10, 105 * f + 10), pelvis=P(3, 18 * f), spine=S(10, -8, -6 * f),
              right_arm=A(35, 15, -15, 30), left_arm=A(70, 72, 0, 18)),
            k(0.58, right_leg=Lg(28 * f, 0, 12, 22), pelvis=P(2, -6), spine=S(4, -4, -4 * f),
              right_arm=A(30, 150, 0, 20), left_arm=A(72, 65, 0, 20)),
            k(0.72, right_leg=Lg(78 * f, -6, 12, 8), pelvis=P(-4, -20 * f), spine=S(-6 * f, -14, -2),
              right_arm=A(38, -15, -10, 30), left_arm=A(65, 85, 0, 20)),
            k(1.02, right_leg=leg_at(0.32, 0.12, 0.08, 0.0, 10, "right"), left_leg=Lg(14, 180, 8, 18),
              pelvis=P(0, -10), spine=S(6, -6), right_arm=A(20, 20, -10, 25), left_arm=A(40, 70, 0, 25)),
            k(1.45, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), pelvis=P(), spine=S(4), right_arm=HANG,
              left_arm=HANG)]


@motion("inside_foot_pass", "Soccer pass with the inside of the right foot: short backswing, foot turned out, "
        "firm ankle, follow through toward the target.", "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _pass():
    plant = leg_at(0.06, 0.15, 0.06, 0.0, 12, "left")
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), pelvis=P(), spine=S(4), right_arm=HANG, left_arm=HANG),
            k(0.3, right_leg=Lg(18, 170, 55, 25), left_leg=plant, pelvis=P(2, 12), spine=S(8),
              right_arm=A(20, 40, 0, 20), left_arm=A(35, 70, 0, 20)),
            k(0.5, right_leg=Lg(14, -10, 60, 14), pelvis=P(2, -4)),
            k(0.68, right_leg=Lg(32, -12, 55, 10), pelvis=P(0, -10), spine=S(4)),
            k(1.0, right_leg=leg_at(0.22, 0.12, 0.06, 0.0, 10, "right"), left_leg=Lg(6, 180, 8, 10)),
            k(1.35, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), pelvis=P(), right_arm=HANG, left_arm=HANG)]


@motion("front_kick", "Martial-arts front kick with the right leg: chamber the knee high, snap the lower leg "
        "out at waist height, re-chamber, set down.", "action", LEGS + ["pelvis"], ["spine"])
def _front_kick():
    base = stance_legs("normal", 0.25, "left", 18)
    return [k(0.0, **base, pelvis=P(2, 15), spine=S(6, 10)),
            k(0.3, right_leg=Lg(85, 0, 4, 115), left_leg=leg_at(0.05, 0.14, 0.08, 0, 25, "left"), pelvis=P(-2, 0), spine=S(-2, 0)),
            k(0.45, right_leg=Lg(85, 0, 4, 5), pelvis=P(-6, -5), spine=S(-8, 0)),
            k(0.6, right_leg=Lg(85, 0, 4, 115), pelvis=P(-2, 0), spine=S(-2)),
            k(0.95, **base, pelvis=P(2, 15), spine=S(6, 10))]


@motion("side_kick", "Martial-arts side kick with the right leg: chamber the knee across, pivot the support "
        "foot, drive the heel out sideways at hip height with the trunk tilting away, retract.", "action",
        LEGS + ["pelvis", "spine"], [])
def _side_kick():
    base = stance_legs("normal", 0.25, "left", 18)
    return [k(0.0, **base, pelvis=P(2, 15), spine=S(6, 10)),
            k(0.32, right_leg=Lg(85, 30, -30, 120), left_leg=leg_at(0.0, 0.12, 0.08, 0, 60, "left"),
              pelvis=P(0, 40, 0), spine=S(4, 40, -10)),
            k(0.5, right_leg=Lg(88, 88, -70, 5), pelvis=P(0, 45, -20), spine=S(0, 45, -30)),
            k(0.62, hold=True),
            k(0.8, right_leg=Lg(80, 30, -30, 120), pelvis=P(0, 40, 0), spine=S(4, 40, -10)),
            k(1.15, **base, pelvis=P(2, 15), spine=S(6, 10))]


@motion("roundhouse_kick", "Martial-arts roundhouse kick with the right leg: pivot on the left foot, the hip "
        "turns over, the knee whips round and the shin snaps through at waist height.", "action",
        LEGS + ["pelvis", "spine"], [])
def _roundhouse():
    base = stance_legs("normal", 0.25, "left", 18)
    return [k(0.0, **base, pelvis=P(2, 15), spine=S(6, 10)),
            k(0.3, right_leg=Lg(70, 60, -20, 110), left_leg=leg_at(0.0, 0.12, 0.08, 0, 70, "left"),
              pelvis=P(0, -20, 0), spine=S(4, -10, -8)),
            k(0.48, right_leg=Lg(85, 25, -80, 15), pelvis=P(0, -55, -15), spine=S(0, -35, -20)),
            k(0.6, right_leg=Lg(80, -5, -80, 20)),
            k(0.85, right_leg=Lg(60, 50, -20, 100), pelvis=P(0, -20, 0), spine=S(4, -10, -6)),
            k(1.2, **base, pelvis=P(2, 15), spine=S(6, 10))]


# =============================================================================
# 6. RACKET / BAT / CLUB / THROWING (upper body - combine with a stance or stride)
# =============================================================================
@motion("forehand", "Tennis forehand (right hand): unit turn with the racket back, drop, swing low-to-high "
        "through contact in front, finish over the left shoulder. Combine with a stance.", "action",
        ARMS + ["spine"], ["pelvis", "neck"])
def _forehand():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(10, 0), pelvis=P(3, 0), neck=N(5, 0)),
            k(0.45, right_arm=A(70, 140, 30, 70), left_arm=A(85, -10, 0, 15), spine=S(10, 62), pelvis=P(3, 30), neck=N(5, -45)),
            k(0.72, right_arm=A(38, 125, 20, 30), spine=S(10, 55)),
            k(0.9, right_arm=A(48, 45, 5, 22), left_arm=A(45, 10, -40, 90), spine=S(8, 5), pelvis=P(3, -10), neck=N(5, -5)),
            k(1.0, right_arm=arm_at(0.05, -0.05, 0.50, "down", "right"), spine=S(7, -25)),
            k(1.15, right_arm=arm_at(-0.22, 0.16, 0.28, "out", "right"), left_arm=A(40, -20, -50, 125), spine=S(6, -55),
              pelvis=P(3, -35), neck=N(5, 20)),
            k(1.6, right_arm=READY_R, left_arm=READY_R, spine=S(10, 0), pelvis=P(3, 0), neck=N(5, 0))]


@motion("volley", "Tennis forehand volley: compact - racket hand up in front, short punch forward and "
        "slightly down to meet the ball in front of the body, no backswing, recover.", "action",
        ARMS + ["spine"], ["pelvis"])
def _volley():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(12), pelvis=P(3)),
            k(0.35, right_arm=arm_at(0.42, -0.02, 0.18, "down", "right"), left_arm=A(50, -10, -30, 80), spine=S(12, 25), pelvis=P(3, 12)),
            k(0.55, right_arm=arm_at(0.32, -0.08, 0.50, "down", "right"), spine=S(14, 5), pelvis=P(3, 0)),
            k(0.75, hold=True),
            k(1.2, right_arm=READY_R, left_arm=READY_R, spine=S(12), pelvis=P(3))]


@motion("backhand", "Two-handed tennis backhand: turn the shoulders left with both hands on the racket back by "
        "the left hip, swing through contact in front, finish high over the right shoulder.", "action",
        ARMS + ["spine"], ["pelvis", "neck"])
def _backhand():
    grip = grip_keys([(0.25, 0.05, -0.30, 0.32, "down"), (0.45, -0.30, -0.35, 0.22, "down"),
                      (0.72, -0.26, -0.45, 0.28, "down"), (0.9, 0.05, -0.36, 0.44, "down"),
                      (1.15, 0.26, 0.14, 0.26, "out")])
    return ([k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(10), pelvis=P(3), neck=N(5))] + grip +
            [k(0.45, spine=S(12, -70), pelvis=P(3, -35), neck=N(5, 45)), k(0.72, spine=S(12, -60)),
             k(0.9, spine=S(10, -5), pelvis=P(3, 5), neck=N(5, 5)), k(1.15, spine=S(6, 50), pelvis=P(3, 30), neck=N(5, -15)),
             k(1.6, right_arm=READY_R, left_arm=READY_R, spine=S(10), pelvis=P(3), neck=N(5))])


@motion("serve", "Tennis serve (full body): toss arm rises, trophy position with knees bent, legs drive up as "
        "the racket arm reaches high to contact, follow through across the body, land on the left foot.",
        "action", ARMS + LEGS + ["spine", "pelvis", "body"], ["neck"])
def _serve():
    base = stance_legs("normal", 0.15, "left", 30)
    pts, T = _flight(1.25, 0.10)
    keys = [k(0.0, **base, right_arm=A(30, 40, 0, 30), left_arm=A(35, 5, 0, 10), spine=S(6, 35), pelvis=P(2, 30), body=B(), neck=N()),
            k(0.8, **stance_legs("normal", 0.6, "left", 30), right_arm=A(95, 120, 80, 100), left_arm=A(165, 10, 0, 5),
              spine=S(-12, 45), pelvis=P(-4, 30), neck=N(-30, -10)),
            k(1.1, right_arm=A(150, 140, 90, 140), left_arm=A(110, -10, -20, 40), spine=S(-14, 30)),
            k(1.25, **{"right_leg": Lg(3, 0, 20, 2), "left_leg": Lg(3, 0, 20, 2)}, right_arm=A(172, 10, 0, 5),
              left_arm=A(60, -20, -40, 100), spine=S(-4, 0), pelvis=P(0, 0), body=B(air=1.0), neck=N(-30, 0))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), right_arm=A(60, -40, -40, 30), spine=S(25, -40), pelvis=P(4, -25),
               left_leg=leg_at(0.08, 0.14, 0.1, 0.0, 15, "left"), right_leg=Lg(30, 180, 8, 40), neck=N(5)),
             k(tl + 0.04, body=B(air=0.0)),
             k(tl + 0.5, right_arm=A(30, -30, -30, 40), left_arm=A(40, -10, -40, 90), spine=S(15, -20)),
             k(tl + 1.0, **stance_legs("normal", 0.3), right_arm=READY_R, left_arm=READY_R, spine=S(10), pelvis=P(3))]
    return keys


@motion("golf_swing", "Golf full swing (right-handed): address with arms hanging, one-piece takeaway, full "
        "shoulder turn to the top, downswing, impact, high finish facing the target. Combine with "
        "stance(width=wide, depth=0.2).", "action", ARMS + ["spine", "neck"], ["pelvis"])
def _golf():
    grip = grip_keys([(0.0, 0.0, -0.50, 0.32, "down"), (0.6, 0.25, -0.38, 0.28, "down"),
                      (1.15, 0.30, 0.05, 0.14, "down"), (1.45, 0.22, -0.30, 0.30, "down"),
                      (1.6, 0.0, -0.50, 0.32, "down"), (1.8, -0.25, -0.35, 0.28, "down"),
                      (2.15, -0.28, 0.12, 0.12, "down")])
    return grip + [k(0.0, spine=S(35, 0), pelvis=P(10, 0), neck=N(25, 0)),
                   k(0.6, spine=S(35, 40), pelvis=P(10, 15), neck=N(25, -30)),
                   k(1.15, spine=S(32, 88), pelvis=P(10, 40), neck=N(25, -65)),
                   k(1.45, spine=S(34, 40), pelvis=P(10, 0), neck=N(25, -30)),
                   k(1.6, spine=S(35, 5), pelvis=P(10, -25), neck=N(25, -5)),
                   k(1.8, spine=S(28, -45), pelvis=P(8, -40), neck=N(15, 25)),
                   k(2.15, spine=S(5, -85), pelvis=P(2, -55), neck=N(0, 60)),
                   k(2.8, hold=True)]


@motion("bat_swing", "Baseball / softball swing (right-handed): load with hands back by the right shoulder, "
        "stride, rotate the hips then shoulders, level swing through contact, wrap finish.", "action",
        ARMS + ["spine"], ["pelvis", "neck"])
def _bat_swing():
    grip = grip_keys([(0.0, 0.22, 0.05, 0.16, "down"), (0.4, 0.28, 0.10, 0.10, "down"),
                      (0.6, 0.26, 0.04, 0.14, "down"), (0.75, 0.10, -0.15, 0.42, "down"),
                      (0.92, -0.26, -0.05, 0.32, "down"), (1.15, -0.24, 0.20, 0.20, "down")])
    return grip + [k(0.0, spine=S(12, 25), pelvis=P(4, 15), neck=N(5, -60)),
                   k(0.4, spine=S(12, 35), pelvis=P(4, 25), neck=N(5, -65)),
                   k(0.6, pelvis=P(4, -15)),
                   k(0.75, spine=S(12, 0), pelvis=P(4, -40), neck=N(5, -60)),
                   k(0.92, spine=S(10, -55), pelvis=P(4, -50), neck=N(5, -40)),
                   k(1.15, spine=S(8, -75), pelvis=P(4, -55)),
                   k(1.6, hold=True)]


@motion("overhand_throw", "Overhand throw (baseball, football, javelin-style): turn sideways, throwing arm "
        "back in the L position, glove arm points at the target, hips then shoulders rotate, arm whips "
        "over the top, release in front, follow through across the body. Pair with stride_step.",
        "action", ARMS + ["spine"], ["pelvis", "neck"])
def _throw():
    return [k(0.0, right_arm=A(30, 20, -20, 60), left_arm=A(30, 20, -20, 60), spine=S(6, 0), pelvis=P(), neck=N()),
            k(0.45, right_arm=A(80, 150, 80, 95), left_arm=A(88, -10, 0, 20), spine=S(0, 60, 8), pelvis=P(0, 40), neck=N(0, -60)),
            k(0.65, right_arm=A(95, 130, 90, 100), pelvis=P(0, 0), spine=S(-4, 45, 10)),
            k(0.8, right_arm=A(120, 60, 80, 85), left_arm=A(40, 40, 0, 90), spine=S(8, 0, 6), pelvis=P(0, -30), neck=N(0, -5)),
            k(0.9, right_arm=A(100, 5, 0, 25), spine=S(25, -25, 0)),
            k(1.1, right_arm=A(45, -40, -20, 30), left_arm=A(30, 120, 30, 80), spine=S(35, -45, 0), pelvis=P(5, -45), neck=N(10, 20)),
            k(1.6, right_arm=A(20, -10, 0, 25), left_arm=A(20, 40, 0, 30), spine=S(10, -15), pelvis=P(2, -15), neck=N())]


@motion("stride_step", "Throwing / pitching stride: lift the left knee, stride the left foot out toward the "
        "target and land on a bent front knee while the right leg drives and drags behind.", "action",
        LEGS, ["pelvis"])
def _stride():
    return [k(0.0, **stance_legs("normal", 0.1), pelvis=P()),
            k(0.4, left_leg=Lg(70, 10, 8, 90), right_leg=leg_at(0.0, 0.14, 0.1, 0.0, 30, "right")),
            k(0.75, left_leg=leg_at(0.45, 0.12, 0.22, 0.0, 10, "left"), right_leg=Lg(30, 180, 30, 30), pelvis=P(4, -20)),
            k(1.05, right_leg=Lg(36, 175, 20, 55), pelvis=P(6, -40)),
            k(1.6, pelvis=P(6, -40))]


@motion("frisbee_backhand", "Ultimate frisbee backhand throw: reach the disc back across the body to the left "
        "hip, step out, uncoil and pull the arm across the chest, wrist snap, follow through pointing at "
        "the target.", "action", ARMS + ["spine"], ["pelvis", "neck"])
def _frisbee_backhand():
    return [k(0.0, right_arm=A(35, 20, -30, 70), left_arm=A(20, 40, 0, 40), spine=S(10, 0), pelvis=P(3), neck=N()),
            k(0.5, right_arm=arm_at(-0.36, -0.24, 0.40, "out", "right"), left_arm=A(25, 60, 0, 30), spine=S(15, -55),
              pelvis=P(3, -25), neck=N(5, 35)),
            k(0.75, right_arm=arm_at(-0.10, -0.20, 0.40, "out", "right"), spine=S(12, -15), pelvis=P(3, 0)),
            k(0.88, right_arm=arm_at(0.45, -0.12, 0.45, "down", "right"), spine=S(10, 15), pelvis=P(3, 15), neck=N(5, -10)),
            k(1.05, right_arm=arm_at(0.60, -0.08, 0.30, "down", "right"), left_arm=A(25, 150, 0, 30), spine=S(10, 25)),
            k(1.5, right_arm=A(35, 20, -30, 70), left_arm=A(20, 40, 0, 40), spine=S(10, 0), pelvis=P(3), neck=N())]


@motion("frisbee_forehand", "Ultimate frisbee forehand (flick): disc out to the right side at hip height with "
        "the elbow close to the body and the palm up, short arm pull, fast forearm-and-wrist flick toward the "
        "target, short follow-through.", "action", ["right_arm"], ["left_arm", "spine", "pelvis"])
def _frisbee_forehand():
    rest = {"right_arm": A(30, 25, -20, 70), "left_arm": A(20, 30, 0, 40)}
    return [k(0.0, **rest, spine=S(10), pelvis=P(3)),
            # disc out to the right, low and back, elbow tucked by the hip, palm up
            k(0.45, right_arm=arm_at(0.56, -0.38, 0.0, "down", "right"), left_arm=A(35, -20, -30, 50),
              spine=S(12, 28), pelvis=P(3, 14)),
            k(0.66, right_arm=arm_at(0.54, -0.37, 0.14, "down", "right"), spine=S(12, 14)),
            # forearm and wrist flick out in front toward the target
            k(0.78, right_arm=arm_at(0.42, -0.34, 0.42, "down", "right"), spine=S(10, -6), pelvis=P(3, -8)),
            k(0.92, right_arm=arm_at(0.26, -0.30, 0.52, "down", "right"), spine=S(10, -12)),
            k(1.35, **rest, spine=S(10), pelvis=P(3))]


# =============================================================================
# 7. BASKETBALL / VOLLEYBALL / CATCHING
# =============================================================================
@motion("shoot", "Basketball shooting arms: ball up to the set point above the right eye (left hand on the "
        "side), extend the right arm up and forward, snap the wrist, hold the follow-through. Combine "
        "with jump for a jump shot.", "action", ARMS, ["neck"])
def _shoot():
    return [k(0.0, right_arm=arm_at(0.12, -0.25, 0.30, "down", "right"), left_arm=arm_at(-0.05, -0.23, 0.32, "out", "left"), neck=N(-5)),
            k(0.45, right_arm=arm_at(0.12, 0.28, 0.18, "down", "right"), left_arm=arm_at(0.0, 0.30, 0.18, "out", "left"), neck=N(-15)),
            k(0.62, right_arm=A(155, 10, -10, 12), left_arm=A(120, 30, -10, 45)),
            k(1.0, right_arm=A(155, 10, -10, 12), left_arm=A(110, 30, -10, 50)),
            k(1.4, right_arm=HANG, left_arm=HANG, neck=N())]


@motion("dribble", "Basketball dribble with the right hand at waist height: the forearm pushes the ball down "
        "and receives it, eyes up. Combine with a stance or run.", "cycle", ["right_arm"], ["left_arm"],
        period=0.5)
def _dribble():
    return [k(0.0, right_arm=A(35, 40, 10, 80), left_arm=A(50, 30, -20, 60)),
            k(0.22, right_arm=A(25, 40, 10, 30)),
            k(0.32, right_arm=A(28, 40, 10, 45))]


@motion("chest_pass", "Two-handed chest pass: ball at the chest with elbows in, step and push both arms "
        "straight out, thumbs finish down.", "action", ARMS, [])
def _chest_pass():
    return grip_keys([(0.0, 0.0, -0.15, 0.28, "down"), (0.35, 0.0, -0.15, 0.28, "down"),
                      (0.55, 0.0, -0.06, 0.58, "out"), (0.8, 0.0, -0.06, 0.58, "out"),
                      (1.2, 0.0, -0.15, 0.28, "down")], step=0.08)


@motion("layup", "Right-handed basketball layup: two gather steps, jump off the left foot driving the right "
        "knee up, lay the ball up high with the right hand, land on both feet.", "action",
        ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _layup():
    pts, T = _flight(0.85, 0.30)
    keys = [k(0.0, **stance_legs("normal", 0.2), body=B(), right_arm=arm_at(0.12, -0.3, 0.3, "down", "right"),
              left_arm=arm_at(-0.05, -0.28, 0.32, "out", "left"), spine=S(10), pelvis=P(3), neck=N()),
            k(0.35, right_leg=leg_at(0.25, 0.14, 0.12, 0, 10, "right"), left_leg=Lg(25, 180, 8, 60), spine=S(14)),
            k(0.7, left_leg=leg_at(0.2, 0.14, 0.2, 0, 10, "left"), right_leg=Lg(25, 180, 8, 70), spine=S(18)),
            k(0.85, left_leg=Lg(5, 180, 8, 5), right_leg=Lg(85, 0, 8, 95), body=B(air=1.0), spine=S(0),
              right_arm=A(150, 10, -10, 30), left_arm=A(120, 20, -10, 60), neck=N(-20))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    keys[-1][1]["right_arm"] = A(165, 8, -5, 8)
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), right_leg=Lg(10, 0, 8, 10), left_leg=Lg(5, 0, 8, 10),
               right_arm=A(90, 10, 0, 20), left_arm=A(70, 20, 0, 40)),
             k(tl + 0.04, body=B(air=0.0)),
             k(tl + 0.35, **stance_legs("normal", 0.6), spine=S(20), right_arm=A(40, 20, -10, 40), left_arm=A(40, 20, -10, 40), neck=N()),
             k(tl + 0.8, **stance_legs("normal", 0.15), spine=S(6), right_arm=HANG, left_arm=HANG)]
    return keys


@motion("volleyball_set", "Volleyball overhead set: hands up above the forehead in a window, absorb the ball "
        "by bending the elbows, extend both arms up and forward together.", "action", ARMS, ["neck"])
def _vb_set():
    window = {"right_arm": arm_at(0.12, 0.32, 0.30, "out", "right"), "left_arm": arm_at(0.12, 0.32, 0.30, "out", "left")}
    absorb = {"right_arm": arm_at(0.12, 0.26, 0.24, "out", "right"), "left_arm": arm_at(0.12, 0.26, 0.24, "out", "left")}
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, neck=N()),
            k(0.4, **window, neck=N(-20)), k(0.6, **absorb), k(0.8, right_arm=A(160, 10, 0, 10), left_arm=A(160, 10, 0, 10)),
            k(1.1, right_arm=A(160, 10, 0, 10), left_arm=A(160, 10, 0, 10)),
            k(1.5, right_arm=READY_R, left_arm=READY_R, neck=N())]


@motion("forearm_pass", "Volleyball forearm pass (bump): arms straight and together in a platform below the "
        "waist, a small shoulder lift through contact, hold the platform toward the target.", "action",
        ARMS, ["spine"])
def _bump():
    return ([k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(18)), k(0.35, spine=S(22)), k(0.6, spine=S(14)),
             k(1.35, right_arm=READY_R, left_arm=READY_R, spine=S(18))] +
            grip_keys([(0.35, 0.0, -0.55, 0.34, "out"), (0.6, 0.0, -0.38, 0.46, "out"),
                       (0.95, 0.0, -0.38, 0.46, "out")], step=0.08))


@motion("spike_arms", "Volleyball spike arm swing: both arms swing back, then up; the right arm draws back "
        "like a bow, whips through high contact and snaps down across the body. Combine with jump.",
        "action", ARMS + ["spine"], ["neck"])
def _spike_arms():
    return [k(0.0, right_arm=HANG, left_arm=HANG, spine=S(6)),
            k(0.38, right_arm=A(45, 175, 10, 12), left_arm=A(45, 175, 10, 12), spine=S(30)),
            k(0.48, right_arm=A(40, 20, 0, 15), left_arm=A(40, 0, 0, 15)),
            k(0.6, right_arm=A(150, 110, 80, 110), left_arm=A(150, 10, 0, 15), spine=S(-10, 30), neck=N(-25)),
            k(0.78, right_arm=A(170, 15, 0, 15), left_arm=A(70, -20, -30, 80), spine=S(0, 0)),
            k(0.95, right_arm=A(70, -25, -20, 25), left_arm=A(40, -10, -30, 90), spine=S(25, -25), neck=N(10)),
            k(1.5, right_arm=HANG, left_arm=HANG, spine=S(6), neck=N())]


@motion("catch", "Catch a ball at chest height: hands reach out with thumbs together, absorb it back into the "
        "chest.", "action", ARMS, [])
def _catch():
    return ([k(0.0, right_arm=READY_R, left_arm=READY_R)] +
            grip_keys([(0.35, 0.0, -0.05, 0.52, "out"), (0.5, 0.0, -0.05, 0.52, "out"),
                       (0.8, 0.0, -0.15, 0.28, "down"), (1.2, 0.0, -0.15, 0.28, "down")], step=0.08))


@motion("touch_low", "Reach the right hand down to touch a cone / the floor in front: hinge and bend, touch, "
        "rise. Combine with a stance (depth 0.6+) for a lower body position.", "action", ["right_arm", "spine"],
        ["left_arm", "right_leg", "left_leg", "pelvis"])
def _touch_low():
    up = stance_legs("normal", 0.15)
    low = stance_legs("wide", 0.75)
    return [k(0.0, **up, right_arm=HANG, left_arm=HANG, spine=S(8), pelvis=P(3)),
            k(0.5, **low, right_arm=A(70, 10, 0, 5), left_arm=A(40, 120, 0, 30), spine=S(62, -10), pelvis=P(14)),
            k(0.7, right_arm=A(72, 10, 0, 5)),
            k(1.2, **up, right_arm=HANG, left_arm=HANG, spine=S(8), pelvis=P(3))]


# =============================================================================
# 8. BOXING / STRIKING (arms - combine with fighting_stance and guard)
# =============================================================================
@motion("jab", "Boxing jab with the lead (left) hand: snap the fist straight out at shoulder height, elbow "
        "behind it, and straight back to the guard.", "action", ["left_arm"], ["spine"])
def _jab():
    return [k(0.0, left_arm=GUARD_L, spine=S(8, 12)), k(0.14, left_arm=A(86, -4, -20, 4), spine=S(10, 4)),
            k(0.22, hold=True), k(0.42, left_arm=GUARD_L, spine=S(8, 12))]


@motion("cross", "Boxing cross with the rear (right) hand: rotate the hips and shoulders, drive the fist "
        "straight out at shoulder height, return to the guard.", "action", ["right_arm", "spine"], ["pelvis"])
def _cross():
    return [k(0.0, right_arm=GUARD_R, spine=S(8, 12), pelvis=P(2, 20)),
            k(0.18, right_arm=A(86, -8, -20, 4), spine=S(12, -25), pelvis=P(2, -15)),
            k(0.28, hold=True),
            k(0.52, right_arm=GUARD_R, spine=S(8, 12), pelvis=P(2, 20))]


@motion("hook", "Boxing lead (left) hook: elbow lifts to shoulder height with the arm bent 90 degrees, the "
        "shoulders and hips rotate right to swing the fist across, back to the guard.", "action",
        ["left_arm", "spine"], ["pelvis"])
def _hook():
    return [k(0.0, left_arm=GUARD_L, spine=S(8, 12), pelvis=P(2, 20)),
            k(0.12, left_arm=A(80, 50, 90, 95), spine=S(8, 25)),
            k(0.28, left_arm=A(85, -10, 90, 95), spine=S(8, -15), pelvis=P(2, -10)),
            k(0.5, left_arm=GUARD_L, spine=S(8, 12), pelvis=P(2, 20))]


@motion("uppercut", "Boxing rear (right) uppercut: dip and turn slightly right, drive the fist up from "
        "below the chest with the palm facing in, elbow bent, return to the guard.", "action",
        ["right_arm", "spine"], ["pelvis"])
def _uppercut():
    return [k(0.0, right_arm=GUARD_R, spine=S(8, 12), pelvis=P(2, 20)),
            k(0.18, right_arm=A(30, 10, -40, 100), spine=S(14, 25, 6), pelvis=P(4, 25)),
            k(0.34, right_arm=A(72, -12, -60, 80), spine=S(0, -20, -4), pelvis=P(0, -10)),
            k(0.44, hold=True),
            k(0.68, right_arm=GUARD_R, spine=S(8, 12), pelvis=P(2, 20))]


# =============================================================================
# 9. SWIMMING (full body, horizontal)
# =============================================================================
SWIM_BODY = B(pitch=86, air=1.0, root=0.0)


@motion("freestyle", "Freestyle / front crawl: alternating overarm pulls with body roll and a steady flutter "
        "kick, face down.", "cycle", ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [], period=1.4)
def _freestyle():
    T = 1.4
    reach, pull, push, rec = A(170, 6, 0, 8), A(95, 0, -10, 70), A(20, 175, 0, 15), A(115, 100, 60, 95)
    kick_a = {"right_leg": Lg(12, 0, 0, 20), "left_leg": Lg(10, 180, 0, 5)}
    kick_b = {"right_leg": Lg(10, 180, 0, 5), "left_leg": Lg(12, 0, 0, 20)}
    return [k(0.0, body=SWIM_BODY, right_arm=reach, left_arm=push, spine=S(0, 30), pelvis=P(0, 15), neck=N(-25, 0), **kick_a),
            k(T * 0.125, **kick_b),
            k(T * 0.25, right_arm=pull, left_arm=rec, spine=S(0, 0), pelvis=P(0, 0), neck=N(-25, 0), **kick_a),
            k(T * 0.375, **kick_b),
            k(T * 0.5, right_arm=push, left_arm=reach, spine=S(0, -30), pelvis=P(0, -15), neck=N(-25, 0), **kick_a),
            k(T * 0.625, **kick_b),
            k(T * 0.75, right_arm=rec, left_arm=pull, spine=S(0, 0), pelvis=P(0, 0), neck=N(-25, 40), **kick_a),
            k(T * 0.875, **kick_b)]


@motion("breaststroke", "Breaststroke: arms sweep out and in under the chest while the head lifts, heels draw "
        "up to the hips, whip kick back to a long streamline glide.", "cycle",
        ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [], period=1.6)
def _breaststroke():
    glide = {"right_arm": A(170, 6, 0, 5), "left_arm": A(170, 6, 0, 5), "right_leg": Lg(0, 0, 0, 0),
             "left_leg": Lg(0, 0, 0, 0), "neck": N(-15), "spine": S(0)}
    return [k(0.0, body=SWIM_BODY, **glide),
            k(0.4, right_arm=A(150, 60, 20, 15), left_arm=A(150, 60, 20, 15)),
            k(0.65, right_arm=A(90, 20, -40, 100), left_arm=A(90, 20, -40, 100), neck=N(-45), spine=S(-12),
              right_leg=Lg(35, 20, 30, 115), left_leg=Lg(35, 20, 30, 115)),
            k(0.85, right_arm=A(120, 10, -20, 80), left_arm=A(120, 10, -20, 80), right_leg=Lg(25, 45, 30, 70),
              left_leg=Lg(25, 45, 30, 70), neck=N(-20), spine=S(0)),
            k(1.05, **glide)]


@motion("butterfly", "Butterfly: both arms pull together under the body and recover over the water, with a "
        "two-beat dolphin kick and the chest pressing down.", "cycle",
        ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [], period=1.3)
def _butterfly():
    return [k(0.0, body=SWIM_BODY, right_arm=A(165, 30, 0, 8), left_arm=A(165, 30, 0, 8), spine=S(6), neck=N(-15),
              right_leg=Lg(15, 0, 0, 40), left_leg=Lg(15, 0, 0, 40), pelvis=P(-8)),
            k(0.3, right_arm=A(95, 10, -20, 70), left_arm=A(95, 10, -20, 70), right_leg=Lg(5, 180, 0, 0),
              left_leg=Lg(5, 180, 0, 0), pelvis=P(6), spine=S(-4)),
            k(0.55, right_arm=A(20, 170, 0, 10), left_arm=A(20, 170, 0, 10), neck=N(-40), right_leg=Lg(12, 0, 0, 35),
              left_leg=Lg(12, 0, 0, 35), pelvis=P(-6)),
            k(0.85, right_arm=A(100, 95, 0, 20), left_arm=A(100, 95, 0, 20), right_leg=Lg(5, 180, 0, 0),
              left_leg=Lg(5, 180, 0, 0), neck=N(-10), pelvis=P(6))]


@motion("backstroke", "Backstroke: face up, alternating straight-arm recovery over the head and pull at the "
        "side, body roll and flutter kick.", "cycle", ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [],
        period=1.5)
def _backstroke():
    body = B(pitch=-86, air=1.0, root=0.0)
    kick_a = {"right_leg": Lg(12, 0, 0, 20), "left_leg": Lg(8, 180, 0, 5)}
    kick_b = {"right_leg": Lg(8, 180, 0, 5), "left_leg": Lg(12, 0, 0, 20)}
    return [k(0.0, body=body, right_arm=A(172, 15, 0, 5), left_arm=A(15, 60, 0, 10), spine=S(0, -25), neck=N(10), **kick_a),
            k(0.375, right_arm=A(110, 90, -60, 90), left_arm=A(90, 0, 0, 5), spine=S(0, 0), **kick_b),
            k(0.75, right_arm=A(15, 60, 0, 10), left_arm=A(172, 15, 0, 5), spine=S(0, 25), **kick_a),
            k(1.125, right_arm=A(90, 0, 0, 5), left_arm=A(110, 90, -60, 90), spine=S(0, 0), **kick_b)]


# =============================================================================
# 10. GESTURES
# =============================================================================
@motion("wave", "Wave with the right hand raised beside the head.", "cycle", ["right_arm"], [], period=0.8)
def _wave():
    return [k(0.0, right_arm=A(100, 80, 90, 60)), k(0.4, right_arm=A(100, 80, 70, 25))]


@motion("point", "Point forward with the right arm straight at shoulder height.", "pose", ["right_arm"])
def _point():
    return [k(0.0, right_arm=A(88, 5, 0, 4))]


@motion("clap", "Clap the hands in front of the chest.", "cycle", ARMS, [], period=0.5)
def _clap():
    apart = {"right_arm": arm_at(0.25, -0.15, 0.35, "down", "right"), "left_arm": arm_at(0.25, -0.15, 0.35, "down", "left")}
    tog = {"right_arm": arm_at(0.03, -0.15, 0.38, "down", "right"), "left_arm": arm_at(0.03, -0.15, 0.38, "down", "left")}
    return [k(0.0, **apart), k(0.25, **tog)]


@motion("arm_circles", "Arm circles: both arms out to the sides drawing small circles.", "cycle", ARMS, [], period=0.8)
def _arm_circles():
    return [k(0.0, right_arm=A(90, 85, 0, 5), left_arm=A(90, 85, 0, 5)),
            k(0.2, right_arm=A(100, 75, 0, 5), left_arm=A(100, 75, 0, 5)),
            k(0.4, right_arm=A(90, 65, 0, 5), left_arm=A(90, 65, 0, 5)),
            k(0.6, right_arm=A(80, 75, 0, 5), left_arm=A(80, 75, 0, 5))]


# =============================================================================
# 11. MORE PLYOMETRICS / CONDITIONING
# =============================================================================
def _lunge_pose(front: str) -> Dict[str, Dict[str, float]]:
    back = "left" if front == "right" else "right"
    return {f"{front}_leg": leg_at(0.36, 0.14, 0.34, 0.0, 6, front), f"{back}_leg": Lg(24, 180, 4, 98)}


@motion("lunge_jump", "Jumping (split) lunges: from a low lunge, explode straight up, switch legs in the air "
        "and land softly in a lunge with the other leg forward - no standing up in between.", "cycle",
        LEGS + ["body"], ARMS + ["spine", "pelvis"], period=1.3)
def _lunge_jump():
    pts, T = _flight(0.2, 0.16)
    keys = [k(0.0, **_lunge_pose("right"), body=B(air=0.0, root=0.0), right_arm=A(30, 175, 10, 40),
              left_arm=A(45, 6, -15, 60), spine=S(6), pelvis=P(2))]
    keys.append(k(0.2, right_leg=leg_at(0.15, 0.14, 0.05, 0, 6, "right"), left_leg=Lg(12, 180, 4, 30),
                  body=B(air=1.0, root=0.0), right_arm=A(70, 6, -10, 40), left_arm=A(70, 6, -10, 40)))
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    mid = pts[len(pts) // 2][0]
    keys.append(k(mid, right_leg=Lg(10, 0, 4, 30), left_leg=Lg(10, 0, 4, 30)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), right_leg=Lg(18, 180, 4, 40), left_leg=leg_at(0.3, 0.14, 0.05, 0, 6, "left")),
             k(tl + 0.03, body=B(air=0.0)),
             k(0.65, **_lunge_pose("left"), left_arm=A(30, 175, 10, 40), right_arm=A(45, 6, -15, 60))]
    pts2, _ = _flight(0.85, 0.16)
    keys.append(k(0.85, left_leg=leg_at(0.15, 0.14, 0.05, 0, 6, "left"), right_leg=Lg(12, 180, 4, 30),
                  body=B(air=1.0, root=0.0), right_arm=A(70, 6, -10, 40), left_arm=A(70, 6, -10, 40)))
    for t, r in pts2[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    keys.append(k(pts2[len(pts2) // 2][0], right_leg=Lg(10, 0, 4, 30), left_leg=Lg(10, 0, 4, 30)))
    keys += [k(pts2[-1][0], body=B(air=1.0, root=0.0), left_leg=Lg(18, 180, 4, 40), right_leg=leg_at(0.3, 0.14, 0.05, 0, 6, "right")),
             k(pts2[-1][0] + 0.03, body=B(air=0.0))]
    return keys


@motion("split_squat", "Split squat (static lunge): feet staggered, lower straight down until the back knee "
        "nearly touches the floor, drive back up. No step.", "cycle", LEGS + ["pelvis"], ARMS + ["spine"], period=2.0)
def _split_squat():
    up = {"right_leg": leg_at(0.36, 0.14, 0.08, 0, 6, "right"), "left_leg": Lg(20, 180, 4, 22)}
    return [k(0.0, **up, spine=S(4), right_arm=A(15, 100, 40, 70), left_arm=A(15, 100, 40, 70)),
            k(0.9, **_lunge_pose("right")), k(1.1, hold=True)]


@motion("broad_jump", "Standing broad (long) jump: big arm swing back, hips load, explode forward and up, "
        "knees tuck forward in flight, land deep with arms forward.", "action", LEGS + ["body"], ARMS + ["spine", "pelvis"])
def _broad_jump():
    pts, T = _flight(0.6, 0.22)
    keys = [k(0.0, **stance_legs("normal", 0.15), body=B(), right_arm=HANG, left_arm=HANG, spine=S(4), pelvis=P()),
            k(0.42, **stance_legs("normal", 0.9), right_arm=A(55, 175, 10, 12), left_arm=A(55, 175, 10, 12), spine=S(45), pelvis=P(10)),
            k(0.52, right_arm=A(30, 0, 0, 10), left_arm=A(30, 0, 0, 10)),
            k(0.6, right_leg=Lg(25, 180, 8, 8), left_leg=Lg(25, 180, 8, 8), body=B(pitch=15, air=1.0), spine=S(15),
              right_arm=A(150, 6, 0, 10), left_arm=A(150, 6, 0, 10))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(pitch=8, air=1.0, root=r)))
    mid = pts[len(pts) // 2][0]
    keys.append(k(mid, right_leg=Lg(70, 0, 8, 70), left_leg=Lg(70, 0, 8, 70), right_arm=A(110, 6, 0, 15), left_arm=A(110, 6, 0, 15)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), right_leg=leg_at(0.15, 0.17, 0.1, 0.05, 10, "right"),
               left_leg=leg_at(0.15, 0.17, 0.1, 0.05, 10, "left"), right_arm=A(80, 6, 0, 15), left_arm=A(80, 6, 0, 15)),
             k(tl + 0.03, body=B(air=0.0)),
             k(tl + 0.3, **stance_legs("normal", 0.95), spine=S(40), right_arm=A(75, 6, 0, 15), left_arm=A(75, 6, 0, 15)),
             k(tl + 0.8, **stance_legs("normal", 0.15), spine=S(4), right_arm=HANG, left_arm=HANG)]
    return keys


@motion("single_leg_hop", "Hops on the right leg in place, the left knee bent behind, arms swinging for balance.",
        "cycle", LEGS + ["body"], ARMS + ["spine"], period=0.55)
def _sl_hop():
    return [k(0.0, right_leg=Lg(6, 0, 8, 22), left_leg=Lg(15, 180, 8, 90), body=B(air=0.0, root=0.0),
              right_arm=A(35, 170, 10, 70), left_arm=A(40, 6, -15, 70), spine=S(8)),
            k(0.14, right_leg=Lg(3, 0, 8, 5), body=B(air=1.0, root=0.0)),
            k(0.27, body=B(air=1.0, root=0.07), right_arm=A(45, 6, -15, 70), left_arm=A(35, 170, 10, 70)),
            k(0.4, body=B(air=1.0, root=0.0), right_leg=Lg(4, 0, 8, 8)),
            k(0.44, body=B(air=0.0))]


@motion("side_hops", "Two-foot lateral hops side to side over a line, quick and light, knees soft.", "cycle",
        LEGS + ["body", "pelvis"], ARMS + ["spine"], period=0.8)
def _side_hops():
    land = stance_legs("narrow", 0.45)
    fly = {"right_leg": Lg(12, 0, 8, 35), "left_leg": Lg(12, 0, 8, 35)}
    arms = {"right_arm": A(35, 40, -15, 70), "left_arm": A(35, 40, -15, 70)}
    return [k(0.0, **land, body=B(air=0.0, roll=0), pelvis=P(4), spine=S(14), **arms),
            k(0.12, body=B(air=1.0, roll=-6)), k(0.2, **fly, body=B(air=1.0, root=0.06, roll=-8)),
            k(0.3, body=B(air=1.0, root=0.0, roll=-4)), k(0.34, **land, body=B(air=0.0, roll=0)),
            k(0.52, body=B(air=1.0, roll=6)), k(0.6, **fly, body=B(air=1.0, root=0.06, roll=8)),
            k(0.7, body=B(air=1.0, root=0.0, roll=4)), k(0.74, **land, body=B(air=0.0, roll=0))]


@motion("star_jump", "Star jump: crouch, then explode up spreading arms and legs into an X, land with feet "
        "together.", "action", LEGS + ARMS + ["body"], ["spine"])
def _star_jump():
    pts, T = _flight(0.45, 0.25)
    keys = [k(0.0, **stance_legs("narrow", 0.1), right_arm=HANG, left_arm=HANG, body=B(), spine=S(4)),
            k(0.35, **stance_legs("narrow", 0.9), right_arm=A(30, 10, 0, 20), left_arm=A(30, 10, 0, 20), spine=S(30)),
            k(0.45, right_leg=Lg(3, 0, 8, 3), left_leg=Lg(3, 0, 8, 3), body=B(air=1.0), spine=S(3))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    mid = pts[len(pts) // 2][0]
    keys.append(k(mid, right_leg=Lg(28, 90, 10, 3), left_leg=Lg(28, 90, 10, 3), right_arm=A(140, 85, 0, 5),
                  left_arm=A(140, 85, 0, 5)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), right_leg=Lg(3, 90, 8, 5), left_leg=Lg(3, 90, 8, 5),
               right_arm=A(60, 85, 0, 10), left_arm=A(60, 85, 0, 10)),
             k(tl + 0.03, body=B(air=0.0)),
             k(tl + 0.3, **stance_legs("narrow", 0.5), spine=S(18), right_arm=A(30, 40, 0, 20), left_arm=A(30, 40, 0, 20)),
             k(tl + 0.7, **stance_legs("narrow", 0.1), spine=S(4), right_arm=HANG, left_arm=HANG)]
    return keys


@motion("calf_raise", "Calf raises: rise up onto the toes, pause, lower the heels.", "cycle", LEGS + ["body"],
        ARMS, period=1.6)
def _calf_raise():
    legs = {"right_leg": Lg(0, 0, 8, 3), "left_leg": Lg(0, 0, 8, 3)}
    return [k(0.0, **legs, body=B(root=0.0), right_arm=HANG, left_arm=HANG), k(0.6, body=B(root=0.07)),
            k(0.9, hold=True), k(1.5, body=B(root=0.0))]


@motion("bear_crawl", "Bear crawl in place: on hands and feet with the knees hovering just off the floor, "
        "opposite hand and foot step forward together.", "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"],
        period=1.0)
def _bear_crawl():
    a = {"right_arm": A(80, 4, 0, 8), "left_arm": A(66, 4, 0, 8), "right_leg": Lg(78, 0, 4, 105), "left_leg": Lg(95, 0, 4, 110)}
    b = {"right_arm": A(66, 4, 0, 8), "left_arm": A(80, 4, 0, 8), "right_leg": Lg(95, 0, 4, 110), "left_leg": Lg(78, 0, 4, 105)}
    return [k(0.0, body=B(70), spine=S(0), pelvis=P(), neck=N(-20), **a), k(0.5, **b)]


@motion("glute_bridge", "Glute bridge: lying on the back with knees bent, drive the hips up until knees, hips and "
        "shoulders line up, lower slowly.", "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"], period=2.0)
def _glute_bridge():
    arms = {"right_arm": A(15, 60, 0, 5), "left_arm": A(15, 60, 0, 5)}
    return [k(0.0, body=B(-86), spine=S(0), pelvis=P(), right_leg=Lg(50, 0, 6, 100), left_leg=Lg(50, 0, 6, 100), neck=N(20), **arms),
            k(0.9, body=B(-62), right_leg=Lg(28, 0, 6, 80), left_leg=Lg(28, 0, 6, 80)), k(1.2, hold=True)]


@motion("sit_up", "Sit-up / crunch: lying on the back with knees bent and arms crossed on the chest, curl the "
        "trunk up, lower back down.", "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"], period=2.0)
def _sit_up():
    arms = {"right_arm": arm_at(-0.12, -0.15, 0.20, "down", "right"), "left_arm": arm_at(-0.12, -0.10, 0.22, "down", "left")}
    return [k(0.0, body=B(-86), spine=S(0), pelvis=P(), right_leg=Lg(50, 0, 6, 100), left_leg=Lg(50, 0, 6, 100), neck=N(15), **arms),
            k(0.9, spine=S(55), neck=N(25)), k(1.1, hold=True)]


@motion("superman", "Superman hold: lying face down, lift the straight arms overhead and the legs off the floor.",
        "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _superman():
    return [k(0.0, body=B(88), spine=S(-14), pelvis=P(), right_arm=A(165, 20, 0, 5), left_arm=A(165, 20, 0, 5),
              right_leg=Lg(14, 180, 4, 3), left_leg=Lg(14, 180, 4, 3), neck=N(-25))]


@motion("russian_twist", "Russian twist: seated leaning back with feet raised, hands together, rotate the trunk "
        "side to side.", "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"], period=1.4)
def _russian_twist():
    legs = {"right_leg": Lg(70, 0, 4, 85), "left_leg": Lg(70, 0, 4, 85)}
    hands = {"right_arm": arm_at(0.0, -0.32, 0.38, "down", "right"), "left_arm": arm_at(0.0, -0.32, 0.38, "down", "left")}
    return [k(0.0, body=B(-45), spine=S(10, 40), pelvis=P(), neck=N(10, 20), **legs, **hands),
            k(0.7, spine=S(10, -40), neck=N(10, -20))]


@motion("torso_twist", "Standing torso twists: feet planted, arms bent at chest height, rotate the shoulders "
        "left and right.", "cycle", ARMS + ["spine"], ["pelvis", "neck"], period=1.6)
def _torso_twist():
    arms = {"right_arm": A(80, 50, 90, 100), "left_arm": A(80, 50, 90, 100)}
    return [k(0.0, **arms, spine=S(3, 55), pelvis=P(0, 15), neck=N(0, 20)), k(0.8, spine=S(3, -55), pelvis=P(0, -15), neck=N(0, -20))]


# =============================================================================
# 12. STRETCHING / YOGA
# =============================================================================
@motion("hamstring_stretch", "Standing hamstring stretch: legs straight, hinge forward and reach the hands down "
        "toward the toes, hold.", "pose", LEGS + ARMS + ["spine", "pelvis"], ["neck"])
def _ham_stretch():
    return [k(0.0, right_leg=Lg(0, 0, 8, 2), left_leg=Lg(0, 0, 8, 2), spine=S(80), pelvis=P(25),
              right_arm=A(85, -5, 0, 4), left_arm=A(85, -5, 0, 4), neck=N(10))]


@motion("quad_stretch", "Standing quad stretch: balance on the left leg, the right heel pulled to the glutes "
        "by the right hand, left arm out for balance.", "pose", LEGS + ARMS, ["spine"])
def _quad_stretch():
    return [k(0.0, right_leg=Lg(5, 180, 8, 150), left_leg=Lg(0, 0, 8, 5), right_arm=A(30, 170, 20, 30),
              left_arm=A(80, 60, 0, 10), spine=S(3))]


@motion("arm_cross_stretch", "Shoulder stretch: the right arm straight across the chest, held by the left forearm.",
        "pose", ARMS)
def _arm_cross():
    return [k(0.0, right_arm=arm_at(-0.36, 0.0, 0.32, "forward", "right"), left_arm=arm_at(0.0, -0.06, 0.36, "down", "left"))]


@motion("warrior_pose", "Yoga warrior II: wide stance, right knee bent over the ankle, left leg straight, arms "
        "extended out at shoulder height, gaze over the right hand.", "pose", LEGS + ARMS + ["spine", "pelvis", "neck"])
def _warrior():
    return [k(0.0, right_leg=leg_at(0.0, 0.48, 0.25, 0, 70, "right"), left_leg=leg_at(0.0, 0.42, 0.0, 0, 10, "left"),
              right_arm=A(88, 90, 0, 3), left_arm=A(88, 90, 0, 3), spine=S(2), pelvis=P(0, 0), neck=N(0, 75))]


@motion("tree_pose", "Yoga tree pose: stand on the left leg, the right foot against the inner left thigh with "
        "the knee turned out, hands together overhead.", "pose", LEGS + ARMS, ["spine"])
def _tree():
    return [k(0.0, right_leg=Lg(40, 80, 60, 135), left_leg=Lg(0, 0, 8, 3), right_arm=A(170, 15, 0, 15),
              left_arm=A(170, 15, 0, 15), spine=S(2))]


# =============================================================================
# 13. TRACK / AGILITY
# =============================================================================
@motion("sprint_start", "Track sprint start on land (NOT swimming): crouched start with the left foot forward and the trunk low, drive out "
        "with powerful arm action into the first strides.", "action", LEGS + ["body", "pelvis"], ARMS + ["spine"])
def _sprint_start():
    return [k(0.0, right_leg=Lg(45, 0, 6, 110), left_leg=Lg(85, 0, 6, 120), body=B(pitch=30), spine=S(35), pelvis=P(10),
              right_arm=A(55, 6, 0, 15), left_arm=A(55, 6, 0, 15)),
            k(0.4, hold=True),
            k(0.62, right_leg=Lg(70, 0, 6, 100), left_leg=Lg(30, 180, 6, 10), body=B(pitch=28), spine=S(20),
              right_arm=A(50, 175, 10, 70), left_arm=A(70, 6, -15, 90)),
            k(0.9, right_leg=Lg(25, 180, 6, 15), left_leg=Lg(70, 0, 6, 100), body=B(pitch=22),
              right_arm=A(70, 6, -15, 90), left_arm=A(50, 175, 10, 70)),
            k(1.2, right_leg=Lg(70, 0, 6, 100), left_leg=Lg(25, 180, 6, 15), body=B(pitch=15),
              right_arm=A(50, 175, 10, 70), left_arm=A(70, 6, -15, 90)),
            k(1.5, right_leg=Lg(20, 180, 6, 20), left_leg=Lg(60, 0, 6, 90), body=B(pitch=8), spine=S(12),
              right_arm=A(65, 6, -15, 90), left_arm=A(45, 175, 10, 70))]


@motion("hurdle_step", "Hurdle clearance: the lead (right) leg drives up and extends over the hurdle, the trail leg "
        "swings out to the side with the knee high, opposite arm reaches forward.", "action", LEGS + ["body"],
        ARMS + ["spine", "pelvis"])
def _hurdle():
    pts, T = _flight(0.3, 0.18)
    keys = [k(0.0, right_leg=Lg(20, 180, 8, 30), left_leg=Lg(10, 0, 8, 15), body=B(), spine=S(10),
              right_arm=A(30, 6, -10, 70), left_arm=A(30, 175, 10, 70)),
            k(0.3, right_leg=Lg(80, 0, 6, 90), left_leg=Lg(15, 180, 8, 10), body=B(air=1.0), spine=S(25),
              left_arm=A(85, 6, 0, 15), right_arm=A(30, 170, 10, 60))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    mid = pts[len(pts) // 2][0]
    keys.append(k(mid, right_leg=Lg(85, 0, 6, 10), left_leg=Lg(60, 100, 40, 100), spine=S(40)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), right_leg=Lg(10, 0, 6, 8), left_leg=Lg(70, 30, 20, 100), spine=S(20)),
             k(tl + 0.03, body=B(air=0.0)),
             k(tl + 0.35, right_leg=Lg(15, 180, 8, 25), left_leg=Lg(60, 0, 6, 80), spine=S(10),
               right_arm=A(45, 6, -15, 80), left_arm=A(30, 175, 10, 70))]
    return keys


@motion("a_skip", "A-skip running drill: a small skip on the support leg while the other knee drives to hip "
        "height with the toes up, alternating, with crisp arm action.", "cycle", LEGS + ["body"], ARMS + ["spine"],
        period=0.9)
def _a_skip():
    up_r = {"right_leg": Lg(85, 0, 6, 95), "left_leg": Lg(3, 0, 8, 8)}
    up_l = {"left_leg": Lg(85, 0, 6, 95), "right_leg": Lg(3, 0, 8, 8)}
    return [k(0.0, **up_r, body=B(air=0.0, root=0.0), right_arm=A(30, 175, 10, 85), left_arm=A(65, 6, -15, 90), spine=S(3)),
            k(0.12, body=B(air=1.0, root=0.04)), k(0.22, body=B(air=0.0, root=0.0)),
            k(0.45, **up_l, right_arm=A(65, 6, -15, 90), left_arm=A(30, 175, 10, 85)),
            k(0.57, body=B(air=1.0, root=0.04)), k(0.67, body=B(air=0.0, root=0.0))]


@motion("crossover_step", "Crossover step to the right: pivot the hips toward the right and drive the left leg "
        "across in front, arms pumping (first step of a lateral sprint).", "action", LEGS + ["pelvis"],
        ARMS + ["spine"])
def _crossover():
    return [k(0.0, **stance_legs("normal", 0.45), pelvis=P(5), spine=S(15), right_arm=READY_R, left_arm=READY_R),
            k(0.25, pelvis=P(5, 50), spine=S(18, 40), right_leg=leg_at(0.0, 0.24, 0.18, 0, 60, "right"),
              left_leg=Lg(60, -40, 20, 90), right_arm=A(40, 160, 10, 70), left_arm=A(60, -10, -15, 85)),
            k(0.55, left_leg=leg_at(0.2, -0.05, 0.15, 0, 30, "left"), right_leg=Lg(25, 150, 30, 40),
              pelvis=P(5, 60), spine=S(18, 55), right_arm=A(60, -10, -15, 85), left_arm=A(40, 160, 10, 70)),
            k(0.9, hold=True)]


@motion("defensive_stance", "Basketball defensive stance: wide and low, back straight, weight on the balls of the "
        "feet, arms out wide with active hands. Optional slide.", "pose", LEGS + ARMS + ["spine", "pelvis"], [],
        params={"bounce": ("off", ("off", "on"))}, loop_pose=True)
def _def_stance(bounce="off"):
    legs = stance_legs("very_wide", 0.75)
    keys = [k(0.0, **legs, pelvis=P(10), spine=S(28), right_arm=A(55, 75, 20, 30), left_arm=A(55, 75, 20, 30))]
    if bounce == "on":
        keys += [k(0.2, **stance_legs("very_wide", 0.85)), k(0.4, **legs)]
    return keys


# =============================================================================
# 14. MORE SPORT SKILLS
# =============================================================================
@motion("header", "Soccer header: arch back slightly with the eyes on the ball, then snap the trunk and neck "
        "forward to strike with the forehead. Combine with jump for a jumping header.", "action",
        ["spine", "neck"], ARMS)
def _header():
    return [k(0.0, spine=S(4), neck=N(0), right_arm=A(30, 40, 0, 40), left_arm=A(30, 40, 0, 40)),
            k(0.4, spine=S(-18), neck=N(-30), right_arm=A(70, 50, 0, 50), left_arm=A(70, 50, 0, 50)),
            k(0.58, spine=S(22), neck=N(15), right_arm=A(40, 120, 0, 40), left_arm=A(40, 120, 0, 40)),
            k(1.0, spine=S(4), neck=N(0), right_arm=A(30, 40, 0, 40), left_arm=A(30, 40, 0, 40))]


@motion("throw_in", "Soccer throw-in / two-hand overhead throw: ball held with both hands behind the head, "
        "arch the back, whip both arms forward over the head and release.", "action", ARMS + ["spine"], ["neck"])
def _throw_in():
    return (grip_keys([(0.0, 0.0, -0.10, 0.30, "down"), (0.2, 0.0, 0.40, 0.34, "out"), (0.32, 0.0, 0.60, 0.14, "out"),
                       (0.45, 0.0, 0.60, -0.06, "out"),
                       (0.7, 0.0, 0.55, 0.22, "out"), (0.85, 0.0, 0.10, 0.55, "out"), (1.2, 0.0, -0.05, 0.50, "out")], step=0.07)
            + [k(0.0, spine=S(4)), k(0.45, spine=S(-20)), k(0.85, spine=S(25)), k(1.2, spine=S(15))])


@motion("bounce_pass", "Two-handed bounce pass: ball at the chest, step and push both arms out and down so the "
        "ball bounces two-thirds of the way to the target.", "action", ARMS, ["spine"])
def _bounce_pass():
    return (grip_keys([(0.0, 0.0, -0.15, 0.28, "down"), (0.35, 0.0, -0.15, 0.28, "down"),
                       (0.58, 0.0, -0.42, 0.52, "out"), (0.85, 0.0, -0.42, 0.52, "out"), (1.25, 0.0, -0.15, 0.28, "down")], step=0.08)
            + [k(0.0, spine=S(10)), k(0.58, spine=S(22)), k(1.25, spine=S(10))])


@motion("block_arms", "Volleyball block / contest arms: both arms extend straight up and slightly forward with "
        "the hands wide. Combine with jump.", "action", ARMS, [])
def _block_arms():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R), k(0.35, right_arm=A(160, 20, 0, 5), left_arm=A(160, 20, 0, 5)),
            k(0.8, hold=True), k(1.2, right_arm=READY_R, left_arm=READY_R)]


@motion("slapshot", "Ice-hockey slapshot: big backswing of both hands up over the right shoulder, weight shift, sweep down and through "
        "the puck, follow through low toward the target.", "action", ARMS + ["spine"], ["pelvis", "neck"])
def _slapshot():
    grip = grip_keys([(0.0, 0.10, -0.40, 0.36, "down"), (0.6, 0.36, 0.10, 0.24, "down"),
                      (0.85, 0.22, -0.38, 0.38, "down"), (0.95, 0.0, -0.46, 0.42, "down"),
                      (1.15, -0.28, -0.20, 0.42, "down"), (1.5, -0.28, -0.20, 0.42, "down")])
    return grip + [k(0.0, spine=S(30, 0), pelvis=P(8, 0), neck=N(20)), k(0.6, spine=S(25, 55), pelvis=P(8, 25)),
                   k(0.95, spine=S(35, 0), pelvis=P(8, -10)), k(1.15, spine=S(30, -45), pelvis=P(8, -35)), k(1.5, hold=True)]


@motion("underhand_pitch", "Softball windmill pitch: the throwing arm makes a full forward circle - up in front, "
        "over the top, down behind - and whips through past the hip to release.", "action", ARMS + ["spine"], ["pelvis"])
def _windmill():
    return [k(0.0, right_arm=arm_at(0.10, -0.30, 0.30, "down", "right"), left_arm=arm_at(-0.05, -0.28, 0.32, "out", "left"), spine=S(8)),
            k(0.3, right_arm=A(90, 15, 0, 5), left_arm=A(80, 0, 0, 10), spine=S(2, 20)),
            k(0.48, right_arm=A(170, 20, 0, 5), spine=S(-4, 35)),
            k(0.62, right_arm=A(100, 170, 0, 5)),
            k(0.74, right_arm=A(20, 175, 0, 8), left_arm=A(40, -20, -30, 80), spine=S(4, 15)),
            k(0.84, right_arm=A(40, 5, 0, 10), spine=S(8, -10)),
            k(1.2, right_arm=A(80, 0, 0, 30), spine=S(10, -15))]


@motion("bowling", "Ten-pin bowling delivery: ball swings back as the knees bend into a long slide, then the arm "
        "swings forward low and releases at the ankle, follow through up.", "action", ["right_arm", "spine"], ["left_arm", "pelvis"])
def _bowling():
    return [k(0.0, right_arm=arm_at(0.12, -0.30, 0.30, "down", "right"), left_arm=arm_at(-0.05, -0.28, 0.32, "out", "left"), spine=S(8)),
            k(0.5, right_arm=A(30, 10, 0, 5), left_arm=A(45, 70, 0, 20), spine=S(15)),
            k(1.0, right_arm=A(70, 175, 10, 5), left_arm=A(70, 75, 0, 15), spine=S(35)),
            k(1.4, right_arm=A(25, 10, 0, 5), spine=S(45)),
            k(1.8, right_arm=A(120, 5, 0, 20), spine=S(30))]


@motion("cricket_bowl", "Cricket bowling: side-on gather, the straight bowling arm rotates over the top past the "
        "ear and releases high, follow through across the body.", "action", ARMS + ["spine"], ["pelvis", "neck"])
def _cricket():
    return [k(0.0, right_arm=A(30, 20, 0, 30), left_arm=A(30, 20, 0, 30), spine=S(6)),
            k(0.4, right_arm=A(40, 160, 0, 15), left_arm=A(150, 20, 0, 10), spine=S(-8, 55), pelvis=P(0, 35), neck=N(0, -60)),
            k(0.62, right_arm=A(110, 170, 0, 5), left_arm=A(60, -30, -30, 70), spine=S(-4, 30)),
            k(0.75, right_arm=A(172, 10, 0, 5), spine=S(5, 0), pelvis=P(0, 0), neck=N(0, -10)),
            k(0.9, right_arm=A(80, -20, 0, 10), spine=S(30, -30), pelvis=P(5, -30)),
            k(1.3, right_arm=A(30, -40, -20, 30), left_arm=A(25, 100, 20, 40), spine=S(25, -40), neck=N(10, 20))]


@motion("shot_put", "Shot put: shot pressed into the neck under the jaw, the trunk coils back, then the legs and "
        "hips drive and the arm punches the shot up and out at 40 degrees, fingers flicking.", "action",
        ARMS + ["spine"], ["pelvis", "neck"])
def _shot_put():
    return [k(0.0, right_arm=arm_at(0.12, 0.05, 0.10, "out", "right"), left_arm=A(80, 0, 0, 20), spine=S(10, 60), pelvis=P(5, 30), neck=N(0, -50)),
            k(0.6, spine=S(20, 70)),
            k(0.85, spine=S(0, 0), pelvis=P(0, -30), left_arm=A(50, 120, 20, 90)),
            k(0.97, right_arm=A(130, 10, 0, 5), spine=S(-5, -20), neck=N(-20, 0)),
            k(1.4, right_arm=A(100, -10, 0, 15), spine=S(10, -30), pelvis=P(2, -35))]


@motion("javelin_throw", "Javelin release: the throwing arm long and back at shoulder height, the trunk leans "
        "back, then the arm comes through high over the shoulder and the chest drives forward.", "action",
        ARMS + ["spine"], ["pelvis", "neck"])
def _javelin():
    return [k(0.0, right_arm=A(95, 175, 90, 5), left_arm=A(80, 0, 0, 15), spine=S(-15, 70), pelvis=P(0, 35), neck=N(0, -70)),
            k(0.4, hold=True),
            k(0.62, right_arm=A(150, 60, 90, 60), spine=S(-5, 20), pelvis=P(0, -10)),
            k(0.75, right_arm=A(130, 5, 0, 10), left_arm=A(40, 100, 30, 90), spine=S(15, -15), neck=N(0, 0)),
            k(1.2, right_arm=A(50, -30, -20, 30), spine=S(30, -30), pelvis=P(4, -30))]


@motion("knee_strike", "Muay Thai knee strike: hands clinch and pull down while the right knee drives up hard, "
        "hips thrust forward.", "action", ["right_leg"] + ARMS + ["pelvis"], ["left_leg", "spine"])
def _knee_strike():
    clinch = {"right_arm": arm_at(0.15, 0.10, 0.40, "down", "right"), "left_arm": arm_at(0.15, 0.10, 0.40, "down", "left")}
    pull = {"right_arm": arm_at(0.15, -0.15, 0.35, "down", "right"), "left_arm": arm_at(0.15, -0.15, 0.35, "down", "left")}
    return [k(0.0, right_leg=Lg(18, 180, 10, 30), left_leg=Lg(4, 0, 15, 15), right_arm=GUARD_R, left_arm=GUARD_L, pelvis=P(), spine=S(6)),
            k(0.3, **clinch),
            k(0.5, right_leg=Lg(100, 0, 4, 130), left_leg=Lg(2, 0, 15, 4), pelvis=P(-12), spine=S(-6), **pull),
            k(0.65, hold=True),
            k(1.0, right_leg=Lg(18, 180, 10, 30), left_leg=Lg(4, 0, 15, 15), right_arm=GUARD_R, left_arm=GUARD_L, pelvis=P(), spine=S(6))]


@motion("bob_and_weave", "Boxing bob and weave: bend the knees and roll the head and shoulders under in a U from "
        "one side to the other, guard held up.", "cycle", LEGS + ["spine"], ["pelvis"], period=1.2)
def _bob():
    up_l = stance_legs("normal", 0.3, "left", 20)
    low = stance_legs("normal", 0.75, "left", 20)
    return [k(0.0, **up_l, spine=S(8, 12, -14)), k(0.3, **low, spine=S(28, 12, 0)), k(0.6, **up_l, spine=S(8, 12, 14)),
            k(0.9, **low, spine=S(28, 12, 0))]


@motion("slip", "Boxing slip: a quick small bend of the trunk to the outside of an incoming punch, knees soft, "
        "back to center.", "action", ["spine"], ["pelvis"], params={"direction": ("right", ("right", "left"))})
def _slip(direction="right"):
    sd = 18 if direction == "right" else -18
    return [k(0.0, spine=S(8, 12)), k(0.2, spine=S(14, 12 + sd, sd)), k(0.4, hold=True), k(0.65, spine=S(8, 12))]


@motion("soccer_dribble", "Soccer dribble in place: small light touches with the inside and outside of the right "
        "foot while bouncing on the left, arms out for balance.", "cycle", LEGS, ARMS + ["spine", "body"], period=0.7)
def _soccer_dribble():
    return [k(0.0, right_leg=Lg(15, 0, 45, 25), left_leg=Lg(3, 0, 10, 18), right_arm=A(30, 70, 0, 40), left_arm=A(30, 70, 0, 40), spine=S(12)),
            k(0.18, right_leg=Lg(8, 20, -10, 20), left_leg=Lg(3, 0, 10, 12)),
            k(0.35, right_leg=Lg(4, 0, 8, 15), left_leg=Lg(3, 0, 10, 18)),
            k(0.53, right_leg=Lg(16, 10, 50, 25))]


# =============================================================================
# 15. BALL HANDLING / CATCHING / PASSING (general)
# =============================================================================
@motion("crossover_dribble", "Low dribble that switches the ball from the right hand to the left in front of the "
        "body and back (crossover).", "cycle", ARMS, ["spine"], period=1.0)
def _crossover_dribble():
    r_ball = {"right_arm": A(30, 40, 10, 60), "left_arm": A(35, 30, -10, 60)}
    mid = {"right_arm": arm_at(0.15, -0.55, 0.32, "down", "right"), "left_arm": arm_at(0.15, -0.55, 0.32, "down", "left")}
    l_ball = {"left_arm": A(30, 40, 10, 60), "right_arm": A(35, 30, -10, 60)}
    return [k(0.0, **r_ball, spine=S(18)), k(0.25, **mid), k(0.5, **l_ball), k(0.75, **mid)]


@motion("two_hand_catch_high", "Reach both arms up high to catch or rebound a ball, then pull it down to the chest "
        "with elbows out. Combine with jump.", "action", ARMS, ["spine", "neck"])
def _catch_high():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, neck=N()),
            k(0.4, right_arm=A(160, 15, 0, 15), left_arm=A(160, 15, 0, 15), neck=N(-25)), k(0.55, hold=True)] + \
        grip_keys([(0.85, 0.0, -0.10, 0.28, "out"), (1.2, 0.0, -0.10, 0.28, "out")], step=0.1)


@motion("over_shoulder_catch", "Catch a ball dropping over the shoulder while running: head turned back, both "
        "hands up and out in front of the face, pinkies together. Combine with run.", "action", ARMS + ["neck"], ["spine"])
def _over_shoulder():
    return [k(0.0, right_arm=A(40, 175, 10, 80), left_arm=A(40, 6, -15, 80), neck=N()),
            k(0.4, right_arm=arm_at(0.08, 0.28, 0.42, "out", "right"), left_arm=arm_at(0.08, 0.28, 0.42, "out", "left"),
              neck=N(-15, -35)), k(0.7, hold=True),
            k(1.0, right_arm=arm_at(0.15, -0.12, 0.22, "down", "right"), left_arm=arm_at(-0.05, -0.12, 0.25, "down", "left"), neck=N())]


@motion("ball_hold_hip", "Hold a ball with both hands at the right hip, elbows out, ready to pass, shoot or "
        "drive (triple-threat / protect the ball).", "pose", [], ARMS)
def _ball_hold_hip():
    return [k(0.0, right_arm=arm_at(0.28, -0.40, 0.18, "out", "right"), left_arm=arm_at(-0.24, -0.38, 0.22, "out", "left"))]


@motion("ball_carry", "Carry a ball tucked high and tight in the right arm against the chest, the left arm "
        "free. Combine with run.", "pose", ["right_arm"], ["left_arm"])
def _ball_carry():
    return [k(0.0, right_arm=arm_at(0.05, -0.18, 0.15, "down", "right"), left_arm=A(30, 20, -10, 70))]


@motion("hook_shot", "One-hand hook shot: side-on, the right arm sweeps up in an arc over the head and releases "
        "high, the left arm shields.", "action", ARMS + ["spine"], ["neck"])
def _hook_shot():
    return [k(0.0, right_arm=arm_at(0.25, -0.30, 0.25, "down", "right"), left_arm=A(60, 70, 0, 50), spine=S(6, 60)),
            k(0.45, right_arm=A(95, 90, 0, 15), spine=S(0, 70, -8)),
            k(0.7, right_arm=A(170, 60, 0, 15), left_arm=A(80, 60, 0, 60), spine=S(0, 60, -18)),
            k(0.85, right_arm=A(165, 20, -20, 30)), k(1.3, right_arm=A(30, 20, 0, 30), spine=S(6, 30))]


@motion("handoff", "Hand a ball off: hold it at the chest, turn and extend it out to the right side at waist "
        "height, then pull the arms back.", "action", ARMS + ["spine"], [])
def _handoff():
    return grip_keys([(0.0, 0.0, -0.12, 0.28, "down"), (0.45, 0.34, -0.26, 0.36, "down"), (0.75, 0.34, -0.26, 0.36, "down"),
                      (1.1, 0.0, -0.12, 0.28, "down")], step=0.08) + [k(0.0, spine=S(10)), k(0.45, spine=S(14, 35)), k(1.1, spine=S(10))]


@motion("center_snap", "Snap a ball backward between the legs: bent over in a wide stance with both hands on the "
        "ball on the ground, then swing it back through the legs.", "action", ARMS + ["spine"], ["neck"])
def _snap():
    return grip_keys([(0.0, 0.0, -0.05, 0.62, "out"), (0.3, 0.0, -0.05, 0.62, "out"), (0.55, 0.0, -0.32, 0.46, "out"),
                      (0.8, 0.0, -0.40, 0.40, "out")], step=0.08) + [k(0.0, spine=S(70), neck=N(-30)), k(0.8, spine=S(72))]


@motion("two_hand_side_pass", "Two-hand sideways spin pass: ball at the right hip, swing it across the body and "
        "release to the left at chest height, fingers following through.", "action", ARMS + ["spine"], ["pelvis"])
def _side_pass():
    return grip_keys([(0.0, 0.30, -0.32, 0.34, "down"), (0.35, 0.32, -0.34, 0.30, "down"), (0.65, -0.10, -0.15, 0.45, "out"),
                      (0.85, -0.40, -0.05, 0.45, "out"), (1.2, -0.40, -0.05, 0.45, "out")], step=0.07) + \
        [k(0.0, spine=S(15, 30)), k(0.35, spine=S(15, 40)), k(0.85, spine=S(10, -40)), k(1.2, spine=S(10, -40))]


@motion("underhand_serve", "Underhand serve / toss: the left hand holds the ball low in front, the right arm "
        "swings back and then straight forward from below to strike or release it.", "action", ARMS + ["spine"], ["pelvis"])
def _underhand_serve():
    return [k(0.0, right_arm=A(10, 20, 0, 10), left_arm=arm_at(0.10, -0.38, 0.40, "down", "left"), spine=S(15)),
            k(0.5, right_arm=A(55, 170, 10, 10), spine=S(18, 15)),
            k(0.8, right_arm=A(35, 10, 0, 10), left_arm=A(20, 60, 0, 30), spine=S(15, -5)),
            k(1.0, right_arm=A(80, 0, 0, 10)), k(1.4, right_arm=A(40, 10, 0, 20), left_arm=A(15, 60, 0, 30), spine=S(10))]


# =============================================================================
# 16. KICKING / FOOTWORK WITH A BALL (general)
# =============================================================================
@motion("outside_foot_flick", "Short pass / flick with the outside of the right foot: the foot turns in and the "
        "lower leg flicks out to the right.", "action", LEGS, ARMS + ["spine", "pelvis"])
def _outside_flick():
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), right_arm=HANG, left_arm=HANG),
            k(0.3, right_leg=Lg(18, 160, -25, 40), left_leg=leg_at(0.05, 0.14, 0.06, 0, 10, "left"), right_arm=A(25, 60, 0, 25), left_arm=A(30, 70, 0, 25)),
            k(0.5, right_leg=Lg(22, 40, -35, 12)), k(0.7, right_leg=Lg(26, 55, -30, 8)),
            k(1.05, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), right_arm=HANG, left_arm=HANG)]


@motion("chip_kick", "Chip / lofted kick: a stabbing short swing that gets under the ball, the trunk leaning "
        "back and a short high follow-through.", "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _chip():
    plant = leg_at(0.06, 0.15, 0.06, 0.0, 15, "left")
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), spine=S(4), right_arm=HANG, left_arm=HANG),
            k(0.3, right_leg=Lg(22, 180, 8, 95), left_leg=plant, spine=S(4), right_arm=A(25, 30, 0, 25), left_arm=A(55, 70, 0, 20)),
            k(0.48, right_leg=Lg(25, 0, 12, 25), spine=S(-12), pelvis=P(-5)),
            k(0.62, right_leg=Lg(55, 0, 12, 15), spine=S(-15)), k(0.8, hold=True),
            k(1.15, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), spine=S(4), pelvis=P(), right_arm=HANG, left_arm=HANG)]


@motion("side_volley_kick", "Side volley: lean away to the left and swing the right leg round horizontally at "
        "hip height to strike a ball in the air.", "action", LEGS + ["pelvis", "spine"], ARMS)
def _side_volley():
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), spine=S(4), pelvis=P(), right_arm=HANG, left_arm=HANG),
            k(0.35, right_leg=Lg(50, 150, 10, 90), left_leg=leg_at(0.0, 0.14, 0.08, 0, 30, "left"), spine=S(5, 10, -30),
              pelvis=P(0, 20, -15), right_arm=A(40, 20, 0, 30), left_arm=A(80, 90, 0, 10)),
            k(0.55, right_leg=Lg(85, 80, -40, 20), spine=S(0, -25, -38), pelvis=P(0, -35, -20)),
            k(0.7, right_leg=Lg(75, 10, -30, 15), spine=S(0, -40, -30)),
            k(1.1, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), spine=S(4), pelvis=P(), right_arm=HANG, left_arm=HANG)]


@motion("punt_kick", "Punt / drop kick: hold the ball out in both hands, step, drop it and swing the right leg "
        "through straight and high, arms opening for balance.", "action", LEGS + ARMS + ["pelvis"], ["spine"])
def _punt():
    hold = {"right_arm": arm_at(0.05, -0.25, 0.45, "down", "right"), "left_arm": arm_at(0.05, -0.25, 0.45, "down", "left")}
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), pelvis=P(), spine=S(6), **hold),
            k(0.35, right_leg=Lg(20, 180, 8, 60), left_leg=leg_at(0.15, 0.14, 0.05, 0, 10, "left")),
            k(0.5, right_arm=A(45, 60, 0, 20), left_arm=A(60, 70, 0, 20), right_leg=Lg(15, 0, 8, 40)),
            k(0.65, right_leg=Lg(95, -4, 10, 6), pelvis=P(-8, -10), spine=S(-10), right_arm=A(40, 160, 0, 20), left_arm=A(80, 70, 0, 15)),
            k(1.1, right_leg=leg_at(0.3, 0.12, 0.05, 0, 10, "right"), left_leg=Lg(12, 180, 8, 15), pelvis=P(), spine=S(6)),
            k(1.5, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), right_arm=HANG, left_arm=HANG)]


@motion("foot_trap", "Receive / trap a ball with the sole or inside of the right foot: lift the foot to meet it "
        "and cushion it down.", "action", LEGS, ARMS + ["spine"])
def _foot_trap():
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 10), right_arm=A(25, 60, 0, 25), left_arm=A(25, 60, 0, 25), spine=S(10)),
            k(0.35, right_leg=Lg(25, 0, 45, 30)), k(0.6, right_leg=Lg(14, 0, 45, 20)), k(0.9, right_leg=Lg(6, 0, 30, 10))]


@motion("chest_trap", "Cushion a high ball on the chest: arms open wide, chest pushes up to meet it, then gives "
        "back so it drops to the feet.", "action", ARMS + ["spine"], ["neck"])
def _chest_trap():
    return [k(0.0, right_arm=A(30, 60, 0, 30), left_arm=A(30, 60, 0, 30), spine=S(5), neck=N()),
            k(0.4, right_arm=A(60, 85, 0, 30), left_arm=A(60, 85, 0, 30), spine=S(-20), neck=N(15)),
            k(0.7, spine=S(-8)), k(1.1, right_arm=A(30, 60, 0, 30), left_arm=A(30, 60, 0, 30), spine=S(10), neck=N())]


@motion("step_over", "Step-over feint: the right foot circles over an imaginary ball from inside to outside and "
        "plants wide, hips and shoulders dropping to sell the fake.", "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _step_over():
    return [k(0.0, **stance_legs("normal", 0.3), pelvis=P(4), spine=S(12), right_arm=A(30, 60, 0, 30), left_arm=A(30, 60, 0, 30)),
            k(0.25, right_leg=Lg(35, -30, 30, 60), left_leg=leg_at(0.0, 0.12, 0.1, 0, 10, "left"), pelvis=P(4, -15)),
            k(0.45, right_leg=Lg(35, 50, -10, 50), spine=S(16, 0, 12), right_arm=A(55, 80, 0, 25)),
            k(0.7, right_leg=leg_at(0.05, 0.40, 0.18, 0, 25, "right"), pelvis=P(6, 10, 6), spine=S(18, 0, 15)),
            k(1.0, **stance_legs("wide", 0.4), pelvis=P(4), spine=S(12), right_arm=A(30, 60, 0, 30))]


@motion("block_tackle", "Block tackle / poke: lunge the left (non-kicking) foot in, the right foot blocks the "
        "ball side-on with the ankle locked, low centre of gravity.", "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _block_tackle():
    return [k(0.0, **stance_legs("normal", 0.4), pelvis=P(4), spine=S(15), right_arm=A(30, 60, 0, 30), left_arm=A(30, 60, 0, 30)),
            k(0.35, left_leg=leg_at(0.35, 0.14, 0.32, 0, 10, "left"), right_leg=Lg(35, 10, 70, 45), spine=S(25)),
            k(0.6, hold=True), k(1.0, **stance_legs("normal", 0.4), spine=S(15))]


# =============================================================================
# 17. RACKET / BAT / CLUB EXTRAS (general)
# =============================================================================
@motion("one_hand_backhand", "One-handed backhand swing: shoulders turn left with the right arm across the body "
        "and the left hand on the throat, swing out to contact in front and finish high to the right with "
        "the arms spread.", "action", ARMS + ["spine"], ["pelvis", "neck"])
def _one_hand_bh():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(10), pelvis=P(3), neck=N(5)),
            k(0.45, right_arm=arm_at(-0.30, -0.25, 0.25, "out", "right"), left_arm=arm_at(0.25, -0.22, 0.28, "down", "left"),
              spine=S(12, -75), pelvis=P(3, -35), neck=N(5, 50)),
            k(0.75, right_arm=arm_at(-0.10, -0.35, 0.40, "out", "right"), spine=S(10, -40)),
            k(0.9, right_arm=A(80, 40, 0, 8), left_arm=A(60, 160, 0, 10), spine=S(8, 0), pelvis=P(3, 5), neck=N(5, 0)),
            k(1.1, right_arm=A(125, 80, 0, 15), left_arm=A(55, 170, 0, 10), spine=S(6, 20)),
            k(1.6, right_arm=READY_R, left_arm=READY_R, spine=S(10), pelvis=P(3), neck=N(5))]


@motion("backhand_block", "Compact backhand block / volley: racket hand up across in front of the left shoulder, "
        "short firm punch forward, no backswing.", "action", ARMS + ["spine"], ["pelvis"])
def _bh_block():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(12)),
            k(0.35, right_arm=arm_at(-0.25, -0.05, 0.25, "out", "right"), left_arm=arm_at(0.0, -0.05, 0.30, "down", "left"), spine=S(12, -30)),
            k(0.55, right_arm=arm_at(-0.12, -0.10, 0.52, "out", "right"), spine=S(14, -10)), k(0.75, hold=True),
            k(1.2, right_arm=READY_R, left_arm=READY_R, spine=S(12))]


@motion("split_step", "Split step: a small hop as the opponent strikes, landing on the balls of the feet in a "
        "wide athletic stance, ready to move.", "action", LEGS + ["body"], ARMS + ["spine", "pelvis"])
def _split_step():
    return [k(0.0, **stance_legs("normal", 0.2), body=B(), right_arm=READY_R, left_arm=READY_R, spine=S(8)),
            k(0.12, body=B(air=1.0, root=0.0)), k(0.22, body=B(air=1.0, root=0.06), right_leg=Lg(6, 60, 12, 12), left_leg=Lg(6, 60, 12, 12)),
            k(0.32, body=B(air=1.0, root=0.0)), k(0.35, **stance_legs("wide", 0.55), body=B(air=0.0), spine=S(16)),
            k(0.8, hold=True)]


@motion("putt", "Putting stroke: bent over the ball with eyes over it, arms hanging and hands together, the "
        "shoulders rock the arms back and through like a pendulum. Combine with stance(depth=0.2).", "action",
        ARMS + ["spine", "neck"], [])
def _putt():
    return grip_keys([(0.0, 0.0, -0.40, 0.40, "down"), (0.5, 0.10, -0.40, 0.38, "down"), (0.9, -0.12, -0.38, 0.40, "down"),
                      (1.3, -0.12, -0.38, 0.40, "down")], step=0.1) + \
        [k(0.0, spine=S(40, 0), neck=N(30)), k(0.5, spine=S(40, 8)), k(0.9, spine=S(40, -10)), k(1.3, spine=S(40, -10))]


@motion("chip_swing", "Short chip / pitch swing with two hands: hands lead, small backswing to hip height, "
        "brush through, short finish. Combine with stance.", "action", ARMS + ["spine", "neck"], ["pelvis"])
def _chip_swing():
    return grip_keys([(0.0, 0.0, -0.50, 0.30, "down"), (0.55, 0.25, -0.38, 0.26, "down"), (0.85, 0.0, -0.50, 0.32, "down"),
                      (1.1, -0.25, -0.38, 0.28, "down"), (1.5, -0.25, -0.38, 0.28, "down")]) + \
        [k(0.0, spine=S(35, 0), neck=N(25)), k(0.55, spine=S(35, 30)), k(0.85, spine=S(35, 0)), k(1.1, spine=S(30, -30)), k(1.5, hold=True)]


@motion("bunt", "Bunt / soft block with a two-hand stick: square up facing forward, hold the bat level out in "
        "front at chest height and give with it on contact.", "action", ARMS + ["spine"], ["pelvis"])
def _bunt():
    return [k(0.0, right_arm=arm_at(0.22, 0.05, 0.16, "down", "right"), left_arm=arm_at(-0.22, 0.05, 0.16, "down", "left"), spine=S(10, 30))] + \
        [k(0.5, right_arm=arm_at(0.15, -0.10, 0.45, "down", "right"), left_arm=arm_at(0.15, -0.12, 0.40, "out", "left"), spine=S(18, 0)),
         k(0.8, right_arm=arm_at(0.15, -0.12, 0.35, "down", "right"), left_arm=arm_at(0.15, -0.14, 0.32, "out", "left")), k(1.2, hold=True)]


@motion("forward_defense", "Forward defensive block with a vertical bat: big front-foot stride, head over the "
        "front knee, hands together with the bat angled down in front of the front pad.", "action",
        ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _fwd_defense():
    return [k(0.0, **stance_legs("normal", 0.25), right_arm=arm_at(0.18, -0.45, 0.15, "down", "right"),
              left_arm=arm_at(-0.18, -0.45, 0.15, "down", "left"), spine=S(15, 40), pelvis=P(3, 30), neck=N(5, -50)),
            k(0.6, left_leg=leg_at(0.45, 0.16, 0.25, 0, 10, "left"), right_leg=Lg(18, 180, 25, 20),
              right_arm=arm_at(-0.05, -0.30, 0.35, "down", "right"), left_arm=arm_at(0.05, -0.20, 0.38, "out", "left"),
              spine=S(28, 20), pelvis=P(6, 15)), k(1.0, hold=True)]


@motion("vertical_two_hand_swing", "Vertical two-hand bat swing (straight drive, overhead chop): hands lift "
        "the bat high behind the right shoulder, the front foot strides, the hands swing straight down in a "
        "vertical arc to contact low in front of the front foot, then up to a high finish in front of the "
        "left shoulder.", "action", ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _vertical_swing():
    grip = grip_keys([(0.0, 0.16, -0.40, 0.30, "down"),      # stance: hands at the waist
                      (0.45, 0.30, 0.38, 0.24, "out"),       # backlift: high beside the right shoulder
                      (0.62, 0.22, 0.05, 0.30, "down"),      # start down
                      (0.78, 0.05, -0.42, 0.50, "down"),     # contact: low, in front of the front foot
                      (0.95, -0.04, 0.12, 0.55, "down"),     # through and up, arms long
                      (1.15, -0.12, 0.62, 0.34, "out"),      # high finish: hands above the head, in front
                      (1.6, -0.12, 0.62, 0.34, "out")], step=0.05)
    base = stance_legs("normal", 0.25)
    return grip + [k(0.0, **base, spine=S(12, 40), pelvis=P(3, 30), neck=N(5, -50)),
                   k(0.45, spine=S(8, 45), pelvis=P(3, 32)),
                   k(0.7, left_leg=leg_at(0.40, 0.16, 0.22, 0, 10, "left"), right_leg=Lg(16, 180, 25, 18),
                     spine=S(28, 25), pelvis=P(6, 20), neck=N(15, -40)),
                   k(1.15, spine=S(12, 10), pelvis=P(4, 10), neck=N(0, -20)),
                   k(1.6, hold=True)]


# =============================================================================
# 18. CONTACT / COMBAT / STANCES (general)
# =============================================================================
@motion("three_point_stance", "Three-point stance: deep crouch, back flat, right hand on the ground in front, "
        "left arm resting on the thigh, ready to fire out.", "pose", ["body"] + LEGS + ARMS + ["spine", "pelvis"], ["neck"])
def _three_point():
    return [k(0.0, body=B(pitch=35), right_leg=Lg(70, 0, 10, 115), left_leg=Lg(90, 0, 10, 125), spine=S(35), pelvis=P(10),
              right_arm=A(70, 0, 0, 4), left_arm=A(25, 30, 0, 60), neck=N(-30))]


@motion("cutting_step", "Change of direction cut: plant the outside (left) foot wide, sink the hips and push off "
        "explosively to the right, the trunk leaning into the new direction.", "action", LEGS + ["pelvis", "spine"], ARMS)
def _cut():
    return [k(0.0, right_leg=Lg(25, 0, 8, 25), left_leg=Lg(15, 180, 8, 30), spine=S(10), pelvis=P(), right_arm=A(30, 175, 10, 80), left_arm=A(50, 6, -15, 85)),
            k(0.3, left_leg=leg_at(0.05, 0.42, 0.25, 0, 30, "left"), right_leg=Lg(30, 60, 8, 60), spine=S(20, 15, 18), pelvis=P(8, 15, 10),
              right_arm=A(50, 60, 0, 60), left_arm=A(40, 120, 0, 60)),
            k(0.55, left_leg=Lg(25, -60, 8, 20), right_leg=leg_at(0.05, 0.40, 0.2, 0, 30, "right"), spine=S(18, 30, 15), pelvis=P(6, 35, 8),
              right_arm=A(45, 175, 10, 80), left_arm=A(60, 6, -15, 85)),
            k(0.9, right_leg=Lg(10, 0, 8, 15), left_leg=Lg(15, 0, 8, 25), spine=S(10, 30), pelvis=P(3, 30))]


@motion("stiff_arm", "Stiff-arm / fend: the left arm shoots out straight and firm at shoulder height to push "
        "away a defender, then pulls back.", "action", ["left_arm"], ["spine"])
def _stiff_arm():
    return [k(0.0, left_arm=A(40, 20, -15, 85), spine=S(10)), k(0.2, left_arm=A(80, 30, 0, 3), spine=S(14, 15)), k(0.55, hold=True),
            k(0.85, left_arm=A(40, 20, -15, 85), spine=S(10))]


@motion("form_tackle", "Form tackle: low hips and flat back, step in close, drive up and through the target "
        "with the head up while both arms wrap and squeeze.", "action", LEGS + ARMS + ["spine", "pelvis"], ["neck"])
def _tackle():
    return [k(0.0, **stance_legs("normal", 0.6), spine=S(30), pelvis=P(10), right_arm=A(40, 40, -15, 80), left_arm=A(40, 40, -15, 80), neck=N(-20)),
            k(0.35, right_leg=leg_at(0.35, 0.14, 0.32, 0, 10, "right"), left_leg=Lg(25, 180, 8, 40), spine=S(40)),
            k(0.6, right_arm=A(80, 60, 0, 40), left_arm=A(80, 60, 0, 40)),
            k(0.8, right_arm=arm_at(-0.05, -0.05, 0.38, "out", "right"), left_arm=arm_at(-0.05, -0.05, 0.38, "out", "left"),
              right_leg=leg_at(0.2, 0.14, 0.15, 0, 10, "right"), left_leg=Lg(35, 180, 8, 25), spine=S(25)),
            k(1.2, hold=True)]


@motion("push_block", "Drive block: from a low stance, step and punch both hands out to chest height, thumbs up, "
        "hips rolling forward, then keep driving.", "action", LEGS + ARMS + ["spine", "pelvis"], ["neck"])
def _push_block():
    return [k(0.0, **stance_legs("wide", 0.6), spine=S(30), pelvis=P(10), right_arm=A(30, 20, -20, 90), left_arm=A(30, 20, -20, 90)),
            k(0.3, right_leg=leg_at(0.25, 0.2, 0.25, 0, 10, "right"), spine=S(25),
              right_arm=arm_at(0.12, -0.05, 0.50, "down", "right"), left_arm=arm_at(0.12, -0.05, 0.50, "down", "left")),
            k(0.6, left_leg=leg_at(0.15, 0.2, 0.25, 0, 10, "left")), k(1.0, hold=True)]


@motion("box_out", "Box out / shield: wide low stance with the backside pushed back, elbows up and arms out wide "
        "to feel and hold the opponent behind.", "pose", LEGS + ARMS + ["spine", "pelvis"], [])
def _box_out():
    return [k(0.0, **stance_legs("very_wide", 0.7), spine=S(22), pelvis=P(12), right_arm=A(80, 85, 90, 80), left_arm=A(80, 85, 90, 80))]


@motion("catcher_crouch", "Catcher / wicket-keeper crouch: deep squat on the balls of the feet, knees wide, the "
        "glove hand out in front as a target, the other hand behind.", "pose", LEGS + ARMS + ["spine", "pelvis"], ["neck"])
def _catcher():
    return [k(0.0, **stance_legs("wide", 1.3), spine=S(25), pelvis=P(10), left_arm=A(70, 10, -10, 40), right_arm=A(30, 150, 20, 90))]


@motion("bent_over_drive", "Low bent-over pushing drive (scrum, ruck, maul, sled push): flat back near "
        "horizontal, arms forward bound, legs driving with short powerful steps.", "cycle", LEGS + ARMS + ["spine", "pelvis", "body"],
        ["neck"], period=0.8)
def _bent_drive():
    arms = {"right_arm": A(95, 10, 0, 30), "left_arm": A(95, 10, 0, 30)}
    return [k(0.0, body=B(pitch=40), spine=S(35), pelvis=P(10), right_leg=Lg(60, 0, 8, 90), left_leg=Lg(15, 180, 8, 40), neck=N(-30), **arms),
            k(0.4, right_leg=Lg(15, 180, 8, 40), left_leg=Lg(60, 0, 8, 90))]


@motion("pivot_turn", "Pivot: keep the left foot planted and swing the body round 180 degrees by stepping the "
        "right foot around behind, staying low.", "action", LEGS + ["body"], ARMS + ["spine", "pelvis"],
        params={"deg": (180, (-270, 270))})
def _pivot(deg=180):
    return [k(0.0, **stance_legs("normal", 0.45), body=B(turn=0), spine=S(15)),
            k(0.25, right_leg=Lg(30, 150, 10, 60), body=B(turn=deg * 0.4)),
            k(0.5, body=B(turn=deg)), k(0.6, **stance_legs("normal", 0.45)), k(0.8, hold=True)]


@motion("jab_step", "Jab step (fake): a short sharp step forward with the right foot, then back to the stance.",
        "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _jab_step():
    base = stance_legs("normal", 0.45)
    return [k(0.0, **base, spine=S(15), pelvis=P(4)),
            k(0.2, right_leg=leg_at(0.32, 0.17, 0.2, 0, 10, "right"), spine=S(20, -10), pelvis=P(6, -10)),
            k(0.4, hold=True), k(0.65, **base, spine=S(15), pelvis=P(4))]


@motion("stop_and_stick", "Deceleration / stick the landing: from a run, chop the steps and drop into a balanced "
        "low athletic stance, hips back, chest up, hold.", "action", LEGS + ["pelvis", "spine"], ARMS)
def _stop():
    return [k(0.0, right_leg=Lg(30, 0, 8, 25), left_leg=Lg(20, 180, 8, 40), spine=S(10), right_arm=A(30, 175, 10, 80), left_arm=A(55, 6, -15, 85)),
            k(0.2, right_leg=leg_at(0.12, 0.17, 0.2, 0, 10, "right"), left_leg=Lg(25, 0, 8, 50)),
            k(0.4, **stance_legs("wide", 0.7), spine=S(25), pelvis=P(10), right_arm=A(40, 20, -15, 70), left_arm=A(40, 20, -15, 70)),
            k(1.0, hold=True)]


# =============================================================================
# 19. GROUND / DIVING (general)
# =============================================================================
@motion("side_dive", "Full-length dive to the right (catch, save, block): push off the left leg, the body "
        "flies horizontal on its side with both arms extended, land on the side.", "action", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _side_dive():
    pts, T = _flight(0.35, 0.18)
    keys = [k(0.0, **stance_legs("wide", 0.5), body=B(), spine=S(15), pelvis=P(4), right_arm=READY_R, left_arm=READY_R),
            k(0.3, right_leg=leg_at(0.0, 0.40, 0.3, 0, 30, "right"), left_leg=leg_at(0.0, 0.2, 0.3, 0, 10, "left"), spine=S(18, 0, 15),
              right_arm=A(110, 70, 0, 20), left_arm=A(100, 30, 0, 30)),
            k(0.35, body=B(air=1.0))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r, roll=-70 * (t - 0.35) / T)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0, roll=-80), right_arm=A(170, 30, 0, 5), left_arm=A(160, 10, 0, 10),
               right_leg=Lg(5, 0, 8, 10), left_leg=Lg(25, 0, 8, 50), spine=S(0, 0, 0)),
             k(tl + 0.4, body=B(air=0.0, roll=-85)), k(tl + 0.9, hold=True)]
    return keys


@motion("low_scoop", "Field a ground ball / pick up from the floor: wide low stance, hinge and get both hands "
        "down in front with the fingers pointing down, scoop up to the chest.", "action", LEGS + ARMS + ["spine", "pelvis"], ["neck"])
def _scoop():
    return [k(0.0, **stance_legs("wide", 0.4), spine=S(15), pelvis=P(5), right_arm=READY_R, left_arm=READY_R, neck=N()),
            k(0.5, **stance_legs("wide", 1.0), spine=S(50), pelvis=P(15), right_arm=A(65, 5, 0, 10), left_arm=A(65, 5, 0, 10), neck=N(-15)),
            k(0.75, hold=True),
            k(1.2, **stance_legs("wide", 0.5), spine=S(15), right_arm=arm_at(0.15, -0.15, 0.25, "down", "right"),
              left_arm=arm_at(0.0, -0.15, 0.28, "down", "left"), neck=N())]


@motion("feet_first_slide", "Feet-first slide: drop the hips and sit back, the right leg slides out straight in "
        "front, the left leg bent under, arms up to stay clear, then stop.", "action", ["body"] + LEGS + ARMS + ["spine", "pelvis"], ["neck"])
def _slide():
    return [k(0.0, right_leg=Lg(30, 0, 8, 25), left_leg=Lg(20, 180, 8, 40), body=B(), spine=S(10), right_arm=A(30, 175, 10, 80), left_arm=A(55, 6, -15, 85)),
            k(0.35, body=B(pitch=-35), right_leg=Lg(70, 0, 8, 5), left_leg=Lg(30, 30, 30, 120), spine=S(10), right_arm=A(120, 30, 0, 30), left_arm=A(120, 30, 0, 30)),
            k(0.7, body=B(pitch=-55)), k(1.2, hold=True)]


# =============================================================================
# 20. SWIMMING EXTRAS (general water skills)
# =============================================================================
@motion("streamline", "Streamline glide: body long and face down, arms squeezed overhead with one hand on the "
        "other, legs together and pointed.", "pose", ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [])
def _streamline():
    return [k(0.0, body=SWIM_BODY, right_arm=A(172, 8, 0, 4), left_arm=A(172, 8, 0, 4), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0),
              spine=S(0), neck=N(-10), pelvis=P())]


@motion("flutter_kick", "Flutter kick drill: streamlined face down, legs kick up and down alternately from the "
        "hips with nearly straight knees.", "cycle", ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [], period=0.5)
def _flutter():
    return [k(0.0, body=SWIM_BODY, right_arm=A(172, 8, 0, 4), left_arm=A(172, 8, 0, 4), spine=S(0), neck=N(-10), pelvis=P(),
              right_leg=Lg(12, 0, 0, 20), left_leg=Lg(10, 180, 0, 5)),
            k(0.25, right_leg=Lg(10, 180, 0, 5), left_leg=Lg(12, 0, 0, 20))]


@motion("dolphin_kick", "Dolphin kick: streamlined, both legs together whip down and up in a wave from the chest "
        "through the hips.", "cycle", ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [], period=0.6)
def _dolphin():
    return [k(0.0, body=SWIM_BODY, right_arm=A(172, 8, 0, 4), left_arm=A(172, 8, 0, 4), neck=N(-10), spine=S(6), pelvis=P(-8),
              right_leg=Lg(18, 0, 0, 45), left_leg=Lg(18, 0, 0, 45)),
            k(0.3, spine=S(-4), pelvis=P(6), right_leg=Lg(6, 180, 0, 0), left_leg=Lg(6, 180, 0, 0))]


@motion("tread_water", "Treading water: upright in the water, hands sculling side to side at waist height, legs "
        "circling in an eggbeater kick.", "cycle", ["body"] + ARMS + LEGS + ["spine"], [], period=1.0)
def _tread():
    return [k(0.0, body=B(pitch=10, air=1.0), spine=S(5), right_arm=A(45, 60, 40, 30), left_arm=A(45, 20, 40, 30),
              right_leg=Lg(55, 40, 30, 100), left_leg=Lg(40, 20, 30, 70)),
            k(0.5, right_arm=A(45, 20, 40, 30), left_arm=A(45, 60, 40, 30), right_leg=Lg(40, 20, 30, 70), left_leg=Lg(55, 40, 30, 100))]


@motion("flip_turn", "Flip turn at the wall: from a stroke, tuck tight and somersault forward, feet plant on the "
        "wall, push off on the back into a streamline.", "action", ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [])
def _flip_turn():
    return [k(0.0, body=SWIM_BODY, right_arm=A(20, 175, 0, 10), left_arm=A(20, 175, 0, 10), spine=S(0), neck=N(-15),
              right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0)),
            k(0.3, body=B(pitch=140, air=1.0), spine=S(40), neck=N(30), right_leg=Lg(110, 0, 0, 130), left_leg=Lg(110, 0, 0, 130)),
            k(0.6, body=B(pitch=230, air=1.0)), k(0.85, body=B(pitch=266, air=1.0), spine=S(10), right_leg=Lg(80, 0, 0, 100),
                                                     left_leg=Lg(80, 0, 0, 100), right_arm=A(150, 10, 0, 30), left_arm=A(150, 10, 0, 30)),
            k(1.2, body=B(pitch=266, air=1.0), spine=S(0), neck=N(-10), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0),
              right_arm=A(172, 8, 0, 4), left_arm=A(172, 8, 0, 4))]


@motion("start_dive", "Swimming racing start from the blocks / poolside: starts crouched on the block with "
        "the hands at the toes (no separate setup needed), springs out horizontally and enters the water "
        "head-first in a streamline. Follow with streamline / dolphin_kick / a stroke.", "action", ["body"] + ARMS + LEGS + ["spine", "neck", "pelvis"], [])
def _start_dive():
    pts, T = _flight(0.4, 0.25)
    keys = [k(0.0, body=B(pitch=0), right_leg=Lg(60, 0, 8, 100), left_leg=Lg(60, 0, 8, 100), spine=S(85), pelvis=P(20),
              right_arm=A(85, 5, 0, 5), left_arm=A(85, 5, 0, 5), neck=N(-20)),
            k(0.3, right_arm=A(140, 5, 0, 5), left_arm=A(140, 5, 0, 5)),
            k(0.4, body=B(pitch=50, air=1.0), spine=S(10), pelvis=P(), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0),
              right_arm=A(172, 8, 0, 4), left_arm=A(172, 8, 0, 4), neck=N(-10))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(pitch=50 + 50 * (t - 0.4) / T, air=1.0, root=r)))
    keys += [k(pts[-1][0], body=B(pitch=105, air=1.0, root=0.0)), k(pts[-1][0] + 0.45, body=B(pitch=96, air=1.0, root=-0.18)),
             k(pts[-1][0] + 1.2, body=SWIM_BODY, neck=N(-10))]   # glide up into a level streamline under the surface
    return keys


# =============================================================================
# 21. WARM-UPS / MOBILITY (general)
# =============================================================================
@motion("b_skip", "B-skip drill: like an A-skip, but the driven knee extends the lower leg out and then paws it "
        "back down under the hips.", "cycle", LEGS + ["body"], ARMS + ["spine"], period=1.0)
def _b_skip():
    return [k(0.0, right_leg=Lg(85, 0, 6, 95), left_leg=Lg(3, 0, 8, 8), body=B(air=0.0, root=0.0), right_arm=A(30, 175, 10, 85), left_arm=A(65, 6, -15, 90)),
            k(0.15, right_leg=Lg(80, 0, 6, 15), body=B(air=1.0, root=0.04)), k(0.3, right_leg=Lg(5, 0, 6, 10), body=B(air=0.0, root=0.0)),
            k(0.5, left_leg=Lg(85, 0, 6, 95), right_leg=Lg(3, 0, 8, 8), right_arm=A(65, 6, -15, 90), left_arm=A(30, 175, 10, 85)),
            k(0.65, left_leg=Lg(80, 0, 6, 15), body=B(air=1.0, root=0.04)), k(0.8, left_leg=Lg(5, 0, 6, 10), body=B(air=0.0, root=0.0))]


@motion("lateral_leg_swing", "Lateral leg swings: holding balance, the straight right leg swings out to the side "
        "and back across in front of the left.", "cycle", ["right_leg"], ["left_leg", "right_arm", "left_arm", "spine"], period=1.2)
def _lat_swing():
    return [k(0.0, right_leg=Lg(45, 88, 8, 5), left_leg=Lg(2, 0, 8, 6), spine=S(3, 0, -8), right_arm=A(70, 80, 0, 15), left_arm=A(70, 80, 0, 15)),
            k(0.6, right_leg=Lg(28, -30, 8, 8), spine=S(3, 0, 4))]


@motion("straight_leg_kick", "Straight-leg kicks (toy soldiers / Frankensteins): kick the straight right leg up "
        "toward the reaching left hand, then alternate legs.", "cycle", LEGS + ARMS, ["spine"], period=1.4)
def _toy_soldier():
    return [k(0.0, right_leg=Lg(80, 0, 8, 4), left_leg=Lg(2, 0, 8, 6), left_arm=A(90, -10, 0, 4), right_arm=A(20, 150, 0, 10), spine=S(8)),
            k(0.35, right_leg=Lg(2, 0, 8, 6), left_leg=Lg(2, 0, 8, 6), left_arm=A(15, 60, 0, 10), right_arm=A(15, 60, 0, 10)),
            k(0.7, left_leg=Lg(80, 0, 8, 4), right_leg=Lg(2, 0, 8, 6), right_arm=A(90, -10, 0, 4), left_arm=A(20, 150, 0, 10)),
            k(1.05, right_leg=Lg(2, 0, 8, 6), left_leg=Lg(2, 0, 8, 6), left_arm=A(15, 60, 0, 10), right_arm=A(15, 60, 0, 10))]


@motion("knee_hug", "Walking knee hug: pull the right knee up to the chest with both hands while rising on the "
        "left toes, hold, release.", "action", LEGS + ARMS + ["body"], ["spine"])
def _knee_hug():
    return [k(0.0, right_leg=Lg(0, 0, 8, 4), left_leg=Lg(0, 0, 8, 6), right_arm=HANG, left_arm=HANG, body=B()),
            k(0.5, right_leg=Lg(115, 0, 8, 135), right_arm=arm_at(0.12, -0.30, 0.32, "out", "right"), left_arm=arm_at(-0.10, -0.30, 0.32, "out", "left"),
              body=B(root=0.04)), k(1.0, hold=True),
            k(1.4, right_leg=Lg(0, 0, 8, 4), right_arm=HANG, left_arm=HANG, body=B())]


@motion("inchworm", "Inchworm: from standing hinge down to put the hands on the floor, walk the hands out to a "
        "plank, then walk the feet back in and stand.", "action", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _inchworm():
    return [k(0.0, body=B(), spine=S(4), pelvis=P(), right_leg=Lg(0, 0, 8, 2), left_leg=Lg(0, 0, 8, 2), right_arm=HANG, left_arm=HANG),
            k(0.8, spine=S(85), pelvis=P(25), right_arm=A(88, 4, 0, 4), left_arm=A(88, 4, 0, 4)),
            k(1.6, body=B(40), spine=S(40), pelvis=P(10), right_arm=A(85, 4, 0, 4), left_arm=A(85, 4, 0, 4)),
            k(2.4, body=B(PLANK_PITCH), spine=S(0), pelvis=P(), **support_arms(PLANK_PITCH), neck=N(-25)),
            k(2.8, hold=True), k(3.6, body=B(30), spine=S(55), pelvis=P(18)),
            k(4.4, body=B(), spine=S(4), pelvis=P(), right_arm=HANG, left_arm=HANG, neck=N())]


@motion("hip_circles", "Hip circles: hands on the hips, draw big slow circles with the hips.", "cycle",
        ["pelvis", "spine"], ARMS, period=2.0)
def _hip_circles():
    hands = {"right_arm": arm_at(0.26, -0.47, 0.02, "out", "right"), "left_arm": arm_at(0.26, -0.47, 0.02, "out", "left")}
    return [k(0.0, pelvis=P(12, 0, 0), spine=S(-8), **hands), k(0.5, pelvis=P(0, 0, 12), spine=S(0, 0, -10)),
            k(1.0, pelvis=P(-12, 0, 0), spine=S(10)), k(1.5, pelvis=P(0, 0, -12), spine=S(0, 0, 10))]


@motion("arm_swings", "Arm swings: both arms swing open wide to the sides at shoulder height, then cross in front "
        "of the chest, alternating which arm is on top.", "cycle", ARMS, ["spine"], period=1.0)
def _arm_swings():
    return [k(0.0, right_arm=A(85, 95, 0, 8), left_arm=A(85, 95, 0, 8)), k(0.5, right_arm=A(85, -40, 0, 8), left_arm=A(80, -35, 0, 8))]


@motion("neck_rolls", "Neck rolls: slowly roll the head in a circle, chin to chest, ear to shoulder, look up.",
        "cycle", ["neck"], [], period=3.0)
def _neck_rolls():
    return [k(0.0, neck=N(30, 0, 0)), k(0.75, neck=N(0, 0, 30)), k(1.5, neck=N(-25, 0, 0)), k(2.25, neck=N(0, 0, -30))]


@motion("pogo_hops", "Pogo / ankle hops: quick bounces with stiff ankles and nearly straight knees, arms relaxed.",
        "cycle", LEGS + ["body"], ARMS, period=0.4)
def _pogo():
    legs = {"right_leg": Lg(2, 0, 8, 6), "left_leg": Lg(2, 0, 8, 6)}
    return [k(0.0, **legs, body=B(air=0.0, root=0.0), right_arm=A(20, 40, 0, 60), left_arm=A(20, 40, 0, 60)),
            k(0.08, body=B(air=1.0, root=0.0)), k(0.2, body=B(air=1.0, root=0.08)), k(0.32, body=B(air=1.0, root=0.0)),
            k(0.36, body=B(air=0.0))]


@motion("overhead_slam", "Two-hand overhead slam (medicine ball slam, chop down): rise up with both arms "
        "straight overhead, then hinge and drive the hands down hard to the floor in front of the feet.",
        "action", ARMS + LEGS + ["spine", "pelvis", "body"], ["neck"])
def _slam():
    top = {"right_arm": A(170, 10, 0, 8), "left_arm": A(170, 10, 0, 8)}
    return [k(0.0, **stance_legs("normal", 0.2), body=B(), spine=S(5), pelvis=P(), right_arm=arm_at(0.10, -0.25, 0.30, "down", "right"),
              left_arm=arm_at(0.10, -0.25, 0.30, "down", "left"), neck=N()),
            k(0.45, right_leg=Lg(0, 0, 8, 2), left_leg=Lg(0, 0, 8, 2), body=B(root=0.05), spine=S(-10), **top, neck=N(-15)),
            k(0.7, **stance_legs("normal", 0.7), body=B(root=0.0), spine=S(55), pelvis=P(16),
              right_arm=A(70, 6, 0, 6), left_arm=A(70, 6, 0, 6), neck=N(10)),
            k(0.95, hold=True),
            k(1.5, **stance_legs("normal", 0.2), spine=S(5), pelvis=P(), right_arm=arm_at(0.10, -0.25, 0.30, "down", "right"),
              left_arm=arm_at(0.10, -0.25, 0.30, "down", "left"), neck=N())]


@motion("forward_roll", "Forward roll: squat, hands on the floor, tuck the chin and roll over the back, come up "
        "onto the feet in a squat and stand.", "action", ["body"] + ARMS + LEGS + ["spine", "pelvis", "neck"], [])
def _forward_roll():
    tuck = {"right_leg": Lg(120, 0, 8, 140), "left_leg": Lg(120, 0, 8, 140)}
    return [k(0.0, **stance_legs("narrow", 0.1), body=B(), spine=S(4), pelvis=P(), neck=N(), right_arm=HANG, left_arm=HANG),
            k(0.5, **stance_legs("narrow", 1.3), spine=S(50), pelvis=P(15), right_arm=A(60, 5, 0, 10), left_arm=A(60, 5, 0, 10), neck=N(40)),
            k(0.8, body=B(pitch=90, air=1.0, root=-0.35), **tuck, spine=S(60), neck=N(45)),
            k(1.1, body=B(pitch=200, air=1.0, root=-0.42)),
            k(1.4, body=B(pitch=330, air=1.0, root=-0.35), right_arm=A(80, 5, 0, 20), left_arm=A(80, 5, 0, 20)),
            k(1.6, body=B(pitch=360, air=0.0, root=0.0), **stance_legs("narrow", 1.3), spine=S(45), neck=N(20)),
            k(2.2, **stance_legs("narrow", 0.1), spine=S(4), pelvis=P(), right_arm=HANG, left_arm=HANG, neck=N())]


@motion("backstroke_start", "Backstroke start: in the water facing the wall, hands gripping the block, knees "
        "bent with the feet on the wall; pull up, throw the arms back over the head and push off arching "
        "backward into a streamline on the back.", "action", ["body"] + ARMS + LEGS + ["spine", "pelvis", "neck"], [])
def _backstroke_start():
    grip = {"right_arm": A(120, 10, 0, 60), "left_arm": A(120, 10, 0, 60)}
    return [k(0.0, body=B(pitch=0, air=1.0, root=-0.3), right_leg=Lg(100, 0, 8, 120), left_leg=Lg(100, 0, 8, 120), spine=S(20),
              pelvis=P(10), neck=N(), **grip),
            k(0.4, body=B(pitch=-10, air=1.0, root=-0.15), right_arm=A(130, 10, 0, 90), left_arm=A(130, 10, 0, 90), spine=S(25)),
            k(0.7, body=B(pitch=-50, air=1.0, root=0.0), right_leg=Lg(40, 0, 8, 40), left_leg=Lg(40, 0, 8, 40), spine=S(-20),
              right_arm=A(170, 20, 0, 10), left_arm=A(170, 20, 0, 10), neck=N(-40)),
            k(1.1, body=B(pitch=-88, air=1.0, root=-0.2), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(0),
              right_arm=A(172, 8, 0, 4), left_arm=A(172, 8, 0, 4), neck=N(-10)),
            k(1.8, body=B(pitch=-88, air=1.0, root=0.0))]


@motion("juggle_ball", "Keep-up / juggling: small taps of a ball with the top of the right foot and the "
        "thigh while balancing on the left foot, arms out.", "cycle", LEGS, ARMS + ["spine"], period=0.9)
def _juggle():
    return [k(0.0, right_leg=Lg(30, 0, 10, 40), left_leg=Lg(3, 0, 8, 15), right_arm=A(35, 70, 0, 30), left_arm=A(35, 70, 0, 30), spine=S(8)),
            k(0.22, right_leg=Lg(8, 0, 8, 20)), k(0.45, right_leg=Lg(75, 0, 8, 90)), k(0.68, right_leg=Lg(8, 0, 8, 20))]


# =============================================================================
# 22. FLOOR / MAT POSITIONS (kneeling, all fours, lying, seated) - solved against the floor
# =============================================================================
STRAIGHT_LEGS = {"legs": {"dir": 0.0, "twist": 0.0}}


def _childs():
    return fit_pose("childs_pose", {"body.pitch": 110, "legs.raise": 100, "legs.knee": 150, "spine.lean": 10, "arms.raise": 150},
                    {"legs": {"dir": 0.0, "twist": 0.0}, "arms": {"dir": 5.0, "twist": 0.0, "elbow": 5.0}, "neck": {"nod": 10.0}},
                    [("right_foot", "floor", 0, 3), ("right_knee", "floor", 0, 3), ("head", "floor", 0, 2),
                     ("right_hand", "floor", 0, 2), ("pelvis", "y", 0.30, 0.5)])


def _table():
    return fit_pose("table_top", {"body.pitch": 90, "legs.raise": 90, "legs.knee": 90, "arms.raise": 90},
                    {"legs": {"dir": 0.0, "twist": 0.0}, "arms": {"dir": 5.0, "twist": 0.0, "elbow": 3.0}, "spine": {"lean": 0.0}},
                    [("right_knee", "floor", 0, 3), ("right_foot", "floor", 0, 2), ("right_hand", "floor", 0, 3),
                     ("pelvis", "y", 0.48, 1), ("neck", "y", 0.50, 1)])


def _down_dog():
    return fit_pose("downward_dog_v2", {"body.pitch": 120, "legs.raise": 75, "arms.raise": 175, "spine.lean": 0},
                    {"legs": {"dir": 0.0, "twist": 0.0, "knee": 2.0}, "arms": {"dir": 5.0, "twist": 0.0, "elbow": 2.0}, "neck": {"nod": 10.0}},
                    [("right_foot", "floor", 0, 3), ("right_hand", "floor", 0, 3), ("pelvis", "y", 0.95, 0.4),
                     ("right_hand", "z", 0.75, 1), ("right_foot", "z", -0.45, 1)])


def _cobra():
    return fit_pose("cobra", {"body.pitch": 90, "spine.lean": -40, "arms.raise": 40, "arms.elbow": 30},
                    {"legs": {"raise": 0.0, "dir": 0.0, "twist": 0.0, "knee": 0.0}, "arms": {"dir": 10.0, "twist": 0.0}, "neck": {"nod": -20.0}},
                    [("right_foot", "floor", 0, 3), ("pelvis", "y", 0.10, 2), ("right_hand", "floor", 0, 3), ("neck", "y", 0.55, 1)])


def _forearm_plank():
    return fit_pose("forearm_plank", {"body.pitch": 75, "arms.raise": 70, "arms.elbow": 90},
                    {"legs": {"raise": 0.0, "dir": 0.0, "twist": 0.0, "knee": 0.0}, "arms": {"dir": 5.0, "twist": 0.0}, "spine": {"lean": 0.0},
                     "neck": {"nod": -20.0}},
                    [("right_foot", "floor", 0, 3), ("right_elbow", "floor", 0, 3), ("right_hand", "floor", 0, 2)])


def _seated():
    return fit_pose("seated_v3", {"body.pitch": 0, "legs.raise": 90},
                    {"legs": {"dir": 0.0, "twist": 5.0, "knee": 3.0}, "spine": {"lean": 0.0},
                     "arms": {"raise": 25.0, "dir": 150.0, "twist": 0.0, "elbow": 5.0}},
                    [("right_foot", "floor", 0, 3), ("right_knee", "floor", 0, 3), ("neck", "z", 0.0, 2)])


def _side_plank_fit():
    return fit_pose("side_plank_v2", {"body.roll": 70, "right_arm.raise": 80, "right_arm.elbow": 90},
                    {"legs": {"raise": 0.0, "dir": 0.0, "twist": 0.0, "knee": 0.0}, "spine": {"lean": 0.0},
                     "right_arm": {"dir": 85.0, "twist": 90.0}, "left_arm": {"raise": 90.0, "dir": 88.0, "twist": 0.0, "elbow": 3.0}},
                    [("right_elbow", "floor", 0, 3), ("right_foot", "floor", 0, 3), ("pelvis", "y", 0.42, 1)])


@motion("kneel", "Tall kneeling: both knees on the floor, shins flat behind, hips over the knees, trunk upright.",
        "pose", LEGS, ARMS + ["spine"])
def _kneel():
    return [k(0.0, right_leg=Lg(0, 0, 0, 90), left_leg=Lg(0, 0, 0, 90), spine=S(3), right_arm=HANG, left_arm=HANG)]


@motion("half_kneel", "Half-kneeling: the left knee on the floor with the shin behind, the right foot planted in "
        "front with the knee at 90 degrees, trunk upright.", "pose", LEGS, ARMS + ["spine"])
def _half_kneel():
    return [k(0.0, right_leg=Lg(88, 0, 4, 90), left_leg=Lg(0, 0, 0, 90), spine=S(3), right_arm=HANG, left_arm=HANG)]


@motion("hip_flexor_stretch", "Kneeling hip-flexor stretch: from half-kneeling, shift the hips forward and reach the "
        "left arm overhead, hold.", "pose", LEGS + ARMS + ["spine", "pelvis"], [])
def _hip_flexor():
    return [k(0.0, **fit_pose("hip_flexor_stretch", {"right_leg.raise": 70, "right_leg.knee": 100, "left_leg.raise": 20,
                                                     "left_leg.knee": 90},
                               {"right_leg": {"dir": 0.0, "twist": 4.0}, "left_leg": {"dir": 180.0, "twist": 0.0},
                                "pelvis": {"tilt": -8.0}, "spine": {"lean": -6.0, "side": 10.0},
                                "left_arm": {"raise": 170.0, "dir": 15.0, "twist": 0.0, "elbow": 5.0},
                                "right_arm": {"raise": 25.0, "dir": 120.0, "twist": 60.0, "elbow": 100.0}},
                               [("right_foot", "floor", 0, 3), ("left_knee", "floor", 0, 3), ("left_foot", "floor", 0, 2),
                                ("right_foot", "z", 0.35, 1)]))]


@motion("childs_pose", "Child's pose (rest / stretch): kneeling with the hips sitting back on the heels, the "
        "chest folded down over the thighs, forehead on the floor and arms stretched long in front.",
        "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis", "neck"], [])
def _childs_pose():
    return [k(0.0, **_childs())]


@motion("table_top", "Hands-and-knees (all fours / table top): hands under the shoulders, knees under the hips, "
        "back flat.", "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _table_top():
    return [k(0.0, **_table(), neck=N(-10))]


@motion("cat_cow", "Cat-cow on hands and knees: round the back up with the chin tucked (cat), then let the belly "
        "drop with the chest and head lifted (cow).", "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis", "neck"], [],
        period=3.0)
def _cat_cow():
    t = _table()
    return [k(0.0, **{**t, "spine": S(22), "pelvis": P(-10), "neck": N(30)}), k(1.5, spine=S(-22), pelvis=P(10), neck=N(-30))]


@motion("bird_dog", "Bird dog: on hands and knees, reach the right arm forward and the left leg straight back, "
        "hold, return, switch sides.", "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"], period=3.2)
def _bird_dog():
    t = _table()
    leg_kn, arm_up = t["right_leg"], t["right_arm"]
    return [k(0.0, **t, neck=N(-10)),
            k(0.6, right_arm=full("right_arm", **{**arm_up, "raise": 175}), left_leg=full("left_leg", **{**leg_kn, "raise": 0.0, "knee": 3.0})),
            k(1.1, hold=True),
            k(1.6, right_arm=full("right_arm", **arm_up), left_leg=full("left_leg", **leg_kn)),
            k(2.2, left_arm=full("left_arm", **{**arm_up, "raise": 175}), right_leg=full("right_leg", **{**leg_kn, "raise": 0.0, "knee": 3.0})),
            k(2.7, hold=True)]


@motion("downward_dog", "Downward dog: hands and feet on the floor with the hips pushed high into an upside-down "
        "V, arms and legs long, head between the arms.", "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis", "neck"], [])
def _downward_dog():
    return [k(0.0, **_down_dog())]


@motion("cobra", "Cobra / upward dog: lying face down, press the hands into the floor and lift the chest, hips "
        "and legs stay on the floor, look forward.", "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis", "neck"], [])
def _cobra_pose():
    return [k(0.0, **_cobra())]


@motion("forearm_plank", "Forearm plank: forearms on the floor with the elbows under the shoulders, body in a "
        "straight line on the toes.", "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _forearm_plank_pose():
    return [k(0.0, **_forearm_plank())]


@motion("lie_on_back", "Lying flat on the back (supine), arms by the sides, legs long - rest or start position.",
        "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _supine():
    return [k(0.0, body=B(-90), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(0), pelvis=P(),
              right_arm=A(10, 30, 0, 5), left_arm=A(10, 30, 0, 5), neck=N())]


@motion("lie_face_down", "Lying face down (prone), arms by the sides or forward, legs long.", "pose",
        ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _prone():
    return [k(0.0, body=B(90), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(0), pelvis=P(),
              right_arm=A(10, 30, 0, 5), left_arm=A(10, 30, 0, 5), neck=N(-10))]


@motion("dead_bug", "Dead bug: on the back with arms pointing up and knees bent at 90 degrees in the air; lower "
        "the right arm overhead and the left leg long toward the floor, return, switch.", "cycle",
        ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"], period=3.0)
def _dead_bug():
    up_leg, up_arm = Lg(90, 0, 0, 90), A(90, 5, 0, 5)
    return [k(0.0, body=B(-90), spine=S(0), pelvis=P(), right_leg=up_leg, left_leg=up_leg, right_arm=up_arm, left_arm=up_arm, neck=N(10)),
            k(0.7, right_arm=A(170, 5, 0, 5), left_leg=Lg(15, 0, 0, 5)), k(1.1, hold=True),
            k(1.5, right_arm=up_arm, left_leg=up_leg),
            k(2.2, left_arm=A(170, 5, 0, 5), right_leg=Lg(15, 0, 0, 5)), k(2.6, hold=True)]


@motion("side_plank", "Side plank on the right forearm: body in a straight line sideways, hips lifted, the left "
        "arm on the hip or reaching up.", "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _side_plank():
    return [k(0.0, **_side_plank_fit(), pelvis=P(), neck=N())]


@motion("seated", "Sitting on the floor with the legs straight out in front, trunk upright, hands beside the hips.",
        "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _seated_pose():
    return [k(0.0, **_seated())]


@motion("seated_forward_fold", "Seated forward fold / sit-and-reach: sitting with straight legs, hinge forward and "
        "reach the hands toward the toes, hold.", "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _seated_fold():
    return [k(0.0, **fit_pose("seated_fold_v2", {"body.pitch": 0, "legs.raise": 90, "spine.lean": 50, "arms.raise": 60},
                               {"legs": {"dir": 0.0, "twist": 5.0, "knee": 3.0}, "arms": {"dir": 5.0, "twist": 0.0, "elbow": 5.0},
                                "neck": {"nod": 15.0}},
                               [("right_foot", "floor", 0, 3), ("right_knee", "floor", 0, 3), ("pelvis", "y", 0.11, 3),
                                ("right_hand", "y", 0.16, 2), ("right_hand", "z", 0.62, 1),
                                ("neck", "z", 0.42, 2), ("neck", "y", 0.38, 1)]))]


@motion("butterfly_stretch", "Butterfly stretch: sitting tall with the soles of the feet together and the knees "
        "dropped out to the sides, hands holding the feet.", "pose", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"])
def _butterfly_stretch():
    return [k(0.0, **fit_pose("butterfly_v2", {"body.pitch": -10, "legs.raise": 60, "legs.knee": 120, "spine.lean": 15},
                               {"legs": {"dir": 60.0, "twist": 70.0}, "arms": {"raise": 45.0, "dir": 0.0, "twist": 0.0, "elbow": 30.0}},
                               [("right_foot", "floor", 0, 3), ("pelvis", "y", 0.11, 3), ("right_knee", "y", 0.22, 1),
                                ("neck", "z", 0.08, 2)]))]


@motion("get_up_from_floor", "Get up from lying on the back: roll up to sitting, tuck the feet in, push up through "
        "a squat to standing.", "action", ["body"] + ARMS + LEGS + ["spine", "pelvis", "neck"], [])
def _get_up():
    return [k(0.0, body=B(-90), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(0), pelvis=P(),
              right_arm=A(10, 30, 0, 5), left_arm=A(10, 30, 0, 5), neck=N()),
            k(0.7, body=B(-20), spine=S(30), right_leg=Lg(60, 0, 8, 100), left_leg=Lg(60, 0, 8, 100), right_arm=A(30, 150, 0, 5), left_arm=A(60, 5, 0, 10)),
            k(1.3, body=B(0), **stance_legs("normal", 1.25), spine=S(45), right_arm=A(60, 5, 0, 10), left_arm=A(60, 5, 0, 10)),
            k(2.1, **stance_legs("normal", 0.05), spine=S(4), right_arm=HANG, left_arm=HANG, neck=N())]


# =============================================================================
# 23. ATHLETIC POSITIONS - core team / field / racket / water sports (general names)
# =============================================================================
FULL = LEGS + ARMS + ["spine", "pelvis"]


def grip2(x: float, y: float, z: float, el: str = "down") -> Dict[str, Dict[str, float]]:
    """Both hands together on one implement at (x, y, z) from the middle of the shoulder line."""
    return {"right_arm": arm_at(x, y, z, el, "right"), "left_arm": arm_at(-x, y, z, el, "left")}


def both(x: float, y: float, z: float, el: str = "down") -> Dict[str, Dict[str, float]]:
    """Both hands mirrored at (x out, y, z) - e.g. hands up in front, palms forward."""
    return {"right_arm": arm_at(x, y, z, el, "right"), "left_arm": arm_at(x, y, z, el, "left")}


@motion("two_point_stance", "Two-point (standing) start stance: staggered feet with the left foot forward, knees "
        "bent, weight on the front foot, trunk leaning forward, right arm forward and left arm back, ready to "
        "explode forward (receivers, sprint standing start, ready to chase).", "pose", FULL, ["neck"])
def _two_point():
    return [k(0.0, **stance_legs("narrow", 0.5, "left", 10), spine=S(32), pelvis=P(8), right_arm=A(45, 5, -15, 80),
              left_arm=A(35, 175, 10, 70), neck=N(-15))]


@motion("four_point_stance", "Four-point stance: both hands on the ground in front, hips high and level with the "
        "shoulders, weight forward on hands and toes (lineman, wrestler down stance).", "pose",
        ["body"] + FULL, ["neck"])
def _four_point():
    return [k(0.0, **fit_pose("four_point", {"body.pitch": 55, "legs.raise": 70, "legs.knee": 110, "arms.raise": 80},
                               {"legs": {"dir": 0.0, "twist": 12.0}, "arms": {"dir": 5.0, "twist": 0.0, "elbow": 3.0},
                                "spine": {"lean": 10.0}, "neck": {"nod": -30.0}},
                               [("right_foot", "floor", 0, 3), ("right_hand", "floor", 0, 3), ("pelvis", "y", 0.62, 1),
                                ("right_hand", "z", 0.55, 1)]))]


@motion("hands_on_knees", "Bent over with the hands resting on the knees (huddle, catching breath, back stance "
        "of a running back).", "pose", FULL, ["neck"])
def _hands_on_knees():
    return [k(0.0, **fit_pose("hands_on_knees", {"spine.lean": 45, "arms.raise": 40, "arms.elbow": 15},
                               {**stance_legs("normal", 0.45), "arms": {"dir": 5.0, "twist": 0.0}, "pelvis": {"tilt": 10.0}},
                               [("right_hand", "y", 0.50, 3), ("right_hand", "z", 0.20, 2), ("neck", "y", 1.05, 1)]))]


@motion("crouch_hands_low", "Low crouch with both hands together low in front, palms down, ready to receive a "
        "ball snapped or rolled to them (quarterback under centre, holder, scrum-half at the base).", "pose",
        FULL, ["neck"])
def _crouch_hands_low():
    return [k(0.0, **stance_legs("normal", 0.7), spine=S(35), pelvis=P(10), **grip2(0.05, -0.45, 0.38, "out"), neck=N(-10))]


@motion("one_knee_hands_ready", "Kneeling on the right knee with the left foot forward, hands out in front ready to "
        "catch and place a ball (holder, ball placement, kneeling catch).", "pose", FULL, ["neck"])
def _one_knee_ready():
    return [k(0.0, left_leg=Lg(88, 0, 4, 90), right_leg=Lg(0, 0, 0, 90), spine=S(20), **both(0.18, -0.25, 0.42, "out"))]


@motion("one_arm_up", "One arm raised straight up overhead (fair catch, signal, asking for the ball, point to the "
        "sky, umpire 'out' with the finger up).", "pose", ["right_arm"], ["left_arm"])
def _one_arm_up():
    return [k(0.0, right_arm=A(172, 15, 0, 3), left_arm=HANG)]


@motion("post_up", "Post-up position: wide low stance with the back to the defender, the left forearm held "
        "horizontal as a bar, the right hand up as a target, chest up.", "pose", FULL, ["neck"])
def _post_up():
    return [k(0.0, **stance_legs("very_wide", 0.7), spine=S(20), pelvis=P(10), left_arm=A(80, 40, 90, 95),
              right_arm=A(120, 20, 0, 40), neck=N(0, -40))]


@motion("denial_stance", "Denial stance: low and side-on, the lead (right) arm stretched out into the passing lane "
        "with the palm out, head turned to see the ball.", "pose", FULL, ["neck"])
def _denial():
    return [k(0.0, **stance_legs("wide", 0.7), spine=S(25, 30), pelvis=P(8, 20), right_arm=A(80, 70, 0, 8),
              left_arm=A(40, 60, -10, 70), neck=N(0, 45))]


@motion("help_side_stance", "Help-side defense ('pistols'): open stance, one hand pointing at the ball and the other "
        "at the opponent.", "pose", FULL, ["neck"])
def _pistols():
    return [k(0.0, **stance_legs("wide", 0.55), spine=S(20), pelvis=P(6), right_arm=A(75, 60, 0, 5),
              left_arm=A(75, 60, 0, 5), neck=N(0, 20))]


@motion("goalkeeper_set", "Goalkeeper set position: wide and low on the balls of the feet, hands up in front at "
        "chest height with the palms forward and elbows bent, ready to react.", "pose", FULL, ["neck"])
def _gk_set():
    return [k(0.0, **stance_legs("wide", 0.65), spine=S(25), pelvis=P(8), **both(0.28, -0.12, 0.30, "down"))]


@motion("jockey_stance", "Side-on low defending stance (jockeying): staggered feet, knees bent, weight on the "
        "balls of the feet, arms slightly out for balance, staying between opponent and goal.", "pose", FULL, ["neck"])
def _jockey():
    return [k(0.0, **stance_legs("normal", 0.6, "left", 20), spine=S(20, 30), pelvis=P(8, 25), right_arm=A(35, 70, 0, 40),
              left_arm=A(35, 70, 0, 40))]


@motion("defensive_wall", "Standing in a wall: feet together, body straight and braced, both hands crossed in front "
        "of the groin.", "pose", FULL, ["neck"])
def _wall():
    return [k(0.0, right_leg=Lg(2, 0, 4, 3), left_leg=Lg(2, 0, 4, 3), spine=S(3),
              right_arm=arm_at(-0.05, -0.62, 0.18, "out", "right"), left_arm=arm_at(-0.05, -0.60, 0.20, "out", "left"))]


@motion("trophy_position", "Serve trophy position: knees bent, the left (toss) arm straight up, the right (hitting) "
        "arm bent with the elbow at shoulder height and the hand behind the head, back arched.", "pose", FULL, ["neck"])
def _trophy():
    return [k(0.0, **stance_legs("normal", 0.6, "left", 30), spine=S(-12, 45), pelvis=P(-4, 30), right_arm=A(95, 120, 80, 100),
              left_arm=A(165, 10, 0, 5), neck=N(-30, -10))]


@motion("unit_turn_right", "Unit turn to the right (forehand side): shoulders and hips turned, both hands back on the "
        "right side, left arm across, ready to swing.", "pose", FULL, ["neck"])
def _unit_turn_r():
    return [k(0.0, **stance_legs("wide", 0.45), right_arm=A(70, 140, 30, 70), left_arm=A(85, -10, 0, 15), spine=S(10, 62),
              pelvis=P(3, 30), neck=N(5, -45))]


@motion("unit_turn_left", "Unit turn to the left (backhand side): shoulders turned left with both hands back by the "
        "left hip.", "pose", FULL, ["neck"])
def _unit_turn_l():
    return [k(0.0, **stance_legs("wide", 0.45), **grip2(-0.30, -0.35, 0.22), spine=S(12, -70), pelvis=P(3, -35), neck=N(5, 45))]


@motion("overhead_ready", "Ready to hit an overhead: side-on, the left arm pointing up at the ball, the right hand "
        "cocked behind the head with the elbow up.", "pose", FULL, ["neck"])
def _overhead_ready():
    return [k(0.0, **stance_legs("normal", 0.35, "left", 30), spine=S(-6, 50), pelvis=P(0, 35), left_arm=A(150, 10, 0, 5),
              right_arm=A(100, 130, 80, 110), neck=N(-30, -30))]


@motion("hitting_stance", "Batting / hitting stance: side-on, feet wider than the shoulders, knees flexed, both "
        "hands up by the rear (right) shoulder holding the bat, head turned to the pitcher.", "pose", FULL, ["neck"])
def _hitting():
    return [k(0.0, **stance_legs("wide", 0.35), **grip2(0.22, 0.05, 0.16), spine=S(12, 25), pelvis=P(4, 15), neck=N(5, -60))]


@motion("set_position", "Pitcher's set / stretch position: side-on, feet narrow, hands together at the chest, "
        "head turned to the target.", "pose", FULL, ["neck"])
def _set_pos():
    return [k(0.0, **stance_legs("narrow", 0.15), **grip2(0.0, -0.18, 0.25, "down"), spine=S(5, 70), pelvis=P(0, 60), neck=N(0, -70))]


@motion("balance_point", "Balance point of a throw: side-on, standing on the right leg with the left knee lifted "
        "high, hands together at the chest.", "pose", FULL, ["neck"])
def _balance_pt():
    return [k(0.0, right_leg=leg_at(0.0, 0.14, 0.08, 0, 30, "right"), left_leg=Lg(85, 10, 8, 100),
              **grip2(0.0, -0.18, 0.25, "down"), spine=S(0, 70), pelvis=P(0, 60), neck=N(0, -70))]


@motion("fielder_ready", "Infield / fielding ready position: wide stance, knees bent, hips back, both hands low "
        "out in front with the glove open.", "pose", FULL, ["neck"])
def _fielder_ready():
    return [k(0.0, **stance_legs("wide", 0.75), spine=S(40), pelvis=P(12), **both(0.18, -0.50, 0.38, "out"), neck=N(-15))]


@motion("long_stretch_reach", "Long stretch toward a throw: a big split with the left leg reaching forward, the "
        "right foot staying back, the glove arm stretched far forward (first-base stretch, long reach).", "pose",
        FULL, ["neck"])
def _long_stretch():
    return [k(0.0, left_leg=leg_at(0.55, 0.14, 0.36, 0, 10, "left"), right_leg=Lg(35, 180, 4, 15), spine=S(30),
              left_arm=A(85, 0, 0, 5), right_arm=A(30, 120, 0, 30))]


@motion("prone_reach", "Lying face down with one arm stretched long overhead along the floor (head-first slide "
        "finish, sprawl / pancake save).", "pose", ["body"] + FULL, ["neck"])
def _prone_reach():
    return [k(0.0, body=B(90), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(5, 0, 0, 20), spine=S(0), pelvis=P(),
              right_arm=A(172, 8, 0, 3), left_arm=A(150, 20, 0, 10), neck=N(-15))]


@motion("hands_up_ready", "Standing with both hands up in front at shoulder height, palms forward (blocker ready, "
        "ready to catch, hands up to defend).", "pose", [], ARMS)
def _hands_up():
    return [k(0.0, **both(0.26, 0.02, 0.28, "down"))]


@motion("jump_load", "Loaded take-off position: deep knee bend, hips back, chest forward, both arms swung back "
        "behind the hips.", "pose", FULL, ["neck"])
def _jump_load():
    return [k(0.0, **stance_legs("normal", 0.9), spine=S(40), pelvis=P(10), right_arm=A(50, 175, 10, 12), left_arm=A(50, 175, 10, 12))]


@motion("platform_ready", "Low ready with the forearms together in a platform below the waist (dig / pass "
        "ready).", "pose", FULL, ["neck"])
def _platform_ready():
    return [k(0.0, **stance_legs("wide", 0.75), spine=S(30), pelvis=P(10), **grip2(0.0, -0.55, 0.34, "out"), neck=N(-10))]


@motion("side_on_batting_stance", "Side-on stance with the bat grounded behind the back foot: feet shoulder width, "
        "knees flexed, hands together low, head turned to face the bowler.", "pose", FULL, ["neck"])
def _cricket_stance():
    return [k(0.0, **stance_legs("normal", 0.35), **grip2(0.10, -0.42, 0.18), spine=S(18, 35), pelvis=P(5, 30), neck=N(5, -65))]


@motion("backlift", "Backlift / bat raised: side-on stance with both hands lifting the bat high behind the right "
        "shoulder, ready to swing down.", "pose", FULL, ["neck"])
def _backlift():
    return [k(0.0, **stance_legs("normal", 0.35), **grip2(0.30, 0.30, 0.22, "out"), spine=S(12, 40), pelvis=P(4, 30), neck=N(5, -60))]


@motion("slip_catch_stance", "Close-catching stance: crouched low, hands together cupped at knee height in front, "
        "eyes forward.", "pose", FULL, ["neck"])
def _slip():
    return [k(0.0, **stance_legs("wide", 0.85), spine=S(40), pelvis=P(12), **grip2(0.0, -0.58, 0.30, "out"), neck=N(-20))]


@motion("delivery_stride", "Delivery stride / coil before a throw: side-on, front (left) arm pointing up high, the "
        "right hand back by the hip, front knee lifted.", "pose", FULL, ["neck"])
def _coil():
    return [k(0.0, right_leg=leg_at(0.0, 0.14, 0.10, 0, 40, "right"), left_leg=Lg(70, 15, 10, 90), spine=S(-8, 60),
              pelvis=P(0, 40), left_arm=A(150, 20, 0, 10), right_arm=A(40, 165, 0, 15), neck=N(0, -60))]


@motion("t_signal", "Hands forming a T in front of the chest (time-out signal).", "pose", ARMS, [])
def _t_signal():
    return [k(0.0, right_arm=arm_at(0.0, 0.10, 0.40, "down", "right"), left_arm=arm_at(0.0, -0.08, 0.30, "out", "left"))]


@motion("arms_crossed", "Arms folded across the chest (waiting, listening, resting).", "pose", ARMS, [])
def _arms_crossed():
    return [k(0.0, right_arm=arm_at(-0.12, -0.20, 0.22, "down", "right"), left_arm=arm_at(-0.12, -0.16, 0.25, "down", "left"))]


@motion("hands_on_head", "Hands resting on top of the head (exhausted, disbelief, recovering).", "pose", ARMS, [])
def _hands_on_head():
    return [k(0.0, right_arm=A(130, 80, 90, 120), left_arm=A(130, 80, 90, 120))]


@motion("overhead_lift_hold", "Lifting position: half squat with both arms straight up overhead and the hands close "
        "together, supporting a teammate or a weight above the head (lineout lifter, overhead hold).", "pose", FULL, ["neck"])
def _overhead_lift():
    return [k(0.0, **stance_legs("normal", 0.45), spine=S(5), **both(0.12, 0.62, 0.10, "out"))]


@motion("jackal_position", "Over-the-ball position: feet wide, hips low and back flat over the ball, both hands "
        "reaching down to the ground in front (jackal, pick up from the ground, ruck).", "pose", FULL, ["neck"])
def _jackal():
    return [k(0.0, **stance_legs("very_wide", 0.8), spine=S(60), pelvis=P(15), right_arm=A(70, 5, 0, 5), left_arm=A(70, 5, 0, 5),
              neck=N(-20))]


@motion("hands_target", "Hands up and open as a target at chest height, fingers spread, calling for the ball.",
        "pose", [], ARMS)
def _hands_target():
    return [k(0.0, **both(0.14, -0.05, 0.42, "out"))]


@motion("swing_top", "Top of a full two-hand backswing: shoulders turned fully, hands high over the right shoulder.",
        "pose", FULL, ["neck"])
def _swing_top():
    return [k(0.0, **stance_legs("wide", 0.2), **grip2(0.30, 0.05, 0.14), spine=S(32, 88), pelvis=P(10, 40), neck=N(25, -65))]


@motion("swing_finish", "Balanced high finish of a two-hand swing: chest facing the target, hands high over the "
        "left shoulder, weight on the left foot with the right heel up.", "pose", FULL, ["neck"])
def _swing_finish():
    return [k(0.0, left_leg=leg_at(0.0, 0.20, 0.03, 0, 30, "left"), right_leg=Lg(18, -20, 40, 40), **grip2(-0.28, 0.12, 0.12),
              spine=S(5, -85), pelvis=P(2, -55), neck=N(0, 60))]


@motion("low_crouch", "Deep crouch on the heels with the forearms resting on the knees (reading the green, "
        "waiting low, catcher at rest).", "pose", FULL, ["neck"])
def _low_crouch():
    return [k(0.0, **stance_legs("normal", 1.3), spine=S(35), pelvis=P(12), right_arm=A(45, 10, -20, 70),
              left_arm=A(45, 10, -20, 70), neck=N(-5))]


@motion("on_the_blocks", "Crouched on a starting block / edge: knees bent, trunk folded forward, both hands "
        "gripping at the toes, head down (swimming start, ready to dive).", "pose", FULL, ["neck"])
def _on_blocks():
    return [k(0.0, right_leg=Lg(60, 0, 8, 100), left_leg=Lg(60, 0, 8, 100), spine=S(85), pelvis=P(20),
              right_arm=A(85, 5, 0, 5), left_arm=A(85, 5, 0, 5), neck=N(-20))]


@motion("sculling", "Sculling in the water: body horizontal face up, hands at the hips sweeping in and out in a "
        "figure-eight to stay afloat.", "cycle", ["body"] + FULL, ["neck"], period=1.0)
def _sculling():
    body = B(pitch=-86, air=1.0, root=0.0)
    return [k(0.0, body=body, right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(0), right_arm=A(25, 60, 60, 20),
              left_arm=A(25, 60, 60, 20), neck=N(10)),
            k(0.5, right_arm=A(25, 20, 30, 20), left_arm=A(25, 20, 30, 20))]


@motion("open_turn", "Open (touch) turn at a wall: both hands touch, knees tuck to the chest, the body turns "
        "sideways, one arm goes over, feet plant and push off into a streamline.", "action",
        ["body"] + FULL + ["neck"], [])
def _open_turn():
    return [k(0.0, body=SWIM_BODY, right_arm=A(170, 8, 0, 10), left_arm=A(170, 8, 0, 10), right_leg=Lg(0, 0, 0, 0),
              left_leg=Lg(0, 0, 0, 0), spine=S(0), neck=N(-15)),
            k(0.4, body=B(pitch=40, air=1.0), right_arm=A(110, 10, 0, 60), left_arm=A(110, 10, 0, 60), right_leg=Lg(110, 0, 0, 130),
              left_leg=Lg(110, 0, 0, 130), spine=S(30)),
            k(0.8, body=B(pitch=30, turn=-90, air=1.0), right_arm=A(170, 30, 0, 20)),
            k(1.2, body=B(pitch=86, turn=-180, air=1.0, root=-0.15), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0),
              right_arm=A(172, 8, 0, 4), left_arm=A(172, 8, 0, 4), spine=S(0), neck=N(-10))]


@motion("pass_block_set", "Pass-protection set: wide base, knees bent, back straight, both hands up at chest "
        "height ready to punch, weight on the insides of the feet.", "pose", FULL, ["neck"])
def _pass_set():
    return [k(0.0, **stance_legs("wide", 0.65), spine=S(15), pelvis=P(8), **both(0.16, -0.18, 0.30, "down"))]


@motion("tip_off_ready", "Jump-ball / contest-ready: knees bent, the right arm raised, eyes up.", "pose", FULL, ["neck"])
def _tip_off():
    return [k(0.0, **stance_legs("normal", 0.6), spine=S(10), pelvis=P(4), right_arm=A(150, 20, 0, 20), left_arm=A(30, 60, 0, 30),
              neck=N(-25))]


@motion("fist_pump", "Celebration fist pump: the right fist pulled down hard from above the head to the chest.",
        "action", ["right_arm"], ["left_arm", "spine"])
def _fist_pump():
    return [k(0.0, right_arm=HANG, spine=S(3)), k(0.3, right_arm=A(150, 30, 0, 60)), k(0.5, right_arm=A(45, 30, -40, 130), spine=S(12)),
            k(0.7, right_arm=A(150, 30, 0, 60), spine=S(3)), k(0.9, right_arm=A(45, 30, -40, 130), spine=S(12)), k(1.3, right_arm=HANG, spine=S(3))]


@motion("high_five", "High five: the right arm swings up and forward to slap hands at head height.", "action",
        ["right_arm"], ["spine"])
def _high_five():
    return [k(0.0, right_arm=HANG), k(0.35, right_arm=A(140, 15, 0, 25)), k(0.45, right_arm=A(130, 10, 0, 10)), k(0.8, right_arm=HANG)]


_POS_ALIASES = {
    "two point stance": "two_point_stance(hold=1.5)", "standing start": "two_point_stance(hold=1.5)",
    "receiver stance": "two_point_stance(hold=1.5)", "four point stance": "four_point_stance(hold=1.5)",
    "lineman stance": "four_point_stance(hold=1.5)", "hands on knees": "hands_on_knees(hold=1.5)", "huddle": "hands_on_knees(hold=1.5)",
    "under center": "crouch_hands_low(hold=1.5)", "quarterback under center": "crouch_hands_low(hold=1.5)",
    "holder": "one_knee_hands_ready(hold=1.5)", "fair catch": "stand + one_arm_up(hold=1.5)", "fair catch signal": "stand + one_arm_up(hold=1.5)",
    "post up": "post_up(hold=1.5)", "denial stance": "denial_stance(hold=1.5)", "deny the pass": "denial_stance(hold=1.5)",
    "help side": "help_side_stance(hold=1.5)", "pistols": "help_side_stance(hold=1.5)",
    "goalkeeper set": "goalkeeper_set(hold=1.5)", "goalkeeper set position": "goalkeeper_set(hold=1.5)",
    "goalie stance": "goalkeeper_set(hold=1.5)", "jockey": "jockey_stance(hold=1.5)", "jockeying": "jockey_stance(hold=1.5)",
    "wall": "defensive_wall(hold=1.5)", "free kick wall": "defensive_wall(hold=1.5)",
    "trophy position": "trophy_position(hold=1.5)", "serve trophy position": "trophy_position(hold=1.5)",
    "unit turn": "unit_turn_right(hold=1.5)", "forehand unit turn": "unit_turn_right(hold=1.5)",
    "backhand unit turn": "unit_turn_left(hold=1.5)", "overhead ready": "overhead_ready(hold=1.5)",
    "batting stance": "hitting_stance(hold=1.5)", "hitting stance": "hitting_stance(hold=1.5)",
    "set position": "set_position(hold=1.5)", "pitcher set position": "set_position(hold=1.5)", "stretch position": "set_position(hold=1.5)",
    "balance point": "balance_point(hold=1.5)", "leg lift": "balance_point(hold=1.5)",
    "infield ready": "fielder_ready(hold=1.5)", "fielding position": "fielder_ready(hold=1.5)", "ready position fielding": "fielder_ready(hold=1.5)",
    "first base stretch": "long_stretch_reach(hold=1.5)", "head first slide": "run(times=2)\nprone_reach(hold=1)",
    "headfirst slide": "run(times=2)\nprone_reach(hold=1)", "pancake": "prone_reach(hold=1.5)",
    "blocker ready": "stance(depth=0.4) + hands_up_ready(hold=1.5)", "block ready": "stance(depth=0.4) + hands_up_ready(hold=1.5)",
    "jump load": "jump_load(hold=1.5)", "dig ready": "platform_ready(hold=1.5)", "passing ready": "platform_ready(hold=1.5)",
    "cricket batting stance": "side_on_batting_stance(hold=1.5)", "backlift": "backlift(hold=1.5)",
    "slip fielder": "slip_catch_stance(hold=1.5)", "slips": "slip_catch_stance(hold=1.5)",
    "delivery stride": "delivery_stride(hold=1.5)", "time out signal": "stand + t_signal(hold=1.5)", "timeout": "stand + t_signal(hold=1.5)",
    "arms crossed": "stand + arms_crossed(hold=1.5)", "hands on head": "stand + hands_on_head(hold=1.5)",
    "lineout lift": "overhead_lift_hold(hold=1.5)", "lifting in the lineout": "overhead_lift_hold(hold=1.5)",
    "jackal": "jackal_position(hold=1.5)", "over the ball": "jackal_position(hold=1.5)",
    "call for the ball": "stance(depth=0.3) + hands_target(hold=1.5)", "hands target": "stance(depth=0.3) + hands_target(hold=1.5)",
    "top of backswing": "swing_top(hold=1.5)", "top of the backswing": "swing_top(hold=1.5)", "golf finish": "swing_finish(hold=1.5)",
    "swing finish": "swing_finish(hold=1.5)", "read the green": "low_crouch(hold=1.5)", "crouch": "low_crouch(hold=1.5)",
    "on the blocks": "on_the_blocks(hold=1.5)", "swimming starting position": "on_the_blocks(hold=1.5)",
    "sculling": "sculling(times=3)", "open turn": "front_crawl\nopen_turn", "touch turn": "front_crawl\nopen_turn",
    "pass set": "pass_block_set(hold=1.5)", "pass protection": "pass_block_set(hold=1.5)",
    "jump ball": "tip_off_ready(hold=1.5)", "tip off": "tip_off_ready(hold=1.5)", "fist pump": "stand + fist_pump",
    "high five": "stand + high_five", "celebrate": "jump + arms_overhead", "touchdown signal": "stand + arms_overhead(hold=1.5)",
}


# =============================================================================
# 24. POSITIONS + SKILLS - other sports (general names)
# =============================================================================
@motion("stick_ready", "Two-hand stick ready position (ice / field hockey, floorball): knees bent, trunk forward, "
        "both hands on the stick with the blade on the ground to the right front.", "pose", FULL, ["neck"])
def _stick_ready():
    return [k(0.0, **stance_legs("wide", 0.6), spine=S(35, 10), pelvis=P(10), **grip2(0.20, -0.52, 0.34), neck=N(-10))]


@motion("stickhandling", "Stickhandling: low stance, both hands on the stick moving the blade side to side in front "
        "(dribbling a puck or ball).", "cycle", ARMS + ["spine"], ["neck"], period=0.7)
def _stickhandling():
    return grip_keys([(0.0, 0.32, -0.52, 0.34, "down"), (0.35, -0.08, -0.52, 0.40, "down"), (0.7, 0.32, -0.52, 0.34, "down")], step=0.07) \
        + [k(0.0, spine=S(35, 15)), k(0.35, spine=S(35, -5))]


@motion("wrist_shot", "Two-hand wrist / sweep shot with a stick: blade back on the right, weight transfer, sweep "
        "forward along the ground and snap through to a follow-through pointing at the target.", "action",
        ARMS + ["spine"], ["pelvis", "neck"])
def _wrist_shot():
    return grip_keys([(0.0, 0.30, -0.44, 0.40, "down"), (0.4, 0.34, -0.42, 0.40, "down"), (0.7, 0.05, -0.52, 0.42, "down"),
                      (0.9, -0.25, -0.20, 0.45, "out"), (1.3, -0.25, -0.20, 0.45, "out")]) + \
        [k(0.0, spine=S(30, 30), pelvis=P(8, 15)), k(0.4, spine=S(30, 40)), k(0.7, spine=S(32, 0), pelvis=P(8, -10)),
         k(0.9, spine=S(25, -30), pelvis=P(6, -25)), k(1.3, hold=True)]


@motion("butterfly_block", "Butterfly save position (hockey goalkeeper): dropped onto both knees with the knees "
        "together and the shins flared out flat to the sides, trunk upright, glove and blocker hands out.",
        "pose", FULL, ["neck"])
def _butterfly_block():
    return [k(0.0, right_leg=Lg(5, 10, -75, 100), left_leg=Lg(5, 10, -75, 100), spine=S(10), right_arm=A(45, 60, 0, 40),
              left_arm=A(55, 70, 0, 30))]


@motion("skating_stride", "Skating stride (ice, roller, speed skating): deep knee bend, trunk low and forward, each "
        "leg pushes out to the side in turn while the opposite arm swings.", "cycle", LEGS + ["pelvis", "spine"], ARMS,
        period=1.2)
def _skating():
    low = 0.75
    push_r = {"right_leg": leg_at(-0.05, 0.50, 0.25, 0.03, 30, "right"), "left_leg": leg_at(0.05, 0.10, 0.25, 0.0, 10, "left")}
    push_l = {"left_leg": leg_at(-0.05, 0.50, 0.25, 0.03, 30, "left"), "right_leg": leg_at(0.05, 0.10, 0.25, 0.0, 10, "right")}
    return [k(0.0, **push_r, spine=S(55), pelvis=P(12, -10), right_arm=A(40, 160, 0, 20), left_arm=A(50, -20, 0, 30)),
            k(0.6, **push_l, pelvis=P(12, 10), left_arm=A(40, 160, 0, 20), right_arm=A(50, -20, 0, 30))]


@motion("stick_cradle", "Cradling a stick (lacrosse): the top hand by the right ear, the bottom hand at the chest, "
        "the stick rocking with the wrists while moving.", "cycle", ARMS, ["neck"], period=0.6)
def _cradle():
    a = {"right_arm": arm_at(0.28, 0.14, 0.10, "down", "right"), "left_arm": arm_at(-0.04, -0.12, 0.25, "down", "left")}
    b = {"right_arm": arm_at(0.24, 0.16, 0.16, "down", "right"), "left_arm": arm_at(0.02, -0.10, 0.28, "down", "left")}
    return [k(0.0, **a), k(0.3, **b)]


@motion("blocks_on_your_marks", "Sprint blocks 'on your marks': the right knee down, the left foot forward, both hands "
        "on the line under the shoulders, head down.", "pose", ["body"] + FULL, ["neck"])
def _marks():
    return [k(0.0, **fit_pose("on_your_marks", {"body.pitch": 50, "spine.lean": 30, "arms.raise": 70, "left_leg.raise": 95,
                                                 "left_leg.knee": 120, "right_leg.raise": 40, "right_leg.knee": 110},
                               {"arms": {"dir": 5.0, "twist": 0.0, "elbow": 2.0}, "right_leg": {"dir": 0.0, "twist": 5.0},
                                "left_leg": {"dir": 0.0, "twist": 5.0}, "neck": {"nod": 15.0}},
                               [("right_hand", "floor", 0, 3), ("right_knee", "floor", 0, 3), ("left_foot", "floor", 0, 3),
                                ("right_foot", "floor", 0, 1), ("right_hand", "z", 0.45, 1)]))]


@motion("blocks_set", "Sprint blocks 'set': hips raised slightly above the shoulders, both knees off the ground and "
        "bent, hands on the line, weight forward.", "pose", ["body"] + FULL, ["neck"])
def _blocks_set():
    return [k(0.0, **fit_pose("blocks_set", {"body.pitch": 60, "spine.lean": 20, "arms.raise": 70, "left_leg.raise": 80,
                                              "left_leg.knee": 90, "right_leg.raise": 45, "right_leg.knee": 60},
                               {"arms": {"dir": 5.0, "twist": 0.0, "elbow": 2.0}, "right_leg": {"dir": 0.0, "twist": 5.0},
                                "left_leg": {"dir": 0.0, "twist": 5.0}, "neck": {"nod": 10.0}},
                               [("right_hand", "floor", 0, 3), ("left_foot", "floor", 0, 3), ("right_foot", "floor", 0, 3),
                                ("pelvis", "y", 0.70, 1), ("right_hand", "z", 0.45, 1)]))]


@motion("long_jump", "Long jump: a few fast approach strides, take off from the left foot driving the right knee up, "
        "arms up in flight, legs reach forward for the landing into a deep sit.", "action", LEGS + ["body"],
        ARMS + ["spine", "pelvis"])
def _long_jump():
    pts, T = _flight(0.9, 0.45)
    keys = [k(0.0, right_leg=Lg(50, 0, 6, 90), left_leg=Lg(25, 180, 6, 20), body=B(), spine=S(12), right_arm=A(45, 175, 10, 70),
              left_arm=A(65, 6, -15, 90)),
            k(0.3, left_leg=Lg(50, 0, 6, 90), right_leg=Lg(25, 180, 6, 20), right_arm=A(65, 6, -15, 90), left_arm=A(45, 175, 10, 70)),
            k(0.6, right_leg=Lg(50, 0, 6, 90), left_leg=Lg(25, 180, 6, 20), right_arm=A(45, 175, 10, 70), left_arm=A(65, 6, -15, 90)),
            k(0.9, left_leg=Lg(15, 180, 6, 5), right_leg=Lg(85, 0, 6, 95), body=B(air=1.0), spine=S(5),
              right_arm=A(150, 10, 0, 20), left_arm=A(120, 10, 0, 30))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    mid = pts[len(pts) // 2][0]
    keys.append(k(mid, right_leg=Lg(70, 0, 6, 60), left_leg=Lg(60, 0, 6, 70), right_arm=A(160, 10, 0, 10), left_arm=A(160, 10, 0, 10)))
    tl = pts[-1][0]
    keys += [k(tl - 0.1, right_leg=Lg(95, 0, 6, 15), left_leg=Lg(95, 0, 6, 15), spine=S(40), right_arm=A(70, 5, 0, 10), left_arm=A(70, 5, 0, 10)),
             k(tl, body=B(air=1.0, root=0.0)), k(tl + 0.04, body=B(air=0.0)),
             k(tl + 0.4, **stance_legs("normal", 1.3), spine=S(40), right_arm=A(80, 5, 0, 10), left_arm=A(80, 5, 0, 10)),
             k(tl + 0.8, hold=True)]
    return keys


@motion("back_arch_flight", "Arched back in the air facing up (high-jump flop over a bar): hips pushed up, head and "
        "shoulders back, knees bent with the feet trailing.", "pose", ["body"] + FULL, ["neck"])
def _flop():
    return [k(0.0, body=B(pitch=-90, air=1.0, root=0.55), spine=S(-35), pelvis=P(-15), right_leg=Lg(20, 180, 4, 80),
              left_leg=Lg(20, 180, 4, 80), right_arm=A(30, 40, 0, 10), left_arm=A(30, 40, 0, 10), neck=N(-30))]


@motion("relay_hand_back", "Receiving a relay baton: the right arm stretched straight back with the palm up, looking "
        "forward.", "pose", ["right_arm"], ["left_arm"])
def _relay():
    return [k(0.0, right_arm=A(50, 178, 0, 3), left_arm=A(45, 6, -15, 85))]


@motion("handstand", "Handstand: upside down on straight arms with the hands under the shoulders, body and legs "
        "straight up, toes pointed.", "pose", ["body"] + FULL, ["neck"])
def _handstand():
    return [k(0.0, body=B(pitch=180), right_arm=A(178, 8, 0, 2), left_arm=A(178, 8, 0, 2), right_leg=Lg(0, 0, 0, 0),
              left_leg=Lg(0, 0, 0, 0), spine=S(0), pelvis=P(), neck=N(-20))]


@motion("cartwheel", "Cartwheel to the left: arms overhead and legs wide, the body wheels sideways through hand, "
        "hand, foot, foot back to standing.", "action", ["body"] + FULL, ["neck"])
def _cartwheel():
    spread = {"right_arm": A(170, 85, 0, 3), "left_arm": A(170, 85, 0, 3), "right_leg": Lg(35, 90, 8, 3), "left_leg": Lg(35, 90, 8, 3)}
    return [k(0.0, body=B(roll=0), **stance_legs("normal", 0.1), right_arm=HANG, left_arm=HANG, spine=S(3)),
            k(0.3, **spread, body=B(roll=0)),
            k(0.55, body=B(roll=-90)), k(0.8, body=B(roll=-180)), k(1.05, body=B(roll=-270)), k(1.3, body=B(roll=-360)),
            k(1.7, body=B(roll=-360), **stance_legs("normal", 0.1), right_arm=HANG, left_arm=HANG)]


@motion("back_bridge", "Back bridge / wheel: face up with the hands and feet on the floor, hips pushed high and the "
        "back arched.", "pose", ["body"] + FULL, ["neck"])
def _bridge():
    return [k(0.0, **fit_pose("back_bridge", {"body.pitch": -100, "spine.lean": -50, "arms.raise": 170, "legs.raise": 40,
                                              "legs.knee": 90},
                               {"arms": {"dir": 8.0, "twist": 0.0, "elbow": 5.0}, "legs": {"dir": 0.0, "twist": 8.0},
                                "neck": {"nod": -30.0}},
                               [("right_hand", "floor", 0, 3), ("right_foot", "floor", 0, 3), ("pelvis", "y", 0.70, 1)]))]


@motion("front_split", "Front split: the right leg straight forward and the left leg straight back along the floor, "
        "hips square and down, trunk upright, arms out.", "pose", ["body"] + FULL, ["neck"])
def _front_split():
    return [k(0.0, **fit_pose("front_split", {"right_leg.raise": 85, "left_leg.raise": 85},
                               {"right_leg": {"dir": 0.0, "twist": 0.0, "knee": 0.0}, "left_leg": {"dir": 180.0, "twist": 0.0, "knee": 0.0},
                                "spine": {"lean": 0.0}, "arms": {"raise": 85.0, "dir": 85.0, "twist": 0.0, "elbow": 5.0}},
                               [("right_foot", "floor", 0, 3), ("left_foot", "floor", 0, 3), ("pelvis", "y", 0.11, 2)]))]


@motion("l_sit", "L-sit: hands on the floor beside the hips with straight arms, body lifted, legs held straight out "
        "in front off the floor.", "pose", ["body"] + FULL, ["neck"])
def _l_sit():
    return [k(0.0, **fit_pose("l_sit_v2", {"body.pitch": 0, "legs.raise": 90, "arms.raise": 10},
                               {"legs": {"dir": 0.0, "twist": 5.0, "knee": 2.0}, "arms": {"dir": 20.0, "twist": 0.0, "elbow": 3.0},
                                "spine": {"lean": 10.0}},
                               [("right_hand", "floor", 0, 3), ("right_foot", "y", 0.22, 3), ("pelvis", "y", 0.16, 2),
                                ("neck", "z", 0.02, 3), ("right_foot", "z", 0.70, 1)]))]


@motion("hollow_hold", "Hollow body hold: lying on the back with the lower back pressed down, shoulders and legs "
        "lifted slightly off the floor, arms long overhead.", "pose", ["body"] + FULL, ["neck"])
def _hollow():
    return [k(0.0, body=B(-90), spine=S(18), pelvis=P(), right_leg=Lg(22, 0, 0, 0), left_leg=Lg(22, 0, 0, 0),
              right_arm=A(160, 5, 0, 3), left_arm=A(160, 5, 0, 3), neck=N(20))]


@motion("arabesque", "Arabesque / single-leg balance: standing on the left leg, the straight right leg lifted behind, "
        "trunk tilted slightly forward, arms extended out.", "pose", FULL, ["neck"])
def _arabesque():
    return [k(0.0, left_leg=Lg(2, 0, 10, 3), right_leg=Lg(75, 180, 10, 3), spine=S(30), pelvis=P(12), right_arm=A(85, 70, 0, 5),
              left_arm=A(100, 20, 0, 5), neck=N(-15))]


@motion("horse_stance", "Horse stance: very wide deep squat with the trunk upright and both fists chambered at the "
        "hips (martial arts base).", "pose", FULL, ["neck"])
def _horse():
    return [k(0.0, **stance_legs("very_wide", 1.0, toe=20), spine=S(5), pelvis=P(), right_arm=arm_at(0.28, -0.42, -0.02, "back", "right"),
              left_arm=arm_at(0.28, -0.42, -0.02, "back", "left"))]


@motion("front_stance", "Long front stance: the left leg forward and bent, the right leg straight back, hips square, "
        "the left fist extended in a punch and the right fist chambered at the hip.", "pose", FULL, ["neck"])
def _front_stance():
    return [k(0.0, left_leg=leg_at(0.45, 0.16, 0.25, 0, 10, "left"), right_leg=Lg(35, 180, 15, 3), spine=S(5), pelvis=P(),
              left_arm=A(88, -4, 0, 3), right_arm=arm_at(0.28, -0.42, -0.02, "back", "right"))]


@motion("high_block", "Rising / high block: the left forearm held above the forehead, angled, the right fist at the "
        "hip.", "pose", ARMS, ["spine"])
def _high_block():
    return [k(0.0, left_arm=A(130, 10, -60, 100), right_arm=arm_at(0.28, -0.42, -0.02, "back", "right"))]


@motion("grappling_stance", "Grappling / wrestling stance: low staggered stance, back flat and angled forward, hands "
        "out in front at waist height, elbows in.", "pose", FULL, ["neck"])
def _wrestling():
    return [k(0.0, **stance_legs("wide", 0.8, "left", 15), spine=S(40), pelvis=P(12), **both(0.18, -0.40, 0.36, "down"), neck=N(-15))]


@motion("sprawl", "Sprawl: from a ready stance, shoot the legs back and drop the hips to the floor with the chest up "
        "on the hands, then pop back up to the stance.", "action", ["body"] + FULL, ["neck"])
def _sprawl():
    ready = {**stance_legs("wide", 0.8, "left", 15), "spine": S(40), "pelvis": P(12)}
    return [k(0.0, **ready, body=B(), **both(0.18, -0.40, 0.36, "down")),
            k(0.3, body=B(80), right_leg=Lg(5, 0, 15, 5), left_leg=Lg(5, 0, 15, 5), spine=S(-25), pelvis=P(-10),
              **support_arms(70)),
            k(0.8, hold=True),
            k(1.2, body=B(), **ready, **both(0.18, -0.40, 0.36, "down"))]


@motion("level_change_shot", "Level change and penetration step (double-leg shot): drop the hips, step deep with the "
        "left leg until the right knee nearly touches the floor, arms reaching forward to wrap.", "action",
        FULL, ["neck"])
def _shot():
    ready = {**stance_legs("wide", 0.8, "left", 15), "spine": S(40), "pelvis": P(12)}
    return [k(0.0, **ready, **both(0.18, -0.40, 0.36, "down")),
            k(0.35, left_leg=leg_at(0.45, 0.15, 0.42, 0, 10, "left"), right_leg=Lg(20, 180, 10, 100), spine=S(30),
              **both(0.12, -0.25, 0.55, "out")),
            k(0.7, hold=True), k(1.1, **ready, **both(0.18, -0.40, 0.36, "down"))]


@motion("downhill_tuck", "Downhill tuck (skiing, cycling descent): deep crouch with the trunk flat and low, hands "
        "together forward in front of the chin.", "pose", FULL, ["neck"])
def _tuck():
    return [k(0.0, **stance_legs("narrow", 1.0), spine=S(60), pelvis=P(15), **both(0.10, 0.0, 0.30, "down"), neck=N(-25))]


@motion("carving_turns", "Carving turns (skiing): knees bent, both legs angle together to one side then the other "
        "while the upper body stays quiet facing downhill, arms forward.", "cycle", LEGS + ["pelvis", "body"],
        ARMS + ["spine"], period=1.6)
def _carving():
    l = stance_legs("narrow", 0.55)
    return [k(0.0, **l, body=B(roll=-12), pelvis=P(5, 15), spine=S(20, -15), right_arm=A(35, 30, -15, 60), left_arm=A(35, 30, -15, 60)),
            k(0.8, body=B(roll=12), pelvis=P(5, -15), spine=S(20, 15))]


@motion("board_stance", "Sideways board stance (surf, snowboard, skate): feet wide along the board with the left "
        "foot forward, knees bent, arms out for balance, head turned forward.", "pose", FULL, ["neck"])
def _board():
    return [k(0.0, right_leg=leg_at(-0.30, 0.10, 0.25, 0, 60, "right"), left_leg=leg_at(0.30, 0.10, 0.25, 0, 30, "left"),
              spine=S(15, -50), pelvis=P(5, -45), right_arm=A(60, 80, 0, 20), left_arm=A(70, 40, 0, 15), neck=N(0, 40))]


@motion("pop_up", "Pop-up (surfing): lying face down with the hands under the chest, push up and jump the feet under "
        "the body into a sideways board stance.", "action", ["body"] + FULL, ["neck"])
def _pop_up():
    return [k(0.0, body=B(90), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(-10), pelvis=P(),
              right_arm=A(30, 60, 30, 110), left_arm=A(30, 60, 30, 110), neck=N(-20)),
            k(0.35, body=B(70), spine=S(-25), **support_arms(70)),
            k(0.6, body=B(25), right_leg=Lg(70, 0, 8, 120), left_leg=Lg(90, 0, 8, 120), spine=S(30)),
            k(0.95, body=B(0), **_board()[0][1])]


@motion("cycling", "Cycling (riding position): trunk leaning forward with the hands on the bars, legs pedaling in "
        "circles.", "cycle", ["body"] + FULL, ["neck"], period=0.8)
def _cycling():
    body = B(pitch=0, air=1.0, root=-0.12)
    arms = both(0.22, -0.30, 0.48, "out")
    top, front, bottom, back = Lg(75, 0, 4, 115), Lg(55, 0, 4, 55), Lg(25, 0, 4, 30), Lg(45, 0, 4, 100)
    return [k(0.0, body=body, spine=S(45), pelvis=P(10), **arms, right_leg=top, left_leg=bottom, neck=N(-20)),
            k(0.2, right_leg=front, left_leg=back), k(0.4, right_leg=bottom, left_leg=top), k(0.6, right_leg=back, left_leg=front)]


@motion("rowing_stroke", "Rowing stroke (seated): catch with knees bent and arms reaching forward, drive the legs, "
        "lean back and pull the hands to the ribs, then recover.", "cycle", ["body"] + FULL, ["neck"], period=2.0)
def _rowing():
    catch = {"right_leg": Lg(60, 0, 8, 125), "left_leg": Lg(60, 0, 8, 125), "spine": S(25), **both(0.12, -0.20, 0.55, "out")}
    finish = {"right_leg": Lg(88, 0, 8, 5), "left_leg": Lg(88, 0, 8, 5), "spine": S(-15), **both(0.18, -0.38, 0.12, "back")}
    return [k(0.0, body=B(-5), **catch), k(0.7, body=B(-5), **finish), k(0.9, hold=True), k(1.3, **{**finish, **both(0.12, -0.30, 0.50, "out"), "spine": S(10)})]


@motion("paddling", "Two-blade paddling (kayak): seated with legs forward, trunk rotating as the hands alternate "
        "pulling a paddle on the right and the left.", "cycle", ["body"] + FULL, ["neck"], period=1.4)
def _paddling():
    legs = {"right_leg": Lg(80, 0, 8, 30), "left_leg": Lg(80, 0, 8, 30)}
    r = {"right_arm": A(60, 20, 0, 20), "left_arm": A(95, 20, -30, 80)}
    l = {"left_arm": A(60, 20, 0, 20), "right_arm": A(95, 20, -30, 80)}
    return [k(0.0, body=B(-5), **legs, spine=S(10, -30), **r), k(0.7, spine=S(10, 30), **l)]


@motion("back_squat", "Barbell back squat: bar on the upper back with the hands gripping either side of the shoulders, "
        "elbows down, squat to depth and stand.", "action", LEGS + ARMS + ["pelvis", "spine"], ["neck"])
def _back_squat():
    bar = both(0.42, 0.02, -0.08, "down")
    return [k(0.0, **stance_legs("wide", 0.05), spine=S(5), pelvis=P(), **bar),
            k(1.0, **stance_legs("wide", 1.0), spine=S(40), pelvis=P(12)), k(1.25, hold=True),
            k(2.1, **stance_legs("wide", 0.05), spine=S(5), pelvis=P())]


@motion("front_rack", "Front rack position: the bar resting on the front of the shoulders, hands just outside the "
        "shoulders, elbows high and pointing forward.", "pose", ARMS, ["spine"])
def _front_rack():
    return [k(0.0, **both(0.20, 0.04, 0.16, "forward"))]


@motion("power_clean", "Power clean: from a deadlift start, extend hips and knees explosively up onto the toes, "
        "shrug, then drop under and catch the bar in the front rack in a quarter squat, stand.", "action",
        LEGS + ARMS + ["spine", "pelvis", "body"], ["neck"])
def _clean():
    return [k(0.0, **stance_legs("normal", 0.6), spine=S(55), pelvis=P(16), right_arm=A(55, -5, 0, 4), left_arm=A(55, -5, 0, 4), body=B()),
            k(0.5, **stance_legs("normal", 0.3), spine=S(25), right_arm=A(25, -5, 0, 4), left_arm=A(25, -5, 0, 4)),
            k(0.75, right_leg=Lg(0, 0, 8, 2), left_leg=Lg(0, 0, 8, 2), body=B(root=0.06), spine=S(-5), **both(0.25, -0.30, 0.10, "out")),
            k(0.95, **stance_legs("normal", 0.45), body=B(root=0.0), spine=S(10), **both(0.20, 0.04, 0.16, "forward")),
            k(1.6, **stance_legs("normal", 0.05), spine=S(3))]


@motion("overhead_squat_hold", "Overhead squat / snatch receiving position: deep squat with the trunk upright and "
        "both arms locked out overhead in a wide grip.", "pose", FULL, ["neck"])
def _ohs():
    return [k(0.0, **stance_legs("wide", 1.1), spine=S(25), pelvis=P(10), right_arm=A(160, 40, 0, 3), left_arm=A(160, 40, 0, 3))]


@motion("bench_press", "Bench press (lying on the back): lower the bar to the chest with the elbows bent at about 45 "
        "degrees, press back up to straight arms.", "cycle", ["body"] + FULL, ["neck"], period=2.0)
def _bench():
    up = {"right_arm": A(88, 10, 0, 3), "left_arm": A(88, 10, 0, 3)}
    down = {"right_arm": A(30, 70, 70, 100), "left_arm": A(30, 70, 70, 100)}
    return [k(0.0, body=B(-90), right_leg=Lg(45, 10, 8, 90), left_leg=Lg(45, 10, 8, 90), spine=S(0), pelvis=P(), **up),
            k(0.9, **down), k(1.1, hold=True)]


@motion("biceps_curl", "Biceps curl: elbows pinned at the sides, curl both hands up to the shoulders and lower.",
        "cycle", ARMS, ["spine"], period=1.8)
def _curl():
    return [k(0.0, right_arm=A(5, 0, 0, 8), left_arm=A(5, 0, 0, 8)), k(0.8, right_arm=A(12, 0, 0, 140), left_arm=A(12, 0, 0, 140)),
            k(1.0, hold=True)]


@motion("bent_over_row", "Bent-over row: hinged forward with a flat back, arms hanging, pull both elbows back past "
        "the ribs and lower.", "cycle", FULL, ["neck"], period=1.8)
def _row():
    return [k(0.0, **stance_legs("normal", 0.3), spine=S(50), pelvis=P(15), right_arm=A(52, -5, 0, 5), left_arm=A(52, -5, 0, 5), neck=N(-10)),
            k(0.8, right_arm=A(25, 160, 30, 100), left_arm=A(25, 160, 30, 100)), k(1.0, hold=True)]


@motion("kettlebell_swing", "Kettlebell swing: hinge so the bell swings back between the legs, then snap the hips "
        "forward so the straight arms float the bell to chest height.", "cycle", FULL, ["neck"], period=1.4)
def _kb_swing():
    return grip_keys([(0.0, 0.0, -0.42, 0.44, "down"), (0.5, 0.0, -0.10, 0.55, "out"), (0.7, 0.0, -0.08, 0.56, "out"),
                      (1.4, 0.0, -0.42, 0.44, "down")], step=0.08) + \
        [k(0.0, **stance_legs("wide", 0.45), spine=S(65), pelvis=P(18)), k(0.5, **stance_legs("wide", 0.05), spine=S(3), pelvis=P()),
         k(0.7, hold=True), k(1.4, **stance_legs("wide", 0.45), spine=S(65), pelvis=P(18))]


@motion("climbing", "Climbing (wall, rope, ladder): hands reach up alternately overhead while the opposite knee "
        "steps up, body close to the wall.", "cycle", ["body"] + FULL, ["neck"], period=1.4)
def _climbing():
    body = B(air=1.0, root=0.0)
    a = {"right_arm": A(170, 15, 0, 15), "left_arm": A(120, 15, 0, 80), "left_leg": Lg(70, 15, 15, 100), "right_leg": Lg(10, 15, 15, 20)}
    b = {"left_arm": A(170, 15, 0, 15), "right_arm": A(120, 15, 0, 80), "right_leg": Lg(70, 15, 15, 100), "left_leg": Lg(10, 15, 15, 20)}
    return [k(0.0, body=body, spine=S(5), neck=N(-20), **a), k(0.7, **b)]


@motion("archery_draw", "Archery draw: standing side-on, the left arm straight out holding the bow, the right hand "
        "pulled back to the chin with the elbow high, eyes along the arm.", "pose", FULL, ["neck"])
def _archery():
    return [k(0.0, **stance_legs("normal", 0.05), spine=S(3), left_arm=A(90, 88, 0, 3), right_arm=arm_at(-0.05, 0.20, 0.12, "out", "right"),
              neck=N(0, -80))]


@motion("en_garde", "En garde (fencing ready): side-on, the right foot pointing forward and the left foot back across, "
        "knees bent, the right arm forward with the hand at chest height, the left arm raised and curved behind.",
        "pose", FULL, ["neck"])
def _en_garde():
    return [k(0.0, right_leg=leg_at(0.30, 0.10, 0.30, 0, 0, "right"), left_leg=leg_at(-0.25, 0.10, 0.30, 0, 80, "left"),
              spine=S(5, 40), pelvis=P(0, 50), right_arm=A(60, 0, 0, 40), left_arm=A(110, 120, 60, 90), neck=N(0, -40))]


@motion("fencing_lunge", "Fencing lunge: from en garde, the front (right) leg kicks forward into a long lunge with "
        "the knee over the ankle, the back leg straightens, the sword arm extends and the rear arm drops back.",
        "action", FULL, ["neck"])
def _fencing_lunge():
    g = {"right_leg": leg_at(0.30, 0.10, 0.30, 0, 0, "right"), "left_leg": leg_at(-0.25, 0.10, 0.30, 0, 80, "left"),
         "spine": S(5, 40), "pelvis": P(0, 50), "right_arm": A(60, 0, 0, 40), "left_arm": A(110, 120, 60, 90)}
    return [k(0.0, **g), k(0.25, right_arm=A(85, 0, 0, 3)),
            k(0.5, right_leg=leg_at(0.75, 0.10, 0.42, 0, 0, "right"), left_leg=Lg(40, 180, 70, 3), left_arm=A(60, 170, 0, 5), spine=S(10, 40)),
            k(0.8, hold=True), k(1.3, **g)]


_POS_ALIASES2 = {
    "hockey stance": "stick_ready(hold=1.5)", "field hockey stance": "stick_ready(hold=1.5)", "stickhandling": "stance(width=wide, depth=0.6) + stickhandling(times=3)",
    "puck handling": "stance(width=wide, depth=0.6) + stickhandling(times=3)", "wrist shot": "stance(width=wide, depth=0.5) + wrist_shot",
    "sweep shot": "stance(width=wide, depth=0.5) + wrist_shot", "butterfly save": "goalkeeper_set\nbutterfly_block(hold=1.5)",
    "goalie butterfly": "goalkeeper_set\nbutterfly_block(hold=1.5)", "skating": "skating_stride(times=3)", "ice skating": "skating_stride(times=3)",
    "speed skating": "skating_stride(times=3)", "cradle": "run(pace=jog) + stick_cradle", "lacrosse cradle": "run(pace=jog) + stick_cradle",
    "on your marks": "blocks_on_your_marks(hold=1.5)", "sprint blocks": "blocks_on_your_marks(hold=1)\nblocks_set(hold=0.8)\nsprint_start",
    "block start": "blocks_on_your_marks(hold=1)\nblocks_set(hold=0.8)\nsprint_start", "long jump": "long_jump", "high jump": "back_arch_flight(hold=1)",
    "relay baton exchange": "run + relay_hand_back", "handstand": "handstand(hold=2)", "cartwheel": "cartwheel", "bridge": "back_bridge(hold=2)",
    "back bridge": "back_bridge(hold=2)", "splits": "front_split(hold=2)", "front split": "front_split(hold=2)", "l sit": "l_sit(hold=2)",
    "hollow hold": "hollow_hold(hold=2)", "hollow body": "hollow_hold(hold=2)", "arabesque": "arabesque(hold=2)",
    "horse stance": "horse_stance(hold=2)", "front stance": "front_stance(hold=2)", "high block": "stance(width=wide, depth=0.5, stagger=left) + high_block(hold=1.5)",
    "rising block": "stance(width=wide, depth=0.5, stagger=left) + high_block(hold=1.5)", "wrestling stance": "grappling_stance(hold=1.5)", "sprawl": "sprawl",
    "double leg takedown": "level_change_shot", "double leg shot": "level_change_shot", "ski tuck": "downhill_tuck(hold=2)",
    "tuck position": "downhill_tuck(hold=2)", "skiing": "carving_turns(times=3)", "ski turns": "carving_turns(times=3)",
    "snowboard stance": "board_stance(hold=2)", "surf stance": "board_stance(hold=2)", "surfing": "pop_up\nboard_stance(hold=1.5)",
    "pop up": "pop_up\nboard_stance(hold=1)", "cycling": "cycling(times=4)", "biking": "cycling(times=4)", "riding a bike": "cycling(times=4)",
    "rowing": "rowing_stroke(times=3)", "row": "rowing_stroke(times=3)", "kayaking": "paddling(times=3)", "paddling": "paddling(times=3)",
    "back squat": "back_squat", "barbell squat": "back_squat", "front rack": "stand + front_rack(hold=1.5)", "clean": "power_clean",
    "power clean": "power_clean", "overhead squat": "overhead_squat_hold(hold=2)", "snatch": "power_clean\noverhead_squat_hold(hold=1)",
    "bench press": "bench_press(times=2)", "bicep curls": "stand + biceps_curl(times=3)", "biceps curl": "stand + biceps_curl(times=3)",
    "bent over row": "bent_over_row(times=3)", "kettlebell swing": "kettlebell_swing(times=3)", "kettlebell swings": "kettlebell_swing(times=3)",
    "rock climbing": "climbing(times=3)", "climbing": "climbing(times=3)", "rope climb": "climbing(times=3)",
    "archery": "archery_draw(hold=2)", "draw a bow": "archery_draw(hold=2)", "en garde": "en_garde(hold=1.5)",
    "fencing lunge": "en_garde\nfencing_lunge", "fencing": "en_garde\nfencing_lunge",
}


# =============================================================================
# 25. FITNESS / YOGA / STRETCHING POSITIONS
# =============================================================================
PRAYER = {"right_arm": arm_at(0.02, -0.20, 0.22, "down", "right"), "left_arm": arm_at(0.02, -0.20, 0.22, "down", "left")}
SUPINE = {"body": B(-90)}   # body orientation only (spine / pelvis keep their defaults unless given)


@motion("mountain_pose", "Mountain pose / tall standing: feet together, legs straight, spine tall, hands pressed "
        "together at the chest (prayer).", "pose", FULL, ["neck"])
def _mountain():
    return [k(0.0, right_leg=Lg(1, 0, 4, 2), left_leg=Lg(1, 0, 4, 2), spine=S(0), pelvis=P(), **PRAYER)]


@motion("chair_pose", "Chair pose: knees bent as if sitting back into a chair, weight in the heels, chest lifted, "
        "both arms reaching up overhead.", "pose", FULL, ["neck"])
def _chair():
    return [k(0.0, **stance_legs("narrow", 0.8), spine=S(18), pelvis=P(8), right_arm=A(165, 10, 0, 5), left_arm=A(165, 10, 0, 5))]


@motion("warrior_one", "Warrior I / crescent lunge: the left foot forward with the knee bent, the right leg long "
        "behind, hips square, both arms reaching straight up.", "pose", FULL, ["neck"])
def _warrior1():
    return [k(0.0, left_leg=leg_at(0.45, 0.16, 0.25, 0, 10, "left"), right_leg=Lg(35, 180, 20, 3), spine=S(-5), pelvis=P(-5),
              right_arm=A(170, 10, 0, 3), left_arm=A(170, 10, 0, 3), neck=N(-15))]


@motion("reverse_warrior", "Reverse warrior: wide stance with the right knee bent, trunk leaning back over the "
        "straight left leg, the right arm arcing up overhead and the left hand sliding down the left leg.",
        "pose", FULL, ["neck"])
def _rev_warrior():
    return [k(0.0, right_leg=leg_at(0.0, 0.48, 0.25, 0, 70, "right"), left_leg=leg_at(0.0, 0.42, 0.0, 0, 10, "left"),
              spine=S(0, 0, -25), right_arm=A(165, 60, 0, 5), left_arm=A(25, 85, 0, 5), neck=N(-20, 0, -10))]


@motion("triangle_pose", "Triangle pose: wide straight-legged stance, the trunk tipped sideways over the right leg, "
        "the right hand down toward the right shin and the left arm straight up to the sky.", "pose", FULL, ["neck"])
def _triangle():
    return [k(0.0, right_leg=leg_at(0.0, 0.50, 0.03, 0, 70, "right"), left_leg=leg_at(0.0, 0.40, 0.03, 0, 10, "left"),
              spine=S(5, 0, 55), pelvis=P(0, 0, 15), right_arm=A(10, 85, 0, 3), left_arm=A(170, 85, 0, 3), neck=N(0, -30))]


@motion("garland_squat", "Garland / deep yogi squat: heels down, knees wide, hips low between the heels, elbows "
        "pressing the knees apart with the hands together at the chest.", "pose", FULL, ["neck"])
def _garland():
    return [k(0.0, **stance_legs("wide", 1.3, toe=35), spine=S(30), pelvis=P(12), **PRAYER)]


@motion("standing_side_stretch", "Standing side stretch: feet together, the right arm reaching up and over the head "
        "to the left as the trunk bends sideways, the left hand on the hip.", "pose", ARMS + ["spine"], ["neck"])
def _side_stretch():
    return [k(0.0, spine=S(0, 0, -25), right_arm=A(160, 60, 0, 10), left_arm=arm_at(0.26, -0.47, 0.02, "out", "left"))]


@motion("triceps_stretch", "Overhead triceps stretch: the right arm up with the elbow bent and the hand dropped "
        "behind the head, the left hand pulling the right elbow.", "pose", ARMS, ["neck"])
def _tri_stretch():
    return [k(0.0, right_arm=A(165, 15, 0, 140), left_arm=A(150, -20, 0, 100))]


@motion("chest_opener", "Chest opener: hands clasped behind the back, arms straight, shoulders pulled back and chest "
        "lifted.", "pose", ARMS + ["spine"], ["neck"])
def _chest_opener():
    return [k(0.0, spine=S(-8), right_arm=A(35, 175, 0, 5), left_arm=A(35, 175, 0, 5), neck=N(-10))]


@motion("neck_stretch", "Neck side stretch: tilt the head toward the right shoulder, the right hand resting on the "
        "head, the left arm long by the side.", "pose", ["neck", "right_arm"], ["left_arm"])
def _neck_stretch():
    return [k(0.0, neck=N(0, 0, 30), right_arm=A(145, 60, 90, 120), left_arm=A(8, 70, 0, 5))]


@motion("calf_stretch", "Standing calf stretch: the right leg back straight with the heel pressed down, the left "
        "knee bent in front, hands on the left thigh.", "pose", FULL, ["neck"])
def _calf_stretch():
    return [k(0.0, left_leg=leg_at(0.30, 0.15, 0.16, 0, 10, "left"), right_leg=Lg(28, 180, 10, 3), spine=S(25),
              **both(0.18, -0.55, 0.30, "out"))]


@motion("wall_sit", "Wall sit hold: back upright, thighs parallel to the floor and shins vertical (as if sitting "
        "against a wall), arms crossed or hanging.", "pose", FULL, ["neck"])
def _wall_sit():
    return [k(0.0, right_leg=Lg(88, 0, 8, 88), left_leg=Lg(88, 0, 8, 88), spine=S(0), pelvis=P(), right_arm=A(10, 30, 0, 5),
              left_arm=A(10, 30, 0, 5))]


@motion("goblet_squat", "Goblet squat: holding a weight with both hands at the chest, elbows down, squat deep between "
        "the knees and stand.", "action", FULL, ["neck"])
def _goblet():
    hold = grip2(0.0, -0.22, 0.26, "down")
    return [k(0.0, **stance_legs("wide", 0.05, toe=25), spine=S(4), pelvis=P(), **hold),
            k(1.0, **stance_legs("wide", 1.1, toe=25), spine=S(25), pelvis=P(10)), k(1.25, hold=True),
            k(2.1, **stance_legs("wide", 0.05, toe=25), spine=S(4), pelvis=P())]


@motion("sumo_squat", "Sumo squat: very wide stance with the toes turned out, sink straight down with the trunk "
        "upright, hands together at the chest, stand.", "action", FULL, ["neck"])
def _sumo():
    return [k(0.0, **stance_legs("very_wide", 0.05, toe=40), spine=S(3), **PRAYER),
            k(1.0, **stance_legs("very_wide", 0.95, toe=40), spine=S(12)), k(1.25, hold=True),
            k(2.1, **stance_legs("very_wide", 0.05, toe=40), spine=S(3))]


@motion("thruster", "Thruster: front squat with the hands at the shoulders, then drive up and press both arms "
        "straight overhead in one motion.", "action", FULL, ["neck"])
def _thruster():
    rack = both(0.20, 0.04, 0.16, "forward")
    return [k(0.0, **stance_legs("normal", 0.05), spine=S(4), **rack),
            k(0.9, **stance_legs("normal", 1.0), spine=S(25), pelvis=P(10)),
            k(1.4, **stance_legs("normal", 0.05), spine=S(0), pelvis=P(), right_arm=A(170, 15, 0, 5), left_arm=A(170, 15, 0, 5)),
            k(1.7, hold=True), k(2.2, **rack, spine=S(4))]


@motion("reverse_lunge", "Reverse lunge: step the right foot back and lower until both knees are near 90 degrees, "
        "then drive back up to standing.", "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _reverse_lunge():
    stand = stance_legs("normal", 0.05)
    low = {"left_leg": leg_at(0.10, 0.14, 0.36, 0, 6, "left"), "right_leg": Lg(30, 180, 4, 100)}
    return [k(0.0, **stand, right_arm=HANG, left_arm=HANG),
            k(0.45, left_leg=leg_at(0.05, 0.14, 0.06, 0, 6, "left"), right_leg=Lg(25, 180, 4, 25)),
            k(1.1, **low, right_arm=A(10, 60, 30, 20), left_arm=A(10, 60, 30, 20)), k(1.35, hold=True),
            k(1.9, left_leg=leg_at(0.05, 0.14, 0.06, 0, 6, "left"), right_leg=Lg(25, 180, 4, 25)), k(2.3, **stand, right_arm=HANG, left_arm=HANG)]


@motion("curtsy_lunge", "Curtsy lunge: step the right foot back and across behind the left, bend both knees, then "
        "return.", "action", LEGS + ["pelvis"], ARMS + ["spine"])
def _curtsy():
    stand = stance_legs("normal", 0.05)
    return [k(0.0, **stand, **PRAYER),
            k(1.0, left_leg=leg_at(0.10, 0.14, 0.32, 0, 10, "left"), right_leg=Lg(30, -160, 0, 95), pelvis=P(5, -15)),
            k(1.3, hold=True), k(2.1, **stand, pelvis=P())]


@motion("good_morning", "Good morning: hands behind the head, knees soft, hinge forward at the hips with a flat back "
        "until the trunk is near horizontal, then stand.", "action", FULL, ["neck"])
def _good_morning():
    hands = {"right_arm": A(130, 80, 90, 120), "left_arm": A(130, 80, 90, 120)}
    return [k(0.0, **stance_legs("normal", 0.1), spine=S(3), pelvis=P(), **hands),
            k(1.0, **stance_legs("normal", 0.25), spine=S(70), pelvis=P(20)), k(1.25, hold=True),
            k(2.1, **stance_legs("normal", 0.1), spine=S(3), pelvis=P())]


@motion("lateral_raise", "Lateral raise: arms straight out to the sides up to shoulder height and back down.",
        "cycle", ARMS, ["spine"], period=1.8)
def _lat_raise():
    return [k(0.0, right_arm=A(10, 85, 0, 10), left_arm=A(10, 85, 0, 10)), k(0.8, right_arm=A(88, 85, 0, 10), left_arm=A(88, 85, 0, 10)),
            k(1.0, hold=True)]


@motion("front_raise", "Front raise: straight arms raised forward to shoulder height and lowered.", "cycle", ARMS,
        ["spine"], period=1.8)
def _front_raise():
    return [k(0.0, right_arm=A(10, 5, 0, 5), left_arm=A(10, 5, 0, 5)), k(0.8, right_arm=A(88, 5, 0, 5), left_arm=A(88, 5, 0, 5)),
            k(1.0, hold=True)]


@motion("overhead_triceps_extension", "Overhead triceps extension: both hands holding a weight behind the head with "
        "the elbows pointing up, straighten the arms overhead and lower.", "cycle", ARMS, ["spine"], period=1.8)
def _oh_tri():
    return [k(0.0, right_arm=A(160, 20, 0, 140), left_arm=A(160, 20, 0, 140)), k(0.8, right_arm=A(170, 15, 0, 5), left_arm=A(170, 15, 0, 5)),
            k(1.0, hold=True)]


@motion("pull_up", "Pull-up / chin-up: hanging from a bar with straight arms overhead, pull the chin up over the bar "
        "with the elbows driving down, lower.", "cycle", ["body"] + FULL, ["neck"], period=2.0)
def _pull_up():
    hang = {"right_arm": A(170, 25, 0, 5), "left_arm": A(170, 25, 0, 5)}
    top = {"right_arm": A(120, 40, 60, 140), "left_arm": A(120, 40, 60, 140)}
    return [k(0.0, body=B(air=1.0, root=0.25), right_leg=Lg(15, 0, 4, 40), left_leg=Lg(15, 0, 4, 40), spine=S(-3), **hang, neck=N(-15)),
            k(0.9, body=B(air=1.0, root=0.55), **top), k(1.1, hold=True)]


@motion("plank_jacks", "Plank jacks: in a plank on straight arms, hop the feet wide apart and back together.",
        "cycle", ["body"] + FULL, ["neck"], period=0.8)
def _plank_jacks():
    arms = support_arms(PLANK_PITCH)
    return [k(0.0, body=B(PLANK_PITCH), spine=S(0), pelvis=P(), **arms, right_leg=Lg(2, 90, 0, 0), left_leg=Lg(2, 90, 0, 0), neck=N(-25)),
            k(0.4, right_leg=Lg(18, 90, 0, 0), left_leg=Lg(18, 90, 0, 0))]


@motion("shoulder_taps", "Plank shoulder taps: in a straight-arm plank, lift one hand to tap the opposite shoulder, "
        "alternating, hips steady.", "cycle", ["body"] + FULL, ["neck"], period=1.2)
def _shoulder_taps():
    arms = support_arms(PLANK_PITCH, spread=0.32)
    tap_r = {"right_arm": arm_at(-0.18, 0.0, 0.12, "down", "right")}
    tap_l = {"left_arm": arm_at(-0.18, 0.0, 0.12, "down", "left")}
    legs = {"right_leg": Lg(8, 90, 0, 0), "left_leg": Lg(8, 90, 0, 0)}
    return [k(0.0, body=B(PLANK_PITCH), spine=S(0), pelvis=P(), **arms, **legs, neck=N(-25)),
            k(0.3, **tap_r), k(0.6, right_arm=arms["right_arm"]), k(0.9, **tap_l)]


@motion("bicycle_crunch", "Bicycle crunch: lying on the back with hands behind the head, shoulders lifted, bring the "
        "right elbow toward the left knee while the right leg extends, then switch.", "cycle", ["body"] + FULL, ["neck"],
        period=1.2)
def _bicycle():
    hands = {"right_arm": A(130, 80, 90, 125), "left_arm": A(130, 80, 90, 125)}
    return [k(0.0, **SUPINE, spine=S(25, -30), **hands, left_leg=Lg(85, 0, 0, 100), right_leg=Lg(25, 0, 0, 5), neck=N(20)),
            k(0.6, spine=S(25, 30), right_leg=Lg(85, 0, 0, 100), left_leg=Lg(25, 0, 0, 5))]


@motion("leg_raises", "Lying leg raises: on the back with the arms by the sides, raise both straight legs to "
        "vertical and lower them slowly toward the floor.", "cycle", ["body"] + FULL, ["neck"], period=2.4)
def _leg_raises():
    arms = {"right_arm": A(10, 30, 0, 5), "left_arm": A(10, 30, 0, 5)}
    return [k(0.0, **SUPINE, **arms, right_leg=Lg(10, 0, 0, 2), left_leg=Lg(10, 0, 0, 2)),
            k(1.0, right_leg=Lg(88, 0, 0, 2), left_leg=Lg(88, 0, 0, 2)), k(1.2, hold=True)]


@motion("flutter_kicks_back", "Flutter kicks on the back: lying face up with the lower back down, straight legs "
        "hovering and kicking up and down in small fast alternating beats.", "cycle", ["body"] + FULL, ["neck"],
        period=0.5)
def _flutter_back():
    arms = {"right_arm": A(10, 30, 0, 5), "left_arm": A(10, 30, 0, 5)}
    return [k(0.0, **SUPINE, **arms, right_leg=Lg(30, 0, 0, 2), left_leg=Lg(12, 0, 0, 2), neck=N(15)),
            k(0.25, right_leg=Lg(12, 0, 0, 2), left_leg=Lg(30, 0, 0, 2))]


@motion("v_up", "V-up: from lying flat with the arms overhead, lift the straight legs and the trunk together so the "
        "hands reach toward the toes in a V, then lower.", "action", ["body"] + FULL, ["neck"])
def _v_up():
    flat = {**SUPINE, "right_leg": Lg(0, 0, 0, 2), "left_leg": Lg(0, 0, 0, 2), "right_arm": A(170, 8, 0, 3), "left_arm": A(170, 8, 0, 3)}
    return [k(0.0, **flat), k(0.6, body=B(-45), spine=S(30), right_leg=Lg(110, 0, 0, 2), left_leg=Lg(110, 0, 0, 2),
                                right_arm=A(75, 5, 0, 3), left_arm=A(75, 5, 0, 3)),
            k(0.8, hold=True), k(1.5, **flat)]


@motion("boat_pose", "Boat pose / V-sit hold: balancing on the sit bones, trunk leaning back, straight legs lifted, "
        "arms reaching forward parallel to the floor.", "pose", ["body"] + FULL, ["neck"])
def _boat():
    return [k(0.0, body=B(-40), spine=S(5), right_leg=Lg(100, 0, 0, 5), left_leg=Lg(100, 0, 0, 5),
              right_arm=A(70, 5, 0, 3), left_arm=A(70, 5, 0, 3))]


@motion("donkey_kicks", "Donkey kicks: on hands and knees, kick the right foot up toward the ceiling with the knee "
        "bent at 90 degrees, lower, repeat.", "cycle", ["body"] + FULL, ["neck"], period=1.4)
def _donkey():
    t = _table()
    return [k(0.0, **t, neck=N(-10)), k(0.6, right_leg=full("right_leg", **{**t["right_leg"], "raise": 10.0, "dir": 180.0, "knee": 90.0})),
            k(0.8, hold=True)]


@motion("fire_hydrants", "Fire hydrants: on hands and knees, lift the bent right knee out to the side to hip height "
        "and lower.", "cycle", ["body"] + FULL, ["neck"], period=1.4)
def _hydrant():
    t = _table()
    return [k(0.0, **t, neck=N(-10)), k(0.6, right_leg=full("right_leg", **{**t["right_leg"], "dir": 70.0})), k(0.8, hold=True)]


@motion("side_lying_leg_raise", "Side-lying leg raise: lying on the left side with the head on the left arm, lift "
        "the straight top (right) leg up and lower it.", "cycle", ["body"] + FULL, ["neck"], period=1.6)
def _side_leg():
    return [k(0.0, body=B(0, 0, -85), spine=S(0), pelvis=P(), left_leg=Lg(0, 0, 0, 2), right_leg=Lg(2, 90, 0, 2),
              left_arm=A(170, 85, 0, 20), right_arm=A(20, 0, 0, 30)),
            k(0.7, right_leg=Lg(45, 90, 0, 2)), k(0.9, hold=True)]


@motion("crab_walk", "Crab walk: face up on the hands and feet with the hips lifted, stepping the opposite hand and "
        "foot forward together.", "cycle", ["body"] + FULL, ["neck"], period=1.0)
def _crab():
    base = fit_pose("crab", {"body.pitch": -90, "legs.raise": 85, "legs.knee": 95, "arms.raise": 35},
                    {"legs": {"dir": 0.0, "twist": 10.0}, "arms": {"dir": 175.0, "twist": 0.0, "elbow": 3.0}, "spine": {"lean": 0.0}},
                    [("right_foot", "floor", 0, 3), ("right_hand", "floor", 0, 3), ("pelvis", "y", 0.45, 1)])
    a, b = dict(base), dict(base)
    a["right_arm"] = full("right_arm", **{**base["right_arm"], "raise": base["right_arm"]["raise"] + 15})
    a["left_leg"] = full("left_leg", **{**base["left_leg"], "raise": base["left_leg"]["raise"] + 12})
    b["left_arm"] = full("left_arm", **{**base["left_arm"], "raise": base["left_arm"]["raise"] + 15})
    b["right_leg"] = full("right_leg", **{**base["right_leg"], "raise": base["right_leg"]["raise"] + 12})
    return [k(0.0, **a, neck=N(20)), k(0.5, **b)]


@motion("pigeon_pose", "Pigeon pose: the right shin folded across in front on the floor, the left leg straight back "
        "along the floor, hips square and low, trunk upright on the hands.", "pose", ["body"] + FULL, ["neck"])
def _pigeon():
    return [k(0.0, **fit_pose("pigeon", {"right_leg.raise": 70, "right_leg.knee": 120, "left_leg.raise": 70, "spine.lean": 10},
                               {"right_leg": {"dir": -15.0, "twist": 70.0}, "left_leg": {"dir": 180.0, "twist": 0.0, "knee": 3.0},
                                "arms": {"raise": 15.0, "dir": 20.0, "twist": 0.0, "elbow": 3.0}},
                               [("right_knee", "floor", 0, 3), ("left_foot", "floor", 0, 3), ("pelvis", "y", 0.16, 2),
                                ("right_hand", "floor", 0, 1)]))]


@motion("happy_baby", "Happy baby: lying on the back, knees pulled wide toward the armpits, hands holding the feet "
        "with the soles facing up.", "pose", ["body"] + FULL, ["neck"])
def _happy_baby():
    return [k(0.0, **SUPINE, right_leg=Lg(115, 45, 30, 95), left_leg=Lg(115, 45, 30, 95), right_arm=A(110, 30, 0, 20),
              left_arm=A(110, 30, 0, 20))]


@motion("knee_to_chest", "Lying knee-to-chest stretch: on the back, both knees hugged into the chest.", "pose",
        ["body"] + FULL, ["neck"])
def _knee_chest():
    return [k(0.0, **SUPINE, right_leg=Lg(125, 0, 0, 130), left_leg=Lg(125, 0, 0, 130), right_arm=A(75, 10, 0, 70),
              left_arm=A(75, 10, 0, 70), neck=N(15))]


@motion("figure_four_stretch", "Figure-four stretch: lying on the back, the right ankle crossed over the left knee, "
        "pulling the left thigh toward the chest.", "pose", ["body"] + FULL, ["neck"])
def _figure_four():
    return [k(0.0, **SUPINE, left_leg=Lg(100, 0, 0, 90), right_leg=Lg(90, 50, 60, 110), right_arm=A(75, 10, 0, 60),
              left_arm=A(75, 10, 0, 60))]


@motion("supine_twist", "Lying spinal twist: on the back with the arms out wide, both bent knees dropped over to "
        "the right side, head turned left.", "pose", ["body"] + FULL, ["neck"])
def _supine_twist():
    return [k(0.0, **SUPINE, pelvis=P(0, 25, 0), right_leg=Lg(80, 75, 0, 95), left_leg=Lg(80, -60, 0, 95), right_arm=A(88, 88, 0, 3),
              left_arm=A(88, 88, 0, 3), neck=N(0, -45))]


@motion("seated_twist", "Seated spinal twist: sitting tall with the legs out, the trunk rotated to the right with "
        "the right hand behind on the floor and the left elbow across the right knee.", "pose", ["body"] + FULL, ["neck"])
def _seated_twist():
    s = _seated()
    return [k(0.0, **{**s, "spine": S(5, 55), "right_arm": A(25, 170, 0, 5), "left_arm": A(60, -40, 0, 60)}, neck=N(0, 30))]


@motion("camel_pose", "Camel pose: kneeling upright, the hips pushed forward and the back arched as the hands reach "
        "back to the heels, chest lifted to the sky.", "pose", FULL, ["neck"])
def _camel():
    return [k(0.0, right_leg=Lg(-10, 0, 0, 100), left_leg=Lg(-10, 0, 0, 100), spine=S(-55), pelvis=P(-15),
              right_arm=A(45, 175, 0, 3), left_arm=A(45, 175, 0, 3), neck=N(-35))]


@motion("low_plank", "Low plank (chaturanga): body in a straight line hovering just above the floor on bent arms, "
        "elbows hugging the ribs.", "pose", ["body"] + FULL, ["neck"])
def _low_plank():
    return [k(0.0, body=B(PUSHUP_LOW_PITCH), spine=S(0), pelvis=P(), **support_arms(PUSHUP_LOW_PITCH),
              right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), neck=N(-30))]


@motion("prayer_hands", "Hands pressed together in front of the chest (greeting, centering, yoga).", "pose", ARMS, [])
def _prayer():
    return [k(0.0, **PRAYER)]


@motion("dead_hang", "Dead hang from a bar: arms straight overhead, body long and relaxed, feet off the ground.",
        "pose", ["body"] + FULL, ["neck"])
def _dead_hang():
    return [k(0.0, body=B(air=1.0, root=0.25), right_leg=Lg(5, 0, 4, 10), left_leg=Lg(5, 0, 4, 10), spine=S(0),
              right_arm=A(172, 20, 0, 3), left_arm=A(172, 20, 0, 3))]


_POS_ALIASES3 = {
    "mountain pose": "mountain_pose(hold=2)", "chair pose": "chair_pose(hold=2)", "warrior one": "warrior_one(hold=2)",
    "warrior 1": "warrior_one(hold=2)", "crescent lunge": "warrior_one(hold=2)", "warrior two": "warrior_pose(hold=2)",
    "warrior 2": "warrior_pose(hold=2)", "reverse warrior": "reverse_warrior(hold=2)", "triangle pose": "triangle_pose(hold=2)",
    "garland pose": "garland_squat(hold=2)", "yogi squat": "garland_squat(hold=2)", "malasana": "garland_squat(hold=2)",
    "side stretch": "stand + standing_side_stretch(hold=2)", "triceps stretch": "stand + triceps_stretch(hold=2)",
    "chest stretch": "stand + chest_opener(hold=2)", "neck stretch": "stand + neck_stretch(hold=2)", "calf stretch": "calf_stretch(hold=2)",
    "wall sit": "wall_sit(hold=3)", "goblet squat": "goblet_squat", "sumo squat": "sumo_squat", "thruster": "thruster",
    "thrusters": "thruster\nthruster", "reverse lunge": "reverse_lunge", "reverse lunges": "reverse_lunge\nreverse_lunge(side=left)",
    "curtsy lunge": "curtsy_lunge\ncurtsy_lunge(side=left)", "good morning": "good_morning", "good mornings": "good_morning\ngood_morning",
    "lateral raise": "stand + lateral_raise(times=3)", "lateral raises": "stand + lateral_raise(times=3)",
    "front raise": "stand + front_raise(times=3)", "front raises": "stand + front_raise(times=3)",
    "triceps extension": "stand + overhead_triceps_extension(times=3)", "overhead triceps extension": "stand + overhead_triceps_extension(times=3)",
    "pull up": "pull_up(times=2)", "pull ups": "pull_up(times=3)", "chin up": "pull_up(times=2)", "chin ups": "pull_up(times=3)",
    "plank jacks": "plank_jacks(times=4)", "shoulder taps": "shoulder_taps(times=3)", "plank shoulder taps": "shoulder_taps(times=3)",
    "bicycle crunches": "bicycle_crunch(times=4)", "bicycle crunch": "bicycle_crunch(times=4)", "leg raises": "leg_raises(times=3)",
    "flutter kicks": "flutter_kicks_back(times=6)", "v up": "v_up", "v ups": "v_up\nv_up", "boat pose": "boat_pose(hold=2)",
    "v sit": "boat_pose(hold=2)", "donkey kicks": "donkey_kicks(times=3)", "fire hydrants": "fire_hydrants(times=3)",
    "side leg raises": "side_lying_leg_raise(times=3)", "crab walk": "crab_walk(times=3)", "pigeon pose": "pigeon_pose(hold=2)",
    "pigeon stretch": "pigeon_pose(hold=2)", "happy baby": "happy_baby(hold=2)", "knee to chest": "knee_to_chest(hold=2)",
    "knees to chest": "knee_to_chest(hold=2)", "figure four stretch": "figure_four_stretch(hold=2)", "figure 4 stretch": "figure_four_stretch(hold=2)",
    "spinal twist": "supine_twist(hold=2)", "lying twist": "supine_twist(hold=2)", "seated twist": "seated_twist(hold=2)",
    "camel pose": "camel_pose(hold=2)", "chaturanga": "plank\nlow_plank(hold=1.5)", "low plank": "low_plank(hold=2)",
    "prayer hands": "stand + prayer_hands(hold=2)", "dead hang": "dead_hang(hold=2)", "hang from a bar": "dead_hang(hold=2)",
    "corpse pose": "lie_on_back(hold=3)", "savasana": "lie_on_back(hold=3)", "forward fold": "hamstring_stretch(hold=2)",
    "toe touch": "hamstring_stretch(hold=2)", "upward salute": "stand + arms_overhead(hold=2)",
}


# =============================================================================
# 26. ADVANCED SKILLS / PLYOMETRICS / GYMNASTICS / BOARD, SNOW, WATER / COMBAT
# =============================================================================
RUN_A = {"right_leg": Lg(50, 0, 6, 90), "left_leg": Lg(25, 180, 6, 20), "right_arm": A(45, 175, 10, 70), "left_arm": A(65, 6, -15, 90)}
RUN_B = {"left_leg": Lg(50, 0, 6, 90), "right_leg": Lg(25, 180, 6, 20), "left_arm": A(45, 175, 10, 70), "right_arm": A(65, 6, -15, 90)}


@motion("euro_step", "Euro step: from a run, a long step out to the right, then a second long step across to the "
        "left, gathering the ball in both hands, ready to finish.", "action", LEGS + ["pelvis", "spine"], ARMS)
def _euro():
    hold = grip2(0.10, -0.25, 0.30, "out")
    return [k(0.0, **RUN_A, spine=S(12), pelvis=P()),
            k(0.3, right_leg=leg_at(0.15, 0.42, 0.25, 0, 30, "right"), left_leg=Lg(30, -120, 8, 70), spine=S(15, 0, 10), pelvis=P(6, 0, 8), **hold),
            k(0.65, left_leg=leg_at(0.15, 0.42, 0.25, 0, 30, "left"), right_leg=Lg(30, -120, 8, 70), spine=S(15, 0, -10), pelvis=P(6, 0, -8)),
            k(0.95, **stance_legs("normal", 0.45), spine=S(12), pelvis=P(4))]


@motion("spin_move", "Spin move while running: plant, spin the whole body a full turn on the plant foot with the arms "
        "tucked, and continue forward.", "action", LEGS + ["body"], ARMS + ["spine", "pelvis"])
def _spin_move():
    return [k(0.0, **RUN_A, body=B(turn=0), spine=S(12)),
            k(0.25, right_leg=leg_at(0.0, 0.14, 0.2, 0, 10, "right"), left_leg=Lg(30, 120, 8, 70), body=B(turn=0),
              right_arm=A(30, 20, -30, 110), left_arm=A(30, 20, -30, 110)),
            k(0.55, body=B(turn=-180)), k(0.85, body=B(turn=-360), **RUN_B), k(1.1, **RUN_A)]


@motion("between_legs_dribble", "Between-the-legs dribble: staggered low stance, the ball pushed down between the legs "
        "from one hand to the other and back.", "cycle", ARMS + ["spine"], ["neck"], period=1.0)
def _btl():
    r = {"right_arm": arm_at(0.30, -0.45, 0.20, "out", "right"), "left_arm": A(40, 30, -20, 70)}
    mid = {"right_arm": arm_at(0.08, -0.60, 0.32, "out", "right"), "left_arm": arm_at(0.08, -0.60, 0.32, "out", "left")}
    l = {"left_arm": arm_at(0.30, -0.45, 0.20, "out", "left"), "right_arm": A(40, 30, -20, 70)}
    return [k(0.0, **r, spine=S(30)), k(0.25, **mid), k(0.5, **l), k(0.75, **mid)]


@motion("behind_back_dribble", "Behind-the-back dribble: the right hand wraps the ball around behind the hips to the "
        "left side, the left hand takes it back.", "cycle", ARMS + ["spine"], ["neck"], period=1.2)
def _btb():
    r = {"right_arm": A(30, 60, 10, 40), "left_arm": A(30, 40, -10, 60)}
    back = {"right_arm": A(30, 170, 30, 70), "left_arm": A(30, 170, 30, 70)}
    l = {"left_arm": A(30, 60, 10, 40), "right_arm": A(30, 40, -10, 60)}
    return [k(0.0, **r, spine=S(25, 10)), k(0.3, **back, spine=S(25, 0)), k(0.6, **l, spine=S(25, -10)), k(0.9, **back, spine=S(25, 0))]


@motion("fadeaway_jump", "Fadeaway jump: take off and lean the whole body back in the air while the arms release a "
        "shot high, land balanced. Combine with one_hand_set_shot(delay=0.3).", "action", LEGS + ["body"], ARMS + ["spine", "pelvis"])
def _fadeaway():
    pts, T = _flight(0.4, 0.22)
    keys = [k(0.0, **stance_legs("normal", 0.2), body=B(), right_arm=HANG, left_arm=HANG, spine=S(5)),
            k(0.3, **stance_legs("normal", 0.8), spine=S(25)),
            k(0.4, right_leg=Lg(3, 0, 8, 2), left_leg=Lg(3, 0, 8, 2), body=B(pitch=-12, air=1.0), spine=S(-5))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(pitch=-15, air=1.0, root=r), right_leg=Lg(15, 0, 8, 30), left_leg=Lg(10, 0, 8, 20)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(pitch=-8, air=1.0, root=0.0)), k(tl + 0.04, body=B(air=0.0)),
             k(tl + 0.35, **stance_legs("normal", 0.6), body=B(), spine=S(15)), k(tl + 0.8, **stance_legs("normal", 0.2), spine=S(5))]
    return keys


@motion("bicycle_kick", "Overhead (bicycle / scissor) kick: jump and fall back so the body is horizontal facing up, "
        "the legs scissor overhead with the right foot striking above, arms out to cushion the landing on the back.",
        "action", ["body"] + FULL, ["neck"])
def _bicycle_kick():
    return [k(0.0, **stance_legs("normal", 0.3), body=B(), spine=S(5), right_arm=HANG, left_arm=HANG),
            k(0.3, body=B(pitch=-40, air=1.0, root=0.25), left_leg=Lg(110, 0, 8, 20), right_leg=Lg(20, 0, 8, 60),
              right_arm=A(70, 80, 0, 20), left_arm=A(70, 80, 0, 20), spine=S(10)),
            k(0.55, body=B(pitch=-95, air=1.0, root=0.45), right_leg=Lg(150, 0, 8, 5), left_leg=Lg(40, 0, 8, 40)),
            k(0.8, body=B(pitch=-90, air=1.0, root=0.0), right_leg=Lg(60, 0, 8, 30), left_leg=Lg(50, 0, 8, 40),
              right_arm=A(40, 100, 0, 10), left_arm=A(40, 100, 0, 10)),
            k(1.0, body=B(pitch=-90, air=0.0)), k(1.5, hold=True)]


@motion("two_fist_punch", "Two-fist punch clear (goalkeeper): both fists together drive up and forward to punch a high "
        "ball away. Combine with jump.", "action", ARMS, ["spine"])
def _fist_punch():
    return [k(0.0, **both(0.10, -0.12, 0.25, "down")), k(0.25, **both(0.05, 0.05, 0.20, "down")),
            k(0.45, right_arm=A(150, 5, 0, 5), left_arm=A(150, 5, 0, 5)), k(0.7, hold=True), k(1.1, **both(0.10, -0.12, 0.25, "down"))]


@motion("drag_back_turn", "Drag-back turn: the sole of the right foot rolls the ball back, the body turns away and "
        "the right foot steps behind to go the other way.", "action", LEGS + ["pelvis", "body"], ARMS + ["spine"])
def _drag_back():
    return [k(0.0, **stance_legs("normal", 0.3), body=B(turn=0), spine=S(12), right_arm=A(30, 60, 0, 30), left_arm=A(30, 60, 0, 30)),
            k(0.3, right_leg=Lg(25, 0, 8, 30), left_leg=leg_at(0.0, 0.14, 0.12, 0, 10, "left")),
            k(0.55, right_leg=Lg(15, 180, 8, 40), body=B(turn=-60)),
            k(0.9, **stance_legs("normal", 0.3), body=B(turn=-180))]


@motion("swim_move", "Pass-rush swim move: step past the blocker while the right arm swings up and over the top like "
        "a freestyle stroke, the left hand clearing down.", "action", FULL, ["neck"])
def _swim_move():
    return [k(0.0, **stance_legs("wide", 0.6), spine=S(30), pelvis=P(10), **both(0.16, -0.18, 0.30, "down")),
            k(0.3, right_leg=leg_at(0.30, 0.16, 0.22, 0, 10, "right"), right_arm=A(165, 20, 0, 20), left_arm=A(30, 60, 0, 20), spine=S(25, -25)),
            k(0.55, left_leg=leg_at(0.25, 0.14, 0.22, 0, 10, "left"), right_leg=Lg(20, 180, 8, 30), right_arm=A(60, -20, 0, 30), spine=S(30, -10)),
            k(0.9, **stance_legs("normal", 0.5), spine=S(25), **both(0.16, -0.18, 0.30, "down"))]


@motion("pump_fake", "Pump fake: the throwing arm cocks back and starts forward as if to throw, then stops and pulls "
        "the ball back in.", "action", ARMS + ["spine"], ["pelvis"])
def _pump_fake():
    ball = grip2(0.18, -0.10, 0.22, "down")
    return [k(0.0, **ball, spine=S(8, 20)), k(0.35, right_arm=A(95, 130, 80, 95), left_arm=A(60, 0, 0, 30), spine=S(5, 45)),
            k(0.55, right_arm=A(110, 60, 70, 80), spine=S(8, 10)), k(0.75, hold=True), k(1.1, **ball, spine=S(8, 20))]


@motion("slice_backhand", "One-hand slice backhand: racket high back by the left shoulder, swing down and forward "
        "under the ball, open finish out in front.", "action", ARMS + ["spine"], ["pelvis", "neck"])
def _slice():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(10)),
            k(0.45, right_arm=arm_at(-0.28, 0.12, 0.25, "out", "right"), left_arm=arm_at(0.18, -0.05, 0.28, "down", "left"), spine=S(12, -70)),
            k(0.8, right_arm=arm_at(0.05, -0.30, 0.48, "out", "right"), spine=S(15, -15)),
            k(1.0, right_arm=A(80, 50, 0, 8), left_arm=A(55, 160, 0, 10), spine=S(12, 5)), k(1.5, right_arm=READY_R, left_arm=READY_R, spine=S(10))]


@motion("drop_step", "Drop step: from an athletic stance, open the hips and step the right foot back at an angle to "
        "turn and run in that direction.", "action", LEGS + ["pelvis", "spine"], ARMS)
def _drop_step():
    return [k(0.0, **stance_legs("wide", 0.5), pelvis=P(5), spine=S(15), right_arm=READY_R, left_arm=READY_R),
            k(0.35, right_leg=leg_at(-0.30, 0.30, 0.22, 0, 60, "right"), pelvis=P(5, 45), spine=S(15, 40),
              right_arm=A(40, 160, 10, 70), left_arm=A(55, 6, -15, 85)),
            k(0.7, hold=True)]


@motion("depth_jump", "Depth jump: step off a box, land on both feet absorbing briefly, then immediately rebound up "
        "as high as possible and land.", "action", LEGS + ["body"], ARMS + ["spine", "pelvis"])
def _depth_jump():
    pts, T = _flight(0.75, 0.3)
    keys = [k(0.0, **stance_legs("narrow", 0.05), body=B(air=1.0, root=0.40), right_arm=HANG, left_arm=HANG, spine=S(3)),
            k(0.25, right_leg=Lg(20, 0, 8, 10), body=B(air=1.0, root=0.40)),
            k(0.5, **stance_legs("normal", 0.1), body=B(air=1.0, root=0.0), right_arm=A(30, 170, 10, 15), left_arm=A(30, 170, 10, 15)),
            k(0.54, body=B(air=0.0)),
            k(0.66, **stance_legs("normal", 0.7), spine=S(30)),
            k(0.75, right_leg=Lg(3, 0, 8, 2), left_leg=Lg(3, 0, 8, 2), body=B(air=1.0), spine=S(3),
              right_arm=A(160, 8, 0, 8), left_arm=A(160, 8, 0, 8))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0)), k(tl + 0.04, body=B(air=0.0)),
             k(tl + 0.35, **stance_legs("normal", 0.6), spine=S(20), right_arm=A(40, 15, -10, 40), left_arm=A(40, 15, -10, 40)),
             k(tl + 0.8, **stance_legs("normal", 0.1), spine=S(4), right_arm=HANG, left_arm=HANG)]
    return keys


@motion("bounding", "Bounding: exaggerated running strides with long flight, the front knee driving high and the "
        "rear leg extended, big opposite arm swings.", "cycle", LEGS + ["body"], ARMS + ["spine"], period=1.2)
def _bounding():
    a = {"right_leg": Lg(80, 0, 6, 80), "left_leg": Lg(35, 180, 6, 15), "right_arm": A(50, 175, 10, 40), "left_arm": A(110, 6, -10, 50)}
    b = {"left_leg": Lg(80, 0, 6, 80), "right_leg": Lg(35, 180, 6, 15), "left_arm": A(50, 175, 10, 40), "right_arm": A(110, 6, -10, 50)}
    return [k(0.0, **a, body=B(air=1.0, root=0.10), spine=S(10)), k(0.3, body=B(air=1.0, root=0.0)),
            k(0.6, **b, body=B(air=1.0, root=0.10)), k(0.9, body=B(air=1.0, root=0.0))]


def _air_shape(name_pose: Dict[str, Dict[str, float]], h: float = 0.3, extra=None):
    pts, T = _flight(0.45, h)
    keys = [k(0.0, **stance_legs("normal", 0.15), body=B(), right_arm=HANG, left_arm=HANG, spine=S(4), pelvis=P()),
            k(0.35, **stance_legs("normal", 0.85), right_arm=A(30, 10, 0, 20), left_arm=A(30, 10, 0, 20), spine=S(30)),
            k(0.45, right_leg=Lg(3, 0, 8, 3), left_leg=Lg(3, 0, 8, 3), body=B(air=1.0), spine=S(3), right_arm=A(150, 10, 0, 5),
              left_arm=A(150, 10, 0, 5))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    keys.append(k(pts[len(pts) // 2][0], **name_pose))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), right_leg=Lg(3, 0, 8, 5), left_leg=Lg(3, 0, 8, 5), spine=S(5),
               right_arm=A(80, 60, 0, 10), left_arm=A(80, 60, 0, 10)),
             k(tl + 0.04, body=B(air=0.0)),
             k(tl + 0.3, **stance_legs("narrow", 0.5), spine=S(15)), k(tl + 0.7, **stance_legs("narrow", 0.1), spine=S(4),
                                                                      right_arm=HANG, left_arm=HANG)]
    return keys


@motion("straddle_jump", "Straddle jump: jump and split the straight legs wide to the sides at hip height, reaching "
        "the hands toward the toes, then land with the feet together.", "action", LEGS + ARMS + ["body", "spine"], ["pelvis"])
def _straddle():
    return _air_shape({"right_leg": Lg(85, 70, 10, 3), "left_leg": Lg(85, 70, 10, 3), "spine": S(40),
                       "right_arm": A(110, 45, 0, 3), "left_arm": A(110, 45, 0, 3)})


@motion("pike_jump", "Pike jump: jump and lift both straight legs together in front to hip height, folding the trunk "
        "so the hands reach the toes, then land.", "action", LEGS + ARMS + ["body", "spine"], ["pelvis"])
def _pike_jump():
    return _air_shape({"right_leg": Lg(85, 0, 4, 3), "left_leg": Lg(85, 0, 4, 3), "spine": S(45),
                       "right_arm": A(100, 5, 0, 3), "left_arm": A(100, 5, 0, 3)})


@motion("split_leap", "Split leap: from a short run, leap off one foot into a front-back split in the air with the "
        "arms out to the sides, land on the front foot.", "action", LEGS + ARMS + ["body", "spine"], ["pelvis"])
def _split_leap():
    return _air_shape({"right_leg": Lg(85, 0, 4, 3), "left_leg": Lg(70, 180, 4, 3), "spine": S(5),
                       "right_arm": A(95, 70, 0, 5), "left_arm": A(95, 70, 0, 5)}, h=0.25)


@motion("pirouette", "Pirouette / single-leg spin: rise onto the ball of the left foot with the right foot drawn up "
        "to the left knee, arms rounded in front, spin a full turn, land.", "action", LEGS + ARMS + ["body"], ["spine"])
def _pirouette():
    rounded = both(0.10, -0.15, 0.38, "out")
    return [k(0.0, **stance_legs("narrow", 0.3), body=B(turn=0, root=0.0), right_arm=A(80, 70, 0, 20), left_arm=A(80, 70, 0, 20)),
            k(0.3, left_leg=Lg(0, 0, 25, 2), right_leg=Lg(50, 75, 70, 120), body=B(root=0.05), **rounded),
            k(1.0, body=B(turn=360, root=0.05)),
            k(1.3, **stance_legs("narrow", 0.3), body=B(turn=360, root=0.0), right_arm=A(80, 70, 0, 20), left_arm=A(80, 70, 0, 20))]


@motion("front_tuck_flip", "Front tuck somersault: jump up, tuck the knees to the chest and rotate forward a full "
        "turn in the air, open out and land on the feet.", "action", ["body"] + FULL, ["neck"])
def _front_tuck():
    tuck = {"right_leg": Lg(120, 0, 8, 140), "left_leg": Lg(120, 0, 8, 140), "spine": S(40), "right_arm": A(70, 10, 0, 90),
            "left_arm": A(70, 10, 0, 90)}
    return [k(0.0, **stance_legs("normal", 0.15), body=B(), right_arm=HANG, left_arm=HANG, spine=S(4)),
            k(0.3, **stance_legs("normal", 0.85), spine=S(30), right_arm=A(30, 170, 10, 15), left_arm=A(30, 170, 10, 15)),
            k(0.4, right_leg=Lg(3, 0, 8, 3), left_leg=Lg(3, 0, 8, 3), body=B(air=1.0, root=0.0), spine=S(0),
              right_arm=A(165, 10, 0, 5), left_arm=A(165, 10, 0, 5)),
            k(0.55, **tuck, body=B(pitch=100, air=1.0, root=0.55)), k(0.75, body=B(pitch=260, air=1.0, root=0.5)),
            k(0.9, body=B(pitch=350, air=1.0, root=0.15), right_leg=Lg(10, 0, 8, 20), left_leg=Lg(10, 0, 8, 20), spine=S(10),
              right_arm=A(90, 60, 0, 10), left_arm=A(90, 60, 0, 10)),
            k(0.95, body=B(pitch=360, air=0.0, root=0.0)),
            k(1.3, **stance_legs("normal", 0.6), spine=S(20)), k(1.7, **stance_legs("normal", 0.1), spine=S(4), right_arm=HANG, left_arm=HANG)]


@motion("pike_dive", "Pike dive from a board: jump up, fold into a pike with straight legs and the hands at the "
        "toes, then open and drop head-first into the water with the arms overhead.", "action", ["body"] + FULL, ["neck"])
def _pike_dive():
    return [k(0.0, **stance_legs("narrow", 0.1), body=B(), right_arm=A(165, 10, 0, 5), left_arm=A(165, 10, 0, 5), spine=S(2)),
            k(0.3, **stance_legs("narrow", 0.7), spine=S(20), right_arm=A(40, 170, 0, 10), left_arm=A(40, 170, 0, 10)),
            k(0.45, right_leg=Lg(3, 0, 4, 2), left_leg=Lg(3, 0, 4, 2), body=B(air=1.0, root=0.3), right_arm=A(165, 10, 0, 5),
              left_arm=A(165, 10, 0, 5), spine=S(0)),
            k(0.7, body=B(pitch=60, air=1.0, root=0.55), right_leg=Lg(100, 0, 4, 2), left_leg=Lg(100, 0, 4, 2), spine=S(40),
              right_arm=A(110, 5, 0, 3), left_arm=A(110, 5, 0, 3)),
            k(1.0, body=B(pitch=180, air=1.0, root=0.2), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(0),
              right_arm=A(178, 5, 0, 2), left_arm=A(178, 5, 0, 2)),
            k(1.4, body=B(pitch=180, air=1.0, root=-0.6))]


@motion("ollie", "Skateboard ollie: from a sideways board stance crouch down, pop up and pull both knees to the chest "
        "in the air, then land back in the crouch.", "action", LEGS + ["body", "spine", "pelvis"], ARMS)
def _ollie():
    base = {"right_leg": leg_at(-0.25, 0.10, 0.25, 0, 60, "right"), "left_leg": leg_at(0.25, 0.10, 0.25, 0, 30, "left")}
    crouch = {"right_leg": leg_at(-0.25, 0.10, 0.42, 0, 60, "right"), "left_leg": leg_at(0.25, 0.10, 0.42, 0, 30, "left")}
    return [k(0.0, **base, body=B(), spine=S(15, -50), pelvis=P(5, -45), right_arm=A(60, 80, 0, 20), left_arm=A(70, 40, 0, 15)),
            k(0.35, **crouch, spine=S(30, -50)),
            k(0.45, body=B(air=1.0, root=0.0)),
            k(0.6, body=B(air=1.0, root=0.25), right_leg=Lg(70, -30, 30, 110), left_leg=Lg(70, 30, 30, 110)),
            k(0.75, body=B(air=1.0, root=0.0), **base), k(0.79, body=B(air=0.0)), k(1.0, **crouch), k(1.4, **base)]


@motion("ski_diagonal_stride", "Cross-country ski diagonal stride: long gliding strides with the opposite arm planting "
        "a pole forward and pushing back past the hip.", "cycle", LEGS + ARMS + ["spine"], ["pelvis"], period=1.4)
def _xc_ski():
    a = {"right_leg": Lg(25, 0, 6, 15), "left_leg": Lg(25, 180, 6, 10), "left_arm": A(60, 5, 0, 15), "right_arm": A(50, 178, 0, 5)}
    b = {"left_leg": Lg(25, 0, 6, 15), "right_leg": Lg(25, 180, 6, 10), "right_arm": A(60, 5, 0, 15), "left_arm": A(50, 178, 0, 5)}
    return [k(0.0, **a, spine=S(25)), k(0.7, **b)]


@motion("double_pole", "Double poling (skiing): both arms reach forward and plant together, the trunk crunches down "
        "as both arms push back past the hips, then rise.", "cycle", ARMS + ["spine"], LEGS, period=1.2)
def _double_pole():
    return [k(0.0, right_arm=A(70, 10, 0, 20), left_arm=A(70, 10, 0, 20), spine=S(15)),
            k(0.5, right_arm=A(45, 175, 0, 5), left_arm=A(45, 175, 0, 5), spine=S(55)), k(0.7, hold=True)]


@motion("water_polo_shot", "Shot from the water: upright in the water with eggbeater legs, the free arm sculling, the "
        "body rises and the throwing arm whips over the top.", "action", ["body"] + FULL, ["neck"])
def _wp_shot():
    legs = {"right_leg": Lg(55, 40, 30, 100), "left_leg": Lg(40, 20, 30, 70)}
    return [k(0.0, body=B(pitch=10, air=1.0, root=-0.3), **legs, spine=S(5), right_arm=A(100, 120, 80, 90), left_arm=A(45, 40, 40, 30)),
            k(0.4, body=B(pitch=0, air=1.0, root=-0.1), spine=S(-5, 40), right_arm=A(110, 140, 85, 100)),
            k(0.6, spine=S(10, -10), right_arm=A(120, 30, 60, 30)), k(0.75, right_arm=A(90, -10, 0, 10), spine=S(20, -25)),
            k(1.2, body=B(pitch=10, air=1.0, root=-0.3), right_arm=A(45, 40, 40, 30), spine=S(5))]


@motion("race_walk", "Race walking: fast walk with the front leg straight at contact, hips rolling, and a strong "
        "bent-arm swing.", "cycle", LEGS + ARMS + ["pelvis"], ["spine"], period=0.9)
def _race_walk():
    return [k(0.0, right_leg=Lg(25, 0, 6, 2), left_leg=Lg(20, 180, 6, 15), right_arm=A(30, 175, 10, 90), left_arm=A(45, 6, -15, 90), pelvis=P(0, 10, 4)),
            k(0.45, left_leg=Lg(25, 0, 6, 2), right_leg=Lg(20, 180, 6, 15), left_arm=A(30, 175, 10, 90), right_arm=A(45, 6, -15, 90), pelvis=P(0, -10, -4))]


@motion("step_up", "Step-up onto a box: plant the right foot on the box, drive up to standing tall on it, bring the "
        "left knee up, then step back down.", "action", LEGS + ["body"], ARMS + ["spine"])
def _step_up():
    return [k(0.0, **stance_legs("normal", 0.05), body=B(root=0.0), right_arm=HANG, left_arm=HANG),
            k(0.4, right_leg=Lg(70, 0, 6, 90), left_leg=Lg(3, 0, 8, 5), body=B(air=1.0, root=0.0), spine=S(15)),
            k(0.9, right_leg=Lg(3, 0, 6, 3), left_leg=Lg(80, 0, 6, 95), body=B(air=1.0, root=0.40), spine=S(3),
              right_arm=A(40, 175, 10, 80), left_arm=A(60, 6, -15, 90)),
            k(1.2, hold=True), k(1.7, left_leg=Lg(3, 0, 8, 5), right_leg=Lg(40, 0, 6, 60), body=B(air=1.0, root=0.10)),
            k(2.0, **stance_legs("normal", 0.05), body=B(air=0.0, root=0.0), right_arm=HANG, left_arm=HANG)]


@motion("body_hook", "Body hook: dip to the side and drive a bent-arm hook into the opponent's ribs at waist height "
        "with the hips turning, guard up with the other hand.", "action", ["left_arm", "spine"], ["pelvis"])
def _body_hook():
    return [k(0.0, left_arm=GUARD_L, spine=S(8, 12), pelvis=P(2, 20)),
            k(0.15, left_arm=A(45, 50, 80, 100), spine=S(18, 25, -10)),
            k(0.3, left_arm=A(55, -10, 80, 95), spine=S(18, -15, -10), pelvis=P(2, -10)),
            k(0.55, left_arm=GUARD_L, spine=S(8, 12), pelvis=P(2, 20))]


@motion("overhand_punch", "Overhand punch with the rear (right) hand: the fist loops up and over in an arc and comes "
        "down onto the target, the head moving off line.", "action", ["right_arm", "spine"], ["pelvis"])
def _overhand():
    return [k(0.0, right_arm=GUARD_R, spine=S(8, 12), pelvis=P(2, 20)),
            k(0.18, right_arm=A(110, 60, 70, 90), spine=S(10, 10, 10)),
            k(0.35, right_arm=A(95, -10, 30, 20), spine=S(25, -30, 10), pelvis=P(2, -15)),
            k(0.6, right_arm=GUARD_R, spine=S(8, 12), pelvis=P(2, 20))]


@motion("elbow_strike", "Horizontal elbow strike with the right arm: the arm folds tight and the elbow swings across "
        "at head height with a strong hip turn.", "action", ["right_arm", "spine"], ["pelvis"])
def _elbow():
    return [k(0.0, right_arm=GUARD_R, spine=S(8, 12), pelvis=P(2, 20)),
            k(0.15, right_arm=A(85, 90, 90, 150), spine=S(8, 30)),
            k(0.32, right_arm=A(88, -10, 90, 150), spine=S(8, -35), pelvis=P(2, -20)),
            k(0.6, right_arm=GUARD_R, spine=S(8, 12), pelvis=P(2, 20))]


@motion("riding_posture", "Riding posture (horse, bike seat): sitting tall with the legs apart and knees bent around "
        "the saddle, heels down, hands forward low holding the reins.", "pose", ["body"] + FULL, ["neck"])
def _riding():
    return [k(0.0, body=B(air=1.0, root=-0.15), right_leg=Lg(45, 40, 20, 80), left_leg=Lg(45, 40, 20, 80), spine=S(5),
              **both(0.12, -0.38, 0.32, "down"))]


_POS_ALIASES4 = {
    "euro step": "run(times=1)\neuro_step\nrunning_lay_up", "spin move": "run(times=1) + ball_carry\nspin_move + ball_carry",
    "between the legs dribble": "stance(width=wide, depth=0.5, stagger=left) + between_legs_dribble(times=2)",
    "behind the back dribble": "stance(depth=0.5) + behind_back_dribble(times=2)", "fadeaway": "fadeaway_jump + one_hand_set_shot(delay=0.3)",
    "fadeaway jumper": "fadeaway_jump + one_hand_set_shot(delay=0.3)", "bicycle kick": "bicycle_kick", "scissor kick": "bicycle_kick",
    "overhead kick": "bicycle_kick", "goalkeeper punch": "jump + two_fist_punch(delay=0.2)", "punch clear": "jump + two_fist_punch(delay=0.2)",
    "drag back": "drag_back_turn", "cruyff turn": "drag_back_turn", "swim move": "swim_move", "pass rush": "four_point_stance(hold=0.5)\nswim_move",
    "pump fake": "stance(depth=0.3) + pump_fake", "slice backhand": "stance(width=wide, depth=0.4) + slice_backhand",
    "drop step": "drop_step", "depth jump": "depth_jump", "depth jumps": "depth_jump", "bounding": "bounding(times=3)", "bounds": "bounding(times=3)",
    "straddle jump": "straddle_jump", "pike jump": "pike_jump", "split leap": "run(times=1)\nsplit_leap", "leap": "run(times=1)\nsplit_leap",
    "pirouette": "pirouette", "spin": "pirouette", "front flip": "front_tuck_flip", "front tuck": "front_tuck_flip", "somersault": "front_tuck_flip",
    "pike dive": "pike_dive", "springboard dive": "pike_dive", "diving board dive": "pike_dive", "ollie": "ollie", "skateboarding": "board_stance(hold=0.5)\nollie",
    "cross country skiing": "ski_diagonal_stride(times=3)", "nordic skiing": "ski_diagonal_stride(times=3)", "double poling": "double_pole(times=3)",
    "water polo shot": "tread_water\nwater_polo_shot", "eggbeater": "tread_water(times=3)", "treading water": "tread_water(times=3)",
    "race walking": "race_walk(times=3)", "power walking": "race_walk(times=3)", "walking": "walk(times=3)", "walk": "walk(times=3)",
    "step up": "step_up", "step ups": "step_up\nstep_up", "box step up": "step_up", "body shot": "fighting_stance + guard + body_hook",
    "body hook": "fighting_stance + guard + body_hook", "overhand": "fighting_stance + guard + overhand_punch",
    "overhand right": "fighting_stance + guard + overhand_punch", "elbow strike": "fighting_stance + guard + elbow_strike",
    "horse riding": "riding_posture(hold=2)", "horseback riding": "riding_posture(hold=2)", "equestrian": "riding_posture(hold=2)",
    "badminton smash": "jump + overhead_arm_strike(delay=0.1)", "badminton clear": "stance(depth=0.3) + overhead_arm_strike",
    "badminton ready position": "stance(width=wide, depth=0.5) + hands_up_ready(hold=1)",
    "table tennis forehand": "stance(width=wide, depth=0.5) + forehand_swing", "ping pong forehand": "stance(width=wide, depth=0.5) + forehand_swing",
    "table tennis backhand": "stance(width=wide, depth=0.5) + backhand_block", "squash forehand": "stance(width=wide, depth=0.5) + forehand_swing",
    "handball jump shot": "run(times=1)\njump + overhand_throw(delay=0.2)", "handball shot": "stride_step + overhand_throw(delay=0.2)",
    "disc golf drive": "run(pace=jog, times=1)\nstance(depth=0.3) + backhand_disc_throw", "pickleball dink": "stance(width=wide, depth=0.6) + punch_volley",
    "teep": "fighting_stance\nfront_kick", "push kick": "fighting_stance\nfront_kick", "jumping rope double unders": "jump_rope(times=6, speed=1.4)",
    "catcher throw down": "catcher_crouch(hold=0.5)\nstride_step + overhand_throw(delay=0.15)",
    "crow hop throw": "single_leg_hop\nstride_step + overhand_throw(delay=0.2)", "hip turn and run": "drop_step\nrun(pace=sprint, times=2)",
    "face off": "stick_ready(hold=1)", "lacrosse face off": "stick_ready(hold=1)",
}


# =============================================================================
# 27. ATHLETICS THROWS/JUMPS, GYMNASTICS APPARATUS, CHEER, SKATING, SLIDING, CURLING, SHOOTING,
#     COMBAT (judo, jiu-jitsu, sumo, taekwondo, kendo), STRENGTH (strongman, CrossFit, bodybuilding)
# =============================================================================
def _spin_keys(turns: float, t0: float, t1: float, n: int = 6):
    return [k(t0 + (t1 - t0) * i / n, body=B(turn=-360.0 * turns * i / n)) for i in range(n + 1)]


@motion("discus_spin", "Rotational discus-style throw: wind the throwing arm back at shoulder height, spin one and a "
        "half turns across the circle on the balls of the feet, then sling the long arm through to release.",
        "action", FULL + ["body"], ["neck"])
def _discus():
    base = stance_legs("wide", 0.45)
    keys = [k(0.0, **base, body=B(turn=0), spine=S(10, 60), pelvis=P(5, 30), right_arm=A(85, 160, 0, 5), left_arm=A(80, 40, 0, 20))]
    keys += _spin_keys(1.5, 0.3, 1.2)
    keys += [k(0.75, right_leg=Lg(30, 90, 20, 60), left_leg=leg_at(0.0, 0.14, 0.2, 0, 30, "left")), k(1.15, **base),
             k(1.3, spine=S(10, -40), pelvis=P(5, -30), right_arm=A(90, 0, 0, 5), left_arm=A(40, 140, 0, 30)),
             k(1.7, spine=S(15, -60), right_arm=A(60, -40, 0, 10))]
    return keys


@motion("hammer_throw", "Hammer-style throw: two-hand winds circling the implement over the head, then three fast "
        "turns with the arms long, and a release up over the left shoulder.", "action", FULL + ["body"], ["neck"])
def _hammer():
    keys = grip_keys([(0.0, 0.0, -0.45, 0.30, "down"), (0.3, 0.32, 0.40, 0.34, "out"), (0.45, 0.0, 0.58, 0.32, "out"), (0.6, -0.32, 0.40, 0.34, "out"),
                      (0.9, 0.0, -0.45, 0.35, "down"), (2.1, 0.0, -0.45, 0.40, "down"), (2.4, -0.25, 0.45, 0.20, "out"),
                      (2.8, -0.25, 0.45, 0.20, "out")], step=0.1)
    keys += [k(0.0, **stance_legs("wide", 0.45), body=B(turn=0), spine=S(15), pelvis=P(5))] + _spin_keys(3, 0.9, 2.1, 9)
    keys += [k(2.4, spine=S(-10, -30)), k(2.8, hold=True)]
    return keys


@motion("triple_jump", "Triple jump: from a run, a hop (take off and land on the same right foot), a step (land on "
        "the left), and a final jump with both legs reaching forward into a sitting landing.", "action",
        LEGS + ["body"], ARMS + ["spine", "pelvis"])
def _triple():
    keys = [k(0.0, **RUN_A, body=B(), spine=S(10))]
    t = 0.25
    for i, (h, lead) in enumerate(((0.18, "right"), (0.16, "left"), (0.35, "both"))):
        pts, T = _flight(t, h)
        if lead == "right":
            pose = {"right_leg": Lg(70, 0, 6, 90), "left_leg": Lg(30, 180, 6, 30)}
        elif lead == "left":
            pose = {"left_leg": Lg(80, 0, 6, 30), "right_leg": Lg(35, 180, 6, 60)}
        else:
            pose = {"right_leg": Lg(90, 0, 6, 15), "left_leg": Lg(90, 0, 6, 15)}
        keys.append(k(t, body=B(air=1.0), **pose, right_arm=A(100, 10, 0, 30), left_arm=A(100, 10, 0, 30)))
        for tt, r in pts[1:-1]:
            keys.append(k(tt, body=B(air=1.0, root=r)))
        t = pts[-1][0]
        keys.append(k(t, body=B(air=1.0, root=0.0)))
        if lead != "both":
            keys.append(k(t + 0.03, body=B(air=0.0)))
            t += 0.12
    keys += [k(t + 0.03, body=B(air=0.0)), k(t + 0.4, **stance_legs("normal", 1.3), spine=S(40), right_arm=A(80, 5, 0, 10),
                                                left_arm=A(80, 5, 0, 10)), k(t + 0.8, hold=True)]
    return keys


@motion("pole_vault", "Pole vault: run holding the pole high, plant it with both arms up, swing the legs up and over "
        "upside down, turn and push off the pole, clear the bar face down and fall back onto the mat.", "action",
        ["body"] + FULL, ["neck"])
def _pole_vault():
    carry = {"right_arm": arm_at(0.22, -0.30, 0.10, "down", "right"), "left_arm": arm_at(0.10, -0.25, 0.30, "down", "left")}
    legs_a = {kk: v for kk, v in RUN_A.items() if kk.endswith("leg")}
    legs_b = {kk: v for kk, v in RUN_B.items() if kk.endswith("leg")}
    return [k(0.0, **legs_a, **carry, body=B(), spine=S(10)), k(0.3, **legs_b), k(0.6, **legs_a),
            k(0.85, right_arm=A(172, 10, 0, 5), left_arm=A(150, 10, 0, 20), left_leg=Lg(5, 180, 6, 5), right_leg=Lg(70, 0, 6, 90),
              body=B(air=1.0, root=0.2)),
            k(1.3, body=B(pitch=-150, air=1.0, root=0.9), right_leg=Lg(100, 0, 6, 10), left_leg=Lg(100, 0, 6, 10), spine=S(40)),
            k(1.6, body=B(pitch=-180, turn=180, air=1.0, root=1.3), right_leg=Lg(5, 0, 6, 5), left_leg=Lg(5, 0, 6, 5), spine=S(0)),
            k(1.9, body=B(pitch=-260, turn=180, air=1.0, root=1.2), right_arm=A(120, 60, 0, 10), left_arm=A(120, 60, 0, 10), spine=S(30)),
            k(2.4, body=B(pitch=-270, turn=180, air=1.0, root=0.1)), k(2.5, body=B(pitch=-270, turn=180, air=0.0)), k(2.9, hold=True)]


@motion("iron_cross", "Iron cross on the rings: hanging in the air with both arms straight out to the sides, body "
        "straight and vertical, legs together.", "pose", ["body"] + FULL, ["neck"])
def _iron_cross():
    return [k(0.0, body=B(air=1.0, root=0.35), right_arm=A(90, 90, 0, 2), left_arm=A(90, 90, 0, 2), right_leg=Lg(0, 0, 0, 0),
              left_leg=Lg(0, 0, 0, 0), spine=S(0))]


@motion("support_hold", "Support hold (parallel bars, dip bars, pommel horse): body held up on straight arms with "
        "the hands beside the hips, legs together hanging or held out front.", "pose", ["body"] + FULL, ["neck"])
def _support_hold():
    return [k(0.0, body=B(air=1.0, root=0.25), right_arm=A(5, 175, 0, 2), left_arm=A(5, 175, 0, 2), right_leg=Lg(0, 0, 0, 0),
              left_leg=Lg(0, 0, 0, 0), spine=S(3))]


@motion("pommel_circles", "Pommel horse circles: supporting on straight arms, the straight legs held together sweep "
        "around in a horizontal circle, the body leaning opposite.", "cycle", ["body"] + FULL, ["neck"], period=1.2)
def _pommel():
    sup = {"right_arm": A(5, 175, 0, 2), "left_arm": A(5, 175, 0, 2)}
    return [k(0.0, body=B(air=1.0, root=0.25, pitch=40), **sup, right_leg=Lg(80, 0, 0, 2), left_leg=Lg(80, 0, 0, 2), spine=S(-20)),
            k(0.3, body=B(air=1.0, root=0.25, roll=-40, pitch=0), right_leg=Lg(80, 90, 0, 2), left_leg=Lg(70, -90, 0, 2)),
            k(0.6, body=B(air=1.0, root=0.25, pitch=-40), right_leg=Lg(60, 180, 0, 2), left_leg=Lg(60, 180, 0, 2), spine=S(20)),
            k(0.9, body=B(air=1.0, root=0.25, roll=40, pitch=0), right_leg=Lg(70, -90, 0, 2), left_leg=Lg(80, 90, 0, 2))]


@motion("front_handspring", "Front handspring / vault: from a run, reach both arms forward and down, hands on the "
        "floor or table, the body flips over upside down with straight arms and lands on the feet.", "action",
        ["body"] + FULL, ["neck"])
def _front_handspring():
    up = {"right_arm": A(170, 8, 0, 3), "left_arm": A(170, 8, 0, 3)}
    return [k(0.0, **RUN_A, body=B(), spine=S(10)), k(0.3, **RUN_B),
            k(0.55, body=B(pitch=60), **up, right_leg=Lg(30, 180, 6, 5), left_leg=Lg(40, 0, 6, 20), spine=S(10)),
            k(0.8, body=B(pitch=180), right_leg=Lg(10, 180, 6, 5), left_leg=Lg(10, 180, 6, 5), spine=S(-15)),
            k(1.05, body=B(pitch=290, air=1.0, root=0.25), spine=S(-25)),
            k(1.3, body=B(pitch=360, air=0.0, root=0.0), **stance_legs("normal", 0.5), spine=S(10)),
            k(1.7, **stance_legs("normal", 0.1), spine=S(3), **up)]


@motion("back_handspring", "Back handspring: sit back as if into a chair, swing the arms back overhead and jump "
        "backward onto the hands, snap the legs over and land on the feet.", "action", ["body"] + FULL, ["neck"])
def _back_handspring():
    up = {"right_arm": A(170, 8, 0, 3), "left_arm": A(170, 8, 0, 3)}
    return [k(0.0, **stance_legs("narrow", 0.1), body=B(), **up, spine=S(3)),
            k(0.35, **stance_legs("narrow", 0.8), spine=S(25), right_arm=A(40, 175, 0, 5), left_arm=A(40, 175, 0, 5)),
            k(0.6, body=B(pitch=-90, air=1.0, root=0.3), right_leg=Lg(10, 0, 6, 20), left_leg=Lg(10, 0, 6, 20), spine=S(-35), **up),
            k(0.8, body=B(pitch=-180, air=0.0), right_leg=Lg(20, 0, 6, 10), left_leg=Lg(20, 0, 6, 10)),
            k(1.0, body=B(pitch=-290, air=1.0, root=0.15), right_leg=Lg(60, 0, 6, 40), left_leg=Lg(60, 0, 6, 40), spine=S(20)),
            k(1.2, body=B(pitch=-360, air=0.0, root=0.0), **stance_legs("narrow", 0.6), spine=S(15)),
            k(1.6, **stance_legs("narrow", 0.1), spine=S(3))]


@motion("round_off", "Round-off: run, hurdle, hands go down one after the other like a cartwheel, the legs snap "
        "together overhead and the body lands on both feet facing back the way it came.", "action", ["body"] + FULL, ["neck"])
def _round_off():
    spread = {"right_arm": A(170, 85, 0, 3), "left_arm": A(170, 85, 0, 3), "right_leg": Lg(35, 90, 8, 3), "left_leg": Lg(35, 90, 8, 3)}
    return [k(0.0, **RUN_A, body=B(), spine=S(10)), k(0.3, **spread, body=B(roll=0)),
            k(0.55, body=B(roll=-90)), k(0.8, body=B(roll=-180, turn=90), right_leg=Lg(3, 0, 8, 3), left_leg=Lg(3, 0, 8, 3)),
            k(1.05, body=B(roll=-300, turn=180)), k(1.25, body=B(roll=-360, turn=180), **stance_legs("normal", 0.6), spine=S(15)),
            k(1.6, **stance_legs("normal", 0.1), spine=S(3), right_arm=A(170, 15, 0, 3), left_arm=A(170, 15, 0, 3))]


@motion("toe_touch_jump", "Toe-touch jump (cheer): arms in a high V, swing the arms down, jump and kick the straight "
        "legs up and wide into a straddle with the arms punched out to the sides in a T, land feet together.",
        "action", LEGS + ARMS + ["body", "spine"], ["pelvis"])
def _toe_touch():
    return _air_shape({"right_leg": Lg(95, 65, 10, 3), "left_leg": Lg(95, 65, 10, 3), "spine": S(15),
                       "right_arm": A(90, 88, 0, 3), "left_arm": A(90, 88, 0, 3)}, h=0.32)


@motion("high_v", "High V motion (cheer): both arms straight up and out in a V above the head, fists tight.", "pose",
        ARMS, [])
def _high_v():
    return [k(0.0, right_arm=A(150, 60, 0, 2), left_arm=A(150, 60, 0, 2))]


@motion("stunt_base", "Stunt base position: wide squat with a flat back, both hands up at shoulder height palms up "
        "to hold a flyer's foot.", "pose", FULL, ["neck"])
def _stunt_base():
    return [k(0.0, **stance_legs("wide", 0.7), spine=S(15), pelvis=P(8), **both(0.15, 0.0, 0.25, "down"), neck=N(-20))]


@motion("liberty_pose", "Liberty (flyer pose): balanced on the straight right leg, the left foot drawn up to the right "
        "knee, arms in a high V.", "pose", FULL, ["neck"])
def _liberty():
    return [k(0.0, right_leg=Lg(0, 0, 10, 2), left_leg=Lg(50, 75, 70, 120), spine=S(0), right_arm=A(150, 60, 0, 2), left_arm=A(150, 60, 0, 2))]


@motion("seat_drop", "Trampoline seat drop: bounce, land sitting with the legs straight out in front and the hands "
        "beside the hips, rebound back up to standing.", "action", ["body"] + FULL, ["neck"])
def _seat_drop():
    return [k(0.0, **stance_legs("narrow", 0.1), body=B(air=1.0, root=0.5), right_arm=A(160, 10, 0, 5), left_arm=A(160, 10, 0, 5)),
            k(0.4, body=B(air=1.0, root=0.0), right_leg=Lg(85, 0, 4, 3), left_leg=Lg(85, 0, 4, 3), spine=S(0),
              right_arm=A(20, 170, 0, 5), left_arm=A(20, 170, 0, 5)),
            k(0.45, body=B(air=0.0)), k(0.6, hold=True),
            k(0.9, body=B(air=1.0, root=0.4), **stance_legs("narrow", 0.1), right_arm=A(160, 10, 0, 5), left_arm=A(160, 10, 0, 5)),
            k(1.2, body=B(air=1.0, root=0.0)), k(1.24, body=B(air=0.0))]


@motion("camel_spin", "Camel spin (skating): gliding on the left leg with the free right leg and trunk horizontal in "
        "an arabesque line, arms out, spinning.", "action", FULL + ["body"], ["neck"])
def _camel_spin():
    pose = dict(left_leg=Lg(3, 0, 10, 8), right_leg=Lg(85, 180, 10, 3), spine=S(70), pelvis=P(15), right_arm=A(90, 80, 0, 5),
                left_arm=A(90, 80, 0, 5))
    return [k(0.0, **pose, body=B(turn=0))] + _spin_keys(2, 0.0, 1.6, 8) + [k(1.6, hold=True)]


@motion("sit_spin", "Sit spin (skating): a deep one-leg squat on the left leg with the right leg stretched forward, "
        "arms forward, spinning.", "action", FULL + ["body"], ["neck"])
def _sit_spin():
    pose = dict(left_leg=leg_at(0.10, 0.12, 0.42, 0, 10, "left"), right_leg=Lg(80, 0, 10, 5), spine=S(35), pelvis=P(12),
                right_arm=A(80, 20, 0, 10), left_arm=A(80, 20, 0, 10))
    return [k(0.0, **pose, body=B(turn=0))] + _spin_keys(2, 0.0, 1.6, 8) + [k(1.6, hold=True)]


@motion("skating_jump", "Figure-skating jump: glide, take off from one edge with the arms swinging, pull the arms in "
        "tight to the chest and rotate one to two turns in the air, land on the right leg gliding backward with the "
        "free leg extended behind and the arms out.", "action", ["body"] + FULL, ["neck"])
def _skate_jump():
    pts, T = _flight(0.45, 0.35)
    keys = [k(0.0, right_leg=Lg(3, 0, 10, 15), left_leg=Lg(30, 180, 10, 10), body=B(turn=0), spine=S(10), right_arm=A(60, 40, 0, 20),
              left_arm=A(60, 100, 0, 20)),
            k(0.35, right_leg=Lg(5, 0, 10, 40), left_leg=Lg(50, 0, 10, 60), spine=S(20)),
            k(0.45, body=B(air=1.0, turn=0), right_leg=Lg(3, 0, 10, 3), left_leg=Lg(10, 30, 10, 20),
              **both(0.05, -0.12, 0.18, "down"))]
    for i, (t, r) in enumerate(pts[1:-1]):
        keys.append(k(t, body=B(air=1.0, root=r, turn=-540.0 * (i + 1) / (len(pts) - 1))))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0, turn=-540), right_leg=Lg(3, 0, 10, 15), left_leg=Lg(45, 180, 10, 5),
               right_arm=A(85, 85, 0, 5), left_arm=A(85, 85, 0, 5), spine=S(20)),
             k(tl + 0.04, body=B(air=0.0, turn=-540)), k(tl + 0.7, hold=True)]
    return keys


@motion("ski_jump_inrun", "Ski-jump in-run position: deep tuck with the trunk flat over the thighs and the arms held "
        "back alongside the body.", "pose", FULL, ["neck"])
def _inrun():
    return [k(0.0, **stance_legs("narrow", 1.1), spine=S(75), pelvis=P(18), right_arm=A(20, 175, 0, 5), left_arm=A(20, 175, 0, 5),
              neck=N(-30))]


@motion("ski_jump_flight", "Ski-jump flight: body straight and leaning far forward over the skis, arms held back "
        "close to the sides, legs straight and slightly apart.", "pose", ["body"] + FULL, ["neck"])
def _ski_flight():
    return [k(0.0, body=B(pitch=55, air=1.0, root=0.5), right_leg=Lg(15, 60, 10, 3), left_leg=Lg(15, 60, 10, 3), spine=S(5),
              right_arm=A(25, 170, 0, 5), left_arm=A(25, 170, 0, 5), neck=N(-30))]


@motion("sled_push", "Bobsled-style push start: bent low, both hands forward on the push bar, driving with fast "
        "sprinting steps.", "cycle", LEGS + ARMS + ["spine", "pelvis"], ["neck"], period=0.6)
def _sled_push():
    arms = both(0.18, -0.40, 0.42, "down")
    return [k(0.0, right_leg=Lg(60, 0, 6, 90), left_leg=Lg(25, 180, 6, 20), spine=S(55), pelvis=P(15), **arms, neck=N(-30)),
            k(0.3, left_leg=Lg(60, 0, 6, 90), right_leg=Lg(25, 180, 6, 20))]


@motion("prone_sled_ride", "Skeleton ride: lying face down head first on the sled, arms tight along the sides, legs "
        "straight and together, head just lifted.", "pose", ["body"] + FULL, ["neck"])
def _skeleton():
    return [k(0.0, body=B(90), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(-5), right_arm=A(10, 175, 0, 3),
              left_arm=A(10, 175, 0, 3), neck=N(-25))]


@motion("supine_sled_ride", "Luge ride: lying on the back feet first, legs straight and together, arms along the sides, "
        "head lifted just enough to see.", "pose", ["body"] + FULL, ["neck"])
def _luge():
    return [k(0.0, body=B(-90), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(8), right_arm=A(10, 30, 0, 3),
              left_arm=A(10, 30, 0, 3), neck=N(25))]


@motion("curling_delivery", "Curling-style sliding delivery: a long low lunge sliding forward on the bent left leg, "
        "the right leg trailing straight behind on the ice, the right arm reaching forward releasing the stone.",
        "pose", FULL, ["neck"])
def _curling():
    return [k(0.0, left_leg=leg_at(0.30, 0.10, 0.50, 0, 10, "left"), right_leg=Lg(70, 180, 20, 5), spine=S(45), pelvis=P(15),
              right_arm=A(70, 5, 0, 5), left_arm=A(45, 70, 0, 10), neck=N(-20))]


@motion("sweeping", "Sweeping the ice (curling): bent over with both hands on the broom low in front, scrubbing it "
        "fast side to side while walking.", "cycle", ARMS + ["spine"], LEGS, period=0.4)
def _sweeping():
    return grip_keys([(0.0, 0.15, -0.55, 0.40, "down"), (0.2, -0.10, -0.58, 0.42, "down"), (0.4, 0.15, -0.55, 0.40, "down")], step=0.05) + \
        [k(0.0, spine=S(45))]


@motion("prone_aim", "Prone shooting position: lying face down, chest raised on the elbows, both hands up at the face "
        "holding a rifle aimed forward, legs apart.", "pose", ["body"] + FULL, ["neck"])
def _prone_aim():
    return [k(0.0, body=B(88), right_leg=Lg(8, 90, 30, 3), left_leg=Lg(8, 90, 0, 3), spine=S(-30), pelvis=P(),
              right_arm=A(110, 30, 0, 110), left_arm=A(130, 5, 0, 90), neck=N(-10))]


@motion("rifle_aim_standing", "Standing rifle aim: side-on, the left elbow tucked against the side supporting the "
        "rifle, the right hand and cheek at the stock, eye along the barrel.", "pose", FULL, ["neck"])
def _rifle_stand():
    return [k(0.0, **stance_legs("normal", 0.05), spine=S(0, 70, -8), pelvis=P(0, 60), right_arm=arm_at(0.05, 0.12, 0.15, "out", "right"),
              left_arm=arm_at(0.10, 0.05, 0.35, "down", "left"), neck=N(10, -70))]


@motion("pistol_aim", "One-hand pistol / target aim: side-on, the right arm straight out at eye level, the left hand "
        "in the pocket or on the hip.", "pose", FULL, ["neck"])
def _pistol():
    return [k(0.0, **stance_legs("normal", 0.05), spine=S(0, 70), pelvis=P(0, 60), right_arm=A(90, 0, 0, 2),
              left_arm=arm_at(0.26, -0.47, 0.02, "out", "left"), neck=N(0, -70))]


@motion("shotgun_mount", "Shotgun mount: staggered stance leaning slightly forward, both hands holding the gun up at "
        "the right shoulder, cheek down on the stock, tracking forward.", "pose", FULL, ["neck"])
def _shotgun():
    return [k(0.0, **stance_legs("normal", 0.2, "left", 20), spine=S(12, 20), pelvis=P(4, 20),
              right_arm=arm_at(0.10, 0.10, 0.12, "out", "right"), left_arm=arm_at(-0.05, 0.10, 0.45, "down", "left"), neck=N(15, -15))]


@motion("kneeling_aim", "Kneeling aim: the right knee down, sitting back on the right heel, the left knee up with the "
        "left elbow resting on it, rifle at the right shoulder.", "pose", FULL, ["neck"])
def _kneel_aim():
    return [k(0.0, left_leg=Lg(80, 0, 4, 100), right_leg=Lg(10, 0, 0, 130), spine=S(15, 30), right_arm=arm_at(0.05, 0.10, 0.15, "out", "right"),
              left_arm=arm_at(0.05, -0.05, 0.40, "down", "left"), neck=N(10, -30))]


@motion("hip_throw", "Hip throw (judo / wrestling): grip and pull with both hands, step across and pivot so the back "
        "turns into the partner, drop the hips low, then bend forward and turn, pulling the arms down around.",
        "action", FULL + ["body"], ["neck"])
def _hip_throw():
    grip = both(0.20, -0.05, 0.45, "down")
    return [k(0.0, **stance_legs("normal", 0.3), body=B(turn=0), spine=S(10), **grip),
            k(0.4, right_leg=leg_at(0.25, -0.05, 0.2, 0, 0, "right"), body=B(turn=-90), right_arm=A(80, -40, 0, 60),
              left_arm=A(70, 40, 0, 40)),
            k(0.7, **stance_legs("normal", 0.7), body=B(turn=-180), spine=S(20)),
            k(1.1, spine=S(65, -30), right_arm=A(40, -20, 0, 50), left_arm=A(55, -20, 0, 35), **stance_legs("normal", 0.4)),
            k(1.5, hold=True)]


@motion("shoulder_throw", "Shoulder throw: pull, turn the back in under the partner while dropping low with the right "
        "arm hooked up under their armpit, then pitch forward over the bent knees.", "action", FULL + ["body"], ["neck"])
def _shoulder_throw():
    grip = both(0.20, -0.05, 0.45, "down")
    return [k(0.0, **stance_legs("normal", 0.3), body=B(turn=0), spine=S(10), **grip),
            k(0.45, body=B(turn=-180), **stance_legs("normal", 1.0), spine=S(25), right_arm=A(100, 30, 90, 120), left_arm=A(60, -20, 0, 40)),
            k(0.85, spine=S(75, -20), **stance_legs("normal", 0.7), right_arm=A(70, -10, 60, 90), left_arm=A(40, -30, 0, 40)),
            k(1.3, hold=True)]


@motion("back_breakfall", "Back breakfall: squat down, roll back onto the rounded back with the chin tucked, and slap "
        "both arms flat on the floor at 45 degrees as the back lands.", "action", ["body"] + FULL, ["neck"])
def _breakfall():
    return [k(0.0, **stance_legs("normal", 0.1), body=B(), spine=S(3), right_arm=A(90, 5, 0, 5), left_arm=A(90, 5, 0, 5), neck=N()),
            k(0.4, **stance_legs("normal", 1.3), spine=S(30), neck=N(35)),
            k(0.75, body=B(-70), right_leg=Lg(70, 0, 8, 60), left_leg=Lg(70, 0, 8, 60), spine=S(30),
              right_arm=A(130, 45, 0, 5), left_arm=A(130, 45, 0, 5)),
            k(0.9, right_arm=A(40, 45, 0, 3), left_arm=A(40, 45, 0, 3)), k(1.4, hold=True)]


@motion("closed_guard", "Guard position (jiu-jitsu): lying on the back with the knees bent and apart up in the air as "
        "if wrapped around an opponent, hands up in front gripping.", "pose", ["body"] + FULL, ["neck"])
def _guard_pos():
    return [k(0.0, body=B(-80), right_leg=Lg(80, 50, 30, 100), left_leg=Lg(80, 50, 30, 100), spine=S(15), right_arm=A(80, 10, 0, 60),
              left_arm=A(80, 10, 0, 60), neck=N(20))]


@motion("mount_position", "Mount position: kneeling astride with the knees wide on the floor, hips sitting up tall, "
        "hands posted forward or up in a guard.", "pose", FULL, ["neck"])
def _mount():
    return [k(0.0, right_leg=Lg(10, 65, 60, 100), left_leg=Lg(10, 65, 60, 100), spine=S(10), **both(0.18, -0.25, 0.35, "down"))]


@motion("side_control", "Side control (top): chest low and heavy across, both knees and the toes on the floor, hips "
        "low, arms wrapped around low in front.", "pose", ["body"] + FULL, ["neck"])
def _side_control():
    return [k(0.0, **fit_pose("side_control", {"body.pitch": 75, "legs.raise": 70, "legs.knee": 110, "arms.raise": 60, "arms.elbow": 60},
                               {"legs": {"dir": 30.0, "twist": 30.0}, "arms": {"dir": 10.0, "twist": 0.0}, "spine": {"lean": 10.0}},
                               [("right_knee", "floor", 0, 3), ("left_foot", "floor", 0, 2), ("neck", "y", 0.35, 2), ("right_hand", "floor", 0, 1)]))]


@motion("shiko_stomp", "Leg stomp (sumo shiko): wide deep squat with the hands on the knees, shift onto the left leg and "
        "lift the straight right leg high to the side, then stomp it down back into the squat.", "action", FULL, ["neck"])
def _shiko():
    base = {**stance_legs("very_wide", 1.0, toe=35), "spine": S(15), "pelvis": P(10), **both(0.35, -0.55, 0.20, "out")}
    return [k(0.0, **base), k(0.6, left_leg=leg_at(0.0, 0.20, 0.08, 0, 30, "left"), right_leg=Lg(80, 80, 20, 5), spine=S(5, 0, 20)),
            k(0.9, hold=True), k(1.15, **base), k(1.5, hold=True)]


@motion("charge_from_crouch", "Explosive charge from a crouch (sumo tachiai, three-point start): low crouch with the "
        "fists down, explode forward and up with both hands thrusting out.", "action", ["body"] + FULL, ["neck"])
def _tachiai():
    return [k(0.0, **stance_legs("very_wide", 1.1, toe=30), body=B(pitch=20), spine=S(45), pelvis=P(12), right_arm=A(65, 5, 0, 5),
              left_arm=A(65, 5, 0, 5), neck=N(-20)),
            k(0.5, hold=True),
            k(0.8, body=B(pitch=15), right_leg=leg_at(0.25, 0.20, 0.30, 0, 10, "right"), left_leg=Lg(35, 180, 10, 20), spine=S(30),
              **both(0.18, 0.0, 0.58, "out")),
            k(1.2, hold=True)]


@motion("axe_kick", "Axe kick: raise the straight right leg up high in front, then chop the heel straight down.",
        "action", LEGS + ["pelvis"], ["spine", "right_arm", "left_arm"])
def _axe():
    base = stance_legs("normal", 0.25, "left", 18)
    return [k(0.0, **base, pelvis=P(2, 15), spine=S(6, 10), right_arm=GUARD_R, left_arm=GUARD_L),
            k(0.4, right_leg=Lg(130, 10, 8, 5), left_leg=leg_at(0.0, 0.14, 0.08, 0, 20, "left"), spine=S(-10), pelvis=P(-15)),
            k(0.6, right_leg=Lg(35, 0, 8, 5), spine=S(10)), k(0.95, **base, pelvis=P(2, 15), spine=S(6, 10))]


@motion("spinning_back_kick", "Spinning back kick: turn the back to the target, look over the shoulder and thrust the "
        "right heel straight back at waist height, recoil and turn back.", "action", LEGS + ["body", "pelvis", "spine"], ARMS)
def _spin_back():
    base = stance_legs("normal", 0.25, "left", 18)
    return [k(0.0, **base, body=B(turn=0), spine=S(6, 10), right_arm=GUARD_R, left_arm=GUARD_L),
            k(0.3, body=B(turn=-150), right_leg=Lg(60, 0, 8, 120), left_leg=leg_at(0.0, 0.12, 0.08, 0, 40, "left")),
            k(0.5, body=B(turn=-180), right_leg=Lg(70, 180, 8, 5), spine=S(40)),
            k(0.7, right_leg=Lg(60, 0, 8, 120), spine=S(10)), k(1.1, **base, body=B(turn=-360), spine=S(6, 10))]


@motion("overhead_two_hand_strike", "Overhead two-hand strike (kendo, axe chop): both hands raise the sword high "
        "overhead, step forward and cut straight down to head height in front, arms extended.", "action", FULL, ["neck"])
def _kendo():
    keys = grip_keys([(0.0, 0.0, -0.20, 0.40, "down"), (0.4, 0.0, 0.55, 0.10, "out"), (0.65, 0.0, 0.10, 0.60, "down"),
                      (0.75, 0.0, 0.02, 0.62, "down"), (1.2, 0.0, -0.20, 0.40, "down")], step=0.06)
    keys += [k(0.0, **stance_legs("normal", 0.2, "right", 0), spine=S(3)),
             k(0.65, right_leg=leg_at(0.35, 0.14, 0.18, 0, 0, "right"), left_leg=Lg(25, 180, 0, 10), spine=S(8)),
             k(1.2, **stance_legs("normal", 0.2, "right", 0), spine=S(3))]
    return keys


@motion("muscle_up", "Muscle-up: from a dead hang, pull explosively, turn the wrists over and push the body up above "
        "the bar to straight-arm support.", "action", ["body"] + FULL, ["neck"])
def _muscle_up():
    return [k(0.0, body=B(air=1.0, root=0.25), right_leg=Lg(5, 0, 4, 10), left_leg=Lg(5, 0, 4, 10), spine=S(0),
              right_arm=A(172, 20, 0, 3), left_arm=A(172, 20, 0, 3)),
            k(0.5, body=B(air=1.0, root=0.55), right_arm=A(110, 30, 60, 140), left_arm=A(110, 30, 60, 140), spine=S(15),
              right_leg=Lg(30, 0, 4, 40), left_leg=Lg(30, 0, 4, 40)),
            k(0.8, body=B(air=1.0, root=0.8), right_arm=A(30, 120, 30, 120), left_arm=A(30, 120, 30, 120), spine=S(25)),
            k(1.2, body=B(air=1.0, root=0.95), right_arm=A(5, 175, 0, 2), left_arm=A(5, 175, 0, 2), spine=S(3),
              right_leg=Lg(3, 0, 4, 3), left_leg=Lg(3, 0, 4, 3)), k(1.5, hold=True)]


@motion("toes_to_bar", "Toes-to-bar: hanging from a bar, swing and lift both straight legs up until the toes touch the "
        "bar, lower under control.", "cycle", ["body"] + FULL, ["neck"], period=1.6)
def _ttb():
    return [k(0.0, body=B(air=1.0, root=0.25), right_leg=Lg(5, 0, 4, 3), left_leg=Lg(5, 0, 4, 3), spine=S(-5),
              right_arm=A(172, 20, 0, 3), left_arm=A(172, 20, 0, 3)),
            k(0.6, right_leg=Lg(150, 0, 4, 3), left_leg=Lg(150, 0, 4, 3), spine=S(30)), k(0.8, hold=True)]


@motion("handstand_push_up", "Handstand push-up: from a handstand, bend the elbows to lower the head toward the "
        "floor, press back up to straight arms.", "cycle", ["body"] + FULL, ["neck"], period=2.0)
def _hspu():
    return [k(0.0, body=B(pitch=180), right_arm=A(178, 8, 0, 2), left_arm=A(178, 8, 0, 2), right_leg=Lg(0, 0, 0, 0),
              left_leg=Lg(0, 0, 0, 0), spine=S(0), neck=N(-20)),
            k(0.9, right_arm=A(150, 60, 0, 90), left_arm=A(150, 60, 0, 90)), k(1.1, hold=True)]


@motion("wall_ball", "Wall ball shot: squat holding a ball at the chest, drive up and throw it up high to a target "
        "with both hands, arms finishing overhead.", "action", FULL, ["neck"])
def _wall_ball():
    hold = grip2(0.0, -0.20, 0.28, "down")
    return [k(0.0, **stance_legs("wide", 0.05), spine=S(4), **hold),
            k(0.8, **stance_legs("wide", 1.0), spine=S(25), pelvis=P(10)),
            k(1.2, **stance_legs("wide", 0.05), spine=S(-3), pelvis=P(), right_arm=A(160, 15, 0, 5), left_arm=A(160, 15, 0, 5)),
            k(1.5, hold=True), k(1.9, **hold, spine=S(4))]


@motion("tire_flip", "Tire flip: deep squat with the chest against the tire and the hands under its edge, drive up "
        "with the legs, flip the hands over and push it forward with straight arms.", "action", FULL, ["neck"])
def _tire_flip():
    return [k(0.0, **stance_legs("wide", 1.2), spine=S(45), pelvis=P(15), right_arm=A(55, 5, 0, 10), left_arm=A(55, 5, 0, 10)),
            k(0.7, **stance_legs("wide", 0.5), spine=S(20), right_arm=A(60, 10, -30, 100), left_arm=A(60, 10, -30, 100)),
            k(1.0, right_leg=leg_at(0.25, 0.16, 0.15, 0, 10, "right"), left_leg=Lg(20, 180, 8, 15), spine=S(25),
              **both(0.12, 0.10, 0.58, "out")), k(1.4, hold=True)]


@motion("stone_lift", "Atlas stone / heavy object lift: deep squat wrapping both arms around a round load, lap it "
        "onto the thighs, then stand and extend the hips to lift it up to chest height.", "action", FULL, ["neck"])
def _stone():
    hug = both(0.05, -0.35, 0.38, "out")
    return [k(0.0, **stance_legs("wide", 1.1), spine=S(55), pelvis=P(15), **both(0.10, -0.55, 0.30, "out")),
            k(0.6, **stance_legs("wide", 0.9), spine=S(30), **hug), k(0.9, hold=True),
            k(1.5, **stance_legs("wide", 0.05), spine=S(-8), pelvis=P(-5), **both(0.05, -0.12, 0.35, "out")), k(1.9, hold=True)]


@motion("front_double_biceps", "Front double-biceps pose: facing forward, both arms raised out to the sides with the "
        "elbows at shoulder height and the fists curled up beside the head, flexing.", "pose", ARMS + ["spine"], ["neck"])
def _fdb():
    return [k(0.0, right_arm=A(95, 88, 90, 125), left_arm=A(95, 88, 90, 125), spine=S(-3))]


@motion("lat_spread", "Front lat spread: fists on the waist with the elbows pushed forward and the back muscles flared "
        "wide.", "pose", ARMS + ["spine"], ["neck"])
def _lat_spread():
    return [k(0.0, right_arm=arm_at(0.24, -0.45, 0.10, "out", "right"), left_arm=arm_at(0.24, -0.45, 0.10, "out", "left"), spine=S(-2))]


@motion("most_muscular", "Most-muscular pose: leaning slightly forward, the hands brought together low in front of "
        "the belly with the arms rounded, everything flexed.", "pose", ARMS + ["spine"], ["neck"])
def _most_muscular():
    return [k(0.0, right_arm=arm_at(0.02, -0.40, 0.28, "out", "right"), left_arm=arm_at(0.02, -0.40, 0.28, "out", "left"), spine=S(18))]


@motion("side_chest", "Side chest pose: turned side-on, the front arm bent across the body with the fist held by the "
        "other hand, chest lifted.", "pose", ARMS + ["spine"], ["neck"])
def _side_chest():
    return [k(0.0, spine=S(-5, 50), right_arm=arm_at(-0.05, -0.30, 0.30, "down", "right"), left_arm=arm_at(0.10, -0.32, 0.25, "out", "left"),
              neck=N(0, -40))]


_POS_ALIASES5 = {
    "discus": "discus_spin", "discus throw": "discus_spin", "hammer throw": "hammer_throw", "triple jump": "triple_jump",
    "hop step and jump": "triple_jump", "pole vault": "pole_vault", "steeplechase": "run(times=2)\nhurdle_step", "iron cross": "iron_cross(hold=2)",
    "rings": "iron_cross(hold=2)", "parallel bars": "support_hold(hold=2)", "dip bars": "support_hold(hold=2)", "pommel horse": "pommel_circles(times=3)",
    "vault": "front_handspring", "front handspring": "front_handspring", "back handspring": "back_handspring", "round off": "round_off",
    "round off back handspring": "round_off\nback_handspring", "balance beam": "arabesque(hold=1)\npirouette",
    "floor routine": "round_off\nback_handspring\nstand + arms_overhead(hold=1)",
    "toe touch": "toe_touch_jump", "cheer jump": "toe_touch_jump", "high v": "stand + high_v(hold=1.5)", "cheer motions": "stand + high_v(hold=0.6)\nstand + arms_out(hold=0.6)\nstand + t_signal(hold=0.6)",
    "stunt base": "stunt_base(hold=2)", "liberty": "liberty_pose(hold=2)", "flyer": "liberty_pose(hold=2)", "seat drop": "seat_drop",
    "trampoline": "jump(height=high)\nseat_drop\ntuck_jump", "camel spin": "camel_spin", "sit spin": "sit_spin", "figure skating jump": "skating_jump",
    "axel": "skating_jump", "figure skating spin": "camel_spin", "ski jump": "ski_jump_inrun(hold=1)\nski_jump_flight(hold=1.5)",
    "ski jumping": "ski_jump_inrun(hold=1)\nski_jump_flight(hold=1.5)", "bobsled push": "sled_push(times=4)", "bobsled": "sled_push(times=4)",
    "skeleton": "sled_push(times=2)\nprone_sled_ride(hold=2)", "luge": "supine_sled_ride(hold=2)", "curling": "curling_delivery(hold=2)",
    "curling delivery": "curling_delivery(hold=2)", "curling sweeping": "sweeping(times=6)", "sweeping": "sweeping(times=6)",
    "biathlon prone": "prone_aim(hold=2)", "prone shooting": "prone_aim(hold=2)", "shooting standing": "rifle_aim_standing(hold=2)",
    "rifle shooting": "rifle_aim_standing(hold=2)", "biathlon standing": "rifle_aim_standing(hold=2)", "pistol shooting": "pistol_aim(hold=2)",
    "target shooting": "pistol_aim(hold=2)", "trap shooting": "shotgun_mount(hold=2)", "skeet shooting": "shotgun_mount(hold=2)",
    "kneeling shooting": "kneeling_aim(hold=2)", "biathlon": "ski_diagonal_stride(times=2)\nprone_aim(hold=1.5)",
    "judo throw": "hip_throw", "hip throw": "hip_throw", "o goshi": "hip_throw", "shoulder throw": "shoulder_throw", "seoi nage": "shoulder_throw",
    "breakfall": "back_breakfall", "ukemi": "back_breakfall", "closed guard": "closed_guard(hold=2)", "guard position": "closed_guard(hold=2)",
    "mount": "mount_position(hold=2)", "mount position": "mount_position(hold=2)", "side control": "side_control(hold=2)",
    "shiko": "shiko_stomp", "sumo stomp": "shiko_stomp", "sumo": "charge_from_crouch", "tachiai": "charge_from_crouch",
    "axe kick": "axe_kick", "spinning back kick": "spinning_back_kick", "back kick": "spinning_back_kick", "taekwondo kick": "fighting_stance\nroundhouse_kick",
    "kendo": "overhead_two_hand_strike", "kendo strike": "overhead_two_hand_strike", "sword strike": "overhead_two_hand_strike",
    "axe throw": "stance(depth=0.2) + two_hand_overhead_throw", "muscle up": "muscle_up", "toes to bar": "toes_to_bar(times=2)",
    "handstand push up": "handstand_push_up(times=2)", "wall ball": "wall_ball\nwall_ball", "wall balls": "wall_ball\nwall_ball",
    "tire flip": "tire_flip", "atlas stone": "stone_lift", "stone lift": "stone_lift", "farmers carry": "walk(times=3) + arms_hang",
    "farmer carry": "walk(times=3) + arms_hang", "yoke carry": "walk(times=3) + front_rack", "front double biceps": "stand + front_double_biceps(hold=2)",
    "double biceps": "stand + front_double_biceps(hold=2)", "lat spread": "stand + lat_spread(hold=2)", "most muscular": "stance(depth=0.2) + most_muscular(hold=2)",
    "side chest": "stand + side_chest(hold=2)", "bodybuilding poses": "stand + front_double_biceps(hold=1)\nstand + lat_spread(hold=1)\nstand + side_chest(hold=1)\nstance(depth=0.2) + most_muscular(hold=1)",
    "posing": "stand + front_double_biceps(hold=1)\nstand + lat_spread(hold=1)", "powerlifting squat": "back_squat",
    "powerlifting bench": "bench_press(times=1)", "powerlifting deadlift": "deadlift",
}


# =============================================================================
# 28. NON-OLYMPIC TEAM / PRECISION / WATER / OTHER SPORTS
# =============================================================================
@motion("drop_punt", "Drop punt (Australian rules, Gaelic): run in holding the ball out in front with both hands, drop "
        "it onto the right foot and kick through with a straight leg and high follow-through.", "action", FULL, ["neck"])
def _drop_punt():
    hold = both(0.05, -0.28, 0.42, "down")
    legs_a = {kk: v for kk, v in RUN_A.items() if kk.endswith("leg")}
    return [k(0.0, **legs_a, **hold, spine=S(10)),
            k(0.35, right_leg=Lg(25, 180, 8, 70), left_leg=leg_at(0.12, 0.14, 0.06, 0, 10, "left"), right_arm=A(45, 60, 0, 20), left_arm=A(55, 70, 0, 20)),
            k(0.55, right_leg=Lg(90, -4, 10, 6), spine=S(-8), right_arm=A(35, 160, 0, 20), left_arm=A(80, 70, 0, 15)),
            k(1.0, right_leg=leg_at(0.30, 0.12, 0.05, 0, 10, "right"), left_leg=Lg(12, 180, 8, 15), spine=S(6)),
            k(1.4, **stance_legs("normal", 0.1), right_arm=HANG, left_arm=HANG)]


@motion("handball_pass", "Handball pass (Australian rules): hold the ball on the flat left palm and punch it away with "
        "the right fist.", "action", ARMS + ["spine"], ["pelvis"])
def _hb_pass():
    return [k(0.0, left_arm=arm_at(0.05, -0.30, 0.32, "down", "left"), right_arm=arm_at(0.15, -0.20, 0.15, "down", "right"), spine=S(15, 20)),
            k(0.25, right_arm=arm_at(0.10, -0.10, 0.10, "down", "right")),
            k(0.4, right_arm=arm_at(0.02, -0.28, 0.50, "down", "right"), spine=S(15, -10)), k(0.8, hold=True)]


@motion("high_mark", "High mark / spectacular catch: jump with the knee up into an opponent's back, both arms reaching "
        "up high to catch the ball above the head.", "action", LEGS + ARMS + ["body", "spine"], ["pelvis"])
def _high_mark():
    pts, T = _flight(0.4, 0.45)
    keys = [k(0.0, **stance_legs("normal", 0.3), body=B(), right_arm=A(30, 175, 10, 20), left_arm=A(30, 175, 10, 20), spine=S(10)),
            k(0.3, **stance_legs("normal", 0.8), spine=S(25)),
            k(0.4, body=B(air=1.0), right_leg=Lg(90, 0, 8, 100), left_leg=Lg(5, 0, 8, 5), right_arm=A(165, 15, 0, 15), left_arm=A(165, 15, 0, 15), spine=S(0))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), **stance_legs("normal", 0.1), **both(0.05, -0.15, 0.30, "out")),
             k(tl + 0.04, body=B(air=0.0)), k(tl + 0.4, **stance_legs("normal", 0.5), spine=S(15)), k(tl + 0.8, hold=True)]
    return keys


@motion("solo_toe_tap", "Running while bouncing / toe-tapping the ball: run with the ball held out, drop it onto the "
        "foot and kick it back up to the hands (Gaelic football solo).", "cycle", FULL, ["neck"], period=0.8)
def _solo():
    hold = both(0.05, -0.30, 0.40, "down")
    return [k(0.0, right_leg=Lg(45, 0, 6, 60), left_leg=Lg(25, 180, 6, 20), **hold, spine=S(10)),
            k(0.3, right_leg=Lg(35, 0, 6, 5), **both(0.05, -0.55, 0.42, "out")),
            k(0.55, left_leg=Lg(45, 0, 6, 60), right_leg=Lg(25, 180, 6, 20), **hold)]


@motion("hurley_strike", "One/two-hand stick strike from the hand (hurling, field games): toss the ball up and swing "
        "the stick from the right shoulder down and through in a level arc, hip turning.", "action", ARMS + ["spine"], ["pelvis", "neck"])
def _hurley():
    return grip_keys([(0.0, 0.20, -0.30, 0.25, "down"), (0.35, 0.30, 0.25, 0.10, "out"), (0.6, 0.05, -0.20, 0.48, "down"),
                      (0.8, -0.28, 0.10, 0.35, "out"), (1.2, -0.28, 0.10, 0.35, "out")]) + \
        [k(0.0, spine=S(10, 30), pelvis=P(4, 20)), k(0.35, spine=S(8, 50)), k(0.6, spine=S(12, 0), pelvis=P(4, -15)),
         k(0.8, spine=S(8, -50), pelvis=P(4, -35)), k(1.2, hold=True)]


@motion("netball_shot", "Netball-style two-hand set shot: feet still, ball balanced high on the right hand above the "
        "head with the left hand on the side, knees bend and the arms extend straight up to release.", "action",
        FULL, ["neck"])
def _netball():
    hold = {"right_arm": A(165, 10, 0, 60), "left_arm": A(150, 40, 0, 70)}
    return [k(0.0, **stance_legs("normal", 0.1), spine=S(0), **hold, neck=N(-25)), k(0.4, **stance_legs("normal", 0.5)),
            k(0.8, **stance_legs("normal", 0.05), right_arm=A(172, 10, 0, 5), left_arm=A(165, 35, 0, 10)), k(1.2, hold=True)]


@motion("pivot_footwork", "Landing-foot pivot (netball / basketball): land on one foot, keep it planted and step the "
        "other foot around to face a new direction, ball held at the chest.", "action", LEGS + ["body"], ARMS + ["spine"])
def _pivot_fw():
    hold = grip2(0.0, -0.18, 0.28, "down")
    return [k(0.0, **stance_legs("normal", 0.4), body=B(turn=0), **hold, spine=S(10)),
            k(0.4, right_leg=Lg(25, 120, 20, 50), body=B(turn=-60)), k(0.8, **stance_legs("normal", 0.4), body=B(turn=-120)), k(1.1, hold=True)]


@motion("roof_kick", "Overhead roof / scissor kick spike (sepak takraw): jump, swing the left leg up then whip the "
        "right leg up and over above head height to strike down, body tilting back, land on the left foot.",
        "action", ["body"] + FULL, ["neck"])
def _takraw():
    return [k(0.0, **stance_legs("normal", 0.3), body=B(), spine=S(5), right_arm=A(40, 80, 0, 20), left_arm=A(40, 80, 0, 20)),
            k(0.3, left_leg=Lg(70, 10, 8, 40), body=B(air=1.0, root=0.2, roll=15), spine=S(-10)),
            k(0.55, right_leg=Lg(160, 20, 8, 10), left_leg=Lg(20, 0, 8, 30), body=B(air=1.0, root=0.4, pitch=-35, roll=25),
              right_arm=A(90, 90, 0, 10), left_arm=A(90, 90, 0, 10)),
            k(0.8, right_leg=Lg(60, 0, 8, 30), body=B(air=1.0, root=0.1, pitch=-10, roll=10)),
            k(0.9, body=B(air=0.0, pitch=0, roll=0), **stance_legs("normal", 0.5)), k(1.3, hold=True)]


@motion("raid_touch", "Raiding lunge-and-touch (kabaddi, tag): low crouch, lunge far out to one side reaching the hand "
        "out to touch, then spring back.", "action", FULL, ["neck"])
def _raid():
    base = {**stance_legs("wide", 0.7), "spine": S(30), "pelvis": P(10), **both(0.25, -0.35, 0.35, "down")}
    return [k(0.0, **base), k(0.35, right_leg=leg_at(0.10, 0.62, 0.35, 0, 40, "right"), left_leg=leg_at(0.0, 0.15, 0.25, 0, 10, "left"),
                                spine=S(25, 0, 15), right_arm=A(85, 70, 0, 3)), k(0.55, hold=True), k(0.9, **base)]


@motion("dodge_ball_throw", "Hard sidearm / overhand ball throw at a target (dodgeball): step and whip the arm through "
        "fast.", "action", FULL, ["neck"])
def _dodge_throw():
    return [k(0.0, **stance_legs("normal", 0.3), spine=S(8), right_arm=A(30, 20, -20, 60), left_arm=A(30, 20, -20, 60)),
            k(0.35, right_arm=A(85, 150, 80, 95), left_arm=A(80, -10, 0, 20), spine=S(5, 55)),
            k(0.55, left_leg=leg_at(0.35, 0.14, 0.18, 0, 10, "left"), right_leg=Lg(25, 180, 15, 25), right_arm=A(95, 30, 60, 40), spine=S(15, -10)),
            k(0.75, right_arm=A(50, -40, 0, 20), spine=S(25, -35)), k(1.2, hold=True)]


@motion("dodge", "Dodge: a quick hop or lean to the side, ducking the head and pulling the arms in, to avoid an "
        "object.", "action", LEGS + ["spine", "body"], ARMS)
def _dodge():
    return [k(0.0, **stance_legs("wide", 0.5), body=B(), spine=S(15), right_arm=READY_R, left_arm=READY_R),
            k(0.2, right_leg=leg_at(0.0, 0.55, 0.35, 0, 30, "right"), left_leg=Lg(25, 60, 8, 30), spine=S(30, 0, 25),
              body=B(air=1.0, root=0.05), right_arm=A(30, 30, -20, 110), left_arm=A(30, 30, -20, 110)),
            k(0.35, body=B(air=0.0)), k(0.8, **stance_legs("wide", 0.5), spine=S(15))]


@motion("tug_of_war_pull", "Tug of war pull: leaning far back, heels dug in with a wide staggered stance, both hands "
        "gripping a rope in front at waist height, walking backward step by step.", "cycle", ["body"] + FULL, ["neck"], period=1.2)
def _tug():
    grip = grip2(0.0, -0.32, 0.45, "out")
    a = {"right_leg": leg_at(-0.25, 0.14, 0.25, 0, 20, "right"), "left_leg": leg_at(0.25, 0.14, 0.25, 0, 10, "left")}
    b = {"right_leg": leg_at(-0.10, 0.14, 0.25, 0, 20, "right"), "left_leg": leg_at(0.35, 0.14, 0.25, 0, 10, "left")}
    return [k(0.0, **a, body=B(pitch=-25), spine=S(10), **grip), k(0.6, **b, spine=S(15))]


@motion("flag_pull", "Flag pull: chase down, close the gap low and reach the right hand down to the hip of a ball "
        "carrier to snatch a flag.", "action", FULL, ["neck"])
def _flag_pull():
    legs_a = {kk: v for kk, v in RUN_A.items() if kk.endswith("leg")}
    return [k(0.0, **legs_a, spine=S(15), right_arm=A(45, 175, 10, 70), left_arm=A(65, 6, -15, 90)),
            k(0.35, **stance_legs("wide", 0.7), spine=S(35), right_arm=A(70, 30, 0, 10), left_arm=A(40, 60, 0, 30)),
            k(0.55, right_arm=A(40, 150, 0, 60)), k(0.9, hold=True)]


@motion("play_the_ball", "Play-the-ball (rugby league): get up from the ground, place the ball on the floor in front "
        "and roll it back under the body with the sole of the foot.", "action", FULL, ["neck"])
def _ptb():
    return [k(0.0, **stance_legs("normal", 0.7), spine=S(55), right_arm=A(65, 5, 0, 10), left_arm=A(65, 5, 0, 10)),
            k(0.4, right_leg=Lg(25, 0, 8, 40), left_leg=leg_at(0.0, 0.14, 0.12, 0, 10, "left"), spine=S(45)),
            k(0.7, right_leg=Lg(20, 180, 8, 30), spine=S(30), right_arm=A(30, 30, 0, 40), left_arm=A(30, 30, 0, 40)),
            k(1.0, **stance_legs("normal", 0.3), spine=S(10))]


@motion("dart_throw", "Dart throw: side-on and still, the throwing forearm held vertical with the dart at eye level, "
        "only the forearm swings back and flicks forward, the elbow staying fixed.", "action", ["right_arm"], ["left_arm", "spine"])
def _dart():
    return [k(0.0, right_arm=A(75, 10, -10, 100), left_arm=A(10, 30, 0, 10), spine=S(8, 25)),
            k(0.4, right_arm=A(75, 10, -10, 125)), k(0.55, right_arm=A(80, 10, -10, 30)), k(0.9, hold=True)]


@motion("cue_stroke", "Billiards cue stroke: bent low over the table with the chin over the cue, the left hand forming a "
        "bridge on the table ahead, the right forearm hanging and swinging back and through like a pendulum.",
        "action", FULL, ["neck"])
def _cue():
    base = dict(**stance_legs("normal", 0.15, "left", 20), spine=S(75, 20), pelvis=P(15, 20), left_arm=A(80, 0, 0, 10), neck=N(-30))
    return [k(0.0, **base, right_arm=A(40, 170, 0, 80)), k(0.5, right_arm=A(45, 170, 0, 115)), k(0.75, right_arm=A(35, 170, 0, 40)),
            k(1.2, hold=True)]


@motion("underhand_toss", "Underhand toss / pitch (bocce, cornhole, horseshoes, bowling a ball): step forward with the "
        "left foot, bend the knees and swing the straight right arm back and then forward to release at waist height.",
        "action", FULL, ["neck"])
def _toss():
    return [k(0.0, **stance_legs("normal", 0.15), spine=S(10), right_arm=arm_at(0.12, -0.35, 0.28, "down", "right"), left_arm=HANG),
            k(0.5, right_arm=A(50, 175, 0, 5), spine=S(25), **stance_legs("normal", 0.4)),
            k(0.85, left_leg=leg_at(0.35, 0.14, 0.25, 0, 10, "left"), right_leg=Lg(25, 180, 8, 30), right_arm=A(60, 5, 0, 5),
              left_arm=A(30, 60, 0, 20), spine=S(25)),
            k(1.1, right_arm=A(95, 5, 0, 10), spine=S(15)), k(1.5, hold=True)]


@motion("croquet_swing", "Croquet / mallet stroke: standing over the ball with the feet apart, both hands on a vertical "
        "mallet handle, swing it back between the legs and forward like a pendulum.", "action", ARMS + ["spine"], LEGS)
def _croquet():
    return grip_keys([(0.0, 0.0, -0.45, 0.38, "down"), (0.5, 0.0, -0.52, 0.24, "down"), (0.8, 0.0, -0.40, 0.50, "out"),
                      (1.2, 0.0, -0.40, 0.48, "out")]) + [k(0.0, spine=S(30)), k(0.5, spine=S(35)), k(0.8, spine=S(22)), k(1.2, hold=True)]


@motion("single_blade_paddle", "Single-blade paddling (canoe, dragon boat, stand-up paddle): kneeling or seated, the top "
        "hand high on the paddle and the bottom hand low on the right side, reach forward, pull back along the side, "
        "then recover.", "cycle", ARMS + ["spine"], LEGS + ["body", "pelvis"], period=1.4)
def _canoe():
    return [k(0.0, right_arm=A(70, 20, 0, 10), left_arm=A(130, 10, 0, 60), spine=S(30, -20)),
            k(0.7, right_arm=A(35, 140, 0, 10), left_arm=A(100, 10, 0, 90), spine=S(10, 10)),
            k(1.0, right_arm=A(50, 60, 0, 40), left_arm=A(110, 10, 0, 80), spine=S(20))]


@motion("hiking_out", "Hiking out (sailing): sitting on the edge with the legs hooked under a strap, the body leaning "
        "far back out over the water, arms holding a line in front.", "pose", ["body"] + FULL, ["neck"])
def _hiking():
    return [k(0.0, body=B(pitch=-60, air=1.0, root=0.0), right_leg=Lg(75, 0, 4, 80), left_leg=Lg(75, 0, 4, 80), spine=S(5),
              **both(0.10, -0.20, 0.40, "down"), neck=N(30))]


@motion("windsurf_stance", "Windsurfing / kitesurfing stance: sideways on the board, legs bent, leaning back against "
        "the pull, both arms out in front holding the boom / bar at chest height.", "pose", ["body"] + FULL, ["neck"])
def _windsurf():
    return [k(0.0, body=B(pitch=-15), right_leg=leg_at(-0.25, 0.10, 0.25, 0, 60, "right"), left_leg=leg_at(0.25, 0.10, 0.25, 0, 30, "left"),
              spine=S(0, -50), pelvis=P(0, -45), **both(0.15, -0.10, 0.45, "out"), neck=N(0, 40))]


@motion("water_ski_stance", "Water-ski / wakeboard stance: knees bent, sitting back, arms straight out in front holding "
        "the tow handle at the hips, leaning back against the pull.", "pose", ["body"] + FULL, ["neck"])
def _waterski():
    return [k(0.0, body=B(pitch=-15), **stance_legs("narrow", 0.6), spine=S(15), **grip2(0.0, -0.40, 0.48, "out"))]


@motion("eggbeater_arms_up", "Synchronized swimming lift / boost: upright in the water, the legs eggbeater beneath, the "
        "trunk rising high out of the water with both arms reaching straight up.", "action", ["body"] + FULL, ["neck"])
def _sync():
    legs = {"right_leg": Lg(55, 40, 30, 100), "left_leg": Lg(40, 20, 30, 70)}
    return [k(0.0, body=B(air=1.0, root=-0.6), **legs, right_arm=A(45, 60, 40, 30), left_arm=A(45, 60, 40, 30), spine=S(5)),
            k(0.6, body=B(air=1.0, root=-0.2), right_leg=Lg(20, 0, 4, 5), left_leg=Lg(20, 0, 4, 5), right_arm=A(170, 30, 0, 3),
              left_arm=A(170, 30, 0, 3)), k(1.2, hold=True), k(1.8, body=B(air=1.0, root=-0.6), **legs, right_arm=A(45, 60, 40, 30),
                                                                                                     left_arm=A(45, 60, 40, 30))]


@motion("rising_trot", "Rising trot / posting (horse riding): seated astride, rise up out of the saddle and sit back "
        "down in rhythm, hands low and forward holding the reins.", "cycle", ["body"] + FULL, ["neck"], period=0.8)
def _posting():
    legs_sit = {"right_leg": Lg(45, 40, 20, 80), "left_leg": Lg(45, 40, 20, 80)}
    legs_up = {"right_leg": Lg(30, 40, 20, 45), "left_leg": Lg(30, 40, 20, 45)}
    hands = both(0.12, -0.38, 0.32, "down")
    return [k(0.0, body=B(air=1.0, root=-0.15), **legs_sit, spine=S(5), **hands), k(0.4, body=B(air=1.0, root=-0.02), **legs_up, spine=S(15))]


@motion("jockey_crouch", "Jockey / two-point riding crouch: standing in the stirrups with the knees bent high, the "
        "trunk low and flat forward, hands low on the neck pushing with the stride.", "cycle", ["body"] + FULL, ["neck"], period=0.6)
def _jockey():
    legs = {"right_leg": Lg(70, 30, 20, 110), "left_leg": Lg(70, 30, 20, 110)}
    return [k(0.0, body=B(air=1.0, root=-0.05), **legs, spine=S(70), **both(0.10, -0.20, 0.50, "out"), neck=N(-40)),
            k(0.3, spine=S(65), **both(0.10, -0.25, 0.42, "out"))]


@motion("driving_posture", "Seated driving posture (motorsport, karting): reclined seat, legs forward on the pedals, "
        "both hands on a wheel at chest height, eyes forward.", "pose", ["body"] + FULL, ["neck"])
def _driving():
    return [k(0.0, body=B(pitch=-30, air=1.0, root=-0.35), right_leg=Lg(70, 0, 8, 40), left_leg=Lg(70, 5, 8, 50), spine=S(5),
              right_arm=arm_at(0.20, -0.05, 0.40, "down", "right"), left_arm=arm_at(0.20, 0.05, 0.38, "down", "left"), neck=N(15))]


@motion("motorbike_lean", "Motorbike cornering: crouched over a seat with knees gripping, the body hanging off to the "
        "inside of the turn with the inside knee out, both hands forward on the bars.", "pose", ["body"] + FULL, ["neck"])
def _motorbike():
    return [k(0.0, body=B(pitch=30, roll=-30, air=1.0, root=-0.2), right_leg=Lg(85, 30, 20, 120), left_leg=Lg(75, 60, 30, 120),
              spine=S(30), **both(0.18, -0.25, 0.45, "out"), neck=N(-20))]


@motion("dance_hold", "Closed ballroom dance hold: upright posture, the left arm raised out to the side with the hand at "
        "eye level, the right arm curved forward at shoulder height as if around a partner.", "pose", ARMS + ["spine"], ["neck"])
def _dance_hold():
    return [k(0.0, left_arm=A(95, 80, 90, 90), right_arm=A(85, 30, 0, 70), spine=S(-3), neck=N(-5, 30))]


@motion("waltz_box_step", "Waltz box step: forward step, side step, close; back step, side step, close - in a smooth "
        "rise and fall rhythm.", "cycle", LEGS + ["body"], ARMS + ["spine"], period=2.4)
def _waltz():
    f = {"right_leg": leg_at(0.25, 0.10, 0.10, 0, 10, "right"), "left_leg": leg_at(0.0, 0.10, 0.10, 0, 10, "left")}
    sd = {"left_leg": leg_at(0.0, 0.32, 0.03, 0, 15, "left"), "right_leg": leg_at(0.0, 0.10, 0.03, 0, 10, "right")}
    cl = stance_legs("narrow", 0.05)
    b = {"left_leg": leg_at(-0.25, 0.10, 0.10, 0, 10, "left"), "right_leg": leg_at(0.0, 0.10, 0.10, 0, 10, "right")}
    sr = {"right_leg": leg_at(0.0, 0.32, 0.03, 0, 15, "right"), "left_leg": leg_at(0.0, 0.10, 0.03, 0, 10, "left")}
    return [k(0.0, **f, body=B(root=-0.02)), k(0.4, **sd, body=B(root=0.03)), k(0.8, **cl, body=B(root=0.0)),
            k(1.2, **b, body=B(root=-0.02)), k(1.6, **sr, body=B(root=0.03)), k(2.0, **cl, body=B(root=0.0))]


@motion("salsa_basic", "Salsa / Latin basic step: step forward and back in rhythm with soft knees and hip motion, "
        "arms bent up in front.", "cycle", LEGS + ["pelvis"], ARMS + ["spine"], period=1.6)
def _salsa():
    return [k(0.0, right_leg=leg_at(0.20, 0.10, 0.08, 0, 15, "right"), left_leg=leg_at(0.0, 0.10, 0.08, 0, 10, "left"), pelvis=P(0, -10, 6),
              right_arm=A(30, 40, -20, 90), left_arm=A(30, 40, -20, 90)),
            k(0.4, **stance_legs("narrow", 0.15), pelvis=P(0, 0, -6)),
            k(0.8, left_leg=leg_at(-0.20, 0.10, 0.08, 0, 15, "left"), right_leg=leg_at(0.0, 0.10, 0.08, 0, 10, "right"), pelvis=P(0, 10, 6)),
            k(1.2, **stance_legs("narrow", 0.15), pelvis=P(0, 0, -6))]


@motion("precision_jump_landing", "Precision jump (parkour): two-foot take-off with a big arm swing, fly forward and "
        "land softly on the balls of the feet in a deep crouch, arms forward for balance.", "action", LEGS + ["body"], ARMS + ["spine", "pelvis"])
def _precision():
    keys = _broad_jump.__wrapped__() if hasattr(_broad_jump, "__wrapped__") else _broad_jump()
    return list(keys)


@motion("vault_over", "Speed / lazy vault (parkour, obstacle): run at an obstacle, place one hand on it and swing both "
        "legs sideways over it, landing running.", "action", ["body"] + FULL, ["neck"])
def _vault_over():
    legs_a = {kk: v for kk, v in RUN_A.items() if kk.endswith("leg")}
    return [k(0.0, **legs_a, body=B(), spine=S(10), right_arm=A(45, 175, 10, 70), left_arm=A(65, 6, -15, 90)),
            k(0.35, body=B(air=1.0, root=0.3, roll=25), left_arm=A(40, 60, 0, 5), right_arm=A(110, 60, 0, 20),
              right_leg=Lg(85, 60, 10, 20), left_leg=Lg(70, 50, 10, 40), spine=S(5, 0, -20)),
            k(0.65, body=B(air=1.0, root=0.1, roll=10), right_leg=Lg(40, 0, 8, 30), left_leg=Lg(20, 180, 8, 40)),
            k(0.8, body=B(air=0.0, roll=0), **RUN_B), k(1.1, **RUN_A)]


@motion("wall_run_climb", "Wall climb-up (parkour, obstacle course): run up a wall with one step, grab the top with both "
        "hands, pull up and swing a leg over onto the top.", "action", ["body"] + FULL, ["neck"])
def _wall_climb():
    return [k(0.0, **RUN_A, body=B(), spine=S(10)),
            k(0.35, body=B(air=1.0, root=0.3), right_leg=Lg(80, 0, 8, 100), left_leg=Lg(5, 0, 8, 10), right_arm=A(170, 15, 0, 10), left_arm=A(170, 15, 0, 10)),
            k(0.7, body=B(air=1.0, root=0.7), right_arm=A(40, 120, 30, 120), left_arm=A(40, 120, 30, 120), spine=S(30), right_leg=Lg(30, 0, 8, 60)),
            k(1.0, body=B(air=1.0, root=0.95), right_leg=Lg(80, 60, 20, 90), right_arm=A(10, 175, 0, 5), left_arm=A(10, 175, 0, 5)),
            k(1.4, body=B(air=1.0, root=1.05), **stance_legs("normal", 0.6), spine=S(20))]


@motion("bowling_stance_approach", "Ten-pin four-step approach: ball held at the chest, push it out on the first step, "
        "let it swing back during the steps, slide on the last step and release low.", "action", FULL, ["neck"])
def _ten_pin():
    hold = grip2(0.08, -0.15, 0.28, "down")
    return [k(0.0, **stance_legs("narrow", 0.1), spine=S(10), **hold),
            k(0.4, right_leg=leg_at(0.15, 0.10, 0.08, 0, 10, "right"), right_arm=A(50, 5, 0, 10), left_arm=A(30, 40, 0, 30)),
            k(0.8, left_leg=leg_at(0.15, 0.10, 0.10, 0, 10, "left"), right_leg=Lg(15, 180, 8, 20), right_arm=A(15, 175, 0, 5)),
            k(1.2, right_leg=leg_at(0.15, 0.10, 0.12, 0, 10, "right"), left_leg=Lg(15, 180, 8, 25), right_arm=A(70, 175, 0, 5), spine=S(20)),
            k(1.6, left_leg=leg_at(0.40, 0.10, 0.40, 0, 10, "left"), right_leg=Lg(45, -150, 10, 10), right_arm=A(25, 10, 0, 5),
              left_arm=A(70, 75, 0, 10), spine=S(40)),
            k(2.0, right_arm=A(110, 5, 0, 15), spine=S(30)), k(2.4, hold=True)]


_POS_ALIASES6 = {
    "australian rules kick": "drop_punt", "afl kick": "drop_punt", "drop punt": "drop_punt", "gaelic football kick": "drop_punt",
    "afl handball": "stance(depth=0.3) + handball_pass", "handball pass": "stance(depth=0.3) + handball_pass", "afl mark": "high_mark",
    "high mark": "high_mark", "spekky": "high_mark", "gaelic solo": "solo_toe_tap(times=3)", "toe tap": "solo_toe_tap(times=3)",
    "hurling": "stance(width=wide, depth=0.4) + hurley_strike", "hurling strike": "stance(width=wide, depth=0.4) + hurley_strike",
    "camogie": "stance(width=wide, depth=0.4) + hurley_strike", "shinty": "stance(width=wide, depth=0.4) + hurley_strike",
    "lacrosse shot": "stride_step + overhand_throw(delay=0.2)", "netball shot": "netball_shot", "netball shooting": "netball_shot",
    "netball pivot": "pivot_footwork", "netball footwork": "pivot_footwork", "netball pass": "stance(depth=0.3) + chest_pass",
    "korfball shot": "netball_shot", "sepak takraw": "roof_kick", "takraw": "roof_kick", "roof kick": "roof_kick",
    "kabaddi": "raid_touch\nraid_touch(side=left)", "kabaddi raid": "raid_touch\nraid_touch(side=left)", "tag": "run(times=2)\nraid_touch",
    "dodgeball throw": "dodge_ball_throw", "dodgeball": "dodge\ndodge_ball_throw", "dodge": "dodge", "tug of war": "tug_of_war_pull(times=3)",
    "flag pull": "flag_pull", "flag football": "run(times=2)\nflag_pull", "rugby league play the ball": "play_the_ball", "play the ball": "play_the_ball",
    "darts": "stand + dart_throw", "dart throw": "stand + dart_throw", "throwing darts": "stand + dart_throw", "billiards": "cue_stroke",
    "pool shot": "cue_stroke", "snooker": "cue_stroke", "bocce": "underhand_toss", "petanque": "underhand_toss", "boules": "underhand_toss",
    "cornhole": "underhand_toss", "horseshoes": "underhand_toss", "lawn bowls": "underhand_toss", "croquet": "stance(width=wide, depth=0.2) + croquet_swing",
    "canoe": "kneel + single_blade_paddle(times=3)", "canoeing": "kneel + single_blade_paddle(times=3)", "dragon boat": "kneel + single_blade_paddle(times=3)",
    "stand up paddle": "stance(depth=0.3) + single_blade_paddle(times=3)", "paddleboarding": "stance(depth=0.3) + single_blade_paddle(times=3)",
    "sailing": "hiking_out(hold=2)", "hiking out": "hiking_out(hold=2)", "windsurfing": "windsurf_stance(hold=2)", "kitesurfing": "windsurf_stance(hold=2)",
    "water skiing": "water_ski_stance(hold=2)", "wakeboarding": "water_ski_stance(hold=2)", "synchronized swimming": "tread_water(times=2)\neggbeater_arms_up",
    "artistic swimming": "tread_water(times=2)\neggbeater_arms_up", "horse riding trot": "rising_trot(times=4)", "posting trot": "rising_trot(times=4)",
    "dressage": "riding_posture(hold=2)", "show jumping": "jockey_crouch(times=3)", "horse racing": "jockey_crouch(times=4)", "jockey": "jockey_crouch(times=4)",
    "car racing": "driving_posture(hold=2)", "driving": "driving_posture(hold=2)", "karting": "driving_posture(hold=2)", "formula 1": "driving_posture(hold=2)",
    "motorcycle racing": "motorbike_lean(hold=2)", "motocross": "board_stance(hold=0.5)\nmotorbike_lean(hold=1.5)",
    "ballroom": "stand + dance_hold(hold=0.5)\nwaltz_box_step + dance_hold", "waltz": "waltz_box_step + dance_hold",
    "dancesport": "waltz_box_step + dance_hold", "dance hold": "stand + dance_hold(hold=2)", "salsa": "salsa_basic(times=2)",
    "latin dance": "salsa_basic(times=2)", "parkour": "run(times=1)\nvault_over\nprecision_jump_landing", "precision jump": "precision_jump_landing",
    "speed vault": "vault_over", "lazy vault": "vault_over", "wall climb": "wall_run_climb", "obstacle course": "run(times=1)\nvault_over\nwall_run_climb",
    "ninja warrior": "run(times=1)\nwall_run_climb", "ten pin bowling": "bowling_stance_approach", "bowling": "bowling_stance_approach",
    "bowling approach": "bowling_stance_approach",
}


# =============================================================================
# 29. REMAINING SKILLS ACROSS SPORTS (batch C)
# =============================================================================
@motion("split_jerk", "Split jerk: bar in the front rack, dip and drive, punch the arms straight overhead while the "
        "feet split front and back, then recover the feet together with the bar locked out.", "action", FULL, ["neck"])
def _jerk():
    rack = both(0.20, 0.04, 0.16, "forward")
    over = {"right_arm": A(168, 15, 0, 3), "left_arm": A(168, 15, 0, 3)}
    return [k(0.0, **stance_legs("normal", 0.05), spine=S(3), **rack), k(0.4, **stance_legs("normal", 0.35)),
            k(0.6, **stance_legs("normal", 0.0), body=B(root=0.04)),
            k(0.8, right_leg=Lg(30, 180, 6, 20), left_leg=leg_at(0.40, 0.14, 0.22, 0, 10, "left"), body=B(root=0.0), **over),
            k(1.2, hold=True), k(1.7, **stance_legs("normal", 0.05), **over), k(2.0, hold=True)]


@motion("snatch", "Snatch: wide grip from the floor, extend the hips and knees explosively, pull high and drop under "
        "the bar catching it overhead in a deep squat, then stand.", "action", FULL + ["body"], ["neck"])
def _snatch():
    return [k(0.0, **stance_legs("normal", 0.6), body=B(), spine=S(55), pelvis=P(16), right_arm=A(55, 40, 0, 3), left_arm=A(55, 40, 0, 3)),
            k(0.55, **stance_legs("normal", 0.3), spine=S(25), right_arm=A(25, 40, 0, 3), left_arm=A(25, 40, 0, 3)),
            k(0.8, right_leg=Lg(0, 0, 8, 2), left_leg=Lg(0, 0, 8, 2), body=B(root=0.06), spine=S(-5), right_arm=A(90, 60, 0, 90), left_arm=A(90, 60, 0, 90)),
            k(1.05, **stance_legs("wide", 1.1), body=B(root=0.0), spine=S(25), pelvis=P(10), right_arm=A(160, 40, 0, 3), left_arm=A(160, 40, 0, 3)),
            k(1.4, hold=True), k(2.2, **stance_legs("wide", 0.05), spine=S(3), pelvis=P())]


@motion("single_leg_takedown", "Single-leg takedown: level change, step in deep and grab one leg with both arms "
        "wrapped around the thigh, lift it and drive forward.", "action", FULL, ["neck"])
def _single_leg():
    ready = {**stance_legs("wide", 0.8, "left", 15), "spine": S(40), "pelvis": P(12)}
    return [k(0.0, **ready, **both(0.18, -0.40, 0.36, "down")),
            k(0.4, left_leg=leg_at(0.45, 0.20, 0.42, 0, 10, "left"), right_leg=Lg(20, 180, 10, 100), spine=S(35, -20),
              **both(0.05, -0.40, 0.45, "out")),
            k(0.75, **stance_legs("wide", 0.6, "left", 15), spine=S(20, -20), **both(0.05, -0.20, 0.40, "out")), k(1.1, hold=True)]


@motion("ground_and_pound", "Ground and pound: kneeling astride on top, posture up and throw short punches straight "
        "down with alternating hands.", "cycle", FULL, ["neck"], period=0.8)
def _gnp():
    legs = {"right_leg": Lg(10, 65, 60, 100), "left_leg": Lg(10, 65, 60, 100)}
    return [k(0.0, **legs, spine=S(25), right_arm=A(90, 10, 0, 100), left_arm=arm_at(0.10, -0.55, 0.40, "down", "left")),
            k(0.2, right_arm=arm_at(0.10, -0.55, 0.40, "down", "right"), left_arm=A(90, 10, 0, 100)),
            k(0.4, right_arm=A(90, 10, 0, 100), left_arm=arm_at(0.10, -0.55, 0.40, "down", "left")),
            k(0.6, right_arm=arm_at(0.10, -0.55, 0.40, "down", "right"), left_arm=A(90, 10, 0, 100))]


@motion("clinch_hold", "Clinch (boxing / Muay Thai): standing chest to chest, both hands clasped behind the "
        "opponent's head at head height, elbows tight in front.", "pose", ARMS, ["neck"])
def _clinch():
    return [k(0.0, **both(0.05, 0.10, 0.38, "down"))]


@motion("low_kick", "Low kick (kickboxing): turn the hips and swing the right shin into the opponent's thigh at knee "
        "height, the right arm swinging down for power, then return to the stance.", "action", LEGS + ["pelvis", "spine", "right_arm"], ["left_arm"])
def _low_kick():
    base = stance_legs("normal", 0.25, "left", 18)
    return [k(0.0, **base, pelvis=P(2, 15), spine=S(6, 10), right_arm=GUARD_R, left_arm=GUARD_L),
            k(0.25, left_leg=leg_at(0.05, 0.10, 0.08, 0, 50, "left"), right_leg=Lg(40, 60, -20, 40), pelvis=P(0, -30)),
            k(0.4, right_leg=Lg(45, 0, -70, 15), pelvis=P(0, -55, -10), spine=S(0, -30, -10), right_arm=A(40, 160, 0, 20)),
            k(0.75, **base, pelvis=P(2, 15), spine=S(6, 10), right_arm=GUARD_R)]


@motion("ginga", "Capoeira ginga: a rocking back-and-forth step, each leg in turn stepping back into a wide lunge "
        "with the opposite arm guarding in front of the face.", "cycle", FULL, ["neck"], period=2.0)
def _ginga():
    mid = {**stance_legs("wide", 0.6), "spine": S(20), "right_arm": A(40, 60, 0, 50), "left_arm": A(40, 60, 0, 50)}
    r = {"right_leg": leg_at(-0.40, 0.25, 0.40, 0, 20, "right"), "left_leg": leg_at(0.10, 0.25, 0.40, 0, 20, "left"),
         "left_arm": A(100, 20, -50, 110), "right_arm": A(30, 120, 0, 30), "spine": S(25, 20)}
    l = {"left_leg": leg_at(-0.40, 0.25, 0.40, 0, 20, "left"), "right_leg": leg_at(0.10, 0.25, 0.40, 0, 20, "right"),
         "right_arm": A(100, 20, -50, 110), "left_arm": A(30, 120, 0, 30), "spine": S(25, -20)}
    return [k(0.0, **mid), k(0.5, **r), k(1.0, **mid), k(1.5, **l)]


@motion("karate_punch_kata", "Kata punch sequence: from a front stance, a lower block then a straight middle punch "
        "with the other fist pulled back to the hip, alternating sides.", "action", ARMS + ["spine"], LEGS)
def _kata():
    hip_r = arm_at(0.28, -0.42, -0.02, "back", "right"); hip_l = arm_at(0.28, -0.42, -0.02, "back", "left")
    return [k(0.0, right_arm=hip_r, left_arm=hip_l, spine=S(3)),
            k(0.35, left_arm=A(40, 20, 0, 5), right_arm=hip_r), k(0.7, right_arm=A(88, -4, 0, 3), left_arm=hip_l),
            k(1.05, left_arm=A(88, -4, 0, 3), right_arm=hip_r), k(1.4, right_arm=A(88, -4, 0, 3), left_arm=hip_l), k(1.8, hold=True)]


@motion("slide_tackle", "Sliding tackle: from a run, drop onto the left hip and slide with the right leg extended "
        "straight along the ground to hook the ball away, arms back for balance.", "action", ["body"] + FULL, ["neck"])
def _slide_tackle():
    return [k(0.0, **RUN_A, body=B(), spine=S(10)),
            k(0.35, body=B(pitch=-30, roll=-25), right_leg=Lg(75, 10, 20, 5), left_leg=Lg(40, 30, 30, 110), spine=S(20),
              right_arm=A(30, 100, 0, 20), left_arm=A(40, 150, 0, 10)),
            k(0.7, body=B(pitch=-45, roll=-30)), k(1.2, hold=True)]


@motion("goalkeeper_throw", "Goalkeeper overarm throw: ball cupped in the right hand, step forward and bowl the straight "
        "arm over the top to distribute the ball long.", "action", FULL, ["neck"])
def _gk_throw():
    return [k(0.0, **stance_legs("normal", 0.2), spine=S(5), right_arm=A(30, 170, 0, 10), left_arm=A(80, 0, 0, 10)),
            k(0.4, right_arm=A(60, 175, 0, 5), spine=S(-5, 40)),
            k(0.7, left_leg=leg_at(0.35, 0.14, 0.18, 0, 10, "left"), right_leg=Lg(25, 180, 15, 25), right_arm=A(170, 30, 0, 5), spine=S(5, 0)),
            k(0.9, right_arm=A(80, -10, 0, 5), spine=S(25, -20)), k(1.3, hold=True)]


@motion("knee_slide", "Knee-slide celebration: run, drop onto both knees and slide, leaning back with both arms spread "
        "wide.", "action", ["body"] + FULL, ["neck"])
def _knee_slide():
    return [k(0.0, **RUN_A, body=B(), spine=S(10)),
            k(0.4, right_leg=Lg(0, 0, 0, 100), left_leg=Lg(0, 0, 0, 100), spine=S(-25), right_arm=A(110, 80, 0, 10), left_arm=A(110, 80, 0, 10),
              neck=N(-30)),
            k(1.2, hold=True)]


@motion("dunk", "Dunk: run in, jump off both feet, carry the ball up in one or two hands and slam it down through a "
        "rim above the head, hanging briefly, land.", "action", LEGS + ARMS + ["body", "spine"], ["pelvis"])
def _dunk():
    pts, T = _flight(0.45, 0.5)
    keys = [k(0.0, **stance_legs("normal", 0.3), body=B(), **grip2(0.05, -0.20, 0.30, "down"), spine=S(10)),
            k(0.35, **stance_legs("normal", 0.9), spine=S(30), right_arm=A(40, 175, 0, 10), left_arm=A(40, 175, 0, 10)),
            k(0.45, body=B(air=1.0), right_leg=Lg(3, 0, 8, 5), left_leg=Lg(3, 0, 8, 5), right_arm=A(170, 10, 0, 30), left_arm=A(165, 15, 0, 30), spine=S(-5))]
    for t, r in pts[1:-1]:
        keys.append(k(t, body=B(air=1.0, root=r)))
    apex = pts[len(pts) // 2][0]
    keys.append(k(apex + 0.05, right_arm=A(120, 10, 0, 50), left_arm=A(110, 15, 0, 50), right_leg=Lg(30, 0, 8, 60), left_leg=Lg(20, 0, 8, 40)))
    tl = pts[-1][0]
    keys += [k(tl, body=B(air=1.0, root=0.0), **stance_legs("normal", 0.1)), k(tl + 0.04, body=B(air=0.0)),
             k(tl + 0.4, **stance_legs("normal", 0.6), spine=S(15), right_arm=A(40, 20, 0, 30), left_arm=A(40, 20, 0, 30)), k(tl + 0.8, hold=True)]
    return keys


@motion("lob_shot", "Lob / high defensive stroke: low open stance, swing the racket upward from low to very high, "
        "lifting the ball up high.", "action", ARMS + ["spine"], ["pelvis"])
def _lob():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(15)),
            k(0.4, right_arm=arm_at(0.45, -0.50, -0.05, "down", "right"), left_arm=A(60, -10, 0, 20), spine=S(20, 40)),
            k(0.75, right_arm=arm_at(0.25, -0.30, 0.45, "down", "right"), spine=S(15, 10)),
            k(1.0, right_arm=A(160, 20, 0, 20), left_arm=A(60, 30, 0, 30), spine=S(0, -15)), k(1.4, hold=True)]


@motion("drop_shot", "Drop shot / touch shot: short soft swing that opens the racket face and stops early in front of "
        "the body.", "action", ARMS + ["spine"], ["pelvis"])
def _drop_shot():
    return [k(0.0, right_arm=READY_R, left_arm=READY_R, spine=S(12)),
            k(0.4, right_arm=arm_at(0.45, -0.20, 0.10, "down", "right"), left_arm=A(60, -10, 0, 20), spine=S(12, 35)),
            k(0.7, right_arm=arm_at(0.30, -0.25, 0.40, "out", "right"), spine=S(14, 5)), k(1.1, hold=True)]


@motion("sweep_shot", "Sweep shot (cricket): drop onto the back knee with the front leg stretched forward, bat swung "
        "horizontally low across in front to the leg side.", "action", FULL, ["neck"])
def _sweep_shot():
    return grip_keys([(0.0, 0.20, -0.30, 0.20, "down"), (0.4, 0.30, 0.05, 0.15, "down"), (0.75, 0.10, -0.52, 0.50, "down"),
                      (1.0, -0.32, -0.38, 0.40, "out"), (1.4, -0.32, -0.38, 0.40, "out")]) + \
        [k(0.0, **stance_legs("normal", 0.35), spine=S(15, 35), pelvis=P(5, 30)),
         k(0.6, left_leg=leg_at(0.45, 0.16, 0.45, 0, 10, "left"), right_leg=Lg(15, 180, 10, 105), spine=S(35, 10)),
         k(1.0, spine=S(30, -30)), k(1.4, hold=True)]


@motion("spin_bowl", "Spin bowling delivery: short approach, side-on gather, the arm comes over high and slower with a "
        "sharp wrist and finger snap, the body pivoting through.", "action", FULL, ["neck"])
def _spin_bowl():
    return [k(0.0, **stance_legs("normal", 0.15), spine=S(6), right_arm=A(40, 20, 0, 60), left_arm=A(40, 20, 0, 60)),
            k(0.4, left_leg=Lg(50, 0, 8, 80), right_leg=leg_at(0.0, 0.14, 0.1, 0, 40, "right"), spine=S(-5, 55),
              left_arm=A(150, 20, 0, 10), right_arm=A(60, 165, 0, 40)),
            k(0.7, left_leg=leg_at(0.30, 0.14, 0.15, 0, 10, "left"), right_leg=Lg(20, 180, 20, 30), right_arm=A(165, 10, 0, 15), spine=S(5, 10)),
            k(0.85, right_arm=A(80, -20, -40, 30), spine=S(20, -25)), k(1.3, hold=True)]


@motion("body_check", "Body check / shoulder charge: low and wide, drive the shoulder into an opponent with the arms "
        "tucked and the legs pushing.", "action", FULL, ["neck"])
def _body_check():
    return [k(0.0, **stance_legs("wide", 0.55), spine=S(25), **both(0.18, -0.35, 0.30, "down")),
            k(0.35, right_leg=leg_at(0.30, 0.20, 0.25, 0, 20, "right"), left_leg=Lg(30, 180, 10, 25), spine=S(30, 35, -15),
              right_arm=A(30, 30, -40, 120), left_arm=A(30, 30, -40, 120)), k(0.7, hold=True)]


@motion("faceoff", "Faceoff / bully crouch: very low crouch with the stick held near the ground in front with both "
        "hands, eyes on the drop point.", "pose", FULL, ["neck"])
def _faceoff():
    return [k(0.0, **stance_legs("wide", 1.0), spine=S(55), pelvis=P(15), **grip2(0.10, -0.62, 0.30, "down"), neck=N(-20))]


@motion("goalie_stance", "Goalie stance with pads (hockey, lacrosse): knees bent and together, hips back, the glove "
        "hand up beside the body and the blocker / stick hand forward.", "pose", FULL, ["neck"])
def _goalie_stance():
    return [k(0.0, right_leg=leg_at(0.05, 0.20, 0.35, 0, 25, "right"), left_leg=leg_at(0.05, 0.20, 0.35, 0, 25, "left"), spine=S(30),
              pelvis=P(10), left_arm=A(55, 60, 0, 50), right_arm=A(45, 15, 0, 40))]


@motion("push_pass", "Push pass (field hockey, floorball): stick on the ground with both hands low, push the ball "
        "forward along the ground without a backswing, following through toward the target.", "action", ARMS + ["spine"], ["pelvis"])
def _push_pass():
    return grip_keys([(0.0, 0.25, -0.55, 0.30, "down"), (0.4, 0.15, -0.55, 0.45, "down"), (0.6, -0.05, -0.45, 0.52, "out"),
                      (1.0, -0.05, -0.45, 0.52, "out")]) + [k(0.0, spine=S(40, 20)), k(0.6, spine=S(40, -10)), k(1.0, hold=True)]


@motion("reverse_stick", "Reverse-stick strike: stick turned over on the left side of the body, swung from left to "
        "right with both hands low.", "action", ARMS + ["spine"], ["pelvis"])
def _reverse_stick():
    return grip_keys([(0.0, -0.20, -0.45, 0.38, "down"), (0.35, -0.32, -0.30, 0.32, "out"), (0.6, 0.0, -0.52, 0.46, "down"),
                      (0.8, 0.25, -0.35, 0.42, "down"), (1.2, 0.25, -0.35, 0.42, "down")]) + \
        [k(0.0, spine=S(35, -20)), k(0.35, spine=S(35, -45)), k(0.6, spine=S(38, 0)), k(0.8, spine=S(35, 30)), k(1.2, hold=True)]


@motion("scoop_ground_ball", "Ground-ball scoop with a stick (lacrosse): bend low with both hands on the stick, scoop "
        "through the ball along the ground and bring the stick up to the chest while running.", "action", FULL, ["neck"])
def _gb():
    return [kk(0.0, RUN_A, grip2(0.15, -0.35, 0.25, "down"), spine=S(15)),
            k(0.35, **stance_legs("wide", 0.8), spine=S(55), **grip2(0.10, -0.60, 0.40, "down")),
            k(0.7, **stance_legs("wide", 0.4), spine=S(20), **grip2(0.15, -0.05, 0.20, "down")), k(1.0, hold=True)]


@motion("pilates_hundred", "Pilates hundred: lying on the back with the head and shoulders curled up, legs straight "
        "and raised, arms long beside the body pumping up and down quickly.", "cycle", ["body"] + FULL, ["neck"], period=0.4)
def _hundred():
    return [k(0.0, body=B(-90), spine=S(25), right_leg=Lg(45, 0, 0, 2), left_leg=Lg(45, 0, 0, 2), right_arm=A(30, 5, 0, 3),
              left_arm=A(30, 5, 0, 3), neck=N(25)),
            k(0.2, right_arm=A(20, 5, 0, 3), left_arm=A(20, 5, 0, 3))]


@motion("roll_up", "Pilates roll-up: lying flat with the arms overhead, peel up one vertebra at a time reaching over "
        "the legs to the toes, then roll back down.", "action", ["body"] + FULL, ["neck"])
def _roll_up():
    flat = {"body": B(-90), "spine": S(0), "right_leg": Lg(0, 0, 0, 2), "left_leg": Lg(0, 0, 0, 2), "right_arm": A(170, 8, 0, 3), "left_arm": A(170, 8, 0, 3)}
    fold = _seated()
    return [k(0.0, **flat), k(0.8, body=B(-40), spine=S(40), right_arm=A(90, 5, 0, 3), left_arm=A(90, 5, 0, 3), neck=N(25)),
            k(1.4, **{**fold, "spine": S(60)}, right_arm=A(80, 5, 0, 5), left_arm=A(80, 5, 0, 5)), k(1.7, hold=True), k(2.8, **flat, neck=N())]


@motion("aerobics_step_touch", "Step touch with arm swings (aerobics, cardio dance): step to the side and bring the other "
        "foot in to tap, side to side, the arms swinging up and in.", "cycle", LEGS + ARMS + ["body"], ["spine"], period=1.2)
def _step_touch():
    r = {"right_leg": leg_at(0.0, 0.32, 0.08, 0, 15, "right"), "left_leg": leg_at(0.0, 0.05, 0.08, 0.03, 10, "left"),
         "right_arm": A(120, 70, 0, 20), "left_arm": A(120, 70, 0, 20)}
    l = {"left_leg": leg_at(0.0, 0.32, 0.08, 0, 15, "left"), "right_leg": leg_at(0.0, 0.05, 0.08, 0.03, 10, "right"),
         "right_arm": A(40, 40, -20, 90), "left_arm": A(40, 40, -20, 90)}
    return [k(0.0, **r, body=B(root=0.0)), k(0.3, body=B(root=-0.03)), k(0.6, **l, body=B(root=0.0)), k(0.9, body=B(root=-0.03))]


@motion("ribbon_twirl", "Rhythmic gymnastics ribbon / apparatus: on the balls of the feet, the right arm drawing big "
        "circles and spirals overhead and to the side while the body turns.", "action", ARMS + ["body", "spine"], LEGS)
def _ribbon():
    keys = [k(0.0, right_arm=A(90, 60, 0, 5), left_arm=A(80, 85, 0, 5), body=B(turn=0, root=0.03), spine=S(-5))]
    for i in range(1, 9):
        keys.append(k(0.25 * i, right_arm=A(120 + 40 * math.sin(i), 60 + 50 * math.cos(i), 0, 10)))
    keys += _spin_keys(1, 0.0, 2.0, 4)
    return keys


@motion("back_walkover", "Back walkover: arms overhead, arch back into a bridge with the hands on the floor, kick one "
        "leg over and then the other, standing up on the far side.", "action", ["body"] + FULL, ["neck"])
def _back_walkover():
    up = {"right_arm": A(172, 10, 0, 3), "left_arm": A(172, 10, 0, 3)}
    bridge = _bridge()[0][1]
    return [k(0.0, **stance_legs("narrow", 0.05), body=B(), **up, spine=S(0)),
            k(0.6, body=B(pitch=-60), spine=S(-40), right_leg=Lg(10, 0, 8, 10), left_leg=Lg(70, 0, 8, 5), neck=N(-30)),
            k(1.1, **bridge),
            k(1.6, body=B(pitch=-250), right_leg=Lg(100, 0, 8, 5), left_leg=Lg(20, 0, 8, 5), spine=S(-30)),
            k(2.1, body=B(pitch=-360), **stance_legs("narrow", 0.1), spine=S(5), **up)]


@motion("dyno", "Dynamic climbing move (dyno): crouched on the wall gripping holds, sink low then explode upward with "
        "both arms reaching up for a far hold, catch it and hang.", "action", ["body"] + FULL, ["neck"])
def _dyno():
    low = {"right_leg": Lg(95, 20, 15, 120), "left_leg": Lg(95, 20, 15, 120), "right_arm": A(130, 15, 0, 30), "left_arm": A(130, 15, 0, 30)}
    return [k(0.0, body=B(air=1.0, root=0.0), **low, spine=S(10), neck=N(-30)),
            k(0.4, body=B(air=1.0, root=-0.1), right_arm=A(150, 15, 0, 10), left_arm=A(150, 15, 0, 10)),
            k(0.7, body=B(air=1.0, root=0.5), right_leg=Lg(10, 0, 8, 10), left_leg=Lg(10, 0, 8, 10), right_arm=A(175, 15, 0, 5), left_arm=A(175, 15, 0, 5),
              spine=S(-5)),
            k(1.0, body=B(air=1.0, root=0.4), right_leg=Lg(20, 10, 8, 40), left_leg=Lg(30, 10, 8, 60)), k(1.4, hold=True)]


@motion("bmx_pump", "BMX / mountain bike standing ride: standing on the pedals with the knees and elbows bent, "
        "pumping the body down and up over bumps, hands on the bars.", "cycle", ["body"] + FULL, ["neck"], period=1.0)
def _bmx():
    bars = both(0.22, -0.35, 0.40, "out")
    return [k(0.0, body=B(air=1.0, root=0.0), **stance_legs("normal", 0.35), spine=S(35), **bars, neck=N(-20)),
            k(0.5, **stance_legs("normal", 0.75), spine=S(50), **both(0.22, -0.40, 0.32, "out"))]


@motion("snowboard_carve", "Snowboard carve: sideways stance, knees bent, the body leaning into the turn - toeside "
        "(knees forward, hands toward the snow) then heelside (sitting back).", "cycle", ["body"] + FULL, ["neck"], period=2.0)
def _sb_carve():
    base = {"right_leg": leg_at(-0.25, 0.10, 0.30, 0, 60, "right"), "left_leg": leg_at(0.25, 0.10, 0.30, 0, 30, "left"),
            "spine": S(20, -50), "pelvis": P(5, -45), "right_arm": A(50, 80, 0, 20), "left_arm": A(60, 40, 0, 15)}
    return [k(0.0, **base, body=B(pitch=20)), k(1.0, body=B(pitch=-20), spine=S(0, -50))]


@motion("back_dive", "Back dive: standing backward on the end of the board with the arms overhead, jump up and arch "
        "backward, rotating head-first into the water.", "action", ["body"] + FULL, ["neck"])
def _back_dive():
    up = {"right_arm": A(170, 10, 0, 3), "left_arm": A(170, 10, 0, 3)}
    return [k(0.0, **stance_legs("narrow", 0.05), body=B(), **up, spine=S(0)),
            k(0.3, **stance_legs("narrow", 0.5), spine=S(15), right_arm=A(40, 170, 0, 5), left_arm=A(40, 170, 0, 5)),
            k(0.5, body=B(air=1.0, root=0.4), right_leg=Lg(2, 0, 4, 2), left_leg=Lg(2, 0, 4, 2), **up, spine=S(-10)),
            k(0.8, body=B(pitch=-90, air=1.0, root=0.6), spine=S(-25)), k(1.1, body=B(pitch=-180, air=1.0, root=0.2), spine=S(0)),
            k(1.4, body=B(pitch=-180, air=1.0, root=-0.6))]


@motion("duck_dive", "Duck dive (surfing): lying on the board paddling, push the nose under with straight arms, then "
        "push down with one knee and glide under the wave.", "action", ["body"] + FULL, ["neck"])
def _duck_dive():
    return [k(0.0, body=B(90), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(-10), right_arm=A(30, 60, 30, 110), left_arm=A(30, 60, 30, 110)),
            k(0.4, body=B(80), spine=S(-25), **support_arms(70)), k(0.8, body=B(110), right_leg=Lg(70, 0, 8, 100), spine=S(10)),
            k(1.3, body=B(90), right_leg=Lg(0, 0, 0, 0), spine=S(0), right_arm=A(160, 10, 0, 10), left_arm=A(160, 10, 0, 10))]


@motion("paddle_board_prone", "Prone paddling (surfboard, lifeguard board): lying face down with the chest lifted, "
        "alternating long arm strokes into the water beside the board.", "cycle", ["body"] + FULL, ["neck"], period=1.2)
def _prone_paddle():
    base = {"body": B(88), "right_leg": Lg(0, 0, 0, 0), "left_leg": Lg(0, 0, 0, 0), "spine": S(-20), "neck": N(-25)}
    return [k(0.0, **base, right_arm=A(150, 30, 0, 20), left_arm=A(40, 120, 0, 20)), k(0.6, right_arm=A(40, 120, 0, 20), left_arm=A(150, 30, 0, 20))]


@motion("alley_oop_catch", "Alley-oop: jump high with both arms reaching up to catch a ball in the air and guide it "
        "straight down, landing.", "action", LEGS + ARMS + ["body", "spine"], ["pelvis"])
def _alley():
    return list(_dunk())


_POS_ALIASES7 = {
    "jerk": "split_jerk", "split jerk": "split_jerk", "clean and jerk": "power_clean\nsplit_jerk", "snatch lift": "snatch",
    "olympic lifting": "power_clean\nsplit_jerk", "single leg takedown": "single_leg_takedown", "single leg": "single_leg_takedown",
    "ground and pound": "ground_and_pound(times=3)", "clinch": "fighting_stance + clinch_hold(hold=2)", "muay thai clinch": "fighting_stance + clinch_hold\nknee_strike",
    "low kick": "low_kick", "leg kick": "low_kick", "capoeira": "ginga(times=2)", "ginga": "ginga(times=2)",
    "kata": "front_stance(hold=0.3)\nstance(width=wide, depth=0.5, stagger=left) + karate_punch_kata", "karate kata": "stance(width=wide, depth=0.5, stagger=left) + karate_punch_kata",
    "karate punch": "stance(width=wide, depth=0.5, stagger=left) + karate_punch_kata", "slide tackle": "slide_tackle", "sliding tackle": "slide_tackle",
    "goalkeeper throw": "goalkeeper_throw", "goalkeeper distribution": "goalkeeper_throw", "knee slide": "knee_slide", "goal celebration knee slide": "knee_slide",
    "dunk": "run(times=1)\ndunk", "slam dunk": "run(times=1)\ndunk", "alley oop": "run(times=1)\nalley_oop_catch", "lob": "stance(width=wide, depth=0.5) + lob_shot",
    "tennis lob": "stance(width=wide, depth=0.5) + lob_shot", "drop shot": "stance(width=wide, depth=0.4) + drop_shot", "sweep shot": "sweep_shot",
    "cricket sweep": "sweep_shot", "spin bowling": "spin_bowl", "spin bowl": "spin_bowl", "off spin": "spin_bowl", "leg spin": "spin_bowl",
    "body check": "body_check", "check": "body_check", "shoulder charge": "body_check", "faceoff": "faceoff(hold=1.5)", "face off": "faceoff(hold=1.5)",
    "bully": "faceoff(hold=1.5)", "goalie stance": "goalie_stance(hold=1.5)", "hockey goalie": "goalie_stance(hold=1)\nbutterfly_block(hold=1)",
    "lacrosse goalie": "goalie_stance(hold=1.5)", "push pass": "stance(width=wide, depth=0.5) + push_pass", "field hockey pass": "stance(width=wide, depth=0.5) + push_pass",
    "reverse stick": "stance(width=wide, depth=0.5) + reverse_stick", "ground ball": "scoop_ground_ball", "lacrosse ground ball": "scoop_ground_ball",
    "pilates hundred": "pilates_hundred(times=6)", "the hundred": "pilates_hundred(times=6)", "roll up": "roll_up", "pilates roll up": "roll_up",
    "pilates": "pilates_hundred(times=4)\nroll_up", "aerobics": "aerobics_step_touch(times=3)", "step touch": "aerobics_step_touch(times=3)",
    "zumba": "aerobics_step_touch(times=2)\nsalsa_basic(times=2)", "cardio dance": "aerobics_step_touch(times=3)", "rhythmic gymnastics": "ribbon_twirl",
    "ribbon": "ribbon_twirl", "back walkover": "back_walkover", "walkover": "back_walkover", "dyno": "dyno", "bouldering": "climbing(times=2)\ndyno",
    "bmx": "bmx_pump(times=3)", "mountain biking": "bmx_pump(times=3)", "snowboarding": "snowboard_carve(times=2)", "snowboard carve": "snowboard_carve(times=2)",
    "back dive": "back_dive", "duck dive": "duck_dive", "surf paddle": "paddle_board_prone(times=3)", "paddling out": "paddle_board_prone(times=3)",
}


# =============================================================================
# 30. BATCH D: ADVANCED YOGA, STRENGTH ACCESSORIES, SWIM STROKES, SKATING/SKIING, DEFENSE
# =============================================================================
@motion("crow_pose", "Crow pose (arm balance): squatting low, hands on the floor in front, knees resting on the backs "
        "of the bent upper arms, tip forward until the feet lift off.", "pose", ["body"] + FULL, ["neck"])
def _crow():
    return [k(0.0, **fit_pose("crow", {"body.pitch": 70, "arms.raise": 70, "arms.elbow": 60, "legs.raise": 110, "legs.knee": 140},
                               {"legs": {"dir": 25.0, "twist": 30.0}, "arms": {"dir": 15.0, "twist": 0.0}, "spine": {"lean": 30.0},
                                "neck": {"nod": -30.0}},
                               [("right_hand", "floor", 0, 3), ("right_foot", "y", 0.25, 2), ("right_knee", "z", 0.25, 1)]))]


@motion("headstand", "Headstand: forearms and the top of the head on the floor, hips stacked over the shoulders, legs "
        "straight up.", "pose", ["body"] + FULL, ["neck"])
def _headstand():
    return [k(0.0, body=B(pitch=180), right_arm=A(150, 30, 90, 90), left_arm=A(150, 30, 90, 90), right_leg=Lg(0, 0, 0, 0),
              left_leg=Lg(0, 0, 0, 0), spine=S(0), neck=N(0))]


@motion("shoulder_stand", "Shoulder stand: lying on the upper back with the hips and straight legs raised vertical, "
        "hands supporting the lower back.", "pose", ["body"] + FULL, ["neck"])
def _shoulder_stand():
    return [k(0.0, body=B(pitch=-170), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(0), right_arm=A(80, 170, 30, 110),
              left_arm=A(80, 170, 30, 110), neck=N(60))]


@motion("plough_pose", "Plough pose: from a shoulder stand, lower the straight legs over the head until the toes touch "
        "the floor behind, arms flat along the floor.", "pose", ["body"] + FULL, ["neck"])
def _plough():
    return [k(0.0, body=B(pitch=-150), right_leg=Lg(110, 0, 0, 2), left_leg=Lg(110, 0, 0, 2), spine=S(20), right_arm=A(30, 175, 0, 3),
              left_arm=A(30, 175, 0, 3), neck=N(60))]


@motion("wheel_pose", "Wheel (full backbend): hands and feet on the floor, straight arms, hips and chest pushed high "
        "in a big arch.", "pose", ["body"] + FULL, ["neck"])
def _wheel():
    return [k(0.0, **fit_pose("wheel", {"body.pitch": -110, "spine.lean": -60, "arms.raise": 175, "legs.raise": 30, "legs.knee": 70},
                               {"arms": {"dir": 8.0, "twist": 0.0, "elbow": 2.0}, "legs": {"dir": 0.0, "twist": 8.0}, "neck": {"nod": -35.0}},
                               [("right_hand", "floor", 0, 3), ("right_foot", "floor", 0, 3), ("pelvis", "y", 0.85, 1)]))]


@motion("half_moon", "Half moon pose: balancing on the straight left leg with the left hand down toward the floor, the "
        "body and the straight right leg horizontal, the right arm reaching to the sky.", "pose", FULL, ["neck"])
def _half_moon():
    return [k(0.0, left_leg=Lg(2, 0, 10, 2), right_leg=Lg(90, 90, 0, 2), spine=S(5, 0, -80), pelvis=P(0, 0, -10),
              left_arm=A(10, 85, 0, 3), right_arm=A(175, 85, 0, 3), neck=N(0, -30))]


@motion("eagle_pose", "Eagle pose: knees bent, the right thigh crossed over the left and the foot hooked behind the "
        "calf, the arms wrapped with the elbows stacked in front of the face.", "pose", FULL, ["neck"])
def _eagle():
    return [k(0.0, left_leg=leg_at(0.05, 0.08, 0.20, 0, 5, "left"), right_leg=Lg(45, -40, 0, 70), spine=S(15),
              right_arm=arm_at(-0.05, 0.10, 0.25, "down", "right"), left_arm=arm_at(-0.05, 0.05, 0.22, "down", "left"))]


@motion("dancer_pose", "Dancer pose: balancing on the left leg, the right hand holds the right foot behind and kicks "
        "it up high, the trunk tips forward and the left arm reaches forward.", "pose", FULL, ["neck"])
def _dancer():
    return [k(0.0, left_leg=Lg(2, 0, 10, 3), right_leg=Lg(60, 180, 8, 110), spine=S(40), pelvis=P(15), right_arm=A(70, 175, 0, 10),
              left_arm=A(130, 5, 0, 3), neck=N(-20))]


@motion("extended_side_angle", "Extended side angle: wide stance with the right knee bent over the ankle, the right "
        "forearm resting on the right thigh, the left arm reaching long over the ear on a diagonal.", "pose", FULL, ["neck"])
def _side_angle():
    return [k(0.0, right_leg=leg_at(0.0, 0.50, 0.32, 0, 70, "right"), left_leg=leg_at(0.0, 0.42, 0.0, 0, 10, "left"), spine=S(10, 0, 50),
              pelvis=P(0, 0, 10), right_arm=A(25, 80, 0, 80), left_arm=A(150, 60, 0, 3), neck=N(0, -30))]


@motion("turkish_get_up", "Turkish get-up: lying on the back holding a weight straight up in the right hand, roll to "
        "the left elbow, then hand, lift the hips, sweep the left leg under to a kneel, and stand - the right arm stays "
        "locked overhead the whole time.", "action", ["body"] + FULL, ["neck"])
def _tgu():
    up = A(90, 10, 0, 2)
    return [k(0.0, body=B(-90), right_leg=Lg(45, 10, 8, 90), left_leg=Lg(0, 20, 0, 2), spine=S(0), right_arm=up, left_arm=A(15, 60, 0, 3)),
            k(0.8, body=B(-50, 0, -20), spine=S(20), left_arm=A(30, 150, 0, 60)),
            k(1.6, body=B(-20, 0, -30), spine=S(10), left_arm=A(25, 160, 0, 5), right_arm=A(140, 15, 0, 2)),
            k(2.6, body=B(0), right_leg=Lg(85, 0, 4, 90), left_leg=Lg(0, 0, 0, 90), spine=S(0), left_arm=HANG, right_arm=A(172, 10, 0, 2)),
            k(3.6, **stance_legs("normal", 0.05), right_arm=A(172, 10, 0, 2), left_arm=HANG), k(4.0, hold=True)]


@motion("kb_windmill", "Kettlebell windmill: weight locked out overhead in the right hand, feet turned out, push the "
        "hips right and hinge down to the left so the left hand slides down the left leg toward the floor, eyes on "
        "the weight, then rise.", "action", FULL, ["neck"])
def _kb_windmill():
    return [k(0.0, **stance_legs("wide", 0.05, toe=35), spine=S(0), right_arm=A(172, 15, 0, 2), left_arm=HANG),
            k(1.2, spine=S(30, -20, -55), pelvis=P(10, 0, 15), left_arm=A(10, 60, 0, 3), right_arm=A(172, 50, 0, 2), neck=N(-20, -30)),
            k(1.5, hold=True), k(2.6, spine=S(0), pelvis=P(), left_arm=HANG, right_arm=A(172, 15, 0, 2), neck=N())]


@motion("battle_ropes", "Battle rope waves: athletic half squat, both hands holding rope ends at the hips, arms "
        "whipping up and down alternately and fast.", "cycle", ARMS, LEGS + ["spine"], period=0.5)
def _ropes():
    lo = arm_at(0.22, -0.45, 0.30, "down", "right"); hi = arm_at(0.22, -0.05, 0.40, "down", "right")
    lol = arm_at(0.22, -0.45, 0.30, "down", "left"); hil = arm_at(0.22, -0.05, 0.40, "down", "left")
    return [k(0.0, right_arm=hi, left_arm=lol), k(0.25, right_arm=lo, left_arm=hil)]


@motion("hip_thrust", "Hip thrust: upper back resting against a bench, feet planted with the knees bent, hands on the "
        "hips, drive the hips up until the body is flat from shoulders to knees, lower.", "cycle", ["body"] + FULL, ["neck"], period=2.0)
def _hip_thrust():
    hands = both(0.26, -0.45, 0.10, "out")
    return [k(0.0, body=B(-40, air=1.0, root=-0.35), right_leg=Lg(85, 10, 8, 120), left_leg=Lg(85, 10, 8, 120), spine=S(0), **hands, neck=N(15)),
            k(0.9, body=B(-88, air=1.0, root=-0.15), right_leg=Lg(5, 10, 8, 90), left_leg=Lg(5, 10, 8, 90), neck=N(35)), k(1.1, hold=True)]


@motion("pistol_squat", "Pistol squat: balancing on the left leg, squat all the way down with the right leg held "
        "straight out in front and the arms forward, stand back up.", "action", FULL, ["neck"])
def _pistol():
    return [k(0.0, left_leg=Lg(0, 0, 8, 3), right_leg=Lg(40, 0, 8, 3), spine=S(5), right_arm=A(80, 5, 0, 3), left_arm=A(80, 5, 0, 3)),
            k(1.2, left_leg=leg_at(0.10, 0.12, 0.50, 0, 8, "left"), right_leg=Lg(85, 0, 8, 3), spine=S(35), pelvis=P(12)),
            k(1.5, hold=True), k(2.5, left_leg=Lg(0, 0, 8, 3), right_leg=Lg(40, 0, 8, 3), spine=S(5), pelvis=P())]


@motion("cossack_squat", "Cossack squat: very wide stance, shift down onto the bent right leg with the left leg straight "
        "out to the side and its toes up, chest up and hands in front, then across to the other side.", "cycle", FULL, ["neck"], period=3.0)
def _cossack():
    r = {"right_leg": leg_at(0.05, 0.50, 0.45, 0, 30, "right"), "left_leg": leg_at(0.0, 0.62, 0.0, 0, -10, "left"), "spine": S(25, 0, 10)}
    l = {"left_leg": leg_at(0.05, 0.50, 0.45, 0, 30, "left"), "right_leg": leg_at(0.0, 0.62, 0.0, 0, -10, "right"), "spine": S(25, 0, -10)}
    hands = grip2(0.0, -0.25, 0.35, "down")
    return [k(0.0, **r, **hands, pelvis=P(10)), k(0.7, hold=True), k(1.5, **l), k(2.2, hold=True)]


@motion("dips", "Dips: supported on straight arms between bars, bend the elbows straight back to lower the body until "
        "the shoulders are near the hands, press back up.", "cycle", ["body"] + FULL, ["neck"], period=1.8)
def _dips():
    return [k(0.0, body=B(air=1.0, root=0.25), right_arm=A(5, 175, 0, 2), left_arm=A(5, 175, 0, 2), right_leg=Lg(20, 0, 4, 60),
              left_leg=Lg(20, 0, 4, 60), spine=S(10)),
            k(0.8, body=B(air=1.0, root=0.05), right_arm=A(50, 175, 0, 95), left_arm=A(50, 175, 0, 95), spine=S(25)), k(1.0, hold=True)]


@motion("push_press", "Push press: weight in the front rack, a quick knee dip, then drive with the legs and press the "
        "arms straight overhead, lower back to the shoulders.", "action", FULL, ["neck"])
def _push_press():
    rack = both(0.20, 0.04, 0.16, "forward")
    return [k(0.0, **stance_legs("normal", 0.05), spine=S(3), **rack), k(0.35, **stance_legs("normal", 0.3)),
            k(0.7, **stance_legs("normal", 0.0), right_arm=A(170, 15, 0, 3), left_arm=A(170, 15, 0, 3)), k(1.0, hold=True),
            k(1.6, **rack)]


@motion("upright_row", "Upright row: hands close together on a bar in front of the thighs, pull it straight up the body "
        "to the chest with the elbows leading high, lower.", "cycle", ARMS, ["spine"], period=1.8)
def _upright():
    return grip_keys([(0.0, 0.08, -0.62, 0.15, "out"), (0.8, 0.08, -0.15, 0.18, "up"), (1.0, 0.08, -0.15, 0.18, "up"), (1.8, 0.08, -0.62, 0.15, "out")], step=0.1)


@motion("shrugs", "Shrugs: arms hanging straight holding weights, lift the shoulders up toward the ears and lower.",
        "cycle", ARMS + ["neck"], ["spine"], period=1.4)
def _shrugs():
    return [k(0.0, right_arm=A(4, 85, 0, 3), left_arm=A(4, 85, 0, 3), neck=N()), k(0.6, right_arm=A(2, 85, 0, 3), left_arm=A(2, 85, 0, 3), neck=N(-5)),
            k(0.8, hold=True)]


@motion("chest_fly", "Chest fly: arms out wide to the sides with a soft elbow, sweep them together in a big hug in front "
        "of the chest and open again (standing or lying).", "cycle", ARMS, ["spine"], period=2.0)
def _fly():
    return [k(0.0, right_arm=A(85, 95, 0, 15), left_arm=A(85, 95, 0, 15)), k(0.9, right_arm=A(85, 5, 0, 15), left_arm=A(85, 5, 0, 15)), k(1.1, hold=True)]


@motion("reverse_fly", "Reverse fly: bent over with a flat back, arms hanging, raise the straight arms out to the sides "
        "squeezing the shoulder blades, lower.", "cycle", FULL, ["neck"], period=1.8)
def _rev_fly():
    return [k(0.0, **stance_legs("normal", 0.3), spine=S(55), pelvis=P(15), right_arm=A(55, -5, 0, 10), left_arm=A(55, -5, 0, 10)),
            k(0.8, right_arm=A(60, 95, 0, 10), left_arm=A(60, 95, 0, 10)), k(1.0, hold=True)]


@motion("hammer_curl", "Hammer curl: palms facing in, elbows at the sides, curl the hands up to the shoulders and lower.",
        "cycle", ARMS, ["spine"], period=1.8)
def _hammer_curl():
    return [k(0.0, right_arm=A(5, 20, -30, 8), left_arm=A(5, 20, -30, 8)), k(0.8, right_arm=A(12, 20, -30, 140), left_arm=A(12, 20, -30, 140)), k(1.0, hold=True)]


@motion("skull_crusher", "Lying triceps extension: lying on the back with the upper arms vertical, bend the elbows to "
        "bring the hands toward the forehead, then extend.", "cycle", ["body"] + FULL, ["neck"], period=1.8)
def _skull():
    return [k(0.0, body=B(-90), right_leg=Lg(45, 10, 8, 90), left_leg=Lg(45, 10, 8, 90), spine=S(0), right_arm=A(95, 5, 0, 3), left_arm=A(95, 5, 0, 3)),
            k(0.8, right_arm=A(110, 5, 0, 120), left_arm=A(110, 5, 0, 120)), k(1.0, hold=True)]


@motion("hanging_knee_raise", "Hanging knee raise: hanging from a bar with straight arms, pull both knees up to the "
        "chest and lower slowly.", "cycle", ["body"] + FULL, ["neck"], period=1.8)
def _hkr():
    return [k(0.0, body=B(air=1.0, root=0.25), right_leg=Lg(5, 0, 4, 5), left_leg=Lg(5, 0, 4, 5), spine=S(0), right_arm=A(172, 20, 0, 3),
              left_arm=A(172, 20, 0, 3)),
            k(0.8, right_leg=Lg(105, 0, 4, 110), left_leg=Lg(105, 0, 4, 110), spine=S(15)), k(1.0, hold=True)]


@motion("copenhagen_plank", "Copenhagen plank: side plank on the right forearm with the top (left) leg resting on a "
        "bench and the bottom leg lifted, hips up.", "pose", ["body"] + FULL, ["neck"])
def _copenhagen():
    sp = _side_plank_fit()
    return [k(0.0, **{**sp, "right_leg": Lg(20, 0, 0, 3)}, pelvis=P(), neck=N())]


@motion("nordic_curl", "Nordic hamstring curl: kneeling upright with the ankles held down, lean the straight body "
        "forward slowly from the knees, catch with the hands, push back up.", "action", ["body"] + FULL, ["neck"])
def _nordic():
    kneel = {"right_leg": Lg(0, 0, 0, 90), "left_leg": Lg(0, 0, 0, 90)}
    return [k(0.0, **kneel, body=B(), spine=S(0), **both(0.18, -0.30, 0.25, "down")),
            k(1.5, body=B(pitch=55), right_leg=Lg(0, 0, 0, 35), left_leg=Lg(0, 0, 0, 35)),
            k(1.9, body=B(pitch=75), right_leg=Lg(0, 0, 0, 15), left_leg=Lg(0, 0, 0, 15), **both(0.20, -0.10, 0.40, "down")),
            k(2.8, **kneel, body=B(), spine=S(0))]


@motion("plank_to_push_up", "Plank up-downs: from a forearm plank, press up one arm at a time into a straight-arm "
        "plank, then lower back down one arm at a time.", "cycle", ["body"] + FULL, ["neck"], period=2.4)
def _updown():
    fp = _forearm_plank()
    hp = {"body": B(PLANK_PITCH), **support_arms(PLANK_PITCH)}
    return [kk(0.0, fp, neck=N(-20)), k(0.6, right_arm=hp["right_arm"]), k(1.0, **hp), k(1.6, right_arm=fp["right_arm"]),
            k(2.0, **{**fp})]


@motion("sidestroke", "Sidestroke: lying on the left side in the water, the lower arm reaching forward and pulling while "
        "the upper arm pushes back, with a scissor kick of the legs.", "cycle", ["body"] + FULL, ["neck"], period=1.8)
def _sidestroke():
    body = B(pitch=88, roll=-80, air=1.0)
    return [k(0.0, body=body, left_arm=A(170, 5, 0, 5), right_arm=A(20, 170, 0, 10), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), spine=S(0)),
            k(0.6, left_arm=A(90, 5, 0, 90), right_arm=A(80, 10, 0, 100), right_leg=Lg(45, 0, 0, 90), left_leg=Lg(30, 180, 0, 90)),
            k(1.0, left_arm=A(170, 5, 0, 5), right_arm=A(20, 170, 0, 10), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0))]


@motion("elementary_backstroke", "Elementary backstroke: floating on the back, the hands slide up the sides to the "
        "armpits, extend out to the sides and sweep down to the hips together, with a frog kick.", "cycle", ["body"] + FULL, ["neck"], period=2.0)
def _ebs():
    body = B(pitch=-86, air=1.0)
    return [k(0.0, body=body, right_arm=A(10, 80, 0, 5), left_arm=A(10, 80, 0, 5), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), neck=N(10)),
            k(0.5, right_arm=A(30, 90, 0, 140), left_arm=A(30, 90, 0, 140), right_leg=Lg(35, 40, 40, 110), left_leg=Lg(35, 40, 40, 110)),
            k(0.9, right_arm=A(100, 90, 0, 5), left_arm=A(100, 90, 0, 5), right_leg=Lg(25, 50, 30, 5), left_leg=Lg(25, 50, 30, 5)),
            k(1.4, right_arm=A(10, 80, 0, 5), left_arm=A(10, 80, 0, 5), right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0))]


@motion("dog_paddle", "Dog paddle / beginner swim: body angled in the water with the head up, hands paddling in small "
        "alternating circles in front of the chest, legs kicking.", "cycle", ["body"] + FULL, ["neck"], period=0.8)
def _dog_paddle():
    body = B(pitch=45, air=1.0)
    return [k(0.0, body=body, right_arm=A(90, 5, 0, 60), left_arm=A(60, 5, 0, 90), right_leg=Lg(20, 0, 0, 40), left_leg=Lg(10, 180, 0, 20), neck=N(-45)),
            k(0.4, right_arm=A(60, 5, 0, 90), left_arm=A(90, 5, 0, 60), right_leg=Lg(10, 180, 0, 20), left_leg=Lg(20, 0, 0, 40))]


@motion("survival_float", "Survival back float: lying back in the water with the arms and legs spread wide and relaxed, "
        "face up.", "pose", ["body"] + FULL, ["neck"])
def _float():
    return [k(0.0, body=B(pitch=-80, air=1.0), right_arm=A(90, 100, 0, 20), left_arm=A(90, 100, 0, 20), right_leg=Lg(20, 90, 0, 10),
              left_leg=Lg(20, 90, 0, 10), spine=S(0), neck=N(-10))]


@motion("crossover_skating", "Skating crossovers through a curve: the outside (right) leg steps over in front of the "
        "inside leg while the inside leg pushes under, body leaning into the turn.", "cycle", LEGS + ["body", "spine", "pelvis"], ARMS, period=1.0)
def _crossovers():
    a = {"right_leg": leg_at(0.0, -0.05, 0.30, 0.04, 5, "right"), "left_leg": leg_at(0.0, 0.45, 0.30, 0.0, 30, "left")}
    b = {"right_leg": leg_at(0.0, 0.20, 0.30, 0.0, 10, "right"), "left_leg": leg_at(0.0, 0.10, 0.30, 0.03, 10, "left")}
    arms = {"right_arm": A(40, 40, 0, 30), "left_arm": A(40, 120, 0, 30)}
    return [k(0.0, **a, body=B(roll=15), spine=S(40, 20), pelvis=P(10, 10), **arms), k(0.5, **b)]


@motion("backward_skating", "Backward skating: sitting low as if in a chair, the feet carving C-cuts outward and back "
        "in alternately, trunk upright, arms out.", "cycle", LEGS + ["pelvis", "spine"], ARMS, period=1.0)
def _back_skate():
    r = {"right_leg": leg_at(0.10, 0.40, 0.35, 0.02, -10, "right"), "left_leg": leg_at(0.0, 0.12, 0.35, 0.0, 10, "left")}
    l = {"left_leg": leg_at(0.10, 0.40, 0.35, 0.02, -10, "left"), "right_leg": leg_at(0.0, 0.12, 0.35, 0.0, 10, "right")}
    return [k(0.0, **r, spine=S(25), pelvis=P(10), right_arm=A(35, 70, 0, 30), left_arm=A(35, 70, 0, 30)), k(0.5, **l)]


@motion("hockey_stop", "Hockey stop: turn both skates sideways quickly and dig the edges in, knees bent and leaning back "
        "against the slide, arms out.", "action", LEGS + ["body", "spine", "pelvis"], ARMS)
def _hockey_stop():
    return [k(0.0, **stance_legs("normal", 0.4), body=B(turn=0), spine=S(30), right_arm=A(40, 60, 0, 30), left_arm=A(40, 60, 0, 30)),
            k(0.3, body=B(turn=-90), **stance_legs("wide", 0.7), spine=S(15, 30, -15), pelvis=P(5, 0, -10)), k(0.8, hold=True)]


@motion("snowplough", "Snowplough / pizza (beginner skiing): knees bent and pushed in, the ski tips together and tails "
        "apart in a wedge, poles held forward.", "pose", FULL, ["neck"])
def _snowplough():
    return [k(0.0, right_leg=leg_at(0.0, 0.32, 0.25, 0, -25, "right"), left_leg=leg_at(0.0, 0.32, 0.25, 0, -25, "left"), spine=S(20),
              right_arm=A(30, 30, 0, 50), left_arm=A(30, 30, 0, 50))]


@motion("parry", "Boxing parry: the rear (right) hand slaps a jab aside with a short sideways push in front of the face, "
        "returns to the guard.", "action", ["right_arm"], ["left_arm", "spine"])
def _parry():
    return [k(0.0, right_arm=GUARD_R, left_arm=GUARD_L), k(0.15, right_arm=arm_at(-0.05, 0.08, 0.32, "down", "right")),
            k(0.4, right_arm=GUARD_R)]


@motion("roll_under", "Boxing roll / U-dip: bend the knees and roll the head and shoulders under a hook in a U shape, "
        "guard tight, rising on the other side.", "action", LEGS + ["spine"], ["pelvis"])
def _roll_under():
    up_l = stance_legs("normal", 0.3, "left", 20)
    low = stance_legs("normal", 0.8, "left", 20)
    return [k(0.0, **up_l, spine=S(8, 12, 14)), k(0.3, **low, spine=S(30, 12, 0)), k(0.6, **up_l, spine=S(8, 12, -14)), k(0.9, hold=True)]


@motion("take_a_charge", "Taking a charge: set in a square stance, absorb the contact and fall backward onto the "
        "backside, arms forward and chin tucked.", "action", ["body"] + FULL, ["neck"])
def _charge():
    return [k(0.0, **stance_legs("wide", 0.5), body=B(), spine=S(10), **both(0.10, -0.20, 0.30, "down")),
            k(0.3, body=B(pitch=-20), spine=S(15), neck=N(25)),
            k(0.7, body=B(pitch=-55), right_leg=Lg(70, 10, 8, 60), left_leg=Lg(70, 10, 8, 60), right_arm=A(40, 150, 0, 10), left_arm=A(40, 150, 0, 10)),
            k(1.2, hold=True)]


_POS_ALIASES8 = {
    "crow pose": "crow_pose(hold=2)", "crane pose": "crow_pose(hold=2)", "headstand": "headstand(hold=2)", "shoulder stand": "shoulder_stand(hold=2)",
    "plough pose": "plough_pose(hold=2)", "plow pose": "plough_pose(hold=2)", "wheel pose": "wheel_pose(hold=2)", "full backbend": "wheel_pose(hold=2)",
    "half moon": "half_moon(hold=2)", "half moon pose": "half_moon(hold=2)", "eagle pose": "eagle_pose(hold=2)", "dancer pose": "dancer_pose(hold=2)",
    "extended side angle": "extended_side_angle(hold=2)", "side angle pose": "extended_side_angle(hold=2)", "turkish get up": "turkish_get_up",
    "kettlebell windmill": "kb_windmill", "windmill": "kb_windmill", "battle ropes": "stance(width=wide, depth=0.5) + battle_ropes(times=6)",
    "hip thrust": "hip_thrust(times=2)", "hip thrusts": "hip_thrust(times=3)", "pistol squat": "pistol_squat", "cossack squat": "cossack_squat",
    "dips": "dips(times=2)", "tricep dips": "dips(times=2)", "push press": "push_press", "upright row": "stand + upright_row(times=3)",
    "shrugs": "stand + shrugs(times=3)", "chest fly": "stand + chest_fly(times=3)", "flyes": "stand + chest_fly(times=3)",
    "reverse fly": "reverse_fly(times=3)", "rear delt fly": "reverse_fly(times=3)", "hammer curl": "stand + hammer_curl(times=3)",
    "hammer curls": "stand + hammer_curl(times=3)", "skull crushers": "skull_crusher(times=3)", "lying triceps extension": "skull_crusher(times=3)",
    "hanging knee raise": "hanging_knee_raise(times=3)", "hanging leg raise": "hanging_knee_raise(times=3)", "copenhagen plank": "copenhagen_plank(hold=2)",
    "nordic curl": "nordic_curl", "nordic hamstring curl": "nordic_curl", "plank up downs": "plank_to_push_up(times=2)", "up downs": "plank_to_push_up(times=2)",
    "sidestroke": "sidestroke(times=3)", "side stroke": "sidestroke(times=3)", "elementary backstroke": "elementary_backstroke(times=3)",
    "dog paddle": "dog_paddle(times=4)", "doggy paddle": "dog_paddle(times=4)", "back float": "survival_float(hold=3)", "floating": "survival_float(hold=3)",
    "starfish float": "survival_float(hold=3)", "crossovers": "crossover_skating(times=3)", "skating crossovers": "crossover_skating(times=3)",
    "backward skating": "backward_skating(times=3)", "skating backwards": "backward_skating(times=3)", "hockey stop": "skating_stride(times=1)\nhockey_stop",
    "snowplough": "snowplough(hold=2)", "snowplow": "snowplough(hold=2)", "pizza": "snowplough(hold=2)", "parry": "fighting_stance + guard + parry",
    "boxing parry": "fighting_stance + guard + parry", "roll under": "roll_under + guard", "u dip": "roll_under + guard", "taking a charge": "take_a_charge",
    "take a charge": "take_a_charge", "draw a charge": "take_a_charge",
}


ALIASES: Dict[str, str] = {
    "childs pose": "childs_pose(hold=2)", "child pose": "childs_pose(hold=2)", "childs pose stretch": "childs_pose(hold=2)",
    "kneeling": "kneel(hold=1)", "kneel": "kneel(hold=1)", "half kneeling": "half_kneel(hold=1)",
    "cat cow": "cat_cow(times=2)", "cat camel": "cat_cow(times=2)", "bird dog": "bird_dog(times=2)", "bird dogs": "bird_dog(times=2)",
    "downward dog": "downward_dog(hold=2)", "down dog": "downward_dog(hold=2)", "cobra": "cobra(hold=2)", "cobra stretch": "cobra(hold=2)",
    "upward dog": "cobra(hold=2)", "forearm plank": "forearm_plank(hold=2)", "elbow plank": "forearm_plank(hold=2)",
    "side plank": "side_plank(hold=2)", "dead bug": "dead_bug(times=2)", "dead bugs": "dead_bug(times=2)",
    "hands and knees": "table_top(hold=1)", "all fours": "table_top(hold=1)", "table top": "table_top(hold=1)",
    "sit and reach": "seated_forward_fold(hold=2)", "seated forward fold": "seated_forward_fold(hold=2)",
    "seated hamstring stretch": "seated_forward_fold(hold=2)", "butterfly stretch": "butterfly_stretch(hold=2)",
    "hip flexor stretch": "hip_flexor_stretch(hold=2)", "kneeling hip flexor stretch": "hip_flexor_stretch(hold=2)",
    "lie down": "lie_on_back(hold=1)", "lying on back": "lie_on_back(hold=1)", "get up": "get_up_from_floor",
    "sun salutation": "stand + arms_overhead\nhamstring_stretch(hold=0.6)\nplank(hold=0.5)\ncobra(hold=0.8)\ndownward_dog(hold=1)\nstand",
    "medicine ball slam": "overhead_slam(times=2)", "ball slam": "overhead_slam(times=2)", "slam": "overhead_slam",
    "forward roll": "forward_roll", "somersault": "forward_roll", "backstroke start": "backstroke_start\nback_crawl(times=2)",
    "juggling": "juggle_ball(times=4)", "soccer juggling": "juggle_ball(times=4)", "keep ups": "juggle_ball(times=4)",
    "straight drive": "vertical_two_hand_swing", "cover drive": "vertical_two_hand_swing", "cricket drive": "vertical_two_hand_swing",
    "kick for touch": "punt_kick", "drop kick": "punt_kick", "free kick": "instep_kick", "corner kick": "instep_kick",
    "penalty kick": "instep_kick", "penalty": "instep_kick", "pitch": "stride_step + overhand_throw(delay=0.25)",
    "baseball pitch": "stride_step + overhand_throw(delay=0.25)", "fastball": "stride_step + overhand_throw(delay=0.25)",
    "scrum": "bent_over_drive(times=3)", "rugby scrum": "bent_over_drive(times=3)", "ruck": "bent_over_drive(times=3)",
    "maul": "bent_over_drive(times=3)", "sled push": "bent_over_drive(times=4)", "rugby ruck": "bent_over_drive(times=3)",
    "swimming start": "start_dive\nstreamline(hold=0.6)", "swim start": "start_dive\nstreamline(hold=0.6)",
    "swimming start from the blocks": "start_dive\nstreamline(hold=0.6)", "start from the blocks": "start_dive\nstreamline(hold=0.6)",
    "dive start": "start_dive\nstreamline(hold=0.6)", "racing dive": "start_dive\nstreamline(hold=0.6)",
    "swimming dive": "start_dive\nstreamline(hold=0.6)", "block start": "start_dive\nstreamline(hold=0.6)",
    "track start": "sprint_start", "sprint start": "sprint_start", "starting blocks sprint": "sprint_start",
    # common names for things the database does with one script (answered instantly, no model call)
    "jumping lunges": "lunge_jump(times=2)", "lunge jumps": "lunge_jump(times=2)", "split jumps": "lunge_jump(times=2)",
    "jump lunges": "lunge_jump(times=2)", "box jump": "jump(height=high)", "box jumps": "jump(height=high)",
    "squat jump": "squat(end=0.5)\njump(height=high)", "squat jumps": "squat(end=0.5)\njump(height=high)",
    "vertical jump": "jump(height=high)", "jog": "run(pace=jog, times=3)", "jogging": "run(pace=jog, times=3)",
    "running": "run(times=3)", "sprint": "run(pace=sprint, times=3)", "sprinting": "run(pace=sprint, times=3)",
    "soccer shot": "soccer_kick", "shoot a soccer ball": "soccer_kick", "penalty kick": "soccer_kick",
    "soccer pass": "inside_foot_pass", "tennis forehand": "stance(width=wide, depth=0.4) + ready_arms\nstance(width=wide, depth=0.4) + forehand",
    "tennis backhand": "stance(width=wide, depth=0.4) + ready_arms\nstance(width=wide, depth=0.4) + backhand",
    "tennis serve": "serve", "golf swing": "stance(width=wide, depth=0.2) + golf_swing",
    "baseball swing": "stance(width=wide, depth=0.3) + bat_swing", "boxing guard": "fighting_stance(bounce=on) + guard(hold=2)",
    "jab": "fighting_stance + guard\nfighting_stance + guard + jab x2", "jab cross": "fighting_stance + guard + jab\nfighting_stance + guard + cross",
    "jump shot": "jump + shoot(delay=0.35)", "basketball jump shot": "jump + shoot(delay=0.35)",
    "free throw": "stance(depth=0.3) + shoot", "layup": "layup", "jumping jacks": "jumping_jack(times=3)",
    "push ups": "push_up(times=2)", "pushups": "push_up(times=2)", "sit ups": "sit_up(times=2)", "crunches": "sit_up(times=2)",
    "split squat": "split_squat(times=2)", "bulgarian split squat": "split_squat(times=2)", "skipping": "a_skip(times=3)",
    "high knees": "high_knees(times=4)", "butt kicks": "butt_kicks(times=4)", "frisbee forehand": "stance(depth=0.2) + frisbee_forehand",
    "frisbee backhand": "stance(depth=0.2) + frisbee_backhand", "volleyball spike": "jump(height=high) + spike_arms(delay=0.1)",
    "volleyball block": "jump + block_arms", "jumping header": "jump + header(delay=0.3)",
    "lateral shuffle": "shuffle(times=3)", "defensive slide": "defensive_stance\nshuffle(times=3)",
}


def catalog_text() -> str:
    """Compact catalog for the language model: name(params) kind parts - short description."""
    abbrev = {"body": "body", "pelvis": "hips", "spine": "trunk", "neck": "head", "right_arm": "Rarm", "left_arm": "Larm",
              "right_leg": "Rleg", "left_leg": "Lleg"}
    lines = []
    for name, m in DB.items():
        ps = []
        for p, v in m["params"].items():
            allowed = v[1]
            if isinstance(allowed, tuple) and len(allowed) == 2 and all(isinstance(x, (int, float)) for x in allowed):
                ps.append(f"{p}={allowed[0]}..{allowed[1]}")
            else:
                ps.append(f"{p}={'|'.join(map(str, allowed))}")
        sig = f"{name}({', '.join(ps)})" if ps else name
        parts = set(m["parts"])
        if {"right_arm", "left_arm", "right_leg", "left_leg"} <= parts:
            pc = "full"
        else:
            pc = "+".join("arms" if p == "right_arm" and "left_arm" in parts else "legs" if p == "right_leg" and "left_leg" in parts
                          else abbrev[p] for p in m["parts"] if not (p == "left_arm" and "right_arm" in parts)
                          and not (p == "left_leg" and "right_leg" in parts)) or "soft"
        desc = re.split(r"(?<=[a-z\)])[:.] ", m["comment"])[0]
        desc = desc if len(desc) <= 110 else desc[:107].rsplit(" ", 1)[0] + "..."
        lines.append(f"- {sig} [{m['kind'][0]}; {pc}] {desc}")
    return "\n".join(lines)


# Names the language model commonly writes that are not database names -> what they mean.
NAME_ALIASES: Dict[str, str] = {
    "sprint": "run(pace=sprint)", "jog": "run(pace=jog)", "running": "run", "athletic_stance": "stance",
    "ready_stance": "stance", "ready": "stance", "boxing_stance": "fighting_stance", "land": "stand", "landing": "stand",
    "recover": "stand", "rest": "stand", "idle": "stand", "hold": "stand", "box_jump": "jump(height=high)",
    "squat_jump": "jump(height=high)", "vertical_jump": "jump(height=high)", "jumping_lunge": "lunge_jump",
    "jump_lunge": "lunge_jump", "split_jump": "lunge_jump", "punch": "cross", "kick": "soccer_kick", "shot": "soccer_kick",
    "throw": "overhand_throw", "pitch": "overhand_throw", "swing": "bat_swing", "skip": "a_skip", "pushup": "push_up",
    "situp": "sit_up", "crunch": "sit_up", "pass": "chest_pass", "spike": "spike_arms", "block": "block_arms",
    "set": "volleyball_set", "kneeling": "kneel", "child_pose": "childs_pose", "childs_pose_stretch": "childs_pose",
    "all_fours": "table_top", "quadruped": "table_top", "down_dog": "downward_dog", "upward_dog": "cobra",
    "supine": "lie_on_back", "lie_down": "lie_on_back", "prone": "lie_face_down", "sit": "seated", "sitting": "seated", "slam": "overhead_slam", "ball_slam": "overhead_slam", "roll": "forward_roll",
    "scrum": "bent_over_drive", "ruck": "bent_over_drive", "sled_push": "bent_over_drive", "juggle": "juggle_ball",
    "churn": "run", "finish": "stand", "secure_catch": "catch", "overhead_two_hand_set_shot": "overhead_two_hand_set",
    "two_hand_overhead_set": "overhead_two_hand_set", "bump": "forearm_pass", "smash": "spike_arms", "plank_hold": "plank", "dive": "side_dive", "follow_through": "stand",
    "jumping_jacks": "jumping_jack", "lateral_shuffle": "shuffle", "defense": "defensive_stance",
}


# General names: motions are described by WHAT the body does, not by one sport, so they can be
# reused anywhere (a "slapshot" is a two-hand ground strike for hockey, hurling, floorball ...).
# The old sport-specific names keep working as aliases.
RENAMES: Dict[str, str] = {
    "soccer_kick": "instep_kick", "inside_foot_pass": "inside_foot_kick", "soccer_dribble": "foot_dribble",
    "forehand": "forehand_swing", "backhand": "two_hand_backhand", "serve": "jumping_overhead_serve",
    "volley": "punch_volley", "golf_swing": "low_two_hand_swing", "bat_swing": "level_two_hand_swing",
    "slapshot": "two_hand_ground_strike", "shoot": "one_hand_set_shot", "dribble": "hand_dribble",
    "layup": "running_lay_up", "volleyball_set": "overhead_two_hand_set", "forearm_pass": "forearm_platform",
    "spike_arms": "overhead_arm_strike", "block_arms": "arms_up_block", "header": "head_strike",
    "throw_in": "two_hand_overhead_throw", "cricket_bowl": "straight_arm_bowl", "underhand_pitch": "windmill_throw",
    "bowling": "underhand_roll", "shot_put": "push_throw", "javelin_throw": "long_arm_throw",
    "frisbee_backhand": "backhand_disc_throw", "frisbee_forehand": "sidearm_flick_throw",
    "freestyle": "front_crawl", "breaststroke": "breaststroke", "butterfly": "butterfly_stroke", "backstroke": "back_crawl",
    "fighting_stance": "fighting_stance", "touch_low": "touch_low", "defensive_stance": "wide_defensive_stance",
}
for _old, _new in RENAMES.items():
    if _old != _new and _old in DB:
        DB[_new] = DB.pop(_old)
        DB[_new]["name"] = _new
        NAME_ALIASES[_old] = _new
GENERAL_COMMENTS: Dict[str, str] = {
    "instep_kick": "Full-power instep kick of a ball on the ground with the right foot (e.g. soccer shot, rugby place/goal kick, kick-off): plant, knee-bent backswing, straight-leg strike, high follow-through. Calm balance arms.",
    "inside_foot_kick": "Inside-of-the-foot kick / pass with the right foot: short backswing, foot turned out, firm ankle, follow through to the target.",
    "foot_dribble": "Ball control with the feet in place: small inside/outside touches with the right foot (e.g. soccer dribbling).",
    "forehand_swing": "One-hand forehand swing on the right side (racket, paddle, bat): unit turn, drop, low-to-high swing through contact in front, finish over the left shoulder. Combine with a stance.",
    "two_hand_backhand": "Two-hand backhand swing on the left side: shoulders turn left with both hands back by the left hip, swing through contact in front, finish high over the right shoulder.",
    "jumping_overhead_serve": "Full-body overhead serve: toss arm up, trophy position with bent knees, legs drive up as the hitting arm reaches high to contact, follow through across the body (e.g. tennis serve, jump serve).",
    "punch_volley": "Compact forehand block / volley: hand up in front, short punch forward to meet the ball in front, no backswing.",
    "low_two_hand_swing": "Two-hand swing from the ground (club or stick): address with arms hanging, takeaway, full shoulder turn to the top, downswing, impact, high finish (e.g. golf full swing). Combine with stance(width=wide, depth=0.2).",
    "level_two_hand_swing": "Two-hand level swing at waist/chest height (bat): load hands back by the right shoulder, rotate hips then shoulders, swing through, wrap finish (e.g. baseball/softball swing, cricket pull shot).",
    "two_hand_ground_strike": "Two-hand stick strike along the ground: big backswing over the right shoulder, sweep down and through low, follow through low (e.g. hockey slapshot, field hockey hit).",
    "one_hand_set_shot": "One-hand overhead shot / release: ball up to the set point above the right eye (other hand on the side), extend the arm up and forward, snap the wrist, hold the follow-through. Combine with jump for a jump shot.",
    "hand_dribble": "Bounce a ball with the right hand at waist height (dribble), eyes up. Combine with a stance or run.",
    "running_lay_up": "Running two-step take-off off the left foot driving the right knee up, laying the ball up high with the right hand, landing on both feet.",
    "overhead_two_hand_set": "Two-hand overhead set / push pass: hands above the forehead, absorb by bending the elbows, extend both arms up and forward together.",
    "forearm_platform": "Forearm platform pass / dig: arms straight and together below the waist, small shoulder lift through contact.",
    "overhead_arm_strike": "Overhead one-arm strike: both arms swing back then up, the right arm draws back like a bow, whips through high contact and snaps down (e.g. volleyball spike, overhead smash). Combine with jump.",
    "arms_up_block": "Both arms extend straight up and slightly forward with the hands wide (block, contest a shot, lineout). Combine with jump.",
    "head_strike": "Strike a ball with the forehead: arch back, then snap the trunk and neck forward (e.g. soccer header). Combine with jump.",
    "two_hand_overhead_throw": "Two-hand overhead throw: ball behind the head, arch the back, whip both arms forward over the head and release (e.g. soccer throw-in, rugby lineout, basketball outlet pass).",
    "straight_arm_bowl": "Straight-arm overarm delivery: side-on gather, the straight arm rotates over the top past the ear and releases high, follow through across the body (e.g. cricket bowling).",
    "windmill_throw": "Windmill underhand throw: the throwing arm makes a full forward circle and whips past the hip to release (e.g. softball pitch).",
    "underhand_roll": "Underhand roll / release at the ankle: arm swings back as the knees bend into a long slide, then forward low (e.g. ten-pin bowling, bocce).",
    "push_throw": "Push throw from the neck: object pressed under the jaw, trunk coils back, legs and hips drive and the arm punches it up and out (e.g. shot put).",
    "long_arm_throw": "Long-arm overhead release: the throwing arm long and back at shoulder height, trunk leans back, then the arm comes through high over the shoulder (e.g. javelin).",
    "backhand_disc_throw": "Backhand throw across the body: reach the object back to the left hip, uncoil and pull the arm across the chest, snap, follow through to the target (e.g. frisbee backhand).",
    "sidearm_flick_throw": "Sidearm flick: object out to the right side at hip height with the elbow tucked, fast forearm-and-wrist flick toward the target (e.g. frisbee forehand, sidearm throw).",
    "front_crawl": "Front crawl (freestyle) swimming: alternating overarm pulls with body roll and a steady flutter kick, face down.",
    "butterfly_stroke": "Butterfly swimming: both arms pull together and recover over the water with a two-beat dolphin kick.",
    "back_crawl": "Back crawl (backstroke) swimming: face up, alternating straight-arm recovery over the head, flutter kick.",
    "wide_defensive_stance": "Wide, low defensive stance: back straight, weight on the balls of the feet, arms out wide with active hands. Optional bounce.",
}
for _n, _c in GENERAL_COMMENTS.items():
    if _n in DB:
        DB[_n]["comment"] = _c
for _a, _script in list(ALIASES.items()):
    for _old, _new in RENAMES.items():
        _script = re.sub(rf"\b{_old}\b", _new, _script)
    ALIASES[_a] = _script

ALIASES.update({k_: v_ for k_, v_ in _POS_ALIASES.items() if k_ not in ALIASES})
ALIASES.update({k_: v_ for k_, v_ in _POS_ALIASES2.items() if k_ not in ALIASES})
ALIASES.update({k_: v_ for k_, v_ in _POS_ALIASES3.items() if k_ not in ALIASES})
ALIASES.update({k_: v_ for k_, v_ in _POS_ALIASES4.items() if k_ not in ALIASES})
ALIASES.update({k_: v_ for k_, v_ in _POS_ALIASES5.items() if k_ not in ALIASES})
# batch B phrases override any earlier fuzzy defaults for the same words (e.g. "bowling")
ALIASES.update(_POS_ALIASES6)
ALIASES.update({k_: v_ for k_, v_ in _POS_ALIASES7.items() if k_ not in ALIASES})
ALIASES.update({k_: v_ for k_, v_ in _POS_ALIASES8.items() if k_ not in ALIASES})
try:   # every movement in the sport coverage map is also an instant request
    import sport_coverage as _cov
    for _sport, _phrase, _script in _cov.all_entries():
        for _key in (_phrase, f"{_sport.split(' ')[0]} {_phrase}"):
            _key = " ".join(re.findall(r"[a-z]+", _key.lower()))
            ALIASES.setdefault(_key, _script)
except ImportError:
    pass


def bake(verbose: bool = True) -> None:
    """Build every motion (and the common stance variants) so all placements are pre-solved."""
    import itertools
    import time
    t0 = time.time()
    for name, m in DB.items():
        m["build"]()
    for w, d, st in itertools.product(STANCE_WIDTH, [x / 20 for x in range(0, 21)], ("none", "left", "right")):
        stance_legs(w, d, st)
    save_solved()
    if verbose:
        print(f"baked {len(DB)} motions, {len(_SOLVED)} solved placements in {time.time() - t0:.0f} s -> {_SOLVED_PATH}")


if __name__ == "__main__":
    import sys
    if "--bake" in sys.argv:
        bake()
    else:
        print(catalog_text())
