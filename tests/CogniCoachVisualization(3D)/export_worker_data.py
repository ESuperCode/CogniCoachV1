"""Export the motion database for the Cloudflare Worker (worker/src/data/motion_data.json).

The Worker cannot run Python, so every motion is built here once for every parameter value it
accepts (word parameters: every choice; number parameters: a fine grid that the Worker snaps to)
and written as plain keyframes, together with the phrases, name aliases, catalog lines and recipes.

    python export_worker_data.py          (run after every motion_database.py / sport_coverage.py change)
"""
from __future__ import annotations

import itertools
import json
import os
import re

import motion_database as md
import motion_engine as me
import motion_script as ms
import sport_coverage as cov

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker", "src", "data", "motion_data.json")

# number parameters -> grid step (the Worker snaps a request to the nearest grid value)
GRID = {("stance", "depth"): 0.01, ("squat", "depth"): 0.01, ("turn", "deg"): 5, ("pivot_turn", "deg"): 5}


def _is_range(allowed) -> bool:
    return isinstance(allowed, tuple) and len(allowed) == 2 and all(isinstance(x, (int, float)) for x in allowed)


def _grid(lo, hi, step):
    n = int(round((hi - lo) / step))
    vals = [round(lo + i * step, 4) for i in range(n + 1)]
    return [int(v) if float(v).is_integer() and isinstance(step, int) else v for v in vals]


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:.4f}".rstrip("0").rstrip(".")
    return str(v)


def variant_key(args: dict) -> str:
    return ",".join(f"{k}={_fmt(args[k])}" for k in sorted(args))


def pack_keys(keys):
    out = []
    for t, kv in keys:   # stored order: the compiler sorts (stable) like motion_script.Track
        parts = {}
        for p, vals in kv.items():
            if p == "_hold":
                continue
            parts[p] = {k: round(float(v), 4) for k, v in vals.items()}
        item = [round(float(t), 4), parts]
        if kv.get("_hold"):
            item.append(1)
        out.append(item)
    return out


def build_variants(name, m):
    variants = {}

    def add(args):
        res = m["build"](**args)
        period = None
        keys = res
        if isinstance(res, dict):
            keys, period = res["keys"], res.get("period")
        entry = {"keys": pack_keys(keys)}
        if period is not None:
            entry["period"] = period
        variants[variant_key(args)] = entry

    add({})
    if not m["params"]:
        return variants
    names = sorted(m["params"])
    choices = []
    for p in names:
        default, allowed = m["params"][p]
        if _is_range(allowed):
            step = GRID.get((name, p))
            if step is None:
                raise SystemExit(f"{name}.{p}: number parameter without a grid in GRID")
            choices.append(_grid(allowed[0], allowed[1], step))
        else:
            choices.append(list(allowed))
    for combo in itertools.product(*choices):
        add(dict(zip(names, combo)))
    return variants


def main():
    motions = {}
    for name, m in md.DB.items():
        params = {}
        for p, (default, allowed) in m["params"].items():
            if _is_range(allowed):
                params[p] = {"default": default, "range": list(allowed), "step": GRID[(name, p)]}
            else:
                params[p] = {"default": default, "choices": list(allowed)}
        entry = {"comment": m["comment"], "kind": m["kind"], "parts": list(m["parts"]),
                 "soft": list(m.get("soft_parts", [])), "params": params, "variants": build_variants(name, m)}
        if m.get("loop_pose"):
            entry["loop_pose"] = True
        if m.get("period"):
            entry["period"] = m["period"]
        motions[name] = entry
    data = {
        "engine_version": me.ENGINE_VERSION,
        "order": list(md.DB),
        "motions": motions,
        "catalog": dict(zip(md.DB, md.catalog_text().split("\n"))),
        "aliases": list(md.ALIASES.items()),
        "name_aliases": md.NAME_ALIASES,
        "recipes": [[s, p, sc] for s, p, sc in cov.all_entries()],
        "neutral": ms.NEUTRAL,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(data, f, separators=(",", ":"))
    md.save_solved()
    print(f"wrote {OUT}: {len(motions)} motions, "
          f"{sum(len(m['variants']) for m in motions.values())} variants, {os.path.getsize(OUT) / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
