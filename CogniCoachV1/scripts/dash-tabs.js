// ==========================================================================
// Dashboard tabs (dashboard.html): Home, Card, Stats, History, Settings.
// One section at a time instead of a long page. The URL hash keeps the tab
// (dashboard.html#stats), old links like #athleteCard still work, and the
// arrow keys move between tabs. Also renders the Home tab's welcome card.
// window.CogniTabs.select(name) is used by the page tour (scripts/tour.js).
// ==========================================================================
(function () {
    'use strict';
    var TABS = ['home', 'card', 'stats', 'history', 'settings'];
    var ALIAS = { athleteCard: 'card', myStats: 'stats', sessions: 'history', badges: 'history', account: 'settings' };
    var current = '';

    function $(s) { return document.querySelector(s); }
    function ic(n, s) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: s || 18 }) : ''; }
    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

    function select(tab, focus) {
        tab = ALIAS[tab] || tab;
        if (TABS.indexOf(tab) < 0) { tab = 'home'; }
        current = tab;
        TABS.forEach(function (t) {
            var b = $('#tab-' + t), p = $('#panel-' + t);
            if (!b || !p) { return; }
            var on = t === tab;
            b.setAttribute('aria-selected', on ? 'true' : 'false');
            b.tabIndex = on ? 0 : -1;
            p.hidden = !on;
        });
        if (focus) { $('#tab-' + tab).focus(); }
        if (location.hash.slice(1) !== tab) { try { history.replaceState(null, '', '#' + tab); } catch (e) {} }
        // charts measure themselves when they become visible
        try { window.dispatchEvent(new Event('resize')); } catch (e) {}
        document.dispatchEvent(new CustomEvent('cognicoach:tab', { detail: { tab: tab } }));
    }

    // ---- Home: a friendly first line and the one thing to do next ----
    function name() {
        try { var s = window.CogniAccount && window.CogniAccount.session(); if (s && s.username) { return s.username; } } catch (e) {}
        try { var d = JSON.parse(localStorage.getItem('cognicoach-dashboard') || '{}'); if (d && d.username) { return d.username; } } catch (e) {}
        return '';
    }
    function welcome() {
        var el = $('#dashWelcome');
        if (!el) { return; }
        var h = new Date().getHours();
        var hello = h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening';
        var n = name();
        var E = window.CogniEconomy, line;
        var hist = [];
        try { hist = JSON.parse(localStorage.getItem('cognicoach-history') || '[]') || []; } catch (e) {}
        if (!hist.length) {
            line = 'Your first session unlocks your streak, stats and Athlete Card.';
        } else if (E) {
            var st = E.streakInfo(), q = E.quests();
            if (st.trainedToday) { line = 'Nice work today: ' + q.todayXp + ' XP earned' + (q.goalDone ? ' and your daily goal is done.' : ', ' + Math.max(0, q.goal - q.todayXp) + ' to your daily goal.'); }
            else if (st.current) { line = 'You’re on a ' + st.current + '-day streak. Train today to keep it going.'; }
            else { line = 'Ready when you are. One session starts a new streak.'; }
        } else { line = 'Ready when you are.'; }
        el.innerHTML = '<div class="dw-text"><h2>' + esc(hello) + (n ? ', ' + esc(n) : '') + '</h2><p>' + esc(line) + '</p></div>' +
            '<div class="dw-actions"><a class="btn btn-primary dw-start" href="index.html">' + ic('play', 16) + ' Start training</a>' +
            '<a class="btn btn-secondary" href="arena.html">' + ic('target', 16) + ' Quests &amp; leagues</a></div>';
    }

    function boot() {
        var tabs = Array.prototype.slice.call(document.querySelectorAll('.page-tabs [role="tab"]'));
        if (!tabs.length) { return; }
        tabs.forEach(function (b, i) {
            b.addEventListener('click', function () { select(b.dataset.tab); });
            b.addEventListener('keydown', function (e) {
                var n = null;
                if (e.key === 'ArrowRight') { n = tabs[(i + 1) % tabs.length]; } else if (e.key === 'ArrowLeft') { n = tabs[(i - 1 + tabs.length) % tabs.length]; }
                else if (e.key === 'Home') { n = tabs[0]; } else if (e.key === 'End') { n = tabs[tabs.length - 1]; }
                if (n) { e.preventDefault(); select(n.dataset.tab, true); }
            });
        });
        select(location.hash.slice(1) || 'home');
        window.addEventListener('hashchange', function () { var t = location.hash.slice(1); if ((ALIAS[t] || t) !== current) { select(t); } });
        welcome();
        document.addEventListener('cognicoach:wallet', welcome);
        window.addEventListener('cognicoach:account', function () { setTimeout(welcome, 300); });
        window.addEventListener('cognicoach:synced', welcome);
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }

    window.CogniTabs = { select: select, current: function () { return current; } };
})();
