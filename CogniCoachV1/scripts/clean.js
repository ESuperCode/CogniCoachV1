// ==========================================================================
// Training page layout (html.clean; ?classic=1 shows the old layout). The drill, the timer, then one
// row of tools (Listen, Hands-free, 3D demo, Muscles, Form check) instead of a long page; the muscle
// map and the 3D preview open on demand, the "why this drill" part folds away, and the rating chips
// appear once the drill is running. The session timeline stays on top.
//
// It only moves and hides the existing elements and presses the existing buttons, so the session
// logic (script.js), Your coach, Coach Mode, Form check and the rest work unchanged.
// ==========================================================================
(function () {
    'use strict';
    var H = document.documentElement;
    if (!H.classList.contains('clean') || window.CogniClean) { return; }

    function $(id) { return document.getElementById(id); }
    function ic(n, s) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: s || 22 }) : ''; }

    // ================================================================== SESSION
    var tools = null;
    function buildSession() {
        var card = document.querySelector('#drillContent > .card');
        var timer = document.querySelector('#drillContent .timer-container');
        if (!card || !timer || tools) { return; }
        // one row of tools under the timer
        tools = document.createElement('div');
        tools.className = 'clean-tools';
        tools.setAttribute('role', 'group');
        tools.setAttribute('aria-label', 'Drill tools');
        var T = [
            { k: 'listen', icon: 'volume', label: 'Listen', pressed: true },
            { k: 'handsfree', icon: 'play', label: 'Hands-free' },
            { k: '3d', icon: 'cube', label: '3D demo', controls: 'motionViewer' },
            { k: 'muscles', icon: 'target', label: 'Muscles', controls: 'cleanMuscles' },
            { k: 'form', icon: 'camera', label: 'Form check', controls: 'formCheckPanel' }
        ];
        tools.innerHTML = T.map(function (t) {
            return '<button type="button" class="clean-tool" data-tool="' + t.k + '"' +
                (t.pressed ? ' aria-pressed="false"' : '') + (t.controls ? ' aria-expanded="false" aria-controls="' + t.controls + '"' : '') + '>' +
                ic(t.icon, 22) + '<span>' + t.label + '</span></button>';
        }).join('');
        timer.insertAdjacentElement('afterend', tools);
        var mg = document.querySelector('#drillContent .muscle-groups');
        if (mg) { mg.id = mg.id || 'cleanMuscles'; }
        tools.addEventListener('click', function (e) {
            var b = e.target.closest('[data-tool]');
            if (!b) { return; }
            var k = b.getAttribute('data-tool');
            if (k === 'listen') { if (window.CogniReadAloud) { window.CogniReadAloud.toggle(); } }
            else if (k === 'handsfree') { if (window.CogniCoachMode) { window.CogniCoachMode.open(); } }
            else if (k === 'form') { if (window.CogniFormCheck) { window.CogniFormCheck.toggle(); } }
            else if (k === '3d') { reveal($('motionViewer'), b, function (v) { var g = v.querySelector('.motion-generate'); if (g && v.getAttribute('data-mode') === 'idle') { g.click(); } }); }
            else if (k === 'muscles') { reveal(document.querySelector('#drillContent .muscle-groups'), b); }
        });
        if (!(window.CogniReadAloud && window.CogniReadAloud.supported)) { tools.querySelector('[data-tool="listen"]').hidden = true; }
        if (!window.CogniFormCheck) { tools.querySelector('[data-tool="form"]').hidden = true; }
        if (!window.CogniCoachMode) { tools.querySelector('[data-tool="handsfree"]').hidden = true; }
    }
    function reveal(el, btn, then) {
        if (!el) { return; }
        var open = !el.classList.contains('clean-show');
        el.classList.toggle('clean-show', open);
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
        if (open) {
            el.scrollIntoView({ block: 'start', behavior: H.classList.contains('a11y-reduce-motion') ? 'auto' : 'smooth' });
            if (then) { then(el); }
        }
    }
    // the drill text: steps first, "why this drill" folded away
    function foldWhy() {
        var d = $('drillDescription');
        if (!d || d.querySelector('.clean-why')) { return; }
        var html = d.innerHTML, i = html.search(/This drill helps/i);
        if (i <= 0) { d.innerHTML = html.replace(/\n/g, '<br>'); return; }
        var steps = html.slice(0, i).trim(), why = html.slice(i).trim();
        d.innerHTML = steps.replace(/\n/g, '<br>') +
            '<details class="clean-why"><summary>Why this drill</summary><p>' + why.replace(/\n/g, '<br>') + '</p></details>';
    }
    function onDrill() {
        buildSession();
        foldWhy();
        H.classList.remove('clean-running');
    }
    document.addEventListener('cognicoach:drill-rendered', function () { setTimeout(onDrill, 0); });
    // rating chips show once the drill is running (nothing to rate before that)
    document.addEventListener('cognicoach:timer', function (e) {
        var st = e.detail && e.detail.state;
        if (st === 'running' || st === 'tick' || st === 'complete') { H.classList.add('clean-running'); }
    });
    document.addEventListener('cognicoach:read-aloud', function (e) {
        var b = tools && tools.querySelector('[data-tool="listen"]');
        if (b) { b.setAttribute('aria-pressed', e.detail && e.detail.state && e.detail.state !== 'idle' ? 'true' : 'false'); }
    });
    document.addEventListener('cognicoach:form-check', function (e) {
        var b = tools && tools.querySelector('[data-tool="form"]');
        if (b) { b.setAttribute('aria-expanded', e.detail && e.detail.open ? 'true' : 'false'); }
    });

    // the tour opens and closes the muscle map and the 3D preview while it explains them
    function show(k, on) {
        buildSession();
        var el = k === '3d' ? $('motionViewer') : document.querySelector('#drillContent .muscle-groups');
        var b = tools && tools.querySelector('[data-tool="' + k + '"]');
        if (!el) { return; }
        el.classList.toggle('clean-show', !!on);
        if (b) { b.setAttribute('aria-expanded', on ? 'true' : 'false'); }
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', buildSession); } else { buildSession(); }

    window.CogniClean = { show: show };
})();
