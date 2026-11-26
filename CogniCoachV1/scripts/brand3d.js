// ==========================================================================
// CogniBrand.mount(el): the CogniCoach logo in 3D - an extruded whistle (stacked layers give it
// real thickness) floating in front of a circuit board whose traces carry glowing data pulses.
// Decorative only (aria-hidden, no pointer interaction). Used by the sign-in window and the tour.
// Loaded on every page by scripts/nav.js; styles in styles/brand3d.css.
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniBrand) { return; }

    // Whistle outline (faces right): round chamber + mouthpiece, with the chamber hole and top slot.
    var WHISTLE = 'M 38 32 L 100 32 Q 106 32 106 38 L 106 46 Q 106 52 100 52 L 62.4 52 A 24 24 0 1 1 38 32 Z';
    var HOLE = 'M 47 56 A 9 9 0 1 0 29 56 A 9 9 0 1 0 47 56 Z';
    var SLOT = 'M 70 32 L 70 40 L 84 40 L 84 32';
    var LAYERS = 12;

    // Circuit traces fanning up and out from behind the whistle, like the logo.
    function traces() {
        var out = [];
        for (var i = -6; i <= 6; i++) {
            var sx = 120 + i * 7, sy = 96;
            var a = Math.abs(i), dir = i < 0 ? -1 : 1;
            var y1 = 78 - a * 3;
            var dx = i === 0 ? 0 : dir * (10 + a * 9);
            var y2 = y1 - Math.abs(dx);
            var y3 = Math.max(20, y2 - 14 - (a % 3) * 8);
            var pts = [[sx, sy], [sx, y1], [sx + dx, y2], [sx + dx, y3]];
            if (a >= 4) { pts.push([sx + dx + dir * 14, y3 - 8]); }
            out.push(pts);
        }
        // a few side branches for density
        [[-3, 60, -1], [3, 60, 1], [-5, 40, -1], [5, 40, 1]].forEach(function (b) {
            var x = 120 + b[0] * 7 + b[2] * 30, y = b[1];
            out.push([[x, y], [x + b[2] * 18, y - 18], [x + b[2] * 18, y - 30]]);
        });
        return out;
    }

    function svgPath(pts) { return 'M ' + pts.map(function (p) { return p[0] + ' ' + p[1]; }).join(' L '); }

    function markup() {
        var t = traces();
        var base = t.map(function (p) { return '<path d="' + svgPath(p) + '"/>'; }).join('');
        var pulses = t.map(function (p, i) {
            return '<path d="' + svgPath(p) + '" style="animation-delay:' + (-(i * 0.37) % 2.6).toFixed(2) + 's;animation-duration:' +
                (2.2 + (i % 4) * 0.35).toFixed(2) + 's"/>';
        }).join('');
        var nodes = t.map(function (p, i) {
            var e = p[p.length - 1];
            return '<circle cx="' + e[0] + '" cy="' + e[1] + '" r="3.2" style="animation-delay:' + (-(i * 0.29) % 2).toFixed(2) + 's"/>';
        }).join('');
        var layers = '';
        for (var k = 0; k < LAYERS; k++) {
            var front = k === LAYERS - 1;
            layers += '<svg class="bw-layer' + (front ? ' front' : '') + '" viewBox="0 0 120 90" style="transform:translateZ(' + (k * 1.1 - LAYERS * 0.55).toFixed(2) + 'px)">' +
                (front ? '<defs><linearGradient id="bwGrad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ffc061"/>' +
                    '<stop offset="0.55" stop-color="#ff8a1f"/><stop offset="1" stop-color="#e35d0c"/></linearGradient></defs>' : '') +
                '<path class="bw-body" d="' + WHISTLE + ' ' + HOLE + '" fill-rule="evenodd"/>' +
                '<path class="bw-slot" d="' + SLOT + '"/>' +
                '<circle class="bw-ring" cx="16" cy="40" r="6"/>' +
                '</svg>';
        }
        return '<div class="brand3d" aria-hidden="true">' +
            '<svg class="bc-board" viewBox="0 0 240 110" preserveAspectRatio="xMidYMax meet">' +
            '<g class="bc-traces">' + base + '</g><g class="bc-pulses">' + pulses + '</g><g class="bc-nodes">' + nodes + '</g></svg>' +
            '<div class="bw-glow"></div>' +
            '<div class="bw-stage"><div class="bw-whistle">' + layers + '</div></div>' +
            '</div>';
    }

    window.CogniBrand = {
        mount: function (el) {
            if (!el || el.querySelector('.brand3d')) { return; }
            el.innerHTML = markup();
        }
    };
})();
