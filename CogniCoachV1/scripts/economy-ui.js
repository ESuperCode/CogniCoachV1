// ==========================================================================
// Economy UI - shared pieces used on the app, dashboard and Arena pages:
//   - the HUD strip: streak (with freezes), coins, today's XP goal ring, boost timer, chests
//   - the chest-opening dialog (shake, lid pops, rewards fly in)
//   - small reward toasts
// Needs scripts/icons.js and scripts/economy.js.
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniEconomyUI) { return; }
    var E = window.CogniEconomy;
    if (!E) { return; }
    function ic(n, size, cls) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: size || 20, cls: cls }) : ''; }
    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function reduce() { return document.documentElement.classList.contains('a11y-reduce-motion'); }
    function fmtLeft(ms) { var m = Math.max(0, Math.ceil(ms / 60000)); return m >= 60 ? Math.floor(m / 60) + 'h ' + (m % 60) + 'm' : m + 'm'; }

    // ------------------------------------------------------------------ HUD
    var huds = [];
    function hud(host, opts) {
        opts = opts || {};
        if (!host) { return null; }
        var el = document.createElement('nav');
        el.className = 'econ-hud' + (opts.compact ? ' econ-hud-compact' : '');
        el.setAttribute('aria-label', 'Your streak, coins and daily goal');
        host.appendChild(el);
        huds.push(el);
        paint(el);
        return el;
    }
    function ring(frac) {
        var C = 2 * Math.PI * 15;
        return '<svg class="econ-ring" viewBox="0 0 36 36" width="34" height="34" aria-hidden="true"><circle cx="18" cy="18" r="15" class="econ-ring-bg"/>' +
            '<circle cx="18" cy="18" r="15" class="econ-ring-fg" stroke-dasharray="' + C.toFixed(1) + '" stroke-dashoffset="' + (C * (1 - Math.min(1, frac))).toFixed(1) + '" transform="rotate(-90 18 18)"/></svg>';
    }
    function paint(el) {
        var w = E.load(), st = E.streakInfo(w), q = E.quests(), boost = E.boostActive(w), chests = w.inventory.chests.length, claim = E.claimableCount();
        var frac = q.goal ? q.todayXp / q.goal : 0;
        el.innerHTML =
            '<a class="econ-chip econ-streak' + (st.trainedToday ? ' on' : '') + '" href="arena.html#quests" title="Streak">' + ic(st.trainedToday ? 'flame' : 'flame-off', 26) +
            '<span class="econ-num">' + st.current + '</span><span class="econ-lbl">day' + (st.current === 1 ? '' : 's') + '</span>' +
            (w.inventory.freeze ? '<span class="econ-freeze" title="' + w.inventory.freeze + ' Streak Freeze' + (w.inventory.freeze > 1 ? 's' : '') + ' equipped">' + ic('freeze', 16) + '<b>' + w.inventory.freeze + '</b></span>' : '') +
            '<span class="a11y-sr-only">' + st.current + ' day streak' + (st.trainedToday ? ', trained today' : ', not trained yet today') + '</span></a>' +
            '<a class="econ-chip econ-coins" href="arena.html#shop" title="Coins - spend them in the shop">' + ic('coin', 24) + '<span class="econ-num">' + w.coins + '</span><span class="a11y-sr-only">coins</span></a>' +
            '<a class="econ-chip econ-goal' + (q.goalDone ? ' done' : '') + '" href="arena.html#quests" title="Daily XP goal">' + ring(frac) +
            '<span class="econ-goal-text"><span class="econ-num">' + q.todayXp + '<small>/' + q.goal + '</small></span><span class="econ-lbl">XP today</span></span></a>' +
            (boost ? '<a class="econ-chip econ-boost" href="arena.html#bag" title="XP Boost running">' + ic('boost', 24) + '<span class="econ-num">' + boost.mult + 'x</span><span class="econ-lbl" data-boost-left>' + fmtLeft(boost.until - Date.now()) + '</span></a>' : '') +
            '<a class="econ-chip econ-chests" href="arena.html#bag" title="Chests to open">' + ic('chest-gold', 26) + '<span class="econ-num">' + chests + '</span>' +
            '<span class="a11y-sr-only">chests to open</span>' + (claim ? '<span class="econ-dot" title="' + claim + ' reward' + (claim > 1 ? 's' : '') + ' to claim"><span class="a11y-sr-only">' + claim + ' rewards to claim</span></span>' : '') + '</a>';
    }
    function repaint() { huds = huds.filter(function (h) { return h.isConnected; }); huds.forEach(paint); }
    document.addEventListener('cognicoach:wallet', repaint);
    document.addEventListener('cognicoach:session-end', function () { setTimeout(repaint, 50); });
    window.addEventListener('cognicoach:synced', repaint);
    setInterval(function () { if (huds.some(function (h) { return h.querySelector('[data-boost-left]'); })) { repaint(); } }, 30000);

    // ------------------------------------------------------------------ toasts
    var toastHost;
    function toast(html, icon) {
        if (!toastHost) { toastHost = document.createElement('div'); toastHost.className = 'econ-toasts'; toastHost.setAttribute('role', 'status'); toastHost.setAttribute('aria-live', 'polite'); document.body.appendChild(toastHost); }
        var t = document.createElement('div');
        t.className = 'econ-toast';
        t.innerHTML = (icon ? ic(icon, 28) : '') + '<span>' + html + '</span>';
        toastHost.appendChild(t);
        setTimeout(function () { t.classList.add('out'); setTimeout(function () { t.remove(); }, 400); }, 3600);
    }

    // ------------------------------------------------------------------ chest dialog
    var REWARD = {
        coins: function (r) { return { icon: 'coin', title: '+' + r.amount + ' coins', sub: 'Spend them in the shop' }; },
        xp: function (r) { return { icon: 'xp', title: '+' + r.amount + ' XP', sub: 'Bonus XP for your level' }; },
        freeze: function (r) { return { icon: 'freeze', title: 'Streak Freeze', sub: r.converted ? 'Slots full - turned into ' + r.converted + ' coins' : 'Equipped - protects one missed day' }; },
        boost2: function (r) { return { icon: 'boost', title: (r.amount > 1 ? r.amount + ' × ' : '') + 'Double XP', sub: 'Activate it from your bag' }; },
        boost3: function (r) { return { icon: 'boost', title: 'Triple XP', sub: 'Activate it from your bag' }; }
    };
    var dlg, lastFocus;
    function openChests(ids, after) {
        ids = (ids || []).slice();
        if (!ids.length) { return; }
        lastFocus = document.activeElement;
        if (!dlg) {
            dlg = document.createElement('div');
            dlg.className = 'chest-overlay';
            dlg.setAttribute('role', 'dialog');
            dlg.setAttribute('aria-modal', 'true');
            dlg.setAttribute('aria-labelledby', 'chestTitle');
            document.body.appendChild(dlg);
            dlg.addEventListener('keydown', function (e) { if (e.key === 'Escape') { close(); } });
        }
        dlg.hidden = false;
        document.documentElement.classList.add('chest-on');
        step(ids, after);
    }
    function step(ids, after) {
        var w = E.load();
        var id = ids.shift();
        var c = w.inventory.chests.filter(function (x) { return x.id === id; })[0];
        if (!c) { if (ids.length) { step(ids, after); } else { close(); } return; }
        dlg.innerHTML = '<div class="chest-card">' +
            '<div class="chest-rays" aria-hidden="true"></div>' +
            '<h2 id="chestTitle">' + esc(E.CHEST_NAMES[c.tier]) + '</h2>' +
            '<p class="chest-src">' + esc(c.source || '') + '</p>' +
            '<button type="button" class="chest-big" data-tier="' + c.tier + '" aria-label="Open the ' + esc(E.CHEST_NAMES[c.tier]) + '">' + ic('chest-' + c.tier, 150) + '</button>' +
            '<p class="chest-hint">Tap the chest to open it</p>' +
            '<div class="chest-rewards" aria-live="polite"></div>' +
            '<div class="chest-actions"></div></div>';
        var big = dlg.querySelector('.chest-big');
        big.focus();
        big.addEventListener('click', function go() {
            big.removeEventListener('click', go);
            big.disabled = true;
            dlg.querySelector('.chest-hint').textContent = '';
            var res = E.openChest(c.id);
            var show = function () {
                big.classList.add('opened');
                dlg.querySelector('.chest-card').classList.add('burst');
                var list = dlg.querySelector('.chest-rewards');
                (res.rewards || []).forEach(function (r, i) {
                    var d = REWARD[r.type] ? REWARD[r.type](r) : { icon: 'gift', title: r.type, sub: '' };
                    var card = document.createElement('div');
                    card.className = 'chest-reward';
                    card.style.animationDelay = (i * 160) + 'ms';
                    card.innerHTML = ic(d.icon, 44) + '<div><b>' + esc(d.title) + '</b><small>' + esc(d.sub) + '</small></div>';
                    list.appendChild(card);
                });
                var acts = dlg.querySelector('.chest-actions');
                var left = E.load().inventory.chests.filter(function (x) { return ids.indexOf(x.id) >= 0; }).length;
                acts.innerHTML = (left ? '<button type="button" class="econ-btn econ-btn-primary" data-next>Open next (' + left + ')</button>' : '') +
                    '<button type="button" class="econ-btn" data-done>' + (left ? 'Later' : 'Nice!') + '</button>';
                var nx = acts.querySelector('[data-next]');
                if (nx) { nx.addEventListener('click', function () { step(ids, after); }); nx.focus(); }
                acts.querySelector('[data-done]').addEventListener('click', function () { close(); if (after) { after(); } });
                if (!nx) { acts.querySelector('[data-done]').focus(); }
            };
            if (reduce()) { show(); } else { big.classList.add('shake'); setTimeout(show, 900); }
        });
    }
    function close() {
        if (!dlg) { return; }
        dlg.hidden = true;
        document.documentElement.classList.remove('chest-on');
        if (lastFocus && lastFocus.focus && lastFocus.isConnected) { try { lastFocus.focus(); } catch (e) {} }
        repaint();
    }

    // pages put <div id="econHud"></div> where the HUD goes
    function boot() { var m = document.getElementById('econHud'); if (m && !m.firstChild) { hud(m); } }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }

    window.CogniEconomyUI = { hud: hud, repaint: repaint, toast: toast, openChests: openChests, ring: ring, fmtLeft: fmtLeft, ic: ic };
})();
