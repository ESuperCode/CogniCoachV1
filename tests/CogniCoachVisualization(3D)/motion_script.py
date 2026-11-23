"""
CogniCoach Motion Script (CMS) - a tiny language that composes stored motions into animations.

    # comment
    stance(width=wide, depth=0.5) + forehand          <- motions on one line play TOGETHER
    stance + recover_ready(hold=0.4)                  <- the next line plays AFTER the previous one
    run(pace=sprint, times=3)
    jab + stance x2                                   <- "x2" repeats the whole line
    loop                                              <- (optional) the animation loops

Every motion in motion_database.py says which BODY PARTS it drives:

    body      whole-body orientation (pitch/turn/roll) and root height (root/air)
    pelvis    hip girdle tilt / twist / side tilt
    spine     trunk lean / twist / side bend
    neck      head nod / turn / tilt
    right_arm, left_arm   shoulder raise / direction / twist + elbow bend
    right_leg, left_leg   hip raise / direction / twist (relative to the BODY) + knee bend

Parts a motion owns are "hard" or "soft". When motions on one line want the same part, a hard
owner beats a soft one (a stance's trunk lean gives way to a forehand's trunk rotation); two hard
owners of one part are an error. Parts nobody owns on a line keep the pose they had at the end of
the previous line, so a guard held on one line stays up while the legs do something else.

Lines blend into each other (joint rotations are slerped over a short window), cycles repeat to fill
their line, and one-shot actions hold their last pose. Ground contact is automatic: the root height
keeps the lowest contact point (soles, knees, hands) on the floor unless a motion is in the air.

Generic parameters accepted by every motion:
    side=left|right   mirror the motion (motions are authored for a right-handed athlete)
    speed=0.5..2      play faster / slower
    times=N           repeat (actions and cycles)
    hold=seconds      hold the end pose
    delay=seconds     start later than the other motions on the line (kinetic chain)
    start=0..1, end=0..1   play only part of an action (e.g. lunge(end=0.5) stays down in the lunge)
"""

from __future__ import annotations

import copy
import difflib
import math
import re
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

import motion_engine as me

FPS = 30
BLEND_SECONDS = 0.22
END_HOLD_SECONDS = 0.4

ARM_PARAMS = ("raise", "dir", "twist", "elbow")
LEG_PARAMS = ("raise", "dir", "twist", "knee")
PART_PARAMS: Dict[str, Tuple[str, ...]] = {
    "body": ("pitch", "turn", "roll", "root", "air"),
    "pelvis": ("tilt", "twist", "side"),
    "spine": ("lean", "twist", "side"),
    "neck": ("nod", "turn", "tilt"),
    "right_arm": ARM_PARAMS, "left_arm": ARM_PARAMS,
    "right_leg": LEG_PARAMS, "left_leg": LEG_PARAMS,
}
PARTS = list(PART_PARAMS)
NEUTRAL: Dict[str, Dict[str, float]] = {
    "body": {"pitch": 0.0, "turn": 0.0, "roll": 0.0, "root": 0.0, "air": 0.0},
    "pelvis": {"tilt": 0.0, "twist": 0.0, "side": 0.0},
    "spine": {"lean": 3.0, "twist": 0.0, "side": 0.0},
    "neck": {"nod": 0.0, "turn": 0.0, "tilt": 0.0},
    "right_arm": {"raise": 6.0, "dir": 80.0, "twist": 0.0, "elbow": 10.0},
    "left_arm": {"raise": 6.0, "dir": 80.0, "twist": 0.0, "elbow": 10.0},
    "right_leg": {"raise": 0.0, "dir": 0.0, "twist": 8.0, "knee": 4.0},
    "left_leg": {"raise": 0.0, "dir": 0.0, "twist": 8.0, "knee": 4.0},
}
GROUPS = {
    "arms": ["right_arm", "left_arm"], "legs": ["right_leg", "left_leg"],
    "upper": ["spine", "neck", "right_arm", "left_arm"],
    "lower": ["pelvis", "right_leg", "left_leg"],
    "all": PARTS,
}
# Base postures that only say "stand / be ready": a specific motion on the same line replaces them.
GENERIC_POSES = {"stand", "stance", "ready_arms", "arms_hang", "fighting_stance", "wide_defensive_stance",
                 "hands_on_hips", "arms_out", "guard"}
MAX_HOLD = 3.0
GENERIC_PARAMS = {"side", "speed", "times", "hold", "delay", "start", "end"}
KIND_RANK = {"action": 3, "cycle": 2, "pose": 1}


class ScriptError(Exception):
    pass


# -----------------------------------------------------------------------------
# Part parameters -> joint rotations
# -----------------------------------------------------------------------------
def part_rotations(pose: Dict[str, Dict[str, float]]) -> Dict[str, np.ndarray]:
    """Local joint rotation matrices (engine convention) for a full pose of part parameters."""
    b, pv, sp, nk = pose["body"], pose["pelvis"], pose["spine"], pose["neck"]
    rot = {
        "body": me.euler_to_matrix(b["pitch"], b["turn"], -b["roll"]),
        "hip": me.euler_to_matrix(pv["tilt"], pv["twist"], -pv["side"]),
        "spine": me.euler_to_matrix(sp["lean"], sp["twist"], -sp["side"]),
        "neck": me.euler_to_matrix(nk["nod"], nk["turn"], -nk["tilt"]),
    }
    for side, sign in (("right", 1.0), ("left", -1.0)):
        a = pose[f"{side}_arm"]
        rot[f"{side}shoulder"] = limb_matrix(a, sign)
        rot[f"{side}elbow"] = me.rx(-a["elbow"])
        lg = pose[f"{side}_leg"]
        # Legs are authored relative to the BODY, so turning the hips does not drag planted feet.
        rot[f"{side}hip"] = rot["hip"].T @ limb_matrix(lg, sign)
        rot[f"{side}knee"] = me.rx(lg["knee"])
    return rot


def limb_matrix(v: Dict[str, Any], sign: float) -> np.ndarray:
    """Limb (shoulder/hip) rotation from either anatomical angles or an interpolated quaternion."""
    if "q" in v:
        return me.quat_to_matrix(np.asarray(v["q"]) / np.linalg.norm(v["q"]))
    return me.limb_local_rotation(v["raise"], v["dir"], v["twist"], sign)


LIMB_SIGN = {"right_arm": 1.0, "left_arm": -1.0, "right_leg": 1.0, "left_leg": -1.0}
BEND = {"right_arm": "elbow", "left_arm": "elbow", "right_leg": "knee", "left_leg": "knee"}


STAND_SOLE_Y = me.HIP_OFFSET[1] - me.THIGH - me.SHIN - me.SOLE_DROP   # rig units below the pelvis


def _support_low(center: np.ndarray, rot: np.ndarray, half: Tuple[float, float, float]) -> float:
    """Lowest point (y) of a rounded body part: ellipsoid support along world-down."""
    return float(center[1] - math.sqrt(sum((rot[1, i] * half[i]) ** 2 for i in range(3))))


def ground_offset(pos: Dict[str, np.ndarray], world: Optional[Dict[str, np.ndarray]] = None) -> float:
    """Metres to move the body so the lowest contact point is on the floor: soles, knees, hands,
    elbows, head and - when the world rotations are given - the hips and the chest (sitting, lying)."""
    r = me.LIMB_RADIUS
    lows = [pos["right_foot"][1] - me.SOLE_DROP, pos["left_foot"][1] - me.SOLE_DROP,
            pos["right_knee"][1] - r, pos["left_knee"][1] - r,
            pos["right_hand"][1] - r, pos["left_hand"][1] - r,
            pos["right_elbow"][1] - r, pos["left_elbow"][1] - r, pos["head"][1] - 8.0]
    if world is not None:
        lows[-1] = _support_low(pos["head"], world["neck"], me.HEAD_HALF)   # rounded head (lying on the back)
        lows.append(_support_low(pos["pelvis"], world["hip"], me.PELVIS_HALF))
        lows.append(_support_low(world["spine"] @ np.array([0.0, me.TORSO_HALF[1], 0.0]), world["spine"], me.TORSO_HALF))
    return -(min(lows) - STAND_SOLE_Y) * me.UNIT_TO_M


# -----------------------------------------------------------------------------
# Motion tracks (sampling a stored motion)
# -----------------------------------------------------------------------------
class Track:
    """A stored motion with its parameters applied, sampled as part-parameter curves."""

    def __init__(self, motion: Dict[str, Any], args: Dict[str, Any]):
        self.motion = motion
        self.name = motion["name"]
        self.kind = motion["kind"]
        self.hard = list(motion["parts"])
        self.soft = list(motion.get("soft_parts", []))
        self.speed = float(args.get("speed", 1.0))
        self.times = int(args.get("times", 1))
        self.hold = float(args.get("hold", 0.0))
        self.delay = float(args.get("delay", 0.0))
        self.mirror = args.get("side", "right") == "left"
        self.start = min(0.95, max(0.0, float(args.get("start", 0.0))))
        self.end = max(self.start + 0.05, min(1.0, float(args.get("end", 1.0))))
        own = {k: v for k, v in args.items() if k not in GENERIC_PARAMS}
        keys = motion["build"](**own) if callable(motion.get("build")) else motion["keys"]
        period = None
        if isinstance(keys, dict):
            keys, period = keys["keys"], keys.get("period")
        self.loop = self.kind == "cycle"
        self.period = float(keys[-1][0]) if keys else 0.0
        if self.loop:
            self.period = float(period or motion.get("period", self.period))
        self.curves = self._curves(keys)

    def _curves(self, keys: List[Tuple[float, Dict[str, Dict[str, float]]]]):
        """Per-part curves. A part is interpolated across the keys that mention it (plus the first
        key); a key marked hold=True pins every part's current value at that time (a pause)."""
        parts = self.hard + self.soft
        state = {p: dict(NEUTRAL[p]) for p in parts}
        per_part: Dict[str, List[Tuple[float, Dict[str, float]]]] = {p: [] for p in parts}
        keys = sorted(keys, key=lambda tk: tk[0])   # stable: keys added out of order still play in time order
        for idx, (t, kv) in enumerate(keys):
            mentioned = set()
            for p, vals in kv.items():
                if p == "_hold":
                    continue
                for p2 in GROUPS.get(p, [p]):
                    if p2 in state:
                        state[p2].update(vals)
                        mentioned.add(p2)
            for p in parts:
                if idx == 0 or p in mentioned or kv.get("_hold"):
                    lst = per_part[p]
                    if lst and abs(lst[-1][0] - float(t)) < 1e-4:
                        lst[-1] = (float(t), dict(state[p]))      # same time: the later key wins
                    else:
                        lst.append((float(t), dict(state[p])))
        curves = {}
        period = self.period if self.loop else None
        for p in parts:
            ts = np.array([t for t, _ in per_part[p]])
            pv = {k: np.array([v[k] for _, v in per_part[p]]) for k in PART_PARAMS[p]}
            if p in LIMB_SIGN:
                # Limbs are interpolated as ROTATIONS (quaternion components, hemisphere-aligned):
                # no singularity when an arm/leg passes through hanging, so nothing can whip round.
                qs = []
                for i in range(len(ts)):
                    m = me.limb_local_rotation(pv["raise"][i], pv["dir"][i], pv["twist"][i], LIMB_SIGN[p])
                    q = me.matrix_to_quat(m)
                    if qs and float(np.dot(q, qs[-1])) < 0:
                        q = -q
                    qs.append(q)
                qs = np.array(qs)
                curves[p] = {"q": [_spline(ts, qs[:, c], period, q_seam=qs) for c in range(4)],
                             BEND[p]: _spline(ts, pv[BEND[p]], period)}
            else:
                curves[p] = {k: _spline(ts, arr, period) for k, arr in pv.items()}
        return curves

    @property
    def length(self) -> float:
        """Seconds this track wants on its line (cycles: one period; poses: 0)."""
        if self.kind == "pose":
            return self.delay + self.hold
        reps = self.times
        span = self.period * (self.end - self.start) if self.kind == "action" else self.period
        return self.delay + reps * span / self.speed + self.hold

    def sample(self, t_line: float, line_len: float) -> Dict[str, Dict[str, float]]:
        vals = self.curves
        tau = (t_line - self.delay) * self.speed
        if self.kind == "cycle":
            u = tau % self.period if self.period > 0 else 0.0
        elif self.kind == "pose" and self.period > 0 and self.motion.get("loop_pose"):
            u = tau % self.period
        else:
            span = self.period * (self.end - self.start)    # start=/end= play part of an action
            if self.times > 1 and span > 0:
                total = span * self.times
                tau = min(max(tau, 0.0), total)
                u = span if tau >= total else tau % span
            else:
                u = min(max(tau, 0.0), span)
            u += self.period * self.start
        out = {}
        for p, pv in vals.items():
            if "q" in pv:
                q = np.array([_eval(sp, u) for sp in pv["q"]])
                out[p] = {"q": q / np.linalg.norm(q), BEND[p]: _eval(pv[BEND[p]], u)}
            else:
                out[p] = {k: _eval(sp, u) for k, sp in pv.items()}
        if self.mirror:
            out = mirror_pose(out)
        return out

    def owned(self) -> List[Tuple[str, bool]]:
        parts = [(p, True) for p in self.hard] + [(p, False) for p in self.soft]
        if self.mirror:
            parts = [(_mirror_part(p), h) for p, h in parts]
        return parts


def _spline(ts: np.ndarray, ys: np.ndarray, period: Optional[float], q_seam: Optional[np.ndarray] = None):
    """Monotone cubic (PCHIP) through the keys: no overshoot, eases into reversals. Cycles get
    periodic tangents so the loop seam is as smooth as any other key."""
    if period and len(ts) > 1 and ts[-1] >= period - 1e-4:
        # a key AT the cycle length is the same instant as the first key: drop it (two keys at one
        # time made the periodic spline divide by zero -> NaN frames)
        ts, ys = ts[:-1], ys[:-1]
        q_seam = q_seam[:-1] if q_seam is not None else None
    if len(ts) == 1:
        return ("const", float(ys[0]))
    if period:
        first, second, last = ys[0], ys[1], ys[-1]
        if q_seam is not None and float(np.dot(q_seam[0], q_seam[-1])) < 0:
            first, second, last = -first, -second, -last   # keep the wrapped keys on the same hemisphere
            x = np.concatenate([[ts[-1] - period], ts, [period, period + ts[1]]])
            y = np.concatenate([[last], ys, [first, second]])
            return ("pchip", x, y, me.pchip_slopes(x, y))
        x = np.concatenate([[ts[-1] - period], ts, [period, period + ts[1]]])
        y = np.concatenate([[last], ys, [first, second]])
    else:
        x, y = ts, ys
    return ("pchip", x, y, me.pchip_slopes(x, y))


def _eval(sp, u: float) -> float:
    if sp[0] == "const":
        return sp[1]
    _, x, y, m = sp
    return float(me.hermite(x, y, m, np.array([u]))[0])


def _mirror_part(p: str) -> str:
    return p.replace("right", "@").replace("left", "right").replace("@", "left")


def mirror_pose(pose: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, float]]:
    out = {}
    for p, vals in pose.items():
        v = dict(vals)
        if p in ("spine", "pelvis"):
            v["twist"], v["side"] = -v["twist"], -v["side"]
        elif p == "neck":
            v["turn"], v["tilt"] = -v["turn"], -v["tilt"]
        elif p == "body":
            v["turn"], v["roll"] = -v["turn"], -v["roll"]
        elif "q" in v:
            w, x, y, z = v["q"]
            v["q"] = np.array([w, x, -y, -z])   # reflect across the body's midline
        out[_mirror_part(p)] = v
    return out


# -----------------------------------------------------------------------------
# Parser
# -----------------------------------------------------------------------------
ITEM_RE = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*(?:\((.*?)\))?\s*((?:[a-z_]+\s*=\s*[^\s,()]+[\s,]*)*)$")


def _value(text: str) -> Any:
    text = text.strip()
    try:
        return float(text) if "." in text else int(text)
    except ValueError:
        return text.strip("'\"").lower()


def parse(script: str) -> Tuple[List[Dict[str, Any]], bool, List[str]]:
    """Script text -> (lines, loop, errors). Each line: {'items': [(name, args)], 'repeat': n, 'no': i}."""
    lines, errors, loop = [], [], False
    # " / " and ";" outside parentheses also start a new line (compact one-line notation)
    flat, depth = [], 0
    for ch in script:
        depth += ch == "("
        depth -= ch == ")"
        flat.append("\n" if ch in "/;" and depth <= 0 else ch)
    script = "".join(flat)
    for no, raw in enumerate(script.splitlines(), start=1):
        text = raw.split("#", 1)[0].strip()
        if not text:
            continue
        # "plant_pole = pole_vault": the model named a step - the right-hand side is the motion
        named = re.fullmatch(r"([a-z_][a-z0-9_]*)\s*=\s*([a-z_][a-z0-9_]*(?:\s*\(.*\))?(?:\s*\+.*)?)", text)
        if named and named.group(1) not in GENERIC_PARAMS:
            text = named.group(2).strip()
        if text.lower() == "loop":
            loop = True
            continue
        if re.search(r"\s+loop$", text.lower()):        # "freestyle loop" on one line
            loop, text = True, text[: -4].strip()
        repeat = 1
        m = re.search(r"\s+[x\*]\s*(\d+)\s*$", text)
        if m:
            repeat, text = int(m.group(1)), text[:m.start()]
        depth, cur, parts = 0, "", []
        for ch in text:
            depth += ch == "("
            depth -= ch == ")"
            if ch == "+" and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        items = []
        for part in parts:
            stray = re.fullmatch(r"\s*([a-z_]+)\s*=\s*([^\s,()]+)\s*", part)
            if stray and items and stray.group(1) not in ("x",):
                items[-1][1][stray.group(1)] = _value(stray.group(2))   # "+ hold=0.5" belongs to the motion before
                continue
            mm = ITEM_RE.match(part)
            if not mm:
                errors.append(f"line {no}: cannot read '{part.strip()}' (use name or name(key=value, ...))")
                continue
            args = {}
            # name(k=v, ...) and the forgiving forms "name k=v k=v" / "name(k=v) k=v"
            arg_text = (mm.group(2) or "") + "," + re.sub(r"\s+(?=[a-z_]+\s*=)", ",", (mm.group(3) or "").strip())
            for a in filter(None, (x.strip() for x in arg_text.split(","))):
                if "=" not in a:
                    errors.append(f"line {no}: argument '{a}' must be key=value")
                    continue
                k, v = a.split("=", 1)
                args[k.strip().lower()] = _value(v)
            items.append((mm.group(1).lower(), args))
        if items:
            lines.append({"items": items, "repeat": max(1, min(10, repeat)), "no": no})
    if not lines:
        errors.append("the script has no motions")
    return lines, loop, errors


# -----------------------------------------------------------------------------
# Compiler
# -----------------------------------------------------------------------------
def _check_args(motion: Dict[str, Any], args: Dict[str, Any], where: str) -> List[str]:
    errs = []
    spec = motion.get("params", {})
    for k, v in args.items():
        if k in GENERIC_PARAMS:
            if k == "side" and v not in ("left", "right"):
                errs.append(f"{where}: side must be left or right")
            elif k != "side" and not isinstance(v, (int, float)):
                errs.append(f"{where}: {k} must be a number")
            continue
        if k not in spec:
            known = ", ".join(sorted(spec)) or "none"
            errs.append(f"{where}: {motion['name']} has no parameter '{k}' (its parameters: {known})")
            continue
        allowed = spec[k][1]
        if isinstance(allowed, tuple) and len(allowed) == 2 and all(isinstance(x, (int, float)) for x in allowed):
            if not isinstance(v, (int, float)) or not allowed[0] <= v <= allowed[1]:
                errs.append(f"{where}: {k} must be a number from {allowed[0]} to {allowed[1]}")
        elif isinstance(allowed, (list, tuple)) and v not in allowed:
            errs.append(f"{where}: {k} must be one of {', '.join(map(str, allowed))}")
    return errs


MAX_SECONDS = 12.0


def compile_script(script: str, db: Dict[str, Dict[str, Any]], dominant_side: str = "right",
                   fps: int = FPS, strict: bool = False) -> Dict[str, Any]:
    """Compile a script. Lenient (default): problems are repaired on the spot instead of failing -
    near-miss names are corrected, unknown motions and bad parameters are dropped, two motions that
    drive the same body part on one line play one after the other, and over-long clips are trimmed.
    Every repair is listed in report.warnings. strict=True turns them into errors."""
    lines, loop, errors = parse(script)
    warnings: List[str] = []
    if not strict and errors:
        warnings += [e + " - skipped" for e in errors if e != "the script has no motions"]
        errors = [e for e in errors if e == "the script has no motions"]
    built = []
    for line in lines:
        sublines: List[List[Track]] = [[]]
        for name, args in line["items"]:
            where = f"line {line['no']} '{name}'"
            if name not in db:
                try:
                    from motion_database import NAME_ALIASES
                except ImportError:
                    NAME_ALIASES = {}
                if name in NAME_ALIASES:
                    am = ITEM_RE.match(NAME_ALIASES[name])
                    alias_args = {}
                    for a in filter(None, (x.strip() for x in (am.group(2) or "").split(","))):
                        kk, vv = a.split("=", 1)
                        alias_args[kk.strip()] = _value(vv)
                    warnings.append(f"{where}: read as '{NAME_ALIASES[name]}'")
                    name, args = am.group(1), {**alias_args, **args}
            if name not in db:
                guess = difflib.get_close_matches(name, list(db), n=1, cutoff=0.75)
                if guess:
                    warnings.append(f"{where}: unknown motion, used '{guess[0]}'")
                    name = guess[0]
            if name not in db:
                close = difflib.get_close_matches(name, list(db), n=5, cutoff=0.45)
                msg = f"{where}: unknown motion" + (f" (similar: {', '.join(close)})" if close else "")
                (errors if strict else warnings).append(msg + ("" if strict else " - skipped"))
                continue
            errs = _check_args(db[name], args, where)
            if errs:
                if strict:
                    errors += errs
                    continue
                warnings += [e + " - ignored" for e in errs]
                args = {k: v for k, v in args.items() if not _check_args(db[name], {k: v}, where)}
            if isinstance(args.get("hold"), (int, float)) and args["hold"] > MAX_HOLD:
                warnings.append(f"{where}: hold={args['hold']} shortened to {MAX_HOLD:.0f} s")
                args = {**args, "hold": MAX_HOLD}
            tr = Track(db[name], args)
            target = sublines[-1]
            clash = [o for o in target if {p for p, h in o.owned() if h} & {p for p, h in tr.owned() if h}]
            new_hard = {p for p, h in tr.owned() if h}

            def overlay(o: Track) -> bool:
                old_hard = {p for p, h in o.owned() if h}
                if tr.name in GENERIC_POSES or o.name in GENERIC_POSES:
                    return False     # generic poses have their own rule: they give way
                return ((new_hard < old_hard and o.kind in ("pose", "cycle")) or
                        (old_hard < new_hard and tr.kind in ("pose", "cycle")))
            if clash:
                if strict and not all(overlay(o) for o in clash):
                    for o in clash:
                        parts = sorted({p for p, h in o.owned() if h} & {p for p, h in tr.owned() if h})
                        errors.append(f"line {line['no']}: '{tr.name}' and '{o.name}' both drive {', '.join(parts)}; "
                                      "put them on different lines or pick motions that use different body parts")
                    continue
                # A held pose only describes where the body is while the other motion plays: the
                # moving motion wins and the pose is dropped (it must not play afterwards - e.g.
                # "start_dive + stand" must not stand up). Two real motions play one after another.
                generic_new = tr.name in GENERIC_POSES
                generic_old = [o for o in clash if o.name in GENERIC_POSES]
                if generic_new:
                    warnings.append(f"line {line['no']}: '{tr.name}' dropped - '{clash[0].name}' already drives those parts")
                    continue
                poses = generic_old
                if len(poses) == len(clash):
                    for o in poses:
                        target.remove(o)
                    warnings.append(f"line {line['no']}: '{', '.join(o.name for o in poses)}' dropped - "
                                    f"'{tr.name}' drives those parts")
                    target.append(tr)
                    continue
                # Base + overlay: a pose / cycle (board_stance, tread_water) and a motion that drives only
                # some of its parts (single_blade_paddle, a shot) play TOGETHER - the more specific motion
                # takes the shared parts (the owner ranking below), the base keeps the rest.
                if all(overlay(o) for o in clash):
                    # ...except a posture pose (sit_on_bench, kneel) inside a moving motion that already has
                    # its own posture (paddling is seated): the pose is dropped, the motion plays as stored.
                    lower = {"body", "right_leg", "left_leg"}
                    if tr.kind == "pose" and new_hard & lower and all(o.kind != "pose" and new_hard < {p for p, h in o.owned() if h}
                                                                      for o in clash):
                        warnings.append(f"line {line['no']}: '{tr.name}' dropped - '{clash[0].name}' already has its posture")
                        continue
                    posture = [o for o in clash if o.kind == "pose" and {p for p, h in o.owned() if h} & lower
                               and tr.kind != "pose" and {p for p, h in o.owned() if h} < new_hard]
                    for o in posture:
                        target.remove(o)
                        warnings.append(f"line {line['no']}: '{o.name}' dropped - '{tr.name}' already has its posture")
                    target.append(tr)
                    continue
                warnings.append(f"line {line['no']}: '{tr.name}' and '{clash[0].name}' drive the same body parts - "
                                f"'{tr.name}' plays right after it")
                sublines.append([tr])
            else:
                target.append(tr)
        for tracks in sublines:
            if not tracks:
                continue
            owners: Dict[str, Tuple[Track, bool]] = {}
            for tr in tracks:
                for part, hard in tr.owned():
                    if part not in owners:
                        owners[part] = (tr, hard)
                        continue
                    cur, cur_hard = owners[part]
                    if hard and not cur_hard:
                        owners[part] = (tr, hard)
                    elif hard == cur_hard and (
                            {p for p, h in tr.owned() if h} < {p for p, h in cur.owned() if h} or
                            (not {p for p, h in cur.owned() if h} < {p for p, h in tr.owned() if h} and
                             (KIND_RANK[tr.kind], -len(tr.owned())) > (KIND_RANK[cur.kind], -len(cur.owned())))):
                        # tie: the more specific motion (fewer body parts) wins - "stand + ready_arms" shows the arms
                        owners[part] = (tr, hard)
            built.append((tracks, line["repeat"], line["no"], owners))
    if errors:
        raise ScriptError("\n".join(errors))
    if not built:
        raise ScriptError("the script has no usable motions")
    # Keep the clip short: trim repetitions (largest first) until it fits.
    def total() -> float:
        return sum(_line_length(t) * r for t, r, _, _ in built)
    trimmed = False
    while total() > MAX_SECONDS:
        cands = [(tr.times, tr) for t, r, _, _ in built for tr in t if tr.times > 1]
        reps = [(r, i) for i, (t, r, _, _) in enumerate(built) if r > 1]
        if reps and (not cands or max(reps)[0] >= max(c[0] for c in cands)):
            i = max(reps)[1]
            t, r, n, o = built[i]
            built[i] = (t, r - 1, n, o)
        elif cands:
            max(cands, key=lambda c: c[0])[1].times -= 1
        else:
            break
        trimmed = True
    if total() > MAX_SECONDS:
        # still too long: shorten every hold proportionally (holds are the only other free time)
        holds = [tr for t, r, _, _ in built for tr in t if tr.hold > 0]
        if holds:
            excess = total() - MAX_SECONDS
            sum_h = sum(tr.hold for tr in holds)
            for tr in holds:
                tr.hold = max(0.2, tr.hold - excess * tr.hold / sum_h)
            trimmed = True
    if trimmed:
        warnings.append(f"repetitions / holds trimmed so the clip stays under {MAX_SECONDS:.0f} s")

    # timeline
    pose = {p: dict(v) for p, v in NEUTRAL.items()}
    prev_rot: Optional[Dict[str, np.ndarray]] = None
    samples: List[Tuple[Dict[str, Dict[str, float]], Dict[str, float]]] = []
    line_info = []
    first = True
    for tracks, repeat, no, owners in built:
        L = _line_length(tracks)
        for _ in range(repeat):
            start_pose = {p: dict(v) for p, v in pose.items()}
            n = max(1, int(round(L * fps)))
            for i in range(n):
                t = i / fps
                cur = {p: dict(v) for p, v in start_pose.items()}
                sampled = {id(tr): tr.sample(t, L) for tr in tracks}
                for part, (tr, _) in owners.items():
                    cur[part] = sampled[id(tr)][part]
                w = 1.0 if first else _smooth(min(1.0, t / BLEND_SECONDS))
                samples.append((cur, {"w": w, "start": start_pose}))
            last = {p: dict(v) for p, v in start_pose.items()}
            for part, (tr, _) in owners.items():
                last[part] = tr.sample(L - 1e-6, L)[part]
            pose = last
            first = False
        line_info.append({"line": no, "seconds": round(L * repeat, 2),
                          "parts": {p: tr.name for p, (tr, _) in owners.items()}})
    if not loop:
        for _ in range(int(END_HOLD_SECONDS * fps)):
            samples.append(({p: dict(v) for p, v in pose.items()}, {"w": 1.0, "start": pose}))

    frames = _frames(samples, loop, fps)
    if dominant_side == "left":
        frames = [_mirror_frame(f) for f in frames]
    report = _check(frames)
    ground = not any(abs(s[0]["body"]["pitch"]) > 45 or abs(s[0]["body"]["roll"]) > 45 or s[0]["body"]["air"] > 0.9
                     and abs(s[0]["body"]["pitch"]) > 30 for s in samples)
    report["warnings"] = warnings
    return {"frames": frames, "fps": fps, "loop": loop, "lines": line_info, "report": report, "ground": ground,
            "duration_seconds": round(len(frames) / fps, 2)}


def _line_length(tracks: List["Track"]) -> float:
    acts = [tr.length for tr in tracks if tr.kind == "action"]
    cyc = [tr.length for tr in tracks if tr.kind == "cycle"]
    poses = [tr.length for tr in tracks if tr.kind == "pose"]
    L = max(acts) if acts else max(cyc) if cyc else max([0.6] + poses)
    return max(L, max(poses) if poses else 0.0)


def _smooth(u: float) -> float:
    return u * u * (3 - 2 * u)


ARM_WAYPOINTS = [  # arm detours (out to the own side, or up) for blends that would pass through the body
    {"raise": 60.0, "dir": 95.0, "twist": 0.0, "elbow": 30.0},
    {"raise": 110.0, "dir": 60.0, "twist": 0.0, "elbow": 30.0},
    {"raise": 45.0, "dir": 30.0, "twist": 0.0, "elbow": 60.0},
]


def _slerp_m(a: np.ndarray, b: np.ndarray, u: float) -> np.ndarray:
    return me.quat_to_matrix(me.slerp(me.matrix_to_quat(a), me.matrix_to_quat(b), u))


def _arm_route_penetration(r0, r1, side: str, wp=None) -> float:
    """Worst arm/body penetration along a blend from rotations r0 to r1 (optionally via waypoint rotations)."""
    worst = 0.0
    sh, el = f"{side}shoulder", f"{side}elbow"
    for u in (0.2, 0.35, 0.5, 0.65, 0.8):
        rot = {j: _slerp_m(r0[j], r1[j], u) for j in r1}
        if wp is not None:
            for j in (sh, el):
                rot[j] = _slerp_m(r0[j], wp[j], u / 0.5) if u < 0.5 else _slerp_m(wp[j], r1[j], (u - 0.5) / 0.5)
        world = me.world_rotations(rot)
        worst = max(worst, body_penetration(world, me.forward_kinematics(world), side))
    return worst


def _frames(samples, loop: bool, fps: int) -> List[Dict[str, float]]:
    frames: List[Dict[str, float]] = []
    prev_e: Dict[str, Tuple[float, float, float]] = {}
    routes: Dict[int, Dict[str, Any]] = {}    # one detour decision per line transition (no flicker)
    for idx, (pose, blend) in enumerate(samples):
        rot = part_rotations(pose)
        w = blend["w"]
        scal = pose["body"]
        if w < 1.0:
            r0 = part_rotations(blend["start"])
            key = id(blend["start"])
            if key not in routes:
                routes[key] = {}
                for side, sign in (("right", 1.0), ("left", -1.0)):
                    if _arm_route_penetration(r0, rot, side) <= 0.03:
                        continue
                    best = None
                    for wpa in ARM_WAYPOINTS:
                        wp = dict(rot)
                        wp[f"{side}shoulder"] = me.limb_local_rotation(wpa["raise"], wpa["dir"], wpa["twist"], sign)
                        wp[f"{side}elbow"] = me.rx(-wpa["elbow"])
                        d = _arm_route_penetration(r0, rot, side, wp)
                        if best is None or d < best[0]:
                            best = (d, wp)
                    if best and best[0] <= 0.03:
                        routes[key][side] = best[1]
            blended = {j: _slerp_m(r0[j], rot[j], w) for j in rot}
            for side, wp in routes[key].items():
                for j in (f"{side}shoulder", f"{side}elbow"):
                    blended[j] = _slerp_m(r0[j], wp[j], w / 0.5) if w < 0.5 else _slerp_m(wp[j], rot[j], (w - 0.5) / 0.5)
            rot = blended
            scal = {k: blend["start"]["body"][k] + (pose["body"][k] - blend["start"]["body"][k]) * w for k in scal}
        world = me.world_rotations(rot)
        pos = me.forward_kinematics(world)
        f: Dict[str, float] = {}
        for j in me.JOINT_NAMES:
            e = me._closest_euler(rot[j], prev_e.get(j))
            prev_e[j] = e
            f[j + "x"], f[j + "y"], f[j + "z"] = (round(v, 2) for v in e)
        f["positionx"], f["positiony"], f["positionz"] = (round(scal["pitch"], 2), round(scal["turn"], 2),
                                                          round(-scal["roll"], 2))
        air = max(0.0, min(1.0, scal["air"]))
        f["rooty"] = round((1 - air) * ground_offset(pos, world) + scal["root"], 3)
        frames.append(f)
    return frames


def _mirror_frame(f: Dict[str, float]) -> Dict[str, float]:
    out = {}
    for k, v in f.items():
        k2 = _mirror_part(k)
        if k2[-1] in "yz" and k2 not in ("rooty",):
            v = -v
        out[k2] = v
    out["positiony"], out["positionz"] = -f.get("positiony", 0.0), -f.get("positionz", 0.0)
    return out


# Rounded body volumes matching the rendered rig (rig units): elliptic chest and hips, ellipsoid head.
def body_penetration(world: Dict[str, np.ndarray], pos: Dict[str, np.ndarray], side: str) -> float:
    """Deepest penetration (metres) of this arm into the chest, hips or head."""
    r = me.LIMB_RADIUS * 0.8
    sh, el, ha = pos[side + "_shoulder"], pos[side + "_elbow"], pos[side + "_hand"]
    vols = [  # (frame rotation, origin, (half x, half y range lo, hi, half z)) as elliptic cylinders
        (world["spine"], np.zeros(3), (me.TORSO_HALF[0], 0.0, 2 * me.TORSO_HALF[1], me.TORSO_HALF[2])),
        (world["hip"], np.zeros(3), (me.PELVIS_HALF[0], -me.PELVIS_HALF[1], me.PELVIS_HALF[1], me.PELVIS_HALF[2])),
    ]
    head_c = pos["neck"] + world["neck"] @ np.array([0.0, me.HEAD_HALF[1], 0.0])
    best = 0.0
    for a, b in ((sh + (el - sh) * 0.35, el), (el, ha)):
        for u in np.linspace(0.0, 1.0, 9):
            pt = a + (b - a) * u
            for rot, org, (hx, ylo, yhi, hz) in vols:
                q = rot.T @ (pt - org)
                if ylo - r < q[1] < yhi + r:
                    e = math.hypot(q[0] / (hx + r), q[2] / (hz + r))
                    if e < 1.0:
                        best = max(best, (1.0 - e) * min(hx + r, hz + r))
            q = world["neck"].T @ (pt - head_c)
            e = math.sqrt((q[0] / (me.HEAD_HALF[0] + r)) ** 2 + (q[1] / (me.HEAD_HALF[1] + r)) ** 2
                          + (q[2] / (me.HEAD_HALF[2] + r)) ** 2)
            if e < 1.0:
                best = max(best, (1.0 - e) * (me.HEAD_HALF[0] + r))
    return best * me.UNIT_TO_M


def _check(frames: List[Dict[str, float]]) -> Dict[str, Any]:
    """Objective checks on the result: arm/body penetration and joint pops."""
    worst_pen, pops, prev, prev2 = 0.0, 0.0, None, None
    bad = sum(1 for f in frames if not all(math.isfinite(v) for v in f.values()))
    if bad:
        return {"max_arm_penetration_m": 0.0, "max_joint_step_m": 0.0, "issues": [f"{bad} frames are not finite (NaN)"]}
    for f in frames:
        local = {j: me.frame_rotation(f, j) for j in me.JOINT_NAMES}
        local["body"] = np.eye(3)
        world = me.world_rotations(local)
        pos = me.forward_kinematics(world)
        for side in ("right", "left"):
            worst_pen = max(worst_pen, body_penetration(world, pos, side))
        if prev is not None and prev2 is not None:
            # a pop = a sudden change of velocity (second difference), not merely a fast limb
            pops = max(pops, max(float(np.linalg.norm(pos[k] - 2 * prev[k] + prev2[k])) for k in pos) * me.UNIT_TO_M)
        prev2, prev = prev, pos
    issues = []
    if worst_pen > 0.03:
        issues.append(f"an arm passes {worst_pen * 100:.0f} cm into the body")
    if pops > 1.5:
        issues.append(f"a joint changes speed abruptly ({pops:.2f} m/frame^2)")
    return {"max_arm_penetration_m": round(worst_pen, 3), "max_joint_step_m": round(pops, 3), "issues": issues}
