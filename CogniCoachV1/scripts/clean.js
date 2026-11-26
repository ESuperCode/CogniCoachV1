// ==========================================================================
// Clean app page (html.clean; ?classic=1 shows the old layout). Less to read, fewer taps:
//
//   Home    one "Today" card: the coach's plan (focus, sport, minutes, why) and one Start button.
//           Everything else (sport, length, where/what, how you feel, Your coach, preferences,
//           Build my own plan) sits in an "Adjust" sheet. The plan is applied for the athlete,
//           so pressing Start is the whole job. New athletes pick their sport right on the card.
//   Session the drill, the timer, then one row of tools (Listen, Hands-free, 3D, Muscles,
//           Form check) instead of a long page; the muscle map and the 3D preview open on demand,
//           the "why this drill" part folds away, rating chips appear once the drill is running.
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
    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function profile() { try { return typeof loadProfile === 'function' ? loadProfile() : {}; } catch (e) { return {}; } }
    function sport() { return window.__quickStartSportOverride || profile().defaultSport || ''; }

    // ================================================================== HOME
    var hero, sheet, adjusted = false, lastFocus = null;

    function greeting() {
        var h = new Date().getHours();
        return h < 5 ? 'Late session' : h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
    }
    function streak() {
        try { return window.CogniEconomy ? window.CogniEconomy.streakInfo().current : 0; } catch (e) { return 0; }
    }
    function plan() {
        var s = sport();
        try { return s && window.CogniCoachProfile ? window.CogniCoachProfile.planToday(s) : null; } catch (e) { return null; }
    }
    function setVal(el, v) {
        if (!el || String(el.value) === String(v)) { return; }
        el.value = v;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
    }
    // Until the athlete changes something, the coach's plan is what Start will do.
    function applyPlan(p) {
        if (adjusted || !p) { return; }
        setVal($('focus'), p.focus);
        setVal($('workoutLength'), String(Math.max(15, Math.min(180, p.minutes))));
    }

    function buildHome() {
        var card = $('quickStartCard'), start = $('quickStartBtn');
        if (!card || !start || hero) { return; }
        hero = document.createElement('section');
        hero.className = 'today';
        hero.setAttribute('aria-labelledby', 'todayTitle');
        hero.innerHTML =
            '<p class="today-hi"></p>' +
            '<h2 class="today-title" id="todayTitle"></h2>' +
            '<p class="today-meta"></p>' +
            '<p class="today-why"></p>' +
            '<div class="today-pick"></div>' +
            '<div class="today-go"></div>' +
            '<button type="button" class="today-adjust" aria-haspopup="dialog" aria-controls="cleanSheet">' + ic('sliders', 18) + '<span>Adjust</span></button>' +
            '<p class="today-streak"></p>';
        card.parentNode.insertBefore(hero, card);
        hero.querySelector('.today-go').appendChild(start);
        var hint = $('quickStartHint');
        if (hint) { hero.querySelector('.today-go').appendChild(hint); }
        start.textContent = 'Start';
        hero.querySelector('.today-adjust').addEventListener('click', openSheet);
        hero.addEventListener('click', function (e) {   // a new athlete picked a sport on the card
            if (e.target.closest('[data-sport-pick]:not([data-sport-pick="__other__"]), #sportSwitcherUse')) { adjusted = false; setTimeout(render, 80); }
        });
        buildSheet();
        fillSheet();

        // Start does the coach's plan unless the athlete adjusted it (runs before the other Start handlers)
        start.addEventListener('click', function () { applyPlan(plan()); }, true);

        // everything below the card folds into one quiet "More" section
        var more = $('marketingIntro');
        if (more && !more.closest('.clean-more')) {
            var d = document.createElement('details');
            d.className = 'clean-more';
            d.innerHTML = '<summary>Sport guides and questions</summary>';
            more.parentNode.insertBefore(d, more);
            d.appendChild(more);
        }
        render();
    }

    function buildSheet() {
        sheet = document.createElement('div');
        sheet.className = 'clean-sheet';
        sheet.id = 'cleanSheet';
        sheet.hidden = true;
        sheet.innerHTML =
            '<div class="cs-panel" role="dialog" aria-modal="true" aria-labelledby="cleanSheetTitle">' +
            '<div class="cs-head"><h2 id="cleanSheetTitle">Adjust today</h2>' +
            '<button type="button" class="cs-x" aria-label="Done">' + ic('close', 20) + '</button></div>' +
            '<div class="cs-body"></div>' +
            '<div class="cs-foot"><button type="button" class="btn btn-primary cs-done">Done</button>' +
            '<button type="button" class="cs-link cs-build">Build my own plan</button></div>' +
            '</div>';
        document.body.appendChild(sheet);
        sheet.querySelector('.cs-x').addEventListener('click', closeSheet);
        sheet.querySelector('.cs-done').addEventListener('click', closeSheet);
        sheet.querySelector('.cs-build').addEventListener('click', function () {
            closeSheet();
            var adv = $('advancedSetup');
            if (adv) { adv.open = true; adv.scrollIntoView({ block: 'start', behavior: 'smooth' }); var s = adv.querySelector('summary'); if (s) { s.focus({ preventScroll: true }); } }
        });
        sheet.addEventListener('click', function (e) { if (e.target === sheet) { closeSheet(); } });
        sheet.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') { e.preventDefault(); closeSheet(); return; }
            if (e.key !== 'Tab') { return; }
            var f = [].slice.call(sheet.querySelectorAll('button, [href], input, select, summary, [tabindex]:not([tabindex="-1"])')).filter(function (el) { return !el.disabled && el.offsetParent !== null; });
            if (!f.length) { return; }
            if (e.shiftKey && document.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
            else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
        });
        // any change in the sheet is the athlete's own choice: keep it
        var body = sheet.querySelector('.cs-body');
        body.addEventListener('input', function (e) { if (e.isTrusted) { adjusted = true; } });
        body.addEventListener('click', function (e) {
            if (e.target.closest('[data-len], [data-plan-use]')) { adjusted = true; }
            if (e.target.closest('[data-sport-pick], #sportSwitcherUse')) { adjusted = false; setTimeout(render, 80); }
        });
    }
    // The existing controls move into the sheet when it opens (they are made by other scripts, some later).
    function fillSheet() {
        var body = sheet.querySelector('.cs-body');
        var parts = [
            sport() ? $('sportSwitcher') : null,
            document.querySelector('#quickStartCard .qs-length'),
            $('qsDetails'),
            $('readinessCheck'),
            document.querySelector('#quickStartCard [data-coach-summary]') || document.querySelector('.cs-body [data-coach-summary]'),
            document.querySelector('.qs-more')
        ];
        parts.forEach(function (el) { if (el && el.parentNode !== body) { body.appendChild(el); } });
    }
    function showDetails() {   // the where/what fields open straight away: the sheet is already the "more" place
        var det = $('qsDetailsPanel'), detBtn = $('qsDetailsBtn');
        if (det && det.hidden && detBtn) { detBtn.click(); }
    }
    function openSheet() {
        lastFocus = document.activeElement;
        applyPlan(plan());   // the sheet shows what Start will do
        fillSheet();
        showDetails();
        sheet.hidden = false;
        H.classList.add('clean-sheet-open');
        var first = sheet.querySelector('.cs-x');
        if (first) { first.focus(); }
    }
    function closeSheet() {
        if (!sheet || sheet.hidden) { return; }
        sheet.hidden = true;
        H.classList.remove('clean-sheet-open');
        render();
        if (lastFocus && document.contains(lastFocus)) { lastFocus.focus(); }
    }

    function render() {
        if (!hero) { return; }
        var s = sport(), p = plan();
        applyPlan(p);
        var hi = hero.querySelector('.today-hi'), title = hero.querySelector('.today-title'), meta = hero.querySelector('.today-meta'),
            why = hero.querySelector('.today-why'), pick = hero.querySelector('.today-pick'), st = hero.querySelector('.today-streak');
        var sw = $('sportSwitcher');
        if (!s) {
            hero.classList.add('today-new');
            hi.textContent = 'Welcome';
            title.textContent = 'What do you play?';
            meta.textContent = 'Pick your sport. Your coach plans every drill.';
            why.textContent = '';
            if (sw && sw.parentNode !== pick) { pick.appendChild(sw); }
        } else {
            hero.classList.remove('today-new');
            if (sw && sw.parentNode === pick) { sheet.querySelector('.cs-body').insertBefore(sw, sheet.querySelector('.cs-body').firstChild); }
            var f = $('focus'), l = $('workoutLength');
            var focus = (f && f.value.trim()) || (p && p.focus) || 'All-round training';
            var mins = (l && Number(l.value)) || (p && p.minutes) || 30;
            hi.textContent = greeting() + (p && !adjusted ? ' · ' + p.tone : '');
            title.textContent = focus;
            meta.textContent = s + ' · ' + mins + ' min';
            why.textContent = !adjusted && p ? p.why : 'Your choice for today.';
        }
        var n = streak();
        st.innerHTML = n > 0 ? ic('flame', 16) + ' ' + n + '-day streak' : '';
        st.hidden = !(n > 0);
    }
    document.addEventListener('cognicoach:coach', function () { if (!adjusted) { render(); } });
    window.addEventListener('cognicoach:synced', render);

    // ================================================================== SESSION
    var tools = null;
    function drillState() {
        try { var s = appState.session; return { s: s, d: s.drills[s.currentDrillIndex] }; } catch (e) { return null; }
    }
    function buildSession() {
        var card = document.querySelector('#drillContent > .card');
        var timer = document.querySelector('#drillContent .timer-container');
        if (!card || !timer || tools) { return; }
        // progress line: "Drill 2 of 8 · Main work" + the full timeline on demand
        var prog = card.querySelector('.progress-indicator');
        if (prog && !$('cleanAllDrills')) {
            var sec = document.createElement('span');
            sec.className = 'clean-section';
            prog.querySelector('.progress-text').appendChild(sec);
            var all = document.createElement('button');
            all.type = 'button';
            all.id = 'cleanAllDrills';
            all.className = 'clean-all';
            all.setAttribute('aria-expanded', 'false');
            all.setAttribute('aria-controls', 'sessionTimeline');
            all.textContent = 'All drills';
            all.addEventListener('click', function () {
                var open = all.getAttribute('aria-expanded') !== 'true';
                all.setAttribute('aria-expanded', open ? 'true' : 'false');
                H.classList.toggle('clean-timeline', open);
            });
            prog.appendChild(all);
        }
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
        var st = drillState(), sec = document.querySelector('.clean-section');
        if (sec) { sec.textContent = st && st.d && st.d.sectionName ? ' · ' + st.d.sectionName : ''; }
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

    function init() { buildHome(); buildSession(); }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
    // other scripts fill the Quick Start card after load (sport switcher, plan, coach summary, readiness)
    window.addEventListener('load', function () { if (sheet) { fillSheet(); } render(); });

    window.CogniClean = { render: render, openSheet: openSheet };
})();
