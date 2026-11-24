// ==========================================================================
// First-visit guided tour of the app page (index.html).
// Runs once per device (localStorage 'cognicoach-tour-done'), after the welcome/onboarding modal,
// and again with index.html?tour=1 (the account menu links there). Loaded on every page by nav.js;
// does nothing on pages without the Quick Start card.
// ==========================================================================
(function () {
    'use strict';
    var DONE_KEY = 'cognicoach-tour-done';
    if (window.CogniTour) { return; }

    var STEPS = [
        { kind: 'hero', title: 'Welcome to CogniCoachAI',
          text: 'Your AI coach builds a full training session around your sport, your space and your time. Take a 30-second look around?' },
        { target: '#quickStartCard', group: ['#quickStartCard .quick-start-header', '#sportSwitcher'], title: 'Quick Start',
          text: 'The fastest way to train. CogniCoach remembers your sport and level, so most days this is all you touch.' },
        { target: '#location', group: ['#location', '#workoutLength', '#focus'], title: 'Where, how long, what',
          text: 'Tell it where you are, how many minutes you have and what you want to work on - the AI plans every drill to fit.' },
        { target: '#quickStartBtn', title: 'One tap to train',
          text: 'Press Start and your drills appear one by one, each with a timer, the muscles it works and a 3D animation you can watch.' },
        { target: '#advancedSetup', title: 'Full control',
          text: 'Pick muscle groups, set your level, or drag drills into your own warm-up, main work and cool-down timeline.', open: false },
        { target: 'site-nav a[href="dashboard.html"]', nav: true, title: 'Your dashboard',
          text: 'Streaks, XP levels, personal records and charts of every session you finish.' },
        { target: '#navAccount', nav: true, title: 'Sync everywhere',
          text: 'Create a free account to keep your profile and history on every device you sign in to.' },
        { kind: 'finale', title: "You're all set",
          text: 'Start a session, and during any drill press Generate Animation to watch it performed in 3D.' }
    ];

    var root, spot, card, idx = 0, active = false, repositionRaf = 0;

    function $(sel) { try { return document.querySelector(sel); } catch (e) { return null; } }

    function visible(el) {
        if (!el) { return false; }
        var r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    }

    function steps() {
        return STEPS.filter(function (s) { return !s.target || visible($(s.target)); });
    }

    function rectFor(step) {
        var els = (step.group || [step.target]).map($).filter(visible);
        if (!els.length) { return null; }
        var r = els.reduce(function (acc, el) {
            var b = el.getBoundingClientRect();
            // a form field: highlight its whole form group
            var g = el.closest && el.closest('.form-group');
            if (g && step.group && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) { b = g.getBoundingClientRect(); }
            return acc ? { left: Math.min(acc.left, b.left), top: Math.min(acc.top, b.top),
                right: Math.max(acc.right, b.right), bottom: Math.max(acc.bottom, b.bottom) } :
                { left: b.left, top: b.top, right: b.right, bottom: b.bottom };
        }, null);
        var pad = 10;
        return { left: r.left - pad, top: r.top - pad, width: r.right - r.left + 2 * pad, height: r.bottom - r.top + 2 * pad };
    }

    function build() {
        root = document.createElement('div');
        root.className = 'tour-root';
        root.innerHTML =
            '<div class="tour-spot"></div>' +
            '<div class="tour-card" role="dialog" aria-live="polite" aria-labelledby="tourTitle">' +
            '  <div class="tour-holo" aria-hidden="true">' +
            '    <div class="holo-ring r1"></div><div class="holo-ring r2"></div><div class="holo-ring r3"></div>' +
            '    <div class="holo-cube"><i class="f1"></i><i class="f2"></i><i class="f3"></i><i class="f4"></i><i class="f5"></i><i class="f6"></i></div>' +
            '    <div class="holo-floor"></div>' +
            '    <span class="holo-p p1"></span><span class="holo-p p2"></span><span class="holo-p p3"></span><span class="holo-p p4"></span>' +
            '  </div>' +
            '  <div class="tour-step-num"></div>' +
            '  <h2 class="tour-title" id="tourTitle"></h2>' +
            '  <p class="tour-text"></p>' +
            '  <div class="tour-dots"></div>' +
            '  <div class="tour-actions">' +
            '    <button type="button" class="tour-skip" data-t="skip">Skip tour</button>' +
            '    <span class="tour-spacer"></span>' +
            '    <button type="button" class="tour-back" data-t="back">Back</button>' +
            '    <button type="button" class="btn btn-primary tour-next" data-t="next">Next</button>' +
            '  </div>' +
            '</div>' +
            '<div class="tour-confetti" aria-hidden="true"></div>';
        document.body.appendChild(root);
        spot = root.querySelector('.tour-spot');
        card = root.querySelector('.tour-card');
        root.addEventListener('click', function (e) {
            var b = e.target.closest('[data-t]');
            if (!b) { return; }
            var t = b.getAttribute('data-t');
            if (t === 'next') { go(idx + 1); } else if (t === 'back') { go(idx - 1); } else { finish(true); }
        });
        // subtle 3D tilt that follows the pointer
        card.addEventListener('pointermove', function (e) {
            var r = card.getBoundingClientRect();
            var x = (e.clientX - r.left) / r.width - 0.5, y = (e.clientY - r.top) / r.height - 0.5;
            card.style.setProperty('--tilt-x', (-y * 6).toFixed(2) + 'deg');
            card.style.setProperty('--tilt-y', (x * 8).toFixed(2) + 'deg');
        });
        card.addEventListener('pointerleave', function () { card.style.setProperty('--tilt-x', '0deg'); card.style.setProperty('--tilt-y', '0deg'); });
        document.addEventListener('keydown', onKey);
        window.addEventListener('resize', schedulePosition);
        window.addEventListener('scroll', schedulePosition, { passive: true });
    }

    function onKey(e) {
        if (!active) { return; }
        if (e.key === 'Escape') { finish(true); }
        else if (e.key === 'ArrowRight' || e.key === 'Enter') { e.preventDefault(); go(idx + 1); }
        else if (e.key === 'ArrowLeft') { e.preventDefault(); go(idx - 1); }
    }

    function schedulePosition() {
        if (!active) { return; }
        cancelAnimationFrame(repositionRaf);
        repositionRaf = requestAnimationFrame(position);
    }

    function position() {
        var list = steps(), step = list[idx];
        if (!step) { return; }
        var mobile = window.innerWidth < 640;
        if (!step.target) {
            spot.classList.add('center');
            spot.style.cssText = 'left:50%;top:50%;width:0;height:0;';
            card.classList.add('centered');
            card.style.left = ''; card.style.top = '';
            return;
        }
        var r = rectFor(step);
        if (!r) { return; }
        spot.classList.remove('center');
        card.classList.remove('centered');
        spot.style.left = r.left + 'px';
        spot.style.top = r.top + 'px';
        spot.style.width = r.width + 'px';
        spot.style.height = r.height + 'px';
        if (mobile) { card.style.left = ''; card.style.top = ''; card.classList.add('docked'); return; }
        card.classList.remove('docked');
        var cw = card.offsetWidth, ch = card.offsetHeight, gap = 18, vw = window.innerWidth, vh = window.innerHeight;
        if (r.height > vh * 0.6) {   // a target taller than most of the screen: park the card in a corner
            card.style.left = (vw - cw - 20) + 'px';
            card.style.top = (vh - ch - 20) + 'px';
            card.setAttribute('data-place', 'corner');
            return;
        }
        var top = r.top + r.height + gap;
        var place = 'below';
        if (top + ch > vh - 12) { top = r.top - ch - gap; place = 'above'; }
        if (top < 12) {   // no room above or below: beside the target, or over it
            top = Math.max(12, Math.min(vh - ch - 12, r.top));
            place = r.left + r.width + gap + cw < vw ? 'right' : 'left';
        }
        var left;
        if (place === 'right') { left = r.left + r.width + gap; }
        else if (place === 'left') { left = Math.max(12, r.left - cw - gap); }
        else { left = Math.max(12, Math.min(vw - cw - 12, r.left + r.width / 2 - cw / 2)); }
        card.style.left = left + 'px';
        card.style.top = top + 'px';
        card.setAttribute('data-place', place);
    }

    function go(n) {
        var list = steps();
        if (n >= list.length) { finish(false); return; }
        if (n < 0) { return; }
        idx = n;
        var step = list[idx];
        card.classList.remove('enter');
        void card.offsetWidth;
        card.classList.add('enter');
        card.classList.toggle('hero', step.kind === 'hero' || step.kind === 'finale');
        card.querySelector('.tour-title').textContent = step.title;
        card.querySelector('.tour-text').textContent = step.text;
        card.querySelector('.tour-step-num').textContent = step.target ? ('Step ' + idx + ' of ' + (list.length - 2)) : '';
        card.querySelector('.tour-dots').innerHTML = list.map(function (s, i) { return '<i class="' + (i === idx ? 'on' : i < idx ? 'done' : '') + '"></i>'; }).join('');
        card.querySelector('.tour-back').style.visibility = idx > 0 ? 'visible' : 'hidden';
        card.querySelector('.tour-next').textContent = step.kind === 'hero' ? "Let's go" : step.kind === 'finale' ? 'Start training' : 'Next';
        card.querySelector('.tour-skip').style.visibility = step.kind === 'finale' ? 'hidden' : 'visible';
        if (step.kind === 'finale') { confetti(); }
        if (step.target) {
            var el = $(step.target);
            if (step.nav) {
                window.scrollTo({ top: 0, behavior: 'smooth' });
                var nav = document.getElementById('siteNav');
                if (nav) { nav.classList.remove('nav-hidden'); }
            } else if (el) {
                var b = el.getBoundingClientRect();
                var mobile = window.innerWidth < 640;
                var want = mobile ? 90 : Math.max(90, (window.innerHeight - b.height) / 2 - 60);
                window.scrollTo({ top: Math.max(0, window.scrollY + b.top - want), behavior: 'smooth' });
            }
            // follow the smooth scroll, then settle
            var t0 = performance.now();
            (function follow() {
                position();
                if (performance.now() - t0 < 900 && active) { requestAnimationFrame(follow); }
            })();
        } else {
            position();
        }
        card.querySelector('.tour-next').focus({ preventScroll: true });
    }

    function confetti() {
        var box = root.querySelector('.tour-confetti');
        box.innerHTML = '';
        var colors = ['#1f7ae0', '#ff8a34', '#2ecc71', '#7fd0ff', '#ffd166'];
        for (var i = 0; i < 46; i++) {
            var p = document.createElement('i');
            p.style.left = (50 + (Math.random() - 0.5) * 30) + '%';
            p.style.background = colors[i % colors.length];
            p.style.setProperty('--dx', ((Math.random() - 0.5) * 900).toFixed(0) + 'px');
            p.style.setProperty('--dy', (-200 - Math.random() * 380).toFixed(0) + 'px');
            p.style.setProperty('--rot', (Math.random() * 720 - 360).toFixed(0) + 'deg');
            p.style.animationDelay = (Math.random() * 0.15).toFixed(2) + 's';
            box.appendChild(p);
        }
    }

    function finish(skipped) {
        active = false;
        try { localStorage.setItem(DONE_KEY, JSON.stringify({ at: Date.now(), skipped: !!skipped })); } catch (e) {}
        root.classList.remove('show');
        document.documentElement.classList.remove('tour-on');
        setTimeout(function () { if (root) { root.remove(); root = null; } }, 350);
        if (!skipped) {
            var btn = $('#quickStartBtn');
            if (btn && visible(btn)) {
                btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
                btn.classList.add('tour-glow');
                setTimeout(function () { btn.classList.remove('tour-glow'); }, 3200);
            }
        }
    }

    function start() {
        if (active || !$('#quickStartCard')) { return; }
        var setup = $('#setupView');
        if (setup && getComputedStyle(setup).display === 'none') { return; }   // mid-session: not now
        if (!root) { build(); }
        active = true;
        idx = 0;
        document.documentElement.classList.add('tour-on');
        requestAnimationFrame(function () { root.classList.add('show'); go(0); });
    }

    function seen() { try { return !!localStorage.getItem(DONE_KEY); } catch (e) { return true; } }

    // Wait until the page is idle: no onboarding/profile modal and no account modal open.
    function startWhenClear(delay) {
        var tries = 0;
        (function wait() {
            if ($('#profileModalOverlay') || $('#accountModal')) {
                if (++tries < 600) { setTimeout(wait, 400); }
                return;
            }
            setTimeout(function () {
                if ($('#profileModalOverlay') || $('#accountModal')) { wait(); return; }
                start();
            }, delay);
        })();
    }

    window.CogniTour = { start: start, reset: function () { try { localStorage.removeItem(DONE_KEY); } catch (e) {} } };

    function init() {
        if (!$('#quickStartCard')) { return; }
        var forced = new URLSearchParams(location.search).get('tour') === '1';
        if (forced) {
            try { history.replaceState(null, '', location.pathname + location.search.replace(/([?&])tour=1(&|$)/, '$1').replace(/[?&]$/, '') + location.hash); } catch (e) {}
            startWhenClear(500);
        } else if (!seen()) {
            startWhenClear(900);
        }
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { setTimeout(init, 0); }
})();
