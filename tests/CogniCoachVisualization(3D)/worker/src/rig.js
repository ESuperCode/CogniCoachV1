// Rig geometry and rotation math - a port of the shared math in motion_engine.py.
// Unity conventions: Quaternion.Euler applies Z, then X, then Y. +X avatar right, +Y up, +Z forward.
// Matrices are plain 9-element arrays, row-major: [m00, m01, m02, m10, ...].

export const UNIT_TO_M = 1.75 / 82.0;
export const SHOULDER_OFFSET = [14.0, 22.5, 0.0];
export const HIP_OFFSET = [6.0, -1.0, 0.0];
export const NECK_OFFSET = [0.0, 30.0, 0.0];
export const UPPER_ARM = 15.0;
export const FOREARM = 16.0;
export const THIGH = 16.5;
export const SHIN = 17.0;
export const LIMB_RADIUS = 3.75;
export const TORSO_HALF = [10.0, 15.0, 5.0];
export const PELVIS_HALF = [10.0, 5.0, 5.0];
export const HEAD_HALF = [6.0, 8.0, 7.5];
export const SOLE_DROP = 3.0;

export const JOINT_NAMES = ["hip", "spine", "neck", "lefthip", "righthip", "leftknee", "rightknee",
  "leftshoulder", "rightshoulder", "leftelbow", "rightelbow"];

const D2R = Math.PI / 180;
const R2D = 180 / Math.PI;

export const I3 = () => [1, 0, 0, 0, 1, 0, 0, 0, 1];

export function mul(a, b) {
  return [
    a[0] * b[0] + a[1] * b[3] + a[2] * b[6], a[0] * b[1] + a[1] * b[4] + a[2] * b[7], a[0] * b[2] + a[1] * b[5] + a[2] * b[8],
    a[3] * b[0] + a[4] * b[3] + a[5] * b[6], a[3] * b[1] + a[4] * b[4] + a[5] * b[7], a[3] * b[2] + a[4] * b[5] + a[5] * b[8],
    a[6] * b[0] + a[7] * b[3] + a[8] * b[6], a[6] * b[1] + a[7] * b[4] + a[8] * b[7], a[6] * b[2] + a[7] * b[5] + a[8] * b[8],
  ];
}

export function mulv(m, v) {
  return [m[0] * v[0] + m[1] * v[1] + m[2] * v[2], m[3] * v[0] + m[4] * v[1] + m[5] * v[2], m[6] * v[0] + m[7] * v[1] + m[8] * v[2]];
}

// transpose(m) @ v
export function tmulv(m, v) {
  return [m[0] * v[0] + m[3] * v[1] + m[6] * v[2], m[1] * v[0] + m[4] * v[1] + m[7] * v[2], m[2] * v[0] + m[5] * v[1] + m[8] * v[2]];
}

export function transpose(m) {
  return [m[0], m[3], m[6], m[1], m[4], m[7], m[2], m[5], m[8]];
}

export const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const scale = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
export const norm3 = (a) => Math.hypot(a[0], a[1], a[2]);

export function rx(deg) {
  const c = Math.cos(deg * D2R), s = Math.sin(deg * D2R);
  return [1, 0, 0, 0, c, -s, 0, s, c];
}

export function ry(deg) {
  const c = Math.cos(deg * D2R), s = Math.sin(deg * D2R);
  return [c, 0, s, 0, 1, 0, -s, 0, c];
}

export function rz(deg) {
  const c = Math.cos(deg * D2R), s = Math.sin(deg * D2R);
  return [c, -s, 0, s, c, 0, 0, 0, 1];
}

export function eulerToMatrix(x, y, z) {
  return mul(mul(ry(y), rx(x)), rz(z));
}

export function matrixToEuler(m) {
  const x = Math.asin(Math.max(-1, Math.min(1, -m[5])));
  let y, z;
  if (Math.abs(Math.cos(x)) > 1e-6) {
    y = Math.atan2(m[2], m[8]);
    z = Math.atan2(m[3], m[4]);
  } else {
    y = Math.atan2(-m[6], m[0]);
    z = 0;
  }
  return [x * R2D, y * R2D, z * R2D];
}

export function axisAngle(axis, deg) {
  const n = norm3(axis);
  if (n < 1e-9 || Math.abs(deg) < 1e-9) return I3();
  const a = [axis[0] / n, axis[1] / n, axis[2] / n];
  const th = deg * D2R, s = Math.sin(th), c1 = 1 - Math.cos(th);
  const k = [0, -a[2], a[1], a[2], 0, -a[0], -a[1], a[0], 0];
  const kk = mul(k, k);
  const out = I3();
  for (let i = 0; i < 9; i++) out[i] += s * k[i] + c1 * kk[i];
  return out;
}

// Swing a limb hanging straight down by `raise` within the vertical plane `direction`.
export function limbLocalRotation(raiseDeg, directionDeg, twistDeg, sideSign) {
  const d = directionDeg * D2R;
  const horizontal = [sideSign * Math.sin(d), 0, Math.cos(d)];
  // cross(DOWN, horizontal) with DOWN = (0, -1, 0)
  const axis = [-horizontal[2], 0, horizontal[0]];
  return mul(axisAngle(axis, raiseDeg), ry(sideSign * twistDeg));
}

export function worldRotations(local) {
  const w = { body: local.body };
  w.hip = mul(w.body, local.hip);
  w.spine = mul(w.body, local.spine);
  w.neck = mul(w.spine, local.neck);
  for (const s of ["left", "right"]) {
    w[s + "hip"] = mul(w.hip, local[s + "hip"]);
    w[s + "knee"] = mul(w[s + "hip"], local[s + "knee"]);
    w[s + "shoulder"] = mul(w.spine, local[s + "shoulder"]);
    w[s + "elbow"] = mul(w[s + "shoulder"], local[s + "elbow"]);
  }
  return w;
}

export function forwardKinematics(world) {
  const p = { pelvis: [0, 0, 0] };
  p.neck = mulv(world.spine, NECK_OFFSET);
  p.head = add(p.neck, mulv(world.neck, [0, 8, 0]));
  p.chest = mulv(world.spine, [0, 15, 0]);
  for (const [s, sign] of [["right", 1], ["left", -1]]) {
    const sh = mulv(world.spine, [sign * SHOULDER_OFFSET[0], SHOULDER_OFFSET[1], 0]);
    const el = add(sh, mulv(world[s + "shoulder"], [0, -UPPER_ARM, 0]));
    const ha = add(el, mulv(world[s + "elbow"], [0, -FOREARM, 0]));
    const hp = mulv(world.hip, [sign * HIP_OFFSET[0], HIP_OFFSET[1], 0]);
    const kn = add(hp, mulv(world[s + "hip"], [0, -THIGH, 0]));
    const an = add(kn, mulv(world[s + "knee"], [0, -SHIN, 0]));
    p[s + "_shoulder"] = sh; p[s + "_elbow"] = el; p[s + "_hand"] = ha;
    p[s + "_hip"] = hp; p[s + "_knee"] = kn; p[s + "_foot"] = an;
  }
  return p;
}

// ---------------------------------------------------------------------------
// Monotone cubic (PCHIP) splines
// ---------------------------------------------------------------------------
const sign = (v) => (v > 0 ? 1 : v < 0 ? -1 : 0);

export function pchipSlopes(x, y) {
  const n = x.length;
  const h = [], delta = [];
  for (let i = 0; i < n - 1; i++) {
    h.push(x[i + 1] - x[i]);
    delta.push((y[i + 1] - y[i]) / h[i]);
  }
  const m = new Array(n).fill(0);
  if (n === 2) {
    m[0] = m[1] = delta[0];
    return m;
  }
  for (let i = 1; i < n - 1; i++) {
    if (delta[i - 1] * delta[i] <= 0) {
      m[i] = 0;
    } else {
      const w1 = 2 * h[i] + h[i - 1];
      const w2 = h[i] + 2 * h[i - 1];
      m[i] = (w1 + w2) / (w1 / delta[i - 1] + w2 / delta[i]);
    }
  }
  const end = (h0, h1, d0, d1) => {
    const s = ((2 * h0 + h1) * d0 - h0 * d1) / (h0 + h1);
    if (sign(s) !== sign(d0)) return 0;
    if (sign(d0) !== sign(d1) && Math.abs(s) > Math.abs(3 * d0)) return 3 * d0;
    return s;
  };
  m[0] = end(h[0], h[1], delta[0], delta[1]);
  m[n - 1] = end(h[n - 2], h[n - 3], delta[n - 2], delta[n - 3]);
  return m;
}

// Hermite evaluation at a single t (x sorted ascending).
export function hermite(x, y, m, t) {
  // searchsorted(x, t, side="right") - 1, clipped to [0, n-2]
  let lo = 0, hi = x.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (x[mid] <= t) lo = mid + 1; else hi = mid;
  }
  let idx = lo - 1;
  if (idx < 0) idx = 0;
  if (idx > x.length - 2) idx = x.length - 2;
  const x0 = x[idx], x1 = x[idx + 1];
  const h = x1 - x0;
  let u = (t - x0) / h;
  u = Math.min(1, Math.max(0, u));
  const u2 = u * u, u3 = u2 * u;
  const h00 = 2 * u3 - 3 * u2 + 1;
  const h10 = u3 - 2 * u2 + u;
  const h01 = -2 * u3 + 3 * u2;
  const h11 = u3 - u2;
  return h00 * y[idx] + h10 * h * m[idx] + h01 * y[idx + 1] + h11 * h * m[idx + 1];
}

// ---------------------------------------------------------------------------
// Quaternions [w, x, y, z]
// ---------------------------------------------------------------------------
const copysign = (mag, s) => (s < 0 || Object.is(s, -0) ? -Math.abs(mag) : Math.abs(mag));

export function matrixToQuat(m) {
  const w = Math.sqrt(Math.max(0, 1 + m[0] + m[4] + m[8])) / 2;
  const x = copysign(Math.sqrt(Math.max(0, 1 + m[0] - m[4] - m[8])) / 2, m[7] - m[5]);
  const y = copysign(Math.sqrt(Math.max(0, 1 - m[0] + m[4] - m[8])) / 2, m[2] - m[6]);
  const z = copysign(Math.sqrt(Math.max(0, 1 - m[0] - m[4] + m[8])) / 2, m[3] - m[1]);
  const n = Math.hypot(w, x, y, z);
  return [w / n, x / n, y / n, z / n];
}

export function quatToMatrix(q) {
  const [w, x, y, z] = q;
  return [
    1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
    2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
    2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y),
  ];
}

export const qdot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2] + a[3] * b[3];

export function qnormalize(q) {
  const n = Math.hypot(q[0], q[1], q[2], q[3]);
  return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
}

export function slerp(qa, qb, u) {
  let d = qdot(qa, qb);
  if (d < 0) {
    qb = [-qb[0], -qb[1], -qb[2], -qb[3]];
    d = -d;
  }
  if (d > 0.9995) {
    return qnormalize([qa[0] + (qb[0] - qa[0]) * u, qa[1] + (qb[1] - qa[1]) * u,
      qa[2] + (qb[2] - qa[2]) * u, qa[3] + (qb[3] - qa[3]) * u]);
  }
  const th = Math.acos(d);
  const a = Math.sin((1 - u) * th) / Math.sin(th), b = Math.sin(u * th) / Math.sin(th);
  return [a * qa[0] + b * qb[0], a * qa[1] + b * qb[1], a * qa[2] + b * qb[2], a * qa[3] + b * qb[3]];
}

// Python-style modulo (result has the sign of the divisor).
export const pmod = (a, b) => ((a % b) + b) % b;

// Python round(): half to even, n decimals.
// Python round(): half to even on the exact binary value. Fast path away from ties; near a tie,
// toFixed (exact decimal) decides, and only true binary ties (dyadic values) use half-to-even.
export function pyRound(v, n = 0) {
  if (!Number.isFinite(v)) return v;
  const f = POW10[n];
  const x = v * f;
  const fl = Math.floor(x);
  const frac = x - fl;
  if (Math.abs(frac - 0.5) > 1e-6) return (frac < 0.5 ? fl : fl + 1) / f + 0;
  if (Number.isInteger(v * 1048576) && (fl + 0.5) / f === v) return (fl % 2 === 0 ? fl : fl + 1) / f + 0;
  return Number(v.toFixed(n)) + 0; // + 0 turns -0 into 0
}
const POW10 = [1, 10, 100, 1000, 10000, 100000, 1000000];

// Pick the Euler triple (of the two equivalent ZXY solutions) closest to the previous frame.
export function closestEuler(m, prev) {
  const [x, y, z] = matrixToEuler(m);
  if (!prev) return [x, y, z];
  const alt = [180 - x, y + 180, z + 180];
  const wrap = (v, ref) => ref + (pmod(v - ref + 180, 360) - 180);
  const c1 = [wrap(x, prev[0]), wrap(y, prev[1]), wrap(z, prev[2])];
  const c2 = [wrap(alt[0], prev[0]), wrap(alt[1], prev[1]), wrap(alt[2], prev[2])];
  const d1 = Math.abs(c1[0] - prev[0]) + Math.abs(c1[1] - prev[1]) + Math.abs(c1[2] - prev[2]);
  const d2 = Math.abs(c2[0] - prev[0]) + Math.abs(c2[1] - prev[1]) + Math.abs(c2[2] - prev[2]);
  return d1 <= d2 ? c1 : c2;
}

export function frameRotation(frame, joint) {
  return eulerToMatrix(frame[joint + "x"] || 0, frame[joint + "y"] || 0, frame[joint + "z"] || 0);
}
