// ==========================================================================
// Competition Mode
//
// Two jobs live in this one file:
//
// 1. Background note-taking (runs on index.html): every time a workout
//    session starts, we ask the Worker to turn that session's sport/
//    focus/level/etc into a short, updated list of "things to focus on
//    at competition" for that sport, merging with whatever was already
//    saved. This never blocks the workout itself — see script.js's
//    startSession(), which fires this and moves on without awaiting it.
//
// 2. The Competition Mode page (competition.html): pick a sport, see its
//    saved focus notes, and chat with a sport-scoped assistant about
//    competition prep. The chatbot's guardrails (topic + safety) live
//    server-side in the Worker's system prompt — see worker code.
//
// All notes/chat data lives in localStorage['cognicoach-competition-notes'],
// keyed by the SAME canonical sport name scripts/sport-normalize.js
// produces, so notes taken while training for "swim" and "Swimming" end
// up in one bucket instead of two.
// ==========================================================================

const COMPETITION_NOTES_API_URL = "https://cognicoach-backend.bodhishanbhag.workers.dev/api/competition-notes";
const COMPETITION_CHAT_API_URL = "https://cognicoach-backend.bodhishanbhag.workers.dev/api/competition-chat";
const COMPETITION_PRODUCTION_URL = "https://cognicoachai.com/CogniCoachV1/";
const COMPETITION_TURNSTILE_SITE_KEY = "0x4AAAAAAD1cShM7YT2v5dHL";
const COMPETITION_NOTES_KEY = "cognicoach-competition-notes";
const COMPETITION_SELECTED_SPORT_KEY = "cognicoach-competition-selected-sport";

// -- Shared helpers ----------------------------------------------------------

function getCompetitionAppPassword() {
    const isProduction = window.location.href.startsWith(COMPETITION_PRODUCTION_URL);
    if (isProduction) return null;

    let password = sessionStorage.getItem("cognicoach_dev_password");
    if (!password) {
        password = window.prompt("This isn't the production site. Enter the dev password to continue:");
        if (password) {
            sessionStorage.setItem("cognicoach_dev_password", password);
        }
    }
    return password;
}

function getCompetitionNotesStore() {
    try {
        return JSON.parse(localStorage.getItem(COMPETITION_NOTES_KEY) || '{}');
    } catch (e) {
        return {};
    }
}

function saveCompetitionNotesStore(store) {
    try {
        localStorage.setItem(COMPETITION_NOTES_KEY, JSON.stringify(store));
    } catch (e) {
        console.warn('Failed to save competition notes:', e);
    }
}

// -- Invisible Turnstile, dedicated to this feature --------------------------
// Independent of script.js's drill-generation widget (different container,
// different token queue) so the two never fight over the same in-flight
// token. Doesn't need to BE the api.js `onload` callback — it just waits
// for the `turnstile` global to exist, however it got loaded.

let competitionTurnstileWidgetId = null;
let competitionTurnstileReadyPromise = null;
let competitionTurnstileBusy = false; // true while an execute() call is in flight
let pendingCompetitionTurnstileResolve = null;
let pendingCompetitionTurnstileReject = null;

function waitForTurnstileGlobal(timeoutMs = 15000) {
    return new Promise((resolve, reject) => {
        const start = Date.now();
        (function poll() {
            if (typeof turnstile !== 'undefined') {
                resolve();
                return;
            }
            if (Date.now() - start > timeoutMs) {
                reject(new Error('Turnstile failed to load.'));
                return;
            }
            setTimeout(poll, 150);
        })();
    });
}

function ensureCompetitionTurnstile() {
    const container = document.getElementById('competitionTurnstileContainer');
    if (!container) return Promise.reject(new Error('No competition Turnstile container on this page.'));

    if (!competitionTurnstileReadyPromise) {
        competitionTurnstileReadyPromise = waitForTurnstileGlobal().then(() => {
            // execution: 'execute' stops Turnstile from auto-firing (and
            // burning) a challenge the instant it's rendered — without
            // this, that silent auto-run consumes the token before we
            // ever call execute() ourselves below, so the token we send
            // the Worker is already-redeemed and siteverify (correctly)
            // 403s it. See script.js's onTurnstileLoad for the same
            // pattern on the drill-generation widget.
            competitionTurnstileWidgetId = turnstile.render('#competitionTurnstileContainer', {
                sitekey: COMPETITION_TURNSTILE_SITE_KEY,
                size: 'invisible',
                execution: 'execute',
                callback: (token) => {
                    competitionTurnstileBusy = false;
                    if (pendingCompetitionTurnstileResolve) {
                        pendingCompetitionTurnstileResolve(token);
                        pendingCompetitionTurnstileResolve = null;
                        pendingCompetitionTurnstileReject = null;
                    }
                },
                'error-callback': () => {
                    competitionTurnstileBusy = false;
                    if (pendingCompetitionTurnstileReject) {
                        pendingCompetitionTurnstileReject(new Error('Bot check failed. Please refresh and try again.'));
                        pendingCompetitionTurnstileResolve = null;
                        pendingCompetitionTurnstileReject = null;
                    }
                }
            });
        });
    }
    return competitionTurnstileReadyPromise;
}

async function getCompetitionTurnstileToken() {
    await ensureCompetitionTurnstile();
    return new Promise((resolve, reject) => {
        if (competitionTurnstileBusy) {
            reject(new Error('Bot check already in progress.'));
            return;
        }
        competitionTurnstileBusy = true;
        pendingCompetitionTurnstileResolve = resolve;
        pendingCompetitionTurnstileReject = reject;
        // Reset before every execute() — without this, a second call on
        // an already-fired widget replays the same spent token instead
        // of getting a fresh one, which the same way redeems a token
        // that's no longer valid and gets 403'd by the Worker.
        turnstile.reset(competitionTurnstileWidgetId);
        turnstile.execute(competitionTurnstileWidgetId);
    });
}

// -- Background note generation (called from script.js's startSession) -----

async function generateCompetitionNotes(setup) {
    try {
        const sport = (setup.sport || '').trim();
        if (!sport || sport === 'General') return; // nothing sport-specific to base notes on

        const store = getCompetitionNotesStore();
        const prior = (store[sport] && store[sport].notes) || [];

        const turnstileToken = await getCompetitionTurnstileToken();

        const headers = { "Content-Type": "application/json" };
        const appPassword = getCompetitionAppPassword();
        if (appPassword) headers["X-App-Password"] = appPassword;

        const response = await fetch(COMPETITION_NOTES_API_URL, {
            method: "POST",
            headers,
            body: JSON.stringify({
                sport,
                focus: setup.focus || '',
                muscleGroup: setup.muscleGroup || '',
                level: String(setup.level != null ? setup.level : ''),
                location: setup.location || '',
                priorNotes: prior,
                turnstileToken
            })
        });

        if (response.status === 401) {
            sessionStorage.removeItem("cognicoach_dev_password");
        }
        if (!response.ok) throw new Error(`Competition notes API error ${response.status}`);

        const data = await response.json();
        const notes = Array.isArray(data.notes) ? data.notes.filter(n => typeof n === 'string' && n.trim()) : [];
        if (notes.length === 0) return;

        store[sport] = {
            notes: notes.slice(0, 8),
            updatedAt: new Date().toISOString(),
            sessionCount: ((store[sport] && store[sport].sessionCount) || 0) + 1
        };
        saveCompetitionNotesStore(store);

        // If Competition Mode happens to be open on this sport right now
        // (rare — different page — but harmless to guard for), refresh it.
        if (typeof renderCompetitionNotes === 'function' && getSelectedCompetitionSport() === sport) {
            renderCompetitionNotes();
        }
    } catch (error) {
        // Never surface this to the person — it's a quiet background
        // enrichment step, not something that should interrupt a workout.
        console.warn('Competition note generation skipped:', error);
    }
}

// -- Competition Mode page ----------------------------------------------------
// Everything below only does anything on competition.html (guarded by the
// presence of #competitionSportSelect), so it's safe to include this file
// on index.html purely for generateCompetitionNotes above.

let competitionChatHistory = []; // [{role: 'user'|'assistant', content: string}] for the SELECTED sport only

function getAllKnownSportsForPicker() {
    const known = new Set();
    if (typeof PROFILE_SPORTS !== 'undefined') PROFILE_SPORTS.forEach(s => known.add(s));
    if (typeof loadProfile === 'function') {
        try {
            const profile = loadProfile();
            Object.keys(profile.sportProfiles || {}).forEach(s => known.add(s));
        } catch (e) { /* ignore */ }
    }
    Object.keys(getCompetitionNotesStore()).forEach(s => known.add(s));
    return Array.from(known).filter(Boolean).sort((a, b) => a.localeCompare(b));
}

function getSelectedCompetitionSport() {
    const saved = localStorage.getItem(COMPETITION_SELECTED_SPORT_KEY);
    if (saved) return saved;
    if (typeof currentSport === 'function') {
        try { return currentSport(); } catch (e) { /* ignore */ }
    }
    const known = getAllKnownSportsForPicker();
    return known[0] || '';
}

function setSelectedCompetitionSport(sport) {
    localStorage.setItem(COMPETITION_SELECTED_SPORT_KEY, sport);
    competitionChatHistory = [];
    renderCompetitionNotes();
    renderCompetitionChatLog();
}

function renderCompetitionSportPicker() {
    const select = document.getElementById('competitionSportSelect');
    if (!select) return;

    const known = getAllKnownSportsForPicker();
    const selected = getSelectedCompetitionSport();

    if (known.length === 0) {
        select.innerHTML = '<option value="">No sports trained yet</option>';
        select.disabled = true;
        return;
    }

    select.disabled = false;
    select.innerHTML = known.map(s =>
        `<option value="${s}" ${s === selected ? 'selected' : ''}>${s}</option>`
    ).join('');
}

function renderCompetitionNotes() {
    const list = document.getElementById('competitionNotesList');
    const meta = document.getElementById('competitionNotesMeta');
    const emptyState = document.getElementById('competitionNotesEmpty');
    if (!list) return;

    const sport = getSelectedCompetitionSport();
    const store = getCompetitionNotesStore();
    const entry = sport && store[sport];

    if (!entry || !entry.notes || entry.notes.length === 0) {
        list.innerHTML = '';
        list.classList.add('hidden');
        if (meta) meta.textContent = '';
        if (emptyState) emptyState.classList.remove('hidden');
        return;
    }

    if (emptyState) emptyState.classList.add('hidden');
    list.classList.remove('hidden');
    list.innerHTML = entry.notes.map(note => `<li>${escapeCompetitionHtml(note)}</li>`).join('');

    if (meta) {
        const when = new Date(entry.updatedAt);
        const whenStr = isNaN(when.getTime()) ? '' : when.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
        meta.textContent = `Based on ${entry.sessionCount || 1} session${(entry.sessionCount || 1) === 1 ? '' : 's'}${whenStr ? ' · updated ' + whenStr : ''}.`;
    }
}

function escapeCompetitionHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

async function handleGenerateNotesClick() {
    const btn = document.getElementById('generateNotesBtn');
    const sport = getSelectedCompetitionSport();
    if (!sport) return;

    let setupBasis = { sport, focus: '', muscleGroup: '', level: '', location: '' };
    if (typeof getSmartDefaults === 'function') {
        try {
            const defaults = getSmartDefaults(sport);
            setupBasis = { sport, focus: defaults.focus, muscleGroup: defaults.muscleGroup, level: defaults.level, location: defaults.location };
        } catch (e) { /* fall back to blank basis */ }
    }

    if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }
    try {
        await generateCompetitionNotes(setupBasis);
        renderCompetitionNotes();
    } catch (e) {
        console.error('Manual note generation failed:', e);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Generate Focus Notes'; }
    }
}

function renderCompetitionChatLog() {
    const log = document.getElementById('competitionChatLog');
    if (!log) return;

    const sport = getSelectedCompetitionSport();

    if (competitionChatHistory.length === 0) {
        log.innerHTML = `<div class="comp-chat-msg comp-chat-assistant">${sport
            ? `Ask me anything about getting ready to compete in ${escapeCompetitionHtml(sport)}.`
            : 'Pick a sport above to start chatting.'}</div>`;
        return;
    }

    log.innerHTML = competitionChatHistory.map(m =>
        `<div class="comp-chat-msg comp-chat-${m.role}">${escapeCompetitionHtml(m.content)}</div>`
    ).join('');
    log.scrollTop = log.scrollHeight;
}

async function handleCompetitionChatSubmit(event) {
    event.preventDefault();

    const input = document.getElementById('competitionChatInput');
    const sendBtn = document.getElementById('competitionChatSendBtn');
    const sport = getSelectedCompetitionSport();
    if (!input || !sport) return;

    const message = input.value.trim();
    if (!message) return;

    competitionChatHistory.push({ role: 'user', content: message.slice(0, 1000) });
    input.value = '';
    renderCompetitionChatLog();

    if (sendBtn) sendBtn.disabled = true;
    if (input) input.disabled = true;

    const typingLog = document.getElementById('competitionChatLog');
    const typingEl = document.createElement('div');
    typingEl.className = 'comp-chat-msg comp-chat-assistant comp-chat-typing';
    typingEl.textContent = 'Thinking…';
    if (typingLog) { typingLog.appendChild(typingEl); typingLog.scrollTop = typingLog.scrollHeight; }

    try {
        const turnstileToken = await getCompetitionTurnstileToken();
        const store = getCompetitionNotesStore();
        const notes = (store[sport] && store[sport].notes) || [];

        const headers = { "Content-Type": "application/json" };
        const appPassword = getCompetitionAppPassword();
        if (appPassword) headers["X-App-Password"] = appPassword;

        const response = await fetch(COMPETITION_CHAT_API_URL, {
            method: "POST",
            headers,
            body: JSON.stringify({
                sport,
                notes,
                history: competitionChatHistory.slice(-16, -1), // recent context, excludes the message just sent (sent separately)
                message,
                turnstileToken
            })
        });

        if (response.status === 401) {
            sessionStorage.removeItem("cognicoach_dev_password");
        }
        if (!response.ok) throw new Error(`Competition chat API error ${response.status}`);

        const data = await response.json();
        const reply = (data && typeof data.reply === 'string' && data.reply.trim())
            ? data.reply.trim()
            : "Sorry, I couldn't come up with a reply just now — try asking again.";

        competitionChatHistory.push({ role: 'assistant', content: reply.slice(0, 3000) });
    } catch (error) {
        console.error('Competition chat failed:', error);
        competitionChatHistory.push({ role: 'assistant', content: "Something went wrong reaching the coach right now. Please try again in a moment." });
    } finally {
        if (typingEl) typingEl.remove();
        renderCompetitionChatLog();
        if (sendBtn) sendBtn.disabled = false;
        if (input) { input.disabled = false; input.focus(); }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const select = document.getElementById('competitionSportSelect');
    if (!select) return; // not on competition.html — nothing else to wire up

    renderCompetitionSportPicker();
    renderCompetitionNotes();
    renderCompetitionChatLog();

    select.addEventListener('change', () => setSelectedCompetitionSport(select.value));

    const generateBtn = document.getElementById('generateNotesBtn');
    if (generateBtn) generateBtn.addEventListener('click', handleGenerateNotesClick);

    const chatForm = document.getElementById('competitionChatForm');
    if (chatForm) chatForm.addEventListener('submit', handleCompetitionChatSubmit);
});