// ==========================================================================
// CogniCoach accounts: sign in on any device and keep your profile in sync.
//
// Loaded on every page by scripts/nav.js. Talks to the cognicoach-accounts Cloudflare Worker
// (workers/accounts). What syncs: your profile, session history, dashboard settings, Competition Mode
// notes and saved 3D animations. Anything gathered before signing in is added to the account.
//
// Passwords never leave this browser: they are stretched here with PBKDF2-SHA256 (600k rounds) and
// only the derived key is sent (the server hashes it again with a random salt).
// ==========================================================================
(function () {
    'use strict';
    if (window.CogniAccount) { return; }

    var API = (function () {
        try {
            var q = new URLSearchParams(location.search).get('accountsApi');   // testing only
            if (q) { sessionStorage.setItem('cognicoach-accounts-api', q); }
            return q || sessionStorage.getItem('cognicoach-accounts-api') || window.COGNICOACH_ACCOUNTS_API ||
                'https://cognicoach-accounts.bodhishanbhag.workers.dev';
        } catch (e) { return 'https://cognicoach-accounts.bodhishanbhag.workers.dev'; }
    })().replace(/\/$/, '');

    var SESSION_KEY = 'cognicoach-account';
    var META_KEY = 'cognicoach-sync-meta';
    var SYNC_KEYS = { 'cognicoach-profile': 'profile', 'cognicoach-history': 'history', 'cognicoach-dashboard': 'dashboard',
        'cognicoach-competition-notes': 'competition', 'cognicoach-motion-saved': 'animations' };
    var MAX_DOC_CHARS = 240000;   // the server accepts 256 KB per account
    var PUSH_DELAY = 2500;
    var PULL_EVERY = 60000;

    var rawSet = Storage.prototype.setItem;
    var rawRemove = Storage.prototype.removeItem;
    var applying = false;
    var pushTimer = null;
    var status = { state: 'idle', at: 0, message: '' };   // idle | syncing | synced | offline | error
    var listeners = [];

    // ---------------------------------------------------------------- storage helpers
    function readJSON(key, fallback) {
        try { var v = JSON.parse(localStorage.getItem(key)); return v === null || v === undefined ? fallback : v; } catch (e) { return fallback; }
    }
    function writeRaw(key, value) { try { rawSet.call(localStorage, key, value); } catch (e) {} }
    function session() { return readJSON(SESSION_KEY, null); }
    function saveSession(s) { if (s) { writeRaw(SESSION_KEY, JSON.stringify(s)); } else { rawRemove.call(localStorage, SESSION_KEY); } }
    function meta() { return readJSON(META_KEY, {}); }
    function saveMeta(m) { writeRaw(META_KEY, JSON.stringify(m)); }

    // Every write to a synced key is stamped (for merging) and scheduled for upload.
    function noteLocalChange(key) {
        if (applying || !SYNC_KEYS[key]) { return; }
        var m = meta();
        m[SYNC_KEYS[key] + 'At'] = Date.now();
        saveMeta(m);
        schedulePush();
    }
    Storage.prototype.setItem = function (key, value) {
        rawSet.call(this, key, value);
        if (this === window.localStorage) { noteLocalChange(key); }
    };
    Storage.prototype.removeItem = function (key) {
        rawRemove.call(this, key);
        if (this === window.localStorage) { noteLocalChange(key); }
    };

    function localDoc() {
        var m = meta();
        return {
            profile: readJSON('cognicoach-profile', null), profileAt: m.profileAt || 0,
            history: readJSON('cognicoach-history', []), historyAt: m.historyAt || 0,
            dashboard: readJSON('cognicoach-dashboard', null), dashboardAt: m.dashboardAt || 0,
            competition: readJSON('cognicoach-competition-notes', {}),
            animations: readJSON('cognicoach-motion-saved', {})
        };
    }

    // per-key maps: keep each entry's newest version
    function mergeMap(x, y, stamp) {
        var out = {};
        [x || {}, y || {}].forEach(function (src) {
            Object.keys(src).forEach(function (k) {
                var v = src[k];
                if (!v || typeof v !== 'object') { return; }
                if (!out[k] || stamp(v) > stamp(out[k])) { out[k] = v; }
            });
        });
        return out;
    }
    function noteTime(v) { var t = new Date(v.updatedAt || 0).getTime(); return isNaN(t) ? 0 : t; }
    function animTime(v) { return Number(v.savedAt) || 0; }

    // keep the synced document under the server's size limit: drop the oldest saved animations first
    function fitSize(doc) {
        var anims = doc.animations || {};
        var ids = Object.keys(anims).sort(function (a, b) { return animTime(anims[b]) - animTime(anims[a]); });
        while (JSON.stringify(doc).length > MAX_DOC_CHARS && ids.length) { delete anims[ids.pop()]; }
        return doc;
    }

    function historyKey(r) { return (r && r.date || '') + '|' + (r && r.sport || ''); }

    // Merge two documents: newer profile / dashboard wins (an onboarded profile beats a blank one),
    // session histories are combined (each session once).
    function merge(a, b) {
        if (!b) { return a; }
        if (!a) { return b; }
        function pick(field) {
            var x = a[field], y = b[field], tx = a[field + 'At'] || 0, ty = b[field + 'At'] || 0;
            if (!x) { return [y, ty]; }
            if (!y) { return [x, tx]; }
            if (field === 'profile' && !!x.onboarded !== !!y.onboarded) { return x.onboarded ? [x, tx] : [y, ty]; }
            return ty > tx ? [y, ty] : [x, tx];
        }
        var p = pick('profile'), d = pick('dashboard');
        var seen = {}, hist = [];
        [].concat(Array.isArray(a.history) ? a.history : [], Array.isArray(b.history) ? b.history : []).forEach(function (r) {
            var k = historyKey(r);
            if (!seen[k]) { seen[k] = 1; hist.push(r); }
        });
        hist.sort(function (r1, r2) { return new Date(r1.date) - new Date(r2.date); });
        var anims = mergeMap(a.animations, b.animations, animTime);
        var ids = Object.keys(anims).sort(function (i, j) { return animTime(anims[j]) - animTime(anims[i]); });
        ids.slice(40).forEach(function (id) { delete anims[id]; });
        return fitSize({ profile: p[0], profileAt: p[1], dashboard: d[0], dashboardAt: d[1], history: hist,
            historyAt: Math.max(a.historyAt || 0, b.historyAt || 0),
            competition: mergeMap(a.competition, b.competition, noteTime), animations: anims });
    }

    function sameDoc(x, y) { return JSON.stringify(x) === JSON.stringify(y); }

    function applyDoc(doc) {
        var before = localDoc();
        applying = true;
        try {
            if (doc.profile) { writeRaw('cognicoach-profile', JSON.stringify(doc.profile)); }
            if (Array.isArray(doc.history)) { writeRaw('cognicoach-history', JSON.stringify(doc.history)); }
            if (doc.dashboard) { writeRaw('cognicoach-dashboard', JSON.stringify(doc.dashboard)); }
            if (doc.competition && Object.keys(doc.competition).length) { writeRaw('cognicoach-competition-notes', JSON.stringify(doc.competition)); }
            if (doc.animations && Object.keys(doc.animations).length) { writeRaw('cognicoach-motion-saved', JSON.stringify(doc.animations)); }
            var m = meta();
            m.profileAt = doc.profileAt || m.profileAt || 0;
            m.historyAt = doc.historyAt || m.historyAt || 0;
            m.dashboardAt = doc.dashboardAt || m.dashboardAt || 0;
            saveMeta(m);
        } finally { applying = false; }
        if (!sameDoc(before, localDoc())) {
            window.dispatchEvent(new CustomEvent('cognicoach:synced', { detail: { changed: true } }));
        }
    }

    // ---------------------------------------------------------------- network
    async function api(path, opts) {
        opts = opts || {};
        var headers = { 'Content-Type': 'application/json' };
        var s = session();
        if (opts.auth !== false && s && s.token) { headers.Authorization = 'Bearer ' + s.token; }
        var resp;
        try {
            resp = await fetch(API + path, { method: opts.method || 'GET', headers: headers, keepalive: !!opts.keepalive,
                body: opts.body ? JSON.stringify(opts.body) : undefined });
        } catch (e) {
            var err = new Error("Couldn't reach the account service. Check your connection.");
            err.offline = true;
            throw err;
        }
        var data = await resp.json().catch(function () { return {}; });
        if (!resp.ok) {
            var e2 = new Error(data.detail || ('Account service error (' + resp.status + ').'));
            e2.status = resp.status; e2.code = data.code; e2.data = data;
            if (resp.status === 401 && data.code === 'signed_out') { signedOutRemotely(); }
            throw e2;
        }
        return data;
    }

    async function deriveKey(username, password) {
        var enc = new TextEncoder();
        var base = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']);
        var bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256',
            salt: enc.encode('cognicoach-accounts:v1:' + username.toLowerCase()), iterations: 600000 }, base, 256);
        return Array.prototype.map.call(new Uint8Array(bits), function (b) { return b.toString(16).padStart(2, '0'); }).join('');
    }

    function setStatus(state, message) {
        status = { state: state, at: Date.now(), message: message || '' };
        listeners.forEach(function (fn) { try { fn(status); } catch (e) {} });
    }

    var syncing = null;
    // Pull the cloud copy, merge it with this browser's data, write the result both ways.
    async function syncNow() {
        if (!session()) { return; }
        if (syncing) { return syncing; }
        syncing = (async function () {
            setStatus('syncing');
            try {
                for (var attempt = 0; attempt < 3; attempt++) {
                    var remote = await api('/profile');
                    var merged = merge(localDoc(), remote.data);
                    applyDoc(merged);
                    if (remote.data && sameDoc(merged, merge(remote.data, null))) {
                        var s = session(); if (s) { s.version = remote.version; saveSession(s); }
                        setStatus('synced');
                        return;
                    }
                    try {
                        var put = await api('/profile', { method: 'PUT', body: { data: merged, baseVersion: remote.version } });
                        var s2 = session(); if (s2) { s2.version = put.version; saveSession(s2); }
                        setStatus('synced');
                        return;
                    } catch (e) {
                        if (e.status !== 409) { throw e; }   // changed on another device meanwhile: merge again
                    }
                }
                setStatus('error', 'Sync conflict - try again.');
            } catch (e) {
                setStatus(e.offline ? 'offline' : (session() ? 'error' : 'idle'), e.message);
            } finally {
                syncing = null;
            }
        })();
        return syncing;
    }

    function schedulePush() {
        if (!session()) { return; }
        clearTimeout(pushTimer);
        setStatus('pending');
        pushTimer = setTimeout(syncNow, PUSH_DELAY);
    }

    function signedOutRemotely() {
        saveSession(null);
        setStatus('idle');
        render();
        toast('You were signed out. Sign in again to keep syncing.', 'warn');
    }

    // What this browser gathered while signed out (shown after sign-up / sign-in).
    function localSummary() {
        var d = localDoc();
        var parts = [];
        var n = Array.isArray(d.history) ? d.history.length : 0;
        if (n) { parts.push(n + ' session' + (n === 1 ? '' : 's')); }
        if (d.profile && d.profile.onboarded) { parts.push('your profile'); }
        var c = Object.keys(d.competition || {}).length;
        if (c) { parts.push('Competition notes for ' + c + ' sport' + (c === 1 ? '' : 's')); }
        var a = Object.keys(d.animations || {}).length;
        if (a) { parts.push(a + ' saved animation' + (a === 1 ? '' : 's')); }
        if (!parts.length) { return ''; }
        return parts.length === 1 ? parts[0] : parts.slice(0, -1).join(', ') + ' and ' + parts[parts.length - 1];
    }

    async function signIn(mode, username, password) {
        username = String(username || '').trim().toLowerCase();
        var gathered = localSummary();
        var key = await deriveKey(username, password);
        var res = await api(mode === 'signup' ? '/signup' : '/login', { method: 'POST', auth: false, body: { username: username, key: key } });
        saveSession({ username: res.username, token: res.token, version: 0, since: Date.now() });
        render();
        await syncNow();
        window.dispatchEvent(new CustomEvent('cognicoach:account', { detail: { signedIn: true, username: res.username } }));
        return { username: res.username, gathered: gathered };
    }

    async function signOut() {
        try { await api('/logout', { method: 'POST' }); } catch (e) {}
        saveSession(null);
        setStatus('idle');
        render();
        window.dispatchEvent(new CustomEvent('cognicoach:account', { detail: { signedIn: false } }));
        toast('Signed out. Your data stays on this device.');
    }

    async function changePassword(current, next) {
        var s = session();
        var res = await api('/password', { method: 'POST', body: { key: await deriveKey(s.username, current), newKey: await deriveKey(s.username, next) } });
        s.token = res.token; saveSession(s);
    }

    // ---------------------------------------------------------------- Sign in with Google
    // The client ID comes from the accounts Worker (/config); no ID there = no Google button.
    var configPromise = null;
    function config() {
        if (!configPromise) {
            configPromise = (async function () {
                try {
                    var cached = sessionStorage.getItem('cognicoach-accounts-config');
                    if (cached) { return JSON.parse(cached); }
                } catch (e) {}
                try {
                    var c = await api('/config', { auth: false });
                    try { sessionStorage.setItem('cognicoach-accounts-config', JSON.stringify(c)); } catch (e) {}
                    return c;
                } catch (e) { configPromise = null; return {}; }
            })();
        }
        return configPromise;
    }

    var gsiPromise = null;
    function loadGsi() {
        if (!gsiPromise) {
            gsiPromise = new Promise(function (resolve, reject) {
                if (window.google && window.google.accounts && window.google.accounts.id) { resolve(window.google); return; }
                var s = document.createElement('script');
                s.src = 'https://accounts.google.com/gsi/client';
                s.async = true;
                s.onload = function () { resolve(window.google); };
                s.onerror = function () { gsiPromise = null; reject(new Error('Google sign-in failed to load.')); };
                document.head.appendChild(s);
            });
        }
        return gsiPromise;
    }

    var gsiReadyFor = '';
    async function renderGoogleButton(container, opts) {
        if (!container) { return false; }
        var cfg = await config();
        if (!cfg.googleClientId || session()) { container.innerHTML = ''; return false; }
        try {
            var g = await loadGsi();
            if (gsiReadyFor !== cfg.googleClientId) {
                g.accounts.id.initialize({ client_id: cfg.googleClientId, callback: onGoogleCredential, ux_mode: 'popup',
                    auto_select: false, cancel_on_tap_outside: true, itp_support: true });
                gsiReadyFor = cfg.googleClientId;
            }
            container.innerHTML = '';
            g.accounts.id.renderButton(container, { type: 'standard', theme: 'outline', size: 'large', shape: 'pill',
                text: (opts && opts.text) || 'continue_with', logo_alignment: 'left',
                width: Math.min(300, Math.max(200, container.clientWidth || 260)) });
            return true;
        } catch (e) {
            container.innerHTML = '';
            return false;
        }
    }

    async function onGoogleCredential(resp) {
        var gathered = localSummary();
        try {
            var res = await api('/google', { method: 'POST', auth: false, body: { credential: resp.credential } });
            saveSession({ username: res.username, token: res.token, provider: 'google', version: 0, since: Date.now() });
            closeModal();
            render();
            await syncNow();
            window.dispatchEvent(new CustomEvent('cognicoach:account', { detail: { signedIn: true, username: res.username } }));
            toast((res.created ? 'Account created - welcome, ' : 'Welcome back, ') + res.username + '. ' +
                (gathered ? (res.created ? 'Added to your account from this device: ' : 'Merged into your account from this device: ') + gathered + '.' :
                    'Your training will sync from now on.'), 'ok');
        } catch (e) {
            var err = document.querySelector('#accountModal .acct-error');
            if (err) { err.textContent = e.message; } else { toast(e.message, 'warn'); }
        }
    }

    // ---------------------------------------------------------------- UI
    function esc(t) {
        return String(t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; });
    }

    function ago(t) {
        if (!t) { return ''; }
        var s = Math.round((Date.now() - t) / 1000);
        if (s < 10) { return 'just now'; }
        if (s < 60) { return s + ' s ago'; }
        if (s < 3600) { return Math.round(s / 60) + ' min ago'; }
        return Math.round(s / 3600) + ' h ago';
    }

    function statusText() {
        switch (status.state) {
            case 'syncing': return 'Syncing…';
            case 'pending': return 'Saving changes…';
            case 'synced': return 'Synced ' + ago(status.at);
            case 'offline': return 'Offline - will sync later';
            case 'error': return status.message || 'Sync problem';
            default: return 'Ready';
        }
    }

    var host = null, menuOpen = false;

    function render() {
        host = document.getElementById('navAccount');
        if (!host) { return; }
        var s = session();
        if (!s) {
            host.innerHTML = '<button type="button" class="nav-account-btn" data-act="open-signin" aria-label="Create account or sign in">' +
                '<span class="nav-account-icon" aria-hidden="true"></span><span class="nav-account-label">Sign up</span></button>';
        } else {
            host.innerHTML = '<button type="button" class="nav-account-btn signed-in" data-act="toggle-menu" aria-haspopup="true" aria-expanded="' + menuOpen + '">' +
                '<span class="nav-avatar">' + esc(s.username.charAt(0).toUpperCase()) + '<i class="sync-dot ' + status.state + '"></i></span>' +
                '<span class="nav-account-label">' + esc(s.username) + '</span></button>' +
                '<div class="nav-account-menu' + (menuOpen ? ' open' : '') + '" role="menu">' +
                '  <div class="menu-head"><span class="nav-avatar big">' + esc(s.username.charAt(0).toUpperCase()) + '</span>' +
                '    <div><div class="menu-user">' + esc(s.username) + '</div><div class="menu-status ' + status.state + '">' + esc(statusText()) + '</div></div></div>' +
                '  <button type="button" data-act="sync" role="menuitem">Sync now</button>' +
                '  <a href="dashboard.html" role="menuitem">My dashboard</a>' +
                (s.provider === 'google' ? '' : '  <button type="button" data-act="password" role="menuitem">Change password</button>') +
                '  <a href="index.html?tour=1" role="menuitem">Take the tour</a>' +
                '  <button type="button" data-act="signout" class="danger" role="menuitem">Sign out</button>' +
                '</div>';
        }
    }

    function openModal(mode) {
        closeMenu();
        var existing = document.getElementById('accountModal');
        if (existing) { existing.remove(); }
        var wrap = document.createElement('div');
        wrap.id = 'accountModal';
        wrap.className = 'acct-overlay';
        var isPw = mode === 'password';
        wrap.innerHTML =
            '<div class="acct-card" role="dialog" aria-modal="true" aria-labelledby="acctTitle">' +
            '  <button type="button" class="acct-close" data-act="close" aria-label="Close">&times;</button>' +
            '  <div class="acct-brand" aria-hidden="true"></div>' +
            (isPw ? '  <h2 id="acctTitle" class="acct-title">Change password</h2>' :
            '  <div class="acct-tabs" role="tablist">' +
            '    <button type="button" role="tab" data-tab="signup" class="' + (mode !== 'login' ? 'active' : '') + '">Create account</button>' +
            '    <button type="button" role="tab" data-tab="login" class="' + (mode === 'login' ? 'active' : '') + '">Sign in</button>' +
            '    <span class="acct-tab-ink"></span></div>' +
            '  <h2 id="acctTitle" class="acct-title"></h2>') +
            '  <p class="acct-sub"></p>' +
            '  <form class="acct-form" novalidate>' +
            (isPw ? '' : '    <label class="acct-field"><span>Username</span><input name="username" autocomplete="username" spellcheck="false" autocapitalize="none" maxlength="24" required></label>') +
            (isPw ? '    <label class="acct-field"><span>Current password</span><input name="current" type="password" autocomplete="current-password" required></label>' : '') +
            '    <label class="acct-field"><span class="pw-label">' + (isPw ? 'New password' : 'Password') + '</span>' +
            '      <div class="acct-pw"><input name="password" type="password" autocomplete="current-password" required minlength="8">' +
            '      <button type="button" class="acct-eye" data-act="eye" aria-label="Show password"></button></div></label>' +
            '    <div class="acct-strength"><i></i><span></span></div>' +
            '    <label class="acct-field acct-confirm"><span>Confirm password</span><input name="confirm" type="password" autocomplete="new-password"></label>' +
            '    <div class="acct-error" role="alert"></div>' +
            '    <button type="submit" class="btn btn-primary acct-submit"><span class="label"></span><span class="acct-spin" aria-hidden="true"></span></button>' +
            '  </form>' +
            (isPw ? '' : '  <div class="acct-google-wrap"><div class="acct-or"><span>or</span></div><div class="acct-google" id="acctGoogle"></div></div>') +
            (isPw ? '' : '  <p class="acct-note">Syncs your profile, training history, dashboard, Competition notes and saved animations. Anything you did before signing up is added to your account. Your password is scrambled on this device before it is sent.</p>') +
            '</div>';
        document.body.appendChild(wrap);
        if (window.CogniBrand) { window.CogniBrand.mount(wrap.querySelector('.acct-brand')); }
        requestAnimationFrame(function () { wrap.classList.add('show'); });
        setTab(wrap, isPw ? 'password' : (mode === 'login' ? 'login' : 'signup'));
        if (!isPw) {
            var gw = wrap.querySelector('.acct-google-wrap');
            gw.hidden = true;
            renderGoogleButton(wrap.querySelector('#acctGoogle'), { text: mode === 'login' ? 'signin_with' : 'signup_with' })
                .then(function (ok) { gw.hidden = !ok; });
        }
        var first = wrap.querySelector('input');
        setTimeout(function () { if (first) { first.focus(); } }, 120);

        wrap.addEventListener('click', function (e) {
            var act = e.target.closest('[data-act]');
            var tab = e.target.closest('[data-tab]');
            if (e.target === wrap || (act && act.getAttribute('data-act') === 'close')) { closeModal(); }
            else if (tab) { setTab(wrap, tab.getAttribute('data-tab')); }
            else if (act && act.getAttribute('data-act') === 'eye') {
                var inp = wrap.querySelector('input[name="password"]');
                inp.type = inp.type === 'password' ? 'text' : 'password';
                act.classList.toggle('on', inp.type === 'text');
            }
        });
        wrap.querySelector('input[name="password"]').addEventListener('input', function (e) { strength(wrap, e.target.value); });
        wrap.querySelector('form').addEventListener('submit', function (e) { e.preventDefault(); submit(wrap); });
        wrap.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeModal(); } });
    }

    function setTab(wrap, tab) {
        wrap.setAttribute('data-tab', tab);
        wrap.querySelectorAll('[data-tab]').forEach(function (b) { b.classList.toggle('active', b.getAttribute('data-tab') === tab); });
        var title = { login: 'Welcome back', signup: 'Create your account', password: 'Change password' }[tab];
        var sub = { login: 'Sign in to pick up your training on any device.',
            signup: 'Save your profile and training to the cloud - free.',
            password: 'Other devices will be signed out.' }[tab];
        wrap.querySelector('.acct-title').textContent = title;
        wrap.querySelector('.acct-sub').textContent = sub;
        wrap.querySelector('.acct-submit .label').textContent = { login: 'Sign in', signup: 'Create account', password: 'Update password' }[tab];
        var pw = wrap.querySelector('input[name="password"]');
        pw.setAttribute('autocomplete', tab === 'login' ? 'current-password' : 'new-password');
        wrap.querySelector('.acct-error').textContent = '';
        strength(wrap, pw.value);
    }

    function strength(wrap, pw) {
        var score = 0;
        if (pw.length >= 8) { score++; }
        if (pw.length >= 12) { score++; }
        if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) { score++; }
        if (/\d/.test(pw) && /[^A-Za-z0-9]/.test(pw)) { score++; }
        var el = wrap.querySelector('.acct-strength');
        el.setAttribute('data-score', pw ? String(score) : '');
        el.querySelector('span').textContent = pw ? ['Too short', 'Okay', 'Good', 'Strong', 'Excellent'][score] : '';
    }

    async function submit(wrap) {
        var tab = wrap.getAttribute('data-tab');
        var f = wrap.querySelector('form');
        var err = wrap.querySelector('.acct-error');
        var btn = wrap.querySelector('.acct-submit');
        var user = f.username ? f.username.value.trim() : '';
        var pw = f.password.value;
        err.textContent = '';
        if (tab !== 'password' && !/^[A-Za-z0-9][A-Za-z0-9_.-]{2,23}$/.test(user)) {
            err.textContent = 'Usernames are 3-24 characters: letters, numbers, dots, dashes or underscores.'; return;
        }
        if (pw.length < 8) { err.textContent = 'Passwords need at least 8 characters.'; return; }
        if (tab !== 'login' && f.confirm.value !== pw) { err.textContent = "The passwords don't match."; return; }
        btn.disabled = true;
        wrap.classList.add('busy');
        try {
            if (tab === 'password') {
                await changePassword(f.current.value, pw);
                closeModal();
                toast('Password updated. Other devices were signed out.', 'ok');
            } else {
                var r = await signIn(tab, user, pw);
                closeModal();
                if (tab === 'signup') {
                    toast('Account created - welcome, ' + r.username + '! ' +
                        (r.gathered ? 'Added to your account from this device: ' + r.gathered + '.' : 'Your training will sync from now on.'), 'ok');
                } else {
                    toast('Welcome back, ' + r.username + '. ' +
                        (r.gathered ? 'Merged into your account from this device: ' + r.gathered + '.' : 'Your profile is synced.'), 'ok');
                }
            }
        } catch (e) {
            err.textContent = e.message || 'Something went wrong.';
            wrap.querySelector('.acct-card').classList.remove('shake');
            void wrap.offsetWidth;
            wrap.querySelector('.acct-card').classList.add('shake');
        } finally {
            btn.disabled = false;
            wrap.classList.remove('busy');
        }
    }

    function closeModal() {
        var m = document.getElementById('accountModal');
        if (!m) { return; }
        m.classList.remove('show');
        setTimeout(function () { m.remove(); }, 250);
    }

    function closeMenu() { if (menuOpen) { menuOpen = false; render(); } }

    function toast(text, kind) {
        var box = document.getElementById('acctToasts');
        if (!box) { box = document.createElement('div'); box.id = 'acctToasts'; box.className = 'acct-toasts'; document.body.appendChild(box); }
        var t = document.createElement('div');
        t.className = 'acct-toast ' + (kind || '');
        t.textContent = text;
        box.appendChild(t);
        requestAnimationFrame(function () { t.classList.add('show'); });
        setTimeout(function () { t.classList.remove('show'); setTimeout(function () { t.remove(); }, 300); }, 4200);
    }

    document.addEventListener('click', function (e) {
        var act = e.target.closest && e.target.closest('#navAccount [data-act]');
        if (!act) { if (menuOpen && !(e.target.closest && e.target.closest('#navAccount'))) { closeMenu(); } return; }
        var a = act.getAttribute('data-act');
        if (a === 'open-signin') { openModal('signup'); }
        else if (a === 'toggle-menu') { menuOpen = !menuOpen; render(); }
        else if (a === 'sync') { syncNow(); }
        else if (a === 'password') { openModal('password'); }
        else if (a === 'signout') { menuOpen = false; signOut(); }
    });
    document.addEventListener('keydown', function (e) { if (e.key === 'Escape') { closeMenu(); } });

    listeners.push(function () {
        if (!host) { return; }
        var dot = host.querySelector('.sync-dot');
        var st = host.querySelector('.menu-status');
        if (dot) { dot.className = 'sync-dot ' + status.state; }
        if (st) { st.className = 'menu-status ' + status.state; st.textContent = statusText(); }
    });

    // pull on load, when the tab comes back, and push before leaving
    var lastPull = 0;
    function maybePull() {
        if (session() && Date.now() - lastPull > PULL_EVERY) { lastPull = Date.now(); syncNow(); }
    }
    window.addEventListener('focus', maybePull);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) { maybePull(); } });
    window.addEventListener('pagehide', function () {
        if (pushTimer && session()) {
            clearTimeout(pushTimer);
            var s = session();
            api('/profile', { method: 'PUT', keepalive: true, body: { data: localDoc(), baseVersion: s.version || 0 } }).catch(function () {});
        }
    });

    window.CogniAccount = {
        api: API, session: session, syncNow: syncNow, status: function () { return status; }, statusText: statusText,
        onStatus: function (fn) { listeners.push(fn); }, open: openModal, renderGoogleButton: renderGoogleButton, signOut: signOut, toast: toast, render: render, merge: merge
    };

    function start() {
        render();
        maybePull();
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', start); } else { start(); }
})();
