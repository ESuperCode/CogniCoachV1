// CogniCoach accounts - Cloudflare Worker + one SQLite Durable Object per user (free plan).
//
// Passwords: the browser stretches the password with PBKDF2-SHA256 (600k rounds, salt derived from
// the username) and sends only that 32-byte key. Here it is hashed again with a random per-user salt
// before storage, so the database never holds anything that logs in directly, and the slow part runs
// in the browser (a free-plan Worker gets ~10 ms of CPU per request - too little for PBKDF2 here).
//
// Endpoints (JSON):
//   GET    /health
//   POST   /signup   {username, key}                 -> {token, username}
//   POST   /login    {username, key}                 -> {token, username}
//   POST   /logout                                    (Authorization: Bearer <token>)
//   GET    /me                                        -> {username, createdAt}
//   GET    /profile                                   -> {data, version, updatedAt}
//   PUT    /profile  {data, baseVersion}              -> {version, updatedAt}  | 409 {data, version}
//   POST   /password {key, newKey}                    -> {token} (other sessions signed out)
//   POST   /delete   {key}                            -> {ok}
//   POST   /google   {credential}                     -> {token, username, provider}  (Sign in with Google)
//   GET    /config                                    -> {googleClientId}
// Access: the site's origins, or any origin with the X-Dev-Code header.

const DEFAULT_ORIGINS = "https://cognicoachai.com,https://www.cognicoachai.com";
const USERNAME_RE = /^[a-z0-9][a-z0-9_.-]{2,23}$/;
const ACCOUNT_ID_RE = /^(?:[a-z0-9][a-z0-9_.-]{2,23}|google-\d{5,40})$/;   // password accounts + Google accounts
const GOOGLE_CERTS = "https://www.googleapis.com/oauth2/v3/certs";
let googleKeys = { at: 0, keys: {} };
const KEY_RE = /^[0-9a-f]{64}$/;
const SESSION_DAYS = 60;
const MAX_SESSIONS = 20;
const MAX_PROFILE_BYTES = 256 * 1024;
const LOCK_AFTER = 8;          // failed logins ...
const LOCK_MINUTES = 15;       // ... lock the account this long
const memHits = new Map();

const enc = new TextEncoder();

function hex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function sha256Hex(text) {
  return hex(await crypto.subtle.digest("SHA-256", enc.encode(text)));
}

function randomHex(bytes) {
  return hex(crypto.getRandomValues(new Uint8Array(bytes)));
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json", ...headers } });

const b64url = (s) => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const unb64url = (s) => decodeURIComponent(escape(atob(s.replace(/-/g, "+").replace(/_/g, "/"))));

// ---------------------------------------------------------------------------------------------
// One Durable Object per username: account row, sessions and the synced profile document.
// ---------------------------------------------------------------------------------------------
export class UserAccount {
  constructor(ctx) {
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS account (
      id INTEGER PRIMARY KEY CHECK (id = 1), username TEXT, salt TEXT, hash TEXT, created_at INTEGER,
      failed INTEGER DEFAULT 0, locked_until INTEGER DEFAULT 0)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, created_at INTEGER, expires_at INTEGER)`);
    this.sql.exec(`CREATE TABLE IF NOT EXISTS profile (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT, version INTEGER, updated_at INTEGER)`);
    const cols = this.sql.exec("PRAGMA table_info(account)").toArray().map((c) => c.name);
    if (!cols.includes("display")) this.sql.exec("ALTER TABLE account ADD COLUMN display TEXT");
    if (!cols.includes("provider")) this.sql.exec("ALTER TABLE account ADD COLUMN provider TEXT");
  }

  displayName(acc) {
    return (acc && (acc.display || acc.username)) || "";
  }

  account() {
    return this.sql.exec("SELECT * FROM account WHERE id = 1").toArray()[0] || null;
  }

  async newSession() {
    const secret = randomHex(32);
    const now = Date.now();
    this.sql.exec("DELETE FROM sessions WHERE expires_at < ?", now);
    this.sql.exec("INSERT INTO sessions VALUES (?, ?, ?)", await sha256Hex(secret), now, now + SESSION_DAYS * 86400000);
    // keep the newest sessions only
    this.sql.exec(`DELETE FROM sessions WHERE token_hash NOT IN
      (SELECT token_hash FROM sessions ORDER BY created_at DESC LIMIT ${MAX_SESSIONS})`);
    return secret;
  }

  async checkSession(secret) {
    if (!secret) return false;
    const row = this.sql.exec("SELECT expires_at FROM sessions WHERE token_hash = ?", await sha256Hex(secret)).toArray()[0];
    return !!row && row.expires_at > Date.now();
  }

  async checkKey(acc, key) {
    return safeEqual(await sha256Hex(acc.salt + ":" + key), acc.hash);
  }

  async fetch(request) {
    const { action, username, key, newKey, secret, data, baseVersion, display } = await request.json();
    const acc = this.account();
    const now = Date.now();

    if (action === "signup") {
      if (acc) return json({ detail: "That username is taken.", code: "taken" }, 409);
      const salt = randomHex(16);
      this.sql.exec("INSERT INTO account (id, username, salt, hash, created_at) VALUES (1, ?, ?, ?, ?)",
        username, salt, await sha256Hex(salt + ":" + key), now);
      return json({ secret: await this.newSession(), username });
    }

    if (action === "google") {   // the Worker already verified Google's signed token
      if (!acc) {
        this.sql.exec("INSERT INTO account (id, username, salt, hash, created_at, display, provider) VALUES (1, ?, '', '', ?, ?, 'google')",
          username, now, display || username);
      } else if (display && display !== acc.display) {
        this.sql.exec("UPDATE account SET display = ? WHERE id = 1", display);
      }
      return json({ secret: await this.newSession(), username, display: display || this.displayName(acc), provider: "google", created: !acc });
    }

    if (!acc) return json({ detail: "Wrong username or password.", code: "bad_login" }, 401);
    if (acc.provider === "google" && (action === "login" || action === "password" || action === "delete")) {
      return json({ detail: "This account uses Sign in with Google.", code: "google_account" }, 401);
    }

    if (action === "login" || action === "password" || action === "delete") {
      if (acc.locked_until > now) {
        const mins = Math.ceil((acc.locked_until - now) / 60000);
        return json({ detail: `Too many attempts. Try again in ${mins} minute${mins > 1 ? "s" : ""}.`, code: "locked" }, 429);
      }
      if (!(await this.checkKey(acc, key))) {
        const failed = (acc.failed || 0) + 1;
        const locked = failed >= LOCK_AFTER ? now + LOCK_MINUTES * 60000 : 0;
        this.sql.exec("UPDATE account SET failed = ?, locked_until = ? WHERE id = 1", locked ? 0 : failed, locked);
        return json({ detail: action === "login" ? "Wrong username or password." : "Wrong password.", code: "bad_login" }, 401);
      }
      this.sql.exec("UPDATE account SET failed = 0, locked_until = 0 WHERE id = 1");
      if (action === "login") return json({ secret: await this.newSession(), username: acc.username });
      if (action === "password") {
        const salt = randomHex(16);
        this.sql.exec("UPDATE account SET salt = ?, hash = ? WHERE id = 1", salt, await sha256Hex(salt + ":" + newKey));
        this.sql.exec("DELETE FROM sessions");
        return json({ secret: await this.newSession(), username: acc.username });
      }
      // delete
      this.sql.exec("DELETE FROM sessions");
      this.sql.exec("DELETE FROM profile");
      this.sql.exec("DELETE FROM account");
      return json({ ok: true });
    }

    // everything below needs a valid session
    if (!(await this.checkSession(secret))) return json({ detail: "Please sign in again.", code: "signed_out" }, 401);

    if (action === "logout") {
      this.sql.exec("DELETE FROM sessions WHERE token_hash = ?", await sha256Hex(secret));
      return json({ ok: true });
    }
    if (action === "me") return json({ username: acc.username, display: this.displayName(acc), provider: acc.provider || "password", createdAt: acc.created_at });
    if (action === "get") {
      const row = this.sql.exec("SELECT data, version, updated_at FROM profile WHERE id = 1").toArray()[0];
      return json(row ? { data: JSON.parse(row.data), version: row.version, updatedAt: row.updated_at }
        : { data: null, version: 0, updatedAt: 0 });
    }
    if (action === "put") {
      const row = this.sql.exec("SELECT data, version FROM profile WHERE id = 1").toArray()[0];
      const current = row ? row.version : 0;
      if (Number(baseVersion) !== current) {
        return json({ detail: "Changed on another device.", code: "conflict", data: row ? JSON.parse(row.data) : null, version: current }, 409);
      }
      const version = current + 1;
      this.sql.exec("INSERT OR REPLACE INTO profile (id, data, version, updated_at) VALUES (1, ?, ?, ?)", JSON.stringify(data), version, now);
      return json({ version, updatedAt: now });
    }
    return json({ detail: "unknown action" }, 400);
  }
}

// ---------------------------------------------------------------------------------------------
// The Worker: access control, rate limits, input checks, routing to the user's Durable Object.
// ---------------------------------------------------------------------------------------------
function allowedOrigins(env) {
  return (env.ALLOWED_ORIGINS || DEFAULT_ORIGINS).split(",").map((o) => o.trim().replace(/\/$/, "")).filter(Boolean);
}

function corsHeaders(request) {
  const origin = request.headers.get("Origin");
  const h = {
    "Access-Control-Allow-Methods": "GET, POST, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Dev-Code",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
  if (origin) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

function allowed(request, env) {
  const origin = (request.headers.get("Origin") || "").replace(/\/$/, "");
  if (env.DEV_CODE && safeEqual(request.headers.get("X-Dev-Code") || "", env.DEV_CODE)) return true;
  return !!origin && allowedOrigins(env).includes(origin);
}

function rateLimited(key, limit) {
  const now = Date.now();
  const hits = (memHits.get(key) || []).filter((t) => now - t < 60000);
  hits.push(now);
  memHits.set(key, hits);
  if (memHits.size > 5000) memHits.clear();
  return hits.length > limit;
}

function parseToken(request) {
  const auth = request.headers.get("Authorization") || "";
  const m = auth.match(/^Bearer ([A-Za-z0-9_-]+)\.([0-9a-f]{64})$/);
  if (!m) return null;
  try {
    return { username: unb64url(m[1]), secret: m[2] };
  } catch (e) {
    return null;
  }
}

async function readJson(request) {
  const text = await request.text();
  if (text.length > MAX_PROFILE_BYTES + 4096) throw Object.assign(new Error("Your saved data is too large to sync."), { status: 413 });
  try {
    return JSON.parse(text || "{}");
  } catch (e) {
    throw Object.assign(new Error("body must be JSON"), { status: 400 });
  }
}

// ---- Sign in with Google: verify the ID token (RS256 JWT) against Google's published keys ----
function b64urlBytes(s) {
  const bin = atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

async function googleKey(env, kid) {
  if (Date.now() - googleKeys.at > 3600000 || !googleKeys.keys[kid]) {
    const r = await fetch(env.GOOGLE_CERTS_URL || GOOGLE_CERTS);
    if (!r.ok) throw Object.assign(new Error("Couldn't reach Google to check the sign-in."), { status: 502 });
    const { keys } = await r.json();
    googleKeys = { at: Date.now(), keys: Object.fromEntries((keys || []).map((k) => [k.kid, k])) };
  }
  const jwk = googleKeys.keys[kid];
  if (!jwk) return null;
  return crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
}

async function verifyGoogleToken(env, credential) {
  const bad = (m) => Object.assign(new Error(m || "Google sign-in could not be verified."), { status: 401 });
  const parts = String(credential || "").split(".");
  if (parts.length !== 3) throw bad();
  let header, payload;
  try {
    header = JSON.parse(new TextDecoder().decode(b64urlBytes(parts[0])));
    payload = JSON.parse(new TextDecoder().decode(b64urlBytes(parts[1])));
  } catch (e) {
    throw bad();
  }
  if (header.alg !== "RS256" || !header.kid) throw bad();
  const key = await googleKey(env, header.kid);
  if (!key) throw bad();
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64urlBytes(parts[2]), enc.encode(parts[0] + "." + parts[1]));
  if (!ok) throw bad();
  const now = Math.floor(Date.now() / 1000);
  if (!["accounts.google.com", "https://accounts.google.com"].includes(payload.iss)) throw bad();
  if (!env.GOOGLE_CLIENT_ID || payload.aud !== env.GOOGLE_CLIENT_ID) throw bad();
  if (!(payload.exp > now - 60) || !(payload.iat < now + 300)) throw bad("That Google sign-in expired - please try again.");
  if (!/^\d{5,40}$/.test(String(payload.sub || ""))) throw bad();
  if (payload.email && payload.email_verified === false) throw bad("Please verify your Google email first.");
  const display = String(payload.name || (payload.email || "").split("@")[0] || "Athlete").slice(0, 40);
  return { id: "google-" + payload.sub, display };
}

function stub(env, username) {
  return env.USERS.get(env.USERS.idFromName(username));
}

async function callUser(env, username, payload) {
  const resp = await stub(env, username).fetch("https://user/", { method: "POST", body: JSON.stringify(payload) });
  const body = await resp.json();
  if (body.secret) {
    body.token = `${b64url(body.username)}.${body.secret}`;
    delete body.secret;
    if (body.display) body.username = body.display;   // what the site shows
  }
  return json(body, resp.status);
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    const withCors = (resp) => {
      for (const [k, v] of Object.entries(cors)) resp.headers.set(k, v);
      return resp;
    };
    const path = new URL(request.url).pathname.replace(/\/+$/, "") || "/";
    try {
      if (path === "/" || path === "/health") return withCors(json({ ok: true, service: "cognicoach-accounts", google: !!env.GOOGLE_CLIENT_ID }));
      if (path === "/config") {
        return withCors(json({ googleClientId: env.GOOGLE_CLIENT_ID || "" }, 200, { "Cache-Control": "public, max-age=300" }));
      }
      const routes = { "/signup": "POST", "/login": "POST", "/logout": "POST", "/me": "GET", "/profile": ["GET", "PUT"],
        "/password": "POST", "/delete": "POST", "/google": "POST" };
      const methods = routes[path];
      if (!methods) return withCors(json({ detail: "not found" }, 404));
      if (![].concat(methods).includes(request.method)) return withCors(json({ detail: "method not allowed" }, 405));
      if (!allowed(request, env)) return withCors(json({ detail: "Accounts only work on the CogniCoach site.", code: "origin" }, 403));

      const ip = request.headers.get("CF-Connecting-IP") || "local";
      const sensitive = ["/signup", "/login", "/password", "/delete", "/google"].includes(path);
      if (rateLimited((sensitive ? "auth:" : "api:") + ip, sensitive ? 20 : 120)) {
        return withCors(json({ detail: "Too many requests - wait a minute and try again.", code: "rate" }, 429, { "Retry-After": "60" }));
      }

      if (path === "/google") {
        if (!env.GOOGLE_CLIENT_ID) return withCors(json({ detail: "Google sign-in isn't set up yet.", code: "google_off" }, 503));
        const body = await readJson(request);
        const g = await verifyGoogleToken(env, body.credential);
        return withCors(await callUser(env, g.id, { action: "google", username: g.id, display: g.display }));
      }

      if (sensitive && path !== "/password" && path !== "/delete") {
        const body = await readJson(request);
        const username = String(body.username || "").trim().toLowerCase();
        if (!USERNAME_RE.test(username) || username.startsWith("google-")) {
          return withCors(json({ detail: "Usernames are 3-24 characters: letters, numbers, dots, dashes or underscores.", code: "username" }, 422));
        }
        if (!KEY_RE.test(String(body.key || ""))) return withCors(json({ detail: "Invalid password data.", code: "key" }, 422));
        return withCors(await callUser(env, username, { action: path.slice(1), username, key: body.key }));
      }

      const tok = parseToken(request);
      if (!tok || !ACCOUNT_ID_RE.test(tok.username)) return withCors(json({ detail: "Please sign in.", code: "signed_out" }, 401));
      if (path === "/logout") return withCors(await callUser(env, tok.username, { action: "logout", secret: tok.secret }));
      if (path === "/me") return withCors(await callUser(env, tok.username, { action: "me", secret: tok.secret }));
      if (path === "/profile" && request.method === "GET") {
        return withCors(await callUser(env, tok.username, { action: "get", secret: tok.secret }));
      }
      const body = await readJson(request);
      if (path === "/profile") {
        if (typeof body.data !== "object" || body.data === null || Array.isArray(body.data)) {
          return withCors(json({ detail: "data must be an object" }, 422));
        }
        if (JSON.stringify(body.data).length > MAX_PROFILE_BYTES) return withCors(json({ detail: "Your saved data is too large to sync." }, 413));
        return withCors(await callUser(env, tok.username, { action: "put", secret: tok.secret, data: body.data, baseVersion: body.baseVersion }));
      }
      // /password and /delete: need the session AND the current password
      if (!KEY_RE.test(String(body.key || "")) || (path === "/password" && !KEY_RE.test(String(body.newKey || "")))) {
        return withCors(json({ detail: "Invalid password data.", code: "key" }, 422));
      }
      const signedIn = await stub(env, tok.username).fetch("https://user/", { method: "POST", body: JSON.stringify({ action: "me", secret: tok.secret }) });
      if (signedIn.status !== 200) return withCors(json({ detail: "Please sign in again.", code: "signed_out" }, 401));
      return withCors(await callUser(env, tok.username, { action: path.slice(1), key: body.key, newKey: body.newKey }));
    } catch (e) {
      const status = e.status || 500;
      console.log("[accounts] error", status, e && e.stack);
      return withCors(json({ detail: status === 500 ? "Account service error." : e.message }, status));
    }
  },
};
