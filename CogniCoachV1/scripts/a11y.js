// ==========================================================================
// Accessibility layer, loaded on every page by scripts/nav.js.
//
// - "Skip to main content" link and a polite live region (CogniA11y.announce)
// - Nav landmark + aria-current on the active link
// - The "Aa" display & reading panel in the nav:
//     text size, high contrast, easy-read font, reduce motion,
//     and (on the app page) read-aloud voice, speed, auto-read and timer cues.
//   Choices are kept in localStorage 'cognicoach-a11y' and applied as classes on <html>
//   (nav.js applies them early so the page does not flash).
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniA11y) { return; }

    var KEY = 'cognicoach-a11y';
    var DEFAULTS = {
        textSize: 'normal',      // normal | large | xlarge
        contrast: false,
        easyRead: false,
        motion: 'auto',          // auto (follow the device) | reduce | full
        voice: '',               // SpeechSynthesisVoice.voiceURI, '' = browser default
        rate: 1,
        autoRead: false,
        timerCues: false
    };

    function load() {
        var p = {};
        try { p = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) {}
        var out = {};
        Object.keys(DEFAULTS).forEach(function (k) { out[k] = (k in p) ? p[k] : DEFAULTS[k]; });
        return out;
    }

    var prefs = load();
    var listeners = [];

    function save() {
        try { localStorage.setItem(KEY, JSON.stringify(prefs)); } catch (e) {}
    }

    function osReducedMotion() {
        return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    }

    function apply() {
        var h = document.documentElement;
        h.classList.toggle('a11y-text-lg', prefs.textSize === 'large');
        h.classList.toggle('a11y-text-xl', prefs.textSize === 'xlarge');
        h.classList.toggle('a11y-contrast', !!prefs.contrast);
        h.classList.toggle('a11y-easy-read', !!prefs.easyRead);
        h.classList.toggle('a11y-reduce-motion', prefs.motion === 'reduce' || (prefs.motion === 'auto' && osReducedMotion()));
    }

    function set(key, value) {
        prefs[key] = value;
        save();
        apply();
        listeners.forEach(function (fn) { try { fn(key, value, prefs); } catch (e) {} });
    }

    // ------------------------------------------------------------------ live region
    var live;
    function announce(msg) {
        if (!live) {
            live = document.createElement('div');
            live.className = 'a11y-sr-only';
            live.setAttribute('role', 'status');
            live.setAttribute('aria-live', 'polite');
            document.body.appendChild(live);
        }
        live.textContent = '';
        setTimeout(function () { live.textContent = msg; }, 60);
    }

    // ------------------------------------------------------------------ page structure
    function addSkipLink() {
        if (document.querySelector('.a11y-skip')) { return; }
        var main = document.getElementById('main') || document.querySelector('main, [role="main"]');
        if (!main) {
            main = document.querySelector('.container');
            if (!main) { return; }
            main.id = main.id || 'main';
            if (!main.matches('main')) { main.setAttribute('role', 'main'); }
        }
        if (!main.hasAttribute('tabindex')) { main.setAttribute('tabindex', '-1'); }
        var a = document.createElement('a');
        a.className = 'a11y-skip';
        a.href = '#' + main.id;
        a.textContent = 'Skip to main content';
        a.addEventListener('click', function (e) {
            e.preventDefault();
            main.focus();
            main.scrollIntoView({ block: 'start' });
        });
        document.body.insertBefore(a, document.body.firstChild);
    }

    function labelNav(nav) {
        nav.setAttribute('role', 'navigation');
        nav.setAttribute('aria-label', 'Main');
        nav.querySelectorAll('.site-nav-link.active').forEach(function (l) { l.setAttribute('aria-current', 'page'); });
        // the nav hides itself on scroll-down; keep it visible while a keyboard user is inside it
        nav.addEventListener('focusin', function () { nav.classList.remove('nav-hidden'); });
    }

    // ------------------------------------------------------------------ settings panel
    var btn, panel, open = false;

    function el(tag, attrs, html) {
        var e = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        if (html != null) { e.innerHTML = html; }
        return e;
    }

    function addNavButton(nav) {
        if (nav.querySelector('.a11y-btn')) { return; }
        btn = el('button', {
            type: 'button', 'class': 'a11y-btn', 'aria-expanded': 'false', 'aria-controls': 'a11yPanel',
            'aria-label': 'Display and reading settings', title: 'Display & reading settings'
        }, '<span aria-hidden="true">Aa</span>');
        var account = nav.querySelector('#navAccount');
        nav.insertBefore(btn, account || null);
        btn.addEventListener('click', function () { open ? close() : show(); });
    }

    function fmtRate(r) { return (Math.round(Number(r) * 100) / 100) + '\u00d7'; }

    function switchRow(id, label, hint, checked) {
        return '<label class="a11y-switch" for="' + id + '">' +
            '<span class="a11y-switch-text"><span class="a11y-switch-label">' + label + '</span>' +
            (hint ? '<span class="a11y-hint">' + hint + '</span>' : '') + '</span>' +
            '<input type="checkbox" role="switch" id="' + id + '"' + (checked ? ' checked' : '') + '>' +
            '<span class="a11y-switch-ui" aria-hidden="true"></span></label>';
    }

    function build() {
        panel = el('div', { id: 'a11yPanel', 'class': 'a11y-panel', role: 'dialog', 'aria-modal': 'false', 'aria-labelledby': 'a11yPanelTitle', hidden: '' });
        var sizes = [['normal', 'A', 'Default'], ['large', 'A', 'Large'], ['xlarge', 'A', 'Extra large']];
        var html = '<div class="a11y-panel-head"><h2 id="a11yPanelTitle">Display &amp; reading</h2>' +
            '<button type="button" class="a11y-close" aria-label="Close settings">&times;</button></div>' +
            '<fieldset class="a11y-group"><legend>Text size</legend><div class="a11y-seg">' +
            sizes.map(function (s, i) {
                return '<label class="a11y-seg-opt a11y-size-' + i + '"><input type="radio" name="a11ySize" value="' + s[0] + '"' +
                    (prefs.textSize === s[0] ? ' checked' : '') + '><span><b aria-hidden="true">' + s[1] + '</b> ' + s[2] + '</span></label>';
            }).join('') + '</div></fieldset>' +
            '<div class="a11y-group">' +
            switchRow('a11yContrast', 'High contrast', 'Darker text and stronger outlines', prefs.contrast) +
            switchRow('a11yEasyRead', 'Easy-read font', 'Plain letters, normal spacing', prefs.easyRead) +
            switchRow('a11yMotion', 'Reduce motion', 'Stops background animation' + (osReducedMotion() ? ' (your device asks for this)' : ''),
                prefs.motion === 'reduce' || (prefs.motion === 'auto' && osReducedMotion())) +
            '</div>';
        if (window.CogniReadAloud && window.CogniReadAloud.supported) {
            html += '<fieldset class="a11y-group a11y-voice"><legend>Read aloud</legend>' +
                switchRow('a11yAutoRead', 'Read each drill automatically', 'Starts when a new drill appears', prefs.autoRead) +
                switchRow('a11yCues', 'Spoken timer cues', '"Halfway", "10 seconds left", "Time"', prefs.timerCues) +
                '<label class="a11y-field" for="a11yVoice">Voice<select id="a11yVoice"><option value="">Browser default</option></select></label>' +
                '<label class="a11y-field" for="a11yRate">Speed <output id="a11yRateOut">' + fmtRate(prefs.rate) + '</output>' +
                '<input type="range" id="a11yRate" min="0.6" max="1.6" step="0.05" value="' + prefs.rate + '"></label>' +
                '<button type="button" class="a11y-test" id="a11yTestVoice">Test voice</button></fieldset>';
        }
        html += '<button type="button" class="a11y-reset" id="a11yReset">Reset to defaults</button>';
        panel.innerHTML = html;
        document.body.appendChild(panel);

        panel.querySelector('.a11y-close').addEventListener('click', function () { close(true); });
        panel.querySelectorAll('input[name="a11ySize"]').forEach(function (r) {
            r.addEventListener('change', function () { if (r.checked) { set('textSize', r.value); } });
        });
        var bind = function (id, fn) { var i = panel.querySelector('#' + id); if (i) { i.addEventListener('change', function () { fn(i); }); } };
        bind('a11yContrast', function (i) { set('contrast', i.checked); });
        bind('a11yEasyRead', function (i) { set('easyRead', i.checked); });
        bind('a11yMotion', function (i) { set('motion', i.checked ? 'reduce' : (osReducedMotion() ? 'full' : 'auto')); });
        bind('a11yAutoRead', function (i) { set('autoRead', i.checked); });
        bind('a11yCues', function (i) { set('timerCues', i.checked); });
        bind('a11yVoice', function (i) { set('voice', i.value); });
        var rate = panel.querySelector('#a11yRate');
        if (rate) {
            rate.addEventListener('input', function () {
                panel.querySelector('#a11yRateOut').textContent = fmtRate(rate.value);
            });
            rate.addEventListener('change', function () { set('rate', Number(rate.value)); });
        }
        var test = panel.querySelector('#a11yTestVoice');
        if (test) { test.addEventListener('click', function () { window.CogniReadAloud.test(); }); }
        panel.querySelector('#a11yReset').addEventListener('click', function () {
            Object.keys(DEFAULTS).forEach(function (k) { prefs[k] = DEFAULTS[k]; });
            save(); apply();
            listeners.forEach(function (fn) { try { fn('*', null, prefs); } catch (e) {} });
            panel.remove(); panel = null;
            show();
            announce('Display settings reset');
        });
        fillVoices();
    }

    function fillVoices() {
        var sel = panel && panel.querySelector('#a11yVoice');
        if (!sel || !window.CogniReadAloud) { return; }
        var voices = window.CogniReadAloud.voices();
        sel.innerHTML = '<option value="">Browser default</option>' + voices.map(function (v) {
            return '<option value="' + v.voiceURI.replace(/"/g, '&quot;') + '"' + (v.voiceURI === prefs.voice ? ' selected' : '') + '>' +
                v.name.replace(/</g, '&lt;') + ' (' + v.lang + ')</option>';
        }).join('');
    }

    function onDocKey(e) {
        if (e.key === 'Escape' && open) { close(true); }
    }
    function onDocClick(e) {
        if (open && panel && !panel.contains(e.target) && btn && !btn.contains(e.target)) { close(false); }
    }

    function show() {
        if (!panel) { build(); }
        panel.hidden = false;
        open = true;
        if (btn) { btn.setAttribute('aria-expanded', 'true'); }
        document.addEventListener('keydown', onDocKey);
        setTimeout(function () { document.addEventListener('click', onDocClick); }, 0);
        var first = panel.querySelector('input:checked, input, button');
        if (first) { first.focus(); }
    }

    function close(returnFocus) {
        if (!panel) { return; }
        panel.hidden = true;
        open = false;
        if (btn) { btn.setAttribute('aria-expanded', 'false'); if (returnFocus) { btn.focus(); } }
        document.removeEventListener('keydown', onDocKey);
        document.removeEventListener('click', onDocClick);
    }

    // ------------------------------------------------------------------ boot
    function init() {
        apply();
        addSkipLink();
        var nav = document.getElementById('siteNav');
        if (nav) { labelNav(nav); addNavButton(nav); }
        if (window.matchMedia) {
            var mq = window.matchMedia('(prefers-reduced-motion: reduce)');
            var onChange = function () { apply(); };
            if (mq.addEventListener) { mq.addEventListener('change', onChange); } else if (mq.addListener) { mq.addListener(onChange); }
        }
    }

    window.CogniA11y = {
        prefs: prefs,
        set: set,
        onChange: function (fn) { listeners.push(fn); },
        announce: announce,
        refreshVoices: fillVoices,
        open: show,
        close: close
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
