// Tests for scripts/form-engine.js with synthetic skeletons (no camera needed).
//   node CogniCoachV1/test/form_engine_test.mjs
// A tiny body model builds 3D joints for a given knee angle / trunk lean / elbow angle / knee cave,
// projects them to a front or side camera, adds noise, and feeds the frames at 30 fps.
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const E = require('../scripts/form-engine.js');

let failed = 0, passed = 0;
function check(name, cond, info) { if (cond) { passed++; } else { failed++; console.log('FAIL', name, info === undefined ? '' : JSON.stringify(info)); } }

const rad = (d) => d * Math.PI / 180;
let seed = 7;
function rand() { seed = (seed * 16807) % 2147483647; return seed / 2147483647; }
function gauss() { return Math.sqrt(-2 * Math.log(rand() + 1e-9)) * Math.cos(2 * Math.PI * rand()); }

// Upright body, sagittal plane: x forward, y down (metres), z to the athlete's left.
function standingPose({ knee = 175, trunk = 5, cave = 0, armsUp = 0, elbow = 170, kneeL, kneeR }) {
    const P = new Array(33).fill(null).map(() => ({ x: 0, y: 0, z: 0 }));
    function leg(side, K) {
        const z = side === 'L' ? 0.12 : -0.12;
        const s = rad((180 - K) * 0.38);                  // shin leans forward as the knee bends
        const ank = { x: 0, y: 0, z: z * 1.15 };
        const kn = { x: ank.x + 0.45 * Math.sin(s), y: ank.y - 0.45 * Math.cos(s), z: z * 1.15 - (side === 'L' ? 1 : -1) * cave };
        // direction knee->ankle, rotated by K so the hip sits behind
        const a = Math.atan2(ank.y - kn.y, ank.x - kn.x), b = a + rad(K);   // rotate counter-clockwise (y down)
        const hp = { x: kn.x + 0.45 * Math.cos(b), y: kn.y + 0.45 * Math.sin(b), z };
        return { ank, kn, hp };
    }
    const L = leg('L', kneeL ?? knee), R = leg('R', kneeR ?? knee);
    P[27] = L.ank; P[25] = L.kn; P[23] = L.hp; P[28] = R.ank; P[26] = R.kn; P[24] = R.hp;
    P[29] = { ...L.ank, x: -0.05 }; P[30] = { ...R.ank, x: -0.05 }; P[31] = { ...L.ank, x: 0.15 }; P[32] = { ...R.ank, x: 0.15 };
    const hip = { x: (L.hp.x + R.hp.x) / 2, y: (L.hp.y + R.hp.y) / 2 };
    const T = rad(trunk);
    for (const [i, z] of [[11, 0.19], [12, -0.19]]) P[i] = { x: hip.x + 0.5 * Math.sin(T), y: hip.y - 0.5 * Math.cos(T), z };
    const sh = P[11];
    P[0] = { x: sh.x + 0.28 * Math.sin(T) + 0.05, y: sh.y - 0.28 * Math.cos(T), z: 0 };
    for (let i = 1; i <= 10; i++) P[i] = { ...P[0], z: (i % 2 ? 0.03 : -0.03) };
    // arms: upper arm raised by armsUp degrees forward/up from hanging, forearm by the elbow angle
    for (const [s, e, w, z] of [[11, 13, 15, 0.21], [12, 14, 16, -0.21]]) {
        const u = rad(armsUp);
        const el = { x: P[s].x + 0.3 * Math.sin(u), y: P[s].y + 0.3 * Math.cos(u), z };
        const f = u + rad(180 - elbow);
        P[e] = el;
        P[w] = { x: el.x + 0.27 * Math.sin(f), y: el.y + 0.27 * Math.cos(f), z };
    }
    for (let i = 17; i <= 22; i++) P[i] = { ...P[i % 2 ? 15 : 16] };
    return P;
}

// Push-up / plank: body horizontal, feet at x=0, hands under the shoulders.
function pushupPose({ elbow = 170, sag = 0 }) {
    const P = new Array(33).fill(null).map(() => ({ x: 0, y: 0, z: 0 }));
    const wr = { x: 1.45, y: 0 };
    const el = { x: wr.x, y: -0.28 };
    const a = rad(180 - elbow);
    const sh = { x: el.x - 0.3 * Math.sin(a), y: el.y - 0.3 * Math.cos(a) };
    const an = { x: 0, y: -0.06 };
    const hp = { x: an.x + (sh.x - an.x) * 0.55, y: an.y + (sh.y - an.y) * 0.55 + sag };
    const kn = { x: (hp.x + an.x) / 2, y: (hp.y + an.y) / 2 + sag * 0.3 };
    for (const [ids, p] of [[[15, 16], wr], [[13, 14], el], [[11, 12], sh], [[23, 24], hp], [[25, 26], kn], [[27, 28], an]]) {
        P[ids[0]] = { ...p, z: 0.18 }; P[ids[1]] = { ...p, z: -0.18 };
    }
    P[0] = { x: sh.x + 0.25, y: sh.y - 0.02, z: 0 };
    for (let i = 1; i <= 10; i++) P[i] = { ...P[0] };
    for (let i = 17; i <= 22; i++) P[i] = { ...P[i % 2 ? 15 : 16] };
    for (let i = 29; i <= 32; i++) P[i] = { ...P[i % 2 ? 27 : 28] };
    return P;
}

// camera: 'front' sees z (left-right) and y; 'side' sees x and y. Image coords 0..1, aspect 1.
function project(P, view, noise, lift = 0) {
    const lm = P.map((p, i) => {
        const X = view === 'front' ? -p.z : p.x;
        const far = view === 'side' && p.z < 0 && i >= 11;   // the far side is less visible side-on
        return { x: 0.5 + (X - 0.4 * (view === 'side')) / 2.4 + gauss() * noise, y: 0.75 + (p.y - lift) / 2.4 + gauss() * noise,
            z: 0, visibility: far ? 0.55 : 0.95 };
    });
    const hip = { x: (P[23].x + P[24].x) / 2, y: (P[23].y + P[24].y) / 2, z: 0 };
    const wl = P.map((p) => ({ x: p.x - hip.x + gauss() * noise * 2, y: p.y - hip.y + gauss() * noise * 2, z: p.z + gauss() * noise * 2 }));
    return { lm, wl };
}

// Run a clip: shape(t) -> pose params; returns {eng, cues, statuses}
function run({ drill = '', text = '', seconds, view = 'front', noise = 0.003, pose, fps = 30, kind = 'stand', world = true }) {
    const eng = E.create({ drill, text });
    const cues = [], statuses = {};
    for (let i = 0; i < seconds * fps; i++) {
        const t = i * 1000 / fps;
        const prm = pose(t / 1000);
        const P = kind === 'pushup' ? pushupPose(prm) : standingPose(prm);
        const { lm, wl } = project(P, view, noise, prm.lift || 0);
        const out = eng.push({ t, lm, wl: world ? wl : null, aspect: 1 });
        statuses[out.status] = (statuses[out.status] || 0) + 1;
        if (out.cue) cues.push(out.cue.id);
    }
    return { eng, cues, statuses, report: eng.report() };
}

// a rep every `period` s after `rest` s standing: 0 -> 1 -> 0
function cycle(t, rest = 1.5, period = 2.4) {
    if (t < rest) return 0;
    const ph = ((t - rest) % period) / period;
    return ph < 0.8 ? Math.sin(Math.PI * ph / 0.8) : 0;
}
const has = (r, id) => r.faults.find((f) => f.id === id);

// 1. good squats, front view: 8 reps, no faults
{
    const { report: r, cues } = run({ drill: 'Goblet squat', seconds: 1.5 + 8 * 2.4 + 0.5, view: 'front',
        pose: (t) => ({ knee: 175 - 92 * cycle(t), trunk: 5 + 25 * cycle(t), armsUp: 80, elbow: 60 }) });
    check('squat front: pattern', r.pattern === 'squat', r.pattern);
    check('squat front: view', r.view === 'front', r.view);
    check('squat front: 8 reps', r.reps.length === 8, r.reps.length);
    check('squat front: no faults', r.faults.length === 0, r.faults);
    check('squat front: depth measured', r.reps[2] && r.reps[2].minKnee < 95, r.reps[2]);
    check('squat front: high score', r.score >= 90, r.score);
    check('squat front: praise cue', cues.includes('good'), cues);
    check('squat front: confidence high', r.confidence === 'high', r.confidence);
    check('squat front: summary short', r.summary.length < 1400 && /Reps counted: 8/.test(r.summary), r.summary);
}
// 2. knees caving in from rep 3 on
{
    const { report: r, cues } = run({ drill: 'Bodyweight squats', seconds: 1.5 + 8 * 2.4 + 0.5, view: 'front',
        pose: (t) => ({ knee: 175 - 92 * cycle(t), trunk: 10, cave: t > 1.5 + 2 * 2.4 ? 0.09 * cycle(t) : 0 }) });
    const f = has(r, 'knees_in');
    check('valgus: detected', f && f.count >= 5 && f.count <= 6, f);
    check('valgus: not on reps 1-2', f && !f.reps.includes(1) && !f.reps.includes(2), f);
    check('valgus: live cue', cues.includes('knees_in'), cues);
    check('valgus: lower score', r.score < 90, r.score);
    check('valgus: fallback names the fix', /knees/i.test(r.fallback.fix), r.fallback);
}
// 3. side view: shallow squats with the chest dropping
{
    const { report: r } = run({ drill: 'Air squat', seconds: 1.5 + 6 * 2.4 + 0.5, view: 'side',
        pose: (t) => ({ knee: 175 - 50 * cycle(t), trunk: 5 + 62 * cycle(t) }) });
    check('side: view', r.view === 'side', r.view);
    check('side: 6 reps', r.reps.length === 6, r.reps.length);
    check('side: shallow', has(r, 'shallow') && has(r, 'shallow').count >= 5, r.faults);
    check('side: chest drop', has(r, 'chest_drop'), r.faults);
    check('side: no valgus claims side-on', !has(r, 'knees_in'), r.faults);
}
// 4. push-ups side-on, hips sagging on the later reps
{
    const { report: r, cues } = run({ drill: 'Push-ups', kind: 'pushup', seconds: 1.5 + 7 * 2.4 + 0.5, view: 'side',
        pose: (t) => ({ elbow: 170 - 88 * cycle(t), sag: t > 1.5 + 3 * 2.4 ? 0.14 : 0 }) });
    check('pushup: pattern', r.pattern === 'pushup', r.pattern);
    check('pushup: 7 reps', r.reps.length === 7, r.reps.length);
    check('pushup: depth ok', !has(r, 'pushup_shallow'), r.faults);
    check('pushup: sag found on later reps', has(r, 'hips_sag') && has(r, 'hips_sag').count >= 3 && !has(r, 'hips_sag').reps.includes(1), r.faults);
    check('pushup: sag cue', cues.includes('hips_sag'), cues);
}
// 5. plank hold that starts sagging after 6 s
{
    const { report: r, cues } = run({ drill: 'Forearm plank', kind: 'pushup', seconds: 14, view: 'side',
        pose: (t) => ({ elbow: 170, sag: t > 6 ? 0.16 : 0 }) });
    check('plank: hold', r.pattern === 'plank' && r.holdSeconds >= 13, r);
    check('plank: sag share', has(r, 'hips_sag') && has(r, 'hips_sag').share > 0.4, r.faults);
    check('plank: cue', cues.includes('hips_sag'), cues);
}
// 6. no keyword in the drill: recognised as a squat from the motion
{
    const { report: r } = run({ drill: 'Defensive base builder', text: 'Sink and rise with control.', seconds: 1.5 + 8 * 2.4 + 0.5, view: 'front',
        pose: (t) => ({ knee: 175 - 92 * cycle(t), trunk: 5 + 35 * cycle(t) }) });
    check('guess: squat from motion', r.pattern === 'squat' && r.patternFrom === 'motion', [r.pattern, r.patternFrom]);
    check('guess: most reps counted', r.reps.length >= 6, r.reps.length);
}
// 7. noisy tracking still counts reps
{
    const { report: r } = run({ drill: 'Squats', seconds: 1.5 + 8 * 2.4 + 0.5, view: 'front', noise: 0.012,
        pose: (t) => ({ knee: 175 - 92 * cycle(t), trunk: 10 }) });
    check('noise: 8 reps', r.reps.length === 8, r.reps.length);
}
// 8. 2D only (no world landmarks): still counts and measures
{
    const { report: r } = run({ drill: 'Squats', seconds: 1.5 + 6 * 2.4 + 0.5, view: 'side', world: false,
        pose: (t) => ({ knee: 175 - 92 * cycle(t), trunk: 10 + 20 * cycle(t) }) });
    check('2D: 6 reps', r.reps.length === 6, r.reps.length);
    check('2D: depth close', Math.abs(r.reps[1].minKnee - 83) < 8, r.reps[1]);
}
// 9. nobody in front of the camera
{
    const eng = E.create({ drill: 'Squats' });
    let s;
    for (let i = 0; i < 60; i++) s = eng.push({ t: i * 33, lm: null, aspect: 1 });
    const r = eng.report();
    check('empty: status', s.status === 'no_person', s);
    check('empty: low confidence + honest fallback', r.confidence === 'low' && /could not see/.test(r.fallback.headline), r.fallback);
}
// 10. jumps with stiff landings
{
    const { report: r } = run({ drill: 'Squat jumps', text: '', seconds: 1.5 + 6 * 2.4 + 0.5, view: 'front',
        pose: (t) => { const c = cycle(t); return { knee: 172 - 10 * c, lift: 0.45 * c }; } });
    check('jump: pattern', r.pattern === 'jump', r.pattern);
    check('jump: reps', r.reps.length === 6, r.reps.length);
    check('jump: stiff landing', has(r, 'stiff_landing'), r.faults);
}
// 11. fatigue trend: reps shrink
{
    const { report: r } = run({ drill: 'Squats', seconds: 1.5 + 9 * 2.4 + 0.5, view: 'front',
        pose: (t) => { const n = Math.floor((t - 1.5) / 2.4); return { knee: 175 - (n < 6 ? 92 : 50) * cycle(t), trunk: 10 }; } });
    check('trend: smaller reps found', r.trend && r.trend.some((x) => /smaller/.test(x)), r.trend);
}
// 12. keyword table
check('kw: lunge', E.patternFromText('Reverse lunges with a twist') === 'lunge');
check('kw: push-up', E.patternFromText('Explosive press-ups') === 'pushup');
check('kw: none', E.patternFromText('Free throw routine') === null);
check('kw: wall sit', E.patternFromText('Wall sit hold') === 'wallsit');

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
