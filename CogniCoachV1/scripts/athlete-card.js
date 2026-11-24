// ==========================================================================
// Athlete Card (dashboard) - a holographic 3D card that tilts with the pointer.
//   - OVR rating and rank emblem (scripts/athlete-stats.js does the maths)
//   - a frame for every rank tier: unlock it by reaching the tier, then equip
//     any frame you have unlocked (or "Auto" = your current rank)
//   - earned titles shown under your name, plus the full title collection
//   - rank ladder with progress to the next division
//   - coach insights from check-ins and drill ratings
//   - "Download card" draws the card (frame, rank, title) to a PNG
// Nothing is sent anywhere; choices sync with an account via dashboard settings.
// ==========================================================================
(function () {
    'use strict';
    var CS = window.CogniStats;
    if (!CS) { return; }

    function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
    function fmtSaved(min) { return min >= 60 ? (Math.round(min / 6) / 10) + ' h' : min + ' m'; }

    function athleteName() {
        try { var s = window.CogniAccount && window.CogniAccount.session(); if (s && s.username) { return s.username; } } catch (e) {}
        try { var d = JSON.parse(localStorage.getItem('cognicoach-dashboard') || '{}'); if (d && d.username) { return String(d.username); } } catch (e) {}
        return 'Athlete';
    }

    // ------------------------------------------------------------------ rank emblem (SVG)
    var emblemId = 0;
    function emblem(rank, size) {
        var id = 'emb' + (++emblemId);
        var t = rank.placed ? rank.tier : { color: '#7b8798', light: '#dfe5ee', id: 'none' };
        var mark = rank.placed ? (rank.division || '★') : '?';
        var gems = rank.placed ? Math.min(rank.index, 6) : 0;
        var dots = '';
        for (var g = 0; g < gems; g++) {
            var a = Math.PI * (0.15 + 0.7 * (gems === 1 ? 0.5 : g / (gems - 1)));
            dots += '<circle cx="' + (50 - Math.cos(a) * 34).toFixed(1) + '" cy="' + (16 + Math.sin(a) * -6 + 6).toFixed(1) + '" r="3.2" fill="#fff" opacity="0.9"/>';
        }
        return '<svg class="rank-emblem" width="' + size + '" height="' + size + '" viewBox="0 0 100 110" aria-hidden="true">' +
            '<defs><linearGradient id="' + id + '" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="' + t.light + '"/><stop offset="0.55" stop-color="' + t.color + '"/><stop offset="1" stop-color="#1b2233"/></linearGradient>' +
            '<linearGradient id="' + id + 's" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity="0.55"/><stop offset="0.5" stop-color="#fff" stop-opacity="0"/></linearGradient></defs>' +
            '<path d="M50 4 L92 20 L88 62 Q82 92 50 106 Q18 92 12 62 L8 20 Z" fill="url(#' + id + ')" stroke="' + t.light + '" stroke-width="3"/>' +
            '<path d="M50 14 L82 26 L79 60 Q74 84 50 96 Q26 84 21 60 L18 26 Z" fill="none" stroke="rgba(255,255,255,0.45)" stroke-width="2"/>' +
            '<path d="M50 4 L92 20 L90 40 Q50 30 10 40 L8 20 Z" fill="url(#' + id + 's)"/>' + dots +
            '<text x="50" y="70" text-anchor="middle" font-family="Orbitron, sans-serif" font-weight="900" font-size="' + (mark.length > 2 ? 22 : 28) + '" fill="#fff" stroke="rgba(0,0,0,0.25)" stroke-width="1">' + mark + '</text>' +
            '</svg>';
    }

    // ------------------------------------------------------------------ frame + title choice
    function chosenFrame(st, prefs) {
        var f = prefs.frame || 'auto';
        if (f === 'auto') { return st.rank.placed ? st.rank.tier.id : 'none'; }
        var idx = CS.TIERS.map(function (t) { return t.id; }).indexOf(f);
        return idx >= 0 && idx <= st.peakIndex ? f : (st.rank.placed ? st.rank.tier.id : 'none');
    }
    function chosenTitle(st, prefs) {
        var t = st.titles.filter(function (x) { return x.earned && x.id === prefs.title; })[0];
        if (t) { return t; }
        var earned = st.titles.filter(function (x) { return x.earned; });
        return earned[earned.length - 1];   // the latest one earned (list is ordered roughly by difficulty)
    }

    // ------------------------------------------------------------------ insights
    function insights(st) {
        var out = [];
        var rated = st.fb.easy + st.fb.right + st.fb.hard;
        if (!st.sessions) { return [['🚀', 'Finish your first session to start your placement. ' + CS.PLACEMENT + ' sessions and you are ranked.']]; }
        if (!st.rank.placed) { out.push(['🏅', st.rank.toGo + ' more session' + (st.rank.toGo === 1 ? '' : 's') + ' to finish placement and get your rank.']); }
        else if (st.rank.next) { out.push(['🏅', st.rank.pointsToNext + ' OVR to ' + st.rank.next + '. Streak days and weekly minutes move it fastest.']); }
        if (rated >= 3) {
            if (st.fb.easy > st.fb.hard * 2) { out.push(['⬆️', 'You rate most drills too easy (' + st.fb.easy + ' of ' + rated + '). Raise your level in Advanced Setup.']); }
            else if (st.fb.hard > st.fb.easy * 2) { out.push(['🌿', 'Lots of drills feel too hard (' + st.fb.hard + ' of ' + rated + '). The coach is easing off - check in honestly before each session.']); }
            else { out.push(['🎯', 'Your drills are well matched: ' + st.fb.right + ' of ' + rated + ' rated just right.']); }
        } else {
            out.push(['💬', 'Rate drills as you go (too easy / just right / too hard) and the coach tunes every session to you.']);
        }
        if (st.ready.low >= 3) { out.push(['🔋', 'You checked in with low energy ' + st.ready.low + ' times lately. Sleep and recovery are training too.']); }
        if (st.streak >= 3) { out.push(['🔥', st.streak + '-day streak. Keep it alive with even a 15-minute session.']); }
        out.push(['⌛', 'CogniCoach has saved you about ' + fmtSaved(st.saved).replace(' h', ' hours').replace(' m', ' minutes') + ' of planning.']);
        return out.slice(0, 4);
    }

    // ------------------------------------------------------------------ render
    function render() {
        var anchor = document.getElementById('profileSummaryCard');
        if (!anchor) { return; }
        var st = CS.compute();
        var prefs = CS.cardPrefs();
        var frame = chosenFrame(st, prefs);
        var title = chosenTitle(st, prefs);
        var host = document.getElementById('athleteCard');
        if (!host) {
            host = document.createElement('section');
            host.id = 'athleteCard';
            host.className = 'card dash-card dash-span-12 athlete-section';
            host.setAttribute('aria-labelledby', 'athleteCardTitle');
            anchor.parentNode.insertBefore(host, anchor);
        }
        var name = athleteName();
        var r = st.rank;
        var top = st.top.length > 10 ? st.top.slice(0, 9) + '…' : st.top;
        var earnedTitles = st.titles.filter(function (t) { return t.earned; });

        host.innerHTML =
            '<h2 class="card-title" id="athleteCardTitle">Athlete Card</h2>' +
            '<div class="ac-layout">' +
            '<div class="ac-stage">' +
            '  <div class="ac-card" data-frame="' + frame + '" tabindex="0" role="img" aria-label="' + esc(name) + ', ' + esc(r.label) + ', ' + esc(st.level.cur.name) + ', overall ' + st.ovr + (title ? ', title ' + esc(title.name) : '') + '. ' + st.sessions + ' sessions, ' + st.minutes + ' minutes, ' + st.streak + ' day streak, top sport ' + esc(st.top) + '.">' +
            '    <div class="ac-frame" aria-hidden="true"></div>' +
            '    <div class="ac-face" aria-hidden="true">' +
            '      <div class="ac-holo" aria-hidden="true"></div>' +
            '      <div class="ac-top"><div class="ac-ovr"><b>' + st.ovr + '</b><span>OVR</span></div><div class="ac-emblem">' + emblem(r, 58) + '<span>' + esc(r.label) + '</span></div></div>' +
            '      <div class="ac-avatar" aria-hidden="true"><span>' + esc(name.charAt(0).toUpperCase()) + '</span></div>' +
            '      <div class="ac-name">' + esc(name) + '</div>' +
            (title ? '      <div class="ac-title">“' + esc(title.name) + '”</div>' : '') +
            '      <div class="ac-level">' + esc(st.level.cur.name) + ' · ' + st.xp + ' XP</div>' +
            '      <div class="ac-xp" aria-hidden="true"><span style="width:' + Math.round(st.level.pct * 100) + '%"></span></div>' +
            '      <div class="ac-grid">' +
            cell(st.sessions, 'Sessions') + cell(st.minutes, 'Minutes') + cell(st.streak, 'Streak') +
            cell(esc(top), 'Top sport') + cell(st.weekMin, 'This week') + cell(fmtSaved(st.saved), 'Saved') +
            '      </div>' +
            '      <div class="ac-foot">CogniCoach<span>AI</span></div>' +
            '    </div>' +
            '  </div>' +
            '  <button type="button" class="btn btn-secondary ac-download">Download card</button>' +
            '</div>' +

            '<div class="ac-side">' +
            // rank panel
            '<div class="ac-rank">' +
            '  <div class="ac-rank-head">' + emblem(r, 84) + '<div><div class="ac-rank-kicker">Current rank</div><div class="ac-rank-name" data-tier="' + (r.placed ? r.tier.id : 'none') + '">' + esc(r.label) + '</div>' +
            '  <div class="ac-rank-sub">' + (r.placed ? (r.next ? r.pointsToNext + ' OVR to ' + esc(r.next) : 'The top. Keep it.') : 'Placement: ' + (CS.PLACEMENT - r.toGo) + ' of ' + CS.PLACEMENT + ' sessions') + '</div></div></div>' +
            '  <div class="ac-rank-bar" role="progressbar" aria-label="Progress to next rank" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round((r.placed ? r.progress : (CS.PLACEMENT - r.toGo) / CS.PLACEMENT) * 100) + '"><span style="width:' + Math.round((r.placed ? r.progress : (CS.PLACEMENT - r.toGo) / CS.PLACEMENT) * 100) + '%"></span></div>' +
            '  <ol class="ac-ladder" aria-label="Rank tiers">' + CS.TIERS.map(function (t, i) {
                var state = r.placed && i === r.index ? 'current' : i <= st.peakIndex ? 'unlocked' : 'locked';
                return '<li class="ac-rung" data-tier="' + t.id + '" data-state="' + state + '" title="' + t.name + ' · OVR ' + t.min + '+"><span class="ac-rung-dot" aria-hidden="true"></span><span class="ac-rung-name">' + t.name + '</span><span class="a11y-sr-only">' + (state === 'current' ? ' (your rank)' : state === 'unlocked' ? ' (reached)' : ' (OVR ' + t.min + ')') + '</span></li>';
            }).join('') + '</ol>' +
            '  <p class="ac-rank-note">Rank follows your current form (OVR), so it can slip if you stop training. Frames you unlock are yours for good.</p>' +
            '</div>' +

            // frame picker
            '<fieldset class="ac-pick"><legend>Card frame</legend><div class="ac-frames">' +
            frameOpt('auto', 'Auto', 'Matches your rank', true, (prefs.frame || 'auto') === 'auto') +
            CS.TIERS.map(function (t, i) { return frameOpt(t.id, t.name, i <= st.peakIndex ? 'Unlocked' : 'Reach ' + t.name, i <= st.peakIndex, prefs.frame === t.id); }).join('') +
            '</div></fieldset>' +

            // titles
            '<div class="ac-pick"><label class="ac-title-label" for="acTitleSelect">Title on your card</label>' +
            '<select id="acTitleSelect">' + earnedTitles.map(function (t) { return '<option value="' + t.id + '"' + (title && t.id === title.id ? ' selected' : '') + '>' + esc(t.name) + '</option>'; }).join('') + '</select>' +
            '<details class="ac-titles"><summary>All titles (' + earnedTitles.length + ' of ' + st.titles.length + ' earned)</summary><ul>' +
            st.titles.map(function (t) { return '<li data-earned="' + t.earned + '"><span class="ac-t-icon" aria-hidden="true">' + (t.earned ? '🏆' : '🔒') + '</span><span><b>' + esc(t.name) + '</b><small>' + esc(t.how) + (t.earned ? '' : ' (locked)') + '</small></span></li>'; }).join('') +
            '</ul></details></div>' +

            '<div class="ac-insights"><h3>Coach insights</h3><ul>' +
            insights(st).map(function (i) { return '<li><span class="ac-ins-icon" aria-hidden="true">' + i[0] + '</span><span>' + esc(i[1]) + '</span></li>'; }).join('') +
            '</ul></div>' +
            '</div>' +
            '</div>';

        wireTilt(host.querySelector('.ac-card'));
        host.querySelector('.ac-download').addEventListener('click', function () { download(st, name, frame, title); });
        host.querySelectorAll('input[name="acFrame"]').forEach(function (inp) {
            inp.addEventListener('change', function () { if (inp.checked) { CS.saveCardPrefs({ frame: inp.value }); render(); focusAgain('input[name="acFrame"][value="' + inp.value + '"]'); } });
        });
        var sel = host.querySelector('#acTitleSelect');
        if (sel) { sel.addEventListener('change', function () { CS.saveCardPrefs({ title: sel.value }); render(); focusAgain('#acTitleSelect'); }); }
        if (location.hash === '#athleteCard' && !render.scrolled) { render.scrolled = true; setTimeout(function () { host.scrollIntoView({ block: 'start' }); }, 200); }
    }
    function focusAgain(sel) { var el = document.querySelector('#athleteCard ' + sel); if (el) { el.focus(); } }
    function cell(v, l) { return '<div class="ac-cell"><b>' + v + '</b><span>' + l + '</span></div>'; }
    function frameOpt(id, name, sub, unlocked, checked) {
        return '<label class="ac-frame-opt" data-tier="' + id + '"' + (unlocked ? '' : ' data-locked="true"') + '>' +
            '<input type="radio" name="acFrame" value="' + id + '"' + (checked ? ' checked' : '') + (unlocked ? '' : ' disabled') + '>' +
            '<span class="ac-swatch" aria-hidden="true">' + (unlocked ? '' : '🔒') + '</span>' +
            '<span class="ac-frame-name">' + name + '</span><span class="ac-frame-sub">' + sub + '</span></label>';
    }

    // ------------------------------------------------------------------ 3D tilt + holo light
    function wireTilt(card) {
        if (!card) { return; }
        var reduce = function () { return document.documentElement.classList.contains('a11y-reduce-motion'); };
        var raf = 0;
        function set(x, y) {
            card.style.setProperty('--rx', ((0.5 - y) * 22).toFixed(2) + 'deg');
            card.style.setProperty('--ry', ((x - 0.5) * 26).toFixed(2) + 'deg');
            card.style.setProperty('--mx', (x * 100).toFixed(1) + '%');
            card.style.setProperty('--my', (y * 100).toFixed(1) + '%');
        }
        card.addEventListener('pointermove', function (e) {
            if (reduce()) { return; }
            var rc = card.getBoundingClientRect();
            var x = (e.clientX - rc.left) / rc.width, y = (e.clientY - rc.top) / rc.height;
            cancelAnimationFrame(raf);
            raf = requestAnimationFrame(function () { card.classList.add('ac-live'); set(x, y); });
        });
        card.addEventListener('pointerleave', function () { card.classList.remove('ac-live'); set(0.5, 0.5); });
        set(0.5, 0.5);
    }

    // ------------------------------------------------------------------ PNG export
    var FRAME_STOPS = {
        none: ['#9fb4d3', '#5d6f8c'], bronze: ['#f0c39a', '#8a4b1f'], silver: ['#ffffff', '#7d8796'], gold: ['#fff1a8', '#b8860b'],
        platinum: ['#e3fffb', '#1d8c84'], diamond: ['#e8f4ff', '#2f6fe0'], master: ['#f0d9ff', '#5b1fc0'], legend: ['#ffe28a', '#ff3d6e']
    };
    function download(st, name, frame, title) {
        var W = 720, H = 1040, c = document.createElement('canvas');
        c.width = W; c.height = H;
        var g = c.getContext('2d');
        var rr = function (x, y, w, h, r) { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); };
        var fit = function (text, weight, size, min, maxW) { g.font = weight + ' ' + size + 'px Orbitron, sans-serif'; while (size > min && g.measureText(text).width > maxW) { size -= 2; g.font = weight + ' ' + size + 'px Orbitron, sans-serif'; } };
        // frame
        var fs = FRAME_STOPS[frame] || FRAME_STOPS.none;
        var fg = g.createLinearGradient(0, 0, W, H);
        fg.addColorStop(0, fs[0]); fg.addColorStop(0.5, fs[1]); fg.addColorStop(1, fs[0]);
        rr(0, 0, W, H, 52); g.fillStyle = fg; g.fill();
        // face
        var bg = g.createLinearGradient(0, 0, W, H);
        bg.addColorStop(0, '#0d2a52'); bg.addColorStop(0.55, '#173d72'); bg.addColorStop(1, '#5a2c0e');
        rr(22, 22, W - 44, H - 44, 38); g.fillStyle = bg; g.fill();
        var holo = g.createLinearGradient(0, 0, W, H);
        holo.addColorStop(0, 'rgba(78,168,255,0.3)'); holo.addColorStop(0.5, 'rgba(255,255,255,0.04)'); holo.addColorStop(1, 'rgba(255,138,52,0.3)');
        g.fillStyle = holo; g.fill();
        g.fillStyle = '#fff'; g.textBaseline = 'alphabetic';
        g.font = '900 120px Orbitron, sans-serif'; g.fillText(String(st.ovr), 64, 176);
        g.font = '700 32px Orbitron, sans-serif'; g.fillStyle = '#ffb979'; g.fillText('OVR', 70, 220);
        // rank badge
        var t = st.rank.placed ? st.rank.tier : { color: '#7b8798', light: '#dfe5ee' };
        g.save(); g.translate(W - 140, 70);
        g.beginPath(); g.moveTo(50, 0); g.lineTo(96, 18); g.lineTo(92, 62); g.quadraticCurveTo(84, 98, 50, 114); g.quadraticCurveTo(16, 98, 8, 62); g.lineTo(4, 18); g.closePath();
        var eg = g.createLinearGradient(0, 0, 96, 114); eg.addColorStop(0, t.light); eg.addColorStop(0.55, t.color); eg.addColorStop(1, '#1b2233');
        g.fillStyle = eg; g.fill(); g.lineWidth = 4; g.strokeStyle = t.light; g.stroke();
        g.textAlign = 'center'; g.fillStyle = '#fff'; g.font = '900 30px Orbitron, sans-serif';
        g.fillText(st.rank.placed ? (st.rank.division || '★') : '?', 50, 72);
        g.font = '700 20px Orbitron, sans-serif'; g.fillStyle = '#ffe1c2'; g.fillText(st.rank.placed ? st.rank.tier.name.toUpperCase() : 'UNRANKED', 50, 148);
        g.restore();
        g.textAlign = 'center';
        var av = g.createRadialGradient(W / 2 - 30, 350, 10, W / 2, 380, 110);
        av.addColorStop(0, '#7cc0ff'); av.addColorStop(1, '#1a6dcc');
        g.beginPath(); g.arc(W / 2, 380, 104, 0, Math.PI * 2); g.fillStyle = av; g.fill();
        g.lineWidth = 8; g.strokeStyle = fs[1]; g.stroke();
        g.fillStyle = '#fff'; g.font = '900 104px Orbitron, sans-serif'; g.fillText(name.charAt(0).toUpperCase(), W / 2, 418);
        var nm = name.length > 16 ? name.slice(0, 15) + '…' : name;
        fit(nm, '700', 54, 28, W - 140); g.fillText(nm, W / 2, 562);
        var y = 606;
        if (title) { g.font = 'italic 400 30px "Space Mono", monospace'; g.fillStyle = '#ffe1c2'; g.fillText('“' + title.name + '”', W / 2, y); y += 42; }
        g.font = '400 28px "Space Mono", monospace'; g.fillStyle = '#cfe3ff'; g.fillText(st.level.cur.name + ' · ' + st.xp + ' XP · ' + (st.rank.placed ? st.rank.label : 'Unranked'), W / 2, y);
        var cells = [[st.sessions, 'SESSIONS'], [st.minutes, 'MINUTES'], [st.streak, 'STREAK'], [st.top.length > 14 ? st.top.slice(0, 13) + '…' : st.top, 'TOP SPORT'], [st.weekMin, 'THIS WEEK'], [fmtSaved(st.saved), 'SAVED']];
        cells.forEach(function (cl, i) {
            var cx = 64 + (i % 3) * 200, cy = 692 + Math.floor(i / 3) * 136;
            rr(cx, cy, 184, 118, 22); g.fillStyle = 'rgba(255,255,255,0.1)'; g.fill();
            g.fillStyle = '#fff'; fit(String(cl[0]), '700', 40, 18, 164); g.fillText(String(cl[0]), cx + 92, cy + 62);
            g.fillStyle = '#a9c4e6'; g.font = '400 20px "Space Mono", monospace'; g.fillText(cl[1], cx + 92, cy + 96);
        });
        g.fillStyle = '#9fb4d3'; g.font = '400 22px "Space Mono", monospace'; g.fillText('cognicoachai.com', W / 2, H - 50);
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
        window.addEventListener('storage', function (e) { if (e.key === 'cognicoach-history' || e.key === 'cognicoach-dashboard') { render(); } });
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }
    window.CogniAthleteCard = { render: render, emblem: emblem };
})();
