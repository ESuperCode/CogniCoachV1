// CogniCoach Motion Engine - Cloudflare Worker.
//
// The Worker does everything that must stay on a server: access control (site origin or dev code,
// optional Turnstile), per-IP rate limits, a daily cap on model calls, the plan cache, and the ONE
// gpt-5-mini call that turns a request into a motion script. The OpenAI key is a Worker secret.
//
// The frames themselves are compiled by the same JS compiler in the browser (dist/motion-compiler.js):
// on the Workers free plan a request may use only 10 ms of CPU, and compiling a long clip takes more.
//
// Endpoints
//   GET  /health     engine version, model, which protections are on
//   POST /generate   {movement, dominant_side?, extra_instructions?, use_cache?} -> plan (script, title, cues ...)
//   POST /validate   {script} -> {ok, warnings} or 400 with the compile error (no model call)
//   GET  /motions    the database catalog
import { ENGINE_VERSION, MODEL, VIEWS, localScript, planScript, warmUp } from "./engine.js";
import { MOTIONS, MOTION_NAMES } from "./db.js";
import { ScriptError, compileScript } from "./script.js";

warmUp(); // start-up time (not request CPU): indexes + JIT

const DEFAULT_ORIGINS = "https://cognicoachai.com,https://www.cognicoachai.com";
const MAX_BODY = 8192;
const memCache = new Map();          // per-isolate plan cache (KV is the shared one)
const MEM_CACHE_SIZE = 200;
const memHits = new Map();           // per-isolate fallback rate limiter

const json = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json", ...headers } });

function allowedOrigins(env) {
  return (env.ALLOWED_ORIGINS || DEFAULT_ORIGINS).split(",").map((o) => o.trim().replace(/\/$/, "")).filter(Boolean);
}

function corsHeaders(request) {
  const origin = request.headers.get("Origin");
  const h = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, X-Dev-Code, X-Turnstile-Token",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
  // Any page may ASK (preflight / read the error); only the site origin or a valid dev code gets work done.
  if (origin) h["Access-Control-Allow-Origin"] = origin;
  return h;
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || !a || !b) return false;
  const ea = new TextEncoder().encode(a), eb = new TextEncoder().encode(b);
  let diff = ea.length ^ eb.length;
  for (let i = 0; i < Math.max(ea.length, eb.length); i++) diff |= (ea[i % ea.length] || 0) ^ (eb[i % eb.length] || 0);
  return diff === 0;
}

// Who is calling: the live site (origin allow-list) or a developer with the dev code.
function access(request, env) {
  const origin = (request.headers.get("Origin") || "").replace(/\/$/, "");
  if (env.DEV_CODE && safeEqual(request.headers.get("X-Dev-Code") || "", env.DEV_CODE)) return { ok: true, via: "dev-code" };
  if (origin && allowedOrigins(env).includes(origin)) return { ok: true, via: "origin" };
  return { ok: false };
}

async function rateLimited(env, key, limit) {
  if (env.RATE_LIMITER && typeof env.RATE_LIMITER.limit === "function") {
    try {
      const { success } = await env.RATE_LIMITER.limit({ key });
      return !success;
    } catch (e) { /* fall through to the per-isolate limiter */ }
  }
  const now = Date.now();
  const hits = (memHits.get(key) || []).filter((t) => now - t < 60000);
  hits.push(now);
  memHits.set(key, hits);
  if (memHits.size > 5000) memHits.clear();
  return hits.length > limit;
}

async function verifyTurnstile(env, token, ip) {
  if (!token) return false;
  const form = new FormData();
  form.append("secret", env.TURNSTILE_SECRET);
  form.append("response", token);
  if (ip) form.append("remoteip", ip);
  try {
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: form });
    const d = await r.json();
    return !!d.success;
  } catch (e) {
    return false;
  }
}

async function sha256(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 32);
}

async function cacheGet(env, key) {
  if (memCache.has(key)) return memCache.get(key);
  if (!env.MOTION_CACHE) return null;
  try {
    const v = await env.MOTION_CACHE.get("plan:" + key, "json");
    if (v) memCache.set(key, v);
    return v;
  } catch (e) {
    return null;
  }
}

async function cachePut(env, key, plan) {
  memCache.set(key, plan);
  while (memCache.size > MEM_CACHE_SIZE) memCache.delete(memCache.keys().next().value);
  if (env.MOTION_CACHE) {
    try {
      await env.MOTION_CACHE.put("plan:" + key, JSON.stringify(plan), { expirationTtl: 60 * 60 * 24 * 30 });
    } catch (e) { /* KV write quota reached: the per-isolate cache still works */ }
  }
}

// Daily cap on model calls (protects the OpenAI bill). KV is eventually consistent: approximate.
async function underDailyCap(env) {
  const limit = Number(env.DAILY_MODEL_LIMIT || 300);
  if (!env.MOTION_CACHE || !(limit > 0)) return true;
  const key = "calls:" + new Date().toISOString().slice(0, 10);
  try {
    const n = Number((await env.MOTION_CACHE.get(key)) || 0);
    if (n >= limit) return false;
    await env.MOTION_CACHE.put(key, String(n + 1), { expirationTtl: 60 * 60 * 48 });
  } catch (e) { /* KV unavailable: do not block */ }
  return true;
}

async function readBody(request) {
  const text = await request.text();
  if (text.length > MAX_BODY) throw Object.assign(new Error("request body too large"), { status: 413 });
  try {
    return JSON.parse(text || "{}");
  } catch (e) {
    throw Object.assign(new Error("body must be JSON"), { status: 400 });
  }
}

async function generate(request, env, ctx, who) {
  const t0 = Date.now();
  const body = await readBody(request);
  const movement = typeof body.movement === "string" ? body.movement.trim() : "";
  const extra = typeof body.extra_instructions === "string" ? body.extra_instructions.trim() : "";
  const side = body.dominant_side === "left" ? "left" : "right";
  if (movement.length < 3 || movement.length > 400) return json({ detail: "movement must be 3-400 characters" }, 422);
  if (extra.length > 800) return json({ detail: "extra_instructions must be at most 800 characters" }, 422);

  const local = localScript(movement);
  const instant = local && local.exact && !extra;
  const cacheKey = await sha256(JSON.stringify(["script", ENGINE_VERSION, movement.toLowerCase(), extra, MODEL]));
  let raw = instant || body.use_cache === false ? null : await cacheGet(env, cacheKey);
  const cached = raw !== null;
  let calls = [];
  if (!raw) {
    if (!instant && !(await underDailyCap(env))) {
      return json({ detail: "The motion service reached today's limit of AI requests. Try again tomorrow, or use a known movement name." }, 429);
    }
    [raw, calls] = await planScript(env, movement, extra);
    if (calls[0] && calls[0].stage.startsWith("script")) ctx.waitUntil(cachePut(env, cacheKey, raw));
  }
  const total = (Date.now() - t0) / 1000;
  const source = cached ? "cache" : calls[0] ? calls[0].stage : "?";
  console.log(`[motion] ${JSON.stringify(movement.slice(0, 50))}: ${total.toFixed(1)} s via ${source} (${who.via})`);
  return json({
    compile: "client",
    script: raw.script || "",
    title: raw.title || "",
    canonical_name: raw.canonical_name || "",
    steps: raw.steps || [],
    coaching_cues: raw.coaching_cues || [],
    camera_view: VIEWS.includes(raw.camera_view) ? raw.camera_view : "three_quarter",
    dominant_side: side,
    model: MODEL,
    llm_calls: calls,
    cached,
    engine_version: ENGINE_VERSION,
    timing: { total_seconds: Math.round(total * 100) / 100, planning_seconds: Math.round(total * 100) / 100, source },
  });
}

async function validate(request) {
  const body = await readBody(request);
  const script = typeof body.script === "string" ? body.script : "";
  if (script.length < 2 || script.length > 4000) return json({ detail: "script must be 2-4000 characters" }, 422);
  try {
    const { warnings } = compileScript(script, { validateOnly: true });
    return json({ ok: true, warnings });
  } catch (e) {
    if (e instanceof ScriptError) return json({ detail: e.message }, 400);
    throw e;
  }
}

function motions() {
  return json({
    motions: MOTION_NAMES.map((n) => {
      const m = MOTIONS[n];
      const params = {};
      for (const [k, v] of Object.entries(m.params)) params[k] = v.range || v.choices;
      return { name: n, comment: m.comment, kind: m.kind, parts: m.parts, soft_parts: m.soft, params };
    }),
  }, 200, { "Cache-Control": "public, max-age=3600" });
}

export default {
  async fetch(request, env, ctx) {
    const cors = corsHeaders(request);
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    const withCors = (resp) => {
      for (const [k, v] of Object.entries(cors)) resp.headers.set(k, v);
      return resp;
    };
    try {
      if (path === "/" || path === "/health") {
        return withCors(json({
          ok: true, engine_version: ENGINE_VERSION, model: MODEL, compile: "client",
          api_key_configured: !!env.OPENAI_API_KEY, motions: MOTION_NAMES.length,
          protections: { origins: allowedOrigins(env), dev_code: !!env.DEV_CODE, turnstile: !!env.TURNSTILE_SECRET,
            rate_limit_per_minute: Number(env.RATE_LIMIT_PER_MINUTE || 10), daily_model_limit: Number(env.DAILY_MODEL_LIMIT || 300),
            shared_cache: !!env.MOTION_CACHE },
        }));
      }
      const known = { "/generate": "POST", "/validate": "POST", "/motions": "GET" };
      if (!known[path]) return withCors(json({ detail: "not found" }, 404));
      if (request.method !== known[path]) return withCors(json({ detail: "method not allowed" }, 405));

      const who = access(request, env);
      if (!who.ok) {
        return withCors(json({ detail: "This motion service only answers the CogniCoach site. Other sites and tools need a dev code (X-Dev-Code header).", code: "dev_code_required" }, 401));
      }
      const ip = request.headers.get("CF-Connecting-IP") || "unknown";
      const perMinute = Number(env.RATE_LIMIT_PER_MINUTE || 10);
      if (path === "/generate") {
        if (await rateLimited(env, "gen:" + ip, perMinute)) {
          return withCors(json({ detail: "Too many requests - wait a minute and try again." }, 429, { "Retry-After": "60" }));
        }
        if (env.TURNSTILE_SECRET && who.via === "origin" &&
          !(await verifyTurnstile(env, request.headers.get("X-Turnstile-Token"), ip))) {
          return withCors(json({ detail: "Bot check failed - refresh the page and try again.", code: "turnstile_failed" }, 403));
        }
        return withCors(await generate(request, env, ctx, who));
      }
      if (await rateLimited({ ...env, RATE_LIMITER: null }, "light:" + ip, perMinute * 6)) {
        return withCors(json({ detail: "Too many requests - wait a minute and try again." }, 429, { "Retry-After": "60" }));
      }
      if (path === "/validate") return withCors(await validate(request));
      return withCors(motions());
    } catch (e) {
      const status = e.status || 500;
      console.log("[motion] error", status, e && e.stack);
      return withCors(json({ detail: status === 500 ? "Motion service error." : e.message }, status));
    }
  },
};
