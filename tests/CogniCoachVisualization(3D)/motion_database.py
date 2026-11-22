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
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

import motion_engine as me

U = me.UNIT_TO_M
HIP_OUT = me.HIP_OFFSET[0] * U          # 0.128 m
LEG_DROP0 = (me.THIGH + me.SHIN) * U    # hip joint -> ankle, standing (0.715 m)

DB: Dict[str, Dict[str, Any]] = {}


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
    samples = sorted(set([round(float(x), 3) for x in np.arange(ts[0], ts[-1], step)] + [float(x) for x in ts]))
    for t in samples:
        x, y, z = (round(float(me.hermite(ts, xyz[:, c], m[c], np.array([t]))[0]), 3) for c in range(3))
        i = int(np.clip(np.searchsorted(ts, t, side="right") - 1, 0, len(ts) - 1))
        j = min(i + 1, len(ts) - 1)
        el = points[i][4] if i == j or (t - ts[i]) < (ts[j] - t) else points[j][4]
        out.append(k(t, right_arm=arm_at(x, y, z, el, "right"), left_arm=arm_at(-x, y, z, el, "left")))
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


@functools.lru_cache(maxsize=4096)
def leg_at(fwd: float, out: float, drop: float = 0.0, lift: float = 0.0, toe: float = 8.0,
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


@functools.lru_cache(maxsize=4096)
def arm_at(x: float, y: float, z: float, elbow: str = "down", side: str = "right") -> Dict[str, float]:
    """Arm angles that put the hand at (x across->out, y up, z forward) metres measured from the
    MIDDLE of the shoulder line (x + = toward the arm's own side), elbow pointing `elbow`."""
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
    return [k(0.0, body=B(76), spine=S(0), pelvis=P(), right_arm=A(84, 4, 0, 0), left_arm=A(84, 4, 0, 0),
              right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), neck=N(-15))]


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
    up = {"right_arm": A(84, 4, 0, 0), "left_arm": A(84, 4, 0, 0)}
    down = {"right_arm": A(30, 50, 40, 95), "left_arm": A(30, 50, 40, 95)}
    legs = {"right_leg": Lg(0, 0, 0, 0), "left_leg": Lg(0, 0, 0, 0)}
    return [k(0.0, body=B(76), spine=S(0), pelvis=P(), **up, **legs, neck=N(-15)),
            k(0.75, body=B(84), **down), k(0.9, hold=True), k(1.6, body=B(76), **up)]


@motion("mountain_climbers", "Mountain climbers: in a plank, drive the knees to the chest alternately and fast.",
        "cycle", ["body"] + ARMS + LEGS + ["spine", "pelvis"], ["neck"], period=0.6)
def _mountain():
    arms = {"right_arm": A(84, 4, 0, 0), "left_arm": A(84, 4, 0, 0)}
    return [k(0.0, body=B(72), spine=S(0), pelvis=P(), **arms, right_leg=Lg(95, 0, 4, 120), left_leg=Lg(0, 0, 4, 0),
              neck=N(-15)),
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
            k(1.05, body=B(76), spine=S(0), pelvis=P(), right_arm=A(84, 4, 0, 0), left_arm=A(84, 4, 0, 0),
              right_leg=Lg(0, 0, 0, 0), left_leg=Lg(0, 0, 0, 0), neck=N(-15)),
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


def catalog_text() -> str:
    """Compact catalog for the language model: name(params) [kind; parts] comment."""
    lines = []
    for name, m in DB.items():
        ps = ", ".join(f"{p}={'|'.join(map(str, v[1])) if not (isinstance(v[1], tuple) and len(v[1]) == 2 and all(isinstance(x, (int, float)) for x in v[1])) else f'{v[1][0]}..{v[1][1]}'}"
                       for p, v in m["params"].items())
        sig = f"{name}({ps})" if ps else name
        parts = "+".join(m["parts"])
        soft = ("; soft: " + "+".join(m["soft_parts"])) if m["soft_parts"] else ""
        lines.append(f"- {sig} [{m['kind']}; drives {parts}{soft}] {m['comment']}")
    return "\n".join(lines)
