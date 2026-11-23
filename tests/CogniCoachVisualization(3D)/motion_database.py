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
    """Compact catalog for the language model: name(params) [kind; parts] comment."""
    lines = []
    for name, m in DB.items():
        ps = ", ".join(f"{p}={'|'.join(map(str, v[1])) if not (isinstance(v[1], tuple) and len(v[1]) == 2 and all(isinstance(x, (int, float)) for x in v[1])) else f'{v[1][0]}..{v[1][1]}'}"
                       for p, v in m["params"].items())
        sig = f"{name}({ps})" if ps else name
        full = {"right_arm", "left_arm"} <= set(m["parts"]) and {"right_leg", "left_leg"} <= set(m["parts"])
        parts = "FULL BODY" if full else "+".join(m["parts"])
        soft = ("; soft: " + "+".join(m["soft_parts"])) if m["soft_parts"] else ""
        lines.append(f"- {sig} [{m['kind']}; drives {parts}{soft}] {m['comment']}")
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
