// ==========================================================================
// Form Check: the camera watches one set and the coach gives feedback on the athlete's form.
//
//   1. the camera picture goes to an on-device pose model (MediaPipe Pose Landmarker lite, served from
//      assets/pose/, loaded only when Form Check is opened); the picture never leaves the device
//   2. scripts/form-engine.js turns the 33 landmarks per frame into reps, angles, faults and live cues
//      (spoken while training, no AI)
//   3. after the set, a short text summary of the measurements goes to the motion Worker's
//      /form-feedback, where ONE call to the cheapest text model writes the coach's note.
//      If that is unavailable, the measured feedback from the rules is shown on its own.
//   4. repeated faults are remembered by Your coach (CogniCoachProfile.recordForm) so later drills
//      are planned around them.
// Button: "Check my form" under the drill card opens a side panel (a bottom sheet on phones) so the drill,
// muscle map and 3D preview stay visible. Escape closes it and returns focus.
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniFormCheck) { return; }
    var params = new URLSearchParams(window.location.search);
    var API = (params.get('motionApi') || 'https://cognicoach-motion.bodhishanbhag.workers.dev').replace(/\/$/, '');
    var BASE = new URL('assets/pose/', document.baseURI).href;
    var VOICE_KEY = 'cognicoach-form-voice';
    var CONNECT = [[11, 12], [11, 13], [13, 15], [12, 14], [14, 16], [11, 23], [12, 24], [23, 24], [23, 25], [25, 27], [24, 26], [26, 28], [27, 31], [28, 32], [27, 29], [28, 30]];

    function ic(n, s) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: s || 18 }) : ''; }
    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function reduceMotion() { return document.documentElement.classList.contains('a11y-reduce-motion'); }

    var root, video, canvas, ctx2d, els = {}, lastFocus = null;
    var landmarkerP = null, landmarker = null, stream = null, engine = null, running = false, raf = 0, lastT = 0, lastCueText = '';
    var drill = null, report = null, reqId = 0, camId = 0;

    // ------------------------------------------------------------------ the drill being trained
    function currentDrill() {
        var d = null;
        try { var s = appState.session; d = s.drills[s.currentDrillIndex].generatedDrill || null; } catch (e) {}
        var name = d && d.name || (document.getElementById('drillName') || {}).textContent || '';
        var text = d && d.description || (document.getElementById('drillDescription') || {}).textContent || '';
        var sport = '';
        try { sport = appState.setup.sport || ''; } catch (e) {}
        return { name: String(name).trim().slice(0, 120), text: String(text).slice(0, 1500), sport: sport, cues: d && Array.isArray(d.cues) ? d.cues.slice(0, 3) : [] };
    }

    // ------------------------------------------------------------------ the pose model (loaded once, on demand)
    function timeout(p, ms, what) {
        return new Promise(function (res, rej) {
            var t = setTimeout(function () { rej(new Error(what + ' timed out')); }, ms);
            p.then(function (v) { clearTimeout(t); res(v); }, function (e) { clearTimeout(t); rej(e); });
        });
    }
    function loadModel() {
        if (landmarkerP) { return landmarkerP; }
        landmarkerP = timeout(import(BASE + 'vision_bundle.mjs').then(function (mp) {
            return mp.FilesetResolver.forVisionTasks(BASE + 'wasm').then(function (files) {
                function make(delegate) {
                    return mp.PoseLandmarker.createFromOptions(files, {
                        baseOptions: { modelAssetPath: BASE + 'pose_landmarker_lite.task', delegate: delegate },
                        runningMode: 'VIDEO', numPoses: 1,
                        minPoseDetectionConfidence: 0.5, minPosePresenceConfidence: 0.5, minTrackingConfidence: 0.5
                    });
                }
                // the graphics card is fastest, but on some devices it fails or hangs: fall back to the processor
                return timeout(make('GPU'), 15000, 'GPU tracker').catch(function () { return make('CPU'); });
            });
        }), 120000, 'Loading the tracker').then(function (lm) { landmarker = lm; return lm; }, function (err) {
            landmarkerP = null;
            if (window.console) { console.warn('Form check: movement tracker failed to load', err); }
            throw err;
        });
        return landmarkerP;
    }

    // ------------------------------------------------------------------ side panel (not modal: the drill card,
    // muscle map and 3D preview stay usable next to it; at phone width it is a sheet along the bottom)
    function build() {
        if (root) { return; }
        root = document.createElement('aside');
        root.className = 'fc-panel';
        root.id = 'formCheckPanel';
        root.hidden = true;
        root.setAttribute('aria-labelledby', 'fcTitle');
        root.innerHTML =
            '<div class="fc-head"><h2 id="fcTitle">' + ic('camera', 20) + ' Form check</h2>' +
            '<button type="button" class="fc-x" aria-label="Close form check">' + ic('close', 20) + '</button></div>' +
            '<p class="fc-drill"></p>' +
            '<div class="fc-live">' +
            '<div class="fc-stage"><video playsinline muted autoplay aria-hidden="true"></video><canvas aria-hidden="true"></canvas>' +
            '<div class="fc-empty">' + ic('pose', 48) + '<span>Your camera shows here.</span></div>' +
            '<div class="fc-reps" hidden><b>0</b><small>reps</small></div></div>' +
            '<p class="fc-msg" role="status" aria-live="polite"></p>' +
            '<p class="fc-cue" aria-live="assertive"></p>' +
            '<div class="fc-actions"><button type="button" class="btn btn-primary fc-start">Turn on camera</button>' +
            '<button type="button" class="btn btn-primary fc-finish" hidden>Finish set</button>' +
            '<label class="fc-voice"><input type="checkbox"> Speak cues</label></div>' +
            '<p class="fc-tip">Camera 2-3 m away at hip height. Side-on shows depth best; facing it shows your knees.</p>' +
            '</div>' +
            '<div class="fc-result" hidden></div>' +
            '<p class="fc-privacy">' + ic('lock', 14) + ' Video stays on your device. Only measurements are sent.</p>';
        document.body.appendChild(root);
        video = root.querySelector('video');
        video.muted = true;   // a muted video may play without another tap (Safari, Chrome autoplay rules)
        canvas = root.querySelector('canvas');
        ctx2d = canvas.getContext('2d');
        ['drill', 'msg', 'cue', 'start', 'finish', 'reps', 'result', 'live', 'empty', 'x', 'stage'].forEach(function (k) { els[k] = root.querySelector('.fc-' + k); });
        els.voice = root.querySelector('.fc-voice input');
        var v = null;
        try { v = localStorage.getItem(VOICE_KEY); } catch (e) {}
        els.voice.checked = v !== 'off';
        els.voice.addEventListener('change', function () { try { localStorage.setItem(VOICE_KEY, els.voice.checked ? 'on' : 'off'); } catch (e) {} });
        els.x.addEventListener('click', close);
        els.start.addEventListener('click', start);
        els.finish.addEventListener('click', finish);
        els.stage.addEventListener('click', function () { if (stream && video.paused) { video.play().catch(function () {}); } });
        root.addEventListener('keydown', function (e) { if (e.key === 'Escape') { e.preventDefault(); close(); } });
    }
    function open() {
        build();
        lastFocus = document.activeElement;
        drill = currentDrill();
        els.drill.textContent = drill.name ? 'Drill: ' + drill.name : '';
        showLive();
        root.hidden = false;
        document.documentElement.classList.add('fc-open');
        var b = document.getElementById('formCheckBtn');
        if (b) { b.setAttribute('aria-expanded', 'true'); }
        els.start.focus();
        checkPermission();
        loadModel().catch(function () {});   // start downloading while the athlete gets in place
    }
    function close() {
        if (!root || root.hidden) { return; }
        stopCamera();
        reqId++;
        root.hidden = true;
        document.documentElement.classList.remove('fc-open');
        var b = document.getElementById('formCheckBtn');
        if (b) { b.setAttribute('aria-expanded', 'false'); }
        if (lastFocus && lastFocus.focus && document.contains(lastFocus)) { lastFocus.focus(); } else if (b) { b.focus(); }
    }
    function toggle() { if (root && !root.hidden) { close(); } else { open(); } }
    function showLive() {
        els.live.hidden = false;
        els.result.hidden = true;
        els.result.innerHTML = '';
        els.start.hidden = false; els.start.disabled = false; els.start.textContent = 'Turn on camera';
        els.finish.hidden = true;
        els.reps.hidden = true;
        els.empty.hidden = false;
        els.cue.textContent = '';
        msg('Press Turn on camera, then allow the camera when your browser asks.');
        if (ctx2d) { ctx2d.clearRect(0, 0, canvas.width, canvas.height); }
    }
    function msg(t) { if (els.msg.textContent !== t) { els.msg.textContent = t; } }
    var BLOCKED = 'Your browser is blocking the camera for this site. Click the camera or lock icon in the address bar, set Camera to Allow, then press Try again.';
    function checkPermission() {
        try {
            if (navigator.permissions && navigator.permissions.query) {
                navigator.permissions.query({ name: 'camera' }).then(function (p) { if (p.state === 'denied' && !stream) { msg(BLOCKED); } }, function () {});
            }
        } catch (e) {}
    }

    // ------------------------------------------------------------------ camera first, tracker second
    // The camera is asked for straight away on the button press (so the browser shows its permission
    // question) and the picture shows as soon as it is allowed; the movement tracker loads alongside and
    // analysis starts when it is ready. A slow or failed tracker never hides the camera.
    function start() {
        if (!window.isSecureContext) { msg('The camera only works on a secure (https) page.'); return; }
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { msg('This browser cannot use a camera here. Try Chrome, Edge or Safari.'); return; }
        var id = ++camId;
        els.start.disabled = true;
        els.start.textContent = 'Waiting for camera...';
        msg('Allow the camera when your browser asks.');
        loadModel().catch(function () {});
        navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 }, height: { ideal: 480 } }, audio: false }).then(function (s) {
            if (id !== camId || root.hidden) { s.getTracks().forEach(function (t) { t.stop(); }); return; }
            stream = s;
            video.srcObject = s;
            els.empty.hidden = true;
            els.start.hidden = true;
            els.finish.hidden = false;
            els.finish.textContent = 'Stop camera';
            els.finish.focus();
            var p = video.play();
            if (p && p.catch) { p.catch(function () { msg('Tap the camera picture to start it.'); }); }
            if (landmarker) { begin(); return; }
            msg('Camera on. Loading the movement tracker (first time only, about 20 MB)...');
            loadModel().then(function () { if (id === camId && stream) { begin(); } }, function () {
                if (id !== camId || !stream) { return; }
                msg('The movement tracker did not load. Check your connection, then stop the camera and try again.');
            });
        }, function (err) {
            if (id !== camId) { return; }
            els.start.disabled = false;
            els.start.textContent = 'Try again';
            var name = err && err.name;
            if (window.console) { console.warn('Form check: camera error', err); }
            msg(name === 'NotAllowedError' || name === 'SecurityError' || name === 'PermissionDeniedError' ? BLOCKED
                : name === 'NotFoundError' || name === 'DevicesNotFoundError' ? 'No camera found on this device.'
                : name === 'NotReadableError' || name === 'TrackStartError' ? 'Another app is using your camera. Close it, then press Try again.'
                : name === 'OverconstrainedError' ? 'Your camera does not support this mode. Press Try again.'
                : 'The camera did not start (' + (name || 'unknown error') + '). Press Try again.');
        });
    }
    function begin() {
        drill = currentDrill();
        engine = window.CogniFormEngine.create({ drill: drill.name, text: drill.text });
        running = true;
        lastT = 0;
        lastCueText = '';
        els.finish.textContent = 'Finish set';
        els.reps.hidden = false;
        els.reps.querySelector('b').textContent = '0';
        els.reps.querySelector('small').textContent = engine.pattern() === 'plank' || engine.pattern() === 'wallsit' ? 'seconds' : 'reps';
        msg('Step back until your whole body is in the picture.');
        loop();
    }
    function stopCamera() {
        running = false;
        camId++;
        cancelAnimationFrame(raf);
        if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
        if (video) { video.srcObject = null; }
        if (window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch (e) {} }
    }
    function loop() {
        if (!running) { return; }
        raf = requestAnimationFrame(loop);
        var now = performance.now();
        if (now - lastT < 45 || document.hidden || video.readyState < 2) { return; }   // about 20 analysed frames a second
        lastT = now;
        var res;
        try { res = landmarker.detectForVideo(video, now); } catch (e) { return; }
        var lm = res && res.landmarks && res.landmarks[0], wl = res && res.worldLandmarks && res.worldLandmarks[0];
        var aspect = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 4 / 3;
        var out = engine.push({ t: now, lm: lm || null, wl: wl || null, aspect: aspect });
        draw(lm, out);
        msg(out.message);
        els.reps.querySelector('b').textContent = String(out.holdSeconds != null ? out.holdSeconds : out.reps);
        if (out.cue) { cue(out.cue); }
    }
    function cue(c) {
        els.cue.textContent = c.text;
        els.cue.classList.toggle('good', c.id === 'good');
        if (els.voice.checked && window.speechSynthesis && c.text !== lastCueText) {
            try { window.speechSynthesis.cancel(); var u = new SpeechSynthesisUtterance(c.text); u.rate = 1.05; window.speechSynthesis.speak(u); } catch (e) {}
        }
        lastCueText = c.text;
        setTimeout(function () { lastCueText = ''; }, 12000);
    }
    function draw(lm, out) {
        var w = video.videoWidth || 640, h = video.videoHeight || 480;
        if (canvas.width !== w) { canvas.width = w; canvas.height = h; }
        ctx2d.clearRect(0, 0, w, h);
        if (!lm) { return; }
        var col = out.cue && out.cue.id !== 'good' ? '#ff8a34' : '#4ea8ff';
        ctx2d.lineWidth = Math.max(3, w / 160);
        ctx2d.strokeStyle = col;
        ctx2d.lineCap = 'round';
        CONNECT.forEach(function (c) {
            var a = lm[c[0]], b = lm[c[1]];
            if (!a || !b || (a.visibility || 1) < 0.4 || (b.visibility || 1) < 0.4) { return; }
            ctx2d.beginPath(); ctx2d.moveTo(a.x * w, a.y * h); ctx2d.lineTo(b.x * w, b.y * h); ctx2d.stroke();
        });
        ctx2d.fillStyle = '#ffffff';
        [11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28].forEach(function (i) {
            var p = lm[i];
            if (!p || (p.visibility || 1) < 0.4) { return; }
            ctx2d.beginPath(); ctx2d.arc(p.x * w, p.y * h, Math.max(3, w / 140), 0, Math.PI * 2); ctx2d.fill();
        });
    }

    // ------------------------------------------------------------------ results
    function finish() {
        if (!running || !engine) { stopCamera(); showLive(); return; }   // "Stop camera" before the tracker was ready
        report = engine.report();
        engine = null;
        stopCamera();
        els.live.hidden = true;
        els.result.hidden = false;
        renderResult(report, report.fallback, 'rules');
        var heading = els.result.querySelector('h3');
        if (heading) { heading.focus(); }
        var enough = report.reps.length >= 1 || report.holdSeconds >= 3;
        if (enough) {
            remember(report);
            askCoach(report);
        }
    }
    function renderResult(r, fb, source) {
        var isHold = r.holdSeconds != null;
        var stats = [];
        if (isHold) { stats.push('<span><b>' + r.holdSeconds + ' s</b> held</span>'); }
        else { stats.push('<span><b>' + r.reps.length + '</b> rep' + (r.reps.length === 1 ? '' : 's') + '</span>'); }
        if (r.tempo) { stats.push('<span><b>' + r.tempo.rep + ' s</b> per rep</span>'); }
        stats.push('<span>' + esc(r.view) + ' view</span>');
        var faults = r.faults.slice(0, 3).map(function (f) {
            return '<li><b>' + esc(f.cue) + '</b><small>' + esc(f.what) + (f.count != null ? ' · ' + f.count + ' of ' + r.reps.length + ' reps' : ' · ' + Math.round(f.share * 100) + '% of the hold') + '</small></li>';
        }).join('');
        els.result.innerHTML =
            '<div class="fc-score-row">' +
            (r.score != null ? '<div class="fc-score" data-band="' + (r.score >= 85 ? 'high' : r.score >= 65 ? 'mid' : 'low') + '"><b>' + r.score + '</b><small>form</small></div>' : '') +
            '<div><h3 tabindex="-1">' + esc(fb.headline) + '</h3><p class="fc-stats">' + stats.join('') + '</p></div></div>' +
            '<div class="fc-coach" aria-live="polite">' +
            '<div class="fc-coach-label">' + ic('message', 16) + ' Coach says' + (source === 'rules' && (r.reps.length || r.holdSeconds >= 3) ? ' <span class="fc-thinking">writing a note...</span>' : '') + '</div>' +
            (fb.praise ? '<p>' + esc(fb.praise) + '</p>' : '') +
            '<p><b>' + esc(fb.fix) + '</b></p>' +
            (fb.cue ? '<p class="fc-next-cue">Next set, think: <b>' + esc(fb.cue) + '</b></p>' : '') +
            (fb.next ? '<p>' + esc(fb.next) + '</p>' : '') + '</div>' +
            (faults ? '<ul class="fc-faults">' + faults + '</ul>' : '') +
            '<details class="fc-measured"><summary>What the camera measured</summary><p>' + esc(r.summary).replace(/\n/g, '<br>') + '</p>' +
            '<p class="fc-note">Measured from body landmarks, so it can be off. ' + (source === 'ai' ? 'Note written by AI from these numbers only.' : '') + '</p></details>' +
            '<div class="fc-actions"><button type="button" class="btn btn-primary fc-again">Check again</button>' +
            '<button type="button" class="btn btn-secondary fc-done">Done</button></div>';
        els.result.querySelector('.fc-again').addEventListener('click', function () { reqId++; showLive(); start(); });
        els.result.querySelector('.fc-done').addEventListener('click', close);
    }
    function askCoach(r) {
        var id = ++reqId;
        var athlete = '';
        try { athlete = window.CogniCoachProfile ? window.CogniCoachProfile.context(drill.sport) : ''; } catch (e) {}
        var ctrl = window.AbortController ? new AbortController() : null;
        var timer = setTimeout(function () { if (ctrl) { ctrl.abort(); } }, 9500);
        fetch(API + '/form-feedback', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, signal: ctrl ? ctrl.signal : undefined,
            body: JSON.stringify({ drill: drill.name, sport: drill.sport, pattern: r.pattern, summary: r.modelSummary || r.summary, athlete: athlete, cues: drill.cues })
        }).then(function (resp) { return resp.ok ? resp.json() : Promise.reject(resp.status); }).then(function (d) {
            if (id !== reqId || !d || !d.fix) { return; }
            // re-rendering replaces the buttons: keep the keyboard focus where it was
            var a = document.activeElement, inside = a && els.result.contains(a);
            var cls = inside && a.classList.contains('fc-again') ? '.fc-again' : inside && a.classList.contains('fc-done') ? '.fc-done' : inside ? 'h3' : '';
            renderResult(r, { headline: d.headline || r.fallback.headline, praise: d.praise, fix: d.fix, cue: d.cue, next: d.next }, 'ai');
            var back = cls && els.result.querySelector(cls);
            if (back) { back.focus(); }
        }).catch(function () {
            if (id !== reqId) { return; }
            var t = els.result.querySelector('.fc-thinking');
            if (t) { t.remove(); }
        }).then(function () { clearTimeout(timer); });
    }
    // Your coach remembers what the camera found (only the fault names, the score and the movement).
    function remember(r) {
        if (!window.CogniCoachProfile || !window.CogniCoachProfile.recordForm) { return; }
        try {
            window.CogniCoachProfile.recordForm({ sport: drill.sport, drill: drill.name, pattern: r.pattern, view: r.view, score: r.score,
                reps: r.reps.length, faults: r.faults.filter(function (f) { return f.count == null ? f.share >= 0.3 : f.count >= 2; }).map(function (f) { return f.id; }) });
        } catch (e) {}
    }

    // ------------------------------------------------------------------ launch button on the drill card
    function addLaunch() {
        var display = document.querySelector('#drillContent .drill-display');
        if (!display || document.getElementById('formCheckBtn')) { return; }
        var b = document.createElement('button');
        b.type = 'button';
        b.id = 'formCheckBtn';
        b.className = 'form-launch';
        b.setAttribute('aria-controls', 'formCheckPanel');
        b.setAttribute('aria-expanded', 'false');
        b.innerHTML = ic('camera', 18) + '<span>Check my form</span><small>camera, stays on your device</small>';
        b.addEventListener('click', toggle);
        display.insertAdjacentElement('afterend', b);
    }
    document.addEventListener('cognicoach:drill-rendered', addLaunch);
    document.addEventListener('cognicoach:session-end', close);
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', addLaunch); } else { addLaunch(); }

    window.CogniFormCheck = { open: open, close: close, preload: loadModel, lastReport: function () { return report; } };
})();
