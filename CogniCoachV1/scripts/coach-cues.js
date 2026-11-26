// ==========================================================================
// Coach cues on the drill card: 2-3 short things a coach would call out during the drill
// (from the drill backend's "cues"), and when the athlete rates the drill too hard or too easy,
// the easier / harder version of THIS drill straight away (the next drills adapt as before).
// The block sits inside .drill-display, so it moves into Coach Mode with the card, and
// read-aloud reads it after the description. Coach Mode calls out a cue at halfway.
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniCoachCues) { return; }
    function ic(n, s) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: s || 16 }) : ''; }
    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

    function current() {
        try { var s = appState.session; return s.drills[s.currentDrillIndex].generatedDrill || null; } catch (e) { return null; }
    }
    function host() {
        var el = document.getElementById('coachCues');
        if (el) { return el; }
        var desc = document.getElementById('drillDescription');
        if (!desc) { return null; }
        el = document.createElement('div');
        el.id = 'coachCues';
        el.className = 'coach-cues';
        desc.insertAdjacentElement('afterend', el);
        return el;
    }
    function render(d) {
        var el = host();
        if (!el) { return; }
        d = d || current();
        var cues = d && Array.isArray(d.cues) ? d.cues : [];
        if (!cues.length && !(d && (d.easier || d.harder))) { el.hidden = true; el.innerHTML = ''; return; }
        el.hidden = false;
        el.innerHTML =
            (cues.length ? '<div class="cc-label">' + ic('message', 16) + ' Coach cues</div><ul class="cc-list">' +
                cues.map(function (c) { return '<li>' + esc(c) + '</li>'; }).join('') + '</ul>' : '') +
            '<p class="cc-variant" aria-live="polite" hidden></p>';
    }
    function showVariant(fb) {
        var el = document.getElementById('coachCues'), d = current();
        if (!el || !d) { return; }
        var v = el.querySelector('.cc-variant');
        if (!v) { return; }
        var text = fb === 'hard' ? d.easier : fb === 'easy' ? d.harder : '';
        if (!text) { v.hidden = true; v.textContent = ''; return; }
        v.hidden = false;
        v.innerHTML = '<b>' + (fb === 'hard' ? 'Make it easier now:' : 'Make it harder now:') + '</b> ' + esc(text) +
            ' <span class="cc-note">The next drills adjust too.</span>';
    }

    document.addEventListener('cognicoach:drill-rendered', function (e) { render(e.detail && e.detail.drill); });
    document.addEventListener('cognicoach:feedback', function (e) { showVariant(e.detail && e.detail.feedback); });

    window.CogniCoachCues = {
        cues: function () { var d = current(); return d && Array.isArray(d.cues) ? d.cues.slice() : []; },
        render: render
    };
})();
