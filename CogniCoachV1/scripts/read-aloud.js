// ==========================================================================
// Read aloud for drills - uses the browser's own speech (Web Speech API), so it
// is free, works offline and never calls a server.
//
// - A "Read aloud" bar under each drill's title: play / stop, pause / resume.
// - The sentence being spoken is highlighted (CSS Custom Highlight API where
//   the browser has it; otherwise the title/focus/description block is marked).
// - Optional: read each new drill automatically, and spoken timer cues
//   ("Halfway", "10 seconds left", "Time"). Both, plus voice and speed, live in
//   the "Aa" display & reading panel (scripts/a11y.js).
// Listens to the cognicoach:* events fired by scripts/script.js.
// ==========================================================================
(function () {
    'use strict';

    var synth = window.speechSynthesis;
    var supported = !!(synth && window.SpeechSynthesisUtterance);
    var HL = 'cc-read-aloud';
    var hasHighlights = !!(window.CSS && CSS.highlights && window.Highlight);

    var bar, playBtn, pauseBtn, autoBox, statusEl;
    var queue = [], pos = 0, run = 0, speaking = false, paused = false;
    var cueMarks = {};

    function ic(n, s, c) { return window.CogniIcons ? window.CogniIcons.svg(n, { size: s || 20, cls: c }) : ''; }
    function prefs() {
        return (window.CogniA11y && window.CogniA11y.prefs) || { rate: 1, voice: '', autoRead: false, timerCues: false };
    }

    function voices() {
        if (!supported) { return []; }
        var all = synth.getVoices() || [];
        var lang = (navigator.language || 'en').slice(0, 2).toLowerCase();
        var mine = all.filter(function (v) { return (v.lang || '').slice(0, 2).toLowerCase() === lang; });
        return (mine.length ? mine : all).slice().sort(function (a, b) {
            return (b.default ? 1 : 0) - (a.default ? 1 : 0) || a.name.localeCompare(b.name);
        });
    }

    function pickVoice() {
        var want = prefs().voice;
        if (!want) { return null; }
        var all = synth.getVoices() || [];
        for (var i = 0; i < all.length; i++) { if (all[i].voiceURI === want) { return all[i]; } }
        return null;
    }

    function utter(text) {
        var u = new SpeechSynthesisUtterance(text);
        var v = pickVoice();
        if (v) { u.voice = v; u.lang = v.lang; } else { u.lang = document.documentElement.lang || 'en'; }
        u.rate = Math.min(2, Math.max(0.5, Number(prefs().rate) || 1));
        return u;
    }

    // ------------------------------------------------------------------ building the script
    function clean(t) { return String(t || '').replace(/\s+/g, ' ').trim(); }

    // Sentences of the description, each tied to its place in the DOM so it can be highlighted.
    function descriptionChunks(root) {
        var out = [];
        if (!root) { return out; }
        // Lines = runs of text nodes between <br>s / block elements, so a sentence can run through <b>, <em>...
        var lines = [[]];
        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, null);
        var node;
        while ((node = walker.nextNode())) {
            if (node.nodeType === 1) {
                if (node.tagName === 'BR' || /^(block|list-item|flex|grid|table)/.test(getComputedStyle(node).display)) {
                    if (lines[lines.length - 1].length) { lines.push([]); }
                }
            } else if (node.nodeValue) {
                lines[lines.length - 1].push(node);
            }
        }
        lines.forEach(function (nodes) {
            if (!nodes.length) { return; }
            var text = '', marks = [];
            nodes.forEach(function (n) { marks.push({ node: n, at: text.length }); text += n.nodeValue; });
            var locate = function (offset) {
                for (var i = marks.length - 1; i >= 0; i--) {
                    if (offset >= marks[i].at) { return { node: marks[i].node, offset: Math.min(offset - marks[i].at, marks[i].node.length) }; }
                }
                return { node: marks[0].node, offset: 0 };
            };
            var re = /[^.!?]+(?:[.!?]+["')\]]*|$)/g, m;
            while ((m = re.exec(text))) {
                if (!m[0]) { re.lastIndex++; continue; }
                var s = clean(m[0]);
                if (!/\w/.test(s)) { continue; }
                var lead = m[0].length - m[0].replace(/^\s+/, '').length;
                var a = locate(m.index + lead), b = locate(m.index + m[0].replace(/\s+$/, '').length);
                out.push({ text: s, from: a, to: b, el: root });
            }
        });
        return out;
    }

    function minutesText(secs) {
        secs = Math.round(secs || 0);
        if (!secs) { return ''; }
        var m = Math.floor(secs / 60), s = secs % 60;
        var parts = [];
        if (m) { parts.push(m + (m === 1 ? ' minute' : ' minutes')); }
        if (s) { parts.push(s + (s === 1 ? ' second' : ' seconds')); }
        return parts.join(' and ');
    }

    function buildQueue() {
        var q = [];
        var cur = document.getElementById('currentDrill'), tot = document.getElementById('totalDrills');
        var name = document.getElementById('drillName');
        var focus = document.getElementById('drillFocus');
        var desc = document.getElementById('drillDescription');
        var timer = document.getElementById('timerDisplay');
        var intro = [];
        if (cur && tot && clean(cur.textContent)) { intro.push('Drill ' + clean(cur.textContent) + ' of ' + clean(tot.textContent) + '.'); }
        if (intro.length) { q.push({ text: intro.join(' ') }); }
        if (name && clean(name.textContent)) { q.push({ text: clean(name.textContent) + '.', el: name }); }
        if (focus && clean(focus.textContent)) { q.push({ text: clean(focus.textContent).replace(/^Focus:/i, 'Focus:') + '.', el: focus }); }
        if (timer && /^\d+:\d+$/.test(clean(timer.textContent))) {
            var p = clean(timer.textContent).split(':');
            var secs = Number(p[0]) * 60 + Number(p[1]);
            if (secs) { q.push({ text: 'Time: ' + minutesText(secs) + '.' }); }
        }
        q = q.concat(descriptionChunks(desc));
        // coach cues (scripts/coach-cues.js)
        var cues = document.querySelectorAll('#coachCues .cc-list li');
        if (cues.length) {
            q.push({ text: 'Coach cues.', el: document.querySelector('#coachCues .cc-label') });
            Array.prototype.forEach.call(cues, function (li) { if (clean(li.textContent)) { q.push({ text: clean(li.textContent) + '.', el: li }); } });
        }
        return q;
    }

    // ------------------------------------------------------------------ highlighting
    function clearHighlight() {
        if (hasHighlights) { try { CSS.highlights.delete(HL); } catch (e) {} }
        document.querySelectorAll('.ra-reading').forEach(function (e) { e.classList.remove('ra-reading'); });
    }

    function highlight(chunk) {
        clearHighlight();
        if (!chunk) { return; }
        if (chunk.from && hasHighlights && chunk.from.node.isConnected) {
            try {
                var r = new Range();
                r.setStart(chunk.from.node, chunk.from.offset);
                r.setEnd(chunk.to.node, chunk.to.offset);
                CSS.highlights.set(HL, new Highlight(r));
                return;
            } catch (e) {}
        }
        if (chunk.el) { chunk.el.classList.add('ra-reading'); }
    }

    // ------------------------------------------------------------------ playback
    function setState(state) {
        speaking = state !== 'idle';
        paused = state === 'paused';
        if (!bar) { return; }
        bar.dataset.state = state;
        playBtn.setAttribute('aria-pressed', speaking ? 'true' : 'false');
        playBtn.querySelector('.ra-label').textContent = speaking ? 'Stop reading' : 'Read aloud';
        playBtn.querySelector('.ra-icon').innerHTML = ic(speaking ? 'stop' : 'volume', 18);
        pauseBtn.hidden = !speaking;
        pauseBtn.setAttribute('aria-pressed', paused ? 'true' : 'false');
        pauseBtn.querySelector('.ra-label').textContent = paused ? 'Resume' : 'Pause';
        pauseBtn.querySelector('.ra-icon').innerHTML = ic(paused ? 'play' : 'pause', 18);
        statusEl.textContent = '';
        document.dispatchEvent(new CustomEvent('cognicoach:read-aloud', { detail: { state: state } }));
    }

    function speakNext(token) {
        if (token !== run) { return; }
        if (pos >= queue.length) { stop(); return; }
        var chunk = queue[pos];
        highlight(chunk);
        if (bar) { statusEl.textContent = 'Reading part ' + (pos + 1) + ' of ' + queue.length; }
        var u = utter(chunk.text);
        var advanced = false;
        var next = function () {
            if (advanced || token !== run) { return; }
            advanced = true;
            pos++;
            speakNext(token);
        };
        u.onend = next;
        u.onerror = function (e) {
            if (e && (e.error === 'interrupted' || e.error === 'canceled')) { return; }
            next();
        };
        synth.speak(u);
    }

    function start(fromIndex) {
        if (!supported) { return; }
        run++;
        synth.cancel();
        queue = buildQueue();
        pos = fromIndex || 0;
        if (!queue.length) { return; }
        setState('speaking');
        var token = run;
        // Chrome sometimes drops an utterance queued right after cancel(); give it a tick.
        setTimeout(function () { speakNext(token); }, 60);
    }

    function stop() {
        run++;
        if (supported) { synth.cancel(); }
        clearHighlight();
        setState('idle');
    }

    function togglePause() {
        if (!speaking) { return; }
        if (paused) {
            synth.resume();
            setState('speaking');
            // some engines lose the paused utterance - if nothing resumes, carry on from the same sentence
            var token = run, at = pos;
            setTimeout(function () { if (token === run && at === pos && !synth.speaking) { speakNext(token); } }, 400);
        } else {
            synth.pause();
            setState('paused');
        }
    }

    // A short spoken line that does not touch the drill queue (timer cues, voice test).
    function say(text, interrupt) {
        if (!supported) { return; }
        if (interrupt && speaking) { stop(); }
        if (speaking) { return; }
        synth.speak(utter(text));
    }

    // ------------------------------------------------------------------ UI
    function buildBar() {
        if (bar || !supported) { return; }
        var focus = document.getElementById('drillFocus');
        if (!focus) { return; }
        bar = document.createElement('div');
        bar.className = 'ra-bar';
        bar.setAttribute('role', 'group');
        bar.setAttribute('aria-label', 'Read this drill aloud');
        bar.dataset.state = 'idle';
        bar.innerHTML =
            '<button type="button" class="ra-btn ra-play" aria-pressed="false"><span class="ra-icon" aria-hidden="true"></span> <span class="ra-label">Read aloud</span></button>' +
            '<button type="button" class="ra-btn ra-pause" aria-pressed="false" hidden><span class="ra-icon" aria-hidden="true"></span> <span class="ra-label">Pause</span></button>' +
            '<label class="ra-auto"><input type="checkbox" class="ra-auto-box"> Auto-read drills</label>' +
            '<span class="ra-status a11y-sr-only" aria-live="off"></span>';
        focus.insertAdjacentElement('afterend', bar);
        playBtn = bar.querySelector('.ra-play');
        pauseBtn = bar.querySelector('.ra-pause');
        autoBox = bar.querySelector('.ra-auto-box');
        statusEl = bar.querySelector('.ra-status');
        autoBox.checked = !!prefs().autoRead;
        playBtn.addEventListener('click', function () { speaking ? stop() : start(0); });
        pauseBtn.addEventListener('click', togglePause);
        autoBox.addEventListener('change', function () {
            if (window.CogniA11y) { window.CogniA11y.set('autoRead', autoBox.checked); }
            if (window.CogniA11y) { window.CogniA11y.announce(autoBox.checked ? 'New drills will be read aloud' : 'Auto-read off'); }
        });
        setState('idle');
    }

    function syncFromPrefs() {
        if (autoBox) { autoBox.checked = !!prefs().autoRead; }
    }

    // ------------------------------------------------------------------ events from the session
    document.addEventListener('cognicoach:drill-loading', function () { stop(); });
    document.addEventListener('cognicoach:session-end', function () { stop(); });
    document.addEventListener('cognicoach:drill-rendered', function () {
        cueMarks = {};
        buildBar();
        if (prefs().autoRead) { setTimeout(function () { start(0); }, 350); }
    });
    document.addEventListener('cognicoach:timer', function (e) {
        var d = e.detail || {};
        if (!prefs().timerCues || !supported) { return; }
        if (d.state === 'running' && !cueMarks.go && d.remaining === d.total) {
            cueMarks.go = true;
            say('Go. ' + minutesText(d.total) + '.', false);
        } else if (d.state === 'tick') {
            if (d.total >= 60 && !cueMarks.half && d.remaining === Math.floor(d.total / 2)) { cueMarks.half = true; say('Halfway.', true); }
            if (d.total > 20 && !cueMarks.ten && d.remaining === 10) { cueMarks.ten = true; say('10 seconds left.', true); }
        } else if (d.state === 'complete' && !cueMarks.done) {
            cueMarks.done = true;
            say('Time. Drill complete.', true);
        }
    });

    // keyboard: Alt+R reads / stops the current drill
    document.addEventListener('keydown', function (e) {
        if (e.altKey && !e.ctrlKey && !e.metaKey && (e.key === 'r' || e.key === 'R' || e.code === 'KeyR')) {
            if (!bar || bar.offsetParent === null) { return; }
            e.preventDefault();
            speaking ? stop() : start(0);
        }
    });

    if (supported) {
        if (synth.addEventListener) {
            synth.addEventListener('voiceschanged', function () { if (window.CogniA11y) { window.CogniA11y.refreshVoices(); } });
        } else {
            synth.onvoiceschanged = function () { if (window.CogniA11y) { window.CogniA11y.refreshVoices(); } };
        }
        window.addEventListener('pagehide', function () { synth.cancel(); });
    }

    function boot() {
        buildBar();   // the tour's demo drill fills the card without a render event
        var tries = 0;
        var t = setInterval(function () {
            if (window.CogniA11y) { window.CogniA11y.onChange(syncFromPrefs); syncFromPrefs(); clearInterval(t); }
            if (++tries > 50) { clearInterval(t); }
        }, 100);
    }

    window.CogniReadAloud = {
        supported: supported,
        voices: voices,
        start: function () { start(0); },
        stop: stop,
        toggle: function () { speaking ? stop() : start(0); },
        isSpeaking: function () { return speaking; },
        busy: function () { return speaking || !!(synth && synth.speaking); },
        say: function (text, interrupt) { say(text, !!interrupt); },
        test: function () { stop(); say('This is how drills will sound. Keep your eyes up and stay low.', true); }
    };

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', boot); } else { boot(); }
})();
