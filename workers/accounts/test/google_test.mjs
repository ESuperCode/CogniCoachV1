// Sign in with Google, tested with a stand-in for Google: a local RSA key whose public half is served
// as the JWKS (GOOGLE_CERTS_URL in .dev.vars). Run `node test/google_test.mjs keys <dir>` first to
// write the key set, start `wrangler dev` with GOOGLE_CERTS_URL + GOOGLE_CLIENT_ID=test-client, then run it.
import { writeFileSync, readFileSync } from "node:fs";
const [, , mode, dir] = process.argv;
const b64u = (buf) => Buffer.from(buf).toString("base64url");
if (mode === "keys") {
  const kp = await crypto.subtle.generateKey({ name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
  const pub = await crypto.subtle.exportKey("jwk", kp.publicKey);
  const priv = await crypto.subtle.exportKey("jwk", kp.privateKey);
  writeFileSync(dir + "/certs.json", JSON.stringify({ keys: [{ ...pub, kid: "test-kid", alg: "RS256", use: "sig" }] }));
  writeFileSync(dir + "/private.json", JSON.stringify(priv));
  console.log("keys written");
  process.exit(0);
}
const BASE = process.env.ACCOUNTS_URL || "http://localhost:8788";
const priv = await crypto.subtle.importKey("jwk", JSON.parse(readFileSync(dir + "/private.json", "utf8")), { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
async function token(claims, kid = "test-kid") {
  const now = Math.floor(Date.now() / 1000);
  const h = b64u(JSON.stringify({ alg: "RS256", kid, typ: "JWT" }));
  const p = b64u(JSON.stringify({ iss: "https://accounts.google.com", aud: "test-client", sub: "109876543210987654321", email: "pat@example.com",
    email_verified: true, name: "Pat Runner", iat: now, exp: now + 3600, ...claims }));
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", priv, new TextEncoder().encode(h + "." + p));
  return h + "." + p + "." + b64u(sig);
}
const call = async (path, body, tok) => {
  const r = await fetch(BASE + path, { method: body ? "POST" : "GET", headers: { "Content-Type": "application/json", Origin: "http://localhost:8099", ...(tok ? { Authorization: "Bearer " + tok } : {}) }, body: body ? JSON.stringify(body) : undefined });
  return { status: r.status, body: await r.json() };
};
let fails = 0;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fails++; };
const cfg = await call("/config");
ok(cfg.body.googleClientId === "test-client", "/config exposes the client ID");
const sub = String(Date.now()) + "1234567";
const first = await call("/google", { credential: await token({ sub }) });
ok(first.status === 200 && first.body.token && first.body.username === "Pat Runner" && first.body.created === true, "valid Google token creates an account (shown as the Google name)");
const again = await call("/google", { credential: await token({ sub }) });
ok(again.status === 200 && again.body.created === false, "same Google user signs in again (no duplicate account)");
const me = await call("/me", null, again.body.token);
ok(me.body.provider === "google" && me.body.display === "Pat Runner", "/me reports a Google account");
const put = await fetch(BASE + "/profile", { method: "PUT", headers: { "Content-Type": "application/json", Origin: "http://localhost:8099", Authorization: "Bearer " + again.body.token }, body: JSON.stringify({ data: { history: [1] }, baseVersion: 0 }) });
ok(put.status === 200, "Google account can sync its profile");
const t = await token({ sub });
ok((await call("/google", { credential: t.slice(0, -4) + "AAAA" })).status === 401, "tampered signature rejected");
ok((await call("/google", { credential: await token({ sub, aud: "someone-else" }) })).status === 401, "token for another app rejected");
ok((await call("/google", { credential: await token({ sub, exp: Math.floor(Date.now() / 1000) - 600 }) })).status === 401, "expired token rejected");
ok((await call("/google", { credential: await token({ sub, iss: "https://evil.example" }) })).status === 401, "wrong issuer rejected");
ok((await call("/google", { credential: await token({ sub }, "unknown-kid") })).status === 401, "unknown signing key rejected");
ok((await call("/signup", { username: "google-12345", key: "a".repeat(64) })).status === 422, "password usernames can't impersonate Google ids");
console.log(fails ? `FAILED (${fails})` : "ALL PASSED");
process.exit(fails ? 1 : 0);
