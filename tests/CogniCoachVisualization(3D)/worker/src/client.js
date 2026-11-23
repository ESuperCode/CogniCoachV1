// Browser build of the compiler (dist/motion-compiler.js): window.CogniCoachMotion.
// The viewer gets the plan (script, title, cues) from the Worker and compiles the frames here.
import { ENGINE_VERSION, scriptResponse } from "./engine.js";
import { ScriptError, compileScript } from "./script.js";

export { ENGINE_VERSION, ScriptError, compileScript };

/** Plan from /generate (or {script, title}) -> the same response motion_engine.py's /generate returned. */
export function compilePlan(plan, side = "right") {
  const t0 = performance.now();
  const resp = scriptResponse({}, plan, side === "left" ? "left" : "right", plan.llm_calls || [], !!plan.cached);
  resp.timing = { ...(plan.timing || {}), compile_seconds: Math.round(performance.now() - t0) / 1000 };
  return resp;
}
