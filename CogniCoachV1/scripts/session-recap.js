// ==========================================================================
// Session recap - replaces the plain "Session Complete" card with a coach's
// debrief: drills done, minutes, XP earned and level progress, streak, the
// planning time CogniCoach saved, how the athlete rated the drills, and one
// piece of advice for next time. A short confetti burst (skipped with reduced
// motion). Reads the record script.js just saved to localStorage history.
// ==========================================================================
(function () {
    'use strict';

    // Same level ladder and XP rule as the dashboard (scripts/dashboard-plus.js).
    var LEVELS = [
        { name: 'Rookie', xp: 0 }, { name: 'Prospect', xp: 150 }, { name: 'Contender', xp: 400 },
        { name: 'Varsity', xp: 800 }, { name: 'All-Star', xp: 1400 }, { name: 'Pro', xp: 2300 },
        { name: 'Elite', xp: 3600 }, { name: 'Champion', xp: 5400 }, { name: 'Legend', xp: 8000 }
    ];
    var PLANNING_MINUTES_SAVED = 14;   // the About page's "Saves 14min+ of workout planning time"

    function history() {
        try { var h = JSON.parse(localStorage.getItem('cognicoach-history') || '[]'); return Array.isArray(h) ? h : []; } catch (e) { return []; }
    }
    function minutesOf(r) {
        var len = Number(r.workoutLength) || 0;
        if (r.drillsTotal > 0 && !r.completed) { len = Math.round(len * (r.drillsCompleted || 0) / r.drillsTotal); }
        return len;
    }
    function xpOfRecord(r) { return typeof r.xp === 'number' ? r.xp : minutesOf(r) + (r.completed ? 25 : 10); }
    function levelFor(xp) {
        var i = 0;
        while (i + 1 < LEVELS.length && xp >= LEVELS[i + 1].xp) { i++; }
        return { index: i, cur: LEVELS[i], next: LEVELS[i + 1] || null };
    }
    function dayKey(d) { d = new Date(d); return d.getFullYear() + '-' + d.getMonth() + '-' + d.getDate(); }
    function streak(h) {
        var days = {};
        h.forEach(function (r) { days[dayKey(r.date)] = true; });
        var n = 0, d = new Date();
        while (days[dayKey(d)]) { n++; d.setDate(d.getDate() - 1); }
        return n;
    }
    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

    function advice(rec) {
        var f = rec.feedback || {};
        var rated = (f.hard || 0) + (f.right || 0) + (f.easy || 0);
        if (rated && f.easy > f.hard && f.easy >= rated / 2) {
            return rec.readiness === 'high'
                ? 'Even fired up, this felt light. Raise your level in Advanced Setup and the coach will start you higher.'
                : 'You found this one light. Next session, pick “Fired up” before you start or raise your level in Advanced Setup.';
        }
        if (rated && f.hard > f.easy && f.hard >= rated / 2) { return 'That was a grind. Good work. Sleep and water now, and try “Low energy” next time if you are still sore.'; }
        if (rec.readiness === 'low') { return 'You trained on a low-energy day. That is how consistency is built. Get some recovery in before the next one.'; }
        if (rated) { return 'Your ratings tuned this session as you went. Keep rating drills and the coach keeps getting sharper.'; }
        return 'Tip: rate each drill (too easy / just right / too hard) and the coach will adjust the next ones for you.';
    }

    // ------------------------------------------------------------------ confetti
    function confetti(host) {
        if (document.documentElement.classList.contains('a11y-reduce-motion')) { return; }
        var c = document.createElement('canvas');
        c.className = 'recap-confetti';
        c.setAttribute('aria-hidden', 'true');
        host.appendChild(c);
        var ctx = c.getContext('2d');
        var dpr = Math.min(2, window.devicePixelRatio || 1);
        var w = c.width = host.clientWidth * dpr, hgt = c.height = host.clientHeight * dpr;
        var colors = ['#4ea8ff', '#ff8a34', '#ffd34d', '#1a6dcc', '#34c38f'];
        var parts = [];
        for (var i = 0; i < 140; i++) {
            parts.push({ x: w / 2 + (Math.random() - 0.5) * w * 0.3, y: hgt * 0.3, vx: (Math.random() - 0.5) * 14 * dpr, vy: (-6 - Math.random() * 10) * dpr,
                r: (4 + Math.random() * 5) * dpr, rot: Math.random() * 6, vr: (Math.random() - 0.5) * 0.4, c: colors[i % colors.length] });
        }
        var t0 = performance.now();
        (function frame(t) {
            var age = t - t0;
            ctx.clearRect(0, 0, w, hgt);
            parts.forEach(function (p) {
                p.vy += 0.35 * dpr; p.vx *= 0.99; p.x += p.vx; p.y += p.vy; p.rot += p.vr;
                ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.rot);
                ctx.globalAlpha = Math.max(0, 1 - age / 2600);
                ctx.fillStyle = p.c; ctx.fillRect(-p.r / 2, -p.r / 4, p.r, p.r / 2);
                ctx.restore();
            });
            if (age < 2600) { requestAnimationFrame(frame); } else { c.remove(); }
        })(t0);
    }

    // ------------------------------------------------------------------ render
    function render() {
        var card = document.querySelector('#sessionComplete .card');
        if (!card) { return; }
        var h = history();
        var rec = h[h.length - 1];
        if (!rec || Date.now() - new Date(rec.date).getTime() > 5 * 60 * 1000) { return; }

        var earned = xpOfRecord(rec);
        var E = window.CogniEconomy, rw = window.__lastSessionReward || null;
        var total = E ? E.totalXp() : h.reduce(function (s, r) { return s + xpOfRecord(r); }, 0);
        var before = levelFor(total - earned), after = levelFor(total);
        var lv = after;
        var pct = lv.next ? Math.round(100 * (total - lv.cur.xp) / (lv.next.xp - lv.cur.xp)) : 100;
        var mins = minutesOf(rec);
        var savedTotal = h.length * PLANNING_MINUTES_SAVED;
        var st = E ? E.streakInfo().current : streak(h);
        var f = rec.feedback || {};
        var rated = (f.hard || 0) + (f.right || 0) + (f.easy || 0);
        var readyWord = { low: 'Low energy', normal: 'Normal', high: 'Fired up' }[rec.readiness] || '';

        card.classList.add('recap');
        card.innerHTML =
            '<div class="recap-medal" aria-hidden="true"><div class="recap-coin">' + icon('trophy-gold', 58) + '</div></div>' +
            '<h2 class="recap-title" tabindex="-1">Session complete</h2>' +
            '<p class="recap-sub">' + esc(rec.sport) + (rec.focus && rec.focus !== 'General' ? ' · ' + esc(rec.focus) : '') + '</p>' +
            (before.index !== after.index ? '<p class="recap-levelup" role="status">Level up! You are now <b>' + esc(after.cur.name) + '</b></p>' : '') +
            rankLine(h) +
            '<div class="recap-grid">' +
            tile(rec.drillsCompleted + '/' + rec.drillsTotal, 'Drills done') +
            tile(mins, 'Minutes trained') +
            tile('+' + earned, 'XP earned') +
            tile(st + (st === 1 ? ' day' : ' days'), 'Streak') +
            '</div>' +
            rewards(rw) +
            '<div class="recap-level"><div class="recap-level-row"><span><b>' + esc(lv.cur.name) + '</b> · ' + total + ' XP</span>' +
            '<span>' + (lv.next ? (lv.next.xp - total) + ' XP to ' + esc(lv.next.name) : 'Top level') + '</span></div>' +
            '<div class="recap-bar" role="progressbar" aria-label="Progress to next level" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + pct + '"><span style="width:' + pct + '%"></span></div></div>' +
            '<div class="recap-saved"><span class="recap-saved-num">' + PLANNING_MINUTES_SAVED + ' min</span> of planning saved today · <b>' +
            (savedTotal >= 60 ? (Math.round(savedTotal / 6) / 10) + ' hours' : savedTotal + ' min') + '</b> saved in total</div>' +
            (rated || readyWord ? '<p class="recap-ratings">' + (readyWord ? 'Started feeling: <b>' + readyWord + '</b>. ' : '') +
                (rated ? 'You rated ' + rated + ' drill' + (rated === 1 ? '' : 's') + ': ' +
                    [f.easy ? f.easy + ' too easy' : '', f.right ? f.right + ' just right' : '', f.hard ? f.hard + ' too hard' : ''].filter(Boolean).join(', ') + '.' : '') + '</p>' : '') +
            '<div class="recap-advice"><span class="recap-advice-label">Coach’s note</span>' + esc(advice(rec)) + '</div>' +
            '<div class="recap-actions">' +
            '<button class="btn btn-primary" type="button" onclick="returnToSetup()">Start new session</button>' +
            '<a class="btn btn-secondary" href="dashboard.html#athleteCard">See your Athlete Card</a>' +
            '</div>';
        var title = card.querySelector('.recap-title');
        if (title) { title.focus({ preventScroll: true }); }
        card.scrollIntoView({ block: 'start', behavior: 'smooth' });
        confetti(card);
        var ob = card.querySelector('[data-open-chests]');
        if (ob && window.CogniEconomyUI) {
            ob.addEventListener('click', function () {
                var ids = (rw && rw.chests || []).map(function (c) { return c.id; });
                window.CogniEconomyUI.openChests(ids, function () { var b = card.querySelector('.recap-rewards [data-open-chests]'); if (b) { b.disabled = true; b.textContent = 'Opened'; } });
            });
        }
    }

    function icon(n, s) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: s || 24 }) : ''; }

    // XP (with boost), coins, chests and today's goal/quests from scripts/economy.js
    function rewards(rw) {
        var E = window.CogniEconomy;
        if (!rw || !E) { return ''; }
        var q = E.quests(), claim = E.claimableCount();
        var C = 2 * Math.PI * 15, frac = Math.min(1, q.goal ? q.todayXp / q.goal : 0);
        var chestIcons = rw.chests.map(function (c) { return icon('chest-' + c.tier, 40); }).join('');
        return '<div class="recap-rewards">' +
            '<div class="rr-item">' + icon('xp', 40) + '<div><b>+' + rw.xp + ' XP</b>' + (rw.mult > 1 ? '<span class="rr-boost">' + icon('boost', 16) + ' ' + rw.mult + 'x boost</span>' : '<small>' + rw.base + ' base</small>') + '</div></div>' +
            '<div class="rr-item">' + icon('coin', 40) + '<div><b>+' + (rw.coins + rw.levelCoins) + '</b><small>coins' + (rw.levelCoins ? ' (incl. level-up bonus)' : '') + '</small></div></div>' +
            '<div class="rr-item rr-goal"><svg viewBox="0 0 36 36" width="40" height="40" aria-hidden="true"><circle cx="18" cy="18" r="15" class="econ-ring-bg"/><circle cx="18" cy="18" r="15" class="econ-ring-fg" stroke-dasharray="' + C.toFixed(1) + '" stroke-dashoffset="' + (C * (1 - frac)).toFixed(1) + '" transform="rotate(-90 18 18)"/></svg>' +
            '<div><b>' + q.todayXp + '/' + q.goal + '</b><small>' + (q.goalDone ? 'daily goal done' : 'daily XP goal') + '</small></div></div>' +
            (rw.chests.length ? '<div class="rr-chests"><span class="rr-chest-icons">' + chestIcons + '</span><span>' + (rw.milestone ? '<b>' + rw.milestone + '-day streak!</b> ' : '') + 'You earned ' + rw.chests.length + ' chest' + (rw.chests.length > 1 ? 's' : '') + '</span>' +
                '<button type="button" class="econ-btn econ-btn-primary" data-open-chests>' + icon('gift', 18) + ' Open</button></div>' : '') +
            (claim ? '<a class="rr-claim" href="arena.html#quests">' + icon('target', 18) + ' ' + claim + ' quest reward' + (claim > 1 ? 's' : '') + ' ready to claim ' + icon('arrow-right', 16) + '</a>' : '') +
            '</div>';
    }

    // Rank change from this session (scripts/athlete-stats.js), e.g. placement finished or a promotion.
    function rankLine(h) {
        var CS = window.CogniStats;
        if (!CS || !h.length) { return ''; }
        var prevH = h.slice(0, -1);
        var last = new Date(h[h.length - 1].date).getTime();
        var before = CS.rankFor(prevH.length ? CS.rating(prevH, last) : 50, prevH.length);
        var nowOvr = CS.rating(h, last);
        var after = CS.rankFor(nowOvr, h.length);
        var order = function (r) { return r.placed ? r.index * 3 + ['III', 'II', 'I'].indexOf(r.division || 'I') : -1; };
        var badge = function (r) {
            return '<span class="recap-rank-badge" style="--tier:' + (r.placed ? r.tier.color : '#7b8798') + ';--tier-light:' + (r.placed ? r.tier.light : '#dfe5ee') + '">' +
                (r.placed ? (r.division || icon('star', 18)) : '?') + '</span>';
        };
        var msg;
        if (!before.placed && after.placed) { msg = 'Placement complete! You are ranked <b>' + esc(after.label) + '</b>.'; }
        else if (!after.placed) { msg = 'Placement: <b>' + (CS.PLACEMENT - after.toGo) + ' of ' + CS.PLACEMENT + '</b> sessions done. ' + after.toGo + ' more to get your rank.'; }
        else if (order(after) > order(before)) { msg = 'Ranked up! <b>' + esc(before.label) + '</b> \u2192 <b>' + esc(after.label) + '</b>' + (after.index > before.index ? ' - new card frame unlocked.' : '.'); }
        else { msg = 'Rank: <b>' + esc(after.label) + '</b> \u00b7 OVR ' + nowOvr + (after.next ? ' \u00b7 ' + after.pointsToNext + ' to ' + esc(after.next) : ''); }
        var up = (!before.placed && after.placed) || (after.placed && order(after) > order(before));
        return '<p class="recap-rank' + (up ? ' recap-rank-up' : '') + '"' + (up ? ' role="status"' : '') + '>' + badge(after) + '<span>' + msg + '</span></p>';
    }

    function tile(num, label) {
        return '<div class="recap-tile"><span class="recap-num">' + esc(num) + '</span><span class="recap-label">' + esc(label) + '</span></div>';
    }

    document.addEventListener('cognicoach:session-end', function (e) {
        if (e.detail && e.detail.completed) { setTimeout(render, 30); }
    });
})();
