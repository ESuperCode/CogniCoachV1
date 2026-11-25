// ==========================================================================
// CogniCoach economy - XP, coins, boosts, chests, shop, streak freezes, daily goal and quests.
// Everything lives in localStorage['cognicoach-wallet'] (synced with an account like the rest).
//
//   XP for a session    minutes + 25 for finishing (10 if not) + 2 per rated drill (max 10),
//                       times an active XP Boost (2x / 3x). Saved on the history record as r.xp.
//   Coins for a session 5 + 2 per 10 minutes + 5 for finishing.
//   Chests              finished session -> wood (45+ min -> silver); streak milestones -> gold;
//                       daily goal -> wood; all 3 daily quests -> silver; league podium -> gold.
//   Shop                streak freezes, XP boosts, chests, streak repair, card frames.
//   Streak freezes      up to 2 equipped; a missed day uses one automatically (Duolingo-style).
// The page asks for rewards through this API; nothing here touches the network.
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniEconomy) { return; }

    var KEY = 'cognicoach-wallet';
    var DAY = 864e5;
    var MAX_FREEZES = 2;
    var GOALS = [{ xp: 20, name: 'Casual' }, { xp: 50, name: 'Regular' }, { xp: 100, name: 'Serious' }, { xp: 150, name: 'Intense' }];
    var MILESTONES = [3, 7, 14, 30, 50, 100, 200, 365];

    var SHOP = [
        { id: 'freeze', name: 'Streak Freeze', desc: 'Covers one missed day so your streak survives. Equip up to 2.', price: 120, icon: 'freeze' },
        { id: 'boost2', name: 'Double XP', desc: '2x XP on sessions for the next 60 minutes. Activate it from your bag.', price: 80, icon: 'boost' },
        { id: 'boost3', name: 'Triple XP', desc: '3x XP on sessions for the next 30 minutes.', price: 200, icon: 'boost' },
        { id: 'chest-silver', name: 'Silver Chest', desc: 'Coins, boosts or a freeze inside.', price: 150, icon: 'chest-silver' },
        { id: 'chest-gold', name: 'Gold Chest', desc: 'The best odds: big coin hauls, Triple XP and freezes.', price: 350, icon: 'chest-gold' },
        { id: 'repair', name: 'Streak Repair', desc: 'Bring back the streak you lost in the last 3 days.', price: 250, icon: 'flame', special: true },
        { id: 'frame-neon', name: 'Neon Frame', desc: 'Electric blue and pink card frame.', price: 300, icon: 'sparkles', frame: 'neon' },
        { id: 'frame-carbon', name: 'Carbon Frame', desc: 'Matte carbon fibre with an orange edge.', price: 400, icon: 'sparkles', frame: 'carbon' },
        { id: 'frame-aurora', name: 'Aurora Frame', desc: 'Slow-moving northern lights.', price: 600, icon: 'sparkles', frame: 'aurora' },
        { id: 'frame-prism', name: 'Prism Frame', desc: 'Holographic rainbow that follows your cursor.', price: 900, icon: 'sparkles', frame: 'prism' }
    ];
    var BOOSTS = { boost2: { mult: 2, minutes: 60 }, boost3: { mult: 3, minutes: 30 } };

    var QUESTS = [
        { id: 'min20', text: 'Train 20 minutes', goal: 20, coins: 15, metric: 'minutes' },
        { id: 'min40', text: 'Train 40 minutes', goal: 40, coins: 25, metric: 'minutes' },
        { id: 'finish', text: 'Finish a full session', goal: 1, coins: 20, metric: 'finished' },
        { id: 'xp60', text: 'Earn 60 XP', goal: 60, coins: 20, metric: 'xp' },
        { id: 'xp100', text: 'Earn 100 XP', goal: 100, coins: 30, metric: 'xp' },
        { id: 'rate3', text: 'Rate 3 drills', goal: 3, coins: 15, metric: 'rated' },
        { id: 'coach', text: 'Finish a session in Coach Mode', goal: 1, coins: 25, metric: 'coach' },
        { id: 'checkin', text: 'Check in how you feel before training', goal: 1, coins: 10, metric: 'checkin' },
        { id: 'drills6', text: 'Complete 6 drills', goal: 6, coins: 20, metric: 'drills' }
    ];

    // ---------------------------------------------------------------- storage
    function blank() {
        return { v: 1, coins: 0, bonusXp: 0, inventory: { freeze: 0, boost2: 0, boost3: 0, chests: [] }, activeBoost: null,
            frozenDays: [], dailyGoal: 50, quests: {}, owned: { frames: [] }, milestones: [], ledger: [], levelSeen: 0 };
    }
    function load() {
        var w;
        try { w = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { w = null; }
        var b = blank();
        if (!w || typeof w !== 'object') { return b; }
        Object.keys(b).forEach(function (k) { if (w[k] === undefined) { w[k] = b[k]; } });
        w.inventory = Object.assign(blank().inventory, w.inventory || {});
        if (!Array.isArray(w.inventory.chests)) { w.inventory.chests = []; }
        w.owned = Object.assign({ frames: [] }, w.owned || {});
        return w;
    }
    function save(w, reason) {
        w.ledger = (w.ledger || []).slice(-60);
        w.frozenDays = (w.frozenDays || []).slice(-90);
        var qk = Object.keys(w.quests || {}).sort();
        while (qk.length > 8) { delete w.quests[qk.shift()]; }
        try { localStorage.setItem(KEY, JSON.stringify(w)); } catch (e) {}
        try { document.dispatchEvent(new CustomEvent('cognicoach:wallet', { detail: { reason: reason || '' } })); } catch (e) {}
        return w;
    }
    function log(w, type, amount, note) { w.ledger.push({ t: Date.now(), type: type, amount: amount, note: note || '' }); }

    // ---------------------------------------------------------------- dates + history
    function dayKey(t) { var d = new Date(t == null ? Date.now() : t); return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }
    function dayStart(t) { var d = new Date(t == null ? Date.now() : t); d.setHours(0, 0, 0, 0); return d.getTime(); }
    function addDays(key, n) { var p = key.split('-'); var d = new Date(+p[0], +p[1] - 1, +p[2] + n); return dayKey(d.getTime()); }
    function history() {
        try { var h = JSON.parse(localStorage.getItem('cognicoach-history') || '[]'); return Array.isArray(h) ? h.filter(function (r) { return r && r.date; }) : []; } catch (e) { return []; }
    }
    function minutesOf(r) {
        var len = Number(r.workoutLength) || 0;
        if (r.drillsTotal > 0 && !r.completed) { len = Math.round(len * (r.drillsCompleted || 0) / r.drillsTotal); }
        return len;
    }
    function ratedOf(r) { var f = r.feedback || {}; return (f.easy || 0) + (f.right || 0) + (f.hard || 0); }
    function baseXp(r) { return minutesOf(r) + (r.completed ? 25 : 10) + Math.min(10, ratedOf(r) * 2); }
    function xpOf(r) { return typeof r.xp === 'number' ? r.xp : minutesOf(r) + (r.completed ? 25 : 10); }

    // ---------------------------------------------------------------- streak (with freezes)
    function activeDays(h) { var s = {}; h.forEach(function (r) { s[dayKey(new Date(r.date).getTime())] = true; }); return s; }
    function streakInfo(w, h) {
        w = w || load(); h = h || history();
        var act = activeDays(h), frozen = {};
        (w.frozenDays || []).forEach(function (k) { frozen[k] = true; });
        var today = dayKey(), d = today, n = 0;
        if (!act[d]) { d = addDays(d, -1); }
        while (act[d] || frozen[d]) { if (act[d]) { n++; } d = addDays(d, -1); }
        return { current: n, trainedToday: !!act[today], frozen: frozen, active: act };
    }
    // Use freezes for missed days since the last training day (only if they can save the streak).
    function reconcile() {
        var w = load(), h = history();
        if (!h.length) { return w; }
        var act = activeDays(h), frozen = {};
        w.frozenDays.forEach(function (k) { frozen[k] = true; });
        var y = addDays(dayKey(), -1), missing = [], d = y, guard = 0;
        while (!act[d] && !frozen[d] && guard++ < 30) { missing.push(d); d = addDays(d, -1); }
        if (!missing.length || guard >= 30 || !act[d] && !frozen[d]) { return w; }
        if (missing.length <= w.inventory.freeze) {
            missing.forEach(function (k) { w.frozenDays.push(k); });
            w.inventory.freeze -= missing.length;
            log(w, 'freeze', -missing.length, 'Streak Freeze used for ' + missing.join(', '));
            w.lastFreezeUsed = { at: Date.now(), days: missing };
            save(w, 'freeze-used');
        }
        return w;
    }
    // A streak lost in the last 3 days can be repaired from the shop.
    function repairable(w, h) {
        w = w || load(); h = h || history();
        var act = activeDays(h), frozen = {};
        w.frozenDays.forEach(function (k) { frozen[k] = true; });
        var today = dayKey(), d = addDays(today, -1), missing = [];
        while (!act[d] && !frozen[d] && missing.length < 4) { missing.push(d); d = addDays(d, -1); }
        if (!missing.length || missing.length > 3 || !(act[d] || frozen[d])) { return null; }
        // the streak that was lost
        var lost = 0, e = d;
        while (act[e] || frozen[e]) { if (act[e]) { lost++; } e = addDays(e, -1); }
        return lost >= 2 ? { days: missing, lost: lost } : null;
    }

    // ---------------------------------------------------------------- boosts
    function boostActive(w, at) {
        w = w || load();
        var b = w.activeBoost;
        return b && b.until > (at || Date.now()) ? b : null;
    }
    function activateBoost(id) {
        var w = load(), def = BOOSTS[id];
        if (!def || !(w.inventory[id] > 0)) { return { ok: false, error: 'You don’t have that boost.' }; }
        if (boostActive(w)) { return { ok: false, error: 'A boost is already running.' }; }
        w.inventory[id]--;
        w.activeBoost = { id: id, mult: def.mult, until: Date.now() + def.minutes * 60000, startedAt: Date.now() };
        log(w, 'boost', 0, def.mult + 'x XP for ' + def.minutes + ' minutes');
        save(w, 'boost');
        return { ok: true, boost: w.activeBoost };
    }

    // ---------------------------------------------------------------- chests
    function rand() { var a = new Uint32Array(1); crypto.getRandomValues(a); return a[0] / 4294967296; }
    function between(a, b) { return a + Math.floor(rand() * (b - a + 1)); }
    var TABLES = {
        wood: [[60, 'coins', 10, 25], [15, 'boost2', 1, 1], [5, 'freeze', 1, 1], [20, 'xp', 15, 35]],
        silver: [[45, 'coins', 30, 60], [25, 'boost2', 1, 1], [12, 'freeze', 1, 1], [6, 'boost3', 1, 1], [12, 'xp', 40, 80]],
        gold: [[35, 'coins', 80, 150], [20, 'boost3', 1, 1], [20, 'freeze', 1, 1], [12, 'boost2', 2, 2], [13, 'xp', 100, 180]]
    };
    var CHEST_NAMES = { wood: 'Wooden Chest', silver: 'Silver Chest', gold: 'Gold Chest' };
    function grantChest(w, tier, source) {
        var c = { id: Date.now().toString(36) + Math.floor(rand() * 1e6).toString(36), tier: tier, source: source || '', at: Date.now() };
        w.inventory.chests.push(c);
        return c;
    }
    function applyReward(w, r, note) {
        if (r.type === 'coins') { w.coins += r.amount; log(w, 'coins', r.amount, note); }
        else if (r.type === 'xp') { w.bonusXp += r.amount; log(w, 'xp', r.amount, note); }
        else if (r.type === 'freeze') {
            var room = Math.max(0, MAX_FREEZES - w.inventory.freeze);
            var give = Math.min(room, r.amount);
            w.inventory.freeze += give;
            if (give < r.amount) { var refund = (r.amount - give) * 60; w.coins += refund; r.converted = refund; log(w, 'coins', refund, 'Freeze slots full - converted'); }
        }
        else if (r.type === 'boost2' || r.type === 'boost3') { w.inventory[r.type] += r.amount; }
    }
    function openChest(id) {
        var w = load();
        var i = w.inventory.chests.findIndex(function (c) { return c.id === id; });
        if (i < 0) { return { ok: false, error: 'That chest is gone.' }; }
        var c = w.inventory.chests.splice(i, 1)[0];
        var table = TABLES[c.tier] || TABLES.wood, total = table.reduce(function (s, x) { return s + x[0]; }, 0), roll = rand() * total, pick = table[0];
        for (var k = 0; k < table.length; k++) { roll -= table[k][0]; if (roll <= 0) { pick = table[k]; break; } }
        var rewards = [{ type: pick[1], amount: between(pick[2], pick[3]) }];
        if (pick[1] !== 'coins') { rewards.push({ type: 'coins', amount: between(c.tier === 'gold' ? 30 : c.tier === 'silver' ? 10 : 5, c.tier === 'gold' ? 60 : c.tier === 'silver' ? 25 : 12) }); }
        rewards.forEach(function (r) { applyReward(w, r, CHEST_NAMES[c.tier]); });
        save(w, 'chest');
        return { ok: true, chest: c, rewards: rewards };
    }

    // ---------------------------------------------------------------- shop
    function buy(id) {
        var w = load(), item = SHOP.filter(function (s) { return s.id === id; })[0];
        if (!item) { return { ok: false, error: 'Unknown item.' }; }
        if (w.coins < item.price) { return { ok: false, error: 'You need ' + (item.price - w.coins) + ' more coins.' }; }
        if (id === 'freeze' && w.inventory.freeze >= MAX_FREEZES) { return { ok: false, error: 'You already have 2 freezes equipped.' }; }
        if (item.frame && w.owned.frames.indexOf(item.frame) >= 0) { return { ok: false, error: 'You already own this frame.' }; }
        var rep = null;
        if (id === 'repair') { rep = repairable(w); if (!rep) { return { ok: false, error: 'There is no recent streak to repair.' }; } }
        w.coins -= item.price;
        log(w, 'coins', -item.price, 'Bought ' + item.name);
        if (id === 'freeze') { w.inventory.freeze++; }
        else if (id === 'boost2' || id === 'boost3') { w.inventory[id]++; }
        else if (id === 'chest-silver') { grantChest(w, 'silver', 'shop'); }
        else if (id === 'chest-gold') { grantChest(w, 'gold', 'shop'); }
        else if (id === 'repair') { rep.days.forEach(function (k) { w.frozenDays.push(k); }); }
        else if (item.frame) { w.owned.frames.push(item.frame); }
        save(w, 'buy');
        return { ok: true, item: item, repaired: rep };
    }

    // ---------------------------------------------------------------- daily goal + quests
    function todayRecords(h) { var k = dayKey(); return (h || history()).filter(function (r) { return dayKey(new Date(r.date).getTime()) === k; }); }
    function todayStats(h) {
        var rs = todayRecords(h);
        return {
            minutes: rs.reduce(function (s, r) { return s + minutesOf(r); }, 0),
            finished: rs.filter(function (r) { return r.completed; }).length,
            xp: rs.reduce(function (s, r) { return s + xpOf(r); }, 0),
            rated: rs.reduce(function (s, r) { return s + ratedOf(r); }, 0),
            coach: rs.filter(function (r) { return r.coachMode && r.completed; }).length,
            checkin: rs.filter(function (r) { return r.readiness; }).length,
            drills: rs.reduce(function (s, r) { return s + (r.drillsCompleted || 0); }, 0)
        };
    }
    function hash(s) { var x = 2166136261; for (var i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 16777619); } return x >>> 0; }
    function questsFor(key) {
        // three different quests per day, same for everyone on that date; never two of the same kind
        var picks = [], used = {}, n = hash('q' + key);
        for (var tries = 0; picks.length < 3 && tries < 40; tries++) {
            var q = QUESTS[(n + tries * 7) % QUESTS.length];
            n = Math.imul(n ^ (n >>> 13), 2654435761) >>> 0;
            if (!used[q.metric]) { used[q.metric] = 1; picks.push(q); }
        }
        return picks;
    }
    function quests() {
        var w = load(), key = dayKey(), st = todayStats(), rec = w.quests[key] || { claimed: [] };
        var list = questsFor(key).map(function (q) {
            var p = Math.min(q.goal, st[q.metric] || 0);
            return { id: q.id, text: q.text, goal: q.goal, progress: p, done: p >= q.goal, claimed: rec.claimed.indexOf(q.id) >= 0, coins: q.coins };
        });
        var goal = w.dailyGoal || 50;
        return {
            day: key, list: list,
            allDone: list.every(function (q) { return q.done; }), allChestClaimed: !!rec.allChest,
            goal: goal, todayXp: st.xp, goalDone: st.xp >= goal, goalChestClaimed: !!rec.goalChest,
            resetsAt: dayStart() + DAY
        };
    }
    function claim(what) {
        var w = load(), key = dayKey(), q = quests();
        var rec = w.quests[key] || (w.quests[key] = { claimed: [] });
        var out = { ok: false };
        if (what === 'goal') {
            if (!q.goalDone || rec.goalChest) { return { ok: false, error: 'Not ready yet.' }; }
            rec.goalChest = true; out = { ok: true, chest: grantChest(w, 'wood', 'Daily goal') };
        } else if (what === 'all') {
            if (!q.allDone || rec.allChest) { return { ok: false, error: 'Finish all three quests first.' }; }
            rec.allChest = true; out = { ok: true, chest: grantChest(w, 'silver', 'All daily quests') };
        } else {
            var item = q.list.filter(function (x) { return x.id === what; })[0];
            if (!item || !item.done || item.claimed) { return { ok: false, error: 'Not ready yet.' }; }
            rec.claimed.push(what);
            w.coins += item.coins; log(w, 'coins', item.coins, 'Quest: ' + item.text);
            out = { ok: true, coins: item.coins };
        }
        save(w, 'claim');
        return out;
    }
    function claimableCount() {
        var q = quests(), n = 0;
        q.list.forEach(function (x) { if (x.done && !x.claimed) { n++; } });
        if (q.goalDone && !q.goalChestClaimed) { n++; }
        if (q.allDone && !q.allChestClaimed) { n++; }
        return n;
    }
    function setDailyGoal(xp) { var w = load(); w.dailyGoal = xp; save(w, 'goal'); }

    // ---------------------------------------------------------------- levels (same ladder as the dashboard)
    var LEVELS = [0, 150, 400, 800, 1400, 2300, 3600, 5400, 8000];
    function totalXp(w, h) { w = w || load(); h = h || history(); return h.reduce(function (s, r) { return s + xpOf(r); }, 0) + (w.bonusXp || 0); }
    function levelIndex(xp) { var i = 0; while (i + 1 < LEVELS.length && xp >= LEVELS[i + 1]) { i++; } return i; }

    // ---------------------------------------------------------------- session reward (called by script.js)
    // Returns fields to store on the history record; grants coins/chests to the wallet.
    function awardSession(record, session) {
        var w = load(), h = history();
        var started = session && session.startedAt;
        var boost = boostActive(w, Date.now()) || (started ? boostActive(w, started) : null);
        var base = baseXp(record), mult = boost ? boost.mult : 1;
        var xp = Math.round(base * mult);
        var mins = minutesOf(record);
        var coins = 5 + Math.floor(mins / 10) * 2 + (record.completed ? 5 : 0);
        var levelBefore = levelIndex(totalXp(w, h));
        w.coins += coins;
        log(w, 'coins', coins, 'Session');
        var chests = [];
        if (record.completed) { chests.push(grantChest(w, mins >= 45 ? 'silver' : 'wood', 'Session')); }
        // streak milestones (counting this session)
        var future = h.concat([Object.assign({}, record, { xp: xp })]);
        var st = streakInfo(w, future).current;
        var milestone = null;
        MILESTONES.forEach(function (m) {
            if (st >= m && w.milestones.indexOf(m) < 0) { w.milestones.push(m); milestone = m; chests.push(grantChest(w, 'gold', m + '-day streak')); }
        });
        var levelAfter = levelIndex(totalXp(w, future));
        var levelCoins = 0;
        if (levelAfter > levelBefore) { levelCoins = 50 * (levelAfter - levelBefore); w.coins += levelCoins; log(w, 'coins', levelCoins, 'Level up'); }
        save(w, 'session');
        return { fields: { xp: xp, xpBase: base, xpBoost: mult, coins: coins }, reward: { xp: xp, base: base, mult: mult, coins: coins, levelCoins: levelCoins, chests: chests, streak: st, milestone: milestone } };
    }

    function init() { reconcile(); }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }

    window.CogniEconomy = {
        KEY: KEY, SHOP: SHOP, GOALS: GOALS, QUESTS: QUESTS, MAX_FREEZES: MAX_FREEZES, CHEST_NAMES: CHEST_NAMES, BOOSTS: BOOSTS, MILESTONES: MILESTONES,
        load: load, save: save, xpOf: xpOf, baseXp: baseXp, minutesOf: minutesOf, totalXp: totalXp, dayKey: dayKey, addDays: addDays,
        streakInfo: streakInfo, reconcile: reconcile, repairable: repairable,
        boostActive: boostActive, activateBoost: activateBoost,
        openChest: openChest, buy: buy, quests: quests, claim: claim, claimableCount: claimableCount, setDailyGoal: setDailyGoal,
        todayStats: todayStats, awardSession: awardSession, grantReward: function (rewards, note, chestTier) {
            var w = load();
            (rewards || []).forEach(function (r) { applyReward(w, r, note); });
            var c = chestTier ? grantChest(w, chestTier, note) : null;
            save(w, 'grant');
            return c;
        }
    };
})();
