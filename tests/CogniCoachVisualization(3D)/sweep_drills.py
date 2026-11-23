"""Run invented coaching drills through the real pipeline (model + compiler) and report time, the script
and any warnings / issues per drill. Use it after changing the database, the prompt or the compiler.

    python sweep_drills.py                   # the built-in drill list
    python sweep_drills.py my_drills.txt     # one drill per line
    python sweep_drills.py --workers 2       # parallel requests (keep low: 6+ slows the API down)

Needs OPENAI_API_KEY (or the environment's proxy credential). Writes sweep_results.json.
"""
import json
import statistics
import sys
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

warnings.filterwarnings("ignore")
import motion_database as db  # noqa: E402
import motion_engine as engine  # noqa: E402
import motion_script as ms  # noqa: E402

DRILLS = """
Closeout drill: sprint toward the shooter, chop your feet, then close out with one hand high
Defensive slide 3 steps right, drop step, slide 3 steps left
Rebound drill: box out, jump to grab the ball with two hands, chin it
Soccer: receive the ball with the inside of the foot, take a touch, and shoot with the laces
Soccer goalkeeper: set, dive to the left to save a low shot, get up quickly
Tennis split step then shuffle to the right and hit a forehand
Tennis serve: toss, trophy position, swing up and pronate, land inside the court
Football QB 3-step drop and throw
Football lineman: three-point stance, explode forward and punch with both hands
Baseball infielder fields a ground ball and throws to first
Baseball hitter load, stride and swing then run to first
Volleyball approach and spike with a 4-step approach
Volleyball blocker shuffles along the net then jumps to block
Swimming: freestyle with bilateral breathing every three strokes
Cricket fast bowler run-up and delivery
Rugby tackle technique: drop low, shoulder contact, wrap arms, drive legs
Golf chip shot with a short backswing
Burpee to tuck jump
Star drill: from the center cone, sprint forward, backpedal back, shuffle right, shuffle left
Euro step layup from the wing
Yoga flow: mountain pose, forward fold, plank, cobra, downward dog
Cooldown: hamstring stretch, quad stretch on each leg, then child's pose
hockey goalie butterfly save then recover to stance
taekwondo spinning hook kick
kayak forward stroke
""".strip().splitlines()


def run(prompt):
    t = time.time()
    try:
        raw, calls = engine.plan_script(prompt)
        r = ms.compile_script(raw["script"], db.DB)
        return {"prompt": prompt, "seconds": round(time.time() - t, 1), "stage": calls[-1].get("stage"), "script": raw["script"],
                "warnings": r["report"].get("warnings", []), "issues": r["report"]["issues"]}
    except Exception as exc:
        return {"prompt": prompt, "seconds": round(time.time() - t, 1), "error": repr(exc)[:300]}


def main():
    args = sys.argv[1:]
    workers = 2
    if "--workers" in args:
        i = args.index("--workers")
        workers = int(args[i + 1])
        del args[i:i + 2]
    drills = [l.strip() for l in open(args[0]) if l.strip()] if args else DRILLS
    with ThreadPoolExecutor(workers) as ex:
        results = list(ex.map(run, drills))
    for r in results:
        print(f"\n### {r['prompt']}  [{r['seconds']} s, {r.get('stage', 'error')}]")
        if "error" in r:
            print("ERROR", r["error"])
            continue
        print(r["script"])
        for w in r["warnings"]:
            print("  warning:", w)
        for i in r["issues"]:
            print("  ISSUE:", i)
    model = [r["seconds"] for r in results if r.get("stage") not in (None, "local")]
    print(f"\n{len(results)} drills | {sum('error' in r for r in results)} errors | "
          f"{sum(bool(r.get('issues')) for r in results)} with issues | model requests: {len(model)}"
          + (f", mean {statistics.mean(model):.1f} s, max {max(model):.1f} s" if model else ""))
    json.dump(results, open("sweep_results.json", "w"), indent=1)


if __name__ == "__main__":
    main()
