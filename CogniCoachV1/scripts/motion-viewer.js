// 3D Motion Preview for the drill card: a "Generate Animation" button that turns the current drill's
// description into a 3D animation (CogniCoach motion engine on Cloudflare Workers + the Unity viewer in
// an iframe, tests/CogniCoachVisualization(3D)/RagdollTest_AI.html?embed=1).
// The Unity build (~10 MB) is only loaded the first time someone presses the button.
(function () {
    'use strict';

    var VIEWER_PATH = '/tests/CogniCoachVisualization(3D)/RagdollTest_AI.html';
    var MAX_PROMPT = 2000;
    var SPLASH_MS = 3200;   // the Unity build shows its "Made with Unity" splash right after it starts
    var LOADING_STEPS = [
        'Reading the drill',
        'Breaking it into movements',
        'Choreographing the athlete',
        'Warming up the 3D athlete'
    ];

    var root, stage, frame, loader, loaderStep, loaderBar, idle, errorBox, errorText, controls,
        playBtn, scrubber, timeLabel, titleLabel, cueList, sideToggle;
    var state = {
        drillKey: '', iframeReady: false, unityProgress: 0, pending: null, generating: false,
        total: 0, fps: 30, position: 0, playing: false, scrubbing: false, side: 'right', stepTimer: null,
        hasAnimation: false, revealAt: 0, revealTimer: null
    };

    // Words that start a sentence explaining WHY the drill helps (not what the athlete does).
    var BENEFIT_START = /^(?:this|these|that|it|the drill|the exercise|the goal|the purpose|purpose|goal|benefits?|why|great for|ideal for|perfect for|designed to|aims? to|meant to|builds?|improves?|develops?|helps?|trains?|enhances?|boosts?|strengthens?|increases?|promotes?|sharpens?|reinforces?|works on|targets?|focuses on (?:improving|building|developing))\b/i;
    var BENEFIT_ANY = /\b(?:this|the) (?:drill|exercise|sequence|workout|circuit|routine|set) (?:builds?|improves?|develops?|helps?|trains?|enhances?|boosts?|strengthens?|increases?|promotes?|sharpens?|targets?|is great|will)\b/i;

    function textFromHtml(html) {
        var div = document.createElement('div');
        div.innerHTML = String(html || '').replace(/<br\s*\/?>/gi, '. ');
        return (div.textContent || '').replace(/\s+/g, ' ').trim();
    }

    // The drill description minus the reasons it helps: only what the athlete does goes to the engine.
    function motionTextFor(name, descriptionHtml) {
        var text = textFromHtml(descriptionHtml);
        var sentences = text.match(/[^.!?]+[.!?]*/g) || [text];
        var kept = sentences.map(function (s) { return s.trim(); }).filter(function (s) {
            return s && !BENEFIT_START.test(s) && !BENEFIT_ANY.test(s);
        });
        var body = (kept.length ? kept : sentences).join(' ').replace(/\s+/g, ' ').trim();
        var title = (name || '').trim();
        var out = title && !/^(drill|loading\.*)$/i.test(title) ? 'Drill: ' + title + '. ' + body : body;
        return out.slice(0, MAX_PROMPT);
    }

    function currentDrill() {
        var nameEl = document.getElementById('drillName');
        var descEl = document.getElementById('drillDescription');
        return { name: nameEl ? nameEl.textContent : '', html: descEl ? descEl.innerHTML : '' };
    }

    function viewerSrc() {
        var params = new URLSearchParams(window.location.search);
        var src = VIEWER_PATH + '?embed=1';
        var api = params.get('motionApi');   // testing only: another motion service
        if (api) { src += '&api=' + encodeURIComponent(api); }
        return src;
    }

    function post(type, data) {
        if (!frame || !frame.contentWindow) { return; }
        var msg = { target: 'cognicoach-motion', type: type };
        for (var k in (data || {})) { msg[k] = data[k]; }
        frame.contentWindow.postMessage(msg, window.location.origin);
    }

    function setMode(mode) {
        root.setAttribute('data-mode', mode);
    }

    function startLoadingSteps() {
        var i = 0;
        clearInterval(state.stepTimer);
        loaderStep.textContent = LOADING_STEPS[0];
        state.stepTimer = setInterval(function () {
            i = Math.min(i + 1, LOADING_STEPS.length - 1);
            loaderStep.textContent = state.iframeReady && i === LOADING_STEPS.length - 1 ? LOADING_STEPS[2] : LOADING_STEPS[i];
        }, 1600);
    }

    function updateLoaderBar() {
        // Planning is unknown-length; the bar blends the 3D load progress with elapsed planning time.
        var unity = state.iframeReady ? 1 : state.unityProgress;
        loaderBar.style.width = Math.round(15 + 75 * unity) + '%';
    }

    function ensureFrame() {
        if (frame) { return; }
        frame = document.createElement('iframe');
        frame.className = 'motion-frame';
        frame.title = '3D drill animation';
        frame.setAttribute('allow', 'fullscreen');
        frame.src = viewerSrc();
        stage.insertBefore(frame, stage.firstChild);
    }

    function generate() {
        var drill = currentDrill();
        var description = motionTextFor(drill.name, drill.html);
        if (description.length < 3) { showError('This drill has no description to animate yet.'); return; }
        state.generating = true;
        state.hasAnimation = false;
        state.drillKey = drill.name + '|' + drill.html;
        setMode('loading');
        startLoadingSteps();
        updateLoaderBar();
        ensureFrame();
        state.pending = { description: description, side: state.side };
        if (state.loaded) { flushPending(); }
    }

    function flushPending() {
        if (!state.pending) { return; }
        post('generate', state.pending);
        state.pending = null;
    }

    function showError(message) {
        clearInterval(state.stepTimer);
        state.generating = false;
        errorText.textContent = message;
        setMode('error');
    }

    function fmt(seconds) {
        return (Math.max(0, seconds)).toFixed(1) + 's';
    }

    function renderProgress() {
        var max = Math.max(0, state.total - 1);
        if (!state.scrubbing) { scrubber.value = String(Math.min(max, state.position)); }
        var pct = max > 0 ? (Number(scrubber.value) / max) * 100 : 0;
        scrubber.style.setProperty('--fill', pct + '%');
        timeLabel.textContent = fmt(Number(scrubber.value) / state.fps) + ' / ' + fmt(max / state.fps);
        playBtn.setAttribute('aria-label', state.playing ? 'Pause' : 'Play');
        playBtn.classList.toggle('is-playing', state.playing);
    }

    function onReady(m) {
        clearInterval(state.stepTimer);
        state.generating = false;
        state.hasAnimation = true;
        state.total = m.frames || 0;
        state.fps = m.fps || 30;
        state.position = 0;
        state.playing = true;
        scrubber.max = String(Math.max(0, state.total - 1));
        scrubber.step = '0.01';
        titleLabel.textContent = (m.title || 'Drill animation').replace(/\s*[(\[][^)\]]*\b(?:representative|rep|one cycle|demo)\b[^)\]]*[)\]]/ig, '').trim();
        cueList.innerHTML = '';
        (m.cues || []).slice(0, 4).forEach(function (c) {
            var li = document.createElement('li');
            li.textContent = c;
            cueList.appendChild(li);
        });
        cueList.hidden = !cueList.children.length;
        renderProgress();
        revealWhenReady();
    }

    function revealWhenReady() {
        if (!state.hasAnimation) { return; }
        var wait = state.iframeReady ? Math.max(0, state.revealAt - Date.now()) : -1;
        if (wait === 0) {
            if (root.getAttribute('data-mode') !== 'ready') { post('seek', { position: 0 }); post('play'); }
            setMode('ready');
            return;
        }
        setMode('loading');
        loaderStep.textContent = LOADING_STEPS[3];
        clearTimeout(state.revealTimer);
        if (wait > 0) { state.revealTimer = setTimeout(revealWhenReady, wait + 20); }
    }

    function onMessage(event) {
        if (event.origin !== window.location.origin || !frame || event.source !== frame.contentWindow) { return; }
        var m = event.data || {};
        if (m.source !== 'cognicoach-motion') { return; }
        switch (m.type) {
            case 'loaded':
                state.loaded = true;
                flushPending();
                break;
            case 'unity-progress':
                state.unityProgress = m.progress || 0;
                updateLoaderBar();
                break;
            case 'unity-ready':
                state.iframeReady = true;
                state.revealAt = Date.now() + SPLASH_MS;
                updateLoaderBar();
                revealWhenReady();
                break;
            case 'ready':
                onReady(m);
                break;
            case 'error':
                showError(m.message || 'The animation could not be generated.');
                break;
            case 'progress':
                state.total = m.total || state.total;
                state.position = m.position || 0;
                state.playing = !!m.playing;
                renderProgress();
                break;
        }
    }

    // A new drill was rendered: go back to the button (the 3D viewer stays loaded for next time).
    function onDrillChanged() {
        var drill = currentDrill();
        var key = drill.name + '|' + drill.html;
        if (key === state.drillKey || state.generating) { return; }
        state.drillKey = key;
        if (state.hasAnimation) { post('pause'); }
        state.hasAnimation = false;
        setMode('idle');
    }

    function rotate(key) {
        var step = 4;
        if (key === 'ArrowLeft') { post('rotate', { dx: 0, dy: -step }); }
        else if (key === 'ArrowRight') { post('rotate', { dx: 0, dy: step }); }
        else if (key === 'ArrowUp') { post('rotate', { dx: step, dy: 0 }); }
        else if (key === 'ArrowDown') { post('rotate', { dx: -step, dy: 0 }); }
    }

    function build() {
        root = document.getElementById('motionViewer');
        if (!root) { return; }
        root.innerHTML =
            '<div class="motion-head">' +
            '  <div><h2 class="motion-heading">3D Motion Preview</h2>' +
            '  <p class="motion-sub">See this drill performed by a 3D athlete.</p></div>' +
            '  <div class="motion-side-wrap"><span class="motion-side-label">Hand</span>' +
            '  <div class="motion-side" role="group" aria-label="Dominant hand">' +
            '    <button type="button" data-side="right" class="active">Right</button>' +
            '    <button type="button" data-side="left">Left</button>' +
            '  </div></div>' +
            '</div>' +
            '<div class="motion-stage" tabindex="0" aria-label="3D animation. Use the arrow keys to turn the athlete.">' +
            '  <div class="motion-idle">' +
            '    <div class="motion-idle-figure" aria-hidden="true"></div>' +
            '    <button type="button" class="btn btn-primary motion-generate">Generate Animation</button>' +
            '    <p class="motion-idle-note">Turns the drill above into a 3D demonstration in a few seconds.</p>' +
            '  </div>' +
            '  <div class="motion-loader" aria-live="polite">' +
            '    <svg class="motion-runner" viewBox="0 0 120 120" aria-hidden="true">' +
            '      <circle class="ring ring-a" cx="60" cy="60" r="54"/><circle class="ring ring-b" cx="60" cy="60" r="44"/>' +
            '      <g class="runner"><circle cx="60" cy="30" r="7"/>' +
            '        <line class="torso" x1="60" y1="38" x2="60" y2="66"/>' +
            '        <line class="arm arm-l" x1="60" y1="44" x2="60" y2="62"/><line class="arm arm-r" x1="60" y1="44" x2="60" y2="62"/>' +
            '        <line class="leg leg-l" x1="60" y1="66" x2="60" y2="92"/><line class="leg leg-r" x1="60" y1="66" x2="60" y2="92"/></g>' +
            '      <line class="floor" x1="30" y1="96" x2="90" y2="96"/>' +
            '    </svg>' +
            '    <div class="motion-loader-text"><span class="motion-loader-step">Reading the drill</span><span class="dots"><i></i><i></i><i></i></span></div>' +
            '    <div class="motion-loader-bar"><span></span></div>' +
            '  </div>' +
            '  <div class="motion-error">' +
            '    <p class="motion-error-text"></p>' +
            '    <button type="button" class="btn btn-secondary motion-retry">Try Again</button>' +
            '  </div>' +
            '  <div class="motion-caption"><span class="motion-title"></span></div>' +
            '</div>' +
            '<div class="motion-controls">' +
            '  <button type="button" class="motion-play" aria-label="Pause"><span class="icon-play"></span><span class="icon-pause"></span></button>' +
            '  <input type="range" class="motion-scrubber" min="0" max="0" step="0.01" value="0" aria-label="Animation position">' +
            '  <span class="motion-time">0.0s / 0.0s</span>' +
            '  <button type="button" class="motion-regen" title="Generate again">&#x21bb;</button>' +
            '</div>' +
            '<div class="motion-help">' +
            '  <span><kbd>&larr;</kbd><kbd>&rarr;</kbd> turn the athlete</span>' +
            '  <span><kbd>&uarr;</kbd><kbd>&darr;</kbd> tilt the view</span>' +
            '  <span class="motion-help-note">Click the animation, then use the arrow keys</span>' +
            '</div>' +
            '<ul class="motion-cues" hidden></ul>';

        stage = root.querySelector('.motion-stage');
        idle = root.querySelector('.motion-idle');
        loader = root.querySelector('.motion-loader');
        loaderStep = root.querySelector('.motion-loader-step');
        loaderBar = root.querySelector('.motion-loader-bar span');
        errorBox = root.querySelector('.motion-error');
        errorText = root.querySelector('.motion-error-text');
        controls = root.querySelector('.motion-controls');
        playBtn = root.querySelector('.motion-play');
        scrubber = root.querySelector('.motion-scrubber');
        timeLabel = root.querySelector('.motion-time');
        titleLabel = root.querySelector('.motion-title');
        cueList = root.querySelector('.motion-cues');
        sideToggle = root.querySelector('.motion-side');
        setMode('idle');

        root.querySelector('.motion-generate').addEventListener('click', generate);
        root.querySelector('.motion-retry').addEventListener('click', generate);
        root.querySelector('.motion-regen').addEventListener('click', generate);
        playBtn.addEventListener('click', function () {
            state.playing = !state.playing;
            post(state.playing ? 'play' : 'pause');
            renderProgress();
        });
        scrubber.addEventListener('input', function () {
            state.scrubbing = true;
            state.playing = false;
            post('seek', { position: Number(scrubber.value) });
            renderProgress();
        });
        scrubber.addEventListener('change', function () { state.scrubbing = false; });
        sideToggle.addEventListener('click', function (e) {
            var b = e.target.closest('button[data-side]');
            if (!b || b.getAttribute('data-side') === state.side) { return; }
            state.side = b.getAttribute('data-side');
            sideToggle.querySelectorAll('button').forEach(function (x) { x.classList.toggle('active', x === b); });
            if (state.hasAnimation) { post('side', { side: state.side }); }
        });
        // Arrow keys while the preview has focus (the iframe handles them itself once clicked).
        root.addEventListener('keydown', function (e) {
            if (!/^Arrow/.test(e.key) || e.target === scrubber || root.getAttribute('data-mode') !== 'ready') { return; }
            rotate(e.key);
            e.preventDefault();
        });
        window.addEventListener('message', onMessage);

        var desc = document.getElementById('drillDescription');
        var name = document.getElementById('drillName');
        var observer = new MutationObserver(onDrillChanged);
        [desc, name].forEach(function (el) {
            if (el) { observer.observe(el, { childList: true, characterData: true, subtree: true }); }
        });
    }

    window.CogniMotionViewer = { motionTextFor: motionTextFor, generate: generate };
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', build); } else { build(); }
})();
