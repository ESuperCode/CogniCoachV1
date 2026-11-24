// ==========================================================================
// Adaptive coach - the session listens to the athlete.
//
// 1. Readiness check-in on Quick Start: "Low energy / Normal / Fired up" (kept for the day).
// 2. Feedback on every drill: "Too hard / Just right / Too easy".
// Both move an intensity level (-2..+2). Drills that haven't been generated yet ask the
// drill API for that intensity (a short note on the focus field - the backend is unchanged).
// When the athlete says a drill is too hard / too easy, the already-prepared next drill is
// thrown away and prepared again at the new intensity.
// Readiness and feedback are saved with the session in history (dashboard + recap use them).
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniCoachAdapt) { return; }

    var READY_KEY = 'cognicoach-readiness';
    var READINESS = [
        { id: 'low', icon: '🔋', label: 'Low energy', bias: -1, tip: 'Easier drills today - recovery still counts.' },
        { id: 'normal', icon: '🙂', label: 'Normal', bias: 0, tip: 'Standard intensity.' },
        { id: 'high', icon: '⚡', label: 'Fired up', bias: 1, tip: 'Harder drills today - let’s push.' }
    ];
    var FEEDBACK = [
        { id: 'hard', icon: '😮‍💨', label: 'Too hard', delta: -1 },
        { id: 'right', icon: '👍', label: 'Just right', delta: 0 },
        { id: 'easy', icon: '😤', label: 'Too easy', delta: 1 }
    ];
    var NOTES = { '-2': 'recovery pace, low intensity', '-1': 'lower intensity', '1': 'higher intensity', '2': 'maximum challenge' };
    var WORDS = { '-2': 'Recovery pace', '-1': 'Lower intensity', '0': 'Standard intensity', '1': 'Higher intensity', '2': 'Max challenge' };

    function today() { var d = new Date(); return d.getFullYear() + '-' + (d.getMonth() + 1) + '-' + d.getDate(); }

    function readiness() {
        try {
            var r = JSON.parse(localStorage.getItem(READY_KEY) || 'null');
            return r && r.date === today() ? r.id : '';
        } catch (e) { return ''; }
    }
    function setReadiness(id) {
        try { localStorage.setItem(READY_KEY, JSON.stringify({ date: today(), id: id })); } catch (e) {}
    }
    function readinessBias() {
        var id = readiness();
        for (var i = 0; i < READINESS.length; i++) { if (READINESS[i].id === id) { return READINESS[i].bias; } }
        return 0;
    }

    function session() { return (typeof appState !== 'undefined' && appState.session) ? appState.session : null; }

    function intensity() {
        var s = session();
        if (!s) { return 0; }
        if (typeof s.intensity !== 'number') { s.intensity = readinessBias(); s.readiness = readiness() || null; }
        return s.intensity;
    }

    function clamp(n) { return Math.max(-2, Math.min(2, n)); }

    // ------------------------------------------------------------------ API used by script.js
    function adjustRequest(req, drill) {
        var level = intensity();
        if (drill) { drill.intensity = level; }
        var note = NOTES[String(level)];
        if (note) {
            var copy = {};
            Object.keys(req).forEach(function (k) { copy[k] = req[k]; });
            copy.focus = (req.focus || 'General') + ' (' + note + ')';
            return copy;
        }
        return req;
    }

    function sessionSummary() {
        var s = session();
        if (!s) { return {}; }
        var counts = { hard: 0, right: 0, easy: 0 };
        (s.drills || []).forEach(function (d) { if (d.feedback && counts[d.feedback] != null) { counts[d.feedback]++; } });
        var out = { intensity: intensity() };
        if (s.readiness) { out.readiness = s.readiness; }
        if (counts.hard + counts.right + counts.easy) { out.feedback = counts; }
        return out;
    }

    // ------------------------------------------------------------------ readiness check-in
    function buildReadiness() {
        var card = document.getElementById('quickStartCard');
        var startRow = card && document.getElementById('quickStartBtn');
        if (!card || !startRow || document.getElementById('readinessCheck')) { return; }
        var wrap = document.createElement('div');
        wrap.id = 'readinessCheck';
        wrap.className = 'readiness';
        wrap.setAttribute('role', 'group');
        wrap.setAttribute('aria-labelledby', 'readinessLabel');
        wrap.innerHTML = '<div class="readiness-label" id="readinessLabel">How do you feel today? <span>(optional)</span></div>' +
            '<div class="readiness-opts">' + READINESS.map(function (r) {
                return '<button type="button" class="adapt-chip" data-ready="' + r.id + '" aria-pressed="false">' +
                    '<span class="adapt-icon" aria-hidden="true">' + r.icon + '</span>' + r.label + '</button>';
            }).join('') + '</div><p class="readiness-tip" aria-live="polite"></p>';
        var holder = startRow.closest('.text-center') || startRow.parentNode;
        holder.parentNode.insertBefore(wrap, holder);
        wrap.addEventListener('click', function (e) {
            var b = e.target.closest('[data-ready]');
            if (!b) { return; }
            var id = b.getAttribute('aria-pressed') === 'true' ? '' : b.dataset.ready;
            setReadiness(id);
            paintReadiness();
        });
        paintReadiness();
    }

    function paintReadiness() {
        var wrap = document.getElementById('readinessCheck');
        if (!wrap) { return; }
        var id = readiness();
        wrap.querySelectorAll('[data-ready]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.ready === id ? 'true' : 'false'); });
        var r = READINESS.filter(function (x) { return x.id === id; })[0];
        wrap.querySelector('.readiness-tip').textContent = r ? r.tip : '';
    }

    // ------------------------------------------------------------------ per-drill feedback
    var fb;
    function buildFeedback() {
        if (fb || !document.querySelector('.timer-container')) { return; }
        fb = document.createElement('div');
        fb.className = 'adapt-feedback';
        fb.setAttribute('role', 'group');
        fb.setAttribute('aria-labelledby', 'adaptFbLabel');
        fb.innerHTML = '<div class="adapt-fb-label" id="adaptFbLabel">How is this drill feeling?</div>' +
            '<div class="adapt-fb-opts">' + FEEDBACK.map(function (f) {
                return '<button type="button" class="adapt-chip" data-fb="' + f.id + '" aria-pressed="false">' +
                    '<span class="adapt-icon" aria-hidden="true">' + f.icon + '</span>' + f.label + '</button>';
            }).join('') + '</div>' +
            '<p class="adapt-status" aria-live="polite"></p>';
        var timer = document.querySelector('.timer-container');
        timer.insertAdjacentElement('afterend', fb);
        fb.addEventListener('click', function (e) {
            var b = e.target.closest('[data-fb]');
            if (b) { giveFeedback(b.dataset.fb); }
        });
    }

    function giveFeedback(id) {
        var s = session();
        if (!s || !s.drills || !s.drills[s.currentDrillIndex]) { return; }
        var d = s.drills[s.currentDrillIndex];
        var before = intensity();
        var prev = d.feedback;
        // undo this drill's earlier answer before applying the new one
        var delta = function (fid) { var f = FEEDBACK.filter(function (x) { return x.id === fid; })[0]; return f ? f.delta : 0; };
        if (prev === id) { s.intensity = clamp(before - delta(prev)); d.feedback = null; }
        else { s.intensity = clamp(before - delta(prev) + delta(id)); d.feedback = id; }
        if (typeof saveState === 'function') { saveState(); }
        if (s.intensity !== before && typeof refreshUpcomingDrill === 'function') { refreshUpcomingDrill(); }
        paintFeedback(s.intensity !== before);
        document.dispatchEvent(new CustomEvent('cognicoach:feedback', { detail: { feedback: d.feedback, intensity: s.intensity } }));
    }

    function paintFeedback(changed) {
        if (!fb) { return; }
        var s = session();
        var d = s && s.drills && s.drills[s.currentDrillIndex];
        var cur = d && d.feedback;
        fb.querySelectorAll('[data-fb]').forEach(function (b) { b.setAttribute('aria-pressed', b.dataset.fb === cur ? 'true' : 'false'); });
        var level = intensity();
        var hasNext = s && s.drills && s.currentDrillIndex < s.drills.length - 1;
        var status = fb.querySelector('.adapt-status');
        status.textContent = hasNext && (changed || level !== 0)
            ? (changed ? 'Got it - ' : 'Coach setting: ') + WORDS[String(level)].toLowerCase() + ' for your next drills.'
            : (cur ? 'Thanks - noted for your stats.' : '');
        status.dataset.level = String(level);
    }

    // ------------------------------------------------------------------ boot
    // The drill API may echo the intensity note back in its focus - show it as a badge instead.
    var NOTE_RE = /\s*\((recovery pace, low intensity|lower intensity|higher intensity|maximum challenge)\)/ig;
    function paintBadge() {
        var focus = document.getElementById('drillFocus');
        if (!focus) { return; }
        if (NOTE_RE.test(focus.textContent)) { focus.textContent = focus.textContent.replace(NOTE_RE, ''); }
        NOTE_RE.lastIndex = 0;
        var badge = document.getElementById('adaptBadge');
        if (!badge) {
            badge = document.createElement('span');
            badge.id = 'adaptBadge';
            badge.className = 'adapt-badge';
            focus.insertAdjacentElement('afterend', badge);
        }
        var s = session(), d = s && s.drills && s.drills[s.currentDrillIndex];
        var level = d && typeof d.intensity === 'number' ? d.intensity : 0;
        badge.hidden = !level;
        badge.dataset.level = String(level);
        badge.textContent = level ? (level > 0 ? '\u26A1 ' : '\uD83C\uDF3F ') + WORDS[String(level)] : '';
        badge.title = 'Set by the adaptive coach from your check-in and drill ratings';
    }
    document.addEventListener('cognicoach:drill-rendered', function () { buildFeedback(); paintFeedback(false); paintBadge(); });
    document.addEventListener('cognicoach:session-end', function () {
        var wrap = document.getElementById('readinessCheck');
        if (wrap) { paintReadiness(); }
    });

    function boot() { buildReadiness(); }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }

    window.CogniCoachAdapt = {
        adjustRequest: adjustRequest,
        sessionSummary: sessionSummary,
        intensity: intensity,
        intensityWord: function (n) { return WORDS[String(n == null ? intensity() : n)]; },
        feedback: giveFeedback,
        FEEDBACK: FEEDBACK
    };
})();
