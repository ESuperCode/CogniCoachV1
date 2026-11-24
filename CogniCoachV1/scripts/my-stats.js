// ==========================================================================
// My Stats (dashboard) - analysis of the athlete's own training history.
//   - range filter (4 weeks / 12 weeks / all time) drives everything below
//   - KPI tiles with change vs the previous period
//   - Training skyline: a 3D isometric city of days (height = minutes),
//     drag or use the buttons to rotate, hover for the day, table view
//   - Sport mix: a 3D extruded donut, legend with values, hover, table view
//   - Rating (OVR) over time with the rank tiers as bands
//   - Training rhythm: by weekday and by time of day
//   - How drills felt: too hard / just right / too easy
//   - "What the numbers say": written analysis and projections
// All client-side canvas/SVG from localStorage history (scripts/athlete-stats.js).
// ==========================================================================
(function () {
    'use strict';
    var CS = window.CogniStats;
    if (!CS) { return; }

    // validated categorical order (blue, orange, aqua, yellow, magenta) + Other
    var SERIES = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4'];
    var OTHER = '#9a9890';
    // sequential blue ramp, light -> dark
    var SEQ = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#2a78d6', '#1c5cab', '#104281'];
    var DAY = 864e5;
    var WD = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    var RANGE_KEY = 'cognicoach-mystats-range';

    var range = '28';
    try { range = localStorage.getItem(RANGE_KEY) || '28'; } catch (e) {}
    var skyline = null, donut = null;

    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function startOfDay(t) { var d = new Date(t); d.setHours(0, 0, 0, 0); return d.getTime(); }
    function fmtDate(t) { return new Date(t).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' }); }
    function pct(n) { return Math.round(n * 100) + '%'; }
    function reduceMotion() { return document.documentElement.classList.contains('a11y-reduce-motion'); }

    // ------------------------------------------------------------------ data
    function slice(all) {
        var now = Date.now();
        var days = range === 'all' ? Math.max(28, Math.ceil((now - (all.length ? new Date(all[0].date).getTime() : now)) / DAY) + 1) : Number(range);
        var from = startOfDay(now) - (days - 1) * DAY;
        var cur = all.filter(function (r) { return new Date(r.date).getTime() >= from; });
        var prevFrom = from - days * DAY;
        var prev = range === 'all' ? [] : all.filter(function (r) { var t = new Date(r.date).getTime(); return t >= prevFrom && t < from; });
        return { days: days, from: from, cur: cur, prev: prev };
    }

    function sum(rs, f) { return rs.reduce(function (s, r) { return s + f(r); }, 0); }
    function kpis(rs, days) {
        var mins = sum(rs, CS.minutesOf);
        var active = {}; rs.forEach(function (r) { active[CS.dayKey(r.date)] = 1; });
        var withI = rs.filter(function (r) { return typeof r.intensity === 'number'; });
        return {
            sessions: rs.length, minutes: mins, avg: rs.length ? Math.round(mins / rs.length) : 0,
            completion: rs.length ? rs.filter(function (r) { return r.completed; }).length / rs.length : 0,
            activeDays: Object.keys(active).length, days: days,
            intensity: withI.length ? sum(withI, function (r) { return r.intensity; }) / withI.length : null
        };
    }

    // stable colour per sport: by all-time minutes, so a range change never repaints a sport
    function sportColors(all) {
        var tot = {};
        all.forEach(function (r) { var k = r.sport || 'General'; tot[k] = (tot[k] || 0) + CS.minutesOf(r); });
        var order = Object.keys(tot).sort(function (a, b) { return tot[b] - tot[a]; });
        var map = {};
        order.forEach(function (s, i) { map[s] = i < SERIES.length ? SERIES[i] : OTHER; });
        return map;
    }

    // ------------------------------------------------------------------ render shell
    function render() {
        var anchor = document.getElementById('athleteCard') || document.getElementById('profileSummaryCard');
        if (!anchor) { return; }
        var host = document.getElementById('myStats');
        if (!host) {
            host = document.createElement('section');
            host.id = 'myStats';
            host.className = 'card dash-card dash-span-12 ms-section';
            host.setAttribute('aria-labelledby', 'myStatsTitle');
            anchor.parentNode.insertBefore(host, anchor.nextSibling);
        }
        var all = CS.history().sort(function (a, b) { return new Date(a.date) - new Date(b.date); });
        if (!all.length) {
            host.innerHTML = '<h2 class="card-title" id="myStatsTitle">My Stats</h2><p class="ms-empty">Finish a session and your stats, 3D charts and analysis show up here.</p>';
            return;
        }
        var sl = slice(all);
        var k = kpis(sl.cur, sl.days), kp = kpis(sl.prev, sl.days);
        var colors = sportColors(all);
        var rangeName = { '28': 'last 4 weeks', '84': 'last 12 weeks', 'all': 'all time' }[range];

        host.innerHTML =
            '<div class="ms-head"><h2 class="card-title" id="myStatsTitle">My Stats</h2>' +
            '<div class="ms-range" role="group" aria-label="Time range">' +
            [['28', '4 weeks'], ['84', '12 weeks'], ['all', 'All time']].map(function (o) {
                return '<button type="button" data-range="' + o[0] + '" aria-pressed="' + (range === o[0]) + '">' + o[1] + '</button>';
            }).join('') + '</div></div>' +

            '<div class="ms-kpis">' +
            kpi('Sessions', k.sessions, delta(k.sessions, kp.sessions)) +
            kpi('Minutes', k.minutes, delta(k.minutes, kp.minutes)) +
            kpi('Avg session', k.avg + ' min', delta(k.avg, kp.avg)) +
            kpi('Finished', pct(k.completion), range === 'all' || !kp.sessions ? '' : ptsDelta(k.completion, kp.completion)) +
            kpi('Active days', k.activeDays + ' / ' + Math.min(k.days, 9999), '') +
            kpi('Intensity', k.intensity == null ? '—' : intensityWord(k.intensity), '') +
            '</div>' +

            '<div class="ms-grid">' +
            '<figure class="ms-panel ms-wide"><figcaption><span><b>Training skyline</b><small>Every day of the ' + rangeName + '. Taller and darker = more minutes.</small></span>' +
            '<span class="ms-tools"><button type="button" class="ms-tool" data-rot="-1" aria-label="Rotate left">⟲</button><button type="button" class="ms-tool" data-rot="1" aria-label="Rotate right">⟳</button>' +
            '<button type="button" class="ms-tool ms-table-btn" aria-pressed="false" data-for="skyTable">Table</button></span></figcaption>' +
            '<div class="ms-canvas-wrap"><canvas class="ms-sky" role="img" aria-label="' + esc(skyAria(sl)) + '"></canvas><div class="ms-tip" hidden></div></div>' +
            '<div class="ms-legend-seq" aria-hidden="true"><span>0 min</span><i style="background:linear-gradient(90deg,' + SEQ.join(',') + ')"></i><span id="skyMax"></span></div>' +
            '<div class="ms-table" id="skyTable" tabindex="0" role="region" aria-label="Minutes per day" hidden>' + skyTable(sl) + '</div></figure>' +

            '<figure class="ms-panel"><figcaption><span><b>Sport mix</b><small>Share of minutes</small></span>' +
            '<span class="ms-tools"><button type="button" class="ms-tool ms-table-btn" aria-pressed="false" data-for="mixTable">Table</button></span></figcaption>' +
            '<div class="ms-canvas-wrap ms-donut-wrap"><canvas class="ms-donut" role="img" aria-label="' + esc(mixAria(sl.cur)) + '"></canvas><div class="ms-tip" hidden></div></div>' +
            '<ul class="ms-legend">' + mixRows(sl.cur, colors).map(function (m) {
                return '<li><i style="background:' + m.color + '"></i><span>' + esc(m.name) + '</span><b>' + m.minutes + ' min</b><small>' + pct(m.share) + '</small></li>';
            }).join('') + '</ul>' +
            '<div class="ms-table" id="mixTable" tabindex="0" role="region" aria-label="Minutes by sport" hidden>' + mixTable(sl.cur, colors) + '</div></figure>' +

            '<figure class="ms-panel"><figcaption><span><b>Rating over time</b><small>Your OVR after each session, with rank tiers</small></span></figcaption>' +
            '<div class="ms-line-wrap"></div></figure>' +

            '<figure class="ms-panel"><figcaption><span><b>Training rhythm</b><small>Minutes by weekday and time of day</small></span></figcaption>' + rhythm(sl.cur) + '</figure>' +

            '<figure class="ms-panel"><figcaption><span><b>How drills felt</b><small>Your ratings during sessions</small></span></figcaption>' + feel(sl.cur) + '</figure>' +

            '<div class="ms-panel ms-wide ms-analysis"><h3>What the numbers say</h3><ul>' +
            analysis(all, sl, k, kp).map(function (a) { return '<li><span class="ms-a-icon" aria-hidden="true">' + a[0] + '</span><span>' + a[1] + '</span></li>'; }).join('') +
            '</ul></div>' +
            '</div>';

        host.querySelectorAll('[data-range]').forEach(function (b) {
            b.addEventListener('click', function () {
                range = b.dataset.range;
                try { localStorage.setItem(RANGE_KEY, range); } catch (e) {}
                render();
                var again = document.querySelector('#myStats [data-range="' + range + '"]');
                if (again) { again.focus(); }
            });
        });
        host.querySelectorAll('.ms-table-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                var t = document.getElementById(b.dataset.for);
                var on = t.hidden;
                t.hidden = !on;
                b.setAttribute('aria-pressed', on ? 'true' : 'false');
            });
        });

        if (skyline) { skyline.destroy(); }
        skyline = Skyline(host.querySelector('.ms-sky'), skyData(sl), host);
        host.querySelectorAll('[data-rot]').forEach(function (b) { b.addEventListener('click', function () { skyline.rotate(Number(b.dataset.rot) * Math.PI / 8); }); });
        if (donut) { donut.destroy(); }
        donut = Donut(host.querySelector('.ms-donut'), mixRows(sl.cur, colors));
        lineChart(host.querySelector('.ms-line-wrap'), all, sl.from);
    }

    function kpi(label, value, d) {
        return '<div class="ms-kpi"><span class="ms-kpi-label">' + label + '</span><span class="ms-kpi-val">' + esc(value) + '</span>' + (d ? '<span class="ms-kpi-delta">' + d + '</span>' : '<span class="ms-kpi-delta ms-muted">&nbsp;</span>') + '</div>';
    }
    function delta(a, b) {
        if (range === 'all' || !b) { return ''; }
        var p = Math.round((a - b) / b * 100);
        if (!p) { return '<span class="ms-flat">→ same as before</span>'; }
        return '<span class="' + (p > 0 ? 'ms-up' : 'ms-down') + '">' + (p > 0 ? '▲ ' : '▼ ') + Math.abs(p) + '%</span> vs previous';
    }
    function ptsDelta(a, b) {
        var p = Math.round((a - b) * 100);
        if (!p) { return '<span class="ms-flat">→ same as before</span>'; }
        return '<span class="' + (p > 0 ? 'ms-up' : 'ms-down') + '">' + (p > 0 ? '▲ ' : '▼ ') + Math.abs(p) + ' pts</span> vs previous';
    }
    function intensityWord(v) { return v > 1.2 ? 'Max' : v > 0.4 ? 'High' : v < -1.2 ? 'Recovery' : v < -0.4 ? 'Lower' : 'Standard'; }

    // ------------------------------------------------------------------ skyline data + table
    function skyData(sl) {
        var weeks = Math.min(26, Math.ceil(sl.days / 7));
        var end = startOfDay(Date.now());
        var endSat = end + (6 - new Date(end).getDay()) * DAY;     // grid ends on this week's Saturday
        var start = endSat - (weeks * 7 - 1) * DAY;
        var byDay = {};
        sl.cur.forEach(function (r) {
            var t = startOfDay(new Date(r.date).getTime());
            var e = byDay[t] || (byDay[t] = { minutes: 0, sports: {} });
            e.minutes += CS.minutesOf(r);
            e.sports[r.sport || 'General'] = 1;
        });
        var cells = [], max = 0;
        for (var w = 0; w < weeks; w++) {
            for (var d = 0; d < 7; d++) {
                var t = start + (w * 7 + d) * DAY;
                var e = byDay[t];
                var m = e ? e.minutes : 0;
                max = Math.max(max, m);
                cells.push({ w: w, d: d, t: t, minutes: m, future: t > end, sports: e ? Object.keys(e.sports).join(', ') : '' });
            }
        }
        return { cells: cells, weeks: weeks, max: max || 1 };
    }
    function skyAria(sl) {
        var mins = sum(sl.cur, CS.minutesOf);
        return '3D chart of daily training minutes: ' + sl.cur.length + ' sessions, ' + mins + ' minutes. Use the Table button for the numbers.';
    }
    function skyTable(sl) {
        var rows = {};
        sl.cur.forEach(function (r) { var t = startOfDay(new Date(r.date).getTime()); rows[t] = (rows[t] || 0) + CS.minutesOf(r); });
        var keys = Object.keys(rows).sort(function (a, b) { return b - a; });
        return '<table><caption class="a11y-sr-only">Minutes per training day</caption><thead><tr><th scope="col">Day</th><th scope="col">Minutes</th></tr></thead><tbody>' +
            keys.map(function (t) { return '<tr><td>' + fmtDate(Number(t)) + '</td><td>' + rows[t] + '</td></tr>'; }).join('') + '</tbody></table>';
    }

    // ------------------------------------------------------------------ 3D skyline (canvas, isometric)
    function Skyline(canvas, data, host) {
        var ctx = canvas.getContext('2d');
        var tip = canvas.parentNode.querySelector('.ms-tip');
        var yaw = -0.62, pitch = 0.62, auto = !reduceMotion(), dragging = false, lastX = 0, raf = 0, polys = [], dead = false, hover = null;
        var maxEl = host.querySelector('#skyMax'); if (maxEl) { maxEl.textContent = data.max + ' min'; }
        var W = 0, H = 0, dpr = 1, fit = null;
        var cols = 7, rows = data.weeks, span = Math.max(cols, rows), hMax = Math.max(2.2, span * 0.38);

        function size() {
            dpr = Math.min(2, window.devicePixelRatio || 1);
            W = canvas.clientWidth; H = canvas.clientHeight;
            canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
            // fit the scene to the canvas for every rotation, so turning it never zooms or clips
            var minX = 1e9, maxX = -1e9, minY = 1e9, maxY = -1e9, sinP = Math.sin(pitch), cosP = Math.cos(pitch);
            for (var a = 0; a < Math.PI * 2; a += Math.PI / 16) {
                [[0, 0], [cols, 0], [cols, rows], [0, rows]].forEach(function (c) {
                    var X = c[0] - cols / 2, Z = c[1] - rows / 2;
                    var xr = X * Math.cos(a) - Z * Math.sin(a), zr = X * Math.sin(a) + Z * Math.cos(a);
                    [0, hMax].forEach(function (y) {
                        var sy = zr * sinP - y * cosP;
                        minX = Math.min(minX, xr); maxX = Math.max(maxX, xr); minY = Math.min(minY, sy); maxY = Math.max(maxY, sy);
                    });
                });
            }
            var sc = Math.min((W - 48) / (maxX - minX), (H - 40) / (maxY - minY + 0.8));
            fit = { scale: sc, cx: W / 2 - (minX + maxX) / 2 * sc, cy: H / 2 - (minY + maxY) / 2 * sc - 6 };
        }
        function color(m) {
            if (!m) { return null; }
            var i = Math.min(SEQ.length - 1, 1 + Math.floor((m / data.max) * (SEQ.length - 1.001)));
            return SEQ[i];
        }
        function shade(hex, f) {
            var n = parseInt(hex.slice(1), 16), r = n >> 16, g = (n >> 8) & 255, b = n & 255;
            return 'rgb(' + Math.round(r * f) + ',' + Math.round(g * f) + ',' + Math.round(b * f) + ')';
        }
        function draw() {
            if (dead) { return; }
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, W, H);
            var scale = fit.scale, cx = fit.cx, cy = fit.cy;
            var cosY = Math.cos(yaw), sinY = Math.sin(yaw), sinP = Math.sin(pitch), cosP = Math.cos(pitch);
            function P(x, y, z) {   // grid coords -> screen; x = weekday, z = week, y = up
                var X = x - cols / 2, Z = z - rows / 2;
                var xr = X * cosY - Z * sinY, zr = X * sinY + Z * cosY;
                return [cx + xr * scale, cy + (zr * sinP - y * cosP) * scale, zr];
            }
            // floor
            ctx.beginPath();
            var f = [P(0, 0, 0), P(cols, 0, 0), P(cols, 0, rows), P(0, 0, rows)];
            ctx.moveTo(f[0][0], f[0][1]); f.slice(1).forEach(function (p) { ctx.lineTo(p[0], p[1]); }); ctx.closePath();
            ctx.fillStyle = 'rgba(26,109,204,0.06)'; ctx.fill();
            ctx.strokeStyle = 'rgba(26,109,204,0.18)'; ctx.lineWidth = 1; ctx.stroke();
            // weekday labels along the front edge
            ctx.fillStyle = '#56657b'; ctx.font = '11px "Space Mono", monospace'; ctx.textAlign = 'center';
            for (var d = 0; d < 7; d++) { var lp = P(d + 0.5, 0, rows + 0.9); ctx.fillText(WD[d].charAt(0), lp[0], lp[1] + 4); }
            var wl = P(-0.9, 0, rows - 0.5); ctx.fillText('now', wl[0], wl[1] + 4);
            if (rows > 1) { var wf = P(-0.9, 0, 0.5); ctx.fillText(rows + 'w', wf[0], wf[1] + 4); }

            // bars, far to near
            var bars = data.cells.map(function (c) {
                var x = c.d + 0.15, z = c.w + 0.15, s = 0.7;
                var h = c.minutes ? Math.max(0.12, (c.minutes / data.max) * hMax) : 0.04;
                var mid = P(x + s / 2, 0, z + s / 2);
                return { c: c, x: x, z: z, s: s, h: h, depth: mid[2] };
            }).sort(function (a, b) { return a.depth - b.depth; });
            polys = [];
            bars.forEach(function (b) {
                var base = b.c.future ? null : color(b.c.minutes);
                var top = [P(b.x, b.h, b.z), P(b.x + b.s, b.h, b.z), P(b.x + b.s, b.h, b.z + b.s), P(b.x, b.h, b.z + b.s)];
                var bot = [P(b.x, 0, b.z), P(b.x + b.s, 0, b.z), P(b.x + b.s, 0, b.z + b.s), P(b.x, 0, b.z + b.s)];
                var faces = [];
                // side faces: [i, j] corners; visible when facing the viewer (larger rotated depth)
                [[0, 1], [1, 2], [2, 3], [3, 0]].forEach(function (e) {
                    var fd = (bot[e[0]][2] + bot[e[1]][2]) / 2;
                    if (fd > b.depth) { faces.push({ pts: [top[e[0]], top[e[1]], bot[e[1]], bot[e[0]]], f: e[0] % 2 ? 0.72 : 0.86 }); }
                });
                var isHover = hover && hover === b.c;
                faces.forEach(function (fc) {
                    poly(fc.pts, base ? shade(base, fc.f) : (b.c.future ? 'rgba(200,210,225,0.25)' : '#dde5ef'), null);
                });
                poly(top, base || (b.c.future ? 'rgba(220,228,238,0.35)' : '#eef2f7'), isHover ? '#172033' : (base ? 'rgba(255,255,255,0.65)' : 'rgba(118,140,168,0.35)'), isHover ? 2 : 1);
                if (!b.c.future) { polys.push({ c: b.c, shapes: [top].concat(faces.map(function (x) { return x.pts; })) }); }
            });
            if (auto && !dragging) { yaw += 0.0035; raf = requestAnimationFrame(draw); }
        }
        function poly(pts, fill, stroke, lw) {
            ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]);
            for (var i = 1; i < pts.length; i++) { ctx.lineTo(pts[i][0], pts[i][1]); }
            ctx.closePath(); ctx.fillStyle = fill; ctx.fill();
            if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lw || 1; ctx.stroke(); }
        }
        function inside(pt, poly) {
            var c = false;
            for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
                var xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
                if (((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi)) { c = !c; }
            }
            return c;
        }
        function pick(x, y) {
            for (var i = polys.length - 1; i >= 0; i--) {
                for (var k = 0; k < polys[i].shapes.length; k++) { if (inside([x, y], polys[i].shapes[k])) { return polys[i].c; } }
            }
            return null;
        }
        function stopAuto() { auto = false; cancelAnimationFrame(raf); }
        canvas.addEventListener('pointerdown', function (e) { dragging = true; lastX = e.clientX; stopAuto(); canvas.setPointerCapture(e.pointerId); });
        canvas.addEventListener('pointerup', function () { dragging = false; });
        canvas.addEventListener('pointercancel', function () { dragging = false; });
        canvas.addEventListener('pointermove', function (e) {
            var r = canvas.getBoundingClientRect();
            if (dragging) { yaw += (e.clientX - lastX) * 0.01; lastX = e.clientX; tip.hidden = true; hover = null; draw(); return; }
            var c = pick(e.clientX - r.left, e.clientY - r.top);
            if (c !== hover) { hover = c; if (!auto) { draw(); } }
            if (c) {
                tip.hidden = false;
                tip.innerHTML = '<b>' + fmtDate(c.t) + '</b><span>' + (c.minutes ? c.minutes + ' min · ' + esc(c.sports) : 'Rest day') + '</span>';
                place(tip, e.clientX - r.left, e.clientY - r.top, r.width);
            } else { tip.hidden = true; }
        });
        canvas.addEventListener('pointerleave', function () { tip.hidden = true; hover = null; if (!auto) { draw(); } });
        var ro = 'ResizeObserver' in window ? new ResizeObserver(function () { size(); if (!auto) { draw(); } }) : null;
        if (ro) { ro.observe(canvas); }
        size(); draw();
        // stop spinning when it scrolls out of view
        var io = 'IntersectionObserver' in window ? new IntersectionObserver(function (en) {
            if (!en[0].isIntersecting) { cancelAnimationFrame(raf); } else if (auto) { cancelAnimationFrame(raf); draw(); }
        }) : null;
        if (io) { io.observe(canvas); }
        return {
            rotate: function (a) { stopAuto(); yaw += a; draw(); },
            destroy: function () { dead = true; cancelAnimationFrame(raf); if (ro) { ro.disconnect(); } if (io) { io.disconnect(); } }
        };
    }
    function place(tip, x, y, w) {
        tip.style.left = Math.min(Math.max(8, x + 14), w - 190) + 'px';
        tip.style.top = Math.max(4, y - 54) + 'px';
    }

    // ------------------------------------------------------------------ sport mix + 3D donut
    function mixRows(rs, colors) {
        var tot = {}, all = 0;
        rs.forEach(function (r) { var k = r.sport || 'General'; var m = CS.minutesOf(r); tot[k] = (tot[k] || 0) + m; all += m; });
        var rows = Object.keys(tot).map(function (k) { return { name: k, minutes: tot[k], color: colors[k] || OTHER }; })
            .sort(function (a, b) { return b.minutes - a.minutes; });
        var main = rows.filter(function (r) { return r.color !== OTHER; }).slice(0, 5);
        var rest = rows.filter(function (r) { return main.indexOf(r) < 0; });
        if (rest.length) { main.push({ name: 'Other (' + rest.length + ')', minutes: sum(rest, function (r) { return r.minutes; }), color: OTHER }); }
        main.forEach(function (r) { r.share = all ? r.minutes / all : 0; });
        return main;
    }
    function mixAria(rs) {
        var rows = mixRows(rs, {});
        return '3D donut chart of minutes by sport: ' + rows.map(function (r) { return r.name + ' ' + pct(r.share); }).join(', ') + '.';
    }
    function mixTable(rs, colors) {
        return '<table><caption class="a11y-sr-only">Minutes by sport</caption><thead><tr><th scope="col">Sport</th><th scope="col">Minutes</th><th scope="col">Share</th></tr></thead><tbody>' +
            mixRows(rs, colors).map(function (m) { return '<tr><td>' + esc(m.name) + '</td><td>' + m.minutes + '</td><td>' + pct(m.share) + '</td></tr>'; }).join('') + '</tbody></table>';
    }

    function Donut(canvas, rows) {
        var ctx = canvas.getContext('2d');
        var tip = canvas.parentNode.querySelector('.ms-tip');
        var W, H, dpr, rot = -Math.PI / 2, hover = -1, segs = [], dead = false, raf = 0, lift = rows.map(function () { return 0; });
        function size() {
            dpr = Math.min(2, window.devicePixelRatio || 1);
            W = canvas.clientWidth; H = canvas.clientHeight;
            canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
        }
        function shade(hex, f) {
            var n = parseInt(hex.slice(1), 16);
            return 'rgb(' + Math.round((n >> 16) * f) + ',' + Math.round(((n >> 8) & 255) * f) + ',' + Math.round((n & 255) * f) + ')';
        }
        function draw() {
            if (dead) { return; }
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, W, H);
            var R = Math.min(W * 0.42, H * 0.7), r = R * 0.62, k = 0.52, depth = Math.max(10, R * 0.16);
            var cx = W / 2, cy = H / 2 - depth / 2;
            var a = rot, total = rows.reduce(function (s, x) { return s + x.minutes; }, 0) || 1;
            segs = rows.map(function (x, i) { var a0 = a; a += (x.minutes / total) * Math.PI * 2; return { i: i, a0: a0, a1: a, row: x }; });
            // ease hover lift
            var animating = false;
            lift = lift.map(function (l, i) { var target = i === hover ? 1 : 0; var n = l + (target - l) * 0.25; if (Math.abs(n - target) > 0.01) { animating = true; } return n; });
            function off(s) { var m = (s.a0 + s.a1) / 2, d = lift[s.i] * R * 0.08; return [Math.cos(m) * d, Math.sin(m) * d * k]; }
            function pt(ang, rad, o, dy) { return [cx + o[0] + Math.cos(ang) * rad, cy + o[1] + Math.sin(ang) * rad * k + (dy || 0)]; }
            function arcPath(a0, a1, rad, o, dy, rev) {
                var n = Math.max(2, Math.ceil(Math.abs(a1 - a0) / 0.06)), out = [];
                for (var j = 0; j <= n; j++) { var t = rev ? a1 - (a1 - a0) * j / n : a0 + (a1 - a0) * j / n; out.push(pt(t, rad, o, dy)); }
                return out;
            }
            function fillPts(pts, fill, stroke) {
                ctx.beginPath(); ctx.moveTo(pts[0][0], pts[0][1]); for (var j = 1; j < pts.length; j++) { ctx.lineTo(pts[j][0], pts[j][1]); }
                ctx.closePath(); ctx.fillStyle = fill; ctx.fill(); if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 2; ctx.stroke(); }
            }
            // inner walls (back half, visible through the hole) then outer walls (front half)
            segs.forEach(function (s) {
                var o = off(s);
                var b0 = Math.max(s.a0, Math.PI), b1 = Math.min(s.a1, 2 * Math.PI);
                [[b0, b1], [Math.max(s.a0, -Math.PI), Math.min(s.a1, 0)]].forEach(function (rg) {
                    if (rg[1] > rg[0]) { fillPts(arcPath(rg[0], rg[1], r, o, 0).concat(arcPath(rg[0], rg[1], r, o, depth, true)), shade(s.row.color, 0.55)); }
                });
            });
            segs.slice().sort(function (p, q) { return Math.sin((p.a0 + p.a1) / 2) - Math.sin((q.a0 + q.a1) / 2); }).forEach(function (s) {
                var o = off(s);
                [[Math.max(s.a0, 0), Math.min(s.a1, Math.PI)], [Math.max(s.a0, 2 * Math.PI), Math.min(s.a1, 3 * Math.PI)]].forEach(function (rg) {
                    if (rg[1] > rg[0]) { fillPts(arcPath(rg[0], rg[1], R, o, 0).concat(arcPath(rg[0], rg[1], R, o, depth, true)), shade(s.row.color, 0.72)); }
                });
            });
            // tops with a 2px surface gap
            segs.forEach(function (s) {
                var o = off(s);
                var top = arcPath(s.a0, s.a1, R, o, 0).concat(arcPath(s.a0, s.a1, r, o, 0, true));
                fillPts(top, s.row.color, '#ffffff');
                s.top = top;
            });
            // centre label
            ctx.fillStyle = '#172033'; ctx.textAlign = 'center';
            ctx.font = '700 ' + Math.round(R * 0.2) + 'px Orbitron, sans-serif';
            ctx.fillText(String(total), cx, cy + r * k * 0.55);
            ctx.fillStyle = '#56657b'; ctx.font = Math.round(R * 0.09) + 'px "Space Mono", monospace';
            ctx.fillText('minutes', cx, cy + r * k * 0.55 + R * 0.12);
            if (animating) { raf = requestAnimationFrame(draw); }
        }
        function inside(pt, poly) {
            var c = false;
            for (var i = 0, j = poly.length - 1; i < poly.length; j = i++) {
                var xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
                if (((yi > pt[1]) !== (yj > pt[1])) && (pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi)) { c = !c; }
            }
            return c;
        }
        canvas.addEventListener('pointermove', function (e) {
            var b = canvas.getBoundingClientRect(), x = e.clientX - b.left, y = e.clientY - b.top;
            var hit = -1;
            segs.forEach(function (s) { if (s.top && inside([x, y], s.top)) { hit = s.i; } });
            if (hit !== hover) { hover = hit; cancelAnimationFrame(raf); draw(); }
            if (hit >= 0) {
                var row = rows[hit];
                tip.hidden = false;
                tip.innerHTML = '<b>' + esc(row.name) + '</b><span>' + row.minutes + ' min · ' + pct(row.share) + '</span>';
                place(tip, x, y, b.width);
            } else { tip.hidden = true; }
        });
        canvas.addEventListener('pointerleave', function () { hover = -1; tip.hidden = true; cancelAnimationFrame(raf); draw(); });
        var ro = 'ResizeObserver' in window ? new ResizeObserver(function () { size(); draw(); }) : null;
        if (ro) { ro.observe(canvas); }
        size(); draw();
        return { destroy: function () { dead = true; cancelAnimationFrame(raf); if (ro) { ro.disconnect(); } } };
    }

    // ------------------------------------------------------------------ rating line (SVG)
    function lineChart(host, all, from) {
        var pts = [];
        for (var i = 0; i < all.length; i++) {
            var t = new Date(all[i].date).getTime();
            if (t < from && i < all.length - 1) { continue; }
            pts.push({ t: t, v: CS.rating(all.slice(0, i + 1), t), n: i + 1 });
        }
        if (pts.length < 2) { host.innerHTML = '<p class="ms-empty">Two or more sessions in this range draw your rating line.</p>'; return; }
        var W = 520, H = 230, L = 34, R = 74, T = 12, B = 28;
        var vmin = Math.max(40, Math.min.apply(null, pts.map(function (p) { return p.v; })) - 6);
        var vmax = Math.min(99, Math.max.apply(null, pts.map(function (p) { return p.v; })) + 6);
        var t0 = pts[0].t, t1 = pts[pts.length - 1].t || t0 + 1;
        var X = function (t) { return L + (t1 === t0 ? 0.5 : (t - t0) / (t1 - t0)) * (W - L - R); };
        var Y = function (v) { return T + (1 - (v - vmin) / (vmax - vmin)) * (H - T - B); };
        var bands = CS.TIERS.map(function (tr, i) { return { tier: tr, lo: tr.min, hi: CS.TIERS[i + 1] ? CS.TIERS[i + 1].min : 100 }; })
            .filter(function (b) { return b.hi > vmin && b.lo < vmax; });
        var path = pts.map(function (p, i) { return (i ? 'L' : 'M') + X(p.t).toFixed(1) + ' ' + Y(p.v).toFixed(1); }).join(' ');
        var area = path + ' L' + X(pts[pts.length - 1].t).toFixed(1) + ' ' + (H - B) + ' L' + X(pts[0].t).toFixed(1) + ' ' + (H - B) + ' Z';
        var last = pts[pts.length - 1];
        var svg = '<svg class="ms-line" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="Rating went from ' + pts[0].v + ' to ' + last.v + ' over ' + pts.length + ' sessions.">' +
            '<defs><linearGradient id="msArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#2a78d6" stop-opacity="0.28"/><stop offset="1" stop-color="#2a78d6" stop-opacity="0"/></linearGradient>' +
            '<filter id="msShadow" x="-5%" y="-20%" width="110%" height="160%"><feDropShadow dx="0" dy="6" stdDeviation="5" flood-color="#1a6dcc" flood-opacity="0.3"/></filter></defs>' +
            bands.map(function (b) {
                var y0 = Y(Math.min(b.hi, vmax)), y1 = Y(Math.max(b.lo, vmin));
                return '<rect x="' + L + '" y="' + y0.toFixed(1) + '" width="' + (W - L - R) + '" height="' + Math.max(0, y1 - y0).toFixed(1) + '" fill="' + b.tier.color + '" opacity="0.08"/>' +
                    '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + y1.toFixed(1) + '" y2="' + y1.toFixed(1) + '" stroke="' + b.tier.color + '" stroke-opacity="0.35" stroke-dasharray="3 4"/>' +
                    '<text x="' + (W - R + 6) + '" y="' + ((y0 + y1) / 2 + 4).toFixed(1) + '" class="ms-band-label">' + b.tier.name + '</text>';
            }).join('') +
            [vmin, Math.round((vmin + vmax) / 2), vmax].map(function (v) { return '<text x="' + (L - 6) + '" y="' + (Y(v) + 4).toFixed(1) + '" text-anchor="end" class="ms-axis">' + Math.round(v) + '</text>'; }).join('') +
            '<text x="' + L + '" y="' + (H - 8) + '" class="ms-axis">' + new Date(t0).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + '</text>' +
            '<text x="' + (W - R) + '" y="' + (H - 8) + '" text-anchor="end" class="ms-axis">' + new Date(t1).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + '</text>' +
            '<path d="' + area + '" fill="url(#msArea)"/>' +
            '<path d="' + path + '" fill="none" stroke="#2a78d6" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round" filter="url(#msShadow)"/>' +
            '<circle cx="' + X(last.t).toFixed(1) + '" cy="' + Y(last.v).toFixed(1) + '" r="5" fill="#2a78d6" stroke="#fff" stroke-width="2"/>' +
            '<text x="' + (X(last.t) - 8).toFixed(1) + '" y="' + (Y(last.v) - 10).toFixed(1) + '" text-anchor="end" class="ms-direct">' + last.v + ' OVR</text>' +
            '<line class="ms-cross" x1="0" x2="0" y1="' + T + '" y2="' + (H - B) + '" stroke="#172033" stroke-opacity="0.35" visibility="hidden"/>' +
            '<circle class="ms-cross-dot" r="5" fill="#2a78d6" stroke="#fff" stroke-width="2" visibility="hidden"/>' +
            '<rect class="ms-hit" x="' + L + '" y="' + T + '" width="' + (W - L - R) + '" height="' + (H - T - B) + '" fill="transparent"/>' +
            '</svg><div class="ms-tip" hidden></div>';
        host.innerHTML = svg;
        var el = host.querySelector('svg'), tip = host.querySelector('.ms-tip'), cross = el.querySelector('.ms-cross'), dot = el.querySelector('.ms-cross-dot');
        el.querySelector('.ms-hit').addEventListener('pointermove', function (e) {
            var b = el.getBoundingClientRect();
            var sx = (e.clientX - b.left) * (W / b.width);
            var best = pts[0];
            pts.forEach(function (p) { if (Math.abs(X(p.t) - sx) < Math.abs(X(best.t) - sx)) { best = p; } });
            var px = X(best.t), py = Y(best.v);
            cross.setAttribute('x1', px); cross.setAttribute('x2', px); cross.setAttribute('visibility', 'visible');
            dot.setAttribute('cx', px); dot.setAttribute('cy', py); dot.setAttribute('visibility', 'visible');
            var rk = CS.rankFor(best.v, best.n);
            tip.hidden = false;
            tip.innerHTML = '<b>' + fmtDate(best.t) + '</b><span>OVR ' + best.v + ' · ' + esc(rk.label) + '</span>';
            place(tip, px * b.width / W, py * b.height / H, b.width);
        });
        el.querySelector('.ms-hit').addEventListener('pointerleave', function () { tip.hidden = true; cross.setAttribute('visibility', 'hidden'); dot.setAttribute('visibility', 'hidden'); });
    }

    // ------------------------------------------------------------------ rhythm + feel
    function bucket(h) { return h < 5 ? 3 : h < 12 ? 0 : h < 17 ? 1 : h < 21 ? 2 : 3; }
    function rhythm(rs) {
        var wd = [0, 0, 0, 0, 0, 0, 0], tod = [0, 0, 0, 0];
        rs.forEach(function (r) { var d = new Date(r.date), m = CS.minutesOf(r); wd[d.getDay()] += m; tod[bucket(d.getHours())] += m; });
        var mw = Math.max.apply(null, wd) || 1, mt = Math.max.apply(null, tod) || 1;
        var bars = function (vals, labels, max, cls) {
            return '<div class="ms-bars ' + cls + '">' + vals.map(function (v, i) {
                return '<div class="ms-bar" title="' + labels[i] + ': ' + v + ' min"><span class="ms-bar-val">' + (v || '') + '</span>' +
                    '<span class="ms-bar-col"><i style="height:' + Math.max(v ? 4 : 0, Math.round(v / max * 100)) + '%"></i></span><span class="ms-bar-lbl">' + labels[i] + '</span></div>';
            }).join('') + '</div>';
        };
        return bars(wd, WD, mw, 'ms-wd') +
            '<table class="a11y-sr-only"><caption>Minutes by weekday</caption><tbody>' + wd.map(function (v, i) { return '<tr><th scope="row">' + WD[i] + '</th><td>' + v + '</td></tr>'; }).join('') + '</tbody></table>' +
            bars(tod, ['Morning', 'Afternoon', 'Evening', 'Night'], mt, 'ms-tod');
    }
    function feel(rs) {
        var f = { hard: 0, right: 0, easy: 0 };
        rs.forEach(function (r) { if (r.feedback) { f.hard += r.feedback.hard || 0; f.right += r.feedback.right || 0; f.easy += r.feedback.easy || 0; } });
        var n = f.hard + f.right + f.easy;
        if (!n) { return '<p class="ms-empty">Rate drills during a session (too hard / just right / too easy) to see this.</p>'; }
        var seg = function (k, label, color) {
            var p = f[k] / n;
            return p ? '<span class="ms-feel-seg" style="flex:' + f[k] + ';background:' + color + '" title="' + label + ': ' + f[k] + '"></span>' : '';
        };
        return '<div class="ms-feel" role="img" aria-label="' + f.hard + ' too hard, ' + f.right + ' just right, ' + f.easy + ' too easy">' +
            seg('hard', 'Too hard', '#e34948') + seg('right', 'Just right', '#b9b7b0') + seg('easy', 'Too easy', '#2a78d6') + '</div>' +
            '<ul class="ms-feel-legend"><li><i style="background:#e34948"></i>Too hard <b>' + f.hard + '</b> <small>' + pct(f.hard / n) + '</small></li>' +
            '<li><i style="background:#b9b7b0"></i>Just right <b>' + f.right + '</b> <small>' + pct(f.right / n) + '</small></li>' +
            '<li><i style="background:#2a78d6"></i>Too easy <b>' + f.easy + '</b> <small>' + pct(f.easy / n) + '</small></li></ul>' +
            '<p class="ms-feel-note">' + (f.right / n >= 0.6 ? 'Well matched: most drills land just right.' : f.easy > f.hard ? 'Leaning easy - the coach is pushing intensity up.' : 'Leaning hard - the coach is easing intensity down.') + '</p>';
    }

    // ------------------------------------------------------------------ analysis
    function analysis(all, sl, k, kp) {
        var out = [], rs = sl.cur;
        if (!rs.length) { return [['📭', 'No sessions in this range yet. Try a longer range above.']]; }
        if (range !== 'all' && kp.minutes) {
            var ch = Math.round((k.minutes - kp.minutes) / kp.minutes * 100);
            out.push([ch >= 0 ? '📈' : '📉', 'You trained <b>' + Math.abs(ch) + '% ' + (ch >= 0 ? 'more' : 'less') + '</b> than the ' + (range === '28' ? 'previous 4 weeks' : 'previous 12 weeks') + ' (' + k.minutes + ' vs ' + kp.minutes + ' minutes).']);
        }
        out.push(['📅', 'Active on <b>' + k.activeDays + ' of ' + Math.min(sl.days, Math.ceil((Date.now() - new Date(all[0].date).getTime()) / DAY) + 1) + ' days</b>, about <b>' + (Math.round(rs.length / (sl.days / 7) * 10) / 10) + ' sessions a week</b>.']);
        var wd = [0, 0, 0, 0, 0, 0, 0], wdn = [0, 0, 0, 0, 0, 0, 0];
        rs.forEach(function (r) { var d = new Date(r.date).getDay(); wd[d] += CS.minutesOf(r); wdn[d]++; });
        var best = wd.indexOf(Math.max.apply(null, wd));
        if (wd[best]) { out.push(['⭐', '<b>' + ['Sundays', 'Mondays', 'Tuesdays', 'Wednesdays', 'Thursdays', 'Fridays', 'Saturdays'][best] + '</b> are your biggest day (' + wd[best] + ' minutes over ' + wdn[best] + ' session' + (wdn[best] === 1 ? '' : 's') + ').']); }
        // time of day vs finishing
        var tb = [[0, 0], [0, 0], [0, 0], [0, 0]];
        rs.forEach(function (r) { var b = bucket(new Date(r.date).getHours()); tb[b][0]++; if (r.completed) { tb[b][1]++; } });
        var names = ['morning', 'afternoon', 'evening', 'night'];
        var most = tb.map(function (x) { return x[0]; }); var mi = most.indexOf(Math.max.apply(null, most));
        var bestFinish = -1, bf = -1;
        tb.forEach(function (x, i) { if (x[0] >= 2 && x[1] / x[0] > bf) { bf = x[1] / x[0]; bestFinish = i; } });
        out.push(['🕒', 'You train most in the <b>' + names[mi] + '</b>' + (bestFinish >= 0 && bestFinish !== mi ? ', but you finish the most sessions in the <b>' + names[bestFinish] + '</b> (' + pct(bf) + ').' : '.')]);
        // session length sweet spot
        var short = rs.filter(function (r) { return Number(r.workoutLength) <= 45; }), long = rs.filter(function (r) { return Number(r.workoutLength) > 45; });
        if (short.length >= 2 && long.length >= 2) {
            var fs = short.filter(function (r) { return r.completed; }).length / short.length, fl = long.filter(function (r) { return r.completed; }).length / long.length;
            if (Math.abs(fs - fl) >= 0.15) { out.push(['⏱️', 'You finish <b>' + pct(fs) + '</b> of sessions up to 45 minutes and <b>' + pct(fl) + '</b> of longer ones. ' + (fs > fl ? 'Shorter sessions suit you right now.' : 'You go the distance - longer sessions work for you.')]); }
        }
        // readiness vs finishing
        var rd = { low: [0, 0], normal: [0, 0], high: [0, 0] };
        rs.forEach(function (r) { if (rd[r.readiness]) { rd[r.readiness][0]++; if (r.completed) { rd[r.readiness][1]++; } } });
        if (rd.low[0] >= 2 && rd.high[0] >= 2) {
            out.push(['🔋', 'On <b>Fired up</b> days you finish ' + pct(rd.high[1] / rd.high[0]) + ' of sessions; on <b>Low energy</b> days, ' + pct(rd.low[1] / rd.low[0]) + '. The coach already eases off when you are low.']);
        } else if (!rs.some(function (r) { return r.readiness; })) {
            out.push(['💬', 'Use the <b>How do you feel today?</b> check-in before sessions and this will show how energy affects your training.']);
        }
        // intensity trend
        var wi = rs.filter(function (r) { return typeof r.intensity === 'number'; });
        if (wi.length >= 4) {
            var half = Math.floor(wi.length / 2);
            var a = wi.slice(0, half).reduce(function (s, r) { return s + r.intensity; }, 0) / half;
            var b = wi.slice(half).reduce(function (s, r) { return s + r.intensity; }, 0) / (wi.length - half);
            if (Math.abs(b - a) >= 0.4) { out.push([b > a ? '🔥' : '🌿', 'Your training intensity has gone <b>' + (b > a ? 'up' : 'down') + '</b> recently (' + intensityWord(a).toLowerCase() + ' → ' + intensityWord(b).toLowerCase() + ').']); }
        }
        // projections
        var st = CS.compute(all);
        var spanDays = Math.max(7, Math.min(sl.days, (Date.now() - new Date(rs[0].date).getTime()) / DAY + 1));
        var xpRate = rs.reduce(function (s, r) { return s + CS.xpOf(r); }, 0) / spanDays;
        if (st.level.next && xpRate > 0) {
            var dl = Math.ceil((st.level.next.xp - st.xp) / xpRate);
            out.push(['🎯', 'At this pace you reach <b>' + st.level.next.name + '</b> level in about <b>' + dl + ' day' + (dl === 1 ? '' : 's') + '</b> (' + (st.level.next.xp - st.xp) + ' XP to go).']);
        }
        if (!st.rank.placed) { out.push(['🏅', '<b>' + st.rank.toGo + '</b> more session' + (st.rank.toGo === 1 ? '' : 's') + ' to finish placement and get your rank.']); }
        else if (st.rank.next) { out.push(['🏅', 'You are <b>' + esc(st.rank.label) + '</b>. ' + st.rank.pointsToNext + ' more OVR gets you <b>' + esc(st.rank.next) + '</b> - a streak day is worth up to 2.']); }
        return out;
    }

    function boot() {
        render();
        window.addEventListener('storage', function (e) { if (e.key === 'cognicoach-history') { render(); } });
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }
    window.CogniMyStats = { render: render };
})();
