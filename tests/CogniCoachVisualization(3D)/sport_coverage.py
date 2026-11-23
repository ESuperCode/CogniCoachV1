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
    "child's pose": "childs_pose(hold=2)", "cat cow": "cat_cow(times=2)", "bird dog": "bird_dog(times=2)",
    "downward dog": "downward_dog(hold=2)", "cobra stretch": "cobra(hold=2)", "forearm plank": "forearm_plank(hold=2)",
    "side plank": "side_plank(hold=2)", "dead bug": "dead_bug(times=2)", "glute bridge": "glute_bridge(times=2)",
    "sit and reach": "seated_forward_fold(hold=2)", "butterfly stretch": "butterfly_stretch(hold=2)",
    "kneeling hip flexor stretch": "hip_flexor_stretch(hold=2)", "half kneeling": "half_kneel(hold=1)",
    "tall kneeling": "kneel(hold=1)", "hands and knees": "table_top(hold=1)", "lying down rest": "lie_on_back(hold=2)",
    "get up off the floor": "get_up_from_floor", "inchworm walkout": "inchworm", "superman hold": "superman(hold=2)",
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
        "bowling": "run(times=2)\nstraight_arm_bowl", "forward defense": "forward_defense", "drive": "vertical_two_hand_swing",
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


POSITIONS = {
    "Football": {"receiver two point stance": "two_point_stance(hold=1)", "lineman four point stance": "four_point_stance(hold=1)",
                 "quarterback under center": "crouch_hands_low(hold=1)", "field goal holder": "one_knee_hands_ready(hold=1)",
                 "fair catch": "stand + one_arm_up(hold=1)", "pass protection set": "pass_block_set(hold=1)",
                 "huddle": "hands_on_knees(hold=1)", "touchdown signal": "stand + arms_overhead(hold=1)"},
    "Basketball": {"post up": "post_up(hold=1)", "denial": "denial_stance(hold=1)", "help side": "help_side_stance(hold=1)",
                   "jump ball": "tip_off_ready(hold=1)", "call for the ball": "stance(depth=0.3) + hands_target(hold=1)"},
    "Soccer": {"goalkeeper set position": "goalkeeper_set(hold=1)", "jockey": "jockey_stance(hold=1)",
               "free kick wall": "defensive_wall(hold=1)", "goal celebration": "jump + arms_overhead\nstand + fist_pump"},
    "Tennis": {"trophy position": "trophy_position(hold=1)", "forehand unit turn": "unit_turn_right(hold=1)",
               "backhand unit turn": "unit_turn_left(hold=1)", "overhead ready": "overhead_ready(hold=1)"},
    "Baseball": {"batting stance": "hitting_stance(hold=1)", "pitcher set position": "set_position(hold=1)",
                 "pitcher leg lift": "balance_point(hold=1)", "infielder ready": "fielder_ready(hold=1)",
                 "first base stretch": "long_stretch_reach(hold=1)", "headfirst slide": "run(times=2)\nprone_reach(hold=1)"},
    "Volleyball": {"blocker ready": "stance(depth=0.4) + hands_up_ready(hold=1)", "dig ready": "platform_ready(hold=1)",
                   "approach load": "jump_load(hold=1)", "pancake save": "side_dive\nprone_reach(hold=1)"},
    "Cricket": {"batting stance": "side_on_batting_stance(hold=1)", "backlift": "backlift(hold=1)",
                "slip catching stance": "slip_catch_stance(hold=1)", "bowling delivery stride": "delivery_stride(hold=1)",
                "umpire out signal": "stand + one_arm_up(hold=1)", "umpire wide signal": "stand + arms_out(hold=1)",
                "umpire six signal": "stand + arms_overhead(hold=1)"},
    "Rugby": {"lineout lifter": "overhead_lift_hold(hold=1)", "jackal over the ball": "jackal_position(hold=1)",
              "hands target for a pass": "stance(depth=0.3) + hands_target(hold=1)"},
    "Golf": {"top of backswing": "swing_top(hold=1)", "finish position": "swing_finish(hold=1)", "read the green": "low_crouch(hold=1)"},
    "Swimming": {"on the blocks": "on_the_blocks(hold=1)", "sculling": "sculling(times=3)", "open turn": "front_crawl\nopen_turn"},
    "Hockey": {"ready stance": "stick_ready(hold=1)", "stickhandling": "stance(width=wide, depth=0.6) + stickhandling(times=3)",
               "wrist shot": "stance(width=wide, depth=0.5) + wrist_shot", "goalie butterfly save": "goalkeeper_set\nbutterfly_block(hold=1)",
               "skating": "skating_stride(times=3)", "slapshot": "stance(width=wide, depth=0.3) + two_hand_ground_strike"},
    "Lacrosse": {"cradling": "run(pace=jog) + stick_cradle", "shot": "stride_step + overhand_throw(delay=0.2)"},
    "Track and field": {"on your marks": "blocks_on_your_marks(hold=1)", "sprint start from blocks": "blocks_on_your_marks(hold=1)\nblocks_set(hold=0.8)\nsprint_start",
                        "long jump": "long_jump", "high jump flop": "back_arch_flight(hold=1)", "relay exchange": "run + relay_hand_back",
                        "hurdles": "run(times=2)\nhurdle_step", "shot put": "stance(depth=0.3) + push_throw", "javelin": "run(times=2)\nlong_arm_throw"},
    "Gymnastics": {"handstand": "handstand(hold=1)", "cartwheel": "cartwheel", "bridge": "back_bridge(hold=1)", "splits": "front_split(hold=1)",
                   "l-sit": "l_sit(hold=1)", "hollow hold": "hollow_hold(hold=1)", "arabesque": "arabesque(hold=1)", "forward roll": "forward_roll"},
    "Martial arts": {"horse stance": "horse_stance(hold=1)", "front stance punch": "front_stance(hold=1)", "high block": "stance(width=wide, depth=0.5, stagger=left) + high_block(hold=1)",
                     "front kick": "front_kick", "roundhouse kick": "roundhouse_kick", "side kick": "side_kick"},
    "Wrestling": {"stance": "grappling_stance(hold=1)", "sprawl": "sprawl", "double leg shot": "level_change_shot"},
    "Winter sports": {"ski tuck": "downhill_tuck(hold=1)", "carving turns": "carving_turns(times=3)", "snowboard stance": "board_stance(hold=1)"},
    "Water and board": {"surf pop-up": "pop_up\nboard_stance(hold=1)", "rowing": "rowing_stroke(times=3)", "kayaking": "paddling(times=3)"},
    "Cycling": {"riding": "cycling(times=4)", "descending tuck": "downhill_tuck(hold=1)"},
    "Weightlifting": {"back squat": "back_squat", "front rack": "stand + front_rack(hold=1)", "power clean": "power_clean",
                      "overhead squat": "overhead_squat_hold(hold=1)", "bench press": "bench_press(times=2)", "deadlift": "deadlift",
                      "biceps curl": "stand + biceps_curl(times=3)", "bent-over row": "bent_over_row(times=3)", "kettlebell swing": "kettlebell_swing(times=3)"},
    "Climbing": {"climbing": "climbing(times=3)"},
    "Archery and fencing": {"archery draw": "archery_draw(hold=1)", "en garde": "en_garde(hold=1)", "fencing lunge": "en_garde\nfencing_lunge"},
    "Rest / sideline": {"hands on hips": "stand + hands_on_hips(hold=1)", "arms crossed": "stand + arms_crossed(hold=1)",
                        "hands on head": "stand + hands_on_head(hold=1)", "time out": "stand + t_signal(hold=1)",
                        "high five": "stand + high_five", "fist pump": "stand + fist_pump"},
}


def all_entries():
    for sport, moves in COVERAGE.items():
        for phrase, script in moves.items():
            yield sport, phrase, script
    for phrase, script in WARMUPS.items():
        yield "Warm-ups (all sports)", phrase, script
    for sport, moves in POSITIONS.items():
        for phrase, script in moves.items():
            yield sport + " positions", phrase, script


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
