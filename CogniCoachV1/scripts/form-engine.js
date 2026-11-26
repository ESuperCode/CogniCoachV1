// ==========================================================================
// CogniCoach Form Engine - turns body landmarks into coaching, with code instead of a vision model.
//
//   camera -> on-device pose model (33 landmarks / frame, MediaPipe, in the browser)
//          -> THIS FILE: smoothing, joint angles, camera view, rep segmentation, per-rep metrics,
//             a rule library of form faults, a score, live cues
//          -> a short text "movement summary" (a few hundred characters)
//          -> a cheap TEXT model writes the coach's words (optional: the rules alone already coach)
//
// No video or image ever leaves the device; only numbers and the summary text.
// Pure logic with no DOM, so it runs (and is tested) in Node: test/form_engine_test.mjs.
//
//   var eng = CogniFormEngine.create({ drill: 'Goblet squat', text: 'description...', pattern: optional });
//   var live = eng.push({ t: ms, lm: [33 x {x,y,z,visibility}], wl: [33 x {x,y,z}] (optional), aspect: w/h });
//     -> { status, message, reps, rep (just finished, or null), cue ({id,text} to say now, or null) }
//   var r = eng.report();
//     -> { pattern, view, seconds, reps[], faults[], score, confidence, summary (text for the model), fallback }
// ==========================================================================
(function (root) {
    'use strict';

    // ---------------------------------------------------------------- landmark ids (MediaPipe Pose)
    var NOSE = 0, LSH = 11, RSH = 12, LEL = 13, REL = 14, LWR = 15, RWR = 16,
        LHIP = 23, RHIP = 24, LKN = 25, RKN = 26, LAN = 27, RAN = 28;

    // ---------------------------------------------------------------- small maths
    function sub(a, b) { return { x: a.x - b.x, y: a.y - b.y, z: (a.z || 0) - (b.z || 0) }; }
    function mid(a, b) { return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: ((a.z || 0) + (b.z || 0)) / 2 }; }
    function len(v) { return Math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z); }
    function len2(v) { return Math.sqrt(v.x * v.x + v.y * v.y); }
    function angle(a, b, c, flat) {   // angle at b, degrees
        var u = sub(a, b), w = sub(c, b);
        if (flat) { u.z = 0; w.z = 0; }
        var d = len(u) * len(w);
        if (!(d > 1e-9)) { return null; }
        var cos = (u.x * w.x + u.y * w.y + u.z * w.z) / d;
        return Math.acos(Math.max(-1, Math.min(1, cos))) * 180 / Math.PI;
    }
    function mean(a) { return a.length ? a.reduce(function (s, v) { return s + v; }, 0) / a.length : null; }
    function median(a) { if (!a.length) { return null; } var s = a.slice().sort(function (x, y) { return x - y; }); var m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; }
    function sd(a) { var m = mean(a); return a.length > 1 ? Math.sqrt(mean(a.map(function (v) { return (v - m) * (v - m); }))) : 0; }
    function r0(v) { return v == null ? null : Math.round(v); }
    function r1(v) { return v == null ? null : Math.round(v * 10) / 10; }
    function r2(v) { return v == null ? null : Math.round(v * 100) / 100; }
    function minOf(a, b) { return a == null ? b : b == null ? a : Math.min(a, b); }
    function maxOf(a, b) { return a == null ? b : b == null ? a : Math.max(a, b); }

    // One Euro filter (Casiez et al. 2012): little lag when moving fast, little jitter when still.
    function OneEuro(minCutoff, beta) {
        var x = null, dx = 0, lastT = null;
        function a(cutoff, dt) { var tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
        return function (v, t) {
            if (v == null) { return null; }
            if (x == null || lastT == null || t <= lastT) { x = v; lastT = t; return v; }
            var dt = Math.min(0.5, (t - lastT) / 1000); lastT = t;
            var d = (v - x) / dt;
            dx = dx + a(1, dt) * (d - dx);
            x = x + a(minCutoff + beta * Math.abs(dx), dt) * (v - x);
            return x;
        };
    }

    // ---------------------------------------------------------------- movement patterns
    // signal: the measurement that moves during one rep. amp0: the smallest movement that counts as a rep.
    // body: which landmarks must be visible. hold: no reps, the athlete holds a position.
    var PATTERNS = {
        squat:    { label: 'squat',    signal: 'knee',     amp0: 25, body: 'lower' },
        lunge:    { label: 'lunge',    signal: 'kneeMin',  amp0: 25, body: 'lower' },
        hinge:    { label: 'hip hinge', signal: 'hip',     amp0: 25, body: 'lower' },
        jump:     { label: 'jump',     signal: 'hipY',     amp0: 0.18, body: 'lower' },
        pushup:   { label: 'push-up',  signal: 'elbow',    amp0: 25, body: 'full' },
        overhead: { label: 'overhead press or raise', signal: 'shoulder', amp0: 35, body: 'upper' },
        plank:    { label: 'plank hold', hold: true, body: 'full' },
        wallsit:  { label: 'wall sit', hold: true, body: 'lower' },
        general:  { label: 'general movement', signal: 'auto', amp0: 25, body: 'any' }
    };
    var KEYWORDS = [
        ['plank', /\bplanks?\b|\bhollow hold\b/],
        ['wallsit', /\bwall ?sits?\b/],
        ['pushup', /\bpush[- ]?ups?\b|\bpress[- ]?ups?\b/],
        ['lunge', /\blunges?\b|\bsplit squats?\b|\bstep[- ]?ups?\b/],
        ['jump', /\bjump|\bhops?\b|\bhopping\b|\bbounds?\b|\bplyo|\bbox jumps?\b|\bskater/],
        ['squat', /\bsquats?\b|\bsit[- ]to[- ]stand\b/],
        ['hinge', /\bdeadlifts?\b|\brdls?\b|\bhinge|\bgood mornings?\b|\bkettlebell swings?\b/],
        ['overhead', /\boverhead\b|\bshoulder press\b|\bmilitary press\b|\b[ytw][- ]raises?\b|\barm raises?\b|\blateral raises?\b/]
    ];
    function patternFromText(text) {
        var t = String(text || '').toLowerCase();
        for (var i = 0; i < KEYWORDS.length; i++) { if (KEYWORDS[i][1].test(t)) { return KEYWORDS[i][0]; } }
        return null;
    }

    // ---------------------------------------------------------------- the form rules
    // Each rule looks at one finished rep (or, for holds, at the whole hold) and returns a severity
    // 0..1 (0 = fine). views: the camera views in which the measurement can be trusted.
    // what: plain words for the summary; cue: what a coach would call out (short, spoken).
    var RULES = [
        // squat
        { id: 'shallow', pats: ['squat'], views: ['front', 'side', 'angled'], cue: 'Sit deeper, thighs toward parallel', what: 'did not reach parallel depth',
          test: function (r) { return r.minKnee == null ? 0 : sev(r.minKnee, 112, 145); } },
        { id: 'knees_in', pats: ['squat', 'lunge', 'jump'], views: ['front', 'angled'], cue: 'Push your knees out over your toes', what: 'knees caved inward',
          test: function (r) { return r.minValgus == null ? 0 : sev(-r.minValgus, -0.82, -0.6); } },
        { id: 'chest_drop', pats: ['squat'], views: ['side', 'angled'], cue: 'Keep your chest up', what: 'chest dropped forward',
          test: function (r) { return r.maxTrunk == null ? 0 : sev(r.maxTrunk, 50, 70); } },
        { id: 'uneven', pats: ['squat', 'hinge', 'jump', 'pushup'], views: ['front'], cue: 'Keep your weight even on both sides', what: 'one side worked more than the other',
          test: function (r) { return Math.max(r.asym == null ? 0 : sev(r.asym, 16, 35), r.tilt == null ? 0 : sev(r.tilt, 0.12, 0.25)); } },
        { id: 'rushed', pats: ['squat', 'lunge', 'hinge', 'pushup', 'overhead'], views: ['front', 'side', 'angled'], cue: 'Slow down on the way down', what: 'lowering phase was rushed',
          test: function (r) { return r.down == null ? 0 : sev(-r.down, -0.45, -0.2); } },
        // lunge
        { id: 'lunge_shallow', pats: ['lunge'], views: ['front', 'side', 'angled'], cue: 'Drop your back knee lower', what: 'lunge was not deep enough',
          test: function (r) { return r.minKnee == null ? 0 : sev(r.minKnee, 112, 145); } },
        { id: 'lean', pats: ['lunge'], views: ['side', 'angled'], cue: 'Stay tall through your chest', what: 'upper body leaned forward',
          test: function (r) { return r.maxTrunk == null ? 0 : sev(r.maxTrunk, 28, 50); } },
        // hinge
        { id: 'knee_dominant', pats: ['hinge'], views: ['side', 'angled'], cue: 'Push your hips back, keep your knees soft', what: 'bent the knees instead of hinging at the hips',
          test: function (r) { return r.minKnee == null ? 0 : sev(-r.minKnee, -125, -95); } },
        { id: 'hinge_short', pats: ['hinge'], views: ['side', 'angled'], cue: 'Hinge further, chest toward the floor', what: 'small hip hinge',
          test: function (r) { return r.amp == null ? 0 : sev(-r.amp, -40, -25); } },
        // push-up
        { id: 'pushup_shallow', pats: ['pushup'], views: ['side', 'angled'], cue: 'Lower your chest closer to the floor', what: 'did not lower far enough',
          test: function (r) { return r.minElbow == null ? 0 : sev(r.minElbow, 105, 135); } },
        { id: 'hips_sag', pats: ['pushup', 'plank'], views: ['side', 'angled'], cue: 'Squeeze your glutes, hips are sagging', what: 'hips sagged below the body line',
          test: function (r) { return r.sag == null ? 0 : sev(r.sag, 12, 28); } },
        { id: 'hips_pike', pats: ['pushup', 'plank'], views: ['side', 'angled'], cue: 'Lower your hips into one straight line', what: 'hips piked above the body line',
          test: function (r) { return r.pike == null ? 0 : sev(r.pike, 15, 32); } },
        // jump landing
        { id: 'stiff_landing', pats: ['jump'], views: ['front', 'side', 'angled'], cue: 'Land soft, bend your knees', what: 'landed with stiff knees',
          test: function (r) { return r.landKnee == null ? 0 : sev(r.landKnee, 150, 168); } },
        // overhead
        { id: 'no_lockout', pats: ['overhead'], views: ['front', 'side', 'angled'], cue: 'Reach all the way up', what: 'arms did not reach full extension',
          test: function (r) { return r.topElbow == null ? 0 : sev(-r.topElbow, -155, -125); } },
        { id: 'arch', pats: ['overhead'], views: ['side', 'angled'], cue: 'Ribs down, do not arch your back', what: 'leaned back while pressing',
          test: function (r) { return r.maxTrunk == null ? 0 : sev(r.maxTrunk, 15, 30); } },
        // holds
        { id: 'wallsit_high', pats: ['wallsit'], views: ['side', 'angled'], cue: 'Slide down until your knees are at ninety degrees', what: 'held the wall sit too high',
          test: function (r) { return r.knee == null ? 0 : sev(r.knee, 110, 140); } },
        // anything with reps
        { id: 'small_reps', pats: ['general'], views: ['front', 'side', 'angled'], cue: 'Use your full range of motion', what: 'reps got much smaller than your best',
          test: function (r, ctx) { return ctx.bestAmp && r.amp != null ? sev(-r.amp / ctx.bestAmp, -0.7, -0.45) : 0; } }
    ];
    // severity: 0 at `ok`, 1 at `bad`, linear in between
    function sev(v, ok, bad) { if (v == null) { return 0; } var s = (v - ok) / (bad - ok); return s <= 0 ? 0 : s >= 1 ? 1 : s; }
    var RULE_BY_ID = {};
    RULES.forEach(function (r) { RULE_BY_ID[r.id] = r; });

    // ---------------------------------------------------------------- per-frame features
    function vis(lm, ids) { var s = 0; ids.forEach(function (i) { s += lm[i] && lm[i].visibility != null ? lm[i].visibility : 1; }); return s / ids.length; }
    // image landmarks with x scaled to the same unit as y (so distances are not stretched)
    function img(lm, aspect) { return lm.map(function (p) { return p ? { x: p.x * aspect, y: p.y, z: (p.z || 0) * aspect } : null; }); }

    function features(frame, prevSide) {
        var lm = frame.lm;
        if (!lm || lm.length < 29) { return null; }
        var aspect = frame.aspect || 4 / 3;
        var I = img(lm, aspect), W = frame.wl && frame.wl.length >= 29 ? frame.wl : null;
        var P = W || I;   // 3D world landmarks (metres) when the model gives them: angles barely depend on the view
        var up = vis(lm, [LSH, RSH, LEL, REL, LWR, RWR]), low = vis(lm, [LHIP, RHIP, LKN, RKN, LAN, RAN]);
        var torso = vis(lm, [LSH, RSH, LHIP, RHIP]);
        var f = { visUpper: up, visLower: low, visTorso: torso };
        if (torso < 0.5) { return f; }
        var shW = len2(sub(I[LSH], I[RSH])), hipW = len2(sub(I[LHIP], I[RHIP]));
        var torsoLen = len2(sub(mid(I[LSH], I[RSH]), mid(I[LHIP], I[RHIP])));
        if (!(torsoLen > 1e-4)) { return f; }
        f.torsoLen = torsoLen;
        // camera view: shoulders look wide facing the camera, narrow side-on
        var widthRatio = Math.max(shW, hipW * 1.2) / torsoLen;
        f.widthRatio = widthRatio;
        // the side nearer the camera is the one to trust side-on
        var lv = vis(lm, [LSH, LEL, LHIP, LKN, LAN]), rv = vis(lm, [RSH, REL, RHIP, RKN, RAN]);
        var side = Math.abs(lv - rv) > 0.08 ? (lv > rv ? 'L' : 'R') : (prevSide || 'L');
        f.side = side;
        var lowOk = low >= 0.5, upOk = up >= 0.5;
        if (lowOk) {
            f.kneeL = angle(P[LHIP], P[LKN], P[LAN]);
            f.kneeR = angle(P[RHIP], P[RKN], P[RAN]);
            f.hipL = angle(P[LSH], P[LHIP], P[LKN]);
            f.hipR = angle(P[RSH], P[RHIP], P[RKN]);
            // knee width vs ankle width (front view): under ~0.8 at the bottom means the knees cave in
            var kw = Math.abs(I[LKN].x - I[RKN].x), aw = Math.abs(I[LAN].x - I[RAN].x);
            f.valgus = aw > hipW * 0.6 && aw > 1e-4 ? kw / aw : null;
            f.hipTilt = hipW > 1e-4 ? Math.abs(I[LHIP].y - I[RHIP].y) / torsoLen : null;
            // height of the hips in torso lengths (y grows downward on screen)
            f.hipY = mid(I[LHIP], I[RHIP]).y / torsoLen;
            // body line shoulder-hip-ankle (push-up / plank), and whether the hips sit below (sag) or above (pike) it
            var s = side === 'L' ? I[LSH] : I[RSH], h = side === 'L' ? I[LHIP] : I[RHIP], a = side === 'L' ? I[LAN] : I[RAN];
            var la = sub(a, s), lh = sub(h, s), L2 = la.x * la.x + la.y * la.y;
            if (L2 > 1e-6) {
                var t = (lh.x * la.x + lh.y * la.y) / L2;
                var dy = h.y - (s.y + t * la.y), dx = h.x - (s.x + t * la.x);
                var off = Math.sqrt(dx * dx + dy * dy);
                var bend = 180 - (angle(s, h, a, true) || 180);
                f.lineBend = bend;
                f.lineDir = dy > 0 ? 'sag' : 'pike';
                f.lineOff = off / torsoLen;
            }
        }
        if (upOk) {
            f.elbowL = angle(P[LSH], P[LEL], P[LWR]);
            f.elbowR = angle(P[RSH], P[REL], P[RWR]);
            f.shoulderL = angle(P[LHIP], P[LSH], P[LEL]);
            f.shoulderR = angle(P[RHIP], P[RSH], P[REL]);
        }
        // trunk lean from vertical (0 = upright, 90 = horizontal), in the image plane
        var tv = sub(mid(I[LSH], I[RSH]), mid(I[LHIP], I[RHIP]));
        f.trunk = Math.acos(Math.max(-1, Math.min(1, -tv.y / len2(tv)))) * 180 / Math.PI;
        // head over shoulders, for horizontal-body checks
        f.noseY = lm[NOSE] ? lm[NOSE].y / torsoLen : null;
        // combined values: the near side when side-on, the average facing the camera
        function both(a, b) { return a == null ? b : b == null ? a : (a + b) / 2; }
        function pick(l, r) { return f.view === 'side' ? (side === 'L' ? l : r) : both(l, r); }
        f.view = widthRatio > 0.62 ? 'front' : widthRatio < 0.38 ? 'side' : 'angled';
        f.knee = pick(f.kneeL, f.kneeR);
        f.kneeMin = minOf(f.kneeL, f.kneeR);
        f.hip = pick(f.hipL, f.hipR);
        f.elbow = pick(f.elbowL, f.elbowR);
        f.shoulder = pick(f.shoulderL, f.shoulderR);
        return f;
    }

    // ---------------------------------------------------------------- rep segmentation
    // A rep = leaving the rest position by more than a threshold, reaching a peak, and coming back.
    // The threshold adapts to the athlete's own range (40% of their recent reps, never under amp0),
    // and the rest value drifts slowly so a person who shifts their stance is not lost.
    function RepDetector(amp0, bothWays) {
        var base = null, buf = [], state = 'rest', cur = null, ampRef = 0, dir = 0, lastRestT = 0, startT = null;
        return {
            base: function () { return base; },
            ready: function () { return base != null; },
            reset: function () { base = null; buf = []; state = 'rest'; cur = null; startT = null; },
            seed: function (v, t) { if (v != null) { base = v; lastRestT = t; } },
            push: function (t, v) {
                if (v == null) { return null; }
                if (base == null) {
                    if (startT == null) { startT = t; }
                    buf.push(v);
                    if (buf.length >= 3 && Math.max.apply(null, buf) - Math.min.apply(null, buf) > amp0 * 0.6) { buf = buf.slice(-3); startT = t; }  // still moving: wait
                    if (t - startT >= 700 && buf.length >= 5) { base = median(buf); lastRestT = t; }
                    return null;
                }
                var e = v - base, thr = Math.max(amp0, 0.4 * ampRef);
                if (state === 'rest') {
                    if (Math.abs(e) < thr * 0.25) { lastRestT = t; base += 0.03 * (v - base); }
                    var goes = Math.abs(e) > thr && (bothWays || !dir || Math.sign(e) === dir);
                    if (goes) {
                        if (!dir && !bothWays) { dir = Math.sign(e); }
                        state = 'rep';
                        cur = { start: lastRestT, peak: Math.abs(e), peakT: t, peakV: v, values: [] };
                    }
                    return null;
                }
                // in a rep
                if (Math.abs(e) > cur.peak) { cur.peak = Math.abs(e); cur.peakT = t; cur.peakV = v; }
                if (t - cur.start > 15000) { state = 'rest'; cur = null; base = v; return null; }   // a new position, not a rep
                if (Math.abs(e) < Math.max(thr * 0.3, cur.peak * 0.3)) {
                    var done = cur; state = 'rest'; cur = null; lastRestT = t;
                    var dur = (t - done.start) / 1000;
                    if (dur < 0.35) { return null; }   // jitter
                    ampRef = ampRef ? 0.7 * ampRef + 0.3 * done.peak : done.peak;
                    return { start: done.start, end: t, peakT: done.peakT, amp: done.peak, peakV: done.peakV,
                        down: (done.peakT - done.start) / 1000, up: (t - done.peakT) / 1000, dur: dur };
                }
                return 'in';
            }
        };
    }

    // ---------------------------------------------------------------- the engine
    function create(opts) {
        opts = opts || {};
        var textPattern = opts.pattern && PATTERNS[opts.pattern] ? opts.pattern : patternFromText((opts.drill || '') + ' ' + (opts.text || ''));
        var pattern = textPattern || 'general';
        var patternFrom = textPattern ? 'drill' : 'guess';
        var cfg = PATTERNS[pattern];
        var filters = {}, prevSide = null;
        var frames = 0, personFrames = 0, bodyFrames = 0, t0 = null, tLast = null, lastStatus = null;
        var views = { front: 0, side: 0, angled: 0 };
        var detector = null, seedRest = null, autoSignal = null, autoBuf = textPattern ? null : {}, inRep = null, reps = [], bestAmp = 0;
        var holdFrames = [], holdGood = 0, holdT = 0;
        var cueLog = [], lastCueT = -1e9, cleanStreak = 0, lastPraiseT = -1e9;

        var SMOOTH = { knee: 0.02, kneeMin: 0.02, kneeL: 0.02, kneeR: 0.02, hip: 0.02, hipL: 0.02, hipR: 0.02, elbow: 0.02, elbowL: 0.02, elbowR: 0.02,
            shoulder: 0.02, shoulderL: 0.02, shoulderR: 0.02, trunk: 0.02, lineBend: 0.02, valgus: 2, hipTilt: 2, hipY: 2, lineOff: 2 };
        function smooth(f, t) {
            Object.keys(SMOOTH).forEach(function (k) {
                if (f[k] == null) { return; }
                if (!filters[k]) { filters[k] = OneEuro(1.5, SMOOTH[k]); }
                f[k] = filters[k](f[k], t);
            });
            return f;
        }
        function viewNow() {
            var best = 'angled', n = -1;
            Object.keys(views).forEach(function (v) { if (views[v] > n) { n = views[v]; best = v; } });
            return best;
        }
        function bodyOk(f) {
            if (cfg.body === 'lower') { return f.visLower >= 0.5; }
            if (cfg.body === 'upper') { return f.visUpper >= 0.5; }
            if (cfg.body === 'full') { return f.visLower >= 0.5 && f.visUpper >= 0.4; }
            return f.visLower >= 0.5 || f.visUpper >= 0.5;
        }
        // When the drill text names no movement, watch the first seconds and pick the measurement that
        // moves the most (and the body position) to choose a pattern.
        function guess(f, t) {
            ['knee', 'hip', 'elbow', 'shoulder', 'hipY', 'trunk'].forEach(function (k) {
                if (f[k] != null) { (autoBuf[k] = autoBuf[k] || []).push(f[k]); }
            });
            if (t - t0 < 4000) { return; }
            var range = {};
            Object.keys(autoBuf).forEach(function (k) {
                var s = autoBuf[k].slice().sort(function (a, b) { return a - b; });
                range[k] = s.length > 10 ? s[Math.floor(s.length * 0.95)] - s[Math.floor(s.length * 0.05)] : 0;
            });
            var trunkMed = median(autoBuf.trunk || []);
            var p = null;
            if (trunkMed != null && trunkMed > 55) { p = (range.elbow || 0) > 30 ? 'pushup' : 'plank'; }
            else if ((range.hipY || 0) > 0.3 && (range.knee || 0) < 60) { p = 'jump'; }
            else if ((range.knee || 0) > 35 && (range.hip || 0) > 35) { p = 'squat'; }
            else if ((range.hip || 0) > 35) { p = 'hinge'; }
            else if ((range.shoulder || 0) > 50) { p = 'overhead'; }
            // the rest position of a joint exercise is the straight end of the range (the shoulder: arms down)
            var restOf = function (k) {
                var s = (autoBuf[k] || []).slice().sort(function (a, b) { return a - b; });
                if (s.length < 10) { return null; }
                return k === 'shoulder' ? s[Math.floor(s.length * 0.1)] : k === 'hipY' ? median(s) : s[Math.floor(s.length * 0.9)];
            };
            if (p) { pattern = p; cfg = PATTERNS[p]; patternFrom = 'motion'; }
            else {   // keep 'general': count reps on whatever moves the most
                var bestK = 'knee', bestR = 0;
                ['knee', 'hip', 'elbow', 'shoulder'].forEach(function (k) { if ((range[k] || 0) > bestR) { bestR = range[k]; bestK = k; } });
                if ((range.hipY || 0) * 120 > bestR) { bestK = 'hipY'; }
                autoSignal = bestK;
            }
            var sig = cfg.hold ? null : cfg.signal === 'auto' ? autoSignal : cfg.signal;
            seedRest = sig ? restOf(sig === 'kneeMin' ? 'knee' : sig) : null;
            autoBuf = null;
        }
        function signalName() { return cfg.signal === 'auto' ? autoSignal : cfg.signal; }
        function ensureDetector() {
            if (detector || cfg.hold) { return; }
            var s = signalName();
            if (!s) { return; }
            detector = RepDetector(s === 'hipY' ? 0.18 : cfg.amp0, s === 'hipY');
            if (seedRest != null) { detector.seed(seedRest, tLast); }
        }

        // collect what happens inside the rep that is in progress
        function trackRep(f, t) {
            if (!inRep) { inRep = { minKnee: null, minKneeL: null, minKneeR: null, minHip: null, minElbow: null, maxTrunk: null, minValgus: null,
                maxTilt: null, maxShoulder: null, topElbow: null, sag: null, pike: null, minHipY: null, minHipYT: null, landKnee: null, asymAt: null, sig: -1 }; }
            var r = inRep;
            r.minKnee = minOf(r.minKnee, pattern === 'lunge' ? f.kneeMin : f.knee);
            r.minHip = minOf(r.minHip, f.hip);
            r.minElbow = minOf(r.minElbow, f.elbow);
            r.maxTrunk = maxOf(r.maxTrunk, pattern === 'overhead' ? f.trunk : f.trunk);
            if (f.knee != null && f.knee < 150) { r.minValgus = minOf(r.minValgus, f.valgus); }
            r.maxTilt = maxOf(r.maxTilt, f.hipTilt);
            if (f.shoulder != null && (r.maxShoulder == null || f.shoulder > r.maxShoulder)) { r.maxShoulder = f.shoulder; r.topElbow = f.elbow; }
            if (f.lineBend != null) { if (f.lineDir === 'sag') { r.sag = maxOf(r.sag, f.lineBend); } else { r.pike = maxOf(r.pike, f.lineBend); } }
            if (f.hipY != null && (r.minHipY == null || f.hipY < r.minHipY)) { r.minHipY = f.hipY; r.minHipYT = t; r.landKnee = null; }
            if (r.minHipYT != null && t > r.minHipYT) { r.landKnee = minOf(r.landKnee, f.knee); }
            // left-right difference at the deepest point of the rep
            var s = f[signalName()];
            var dev = s == null || !detector || detector.base() == null ? -1 : Math.abs(s - detector.base());
            if (dev > r.sig) {
                r.sig = dev;
                var pair = pattern === 'pushup' ? [f.elbowL, f.elbowR] : pattern === 'overhead' ? [f.shoulderL, f.shoulderR] : [f.kneeL, f.kneeR];
                r.asymAt = pair[0] != null && pair[1] != null && viewNow() === 'front' ? Math.abs(pair[0] - pair[1]) : null;
            }
        }
        function finishRep(ev) {
            var r = inRep || {};
            inRep = null;
            var rep = { n: reps.length + 1, t: Math.round((ev.end - t0) / 100) / 10, dur: r1(ev.dur), down: r1(ev.down), up: r1(ev.up),
                amp: signalName() === 'hipY' ? r2(ev.amp) : r0(ev.amp),
                minKnee: r0(r.minKnee), minHip: r0(r.minHip), minElbow: r0(r.minElbow), maxTrunk: r0(r.maxTrunk),
                minValgus: r2(r.minValgus), tilt: r2(r.maxTilt), topElbow: r0(r.topElbow), sag: r0(r.sag), pike: r0(r.pike),
                landKnee: r0(r.landKnee), asym: r0(r.asymAt), faults: [] };
            if (pattern !== 'jump') { rep.landKnee = null; }
            bestAmp = Math.max(bestAmp, ev.amp);
            var view = viewNow();
            RULES.forEach(function (rule) {
                if (rule.pats.indexOf(pattern) < 0 || rule.views.indexOf(view) < 0) { return; }
                var s = rule.test(rep, { bestAmp: signalName() === 'hipY' ? bestAmp : bestAmp, pattern: pattern });
                if (s > 0.05) { rep.faults.push({ id: rule.id, sev: r2(s) }); }
            });
            rep.faults.sort(function (a, b) { return b.sev - a.sev; });
            rep.score = Math.max(0, Math.round(100 - rep.faults.reduce(function (s, f) { return s + 30 * f.sev; }, 0)));
            reps.push(rep);
            return rep;
        }
        // Live coaching: say the worst fault when it repeats (2 of the last 3 reps) or is serious,
        // at most every 6 s and never the same cue twice within 15 s; praise a run of clean reps.
        function liveCue(rep, t) {
            if (!rep) { return null; }
            if (!rep.faults.length) {
                cleanStreak++;
                if (cleanStreak >= 3 && t - lastPraiseT > 20000 && t - lastCueT > 6000) { lastPraiseT = t; lastCueT = t; cleanStreak = 0; return say('good', 'Good reps, keep that form', t); }
                return null;
            }
            cleanStreak = 0;
            if (t - lastCueT < 6000) { return null; }
            var last3 = reps.slice(-3);
            for (var i = 0; i < rep.faults.length; i++) {
                var id = rep.faults[i].id;
                var times = last3.filter(function (r) { return r.faults.some(function (f) { return f.id === id; }); }).length;
                var recent = cueLog.filter(function (c) { return c.id === id && t - c.t < 15000; }).length;
                if ((times >= 2 || rep.faults[i].sev >= 0.6) && !recent) { lastCueT = t; return say(id, RULE_BY_ID[id].cue, t); }
            }
            return null;
        }
        function say(id, text, t) { var c = { id: id, text: text, t: t }; cueLog.push(c); return { id: id, text: text }; }

        // holds (plank, wall sit): judge the position the whole time
        var holdCueT = -1e9;
        function trackHold(f, t, dt) {
            var rec = { knee: f.knee, sag: f.lineDir === 'sag' ? f.lineBend : 0, pike: f.lineDir === 'pike' ? f.lineBend : 0 };
            holdFrames.push(rec);
            holdT += dt;
            var view = viewNow(), worst = null, worstS = 0;
            RULES.forEach(function (rule) {
                if (rule.pats.indexOf(pattern) < 0 || rule.views.indexOf(view) < 0) { return; }
                var s = rule.test(rec, {});
                rec[rule.id] = s;
                if (s > worstS) { worstS = s; worst = rule; }
            });
            if (worstS < 0.2) { holdGood += dt; }
            // a fault must last ~1.5 s before it is called out
            var recentBad = holdFrames.slice(-25).filter(function (r) { return worst && (r[worst.id] || 0) > 0.2; }).length;
            if (worst && recentBad >= 20 && t - holdCueT > 8000) { holdCueT = t; return say(worst.id, worst.cue, t); }
            return null;
        }

        function push(frame) {
            var t = frame.t;
            if (t0 == null) { t0 = t; }
            var dt = tLast == null ? 0 : Math.min(500, t - tLast) / 1000;
            tLast = t;
            frames++;
            var f = frame.lm ? features(frame, prevSide) : null;
            if (!f || f.visTorso < 0.5) {
                return status('no_person', 'I cannot see you yet. Step into the frame.', null, null);
            }
            personFrames++;
            prevSide = f.side;
            if (f.view) { views[f.view]++; }
            if (autoBuf) { guess(f, t); }
            if (!bodyOk(f)) {
                return status('partial', cfg.body === 'upper' ? 'Move so your arms and shoulders are in view.' : 'Step back so I can see your whole body, feet included.', null, null);
            }
            bodyFrames++;
            smooth(f, t);
            if (cfg.hold) {
                var c = trackHold(f, t, dt);
                return status('tracking', 'Hold it. ' + Math.round(holdT) + ' s', null, c);
            }
            if (autoBuf && pattern === 'general') { return status('calibrating', 'Start moving. I am learning the movement.', null, null); }
            ensureDetector();
            if (!detector) { return status('calibrating', 'Start moving.', null, null); }
            var v = f[signalName()];
            var ev = detector.push(t, v);
            if (!detector.ready()) { return status('calibrating', 'Hold still in your start position for a second.', null, null); }
            if (ev === 'in' || inRep) { trackRep(f, t); }
            var rep = ev && ev !== 'in' ? finishRep(ev) : null;
            return status('tracking', reps.length ? 'Rep ' + reps.length : 'Go! Start your reps.', rep, liveCue(rep, t));
        }
        function status(code, message, rep, cue) {
            lastStatus = code;
            return { status: code, message: message, reps: reps.length, rep: rep, cue: cue, pattern: pattern, holdSeconds: cfg.hold ? Math.round(holdT) : null };
        }

        // ---------------------------------------------------------------- the report
        function report() {
            var view = viewNow();
            var seconds = t0 == null ? 0 : Math.round((tLast - t0) / 100) / 10;
            var visible = frames ? bodyFrames / frames : 0;
            var viewShare = personFrames ? views[view] / personFrames : 0;
            var out = { pattern: pattern, patternLabel: cfg.label, patternFrom: patternFrom, view: view, seconds: seconds,
                frames: frames, visible: r2(visible), reps: reps.slice(), faults: [], score: null, confidence: 'low', summary: '', fallback: null };
            var lines = [];
            lines.push('Movement: ' + cfg.label + ' (' + (patternFrom === 'drill' ? 'from the drill name' : patternFrom === 'motion' ? 'recognised from the motion' : 'unknown, counted the joint that moved most: ' + (autoSignal || 'none')) + ').');
            lines.push('Camera: ' + view + ' view. Tracked ' + seconds + ' s, whole body visible in ' + Math.round(visible * 100) + '% of frames.');

            if (cfg.hold) {
                var good = holdT ? holdGood / holdT : 0;
                out.holdSeconds = Math.round(holdT);
                out.goodShare = r2(good);
                RULES.forEach(function (rule) {
                    if (rule.pats.indexOf(pattern) < 0 || rule.views.indexOf(view) < 0) { return; }
                    var bad = holdFrames.filter(function (r) { return (r[rule.id] || 0) > 0.2; }).length;
                    if (bad / Math.max(1, holdFrames.length) > 0.15) {
                        out.faults.push({ id: rule.id, count: null, share: r2(bad / holdFrames.length), what: rule.what, cue: rule.cue });
                    }
                });
                lines.push('Hold: ' + Math.round(holdT) + ' s, good position ' + Math.round(good * 100) + '% of the time.');
                var knees = holdFrames.map(function (r) { return r.knee; }).filter(function (v) { return v != null; });
                if (pattern === 'wallsit' && knees.length) { lines.push('Knee angle: median ' + r0(median(knees)) + ' deg (target about 90).'); }
                var sags = holdFrames.map(function (r) { return r.sag || 0; }), pikes = holdFrames.map(function (r) { return r.pike || 0; });
                if (pattern === 'plank' && view !== 'front') { lines.push('Body line: median bend ' + r0(median(sags.map(function (s, i) { return s || -pikes[i]; }))) + ' deg (positive = hips sagging, negative = piking, 0 = straight).'); }
                out.score = holdT < 3 ? null : Math.round(100 * (0.4 + 0.6 * good));
            } else {
                var n = reps.length;
                lines.push('Reps counted: ' + n + '.');
                if (n) {
                    var durs = reps.map(function (r) { return r.dur; }), downs = reps.map(function (r) { return r.down; }), ups = reps.map(function (r) { return r.up; });
                    var amps = reps.map(function (r) { return r.amp; });
                    var cv = mean(amps) ? sd(amps) / mean(amps) : 0;
                    out.tempo = { rep: r1(mean(durs)), down: r1(mean(downs)), up: r1(mean(ups)) };
                    out.consistency = cv < 0.12 ? 'very consistent' : cv < 0.25 ? 'fairly consistent' : 'uneven';
                    lines.push('Tempo: ' + r1(mean(durs)) + ' s per rep (' + r1(mean(downs)) + ' s down, ' + r1(mean(ups)) + ' s up). Rep size ' + out.consistency + '.');
                    function stat(key, label, unit, better) {
                        var v = reps.map(function (r) { return r[key]; }).filter(function (x) { return x != null; });
                        if (!v.length) { return; }
                        var best = better === 'low' ? Math.min.apply(null, v) : Math.max.apply(null, v), worst = better === 'low' ? Math.max.apply(null, v) : Math.min.apply(null, v);
                        lines.push(label + ': avg ' + (unit === '' ? r2(mean(v)) : r0(mean(v))) + unit + ' (best ' + best + unit + ', worst ' + worst + unit + ').');
                    }
                    if (/squat|lunge|hinge|jump/.test(pattern) || (pattern === 'general' && autoSignal === 'knee')) { stat('minKnee', 'Knee angle at the bottom (180 = straight)', ' deg', 'low'); }
                    if (pattern === 'hinge') { stat('minHip', 'Hip angle at the bottom', ' deg', 'low'); }
                    if (pattern === 'jump') { stat('landKnee', 'Knee bend when landing', ' deg', 'low'); }
                    if (pattern === 'pushup' || (pattern === 'general' && autoSignal === 'elbow')) { stat('minElbow', 'Elbow angle at the bottom', ' deg', 'low'); }
                    if (pattern === 'overhead') { stat('topElbow', 'Elbow angle at the top', ' deg', 'high'); }
                    if (view !== 'front' && /squat|lunge|hinge|overhead/.test(pattern)) { stat('maxTrunk', 'Upper body lean from vertical', ' deg', 'low'); }
                    if (view !== 'side' && /squat|lunge|jump/.test(pattern)) { stat('minValgus', 'Knee width / ankle width at the bottom (under 0.8 = knees caving)', '', 'high'); }
                    if (view === 'front') { stat('asym', 'Left-right difference at the bottom', ' deg', 'low'); }
                    // fatigue: did the reps get smaller or slower near the end?
                    if (n >= 6) {
                        var k = Math.max(2, Math.floor(n / 3)), first = reps.slice(0, k), last = reps.slice(-k);
                        var a1 = mean(first.map(function (r) { return r.amp; })), a2 = mean(last.map(function (r) { return r.amp; }));
                        var d1 = mean(first.map(function (r) { return r.dur; })), d2 = mean(last.map(function (r) { return r.dur; }));
                        var trend = [];
                        if (a2 < a1 * 0.85) { trend.push('last ' + k + ' reps were ' + Math.round((1 - a2 / a1) * 100) + '% smaller than the first ' + k); }
                        if (d2 > d1 * 1.3) { trend.push('last reps were ' + Math.round((d2 / d1 - 1) * 100) + '% slower'); }
                        if (d2 < d1 * 0.7) { trend.push('last reps were rushed (' + Math.round((1 - d2 / d1) * 100) + '% faster)'); }
                        out.trend = trend;
                        lines.push('Trend: ' + (trend.length ? trend.join('; ') : 'form held steady from first to last rep') + '.');
                    }
                    var counts = {};
                    reps.forEach(function (r) { r.faults.forEach(function (f) { (counts[f.id] = counts[f.id] || []).push(r.n); }); });
                    Object.keys(counts).forEach(function (id) {
                        var rule = RULE_BY_ID[id];
                        out.faults.push({ id: id, count: counts[id].length, reps: counts[id], what: rule.what, cue: rule.cue });
                    });
                    out.faults.sort(function (a, b) { return b.count - a.count; });
                    if (out.faults.length) {
                        lines.push('Faults (rule checks): ' + out.faults.map(function (f) { return f.what + ' on ' + f.count + ' of ' + n + ' reps (' + f.reps.slice(0, 8).join(',') + ')'; }).join('; ') + '.');
                    } else { lines.push('Faults (rule checks): none.'); }
                    out.score = Math.round(mean(reps.map(function (r) { return r.score; })));
                }
            }
            var checked = RULES.filter(function (r) { return r.pats.indexOf(pattern) >= 0; });
            var unseen = checked.filter(function (r) { return r.views.indexOf(view) < 0; }).map(function (r) { return r.what.replace(/^(did not|was) /, ''); });
            if (out.score != null) { lines.push('Form score from the rules: ' + out.score + '/100.'); }
            var enough = cfg.hold ? holdT >= 8 : reps.length >= 3;
            out.confidence = enough && visible > 0.75 && viewShare > 0.6 ? 'high' : (cfg.hold ? holdT >= 3 : reps.length >= 1) && visible > 0.5 ? 'medium' : 'low';
            lines.push('Measurement confidence: ' + out.confidence + '.');
            // For the model: when nothing is wrong it must not hunt for a fault among things it cannot see,
            // so the unseen checks are left out and the job is stated plainly.
            var forModel = lines.slice();
            if (!out.faults.length && out.confidence !== 'low') { forModel.push('No faults found: the fix should be a progression that keeps this form.'); }
            if (unseen.length) { lines.push('Not checked from this camera view: ' + unseen.slice(0, 3).join(', ') + '.'); }
            out.summary = lines.join('\n').slice(0, 1400);
            out.modelSummary = forModel.join('\n').slice(0, 1400);
            out.fallback = fallbackFeedback(out);
            return out;
        }

        return { push: push, report: report, pattern: function () { return pattern; }, reps: function () { return reps.length; } };
    }

    // Coach's words without any AI: used offline, while the model is thinking, or if it fails.
    function fallbackFeedback(r) {
        var top = r.faults[0];
        var reps = r.reps.length;
        if (r.confidence === 'low' && !(r.holdSeconds >= 3) && !reps) {
            return { headline: 'I could not see enough to judge your form.', praise: '', fix: 'Set the camera 2 to 3 metres away at hip height so your whole body is in view, then do at least 3 reps.', cue: 'Whole body in view', next: '' };
        }
        var praise = '';
        if (r.pattern !== 'plank' && r.pattern !== 'wallsit') {
            if (r.consistency === 'very consistent') { praise = 'Your reps were very consistent in size.'; }
            else if (r.trend && !r.trend.length) { praise = 'Your form held steady from the first rep to the last.'; }
            else if (reps && r.tempo && r.tempo.down >= 0.8) { praise = 'Good control on the way down.'; }
            else if (reps) { praise = 'You got ' + reps + ' rep' + (reps === 1 ? '' : 's') + ' in.'; }
        } else if (r.goodShare != null) { praise = 'You held a good position ' + Math.round(r.goodShare * 100) + '% of the time.'; }
        var fix = top ? 'Main fix: your ' + top.what.replace(/^(did not|was) /, '') + (top.count != null ? ' on ' + top.count + ' of ' + reps + ' reps.' : ' for part of the hold.') + ' ' + top.cue + '.'
            : 'No faults found by the checks I can run from this camera view.';
        var headline = r.score == null ? 'Form check done.' : r.score >= 85 ? 'Strong form.' : r.score >= 65 ? 'Solid, with one thing to fix.' : 'Let us clean up your form.';
        return { headline: headline, praise: praise, fix: fix, cue: top ? top.cue : 'Same again', next: r.trend && r.trend.length ? 'Your reps faded near the end: take a longer rest or do fewer reps per set.' : '' };
    }

    var api = { create: create, patternFromText: patternFromText, PATTERNS: PATTERNS, RULES: RULES, features: features, fallbackFeedback: fallbackFeedback };
    if (typeof module === 'object' && module.exports) { module.exports = api; }
    root.CogniFormEngine = api;
})(typeof window !== 'undefined' ? window : globalThis);
