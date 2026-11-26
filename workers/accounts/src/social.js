// CogniCoach social: friends, public profiles, cheers and weekly leagues.
// One global SQLite Durable Object ("hub") holds the shared tables (free plan friendly: a single
// object, small rows, no cross-object fan-out). The Worker checks the caller's session with their
// own UserAccount object first and then calls the hub with their verified account id.
//
// Endpoints (all need Authorization: Bearer <token>):
//   POST /social/sync     {public, weekXp, leagues}  -> {handle, league}
//   GET  /social/me                                  -> {handle, friends[], incoming[], outgoing[], cheers[], leagues}
//   POST /social/request  {handle}                   -> {status: 'sent' | 'friends'}
//   POST /social/respond  {handle, accept}           -> {ok}
//   POST /social/remove   {handle}                   -> {ok}
//   POST /social/find     {handle}                   -> {handle, display, avatar, relation}
//   POST /social/profile  {handle}                   -> {profile}  (yourself or a friend)
//   GET  /social/league                              -> {week, tier, members[], promote, demote, endsAt, lastResult}
//   POST /social/claim                               -> {coins, chest}  (last week's league reward, once)
//   POST /social/cheer    {handle}                   -> {ok}   (once per friend per day)
//   POST /social/handle   {handle}                   -> {handle}
// Profiles are visible to friends only; leagues show handle, name, weekly XP and card frame.

const HANDLE_RE = /^[a-z0-9][a-z0-9_.-]{2,23}$/;
const DAY = 86400000;
const WEEK = 7 * DAY;
const EPOCH = Date.UTC(2024, 0, 1);       // a Monday: weeks run Monday 00:00 UTC -> Sunday
const GROUP_SIZE = 30;
const MAX_FRIENDS = 100;
const MAX_PENDING = 50;
const MAX_WEEK_XP = 6000;                  // sanity cap on a week's XP
export const LEAGUES = ["Amateur", "Club", "Regional", "National", "Continental", "World", "Olympian"];
const PODIUM_COINS = [150, 100, 60];

export const weekOf = (t) => Math.floor((t - EPOCH) / WEEK);
export const weekStart = (w) => EPOCH + w * WEEK;

const json = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
const err = (detail, status = 400, code) => json({ detail, code }, status);

function clampInt(v, max) { v = Math.round(Number(v) || 0); return Math.max(0, Math.min(max, v)); }
function clampStr(v, n) { return typeof v === "string" ? v.slice(0, n) : ""; }

// Only these fields of a public profile are stored (and only these are shown to friends).
export function cleanPublic(p) {
  p = p && typeof p === "object" ? p : {};
  return {
    level: clampStr(p.level, 20), xp: clampInt(p.xp, 1e7), weekXp: clampInt(p.weekXp, MAX_WEEK_XP), todayXp: clampInt(p.todayXp, 5000),
    streak: clampInt(p.streak, 5000), bestStreak: clampInt(p.bestStreak, 5000), ovr: clampInt(p.ovr, 99),
    rank: clampStr(p.rank, 20), tier: clampStr(p.tier, 12), frame: clampStr(p.frame, 12), title: clampStr(p.title, 30),
    topSport: clampStr(p.topSport, 30), sessions: clampInt(p.sessions, 1e6), minutes: clampInt(p.minutes, 1e8),
    avatar: /^#[0-9a-f]{6}$/i.test(p.avatar || "") ? p.avatar : "#2a78d6",
    titles: clampInt(p.titles, 99), coinsEarned: clampInt(p.coinsEarned, 1e8),
  };
}

export class SocialHub {
  constructor(ctx) {
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, handle TEXT UNIQUE, display TEXT, public TEXT,
      updated_at INTEGER, league_tier INTEGER DEFAULT 0, league_week INTEGER DEFAULT -1, resolved_week INTEGER DEFAULT -1,
      leagues_on INTEGER DEFAULT 1, last_result TEXT)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS friends (a TEXT, b TEXT, status TEXT, created_at INTEGER, PRIMARY KEY (a, b))`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS members (week INTEGER, id TEXT, tier INTEGER, grp INTEGER, xp INTEGER, updated_at INTEGER, PRIMARY KEY (week, id))`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS groups (week INTEGER, tier INTEGER, grp INTEGER, size INTEGER, PRIMARY KEY (week, tier, grp))`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS cheers (to_id TEXT, from_id TEXT, at INTEGER, seen INTEGER DEFAULT 0)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS claims (id TEXT, week INTEGER, PRIMARY KEY (id, week))`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS members_grp ON members (week, tier, grp)`);
    this.sql.exec(`CREATE INDEX IF NOT EXISTS cheers_to ON cheers (to_id, seen)`);
  }

  one(q, ...a) { return this.sql.exec(q, ...a).toArray()[0] || null; }
  all(q, ...a) { return this.sql.exec(q, ...a).toArray(); }

  // ---- users + handles ----
  freeHandle(base) {
    base = String(base || "athlete").toLowerCase().replace(/[^a-z0-9_.-]+/g, "").replace(/^[^a-z0-9]+/, "").slice(0, 18) || "athlete";
    if (base.length < 3) base = (base + "fan").slice(0, 18);
    if (!this.one("SELECT id FROM users WHERE handle = ?", base)) return base;
    for (let i = 0; i < 50; i++) {
      const h = base + "-" + (1000 + Math.floor(Math.random() * 9000));
      if (!this.one("SELECT id FROM users WHERE handle = ?", h)) return h;
    }
    return base + "-" + Date.now().toString(36);
  }

  ensureUser(me) {
    let u = this.one("SELECT * FROM users WHERE id = ?", me.id);
    if (!u) {
      const base = me.id.startsWith("google-") ? me.display : me.id;
      const handle = this.freeHandle(base);
      this.sql.exec("INSERT INTO users (id, handle, display, public, updated_at) VALUES (?, ?, ?, ?, ?)", me.id, handle, me.display || handle, "{}", Date.now());
      u = this.one("SELECT * FROM users WHERE id = ?", me.id);
    } else if (me.display && me.display !== u.display) {
      this.sql.exec("UPDATE users SET display = ? WHERE id = ?", me.display, me.id);
      u.display = me.display;
    }
    return u;
  }

  byHandle(h) { return this.one("SELECT * FROM users WHERE handle = ?", String(h || "").toLowerCase().trim().replace(/^@/, "")); }

  relation(a, b) {
    if (a === b) return "self";
    const ab = this.one("SELECT status FROM friends WHERE a = ? AND b = ?", a, b);
    if (ab && ab.status === "friends") return "friends";
    if (ab) return "outgoing";
    if (this.one("SELECT status FROM friends WHERE a = ? AND b = ? AND status = 'pending'", b, a)) return "incoming";
    return "none";
  }

  card(u, full) {
    const pub = JSON.parse(u.public || "{}");
    const base = { handle: u.handle, display: u.display, avatar: pub.avatar || "#2a78d6", frame: pub.frame || "", level: pub.level || "", league: LEAGUES[u.league_tier || 0] };
    return full ? { ...base, ...pub, updatedAt: u.updated_at } : base;
  }

  // ---- leagues ----
  resolveLastWeek(u, now) {
    const cw = weekOf(now);
    if (u.league_week < 0 || u.league_week >= cw || u.resolved_week >= u.league_week) return u;
    const m = this.one("SELECT * FROM members WHERE week = ? AND id = ?", u.league_week, u.id);
    if (m) {
      const group = this.all("SELECT id, xp, updated_at FROM members WHERE week = ? AND tier = ? AND grp = ? ORDER BY xp DESC, updated_at ASC", m.week, m.tier, m.grp);
      const n = group.length, place = group.findIndex((g) => g.id === u.id) + 1;
      const promote = n >= 2 ? Math.min(7, Math.ceil(n * 0.25)) : 1;
      const demote = n >= 10 ? Math.min(5, Math.floor(n * 0.2)) : 0;
      let tier = m.tier, moved = "stay";
      if (place <= promote && m.xp >= 50 && tier < LEAGUES.length - 1) { tier++; moved = "up"; }
      else if (demote && place > n - demote && tier > 0) { tier--; moved = "down"; }
      const coins = (n >= 2 && place <= 3 ? PODIUM_COINS[place - 1] : 0) + (moved === "up" ? 50 : 0);
      const result = { week: m.week, league: LEAGUES[m.tier], newLeague: LEAGUES[tier], place, size: n, xp: m.xp, moved, coins, chest: moved === "up" || (n >= 2 && place <= 3) ? "gold" : "" };
      this.sql.exec("UPDATE users SET league_tier = ?, resolved_week = ?, last_result = ? WHERE id = ?", tier, u.league_week, JSON.stringify(result), u.id);
      u.league_tier = tier; u.resolved_week = u.league_week; u.last_result = JSON.stringify(result);
    } else {
      this.sql.exec("UPDATE users SET resolved_week = ? WHERE id = ?", u.league_week, u.id);
    }
    return u;
  }

  joinAndScore(u, weekXp, now) {
    const cw = weekOf(now);
    let m = this.one("SELECT * FROM members WHERE week = ? AND id = ?", cw, u.id);
    if (!m) {
      if (!(weekXp > 0)) return null;
      const tier = u.league_tier || 0;
      let g = this.one("SELECT grp, size FROM groups WHERE week = ? AND tier = ? AND size < ? ORDER BY grp LIMIT 1", cw, tier, GROUP_SIZE);
      if (!g) {
        const last = this.one("SELECT MAX(grp) AS g FROM groups WHERE week = ? AND tier = ?", cw, tier);
        g = { grp: (last && last.g != null ? last.g : -1) + 1, size: 0 };
        this.sql.exec("INSERT INTO groups (week, tier, grp, size) VALUES (?, ?, ?, 0)", cw, tier, g.grp);
      }
      this.sql.exec("UPDATE groups SET size = size + 1 WHERE week = ? AND tier = ? AND grp = ?", cw, tier, g.grp);
      this.sql.exec("INSERT INTO members (week, id, tier, grp, xp, updated_at) VALUES (?, ?, ?, ?, ?, ?)", cw, u.id, tier, g.grp, weekXp, now);
      this.sql.exec("UPDATE users SET league_week = ? WHERE id = ?", cw, u.id);
      m = { week: cw, tier, grp: g.grp, xp: weekXp };
    } else if (weekXp !== m.xp) {
      this.sql.exec("UPDATE members SET xp = ?, updated_at = ? WHERE week = ? AND id = ?", weekXp, now, cw, u.id);
      m.xp = weekXp;
    }
    return m;
  }

  standings(u, now) {
    const cw = weekOf(now);
    const m = this.one("SELECT * FROM members WHERE week = ? AND id = ?", cw, u.id);
    const tier = m ? m.tier : u.league_tier || 0;
    const out = { week: cw, weekStart: weekStart(cw), endsAt: weekStart(cw + 1), league: LEAGUES[tier], tier, leagues: LEAGUES, joined: !!m,
      leaguesOn: !!u.leagues_on, members: [], promote: 0, demote: 0, lastResult: null };
    if (u.last_result) {
      const r = JSON.parse(u.last_result);
      r.claimed = !!this.one("SELECT id FROM claims WHERE id = ? AND week = ?", u.id, r.week);
      out.lastResult = r;
    }
    if (!m) return out;
    const rows = this.all(`SELECT m.id, m.xp, m.updated_at, u.handle, u.display, u.public FROM members m JOIN users u ON u.id = m.id
      WHERE m.week = ? AND m.tier = ? AND m.grp = ? ORDER BY m.xp DESC, m.updated_at ASC`, cw, m.tier, m.grp);
    const n = rows.length;
    out.promote = tier < LEAGUES.length - 1 ? (n >= 2 ? Math.min(7, Math.ceil(n * 0.25)) : 1) : 0;
    out.demote = tier > 0 && n >= 10 ? Math.min(5, Math.floor(n * 0.2)) : 0;
    out.members = rows.map((r, i) => {
      const pub = JSON.parse(r.public || "{}");
      return { place: i + 1, handle: r.handle, display: r.display, xp: r.xp, me: r.id === u.id, avatar: pub.avatar || "#2a78d6",
        frame: pub.frame || "", streak: pub.streak || 0, friend: r.id !== u.id && this.relation(u.id, r.id) === "friends" };
    });
    return out;
  }

  // ---- requests ----
  async fetch(request) {
    const body = await request.json();
    const { op, me } = body;
    const now = Number(body.testNow) > 0 ? Number(body.testNow) : Date.now();
    if (op === "purge") {
      const u = this.one("SELECT handle FROM users WHERE id = ?", me.id);
      this.sql.exec("DELETE FROM friends WHERE a = ? OR b = ?", me.id, me.id);
      this.sql.exec("DELETE FROM cheers WHERE to_id = ? OR from_id = ?", me.id, me.id);
      this.sql.exec("DELETE FROM members WHERE id = ?", me.id);
      this.sql.exec("DELETE FROM claims WHERE id = ?", me.id);
      this.sql.exec("DELETE FROM users WHERE id = ?", me.id);
      return json({ ok: true, removed: !!u });
    }
    let u = this.ensureUser(me);
    u = this.resolveLastWeek(u, now);

    if (op === "sync") {
      const pub = cleanPublic(body.public);
      const leaguesOn = body.leagues === false ? 0 : 1;
      this.sql.exec("UPDATE users SET public = ?, updated_at = ?, leagues_on = ? WHERE id = ?", JSON.stringify(pub), now, leaguesOn, u.id);
      u.leagues_on = leaguesOn; u.public = JSON.stringify(pub);
      if (leaguesOn) this.joinAndScore(u, clampInt(body.weekXp, MAX_WEEK_XP), now);
      else this.sql.exec("DELETE FROM members WHERE week = ? AND id = ?", weekOf(now), u.id);
      return json({ handle: u.handle, league: this.standings(u, now) });
    }

    if (op === "me") {
      const friends = this.all(`SELECT u.* FROM friends f JOIN users u ON u.id = f.b WHERE f.a = ? AND f.status = 'friends'`, u.id).map((f) => this.card(f, true));
      const incoming = this.all(`SELECT u.* FROM friends f JOIN users u ON u.id = f.a WHERE f.b = ? AND f.status = 'pending' ORDER BY f.created_at DESC`, u.id).map((f) => this.card(f, false));
      const outgoing = this.all(`SELECT u.* FROM friends f JOIN users u ON u.id = f.b WHERE f.a = ? AND f.status = 'pending' ORDER BY f.created_at DESC`, u.id).map((f) => this.card(f, false));
      const cheers = this.all(`SELECT c.at, u.handle, u.display FROM cheers c JOIN users u ON u.id = c.from_id WHERE c.to_id = ? AND c.seen = 0 ORDER BY c.at DESC LIMIT 20`, u.id);
      this.sql.exec("UPDATE cheers SET seen = 1 WHERE to_id = ?", u.id);
      this.sql.exec("DELETE FROM cheers WHERE at < ?", now - 30 * DAY);
      return json({ handle: u.handle, display: u.display, leaguesOn: !!u.leagues_on, friends, incoming, outgoing, cheers });
    }

    if (op === "league") return json(this.standings(u, now));

    if (op === "claim") {
      const r = u.last_result ? JSON.parse(u.last_result) : null;
      if (!r || !(r.coins || r.chest)) return err("No league reward to claim.", 404, "none");
      if (this.one("SELECT id FROM claims WHERE id = ? AND week = ?", u.id, r.week)) return err("Already claimed.", 409, "claimed");
      this.sql.exec("INSERT INTO claims (id, week) VALUES (?, ?)", u.id, r.week);
      return json({ coins: r.coins, chest: r.chest, result: r });
    }

    if (op === "handle") {
      const h = String(body.handle || "").toLowerCase().trim().replace(/^@/, "");
      if (!HANDLE_RE.test(h)) return err("Handles are 3-24 characters: letters, numbers, dots, dashes or underscores.", 422, "handle");
      const taken = this.byHandle(h);
      if (taken && taken.id !== u.id) return err("That handle is taken.", 409, "taken");
      this.sql.exec("UPDATE users SET handle = ? WHERE id = ?", h, u.id);
      return json({ handle: h });
    }

    // everything below acts on another athlete
    const other = this.byHandle(body.handle);
    if (!other) return err("No athlete with that handle.", 404, "not_found");
    const rel = this.relation(u.id, other.id);

    if (op === "find") return json({ ...this.card(other, false), relation: rel });

    if (op === "profile") {
      if (rel !== "friends" && rel !== "self") return err("Only friends can see this profile.", 403, "private");
      return json({ profile: this.card(other, true), relation: rel });
    }

    if (op === "request") {
      if (rel === "self") return err("That's you.", 422, "self");
      if (rel === "friends") return json({ status: "friends" });
      if (rel === "incoming") {   // they already asked: accept
        this.sql.exec("UPDATE friends SET status = 'friends' WHERE a = ? AND b = ?", other.id, u.id);
        this.sql.exec("INSERT OR REPLACE INTO friends (a, b, status, created_at) VALUES (?, ?, 'friends', ?)", u.id, other.id, now);
        return json({ status: "friends" });
      }
      if (rel === "outgoing") return json({ status: "sent" });
      const counts = this.one(`SELECT SUM(status = 'friends') AS f, SUM(status = 'pending') AS p FROM friends WHERE a = ?`, u.id) || {};
      if ((counts.f || 0) >= MAX_FRIENDS) return err("You've reached " + MAX_FRIENDS + " friends.", 422, "limit");
      if ((counts.p || 0) >= MAX_PENDING) return err("Too many requests waiting - wait for some answers first.", 422, "limit");
      this.sql.exec("INSERT INTO friends (a, b, status, created_at) VALUES (?, ?, 'pending', ?)", u.id, other.id, now);
      return json({ status: "sent" });
    }

    if (op === "respond") {
      if (rel !== "incoming") return err("No request from that athlete.", 404, "none");
      if (body.accept) {
        this.sql.exec("UPDATE friends SET status = 'friends' WHERE a = ? AND b = ?", other.id, u.id);
        this.sql.exec("INSERT OR REPLACE INTO friends (a, b, status, created_at) VALUES (?, ?, 'friends', ?)", u.id, other.id, now);
      } else {
        this.sql.exec("DELETE FROM friends WHERE a = ? AND b = ?", other.id, u.id);
      }
      return json({ ok: true });
    }

    if (op === "remove") {
      this.sql.exec("DELETE FROM friends WHERE (a = ? AND b = ?) OR (a = ? AND b = ?)", u.id, other.id, other.id, u.id);
      return json({ ok: true });
    }

    if (op === "cheer") {
      if (rel !== "friends") return err("You can only cheer friends.", 403, "private");
      if (this.one("SELECT at FROM cheers WHERE to_id = ? AND from_id = ? AND at > ?", other.id, u.id, now - DAY)) return err("You already cheered them today.", 429, "once");
      this.sql.exec("INSERT INTO cheers (to_id, from_id, at) VALUES (?, ?, ?)", other.id, u.id, now);
      return json({ ok: true });
    }

    return err("unknown op");
  }
}

// ---- Worker side: route /social/* to the hub with the verified account ----
const ROUTES = {
  "/social/sync": ["POST", "sync"], "/social/me": ["GET", "me"], "/social/request": ["POST", "request"],
  "/social/respond": ["POST", "respond"], "/social/remove": ["POST", "remove"], "/social/find": ["POST", "find"],
  "/social/profile": ["POST", "profile"], "/social/league": ["GET", "league"], "/social/claim": ["POST", "claim"],
  "/social/cheer": ["POST", "cheer"], "/social/handle": ["POST", "handle"],
};
export const isSocial = (path) => !!ROUTES[path];
export const socialMethod = (path) => ROUTES[path] && ROUTES[path][0];

export function hub(env) { return env.HUB.get(env.HUB.idFromName("hub")); }

// testNow: only with ALLOW_TEST_CLOCK=1 (local .dev.vars for the tests), never in production.
export async function handleSocial(env, path, me, body, testNow) {
  const op = ROUTES[path][1];
  const clock = env.ALLOW_TEST_CLOCK === "1" && Number(testNow) > 0 ? Number(testNow) : undefined;
  const resp = await hub(env).fetch("https://hub/", { method: "POST", body: JSON.stringify({ ...(body || {}), op, me, testNow: clock }) });
  return new Response(resp.body, { status: resp.status, headers: { "Content-Type": "application/json" } });
}
