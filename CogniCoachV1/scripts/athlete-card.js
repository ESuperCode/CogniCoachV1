// ==========================================================================
// Athlete Card (dashboard) - a holographic 3D card that tilts with the pointer:
// level, an overall rating built from consistency, volume and intensity, and
// the athlete's key numbers. Next to it, "Coach insights" read the adaptive
// coach data (readiness check-ins + drill ratings) saved with each session.
// "Download card" draws the card to a PNG (canvas) for sharing.
// Everything comes from localStorage['cognicoach-history'] - nothing is sent anywhere.
// ==========================================================================
(function () {
    'use strict';

    var LEVELS = [
        { name: 'Rookie', xp: 0 }, { name: 'Prospect', xp: 150 }, { name: 'Contender', xp: 400 },
        { name: 'Varsity', xp: 800 }, { name: 'All-Star', xp: 1400 }, { name: 'Pro', xp: 2300 },
        { name: 'Elite', xp: 3600 }, { name: 'Champion', xp: 5400 }, { name: 'Legend', xp: 8000 }
    ];
    var SAVED_PER_SESSION = 14;

    function history() {
        try { var h = JSON.parse(localStorage.getItem('cognicoach-history') || '[]'); return Array.isArray(h) ? h : []; } catch (e) { return []; }
    }
    function minutesOf(r) {
        var len = Number(r.workoutLength) || 0;
        if (r.drillsTotal > 0 && !r.completed) { len = Math.round(len * (r.drillsCompleted || 0) / r.drillsTotal); }
        return len;
    }
    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function dayKey(d) { d = new Date(d); return d.getFullYear() + '-' + d.getMonth() + '-' + d.getDate(); }

    function stats() {
        var h = history();
        var xp = h.reduce(function (s, r) { return s + minutesOf(r) + (r.completed ? 25 : 10); }, 0);
        var li = 0; while (li + 1 < LEVELS.length && xp >= LEVELS[li + 1].xp) { li++; }
        var minutes = h.reduce(function (s, r) { return s + minutesOf(r); }, 0);
        var days = {}; h.forEach(function (r) { days[dayKey(r.date)] = true; });
        var streak = 0, d = new Date();
        if (!days[dayKey(d)]) { d.setDate(d.getDate() - 1); }   // a streak is still alive until today ends
        while (days[dayKey(d)]) { streak++; d.setDate(d.getDate() - 1); }
        var sports = {}; h.forEach(function (r) { var s = r.sport || 'General'; sports[s] = (sports[s] || 0) + minutesOf(r); });
        var top = Object.keys(sports).sort(function (a, b) { return sports[b] - sports[a]; })[0] || '—';
        var weekAgo = Date.now() - 7 * 864e5;
        var weekMin = h.filter(function (r) { return new Date(r.date).getTime() >= weekAgo; }).reduce(function (s, r) { return s + minutesOf(r); }, 0);
        var withIntensity = h.filter(function (r) { return typeof r.intensity === 'number'; });
        var avgInt = withIntensity.length ? withIntensity.reduce(function (s, r) { return s + r.intensity; }, 0) / withIntensity.length : 0;
        var fb = { easy: 0, right: 0, hard: 0 };
        h.forEach(function (r) { if (r.feedback) { fb.easy += r.feedback.easy || 0; fb.right += r.feedback.right || 0; fb.hard += r.feedback.hard || 0; } });
        var ready = { low: 0, normal: 0, high: 0 };
        h.slice(-10).forEach(function (r) { if (r.readiness && ready[r.readiness] != null) { ready[r.readiness]++; } });
        var completion = h.length ? h.filter(function (r) { return r.completed; }).length / h.length : 0;
        // Overall: 50 to start, up to 99 - consistency, volume, finishing what you start, intensity.
        var ovr = 50 + Math.min(16, h.length * 1.2) + Math.min(14, streak * 2) + Math.min(10, weekMin / 25) + Math.round(completion * 6) + Math.max(-3, Math.round(avgInt * 3));
        ovr = Math.max(40, Math.min(99, Math.round(h.length ? ovr : 50)));
        return {
            h: h, xp: xp, level: LEVELS[li], next: LEVELS[li + 1] || null, levelIndex: li, minutes: minutes, sessions: h.length,
            streak: streak, top: top, weekMin: weekMin, saved: h.length * SAVED_PER_SESSION, ovr: ovr, avgInt: avgInt, fb: fb, ready: ready, completion: completion
        };
    }

    function athleteName() {
        try { var s = window.CogniAccount && window.CogniAccount.session(); if (s && s.username) { return s.username; } } catch (e) {}
        return 'Athlete';
    }
    function fmtSaved(min) { return min >= 60 ? (Math.round(min / 6) / 10) + ' h' : min + ' m'; }

    function insights(st) {
        var out = [];
        var rated = st.fb.easy + st.fb.right + st.fb.hard;
        if (!st.sessions) {
            out.push(['🚀', 'Finish your first session to unlock your rating and insights.']);
            return out;
        }
        if (rated >= 3) {
            if (st.fb.easy > st.fb.hard * 2) { out.push(['⬆️', 'You rate most drills too easy (' + st.fb.easy + ' of ' + rated + '). Raise your level in Advanced Setup.']); }
            else if (st.fb.hard > st.fb.easy * 2) { out.push(['🌿', 'Lots of drills feel too hard (' + st.fb.hard + ' of ' + rated + '). The coach is easing off - check in honestly before each session.']); }
            else { out.push(['🎯', 'Your drills are well matched: ' + st.fb.right + ' of ' + rated + ' rated just right.']); }
        } else {
            out.push(['💬', 'Rate drills as you go (too easy / just right / too hard) and the coach tunes every session to you.']);
        }
        if (st.ready.low >= 3) { out.push(['🔋', 'You checked in with low energy ' + st.ready.low + ' times lately. Sleep and recovery are training too.']); }
        if (st.streak >= 3) { out.push(['🔥', st.streak + '-day streak. Keep it alive with even a 15-minute session.']); }
        else if (st.sessions >= 2) { out.push(['📅', 'Consistency drives your rating most. Two short sessions beat one long one.']); }
        if (st.completion < 0.6 && st.sessions >= 3) { out.push(['⏱️', 'You finish ' + Math.round(st.completion * 100) + '% of sessions. Try shorter workouts so you can finish strong.']); }
        out.push(['⌛', 'CogniCoach has saved you about ' + fmtSaved(st.saved).replace(' h', ' hours').replace(' m', ' minutes') + ' of planning.']);
        return out.slice(0, 4);
    }

    // ------------------------------------------------------------------ render
    function render() {
        var anchor = document.getElementById('profileSummaryCard');
        if (!anchor) { return; }
        var st = stats();
        var host = document.getElementById('athleteCard');
        if (!host) {
            host = document.createElement('section');
            host.id = 'athleteCard';
            host.className = 'card dash-card dash-span-12 athlete-section';
            host.setAttribute('aria-labelledby', 'athleteCardTitle');
            anchor.parentNode.insertBefore(host, anchor);
        }
        var pct = st.next ? Math.round(100 * (st.xp - st.level.xp) / (st.next.xp - st.level.xp)) : 100;
        var name = athleteName();
        host.innerHTML =
            '<h2 class="card-title" id="athleteCardTitle">Athlete Card</h2>' +
            '<div class="ac-layout">' +
            '<div class="ac-stage">' +
            '  <div class="ac-card" tabindex="0" role="img" aria-label="' + esc(name) + ', ' + esc(st.level.name) + ', overall ' + st.ovr + '. ' + st.sessions + ' sessions, ' + st.minutes + ' minutes, ' + st.streak + ' day streak, top sport ' + esc(st.top) + '.">' +
            '    <div class="ac-face">' +
            '      <div class="ac-holo" aria-hidden="true"></div>' +
            '      <div class="ac-top"><div class="ac-ovr"><b>' + st.ovr + '</b><span>OVR</span></div><div class="ac-brand">CogniCoach<span>AI</span></div></div>' +
            '      <div class="ac-avatar" aria-hidden="true"><span>' + esc(name.charAt(0).toUpperCase()) + '</span></div>' +
            '      <div class="ac-name">' + esc(name) + '</div>' +
            '      <div class="ac-level">' + esc(st.level.name) + ' · ' + st.xp + ' XP</div>' +
            '      <div class="ac-xp" aria-hidden="true"><span style="width:' + pct + '%"></span></div>' +
            '      <div class="ac-grid">' +
            cell(st.sessions, 'Sessions') + cell(st.minutes, 'Minutes') + cell(st.streak, 'Streak') +
            cell(esc(st.top.length > 10 ? st.top.slice(0, 9) + '…' : st.top), 'Top sport') + cell(st.weekMin, 'This week') + cell(fmtSaved(st.saved), 'Saved') +
            '      </div>' +
            '    </div>' +
            '  </div>' +
            '  <button type="button" class="btn btn-secondary ac-download">Download card</button>' +
            '</div>' +
            '<div class="ac-insights"><h3>Coach insights</h3><ul>' +
            insights(st).map(function (i) { return '<li><span class="ac-ins-icon" aria-hidden="true">' + i[0] + '</span><span>' + esc(i[1]) + '</span></li>'; }).join('') +
            '</ul>' +
            '<div class="ac-meters">' + meter('Intensity you train at', (st.avgInt + 2) / 4, st.sessions ? (st.avgInt > 0.4 ? 'Pushing' : st.avgInt < -0.4 ? 'Easing' : 'Balanced') : '—') +
            meter('Sessions finished', st.completion, st.sessions ? Math.round(st.completion * 100) + '%' : '—') + '</div>' +
            '</div>' +
            '</div>';
        wireTilt(host.querySelector('.ac-card'));
        host.querySelector('.ac-download').addEventListener('click', function () { download(st, name); });
        if (location.hash === '#athleteCard') { setTimeout(function () { host.scrollIntoView({ block: 'start' }); }, 200); }
    }
    function cell(v, l) { return '<div class="ac-cell"><b>' + v + '</b><span>' + l + '</span></div>'; }
    function meter(label, frac, word) {
        frac = Math.max(0, Math.min(1, frac || 0));
        return '<div class="ac-meter"><div class="ac-meter-row"><span>' + label + '</span><b>' + word + '</b></div>' +
            '<div class="ac-meter-bar" aria-hidden="true"><span style="width:' + Math.round(frac * 100) + '%"></span></div></div>';
    }

    // ------------------------------------------------------------------ 3D tilt + holo light
    function wireTilt(card) {
        if (!card) { return; }
        var reduce = function () { return document.documentElement.classList.contains('a11y-reduce-motion'); };
        var raf = 0;
        function set(x, y) {   // x, y in 0..1
            card.style.setProperty('--rx', ((0.5 - y) * 22).toFixed(2) + 'deg');
            card.style.setProperty('--ry', ((x - 0.5) * 26).toFixed(2) + 'deg');
            card.style.setProperty('--mx', (x * 100).toFixed(1) + '%');
            card.style.setProperty('--my', (y * 100).toFixed(1) + '%');
        }
        card.addEventListener('pointermove', function (e) {
            if (reduce()) { return; }
            var r = card.getBoundingClientRect();
            var x = (e.clientX - r.left) / r.width, y = (e.clientY - r.top) / r.height;
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(function () { card.classList.add('ac-live'); set(x, y); });
        });
        card.addEventListener('pointerleave', function () { card.classList.remove('ac-live'); set(0.5, 0.5); });
        set(0.5, 0.5);
    }

    // ------------------------------------------------------------------ PNG export
    function download(st, name) {
        var W = 720, H = 1000, c = document.createElement('canvas');
        c.width = W; c.height = H;
        var g = c.getContext('2d');
        var rr = function (x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); };
        var bg = g.createLinearGradient(0, 0, W, H);
        bg.addColorStop(0, '#0d2a52'); bg.addColorStop(0.55, '#173d72'); bg.addColorStop(1, '#5a2c0e');
        rr(0, 0, W, H, 48); g.fillStyle = bg; g.fill();
        var holo = g.createLinearGradient(0, 0, W, H);
        holo.addColorStop(0, 'rgba(78,168,255,0.35)'); holo.addColorStop(0.5, 'rgba(255,255,255,0.05)'); holo.addColorStop(1, 'rgba(255,138,52,0.35)');
        g.fillStyle = holo; g.fill();
        g.strokeStyle = 'rgba(255,255,255,0.35)'; g.lineWidth = 6; rr(14, 14, W - 28, H - 28, 38); g.stroke();
        g.fillStyle = '#fff'; g.textBaseline = 'alphabetic';
        g.font = '900 120px Orbitron, sans-serif'; g.fillText(String(st.ovr), 60, 170);
        g.font = '700 32px Orbitron, sans-serif'; g.fillStyle = '#ffb979'; g.fillText('OVR', 66, 214);
        g.textAlign = 'right'; g.fillStyle = '#cfe3ff'; g.font = '700 30px Orbitron, sans-serif'; g.fillText('CogniCoachAI', W - 60, 110);
        g.textAlign = 'center';
        var av = g.createRadialGradient(W / 2 - 30, 330, 10, W / 2, 360, 120);
        av.addColorStop(0, '#7cc0ff'); av.addColorStop(1, '#1a6dcc');
        g.beginPath(); g.arc(W / 2, 360, 110, 0, Math.PI * 2); g.fillStyle = av; g.fill();
        g.lineWidth = 8; g.strokeStyle = '#ff8a34'; g.stroke();
        g.fillStyle = '#fff'; g.font = '900 110px Orbitron, sans-serif'; g.fillText(name.charAt(0).toUpperCase(), W / 2, 400);
        var nm = name.length > 16 ? name.slice(0, 15) + '…' : name, ns = 54;
        g.font = '700 ' + ns + 'px Orbitron, sans-serif';
        while (ns > 28 && g.measureText(nm).width > W - 120) { ns -= 2; g.font = '700 ' + ns + 'px Orbitron, sans-serif'; }
        g.fillText(nm, W / 2, 550);
        g.font = '400 32px "Space Mono", monospace'; g.fillStyle = '#ffd3ad'; g.fillText(st.level.name + ' · ' + st.xp + ' XP', W / 2, 600);
        var cells = [[st.sessions, 'SESSIONS'], [st.minutes, 'MINUTES'], [st.streak, 'STREAK'], [st.top.length > 14 ? st.top.slice(0, 13) + '…' : st.top, 'TOP SPORT'], [st.weekMin, 'THIS WEEK'], [fmtSaved(st.saved), 'SAVED']];
        cells.forEach(function (cl, i) {
            var cx = 60 + (i % 3) * 200, cy = 660 + Math.floor(i / 3) * 140;
            rr(cx, cy, 180, 120, 22); g.fillStyle = 'rgba(255,255,255,0.1)'; g.fill();
            g.fillStyle = '#fff';
            var size = 40; g.font = '700 ' + size + 'px Orbitron, sans-serif';
            while (size > 18 && g.measureText(String(cl[0])).width > 160) { size -= 2; g.font = '700 ' + size + 'px Orbitron, sans-serif'; }
            g.fillText(String(cl[0]), cx + 90, cy + 62);
            g.fillStyle = '#a9c4e6'; g.font = '400 20px "Space Mono", monospace'; g.fillText(cl[1], cx + 90, cy + 98);
        });
        g.fillStyle = '#9fb4d3'; g.font = '400 22px "Space Mono", monospace'; g.fillText('cognicoachai.com', W / 2, H - 46);
        c.toBlob(function (blob) {
            if (!blob) { return; }
            var a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'cognicoach-athlete-card.png';
            document.body.appendChild(a); a.click(); a.remove();
            setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
        }, 'image/png');
    }

    function boot() {
        render();
        window.addEventListener('cognicoach:account', function () { render(); });
        window.addEventListener('storage', function (e) { if (e.key === 'cognicoach-history') { render(); } });
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }
    window.CogniAthleteCard = { render: render };
})();
