// ==========================================================================
// Dashboard extras: athlete level (XP), personal records, weekly minutes chart, training mix,
// recent sessions, and the account & data card (sign-in sync, export / import).
// Reads the same localStorage['cognicoach-history'] records as scripts/dashboard.js.
// ==========================================================================
(function () {
    'use strict';

    var LEVELS = [
        { name: 'Rookie', xp: 0 }, { name: 'Prospect', xp: 150 }, { name: 'Contender', xp: 400 },
        { name: 'Varsity', xp: 800 }, { name: 'All-Star', xp: 1400 }, { name: 'Pro', xp: 2300 },
        { name: 'Elite', xp: 3600 }, { name: 'Champion', xp: 5400 }, { name: 'Legend', xp: 8000 }
    ];

    function history() {
        try { var h = JSON.parse(localStorage.getItem('cognicoach-history') || '[]'); return Array.isArray(h) ? h : []; }
        catch (e) { return []; }
    }
    function minutesOf(r) {
        var len = Number(r.workoutLength) || 0;
        if (r.drillsTotal > 0 && !r.completed) { len = Math.round(len * (r.drillsCompleted || 0) / r.drillsTotal); }
        return len;
    }
    function pic(n, s) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: s }) : ''; }
    function esc(t) {
        return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function startOfWeek(d) { var c = new Date(d); c.setHours(0, 0, 0, 0); c.setDate(c.getDate() - c.getDay()); return c; }
    function shortDate(d) { return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); }

    // ---------------------------------------------------------------- XP / level
    function xpOf(h) {
        // stored per session since the economy update (boosts); plus bonus XP from chests
        var bonus = 0;
        try { bonus = Number(JSON.parse(localStorage.getItem('cognicoach-wallet') || '{}').bonusXp) || 0; } catch (e) {}
        return h.reduce(function (s, r) { return s + (typeof r.xp === 'number' ? r.xp : minutesOf(r) + (r.completed ? 25 : 10)); }, 0) + bonus;
    }
    function renderLevel(h) {
        var el = document.getElementById('levelCard');
        if (!el) { return; }
        var xp = xpOf(h);
        var i = 0;
        while (i + 1 < LEVELS.length && xp >= LEVELS[i + 1].xp) { i++; }
        var cur = LEVELS[i], next = LEVELS[i + 1];
        var pct = next ? (xp - cur.xp) / (next.xp - cur.xp) : 1;
        el.innerHTML =
            '<h2 class="card-title">Athlete level</h2>' +
            '<div class="lvl-row"><div class="lvl-badge" aria-hidden="true">' + (i + 1) + '</div>' +
            '<div class="lvl-main"><div class="lvl-name">Level ' + (i + 1) + ' \u00b7 ' + cur.name + '</div>' +
            '<div class="lvl-bar" role="progressbar" aria-label="Progress to the next level" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round(pct * 100) + '"><i style="width:' + Math.round(pct * 100) + '%"></i></div>' +
            '<div class="level-xp"><b>' + xp.toLocaleString() + ' XP</b>' +
            (next ? ' \u00b7 ' + (next.xp - xp).toLocaleString() + ' to <b>' + next.name + '</b>' : ' \u00b7 max level') + '</div></div></div>' +
            '<div class="level-hint">XP comes from every minute you train, plus a bonus for finishing.</div>';
    }

    // ---------------------------------------------------------------- records
    function renderRecords(h) {
        var el = document.getElementById('recordsGrid');
        if (!el) { return; }
        var totalMin = h.reduce(function (s, r) { return s + minutesOf(r); }, 0);
        var longest = h.reduce(function (m, r) { return Math.max(m, minutesOf(r)); }, 0);
        var mostDrills = h.reduce(function (m, r) { return Math.max(m, r.drillsCompleted || 0); }, 0);
        var weeks = {};
        h.forEach(function (r) { var k = startOfWeek(new Date(r.date)).getTime(); weeks[k] = (weeks[k] || 0) + minutesOf(r); });
        var bestWeek = Object.keys(weeks).reduce(function (m, k) { return Math.max(m, weeks[k]); }, 0);
        var done = h.filter(function (r) { return r.completed; }).length;
        var rate = h.length ? Math.round(100 * done / h.length) : 0;
        var sports = {};
        h.forEach(function (r) { if (r.sport) { sports[r.sport.trim().toLowerCase()] = 1; } });
        var tiles = [
            ['stopwatch', (totalMin / 60).toFixed(totalMin >= 600 ? 0 : 1), 'Hours trained'],
            ['dumbbell', longest + ' min', 'Longest session'],
            ['calendar', bestWeek + ' min', 'Best week'],
            ['target', mostDrills, 'Most drills in a session'],
            ['check-circle', rate + '%', 'Sessions finished'],
            ['globe', Object.keys(sports).length, 'Sports trained']
        ];
        el.innerHTML = tiles.map(function (t, i) {
            return '<div class="record-tile" style="animation-delay:' + (i * 60) + 'ms"><span class="record-icon" aria-hidden="true">' + pic(t[0], 26) +
                '</span><div class="record-value">' + esc(t[1]) + '</div><div class="stat-label">' + t[2] + '</div></div>';
        }).join('');
    }

    // ---------------------------------------------------------------- weekly minutes (single series bars)
    function renderWeekly(h) {
        var el = document.getElementById('weeklyChart');
        if (!el) { return; }
        var N = 10, now = startOfWeek(new Date()), weeks = [];
        for (var i = N - 1; i >= 0; i--) { var d = new Date(now); d.setDate(d.getDate() - 7 * i); weeks.push({ start: d, min: 0, n: 0 }); }
        h.forEach(function (r) {
            var t = startOfWeek(new Date(r.date)).getTime();
            weeks.forEach(function (w) { if (w.start.getTime() === t) { w.min += minutesOf(r); w.n++; } });
        });
        var max = Math.max(30, Math.max.apply(null, weeks.map(function (w) { return w.min; })));
        var nice = Math.ceil(max / 30) * 30;
        var W = 560, H = 220, L = 34, B = 26, T = 14, plotW = W - L - 6, plotH = H - B - T, gap = 10;
        var bw = (plotW - gap * (N - 1)) / N;
        var grid = '', bars = '', labels = '';
        [0, 0.5, 1].forEach(function (f) {
            var y = T + plotH * (1 - f);
            grid += '<line x1="' + L + '" x2="' + (W - 6) + '" y1="' + y + '" y2="' + y + '" class="chart-grid"/>' +
                '<text x="' + (L - 6) + '" y="' + (y + 4) + '" class="chart-axis" text-anchor="end">' + Math.round(nice * f) + '</text>';
        });
        weeks.forEach(function (w, k) {
            var x = L + k * (bw + gap), bh = w.min ? Math.max(4, plotH * w.min / nice) : 0, y = T + plotH - bh;
            var tip = 'Week of ' + shortDate(w.start) + ': ' + w.min + ' min · ' + w.n + ' session' + (w.n === 1 ? '' : 's');
            bars += '<g class="bar-g" data-tip="' + esc(tip) + '">' +
                '<rect class="bar-hit" x="' + (x - gap / 2) + '" y="' + T + '" width="' + (bw + gap) + '" height="' + plotH + '"/>' +
                (bh ? '<path class="bar" style="animation-delay:' + (k * 50) + 'ms" d="M' + x + ',' + (T + plotH) + 'V' + (y + 4) + 'q0,-4 4,-4h' + (bw - 8) + 'q4,0 4,4V' + (T + plotH) + 'Z"/>' : '') +
                (w.min && k === N - 1 ? '<text class="chart-value" x="' + (x + bw / 2) + '" y="' + (y - 6) + '" text-anchor="middle">' + w.min + '</text>' : '') +
                '</g>';
            if (k % 2 === (N - 1) % 2) {
                labels += '<text x="' + (x + bw / 2) + '" y="' + (H - 6) + '" class="chart-axis" text-anchor="middle">' + (k === N - 1 ? 'This wk' : shortDate(w.start)) + '</text>';
            }
        });
        var total = weeks.reduce(function (s, w) { return s + w.min; }, 0);
        el.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" class="chart-svg" role="img" aria-label="Minutes trained per week for the last ' + N + ' weeks, ' + total + ' minutes in total">' +
            grid + bars + labels + '<line x1="' + L + '" x2="' + (W - 6) + '" y1="' + (T + plotH) + '" y2="' + (T + plotH) + '" class="chart-base"/></svg>';
        wireTips(el);
    }

    // ---------------------------------------------------------------- training mix (sport / focus)
    var mixBy = 'sport';
    function renderMix(h) {
        var el = document.getElementById('mixChart');
        if (!el) { return; }
        var by = {};
        h.forEach(function (r) {
            var k = String((mixBy === 'sport' ? r.sport : r.focus) || '').trim() || (mixBy === 'sport' ? 'General' : 'General');
            k = k.charAt(0).toUpperCase() + k.slice(1);
            by[k] = (by[k] || 0) + minutesOf(r);
        });
        var rows = Object.keys(by).map(function (k) { return [k, by[k]]; }).sort(function (a, b) { return b[1] - a[1]; });
        if (rows.length > 6) {
            var other = rows.slice(5).reduce(function (s, r) { return s + r[1]; }, 0);
            rows = rows.slice(0, 5).concat([['Other', other]]);
        }
        var total = rows.reduce(function (s, r) { return s + r[1]; }, 0) || 1;
        var max = rows.length ? rows[0][1] || 1 : 1;
        el.innerHTML = rows.length ? rows.map(function (r, i) {
            var pct = Math.round(100 * r[1] / total);
            return '<div class="mix-row" data-tip="' + esc(r[0] + ': ' + r[1] + ' min (' + pct + '%)') + '">' +
                '<div class="mix-label"><span>' + esc(r[0]) + '</span><b>' + pct + '%</b></div>' +
                '<div class="mix-track"><i style="--w:' + (100 * r[1] / max).toFixed(1) + '%;animation-delay:' + (i * 70) + 'ms"></i></div></div>';
        }).join('') : '<p class="dash-muted">Finish a session to see your mix.</p>';
        wireTips(el);
    }

    // ---------------------------------------------------------------- recent sessions
    var sportFilter = '';
    function renderSessions(h) {
        var el = document.getElementById('sessionsTable');
        var sel = document.getElementById('sessionsFilter');
        if (!el || !sel) { return; }
        var sports = {};
        h.forEach(function (r) { if (r.sport) { sports[r.sport] = 1; } });
        var opts = '<option value="">All sports</option>' + Object.keys(sports).sort().map(function (s) {
            return '<option value="' + esc(s) + '"' + (s === sportFilter ? ' selected' : '') + '>' + esc(s) + '</option>';
        }).join('');
        sel.innerHTML = opts;
        var rows = h.filter(function (r) { return !sportFilter || r.sport === sportFilter; }).slice().reverse().slice(0, 12);
        el.innerHTML = rows.length ?
            '<table class="sessions"><thead><tr><th>Date</th><th>Sport</th><th>Focus</th><th class="num">Minutes</th><th class="num">Drills</th><th>Status</th></tr></thead><tbody>' +
            rows.map(function (r) {
                var d = new Date(r.date);
                return '<tr><td class="s-date">' + esc(d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: d.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined })) +
                    '</td><td class="s-sport">' + esc(r.sport || '—') + '</td><td class="s-focus" data-label="Focus">' + esc(r.focus || '—') + '</td><td class="num s-min" data-label="Minutes">' + minutesOf(r) +
                    '</td><td class="num s-drills" data-label="Drills">' + (r.drillsCompleted || 0) + '/' + (r.drillsTotal || 0) + '</td><td class="s-status">' +
                    (r.completed ? '<span class="pill done">' + pic('check', 12) + ' Finished</span>' : '<span class="pill partial">' + pic('half-circle', 12) + ' Partial</span>') + '</td></tr>';
            }).join('') + '</tbody></table>' : '<p class="dash-muted">No sessions yet.</p>';
    }

    // ---------------------------------------------------------------- account & data
    function renderAccount() {
        var el = document.getElementById('accountCardBody');
        if (!el) { return; }
        var A = window.CogniAccount;
        var s = A && A.session();
        if (s) {
            el.innerHTML =
                '<div class="acct-panel signed-in">' +
                '  <span class="acct-panel-avatar">' + esc(s.username.charAt(0).toUpperCase()) + '</span>' +
                '  <div class="acct-panel-text"><div class="acct-panel-title">' + esc(s.username) + '</div>' +
                '    <div class="acct-panel-sub"><i class="sync-dot-inline"></i><span id="dashSyncStatus">' + esc(A.statusText()) + '</span></div>' +
                '    <p>Profile, history, dashboard, Competition notes and saved animations sync to this account.</p></div>' +
                '  <div class="acct-panel-actions"><button class="dash-btn primary" id="dashSyncBtn" type="button">Sync now</button></div>' +
                '</div>';
        } else {
            el.innerHTML =
                '<div class="acct-panel">' +
                '  <div class="acct-panel-icon" aria-hidden="true"><span class="cloud"></span><span class="arrow"></span></div>' +
                '  <div class="acct-panel-text"><div class="acct-panel-title">Train on any device</div>' +
                '    <p>Create a free account to back up everything on this device and pick up where you left off on your phone or another computer.</p>' +
                '    <ul class="acct-perks"><li>Profile &amp; level</li><li>Session history</li><li>Competition notes</li><li>Saved animations</li></ul></div>' +
                '  <div class="acct-panel-actions">' +
                '    <button class="dash-btn primary" id="dashSignUpBtn" type="button">Create free account</button>' +
                '    <button class="dash-link" id="dashSignInBtn" type="button">I already have an account</button></div>' +
                '</div>';
        }
        var b1 = document.getElementById('dashSyncBtn');
        if (b1) { b1.onclick = function () { A.syncNow(); }; }
        var b2 = document.getElementById('dashSignUpBtn');
        if (b2) { b2.onclick = function () { A.open('signup'); }; }
        var b3 = document.getElementById('dashSignInBtn');
        if (b3) { b3.onclick = function () { A.open('login'); }; }
        var dot = el.querySelector('.sync-dot-inline');
        if (dot && A) { dot.className = 'sync-dot-inline ' + A.status().state; }
    }

    function importData(file) {
        var reader = new FileReader();
        reader.onload = function () {
            try {
                var data = JSON.parse(reader.result);
                var incoming = Array.isArray(data.history) ? data.history : [];
                var seen = {}, merged = [];
                history().concat(incoming).forEach(function (r) {
                    var k = (r && r.date) + '|' + (r && r.sport);
                    if (r && r.date && !seen[k]) { seen[k] = 1; merged.push(r); }
                });
                merged.sort(function (a, b) { return new Date(a.date) - new Date(b.date); });
                localStorage.setItem('cognicoach-history', JSON.stringify(merged));
                if (data.settings && typeof data.settings === 'object') { localStorage.setItem('cognicoach-dashboard', JSON.stringify(data.settings)); }
                if (data.profile && typeof data.profile === 'object') { localStorage.setItem('cognicoach-profile', JSON.stringify(data.profile)); }
                if (data.coach && typeof data.coach === 'object') { localStorage.setItem('cognicoach-coach', JSON.stringify(data.coach)); document.dispatchEvent(new CustomEvent('cognicoach:coach')); }
                refreshAll();
                toast('Import done - ' + merged.length + ' sessions in your history.', 'ok');
            } catch (e) {
                toast("That file isn't a CogniCoach export.", 'warn');
            }
        };
        reader.readAsText(file);
    }

    function toast(t, k) { if (window.CogniAccount) { window.CogniAccount.toast(t, k); } else { alert(t); } }

    // ---------------------------------------------------------------- tooltip
    var tipEl = null;
    function wireTips(root) {
        if (!tipEl) {
            tipEl = document.createElement('div');
            tipEl.className = 'chart-tip';
            document.body.appendChild(tipEl);
        }
        root.querySelectorAll('[data-tip]').forEach(function (n) {
            n.addEventListener('pointerenter', function (e) { if (e.pointerType && e.pointerType !== 'mouse') { return; } tipEl.textContent = n.getAttribute('data-tip'); tipEl.classList.add('show'); n.classList.add('hover'); });
            n.addEventListener('pointermove', function (e) {
                if (e.pointerType && e.pointerType !== 'mouse') { return; }
                var x = Math.min(window.innerWidth - tipEl.offsetWidth - 8, e.clientX + 14);
                tipEl.style.transform = 'translate(' + Math.max(8, x) + 'px,' + (e.clientY - 40) + 'px)';
            });
            n.addEventListener('pointerleave', function () { tipEl.classList.remove('show'); n.classList.remove('hover'); });
        });
    }

    function refreshAll() {
        var h = history();
        renderLevel(h);
        renderRecords(h);
        renderWeekly(h);
        renderMix(h);
        renderSessions(h);
        renderAccount();
        if (typeof renderAll === 'function') { renderAll(); }
    }

    document.addEventListener('DOMContentLoaded', function () {
        refreshAll();
        var sel = document.getElementById('sessionsFilter');
        if (sel) { sel.addEventListener('change', function () { sportFilter = sel.value; renderSessions(history()); }); }
        document.querySelectorAll('[data-mix]').forEach(function (b) {
            b.addEventListener('click', function () {
                mixBy = b.getAttribute('data-mix');
                document.querySelectorAll('[data-mix]').forEach(function (x) { x.classList.toggle('active', x === b); });
                renderMix(history());
            });
        });
        var imp = document.getElementById('importDataInput');
        if (imp) { imp.addEventListener('change', function () { if (imp.files[0]) { importData(imp.files[0]); } imp.value = ''; }); }
        var impBtn = document.getElementById('importDataBtn');
        if (impBtn) { impBtn.addEventListener('click', function () { imp.click(); }); }
        window.addEventListener('cognicoach:synced', refreshAll);
        window.addEventListener('cognicoach:account', renderAccount);
        var wait = setInterval(function () {   // account.js loads after this file
            if (window.CogniAccount) {
                clearInterval(wait);
                renderAccount();
                window.CogniAccount.onStatus(function () {
                    var st = document.getElementById('dashSyncStatus');
                    if (st) { st.textContent = window.CogniAccount.statusText(); }
                    var dot = document.querySelector('#accountCardBody .sync-dot-inline');
                    if (dot) { dot.className = 'sync-dot-inline ' + window.CogniAccount.status().state; }
                });
            }
        }, 100);
        setTimeout(function () { clearInterval(wait); }, 10000);
    });
})();
