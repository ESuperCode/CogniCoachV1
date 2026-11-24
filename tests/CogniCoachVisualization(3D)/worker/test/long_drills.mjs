// Sends long drill descriptions through the real model (planScript) and compiles them. Prints script + per-line motions.
import { build } from "esbuild";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
const here = path.dirname(fileURLToPath(import.meta.url));
await build({ entryPoints: [path.join(here, "entry.mjs")], bundle: true, platform: "node", format: "esm", outfile: path.join(here, ".bundle.mjs"), logLevel: "error" });
const E = await import(pathToFileURL(path.join(here, ".bundle.mjs")).href + "?" + Date.now());
E.warmUp();
const drills = readFileSync(process.argv[2] || path.join(here, "long_drills.txt"), "utf8").split("\n").filter((l) => l.trim());
const strip = process.argv.includes("--strip");
for (const d of drills) {
  const text = strip ? E.drillMotionText ? E.drillMotionText(d) : d : d;
  const t0 = Date.now();
  const [raw, calls] = await E.planScript({ OPENAI_API_KEY: "sk-proxy-injected" }, text);
  const secs = ((Date.now() - t0) / 1000).toFixed(1);
  const r = E._c(raw.script, {});
  console.log(`\n=== ${secs}s ${calls[0].stage}${calls[0].reason ? " " + calls[0].reason : ""} | ${r.duration_seconds}s clip | ${d.slice(0, 80)}...`);
  console.log("steps:", JSON.stringify(raw.steps));
  console.log("script:\n  " + raw.script.split("\n").join("\n  "));
  if (r.report.warnings.length) console.log("warnings:", r.report.warnings);
  if (r.report.issues.length) console.log("ISSUES:", r.report.issues);
}
