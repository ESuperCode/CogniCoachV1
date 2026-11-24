// ==========================================================================
// Session dock - on phones and small tablets the timer sits far below the
// drill (after the muscle map and 3D preview). While it is scrolled out of
// view this bar stays at the bottom of the screen with the time left, the
// main timer action (Start / Pause / Resume / Next drill) and Read aloud.
// Its buttons press the real ones, so the session logic stays in script.js.
// ==========================================================================
(function () {
    'use strict';

    var dock, timeEl, fillEl, mainBtn, readBtn;
    var timerVisible = true, sessionOn = false;

    function $(id) { return document.getElementById(id); }
    function shown(el) { return !!el && el.style.display !== 'none' && !el.hidden && el.offsetParent !== null; }

    function build() {
        dock = document.createElement('div');
        dock.className = 'session-dock';
        dock.setAttribute('role', 'region');
        dock.setAttribute('aria-label', 'Timer shortcuts');
        dock.hidden = true;
        dock.innerHTML =
            '<button type="button" class="sd-time" aria-label="Go to the timer"><span class="sd-clock">00:00</span>' +
            '<span class="sd-track" aria-hidden="true"><span class="sd-fill"></span></span></button>' +
            '<button type="button" class="sd-read" aria-pressed="false"><span aria-hidden="true">🔊</span><span class="a11y-sr-only">Read drill aloud</span></button>' +
            '<button type="button" class="sd-main">Start</button>';
        document.body.appendChild(dock);
        timeEl = dock.querySelector('.sd-clock');
        fillEl = dock.querySelector('.sd-fill');
        mainBtn = dock.querySelector('.sd-main');
        readBtn = dock.querySelector('.sd-read');

        dock.querySelector('.sd-time').addEventListener('click', function () {
            var t = document.querySelector('.timer-container');
            if (t) { t.scrollIntoView({ block: 'center', behavior: 'smooth' }); }
            var s = $('startTimerBtn');
            setTimeout(function () { (shown(s) ? s : $('pauseBtn')).focus({ preventScroll: true }); }, 400);
        });
        mainBtn.addEventListener('click', function () {
            var target = mainBtn._target;
            if (target) { target.click(); }
            setTimeout(sync, 50);
        });
        readBtn.addEventListener('click', function () {
            if (window.CogniReadAloud) { window.CogniReadAloud.toggle(); }
        });
        if (!(window.CogniReadAloud && window.CogniReadAloud.supported)) { readBtn.hidden = true; }
    }

    // Mirror the real timer controls.
    function sync() {
        if (!dock) { return; }
        var display = $('timerDisplay'), bar = $('timerProgressBar');
        if (display) { timeEl.textContent = display.textContent; }
        if (bar) { fillEl.style.width = bar.style.width || '0%'; }

        var start = $('startTimerBtn'), pause = $('pauseBtn');
        var nextWrap = $('nextDrillContainer');
        var next = nextWrap && nextWrap.querySelector('button');
        var target = null, label = '';
        if (nextWrap && nextWrap.style.display !== 'none' && next) { target = next; label = 'Next drill'; }
        else if (start && start.style.display !== 'none') { target = start; label = 'Start'; }
        else if (pause && !pause.disabled) { target = pause; label = pause.textContent.trim() || 'Pause'; }
        mainBtn._target = target;
        mainBtn.textContent = label || 'Timer';
        mainBtn.disabled = !target;
        mainBtn.className = 'sd-main' + (label === 'Start' || label === 'Next drill' ? ' sd-go' : '');

        var drill = $('drillContent');
        sessionOn = !!(drill && !drill.classList.contains('hidden') && $('sessionView') && $('sessionView').classList.contains('active'));
        var show = sessionOn && !timerVisible && !document.documentElement.classList.contains('tour-on');
        if (dock.hidden === show) {
            dock.hidden = !show;
            document.body.classList.toggle('has-session-dock', show);
        }
    }

    function boot() {
        if (!$('timerDisplay')) { return; }
        build();
        var timer = document.querySelector('.timer-container');
        if (timer && 'IntersectionObserver' in window) {
            new IntersectionObserver(function (entries) {
                timerVisible = entries[entries.length - 1].isIntersecting;
                sync();
            }, { threshold: 0.15 }).observe(timer);
        }
        var mo = new MutationObserver(sync);
        ['timerDisplay', 'startTimerBtn', 'pauseBtn', 'nextDrillContainer', 'drillContent'].forEach(function (id) {
            var el = $(id);
            if (el) { mo.observe(el, { attributes: true, childList: true, characterData: true, subtree: id === 'timerDisplay' }); }
        });
        ['timer', 'drill-rendered', 'drill-loading', 'session-end'].forEach(function (n) {
            document.addEventListener('cognicoach:' + n, function () { setTimeout(sync, 0); });
        });
        document.addEventListener('cognicoach:read-aloud', function (e) {
            var on = e.detail && e.detail.state !== 'idle';
            readBtn.setAttribute('aria-pressed', on ? 'true' : 'false');
            readBtn.classList.toggle('on', on);
        });
        sync();
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }
})();
