// ==========================================================================
// Sport-name normalization
//
// The sport field throughout the app (Advanced Setup, onboarding, sport
// switcher) is free text. Left alone, "swim", "Swimming", and "swimming "
// would each become a *different* storage key in profile.js's
// sportProfiles map, dashboard.js's session history, and
// competition.js's competition notes — fragmenting one athlete's data
// across near-duplicate sports.
//
// normalizeSportName(rawSport) collapses those into one canonical name:
//   1. Exact cache hit (localStorage) -> instant, no network call.
//   2. Case-insensitive match against sports we already know about
//      (PROFILE_SPORTS + anything already saved) -> instant.
//   3. Otherwise, ask the Worker to have the model decide whether this is
//      really the same sport as one already on file (e.g. "bball" ->
//      "Basketball") or a genuinely new one — this is the "AI grouping"
//      step, since a hardcoded alias table can't anticipate every
//      abbreviation, misspelling, or language someone might type.
// Every result is cached, so a given raw string only ever costs one
// network call across the whole app.
// ==========================================================================

const SPORT_NORMALIZE_API_URL = "https://cognicoach-backend.bodhishanbhag.workers.dev/api/normalize-sport";
const SPORT_NORMALIZE_PRODUCTION_URL = "https://cognicoachai.com/CogniCoachV1/";
const SPORT_ALIAS_CACHE_KEY = "cognicoach-sport-aliases";

function getSportAliasCache() {
    try {
        return JSON.parse(localStorage.getItem(SPORT_ALIAS_CACHE_KEY) || '{}');
    } catch (e) {
        return {};
    }
}

function saveSportAliasCache(cache) {
    try {
        localStorage.setItem(SPORT_ALIAS_CACHE_KEY, JSON.stringify(cache));
    } catch (e) {
        console.warn('Failed to save sport alias cache:', e);
    }
}

// Every canonical sport name this browser already knows about, from every
// place a sport can be recorded — used both as the "known sports" list we
// send the model and as a free local match before bothering the network.
function getKnownCanonicalSports() {
    const known = new Set();

    if (typeof PROFILE_SPORTS !== 'undefined') {
        PROFILE_SPORTS.forEach(s => known.add(s));
    }

    if (typeof loadProfile === 'function') {
        try {
            const profile = loadProfile();
            Object.keys(profile.sportProfiles || {}).forEach(s => known.add(s));
        } catch (e) { /* profile.js not ready yet — fine, skip */ }
    }

    try {
        const notesStore = JSON.parse(localStorage.getItem('cognicoach-competition-notes') || '{}');
        Object.keys(notesStore).forEach(s => known.add(s));
    } catch (e) { /* ignore */ }

    const cache = getSportAliasCache();
    Object.values(cache).forEach(s => known.add(s));

    return Array.from(known).filter(Boolean);
}

function titleCaseSport(raw) {
    return raw
        .split(/\s+/)
        .filter(Boolean)
        .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
        .join(' ');
}

function getSportNormalizeAppPassword() {
    const isProduction = window.location.href.startsWith(SPORT_NORMALIZE_PRODUCTION_URL);
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

// Resolves a raw, user-typed sport name to its canonical form. Always
// resolves (never rejects) — worst case it falls back to a cleaned-up
// version of exactly what was typed, so callers never need a try/catch
// just to keep the workout moving.
async function normalizeSportName(rawSport) {
    const trimmed = (rawSport || '').trim();
    if (!trimmed) return 'General';

    const cacheKey = trimmed.toLowerCase();
    const cache = getSportAliasCache();
    if (cache[cacheKey]) {
        return cache[cacheKey];
    }

    const known = getKnownCanonicalSports();
    const localMatch = known.find(s => s.toLowerCase() === cacheKey);
    if (localMatch) {
        cache[cacheKey] = localMatch;
        saveSportAliasCache(cache);
        return localMatch;
    }

    // Nothing local matched — ask the Worker to decide whether this is an
    // alias of a known sport or genuinely new. Only do this when there's
    // something to actually compare against or it's not worth the call.
    try {
        const headers = { "Content-Type": "application/json" };
        const appPassword = getSportNormalizeAppPassword();
        if (appPassword) headers["X-App-Password"] = appPassword;

        const response = await fetch(SPORT_NORMALIZE_API_URL, {
            method: "POST",
            headers,
            body: JSON.stringify({ sport: trimmed, knownSports: known.slice(0, 40) })
        });

        if (response.status === 401) {
            sessionStorage.removeItem("cognicoach_dev_password");
        }

        if (!response.ok) throw new Error(`Normalize API error ${response.status}`);

        const data = await response.json();
        const canonical = (data && typeof data.canonical === 'string' && data.canonical.trim())
            ? data.canonical.trim().slice(0, 60)
            : titleCaseSport(trimmed);

        cache[cacheKey] = canonical;
        saveSportAliasCache(cache);
        return canonical;
    } catch (error) {
        console.warn('Sport normalization request failed, using a cleaned-up local guess:', error);
        // Offline / worker unreachable — still return something usable and
        // consistent for THIS raw string, just without cross-sport grouping.
        const fallback = titleCaseSport(trimmed);
        cache[cacheKey] = fallback;
        saveSportAliasCache(cache);
        return fallback;
    }
}
