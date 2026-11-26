// ==========================================================================
// Session timeline: the whole workout you built (warm-up -> main work -> cool-down ...) as a bar
// of drills, showing what's done, the drill you're on (filling live with its timer) and what's next.
// Reads appState (scripts/script.js); updates itself when the drill or the timer changes.
// ==========================================================================
(function () {
    'use strict';
    var root, expanded = false, demo = null, lastSig = '';

    function esc(t) {
        return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function mmss(sec) {
        sec = Math.max(0, Math.round(sec || 0));
        var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
        return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
    }
    function niceLen(sec) {
        var m = Math.round((sec || 0) / 60);
        return m >= 1 ? m + ' min' : Math.round(sec || 0) + ' s';
    }

    function state() {
        if (demo) { return demo; }
        if (typeof appState === 'undefined' || !appState.session) { return null; }
        var s = appState.session;
        return {
            drills: s.drills || [],
            index: s.currentDrillIndex || 0,
            sections: (appState.setup && appState.setup.sections) || [],
            remaining: s.timeRemaining, total: s.totalTime, started: !!s.timerStarted
        };
    }

    function drillName(d) {
        var g = d && d.generatedDrill;
        if (!g) { return ''; }
        if (typeof g === 'string') { try { g = JSON.parse(g); } catch (e) { return ''; } }
        return g.name || g.Name || '';
    }

    function render() {
        if (!root) { return; }
        var st = state();
        var oldLine = root.previousElementSibling && root.previousElementSibling.classList.contains('progress-indicator') ? root.previousElementSibling : null;
        if (!st || !st.drills.length) { root.innerHTML = ''; root.hidden = true; if (oldLine) { oldLine.hidden = false; } return; }
        root.hidden = false;
        if (oldLine) { oldLine.hidden = true; }   // the timeline header says "Drill 3 of 8" already
        var drills = st.drills, cur = Math.min(st.index, drills.length - 1);
        var total = drills.reduce(function (s, d) { return s + (d.drillTime || 0); }, 0) || 1;
        var curLen = drills[cur].drillTime || 0;
        var curLeft = st.started && typeof st.remaining === 'number' ? st.remaining : curLen;
        var curPct = curLen ? Math.max(0, Math.min(100, 100 * (1 - curLeft / curLen))) : 0;
        var left = curLeft + drills.slice(cur + 1).reduce(function (s, d) { return s + (d.drillTime || 0); }, 0);
        var color = function (d) { var sec = st.sections[d.section]; return (sec && sec.color) || '#1f7ae0'; };
        var section = function (d) { return d.sectionName || (st.sections[d.section] || {}).name || 'Drill'; };

        // segments
        var segs = drills.map(function (d, i) {
            var stt = i < cur ? 'done' : i === cur ? 'current' : 'next';
            var name = drillName(d);
            var tip = 'Drill ' + (i + 1) + ' · ' + section(d) + ' · ' + niceLen(d.drillTime) + (name ? ' - ' + name : '') +
                (stt === 'done' ? ' (done)' : stt === 'current' ? ' (now)' : '');
            return '<div class="st-seg ' + stt + '" style="flex:' + Math.max(1, d.drillTime || 1) + ' 1 0;--c:' + esc(color(d)) + '" title="' + esc(tip) + '">' +
                '<span class="st-fill"' + (stt === 'current' ? ' style="width:' + curPct.toFixed(1) + '%"' : '') + '></span>' +
                (stt === 'done' ? '<span class="st-check" aria-hidden="true"></span>' : '') +
                (stt === 'current' ? '<span class="st-here" aria-hidden="true"></span>' : '') +
                '</div>';
        }).join('');

        // section labels under the bar (consecutive drills of one section grouped)
        var groups = [];
        drills.forEach(function (d) {
            var name = section(d), g = groups[groups.length - 1];
            if (g && g.name === name) { g.time += d.drillTime || 0; } else { groups.push({ name: name, time: d.drillTime || 0, color: color(d) }); }
        });
        var labels = groups.map(function (g) {
            return '<div class="st-label" style="flex:' + Math.max(1, g.time) + ' 1 0;--c:' + esc(g.color) + '"><i></i><span>' + esc(g.name) + '</span></div>';
        }).join('');

        var list = drills.map(function (d, i) {
            var stt = i < cur ? 'done' : i === cur ? 'current' : 'next';
            var name = drillName(d) ||
                (i === cur ? 'Loading…' : i === cur + 1 ? 'Getting ready…' : i > cur ? 'Comes up when you get there' : 'Done');
            return '<li class="' + stt + '" style="--c:' + esc(color(d)) + '"><span class="st-num">' + (stt === 'done' ? '' : i + 1) + '</span>' +
                '<span class="st-name">' + esc(name) + '</span><span class="st-sec">' + esc(section(d)) + '</span>' +
                '<span class="st-time">' + niceLen(d.drillTime) + '</span></li>';
        }).join('');

        root.innerHTML =
            '<div class="st-head">' +
            '  <div class="st-where"><b>Drill ' + (cur + 1) + '</b> of ' + drills.length + ' <span class="st-dot">·</span> ' +
            '    <span class="st-section" style="--c:' + esc(color(drills[cur])) + '">' + esc(section(drills[cur])) + '</span></div>' +
            '  <div class="st-left">' + mmss(left) + ' left in session</div>' +
            '  <button type="button" class="st-toggle" aria-expanded="' + expanded + '">' + (expanded ? 'Hide drills' : 'All drills') + '</button>' +
            '</div>' +
            '<div class="st-bar" role="img" aria-label="Drill ' + (cur + 1) + ' of ' + drills.length + ', ' + Math.round(100 * (total - left) / total) + '% of the session done">' + segs + '</div>' +
            '<div class="st-labels">' + labels + '</div>' +
            '<ol class="st-list"' + (expanded ? '' : ' hidden') + '>' + list + '</ol>';
        root.querySelector('.st-toggle').onclick = function () { expanded = !expanded; render(); };
    }

    // Every second: a full rebuild only when the drill list / current drill / names change;
    // otherwise just move the current drill's fill and the clock (no layout churn).
    function liveNumbers(st) {
        var drills = st.drills, cur = Math.min(st.index, drills.length - 1);
        var curLen = drills[cur].drillTime || 0;
        var curLeft = st.started && typeof st.remaining === 'number' ? st.remaining : curLen;
        var left = curLeft + drills.slice(cur + 1).reduce(function (s, d) { return s + (d.drillTime || 0); }, 0);
        return { pct: curLen ? Math.max(0, Math.min(100, 100 * (1 - curLeft / curLen))) : 0, left: left };
    }
    function tick() {
        var st = state();
        var sig = st ? [st.drills.length, st.index, st.drills.map(function (d) { return d.generatedDrill ? 1 : 0; }).join('')].join('|') : '';
        if (sig !== lastSig || !root || !root.firstChild) { lastSig = sig; render(); return; }
        if (!st || !st.drills.length) { return; }
        var n = liveNumbers(st);
        var fill = root.querySelector('.st-seg.current .st-fill');
        if (fill) { fill.style.width = n.pct.toFixed(1) + '%'; }
        var left = root.querySelector('.st-left');
        var text = mmss(n.left) + ' left in session';
        if (left && left.textContent !== text) { left.textContent = text; }
    }

    function init() {
        root = document.getElementById('sessionTimeline');
        if (!root) { return; }
        var watch = ['currentDrill', 'timerDisplay', 'drillName'].map(function (id) { return document.getElementById(id); }).filter(Boolean);
        var obs = new MutationObserver(tick);
        watch.forEach(function (el) { obs.observe(el, { childList: true, characterData: true, subtree: true }); });
        setInterval(tick, 1000);
        tick();
    }

    window.CogniSessionTimeline = {
        render: render,
        // the tour's demo session (no appState session exists then)
        demo: function (d) { demo = d; lastSig = ''; render(); },
        endDemo: function () { demo = null; lastSig = ''; render(); }
    };
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { init(); }
})();
