// ==========================================================================
// Phone helpers, on every page (loaded by scripts/nav.js; styles in styles/mobile.css).
// The on-screen keyboard: while a text field has focus on a touch screen, html.kb-open hides
// the fixed bars (bottom tabs, timer dock, toasts) and lets the top bar scroll away, and once the
// keyboard is up the field is scrolled into the part of the screen that is still visible.
// ==========================================================================
(function () {
    'use strict';
    if (window.__cogniMobile) { return; }
    window.__cogniMobile = true;
    var H = document.documentElement;
    var touch = window.matchMedia && window.matchMedia('(pointer: coarse)').matches;
    if (!touch) { return; }

    function isField(el) {
        if (!el || !el.tagName) { return false; }
        if (el.isContentEditable || el.tagName === 'TEXTAREA') { return true; }
        return el.tagName === 'INPUT' && !/^(checkbox|radio|button|submit|reset|range|color|file|image|hidden)$/i.test(el.type || 'text');
    }
    function visibleArea() {
        var vv = window.visualViewport;
        return vv ? { top: vv.offsetTop, bottom: vv.offsetTop + vv.height } : { top: 0, bottom: window.innerHeight };
    }
    // The box that scrolls around the field: a dialog's own scroll area, a fixed panel (nothing to
    // scroll), or the page. Fields inside windows scroll the window only, never the page behind it.
    function scroller(el) {
        for (var p = el.parentElement; p && p !== document.body && p !== H; p = p.parentElement) {
            var cs = getComputedStyle(p);
            if (/(auto|scroll)/.test(cs.overflowY) && p.scrollHeight > p.clientHeight + 1) { return p; }
            if (cs.position === 'fixed') { return p; }
        }
        return null;
    }
    function keepInView(el) {
        if (!el || document.activeElement !== el) { return; }
        var r = el.getBoundingClientRect(), a = visibleArea();
        if (r.top >= a.top + 56 && r.bottom <= a.bottom - 12) { return; }
        var box = scroller(el);
        var want = r.top - (a.top + Math.max(56, (a.bottom - a.top - r.height) / 2));
        if (!box) { window.scrollBy(0, want); return; }
        if (box.scrollHeight > box.clientHeight + 1) { box.scrollTop += want; }
    }
    var offTimer = 0;
    document.addEventListener('focusin', function (e) {
        if (!isField(e.target)) { return; }
        clearTimeout(offTimer);
        H.classList.add('kb-open');
        var el = e.target;
        setTimeout(function () { keepInView(el); }, 320);   // after the keyboard slides up
    });
    document.addEventListener('focusout', function () {
        clearTimeout(offTimer);
        offTimer = setTimeout(function () { if (!isField(document.activeElement)) { H.classList.remove('kb-open'); } }, 200);
    });
    if (window.visualViewport) {
        window.visualViewport.addEventListener('resize', function () {
            if (isField(document.activeElement)) { keepInView(document.activeElement); }
        });
    }
})();
