// CogniCoach Motion Script - parser + compiler. A port of motion_script.py (see that file for the
// language description). Motions on one line play together, the next line plays after it.
import * as me from "./rig.js";
import { getCloseMatches } from "./difflib.js";
import { MOTIONS, MOTION_NAMES, NAME_ALIASES, NEUTRAL, buildKeys, hasMotion } from "./db.js";

export const FPS = 30;
const BLEND_SECONDS = 0.22;
const END_HOLD_SECONDS = 0.4;
const MAX_HOLD = 3.0;
const MAX_SECONDS = 12.0;

const ARM_PARAMS = ["raise", "dir", "twist", "elbow"];
const LEG_PARAMS = ["raise", "dir", "twist", "knee"];
const PART_PARAMS = {
  body: ["pitch", "turn", "roll", "root", "air"],
  pelvis: ["tilt", "twist", "side"],
  spine: ["lean", "twist", "side"],
  neck: ["nod", "turn", "tilt"],
  right_arm: ARM_PARAMS, left_arm: ARM_PARAMS,
  right_leg: LEG_PARAMS, left_leg: LEG_PARAMS,
};
const PARTS = Object.keys(PART_PARAMS);
const GROUPS = {
  arms: ["right_arm", "left_arm"], legs: ["right_leg", "left_leg"],
  upper: ["spine", "neck", "right_arm", "left_arm"],
  lower: ["pelvis", "right_leg", "left_leg"],
  all: PARTS,
};
const GENERIC_POSES = new Set(["stand", "stance", "ready_arms", "arms_hang", "fighting_stance", "wide_defensive_stance",
  "hands_on_hips", "arms_out", "guard"]);
const GENERIC_PARAMS = new Set(["side", "speed", "times", "hold", "delay", "start", "end"]);
const KIND_RANK = { action: 3, cycle: 2, pose: 1 };
const LIMB_SIGN = { right_arm: 1, left_arm: -1, right_leg: 1, left_leg: -1 };
const BEND = { right_arm: "elbow", left_arm: "elbow", right_leg: "knee", left_leg: "knee" };
const STAND_SOLE_Y = me.HIP_OFFSET[1] - me.THIGH - me.SHIN - me.SOLE_DROP;
const ARMS = new Set(["right_arm", "left_arm"]);

export class ScriptError extends Error {}

const copyPose = (pose) => {
  const out = {};
  for (const p in pose) out[p] = { ...pose[p] };
  return out;
};

// ---------------------------------------------------------------------------
// Part parameters -> joint rotations
// ---------------------------------------------------------------------------
function limbMatrix(v, sign) {
  if (v.q) return me.quatToMatrix(me.qnormalize(v.q));
  return me.limbLocalRotation(v.raise, v.dir, v.twist, sign);
}

function partRotations(pose) {
  const b = pose.body, pv = pose.pelvis, sp = pose.spine, nk = pose.neck;
  const rot = {
    body: me.eulerToMatrix(b.pitch, b.turn, -b.roll),
    hip: me.eulerToMatrix(pv.tilt, pv.twist, -pv.side),
    spine: me.eulerToMatrix(sp.lean, sp.twist, -sp.side),
    neck: me.eulerToMatrix(nk.nod, nk.turn, -nk.tilt),
  };
  const hipT = me.transpose(rot.hip);
  for (const [side, sign] of [["right", 1], ["left", -1]]) {
    const a = pose[side + "_arm"];
    rot[side + "shoulder"] = limbMatrix(a, sign);
    rot[side + "elbow"] = me.rx(-a.elbow);
    const lg = pose[side + "_leg"];
    rot[side + "hip"] = me.mul(hipT, limbMatrix(lg, sign));
    rot[side + "knee"] = me.rx(lg.knee);
  }
  return rot;
}

function supportLow(center, rot, half) {
  return center[1] - Math.sqrt((rot[3] * half[0]) ** 2 + (rot[4] * half[1]) ** 2 + (rot[5] * half[2]) ** 2);
}

function groundOffset(pos, world) {
  const r = me.LIMB_RADIUS;
  const lows = [pos.right_foot[1] - me.SOLE_DROP, pos.left_foot[1] - me.SOLE_DROP,
    pos.right_knee[1] - r, pos.left_knee[1] - r,
    pos.right_hand[1] - r, pos.left_hand[1] - r,
    pos.right_elbow[1] - r, pos.left_elbow[1] - r, pos.head[1] - 8.0];
  if (world) {
    lows[lows.length - 1] = supportLow(pos.head, world.neck, me.HEAD_HALF);
    lows.push(supportLow(pos.pelvis, world.hip, me.PELVIS_HALF));
    lows.push(supportLow(me.mulv(world.spine, [0, me.TORSO_HALF[1], 0]), world.spine, me.TORSO_HALF));
  }
  return -(Math.min(...lows) - STAND_SOLE_Y) * me.UNIT_TO_M;
}

// ---------------------------------------------------------------------------
// Splines
// ---------------------------------------------------------------------------
function spline(ts, ys, period, qSeam) {
  if (period && ts.length > 1 && ts[ts.length - 1] >= period - 1e-4) {
    ts = ts.slice(0, -1);
    ys = ys.slice(0, -1);
    if (qSeam) qSeam = qSeam.slice(0, -1);
  }
  if (ts.length === 1) return { c: ys[0] };
  let x, y;
  if (period) {
    let first = ys[0], second = ys[1], last = ys[ys.length - 1];
    if (qSeam && me.qdot(qSeam[0], qSeam[qSeam.length - 1]) < 0) {
      first = -first; second = -second; last = -last;
    }
    x = [ts[ts.length - 1] - period, ...ts, period, period + ts[1]];
    y = [last, ...ys, first, second];
  } else {
    x = ts; y = ys;
  }
  return { x, y, m: me.pchipSlopes(x, y) };
}

const evalSpline = (sp, u) => ("c" in sp ? sp.c : me.hermite(sp.x, sp.y, sp.m, u));

const mirrorPart = (p) => p.replace(/right/g, "@").replace(/left/g, "right").replace(/@/g, "left");

function mirrorPose(pose) {
  const out = {};
  for (const p in pose) {
    const v = { ...pose[p] };
    if (p === "spine" || p === "pelvis") { v.twist = -v.twist; v.side = -v.side; }
    else if (p === "neck") { v.turn = -v.turn; v.tilt = -v.tilt; }
    else if (p === "body") { v.turn = -v.turn; v.roll = -v.roll; }
    else if (v.q) { const [w, x, y, z] = v.q; v.q = [w, x, -y, -z]; }
    out[mirrorPart(p)] = v;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Motion tracks (sampling a stored motion)
// ---------------------------------------------------------------------------
class Track {
  constructor(name, args) {
    const motion = MOTIONS[name];
    this.motion = motion;
    this.name = name;
    this.kind = motion.kind;
    this.hard = [...motion.parts];
    this.soft = [...(motion.soft || [])];
    this.speed = Number(args.speed ?? 1);
    this.times = Math.trunc(Number(args.times ?? 1));
    this.hold = Number(args.hold ?? 0);
    this.delay = Number(args.delay ?? 0);
    this.mirror = args.side === "left";
    this.start = Math.min(0.95, Math.max(0, Number(args.start ?? 0)));
    this.end = Math.max(this.start + 0.05, Math.min(1, Number(args.end ?? 1)));
    const own = {};
    for (const k in args) if (!GENERIC_PARAMS.has(k)) own[k] = args[k];
    const built = buildKeys(name, own);
    const keys = built.keys;
    this.loop = this.kind === "cycle";
    this.period = keys.length ? keys[keys.length - 1][0] : 0;
    if (this.loop) this.period = Number(built.period || motion.period || this.period);
    this._keys = keys;
    this._curveCache = null;
  }

  // Curves are built on first use, so validating a script (Worker side) stays cheap.
  get curves() {
    if (!this._curveCache) this._curveCache = this._curves(this._keys);
    return this._curveCache;
  }

  _curves(keys) {
    const parts = [...this.hard, ...this.soft];
    const state = {};
    const perPart = {};
    for (const p of parts) { state[p] = { ...NEUTRAL[p] }; perPart[p] = []; }
    keys = [...keys].sort((a, b) => a[0] - b[0]);
    keys.forEach(([t, kv, hold], idx) => {
      const mentioned = new Set();
      for (const p in kv) {
        for (const p2 of GROUPS[p] || [p]) {
          if (p2 in state) {
            Object.assign(state[p2], kv[p]);
            mentioned.add(p2);
          }
        }
      }
      for (const p of parts) {
        if (idx === 0 || mentioned.has(p) || hold) {
          const lst = perPart[p];
          if (lst.length && Math.abs(lst[lst.length - 1][0] - t) < 1e-4) lst[lst.length - 1] = [t, { ...state[p] }];
          else lst.push([t, { ...state[p] }]);
        }
      }
    });
    const curves = {};
    const period = this.loop ? this.period : null;
    for (const p of parts) {
      const ts = perPart[p].map((e) => e[0]);
      const col = (k) => perPart[p].map((e) => e[1][k]);
      if (p in LIMB_SIGN) {
        const qs = [];
        for (const [, v] of perPart[p]) {
          let q = me.matrixToQuat(me.limbLocalRotation(v.raise, v.dir, v.twist, LIMB_SIGN[p]));
          if (qs.length && me.qdot(q, qs[qs.length - 1]) < 0) q = [-q[0], -q[1], -q[2], -q[3]];
          qs.push(q);
        }
        curves[p] = {
          q: [0, 1, 2, 3].map((c) => spline(ts, qs.map((q) => q[c]), period, qs)),
          [BEND[p]]: spline(ts, col(BEND[p]), period),
        };
      } else {
        const c = {};
        for (const k of PART_PARAMS[p]) c[k] = spline(ts, col(k), period);
        curves[p] = c;
      }
    }
    return curves;
  }

  get length() {
    if (this.kind === "pose") return this.delay + this.hold;
    const span = this.kind === "action" ? this.period * (this.end - this.start) : this.period;
    return this.delay + (this.times * span) / this.speed + this.hold;
  }

  sample(tLine) {
    let tau = (tLine - this.delay) * this.speed;
    let u;
    if (this.kind === "cycle") {
      u = this.period > 0 ? me.pmod(tau, this.period) : 0;
    } else if (this.kind === "pose" && this.period > 0 && this.motion.loop_pose) {
      u = me.pmod(tau, this.period);
    } else {
      const span = this.period * (this.end - this.start);
      if (this.times > 1 && span > 0) {
        const total = span * this.times;
        tau = Math.min(Math.max(tau, 0), total);
        u = tau >= total ? span : me.pmod(tau, span);
      } else {
        u = Math.min(Math.max(tau, 0), span);
      }
      u += this.period * this.start;
    }
    let out = {};
    for (const p in this.curves) {
      const pv = this.curves[p];
      if (pv.q) {
        out[p] = { q: me.qnormalize(pv.q.map((sp) => evalSpline(sp, u))), [BEND[p]]: evalSpline(pv[BEND[p]], u) };
      } else {
        const o = {};
        for (const k in pv) o[k] = evalSpline(pv[k], u);
        out[p] = o;
      }
    }
    if (this.mirror) out = mirrorPose(out);
    return out;
  }

  owned() {
    let parts = [...this.hard.map((p) => [p, true]), ...this.soft.map((p) => [p, false])];
    if (this.mirror) parts = parts.map(([p, h]) => [mirrorPart(p), h]);
    return parts;
  }

  hardSet() {
    return new Set(this.owned().filter(([, h]) => h).map(([p]) => p));
  }
}

// ---------------------------------------------------------------------------
// Parser
// ---------------------------------------------------------------------------
const ITEM_RE = /^\s*([a-z_][a-z0-9_]*)\s*(?:\((.*?)\))?\s*((?:[a-z_]+\s*=\s*[^\s,()]+[\s,]*)*)$/;

function pyValue(text) {
  text = text.trim();
  if (text.includes(".")) {
    if (/^\s*[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\s*$/.test(text)) return parseFloat(text);
  } else if (/^\s*[+-]?\d+\s*$/.test(text)) {
    return parseInt(text, 10);
  }
  return text.replace(/^['"]+|['"]+$/g, "").toLowerCase();
}

export function parse(script) {
  const lines = [], errors = [];
  let loop = false;
  let flat = "", depth = 0;
  for (const ch of script) {
    depth += ch === "(" ? 1 : 0;
    depth -= ch === ")" ? 1 : 0;
    flat += (ch === "/" || ch === ";") && depth <= 0 ? "\n" : ch;
  }
  const raws = flat.split(/\r\n|\r|\n/);
  raws.forEach((raw, i) => {
    const no = i + 1;
    let text = raw.split("#")[0].trim();
    if (!text) return;
    const named = text.match(/^([a-z_][a-z0-9_]*)\s*=\s*([a-z_][a-z0-9_]*(?:\s*\(.*\))?(?:\s*\+.*)?)$/s);
    if (named && !GENERIC_PARAMS.has(named[1])) text = named[2].trim();
    if (text.toLowerCase() === "loop") { loop = true; return; }
    if (/\s+loop$/.test(text.toLowerCase())) { loop = true; text = text.slice(0, -4).trim(); }
    let repeat = 1;
    const m = text.match(/\s+[x*]\s*(\d+)\s*$/);
    if (m) { repeat = parseInt(m[1], 10); text = text.slice(0, m.index); }
    let d = 0, cur = "";
    const parts = [];
    for (const ch of text) {
      d += ch === "(" ? 1 : 0;
      d -= ch === ")" ? 1 : 0;
      if (ch === "+" && d === 0) { parts.push(cur); cur = ""; } else cur += ch;
    }
    parts.push(cur);
    const items = [];
    for (const part of parts) {
      const stray = part.match(/^\s*([a-z_]+)\s*=\s*([^\s,()]+)\s*$/);
      if (stray && items.length && stray[1] !== "x") {
        items[items.length - 1][1][stray[1]] = pyValue(stray[2]);
        continue;
      }
      const mm = part.match(ITEM_RE);
      if (!mm) {
        errors.push(`line ${no}: cannot read '${part.trim()}' (use name or name(key=value, ...))`);
        continue;
      }
      const args = {};
      const argText = (mm[2] || "") + "," + (mm[3] || "").trim().replace(/\s+(?=[a-z_]+\s*=)/g, ",");
      for (const a of argText.split(",").map((x) => x.trim()).filter(Boolean)) {
        if (!a.includes("=")) {
          errors.push(`line ${no}: argument '${a}' must be key=value`);
          continue;
        }
        const eq = a.indexOf("=");
        args[a.slice(0, eq).trim().toLowerCase()] = pyValue(a.slice(eq + 1));
      }
      items.push([mm[1].toLowerCase(), args]);
    }
    if (items.length) lines.push({ items, repeat: Math.max(1, Math.min(10, repeat)), no });
  });
  if (!lines.length) errors.push("the script has no motions");
  return { lines, loop, errors };
}

// ---------------------------------------------------------------------------
// Compiler
// ---------------------------------------------------------------------------
const isNum = (v) => typeof v === "number";

function checkArgs(name, args, where) {
  const errs = [];
  const spec = MOTIONS[name].params || {};
  for (const [k, v] of Object.entries(args)) {
    if (GENERIC_PARAMS.has(k)) {
      if (k === "side" && v !== "left" && v !== "right") errs.push(`${where}: side must be left or right`);
      else if (k !== "side" && !isNum(v)) errs.push(`${where}: ${k} must be a number`);
      continue;
    }
    if (!(k in spec)) {
      const known = Object.keys(spec).sort().join(", ") || "none";
      errs.push(`${where}: ${name} has no parameter '${k}' (its parameters: ${known})`);
      continue;
    }
    const s = spec[k];
    if (s.range) {
      if (!isNum(v) || !(s.range[0] <= v && v <= s.range[1])) errs.push(`${where}: ${k} must be a number from ${s.range[0]} to ${s.range[1]}`);
    } else if (!s.choices.includes(v)) {
      errs.push(`${where}: ${k} must be one of ${s.choices.join(", ")}`);
    }
  }
  return errs;
}

const isSubset = (a, b) => { for (const x of a) if (!b.has(x)) return false; return true; };
const isProperSubset = (a, b) => a.size < b.size && isSubset(a, b);
const intersect = (a, b) => new Set([...a].filter((x) => b.has(x)));
const union = (a, b) => new Set([...a, ...b]);

function lineLength(tracks) {
  const acts = tracks.filter((t) => t.kind === "action").map((t) => t.length);
  const cyc = tracks.filter((t) => t.kind === "cycle").map((t) => t.length);
  const poses = tracks.filter((t) => t.kind === "pose").map((t) => t.length);
  const L = acts.length ? Math.max(...acts) : cyc.length ? Math.max(...cyc) : Math.max(0.6, ...poses);
  return Math.max(L, poses.length ? Math.max(...poses) : 0);
}

const smooth = (u) => u * u * (3 - 2 * u);

/**
 * Compile a script. Lenient (default): problems are repaired on the spot - near-miss names are
 * corrected, unknown motions and bad parameters are dropped, two motions that drive the same body
 * part on one line play one after the other, over-long clips are trimmed (all listed in
 * report.warnings). strict=true turns them into errors. validateOnly=true stops before animating.
 */
export function compileScript(script, { dominantSide = "right", fps = FPS, strict = false, validateOnly = false } = {}) {
  const parsed = parse(script);
  const { lines, loop } = parsed;
  let errors = parsed.errors;
  const warnings = [];
  if (!strict && errors.length) {
    for (const e of errors) if (e !== "the script has no motions") warnings.push(e + " - skipped");
    errors = errors.filter((e) => e === "the script has no motions");
  }
  const built = [];
  for (const line of lines) {
    const sublines = [[]];
    for (let [name, args] of line.items) {
      const where = `line ${line.no} '${name}'`;
      if (!hasMotion(name) && Object.prototype.hasOwnProperty.call(NAME_ALIASES, name)) {
        const am = NAME_ALIASES[name].match(ITEM_RE);
        const aliasArgs = {};
        for (const a of (am[2] || "").split(",").map((x) => x.trim()).filter(Boolean)) {
          const eq = a.indexOf("=");
          aliasArgs[a.slice(0, eq).trim()] = pyValue(a.slice(eq + 1));
        }
        warnings.push(`${where}: read as '${NAME_ALIASES[name]}'`);
        name = am[1];
        args = { ...aliasArgs, ...args };
      }
      if (!hasMotion(name)) {
        const guess = getCloseMatches(name, MOTION_NAMES, 1, 0.75);
        if (guess.length) {
          warnings.push(`${where}: unknown motion, used '${guess[0]}'`);
          name = guess[0];
        }
      }
      if (!hasMotion(name)) {
        const close = getCloseMatches(name, MOTION_NAMES, 5, 0.45);
        const msg = `${where}: unknown motion` + (close.length ? ` (similar: ${close.join(", ")})` : "");
        (strict ? errors : warnings).push(msg + (strict ? "" : " - skipped"));
        continue;
      }
      const errs = checkArgs(name, args, where);
      if (errs.length) {
        if (strict) { errors.push(...errs); continue; }
        warnings.push(...errs.map((e) => e + " - ignored"));
        const kept = {};
        for (const [k, v] of Object.entries(args)) if (!checkArgs(name, { [k]: v }, where).length) kept[k] = v;
        args = kept;
      }
      if (isNum(args.hold) && args.hold > MAX_HOLD) {
        warnings.push(`${where}: hold=${args.hold} shortened to ${MAX_HOLD.toFixed(0)} s`);
        args = { ...args, hold: MAX_HOLD };
      }
      const tr = new Track(name, args);
      const target = sublines[sublines.length - 1];
      const newHard = tr.hardSet();
      const clash = target.filter((o) => intersect(o.hardSet(), newHard).size > 0);
      const overlay = (o) => {
        const oldHard = o.hardSet();
        if (GENERIC_POSES.has(tr.name) || GENERIC_POSES.has(o.name)) return false;
        return (isProperSubset(newHard, oldHard) && (o.kind === "pose" || o.kind === "cycle")) ||
          (isProperSubset(oldHard, newHard) && (tr.kind === "pose" || tr.kind === "cycle"));
      };
      const trunkShare = (o) => isSubset(intersect(o.hardSet(), newHard), new Set(["spine", "neck"])) &&
        intersect(union(o.hardSet(), newHard), ARMS).size > 0;
      if (clash.length) {
        if (strict && !clash.every((o) => overlay(o) || trunkShare(o))) {
          for (const o of clash) {
            const parts = [...intersect(o.hardSet(), newHard)].sort();
            errors.push(`line ${line.no}: '${tr.name}' and '${o.name}' both drive ${parts.join(", ")}; ` +
              "put them on different lines or pick motions that use different body parts");
          }
          continue;
        }
        if (GENERIC_POSES.has(tr.name)) {
          warnings.push(`line ${line.no}: '${tr.name}' dropped - '${clash[0].name}' already drives those parts`);
          continue;
        }
        const poses = clash.filter((o) => GENERIC_POSES.has(o.name));
        if (poses.length === clash.length) {
          for (const o of poses) target.splice(target.indexOf(o), 1);
          warnings.push(`line ${line.no}: '${poses.map((o) => o.name).join(", ")}' dropped - '${tr.name}' drives those parts`);
          target.push(tr);
          continue;
        }
        if (clash.every(trunkShare)) {
          target.push(tr);
          continue;
        }
        if (clash.every(overlay)) {
          const lower = new Set(["body", "right_leg", "left_leg"]);
          if (tr.kind === "pose" && intersect(newHard, lower).size &&
            clash.every((o) => o.kind !== "pose" && isProperSubset(newHard, o.hardSet()))) {
            warnings.push(`line ${line.no}: '${tr.name}' dropped - '${clash[0].name}' already has its posture`);
            continue;
          }
          const posture = clash.filter((o) => o.kind === "pose" && intersect(o.hardSet(), lower).size &&
            tr.kind !== "pose" && isProperSubset(o.hardSet(), newHard));
          for (const o of posture) {
            target.splice(target.indexOf(o), 1);
            warnings.push(`line ${line.no}: '${o.name}' dropped - '${tr.name}' already has its posture`);
          }
          target.push(tr);
          continue;
        }
        warnings.push(`line ${line.no}: '${tr.name}' and '${clash[0].name}' drive the same body parts - ` +
          `'${tr.name}' plays right after it`);
        sublines.push([tr]);
      } else {
        target.push(tr);
      }
    }
    for (const tracks of sublines) {
      if (!tracks.length) continue;
      const owners = new Map();
      for (const tr of tracks) {
        for (const [part, hard] of tr.owned()) {
          if (!owners.has(part)) { owners.set(part, [tr, hard]); continue; }
          const [cur, curHard] = owners.get(part);
          if ((part === "spine" || part === "neck") && hard && curHard) {
            const trArm = tr.owned().some(([p, h]) => ARMS.has(p) && h);
            const curArm = cur.owned().some(([p, h]) => ARMS.has(p) && h);
            if (trArm !== curArm) {
              if (trArm) owners.set(part, [tr, hard]);
              continue;
            }
          }
          if (hard && !curHard) {
            owners.set(part, [tr, hard]);
          } else if (hard === curHard) {
            const th = tr.hardSet(), ch = cur.hardSet();
            const a = [KIND_RANK[tr.kind], -tr.owned().length], b = [KIND_RANK[cur.kind], -cur.owned().length];
            const rankBetter = a[0] > b[0] || (a[0] === b[0] && a[1] > b[1]);
            if (isProperSubset(th, ch) || (!isProperSubset(ch, th) && rankBetter)) owners.set(part, [tr, hard]);
          }
        }
      }
      built.push({ tracks, repeat: line.repeat, no: line.no, owners });
    }
  }
  if (errors.length) throw new ScriptError(errors.join("\n"));
  if (!built.length) throw new ScriptError("the script has no usable motions");
  if (validateOnly) return { warnings };

  // Keep the clip short: trim repetitions (largest first) until it fits.
  const total = () => built.reduce((s, b) => s + lineLength(b.tracks) * b.repeat, 0);
  let trimmed = false;
  while (total() > MAX_SECONDS) {
    const cands = [];
    for (const b of built) for (const tr of b.tracks) if (tr.times > 1) cands.push(tr);
    const reps = [];
    built.forEach((b, i) => { if (b.repeat > 1) reps.push([b.repeat, i]); });
    let maxRep = null;
    for (const r of reps) if (!maxRep || r[0] > maxRep[0] || (r[0] === maxRep[0] && r[1] > maxRep[1])) maxRep = r;
    const maxTimes = cands.length ? Math.max(...cands.map((c) => c.times)) : -Infinity;
    if (reps.length && (!cands.length || maxRep[0] >= maxTimes)) {
      built[maxRep[1]].repeat -= 1;
    } else if (cands.length) {
      cands.find((c) => c.times === maxTimes).times -= 1;
    } else {
      break;
    }
    trimmed = true;
  }
  if (total() > MAX_SECONDS) {
    const holds = [];
    for (const b of built) for (const tr of b.tracks) if (tr.hold > 0) holds.push(tr);
    if (holds.length) {
      const excess = total() - MAX_SECONDS;
      const sumH = holds.reduce((s, tr) => s + tr.hold, 0);
      for (const tr of holds) tr.hold = Math.max(0.2, tr.hold - (excess * tr.hold) / sumH);
      trimmed = true;
    }
  }
  if (trimmed) warnings.push(`repetitions / holds trimmed so the clip stays under ${MAX_SECONDS.toFixed(0)} s`);

  // timeline
  let pose = copyPose(NEUTRAL);
  const samples = [];
  const lineInfo = [];
  let first = true;
  for (const { tracks, repeat, no, owners } of built) {
    const L = lineLength(tracks);
    for (let r = 0; r < repeat; r++) {
      const startPose = copyPose(pose);
      const n = Math.max(1, me.pyRound(L * fps));
      for (let i = 0; i < n; i++) {
        const t = i / fps;
        const cur = copyPose(startPose);
        const sampled = new Map(tracks.map((tr) => [tr, tr.sample(t)]));
        for (const [part, [tr]] of owners) cur[part] = sampled.get(tr)[part];
        const w = first ? 1 : smooth(Math.min(1, t / BLEND_SECONDS));
        samples.push([cur, { w, start: startPose }]);
      }
      const last = copyPose(startPose);
      const endSamples = new Map();
      for (const [part, [tr]] of owners) {
        if (!endSamples.has(tr)) endSamples.set(tr, tr.sample(L - 1e-6));
        last[part] = endSamples.get(tr)[part];
      }
      pose = last;
      first = false;
    }
    const parts = {};
    for (const [p, [tr]] of owners) parts[p] = tr.name;
    lineInfo.push({ line: no, seconds: me.pyRound(L * repeat, 2), parts });
  }
  if (!loop) {
    for (let i = 0; i < Math.trunc(END_HOLD_SECONDS * fps); i++) samples.push([copyPose(pose), { w: 1, start: pose }]);
  }

  let frames = buildFrames(samples, loop, fps);
  if (dominantSide === "left") frames = frames.map(mirrorFrame);
  const report = check(frames);
  const ground = !samples.some(([s]) => Math.abs(s.body.pitch) > 45 || Math.abs(s.body.roll) > 45 ||
    (s.body.air > 0.9 && Math.abs(s.body.pitch) > 30));
  report.warnings = warnings;
  return { frames, fps, loop, lines: lineInfo, report, ground, duration_seconds: me.pyRound(frames.length / fps, 2) };
}

// ---------------------------------------------------------------------------
// Frames
// ---------------------------------------------------------------------------
const ARM_WAYPOINTS = [
  { raise: 60, dir: 95, twist: 0, elbow: 30 },
  { raise: 110, dir: 60, twist: 0, elbow: 30 },
  { raise: 45, dir: 30, twist: 0, elbow: 60 },
];

const slerpM = (a, b, u) => me.quatToMatrix(me.slerp(me.matrixToQuat(a), me.matrixToQuat(b), u));

function slerpDir(qa, qb, u) {
  const d = Math.max(-1, Math.min(1, me.qdot(qa, qb)));
  if (Math.abs(d) > 0.9995) {
    return me.qnormalize([qa[0] + (qb[0] - qa[0]) * u, qa[1] + (qb[1] - qa[1]) * u,
      qa[2] + (qb[2] - qa[2]) * u, qa[3] + (qb[3] - qa[3]) * u]);
  }
  const th = Math.acos(d);
  const a = Math.sin((1 - u) * th) / Math.sin(th), b = Math.sin(u * th) / Math.sin(th);
  return [a * qa[0] + b * qb[0], a * qa[1] + b * qb[1], a * qa[2] + b * qb[2], a * qa[3] + b * qb[3]];
}

function slerpSteady(a, b, u, prev) {
  const qa = me.matrixToQuat(a);
  let qb = me.matrixToQuat(b);
  if (me.qdot(qa, qb) < 0) qb = qb.map((v) => -v);
  let q = slerpDir(qa, qb, u);
  if (prev) {
    const q2 = slerpDir(qa, qb.map((v) => -v), u);
    if (Math.abs(me.qdot(q2, prev)) > Math.abs(me.qdot(q, prev)) + 1e-6) q = q2;
  }
  return q;
}

function armRoutePenetration(r0, r1, side, wp) {
  let worst = 0;
  const sh = side + "shoulder", el = side + "elbow";
  for (const u of [0.2, 0.35, 0.5, 0.65, 0.8]) {
    const rot = {};
    for (const j in r1) rot[j] = slerpM(r0[j], r1[j], u);
    if (wp) {
      for (const j of [sh, el]) rot[j] = u < 0.5 ? slerpM(r0[j], wp[j], u / 0.5) : slerpM(wp[j], r1[j], (u - 0.5) / 0.5);
    }
    const world = me.worldRotations(rot);
    worst = Math.max(worst, bodyPenetration(world, me.forwardKinematics(world), side));
  }
  return worst;
}

function buildFrames(samples, loop, fps) {
  const frames = [];
  const prevE = {};
  const routes = new Map();
  let prevBlend = new Map();
  let prevBlendKey = null;
  for (const [pose, blend] of samples) {
    let rot = partRotations(pose);
    const w = blend.w;
    let scal = pose.body;
    if (w < 1) {
      const r0 = partRotations(blend.start);
      const key = blend.start;
      if (!routes.has(key)) {
        const r = {};
        for (const [side, sign] of [["right", 1], ["left", -1]]) {
          if (armRoutePenetration(r0, rot, side) <= 0.03) continue;
          let best = null;
          for (const wpa of ARM_WAYPOINTS) {
            const wp = { ...rot };
            wp[side + "shoulder"] = me.limbLocalRotation(wpa.raise, wpa.dir, wpa.twist, sign);
            wp[side + "elbow"] = me.rx(-wpa.elbow);
            const d = armRoutePenetration(r0, rot, side, wp);
            if (!best || d < best[0]) best = [d, wp];
          }
          if (best && best[0] <= 0.03) r[side] = best[1];
        }
        routes.set(key, r);
      }
      if (prevBlendKey !== key) {
        prevBlend = new Map();
        prevBlendKey = key;
      }
      const blended = {};
      for (const j in rot) {
        let src = r0[j], dst = rot[j], u = w;
        const side = j === "rightshoulder" || j === "rightelbow" ? "right" : j === "leftshoulder" || j === "leftelbow" ? "left" : null;
        const wp = side ? routes.get(key)[side] : undefined;
        if (wp) {
          if (w < 0.5) { src = r0[j]; dst = wp[j]; u = w / 0.5; } else { src = wp[j]; dst = rot[j]; u = (w - 0.5) / 0.5; }
        }
        const q = slerpSteady(src, dst, u, prevBlend.get(j));
        prevBlend.set(j, q);
        blended[j] = me.quatToMatrix(q);
      }
      rot = blended;
      const s0 = blend.start.body;
      scal = {};
      for (const k in pose.body) scal[k] = s0[k] + (pose.body[k] - s0[k]) * w;
    }
    const world = me.worldRotations(rot);
    const pos = me.forwardKinematics(world);
    const f = {};
    for (const j of me.JOINT_NAMES) {
      const e = me.closestEuler(rot[j], prevE[j]);
      prevE[j] = e;
      f[j + "x"] = me.pyRound(e[0], 2);
      f[j + "y"] = me.pyRound(e[1], 2);
      f[j + "z"] = me.pyRound(e[2], 2);
    }
    f.positionx = me.pyRound(scal.pitch, 2);
    f.positiony = me.pyRound(scal.turn, 2);
    f.positionz = me.pyRound(-scal.roll, 2);
    const air = Math.max(0, Math.min(1, scal.air));
    f.rooty = me.pyRound((1 - air) * groundOffset(pos, world) + scal.root, 3);
    frames.push(f);
  }
  return frames;
}

function mirrorFrame(f) {
  const out = {};
  for (const k in f) {
    const k2 = mirrorPart(k);
    let v = f[k];
    if ("yz".includes(k2[k2.length - 1]) && k2 !== "rooty") v = -v;
    out[k2] = v + 0;
  }
  out.positiony = -(f.positiony || 0) + 0;
  out.positionz = -(f.positionz || 0) + 0;
  return out;
}

// Rounded body volumes matching the rendered rig (rig units): elliptic chest and hips, ellipsoid head.
export function bodyPenetration(world, pos, side) {
  // Scalar math, no allocations: this runs for every frame (check) and every blend candidate.
  const r = me.LIMB_RADIUS * 0.8;
  const sh = pos[side + "_shoulder"], el = pos[side + "_elbow"], ha = pos[side + "_hand"];
  const S = world.spine, H = world.hip, N = world.neck;
  const thx = me.TORSO_HALF[0] + r, thz = me.TORSO_HALF[2] + r, tlo = -r, thi = 2 * me.TORSO_HALF[1] + r, tmin = Math.min(thx, thz);
  const phx = me.PELVIS_HALF[0] + r, phz = me.PELVIS_HALF[2] + r, plo = -me.PELVIS_HALF[1] - r, phi = me.PELVIS_HALF[1] + r, pmin = Math.min(phx, phz);
  const hx0 = me.HEAD_HALF[0] + r, hy0 = me.HEAD_HALF[1] + r, hz0 = me.HEAD_HALF[2] + r;
  const hy = me.HEAD_HALF[1];
  const cx = pos.neck[0] + N[1] * hy, cy = pos.neck[1] + N[4] * hy, cz = pos.neck[2] + N[7] * hy;
  let best = 0;
  for (let s = 0; s < 2; s++) {
    let ax, ay, az, bx, by, bz;
    if (s === 0) {
      ax = sh[0] + (el[0] - sh[0]) * 0.35; ay = sh[1] + (el[1] - sh[1]) * 0.35; az = sh[2] + (el[2] - sh[2]) * 0.35;
      bx = el[0]; by = el[1]; bz = el[2];
    } else {
      ax = el[0]; ay = el[1]; az = el[2]; bx = ha[0]; by = ha[1]; bz = ha[2];
    }
    const dx = bx - ax, dy = by - ay, dz = bz - az;
    for (let i = 0; i < 9; i++) {
      const u = i / 8;
      const px = ax + dx * u, py = ay + dy * u, pz = az + dz * u;
      // chest (spine frame), q = S^T p
      let qy = S[1] * px + S[4] * py + S[7] * pz;
      if (tlo < qy && qy < thi) {
        const qx = S[0] * px + S[3] * py + S[6] * pz, qz = S[2] * px + S[5] * py + S[8] * pz;
        const e = Math.hypot(qx / thx, qz / thz);
        if (e < 1 && (1 - e) * tmin > best) best = (1 - e) * tmin;
      }
      // hips (hip frame)
      qy = H[1] * px + H[4] * py + H[7] * pz;
      if (plo < qy && qy < phi) {
        const qx = H[0] * px + H[3] * py + H[6] * pz, qz = H[2] * px + H[5] * py + H[8] * pz;
        const e = Math.hypot(qx / phx, qz / phz);
        if (e < 1 && (1 - e) * pmin > best) best = (1 - e) * pmin;
      }
      // head (neck frame)
      const rx = px - cx, ry = py - cy, rz = pz - cz;
      const hqx = N[0] * rx + N[3] * ry + N[6] * rz, hqy = N[1] * rx + N[4] * ry + N[7] * rz, hqz = N[2] * rx + N[5] * ry + N[8] * rz;
      const e = Math.sqrt((hqx / hx0) ** 2 + (hqy / hy0) ** 2 + (hqz / hz0) ** 2);
      if (e < 1 && (1 - e) * hx0 > best) best = (1 - e) * hx0;
    }
  }
  return best * me.UNIT_TO_M;
}

function check(frames) {
  let worstPen = 0, pops = 0, prev = null, prev2 = null;
  const bad = frames.filter((f) => !Object.values(f).every(Number.isFinite)).length;
  if (bad) return { max_arm_penetration_m: 0, max_joint_step_m: 0, issues: [`${bad} frames are not finite (NaN)`] };
  for (const f of frames) {
    const local = {};
    for (const j of me.JOINT_NAMES) local[j] = me.frameRotation(f, j);
    local.body = me.I3();
    const world = me.worldRotations(local);
    const pos = me.forwardKinematics(world);
    for (const side of ["right", "left"]) worstPen = Math.max(worstPen, bodyPenetration(world, pos, side));
    if (prev && prev2) {
      for (const k in pos) {
        const a = pos[k], b = prev[k], c = prev2[k];
        pops = Math.max(pops, Math.hypot(a[0] - 2 * b[0] + c[0], a[1] - 2 * b[1] + c[1], a[2] - 2 * b[2] + c[2]) * me.UNIT_TO_M);
      }
    }
    prev2 = prev;
    prev = pos;
  }
  const issues = [];
  if (worstPen > 0.03) issues.push(`an arm passes ${(worstPen * 100).toFixed(0)} cm into the body`);
  if (pops > 1.5) issues.push(`a joint changes speed abruptly (${pops.toFixed(2)} m/frame^2)`);
  return { max_arm_penetration_m: me.pyRound(worstPen, 3), max_joint_step_m: me.pyRound(pops, 3), issues };
}
