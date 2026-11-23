"""Compile a sample of scripts with the Python engine (reference for the JS port): test/reference.json"""
import json, os, random, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", ".."))
import motion_database as mdb, motion_script as ms, motion_engine as me

random.seed(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
n = int(sys.argv[2]) if len(sys.argv) > 2 else 120
scripts = ["stance(width=wide, depth=0.5) + forehand\nfighting_stance + guard + jab", "stance + run", "lunge + jump",
           "turn(deg=135)\npivot_turn(deg=-90)", "squat(depth=0.73)", "stance(depth=0.33, bounce=on) + ready_arms",
           "jmp + shot(delay=0.35)", "run(pace=sprint, times=9) x3", "nonsense_motion + jab", "plank\npush_up(times=2)",
           "stance + hold=0.5 + ready_arms", "freestyle loop", "sprint = run(pace=sprint)", "jump + shoot(delay=0.35); stand"]
scripts += random.sample([s for s in mdb.ALIASES.values()], n)
scripts += [f"{name}" for name in random.sample(list(mdb.DB), 40)]
out = []
for s in scripts:
    for side in ("right", "left"):
        try:
            r = ms.compile_script(s, mdb.DB, dominant_side=side)
            out.append({"script": s, "side": side, "frames": me.sparse(r["frames"]), "lines": r["lines"],
                        "report": r["report"], "ground": r["ground"], "loop": r["loop"]})
        except ms.ScriptError as e:
            out.append({"script": s, "side": side, "error": str(e)})
# local_script / retrieval references
reqs = ["tennis forehand", "soccer penalty kick", "a proper golf putt", "cricket straight drive", "euro step layup drill",
        "turkish get up", "sprint then backpedal and touch the cone", "zig zag cone drill with crossover dribble", "jab cross",
        "pushups", "front crawl swimming", "goalkeeper diving save", "hammer throw spin", "salsa basic step"]
loc = [{"req": q, "local": me.local_script(q), "catalog": me.relevant_catalog(q + " "), "recipes": me.relevant_recipes(q + " "),
        "instructions": me.script_instructions(q + " ")} for q in reqs]
json.dump({"compiles": out, "local": loc}, open(os.path.join(HERE, "reference.json"), "w"))
print(len(out), "compiles,", len(loc), "requests")
