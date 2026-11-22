# Sport coverage

Every movement below is produced from the general motions in `motion_database.py`.
Each phrase is also an instant request (no model call). Regenerate: `python sport_coverage.py`.


## Basketball

| Movement | Script | Seconds |
|---|---|---|
| triple threat | `stance(depth=0.5) + ball_hold_hip(hold=1)` | 1.4 |
| dribble | `stance(depth=0.4) + hand_dribble(times=4)` | 2.4 |
| crossover dribble | `stance(depth=0.5) + crossover_dribble(times=2)` | 2.4 |
| dribble while running | `run(pace=jog, times=3) + hand_dribble` | 2.73 |
| jump shot | `jump + one_hand_set_shot(delay=0.35)` | 2.13 |
| free throw | `stance(depth=0.3) + one_hand_set_shot` | 1.8 |
| layup | `running_lay_up` | 2.53 |
| hook shot | `stance(depth=0.3) + hook_shot` | 1.7 |
| dunk | `run(times=2) / jump(height=high) + overhead_arm_strike(delay=0.2)` | 3.47 |
| chest pass | `stance(depth=0.3) + chest_pass` | 1.6 |
| bounce pass | `stance(depth=0.3) + bounce_pass` | 1.67 |
| overhead pass | `stance(depth=0.3) + two_hand_overhead_throw` | 1.6 |
| rebound | `jump(height=high) + two_hand_catch_high(delay=0.3)` | 2.13 |
| box out | `box_out(hold=1.5)` | 1.9 |
| defensive stance | `wide_defensive_stance(bounce=on, hold=1.5)` | 1.9 |
| defensive slide | `wide_defensive_stance / shuffle(times=3)` | 2.37 |
| closeout | `run(times=2) / stop_and_stick + arms_up_block` | 2.93 |
| block a shot | `jump(height=high) + arms_up_block(delay=0.2)` | 2.13 |
| pivot | `pivot_turn` | 1.2 |
| jab step | `stance(depth=0.5) + ball_hold_hip / jab_step + ball_hold_hip` | 1.67 |
| catch a pass | `stance(depth=0.3) + catch` | 1.6 |
| sprint back on defense | `run(pace=sprint, times=3)` | 2.07 |
| jump stop | `run(times=2) / stop_and_stick` | 2.73 |

## Soccer

| Movement | Script | Seconds |
|---|---|---|
| shot | `instep_kick` | 1.87 |
| pass | `inside_foot_kick` | 1.73 |
| outside foot pass | `outside_foot_flick` | 1.47 |
| chip | `chip_kick` | 1.53 |
| volley | `side_volley_kick` | 1.5 |
| long ball | `instep_kick` | 1.87 |
| dribble | `foot_dribble(times=3)` | 2.5 |
| step over | `step_over` | 1.4 |
| receive with the foot | `foot_trap` | 1.3 |
| chest control | `chest_trap` | 1.5 |
| header | `head_strike` | 1.4 |
| jumping header | `jump + head_strike(delay=0.3)` | 2.0 |
| throw-in | `two_hand_overhead_throw` | 1.6 |
| block tackle | `block_tackle` | 1.4 |
| shielding the ball | `box_out(hold=1)` | 1.4 |
| goalkeeper ready stance | `stance(width=wide, depth=0.6, bounce=on) + ready_arms(hold=1)` | 1.4 |
| goalkeeper dive | `side_dive` | 2.03 |
| goalkeeper high catch | `jump + two_hand_catch_high(delay=0.25)` | 2.0 |
| goalkeeper scoop | `low_scoop` | 1.6 |
| goal kick | `instep_kick` | 1.87 |
| goalkeeper punt | `punt_kick` | 1.9 |
| sprint | `run(pace=sprint, times=3)` | 2.07 |
| cut | `cutting_step` | 1.3 |
| jockeying | `wide_defensive_stance / backpedal(times=3)` | 2.5 |

## Tennis

| Movement | Script | Seconds |
|---|---|---|
| forehand | `stance(width=wide, depth=0.4) + forehand_swing` | 2.0 |
| two-handed backhand | `stance(width=wide, depth=0.4) + two_hand_backhand` | 2.0 |
| one-handed backhand | `stance(width=wide, depth=0.4) + one_hand_backhand` | 2.0 |
| serve | `jumping_overhead_serve` | 2.93 |
| forehand volley | `stance(width=wide, depth=0.4) + punch_volley` | 1.6 |
| backhand volley | `stance(width=wide, depth=0.4) + backhand_block` | 1.6 |
| overhead smash | `stance(width=wide, depth=0.3) + overhead_arm_strike` | 1.9 |
| split step | `split_step` | 1.2 |
| ready position | `stance(width=wide, depth=0.5, bounce=on) + ready_arms(hold=1)` | 1.4 |
| side shuffle recovery | `shuffle(times=3) + ready_arms` | 1.77 |
| lunge to reach | `lateral_lunge + ready_arms` | 2.6 |

## Football

| Movement | Script | Seconds |
|---|---|---|
| three-point stance | `three_point_stance(hold=1.5)` | 1.9 |
| snap | `center_snap` | 1.2 |
| quarterback drop back | `backpedal(times=3) + ball_carry` | 1.9 |
| throw a pass | `stride_step + overhand_throw(delay=0.2)` | 2.2 |
| handoff | `stance(depth=0.3) + handoff` | 1.5 |
| catch | `stance(depth=0.3) + catch` | 1.6 |
| over the shoulder catch | `run(times=2) + over_shoulder_catch` | 1.4 |
| carry the ball | `run(times=3) + ball_carry` | 2.37 |
| stiff arm | `run(times=2) + ball_carry + stiff_arm` | 1.27 |
| juke / cut | `cutting_step + ball_carry` | 1.3 |
| spin move | `pivot_turn(deg=270) + ball_carry` | 1.2 |
| tackle | `form_tackle` | 1.6 |
| block | `push_block` | 1.4 |
| kickoff | `run(times=2) / instep_kick` | 3.2 |
| punt | `punt_kick` | 1.9 |
| field goal | `instep_kick` | 1.87 |
| backpedal coverage | `backpedal(times=4)` | 2.4 |
| linebacker stance | `wide_defensive_stance(hold=1)` | 1.4 |

## Baseball

| Movement | Script | Seconds |
|---|---|---|
| batting stance and swing | `stance(width=wide, depth=0.3) + level_two_hand_swing` | 2.0 |
| bunt | `stance(width=wide, depth=0.4) + bunt` | 1.6 |
| pitch | `stride_step + overhand_throw(delay=0.25)` | 2.27 |
| throw | `stride_step + overhand_throw(delay=0.2)` | 2.2 |
| field a ground ball | `low_scoop` | 1.6 |
| catch a fly ball | `stance(depth=0.2) + two_hand_catch_high` | 1.6 |
| catcher stance | `catcher_crouch(hold=1.5)` | 1.9 |
| slide into base | `run(times=2) / feet_first_slide` | 2.93 |
| base running | `run(pace=sprint, times=3)` | 2.07 |
| leading off | `wide_defensive_stance / shuffle(times=2)` | 1.93 |
| softball windmill pitch | `stance(depth=0.3) + windmill_throw` | 1.6 |

## Volleyball

| Movement | Script | Seconds |
|---|---|---|
| ready position | `stance(width=wide, depth=0.6) + ready_arms(hold=1)` | 1.4 |
| forearm pass | `stance(width=wide, depth=0.6) + forearm_platform` | 1.33 |
| set | `stance(depth=0.3) + overhead_two_hand_set` | 1.9 |
| spike | `run(times=1) / jump(height=high) + overhead_arm_strike(delay=0.1)` | 2.8 |
| block | `jump + arms_up_block` | 2.0 |
| underhand serve | `stance(depth=0.2) + underhand_serve` | 1.8 |
| overhand serve | `stance(depth=0.2) + overhead_arm_strike` | 1.9 |
| jump serve | `jumping_overhead_serve` | 2.93 |
| dig | `lateral_lunge + forearm_platform` | 2.6 |
| dive for the ball | `side_dive` | 2.03 |
| approach steps | `stride_step / jump(height=high)` | 3.73 |

## Swimming

| Movement | Script | Seconds |
|---|---|---|
| freestyle | `front_crawl(times=2) / loop` | 2.8 |
| backstroke | `back_crawl(times=2) / loop` | 3.0 |
| breaststroke | `breaststroke(times=2) / loop` | 3.2 |
| butterfly | `butterfly_stroke(times=2) / loop` | 2.6 |
| streamline | `streamline(hold=2)` | 2.4 |
| flutter kick | `flutter_kick(times=4)` | 2.4 |
| dolphin kick | `dolphin_kick(times=4)` | 2.8 |
| flip turn | `front_crawl / flip_turn` | 3.0 |
| start dive | `start_dive` | 1.77 |
| treading water | `tread_water(times=3)` | 3.4 |
| streamline stretch | `stand + arms_overhead(hold=2)` | 2.4 |

## Cricket

| Movement | Script | Seconds |
|---|---|---|
| bowling | `run(times=2) / straight_arm_bowl` | 3.03 |
| forward defense | `forward_defense` | 1.4 |
| drive | `stance(width=wide, depth=0.3) + vertical_two_hand_swing` | 1.9 |
| pull shot | `stance(width=wide, depth=0.3) + level_two_hand_swing` | 2.0 |
| wicket keeping | `catcher_crouch(hold=1.5)` | 1.9 |
| field and throw | `low_scoop / stride_step + overhand_throw(delay=0.2)` | 3.4 |
| catch high | `stance(depth=0.2) + two_hand_catch_high` | 1.6 |
| diving catch | `side_dive` | 2.03 |
| run between wickets | `run(pace=sprint, times=3)` | 2.07 |

## Rugby

| Movement | Script | Seconds |
|---|---|---|
| pass | `run(times=2) + ball_carry / stance(depth=0.3) + two_hand_side_pass` | 2.93 |
| catch | `stance(depth=0.3) + catch` | 1.6 |
| carry | `run(times=3) + ball_carry` | 2.37 |
| fend | `run(times=2) + ball_carry + stiff_arm` | 1.27 |
| side step | `cutting_step + ball_carry` | 1.3 |
| tackle | `form_tackle` | 1.6 |
| ruck / maul / scrum drive | `bent_over_drive(times=3)` | 2.8 |
| lineout throw | `stance(depth=0.2) + two_hand_overhead_throw` | 1.6 |
| lineout jump | `jump(height=high) + arms_up_block(delay=0.2)` | 2.13 |
| place kick | `instep_kick` | 1.87 |
| drop kick | `punt_kick` | 1.9 |
| box kick | `punt_kick` | 1.9 |

## Golf

| Movement | Script | Seconds |
|---|---|---|
| full swing | `stance(width=wide, depth=0.2) + low_two_hand_swing` | 3.2 |
| chip | `stance(width=normal, depth=0.2) + chip_swing` | 1.9 |
| putt | `stance(width=normal, depth=0.2) + putt` | 1.7 |
| address | `stance(width=wide, depth=0.2) + low_two_hand_swing(end=0.01, hold=1)` | 1.53 |
| tee up the ball | `touch_low` | 1.6 |
| practice swing | `stance(width=wide, depth=0.2) + low_two_hand_swing` | 3.2 |
| golf warm-up rotation | `stance(depth=0.1) + torso_twist(times=2)` | 3.6 |

## Warm-ups (all sports)

| Movement | Script | Seconds |
|---|---|---|
| jog | `run(pace=jog, times=3)` | 2.73 |
| high knees | `high_knees(times=4)` | 2.4 |
| butt kicks | `butt_kicks(times=4)` | 2.23 |
| a skips | `a_skip(times=3)` | 3.1 |
| b skips | `b_skip(times=3)` | 3.4 |
| carioca | `carioca(times=2)` | 2.4 |
| lateral shuffle | `shuffle(times=3)` | 1.77 |
| backpedal | `backpedal(times=4)` | 2.4 |
| strides | `run(times=3)` | 2.37 |
| leg swings | `leg_swing(times=3)` | 4.0 |
| lateral leg swings | `lateral_leg_swing(times=3)` | 4.0 |
| walking lunges | `lunge / lunge(side=left)` | 5.4 |
| side lunges | `lateral_lunge / lateral_lunge(side=left)` | 4.8 |
| knee hugs | `knee_hug / knee_hug(side=left)` | 3.2 |
| straight leg kicks | `straight_leg_kick(times=2)` | 3.2 |
| inchworms | `inchworm` | 4.8 |
| hip circles | `hip_circles(times=2)` | 4.4 |
| arm circles | `stance(depth=0.1) + arm_circles(times=3)` | 2.8 |
| arm swings | `stance(depth=0.1) + arm_swings(times=3)` | 3.4 |
| torso twists | `stance(depth=0.1) + torso_twist(times=2)` | 3.6 |
| neck rolls | `stand + neck_rolls` | 3.4 |
| jumping jacks | `jumping_jack(times=3)` | 3.1 |
| pogo hops | `pogo_hops(times=6)` | 2.8 |
| jump rope | `jump_rope(times=6)` | 3.4 |
| squats | `squat / squat` | 4.6 |
| push ups | `push_up(times=2)` | 3.6 |
| plank | `plank(hold=2)` | 2.4 |
| hamstring stretch | `hamstring_stretch(hold=2)` | 2.4 |
| quad stretch | `quad_stretch(hold=2)` | 2.4 |
| shoulder stretch | `stand + arm_cross_stretch(hold=2)` | 2.4 |
| calf raises | `calf_raise(times=3)` | 5.2 |
