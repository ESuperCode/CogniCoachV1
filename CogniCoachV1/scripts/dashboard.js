// ==========================================================================
// CogniCoachAI Dashboard
// Reads:
//   localStorage['cognicoach-history']   -> array of completed-session records
//                                            (written by scripts/script.js)
//   localStorage['cognicoach-state']     -> in-progress session (from the app)
// Reads/writes:
//   localStorage['cognicoach-dashboard'] -> { username, weeklyGoal }
// ==========================================================================

const HISTORY_KEY = 'cognicoach-history';
const DASH_KEY = 'cognicoach-dashboard';
const STATE_KEY = 'cognicoach-state';

const ALL_SPORTS = [
    'Basketball', 'Soccer', 'Tennis', 'Football', 'Baseball',
    'Volleyball', 'Swimming', 'Cricket', 'Rugby', 'Golf'
];

const SPORT_LANDING_PAGES = {
    basketball: 'basketball-drills.html',
    soccer: 'soccer-training.html',
    tennis: 'tennis-workout.html',
    football: 'football-drills.html',
    baseball: 'baseball-practice.html',
    volleyball: 'volleyball-training.html',
    swimming: 'swimming-training.html',
    cricket: 'cricket-practice.html',
    rugby: 'rugby-training.html',
    golf: 'golf-training.html'
};

// -- Storage helpers --------------------------------------------------------

function loadHistory() {
    try {
        const raw = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
        return Array.isArray(raw) ? raw : [];
    } catch (e) {
        console.error('Failed to read session history:', e);
        return [];
    }
}

function loadDashboardSettings() {
    const defaults = { weeklyGoal: 3 };
    try {
        const saved = JSON.parse(localStorage.getItem(DASH_KEY) || '{}');
        return { ...defaults, ...saved };
    } catch (e) {
        return defaults;
    }
}

function saveDashboardSettings(settings) {
    localStorage.setItem(DASH_KEY, JSON.stringify(settings));
}

// -- Date helpers (local calendar days, not UTC) -----------------------------

function toLocalDateStr(d) {
    const offsetMs = d.getTimezoneOffset() * 60000;
    return new Date(d.getTime() - offsetMs).toISOString().slice(0, 10);
}

function startOfWeek(d) {
    const copy = new Date(d);
    copy.setHours(0, 0, 0, 0);
    copy.setDate(copy.getDate() - copy.getDay());
    return copy;
}

// -- Streaks ------------------------------------------------------------------

function getSessionDaySet(history) {
    const days = new Set();
    history.forEach(r => days.add(toLocalDateStr(new Date(r.date))));
    return days;
}

function computeStreaks(history) {
    const days = getSessionDaySet(history);
    if (days.size === 0) return { current: 0, longest: 0 };
    // Days covered by a Streak Freeze (scripts/economy.js) keep a streak alive without adding to it.
    let frozen = new Set();
    try { frozen = new Set((JSON.parse(localStorage.getItem('cognicoach-wallet') || '{}').frozenDays) || []); } catch (e) {}

    const sorted = Array.from(days).sort();
    let longest = 1;
    let run = 1;
    for (let i = 1; i < sorted.length; i++) {
        const diffDays = Math.round(
            (new Date(sorted[i]) - new Date(sorted[i - 1])) / 86400000
        );
        let bridged = diffDays === 1;
        if (!bridged && diffDays > 1) {
            bridged = true;
            for (let g = 1; g < diffDays; g++) {
                const mid = new Date(sorted[i - 1] + 'T12:00:00');
                mid.setDate(mid.getDate() + g);
                if (!frozen.has(toLocalDateStr(mid))) { bridged = false; break; }
            }
        }
        run = bridged ? run + 1 : 1;
        longest = Math.max(longest, run);
    }

    // Count backward from today; allow yesterday as the anchor so the
    // streak doesn't reset to 0 before the person has trained today.
    let current = 0;
    let cursor = new Date();
    let cursorStr = toLocalDateStr(cursor);
    if (!days.has(cursorStr)) {
        cursor.setDate(cursor.getDate() - 1);
        cursorStr = toLocalDateStr(cursor);
    }
    while (days.has(cursorStr) || frozen.has(cursorStr)) {
        if (days.has(cursorStr)) current++;
        cursor.setDate(cursor.getDate() - 1);
        cursorStr = toLocalDateStr(cursor);
    }

    return { current, longest };
}

// -- Heatmap ------------------------------------------------------------------

function buildHeatmapCells(history, weeks) {
    const counts = {};
    history.forEach(r => {
        const key = toLocalDateStr(new Date(r.date));
        counts[key] = (counts[key] || 0) + 1;
    });

    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const endOfThisWeek = new Date(today);
    endOfThisWeek.setDate(today.getDate() + (6 - today.getDay()));

    const totalDays = weeks * 7;
    const start = new Date(endOfThisWeek);
    start.setDate(endOfThisWeek.getDate() - totalDays + 1);

    const cells = [];
    for (let i = 0; i < totalDays; i++) {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        const key = toLocalDateStr(d);
        cells.push({
            date: key,
            count: counts[key] || 0,
            isFuture: d > today
        });
    }
    return cells;
}

function levelForCount(count) {
    if (count <= 0) return 0;
    if (count === 1) return 1;
    if (count === 2) return 2;
    return 3;
}

function renderHeatmap(history) {
    const weeks = window.innerWidth < 600 ? 10 : 18;
    const cells = buildHeatmapCells(history, weeks);
    const grid = document.getElementById('heatmapGrid');
    grid.innerHTML = '';

    cells.forEach(cell => {
        const el = document.createElement('div');
        el.className = 'heatmap-cell' + (cell.isFuture ? ' future' : '');
        el.dataset.level = String(levelForCount(cell.count));
        const label = cell.count === 0
            ? 'No session'
            : `${cell.count} session${cell.count > 1 ? 's' : ''}`;
        el.title = `${cell.date} — ${label}`;
        grid.appendChild(el);
    });
}

// -- Weekly goal ----------------------------------------------------------------

function sessionsThisWeek(history) {
    const weekStart = startOfWeek(new Date());
    return history.filter(r => new Date(r.date) >= weekStart).length;
}

function renderGoal(history, settings) {
    const input = document.getElementById('weeklyGoalInput');
    input.value = settings.weeklyGoal;
    const goalNow = document.getElementById('weeklyGoalNow');
    if (goalNow) goalNow.textContent = `${settings.weeklyGoal} session${settings.weeklyGoal == 1 ? '' : 's'} a week`;

    const done = sessionsThisWeek(history);
    const goal = Math.max(1, parseInt(settings.weeklyGoal, 10) || 1);
    const pct = Math.min(100, Math.round((done / goal) * 100));

    document.getElementById('goalProgressFill').style.width = pct + '%';
    const weekStart = startOfWeek(new Date());
    const mins = history.filter(r => new Date(r.date) >= weekStart).reduce((t, r) => t + (Number(r.workoutLength) || 0), 0);
    document.getElementById('goalProgressText').textContent =
        (done >= goal
            ? `Goal reached: ${done} of ${goal} sessions.`
            : `${done} of ${goal} sessions done.`) + ` ${mins} minutes trained this week.`;
}

// -- Badges -----------------------------------------------------------------------

function computeBadges(history) {
    const { longest } = computeStreaks(history);
    const totalSessions = history.length;
    const sportsSet = new Set(
        history.map(r => (r.sport || '').trim().toLowerCase()).filter(Boolean)
    );
    const longestSession = history.reduce((m, r) => Math.max(m, r.workoutLength || 0), 0);
    const hasEarly = history.some(r => new Date(r.date).getHours() < 7);
    const hasNight = history.some(r => new Date(r.date).getHours() >= 21);
    const hasWeekend = history.some(r => {
        const day = new Date(r.date).getDay();
        return day === 0 || day === 6;
    });

    return [
        { icon: 'flag', name: 'First Step', desc: 'Complete your first session', unlocked: totalSessions >= 1 },
        { icon: 'flame', name: 'Consistent', desc: '3-day streak', unlocked: longest >= 3 },
        { icon: 'bolt', name: 'On Fire', desc: '7-day streak', unlocked: longest >= 7 },
        { icon: 'gem', name: 'Iron Will', desc: '30-day streak', unlocked: longest >= 30 },
        { icon: 'target', name: 'Committed', desc: '10 total sessions', unlocked: totalSessions >= 10 },
        { icon: 'trophy-gold', name: 'Century Club', desc: '50 total sessions', unlocked: totalSessions >= 50 },
        { icon: 'compass', name: 'Explorer', desc: 'Train in 3 different sports', unlocked: sportsSet.size >= 3 },
        { icon: 'globe', name: 'All-Rounder', desc: 'Train in 5 different sports', unlocked: sportsSet.size >= 5 },
        { icon: 'runner', name: 'Marathoner', desc: 'Complete a 90+ min session', unlocked: longestSession >= 90 },
        { icon: 'sunrise', name: 'Early Bird', desc: 'Train before 7am', unlocked: hasEarly },
        { icon: 'moon', name: 'Night Owl', desc: 'Train after 9pm', unlocked: hasNight },
        { icon: 'party', name: 'Weekend Warrior', desc: 'Train on a weekend', unlocked: hasWeekend }
    ];
}

function renderBadges(history) {
    const badges = computeBadges(history);
    const grid = document.getElementById('badgeGrid');
    grid.innerHTML = '';

    // Earned badges first, then the ones still to get.
    badges.filter(b => b.unlocked).concat(badges.filter(b => !b.unlocked)).forEach(b => {
        const el = document.createElement('div');
        el.className = 'badge ' + (b.unlocked ? 'unlocked' : 'locked');
        el.innerHTML = `
            <span class="badge-icon" aria-hidden="true">${window.CogniIcons ? window.CogniIcons.svg(b.icon, { size: 34 }) : ''}</span>
            <div class="badge-name">${b.name}</div>
            <div class="badge-desc">${b.desc}</div>
        `;
        grid.appendChild(el);
    });

    const unlockedCount = badges.filter(b => b.unlocked).length;
    document.getElementById('badgeCount').textContent = `${unlockedCount} / ${badges.length}`;
}

// -- Recommendations ------------------------------------------------------------

function getRecommendedSports(history) {
    const lastPracticed = {};
    const countBySport = {};

    history.forEach(r => {
        const sport = (r.sport || '').trim();
        if (!sport) return;
        countBySport[sport] = (countBySport[sport] || 0) + 1;
        const d = new Date(r.date);
        if (!lastPracticed[sport] || d > lastPracticed[sport]) lastPracticed[sport] = d;
    });

    // Your own sports first: your main sport, then the ones you have not trained for a while,
    // then one new sport to try.
    let main = '';
    try { main = (typeof loadProfile === 'function' && loadProfile().defaultSport) || ''; } catch (e) {}
    const tried = Object.keys(lastPracticed).sort((a, b) => lastPracticed[a] - lastPracticed[b]);
    const has = (list, s) => list.some(t => t.toLowerCase() === String(s).toLowerCase());
    const result = [];
    if (main) result.push(main);
    tried.forEach(s => { if (result.length < 3 && !has(result, s)) result.push(s); });
    const fresh = ALL_SPORTS.find(s => !has(result, s) && !has(Object.keys(countBySport), s));
    if (result.length < 3 && fresh) result.push(fresh);

    return result.map(sport => {
        const key = Object.keys(lastPracticed).find(t => t.toLowerCase() === sport.toLowerCase());
        if (!key) return { sport, reason: sport === main ? 'Your main sport' : 'Something new to try' };
        const days = Math.floor((new Date() - lastPracticed[key]) / 86400000);
        const when = days <= 0 ? 'Trained today' : `Last trained ${days} day${days > 1 ? 's' : ''} ago`;
        return { sport, reason: sport === main ? `Your main sport · ${when.toLowerCase()}` : when };
    });
}

function buildQuickStartUrl(sport, opts) {
    // Use what this athlete usually picks for the sport (scripts/profile.js), when it knows.
    let learned = {};
    try { if (typeof getSmartDefaults === 'function') learned = getSmartDefaults(sport) || {}; } catch (e) {}
    const params = new URLSearchParams({
        sport,
        location: (opts && opts.location) || learned.location || 'Gym',
        focus: (opts && opts.focus) || learned.focus || '',
        workoutLength: (opts && opts.workoutLength) || learned.workoutLength || 45
    });
    return `index.html?${params.toString()}`;
}

function renderRecommendations(history) {
    const recs = getRecommendedSports(history);
    const grid = document.getElementById('recommendGrid');
    grid.innerHTML = '';

    recs.forEach(({ sport, reason }) => {
        const el = document.createElement('div');
        el.className = 'recommend-card';
        el.innerHTML = `
            <div class="recommend-text"><div class="recommend-sport">${sport}</div>
            <div class="recommend-reason">${reason}</div></div>
            <a class="btn btn-secondary" href="${buildQuickStartUrl(sport)}" aria-label="Start a ${sport} workout">Start</a>
        `;
        grid.appendChild(el);
    });
}

// -- Repeat last workout / resume in-progress session ---------------------------

function renderSmartActions(history) {
    const container = document.getElementById('smartActions');
    container.innerHTML = '';

    // Resume an unfinished session, if one exists.
    try {
        const saved = JSON.parse(localStorage.getItem(STATE_KEY) || 'null');
        if (saved && saved.session && saved.session.drills && saved.session.drills.length > 0) {
            const sport = (saved.setup && saved.setup.sport) || 'your workout';
            const banner = document.createElement('div');
            banner.className = 'resume-banner';
            banner.innerHTML = `
                <div class="resume-banner-text">You have an unfinished <strong>${sport}</strong> session waiting.</div>
                <a class="btn btn-primary" href="index.html">Resume Session</a>
            `;
            container.appendChild(banner);
        }
    } catch (e) {
        // ignore malformed state
    }

    // Repeat the most recent completed workout.
    if (history.length > 0) {
        const last = history[history.length - 1];
        const banner = document.createElement('div');
        banner.className = 'resume-banner';
        banner.innerHTML = `
            <div class="resume-banner-text">Repeat your last session: <strong>${last.sport}</strong>${last.focus ? ` — ${last.focus}` : ''}</div>
            <a class="btn btn-secondary" href="${buildQuickStartUrl(last.sport, last)}">Repeat Workout</a>
        `;
        container.appendChild(banner);
    }
}

// -- Weekly summary stats ---------------------------------------------------------

function renderStats(history) {
    const { current, longest } = computeStreaks(history);
    const totalSessions = history.length;
    const weekSessions = sessionsThisWeek(history);
    const weekMinutes = history
        .filter(r => new Date(r.date) >= startOfWeek(new Date()))
        .reduce((sum, r) => sum + (r.workoutLength || 0), 0);

    const sportCounts = {};
    history.forEach(r => {
        if (!r.sport) return;
        sportCounts[r.sport] = (sportCounts[r.sport] || 0) + 1;
    });
    const favoriteSport = Object.keys(sportCounts).sort(
        (a, b) => sportCounts[b] - sportCounts[a]
    )[0] || '—';

    document.getElementById('statCurrentStreak').textContent = current;
    document.getElementById('statLongestStreak').textContent = longest;
    document.getElementById('statTotalSessions').textContent = totalSessions;
    document.getElementById('statWeekSessions').textContent = weekSessions;
    document.getElementById('statWeekMinutes').textContent = weekMinutes;
    document.getElementById('statFavoriteSport').textContent = favoriteSport;
}

// -- Wiring ------------------------------------------------------------------------------

function renderAll() {
    const history = loadHistory();
    const settings = loadDashboardSettings();

    renderStats(history);
    renderHeatmap(history);
    renderGoal(history, settings);
    renderBadges(history);
    renderRecommendations(history);
    renderSmartActions(history);

    // Before the first session there is nothing to show yet: Home keeps just the welcome card.
    const home = document.getElementById('panel-home');
    if (home) home.classList.toggle('dash-new', history.length === 0);
}

document.addEventListener('DOMContentLoaded', () => {
    renderAll();

    document.getElementById('weeklyGoalInput').addEventListener('change', (e) => {
        const settings = loadDashboardSettings();
        let val = parseInt(e.target.value, 10);
        if (!val || val < 1) val = 1;
        if (val > 14) val = 14;
        settings.weeklyGoal = val;
        saveDashboardSettings(settings);
        renderGoal(loadHistory(), settings);
    });

    // The goal number sits behind a small Change toggle.
    const goalBtn = document.getElementById('weeklyGoalChange');
    const goalRow = document.getElementById('weeklyGoalRow');
    if (goalBtn && goalRow) {
        goalBtn.addEventListener('click', () => {
            const open = goalRow.hidden;
            goalRow.hidden = !open;
            goalBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
            goalBtn.textContent = open ? 'Done' : 'Change';
            if (open) document.getElementById('weeklyGoalInput').focus();
        });
    }

    document.getElementById('exportDataBtn').addEventListener('click', () => {
        let profile = null;
        try { profile = JSON.parse(localStorage.getItem('cognicoach-profile') || 'null'); } catch (e) { profile = null; }
        const data = {
            history: loadHistory(),
            settings: loadDashboardSettings(),
            profile
        };
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `cognicoach-data-${toLocalDateStr(new Date())}.json`;
        a.click();
        URL.revokeObjectURL(url);
    });

    document.getElementById('clearHistoryBtn').addEventListener('click', () => {
        if (confirm('This will permanently delete your saved workout history from this browser. Continue?')) {
            localStorage.removeItem(HISTORY_KEY);
            renderAll();
        }
    });

    window.addEventListener('resize', () => {
        renderHeatmap(loadHistory());
    });
});