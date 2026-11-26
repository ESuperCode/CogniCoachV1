// ==========================================================================
// Social client - talks to the accounts Worker's /social/* routes (workers/accounts/src/social.js).
//   CogniSocial.call(path, {method, body})   signed-in API call
//   CogniSocial.publicSummary()              what friends (and leagues) can see about you
//   CogniSocial.sync()                       push your summary + this week's XP (debounced, signed in only)
// The summary is built from history, the wallet and the stats engine; it holds no personal details
// beyond your display name and handle (set on the server from your account).
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniSocial) { return; }

    var EPOCH = Date.UTC(2024, 0, 1), WEEK = 7 * 864e5;     // same week as the server: Monday 00:00 UTC
    var AVATARS = ['#2a78d6', '#eb6834', '#1baf7a', '#8a3ffc', '#e34948', '#c98500', '#1c5cab', '#d55181'];
    var lastSync = 0, timer = 0, state = { handle: '', league: null };

    function base() {
        var a = window.CogniAccount && window.CogniAccount.api;
        if (typeof a === 'string' && a) { return a; }
        try {
            var q = new URLSearchParams(location.search).get('accountsApi') || sessionStorage.getItem('cognicoach-accounts-api');
            if (q) { return q.replace(/\/$/, ''); }
        } catch (e) {}
        return 'https://cognicoach-accounts.bodhishanbhag.workers.dev';
    }
    function session() { try { return window.CogniAccount ? window.CogniAccount.session() : JSON.parse(localStorage.getItem('cognicoach-account') || 'null'); } catch (e) { return null; } }
    function signedIn() { var s = session(); return !!(s && s.token); }

    async function call(path, opts) {
        opts = opts || {};
        var s = session();
        if (!s || !s.token) { var e0 = new Error('Sign in to use friends and leagues.'); e0.code = 'signed_out'; throw e0; }
        var resp;
        try {
            resp = await fetch(base() + path, { method: opts.method || (opts.body ? 'POST' : 'GET'),
                headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + s.token }, body: opts.body ? JSON.stringify(opts.body) : undefined });
        } catch (e) { var e1 = new Error('Couldn’t reach CogniCoach. Check your connection.'); e1.offline = true; throw e1; }
        var data = await resp.json().catch(function () { return {}; });
        if (!resp.ok) { var e2 = new Error(data.detail || 'Something went wrong (' + resp.status + ').'); e2.status = resp.status; e2.code = data.code; throw e2; }
        return data;
    }

    function weekStart(t) { return EPOCH + Math.floor(((t || Date.now()) - EPOCH) / WEEK) * WEEK; }
    function avatarFor(name) {
        var prefs = window.CogniStats ? window.CogniStats.cardPrefs() : {};
        if (prefs.avatar) { return prefs.avatar; }
        var h = 0; String(name || 'a').split('').forEach(function (c) { h = (h * 31 + c.charCodeAt(0)) >>> 0; });
        return AVATARS[h % AVATARS.length];
    }

    function publicSummary() {
        var CS = window.CogniStats, E = window.CogniEconomy;
        if (!CS || !E) { return null; }
        var st = CS.compute(), w = E.load(), h = CS.history(), ws = weekStart();
        var weekXp = h.filter(function (r) { return new Date(r.date).getTime() >= ws; }).reduce(function (s, r) { return s + E.xpOf(r); }, 0);
        var prefs = CS.cardPrefs();
        var frame = prefs.frame && prefs.frame !== 'auto' ? prefs.frame : (st.rank.placed ? st.rank.tier.id : '');
        var title = (st.titles.filter(function (t) { return t.earned && t.id === prefs.title; })[0] || st.titles.filter(function (t) { return t.earned; }).pop() || {}).name || '';
        var s = session() || {};
        return {
            level: st.level.cur.name, xp: st.xp, weekXp: weekXp, todayXp: E.todayStats().xp, streak: E.streakInfo().current, bestStreak: st.bestStreak,
            ovr: st.ovr, rank: st.rank.label, tier: st.rank.placed ? st.rank.tier.id : '', frame: frame, title: title, topSport: st.top === '—' ? '' : st.top,
            sessions: st.sessions, minutes: st.minutes, avatar: avatarFor(s.username), titles: st.titles.filter(function (t) { return t.earned; }).length,
            coinsEarned: (w.ledger || []).filter(function (l) { return l.type === 'coins' && l.amount > 0; }).reduce(function (a, l) { return a + l.amount; }, 0)
        };
    }

    function leaguesOn() { try { return JSON.parse(localStorage.getItem('cognicoach-dashboard') || '{}').leaguesOff !== true; } catch (e) { return true; } }

    async function sync(force) {
        if (!signedIn()) { return null; }
        if (!force && Date.now() - lastSync < 20000) { return state; }
        var pub = publicSummary();
        if (!pub) { return null; }
        lastSync = Date.now();
        try {
            var r = await call('/social/sync', { body: { public: pub, weekXp: pub.weekXp, leagues: leaguesOn() } });
            state.handle = r.handle; state.league = r.league;
            document.dispatchEvent(new CustomEvent('cognicoach:social', { detail: r }));
            return r;
        } catch (e) { return null; }
    }
    function later() { clearTimeout(timer); timer = setTimeout(function () { sync(true); }, 2500); }

    document.addEventListener('cognicoach:session-end', later);
    document.addEventListener('cognicoach:wallet', later);
    window.addEventListener('cognicoach:account', function () { setTimeout(function () { sync(true); }, 800); });
    window.addEventListener('cognicoach:synced', later);
    function boot() { setTimeout(function () { sync(true); }, 1500); }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }

    window.CogniSocial = { call: call, sync: sync, publicSummary: publicSummary, signedIn: signedIn, weekStart: weekStart, avatarFor: avatarFor, AVATARS: AVATARS, state: state };
})();
