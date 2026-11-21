"""CogniCoach motion library: hand-built, render-verified movement templates and poses.

The language model never writes raw animation numbers. It only chooses entries from this library
(template + variant + a few enum parameters, or a sequence of named poses). Everything here is
authored for a RIGHT-handed athlete; the engine mirrors whole plans for left-handers.

Keyframe shorthand used by every template (see `K`):
  rh / lh  hand  (forward, up, out)          metres, chest frame, out = toward that hand's own side
  rf / lf  foot  (forward, out, lift, toe_out) metres, body frame
  pel      pelvis (height, twist, tilt, side)
  tor      torso  (lean, twist, side_bend)    twist + = chest faces the athlete's right
  head     (nod, turn, tilt)
  body     (pitch, turn, roll)                whole-body rotation
  plant    "both" | "left" | "right" | "none"
  re / le  elbow direction hint ("down", "out", "back", "up", "forward")
  grip     both hands on one implement (left hand attaches to the right)
"""

from __future__ import annotations

import copy
import difflib
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

# -----------------------------------------------------------------------------
# Keyframe helpers
# -----------------------------------------------------------------------------

_FIELDS = {
    "rh": ("right_hand", ("forward", "up", "out")),
    "lh": ("left_hand", ("forward", "up", "out")),
    "rf": ("right_foot", ("forward", "out", "lift", "toe_out")),
    "lf": ("left_foot", ("forward", "out", "lift", "toe_out")),
    "pel": ("pelvis", ("height", "twist", "tilt", "side")),
    "tor": ("torso", ("lean", "twist", "side_bend")),
    "head": ("head", ("nod", "turn", "tilt")),
    "body": ("body", ("pitch", "turn", "roll")),
}

HANG = (0.05, -0.6, 0.33)
STAND_FOOT = (0.0, 0.12, 0.0, 10.0)


def K(t: float, phase: str, plant: str = "both", grip: bool = False, re: str = "down", le: str = "down",
      **parts: Sequence[float]) -> Dict[str, Any]:
    """Build a partial keyframe (missing groups/fields fall back to the neutral standing pose)."""
    kf: Dict[str, Any] = {"t": float(t), "phase": phase}
    for short, values in parts.items():
        if values is None:
            continue
        group, names = _FIELDS[short]
        kf[group] = {n: float(v) for n, v in zip(names, values)}
    kf["left_foot_planted"] = plant in ("both", "left")
    kf["right_foot_planted"] = plant in ("both", "right")
    kf["hands_together"] = bool(grip)
    kf["right_elbow_points"] = re
    kf["left_elbow_points"] = le
    return kf


def swap_sides(kf: Dict[str, Any], t: Optional[float] = None, phase: Optional[str] = None) -> Dict[str, Any]:
    """Mirror one keyframe left<->right (for alternating cycles such as running or swimming)."""
    out = copy.deepcopy(kf)
    for a, b in (("right_hand", "left_hand"), ("right_foot", "left_foot"),
                 ("right_foot_planted", "left_foot_planted"), ("right_elbow_points", "left_elbow_points")):
        va, vb = out.pop(a, None), out.pop(b, None)
        if vb is not None:
            out[a] = vb
        if va is not None:
            out[b] = va
    for group, fields in (("body", ("turn", "roll")), ("pelvis", ("twist", "side")),
                          ("torso", ("twist", "side_bend")), ("head", ("turn", "tilt"))):
        for f in fields:
            if group in out and f in out[group]:
                out[group][f] = -out[group][f]
    if t is not None:
        out["t"] = float(t)
    if phase is not None:
        out["phase"] = phase
    return out


def retime(keys: List[Dict[str, Any]], times: Sequence[float]) -> List[Dict[str, Any]]:
    for k, t in zip(keys, times):
        k["t"] = float(t)
    return keys


def scale_amp(v: float, amp: float, base: float = 0.0) -> float:
    return base + (v - base) * amp


# Common bases ---------------------------------------------------------------
READY = dict(pel=(-0.08, 0, 4), tor=(18, 0, 0), rh=(0.3, -0.35, 0.22), lh=(0.3, -0.35, 0.22),
             rf=(0.0, 0.24, 0, 12), lf=(0.0, 0.24, 0, 12))
STANDING = dict(rh=HANG, lh=HANG, rf=STAND_FOOT, lf=STAND_FOOT)


def _merge(base: Dict[str, Any], **over: Any) -> Dict[str, Any]:
    d = dict(base)
    d.update(over)
    return d


# -----------------------------------------------------------------------------
# Templates. Each returns {"keys": [...], "duration": s, "loop": bool, "view": str}
# `amp` is the intensity multiplier (0.75 low, 1 medium, 1.2 high).
# -----------------------------------------------------------------------------

def tpl_run(variant: str, amp: float) -> Dict[str, Any]:
    cfg = {
        "jog": dict(knee=0.22, back=0.22, stride=0.16, arm=0.75, flight=0.02, dur=0.72, lean=6, pitch=2),
        "sprint": dict(knee=0.42, back=0.32, stride=0.28, arm=1.15, flight=0.05, dur=0.6, lean=10, pitch=4),
        "high_knees": dict(knee=0.55, back=0.05, stride=0.03, arm=0.9, flight=0.03, dur=0.5, lean=0, pitch=0),
        "butt_kicks": dict(knee=0.08, back=0.6, stride=0.0, arm=0.7, flight=0.03, dur=0.5, lean=4, pitch=0),
        "march": dict(knee=0.4, back=0.0, stride=0.0, arm=0.8, flight=0.0, dur=1.1, lean=0, pitch=0),
        "backpedal": dict(knee=0.18, back=0.15, stride=-0.15, arm=0.6, flight=0.0, dur=0.6, lean=18, pitch=0),
        "a_skip": dict(knee=0.5, back=0.05, stride=0.05, arm=1.0, flight=0.06, dur=0.8, lean=2, pitch=0),
    }
    c = cfg.get(variant, cfg["jog"])
    knee, back, stride, arm = c["knee"] * amp, c["back"] * amp, c["stride"] * amp, c["arm"] * amp
    tor = (c["lean"], -6 * amp, 0)
    body = (c["pitch"], 0, 0)
    front_hand = (0.32 * arm, -0.15 - 0.05 / max(arm, 0.5), 0.2)
    back_hand = (-0.22 * arm, -0.45, 0.31)
    mid_hand = (0.05, -0.42, 0.29)
    # Contact: right foot lands, left leg trails behind.
    k0 = K(0.0, "right foot contact", plant="right", re="back", le="back",
           rf=(0.4 * stride, 0.11, 0, 6), lf=(-0.5 * abs(stride) - 0.05, 0.11, 0.5 * back + 0.05, 6),
           rh=mid_hand, lh=mid_hand, pel=(-0.05, 0, 3), tor=tor, body=body)
    # Mid stance: right leg under/behind, left knee drives, arms at extremes (right arm forward).
    k1 = K(0.22, "left knee drive", plant="right", re="back", le="back",
           rf=(-0.6 * stride, 0.11, 0.0, 6), lf=(0.4 * stride + 0.08 * knee / 0.4, 0.11, knee, 6),
           rh=front_hand, lh=back_hand, pel=(0.0, 8 * amp, 3), tor=(c["lean"], -8 * amp, 0), body=body)
    planted_flight = "none" if c["flight"] > 0 else "right"
    k2 = K(0.36, "flight", plant=planted_flight, re="back", le="back",
           rf=(-0.5 * abs(stride) - 0.05, 0.11, 0.35 * back + 0.06, 6), lf=(0.45 * stride + 0.02, 0.11, 0.6 * knee, 6),
           rh=(0.2 * arm, -0.25, 0.24), lh=(-0.12 * arm, -0.45, 0.3), pel=(c["flight"], 4 * amp, 3), tor=tor, body=body)
    keys = [k0, k1, k2, swap_sides(k0, 0.5, "left foot contact"), swap_sides(k1, 0.72, "right knee drive"),
            swap_sides(k2, 0.86, "flight")]
    return {"keys": keys, "duration": c["dur"], "loop": True, "view": "side"}


def tpl_track(variant: str, amp: float) -> Dict[str, Any]:
    a = amp
    if variant in ("hurdle", "sprint_hurdle", "hurdle_clearance"):
        # Lead leg (right) attacks straight forward with the knee leading then extends; opposite arm
        # reaches forward; trail leg (left) is pulled through flat, knee out to the side, then drives
        # forward into the next stride.
        lean = dict(body=(5, 0, 0), tor=(14, 0, 0))
        keys = [
            K(0.0, "approach stride", plant="left", re="back", le="back",
              **_merge(lean, rf=(0.2, 0.11, 0.35, 5), lf=(-0.1, 0.11, 0, 5), rh=(-0.2, -0.45, 0.3), lh=(0.3, -0.2, 0.2))),
            K(0.2, "attack: lead knee drives", plant="left", re="back", le="down",
              **_merge(lean, rf=(0.35, 0.1, 0.5, 5), lf=(-0.25, 0.11, 0.02, 5), rh=(-0.2, -0.45, 0.32), lh=(0.5, -0.1, 0.15),
                       pel=(0.05, 0, 0))),
            K(0.35, "clearance: lead leg extends, chest dips", plant="none", re="back", le="down",
              **_merge(lean, body=(8, 0, 0), tor=(24 * a, 0, 0), rf=(0.64, 0.1, 0.5, 5), lf=(-0.3, 0.2, 0.25, 30),
                       rh=(-0.15, -0.45, 0.35), lh=(0.62, -0.15, 0.0), pel=(0.25, 0, 0))),
            K(0.5, "trail leg pulls through flat", plant="none", re="back", le="back",
              **_merge(lean, body=(8, 0, 0), tor=(22, 0, 0), rf=(0.25, 0.1, 0.15, 5), lf=(-0.05, 0.42, 0.45, 70),
                       rh=(0.2, -0.3, 0.3), lh=(0.0, -0.4, 0.45), pel=(0.2, 0, 0))),
            K(0.65, "land on lead leg, trail knee drives", plant="right", re="back", le="back",
              **_merge(lean, rf=(0.0, 0.11, 0, 5), lf=(0.2, 0.12, 0.45, 10), rh=(0.3, -0.2, 0.2), lh=(-0.2, -0.45, 0.3))),
            K(0.82, "next stride", plant="left", re="back", le="back",
              **_merge(lean, rf=(-0.25, 0.11, 0.3, 5), lf=(0.1, 0.11, 0, 5), rh=(-0.2, -0.45, 0.3), lh=(0.3, -0.2, 0.2))),
            K(1.0, "approach stride", plant="left", re="back", le="back",
              **_merge(lean, rf=(0.2, 0.11, 0.35, 5), lf=(-0.1, 0.11, 0, 5), rh=(-0.2, -0.45, 0.3), lh=(0.3, -0.2, 0.2))),
        ]
        return {"keys": keys, "duration": 1.5, "loop": False, "view": "side"}
    raise KeyError(variant)


def tpl_swim(variant: str, amp: float) -> Dict[str, Any]:
    """Swimming strokes. Body horizontal (pitch 88 face-down; -88 for backstroke).

    In the chest frame of a horizontal swimmer: up = toward the head (direction of travel),
    forward = out of the chest (down toward the pool bottom), negative forward = above the back.
    """
    if variant == "breaststroke":
        body = (86, 0, 0)
        glide = K(0.0, "glide", plant="none", re="out", le="out", body=body, head=(10, 0, 0),
                  rh=(0.12, 0.6, 0.12), lh=(0.12, 0.6, 0.12), rf=(0.0, 0.08, 0.0, 10), lf=(0.0, 0.08, 0.0, 10))
        outsweep = K(0.25, "outsweep", plant="none", re="out", le="out", body=(84, 0, 0), head=(5, 0, 0),
                     rh=(0.22, 0.45, 0.48), lh=(0.22, 0.45, 0.48), rf=(0.0, 0.08, 0.0, 10), lf=(0.0, 0.08, 0.0, 10))
        insweep = K(0.45, "insweep + breathe", plant="none", re="out", le="out", body=(74, 0, 0), head=(-25, 0, 0),
                    rh=(0.4, 0.02, 0.1), lh=(0.4, 0.02, 0.1), rf=(-0.04, 0.16, 0.2, 35), lf=(-0.04, 0.16, 0.2, 35))
        recover = K(0.6, "heels to seat, knees apart", plant="none", re="down", le="down", body=(82, 0, 0),
                    head=(0, 0, 0), pel=(0, 0, 10, 0),
                    rh=(0.3, 0.35, 0.08), lh=(0.3, 0.35, 0.08), rf=(-0.16, 0.3, 0.36, 50), lf=(-0.16, 0.3, 0.36, 50))
        kick = K(0.75, "whip kick", plant="none", re="out", le="out", body=(86, 0, 0), head=(10, 0, 0),
                 rh=(0.15, 0.6, 0.12), lh=(0.15, 0.6, 0.12), rf=(0.02, 0.38, 0.1, 40), lf=(0.02, 0.38, 0.1, 40))
        return {"keys": [glide, outsweep, insweep, recover, kick], "duration": 1.6, "loop": True, "view": "side"}
    if variant == "butterfly":
        # Arms: catch wide, keyhole pull under the chest, push past the hips, then a straight-arm
        # recovery swung OUT to the sides ABOVE the body (forward < 0 = above the back), re-entry
        # shoulder-width ahead. Legs: two dolphin kicks per cycle; knees bend (feet rise toward the
        # surface) then whip straight, with the hips undulating (body pitch / pelvis tilt).
        def fly(t, ph, hand, el, pitch, tilt, feet_fwd, feet_lift, head_nod=0):
            return K(t, ph, plant="none", re=el, le=el, body=(pitch, 0, 0), pel=(0, 0, tilt, 0),
                     head=(head_nod, 0, 0), rh=hand, lh=hand,
                     rf=(feet_fwd, 0.08, feet_lift, 0), lf=(feet_fwd, 0.08, feet_lift, 0))
        keys = [
            fly(0.0, "entry + 1st kick down", (0.05, 0.6, 0.3), "out", 94, -8, 0.12, 0.0),
            fly(0.14, "catch wide", (0.3, 0.42, 0.42), "out", 90, 0, -0.05, 0.12),
            fly(0.3, "keyhole pull", (0.45, 0.02, 0.12), "out", 84, 8, -0.15, 0.3),
            fly(0.44, "push + 2nd kick down + breathe", (0.15, -0.55, 0.3), "back", 76, -6, 0.12, 0.0, -30),
            fly(0.56, "exit at hips", (-0.12, -0.5, 0.42), "back", 80, 0, 0.02, 0.06, -20),
            fly(0.7, "recovery swings out over water", (-0.32, -0.02, 0.62), "back", 86, 4, -0.08, 0.18),
            fly(0.85, "recovery forward above water", (-0.18, 0.42, 0.45), "back", 90, 6, -0.15, 0.3),
        ]
        return {"keys": keys, "duration": 1.3, "loop": True, "view": "side"}
    if variant == "backstroke":
        body = (-86, 0, 0)
        # Face up: forward (out of chest) points to the sky.
        def bk(t, ph, r, l, re, le, roll):
            return K(t, ph, plant="none", re=re, le=le, body=(-86, 0, roll), rh=r, lh=l,
                     rf=(0.06 if t < 0.5 else -0.06, 0.1, 0.0, 5), lf=(-0.06 if t < 0.5 else 0.06, 0.1, 0.0, 5))
        k0 = bk(0.0, "right entry", (0.0, 0.62, 0.25), (0.05, -0.6, 0.3), "out", "down", 25)
        k1 = bk(0.25, "right pull", (-0.22, 0.15, 0.4), (0.55, -0.25, 0.28), "out", "down", 25)
        k2 = swap_sides(k0, 0.5, "left entry")
        k3 = swap_sides(k1, 0.75, "left pull")
        for k in (k2, k3):
            k["body"]["pitch"] = -86
        return {"keys": [k0, k1, k2, k3], "duration": 1.6, "loop": True, "view": "side"}
    # Freestyle (default): alternate arms half a cycle apart, body roll toward the pulling arm.
    def fs(t, ph, r, l, re, le, roll, head_turn, rkick):
        return K(t, ph, plant="none", re=re, le=le, body=(88, 0, roll), head=(0, head_turn, 0), rh=r, lh=l,
                 rf=(0.08 * rkick, 0.1, 0.0, 5), lf=(-0.08 * rkick, 0.1, 0.0, 5))
    entry = (0.12, 0.6, 0.22)
    catch = (0.35, 0.38, 0.18)
    pull = (0.45, -0.02, 0.06)
    push = (0.12, -0.56, 0.3)
    exit_ = (-0.15, -0.45, 0.4)
    recov = (-0.28, 0.12, 0.45)
    r_roll = 35 * amp
    keys = [
        fs(0.0, "right entry / left push", entry, push, "out", "back", -r_roll * 0.6, 0, 1),
        fs(0.17, "right catch / left exit", catch, exit_, "out", "back", -r_roll * 0.2, 0, -1),
        fs(0.33, "right pull / left recovery", pull, recov, "out", "back", r_roll * 0.3, 0, 1),
        fs(0.5, "right push + breathe / left entry", push, entry, "back", "out", r_roll, 60, -1),
        fs(0.67, "right exit / left catch", exit_, catch, "back", "out", r_roll * 0.3, 20, 1),
        fs(0.83, "right recovery / left pull", recov, pull, "back", "out", -r_roll * 0.3, 0, -1),
    ]
    return {"keys": keys, "duration": 1.4, "loop": True, "view": "side"}


def tpl_swing(variant: str, amp: float) -> Dict[str, Any]:
    """Implement swings for a right-hander (racket, club, bat, stick)."""
    if variant in ("golf_drive", "golf_iron", "golf_chip", "golf_putt"):
        scale = {"golf_drive": 1.0, "golf_iron": 0.85, "golf_chip": 0.35, "golf_putt": 0.12}[variant] * amp
        base = dict(pel=(-0.06, 0, 8), tor=(38, 0, 0), rf=(0.0, 0.22 if scale > 0.5 else 0.14, 0, 8),
                    lf=(0.0, 0.22 if scale > 0.5 else 0.14, 0, 18), head=(25, 0, 0))
        addr = (0.3, -0.58, 0.02)
        keys = [
            K(0.0, "address", grip=True, **_merge(base, rh=addr, lh=addr)),
            K(0.22, "takeaway", grip=True, **_merge(base, rh=(0.3, -0.5 + 0.1 * scale, 0.1 * scale + 0.02), lh=addr,
                                                     tor=(37, 35 * scale, 0), pel=(-0.06, 15 * scale, 8))),
            K(0.48, "top of backswing", grip=True, re="down",
              **_merge(base, rh=(0.3, -0.5 + 0.8 * scale, 0.1 * scale), lh=addr,
                       tor=(32, 90 * scale, -5 * scale), pel=(-0.06, 42 * scale, 8), head=(25, 15 * scale, 0))),
            K(0.62, "downswing", grip=True,
              **_merge(base, rh=(0.3, -0.4 + 0.35 * scale, 0.1 * scale), lh=addr,
                       tor=(35, 45 * scale, 0), pel=(-0.07, 0, 8))),
            K(0.7, "impact", grip=True, **_merge(base, rh=(0.32, -0.58, 0.02), lh=addr,
                                                 tor=(37, -10 * scale, 0), pel=(-0.06, -35 * scale, 8))),
            K(0.8, "release", grip=True, **_merge(base, rh=(0.32, -0.45 + 0.3 * scale, -0.08 * scale), lh=addr,
                                                  tor=(28, -55 * scale, 5 * scale), pel=(-0.04, -45 * scale, 4),
                                                  head=(15, -20 * scale, 0))),
            K(1.0, "finish", grip=True, plant="left" if scale > 0.5 else "both",
              **_merge(base, rh=(0.3, -0.5 + 0.75 * scale, -0.1 * scale), lh=addr,
                       tor=(38 - 30 * scale, -90 * scale, 10 * scale), pel=(-0.02, -50 * scale, 2),
                       head=(5, -35 * scale, 0), rf=(0.0, 0.22, 0.05 * scale, 8))),
        ]
        dur = {"golf_drive": 2.3, "golf_iron": 2.1, "golf_chip": 1.6, "golf_putt": 1.6}[variant]
        return {"keys": keys, "duration": dur, "loop": False, "view": "front"}
    if variant in ("baseball_bat", "softball_bat"):
        base = dict(pel=(-0.08, 25, 4), tor=(12, 35, 0), rf=(-0.15, 0.22, 0, 10), lf=(0.18, 0.22, 0, 20),
                    head=(5, -45, 0))
        hands_up = (0.12, 0.08, 0.3)
        keys = [
            K(0.0, "stance", grip=True, re="down", **_merge(base, rh=hands_up, lh=hands_up)),
            K(0.3, "load + stride", grip=True, plant="right",
              **_merge(base, rh=(0.05, 0.12, 0.38), lh=hands_up, tor=(12, 50, 0), pel=(-0.1, 35, 4),
                       lf=(0.25, 0.2, 0.12, 20))),
            K(0.5, "foot plant", grip=True, **_merge(base, rh=(0.05, 0.1, 0.38), lh=hands_up, tor=(12, 45, 0),
                                                     pel=(-0.1, 15, 4), lf=(0.3, 0.2, 0, 25))),
            K(0.62, "hips fire", grip=True, **_merge(base, rh=(0.25, -0.05, 0.3), lh=hands_up, tor=(14, 15, 0),
                                                     pel=(-0.1, -30, 4), lf=(0.3, 0.2, 0, 25))),
            K(0.7, "contact", grip=True, **_merge(base, rh=(0.5, -0.2, 0.05), lh=hands_up, tor=(14, -25, 0),
                                                  pel=(-0.08, -45, 4), lf=(0.3, 0.2, 0, 25), head=(10, -30, 0))),
            K(0.85, "extension", grip=True, **_merge(base, rh=(0.45, -0.05, -0.35), lh=hands_up,
                                                     tor=(10, -60, 0), pel=(-0.06, -55, 4), lf=(0.3, 0.2, 0, 25))),
            K(1.0, "finish", grip=True, plant="left",
              **_merge(base, rh=(0.15, 0.2, -0.35), lh=hands_up, tor=(6, -80, 0), pel=(-0.05, -60, 2),
                       lf=(0.3, 0.2, 0, 25), rf=(-0.1, 0.18, 0.06, 10), head=(5, -30, 0))),
        ]
        return {"keys": keys, "duration": 1.5, "loop": False, "view": "front"}
    if variant in ("tennis_backhand", "tennis_two_handed_backhand"):
        base = dict(pel=(-0.1, 0, 4), tor=(18, 0, 0), rf=(0.0, 0.25, 0, 12), lf=(0.0, 0.25, 0, 12))
        rdy = (0.32, -0.35, 0.1)
        keys = [
            K(0.0, "ready", grip=True, **_merge(base, rh=rdy, lh=rdy)),
            K(0.28, "unit turn left", grip=True, **_merge(base, rh=(0.0, -0.15, -0.45), lh=rdy, tor=(18, -60, 0),
                                                         pel=(-0.12, -35, 4), rf=(0.12, 0.2, 0, 12))),
            K(0.5, "drop", grip=True, **_merge(base, rh=(0.0, -0.45, -0.4), lh=rdy, tor=(20, -40, 0),
                                               pel=(-0.14, -10, 4), rf=(0.12, 0.2, 0, 12))),
            K(0.6, "contact", grip=True, **_merge(base, rh=(0.45, -0.3, -0.3), lh=rdy, tor=(18, 0, 0),
                                                  pel=(-0.12, 20, 4), rf=(0.12, 0.2, 0, 12))),
            K(0.72, "extension", grip=True, **_merge(base, rh=(0.5, -0.05, 0.0), lh=rdy, tor=(16, 35, 0),
                                                     pel=(-0.1, 35, 4), rf=(0.12, 0.2, 0, 12))),
            K(0.88, "finish over right shoulder", grip=True,
              **_merge(base, rh=(0.2, 0.12, 0.35), lh=rdy, tor=(14, 60, 0), pel=(-0.08, 40, 4), rf=(0.12, 0.2, 0, 12))),
            K(1.0, "recover", grip=True, **_merge(base, rh=rdy, lh=rdy)),
        ]
        return {"keys": keys, "duration": 1.6, "loop": False, "view": "three_quarter"}
    if variant in ("hockey_slapshot", "hockey_wristshot", "field_hockey_hit", "lacrosse_shot"):
        base = dict(pel=(-0.12, 0, 6), tor=(30, 0, 0), rf=(-0.1, 0.25, 0, 15), lf=(0.15, 0.25, 0, 20))
        lo = (0.35, -0.55, 0.1)
        high = 0.4 if variant == "hockey_slapshot" else 0.1
        keys = [
            K(0.0, "set", grip=True, **_merge(base, rh=lo, lh=lo)),
            K(0.4, "wind-up", grip=True, **_merge(base, rh=(0.05, -0.3 + high, 0.45), lh=lo, tor=(25, 55, 0),
                                                  pel=(-0.12, 30, 6))),
            K(0.62, "downswing", grip=True, **_merge(base, rh=(0.3, -0.5, 0.3), lh=lo, tor=(30, 15, 0), pel=(-0.13, -10, 6))),
            K(0.7, "contact", grip=True, **_merge(base, rh=(0.42, -0.55, 0.0), lh=lo, tor=(30, -20, 0), pel=(-0.12, -35, 6))),
            K(0.85, "follow-through", grip=True, plant="left",
              **_merge(base, rh=(0.45, -0.2, -0.35), lh=lo, tor=(22, -55, 0), pel=(-0.1, -45, 6), rf=(-0.1, 0.2, 0.08, 15))),
            K(1.0, "recover", grip=True, **_merge(base, rh=lo, lh=lo)),
        ]
        return {"keys": keys, "duration": 1.5, "loop": False, "view": "front"}
    if variant == "table_tennis_forehand":
        base = dict(pel=(-0.14, 0, 6), tor=(28, 0, 0), rf=(-0.05, 0.28, 0, 15), lf=(0.05, 0.28, 0, 15))
        keys = [
            K(0.0, "ready", **_merge(base, rh=(0.35, -0.3, 0.2), lh=(0.35, -0.25, 0.15))),
            K(0.35, "backswing", **_merge(base, rh=(0.15, -0.4, 0.45), lh=(0.35, -0.2, 0.1), tor=(28, 30, 0), pel=(-0.15, 15, 6))),
            K(0.6, "contact", **_merge(base, rh=(0.45, -0.2, 0.25), lh=(0.3, -0.2, 0.1), tor=(26, 0, 0), pel=(-0.14, -5, 6))),
            K(0.8, "finish", **_merge(base, rh=(0.35, 0.05, -0.05), lh=(0.3, -0.2, 0.15), tor=(24, -25, 0), pel=(-0.13, -15, 6))),
            K(1.0, "ready", **_merge(base, rh=(0.35, -0.3, 0.2), lh=(0.35, -0.25, 0.15))),
        ]
        return {"keys": keys, "duration": 1.0, "loop": False, "view": "three_quarter"}
    # Tennis / padel / squash forehand (default). Elbow stays "down": the forearm swings around the
    # body with the trunk instead of the elbow whipping around.
    base = dict(pel=(-0.1, 0, 4), tor=(18, 0, 0), rf=(0.0, 0.25, 0, 12), lf=(0.0, 0.25, 0, 12))
    rdy_r, rdy_l = (0.33, -0.33, 0.12), (0.38, -0.3, 0.02)
    a = amp
    keys = [
        K(0.0, "ready", **_merge(base, rh=rdy_r, lh=rdy_l)),
        K(0.25, "unit turn", **_merge(base, rh=(0.12, -0.2, 0.42), lh=(0.42, -0.15, 0.05), tor=(18, 50 * a, 0),
                                     pel=(-0.12, 28 * a, 4), lf=(0.12, 0.2, 0, 15))),
        K(0.45, "racket back", **_merge(base, rh=(-0.08, -0.15, 0.55), lh=(0.45, -0.05, -0.05), tor=(18, 60 * a, 0),
                                        pel=(-0.13, 35 * a, 4), lf=(0.12, 0.2, 0, 15))),
        K(0.58, "drop + hips fire", **_merge(base, rh=(0.02, -0.45, 0.5), lh=(0.35, -0.15, 0.0), tor=(20, 35 * a, 0),
                                             pel=(-0.14, 5, 4), lf=(0.12, 0.2, 0, 15))),
        K(0.66, "contact", **_merge(base, rh=(0.45, -0.32, 0.42), lh=(0.25, -0.2, 0.0), tor=(18, 0, 0),
                                    pel=(-0.12, -25 * a, 4), lf=(0.12, 0.2, 0, 15))),
        K(0.74, "extend through", **_merge(base, rh=(0.58, -0.12, 0.12), lh=(0.2, -0.25, 0.05), tor=(16, -30 * a, 0),
                                           pel=(-0.1, -35 * a, 4), lf=(0.12, 0.2, 0, 15))),
        K(0.88, "finish over shoulder", plant="left",
          **_merge(base, rh=(0.3, 0.05, -0.32), lh=(0.25, -0.1, 0.05), tor=(14, -60 * a, 0),
                   pel=(-0.08, -40 * a, 4), lf=(0.12, 0.2, 0, 15), rf=(-0.05, 0.22, 0.05, 12))),
        K(1.0, "recover", **_merge(base, rh=rdy_r, lh=rdy_l)),
    ]
    return {"keys": keys, "duration": 1.7, "loop": False, "view": "three_quarter"}


def tpl_overhead(variant: str, amp: float) -> Dict[str, Any]:
    """Overhead arm actions: throws, serves, spikes, smashes, passes."""
    a = amp
    if variant in ("tennis_serve", "volleyball_serve_jump", "badminton_smash", "overhead_smash"):
        jump = 0.15 if variant in ("tennis_serve", "badminton_smash") else 0.3
        base = dict(rf=(-0.15, 0.2, 0, 15), lf=(0.15, 0.15, 0, 25), tor=(10, 30, 0), pel=(-0.04, 25, 2))
        keys = [
            K(0.0, "stance", **_merge(base, rh=(0.35, -0.3, 0.15), lh=(0.38, -0.3, 0.05))),
            K(0.25, "toss", **_merge(base, rh=(-0.05, -0.45, 0.4), lh=(0.25, 0.55, 0.05), tor=(6, 45, 5),
                                    pel=(-0.06, 35, 2), head=(-25, 0, 0))),
            K(0.48, "trophy + knee bend", re="up",
              **_merge(base, rh=(-0.15, 0.2, 0.45), lh=(0.2, 0.55, 0.05), tor=(-12, 55, 12), pel=(-0.2, 40, -4),
                       head=(-35, 0, 0))),
            K(0.62, "drive up", re="up", plant="none",
              **_merge(base, rh=(-0.15, 0.05, 0.35), lh=(0.35, 0.0, 0.0), tor=(-8, 25, 8), pel=(jump * 0.5, 10, 0),
                       head=(-35, 0, 0), rf=(-0.15, 0.18, 0.05, 15), lf=(0.15, 0.15, 0.02, 25))),
            K(0.7, "contact", re="forward", plant="none",
              **_merge(base, rh=(0.15, 0.63, 0.18), lh=(0.3, -0.3, 0.1), tor=(5, -10, 0), pel=(jump, -20, 0),
                       head=(-30, 0, 0), rf=(-0.2, 0.15, 0.12, 15), lf=(0.1, 0.15, 0.05, 25))),
            K(0.86, "follow-through", plant="left",
              **_merge(base, rh=(0.35, -0.5, -0.25), lh=(0.25, -0.35, 0.15), tor=(30, -45, 0), pel=(-0.12, -35, 6),
                       head=(10, 0, 0), lf=(0.2, 0.15, 0, 25), rf=(0.0, 0.2, 0.15, 15))),
            K(1.0, "recover", **_merge(base, rh=(0.35, -0.3, 0.15), lh=(0.38, -0.3, 0.05), tor=(15, 0, 0),
                                       pel=(-0.08, 0, 4), rf=(0.0, 0.24, 0, 12), lf=(0.0, 0.24, 0, 12))),
        ]
        return {"keys": keys, "duration": 2.0, "loop": False, "view": "three_quarter"}
    if variant in ("volleyball_spike", "basketball_dunk", "header_jump"):
        keys = [
            K(0.0, "approach", **_merge(READY, rh=(0.2, -0.4, 0.25), lh=(0.2, -0.4, 0.25))),
            K(0.25, "penultimate step + arms back", **_merge(READY, rh=(-0.35, -0.4, 0.3), lh=(-0.35, -0.4, 0.3),
                                                             pel=(-0.28, 0, 10), tor=(40, 0, 0), re="back", le="back")),
            K(0.42, "arm swing up + take off", plant="none",
              **_merge(READY, rh=(0.35, 0.5, 0.25), lh=(0.35, 0.5, 0.25), pel=(0.25 * a, 0, 0), tor=(0, 0, 0),
                       rf=(0.0, 0.18, 0.08, 10), lf=(0.0, 0.18, 0.08, 10))),
            K(0.55, "cock (bow)", plant="none", re="up",
              **_merge(READY, rh=(-0.12, 0.25, 0.45), lh=(0.3, 0.55, 0.12), pel=(0.4 * a, 25, -4), tor=(-15, 35, 0),
                       rf=(-0.05, 0.18, 0.2, 10), lf=(0.0, 0.18, 0.15, 10), head=(-25, 0, 0))),
            K(0.64, "contact", plant="none", re="forward",
              **_merge(READY, rh=(0.2, 0.63, 0.15), lh=(0.35, -0.2, 0.15), pel=(0.42 * a, -15, 0), tor=(10, -25, 0),
                       rf=(0.05, 0.18, 0.12, 10), lf=(0.05, 0.18, 0.1, 10), head=(-20, 0, 0))),
            K(0.78, "snap + follow-through", plant="none",
              **_merge(READY, rh=(0.35, -0.45, -0.15), lh=(0.25, -0.35, 0.2), pel=(0.15, -25, 4), tor=(35, -30, 0),
                       rf=(0.08, 0.18, 0.1, 10), lf=(0.05, 0.18, 0.08, 10))),
            K(0.9, "two-foot landing", **_merge(READY, rh=(0.3, -0.35, 0.3), lh=(0.3, -0.35, 0.3), pel=(-0.25, 0, 10),
                                                tor=(35, 0, 0))),
            K(1.0, "recover", **_merge(READY)),
        ]
        return {"keys": keys, "duration": 2.0, "loop": False, "view": "three_quarter"}
    if variant in ("soccer_throw_in", "two_hand_overhead_pass"):
        keys = [
            K(0.0, "hold ball", grip=True, **_merge(READY, rh=(0.3, -0.25, 0.0), lh=(0.3, -0.25, 0.0))),
            K(0.4, "ball behind head", grip=True, re="up",
              **_merge(READY, rh=(-0.12, 0.35, 0.05), lh=(-0.12, 0.35, 0.05), tor=(-20, 0, 0), pel=(-0.12, 0, -8),
                       rf=(-0.2, 0.15, 0, 10), lf=(0.2, 0.15, 0, 10))),
            K(0.62, "release", grip=True, re="up",
              **_merge(READY, rh=(0.35, 0.45, 0.02), lh=(0.35, 0.45, 0.02), tor=(20, 0, 0), pel=(-0.08, 0, 4),
                       rf=(-0.2, 0.15, 0, 10), lf=(0.2, 0.15, 0, 10))),
            K(0.8, "follow-through", grip=True,
              **_merge(READY, rh=(0.5, -0.15, 0.02), lh=(0.5, -0.15, 0.02), tor=(35, 0, 0), pel=(-0.08, 0, 6),
                       rf=(-0.2, 0.15, 0.03, 10), lf=(0.2, 0.15, 0, 10))),
            K(1.0, "recover", **_merge(READY)),
        ]
        return {"keys": keys, "duration": 1.6, "loop": False, "view": "side"}
    if variant in ("softball_windmill", "windmill_pitch"):
        # Straight pitching arm makes a full forward circle (front -> top -> back -> down) while the
        # left leg strides; release at the hip with the arm brushing the thigh, then follow-through up.
        base = dict(rf=(0.0, 0.14, 0, 15), lf=(0.0, 0.14, 0, 15), pel=(-0.06, 0, 4), tor=(10, 0, 0))
        keys = [
            K(0.0, "set (ball in glove at chest)", grip=True, **_merge(base, rh=(0.3, -0.25, 0.05), lh=(0.3, -0.25, 0.05))),
            K(0.15, "arm forward, start stride", plant="right",
              **_merge(base, rh=(0.6, -0.05, 0.25), lh=(0.45, -0.15, 0.1), lf=(0.15, 0.14, 0.12, 20), tor=(8, 10, 0))),
            K(0.3, "arm at top", plant="right",
              **_merge(base, rh=(0.1, 0.63, 0.28), lh=(0.55, 0.0, 0.05), lf=(0.3, 0.14, 0.1, 25), pel=(-0.1, 25, 2),
                       tor=(0, 35, 0))),
            K(0.45, "arm back (open hips)", plant="right",
              **_merge(base, rh=(-0.5, 0.25, 0.38), lh=(0.55, -0.05, 0.05), lf=(0.42, 0.12, 0.04, 30),
                       pel=(-0.14, 40, 2), tor=(0, 50, 0))),
            K(0.56, "stride foot lands, arm whips down",
              **_merge(base, rh=(-0.25, -0.5, 0.38), lh=(0.35, -0.25, 0.15), lf=(0.45, 0.12, 0, 30),
                       rf=(-0.15, 0.14, 0, 15), pel=(-0.16, 20, 4), tor=(5, 25, 0))),
            K(0.64, "release at the hip",
              **_merge(base, rh=(0.25, -0.58, 0.3), lh=(0.1, -0.35, 0.3), lf=(0.45, 0.12, 0, 30),
                       rf=(-0.15, 0.14, 0, 15), pel=(-0.15, -10, 6), tor=(12, -5, 0))),
            K(0.78, "follow-through up", plant="left", re="down",
              **_merge(base, rh=(0.45, 0.05, 0.15), lh=(0.0, -0.4, 0.35), lf=(0.45, 0.12, 0, 30),
                       rf=(0.0, 0.14, 0.15, 15), pel=(-0.12, -20, 6), tor=(15, -15, 0))),
            K(1.0, "fielding position", **READY),
        ]
        return {"keys": keys, "duration": 1.6, "loop": False, "view": "side"}
    if variant in ("shot_put", "shot_put_glide"):
        # Glide: start facing away from the throw (body turned 180), crouch, glide back across the
        # circle, turn the hips and chest to the front and drive the shot up and out from the neck.
        neck = (0.1, 0.08, 0.15)
        keys = [
            K(0.0, "start, back to the throw", re="out",
              **_merge(STANDING, body=(0, 170, 0), rh=neck, lh=(0.3, 0.2, 0.4), rf=(0, 0.12, 0, 10), lf=(-0.15, 0.12, 0.05, 10),
                       plant="right")),
            K(0.25, "crouch (low T)", plant="right", re="out",
              **_merge(STANDING, body=(0, 170, 0), rh=neck, lh=(0.35, -0.1, 0.35), tor=(60, 0, 0), pel=(-0.3, 0, 15),
                       lf=(-0.15, 0.12, 0.25, 10))),
            K(0.42, "glide (left leg drives)", plant="none", re="out",
              **_merge(STANDING, body=(0, 165, 0), rh=neck, lh=(0.35, -0.05, 0.4), tor=(55, 0, 0), pel=(-0.25, 0, 12),
                       lf=(-0.35, 0.12, 0.2, 10), rf=(0.05, 0.12, 0.08, 10))),
            K(0.55, "power position", re="out",
              **_merge(STANDING, body=(0, 110, 0), rh=neck, lh=(0.4, 0.15, 0.3), tor=(30, 40, 10), pel=(-0.2, 30, 6),
                       rf=(0.0, 0.18, 0, 30), lf=(-0.3, 0.18, 0, 20))),
            K(0.7, "hips + chest turn to the front", re="out",
              **_merge(STANDING, body=(0, 30, 0), rh=(0.2, 0.15, 0.15), lh=(0.2, -0.2, 0.45), tor=(10, -10, -5), pel=(-0.1, -10, 2),
                       rf=(0.0, 0.18, 0, 30), lf=(-0.3, 0.18, 0, 20))),
            K(0.78, "release (punch up and out)", re="down",
              **_merge(STANDING, body=(0, 0, 0), rh=(0.55, 0.32, 0.1), lh=(0.05, -0.35, 0.45), tor=(0, -25, -10), pel=(0.05, -20, 0),
                       rf=(0.0, 0.18, 0.05, 30), lf=(-0.3, 0.18, 0, 20), plant="left")),
            K(0.9, "reverse (balance)", plant="right",
              **_merge(STANDING, body=(0, -10, 0), rh=(0.35, -0.2, 0.1), lh=(-0.1, -0.35, 0.5), tor=(35, -20, 0), pel=(-0.15, -10, 8),
                       rf=(0.1, 0.18, 0, 20), lf=(-0.35, 0.14, 0.3, 10))),
            K(1.0, "recover", **_merge(STANDING, body=(0, 0, 0))),
        ]
        for k in keys[:-1]:
            # The whole body turns ~180 degrees: feet travel with it, so they must not be locked.
            k["left_foot_planted"] = k["right_foot_planted"] = False
        return {"keys": keys, "duration": 2.2, "loop": False, "view": "front"}
    # Overhand throw (baseball pitch / quarterback / javelin-style / cricket bowl simplified).
    stride = 0.35 if variant in ("baseball_pitch", "javelin") else 0.28
    base = dict(rf=(0.0, 0.16, 0, 15), lf=(0.0, 0.16, 0, 15))
    keys = [
        K(0.0, "set", **_merge(base, rh=(0.25, -0.2, 0.05), lh=(0.25, -0.2, 0.05), pel=(-0.04, 0, 2), tor=(8, 0, 0))),
        K(0.22, "leg lift / coil", plant="right",
          **_merge(base, rh=(0.2, -0.25, 0.1), lh=(0.2, -0.25, 0.05), pel=(-0.06, 35, 0), tor=(5, 50 * a, 0),
                   lf=(0.15, 0.1, 0.35 if variant == "baseball_pitch" else 0.15, 15))),
        K(0.45, "stride + arm back", plant="right", re="out",
          **_merge(base, rh=(-0.3, -0.05, 0.45), lh=(0.45, 0.0, 0.05), pel=(-0.12, 30, 2), tor=(5, 55 * a, 0),
                   lf=(stride * 0.8, 0.12, 0.1, 25))),
        K(0.58, "foot plant + cock", re="up",
          **_merge(base, rh=(-0.12, 0.28, 0.42), lh=(0.4, -0.05, 0.1), pel=(-0.15, 0, 4), tor=(-5, 45 * a, 8),
                   lf=(stride, 0.12, 0, 30), rf=(-0.15, 0.16, 0, 15), head=(0, -20, 0))),
        K(0.68, "acceleration", re="up",
          **_merge(base, rh=(0.12, 0.35, 0.3), lh=(0.2, -0.3, 0.2), pel=(-0.15, -35, 6), tor=(15, -5, 0),
                   lf=(stride, 0.12, 0, 30), rf=(-0.15, 0.16, 0, 15))),
        K(0.74, "release", re="forward",
          **_merge(base, rh=(0.5, 0.2, 0.15), lh=(0.1, -0.35, 0.3), pel=(-0.15, -45, 8), tor=(30, -30, 0),
                   lf=(stride, 0.12, 0, 30), rf=(-0.15, 0.16, 0.05, 15))),
        K(0.88, "follow-through", plant="left",
          **_merge(base, rh=(0.35, -0.5, -0.25), lh=(0.0, -0.4, 0.35), pel=(-0.18, -50, 12), tor=(50, -45, 0),
                   lf=(stride, 0.12, 0, 30), rf=(-0.05, 0.16, 0.2, 15))),
        K(1.0, "fielding position", **_merge(READY)),
    ]
    return {"keys": keys, "duration": 1.8, "loop": False, "view": "three_quarter"}


def tpl_punch(variant: str, amp: float) -> Dict[str, Any]:
    """Boxing combinations from orthodox stance. variant: tokens like 'jab-cross-hook-uppercut'."""
    stance = dict(rf=(-0.2, 0.17, 0, 25), lf=(0.22, 0.1, 0, 15), pel=(-0.07, 20, 4), tor=(12, 25, 0),
                  rh=(0.22, 0.06, 0.12), lh=(0.3, 0.08, 0.12), head=(10, -15, 0))
    shots = {
        "jab": [dict(lh=(0.62, 0.03, 0.02), tor=(12, 15, 0), pel=(-0.07, 15, 4))],
        "cross": [dict(rh=(0.62, 0.03, -0.02), tor=(14, -35, 0), pel=(-0.07, -15, 4), rf=(-0.2, 0.17, 0.04, 40))],
        "hook": [dict(lh=(0.35, 0.03, -0.05), tor=(12, -30, 0), pel=(-0.08, -5, 4), le="out", lf=(0.22, 0.1, 0.02, 45))],
        "uppercut": [dict(pel=(-0.15, 10, 4), tor=(20, 10, 0), rh=(0.2, -0.3, 0.12)),
                     dict(rh=(0.35, 0.15, 0.02), tor=(8, -25, 0), pel=(-0.05, -10, 4))],
        "lead_uppercut": [dict(pel=(-0.15, 30, 4), tor=(20, 35, 0)), dict(lh=(0.35, 0.15, 0.02), tor=(8, 0, 0))],
        "rear_hook": [dict(rh=(0.35, 0.03, -0.05), tor=(12, -45, 0), pel=(-0.08, -25, 4), re="out",
                           rf=(-0.2, 0.17, 0.04, 45))],
        "slip": [dict(tor=(18, 15, 20), pel=(-0.12, 20, 4))],
        "body_hook": [dict(lh=(0.38, -0.3, -0.05), tor=(28, -30, -10), pel=(-0.18, -5, 6), le="out", lf=(0.22, 0.1, 0.02, 45))],
        "roll": [dict(pel=(-0.24, 20, 6), tor=(28, 25, 18)), dict(pel=(-0.24, 20, 6), tor=(28, 25, -18))],
        "duck": [dict(pel=(-0.25, 20, 6), tor=(25, 25, 0))],
    }
    tokens = [t.strip().lower().replace(" ", "_") for t in variant.replace(",", "-").split("-") if t.strip()]
    tokens = [difflib.get_close_matches(t, list(shots), 1, 0.5)[0] for t in tokens
              if difflib.get_close_matches(t, list(shots), 1, 0.5)] or ["jab", "cross"]
    keys = [K(0, "guard", **stance)]
    t = 0.0
    for tok in tokens[:6]:
        for part in shots[tok]:
            t += 0.22
            over = dict(part)
            re, le = over.pop("re", "down"), over.pop("le", "down")
            keys.append(K(t, tok, re=re, le=le, **_merge(stance, **over)))
        t += 0.2
        keys.append(K(t, "back to guard", **stance))
    total = t + 0.15
    keys = retime(keys, [k["t"] / total for k in keys])
    return {"keys": keys, "duration": max(0.8, total * 0.75 / max(amp, 0.6)), "loop": False, "view": "three_quarter"}


def tpl_kick(variant: str, amp: float) -> Dict[str, Any]:
    a = amp
    if variant in ("front_kick", "martial_arts_front_kick", "push_kick"):
        guard = dict(rh=(0.22, 0.05, 0.12), lh=(0.3, 0.08, 0.12), pel=(-0.06, 15, 4), tor=(10, 15, 0),
                     rf=(-0.15, 0.15, 0, 20), lf=(0.15, 0.1, 0, 15))
        keys = [K(0.0, "guard", **guard),
                K(0.3, "chamber knee", plant="left", **_merge(guard, rf=(0.25, 0.1, 0.55 * a, 10), tor=(0, 5, 0))),
                K(0.5, "extend", plant="left", **_merge(guard, rf=(0.62, 0.08, 0.6 * a, 10), tor=(-10, 0, 0))),
                K(0.7, "re-chamber", plant="left", **_merge(guard, rf=(0.25, 0.1, 0.5 * a, 10), tor=(0, 5, 0))),
                K(1.0, "guard", **guard)]
        return {"keys": keys, "duration": 1.3, "loop": False, "view": "side"}
    if variant in ("roundhouse_kick", "side_kick"):
        guard = dict(rh=(0.22, 0.05, 0.12), lh=(0.3, 0.08, 0.12), pel=(-0.06, 15, 4), tor=(10, 15, 0),
                     rf=(-0.15, 0.15, 0, 20), lf=(0.15, 0.1, 0, 15))
        keys = [K(0.0, "guard", **guard),
                K(0.3, "chamber + pivot", plant="left",
                  **_merge(guard, rf=(0.2, 0.25, 0.5 * a, 30), pel=(-0.06, -40, 0, -10), tor=(10, -30, 15),
                           lf=(0.15, 0.1, 0, 70))),
                K(0.48, "extend", plant="left",
                  **_merge(guard, rf=(0.35, 0.5, 0.75 * a, 40), pel=(-0.06, -60, 0, -20), tor=(5, -50, 30),
                           lf=(0.15, 0.1, 0, 80), lh=(0.25, -0.2, 0.3))),
                K(0.68, "re-chamber", plant="left",
                  **_merge(guard, rf=(0.2, 0.25, 0.45 * a, 30), pel=(-0.06, -35, 0, -10), tor=(10, -25, 15),
                           lf=(0.15, 0.1, 0, 60))),
                K(1.0, "guard", **guard)]
        return {"keys": keys, "duration": 1.4, "loop": False, "view": "front"}
    if variant in ("soccer_pass", "inside_foot_pass"):
        # Inside-of-the-foot pass: plant foot beside the ball, kicking leg turned out (toe_out 70)
        # so the inside of the foot faces the target, short controlled swing, firm ankle.
        arms = dict(rh=(0.1, -0.45, 0.4), lh=(0.1, -0.45, 0.4))
        keys = [
            K(0.0, "approach", **_merge(STANDING, **arms, pel=(-0.06, 0, 4), tor=(12, 0, 0),
                                        rf=(-0.05, 0.12, 0, 10), lf=(0.05, 0.12, 0, 10))),
            K(0.3, "plant beside ball", plant="left",
              **_merge(STANDING, **arms, pel=(-0.1, 0, 4), tor=(14, 0, 0), lf=(0.1, 0.18, 0, 10),
                       rf=(-0.2, 0.12, 0.12, 60))),
            K(0.5, "backswing, foot turned out", plant="left",
              **_merge(STANDING, rh=(0.0, -0.4, 0.45), lh=(0.2, -0.3, 0.45), pel=(-0.12, 10, 4), tor=(14, 5, 0),
                       lf=(0.1, 0.18, 0, 10), rf=(-0.25, 0.14, 0.18, 70))),
            K(0.66, "contact (inside of foot)", plant="left",
              **_merge(STANDING, rh=(0.15, -0.4, 0.4), lh=(0.15, -0.35, 0.45), pel=(-0.12, -5, 4), tor=(18, -5, 0),
                       lf=(0.1, 0.18, 0, 10), rf=(0.12, 0.06, 0.1, 75))),
            K(0.8, "short follow-through", plant="left",
              **_merge(STANDING, **arms, pel=(-0.1, -10, 4), tor=(16, -8, 0),
                       lf=(0.1, 0.18, 0, 10), rf=(0.3, 0.04, 0.14, 70))),
            K(1.0, "set", **_merge(STANDING, **arms, pel=(-0.06, 0, 4), tor=(12, 0, 0),
                                   rf=(0.15, 0.14, 0, 15), lf=(0.05, 0.14, 0, 10))),
        ]
        return {"keys": keys, "duration": 1.4, "loop": False, "view": "three_quarter"}
    if variant in ("knee_strike",):
        guard = dict(rh=(0.25, 0.1, 0.15), lh=(0.28, 0.1, 0.15), pel=(-0.06, 10, 4), tor=(10, 10, 0),
                     rf=(-0.15, 0.15, 0, 20), lf=(0.15, 0.1, 0, 15))
        keys = [K(0.0, "clinch", **guard),
                K(0.4, "drive knee", plant="left", **_merge(guard, rf=(0.3, 0.05, 0.6 * a, 5), tor=(-10, 0, 0),
                                                            rh=(0.4, -0.15, 0.05), lh=(0.4, -0.15, 0.05))),
                K(1.0, "clinch", **guard)]
        return {"keys": keys, "duration": 1.0, "loop": False, "view": "side"}
    # Soccer instep shot (default). Sagittal leg swing: plant foot beside the ball, kicking knee
    # cocked behind, knee drives forward over the ball, shin snaps through, follow-through up the
    # line of the shot and land on the kicking foot. Left arm out wide for balance, right arm
    # swings back then forward in counter-rotation. No sideways leg motion.
    arms_ready = dict(rh=(0.12, -0.5, 0.3), lh=(0.12, -0.5, 0.3))
    keys = [
        K(0.0, "last stride", plant="right",
          **_merge(STANDING, **arms_ready, pel=(-0.04, 0, 4), tor=(12, 0, 0),
                   rf=(0.05, 0.11, 0, 5), lf=(-0.25, 0.11, 0.25, 5))),
        K(0.25, "plant foot beside ball", plant="left",
          **_merge(STANDING, pel=(-0.1, 10, 4, -4), tor=(8, 15, -6),
                   lf=(0.12, 0.16, 0, 8), rf=(-0.22, 0.1, 0.3, 0),
                   rh=(-0.15, -0.4, 0.38), lh=(0.2, -0.2, 0.55))),
        K(0.42, "backswing (knee cocked)", plant="left", re="back",
          **_merge(STANDING, pel=(-0.12, 18 * a, 2, -5), tor=(2, 25 * a, -8),
                   lf=(0.12, 0.16, 0, 8), rf=(-0.32, 0.08, 0.5 * a, 0),
                   rh=(-0.25, -0.35, 0.35), lh=(0.25, -0.1, 0.62))),
        K(0.54, "knee drives over ball", plant="left",
          **_merge(STANDING, pel=(-0.12, 0, 6, -5), tor=(12, 0, -6),
                   lf=(0.12, 0.16, 0, 8), rf=(0.02, 0.08, 0.3, 0),
                   rh=(0.0, -0.45, 0.3), lh=(0.3, -0.15, 0.55))),
        K(0.6, "contact (laces)", plant="left",
          **_merge(STANDING, pel=(-0.12, -15 * a, 6, -5), tor=(18, -15 * a, -5),
                   lf=(0.12, 0.16, 0, 8), rf=(0.22, 0.08, 0.1, 0),
                   rh=(0.15, -0.45, 0.22), lh=(0.25, -0.2, 0.5))),
        K(0.75, "follow-through", plant="left",
          **_merge(STANDING, pel=(-0.1, -25 * a, 4, -4), tor=(10, -25 * a, -3),
                   lf=(0.12, 0.16, 0, 8), rf=(0.5, 0.08, 0.45 * a, 0),
                   rh=(0.3, -0.35, 0.1), lh=(0.05, -0.35, 0.45))),
        K(0.9, "land on kicking foot", plant="right",
          **_merge(STANDING, pel=(-0.12, -10, 6), tor=(18, -5, 0),
                   rf=(0.3, 0.12, 0, 5), lf=(-0.15, 0.12, 0.15, 5),
                   rh=(0.2, -0.4, 0.3), lh=(0.0, -0.45, 0.35))),
        K(1.0, "balanced", **_merge(STANDING, **arms_ready, pel=(-0.06, 0, 4), tor=(12, 0, 0),
                                   rf=(0.15, 0.12, 0, 5), lf=(-0.05, 0.12, 0, 5))),
    ]
    return {"keys": keys, "duration": 1.5, "loop": False, "view": "side"}


def tpl_jump(variant: str, amp: float) -> Dict[str, Any]:
    a = amp
    if variant == "jumping_jack":
        closed = K(0.0, "feet together", rh=HANG, lh=HANG, rf=(0, 0.1, 0, 10), lf=(0, 0.1, 0, 10), pel=(-0.05, 0, 0))
        up = K(0.25, "hop out", plant="none", rh=(0.05, -0.05, 0.85), lh=(0.05, -0.05, 0.85),
               rf=(0, 0.3, 0.02, 15), lf=(0, 0.3, 0.02, 15), pel=(0.1 * a, 0, 0))
        open_ = K(0.5, "wide + hands overhead", rh=(0.05, 0.65, 0.27), lh=(0.05, 0.65, 0.27),
                  rf=(0, 0.42, 0, 20), lf=(0, 0.42, 0, 20), pel=(-0.08, 0, 0))
        down = K(0.75, "hop in", plant="none", rh=(0.05, -0.05, 0.85), lh=(0.05, -0.05, 0.85),
                 rf=(0, 0.3, 0.02, 15), lf=(0, 0.3, 0.02, 15), pel=(0.1 * a, 0, 0))
        return {"keys": [closed, up, open_, down], "duration": 1.0, "loop": True, "view": "front"}
    if variant == "jump_rope":
        k0 = K(0.0, "land", rh=(0.15, -0.5, 0.35), lh=(0.15, -0.5, 0.35), rf=(0, 0.1, 0, 5), lf=(0, 0.1, 0, 5),
               pel=(-0.05, 0, 0), re="down", le="down")
        k1 = K(0.5, "hop", plant="none", rh=(0.1, -0.45, 0.38), lh=(0.1, -0.45, 0.38), rf=(0, 0.1, 0.03, 5),
               lf=(0, 0.1, 0.03, 5), pel=(0.08 * a, 0, 0))
        return {"keys": [k0, k1], "duration": 0.45, "loop": True, "view": "front"}
    if variant in ("skater_jump", "lateral_bound", "lateral_hops"):
        k0 = K(0.0, "land on right", plant="right", rf=(0, 0.3, 0, 15), lf=(-0.25, -0.05, 0.12, 10),
               pel=(-0.22, 10, 6, 5), tor=(35, -10, 0), rh=(0.0, -0.45, -0.2), lh=(-0.2, -0.45, 0.4))
        k1 = K(0.25, "push off", plant="none", rf=(0, 0.25, 0.05, 15), lf=(0, 0.25, 0.08, 15), pel=(0.15 * a, 0, 4),
               tor=(20, 0, 0), rh=(0.15, -0.3, 0.2), lh=(0.15, -0.3, 0.2))
        keys = [k0, k1, swap_sides(k0, 0.5, "land on left"), swap_sides(k1, 0.75, "push off")]
        return {"keys": keys, "duration": 1.2, "loop": True, "view": "front"}
    if variant == "box_jump":
        pass
    if variant in ("broad_jump", "standing_long_jump"):
        keys = [
            K(0.0, "stand", **_merge(STANDING, rf=(0, 0.14, 0, 10), lf=(0, 0.14, 0, 10))),
            K(0.3, "swing arms back + load", re="back", le="back",
              **_merge(STANDING, rh=(-0.4, -0.35, 0.3), lh=(-0.4, -0.35, 0.3), pel=(-0.3, 0, 14), tor=(55, 0, 0))),
            K(0.45, "drive forward", plant="none",
              **_merge(STANDING, rh=(0.45, 0.35, 0.25), lh=(0.45, 0.35, 0.25), pel=(0.1, 0, 0), tor=(25, 0, 0),
                       body=(20, 0, 0), rf=(-0.1, 0.14, 0.05, 10), lf=(-0.1, 0.14, 0.05, 10))),
            K(0.62, "flight, knees forward", plant="none",
              **_merge(STANDING, rh=(0.45, 0.1, 0.25), lh=(0.45, 0.1, 0.25), pel=(0.3, 0, 0), tor=(20, 0, 0),
                       body=(5, 0, 0), rf=(0.25, 0.14, 0.35, 10), lf=(0.25, 0.14, 0.35, 10))),
            K(0.8, "stick the landing", **_merge(STANDING, rh=(0.45, -0.2, 0.25), lh=(0.45, -0.2, 0.25),
                                                 pel=(-0.32, 0, 14), tor=(40, 0, 0))),
            K(1.0, "stand", **_merge(STANDING, rf=(0, 0.14, 0, 10), lf=(0, 0.14, 0, 10))),
        ]
        return {"keys": keys, "duration": 1.8, "loop": False, "view": "side"}
    tuck = variant in ("tuck_jump",)
    squat_jump = variant in ("squat_jump", "box_jump")
    load_h = -0.4 if squat_jump else -0.25
    keys = [
        K(0.0, "stand", **_merge(STANDING, pel=(0, 0, 0), rf=(0, 0.14, 0, 10), lf=(0, 0.14, 0, 10))),
        K(0.3, "load (arms back)", re="back", le="back",
          **_merge(STANDING, rh=(-0.35, -0.42, 0.3), lh=(-0.35, -0.42, 0.3), pel=(load_h, 0, 12), tor=(40, 0, 0),
                   rf=(0, 0.14, 0, 12), lf=(0, 0.14, 0, 12))),
        K(0.45, "explode", plant="none",
          **_merge(STANDING, rh=(0.25, 0.5, 0.25), lh=(0.25, 0.5, 0.25), pel=(0.15 * a, 0, 0), tor=(0, 0, 0),
                   rf=(0, 0.14, 0.02, 10), lf=(0, 0.14, 0.02, 10))),
        K(0.6, "peak" + (" tuck" if tuck else ""), plant="none",
          **_merge(STANDING, rh=(0.3, 0.3 if not tuck else -0.15, 0.25), lh=(0.3, 0.3 if not tuck else -0.15, 0.25),
                   pel=(0.4 * a, 0, 0), tor=(5 if not tuck else 25, 0, 0),
                   rf=(0.1 if tuck else 0, 0.14, 0.45 if tuck else 0.03, 10),
                   lf=(0.1 if tuck else 0, 0.14, 0.45 if tuck else 0.03, 10))),
        K(0.75, "descend", plant="none",
          **_merge(STANDING, rh=(0.3, -0.1, 0.3), lh=(0.3, -0.1, 0.3), pel=(0.12, 0, 0),
                   rf=(0, 0.14, 0.04, 10), lf=(0, 0.14, 0.04, 10))),
        K(0.85, "soft landing", **_merge(STANDING, rh=(0.35, -0.3, 0.28), lh=(0.35, -0.3, 0.28), pel=(-0.25, 0, 10),
                                         tor=(35, 0, 0), rf=(0, 0.14, 0, 12), lf=(0, 0.14, 0, 12))),
        K(1.0, "stand", **_merge(STANDING, pel=(0, 0, 0), rf=(0, 0.14, 0, 10), lf=(0, 0.14, 0, 10))),
    ]
    return {"keys": keys, "duration": 1.8, "loop": False, "view": "side"}


def tpl_strength(variant: str, amp: float) -> Dict[str, Any]:
    a = amp
    if variant in ("squat", "goblet_squat", "sumo_squat", "air_squat"):
        wide = 0.32 if variant == "sumo_squat" else 0.2
        toe = 40 if variant == "sumo_squat" else 22
        hands_low = (0.3, -0.2, 0.05) if variant == "goblet_squat" else HANG
        hands_bottom = (0.32, -0.05, 0.05) if variant == "goblet_squat" else (0.55, 0.0, 0.22)
        grip = variant == "goblet_squat"
        top = K(0.0, "stand tall", grip=grip, rh=hands_low, lh=hands_low, rf=(0, wide, 0, toe), lf=(0, wide, 0, toe))
        mid = K(0.35, "hips back + down", grip=grip, rh=(0.45, -0.15, 0.2) if not grip else hands_bottom,
                lh=(0.45, -0.15, 0.2) if not grip else hands_bottom, pel=(-0.22 * a, 0, 15), tor=(30, 0, 0),
                rf=(0, wide, 0, toe), lf=(0, wide, 0, toe))
        bottom = K(0.55, "bottom (thighs parallel)", grip=grip, rh=hands_bottom, lh=hands_bottom,
                   pel=(-0.42 * a, 0, 18), tor=(38, 0, 0), rf=(0, wide, 0, toe), lf=(0, wide, 0, toe))
        drive = K(0.78, "drive up", grip=grip, rh=(0.4, -0.2, 0.2) if not grip else hands_bottom,
                  lh=(0.4, -0.2, 0.2) if not grip else hands_bottom, pel=(-0.15, 0, 10), tor=(22, 0, 0),
                  rf=(0, wide, 0, toe), lf=(0, wide, 0, toe))
        end = copy.deepcopy(top); end["t"] = 1.0
        return {"keys": [top, mid, bottom, drive, end], "duration": 2.6, "loop": False, "view": "side"}
    if variant in ("lunge", "forward_lunge", "reverse_lunge", "walking_lunge", "split_squat"):
        hips = dict(rh=(0.0, -0.45, 0.35), lh=(0.0, -0.45, 0.35), re="out", le="out")
        top = K(0.0, "stand", **_merge(STANDING, **{k: v for k, v in hips.items() if k in ("rh", "lh")}), re="out", le="out")
        step = K(0.3, "step", plant="none", re="out", le="out", rh=hips["rh"], lh=hips["lh"],
                 rf=(0.3 if variant != "reverse_lunge" else -0.3, 0.12, 0.08, 10), lf=(0, 0.12, 0, 10), pel=(-0.05, 0, 0))
        front = 0.45 if variant != "reverse_lunge" else 0.0
        backf = -0.05 if variant != "reverse_lunge" else -0.5
        if variant == "reverse_lunge":
            bottom_feet = dict(rf=(-0.5, 0.12, 0.04, 5), lf=(0.0, 0.12, 0, 10))
        else:
            bottom_feet = dict(rf=(front, 0.12, 0, 10), lf=(-0.45, 0.12, 0.04, 5))
        bottom = K(0.55, "bottom (back knee low)", re="out", le="out", rh=hips["rh"], lh=hips["lh"],
                   pel=(-0.32 * a, 0, 0), tor=(5, 0, 0), **bottom_feet)
        hold = copy.deepcopy(bottom); hold["t"] = 0.65; hold["phase"] = "hold"
        back = K(0.85, "push back", plant="none", re="out", le="out", rh=hips["rh"], lh=hips["lh"],
                 rf=(0.25 if variant != "reverse_lunge" else -0.25, 0.12, 0.08, 10), lf=(0, 0.12, 0, 10),
                 pel=(-0.05, 0, 0))
        end = copy.deepcopy(top); end["t"] = 1.0
        _ = backf
        return {"keys": [top, step, bottom, hold, back, end], "duration": 2.6, "loop": False, "view": "side"}
    if variant in ("lunge_with_twist", "lunge_rotation"):
        hands = (0.35, -0.15, 0.0)
        top = K(0.0, "stand", grip=True, rh=hands, lh=hands)
        down = K(0.3, "lunge down (right leg forward)", grip=True, rh=hands, lh=hands, pel=(-0.32 * a, 0, 0),
                 rf=(0.45, 0.12, 0, 10), lf=(-0.45, 0.12, 0.04, 5), plant="none")
        twist = K(0.5, "rotate over the front knee", grip=True, rh=(0.35, -0.1, 0.3), lh=(0.35, -0.1, 0.3),
                  pel=(-0.32 * a, 0, 0), tor=(5, 50 * a, 0), rf=(0.45, 0.12, 0, 10), lf=(-0.45, 0.12, 0.04, 5))
        back = K(0.7, "untwist", grip=True, rh=hands, lh=hands, pel=(-0.32 * a, 0, 0), rf=(0.45, 0.12, 0, 10),
                 lf=(-0.45, 0.12, 0.04, 5))
        end = copy.deepcopy(top); end["t"] = 1.0
        return {"keys": [top, down, twist, back, end], "duration": 3.0, "loop": False, "view": "three_quarter"}
    if variant in ("lateral_lunge", "side_lunge", "cossack_squat"):
        top = K(0.0, "stand", rh=(0.25, -0.3, 0.1), lh=(0.25, -0.3, 0.1), rf=(0, 0.14, 0, 10), lf=(0, 0.14, 0, 10))
        bottom = K(0.5, "sit into right hip", rh=(0.5, -0.15, 0.05), lh=(0.5, -0.15, 0.05), rf=(0, 0.45, 0, 25),
                   lf=(0, 0.35, 0, 20), pel=(-0.3 * a, 0, 15, -10), tor=(30, 0, -5))
        end = copy.deepcopy(top); end["t"] = 1.0
        return {"keys": [top, bottom, end], "duration": 2.2, "loop": False, "view": "front"}
    if variant in ("deadlift", "romanian_deadlift", "good_morning", "kettlebell_swing"):
        swing = variant == "kettlebell_swing"
        top = K(0.0, "stand", grip=True, rh=(0.15, -0.6, 0.12), lh=(0.15, -0.6, 0.12), rf=(0, 0.16, 0, 10), lf=(0, 0.16, 0, 10))
        hinge = K(0.45, "hip hinge", grip=True, rh=(0.25, -0.62, 0.12) if not swing else (-0.05, -0.62, 0.05),
                  lh=(0.25, -0.62, 0.12), pel=(-0.1, 0, 20), tor=(70 * a if not swing else 55, 0, 0),
                  rf=(0, 0.16, 0, 10), lf=(0, 0.16, 0, 10))
        if swing:
            snap = K(0.75, "hip snap, bell to chest height", grip=True, rh=(0.62, -0.05, 0.05), lh=(0.62, -0.05, 0.05),
                     pel=(0, 0, -4), tor=(0, 0, 0), rf=(0, 0.2, 0, 10), lf=(0, 0.2, 0, 10))
            return {"keys": [top, hinge, snap], "duration": 1.4, "loop": True, "view": "side"}
        end = copy.deepcopy(top); end["t"] = 1.0
        return {"keys": [top, hinge, end], "duration": 2.6, "loop": False, "view": "side"}
    if variant in ("single_leg_rdl", "single_leg_deadlift"):
        top = K(0.0, "stand on left", plant="left", rh=HANG, lh=HANG, rf=(0, 0.12, 0.03, 10), lf=(0, 0.12, 0, 10))
        bottom = K(0.5, "hinge, right leg back", plant="left", rh=(0.15, -0.62, 0.25), lh=(0.15, -0.62, 0.25),
                   body=(60 * a, 0, 0), tor=(10, 0, 0), lf=(0.25, 0.1, 0, 10), rf=(-0.15, 0.12, 0.0, 0), pel=(-0.05, 0, 0))
        end = copy.deepcopy(top); end["t"] = 1.0
        return {"keys": [top, bottom, end], "duration": 2.6, "loop": False, "view": "side"}
    if variant in ("overhead_press", "push_press", "shoulder_press"):
        rack = (0.15, 0.02, 0.32)
        top = K(0.0, "rack", re="down", le="down", rh=rack, lh=rack, rf=(0, 0.16, 0, 10), lf=(0, 0.16, 0, 10))
        dip = K(0.3, "dip" if variant == "push_press" else "brace", re="down", le="down", rh=rack, lh=rack,
                pel=(-0.1 if variant == "push_press" else 0, 0, 0), rf=(0, 0.16, 0, 10), lf=(0, 0.16, 0, 10))
        lock = K(0.6, "lockout overhead", re="out", le="out", rh=(0.05, 0.63, 0.25), lh=(0.05, 0.63, 0.25),
                 rf=(0, 0.16, 0, 10), lf=(0, 0.16, 0, 10))
        end = copy.deepcopy(top); end["t"] = 1.0
        return {"keys": [top, dip, lock, end], "duration": 2.2, "loop": False, "view": "side"}
    if variant in ("bent_over_row", "row"):
        base = dict(tor=(55, 0, 0), pel=(-0.12, 0, 20), rf=(0, 0.16, 0, 10), lf=(0, 0.16, 0, 10))
        k0 = K(0.0, "arms long", re="back", le="back", **_merge(base, rh=(0.15, -0.62, 0.18), lh=(0.15, -0.62, 0.18)))
        k1 = K(0.5, "pull to ribs", re="back", le="back", **_merge(base, rh=(0.12, -0.42, 0.3), lh=(0.12, -0.42, 0.3)))
        return {"keys": [k0, k1], "duration": 2.0, "loop": True, "view": "side"}
    if variant in ("bicep_curl", "curl"):
        k0 = K(0.0, "arms long", rh=HANG, lh=HANG)
        k1 = K(0.5, "curl up", rh=(0.25, -0.05, 0.3), lh=(0.25, -0.05, 0.3))
        return {"keys": [k0, k1], "duration": 2.0, "loop": True, "view": "side"}
    if variant in ("arm_circles",):
        def ac(t, ang):
            import math as _m
            a_ = _m.radians(ang)
            hand = (0.05 + 0.18 * _m.sin(a_), 0.18 * _m.cos(a_), 0.92)
            return K(t, "circle", rh=hand, lh=hand)
        return {"keys": [ac(i / 6, i * 60) for i in range(6)], "duration": 1.2, "loop": True, "view": "front"}
    if variant in ("calf_raise",):
        k0 = K(0.0, "flat", rh=(0.0, -0.45, 0.35), lh=(0.0, -0.45, 0.35), re="out", le="out")
        k1 = K(0.5, "up on toes", rh=(0.0, -0.45, 0.35), lh=(0.0, -0.45, 0.35), re="out", le="out", pel=(0.08, 0, 0))
        return {"keys": [k0, k1], "duration": 1.6, "loop": True, "view": "side"}
    raise KeyError(variant)


def tpl_floor(variant: str, amp: float) -> Dict[str, Any]:
    a = amp
    plank_feet = dict(rf=(0, 0.12, 0, 5), lf=(0, 0.12, 0, 5))
    if variant in ("push_up", "pushup"):
        up = K(0.0, "plank (arms straight)", plant="none", body=(78, 0, 0), rh=(0.0, -0.6, 0.32), lh=(0.0, -0.6, 0.32),
               re="back", le="back", **plank_feet)
        down = K(0.45, "chest to floor", plant="none", body=(82, 0, 0), rh=(0.05, -0.3, 0.42), lh=(0.05, -0.3, 0.42),
                 re="back", le="back", **plank_feet)
        hold = copy.deepcopy(down); hold["t"] = 0.55
        return {"keys": [up, down, hold], "duration": 2.0, "loop": True, "view": "side"}
    if variant in ("plank", "forearm_plank"):
        forearm = variant == "forearm_plank"
        k0 = K(0.0, "hold", plant="none", body=(80 if forearm else 76, 0, 0),
               rh=(0.25, -0.35, 0.2) if forearm else (0.0, -0.6, 0.32), lh=(0.25, -0.35, 0.2) if forearm else (0.0, -0.6, 0.32),
               re="back", le="back", **plank_feet)
        k1 = copy.deepcopy(k0); k1["t"] = 0.5; k1["head"] = {"nod": 8}
        return {"keys": [k0, k1], "duration": 3.0, "loop": True, "view": "side"}
    if variant in ("mountain_climber", "mountain_climbers"):
        k0 = K(0.0, "right knee in", plant="none", body=(70, 0, 0), rh=(0.0, -0.6, 0.32), lh=(0.0, -0.6, 0.32),
               re="back", le="back", rf=(0.2, 0.12, 0.45 * a, 5), lf=(0, 0.12, 0, 5))
        k1 = swap_sides(k0, 0.5, "left knee in")
        return {"keys": [k0, k1], "duration": 0.7, "loop": True, "view": "side"}
    if variant in ("burpee",):
        keys = [
            K(0.0, "stand", rh=HANG, lh=HANG),
            K(0.15, "squat, hands down", rh=(0.55, -0.45, 0.25), lh=(0.55, -0.45, 0.25), pel=(-0.45, 0, 18), tor=(55, 0, 0),
              rf=(0, 0.16, 0, 20), lf=(0, 0.16, 0, 20)),
            K(0.3, "jump feet back to plank", plant="none", body=(76, 0, 0), rh=(0.0, -0.6, 0.32), lh=(0.0, -0.6, 0.32),
              re="back", le="back", **plank_feet),
            K(0.42, "push-up bottom", plant="none", body=(82, 0, 0), rh=(0.05, -0.3, 0.42), lh=(0.05, -0.3, 0.42),
              re="back", le="back", **plank_feet),
            K(0.52, "push up", plant="none", body=(76, 0, 0), rh=(0.0, -0.6, 0.32), lh=(0.0, -0.6, 0.32),
              re="back", le="back", **plank_feet),
            K(0.64, "feet to hands", rh=(0.55, -0.45, 0.25), lh=(0.55, -0.45, 0.25), pel=(-0.45, 0, 18), tor=(55, 0, 0),
              rf=(0, 0.16, 0, 20), lf=(0, 0.16, 0, 20)),
            K(0.78, "jump, arms overhead", plant="none", rh=(0.05, 0.63, 0.22), lh=(0.05, 0.63, 0.22), pel=(0.35 * a, 0, 0),
              rf=(0, 0.14, 0.03, 10), lf=(0, 0.14, 0.03, 10)),
            K(0.9, "land", rh=(0.3, -0.3, 0.3), lh=(0.3, -0.3, 0.3), pel=(-0.22, 0, 10), tor=(30, 0, 0)),
            K(1.0, "stand", rh=HANG, lh=HANG),
        ]
        return {"keys": keys, "duration": 3.2, "loop": False, "view": "side"}
    if variant in ("sit_up", "crunch"):
        lie = K(0.0, "lying", plant="none", body=(-85, 0, 0), rh=(0.15, 0.1, 0.2), lh=(0.15, 0.1, 0.2), re="out", le="out",
                rf=(0.25, 0.14, 0.35, 10), lf=(0.25, 0.14, 0.35, 10))
        up = K(0.5, "curl up", plant="none", body=(-85, 0, 0), tor=(-60 if variant == "sit_up" else -30, 0, 0),
               rh=(0.15, 0.1, 0.2), lh=(0.15, 0.1, 0.2), re="out", le="out",
               rf=(0.25, 0.14, 0.35, 10), lf=(0.25, 0.14, 0.35, 10), head=(25, 0, 0))
        return {"keys": [lie, up], "duration": 2.0, "loop": True, "view": "side"}
    if variant in ("glute_bridge", "hip_bridge"):
        lie = K(0.0, "lying", plant="none", body=(-85, 0, 0), rh=(-0.05, -0.55, 0.35), lh=(-0.05, -0.55, 0.35),
                rf=(0.25, 0.14, 0.35, 10), lf=(0.25, 0.14, 0.35, 10))
        up = K(0.5, "hips up", plant="none", body=(-62, 0, 0), tor=(-20, 0, 0), rh=(-0.05, -0.55, 0.35),
               lh=(-0.05, -0.55, 0.35), rf=(0.35, 0.14, 0.45, 10), lf=(0.35, 0.14, 0.45, 10))
        return {"keys": [lie, up], "duration": 2.0, "loop": True, "view": "side"}
    if variant in ("russian_twist",):
        base = dict(body=(-50, 0, 0), plant="none", rf=(0.3, 0.12, 0.38, 10), lf=(0.3, 0.12, 0.38, 10))
        k0 = K(0.0, "twist right", grip=True, body=(-50, 0, 0), plant="none", rf=base["rf"], lf=base["lf"],
               tor=(25, 45 * a, 0), rh=(0.4, -0.35, 0.05), lh=(0.4, -0.35, 0.05))
        k1 = swap_sides(k0, 0.5, "twist left")
        return {"keys": [k0, k1], "duration": 1.6, "loop": True, "view": "three_quarter"}
    if variant in ("inchworm", "inchworm_walkout"):
        keys = [
            K(0.0, "stand", rh=HANG, lh=HANG),
            K(0.18, "hinge, hands to floor", rh=(0.35, -0.62, 0.2), lh=(0.35, -0.62, 0.2), tor=(85, 0, 0), pel=(-0.04, 0, 25)),
            K(0.34, "walk hands out", plant="none", rh=(0.25, -0.6, 0.25), lh=(0.25, -0.6, 0.25), body=(45, 0, 0),
              tor=(40, 0, 0), re="back", le="back"),
            K(0.5, "plank", plant="none", body=(76, 0, 0), rh=(0.0, -0.6, 0.32), lh=(0.0, -0.6, 0.32), re="back", le="back"),
            K(0.58, "plank hold", plant="none", body=(76, 0, 0), rh=(0.0, -0.6, 0.32), lh=(0.0, -0.6, 0.32), re="back", le="back"),
            K(0.75, "walk hands back", plant="none", rh=(0.25, -0.6, 0.25), lh=(0.25, -0.6, 0.25), body=(45, 0, 0),
              tor=(40, 0, 0), re="back", le="back"),
            K(0.88, "hinge", rh=(0.35, -0.62, 0.2), lh=(0.35, -0.62, 0.2), tor=(85, 0, 0), pel=(-0.04, 0, 25)),
            K(1.0, "stand", rh=HANG, lh=HANG),
        ]
        return {"keys": keys, "duration": 4.5, "loop": False, "view": "side"}
    if variant in ("bear_crawl",):
        # Hands and feet on the floor, knees hovering; opposite hand and foot move together.
        def bc(t, ph, rh_f, lh_f, rf_f, lf_f, plant):
            return K(t, ph, plant="none", re="back", le="back", body=(72, 0, 0), tor=(-8, 0, 0), pel=(0, 0, 0),
                     rh=(rh_f, -0.6, 0.3), lh=(lh_f, -0.6, 0.3),
                     rf=(rf_f, 0.14, 0.42, 5), lf=(lf_f, 0.14, 0.42, 5))
        k0 = bc(0.0, "right hand + left foot forward", 0.15, -0.12, -0.08, 0.12, "none")
        k1 = bc(0.25, "pass", 0.02, 0.02, 0.02, 0.02, "none")
        k2 = bc(0.5, "left hand + right foot forward", -0.12, 0.15, 0.12, -0.08, "none")
        k3 = bc(0.75, "pass", 0.02, 0.02, 0.02, 0.02, "none")
        return {"keys": [k0, k1, k2, k3], "duration": 1.2, "loop": True, "view": "side"}
    if variant in ("superman",):
        k0 = K(0.0, "lying face down", plant="none", body=(88, 0, 0), rh=(0.05, 0.6, 0.25), lh=(0.05, 0.6, 0.25))
        k1 = K(0.5, "lift arms + legs", plant="none", body=(88, 0, 0), tor=(-20, 0, 0), head=(-15, 0, 0),
               rh=(-0.2, 0.55, 0.25), lh=(-0.2, 0.55, 0.25), rf=(-0.2, 0.12, 0.0, 5), lf=(-0.2, 0.12, 0.0, 5))
        return {"keys": [k0, k1], "duration": 2.0, "loop": True, "view": "side"}
    raise KeyError(variant)


def tpl_agility(variant: str, amp: float) -> Dict[str, Any]:
    a = amp
    if variant in ("defensive_slide", "lateral_shuffle", "shuffle"):
        base = dict(pel=(-0.16, 0, 8), tor=(25, 0, 0), rh=(0.25, -0.1, 0.45), lh=(0.25, -0.1, 0.45))
        k0 = K(0.0, "wide stance", **_merge(base, rf=(0, 0.38, 0, 15), lf=(0, 0.38, 0, 15)))
        k1 = K(0.2, "push, right foot steps out", plant="left",
               **_merge(base, rf=(0, 0.5 * a, 0.08, 15), lf=(0, 0.3, 0, 15), pel=(-0.14, 0, 8, 4), tor=(25, 0, 6)))
        k2 = K(0.35, "close step", plant="right", **_merge(base, rf=(0, 0.42, 0, 15), lf=(0, 0.15, 0.06, 15)))
        k3 = K(0.5, "wide stance", **_merge(base, rf=(0, 0.38, 0, 15), lf=(0, 0.38, 0, 15)))
        k4 = swap_sides(k1, 0.7, "push, left foot steps out")
        k5 = swap_sides(k2, 0.85, "close step")
        return {"keys": [k0, k1, k2, k3, k4, k5], "duration": 1.6, "loop": True, "view": "front"}
    if variant in ("carioca", "grapevine"):
        base = dict(pel=(-0.1, 0, 4), tor=(12, 0, 0), rh=(0.1, -0.42, 0.48), lh=(0.1, -0.42, 0.48))
        k0 = K(0.0, "feet apart", **_merge(base, rf=(0, 0.2, 0, 10), lf=(0, 0.2, 0, 10)))
        k1 = K(0.25, "left crosses in front", plant="right",
               **_merge(base, lf=(0.18, -0.08, 0.15, 10), rf=(0, 0.2, 0, 10), pel=(-0.1, 40 * a, 4), tor=(12, -25, 0),
                        rh=(-0.05, -0.4, 0.5), lh=(0.25, -0.4, 0.42)))
        k2 = K(0.5, "feet apart", **_merge(base, rf=(0, 0.2, 0, 10), lf=(0, 0.2, 0, 10)))
        k3 = K(0.75, "left crosses behind", plant="right",
               **_merge(base, lf=(-0.18, -0.08, 0.12, 10), rf=(0, 0.2, 0, 10), pel=(-0.1, -40 * a, 4), tor=(12, 25, 0),
                        rh=(0.25, -0.4, 0.42), lh=(-0.05, -0.4, 0.5)))
        return {"keys": [k0, k1, k2, k3], "duration": 1.2, "loop": True, "view": "front"}
    if variant in ("closeout", "basketball_closeout"):
        def stride(t, ph, right_up):
            r, l = ((0.15, 0.11, 0.35, 5), (-0.15, 0.11, 0, 5)) if right_up else ((-0.15, 0.11, 0, 5), (0.15, 0.11, 0.35, 5))
            return K(t, ph, plant="left" if right_up else "right", re="back", le="back", body=(6, 0, 0), tor=(12, 0, 0),
                     rf=r, lf=l, rh=(0.3 if not right_up else -0.2, -0.3, 0.25), lh=(0.3 if right_up else -0.2, -0.3, 0.25))
        chop = dict(pel=(-0.18, 0, 8), tor=(22, 0, 0), rh=(0.2, 0.15, 0.3), lh=(0.25, 0.0, 0.3), rf=(0, 0.25, 0, 15), lf=(0, 0.25, 0, 15))
        keys = [stride(0.0, "sprint stride", True), stride(0.12, "sprint stride", False), stride(0.24, "sprint stride", True),
                K(0.34, "chop feet (short, fast)", plant="left", **_merge(chop, rf=(0, 0.25, 0.06, 15))),
                K(0.42, "chop", plant="right", **_merge(chop, lf=(0, 0.25, 0.06, 15))),
                K(0.5, "chop", plant="left", **_merge(chop, rf=(0, 0.25, 0.06, 15))),
                K(0.6, "contest: hand high", **_merge(chop, rh=(0.25, 0.62, 0.2), pel=(-0.1, 0, 6), tor=(10, 0, 0))),
                K(0.75, "slide to cut off the drive", plant="left",
                  **_merge(chop, rh=(0.25, -0.1, 0.45), lh=(0.25, -0.1, 0.45), rf=(0, 0.5, 0.08, 15), lf=(0, 0.3, 0, 15))),
                K(0.88, "close step", plant="right", **_merge(chop, rh=(0.25, -0.1, 0.45), lh=(0.25, -0.1, 0.45),
                                                             rf=(0, 0.42, 0, 15), lf=(0, 0.15, 0.06, 15))),
                K(1.0, "stance", **_merge(chop, rh=(0.25, -0.1, 0.45), lh=(0.25, -0.1, 0.45), rf=(0, 0.35, 0, 15),
                                          lf=(0, 0.35, 0, 15)))]
        return {"keys": keys, "duration": 2.6, "loop": False, "view": "front"}
    if variant in ("drop_step", "crossover_step", "cut", "jab_step"):
        keys = [K(0.0, "athletic stance", **READY),
                K(0.35, "drop right foot back + turn", plant="left",
                  **_merge(READY, rf=(-0.3, 0.3, 0.06, 40), pel=(-0.12, 45 * a, 4), tor=(20, 40 * a, 0))),
                K(0.6, "plant + drive", **_merge(READY, rf=(-0.3, 0.3, 0, 40), pel=(-0.14, 45 * a, 6), tor=(25, 45 * a, 0),
                                                 rh=(-0.2, -0.4, 0.3), lh=(0.35, -0.2, 0.2))),
                K(1.0, "athletic stance", **READY)]
        return {"keys": keys, "duration": 1.4, "loop": False, "view": "front"}
    raise KeyError(variant)


def tpl_ball(variant: str, amp: float) -> Dict[str, Any]:
    if variant in ("basketball_jump_shot", "basketball_free_throw", "set_shot"):
        jump = 0.0 if variant == "basketball_free_throw" else 0.3 * amp
        base = dict(rf=(0.03, 0.16, 0, 12), lf=(-0.03, 0.16, 0, 18))
        keys = [
            K(0.0, "triple threat", grip=True, **_merge(base, rh=(0.3, -0.35, 0.12), lh=(0.3, -0.35, 0.12),
                                                       pel=(-0.12, 0, 6), tor=(20, 0, 0))),
            K(0.3, "dip", grip=True, **_merge(base, rh=(0.3, -0.4, 0.15), lh=(0.3, -0.4, 0.15), pel=(-0.22, 0, 8), tor=(22, 0, 0))),
            K(0.5, "set point", grip=True, re="down", plant="both" if jump == 0 else "none",
              **_merge(base, rh=(0.15, 0.3, 0.12), lh=(0.15, 0.3, 0.12), pel=(jump * 0.6, 0, 0), tor=(0, 0, 0),
                       head=(-10, 0, 0))),
            K(0.62, "release (wrist flick)", plant="both" if jump == 0 else "none", re="forward",
              **_merge(base, rh=(0.25, 0.6, 0.18), lh=(0.2, 0.35, 0.15), pel=(jump, 0, 0), tor=(-2, 0, 0), head=(-15, 0, 0))),
            K(0.78, "hold follow-through", plant="both" if jump == 0 else "none", re="forward",
              **_merge(base, rh=(0.28, 0.58, 0.18), lh=(0.2, 0.3, 0.15), pel=(jump * 0.3, 0, 0), head=(-15, 0, 0))),
            K(1.0, "land", **_merge(base, rh=(0.3, -0.3, 0.2), lh=(0.3, -0.3, 0.2), pel=(-0.12, 0, 6), tor=(18, 0, 0))),
        ]
        return {"keys": keys, "duration": 1.8, "loop": False, "view": "side"}
    if variant in ("basketball_layup", "layup"):
        # Right-hand layup in place: right-left gather, drive the right knee up, lift off the left
        # foot, ball carried up with two hands, right hand extends to lay it off the board.
        keys = [
            K(0.0, "gather (right foot)", grip=True, plant="right",
              **_merge(STANDING, rh=(0.3, -0.3, 0.12), lh=(0.3, -0.3, 0.12), pel=(-0.1, 10, 6), tor=(20, 10, 0),
                       rf=(0.1, 0.12, 0, 10), lf=(-0.25, 0.12, 0.2, 10))),
            K(0.3, "left foot plant", grip=True,
              **_merge(STANDING, rh=(0.3, -0.15, 0.15), lh=(0.3, -0.15, 0.15), pel=(-0.18, 0, 6), tor=(15, 0, 0),
                       rf=(-0.2, 0.12, 0.1, 10), lf=(0.15, 0.12, 0, 10))),
            K(0.5, "take off, right knee drives", plant="none", grip=True,
              **_merge(STANDING, rh=(0.25, 0.35, 0.22), lh=(0.25, 0.35, 0.22), pel=(0.25, 0, 0), tor=(0, 0, 0),
                       rf=(0.25, 0.12, 0.45, 10), lf=(0.0, 0.12, 0.03, 10), head=(-20, 0, 0))),
            K(0.62, "release at the top", plant="none", re="forward",
              **_merge(STANDING, rh=(0.25, 0.62, 0.22), lh=(0.25, 0.2, 0.2), pel=(0.4, 0, 0), tor=(0, 0, 0),
                       rf=(0.25, 0.12, 0.42, 10), lf=(0.0, 0.12, 0.03, 10), head=(-25, 0, 0))),
            K(0.8, "descend", plant="none",
              **_merge(STANDING, rh=(0.3, -0.1, 0.3), lh=(0.3, -0.1, 0.3), pel=(0.15, 0, 0),
                       rf=(0.05, 0.14, 0.08, 10), lf=(0.0, 0.14, 0.05, 10))),
            K(1.0, "two-foot landing", **_merge(STANDING, rh=(0.3, -0.3, 0.3), lh=(0.3, -0.3, 0.3), pel=(-0.2, 0, 8),
                                                tor=(25, 0, 0), rf=(0, 0.16, 0, 12), lf=(0, 0.16, 0, 12))),
        ]
        return {"keys": keys, "duration": 1.6, "loop": False, "view": "side"}
    if variant in ("chest_pass", "bounce_pass"):
        low = -0.25 if variant == "bounce_pass" else 0.0
        keys = [
            K(0.0, "ball at chest", grip=True, re="down", le="down", **_merge(READY, rh=(0.25, -0.15, 0.0), lh=(0.25, -0.15, 0.0))),
            K(0.35, "step in", grip=True, plant="right",
              **_merge(READY, rh=(0.22, -0.15, 0.0), lh=(0.22, -0.15, 0.0), lf=(0.2, 0.2, 0.06, 12))),
            K(0.55, "push + extend", grip=True, re="down",
              **_merge(READY, rh=(0.62, -0.05 + low, 0.0), lh=(0.62, -0.05 + low, 0.0), lf=(0.25, 0.2, 0, 12), tor=(25, 0, 0))),
            K(0.7, "thumbs down follow-through", re="down", le="down",
              **_merge(READY, rh=(0.6, -0.1 + low, 0.2), lh=(0.6, -0.1 + low, 0.2), lf=(0.25, 0.2, 0, 12), tor=(25, 0, 0))),
            K(1.0, "ready", **READY),
        ]
        return {"keys": keys, "duration": 1.4, "loop": False, "view": "side"}
    if variant in ("crossover_dribble", "crossover"):
        base = dict(pel=(-0.18, 0, 8), tor=(30, 0, 0), rf=(0.05, 0.28, 0, 12), lf=(-0.05, 0.28, 0, 12))
        keys = [
            K(0.0, "dribble right", **_merge(base, rh=(0.3, -0.62, 0.35), lh=(0.35, -0.15, 0.2))),
            K(0.15, "receive right", re="back", **_merge(base, rh=(0.18, -0.25, 0.38), lh=(0.35, -0.15, 0.2))),
            K(0.32, "push low across the body", plant="left",
              **_merge(base, rh=(0.38, -0.62, 0.0), lh=(0.3, -0.45, 0.25), pel=(-0.22, -10, 8, -4), tor=(32, -10, -5),
                       rf=(0.05, 0.36, 0, 12))),
            K(0.45, "catch in left hand", re="down", le="back",
              **_merge(base, rh=(0.35, -0.3, 0.1), lh=(0.2, -0.3, 0.4), pel=(-0.22, -15, 8), tor=(30, -15, 0))),
            K(0.62, "explode: first step left", plant="right", le="back",
              **_merge(base, body=(10, -10, 0), rh=(0.3, -0.15, 0.2), lh=(0.25, -0.6, 0.4), pel=(-0.15, -30, 6),
                       tor=(30, -30, 0), lf=(0.35, 0.3, 0.12, 30))),
            K(0.8, "drive past", le="back",
              **_merge(base, body=(10, -10, 0), rh=(0.35, -0.1, 0.2), lh=(0.2, -0.3, 0.42), pel=(-0.16, -30, 6),
                       tor=(30, -30, 0), lf=(0.4, 0.3, 0, 30))),
            K(1.0, "dribble right", **_merge(base, rh=(0.3, -0.62, 0.35), lh=(0.35, -0.15, 0.2))),
        ]
        return {"keys": keys, "duration": 1.8, "loop": False, "view": "front"}
    if variant in ("dribble", "basketball_dribble"):
        base = dict(pel=(-0.15, 0, 8), tor=(30, 0, 0), lh=(0.35, -0.2, 0.15), rf=(0.05, 0.25, 0, 12), lf=(-0.05, 0.25, 0, 12))
        k0 = K(0.0, "push ball down", **_merge(base, rh=(0.32, -0.62, 0.32), pel=(-0.18, 0, 8)))
        k1 = K(0.5, "receive at hip", re="back", **_merge(base, rh=(0.15, -0.22, 0.35), pel=(-0.13, 0, 8)))
        return {"keys": [k0, k1], "duration": 0.55, "loop": True, "view": "three_quarter"}
    if variant in ("volleyball_bump", "volleyball_pass", "forearm_pass"):
        keys = [K(0.0, "ready", grip=True, **_merge(READY, rh=(0.45, -0.45, 0.0), lh=(0.45, -0.45, 0.0), pel=(-0.2, 0, 10), tor=(30, 0, 0))),
                K(0.5, "platform lift", grip=True, **_merge(READY, rh=(0.55, -0.3, 0.0), lh=(0.55, -0.3, 0.0), pel=(-0.08, 0, 4), tor=(18, 0, 0))),
                K(1.0, "ready", grip=True, **_merge(READY, rh=(0.45, -0.45, 0.0), lh=(0.45, -0.45, 0.0), pel=(-0.2, 0, 10), tor=(30, 0, 0)))]
        return {"keys": keys, "duration": 1.4, "loop": False, "view": "side"}
    if variant in ("volleyball_set", "overhead_set"):
        keys = [K(0.0, "ready", **_merge(READY, rh=(0.2, 0.25, 0.15), lh=(0.2, 0.25, 0.15), pel=(-0.15, 0, 6))),
                K(0.5, "extend up", **_merge(READY, rh=(0.15, 0.62, 0.15), lh=(0.15, 0.62, 0.15), pel=(-0.02, 0, 0), tor=(0, 0, 0))),
                K(1.0, "ready", **_merge(READY, rh=(0.2, 0.25, 0.15), lh=(0.2, 0.25, 0.15), pel=(-0.15, 0, 6)))]
        return {"keys": keys, "duration": 1.3, "loop": False, "view": "side"}
    if variant in ("catch", "goalkeeper_catch"):
        keys = [K(0.0, "ready", **READY),
                K(0.45, "hands out (W shape)", **_merge(READY, rh=(0.55, 0.1, 0.08), lh=(0.55, 0.1, 0.08))),
                K(0.65, "absorb to chest", grip=True, **_merge(READY, rh=(0.25, -0.1, 0.0), lh=(0.25, -0.1, 0.0), pel=(-0.12, 0, 6))),
                K(1.0, "ready", **READY)]
        return {"keys": keys, "duration": 1.4, "loop": False, "view": "side"}
    raise KeyError(variant)


# -----------------------------------------------------------------------------
# Named poses (for the pose_sequence template: novel drills, stretches, holds)
# -----------------------------------------------------------------------------

POSES: Dict[str, Dict[str, Any]] = {
    "standing": dict(rh=HANG, lh=HANG),
    "athletic_stance": dict(READY),
    "quarter_squat": dict(pel=(-0.18, 0, 8), tor=(22, 0, 0), rh=(0.35, -0.3, 0.25), lh=(0.35, -0.3, 0.25),
                          rf=(0, 0.2, 0, 15), lf=(0, 0.2, 0, 15)),
    "deep_squat": dict(pel=(-0.45, 0, 18), tor=(38, 0, 0), rh=(0.55, 0.0, 0.22), lh=(0.55, 0.0, 0.22),
                       rf=(0, 0.2, 0, 22), lf=(0, 0.2, 0, 22)),
    "low_crouch_hands_down": dict(pel=(-0.45, 0, 18), tor=(55, 0, 0), rh=(0.55, -0.45, 0.25), lh=(0.55, -0.45, 0.25),
                                  rf=(0, 0.2, 0, 20), lf=(0, 0.2, 0, 20)),
    "lunge_right_forward": dict(pel=(-0.32, 0, 0), rf=(0.45, 0.12, 0, 10), lf=(-0.45, 0.12, 0.04, 5),
                                rh=(0.0, -0.45, 0.35), lh=(0.0, -0.45, 0.35), _re="out", _le="out"),
    "lunge_left_forward": dict(pel=(-0.32, 0, 0), lf=(0.45, 0.12, 0, 10), rf=(-0.45, 0.12, 0.04, 5),
                               rh=(0.0, -0.45, 0.35), lh=(0.0, -0.45, 0.35), _re="out", _le="out"),
    "lateral_lunge_right": dict(rf=(0, 0.45, 0, 25), lf=(0, 0.35, 0, 20), pel=(-0.3, 0, 15, -10), tor=(30, 0, -5),
                                rh=(0.5, -0.15, 0.05), lh=(0.5, -0.15, 0.05)),
    "lateral_lunge_left": dict(lf=(0, 0.45, 0, 25), rf=(0, 0.35, 0, 20), pel=(-0.3, 0, 15, 10), tor=(30, 0, 5),
                               rh=(0.5, -0.15, 0.05), lh=(0.5, -0.15, 0.05)),
    "toe_touch": dict(tor=(85, 0, 0), pel=(-0.02, 0, 25), rh=(0.35, -0.62, 0.15), lh=(0.35, -0.62, 0.15)),
    "overhead_reach": dict(rh=(0.05, 0.65, 0.3), lh=(0.05, 0.65, 0.3), head=(-15, 0, 0)),
    "t_pose": dict(rh=(0.0, 0.0, 0.95), lh=(0.0, 0.0, 0.95)),
    "arms_forward": dict(rh=(0.64, 0.0, 0.25), lh=(0.64, 0.0, 0.25)),
    "hands_on_hips": dict(rh=(0.0, -0.45, 0.35), lh=(0.0, -0.45, 0.35), _re="out", _le="out"),
    "hands_behind_head": dict(rh=(-0.05, 0.2, 0.12), lh=(-0.05, 0.2, 0.12), _re="out", _le="out"),
    "boxing_guard": dict(rf=(-0.2, 0.17, 0, 25), lf=(0.22, 0.1, 0, 15), pel=(-0.07, 20, 4), tor=(12, 25, 0),
                         rh=(0.22, 0.06, 0.12), lh=(0.3, 0.08, 0.12)),
    "plank": dict(body=(76, 0, 0), rh=(0.0, -0.6, 0.32), lh=(0.0, -0.6, 0.32), _re="back", _le="back", _plant="none"),
    "push_up_bottom": dict(body=(82, 0, 0), rh=(0.05, -0.3, 0.42), lh=(0.05, -0.3, 0.42), _re="back", _le="back", _plant="none"),
    "side_plank_right": dict(body=(0, 0, 70), rh=(0.0, -0.6, 0.32), lh=(0.0, 0.6, 0.3), _plant="none"),
    "right_knee_raise": dict(rf=(0.2, 0.12, 0.5, 10), rh=(-0.2, -0.45, 0.3), lh=(0.3, -0.2, 0.2), _plant="left", _re="back", _le="back"),
    "left_knee_raise": dict(lf=(0.2, 0.12, 0.5, 10), lh=(-0.2, -0.45, 0.3), rh=(0.3, -0.2, 0.2), _plant="right", _re="back", _le="back"),
    "balance_on_left_leg": dict(rf=(-0.1, 0.12, 0.25, 10), rh=(0.0, -0.1, 0.8), lh=(0.0, -0.1, 0.8), _plant="left"),
    "balance_on_right_leg": dict(lf=(-0.1, 0.12, 0.25, 10), rh=(0.0, -0.1, 0.8), lh=(0.0, -0.1, 0.8), _plant="right"),
    "reach_right_hand_to_left_foot": dict(pel=(-0.35, 0, 15), tor=(65, -35, 0), rh=(0.25, -0.62, -0.18),
                                          lh=(-0.2, -0.35, 0.5), rf=(0, 0.22, 0, 20), lf=(0, 0.22, 0, 20)),
    "reach_left_hand_to_right_foot": dict(pel=(-0.35, 0, 15), tor=(65, 35, 0), lh=(0.25, -0.62, -0.18),
                                          rh=(-0.2, -0.35, 0.5), rf=(0, 0.22, 0, 20), lf=(0, 0.22, 0, 20)),
    "reach_low_right": dict(pel=(-0.3, 15, 12, 6), tor=(50, 30, -10), rh=(0.55, -0.55, 0.35), lh=(0.1, -0.3, 0.4),
                            rf=(0.1, 0.35, 0, 25), lf=(0, 0.2, 0, 15)),
    "reach_low_left": dict(pel=(-0.3, -15, 12, -6), tor=(50, -30, 10), lh=(0.55, -0.55, 0.35), rh=(0.1, -0.3, 0.4),
                           lf=(0.1, 0.35, 0, 25), rf=(0, 0.2, 0, 15)),
    "twist_right": dict(tor=(5, 55, 0), pel=(0, 15, 0), rh=(0.15, -0.1, 0.6), lh=(0.45, -0.1, -0.1)),
    "twist_left": dict(tor=(5, -55, 0), pel=(0, -15, 0), lh=(0.15, -0.1, 0.6), rh=(0.45, -0.1, -0.1)),
    "side_bend_right": dict(tor=(0, 0, 30), rh=(0.0, -0.55, 0.35), lh=(0.05, 0.6, 0.15)),
    "side_bend_left": dict(tor=(0, 0, -30), lh=(0.0, -0.55, 0.35), rh=(0.05, 0.6, 0.15)),
    "lean_back_arch": dict(tor=(-25, 0, 0), head=(-20, 0, 0), rh=(-0.1, 0.55, 0.3), lh=(-0.1, 0.55, 0.3)),
    "lying_face_up": dict(body=(-88, 0, 0), _plant="none"),
    "lying_face_down": dict(body=(88, 0, 0), rh=(0.05, 0.6, 0.25), lh=(0.05, 0.6, 0.25), _plant="none"),
    "kneeling": dict(pel=(-0.4, 0, 0), rf=(-0.35, 0.12, 0.05, 5), lf=(-0.35, 0.12, 0.05, 5), _plant="none"),
    "jump_airborne": dict(pel=(0.3, 0, 0), rh=(0.15, 0.55, 0.25), lh=(0.15, 0.55, 0.25), rf=(0, 0.14, 0.03, 10),
                          lf=(0, 0.14, 0.03, 10), _plant="none"),
    "sprint_start_set": dict(body=(45, 0, 0), pel=(-0.3, 0, 10), rf=(-0.3, 0.12, 0.05, 5), lf=(0.15, 0.12, 0, 5),
                             rh=(0.3, -0.62, 0.3), lh=(0.3, -0.62, 0.3)),
}


def pose_key(name: str, t: float) -> Dict[str, Any]:
    spec = dict(POSES[name])
    re = spec.pop("_re", "down")
    le = spec.pop("_le", "down")
    plant = spec.pop("_plant", "both")
    base = dict(rh=HANG, lh=HANG, rf=STAND_FOOT, lf=STAND_FOOT)
    base.update(spec)
    return K(t, name.replace("_", " "), plant=plant, re=re, le=le, **base)


def tpl_poses(variant: str, amp: float) -> Dict[str, Any]:
    """variant: pose names joined by '>' (e.g. 'standing>toe_touch>overhead_reach>standing')."""
    names = []
    for token in variant.replace(",", ">").split(">"):
        token = token.strip().lower().replace(" ", "_").replace("-", "_")
        if not token:
            continue
        match = difflib.get_close_matches(token, list(POSES), 1, 0.45)
        if match:
            names.append(match[0])
    names = [n for i, n in enumerate(names) if i == 0 or n != names[i - 1]]
    if not names:
        names = ["standing"]
    if len(names) == 1:
        names = names + names
    # Timing like a real athlete: big changes (standing -> floor) take longer than small ones,
    # and each pose is briefly held so it reads clearly before the next move.
    def vec(name: str) -> List[float]:
        spec = dict(rh=HANG, lh=HANG, rf=STAND_FOOT, lf=STAND_FOOT, pel=(0, 0, 0, 0), tor=(0, 0, 0), body=(0, 0, 0))
        spec.update({k: v for k, v in POSES[name].items() if not k.startswith("_")})
        out: List[float] = []
        for key, scale in (("rh", 1.0), ("lh", 1.0), ("rf", 1.0), ("lf", 1.0), ("pel", 1.0), ("tor", 0.01),
                           ("body", 0.015)):
            vals = list(spec[key])
            if key in ("rf", "lf"):
                vals = vals[:3]
            if key == "pel":
                vals = [vals[0], vals[1] * 0.01]
            out += [float(x) * scale for x in vals]
        return out

    hold = 0.15
    times = [0.0]
    for prev, cur in zip(names, names[1:]):
        dist = sum(abs(x - y) for x, y in zip(vec(prev), vec(cur)))
        move = min(1.1, 0.25 + 0.25 * dist)
        times.append(times[-1] + hold + move)
    keys: List[Dict[str, Any]] = []
    for i, (name, t) in enumerate(zip(names, times)):
        keys.append(pose_key(name, t))
        if 0 < i < len(names) - 1:
            held = pose_key(name, t + hold)
            held["phase"] = name.replace("_", " ") + " (hold)"
            keys.append(held)
    total = times[-1]
    for k in keys:
        k["t"] = k["t"] / total
    return {"keys": keys, "duration": total / max(0.6, amp), "loop": False, "view": "three_quarter"}


# -----------------------------------------------------------------------------
# Catalog (what the language model may choose from)
# -----------------------------------------------------------------------------

TEMPLATES: Dict[str, Tuple[Callable[[str, float], Dict[str, Any]], List[str], str]] = {
    "run": (tpl_run, ["jog", "sprint", "high_knees", "butt_kicks", "march", "backpedal", "a_skip"],
            "running/marching gaits in place (loops)"),
    "track": (tpl_track, ["hurdle"], "track and field running events"),
    "swim": (tpl_swim, ["freestyle", "backstroke", "breaststroke", "butterfly"], "swimming strokes (loops)"),
    "swing": (tpl_swing, ["tennis_forehand", "tennis_backhand", "golf_drive", "golf_iron", "golf_chip", "golf_putt",
                          "baseball_bat", "softball_bat", "hockey_slapshot", "hockey_wristshot", "field_hockey_hit",
                          "lacrosse_shot", "table_tennis_forehand", "padel_forehand", "squash_forehand",
                          "badminton_forehand", "cricket_drive"],
              "striking with a racket, club, bat or stick"),
    "overhead": (tpl_overhead, ["baseball_pitch", "football_throw", "javelin", "softball_overhand", "dodgeball_throw",
                                "cricket_bowl", "softball_windmill", "shot_put", "tennis_serve", "badminton_smash", "overhead_smash",
                                "volleyball_spike", "volleyball_serve_jump", "basketball_dunk", "header_jump",
                                "soccer_throw_in", "two_hand_overhead_pass"],
                 "overhead throws, serves, spikes, smashes"),
    "punch": (tpl_punch, ["jab", "cross", "jab-cross", "jab-cross-hook", "jab-cross-hook-uppercut", "hook",
                          "uppercut", "rear_hook", "body_hook", "slip", "duck", "roll"],
              "boxing/striking combos; variant = shots joined by '-' from: jab, cross, hook, uppercut, "
              "lead_uppercut, rear_hook, body_hook, slip, duck, roll (write repeats out: double jab = jab-jab)"),
    "kick": (tpl_kick, ["soccer_instep", "soccer_pass", "punt", "front_kick", "roundhouse_kick", "side_kick", "knee_strike"],
             "kicking actions"),
    "jump": (tpl_jump, ["vertical_jump", "squat_jump", "tuck_jump", "box_jump", "jumping_jack", "jump_rope",
                        "skater_jump", "lateral_hops", "broad_jump"], "jumps and plyometrics"),
    "strength": (tpl_strength, ["squat", "goblet_squat", "sumo_squat", "forward_lunge", "reverse_lunge",
                                "walking_lunge", "split_squat", "lunge_with_twist", "lateral_lunge", "deadlift", "romanian_deadlift",
                                "kettlebell_swing", "single_leg_rdl", "overhead_press", "push_press",
                                "bent_over_row", "bicep_curl", "calf_raise", "arm_circles"],
                 "gym / strength / warm-up exercises"),
    "floor": (tpl_floor, ["push_up", "plank", "forearm_plank", "mountain_climber", "burpee", "sit_up", "crunch",
                          "glute_bridge", "superman", "bear_crawl", "russian_twist", "inchworm"],
              "exercises on or near the floor"),
    "agility": (tpl_agility, ["defensive_slide", "lateral_shuffle", "carioca", "drop_step", "crossover_step",
                              "closeout"],
                "footwork and agility patterns"),
    "ball": (tpl_ball, ["basketball_jump_shot", "basketball_free_throw", "basketball_layup", "chest_pass", "bounce_pass", "dribble", "crossover_dribble",
                        "volleyball_bump", "volleyball_set", "catch"], "ball handling, passing and shooting"),
    "poses": (tpl_poses, [], "custom drill as a sequence of named poses joined by '>' (see POSES); "
                             "use for stretches, holds, novel drills, reaches, transitions"),
}

VARIANT_ALIASES = {
    "padel_forehand": "tennis_forehand", "squash_forehand": "tennis_forehand", "badminton_forehand": "tennis_forehand",
    "cricket_drive": "baseball_bat", "soccer_instep": "instep", "punt": "instep", "football_throw": "throw",
    "softball_overhand": "throw", "dodgeball_throw": "throw", "cricket_bowl": "throw", "javelin": "javelin",
    "vertical_jump": "vertical", "walking_lunge": "forward_lunge", "split_squat": "forward_lunge",
}


def catalog_text() -> str:
    lines = []
    for name, (_, variants, desc) in TEMPLATES.items():
        if name == "poses":
            lines.append(f"- poses: {desc}. Pose names: {', '.join(POSES)}")
        else:
            lines.append(f"- {name}: {desc}. Variants: {', '.join(variants)}")
    return "\n".join(lines)


def resolve(template: str, variant: str) -> Tuple[str, str, List[str]]:
    """Fuzzy-match a (template, variant) choice onto the catalog. Returns (template, variant, notes)."""
    notes: List[str] = []
    template = (template or "").strip().lower()
    if template not in TEMPLATES:
        # Maybe the variant names it.
        for name, (_, variants, _) in TEMPLATES.items():
            if variant in variants:
                notes.append(f"template '{template}' -> '{name}'")
                template = name
                break
        else:
            match = difflib.get_close_matches(template, list(TEMPLATES), 1, 0.5)
            if not match:
                raise KeyError(f"unknown template '{template}'")
            notes.append(f"template '{template}' -> '{match[0]}'")
            template = match[0]
    if template in ("poses", "punch"):
        return template, variant, notes
    variants = TEMPLATES[template][1]
    v = (variant or "").strip().lower().replace(" ", "_").replace("-", "_")
    if v not in variants:
        match = difflib.get_close_matches(v, variants, 1, 0.4)
        if not match:
            raise KeyError(f"unknown variant '{variant}' for template '{template}'")
        notes.append(f"variant '{variant}' -> '{match[0]}'")
        v = match[0]
    return template, v, notes


def build_segment(template: str, variant: str, amp: float) -> Dict[str, Any]:
    fn = TEMPLATES[template][0]
    try:
        return fn(VARIANT_ALIASES.get(variant, variant), amp)
    except KeyError:
        return fn(variant, amp)


def all_choices() -> List[Tuple[str, str]]:
    out = []
    for name, (_, variants, _) in TEMPLATES.items():
        for v in variants:
            out.append((name, v))
    return out


# =============================================================================
# Movement grammar: build ANY drill from beats of body-part actions
# =============================================================================
# The model describes a drill as an ordered list of "beats". Each beat chooses, from fixed menus,
# what the stance/level/trunk/arms/legs/facing are at the END of that beat. Code turns every choice
# into exact targets and adds the biomechanics (counter-rotation, hinging to reach the floor,
# counter-swinging arms, pivots on facing changes). The model never writes numbers.

BEAT_TIME = {"instant": 0.18, "quick": 0.32, "normal": 0.55, "slow": 0.95, "hold": 0.8}

STANCES = {
    # name: (right foot, left foot, pelvis height, body pitch, planted?)
    "standing": ((0, 0.12, 0, 10), (0, 0.12, 0, 10), 0.0, 0, True),
    "athletic": ((0, 0.24, 0, 12), (0, 0.24, 0, 12), -0.1, 0, True),
    "wide": ((0, 0.38, 0, 20), (0, 0.38, 0, 20), -0.12, 0, True),
    "narrow": ((0, 0.07, 0, 5), (0, 0.07, 0, 5), 0.0, 0, True),
    "staggered_left_forward": ((-0.2, 0.15, 0, 20), (0.22, 0.1, 0, 10), -0.08, 0, True),
    "staggered_right_forward": ((0.22, 0.1, 0, 10), (-0.2, 0.15, 0, 20), -0.08, 0, True),
    "lunge_left_forward": ((-0.45, 0.12, 0.04, 5), (0.45, 0.12, 0, 10), -0.32, 0, True),
    "lunge_right_forward": ((0.45, 0.12, 0, 10), (-0.45, 0.12, 0.04, 5), -0.32, 0, True),
    "lateral_lunge_left": ((0, 0.32, 0, 20), (0, 0.45, 0, 25), -0.3, 0, True),
    "lateral_lunge_right": ((0, 0.45, 0, 25), (0, 0.32, 0, 20), -0.3, 0, True),
    "single_leg_left": ((-0.1, 0.12, 0.25, 10), (0, 0.12, 0, 10), -0.05, 0, True),
    "single_leg_right": ((0, 0.12, 0, 10), (-0.1, 0.12, 0.25, 10), -0.05, 0, True),
    "kneeling": ((-0.35, 0.12, 0.05, 5), (-0.35, 0.12, 0.05, 5), -0.4, 0, False),
    "plank": ((0, 0.12, 0, 5), (0, 0.12, 0, 5), 0.0, 76, False),
    "push_up_bottom": ((0, 0.12, 0, 5), (0, 0.12, 0, 5), 0.0, 82, False),
    "bear_position": ((0, 0.14, 0.42, 5), (0, 0.14, 0.42, 5), 0.0, 72, False),
    "lying_face_up": ((0, 0.12, 0, 5), (0, 0.12, 0, 5), 0.0, -88, False),
    "lying_face_down": ((0, 0.12, 0, 5), (0, 0.12, 0, 5), 0.0, 88, False),
    "seated": ((0.3, 0.14, 0.38, 10), (0.3, 0.14, 0.38, 10), 0.0, -45, False),
    "airborne": ((0, 0.14, 0.05, 10), (0, 0.14, 0.05, 10), 0.3, 0, False),
    "half_kneeling_left_forward": ((-0.4, 0.12, 0.08, 5), (0.35, 0.12, 0, 10), -0.42, 0, True),
    "half_kneeling_right_forward": ((0.35, 0.12, 0, 10), (-0.4, 0.12, 0.08, 5), -0.42, 0, True),
    "reverse_tabletop": ((-0.35, 0.16, 0.4, 10), (-0.35, 0.16, 0.4, 10), 0.0, -80, False),
    "dive_left": ((0, 0.2, 0, 5), (0, 0.1, 0, 5), 0.0, 0, False),
    "dive_right": ((0, 0.1, 0, 5), (0, 0.2, 0, 5), 0.0, 0, False),
}
STANCE_ROLL = {"dive_left": -80, "dive_right": 80}
LEVELS = {"keep": None, "tall": 0.03, "normal": None, "half_squat": -0.22, "deep_squat": -0.42}
TRUNKS = {
    # name: (lean, twist, side_bend, pelvis twist)
    "upright": (5, 0, 0, 0), "lean_forward": (25, 0, 0, 0), "hinge": (55, 0, 0, 0), "deep_hinge": (80, 0, 0, 0),
    "lean_back": (-20, 0, 0, 0), "turn_left": (8, -45, 0, -15), "turn_right": (8, 45, 0, 15),
    "coil_right": (12, 55, 0, 25), "coil_left": (12, -55, 0, -25),
    "side_bend_left": (0, 0, -25, 0), "side_bend_right": (0, 0, 25, 0),
}
FACINGS = {"front": 0, "left_45": -45, "right_45": 45, "left_90": -90, "right_90": 90, "back": 180}

# Arm actions for the RIGHT arm in the chest frame (forward, up, out); left arm uses the same numbers.
# Extras: elbow hint, implied trunk (lean, twist toward the reaching side sign), implied level.
ARM_ACTIONS = {
    "relaxed": dict(hand=(0.05, -0.6, 0.33)),
    "ready": dict(hand=(0.3, -0.35, 0.22)),
    "guard": dict(hand=(0.28, 0.06, 0.13)),
    "on_hips": dict(hand=(0.0, -0.45, 0.35), elbow="out"),
    "behind_head": dict(hand=(-0.05, 0.2, 0.12), elbow="out"),
    "overhead": dict(hand=(0.05, 0.65, 0.3)),
    "forward_reach": dict(hand=(0.64, 0.0, 0.25)),
    "side_reach": dict(hand=(0.0, 0.0, 0.95)),
    "reach_high_forward": dict(hand=(0.4, 0.48, 0.25)),
    "reach_low_forward": dict(hand=(0.5, -0.5, 0.22), lean=35),
    "reach_across": dict(hand=(0.42, -0.12, -0.18), twist=-35),
    "touch_floor_front": dict(hand=(0.45, -0.62, 0.22), lean=70, level=-0.3),
    "touch_same_foot": dict(hand=(0.3, -0.62, 0.3), lean=80, level=-0.15),
    "touch_opposite_foot": dict(hand=(0.25, -0.62, -0.18), lean=65, twist=-35, level=-0.3),
    "swing_back": dict(hand=(-0.35, -0.42, 0.3), elbow="back"),
    "pump_forward": dict(hand=(0.32, -0.2, 0.2), elbow="back"),
    "pump_back": dict(hand=(-0.22, -0.45, 0.31), elbow="back"),
    "punch": dict(hand=(0.64, 0.03, 0.0), twist=-30, pelvis_twist=-12),
    "uppercut": dict(hand=(0.35, 0.15, 0.02), twist=-25),
    "hook": dict(hand=(0.35, 0.03, -0.05), elbow="out", twist=-35),
    "throw_cock": dict(hand=(-0.15, 0.28, 0.42), elbow="up", twist=45, pelvis_twist=20),
    "throw_release": dict(hand=(0.5, 0.2, 0.15), elbow="forward", twist=-30, pelvis_twist=-30),
    "follow_through_across": dict(hand=(0.35, -0.45, -0.25), twist=-45, lean=30),
    "chest_hold": dict(hand=(0.25, -0.15, 0.0)),
    "catch_high": dict(hand=(0.35, 0.5, 0.12)),
    "contest_high": dict(hand=(0.2, 0.63, 0.18)),
    "plank_support": dict(hand=(0.0, -0.6, 0.32), elbow="back"),
    "touch_opposite_shoulder": dict(hand=(0.18, 0.02, -0.28)),
    "wrap_hug": dict(hand=(0.38, -0.35, -0.08), elbow="out", lean=35),
    "pull_in": dict(hand=(0.15, -0.3, 0.2), elbow="back"),
    "push_forward": dict(hand=(0.62, -0.05, 0.08)),
    "row_pull": dict(hand=(0.05, -0.4, 0.32), elbow="back"),
    "catch_low": dict(hand=(0.45, -0.5, 0.12), lean=30, level=-0.15),
    "auto": dict(hand=None),
}
# Leg actions for the RIGHT leg (forward, out, lift, toe_out) + whether the foot is on the floor.
LEG_ACTIONS = {
    "planted": dict(foot=None, planted=True),
    "knee_drive": dict(foot=(0.2, 0.12, 0.5, 5), planted=False),
    "kick_front": dict(foot=(0.6, 0.08, 0.5, 0), planted=False),
    "heel_to_butt": dict(foot=(-0.2, 0.12, 0.55, 5), planted=False),
    "kick_side": dict(foot=(0.1, 0.5, 0.45, 30), planted=False),
    "swing_back": dict(foot=(-0.35, 0.1, 0.35, 0), planted=False),
    "step_forward": dict(foot=(0.35, 0.12, 0, 10), planted=True),
    "step_back": dict(foot=(-0.35, 0.12, 0, 10), planted=True),
    "step_out_side": dict(foot=(0, 0.45, 0, 15), planted=True),
    "cross_in_front": dict(foot=(0.18, -0.1, 0, 10), planted=True),
    "cross_behind": dict(foot=(-0.18, -0.1, 0, 10), planted=True),
    "lift_small": dict(foot=(0, 0.12, 0.12, 10), planted=False),
}


ONE_ARM_ACTIONS = {"throw_cock", "throw_release", "follow_through_across", "punch", "uppercut", "hook"}
LIFTING_LEGS = {"knee_drive", "kick_front", "heel_to_butt", "kick_side", "swing_back"}


def sanitize_beat(beat: Dict[str, Any]) -> Dict[str, Any]:
    """Guardrails that turn contradictory menu choices into clean, plausible ones."""
    b = dict(beat)
    ra, la = b.get("right_arm", "auto"), b.get("left_arm", "auto")
    if ra == la and ra in ONE_ARM_ACTIONS:
        b["left_arm"] = "auto"  # a throw/punch is done by ONE arm; the other counter-balances
    rl, ll = b.get("right_leg", "planted"), b.get("left_leg", "planted")
    airborne = b.get("stance") == "airborne"
    if rl in LIFTING_LEGS and ll in LIFTING_LEGS and not airborne:
        b["left_leg"] = "planted"  # can't drive both knees while standing: keep one
    if rl == ll and rl in ("step_forward", "step_back"):
        b["right_leg"] = b["left_leg"] = "planted"  # both feet the same way = same stance
    if rl == ll and rl in ("cross_in_front", "cross_behind"):
        b["right_leg"], b["left_leg"] = "cross_in_front", "cross_behind"  # a scissor, not a collision
    if b.get("stance") in ("plank", "push_up_bottom", "lying_face_down", "lying_face_up", "bear_position") \
            and b.get("trunk") in ("hinge", "deep_hinge", "lean_forward", "lean_back"):
        b["trunk"] = "keep"  # the body is already horizontal
    if b.get("hands_together") and (ra in ONE_ARM_ACTIONS or ra in ("auto", "relaxed")):
        b["hands_together"] = False  # nothing to hold with a one-arm strike or loose arms
    return b


def _beat_keyframe(beat: Dict[str, Any], prev: Dict[str, Any], t: float) -> Dict[str, Any]:
    """Resolve one beat into a full keyframe, carrying 'keep' values over from the previous one."""
    beat = sanitize_beat(beat)
    st_name = beat.get("stance", "keep")
    state = copy.deepcopy(prev)
    if st_name in STANCES:
        rf, lf, h, pitch, planted = STANCES[st_name]
        state.update(rf=rf, lf=lf, height=h, pitch=pitch, base_planted=planted, stance=st_name,
                     roll=STANCE_ROLL.get(st_name, 0))
    lv = LEVELS.get(beat.get("level", "keep"))
    if lv is not None and state["pitch"] == 0:
        state["height"] = lv
    tr = beat.get("trunk", "keep")
    if tr in TRUNKS:
        lean, twist, bend, ptw = TRUNKS[tr]
        state.update(lean=lean, twist=twist, bend=bend, ptwist=ptw)
    elif tr == "keep" and beat.get("stance") in STANCES:
        pass
    fac = beat.get("facing", "keep")
    facing_changed = fac in FACINGS and FACINGS[fac] != state["facing"]
    if fac in FACINGS:
        state["facing"] = FACINGS[fac]

    # Legs.
    feet = {"right": list(state["rf"]), "left": list(state["lf"])}
    planted = {"right": state["base_planted"], "left": state["base_planted"]}
    if st_name in ("single_leg_left",):
        planted["right"] = False
    if st_name in ("single_leg_right",):
        planted["left"] = False
    lifted_legs = []
    support = {"single_leg_left": "left", "single_leg_right": "right"}.get(state["stance"])
    for side in ("right", "left"):
        act = LEG_ACTIONS.get(beat.get(f"{side}_leg", "planted"), LEG_ACTIONS["planted"])
        if side == support and not act.get("planted", True):
            continue  # never lift the leg the athlete is standing on
        if act["foot"] is not None and (state["pitch"] == 0 or not act["planted"]):
            feet[side] = list(act["foot"])
            planted[side] = act["planted"]
            if not act["planted"]:
                lifted_legs.append(side)
    if st_name == "airborne":
        planted = {"right": False, "left": False}
    if len(lifted_legs) == 2 and st_name != "airborne":
        state["height"] = max(state["height"], 0.15)  # both feet up = the athlete is in the air
    if facing_changed:
        planted = {"right": False, "left": False}  # turning: the feet pivot / hop round

    # Arms (+ the trunk/level changes they imply).
    lean, twist, bend, ptwist, height = state["lean"], state["twist"], state["bend"], state["ptwist"], state["height"]
    trunk_explicit = tr in TRUNKS
    hands, elbows = {}, {}
    implied_lean, implied_twist, implied_ptwist, implied_level = [], [], [], []
    for side, sign in (("right", 1.0), ("left", -1.0)):
        name = beat.get(f"{side}_arm", "auto")
        act = ARM_ACTIONS.get(name, ARM_ACTIONS["auto"])
        if name == "auto" or act["hand"] is None:
            continue
        if state["pitch"] > 45 and name in ("relaxed", "ready", "auto"):
            act = ARM_ACTIONS["plank_support"]
        if state["pitch"] < -45 and name in ("plank_support", "relaxed", "ready"):
            act = dict(hand=(-0.6, 0.0, 0.3), elbow="down")  # face-up: hands on the floor behind
        if state["stance"] in STANCE_ROLL and name in ("relaxed", "ready", "auto", "touch_floor_front",
                                                       "reach_low_forward", "forward_reach", "touch_same_foot"):
            act = ARM_ACTIONS["overhead"]
        hands[side] = act["hand"]
        elbows[side] = act.get("elbow", "down")
        if "lean" in act:
            implied_lean.append(act["lean"])
        if "twist" in act:
            implied_twist.append(sign * act["twist"])
        if "pelvis_twist" in act:
            implied_ptwist.append(sign * act["pelvis_twist"])
        if "level" in act:
            implied_level.append(act["level"])
    if not trunk_explicit or tr in ("upright",):
        if implied_lean:
            lean = max(lean, max(implied_lean))
        if implied_twist:
            twist = sum(implied_twist) / len(implied_twist) * (1.0 if len(implied_twist) == 1 else 0.5)
        if implied_ptwist:
            ptwist = sum(implied_ptwist) / len(implied_ptwist)
    if implied_level and state["pitch"] == 0:
        height = min(height, min(implied_level))
    if height < -0.25 and lean < 25 and state["pitch"] == 0:
        lean = 30  # deep knee bend needs the chest over the feet to look balanced
    if abs(state["pitch"]) > 45 or state["stance"] in STANCE_ROLL:
        lean = max(-15, min(15, lean))  # on the floor the trunk stays in line with the body
        height = 0.0 if state["pitch"] else height

    # Unspecified arms: counter-swing against the legs, or a stance-appropriate default.
    for side, other in (("right", "left"), ("left", "right")):
        if side in hands:
            continue
        other_leg = beat.get(f"{other}_leg", "planted")
        same_leg = beat.get(f"{side}_leg", "planted")
        if state["pitch"] > 45:
            hands[side], elbows[side] = ARM_ACTIONS["plank_support"]["hand"], "back"
        elif state["pitch"] < -45 and state["stance"] == "reverse_tabletop":
            hands[side], elbows[side] = (-0.6, 0.0, 0.3), "down"
        elif state["stance"] in STANCE_ROLL:
            hands[side], elbows[side] = ARM_ACTIONS["overhead"]["hand"], "out"
        elif other_leg in ("knee_drive", "step_forward", "kick_front") or same_leg in ("heel_to_butt", "swing_back", "step_back"):
            hands[side], elbows[side] = ARM_ACTIONS["pump_forward"]["hand"], "back"
        elif same_leg in ("knee_drive", "step_forward", "kick_front") or other_leg in ("heel_to_butt", "swing_back"):
            hands[side], elbows[side] = ARM_ACTIONS["pump_back"]["hand"], "back"
        elif same_leg == "kick_side" or other_leg == "kick_side":
            hands[side], elbows[side] = (0.1, -0.2, 0.6), "down"
        elif state["stance"] in ("athletic", "wide", "staggered_left_forward", "staggered_right_forward") or height < -0.15:
            hands[side], elbows[side] = ARM_ACTIONS["ready"]["hand"], "down"
        elif state["stance"] == "seated":
            hands[side], elbows[side] = (0.35, -0.3, 0.15), "down"
        else:
            hands[side], elbows[side] = state["hands"].get(side, ARM_ACTIONS["relaxed"]["hand"]), state["elbows"].get(side, "down")
    state["hands"], state["elbows"] = hands, elbows

    kf = K(t, beat.get("label", "beat")[:40],
           plant="both" if planted["right"] and planted["left"] else "right" if planted["right"] else
           "left" if planted["left"] else "none",
           grip=bool(beat.get("hands_together")), re=elbows["right"], le=elbows["left"],
           rh=hands["right"], lh=hands["left"], rf=feet["right"], lf=feet["left"],
           pel=(height, ptwist, 6 if lean > 20 else 2), tor=(lean, twist, bend),
           body=(state["pitch"], state["facing"], state.get("roll", 0)),
           head=(15 if state["pitch"] > 45 else -20 if state["pitch"] < -45 else 0, 0, 0))
    # Remember what persists into the next beat ("keep"): stance feet, level, trunk, arms.
    state.update(height=height if lv is not None or st_name in STANCES else state["height"])
    return kf, state


def _pose_points(kf: Dict[str, Any]) -> List[Tuple[float, ...]]:
    pts = []
    for grp in ("right_hand", "left_hand"):
        h = kf.get(grp, {})
        pts.append((h.get("forward", 0.05), h.get("up", -0.6), h.get("out", 0.33)))
    for grp in ("right_foot", "left_foot"):
        f = kf.get(grp, {})
        pts.append((f.get("forward", 0.0), f.get("out", 0.12), f.get("lift", 0.0)))
    return pts


def min_transition_time(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """Shortest believable time to move from pose a to pose b (seconds)."""
    import math as _m
    travel = max(_m.dist(p, q) for p, q in zip(_pose_points(a), _pose_points(b)))
    hip = abs(a.get("pelvis", {}).get("height", 0.0) - b.get("pelvis", {}).get("height", 0.0))
    rot = 0.0
    for g, f in (("body", "pitch"), ("body", "turn"), ("body", "roll"), ("torso", "twist"), ("torso", "lean")):
        rot = max(rot, abs(a.get(g, {}).get(f, 0.0) - b.get(g, {}).get(f, 0.0)))
    # Fast athletic limbs ~3.5 m/s, hips ~1.5 m/s, whole-body rotations ~300 deg/s, trunk ~400 deg/s.
    return max(0.12, travel / 3.5 + 0.06, hip / 1.5 + 0.06, rot / 330.0 + 0.06)


def build_beats(beats: List[Dict[str, Any]], loop: bool, amp: float = 1.0) -> Dict[str, Any]:
    """Turn a beat list into keyframes. Beats may also be library macros ('template:variant')."""
    state = dict(rf=STANCES["standing"][0], lf=STANCES["standing"][1], height=0.0, pitch=0, roll=0, base_planted=True,
                 stance="standing", lean=5, twist=0, bend=0, ptwist=0, facing=0, hands={}, elbows={})
    first = dict(stance="standing", label="start")
    if beats and beats[0].get("stance") in STANCES:
        first["stance"] = beats[0]["stance"]
    kf0, state = _beat_keyframe(first, state, 0.0)
    keys_abs: List[Tuple[float, Dict[str, Any]]] = [(0.0, kf0)]
    clock = 0.0
    for beat in beats[:24]:
        macro = beat.get("macro", "none")
        if macro and macro != "none" and ":" in macro:
            template, variant = macro.split(":", 1)
            try:
                seg = build_segment(*resolve(template, variant)[:2], amp)
            except Exception:
                seg = None
            if seg:
                clock += 0.25
                cycles = 2 if seg["loop"] else 1
                for c in range(cycles):
                    for k in seg["keys"]:
                        keys_abs.append((clock + (c + k["t"]) * seg["duration"], copy.deepcopy(k)))
                clock += cycles * seg["duration"]
                continue
        dt = BEAT_TIME.get(beat.get("timing", "normal"), 0.55) / max(0.7, amp)
        if beat.get("timing") == "hold":
            # Hold: repeat the previous pose (no new movement), just time passing.
            last = copy.deepcopy(keys_abs[-1][1])
            clock += dt
            last["phase"] = beat.get("label", "hold")[:40]
            keys_abs.append((clock, last))
            continue
        kf, state = _beat_keyframe(beat, state, 0.0)
        # Physical speed limit: a beat can't be faster than the distance the body must travel allows
        # (an athlete can't go from standing to a plank in 0.2 s). This removes snapping transitions.
        dt = max(dt, min_transition_time(keys_abs[-1][1], kf))
        clock += dt
        keys_abs.append((clock, kf))
    if loop:
        # Transition back to the first beat obeys the same speed limit as every other beat.
        clock += max(0.4, min_transition_time(keys_abs[-1][1], keys_abs[1][1] if len(keys_abs) > 1 else kf0))
        if len(keys_abs) > 1:
            keys_abs = keys_abs[1:]  # the cycle starts at the first real beat, not the neutral start
            t0 = keys_abs[0][0]
            keys_abs = [(t - t0, k) for t, k in keys_abs]
            clock -= t0
    else:
        end, _ = _beat_keyframe(dict(stance=first["stance"], trunk="upright", facing="front", label="finish"),
                                state, 0.0)
        clock += max(0.5, min_transition_time(keys_abs[-1][1], end))
        keys_abs.append((clock, end))
    total = max(clock, 0.5)
    keys = []
    for t_abs, k in keys_abs:
        k["t"] = t_abs / total
        keys.append(k)
    if loop:
        keys = [k for k in keys if k["t"] < 0.999]
    return {"keys": keys, "duration": total, "loop": loop, "view": "three_quarter"}
