// ==========================================================================
// Coach Mode - a hands-free, full-screen workout. CogniCoach does the coaching,
// the athlete just trains:
//   - a big 3D ring timer you can read from across the gym
//   - hands-free flow: reads the drill, counts you in (3-2-1 beeps), runs it,
//     calls halfway / 10 seconds / time, rests, then moves to the next drill
//   - voice control (where the browser supports it): "pause", "go", "next",
//     "skip", "read", "too easy", "too hard", "just right", "exit"
//   - keeps the screen awake (Wake Lock) while it is open
// The drill card itself (title, focus, description, read-aloud bar) and the
// feedback chips are moved into the overlay while it is open, so everything
// else keeps working through the normal session functions in script.js.
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniCoachMode) { return; }

    var KEY = 'cognicoach-coach-mode';
    var opts = { handsFree: true, rest: 15, beeps: true, voice: false };
    try { var saved = JSON.parse(localStorage.getItem(KEY) || '{}'); Object.keys(opts).forEach(function (k) { if (k in saved) { opts[k] = saved[k]; } }); } catch (e) {}
    function saveOpts() { try { localStorage.setItem(KEY, JSON.stringify(opts)); } catch (e) {} }

    var root, ring, ringFg, digits, phaseEl, metaEl, upNextEl, mainBtn, nextBtn, skipBtn, readBtn, micBtn, micText, slot, slotFb;
    var isOpen = false, phase = 'idle', countdownTimer = 0, restLeft = 0, restTotal = 0, restPaused = false;
    var audio = null, wakeLock = null, rec = null, recOn = false, lastFocus = null;
    var homes = [];   // [{ node, placeholder }] for the moved drill card pieces
    var cue = {};

    var CIRC = 2 * Math.PI * 88;

    function $(id) { return document.getElementById(id); }
    function S() { return (typeof appState !== 'undefined' && appState.session) ? appState.session : null; }
    function RA() { return window.CogniReadAloud && window.CogniReadAloud.supported ? window.CogniReadAloud : null; }
    function fmt(sec) { sec = Math.max(0, Math.round(sec)); return String(Math.floor(sec / 60)).padStart(2, '0') + ':' + String(sec % 60).padStart(2, '0'); }

    // ------------------------------------------------------------------ sound
    function beep(freq, ms, vol) {
        if (!opts.beeps) { return; }
        try {
            if (!audio) { audio = new (window.AudioContext || window.webkitAudioContext)(); }
            if (audio.state === 'suspended') { audio.resume(); }
            var o = audio.createOscillator(), g = audio.createGain(), t = audio.currentTime;
            o.type = 'sine'; o.frequency.value = freq || 880;
            g.gain.setValueAtTime(0.0001, t);
            g.gain.exponentialRampToValueAtTime(vol || 0.25, t + 0.015);
            g.gain.exponentialRampToValueAtTime(0.0001, t + (ms || 160) / 1000);
            o.connect(g); g.connect(audio.destination);
            o.start(t); o.stop(t + (ms || 160) / 1000 + 0.05);
        } catch (e) {}
    }
    function speak(text, interrupt) { var ra = RA(); if (ra) { ra.say(text, interrupt); } }
    // read-aloud's own timer cues already speak when that setting is on - don't double up
    function cuesByReadAloud() { return !!(window.CogniA11y && window.CogniA11y.prefs.timerCues); }

    // ------------------------------------------------------------------ wake lock
    function lockScreen() {
        if (!('wakeLock' in navigator) || wakeLock) { return; }
        navigator.wakeLock.request('screen').then(function (l) {
            wakeLock = l;
            l.addEventListener('release', function () { wakeLock = null; });
        }).catch(function () {});
    }
    document.addEventListener('visibilitychange', function () { if (isOpen && document.visibilityState === 'visible') { lockScreen(); } });

    // ------------------------------------------------------------------ building
    function build() {
        root = document.createElement('div');
        root.id = 'coachMode';
        root.className = 'coach-mode';
        root.setAttribute('role', 'dialog');
        root.setAttribute('aria-modal', 'true');
        root.setAttribute('aria-label', 'Coach Mode');
        root.hidden = true;
        root.innerHTML =
            '<div class="cm-floor" aria-hidden="true"></div>' +
            '<div class="cm-top">' +
            '  <div class="cm-brand"><span class="cm-dot" aria-hidden="true"></span>Coach Mode <span class="cm-meta"></span></div>' +
            '  <div class="cm-top-actions">' +
            '    <label class="cm-toggle"><input type="checkbox" class="cm-hf"> Hands-free</label>' +
            '    <button type="button" class="cm-icon cm-mic" aria-pressed="false" title="Voice control"><span aria-hidden="true">🎙️</span><span class="a11y-sr-only">Voice control</span></button>' +
            '    <button type="button" class="cm-icon cm-settings" aria-expanded="false" title="Coach Mode settings"><span aria-hidden="true">⚙️</span><span class="a11y-sr-only">Coach Mode settings</span></button>' +
            '    <button type="button" class="cm-icon cm-exit" title="Exit Coach Mode (Esc)"><span aria-hidden="true">✕</span><span class="a11y-sr-only">Exit Coach Mode</span></button>' +
            '  </div>' +
            '</div>' +
            '<div class="cm-settings-panel" hidden>' +
            '  <label>Rest between drills <select class="cm-rest">' + [0, 10, 15, 20, 30, 45, 60].map(function (n) { return '<option value="' + n + '">' + (n ? n + ' s' : 'None') + '</option>'; }).join('') + '</select></label>' +
            '  <label class="cm-toggle"><input type="checkbox" class="cm-beeps"> Countdown beeps</label>' +
            '</div>' +
            '<div class="cm-body">' +
            '  <div class="cm-stage">' +
            '    <div class="cm-ring-wrap">' +
            '      <svg class="cm-ring" viewBox="0 0 200 200" aria-hidden="true">' +
            '        <defs><linearGradient id="cmGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4ea8ff"/><stop offset="1" stop-color="#ff8a34"/></linearGradient></defs>' +
            '        <circle class="cm-ring-ticks" cx="100" cy="100" r="96"/>' +
            '        <circle class="cm-ring-bg" cx="100" cy="100" r="88"/>' +
            '        <circle class="cm-ring-fg" cx="100" cy="100" r="88" transform="rotate(-90 100 100)"/>' +
            '      </svg>' +
            '      <div class="cm-center"><div class="cm-phase">Ready</div><div class="cm-digits" role="timer">00:00</div><div class="cm-upnext"></div></div>' +
            '    </div>' +
            '    <div class="cm-controls">' +
            '      <button type="button" class="cm-btn cm-read"><span aria-hidden="true">🔊</span> Read</button>' +
            '      <button type="button" class="cm-btn cm-main">Start</button>' +
            '      <button type="button" class="cm-btn cm-skip"><span aria-hidden="true">⏭</span> Skip</button>' +
            '    </div>' +
            '    <button type="button" class="cm-btn cm-next" hidden>Next drill →</button>' +
            '    <p class="cm-mic-text" aria-live="polite"></p>' +
            '  </div>' +
            '  <div class="cm-card"><div class="cm-slot"></div><div class="cm-slot-fb"></div></div>' +
            '</div>' +
            '<p class="cm-live a11y-sr-only" aria-live="assertive"></p>';
        document.body.appendChild(root);

        ring = root.querySelector('.cm-ring-wrap');
        ringFg = root.querySelector('.cm-ring-fg');
        ringFg.style.strokeDasharray = CIRC;
        ringFg.style.strokeDashoffset = CIRC;
        digits = root.querySelector('.cm-digits');
        phaseEl = root.querySelector('.cm-phase');
        metaEl = root.querySelector('.cm-meta');
        upNextEl = root.querySelector('.cm-upnext');
        mainBtn = root.querySelector('.cm-main');
        nextBtn = root.querySelector('.cm-next');
        skipBtn = root.querySelector('.cm-skip');
        readBtn = root.querySelector('.cm-read');
        micBtn = root.querySelector('.cm-mic');
        micText = root.querySelector('.cm-mic-text');
        slot = root.querySelector('.cm-slot');
        slotFb = root.querySelector('.cm-slot-fb');

        var hf = root.querySelector('.cm-hf');
        hf.checked = opts.handsFree;
        hf.addEventListener('change', function () {
            opts.handsFree = hf.checked; saveOpts();
            if (opts.handsFree && phase === 'loaded') { intro(); }
            if (!opts.handsFree) { cancelCountdown(); if (phase === 'ready' || phase === 'intro') { setPhase('loaded'); } }
        });
        var rest = root.querySelector('.cm-rest');
        rest.value = String(opts.rest);
        rest.addEventListener('change', function () { opts.rest = Number(rest.value); saveOpts(); });
        var beeps = root.querySelector('.cm-beeps');
        beeps.checked = opts.beeps;
        beeps.addEventListener('change', function () { opts.beeps = beeps.checked; saveOpts(); });
        var setBtn = root.querySelector('.cm-settings'), setPanel = root.querySelector('.cm-settings-panel');
        setBtn.addEventListener('click', function () {
            setPanel.hidden = !setPanel.hidden;
            setBtn.setAttribute('aria-expanded', setPanel.hidden ? 'false' : 'true');
        });

        root.querySelector('.cm-exit').addEventListener('click', close);
        mainBtn.addEventListener('click', mainAction);
        nextBtn.addEventListener('click', goNext);
        skipBtn.addEventListener('click', skip);
        readBtn.addEventListener('click', function () { var ra = RA(); if (ra) { cancelCountdown(); ra.toggle(); } });
        if (!RA()) { readBtn.hidden = true; }
        micBtn.addEventListener('click', function () { setVoice(!recOn); });
        if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) { micBtn.hidden = true; }

        root.addEventListener('keydown', onKey);
    }

    function addLaunchButton() {
        var display = document.querySelector('#drillContent .drill-display');
        if (!display || document.getElementById('coachModeBtn')) { return; }
        var b = document.createElement('button');
        b.type = 'button';
        b.id = 'coachModeBtn';
        b.className = 'coach-launch';
        b.innerHTML = '<span class="coach-launch-icon" aria-hidden="true">▶</span><span><b>Coach Mode</b><small>Hands-free, full screen</small></span>';
        b.addEventListener('click', open);
        display.parentNode.insertBefore(b, display);
    }

    // ------------------------------------------------------------------ open / close
    function moveIn(node, into) {
        if (!node) { return; }
        var ph = document.createComment('coach-mode');
        node.parentNode.insertBefore(ph, node);
        into.appendChild(node);
        homes.push({ node: node, placeholder: ph });
    }
    function moveBack() {
        homes.forEach(function (h) { if (h.placeholder.parentNode) { h.placeholder.parentNode.insertBefore(h.node, h.placeholder); h.placeholder.remove(); } });
        homes = [];
    }

    function open() {
        if (isOpen) { return; }
        if (!root) { build(); }
        lastFocus = document.activeElement;
        moveIn(document.querySelector('#drillContent .drill-display'), slot);
        moveIn(document.querySelector('.adapt-feedback'), slotFb);
        root.hidden = false;
        isOpen = true;
        document.querySelectorAll('main, site-nav, .session-dock').forEach(function (el) { el.inert = true; });
        document.documentElement.classList.add('coach-on');
        try { if (!audio) { audio = new (window.AudioContext || window.webkitAudioContext)(); } } catch (e) {}
        lockScreen();
        if (root.requestFullscreen && window.matchMedia('(pointer: coarse)').matches) { root.requestFullscreen().catch(function () {}); }
        cue = {};
        syncFromSession(true);
        mainBtn.focus();
        if (opts.voice) { setVoice(true); }
    }

    function close() {
        if (!isOpen) { return; }
        cancelCountdown();
        stopRest();
        setVoice(false, true);
        var ra = RA(); if (ra) { ra.stop(); }
        moveBack();
        document.querySelectorAll('main, site-nav, .session-dock').forEach(function (el) { el.inert = false; });
        root.hidden = true;
        isOpen = false;
        phase = 'idle';
        document.documentElement.classList.remove('coach-on');
        if (wakeLock) { try { wakeLock.release(); } catch (e) {} wakeLock = null; }
        if (document.fullscreenElement === root && document.exitFullscreen) { document.exitFullscreen().catch(function () {}); }
        if (lastFocus && lastFocus.focus) { try { lastFocus.focus(); } catch (e) {} }
    }

    // ------------------------------------------------------------------ state
    function setPhase(p, label) {
        phase = p;
        root.dataset.phase = p;
        var words = { loading: 'Preparing', loaded: 'Ready', intro: 'Listen up', ready: 'Get ready', work: 'Go', paused: 'Paused', done: 'Time', rest: 'Rest', finished: 'Done' };
        phaseEl.textContent = label || words[p] || '';
        var s = S();
        var running = s && s.timerStarted && !s.isPaused;
        mainBtn.textContent = p === 'rest' ? (restPaused ? 'Resume rest' : 'Skip rest')
            : p === 'loading' ? 'Loading…'
            : (s && s.timerStarted) ? (s.isPaused ? 'Resume' : 'Pause')
            : p === 'done' ? 'Next drill' : 'Start';
        mainBtn.disabled = p === 'loading';
        mainBtn.classList.toggle('cm-go', !running && p !== 'rest' && p !== 'loading');
        nextBtn.hidden = !(p === 'rest');
        skipBtn.disabled = p === 'loading' || p === 'done' || p === 'rest';
        var hasNext = s && s.drills && s.currentDrillIndex < s.drills.length - 1;
        if (p === 'done' && !hasNext) { mainBtn.textContent = 'Finish session'; }
    }

    function setRing(fraction) {
        ringFg.style.strokeDashoffset = String(CIRC * (1 - Math.max(0, Math.min(1, fraction))));
    }

    function syncFromSession(fresh) {
        var s = S();
        if (!s) { return; }
        var loading = $('loadingContainer') && $('loadingContainer').classList.contains('active');
        metaEl.textContent = s.drills && s.drills.length ? '· Drill ' + (s.currentDrillIndex + 1) + ' of ' + s.drills.length : '';
        if (loading) { setPhase('loading'); digits.textContent = '--:--'; setRing(0); upNextEl.textContent = ''; return; }
        digits.textContent = fmt(s.timeRemaining);
        setRing(s.totalTime ? 1 - s.timeRemaining / s.totalTime : 0);
        upNextEl.textContent = '';
        if (s.timerStarted) { setPhase(s.isPaused ? 'paused' : 'work'); }
        else if (s.totalTime && s.timeRemaining <= 0) { setPhase('done'); }
        else if (fresh && opts.handsFree) { intro(); }
        else if (phase !== 'intro' && phase !== 'ready') { setPhase('loaded'); }
    }

    // read the drill, then count in, then start
    function intro() {
        cancelCountdown();
        var ra = RA();
        if (ra) {
            setPhase('intro');
            ra.start();
            // read-aloud fires cognicoach:read-aloud {state:'idle'} when done -> countIn()
        } else {
            countIn();
        }
    }

    function countIn() {
        cancelCountdown();
        var n = 5;
        setPhase('ready');
        digits.textContent = String(n);
        if (!cuesByReadAloud()) { speak('Get ready.', false); }
        countdownTimer = setInterval(function () {
            n--;
            if (n <= 0) {
                cancelCountdown();
                beep(1320, 380, 0.3);
                if (typeof startTimer === 'function') { startTimer(); }
                return;
            }
            digits.textContent = String(n);
            if (n <= 3) { beep(880, 150); }
        }, 1000);
    }
    function cancelCountdown() { if (countdownTimer) { clearInterval(countdownTimer); countdownTimer = 0; } }

    function startRest() {
        stopRest();
        var s = S();
        var hasNext = s && s.drills && s.currentDrillIndex < s.drills.length - 1;
        if (!hasNext) { setPhase('done'); return; }
        var next = s.drills[s.currentDrillIndex + 1];
        var name = next.generatedDrill && typeof next.generatedDrill === 'object' ? next.generatedDrill.name : '';
        if (!opts.rest) { goNext(); return; }
        restTotal = restLeft = opts.rest;
        restPaused = false;
        setPhase('rest');
        upNextEl.textContent = name ? 'Up next: ' + name : 'Up next: drill ' + (s.currentDrillIndex + 2);
        digits.textContent = fmt(restLeft);
        setRing(0);
        speak('Rest. ' + (name ? 'Up next, ' + name + '.' : ''), false);
        countdownTimer = setInterval(function () {
            if (restPaused) { return; }
            restLeft--;
            digits.textContent = fmt(restLeft);
            setRing(1 - restLeft / restTotal);
            if (restLeft > 0 && restLeft <= 3) { beep(660, 120); }
            if (restLeft <= 0) { stopRest(); goNext(); }
        }, 1000);
    }
    function stopRest() { cancelCountdown(); }

    // ------------------------------------------------------------------ actions
    function mainAction() {
        var s = S();
        if (!s) { return; }
        if (phase === 'rest') { stopRest(); goNext(); return; }
        if (phase === 'done') { goNext(); return; }
        if (s.timerStarted) { if (typeof togglePause === 'function') { togglePause(); } return; }
        cancelCountdown();
        phase = 'starting';   // so stopping the reading below doesn't trigger the count-in
        var ra = RA(); if (ra && ra.isSpeaking()) { ra.stop(); }
        beep(1320, 300, 0.3);
        if (typeof startTimer === 'function') { startTimer(); }
    }
    function goNext() {
        stopRest();
        var ra = RA(); if (ra) { ra.stop(); }
        if (typeof nextDrill === 'function') { nextDrill(); }
    }
    function skip() {
        var s = S();
        if (!s || phase === 'loading') { return; }
        cancelCountdown();
        if (typeof skipToEnd === 'function') { skipToEnd(); }
    }

    function onKey(e) {
        if (e.target && /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) { return; }
        if (e.key === 'Escape') { e.preventDefault(); close(); }
        else if (e.key === ' ' && !(e.target.closest && e.target.closest('button, a, label'))) { e.preventDefault(); mainAction(); }
        else if (e.key === 'n' || e.key === 'N') { if (phase === 'rest' || phase === 'done') { goNext(); } }
        else if (e.key === 'r' || e.key === 'R') { if (!e.altKey) { var ra = RA(); if (ra) { ra.toggle(); } } }
    }

    // ------------------------------------------------------------------ voice control
    function setVoice(on, keepPref) {
        var SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) { return; }
        if (!keepPref) { opts.voice = on; saveOpts(); }
        recOn = on;
        if (micBtn) { micBtn.setAttribute('aria-pressed', on ? 'true' : 'false'); micBtn.classList.toggle('on', on); }
        if (!on) { if (rec) { try { rec.abort(); } catch (e) {} } rec = null; if (micText) { micText.textContent = ''; } return; }
        if (rec) { return; }
        rec = new SR();
        rec.lang = document.documentElement.lang || 'en-US';
        rec.continuous = true;
        rec.interimResults = false;
        rec.onresult = function (ev) {
            var r = ev.results[ev.results.length - 1];
            if (!r || !r.isFinal) { return; }
            var ra = RA();
            if (ra && ra.busy()) { return; }   // ignore our own voice
            command(String(r[0].transcript || '').toLowerCase().trim());
        };
        rec.onerror = function (ev) {
            if (ev.error === 'not-allowed' || ev.error === 'service-not-allowed') {
                micText.textContent = 'Microphone blocked - voice control is off.';
                setVoice(false);
            }
        };
        rec.onend = function () { if (recOn && isOpen) { try { rec.start(); } catch (e) {} } else { rec = null; } };
        try { rec.start(); micText.textContent = 'Listening: say “pause”, “go”, “next”, “too easy”…'; } catch (e) {}
    }

    function command(t) {
        var s = S();
        var said = function (msg) { micText.textContent = '“' + t + '” → ' + msg; };
        var has = function (re) { return re.test(t); };
        if (has(/too (easy|light)/)) { said('noted, harder next'); if (window.CogniCoachAdapt) { window.CogniCoachAdapt.feedback('easy'); } }
        else if (has(/too (hard|tough|much)/)) { said('noted, easier next'); if (window.CogniCoachAdapt) { window.CogniCoachAdapt.feedback('hard'); } }
        else if (has(/just right|perfect|good one/)) { said('noted'); if (window.CogniCoachAdapt) { window.CogniCoachAdapt.feedback('right'); } }
        else if (has(/\b(pause|stop|hold|wait)\b/)) { said('pause'); if (s && s.timerStarted && !s.isPaused) { togglePause(); } else if (phase === 'rest') { restPaused = true; setPhase('rest'); } else { cancelCountdown(); } }
        else if (has(/\b(go|start|resume|continue)\b/)) { said('go'); if (phase === 'rest') { restPaused = false; setPhase('rest'); } else if (s && s.timerStarted && s.isPaused) { togglePause(); } else if (!s.timerStarted && phase !== 'done') { mainAction(); } }
        else if (has(/\b(next|done)\b/)) { said('next'); if (phase === 'rest' || phase === 'done') { goNext(); } }
        else if (has(/\bskip\b/)) { said('skip'); skip(); }
        else if (has(/\b(read|repeat|again)\b/)) { said('reading'); var ra = RA(); if (ra) { ra.start(); } }
        else if (has(/\b(exit|close|quit)\b/)) { said('exit'); close(); }
    }

    // ------------------------------------------------------------------ session events
    document.addEventListener('cognicoach:drill-loading', function () {
        if (!isOpen) { return; }
        cue = {};
        stopRest();
        setPhase('loading');
        digits.textContent = '--:--';
        setRing(0);
        metaEl.textContent = '· Drill ' + (S().currentDrillIndex + 1) + ' of ' + S().drills.length;
        upNextEl.textContent = 'Coach is preparing your next drill…';
    });
    document.addEventListener('cognicoach:drill-rendered', function () {
        addLaunchButton();
        if (!isOpen) { return; }
        // the card's feedback chips may have just been created
        if (!slotFb.firstChild) { moveIn(document.querySelector('.adapt-feedback'), slotFb); }
        syncFromSession(true);
    });
    document.addEventListener('cognicoach:read-aloud', function (e) {
        if (!isOpen) { return; }
        root.classList.toggle('cm-reading', e.detail.state !== 'idle');
        if (e.detail.state === 'idle' && phase === 'intro' && opts.handsFree) { countIn(); }
    });
    document.addEventListener('cognicoach:timer', function (e) {
        if (!isOpen) { return; }
        var d = e.detail || {};
        digits.textContent = fmt(d.remaining);
        setRing(d.total ? 1 - d.remaining / d.total : 0);
        if (d.state === 'running') { setPhase('work'); }
        else if (d.state === 'paused') { setPhase('paused'); }
        else if (d.state === 'tick') {
            if (phase !== 'work') { setPhase('work'); }
            if (d.remaining > 0 && d.remaining <= 3) { beep(880, 150); }
            if (!cuesByReadAloud()) {
                if (d.total >= 60 && !cue.half && d.remaining === Math.floor(d.total / 2)) { cue.half = true; speak('Halfway.', true); }
                if (d.total > 20 && !cue.ten && d.remaining === 10) { cue.ten = true; speak('10 seconds.', true); }
            }
        } else if (d.state === 'complete') {
            beep(1320, 500, 0.32);
            if (!cuesByReadAloud()) { speak('Time!', true); }
            root.querySelector('.cm-live').textContent = 'Drill complete';
            if (opts.handsFree) { setTimeout(function () { if (isOpen && phase !== 'loading') { startRest(); } }, 1200); }
            else { setPhase('done'); }
        }
    });
    document.addEventListener('cognicoach:session-end', function () { if (isOpen) { close(); } });

    function boot() { addLaunchButton(); }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }

    window.CogniCoachMode = { open: open, close: close, isOpen: function () { return isOpen; } };
})();
