// Exercises /social/* against a running Worker (`wrangler dev --port 8788` with ALLOW_TEST_CLOCK=1 in .dev.vars).
//   ACCOUNTS_URL=http://localhost:8788 ORIGIN=http://localhost:8099 node test/social_test.mjs
const BASE = process.env.ACCOUNTS_URL || "http://localhost:8788";
const ORIGIN = process.env.ORIGIN || "http://localhost:8099";
let failures = 0;
const ok = (cond, msg, extra) => { console.log((cond ? "PASS " : "FAIL ") + msg + (cond || extra === undefined ? "" : "  -> " + JSON.stringify(extra))); if (!cond) failures++; };
const key = "ab".repeat(32);   // the API only checks the key format; any 64-hex string works for test accounts
async function call(path, { method = "POST", body, token, now } = {}) {
  const headers = { "Content-Type": "application/json", Origin: ORIGIN };
  if (token) headers.Authorization = "Bearer " + token;
  if (now) headers["X-Test-Now"] = String(now);
  const r = await fetch(BASE + path, { method, headers, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.json().catch(() => ({})) };
}
const tag = Math.random().toString(36).slice(2, 7);
const names = ["ana_" + tag, "ben_" + tag, "cam_" + tag];
const tok = {};
for (const n of names) { const s = await call("/signup", { body: { username: n, key } }); tok[n] = s.body.token; }
const [A, B, C] = names;
ok(Object.values(tok).every(Boolean), "three test accounts");
ok((await call("/social/me", { method: "GET" })).status === 401, "social needs sign-in");
ok((await call("/social/me", { method: "POST", token: tok[A] })).status === 405, "wrong method refused");

const WEEK = 7 * 86400000, EPOCH = Date.UTC(2024, 0, 1);
const now = Date.now(), wk = Math.floor((now - EPOCH) / WEEK), mid = EPOCH + wk * WEEK + 2 * 86400000;
const pub = (xp, extra) => ({ public: { level: "Contender", xp: 500, weekXp: xp, streak: 4, ovr: 70, rank: "Gold II", frame: "gold", title: "Night Owl", avatar: "#eb6834", evil: "<script>", ...extra }, weekXp: xp });
const sA = await call("/social/sync", { token: tok[A], body: pub(120), now: mid });
ok(sA.status === 200 && sA.body.handle === A, "sync creates a handle (= username)", sA.body);
ok(sA.body.league && sA.body.league.joined && sA.body.league.league === "Amateur", "joined this week's Amateur league", sA.body.league);
await call("/social/sync", { token: tok[B], body: pub(40), now: mid });
await call("/social/sync", { token: tok[C], body: pub(0), now: mid });
const lg = await call("/social/league", { method: "GET", token: tok[A], now: mid });
ok(lg.body.members.length === 2 && lg.body.members[0].handle === A && lg.body.members[0].me, "standings: A first, C (0 XP) not in a league", lg.body.members);

ok((await call("/social/profile", { token: tok[B], body: { handle: A } })).status === 403, "profile private before friending");
const f = await call("/social/find", { token: tok[B], body: { handle: "@" + A.toUpperCase() } });
ok(f.status === 200 && f.body.relation === "none" && !("xp" in f.body), "find by handle shows only the basics", f.body);
ok((await call("/social/request", { token: tok[B], body: { handle: A } })).body.status === "sent", "B sends A a request");
const meA = await call("/social/me", { method: "GET", token: tok[A] });
ok(meA.body.incoming.length === 1 && meA.body.incoming[0].handle === B, "A sees the incoming request", meA.body);
ok((await call("/social/respond", { token: tok[A], body: { handle: B, accept: true } })).status === 200, "A accepts");
const prof = await call("/social/profile", { token: tok[B], body: { handle: A } });
ok(prof.status === 200 && prof.body.profile.title === "Night Owl" && !("evil" in prof.body.profile), "friend sees the profile (unknown fields dropped)", prof.body);
ok((await call("/social/request", { token: tok[C], body: { handle: A } })).body.status === "sent", "C requests A");
ok((await call("/social/request", { token: tok[A], body: { handle: C } })).body.status === "friends", "A requesting C back = accept");
const meA2 = await call("/social/me", { method: "GET", token: tok[A] });
ok(meA2.body.friends.length === 2 && meA2.body.incoming.length === 0, "A has two friends", meA2.body);
ok((await call("/social/cheer", { token: tok[B], body: { handle: A } })).status === 200, "B cheers A");
ok((await call("/social/cheer", { token: tok[B], body: { handle: A } })).status === 429, "only once a day");
const meA3 = await call("/social/me", { method: "GET", token: tok[A] });
ok(meA3.body.cheers.length === 1 && meA3.body.cheers[0].handle === B, "A sees the cheer once", meA3.body.cheers);
ok((await call("/social/me", { method: "GET", token: tok[A] })).body.cheers.length === 0, "cheers marked seen");
ok((await call("/social/handle", { token: tok[C], body: { handle: A } })).status === 409, "taken handle refused");
const nh = await call("/social/handle", { token: tok[C], body: { handle: "cam-new-" + tag } });
ok(nh.status === 200 && nh.body.handle === "cam-new-" + tag, "handle changed");
ok((await call("/social/remove", { token: tok[A], body: { handle: B } })).status === 200, "A removes B");
ok((await call("/social/profile", { token: tok[B], body: { handle: A } })).status === 403, "B can't see A anymore");

// next week: A (1st of 2, 120 XP) is promoted and can claim the podium reward once
const next = EPOCH + (wk + 1) * WEEK + 3600000;
const lgNext = await call("/social/league", { method: "GET", token: tok[A], now: next });
ok(lgNext.body.lastResult && lgNext.body.lastResult.moved === "up" && lgNext.body.league === "Club", "promoted to Club next week", lgNext.body);
const cl = await call("/social/claim", { token: tok[A], now: next });
ok(cl.status === 200 && cl.body.coins === 200 && cl.body.chest === "gold", "claim 150 + 50 coins and a gold chest", cl.body);
ok((await call("/social/claim", { token: tok[A], now: next })).status === 409, "claim only once");
const lgB = await call("/social/league", { method: "GET", token: tok[B], now: next });
ok(lgB.body.lastResult && lgB.body.lastResult.moved === "stay" && lgB.body.league === "Amateur", "B (40 XP, 2nd) stays", lgB.body.lastResult);
const prodClock = await call("/social/league", { method: "GET", token: tok[A] });
ok(prodClock.body.week === wk, "without the test header the real clock is used");

// deleting an account removes its social data
const del = await call("/delete", { token: tok[C], body: { key } });
ok(del.status === 200, "C deletes the account");
ok((await call("/social/find", { token: tok[A], body: { handle: "cam-new-" + tag } })).status === 404, "C is gone from social");
console.log(failures ? `FAILED (${failures})` : "ALL PASSED");
process.exit(failures ? 1 : 0);
