// ==========================================================================
// Depth - a light 3D feel across the site, loaded on every page by nav.js.
// The page background tilts toward the pointer, and cards marked for it
// lean toward the pointer with a soft light following it.
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

    // ---------------------------------------------------------------- background tilt
    // The grid and glow behind every page lean toward the pointer (moved here from scripts/script.js
    // so all pages get it). Mouse/trackpad only; paused while the 3D viewer plays and with Reduce motion.
    function initializeInteractiveBackground() {
        if (window.__cogniBgTilt) { return; }
        window.__cogniBgTilt = true;
        // Touch devices don't have a meaningful "pointer position" to track —
        // driving this effect off touchmove meant the background tilted and
        // shifted on every scroll drag, which just looked janky and fought
        // with scrolling. Skip it entirely on coarse/no-hover (touch) devices.
        const isTouchDevice = window.matchMedia &&
            window.matchMedia('(hover: none), (pointer: coarse)').matches;
        if (isTouchDevice) {
            return;
        }

        const root = document.documentElement;
        const updatePointer = (clientX, clientY) => {
            const x = Math.max(0, Math.min(100, (clientX / window.innerWidth) * 100));
            const y = Math.max(0, Math.min(100, (clientY / window.innerHeight) * 100));
            const dx = (x - 50) / 50;
            const dy = (y - 50) / 50;

            const shiftX = (dx * -3).toFixed(2) + 'px';
            const shiftY = (dy * -3).toFixed(2) + 'px';
            const gridOffsetX = (dx * -8).toFixed(2) + 'px';
            const gridOffsetY = (dy * -8).toFixed(2) + 'px';
            const rotateX = (dy * -14).toFixed(2) + 'deg';
            const rotateY = (dx * 14).toFixed(2) + 'deg';
            const scale = (1 + Math.abs(dx) * 0.03 + Math.abs(dy) * 0.03).toFixed(2);
            const bgRotateX = (dy * -8).toFixed(2) + 'deg';
            const bgRotateY = (dx * 8).toFixed(2) + 'deg';
            const bgScale = (1 + Math.abs(dx) * 0.02 + Math.abs(dy) * 0.02).toFixed(2);

            root.style.setProperty('--pointer-x', x.toFixed(2) + '%');
            root.style.setProperty('--pointer-y', y.toFixed(2) + '%');
            root.style.setProperty('--bg-shift-x', shiftX);
            root.style.setProperty('--bg-shift-y', shiftY);
            root.style.setProperty('--grid-shift-x', gridOffsetX);
            root.style.setProperty('--grid-shift-y', gridOffsetY);
            root.style.setProperty('--grid-offset-x', gridOffsetX);
            root.style.setProperty('--grid-offset-y', gridOffsetY);
            root.style.setProperty('--grid-rotate-x', rotateX);
            root.style.setProperty('--grid-rotate-y', rotateY);
            root.style.setProperty('--grid-scale', scale);
            root.style.setProperty('--bg-rotate-x', bgRotateX);
            root.style.setProperty('--bg-rotate-y', bgRotateY);
            root.style.setProperty('--bg-scale', bgScale);
        };

        // At most one update per frame, and none while the 3D viewer plays (each update restyles the
        // whole page; see html.motion-live in styles/motion-viewer.css).
        let pointerRaf = 0, lastPointer = null;
        window.addEventListener('pointermove', event => {
            lastPointer = event;
            if (pointerRaf || root.classList.contains('motion-live') || root.classList.contains('a11y-reduce-motion')) return;
            pointerRaf = requestAnimationFrame(() => {
                pointerRaf = 0;
                if (lastPointer) updatePointer(lastPointer.clientX, lastPointer.clientY);
            });
        }, { passive: true });
    }
    initializeInteractiveBackground();
})();
