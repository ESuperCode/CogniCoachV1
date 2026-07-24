// ==========================================================================
// CogniCoachAI — Personalization / Profile system
//
// Everything here lives entirely in localStorage['cognicoach-profile'].
// Nothing is sent to a server. This file is shared by index.html (Quick
// Start + onboarding) and dashboard.html (profile summary card), so every
// function guards on the presence of the DOM it needs before touching it.
//
// Responsibilities:
//   1. First-run onboarding: main sport + date of birth -> starting level.
//   2. Learning saved preferences over time (location/focus/muscle/length
//      per sport) using simple frequency + rolling-average math, so Quick
//      Start gets faster to use the more it's used.
//   3. A Quick Start card: location + duration + focus is *all* a returning
//      user has to type; everything else is inferred.
//   4. A sport switcher: shows the current default sport, with "just this
//      workout" vs "set as my default" options.
//   5. An Advanced Settings modal to edit/override anything the system
//      learned or guessed.
// ==========================================================================

const PROFILE_KEY = 'cognicoach-profile';

const PROFILE_SPORTS = [
    'Basketball', 'Soccer', 'Tennis', 'Football', 'Baseball',
    'Volleyball', 'Swimming', 'Cricket', 'Rugby', 'Golf'
];

const PROFILE_LEVELS = ['learning', 'beginner', 'intermediate', 'advanced', 'professional'];

// -- Storage ----------------------------------------------------------------

function defaultProfile() {
    return {
        onboarded: false,
        dob: null,
        age: null,
        autoLevel: true,
        manualLevel: 'intermediate',
        defaultSport: '',
        pinnedDefaultSport: false,
        sportProfiles: {},
        totalSessions: 0,
        createdAt: new Date().toISOString()
    };
}

function loadProfile() {
    try {
        const raw = JSON.parse(localStorage.getItem(PROFILE_KEY) || 'null');
        if (!raw) return defaultProfile();
        // Merge with defaults so older saved profiles pick up new fields.
        return { ...defaultProfile(), ...raw, sportProfiles: raw.sportProfiles || {} };
    } catch (e) {
        console.error('Failed to read profile, resetting:', e);
        return defaultProfile();
    }
}

function saveProfile(profile) {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(profile));
}

// -- Age / skill-level math ---------------------------------------------

function calcAge(dobStr) {
    if (!dobStr) return null;
    const dob = new Date(dobStr);
    if (isNaN(dob.getTime())) return null;
    const today = new Date();
    let age = today.getFullYear() - dob.getFullYear();
    const monthDiff = today.getMonth() - dob.getMonth();
    if (monthDiff < 0 || (monthDiff === 0 && today.getDate() < dob.getDate())) age--;
    return age >= 0 && age < 130 ? age : null;
}

// Naive age -> starting-skill-level proxy. This is deliberately simple —
// a placeholder starting point, not a real skill assessment — and is
// always editable per-sport or globally in Advanced Settings.
function levelFromAge(age) {
    if (age == null) return 'intermediate';
    if (age < 13) return 'learning';
    if (age < 18) return 'beginner';
    if (age < 40) return 'intermediate';
    if (age < 55) return 'advanced';
    return 'professional';
}

function getEffectiveLevel(profile, sport) {
    const sp = sport && profile.sportProfiles[sport];
    if (sp && sp.levelOverride) return sp.levelOverride;
    if (!profile.autoLevel) return profile.manualLevel;
    return levelFromAge(profile.age);
}

// -- Per-sport learned preferences ---------------------------------------

function ensureSportProfile(profile, sportRaw) {
    const sport = (sportRaw || 'General').trim() || 'General';
    if (!profile.sportProfiles[sport]) {
        profile.sportProfiles[sport] = {
            location: {}, focus: {}, muscleGroup: {},
            workoutLengths: [], levelOverride: null, sessions: 0
        };
    }
    return profile.sportProfiles[sport];
}

function bumpChoice(map, value) {
    const key = (value || '').trim();
    if (!key) return;
    map[key] = (map[key] || 0) + 1;
}

// Mode (most frequent value) of a frequency map.
function topChoice(map, fallback) {
    const keys = Object.keys(map || {});
    if (keys.length === 0) return fallback;
    return keys.reduce((a, b) => (map[a] >= map[b] ? a : b));
}

// Rolling average, rounded to the nearest 5 minutes and clamped to the
// slider's range, so it always drops in as a legal workoutLength value.
function averageWorkoutLength(lengths, fallback) {
    if (!lengths || lengths.length === 0) return fallback;
    const avg = lengths.reduce((a, b) => a + b, 0) / lengths.length;
    return Math.max(15, Math.min(180, Math.round(avg / 5) * 5));
}

// Called after a session's setup is collected (both Quick Start and the
// Advanced/manual builder funnel through this), so every session — however
// it was started — teaches the system a little more.
function recordSessionPreferences(setup) {
    const profile = loadProfile();
    const sport = (setup.sport || 'General').trim() || 'General';
    const sp = ensureSportProfile(profile, sport);

    bumpChoice(sp.location, setup.location);
    bumpChoice(sp.focus, setup.focus);
    bumpChoice(sp.muscleGroup, setup.muscleGroup);
    if (Number.isFinite(setup.workoutLength)) {
        sp.workoutLengths.push(setup.workoutLength);
        if (sp.workoutLengths.length > 12) sp.workoutLengths.shift();
    }
    sp.sessions = (sp.sessions || 0) + 1;

    // The most recently *used* sport quietly becomes the new default, so
    // Quick Start keeps following what someone actually trains — unless
    // they've explicitly pinned one in Advanced Settings.
    if (!profile.pinnedDefaultSport) {
        profile.defaultSport = sport;
    }

    profile.totalSessions = (profile.totalSessions || 0) + 1;
    saveProfile(profile);
}

function getSmartDefaults(sport) {
    const profile = loadProfile();
    const sp = profile.sportProfiles[sport] || {};
    return {
        location: topChoice(sp.location, ''),
        focus: topChoice(sp.focus, ''),
        muscleGroup: topChoice(sp.muscleGroup, ''),
        workoutLength: averageWorkoutLength(sp.workoutLengths, 60),
        level: getEffectiveLevel(profile, sport)
    };
}

function setDefaultSport(sport, pin) {
    const profile = loadProfile();
    profile.defaultSport = sport;
    profile.pinnedDefaultSport = !!pin;
    saveProfile(profile);
    return profile;
}

function currentSport() {
    const profile = loadProfile();
    return window.__quickStartSportOverride || profile.defaultSport || PROFILE_SPORTS[0];
}

// ==========================================================================
// Shared modal shell
// ==========================================================================

function closeProfileModal() {
    const el = document.getElementById('profileModalOverlay');
    if (el) el.remove();
}

function openProfileModal(innerHtml, { dismissible = true } = {}) {
    closeProfileModal();
    const overlay = document.createElement('div');
    overlay.id = 'profileModalOverlay';
    overlay.className = 'profile-modal-overlay';
    overlay.innerHTML = `<div class="profile-modal card">${innerHtml}</div>`;
    if (dismissible) {
        overlay.addEventListener('click', (e) => {
            if (e.target === overlay) closeProfileModal();
        });
    }
    document.body.appendChild(overlay);
    return overlay;
}

// ==========================================================================
// Onboarding (first run)
// ==========================================================================

function sportOptionsHtml(selected) {
    return PROFILE_SPORTS.map(s =>
        `<option value="${s}" ${s === selected ? 'selected' : ''}>${s}</option>`
    ).join('') + `<option value="__other__">Other / not listed</option>`;
}

function maybeShowOnboarding() {
    const profile = loadProfile();
    if (profile.onboarded) return;

    const overlay = openProfileModal(`
        <h2 class="card-title">Welcome to CogniCoachAI</h2>
        <p class="profile-modal-sub">Quick setup — about 10 seconds. This teaches Quick Start what to guess for you, and you can change any of it later.</p>

        <div class="form-group">
            <label for="onbSport">Main sport</label>
            <select id="onbSport">${sportOptionsHtml('')}</select>
            <input type="text" id="onbSportCustom" placeholder="Enter your sport" class="hidden mt-2">
        </div>

        <div class="form-group">
            <label for="onbDob">Date of birth (optional)</label>
            <input type="date" id="onbDob">
            <p class="profile-hint">Used only to suggest a starting skill level for drills — never shown anywhere else.</p>
        </div>

        <div class="profile-modal-actions">
            <button class="btn btn-secondary" id="onbSkipBtn">Skip for now</button>
            <button class="btn btn-primary" id="onbSaveBtn">Get Started</button>
        </div>
    `, { dismissible: false });

    const sportSelect = overlay.querySelector('#onbSport');
    const sportCustom = overlay.querySelector('#onbSportCustom');
    sportSelect.addEventListener('change', () => {
        sportCustom.classList.toggle('hidden', sportSelect.value !== '__other__');
    });

    overlay.querySelector('#onbSkipBtn').addEventListener('click', () => {
        const p = loadProfile();
        p.onboarded = true;
        saveProfile(p);
        closeProfileModal();
        refreshQuickStartUI();
    });

    overlay.querySelector('#onbSaveBtn').addEventListener('click', () => {
        const p = loadProfile();
        let sport = sportSelect.value === '__other__' ? sportCustom.value.trim() : sportSelect.value;
        if (!sport) sport = '';

        const dobVal = overlay.querySelector('#onbDob').value;

        p.onboarded = true;
        if (sport) {
            p.defaultSport = sport;
            ensureSportProfile(p, sport);
        }
        if (dobVal) {
            p.dob = dobVal;
            p.age = calcAge(dobVal);
        }
        saveProfile(p);
        closeProfileModal();
        refreshQuickStartUI();
    });
}

// ==========================================================================
// Sport switcher (Quick Start card)
// ==========================================================================

function renderSportSwitcher() {
    const container = document.getElementById('sportSwitcher');
    if (!container) return;

    const profile = loadProfile();
    const sport = currentSport();
    const level = getEffectiveLevel(profile, sport);

    container.innerHTML = `
        <div class="sport-switcher-row">
            <span class="sport-switcher-label">Training for</span>
            <span class="sport-switcher-current">${sport || 'Not set'}</span>
            <span class="sport-switcher-level" title="Suggested skill level for this sport">${level}</span>
            <button type="button" class="btn-chip" id="sportSwitcherToggle">Change</button>
        </div>
        <div class="sport-switcher-panel hidden" id="sportSwitcherPanel">
            <select id="sportSwitcherSelect">${sportOptionsHtml(sport)}</select>
            <input type="text" id="sportSwitcherCustom" placeholder="Custom sport name" class="hidden mt-2">
            <div class="sport-switcher-actions">
                <button type="button" class="btn btn-secondary" id="sportSwitcherOnceBtn">Just This Workout</button>
                <button type="button" class="btn btn-primary" id="sportSwitcherDefaultBtn">Set As My Default</button>
            </div>
        </div>
    `;

    const select = container.querySelector('#sportSwitcherSelect');
    const custom = container.querySelector('#sportSwitcherCustom');
    const panel = container.querySelector('#sportSwitcherPanel');

    if (sport && !PROFILE_SPORTS.includes(sport)) {
        select.value = '__other__';
        custom.value = sport;
        custom.classList.remove('hidden');
    }

    select.addEventListener('change', () => {
        custom.classList.toggle('hidden', select.value !== '__other__');
    });

    container.querySelector('#sportSwitcherToggle').addEventListener('click', () => {
        panel.classList.toggle('hidden');
    });

    function pickedSport() {
        return select.value === '__other__' ? custom.value.trim() : select.value;
    }

    container.querySelector('#sportSwitcherOnceBtn').addEventListener('click', () => {
        const picked = pickedSport();
        if (!picked) return;
        window.__quickStartSportOverride = picked;
        panel.classList.add('hidden');
        renderSportSwitcher();
        prefillQuickStartFields(picked);
    });

    container.querySelector('#sportSwitcherDefaultBtn').addEventListener('click', () => {
        const picked = pickedSport();
        if (!picked) return;
        window.__quickStartSportOverride = null;
        setDefaultSport(picked, true);
        panel.classList.add('hidden');
        renderSportSwitcher();
        prefillQuickStartFields(picked);
    });
}

// -- Prefill the actual form fields (#sport/#location/#focus/#workoutLength
// etc.) with smart defaults for a sport, so Quick Start is a single click
// for a returning user, and every field stays fully editable inline.
function prefillQuickStartFields(sport) {
    const sportInput = document.getElementById('sport');
    const locationInput = document.getElementById('location');
    const focusInput = document.getElementById('focus');
    const muscleInput = document.getElementById('muscleGroup');
    const levelSelect = document.getElementById('level');
    const lengthInput = document.getElementById('workoutLength');

    if (!sportInput) return; // not on this page

    const defaults = getSmartDefaults(sport);

    sportInput.value = sport || '';
    if (locationInput && !locationInput.dataset.userEdited) locationInput.value = defaults.location;
    if (focusInput && !focusInput.dataset.userEdited) focusInput.value = defaults.focus;
    if (muscleInput && !muscleInput.dataset.userEdited) muscleInput.value = defaults.muscleGroup;
    if (levelSelect && !levelSelect.dataset.userEdited) levelSelect.value = defaults.level;
    if (lengthInput && !lengthInput.dataset.userEdited) {
        lengthInput.value = defaults.workoutLength;
        if (typeof updateSliderValue === 'function') updateSliderValue();
    }

    const hint = document.getElementById('quickStartHint');
    if (hint) {
        const sp = loadProfile().sportProfiles[sport];
        hint.textContent = sp && sp.sessions
            ? `Filled in from ${sp.sessions} past ${sport} session${sp.sessions > 1 ? 's' : ''} — tweak anything you like.`
            : `First time with ${sport || 'this sport'} — using sensible starting defaults.`;
    }
}

// Marks a field as manually edited so prefill won't stomp on it again
// this page load.
function wireUserEditTracking() {
    ['location', 'focus', 'muscleGroup', 'level', 'workoutLength'].forEach(id => {
        const el = document.getElementById(id);
        if (!el) return;
        const evt = el.tagName === 'SELECT' ? 'change' : 'input';
        el.addEventListener(evt, () => { el.dataset.userEdited = '1'; });
    });
}

function resetUserEditTracking() {
    ['location', 'focus', 'muscleGroup', 'level', 'workoutLength'].forEach(id => {
        const el = document.getElementById(id);
        if (el) delete el.dataset.userEdited;
    });
}

// -- Quick Start button ---------------------------------------------------

function quickStartSession() {
    const sport = currentSport();
    if (!sport) {
        alert('Pick a sport first using the switcher above.');
        return;
    }
    document.getElementById('sport').value = sport;

    // A one-click Quick Start shouldn't require building a timeline by
    // hand — fall back to the default plan if none exists yet.
    if (!appState.setup.timeline || appState.setup.timeline.length === 0) {
        useDefaultWorkout();
    }

    startSession();
}

function refreshQuickStartUI() {
    if (!document.getElementById('quickStartCard')) return;
    resetUserEditTracking();
    renderSportSwitcher();
    prefillQuickStartFields(currentSport());
    wireUserEditTracking();
}

// ==========================================================================
// Advanced Settings modal (used from both index.html and dashboard.html)
// ==========================================================================

function sportPrefsRowHtml(sport, sp) {
    const location = topChoice(sp.location, '—');
    const focus = topChoice(sp.focus, '—');
    const avgLen = averageWorkoutLength(sp.workoutLengths, null);
    return `
        <tr data-sport="${sport}">
            <td>${sport}</td>
            <td>${sp.sessions || 0}</td>
            <td>${location}</td>
            <td>${focus}</td>
            <td>${avgLen ? avgLen + ' min' : '—'}</td>
            <td>
                <select class="sport-level-override" data-sport="${sport}">
                    <option value="">Auto</option>
                    ${PROFILE_LEVELS.map(l => `<option value="${l}" ${sp.levelOverride === l ? 'selected' : ''}>${l}</option>`).join('')}
                </select>
            </td>
            <td><button type="button" class="btn-chip btn-chip-danger" data-reset-sport="${sport}">Reset</button></td>
        </tr>
    `;
}

function openAdvancedSettings() {
    const profile = loadProfile();
    const sportsWithData = Object.keys(profile.sportProfiles);

    const overlay = openProfileModal(`
        <div class="profile-modal-header">
            <h2 class="card-title">Advanced Settings</h2>
            <button type="button" class="btn-chip" id="settingsCloseBtn">Close</button>
        </div>

        <div class="settings-section">
            <h3>Profile</h3>
            <div class="form-group">
                <label for="setDob">Date of birth</label>
                <input type="date" id="setDob" value="${profile.dob || ''}">
            </div>
            <div class="form-group checkbox-row">
                <label for="setAutoLevel" class="checkbox-label">
                    <input type="checkbox" id="setAutoLevel" ${profile.autoLevel ? 'checked' : ''}>
                    Auto-suggest skill level from age
                </label>
            </div>
            <div class="form-group" id="manualLevelGroup" style="${profile.autoLevel ? 'display:none;' : ''}">
                <label for="setManualLevel">Manual default level</label>
                <select id="setManualLevel">
                    ${PROFILE_LEVELS.map(l => `<option value="${l}" ${profile.manualLevel === l ? 'selected' : ''}>${l}</option>`).join('')}
                </select>
            </div>
            <div class="form-group">
                <label for="setDefaultSport">Default sport</label>
                <select id="setDefaultSport">${sportOptionsHtml(profile.defaultSport)}</select>
                <input type="text" id="setDefaultSportCustom" placeholder="Custom sport name" class="hidden mt-2">
                <div class="form-group checkbox-row mt-2">
                    <label for="setPinSport" class="checkbox-label">
                        <input type="checkbox" id="setPinSport" ${profile.pinnedDefaultSport ? 'checked' : ''}>
                        Keep this pinned (don't auto-switch to my most recent sport)
                    </label>
                </div>
            </div>
        </div>

        <div class="settings-section">
            <h3>Learned Preferences</h3>
            ${sportsWithData.length === 0
                ? '<p class="profile-hint">No sessions logged yet — this fills in as you train.</p>'
                : `<div class="settings-table-wrap">
                    <table class="settings-table">
                        <thead>
                            <tr><th>Sport</th><th>Sessions</th><th>Top Location</th><th>Top Focus</th><th>Avg. Length</th><th>Level Override</th><th></th></tr>
                        </thead>
                        <tbody id="sportPrefsBody">
                            ${sportsWithData.map(s => sportPrefsRowHtml(s, profile.sportProfiles[s])).join('')}
                        </tbody>
                    </table>
                </div>`
            }
        </div>

        <div class="settings-section text-center">
            <button type="button" class="btn btn-secondary" id="redoOnboardingBtn">Redo Setup Wizard</button>
            <button type="button" class="btn btn-danger" id="resetProfileBtn">Reset All Preferences</button>
        </div>

        <div class="profile-modal-actions">
            <button type="button" class="btn btn-primary" id="settingsSaveBtn">Save Changes</button>
        </div>
    `);

    overlay.querySelector('#settingsCloseBtn').addEventListener('click', closeProfileModal);

    const autoLevelBox = overlay.querySelector('#setAutoLevel');
    const manualLevelGroup = overlay.querySelector('#manualLevelGroup');
    autoLevelBox.addEventListener('change', () => {
        manualLevelGroup.style.display = autoLevelBox.checked ? 'none' : 'block';
    });

    const defaultSportSelect = overlay.querySelector('#setDefaultSport');
    const defaultSportCustom = overlay.querySelector('#setDefaultSportCustom');
    if (profile.defaultSport && !PROFILE_SPORTS.includes(profile.defaultSport)) {
        defaultSportSelect.value = '__other__';
        defaultSportCustom.value = profile.defaultSport;
        defaultSportCustom.classList.remove('hidden');
    }
    defaultSportSelect.addEventListener('change', () => {
        defaultSportCustom.classList.toggle('hidden', defaultSportSelect.value !== '__other__');
    });

    overlay.querySelectorAll('[data-reset-sport]').forEach(btn => {
        btn.addEventListener('click', () => {
            const sport = btn.getAttribute('data-reset-sport');
            if (!confirm(`Clear all learned preferences for ${sport}?`)) return;
            const p = loadProfile();
            delete p.sportProfiles[sport];
            saveProfile(p);
            closeProfileModal();
            openAdvancedSettings();
        });
    });

    overlay.querySelector('#redoOnboardingBtn').addEventListener('click', () => {
        const p = loadProfile();
        p.onboarded = false;
        saveProfile(p);
        closeProfileModal();
        maybeShowOnboarding();
    });

    overlay.querySelector('#resetProfileBtn').addEventListener('click', () => {
        if (!confirm('This clears your saved sport, age, and all learned preferences from this browser. Continue?')) return;
        localStorage.removeItem(PROFILE_KEY);
        closeProfileModal();
        if (typeof refreshQuickStartUI === 'function') refreshQuickStartUI();
        if (typeof renderProfileSummaryCard === 'function') renderProfileSummaryCard();
        maybeShowOnboarding();
    });

    overlay.querySelector('#settingsSaveBtn').addEventListener('click', () => {
        const p = loadProfile();

        const dobVal = overlay.querySelector('#setDob').value;
        p.dob = dobVal || null;
        p.age = calcAge(dobVal);

        p.autoLevel = autoLevelBox.checked;
        p.manualLevel = overlay.querySelector('#setManualLevel').value;

        const pickedDefault = defaultSportSelect.value === '__other__'
            ? defaultSportCustom.value.trim()
            : defaultSportSelect.value;
        if (pickedDefault) p.defaultSport = pickedDefault;
        p.pinnedDefaultSport = overlay.querySelector('#setPinSport').checked;

        overlay.querySelectorAll('.sport-level-override').forEach(sel => {
            const sport = sel.getAttribute('data-sport');
            if (p.sportProfiles[sport]) {
                p.sportProfiles[sport].levelOverride = sel.value || null;
            }
        });

        saveProfile(p);
        closeProfileModal();
        window.__quickStartSportOverride = null;
        if (typeof refreshQuickStartUI === 'function') refreshQuickStartUI();
        if (typeof renderProfileSummaryCard === 'function') renderProfileSummaryCard();
    });
}

// ==========================================================================
// Dashboard profile summary card
// ==========================================================================

function renderProfileSummaryCard() {
    const container = document.getElementById('profileSummaryCard');
    if (!container) return;

    const profile = loadProfile();
    const sport = profile.defaultSport || '—';
    const level = getEffectiveLevel(profile, profile.defaultSport);
    const sportsTrained = Object.keys(profile.sportProfiles).length;

    container.innerHTML = `
        <h2 class="card-title">Your Profile</h2>
        <div class="stat-row">
            <div class="stat-pill">
                <div class="stat-value">${profile.age != null ? profile.age : '—'}</div>
                <div class="stat-label">Age</div>
            </div>
            <div class="stat-pill">
                <div class="stat-value" style="font-size:1.1rem;">${level}</div>
                <div class="stat-label">Suggested Level</div>
            </div>
            <div class="stat-pill">
                <div class="stat-value" style="font-size:1.1rem;">${sport}</div>
                <div class="stat-label">Default Sport</div>
            </div>
            <div class="stat-pill">
                <div class="stat-value">${sportsTrained}</div>
                <div class="stat-label">Sports Tracked</div>
            </div>
        </div>
        <div class="text-center mt-4">
            <button type="button" class="btn btn-secondary" id="openSettingsFromDash">Advanced Settings</button>
        </div>
    `;

    container.querySelector('#openSettingsFromDash').addEventListener('click', openAdvancedSettings);
}

// ==========================================================================
// Wiring
// ==========================================================================

document.addEventListener('DOMContentLoaded', () => {
    // index.html — Quick Start flow
    if (document.getElementById('quickStartCard')) {
        maybeShowOnboarding();
        refreshQuickStartUI();

        const qsBtn = document.getElementById('quickStartBtn');
        if (qsBtn) qsBtn.addEventListener('click', quickStartSession);

        const settingsBtn = document.getElementById('openSettingsBtn');
        if (settingsBtn) settingsBtn.addEventListener('click', openAdvancedSettings);
    }

    // dashboard.html — profile summary
    if (document.getElementById('profileSummaryCard')) {
        renderProfileSummaryCard();
    }
});