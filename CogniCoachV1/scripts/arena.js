// ==========================================================================
// Arena page (arena.html): League, Friends, Quests, Shop and Bag tabs.
// Economy: scripts/economy.js (+ economy-ui.js). Social: scripts/social.js -> /social/* on the
// accounts Worker. Leagues and friends need an account; quests, shop and bag work for everyone.
// ==========================================================================
(function () {
    'use strict';
    var E = window.CogniEconomy, UI = window.CogniEconomyUI, S = window.CogniSocial, CS = window.CogniStats;
    if (!E || !UI) { return; }
    var ic = UI.ic;
    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function $(s, r) { return (r || document).querySelector(s); }
    function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
    var TABS = ['league', 'friends', 'quests', 'shop', 'bag'];
    var current = 'league', social = null;
    function signedIn() { return !!(S && S.signedIn()); }
    function openAccount() { if (window.CogniAccount && window.CogniAccount.open) { window.CogniAccount.open('signup'); } }
    function initial(name) { return esc(String(name || '?').trim().charAt(0).toUpperCase() || '?'); }
    function avatar(color, name, size) { return '<span class="ar-avatar" style="--av:' + esc(color || '#2a78d6') + ';width:' + (size || 40) + 'px;height:' + (size || 40) + 'px" aria-hidden="true">' + initial(name) + '</span>'; }
    function timeLeft(ms) {
        var h = Math.max(0, Math.floor(ms / 36e5)), d = Math.floor(h / 24);
        return d ? d + 'd ' + (h % 24) + 'h' : h ? h + 'h ' + Math.floor((ms % 36e5) / 6e4) + 'm' : Math.max(1, Math.floor(ms / 6e4)) + 'm';
    }
    function signedOutCard(title, text, icon) {
        return '<div class="ar-empty">' + ic(icon || 'users', 56) + '<h2>' + title + '</h2><p>' + text + '</p>' +
            '<button type="button" class="econ-btn econ-btn-primary" data-signin>' + ic('user-plus', 18) + ' Create a free account</button>' +
            '<p class="ar-small">Already have one? Use <b>Sign in</b> in the top bar.</p></div>';
    }
    function wireSignin(p) { $$('[data-signin]', p).forEach(function (b) { b.addEventListener('click', openAccount); }); }
    function errorBox(e) { return '<p class="ar-error" role="alert">' + ic('info', 18) + ' ' + esc(e.message || 'Something went wrong.') + '</p>'; }

    // ------------------------------------------------------------------ tabs
    function select(tab, focus) {
        if (TABS.indexOf(tab) < 0) { tab = 'league'; }
        current = tab;
        TABS.forEach(function (t) {
            var b = $('#tab-' + t), p = $('#panel-' + t);
            var on = t === tab;
            b.setAttribute('aria-selected', on ? 'true' : 'false');
            b.tabIndex = on ? 0 : -1;
            p.hidden = !on;
        });
        if (focus) { $('#tab-' + tab).focus(); }
        if (location.hash !== '#' + tab) { history.replaceState(null, '', '#' + tab); }
        render(tab);
    }
    function render(tab) {
        var p = $('#panel-' + tab);
        ({ league: league, friends: friends, quests: quests, shop: shop, bag: bag })[tab](p);
        dots();
    }
    function dots() {
        var q = E.claimableCount(), w = E.load();
        $('#tab-quests .tab-dot').hidden = !q;
        $('#tab-bag .tab-dot').hidden = !w.inventory.chests.length;
    }

    // ------------------------------------------------------------------ League
    async function league(p) {
        if (!signedIn()) {
            p.innerHTML = signedOutCard('Weekly leagues', 'Earn XP from training to climb a weekly league against athletes at your level. Finish in the top spots to move up - from Amateur all the way to Olympian.', 'podium') +
                '<div class="ar-ladder">' + [0, 1, 2, 3, 4, 5, 6].map(function (i) { return ic('league-' + i, 44); }).join('') + '</div>';
            wireSignin(p);
            return;
        }
        p.innerHTML = '<p class="ar-loading">' + ic('refresh', 18, 'spin') + ' Loading your league…</p>';
        var lg;
        try { var r = await S.sync(true); lg = r && r.league ? r.league : await S.call('/social/league'); }
        catch (e) { p.innerHTML = errorBox(e); return; }
        if (current !== 'league') { return; }
        var on = lg.leaguesOn !== false;
        var html = '<div class="lg-head">' + ic('league-' + lg.tier, 84) + '<div><h2>' + esc(lg.league) + ' League</h2>' +
            '<p>' + (lg.joined ? (lg.promote ? 'Top ' + lg.promote + ' move up' : 'Top league - stay on top') + (lg.demote ? ' · bottom ' + lg.demote + ' move down' : '') + ' · ' : '') +
            'Ends in <b>' + timeLeft(lg.endsAt - Date.now()) + '</b></p></div></div>' +
            '<ol class="lg-ladder" aria-label="Leagues">' + lg.leagues.map(function (n, i) {
                return '<li' + (i === lg.tier ? ' aria-current="true" class="on"' : i < lg.tier ? ' class="past"' : '') + '>' + ic('league-' + i, 34) + '<span>' + esc(n) + '</span></li>';
            }).join('') + '</ol>';
        var lr = lg.lastResult;
        if (lr && !lr.claimed && (lr.coins || lr.chest)) {
            html += '<div class="lg-result">' + ic(lr.place === 1 ? 'medal-gold' : lr.place === 2 ? 'medal-silver' : lr.place === 3 ? 'medal-bronze' : 'trophy-gold', 56) +
                '<div><b>Last week: ' + ordinal(lr.place) + ' of ' + lr.size + ' in ' + esc(lr.league) + '</b><span>' +
                (lr.moved === 'up' ? 'Promoted to ' + esc(lr.newLeague) + '!' : lr.moved === 'down' ? 'Moved down to ' + esc(lr.newLeague) + '.' : 'You stay in ' + esc(lr.newLeague) + '.') +
                ' Reward: ' + (lr.coins ? lr.coins + ' coins' : '') + (lr.chest ? (lr.coins ? ' + ' : '') + 'a Gold Chest' : '') + '</span></div>' +
                '<button type="button" class="econ-btn econ-btn-primary" data-claim-league>Claim</button></div>';
        } else if (lr && lr.moved !== 'stay') {
            html += '<p class="lg-note">' + ic(lr.moved === 'up' ? 'arrow-up' : 'arrow-down', 18) + ' Last week you ' + (lr.moved === 'up' ? 'moved up to ' : 'moved down to ') + esc(lr.newLeague) + '.</p>';
        }
        if (!on) {
            html += '<div class="ar-empty small">' + ic('eye', 36) + '<p>You’re hidden from leagues. Turn it back on below to compete.</p></div>';
        } else if (!lg.joined) {
            html += '<div class="ar-empty small">' + ic('runner', 40) + '<h3>Earn XP to join this week’s group</h3><p>Finish a session and you’re placed with up to 30 athletes in the ' + esc(lg.league) + ' League.</p>' +
                '<a class="econ-btn econ-btn-primary" href="index.html">' + ic('play', 16) + ' Start training</a></div>';
        } else {
            html += '<ol class="lg-table" aria-label="' + esc(lg.league) + ' League standings">';
            lg.members.forEach(function (m) {
                if (lg.promote && m.place === lg.promote + 1 && lg.members.length > lg.promote) { html += '<li class="lg-zone up" aria-hidden="true">' + ic('arrow-up', 14) + ' Promotion zone</li>'; }
                if (lg.demote && m.place === lg.members.length - lg.demote + 1) { html += '<li class="lg-zone down" aria-hidden="true">' + ic('arrow-down', 14) + ' Demotion zone</li>'; }
                html += '<li class="lg-row' + (m.me ? ' me' : '') + (m.place <= lg.promote ? ' up' : lg.demote && m.place > lg.members.length - lg.demote ? ' down' : '') + '">' +
                    '<span class="lg-place">' + (m.place <= 3 ? ic(['medal-gold', 'medal-silver', 'medal-bronze'][m.place - 1], 30) : m.place) + '<span class="a11y-sr-only">place ' + m.place + '</span></span>' +
                    avatar(m.avatar, m.display, 40) +
                    '<span class="lg-who"><b>' + esc(m.display) + (m.me ? ' <em>(you)</em>' : '') + '</b><small>@' + esc(m.handle) + (m.friend ? ' · friend' : '') + '</small></span>' +
                    (m.streak ? '<span class="lg-streak" title="' + m.streak + ' day streak">' + ic('flame', 18) + m.streak + '</span>' : '<span></span>') +
                    '<span class="lg-xp">' + m.xp + ' XP</span></li>';
            });
            html += '</ol>';
            if (lg.members.length < 3) { html += '<p class="ar-small center">Your group fills up as more athletes train this week. Add friends to race them too.</p>'; }
        }
        html += '<label class="ar-toggle"><input type="checkbox" data-leagues-on' + (on ? ' checked' : '') + '> Show me in weekly leagues <small>(others in your group see your name, handle and weekly XP)</small></label>';
        p.innerHTML = html;
        var cl = $('[data-claim-league]', p);
        if (cl) {
            cl.addEventListener('click', async function () {
                cl.disabled = true;
                try {
                    var r = await S.call('/social/claim', { body: {} });
                    var chest = E.grantReward(r.coins ? [{ type: 'coins', amount: r.coins }] : [], 'League reward', r.chest || null);
                    UI.toast('League reward: <b>' + (r.coins || 0) + ' coins</b>' + (chest ? ' and a Gold Chest' : ''), 'coin');
                    if (chest) { UI.openChests([chest.id], function () { league(p); }); } else { league(p); }
                } catch (e) { cl.disabled = false; UI.toast(esc(e.message), 'info'); }
            });
        }
        $('[data-leagues-on]', p).addEventListener('change', async function (ev) {
            var d = {}; try { d = JSON.parse(localStorage.getItem('cognicoach-dashboard') || '{}') || {}; } catch (e) {}
            d.leaguesOff = !ev.target.checked;
            localStorage.setItem('cognicoach-dashboard', JSON.stringify(d));
            await S.sync(true);
            league(p);
        });
    }
    function ordinal(n) { var s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }

    // ------------------------------------------------------------------ Friends
    async function friends(p) {
        if (!signedIn()) {
            p.innerHTML = signedOutCard('Train with friends', 'Add friends by their handle, compare weekly XP and streaks, see each other’s Athlete Cards and send a cheer when they train.', 'users');
            wireSignin(p);
            return;
        }
        p.innerHTML = '<p class="ar-loading">' + ic('refresh', 18, 'spin') + ' Loading friends…</p>';
        try { await S.sync(true); social = await S.call('/social/me'); } catch (e) { p.innerHTML = errorBox(e); return; }
        if (current !== 'friends') { return; }
        var me = S.publicSummary() || {};
        var myColor = me.avatar;
        var board = social.friends.map(function (f) { return f; }).concat([{ handle: social.handle, display: social.display, avatar: myColor, weekXp: me.weekXp, streak: me.streak, me: true }])
            .sort(function (a, b) { return (b.weekXp || 0) - (a.weekXp || 0); });
        var html = '<div class="fr-me">' + avatar(myColor, social.display, 56) + '<div class="fr-me-text"><b>' + esc(social.display) + '</b>' +
            '<span class="fr-handle">@<span data-handle>' + esc(social.handle) + '</span> <button type="button" class="ar-link" data-copy>' + ic('copy', 14) + ' Copy</button> <button type="button" class="ar-link" data-edit-handle>Change</button></span>' +
            '<form class="fr-handle-form" hidden><label for="newHandle" class="a11y-sr-only">New handle</label><input id="newHandle" value="' + esc(social.handle) + '" maxlength="24" autocomplete="off" spellcheck="false"><button class="econ-btn" type="submit">Save</button></form>' +
            '<div class="fr-colors" role="radiogroup" aria-label="Avatar colour">' + S.AVATARS.map(function (c, i) {
                return '<button type="button" role="radio" class="fr-color" style="--av:' + c + '" aria-checked="' + (c === myColor) + '" aria-label="Colour ' + (i + 1) + '" data-color="' + c + '"></button>';
            }).join('') + '</div></div></div>';
        if (social.cheers && social.cheers.length) {
            html += '<div class="fr-cheers">' + ic('heart', 22) + '<span><b>' + social.cheers.map(function (c) { return esc(c.display); }).join(', ') + '</b> cheered you on!</span></div>';
        }
        html += '<form class="fr-add" role="search"><label for="friendHandle">Add a friend by handle</label><div class="fr-add-row"><span class="fr-at" aria-hidden="true">@</span>' +
            '<input id="friendHandle" placeholder="their-handle" autocomplete="off" spellcheck="false" maxlength="25" required><button class="econ-btn econ-btn-primary" type="submit">' + ic('search', 16) + ' Find</button></div><div class="fr-found" aria-live="polite"></div></form>';
        if (social.incoming.length) {
            html += '<h2 class="ar-h3">Requests</h2><ul class="fr-list">' + social.incoming.map(function (f) {
                return '<li class="fr-row">' + avatar(f.avatar, f.display) + '<span class="fr-who"><b>' + esc(f.display) + '</b><small>@' + esc(f.handle) + ' · ' + esc(f.league) + ' League</small></span>' +
                    '<span class="fr-acts"><button type="button" class="econ-btn econ-btn-primary" data-accept="' + esc(f.handle) + '">' + ic('check', 16) + ' Accept</button>' +
                    '<button type="button" class="econ-btn" data-decline="' + esc(f.handle) + '">Decline</button></span></li>';
            }).join('') + '</ul>';
        }
        html += '<h2 class="ar-h3">This week with friends</h2>';
        if (!social.friends.length) {
            html += '<div class="ar-empty small">' + ic('user-plus', 40) + '<p>No friends yet. Share your handle <b>@' + esc(social.handle) + '</b> or add someone above.</p></div>';
        } else {
            html += '<ol class="fr-list fr-board">' + board.map(function (f, i) {
                return '<li class="fr-row' + (f.me ? ' me' : '') + '"><span class="fr-place">' + (i + 1) + '</span>' + avatar(f.avatar, f.display) +
                    '<span class="fr-who"><b>' + esc(f.display) + (f.me ? ' <em>(you)</em>' : '') + '</b><small>@' + esc(f.handle) + (f.level ? ' · ' + esc(f.level) : '') + '</small></span>' +
                    '<span class="fr-streak" title="Streak">' + ic(f.streak ? 'flame' : 'flame-off', 18) + (f.streak || 0) + '</span>' +
                    '<span class="fr-xp">' + (f.weekXp || 0) + ' XP</span>' +
                    (f.me ? '<span></span>' : '<span class="fr-acts"><button type="button" class="econ-btn econ-btn-icon" data-cheer="' + esc(f.handle) + '" aria-label="Cheer ' + esc(f.display) + '">' + ic('heart', 18) + '</button>' +
                        '<button type="button" class="econ-btn" data-view="' + esc(f.handle) + '">Profile</button></span>') + '</li>';
            }).join('') + '</ol>';
        }
        if (social.outgoing.length) {
            html += '<h2 class="ar-h3">Waiting for an answer</h2><ul class="fr-list">' + social.outgoing.map(function (f) {
                return '<li class="fr-row">' + avatar(f.avatar, f.display) + '<span class="fr-who"><b>' + esc(f.display) + '</b><small>@' + esc(f.handle) + '</small></span>' +
                    '<span class="fr-acts"><button type="button" class="econ-btn" data-remove="' + esc(f.handle) + '">Cancel</button></span></li>';
            }).join('') + '</ul>';
        }
        p.innerHTML = html;

        $('[data-copy]', p).addEventListener('click', function () {
            var t = '@' + social.handle;
            (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function () { UI.toast('Copied <b>' + esc(t) + '</b>', 'copy'); }, function () { UI.toast('Your handle is <b>' + esc(t) + '</b>', 'user'); });
        });
        var form = $('.fr-handle-form', p);
        $('[data-edit-handle]', p).addEventListener('click', function () { form.hidden = !form.hidden; if (!form.hidden) { $('#newHandle').focus(); } });
        form.addEventListener('submit', async function (ev) {
            ev.preventDefault();
            try { var r = await S.call('/social/handle', { body: { handle: $('#newHandle').value } }); UI.toast('Your handle is now <b>@' + esc(r.handle) + '</b>', 'check'); friends(p); }
            catch (e) { UI.toast(esc(e.message), 'info'); }
        });
        $$('[data-color]', p).forEach(function (b) {
            b.addEventListener('click', function () { if (CS) { CS.saveCardPrefs({ avatar: b.dataset.color }); } S.sync(true).then(function () { friends(p); }); });
        });
        var add = $('.fr-add', p), found = $('.fr-found', p);
        add.addEventListener('submit', async function (ev) {
            ev.preventDefault();
            var h = $('#friendHandle').value.trim().replace(/^@/, '');
            found.innerHTML = '';
            try {
                var f = await S.call('/social/find', { body: { handle: h } });
                var label = { none: 'Add friend', incoming: 'Accept request', outgoing: 'Request sent', friends: 'Already friends', self: 'That’s you' }[f.relation];
                found.innerHTML = '<div class="fr-row found">' + avatar(f.avatar, f.display) + '<span class="fr-who"><b>' + esc(f.display) + '</b><small>@' + esc(f.handle) + ' · ' + esc(f.league) + ' League</small></span>' +
                    '<span class="fr-acts"><button type="button" class="econ-btn econ-btn-primary" data-add="' + esc(f.handle) + '"' + (f.relation === 'none' || f.relation === 'incoming' ? '' : ' disabled') + '>' + ic('user-plus', 16) + ' ' + label + '</button></span></div>';
                var b = $('[data-add]', found);
                if (b && !b.disabled) {
                    b.addEventListener('click', async function () {
                        try { var r = await S.call('/social/request', { body: { handle: f.handle } }); UI.toast(r.status === 'friends' ? 'You and <b>' + esc(f.display) + '</b> are now friends!' : 'Request sent to <b>' + esc(f.display) + '</b>', 'user-check'); friends(p); }
                        catch (e) { UI.toast(esc(e.message), 'info'); }
                    });
                }
            } catch (e) { found.innerHTML = errorBox(e); }
        });
        $$('[data-accept]', p).forEach(function (b) { b.addEventListener('click', function () { respond(b.dataset.accept, true, p); }); });
        $$('[data-decline]', p).forEach(function (b) { b.addEventListener('click', function () { respond(b.dataset.decline, false, p); }); });
        $$('[data-remove]', p).forEach(function (b) { b.addEventListener('click', async function () { await S.call('/social/remove', { body: { handle: b.dataset.remove } }).catch(function () {}); friends(p); }); });
        $$('[data-cheer]', p).forEach(function (b) {
            b.addEventListener('click', async function () {
                try { await S.call('/social/cheer', { body: { handle: b.dataset.cheer } }); b.classList.add('cheered'); b.disabled = true; UI.toast('Cheer sent!', 'heart'); }
                catch (e) { UI.toast(esc(e.message), 'info'); }
            });
        });
        $$('[data-view]', p).forEach(function (b) { b.addEventListener('click', function () { viewProfile(b.dataset.view, p); }); });
    }
    async function respond(handle, accept, p) {
        try { await S.call('/social/respond', { body: { handle: handle, accept: accept } }); if (accept) { UI.toast('New friend: <b>@' + esc(handle) + '</b>', 'user-check'); } }
        catch (e) { UI.toast(esc(e.message), 'info'); }
        friends(p);
    }

    // friend profile dialog: a static Athlete Card + their numbers
    var pdlg;
    async function viewProfile(handle, p) {
        var r;
        try { r = await S.call('/social/profile', { body: { handle: handle } }); } catch (e) { UI.toast(esc(e.message), 'info'); return; }
        var f = r.profile;
        var last = document.activeElement;
        if (!pdlg) { pdlg = document.createElement('div'); pdlg.className = 'chest-overlay'; pdlg.setAttribute('role', 'dialog'); pdlg.setAttribute('aria-modal', 'true'); pdlg.setAttribute('aria-labelledby', 'pfTitle'); document.body.appendChild(pdlg); }
        pdlg.hidden = false;
        document.documentElement.classList.add('chest-on');
        pdlg.innerHTML = '<div class="pf-card"><button type="button" class="pf-close" aria-label="Close">' + ic('close', 20) + '</button>' +
            '<div class="ac-stage pf-stage"><div class="ac-card pf-ac" data-frame="' + esc(f.frame || 'none') + '"><div class="ac-frame" aria-hidden="true"></div><div class="ac-face">' +
            '<div class="ac-top"><div class="ac-ovr"><b>' + (f.ovr || 50) + '</b><span>OVR</span></div><div class="ac-emblem"><span>' + esc(f.rank || 'Unranked') + '</span></div></div>' +
            '<div class="ac-avatar" style="background:' + esc(f.avatar) + '"><span>' + initial(f.display) + '</span></div>' +
            '<div class="ac-name" id="pfTitle">' + esc(f.display) + '</div>' + (f.title ? '<div class="ac-title">“' + esc(f.title) + '”</div>' : '') +
            '<div class="ac-level">' + esc(f.level || 'Rookie') + ' · ' + (f.xp || 0) + ' XP</div>' +
            '<div class="ac-grid">' + [[f.sessions, 'Sessions'], [f.minutes, 'Minutes'], [f.streak, 'Streak'], [f.weekXp, 'Week XP'], [f.bestStreak, 'Best streak'], [esc(f.topSport || '—'), 'Top sport']].map(function (c) {
                return '<div class="ac-cell"><b>' + (c[0] == null ? 0 : c[0]) + '</b><span>' + c[1] + '</span></div>';
            }).join('') + '</div><div class="ac-foot">@' + esc(f.handle) + ' · ' + esc(f.league) + ' League</div></div></div></div>' +
            '<div class="pf-acts"><button type="button" class="econ-btn econ-btn-primary" data-pf-cheer>' + ic('heart', 16) + ' Cheer</button>' +
            '<button type="button" class="econ-btn" data-pf-remove>Remove friend</button></div></div>';
        var close = function () { pdlg.hidden = true; document.documentElement.classList.remove('chest-on'); if (last && last.isConnected) { last.focus(); } };
        $('.pf-close', pdlg).addEventListener('click', close);
        $('.pf-close', pdlg).focus();
        pdlg.onkeydown = function (e) { if (e.key === 'Escape') { close(); } };
        pdlg.onclick = function (e) { if (e.target === pdlg) { close(); } };
        $('[data-pf-cheer]', pdlg).addEventListener('click', async function () {
            try { await S.call('/social/cheer', { body: { handle: f.handle } }); UI.toast('Cheer sent to <b>' + esc(f.display) + '</b>!', 'heart'); } catch (e) { UI.toast(esc(e.message), 'info'); }
        });
        $('[data-pf-remove]', pdlg).addEventListener('click', async function () {
            if (!confirm('Remove ' + f.display + ' from your friends?')) { return; }
            await S.call('/social/remove', { body: { handle: f.handle } }).catch(function () {});
            close(); friends(p);
        });
    }

    // ------------------------------------------------------------------ Quests
    var METRIC_ICON = { minutes: 'stopwatch', finished: 'flag', xp: 'bolt', rated: 'thumbs-up', coach: 'whistle', checkin: 'smile', drills: 'dumbbell' };
    function quests(p) {
        var q = E.quests(), w = E.load(), st = E.streakInfo(w);
        var next = E.MILESTONES.filter(function (m) { return m > st.current; })[0];
        var html = '<div class="qs-grid">' +
            '<div class="qs-goal"><div class="qs-ring">' + UI.ring(q.goal ? q.todayXp / q.goal : 0).replace('width="34" height="34"', 'width="132" height="132"') +
            '<div class="qs-ring-text"><b>' + q.todayXp + '</b><span>of ' + q.goal + ' XP</span></div></div>' +
            '<h2>Daily goal</h2>' +
            '<div class="qs-goals" role="radiogroup" aria-label="Daily XP goal">' + E.GOALS.map(function (g) {
                return '<button type="button" role="radio" aria-checked="' + (g.xp === q.goal) + '" data-goal="' + g.xp + '"><b>' + g.name + '</b><small>' + g.xp + ' XP</small></button>';
            }).join('') + '</div>' +
            (q.goalDone ? (q.goalChestClaimed ? '<p class="qs-done">' + ic('check-circle', 18) + ' Goal reached today</p>' : '<button type="button" class="econ-btn econ-btn-primary" data-claim="goal">' + ic('chest-wood', 22) + ' Claim goal chest</button>')
                : '<p class="ar-small">' + (q.goal - q.todayXp) + ' XP to go today</p>') + '</div>' +

            '<div class="qs-streak">' + ic(st.trainedToday ? 'flame' : 'flame-off', 72) + '<div class="qs-streak-num"><b>' + st.current + '</b> day streak</div>' +
            '<p class="ar-small">' + (st.trainedToday ? 'You trained today. See you tomorrow!' : st.current ? 'Train today to keep it going.' : 'Train today to start a streak.') + '</p>' +
            '<div class="qs-freezes" aria-label="' + w.inventory.freeze + ' of 2 Streak Freezes equipped">' + [0, 1].map(function (i) {
                return '<span class="qs-slot' + (i < w.inventory.freeze ? ' full' : '') + '">' + ic('freeze', 34) + '</span>';
            }).join('') + '<span class="ar-small">Streak Freezes ' + w.inventory.freeze + '/2</span></div>' +
            (next ? '<div class="qs-mile"><span>Next milestone: <b>' + next + ' days</b> ' + ic('chest-gold', 22) + '</span><div class="qs-bar"><i style="width:' + Math.round(st.current / next * 100) + '%"></i></div></div>' : '') +
            (w.lastFreezeUsed && Date.now() - w.lastFreezeUsed.at < 3 * 864e5 ? '<p class="qs-freeze-note">' + ic('freeze', 18) + ' A Streak Freeze saved your streak.</p>' : '') + '</div></div>' +

            '<h2 class="ar-h2">Daily quests <small>New quests in ' + timeLeft(q.resetsAt - Date.now()) + '</small></h2><ul class="qs-list">' + q.list.map(function (x) {
                var metric = (E.QUESTS.filter(function (d) { return d.id === x.id; })[0] || {}).metric;
                return '<li class="qs-item' + (x.done ? ' done' : '') + '"><span class="qs-icon">' + ic(METRIC_ICON[metric] || 'target', 24) + '</span>' +
                    '<div class="qs-body"><b>' + esc(x.text) + '</b><div class="qs-bar" role="progressbar" aria-valuemin="0" aria-valuemax="' + x.goal + '" aria-valuenow="' + x.progress + '" aria-label="' + esc(x.text) + '"><i style="width:' + Math.round(x.progress / x.goal * 100) + '%"></i></div>' +
                    '<small>' + x.progress + ' / ' + x.goal + '</small></div>' +
                    (x.claimed ? '<span class="qs-claimed">' + ic('check', 18) + ' Claimed</span>' : x.done ? '<button type="button" class="econ-btn econ-btn-primary" data-claim="' + x.id + '">' + ic('coin', 20) + ' ' + x.coins + '</button>' :
                        '<span class="qs-reward">' + ic('coin', 20) + ' ' + x.coins + '</span>') + '</li>';
            }).join('') + '</ul>' +
            '<div class="qs-all' + (q.allDone ? ' done' : '') + '">' + ic('chest-silver', 52) + '<div><b>Finish all three</b><small>A Silver Chest for completing every quest today</small></div>' +
            (q.allChestClaimed ? '<span class="qs-claimed">' + ic('check', 18) + ' Claimed</span>' : '<button type="button" class="econ-btn econ-btn-primary" data-claim="all"' + (q.allDone ? '' : ' disabled') + '>Claim</button>') + '</div>';
        p.innerHTML = html;
        $$('[data-goal]', p).forEach(function (b) { b.addEventListener('click', function () { E.setDailyGoal(Number(b.dataset.goal)); quests(p); $('[data-goal="' + b.dataset.goal + '"]', p).focus(); }); });
        $$('[data-claim]', p).forEach(function (b) {
            b.addEventListener('click', function () {
                var r = E.claim(b.dataset.claim);
                if (!r.ok) { UI.toast(esc(r.error), 'info'); return; }
                if (r.chest) { UI.openChests([r.chest.id], function () { quests(p); }); }
                else { UI.toast('+' + r.coins + ' coins', 'coin'); }
                quests(p); dots();
            });
        });
    }

    // ------------------------------------------------------------------ Shop
    var FRAME_SWATCH = { neon: 'linear-gradient(135deg,#00e0ff,#ff2bd6)', carbon: 'repeating-linear-gradient(45deg,#1b1f27 0 4px,#2b313c 4px 8px)', aurora: 'linear-gradient(135deg,#34c38f,#4ea8ff,#8a3ffc)', prism: 'conic-gradient(#ff3d6e,#ffcf4d,#34c38f,#4ea8ff,#8a3ffc,#ff3d6e)' };
    function shop(p) {
        var w = E.load(), rep = E.repairable(w);
        var html = '<div class="sh-head"><h2>Shop</h2><span class="sh-bal">' + ic('coin', 30) + '<b>' + w.coins + '</b> coins</span></div>' +
            '<p class="ar-small">Earn coins by training, finishing quests, opening chests and placing in your league.</p><div class="sh-grid">';
        E.SHOP.forEach(function (it) {
            if (it.id === 'repair' && !rep) { return; }
            var owned = it.frame && w.owned.frames.indexOf(it.frame) >= 0;
            var full = it.id === 'freeze' && w.inventory.freeze >= E.MAX_FREEZES;
            var short = w.coins < it.price;
            var status = owned ? 'Owned' : full ? 'Equipped 2/2' : '';
            html += '<div class="sh-item' + (it.frame ? ' frame' : '') + (it.id === 'repair' ? ' special' : '') + '">' +
                (it.frame ? '<span class="sh-swatch" style="background:' + FRAME_SWATCH[it.frame] + '" aria-hidden="true"></span>' : ic(it.icon, 56)) +
                '<b>' + esc(it.name) + (it.id === 'boost3' ? ' <span class="sh-tag">3x</span>' : it.id === 'boost2' ? ' <span class="sh-tag">2x</span>' : '') + '</b>' +
                '<small>' + esc(it.id === 'repair' ? 'Bring back your ' + rep.lost + '-day streak.' : it.desc) + '</small>' +
                (it.id === 'freeze' ? '<span class="sh-own">' + w.inventory.freeze + '/2 equipped</span>' : it.id === 'boost2' || it.id === 'boost3' ? '<span class="sh-own">' + w.inventory[it.id] + ' in bag</span>' : '') +
                '<button type="button" class="econ-btn ' + (status || short ? '' : 'econ-btn-primary') + '" data-buy="' + it.id + '"' + (status || short ? ' disabled' : '') + '>' +
                (status ? ic('check', 16) + ' ' + status : ic('coin', 20) + ' ' + it.price + (short ? '<span class="a11y-sr-only"> - not enough coins</span>' : '')) + '</button></div>';
        });
        html += '</div>';
        p.innerHTML = html;
        $$('[data-buy]', p).forEach(function (b) {
            b.addEventListener('click', function () {
                var r = E.buy(b.dataset.buy);
                if (!r.ok) { UI.toast(esc(r.error), 'info'); return; }
                var it = r.item;
                if (it.id === 'chest-silver' || it.id === 'chest-gold') {
                    var c = E.load().inventory.chests.slice(-1)[0];
                    UI.openChests([c.id], function () { shop(p); });
                } else {
                    UI.toast('Bought <b>' + esc(it.name) + '</b>' + (it.frame ? ' - equip it on your Athlete Card' : it.id.indexOf('boost') === 0 ? ' - activate it in your bag' : ''), it.frame ? 'sparkles' : it.icon);
                }
                shop(p); dots();
            });
        });
    }

    // ------------------------------------------------------------------ Bag
    function bag(p) {
        var w = E.load(), boost = E.boostActive(w);
        var chests = w.inventory.chests;
        var html = '<h2 class="ar-h2">Chests</h2>';
        if (!chests.length) { html += '<div class="ar-empty small">' + ic('chest-wood', 56) + '<p>No chests right now. Finish a session to earn one.</p></div>'; }
        else {
            html += '<div class="bg-chests">' + chests.map(function (c) {
                return '<button type="button" class="bg-chest" data-open="' + c.id + '">' + ic('chest-' + c.tier, 72) + '<b>' + esc(E.CHEST_NAMES[c.tier]) + '</b><small>' + esc(c.source || '') + '</small></button>';
            }).join('') + '</div>' + (chests.length > 1 ? '<button type="button" class="econ-btn econ-btn-primary" data-open-all>' + ic('gift', 18) + ' Open all ' + chests.length + '</button>' : '');
        }
        html += '<h2 class="ar-h2">Boosts</h2><div class="bg-boosts">';
        if (boost) {
            html += '<div class="bg-active">' + ic('boost', 48) + '<div><b>' + boost.mult + 'x XP is on</b><small>' + UI.fmtLeft(boost.until - Date.now()) + ' left - every session you finish now earns ' + boost.mult + 'x XP.</small></div></div>';
        }
        [['boost2', 'Double XP', '60 minutes of 2x XP'], ['boost3', 'Triple XP', '30 minutes of 3x XP']].forEach(function (b) {
            html += '<div class="bg-boost">' + ic('boost', 44) + '<div><b>' + b[1] + ' <span class="sh-tag">' + w.inventory[b[0]] + '</span></b><small>' + b[2] + '. Turn it on just before you train.</small></div>' +
                '<button type="button" class="econ-btn' + (w.inventory[b[0]] && !boost ? ' econ-btn-primary' : '') + '" data-activate="' + b[0] + '"' + (w.inventory[b[0]] && !boost ? '' : ' disabled') + '>Activate</button></div>';
        });
        html += '</div><h2 class="ar-h2">Streak Freezes</h2><div class="qs-freezes big">' + [0, 1].map(function (i) { return '<span class="qs-slot' + (i < w.inventory.freeze ? ' full' : '') + '">' + ic('freeze', 44) + '</span>'; }).join('') +
            '<span class="ar-small">' + w.inventory.freeze + ' of 2 equipped. A missed day uses one automatically.</span></div>';
        if (w.owned.frames.length) {
            html += '<h2 class="ar-h2">Card frames</h2><div class="bg-frames">' + w.owned.frames.map(function (f) {
                return '<span class="bg-frame"><span class="sh-swatch" style="background:' + FRAME_SWATCH[f] + '"></span>' + esc(f.charAt(0).toUpperCase() + f.slice(1)) + '</span>';
            }).join('') + '<a class="econ-btn" href="dashboard.html#athleteCard">Equip on your card ' + ic('arrow-right', 16) + '</a></div>';
        }
        var LEDGER_ICON = { coins: 'coin', xp: 'xp', freeze: 'freeze', boost: 'boost' };
        var led = (w.ledger || []).slice(-12).reverse();
        if (led.length) {
            html += '<h2 class="ar-h2">Recent activity</h2><ul class="bg-ledger">' + led.map(function (l) {
                return '<li>' + ic(LEDGER_ICON[l.type] || 'info', 24) + '<span>' + esc(l.note || l.type) + '</span>' +
                    (l.amount ? '<b class="' + (l.amount > 0 ? 'pos' : 'neg') + '">' + (l.amount > 0 ? '+' : '') + l.amount + (l.type === 'xp' ? ' XP' : '') + '</b>' : '<b></b>') +
                    '<time datetime="' + new Date(l.t).toISOString() + '">' + new Date(l.t).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + '</time></li>';
            }).join('') + '</ul>';
        }
        p.innerHTML = html;
        $$('[data-open]', p).forEach(function (b) { b.addEventListener('click', function () { UI.openChests([b.dataset.open], function () { bag(p); }); }); });
        var all = $('[data-open-all]', p);
        if (all) { all.addEventListener('click', function () { UI.openChests(E.load().inventory.chests.map(function (c) { return c.id; }), function () { bag(p); }); }); }
        $$('[data-activate]', p).forEach(function (b) {
            b.addEventListener('click', function () {
                var r = E.activateBoost(b.dataset.activate);
                if (!r.ok) { UI.toast(esc(r.error), 'info'); return; }
                UI.toast('<b>' + r.boost.mult + 'x XP</b> is on - go train!', 'boost');
                bag(p);
            });
        });
    }

    // ------------------------------------------------------------------ boot
    function boot() {
        UI.hud(document.getElementById('arenaHud'));
        var tabs = $$('[role="tab"]');
        tabs.forEach(function (b, i) {
            b.addEventListener('click', function () { select(b.dataset.tab); });
            b.addEventListener('keydown', function (e) {
                var k = e.key, n = null;
                if (k === 'ArrowRight') { n = tabs[(i + 1) % tabs.length]; } else if (k === 'ArrowLeft') { n = tabs[(i - 1 + tabs.length) % tabs.length]; }
                else if (k === 'Home') { n = tabs[0]; } else if (k === 'End') { n = tabs[tabs.length - 1]; }
                if (n) { e.preventDefault(); select(n.dataset.tab, true); }
            });
        });
        select((location.hash || '#league').slice(1));
        window.addEventListener('hashchange', function () { var t = location.hash.slice(1); if (t !== current && TABS.indexOf(t) >= 0) { select(t); } });
        document.addEventListener('cognicoach:wallet', function () { dots(); if (current === 'shop' || current === 'bag' || current === 'quests') { /* panels refresh after their own actions */ } });
        window.addEventListener('cognicoach:account', function () { setTimeout(function () { render(current); }, 600); });
        window.addEventListener('cognicoach:synced', function () { if (current !== 'friends' && current !== 'league') { render(current); } });
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }
})();
