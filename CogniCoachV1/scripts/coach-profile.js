// ==========================================================================
// Your coach: what CogniCoach knows about the athlete, so it coaches the person, not just the sport.
//   - "About you": the athlete's own words (position, level, goals, injuries), up to 400 characters
//   - what the coach has learned from training: drill ratings, readiness check-ins, how often
//     sessions are finished, how hard drills end up, recent focus areas. Worked out here in the
//     browser from saved history (no extra AI calls), shown to the athlete, and each item can be
//     forgotten. Learning can be switched off.
//   - context(sport): a short text added to drill requests and Competition Mode (notes + chat)
//     through fields the live backend already accepts (the request's focus / message), with
//     strip() so callers can retry without it if the backend ever rejects the longer text.
// Stored in localStorage 'cognicoach-coach' (synced by account.js as "coach").
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniCoachProfile) { return; }
    var KEY = 'cognicoach-coach';
    var MAX_ABOUT = 400, MAX_CTX = 440, MARK = ' || About the athlete: ';

    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function ic(n, s) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: s || 18 }) : ''; }
    function load() {
        var c;
        try { c = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { c = {}; }
        c.about = typeof c.about === 'string' ? c.about : '';
        c.learn = c.learn !== false;
        c.forget = Array.isArray(c.forget) ? c.forget : [];
        c.drills = Array.isArray(c.drills) ? c.drills : [];
        c.seen = Array.isArray(c.seen) ? c.seen : [];
        return c;
    }
    function save(c) {
        c.updatedAt = Date.now();
        try { localStorage.setItem(KEY, JSON.stringify(c)); } catch (e) {}
        document.dispatchEvent(new CustomEvent('cognicoach:coach'));
    }
    function history() { try { var h = JSON.parse(localStorage.getItem('cognicoach-history') || '[]'); return Array.isArray(h) ? h : []; } catch (e) { return []; } }
    function same(a, b) { return String(a || '').toLowerCase() === String(b || '').toLowerCase(); }
    // ------------------------------------------------------------------ learning
    // Each insight: { id, sport ('' = every sport), text (shown to the athlete), ctx (sent to the AI, optional) }
    function insights(c) {
        c = c || load();
        if (!c.learn) { return []; }
        var out = [], h = history();
        var sports = {};
        h.forEach(function (r) { if (r.sport) { sports[r.sport] = (sports[r.sport] || 0) + 1; } });

        Object.keys(sports).forEach(function (sport) {
            var rs = h.filter(function (r) { return same(r.sport, sport); });
            var last = rs.slice(-8);
            // drill ratings, by part of the session and by drill focus
            var ratings = c.drills.filter(function (d) { return same(d.sport, sport); }).slice(-30);
            var groups = {};
            ratings.forEach(function (d) {
                [['part', d.section], ['focus', d.focus]].forEach(function (g) {
                    if (!g[1] || /^general$/i.test(g[1])) { return; }
                    var k = g[0] + ':' + g[1].toLowerCase();
                    groups[k] = groups[k] || { kind: g[0], name: g[1], easy: 0, hard: 0, right: 0 };
                    groups[k][d.fb] = (groups[k][d.fb] || 0) + 1;
                });
            });
            Object.keys(groups).forEach(function (k) {
                var g = groups[k], n = g.easy + g.hard + g.right, what = g.name.toLowerCase() + ' drills';
                if (n < 3) { return; }
                if (g.easy - g.hard >= 2 && g.easy >= n / 2) { out.push({ id: 'easy:' + k + ':' + sport, sport: sport, text: 'You find ' + sport + ' ' + what + ' too easy, so those get harder.', ctx: 'finds ' + what + ' too easy, make them harder' }); }
                else if (g.hard - g.easy >= 2 && g.hard >= n / 2) { out.push({ id: 'hard:' + k + ':' + sport, sport: sport, text: 'You find ' + sport + ' ' + what + ' too hard, so those get easier.', ctx: 'finds ' + what + ' too hard, make them easier' }); }
            });
            // how hard sessions end up after ratings and check-ins
            var ints = last.map(function (r) { return r.intensity; }).filter(function (v) { return typeof v === 'number'; });
            if (ints.length >= 3) {
                var avg = ints.reduce(function (a, b) { return a + b; }, 0) / ints.length;
                if (avg >= 0.9) { out.push({ id: 'harder:' + sport, sport: sport, text: 'In ' + sport + ' you handle harder drills than standard for your level.', ctx: 'handles harder drills than standard for their level' }); }
                else if (avg <= -0.9) { out.push({ id: 'easier:' + sport, sport: sport, text: 'In ' + sport + ' easier drills than standard suit you best right now.', ctx: 'does best with easier drills than standard for their level' }); }
            }
            // recent focus areas
            var foc = {};
            rs.slice(-6).forEach(function (r) { var f = String(r.focus || '').trim(); if (f && !/^general$/i.test(f)) { foc[f] = (foc[f] || 0) + 1; } });
            var top = Object.keys(foc).sort(function (a, b) { return foc[b] - foc[a]; }).slice(0, 2);
            if (top.length && rs.length >= 2) { out.push({ id: 'focus:' + sport, sport: sport, text: 'Lately you have been working on ' + top.join(' and ') + ' in ' + sport + '.', ctx: 'recently working on ' + top.join(' and ') }); }
            // usual session length
            if (rs.length >= 3) {
                var mins = Math.round(rs.slice(-6).reduce(function (a, r) { return a + (Number(r.workoutLength) || 0); }, 0) / Math.min(6, rs.length) / 5) * 5;
                if (mins) { out.push({ id: 'len:' + sport, sport: sport, text: 'You usually train ' + sport + ' for about ' + mins + ' minutes.' }); }
            }
        });

        out = out.filter(function (i) {
            var m = /^(easy|hard):part:/.exec(i.id);
            return !m || !out.some(function (o) { return o.sport === i.sport && o.id.indexOf(m[1] + ':focus:') === 0; });
        });
        // across sports: energy and finishing
        var ready = h.slice(-8).map(function (r) { return r.readiness; }).filter(Boolean);
        if (ready.length >= 4) {
            var low = ready.filter(function (v) { return v === 'low'; }).length, high = ready.filter(function (v) { return v === 'high'; }).length;
            if (low >= ready.length / 2) { out.push({ id: 'energy:low', sport: '', text: 'You often start sessions low on energy.', ctx: 'often starts low on energy, favour quality over volume' }); }
            else if (high >= ready.length / 2) { out.push({ id: 'energy:high', sport: '', text: 'You usually come in fired up.', ctx: 'usually fired up, welcomes intense work' }); }
        }
        var lastS = h.slice(-6);
        if (lastS.length >= 4) {
            var done = lastS.filter(function (r) { return r.completed; }).length / lastS.length;
            if (done < 0.5) { out.push({ id: 'finish:low', sport: '', text: 'You often stop before the end, so key work comes earlier.', ctx: 'often ends sessions early, put the most important work first' }); }
            else if (done >= 0.9) { out.push({ id: 'finish:high', sport: '', text: 'You finish almost every session you start.' }); }
        }
        return out.filter(function (i) { return c.forget.indexOf(i.id) < 0; });
    }

    // Short text for the AI: the athlete's own words, then what the coach learned for this sport.
    function context(sport) {
        var c = load();
        var about = c.about.trim().replace(/\s+/g, ' ').slice(0, MAX_ABOUT);
        var notes = insights(c).filter(function (i) { return i.ctx && (!i.sport || same(i.sport, sport)); }).map(function (i) { return i.ctx; });
        var text = about;
        if (notes.length) {
            var rest = 'Coach notes: ' + notes.join('; ') + '.';
            while (notes.length && (text + ' ' + rest).length > MAX_CTX) { notes.pop(); rest = notes.length ? 'Coach notes: ' + notes.join('; ') + '.' : ''; }
            if (rest) { text = (text ? text + ' ' : '') + rest; }
        }
        return text.slice(0, MAX_CTX).trim();
    }
    var refused = false;   // the backend refused the longer request once: plain requests for this visit
    function apply(req, sport) {
        if (refused) { return req; }
        var ctx = context(sport || (req && req.sport));
        if (!ctx || !req) { return req; }
        var copy = {};
        Object.keys(req).forEach(function (k) { copy[k] = req[k]; });
        copy.focus = (req.focus || 'General') + MARK + ctx;
        return copy;
    }
    function strip(req) {
        refused = true;
        if (!req || typeof req.focus !== 'string' || req.focus.indexOf(MARK) < 0) { return null; }
        var copy = {};
        Object.keys(req).forEach(function (k) { copy[k] = req[k]; });
        copy.focus = req.focus.slice(0, req.focus.indexOf(MARK));
        return copy;
    }
    function forChat(message, sport) {
        var ctx = refused ? '' : context(sport);
        return ctx ? '(About me: ' + ctx + ')\n\n' + message : message;
    }

    // ------------------------------------------------------------------ learning inputs
    document.addEventListener('cognicoach:feedback', function (e) {
        var c = load();
        if (!c.learn) { return; }
        try {
            var s = appState.session, d = s.drills[s.currentDrillIndex], fb = e.detail && e.detail.feedback;
            var at = s.startedAt || 0, idx = s.currentDrillIndex;
            c.drills = c.drills.filter(function (x) { return !(x.at === at && x.i === idx); });   // re-rating replaces
            if (fb) {
                c.drills.push({ at: at, i: idx, sport: appState.setup.sport || '', section: d.sectionName || '',
                    focus: (d.generatedDrill && d.generatedDrill.focus) || '', fb: fb, t: Date.now() });
            }
            c.drills = c.drills.slice(-80);
            save(c);
        } catch (err) {}
    });

    // New things learned since last time (for the session recap).
    function takeNew() {
        var c = load();
        var now = insights(c), fresh = now.filter(function (i) { return c.seen.indexOf(i.id) < 0; });
        c.seen = now.map(function (i) { return i.id; }).concat(c.seen.filter(function (id) { return !now.some(function (i) { return i.id === id; }); })).slice(0, 60);
        save(c);
        return fresh;
    }
    function recapHtml() {
        var c = load();
        var fresh = takeNew();
        if (!c.about.trim()) {
            return '<div class="coach-recap"><span class="coach-recap-label">' + ic('user', 16) + ' Your coach</span>' +
                '<p>Tell your coach about you (position, level, goals, injuries) and every drill gets more personal.</p>' +
                '<button type="button" class="btn-chip" data-coach-edit>Tell your coach</button></div>';
        }
        if (!fresh.length) { return ''; }
        return '<div class="coach-recap"><span class="coach-recap-label">' + ic('idea', 16) + ' Your coach learned</span><ul>' +
            fresh.slice(0, 3).map(function (i) { return '<li>' + esc(i.text) + '</li>'; }).join('') + '</ul>' +
            '<button type="button" class="btn-chip" data-coach-edit>See everything</button></div>';
    }

    // ------------------------------------------------------------------ summary line + card
    function summary() {
        var c = load(), n = insights(c).length, about = c.about.trim();
        if (!about) { return { empty: true, html: 'nothing yet. Tell it your position, level and goals.' }; }
        var short = about.length > 70 ? about.slice(0, 68).replace(/\s+\S*$/, '') + '…' : about;
        return { empty: false, html: '<b>' + esc(short) + '</b>' + (n ? ' · ' + n + ' thing' + (n === 1 ? '' : 's') + ' learned' : '') };
    }
    function paintHosts() {
        var s = summary();
        document.querySelectorAll('[data-coach-summary]').forEach(function (host) {
            host.classList.toggle('coach-empty', s.empty);
            host.innerHTML = '<p class="coach-sum"><span class="qs-sum-k">Your coach knows:</span> ' + s.html + '</p>' +
                '<button type="button" class="btn-chip" data-coach-edit aria-haspopup="dialog">' + (s.empty ? 'Tell your coach' : 'Edit') + '</button>';
        });
    }

    // ------------------------------------------------------------------ dialog
    var dlg = null, lastFocus = null, lastHost = null;
    function close() {
        if (!dlg) { return; }
        dlg.remove();
        dlg = null;
        document.removeEventListener('keydown', onKey, true);
        var back = lastFocus;
        if (back && !back.isConnected && lastHost) { back = lastHost.querySelector('[data-coach-edit]'); }
        if (back && back.focus) { try { back.focus(); } catch (e) {} }
    }
    function onKey(e) {
        if (!dlg) { return; }
        if (e.key === 'Escape') { e.preventDefault(); close(); return; }
        if (e.key === 'Tab') {   // keep focus inside
            var f = dlg.querySelectorAll('button, textarea, input, [href]');
            var list = Array.prototype.filter.call(f, function (x) { return !x.disabled && x.offsetParent !== null; });
            if (!list.length) { return; }
            var first = list[0], lastEl = list[list.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); lastEl.focus(); }
            else if (!e.shiftKey && document.activeElement === lastEl) { e.preventDefault(); first.focus(); }
        }
    }
    function learnedHtml(c) {
        var list = insights(c);
        if (!c.learn) { return '<p class="coach-muted">Learning is off. Your coach only uses what you wrote above.</p>'; }
        if (!list.length) { return '<p class="coach-muted">Nothing yet. It learns from your sessions, how you feel before training and how you rate drills.</p>'; }
        return '<ul class="coach-learned">' + list.map(function (i) {
            return '<li><span>' + esc(i.text) + '</span><button type="button" class="coach-forget" data-forget="' + esc(i.id) + '" aria-label="Forget: ' + esc(i.text) + '">' + ic('close', 16) + '</button></li>';
        }).join('') + '</ul>';
    }
    function open() {
        if (dlg) { return; }
        lastFocus = document.activeElement;
        lastHost = lastFocus && lastFocus.closest ? lastFocus.closest('[data-coach-summary], .coach-recap') : null;
        var c = load();
        dlg = document.createElement('div');
        dlg.className = 'coach-overlay';
        dlg.innerHTML =
            '<div class="coach-dialog" role="dialog" aria-modal="true" aria-labelledby="coachDlgTitle">' +
            '  <div class="coach-head"><h2 id="coachDlgTitle">Your coach</h2><button type="button" class="coach-x" data-coach-close aria-label="Close">' + ic('close', 20) + '</button></div>' +
            '  <p class="coach-intro">What you write here and what your coach learns go into every drill and into Competition Mode, so it coaches you, not just your sport.</p>' +
            '  <label for="coachAbout" class="coach-label">About you as an athlete</label>' +
            '  <textarea id="coachAbout" maxlength="' + MAX_ABOUT + '" rows="4" aria-describedby="coachAboutHint coachCount" placeholder="e.g. 16, point guard on my school team. Good shooter, want a quicker first step. Coming back from a sprained left ankle.">' + esc(c.about) + '</textarea>' +
            '  <div class="coach-row"><span id="coachAboutHint" class="coach-muted">Position, level, goals, injuries, anything a coach should know.</span><span id="coachCount" class="coach-muted" aria-live="polite"></span></div>' +
            '  <h3 class="coach-label">What your coach has learned</h3>' +
            '  <div class="coach-learned-host">' + learnedHtml(c) + '</div>' +
            '  <label class="coach-check"><input type="checkbox" id="coachLearn"' + (c.learn ? ' checked' : '') + '> Learn from my training</label>' +
            '  <p class="coach-muted coach-privacy">Friends never see this. It is sent to the AI with your requests, so leave out anything private.</p>' +
            '  <div class="coach-actions"><button type="button" class="btn btn-secondary" data-coach-close>Cancel</button><button type="button" class="btn btn-primary" data-coach-save>Save</button></div>' +
            '</div>';
        document.body.appendChild(dlg);
        var ta = dlg.querySelector('#coachAbout'), count = dlg.querySelector('#coachCount'), learn = dlg.querySelector('#coachLearn');
        var forgotten = [];
        function paintCount() { count.textContent = ta.value.length + '/' + MAX_ABOUT; }
        paintCount();
        ta.addEventListener('input', paintCount);
        dlg.addEventListener('click', function (e) {
            if (e.target === dlg || e.target.closest('[data-coach-close]')) { close(); return; }
            var fg = e.target.closest('[data-forget]');
            if (fg) {
                forgotten.push(fg.getAttribute('data-forget'));
                var li = fg.closest('li'), next = li.nextElementSibling || li.previousElementSibling;
                li.remove();
                var nb = next && next.querySelector('button');
                (nb || learn).focus();
                return;
            }
            if (e.target.closest('[data-coach-save]')) {
                var cur = load();
                cur.about = ta.value.slice(0, MAX_ABOUT);
                cur.learn = learn.checked;
                cur.forget = cur.forget.concat(forgotten.filter(function (id) { return cur.forget.indexOf(id) < 0; }));
                close();
                save(cur);   // repaints the summary; close() already noted where focus goes back
                var h = lastHost && lastHost.isConnected ? lastHost.querySelector('[data-coach-edit]') : null;
                if (h) { h.focus(); }
            }
        });
        document.addEventListener('keydown', onKey, true);
        ta.focus();
    }
    document.addEventListener('click', function (e) {
        var b = e.target.closest && e.target.closest('[data-coach-edit]');
        if (b) { e.preventDefault(); open(); }
    });

    document.addEventListener('cognicoach:coach', paintHosts);
    window.addEventListener('cognicoach:synced', paintHosts);
    document.addEventListener('cognicoach:session-end', function () { setTimeout(paintHosts, 100); });
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', paintHosts); } else { paintHosts(); }

    window.CogniCoachProfile = { context: context, apply: apply, strip: strip, forChat: forChat, insights: insights,
        recapHtml: recapHtml, open: open, load: load, MARK: MARK };
})();
