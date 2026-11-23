// Text -> motion script -> frames. A port of the script pipeline in motion_engine.py:
// instant phrases, request-specific catalog retrieval, ONE gpt-5-mini call, then the compiler.
import { ALIASES, CATALOG, ENGINE_DATA_VERSION, MOTIONS, MOTION_NAMES, RECIPES } from "./db.js";
import { compileScript, ScriptError } from "./script.js";

export const ENGINE_VERSION = `${ENGINE_DATA_VERSION}-worker`;
export const VIEWS = ["front", "side", "three_quarter", "back"];
// Only the cheap text model - deliberately not configurable.
export const MODEL = "gpt-5-mini";
const SPARSE_EPS_DEG = 0.05;

const obj = (props) => ({ type: "object", properties: props, required: Object.keys(props), additionalProperties: false });
const SCRIPT_SCHEMA = obj({
  canonical_name: { type: "string" },
  steps: { type: "array", items: { type: "string" } },
  title: { type: "string" },
  coaching_cues: { type: "array", items: { type: "string" } },
  camera_view: { type: "string", enum: VIEWS },
  script: { type: "string" },
});

// ---------------------------------------------------------------------------
// Retrieval: recipes and the per-request catalog
// ---------------------------------------------------------------------------
const STOP = new Set(["the", "and", "then", "with", "into", "from", "for", "a", "an", "of", "to", "on", "in", "at", "your", "do",
  "does", "drill", "player", "athlete", "takes", "while", "after", "before"]);
const rstripS = (w) => w.replace(/s+$/, "");
const alphaWords = (text) => text.toLowerCase().match(/[a-z]+/g) || [];
const contentWords = (text) => new Set(alphaWords(text).filter((w) => !STOP.has(w) && w.length > 2).map(rstripS));
const overlap = (a, b) => { let n = 0; for (const x of a) if (b.has(x)) n++; return n; };

// Python tuple ordering for (number, number, string) sorted in reverse.
const cmpDesc = (a, b) => {
  for (let i = 0; i < a.length; i++) {
    if (a[i] === b[i]) continue;
    return a[i] < b[i] ? 1 : -1;
  }
  return 0;
};

const RECIPE_INDEX = RECIPES.map(([sport, phrase, script]) => ({
  pw: contentWords(phrase),
  sw: new Set(alphaWords(sport).map(rstripS)),
  line: `${sport.split(" ")[0].toLowerCase()} ${phrase}: ${script.replace(/\n/g, " / ")}`,
}));

export function relevantRecipes(text, n = 8) {
  const words = contentWords(text);
  const scored = [];
  for (const r of RECIPE_INDEX) {
    const score = 2 * overlap(words, r.pw) + overlap(words, r.sw);
    if (score >= 2) scored.push([score, -r.pw.size, r.line]);
  }
  scored.sort(cmpDesc);
  return scored.slice(0, n).map((x) => x[2]);
}

const CORE = 30;
const CATALOG_N = 70;
const CORE_EXTRA = ["seated", "sit_on_bench", "lie_on_back", "lie_face_down", "kneel", "half_kneel", "table_top", "stride_step",
  "crossover_step", "cutting_step", "stop_and_stick", "catch", "overhand_throw", "chest_pass", "balance_point"];
const stems = (text) => new Set(alphaWords(text).filter((w) => !STOP.has(w) && w.length > 2).map((w) => rstripS(w).slice(0, 6)));
const CORE_NAMES = MOTION_NAMES.slice(0, CORE);
const CORE_SET = new Set(CORE_NAMES);
let catIndex = null;

export function catalogIndex() {
  if (catIndex) return catIndex;
  const used = new Map(MOTION_NAMES.map((n) => [n, new Set()]));
  for (const [phrase, script] of ALIASES) {
    const st = stems(phrase);
    for (const name of new Set(script.match(/[a-z_0-9]+/g) || [])) {
      if (used.has(name)) for (const s of st) used.get(name).add(s);
    }
  }
  catIndex = MOTION_NAMES.map((name) => [name, stems(name.replace(/_/g, " ")), used.get(name), stems(MOTIONS[name].comment)]);
  return catIndex;
}

export function relevantCatalog(request, n = CATALOG_N) {
  const index = catalogIndex();
  const names = [...CORE_NAMES, ...CORE_EXTRA.filter((x) => x in MOTIONS && !CORE_SET.has(x))];
  if (!request) return MOTION_NAMES.map((nm) => CATALOG[nm]).join("\n");
  const q = stems(request);
  const hinted = new Set();
  for (const h of relevantRecipes(request)) {
    const tail = h.includes(":") ? h.slice(h.indexOf(":") + 1) : h;
    for (const w of tail.match(/[a-z_0-9]+/g) || []) if (w in CATALOG) hinted.add(w);
  }
  const have = new Set(names);
  const scored = [];
  for (const [name, nw, aw, cw] of index) {
    const sc = 3 * overlap(q, nw) + 2 * overlap(q, aw) + overlap(q, cw) + (hinted.has(name) ? 4 : 0);
    if (sc > 0 && !have.has(name)) scored.push([sc, -name.length, name]);
  }
  scored.sort(cmpDesc);
  names.push(...scored.slice(0, n).map((x) => x[2]));
  const rw = new Set(alphaWords(request.replace(/-/g, " ")));
  const named = MOTION_NAMES.filter((nm) => nm.length > 3 && nm.split("_").every((p) => rw.has(p)) && !CORE_SET.has(nm) &&
    nm.split("_").length >= 2);
  if (named.length) {
    const namedSet = new Set(named);
    return "Motions NAMED in the request - use them for those steps:\n" + named.map((nm) => CATALOG[nm]).join("\n") +
      "\n\nOther motions:\n" + names.filter((nm) => !namedSet.has(nm)).map((nm) => CATALOG[nm]).join("\n");
  }
  return names.map((nm) => CATALOG[nm]).join("\n");
}

export function scriptInstructions(request = "") {
  return `
You turn a coaching request into a short animation script for a 3D athlete, built from a database
of stored, high-quality motions. You decide WHAT the athlete does; the motions already know HOW.

Fill the fields in order:
1. canonical_name: the core movement or drill in 2-6 words.
2. steps: what the athlete does, in order, as 1-8 plain steps (e.g. "sprint forward", "touch the cone
   with the right hand", "backpedal to the start"). Drop story, setting and chatter.
3. title, coaching_cues (3-5 short cues for a right-handed athlete), camera_view (side for forward/back
   motion and swimming, front for side-to-side motion, three_quarter otherwise).
4. script: the steps written in the motion language below.

THE MOTION LANGUAGE
- Each line lists motions from the CATALOG: name or name(param=value, ...). Use ONLY exact catalog
  names. A FULL BODY motion needs nothing else on its line.
- Motions joined with + on ONE line play at the SAME time. The next line starts when the line before
  it ends (the engine blends between lines).
- Each motion drives only some body parts (listed in the catalog). Build a full-body skill by putting
  a lower-body motion (stance, fighting_stance, run, stride_step, jump ...) on the same line as an
  upper-body motion (forehand, guard, jab, shoot ...). Two motions that both DRIVE the same part
  cannot share a line; "soft" parts simply give way.
- Parts that nothing drives on a line keep their previous pose, but it is clearer to repeat held
  motions (e.g. fighting_stance + guard) on every line where they apply.
- Every motion also accepts: side=left (mirror it: shuffle(side=left) moves left, jab is already the
  left hand), speed=0.5..2, times=N (repeat), hold=seconds (hold the end), delay=seconds (start later
  than the rest of its line - e.g. jump + shoot(delay=0.35)).
- Add " x3" at the end of a line to repeat the whole line. A final line "loop" makes the clip loop
  (continuous drills: running, swimming, skipping, shuffles).
- The athlete is right-handed (the engine mirrors everything for left-handers).
- Motions already contain their natural supporting action as SOFT parts: soccer_kick has calm balance
  arms, run pumps the arms, jump swings the arms, stance leans the trunk. Do NOT add an arm motion on
  top of a kick, run or jump unless the request needs a specific arm action (guard, dribble, shoot,
  carrying, hands high). Never add arms_out / arms_overhead just for balance.
- Many actions contain their own starting position (start_dive begins crouched on the block,
  sprint_start begins in the blocks, three_point_stance, catcher_crouch ...). Do not put a separate
  setup or "stand" line before or with them, and never put a pose on the same line as a motion that
  drives the same body parts.
- Start straight into the movement (a short ready stance is fine before a sport skill). Never insert
  a pose from a different activity (no plank before swimming, no stance before a swim stroke).
- Use the fewest motions that show the request; usually 1-5 lines and under 8 seconds. For a drill
  that is not in the catalog, chain catalog motions that match its steps.

Syntax examples:
stance(width=wide, depth=0.5) + ready_arms
stance(width=wide, depth=0.5) + forehand
run(pace=sprint, times=2)

The script field holds ONLY script lines: no notes, comments, explanations or invented names. If no
catalog motion fits a step, leave that step out or use the closest catalog motion. When the catalog has
a motion named for the requested skill (discus_spin, pole_vault, sit_spin, fencing_lunge ...), use it.

CATALOG - the basic building blocks plus the database motions that match this request
(name(params) [kind a=action c=cycle p=pose; body parts it drives] description):
${relevantCatalog(request)}
`.trim();
}

// ---------------------------------------------------------------------------
// Instant scripts without the model
// ---------------------------------------------------------------------------
const words3 = (text) => alphaWords(text).filter((w) => w.length > 2);
const FILLER = new Set(["basketball", "soccer", "football", "tennis", "baseball", "softball", "volleyball", "swimming",
  "swim", "cricket", "rugby", "golf", "hockey", "track", "a", "the", "proper", "basic", "simple",
  "technique", "drill", "practice", "form", "position", "from", "line", "on", "at", "in", "place",
  "during", "side", "underwater", "properly", "correctly", "how", "to", "do"]);
const titleCase = (s) => s.replace(/[A-Za-z]+/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase());
const SIDE_VIEW = new Set(["freestyle", "breaststroke", "butterfly", "backstroke", "push_up", "plank", "mountain_climbers"]);

export function localScript(movement) {
  const text = words3(movement).join(" ");
  let alias = ALIASES.get(text) || ALIASES.get(text.replace(/s+$/, ""));
  if (!alias) {
    const words = text.split(" ").filter(Boolean);
    let bestKey = null, anyKey = null;
    for (const key of ALIASES.keys()) {
      const kw = key.split(/\s+/).filter(Boolean);
      if (kw.length < 2 || kw.length > words.length) continue;
      for (let i = 0; i <= words.length - kw.length; i++) {
        let eq = true;
        for (let j = 0; j < kw.length; j++) if (words[i + j] !== kw[j]) { eq = false; break; }
        if (!eq) continue;
        if (anyKey === null || kw.length > anyKey.split(/\s+/).filter(Boolean).length) anyKey = key;
        const extra = words.filter((w, j) => !(i <= j && j < i + kw.length));
        if (extra.filter((w) => !FILLER.has(w)).length <= 1 &&
          (bestKey === null || kw.length > bestKey.split(/\s+/).filter(Boolean).length)) bestKey = key;
      }
    }
    alias = bestKey ? ALIASES.get(bestKey) : undefined;
    if (!alias && anyKey) {
      return { canonical_name: anyKey, steps: [], title: movement.trim().slice(0, 60), coaching_cues: [],
        camera_view: "three_quarter", script: ALIASES.get(anyKey), exact: false };
    }
  }
  if (alias) {
    return { canonical_name: text, steps: [], title: titleCase(text), coaching_cues: [], camera_view: "three_quarter",
      script: alias, exact: true };
  }
  const textWords = text.split(" ").filter(Boolean);
  const textWordSet = new Set(textWords);
  let best = null, score = 0;
  for (const name of MOTION_NAMES) {
    const m = MOTIONS[name];
    const names = [name.replace(/_/g, " ")];
    if (names.includes(text)) { best = name; score = 99; break; }
    let sc = 0;
    for (const nm of names) {
      const nw = nm.split(/\s+/).filter(Boolean);
      const hits = nw.filter((w) => textWordSet.has(w) || text.includes(w.replace(/s+$/, ""))).length;
      sc = Math.max(sc, (3 * hits) / nw.length);
    }
    sc += (0.5 * overlap(new Set(words3(m.comment)), textWordSet)) / Math.max(3, textWords.length);
    if (sc > score) { best = name; score = sc; }
  }
  if (best === null || score < 1.5) return null;
  const m = MOTIONS[best];
  const lower = m.parts.some((p) => p === "right_leg" || p === "left_leg" || p === "body");
  const item = best + (m.kind === "cycle" ? "(times=2)" : "");
  let script;
  if (lower) script = item;
  else if (m.parts.some((p) => p === "right_arm" || p === "left_arm") && ["jab", "cross", "hook", "uppercut"].includes(best)) {
    script = `fighting_stance + guard\nfighting_stance + guard + ${item}`;
  } else {
    script = `stance(depth=0.3) + ready_arms\nstance(depth=0.3) + ${item}`;
  }
  return { canonical_name: best.replace(/_/g, " "), steps: [m.comment], title: titleCase(best.replace(/_/g, " ")),
    coaching_cues: [], camera_view: m.parts.length && m.parts.includes("body") && SIDE_VIEW.has(best) ? "side" : "three_quarter",
    script, exact: score >= 99 };
}

// ---------------------------------------------------------------------------
// The model call (OpenAI Responses API, structured output)
// ---------------------------------------------------------------------------
export async function callModel(env, instructions, input, { effort, schema, name, maxTokens, timeoutMs }) {
  if (!env.OPENAI_API_KEY) {
    const e = new Error("OPENAI_API_KEY is not configured for the motion service.");
    e.status = 503;
    throw e;
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), Math.max(500, timeoutMs));
  const t0 = Date.now();
  try {
    const resp = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      signal: ctrl.signal,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${env.OPENAI_API_KEY}` },
      body: JSON.stringify({
        model: MODEL,
        instructions,
        input,
        reasoning: { effort },
        store: false,
        text: { format: { type: "json_schema", name, strict: true, schema } },
        max_output_tokens: maxTokens,
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(`OpenAI HTTP ${resp.status}: ${(data.error && data.error.message || "").slice(0, 160)}`);
    if (data.status === "incomplete") throw new Error(`Model output incomplete: ${JSON.stringify(data.incomplete_details)}`);
    let text = data.output_text || "";
    if (!text) {
      for (const item of data.output || []) {
        if (item.type !== "message") continue;
        for (const c of item.content || []) if (c.type === "output_text") text += c.text;
      }
    }
    const usage = data.usage || {};
    return [JSON.parse(text.trim()), { seconds: Math.round((Date.now() - t0) / 100) / 10,
      input_tokens: usage.input_tokens ?? null, output_tokens: usage.output_tokens ?? null }];
  } finally {
    clearTimeout(timer);
  }
}

const SCRIPT_EFFORT = "minimal";
const SCRIPT_TIMEOUT_S = 9;

/** Text -> motion script in ONE fast model call; a local database match answers when the model fails. */
export async function planScript(env, movement, extra = "") {
  const t0 = Date.now();
  const elapsed = () => (Date.now() - t0) / 1000;
  const local = localScript(movement);
  if (local && local.exact && !extra.trim()) {
    return [local, [{ stage: "local", seconds: Math.round(elapsed() * 100) / 100, script: local.script }]];
  }
  let request = `Request: ${movement.trim()}` + (extra.trim() ? `\nNotes: ${extra.trim()}` : "");
  const hints = relevantRecipes(movement + " " + extra);
  if (hints.length) request += "\n\nMost relevant recipes for this request (adapt them):\n" + hints.join("\n");
  const timeout = Number(env.MOTION_SCRIPT_TIMEOUT || SCRIPT_TIMEOUT_S);
  let lastExc = null;
  for (let attempt = 0; attempt < 2; attempt++) {
    const budget = timeout - elapsed();
    if (attempt && budget < 4) break;
    try {
      const [raw, meta] = await callModel(env, scriptInstructions(movement + " " + extra), request, {
        effort: SCRIPT_EFFORT, schema: SCRIPT_SCHEMA, name: "motion_script", maxTokens: 3000, timeoutMs: budget * 1000,
      });
      compileScript(raw.script || "", { validateOnly: true });   // lenient: only fails if nothing usable is left
      return [raw, [{ stage: attempt ? "script-retry" : "script", ...meta, script: raw.script }]];
    } catch (exc) {
      if (exc.status === 503) throw exc;
      lastExc = exc;
    }
  }
  const fallback = local || { canonical_name: "stance", steps: [], title: movement.trim().slice(0, 60), coaching_cues: [],
    camera_view: "three_quarter", script: "stance(depth=0.3) + ready_arms" };
  const reason = lastExc ? `${lastExc.name === "AbortError" ? "Timeout" : lastExc.name}: ${String(lastExc.message).slice(0, 120)}` : "no time left";
  return [fallback, [{ stage: "local-fallback", seconds: Math.round(elapsed() * 10) / 10, reason, script: fallback.script }]];
}

// ---------------------------------------------------------------------------
// Responses
// ---------------------------------------------------------------------------
export function mirrorText(text) {
  return String(text).replace(/\b(left|right)\b/gi, (word) => {
    const out = word.toLowerCase() === "left" ? "right" : "left";
    if (word === word.toUpperCase()) return out.toUpperCase();
    return word[0] === word[0].toUpperCase() ? out[0].toUpperCase() + out.slice(1) : out;
  });
}

export function sparse(frames) {
  return frames.map((f) => {
    const s = {};
    for (const k in f) {
      const v = f[k];
      if (k.startsWith("_")) continue;
      if (Math.abs(v) >= SPARSE_EPS_DEG || (k === "rooty" && Math.abs(v) >= 0.001)) s[k] = v;
    }
    return s;
  });
}

export function scriptResponse(env, raw, side, calls, cached) {
  const compiled = compileScript(raw.script || "", { dominantSide: side });
  const text = side === "left" ? mirrorText : (t) => t;
  return {
    frames: sparse(compiled.frames),
    playback_fps: compiled.fps,
    duration_seconds: compiled.duration_seconds,
    loop: compiled.loop,
    camera_view: VIEWS.includes(raw.camera_view) ? raw.camera_view : "three_quarter",
    ground: compiled.ground,
    dominant_side: side,
    title: text(raw.title || ""),
    movement_summary: (raw.steps || []).join("; "),
    coaching_cues: (raw.coaching_cues || []).map(text),
    script: raw.script || "",
    plan: { script: raw.script || "", steps: raw.steps ?? null, lines: compiled.lines },
    report: { ...compiled.report, playback_time_scale: 1.0 },
    model: MODEL,
    llm_calls: calls,
    cached,
    engine_version: ENGINE_VERSION,
  };
}

export { ScriptError };

// Warm-up at module load (Worker start-up time, not request CPU time): build the retrieval indexes
// and let the JIT see the hot paths once, so a request's CPU stays well under the free plan's 10 ms.
export function warmUp() {
  catalogIndex();
  scriptInstructions("warm up sprint and backpedal then jump shot and tennis forehand");
  localScript("zig zag cone drill with a crossover dribble");
  compileScript("stance(width=wide, depth=0.5) + forehand\nfighting_stance + guard + jab x2\nrun(pace=sprint)", { validateOnly: true });
}
