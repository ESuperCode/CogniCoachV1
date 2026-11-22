"""
Sport coverage map: every movement used in competition, practice and warm-ups for ten sports,
written as a motion script over the GENERAL motions in motion_database.py. Each phrase is also an
instant request (no model call). Check / regenerate the readable table with:
    python sport_coverage.py            (compiles every entry and writes SPORT_COVERAGE.md)
"""

WARMUPS = {
    "jog": "run(pace=jog, times=3)", "high knees": "high_knees(times=4)", "butt kicks": "butt_kicks(times=4)",
    "a skips": "a_skip(times=3)", "b skips": "b_skip(times=3)", "carioca": "carioca(times=2)",
    "lateral shuffle": "shuffle(times=3)", "backpedal": "backpedal(times=4)", "strides": "run(times=3)",
    "leg swings": "leg_swing(times=3)", "lateral leg swings": "lateral_leg_swing(times=3)",
    "walking lunges": "lunge\nlunge(side=left)", "side lunges": "lateral_lunge\nlateral_lunge(side=left)",
    "knee hugs": "knee_hug\nknee_hug(side=left)", "straight leg kicks": "straight_leg_kick(times=2)",
    "inchworms": "inchworm", "hip circles": "hip_circles(times=2)", "arm circles": "stance(depth=0.1) + arm_circles(times=3)",
    "arm swings": "stance(depth=0.1) + arm_swings(times=3)", "torso twists": "stance(depth=0.1) + torso_twist(times=2)",
    "neck rolls": "stand + neck_rolls", "jumping jacks": "jumping_jack(times=3)", "pogo hops": "pogo_hops(times=6)",
    "jump rope": "jump_rope(times=6)", "squats": "squat\nsquat", "push ups": "push_up(times=2)",
    "plank": "plank(hold=2)", "hamstring stretch": "hamstring_stretch(hold=2)", "quad stretch": "quad_stretch(hold=2)",
    "shoulder stretch": "stand + arm_cross_stretch(hold=2)", "calf raises": "calf_raise(times=3)",
}

COVERAGE = {
    "Basketball": {
        "triple threat": "stance(depth=0.5) + ball_hold_hip(hold=1)",
        "dribble": "stance(depth=0.4) + hand_dribble(times=4)",
        "crossover dribble": "stance(depth=0.5) + crossover_dribble(times=2)",
        "dribble while running": "run(pace=jog, times=3) + hand_dribble",
        "jump shot": "jump + one_hand_set_shot(delay=0.35)",
        "free throw": "stance(depth=0.3) + one_hand_set_shot",
        "layup": "running_lay_up",
        "hook shot": "stance(depth=0.3) + hook_shot",
        "dunk": "run(times=2)\njump(height=high) + overhead_arm_strike(delay=0.2)",
        "chest pass": "stance(depth=0.3) + chest_pass",
        "bounce pass": "stance(depth=0.3) + bounce_pass",
        "overhead pass": "stance(depth=0.3) + two_hand_overhead_throw",
        "rebound": "jump(height=high) + two_hand_catch_high(delay=0.3)",
        "box out": "box_out(hold=1.5)",
        "defensive stance": "wide_defensive_stance(bounce=on, hold=1.5)",
        "defensive slide": "wide_defensive_stance\nshuffle(times=3)",
        "closeout": "run(times=2)\nstop_and_stick + arms_up_block",
        "block a shot": "jump(height=high) + arms_up_block(delay=0.2)",
        "pivot": "pivot_turn",
        "jab step": "stance(depth=0.5) + ball_hold_hip\njab_step + ball_hold_hip",
        "catch a pass": "stance(depth=0.3) + catch",
        "sprint back on defense": "run(pace=sprint, times=3)",
        "jump stop": "run(times=2)\nstop_and_stick",
    },
    "Soccer": {
        "shot": "instep_kick", "pass": "inside_foot_kick", "outside foot pass": "outside_foot_flick",
        "chip": "chip_kick", "volley": "side_volley_kick", "long ball": "instep_kick",
        "dribble": "foot_dribble(times=3)", "step over": "step_over", "receive with the foot": "foot_trap",
        "chest control": "chest_trap", "header": "head_strike", "jumping header": "jump + head_strike(delay=0.3)",
        "throw-in": "two_hand_overhead_throw", "block tackle": "block_tackle", "shielding the ball": "box_out(hold=1)",
        "goalkeeper ready stance": "stance(width=wide, depth=0.6, bounce=on) + ready_arms(hold=1)",
        "goalkeeper dive": "side_dive", "goalkeeper high catch": "jump + two_hand_catch_high(delay=0.25)",
        "goalkeeper scoop": "low_scoop", "goal kick": "instep_kick", "goalkeeper punt": "punt_kick",
        "sprint": "run(pace=sprint, times=3)", "cut": "cutting_step", "jockeying": "wide_defensive_stance\nbackpedal(times=3)",
    },
    "Tennis": {
        "forehand": "stance(width=wide, depth=0.4) + forehand_swing",
        "two-handed backhand": "stance(width=wide, depth=0.4) + two_hand_backhand",
        "one-handed backhand": "stance(width=wide, depth=0.4) + one_hand_backhand",
        "serve": "jumping_overhead_serve", "forehand volley": "stance(width=wide, depth=0.4) + punch_volley",
        "backhand volley": "stance(width=wide, depth=0.4) + backhand_block",
        "overhead smash": "stance(width=wide, depth=0.3) + overhead_arm_strike",
        "split step": "split_step", "ready position": "stance(width=wide, depth=0.5, bounce=on) + ready_arms(hold=1)",
        "side shuffle recovery": "shuffle(times=3) + ready_arms", "lunge to reach": "lateral_lunge + ready_arms",
    },
    "Football": {
        "three-point stance": "three_point_stance(hold=1.5)", "snap": "center_snap", "quarterback drop back": "backpedal(times=3) + ball_carry",
        "throw a pass": "stride_step + overhand_throw(delay=0.2)", "handoff": "stance(depth=0.3) + handoff",
        "catch": "stance(depth=0.3) + catch", "over the shoulder catch": "run(times=2) + over_shoulder_catch",
        "carry the ball": "run(times=3) + ball_carry", "stiff arm": "run(times=2) + ball_carry + stiff_arm",
        "juke / cut": "cutting_step + ball_carry", "spin move": "pivot_turn(deg=270) + ball_carry", "tackle": "form_tackle",
        "block": "push_block", "kickoff": "run(times=2)\ninstep_kick", "punt": "punt_kick", "field goal": "instep_kick",
        "backpedal coverage": "backpedal(times=4)", "linebacker stance": "wide_defensive_stance(hold=1)",
    },
    "Baseball": {
        "batting stance and swing": "stance(width=wide, depth=0.3) + level_two_hand_swing", "bunt": "stance(width=wide, depth=0.4) + bunt",
        "pitch": "stride_step + overhand_throw(delay=0.25)", "throw": "stride_step + overhand_throw(delay=0.2)",
        "field a ground ball": "low_scoop", "catch a fly ball": "stance(depth=0.2) + two_hand_catch_high",
        "catcher stance": "catcher_crouch(hold=1.5)", "slide into base": "run(times=2)\nfeet_first_slide",
        "base running": "run(pace=sprint, times=3)", "leading off": "wide_defensive_stance\nshuffle(times=2)",
        "softball windmill pitch": "stance(depth=0.3) + windmill_throw",
    },
    "Volleyball": {
        "ready position": "stance(width=wide, depth=0.6) + ready_arms(hold=1)", "forearm pass": "stance(width=wide, depth=0.6) + forearm_platform",
        "set": "stance(depth=0.3) + overhead_two_hand_set", "spike": "run(times=1)\njump(height=high) + overhead_arm_strike(delay=0.1)",
        "block": "jump + arms_up_block", "underhand serve": "stance(depth=0.2) + underhand_serve",
        "overhand serve": "stance(depth=0.2) + overhead_arm_strike", "jump serve": "jumping_overhead_serve",
        "dig": "lateral_lunge + forearm_platform", "dive for the ball": "side_dive", "approach steps": "stride_step\njump(height=high)",
    },
    "Swimming": {
        "freestyle": "front_crawl(times=2)\nloop", "backstroke": "back_crawl(times=2)\nloop",
        "breaststroke": "breaststroke(times=2)\nloop", "butterfly": "butterfly_stroke(times=2)\nloop",
        "streamline": "streamline(hold=2)", "flutter kick": "flutter_kick(times=4)", "dolphin kick": "dolphin_kick(times=4)",
        "flip turn": "front_crawl\nflip_turn", "start dive": "start_dive", "treading water": "tread_water(times=3)",
        "streamline stretch": "stand + arms_overhead(hold=2)",
    },
    "Cricket": {
        "bowling": "run(times=2)\nstraight_arm_bowl", "forward defense": "forward_defense", "drive": "stance(width=wide, depth=0.3) + vertical_two_hand_swing",
        "pull shot": "stance(width=wide, depth=0.3) + level_two_hand_swing", "wicket keeping": "catcher_crouch(hold=1.5)",
        "field and throw": "low_scoop\nstride_step + overhand_throw(delay=0.2)", "catch high": "stance(depth=0.2) + two_hand_catch_high",
        "diving catch": "side_dive", "run between wickets": "run(pace=sprint, times=3)",
    },
    "Rugby": {
        "pass": "run(times=2) + ball_carry\nstance(depth=0.3) + two_hand_side_pass", "catch": "stance(depth=0.3) + catch",
        "carry": "run(times=3) + ball_carry", "fend": "run(times=2) + ball_carry + stiff_arm", "side step": "cutting_step + ball_carry",
        "tackle": "form_tackle", "ruck / maul / scrum drive": "bent_over_drive(times=3)", "lineout throw": "stance(depth=0.2) + two_hand_overhead_throw",
        "lineout jump": "jump(height=high) + arms_up_block(delay=0.2)", "place kick": "instep_kick", "drop kick": "punt_kick", "box kick": "punt_kick",
    },
    "Golf": {
        "full swing": "stance(width=wide, depth=0.2) + low_two_hand_swing", "chip": "stance(width=normal, depth=0.2) + chip_swing",
        "putt": "stance(width=normal, depth=0.2) + putt", "address": "stance(width=wide, depth=0.2) + low_two_hand_swing(end=0.01, hold=1)",
        "tee up the ball": "touch_low", "practice swing": "stance(width=wide, depth=0.2) + low_two_hand_swing",
        "golf warm-up rotation": "stance(depth=0.1) + torso_twist(times=2)",
    },
}


def all_entries():
    for sport, moves in COVERAGE.items():
        for phrase, script in moves.items():
            yield sport, phrase, script
    for phrase, script in WARMUPS.items():
        yield "Warm-ups (all sports)", phrase, script


if __name__ == "__main__":
    import warnings
    warnings.filterwarnings("ignore")
    import motion_database as db
    import motion_script as ms
    rows, bad = [], []
    for sport, phrase, script in all_entries():
        try:
            r = ms.compile_script(script, db.DB, strict=True)
            rows.append((sport, phrase, script, r["duration_seconds"], r["report"]["issues"]))
        except ms.ScriptError as e:
            bad.append((sport, phrase, str(e)))
    out = ["# Sport coverage", "", "Every movement below is produced from the general motions in `motion_database.py`.",
           "Each phrase is also an instant request (no model call). Regenerate: `python sport_coverage.py`.", ""]
    cur = None
    for sport, phrase, script, dur, issues in rows:
        if sport != cur:
            out += ["", f"## {sport}", "", "| Movement | Script | Seconds |", "|---|---|---|"]
            cur = sport
        out.append(f"| {phrase} | `{script.replace(chr(10), ' / ')}` | {dur} |")
    open("SPORT_COVERAGE.md", "w").write("\n".join(out) + "\n")
    print(f"{len(rows)} movements compile, {len(bad)} fail")
    for b in bad:
        print("FAIL", b)
