// Compares the JS port with the Python engine on test/reference.json (make it with
// `python test/make_reference.py` from this folder's parent), and times the compiler.
//   node test/run_tests.mjs
import { build } from "esbuild";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, ".bundle.mjs");
await build({ entryPoints: [path.join(here, "entry.mjs")], bundle: true, platform: "node", format: "esm", outfile: out, logLevel: "error" });
const E = await import(pathToFileURL(out).href + "?" + Date.now());

const refPath = path.join(here, "reference.json");
let failures = 0;
if (existsSync(refPath)) {
  const ref = JSON.parse(readFileSync(refPath, "utf8"));
  let worst = 0, worstWhere = "", compared = 0;
  for (const c of ref.compiles) {
    let r, err = null;
    try { r = E.compileScript(c.script, { dominantSide: c.side }); } catch (e) { err = e; }
    if (c.error || err) {
      if (!(c.error && err && err.message === c.error)) {
        failures++;
        console.log("ERROR MISMATCH", JSON.stringify(c.script), c.side, "py:", c.error, "js:", err && err.message);
      }
      continue;
    }
    const jf = E.sparse(r.frames);
    if (jf.length !== c.frames.length) { failures++; console.log("FRAME COUNT", JSON.stringify(c.script), c.side, jf.length, c.frames.length); continue; }
    for (let i = 0; i < jf.length; i++) {
      const keys = new Set([...Object.keys(jf[i]), ...Object.keys(c.frames[i])]);
      for (const k of keys) {
        const a = jf[i][k] || 0, b = c.frames[i][k] || 0;
        let d = Math.abs(a - b);
        if (!k.startsWith("position") && k !== "rooty") d = Math.min(d, Math.abs(((a - b) % 360 + 540) % 360 - 180));
        if (d > worst) { worst = d; worstWhere = `${JSON.stringify(c.script)} ${c.side} frame ${i} ${k}: js ${a} py ${b}`; }
      }
    }
    compared++;
    const same = JSON.stringify(r.report.warnings) === JSON.stringify(c.report.warnings) && r.ground === c.ground &&
      r.loop === c.loop && JSON.stringify(r.lines) === JSON.stringify(c.lines) && JSON.stringify(r.report.issues) === JSON.stringify(c.report.issues);
    if (!same) {
      failures++;
      console.log("META MISMATCH", JSON.stringify(c.script), c.side);
      console.log("  js:", JSON.stringify({ w: r.report.warnings, g: r.ground, l: r.lines, i: r.report.issues }).slice(0, 600));
      console.log("  py:", JSON.stringify({ w: c.report.warnings, g: c.ground, l: c.lines, i: c.report.issues }).slice(0, 600));
    }
  }
  console.log(`compiled ${compared} scripts; largest frame difference ${worst.toFixed(3)} (${worstWhere})`);
  if (worst > 0.5) failures++;
  for (const q of ref.local) {
    const loc = E.localScript(q.req);
    const checks = [["local", JSON.stringify(loc) === JSON.stringify(q.local)], ["catalog", E.relevantCatalog(q.req + " ") === q.catalog],
      ["recipes", JSON.stringify(E.relevantRecipes(q.req + " ")) === JSON.stringify(q.recipes)],
      ["instructions", E.scriptInstructions(q.req + " ") === q.instructions]];
    for (const [what, ok] of checks) if (!ok) { failures++; console.log(`REQUEST MISMATCH ${what}: ${q.req}`); if (what === "local") console.log(" js", JSON.stringify(loc), "\n py", JSON.stringify(q.local)); }
  }
  console.log(`checked ${ref.local.length} requests (instant phrases, catalog retrieval, recipes, prompt)`);
} else {
  console.log("no test/reference.json - run: python worker/test/make_reference.py (from the 3D folder)");
}

// timing (CPU budget on the Workers free plan is tight: keep compiles fast)
const timing = ["stance(width=wide, depth=0.5) + forehand\nfighting_stance + guard + jab", "run(pace=sprint, times=3)",
  "stance + ready_arms\nshuffle(times=3)\nrun(pace=sprint)\nbackpedal(times=2)\njump + shoot(delay=0.35)"];
for (const s of timing) {
  E.compileScript(s);
  const t0 = performance.now();
  const n = 10;
  let r;
  for (let i = 0; i < n; i++) r = E.compileScript(s);
  console.log(`compile ${((performance.now() - t0) / n).toFixed(1)} ms for ${r.frames.length} frames: ${JSON.stringify(s).slice(0, 60)}`);
}
console.log(failures ? `FAILED (${failures})` : "ALL PASSED");
process.exit(failures ? 1 : 0);
