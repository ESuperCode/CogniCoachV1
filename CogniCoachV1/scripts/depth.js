// ==========================================================================
// Depth - a light 3D feel across the site, loaded on every page by nav.js.
// Cards marked for it lean toward the pointer with a soft light following it.
// Mouse / trackpad only; off with "Reduce motion" and while the 3D viewer
// is playing (html.motion-live) so it never costs performance.
// ==========================================================================
(function () {
    'use strict';
    if (window.__cogniDepth) { return; }
    window.__cogniDepth = true;

    var SELECTOR = '.about-feature, .about-card, .recap-tile, .stat-card, .dash-stat, .quick-start-card, .readiness .adapt-chip';
    var MAX = 6;   // degrees

    function off() {
        var h = document.documentElement;
        return h.classList.contains('a11y-reduce-motion') || h.classList.contains('motion-live') || h.classList.contains('coach-on') ||
            !(window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches);
    }

    var current = null, raf = 0;
    function reset(el) {
        if (!el) { return; }
        el.classList.remove('depth-live');
        el.style.removeProperty('--d-rx'); el.style.removeProperty('--d-ry');
    }
    document.addEventListener('pointermove', function (e) {
        if (e.pointerType && e.pointerType !== 'mouse') { return; }
        var el = e.target.closest && e.target.closest(SELECTOR);
        if (el !== current) { reset(current); current = el; }
        if (!el || off()) { return; }
        cancelAnimationFrame(raf);
        raf = requestAnimationFrame(function () {
            var r = el.getBoundingClientRect();
            var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
            // big cards lean less
            var k = Math.min(1, 420 / Math.max(r.width, 1));
            el.classList.add('depth', 'depth-live');
            el.style.setProperty('--d-rx', ((0.5 - y) * MAX * k).toFixed(2) + 'deg');
            el.style.setProperty('--d-ry', ((x - 0.5) * MAX * k).toFixed(2) + 'deg');
            el.style.setProperty('--d-mx', (x * 100).toFixed(1) + '%');
            el.style.setProperty('--d-my', (y * 100).toFixed(1) + '%');
        });
    }, { passive: true });
    document.addEventListener('pointerleave', function () { reset(current); current = null; });
})();
