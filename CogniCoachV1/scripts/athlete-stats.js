// ==========================================================================
// Athlete stats engine - shared by the Athlete Card, My Stats (dashboard) and
// the session recap. Everything is computed from localStorage history.
//
//   OVR rating (40-99): consistency, volume, finishing sessions, intensity
//   Rank: 7 tiers (Bronze ... Legend) with divisions III / II / I, from OVR.
//         3 placement sessions before you are ranked. Rank can drop if you stop
//         training (it is "current form"); frames you have unlocked stay unlocked.
//   Titles: earned from what you have done; pick one to show on your card.
//   Card prefs (frame, title, peak rank) live in 'cognicoach-dashboard'.card so
//   they sync with an account like the rest of the dashboard settings.
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniStats) { return; }

    var LEVELS = [
        { name: 'Rookie', xp: 0 }, { name: 'Prospect', xp: 150 }, { name: 'Contender', xp: 400 },
        { name: 'Varsity', xp: 800 }, { name: 'All-Star', xp: 1400 }, { name: 'Pro', xp: 2300 },
        { name: 'Elite', xp: 3600 }, { name: 'Champion', xp: 5400 }, { name: 'Legend', xp: 8000 }
    ];
    var SAVED_PER_SESSION = 14;
    var PLACEMENT = 3;

    // min OVR for each tier; divisions split each tier's range in three (Legend has none)
    var TIERS = [
        { id: 'bronze', name: 'Bronze', min: 40, color: '#b87333', light: '#f0c39a' },
        { id: 'silver', name: 'Silver', min: 55, color: '#8e9aab', light: '#eef2f7' },
        { id: 'gold', name: 'Gold', min: 65, color: '#d4a017', light: '#ffe58a' },
        { id: 'platinum', name: 'Platinum', min: 75, color: '#2bb3a8', light: '#c9fff8' },
        { id: 'diamond', name: 'Diamond', min: 83, color: '#3d8bff', light: '#d8ecff' },
        { id: 'master', name: 'Master', min: 90, color: '#8a3ffc', light: '#e3cfff' },
        { id: 'legend', name: 'Legend', min: 96, color: '#ff5a36', light: '#ffe0a3' }
    ];
    var DIV = ['III', 'II', 'I'];

    // ------------------------------------------------------------------ basics
    function history() {
        try { var h = JSON.parse(localStorage.getItem('cognicoach-history') || '[]'); return Array.isArray(h) ? h.filter(function (r) { return r && r.date; }) : []; }
        catch (e) { return []; }
    }
    function minutesOf(r) {
        var len = Number(r.workoutLength) || 0;
        if (r.drillsTotal > 0 && !r.completed) { len = Math.round(len * (r.drillsCompleted || 0) / r.drillsTotal); }
        return len;
    }
    function xpOf(r) { return minutesOf(r) + (r.completed ? 25 : 10); }
    function dayKey(d) { d = new Date(d); return d.getFullYear() + '-' + d.getMonth() + '-' + d.getDate(); }
    function levelFor(xp) {
        var i = 0;
        while (i + 1 < LEVELS.length && xp >= LEVELS[i + 1].xp) { i++; }
        return { index: i, cur: LEVELS[i], next: LEVELS[i + 1] || null, pct: LEVELS[i + 1] ? (xp - LEVELS[i].xp) / (LEVELS[i + 1].xp - LEVELS[i].xp) : 1 };
    }

    function streaks(h, asOf) {
        var days = {};
        h.forEach(function (r) { days[dayKey(r.date)] = true; });
        var cur = 0, d = new Date(asOf || Date.now());
        if (!days[dayKey(d)]) { d.setDate(d.getDate() - 1); }   // still alive until the day ends
        while (days[dayKey(d)]) { cur++; d.setDate(d.getDate() - 1); }
        var sorted = Object.keys(days).map(function (k) { var p = k.split('-'); return new Date(+p[0], +p[1], +p[2]).getTime(); }).sort(function (a, b) { return a - b; });
        var best = 0, run = 0, prev = null;
        sorted.forEach(function (t) { run = prev !== null && Math.round((t - prev) / 864e5) === 1 ? run + 1 : 1; best = Math.max(best, run); prev = t; });
        return { current: cur, best: best, activeDays: sorted.length };
    }

    // ------------------------------------------------------------------ rating + rank
    // OVR as of a moment in time (used for the trend line too).
    function rating(h, asOf) {
        asOf = asOf || Date.now();
        if (!h.length) { return 50; }
        var st = streaks(h, asOf).current;
        var weekMin = h.filter(function (r) { var t = new Date(r.date).getTime(); return t <= asOf && t > asOf - 7 * 864e5; })
            .reduce(function (s, r) { return s + minutesOf(r); }, 0);
        var completion = h.filter(function (r) { return r.completed; }).length / h.length;
        var withI = h.filter(function (r) { return typeof r.intensity === 'number'; });
        var avgInt = withI.length ? withI.reduce(function (s, r) { return s + r.intensity; }, 0) / withI.length : 0;
        var ovr = 50 + Math.min(16, h.length * 1.2) + Math.min(14, st * 2) + Math.min(10, weekMin / 25) + Math.round(completion * 6) + Math.max(-3, Math.round(avgInt * 3));
        return Math.max(40, Math.min(99, Math.round(ovr)));
    }

    function rankFor(ovr, sessions) {
        if (sessions != null && sessions < PLACEMENT) {
            return { placed: false, tier: null, name: 'Unranked', label: 'Unranked', toGo: PLACEMENT - sessions, index: -1 };
        }
        var ti = 0;
        while (ti + 1 < TIERS.length && ovr >= TIERS[ti + 1].min) { ti++; }
        var tier = TIERS[ti], nextTier = TIERS[ti + 1] || null;
        var top = nextTier ? nextTier.min : 100;
        var div = null, divMin = tier.min, divMax = top;
        if (tier.id !== 'legend') {
            var span = (top - tier.min) / 3;
            var di = Math.min(2, Math.floor((ovr - tier.min) / span));
            div = DIV[di];
            divMin = Math.round(tier.min + span * di);
            divMax = di < 2 ? Math.round(tier.min + span * (di + 1)) : top;
        }
        var nextLabel = tier.id === 'legend' ? null : (div === 'I' ? nextTier.name + ' III' : tier.name + ' ' + DIV[DIV.indexOf(div) + 1]);
        return {
            placed: true, tier: tier, index: ti, division: div,
            name: tier.name + (div ? ' ' + div : ''), label: tier.name + (div ? ' ' + div : ''),
            progress: divMax > divMin ? Math.max(0, Math.min(1, (ovr - divMin) / (divMax - divMin))) : 1,
            next: nextLabel, pointsToNext: tier.id === 'legend' ? 0 : Math.max(1, divMax - ovr)
        };
    }

    // ------------------------------------------------------------------ titles
    var TITLES = [
        { id: 'fresh', name: 'Fresh Legs', how: 'Everyone starts here', test: function () { return true; } },
        { id: 'early', name: 'Early Bird', how: 'Train before 8 am', test: function (s) { return s.h.some(function (r) { return new Date(r.date).getHours() < 8; }); } },
        { id: 'night', name: 'Night Owl', how: 'Train after 9 pm', test: function (s) { return s.h.some(function (r) { return new Date(r.date).getHours() >= 21; }); } },
        { id: 'grinder', name: 'The Grinder', how: 'Log 10 sessions', test: function (s) { return s.sessions >= 10; } },
        { id: 'marathon', name: 'Marathoner', how: 'Finish a 60+ minute session', test: function (s) { return s.h.some(function (r) { return r.completed && minutesOf(r) >= 60; }); } },
        { id: 'streak7', name: 'Unstoppable', how: 'Reach a 7-day streak', test: function (s) { return s.bestStreak >= 7; } },
        { id: 'multi', name: 'Multi-Sport', how: 'Train 3 different sports', test: function (s) { return s.sportCount >= 3; } },
        { id: 'iron', name: 'Iron Will', how: 'Push through 5 drills you rated too hard', test: function (s) { return s.fb.hard >= 5; } },
        { id: 'honest', name: 'Self-Aware', how: 'Rate 20 drills', test: function (s) { return s.fb.easy + s.fb.right + s.fb.hard >= 20; } },
        { id: 'firedup', name: 'Fired Up', how: 'Check in "Fired up" 5 times', test: function (s) { return s.readyAll.high >= 5; } },
        { id: 'centurion', name: 'Centurion', how: 'Train 1,000 minutes', test: function (s) { return s.minutes >= 1000; } },
        { id: 'comeback', name: 'Comeback Kid', how: 'Train again after a week off', test: function (s) { return s.longestGapDays >= 7 && s.sessions >= 2; } },
        { id: 'goldrush', name: 'Gold Standard', how: 'Reach Gold rank', test: function (s) { return s.peakIndex >= 2; } },
        { id: 'diamond', name: 'Unbreakable', how: 'Reach Diamond rank', test: function (s) { return s.peakIndex >= 4; } },
        { id: 'legend', name: 'Living Legend', how: 'Reach Legend rank', test: function (s) { return s.peakIndex >= 6; } }
    ];

    // ------------------------------------------------------------------ card prefs (synced via dashboard settings)
    function dashSettings() {
        try { var d = JSON.parse(localStorage.getItem('cognicoach-dashboard') || '{}'); return d && typeof d === 'object' ? d : {}; } catch (e) { return {}; }
    }
    function cardPrefs() {
        var c = dashSettings().card;
        return c && typeof c === 'object' ? c : {};
    }
    function saveCardPrefs(patch) {
        var d = dashSettings();
        var c = d.card && typeof d.card === 'object' ? d.card : {};
        Object.keys(patch).forEach(function (k) { c[k] = patch[k]; });
        d.card = c;
        try { localStorage.setItem('cognicoach-dashboard', JSON.stringify(d)); } catch (e) {}
        return c;
    }

    // ------------------------------------------------------------------ everything at once
    function compute(h) {
        h = h || history();
        h = h.slice().sort(function (a, b) { return new Date(a.date) - new Date(b.date); });
        var xp = h.reduce(function (s, r) { return s + xpOf(r); }, 0);
        var minutes = h.reduce(function (s, r) { return s + minutesOf(r); }, 0);
        var stk = streaks(h);
        var sports = {};
        h.forEach(function (r) { var k = r.sport || 'General'; sports[k] = (sports[k] || 0) + minutesOf(r); });
        var top = Object.keys(sports).sort(function (a, b) { return sports[b] - sports[a]; })[0] || '—';
        var weekAgo = Date.now() - 7 * 864e5;
        var weekMin = h.filter(function (r) { return new Date(r.date).getTime() >= weekAgo; }).reduce(function (s, r) { return s + minutesOf(r); }, 0);
        var withI = h.filter(function (r) { return typeof r.intensity === 'number'; });
        var avgInt = withI.length ? withI.reduce(function (s, r) { return s + r.intensity; }, 0) / withI.length : 0;
        var fb = { easy: 0, right: 0, hard: 0 };
        h.forEach(function (r) { if (r.feedback) { fb.easy += r.feedback.easy || 0; fb.right += r.feedback.right || 0; fb.hard += r.feedback.hard || 0; } });
        var readyAll = { low: 0, normal: 0, high: 0 }, ready = { low: 0, normal: 0, high: 0 };
        h.forEach(function (r) { if (r.readiness && readyAll[r.readiness] != null) { readyAll[r.readiness]++; } });
        h.slice(-10).forEach(function (r) { if (r.readiness && ready[r.readiness] != null) { ready[r.readiness]++; } });
        var gap = 0;
        for (var i = 1; i < h.length; i++) { gap = Math.max(gap, (new Date(h[i].date) - new Date(h[i - 1].date)) / 864e5); }
        var ovr = h.length ? rating(h) : 50;
        var rank = rankFor(ovr, h.length);
        var prefs = cardPrefs();
        var peakIndex = Math.max(typeof prefs.peak === 'number' ? prefs.peak : -1, rank.index);
        if (rank.placed && peakIndex > (typeof prefs.peak === 'number' ? prefs.peak : -1)) { saveCardPrefs({ peak: peakIndex }); }
        var s = {
            h: h, xp: xp, level: levelFor(xp), minutes: minutes, sessions: h.length, streak: stk.current, bestStreak: stk.best, activeDays: stk.activeDays,
            sports: sports, sportCount: Object.keys(sports).length, top: top, weekMin: weekMin, saved: h.length * SAVED_PER_SESSION,
            avgInt: avgInt, fb: fb, ready: ready, readyAll: readyAll, completion: h.length ? h.filter(function (r) { return r.completed; }).length / h.length : 0,
            longestGapDays: gap, ovr: ovr, rank: rank, peakIndex: peakIndex
        };
        s.titles = TITLES.map(function (t) { return { id: t.id, name: t.name, how: t.how, earned: !!t.test(s) }; });
        return s;
    }

    window.CogniStats = {
        LEVELS: LEVELS, TIERS: TIERS, TITLES: TITLES, PLACEMENT: PLACEMENT, SAVED_PER_SESSION: SAVED_PER_SESSION,
        history: history, minutesOf: minutesOf, xpOf: xpOf, levelFor: levelFor, rating: rating, rankFor: rankFor,
        streaks: streaks, compute: compute, cardPrefs: cardPrefs, saveCardPrefs: saveCardPrefs, dayKey: dayKey
    };
})();
