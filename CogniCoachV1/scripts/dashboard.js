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

    const sorted = Array.from(days).sort();
    let longest = 1;
    let run = 1;
    for (let i = 1; i < sorted.length; i++) {
        const diffDays = Math.round(
            (new Date(sorted[i]) - new Date(sorted[i - 1])) / 86400000
        );
        run = diffDays === 1 ? run + 1 : 1;
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
    while (days.has(cursorStr)) {
        current++;
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

    const done = sessionsThisWeek(history);
    const goal = Math.max(1, parseInt(settings.weeklyGoal, 10) || 1);
    const pct = Math.min(100, Math.round((done / goal) * 100));

    document.getElementById('goalProgressFill').style.width = pct + '%';
    document.getElementById('goalProgressText').textContent =
        done >= goal
            ? `Goal reached — ${done} of ${goal} sessions this week. Nice work.`
            : `${done} of ${goal} sessions this week.`;
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
        { icon: '🏁', name: 'First Step', desc: 'Complete your first session', unlocked: totalSessions >= 1 },
        { icon: '🔥', name: 'Consistent', desc: '3-day streak', unlocked: longest >= 3 },
        { icon: '⚡', name: 'On Fire', desc: '7-day streak', unlocked: longest >= 7 },
        { icon: '💎', name: 'Iron Will', desc: '30-day streak', unlocked: longest >= 30 },
        { icon: '🎯', name: 'Committed', desc: '10 total sessions', unlocked: totalSessions >= 10 },
        { icon: '🏆', name: 'Century Club', desc: '50 total sessions', unlocked: totalSessions >= 50 },
        { icon: '🧭', name: 'Explorer', desc: 'Train in 3 different sports', unlocked: sportsSet.size >= 3 },
        { icon: '🌐', name: 'All-Rounder', desc: 'Train in 5 different sports', unlocked: sportsSet.size >= 5 },
        { icon: '🏃', name: 'Marathoner', desc: 'Complete a 90+ min session', unlocked: longestSession >= 90 },
        { icon: '🌅', name: 'Early Bird', desc: 'Train before 7am', unlocked: hasEarly },
        { icon: '🌙', name: 'Night Owl', desc: 'Train after 9pm', unlocked: hasNight },
        { icon: '🎉', name: 'Weekend Warrior', desc: 'Train on a weekend', unlocked: hasWeekend }
    ];
}

function renderBadges(history) {
    const badges = computeBadges(history);
    const grid = document.getElementById('badgeGrid');
    grid.innerHTML = '';

    badges.forEach(b => {
        const el = document.createElement('div');
        el.className = 'badge ' + (b.unlocked ? 'unlocked' : 'locked');
        el.innerHTML = `
            <span class="badge-icon">${b.icon}</span>
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

    const neverTried = ALL_SPORTS.filter(
        s => !Object.keys(countBySport).some(t => t.toLowerCase() === s.toLowerCase())
    );
    const triedSorted = Object.keys(lastPracticed).sort(
        (a, b) => lastPracticed[a] - lastPracticed[b]
    );

    const ranked = [...neverTried, ...triedSorted];
    const result = [];
    ranked.forEach(sport => {
        if (result.length < 3 && !result.includes(sport)) result.push(sport);
    });
    if (result.length === 0) return ALL_SPORTS.slice(0, 3).map(s => ({ sport: s, reason: 'A fresh sport to try' }));

    return result.map(sport => {
        const isNew = !Object.keys(countBySport).some(t => t.toLowerCase() === sport.toLowerCase());
        if (isNew) return { sport, reason: "You haven't trained this yet" };
        const days = Math.round((new Date() - lastPracticed[sport]) / 86400000);
        return { sport, reason: days <= 0 ? 'Trained today' : `Last trained ${days} day${days > 1 ? 's' : ''} ago` };
    });
}

function buildQuickStartUrl(sport, opts) {
    const params = new URLSearchParams({
        sport,
        location: (opts && opts.location) || 'Gym',
        focus: (opts && opts.focus) || '',
        workoutLength: (opts && opts.workoutLength) || 45
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
            <div class="recommend-sport">${sport}</div>
            <div class="recommend-reason">${reason}</div>
            <a class="btn btn-secondary" href="${buildQuickStartUrl(sport)}">Quick Start</a>
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

    const emptyState = document.getElementById('dashEmptyState');
    emptyState.style.display = history.length === 0 ? 'block' : 'none';
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

    document.getElementById('exportDataBtn').addEventListener('click', () => {
        const data = {
            history: loadHistory(),
            settings: loadDashboardSettings()
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