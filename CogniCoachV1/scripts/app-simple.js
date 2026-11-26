// ==========================================================================
// Simpler app page (index.html):
//   - "How long?" as one-tap chips (20/30/45/60/90, Other opens the slider)
//   - where / what-to-work-on folded into a one-line summary with an Edit toggle
//   - the muscle list on the drill card folded behind an Edit toggle
// The real fields (#workoutLength, #location, #focus, the muscle checkboxes) stay in the page,
// so script.js, profile.js and the tour read and fill them exactly as before.
// ==========================================================================
(function () {
    'use strict';
    function $(id) { return document.getElementById(id); }

    // ------------------------------------------------------------------ length chips
    function paintLength() {
        var slider = $('workoutLength'), chips = $('qsLengthChips'), custom = $('qsCustomLength');
        if (!slider || !chips) { return; }
        var v = String(slider.value), matched = false;
        chips.querySelectorAll('[data-len]').forEach(function (b) {
            if (b.dataset.len === 'custom') { return; }
            var on = b.dataset.len === v;
            if (on) { matched = true; }
            b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        var other = chips.querySelector('[data-len="custom"]');
        var open = !custom.hidden;
        if (!matched) { custom.hidden = false; open = true; }
        other.setAttribute('aria-pressed', !matched ? 'true' : 'false');
        other.setAttribute('aria-expanded', open ? 'true' : 'false');
        other.textContent = matched ? 'Other' : 'Other: ' + v + ' min';
    }
    function wireLength() {
        var slider = $('workoutLength'), chips = $('qsLengthChips'), custom = $('qsCustomLength');
        if (!slider || !chips) { return; }
        chips.addEventListener('click', function (e) {
            var b = e.target.closest('[data-len]');
            if (!b) { return; }
            if (b.dataset.len === 'custom') {
                custom.hidden = !custom.hidden;
                paintLength();
                if (!custom.hidden) { slider.focus(); }
                return;
            }
            slider.value = b.dataset.len;
            slider.dispatchEvent(new Event('input', { bubbles: true }));   // updates the label and marks it edited
            custom.hidden = true;
            paintLength();
        });
        slider.addEventListener('input', paintLength);
        slider.addEventListener('change', paintLength);
    }

    // ------------------------------------------------------------------ where / what summary
    function paintDetails() {
        var out = $('qsDetailsSummary');
        if (!out) { return; }
        var loc = ($('location') || {}).value || '', focus = ($('focus') || {}).value || '';
        loc = loc.trim(); focus = focus.trim();
        var where = loc && !/^any(where)?$/i.test(loc) ? loc : 'Anywhere';
        var what = focus && !/^general$/i.test(focus) ? focus : 'All-round training';
        out.innerHTML = '';
        [['Where', where], ['Working on', what]].forEach(function (pair, i) {
            if (i) { out.appendChild(document.createTextNode(' · ')); }
            var s = document.createElement('span');
            s.className = 'qs-sum-k';
            s.textContent = pair[0] + ': ';
            var b = document.createElement('b');
            b.textContent = pair[1];
            out.appendChild(s);
            out.appendChild(b);
        });
    }
    function wireDetails() {
        var btn = $('qsDetailsBtn'), panel = $('qsDetailsPanel');
        if (!btn || !panel) { return; }
        btn.addEventListener('click', function () {
            var open = panel.hidden;
            panel.hidden = !open;
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            btn.textContent = open ? 'Done' : 'Edit';
            if (open) { var l = $('location'); if (l) { l.focus(); } }
            paintDetails();
        });
        ['location', 'focus'].forEach(function (id) {
            var el = $(id);
            if (el) { el.addEventListener('input', paintDetails); }
        });
    }

    // ------------------------------------------------------------------ muscle list toggle
    function wireMuscles() {
        var btn = $('muscleEditBtn'), list = $('muscleList');
        if (!btn || !list) { return; }
        btn.addEventListener('click', function () {
            var open = list.hidden;
            list.hidden = !open;
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            btn.textContent = open ? 'Done' : 'Edit';
        });
    }

    // profile.js / script.js fill the fields without firing events: repaint after they do.
    function wrap(name) {
        var orig = window[name];
        if (typeof orig !== 'function' || orig.__simple) { return; }
        var w = function () { var r = orig.apply(this, arguments); paintLength(); paintDetails(); return r; };
        w.__simple = true;
        window[name] = w;
    }

    function init() {
        if (!$('quickStartCard')) { return; }
        wireLength();
        wireDetails();
        wireMuscles();
        ['updateSliderValue', 'prefillQuickStartFields', 'refreshQuickStartUI', 'returnToSetup'].forEach(wrap);
        paintLength();
        paintDetails();
        setTimeout(function () { paintLength(); paintDetails(); }, 400);   // after saved-state restore
    }
    window.CogniAppSimple = { repaint: function () { paintLength(); paintDetails(); } };
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
