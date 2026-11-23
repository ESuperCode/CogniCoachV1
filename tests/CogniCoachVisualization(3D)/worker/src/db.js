// The motion database, exported from motion_database.py by export_worker_data.py.
// Every motion is stored pre-built for each parameter value it accepts; number parameters are
// stored on a fine grid and a request snaps to the nearest grid value.
import DATA from "./data/motion_data.json";

export const ENGINE_DATA_VERSION = DATA.engine_version;
export const MOTIONS = DATA.motions;            // name -> {comment, kind, parts, soft, params, variants, ...}
export const MOTION_NAMES = DATA.order;         // database order (the first ones are the core building blocks)
export const CATALOG = DATA.catalog;            // name -> catalog line shown to the model
export const ALIASES = new Map(DATA.aliases);   // instant phrase -> script (insertion order kept)
export const NAME_ALIASES = DATA.name_aliases;  // names the model writes that are not database names
export const RECIPES = DATA.recipes;            // [sport, phrase, script]
export const NEUTRAL = DATA.neutral;

export function hasMotion(name) {
  return Object.prototype.hasOwnProperty.call(MOTIONS, name);
}

function fmt(v) {
  if (typeof v === "number") {
    if (Number.isInteger(v)) return String(v);
    return v.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  }
  return String(v);
}

// Keys of a motion for its own (non-generic) parameters: [[t, {part: {param: value}}, hold?], ...]
// plus the cycle period when the motion defines one.
export function buildKeys(name, own) {
  const m = MOTIONS[name];
  const given = Object.keys(own);
  if (!given.length) return m.variants[""];
  const full = {};
  for (const [p, spec] of Object.entries(m.params)) {
    let v = p in own ? own[p] : spec.default;
    if (spec.range) {
      const step = spec.step;
      v = Math.min(spec.range[1], Math.max(spec.range[0], Number(v)));
      v = spec.range[0] + Math.round((v - spec.range[0]) / step) * step;
      v = Number.isInteger(step) ? Math.round(v) : Math.round(v * 10000) / 10000;
    }
    full[p] = v;
  }
  const key = Object.keys(full).sort().map((k) => `${k}=${fmt(full[k])}`).join(",");
  return m.variants[key] || m.variants[""];
}
