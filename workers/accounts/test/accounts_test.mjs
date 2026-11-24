// Exercises the accounts API against a running Worker (default: `wrangler dev` on :8788).
//   ACCOUNTS_URL=http://localhost:8788 ORIGIN=http://localhost:8099 node test/accounts_test.mjs
const BASE = process.env.ACCOUNTS_URL || "http://localhost:8788";
const ORIGIN = process.env.ORIGIN || "http://localhost:8099";
let failures = 0;
const ok = (cond, msg) => { console.log((cond ? "PASS " : "FAIL ") + msg); if (!cond) failures++; };

async function deriveKey(username, password) {   // same as the site's scripts/account.js
  const enc = new TextEncoder();
  const base = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveBits"]);
  const bits = await crypto.subtle.deriveBits({ name: "PBKDF2", hash: "SHA-256", salt: enc.encode("cognicoach-accounts:v1:" + username.toLowerCase()), iterations: 600000 }, base, 256);
  return [...new Uint8Array(bits)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

async function call(path, { method = "POST", body, token, origin = ORIGIN } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (origin) headers.Origin = origin;
  if (token) headers.Authorization = "Bearer " + token;
  const r = await fetch(BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}

const user = "tester_" + Math.random().toString(36).slice(2, 8);
const key = await deriveKey(user, "correct horse battery");
const wrong = await deriveKey(user, "wrong password");

ok((await call("/signup", { body: { username: user, key }, origin: "https://evil.example" })).status === 403, "other origins are refused");
ok((await call("/signup", { body: { username: "x", key } })).status === 422, "short username rejected");
const s1 = await call("/signup", { body: { username: user.toUpperCase(), key } });
ok(s1.status === 200 && s1.body.token && s1.body.username === user, "signup returns a token (username lower-cased)");
ok((await call("/signup", { body: { username: user, key } })).status === 409, "duplicate username refused");
const t1 = s1.body.token;
ok((await call("/me", { method: "GET", token: t1 })).body.username === user, "/me with token");
ok((await call("/me", { method: "GET", token: t1.slice(0, -2) + "00" })).status === 401, "tampered token refused");
const g0 = await call("/profile", { method: "GET", token: t1 });
ok(g0.status === 200 && g0.body.version === 0 && g0.body.data === null, "empty profile at version 0");
const p1 = await call("/profile", { method: "PUT", token: t1, body: { data: { profile: { defaultSport: "Tennis" } }, baseVersion: 0 } });
ok(p1.status === 200 && p1.body.version === 1, "profile saved (version 1)");
const conflict = await call("/profile", { method: "PUT", token: t1, body: { data: { profile: {} }, baseVersion: 0 } });
ok(conflict.status === 409 && conflict.body.version === 1 && conflict.body.data.profile.defaultSport === "Tennis", "stale write -> 409 with the current data");
const l1 = await call("/login", { body: { username: user, key } });
ok(l1.status === 200 && l1.body.token !== t1, "login on a 2nd device");
ok((await call("/profile", { method: "GET", token: l1.body.token })).body.data.profile.defaultSport === "Tennis", "2nd device reads the synced profile");
ok((await call("/login", { body: { username: user, key: wrong } })).status === 401, "wrong password refused");
ok((await call("/login", { body: { username: "nobody_" + user, key } })).status === 401, "unknown user -> same 401");
const pw = await call("/password", { token: t1, body: { key, newKey: wrong } });
ok(pw.status === 200 && pw.body.token, "password changed");
ok((await call("/me", { method: "GET", token: l1.body.token })).status === 401, "other sessions signed out after a password change");
ok((await call("/login", { body: { username: user, key: wrong } })).status === 200, "login with the new password");
ok((await call("/logout", { token: pw.body.token })).status === 200, "logout");
ok((await call("/me", { method: "GET", token: pw.body.token })).status === 401, "token dead after logout");
let locked = false;
for (let i = 0; i < 9; i++) if ((await call("/login", { body: { username: user, key } })).status === 429) locked = true;
ok(locked, "account locks after repeated wrong passwords");
console.log(failures ? `FAILED (${failures})` : "ALL PASSED");
process.exit(failures ? 1 : 0);
