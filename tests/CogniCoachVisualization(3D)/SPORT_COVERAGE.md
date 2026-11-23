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
| start dive | `start_dive` | 2.47 |
| treading water | `tread_water(times=3)` | 3.4 |
| streamline stretch | `stand + arms_overhead(hold=2)` | 2.4 |

## Cricket

| Movement | Script | Seconds |
|---|---|---|
| bowling | `run(times=2) / straight_arm_bowl` | 3.03 |
| forward defense | `forward_defense` | 1.4 |
| drive | `vertical_two_hand_swing` | 2.0 |
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
| child's pose | `childs_pose(hold=2)` | 2.4 |
| cat cow | `cat_cow(times=2)` | 6.4 |
| bird dog | `bird_dog(times=2)` | 6.8 |
| downward dog | `downward_dog(hold=2)` | 2.4 |
| cobra stretch | `cobra(hold=2)` | 2.4 |
| forearm plank | `forearm_plank(hold=2)` | 2.4 |
| side plank | `side_plank(hold=2)` | 2.4 |
| dead bug | `dead_bug(times=2)` | 6.4 |
| glute bridge | `glute_bridge(times=2)` | 4.4 |
| sit and reach | `seated_forward_fold(hold=2)` | 2.4 |
| butterfly stretch | `butterfly_stretch(hold=2)` | 2.4 |
| kneeling hip flexor stretch | `hip_flexor_stretch(hold=2)` | 2.4 |
| half kneeling | `half_kneel(hold=1)` | 1.4 |
| tall kneeling | `kneel(hold=1)` | 1.4 |
| hands and knees | `table_top(hold=1)` | 1.4 |
| lying down rest | `lie_on_back(hold=2)` | 2.4 |
| get up off the floor | `get_up_from_floor` | 2.5 |
| inchworm walkout | `inchworm` | 4.8 |
| superman hold | `superman(hold=2)` | 2.4 |

## Football positions

| Movement | Script | Seconds |
|---|---|---|
| receiver two point stance | `two_point_stance(hold=1)` | 1.4 |
| lineman four point stance | `four_point_stance(hold=1)` | 1.4 |
| quarterback under center | `crouch_hands_low(hold=1)` | 1.4 |
| field goal holder | `one_knee_hands_ready(hold=1)` | 1.4 |
| fair catch | `stand + one_arm_up(hold=1)` | 1.4 |
| pass protection set | `pass_block_set(hold=1)` | 1.4 |
| huddle | `hands_on_knees(hold=1)` | 1.4 |
| touchdown signal | `stand + arms_overhead(hold=1)` | 1.4 |

## Basketball positions

| Movement | Script | Seconds |
|---|---|---|
| post up | `post_up(hold=1)` | 1.4 |
| denial | `denial_stance(hold=1)` | 1.4 |
| help side | `help_side_stance(hold=1)` | 1.4 |
| jump ball | `tip_off_ready(hold=1)` | 1.4 |
| call for the ball | `stance(depth=0.3) + hands_target(hold=1)` | 1.4 |

## Soccer positions

| Movement | Script | Seconds |
|---|---|---|
| goalkeeper set position | `goalkeeper_set(hold=1)` | 1.4 |
| jockey | `jockey_stance(hold=1)` | 1.4 |
| free kick wall | `defensive_wall(hold=1)` | 1.4 |
| goal celebration | `jump + arms_overhead / stand + fist_pump` | 3.3 |

## Tennis positions

| Movement | Script | Seconds |
|---|---|---|
| trophy position | `trophy_position(hold=1)` | 1.4 |
| forehand unit turn | `unit_turn_right(hold=1)` | 1.4 |
| backhand unit turn | `unit_turn_left(hold=1)` | 1.4 |
| overhead ready | `overhead_ready(hold=1)` | 1.4 |

## Baseball positions

| Movement | Script | Seconds |
|---|---|---|
| batting stance | `hitting_stance(hold=1)` | 1.4 |
| pitcher set position | `set_position(hold=1)` | 1.4 |
| pitcher leg lift | `balance_point(hold=1)` | 1.4 |
| infielder ready | `fielder_ready(hold=1)` | 1.4 |
| first base stretch | `long_stretch_reach(hold=1)` | 1.4 |
| headfirst slide | `run(times=2) / prone_reach(hold=1)` | 2.73 |

## Volleyball positions

| Movement | Script | Seconds |
|---|---|---|
| blocker ready | `stance(depth=0.4) + hands_up_ready(hold=1)` | 1.4 |
| dig ready | `platform_ready(hold=1)` | 1.4 |
| approach load | `jump_load(hold=1)` | 1.4 |
| pancake save | `side_dive / prone_reach(hold=1)` | 3.03 |

## Cricket positions

| Movement | Script | Seconds |
|---|---|---|
| batting stance | `side_on_batting_stance(hold=1)` | 1.4 |
| backlift | `backlift(hold=1)` | 1.4 |
| slip catching stance | `slip_catch_stance(hold=1)` | 1.4 |
| bowling delivery stride | `delivery_stride(hold=1)` | 1.4 |
| umpire out signal | `stand + one_arm_up(hold=1)` | 1.4 |
| umpire wide signal | `stand + arms_out(hold=1)` | 1.4 |
| umpire six signal | `stand + arms_overhead(hold=1)` | 1.4 |

## Rugby positions

| Movement | Script | Seconds |
|---|---|---|
| lineout lifter | `overhead_lift_hold(hold=1)` | 1.4 |
| jackal over the ball | `jackal_position(hold=1)` | 1.4 |
| hands target for a pass | `stance(depth=0.3) + hands_target(hold=1)` | 1.4 |

## Golf positions

| Movement | Script | Seconds |
|---|---|---|
| top of backswing | `swing_top(hold=1)` | 1.4 |
| finish position | `swing_finish(hold=1)` | 1.4 |
| read the green | `low_crouch(hold=1)` | 1.4 |

## Swimming positions

| Movement | Script | Seconds |
|---|---|---|
| on the blocks | `on_the_blocks(hold=1)` | 1.4 |
| sculling | `sculling(times=3)` | 3.4 |
| open turn | `front_crawl / open_turn` | 3.0 |

## Hockey positions

| Movement | Script | Seconds |
|---|---|---|
| ready stance | `stick_ready(hold=1)` | 1.4 |
| stickhandling | `stance(width=wide, depth=0.6) + stickhandling(times=3)` | 2.5 |
| wrist shot | `stance(width=wide, depth=0.5) + wrist_shot` | 1.7 |
| goalie butterfly save | `goalkeeper_set / butterfly_block(hold=1)` | 2.0 |
| skating | `skating_stride(times=3)` | 4.0 |
| slapshot | `stance(width=wide, depth=0.3) + two_hand_ground_strike` | 1.9 |

## Lacrosse positions

| Movement | Script | Seconds |
|---|---|---|
| cradling | `run(pace=jog) + stick_cradle` | 1.17 |
| shot | `stride_step + overhand_throw(delay=0.2)` | 2.2 |

## Track and field positions

| Movement | Script | Seconds |
|---|---|---|
| on your marks | `blocks_on_your_marks(hold=1)` | 1.4 |
| sprint start from blocks | `blocks_on_your_marks(hold=1) / blocks_set(hold=0.8) / sprint_start` | 3.7 |
| long jump | `long_jump` | 2.7 |
| high jump flop | `back_arch_flight(hold=1)` | 1.4 |
| relay exchange | `run + relay_hand_back` | 1.07 |
| hurdles | `run(times=2) / hurdle_step` | 2.77 |
| shot put | `stance(depth=0.3) + push_throw` | 1.8 |
| javelin | `run(times=2) / long_arm_throw` | 2.93 |

## Gymnastics positions

| Movement | Script | Seconds |
|---|---|---|
| handstand | `handstand(hold=1)` | 1.4 |
| cartwheel | `cartwheel` | 2.1 |
| bridge | `back_bridge(hold=1)` | 1.4 |
| splits | `front_split(hold=1)` | 1.4 |
| l-sit | `l_sit(hold=1)` | 1.4 |
| hollow hold | `hollow_hold(hold=1)` | 1.4 |
| arabesque | `arabesque(hold=1)` | 1.4 |
| forward roll | `forward_roll` | 2.6 |

## Martial arts positions

| Movement | Script | Seconds |
|---|---|---|
| horse stance | `horse_stance(hold=1)` | 1.4 |
| front stance punch | `front_stance(hold=1)` | 1.4 |
| high block | `stance(width=wide, depth=0.5, stagger=left) + high_block(hold=1)` | 1.4 |
| front kick | `front_kick` | 1.33 |
| roundhouse kick | `roundhouse_kick` | 1.6 |
| side kick | `side_kick` | 1.53 |

## Wrestling positions

| Movement | Script | Seconds |
|---|---|---|
| stance | `grappling_stance(hold=1)` | 1.4 |
| sprawl | `sprawl` | 1.6 |
| double leg shot | `level_change_shot` | 1.5 |

## Winter sports positions

| Movement | Script | Seconds |
|---|---|---|
| ski tuck | `downhill_tuck(hold=1)` | 1.4 |
| carving turns | `carving_turns(times=3)` | 5.2 |
| snowboard stance | `board_stance(hold=1)` | 1.4 |

## Water and board positions

| Movement | Script | Seconds |
|---|---|---|
| surf pop-up | `pop_up / board_stance(hold=1)` | 2.33 |
| rowing | `rowing_stroke(times=3)` | 6.4 |
| kayaking | `paddling(times=3)` | 4.6 |

## Cycling positions

| Movement | Script | Seconds |
|---|---|---|
| riding | `cycling(times=4)` | 3.6 |
| descending tuck | `downhill_tuck(hold=1)` | 1.4 |

## Weightlifting positions

| Movement | Script | Seconds |
|---|---|---|
| back squat | `back_squat` | 2.5 |
| front rack | `stand + front_rack(hold=1)` | 1.4 |
| power clean | `power_clean` | 2.0 |
| overhead squat | `overhead_squat_hold(hold=1)` | 1.4 |
| bench press | `bench_press(times=2)` | 4.4 |
| deadlift | `deadlift` | 2.7 |
| biceps curl | `stand + biceps_curl(times=3)` | 5.8 |
| bent-over row | `bent_over_row(times=3)` | 5.8 |
| kettlebell swing | `kettlebell_swing(times=3)` | 4.6 |

## Climbing positions

| Movement | Script | Seconds |
|---|---|---|
| climbing | `climbing(times=3)` | 4.6 |

## Archery and fencing positions

| Movement | Script | Seconds |
|---|---|---|
| archery draw | `archery_draw(hold=1)` | 1.4 |
| en garde | `en_garde(hold=1)` | 1.4 |
| fencing lunge | `en_garde / fencing_lunge` | 2.3 |

## Fitness positions

| Movement | Script | Seconds |
|---|---|---|
| burpee | `burpee` | 3.73 |
| burpee with push up | `burpee / push_up` | 5.33 |
| squat | `squat` | 2.5 |
| goblet squat | `goblet_squat` | 2.5 |
| sumo squat | `sumo_squat` | 2.5 |
| jump squat | `squat(end=0.5) / jump(height=high)` | 3.2 |
| thruster | `thruster` | 2.6 |
| reverse lunge | `reverse_lunge` | 2.7 |
| curtsy lunge | `curtsy_lunge` | 2.5 |
| lateral lunge | `lateral_lunge` | 2.6 |
| good morning | `good_morning` | 2.5 |
| wall sit | `wall_sit(hold=2)` | 2.4 |
| lateral raise | `stand + lateral_raise(times=3)` | 5.8 |
| front raise | `stand + front_raise(times=3)` | 5.8 |
| triceps extension | `stand + overhead_triceps_extension(times=3)` | 5.8 |
| pull up | `pull_up(times=2)` | 4.4 |
| dead hang | `dead_hang(hold=2)` | 2.4 |
| plank jacks | `plank_jacks(times=4)` | 3.6 |
| shoulder taps | `shoulder_taps(times=3)` | 4.0 |
| bicycle crunches | `bicycle_crunch(times=4)` | 5.2 |
| leg raises | `leg_raises(times=3)` | 7.6 |
| flutter kicks | `flutter_kicks_back(times=6)` | 3.4 |
| v-up | `v_up` | 1.9 |
| sit-up | `sit_up(times=2)` | 4.4 |
| russian twist | `russian_twist(times=3)` | 4.6 |
| mountain climbers | `mountain_climbers(times=4)` | 2.8 |
| donkey kicks | `donkey_kicks(times=3)` | 4.6 |
| fire hydrants | `fire_hydrants(times=3)` | 4.6 |
| side leg raise | `side_lying_leg_raise(times=3)` | 5.2 |
| crab walk | `crab_walk(times=3)` | 3.4 |
| bear crawl | `bear_crawl(times=3)` | 3.4 |
| glute bridge | `glute_bridge(times=2)` | 4.4 |
| low plank | `low_plank(hold=2)` | 2.4 |
| dumbbell upper body circuit | `stand + lateral_raise(times=2) / stand + biceps_curl(times=2) / stand + overhead_triceps_extension(times=2)` | 11.2 |

## Yoga and stretching positions

| Movement | Script | Seconds |
|---|---|---|
| mountain pose | `mountain_pose(hold=2)` | 2.4 |
| chair pose | `chair_pose(hold=2)` | 2.4 |
| warrior one | `warrior_one(hold=2)` | 2.4 |
| warrior two | `warrior_pose(hold=2)` | 2.4 |
| reverse warrior | `reverse_warrior(hold=2)` | 2.4 |
| triangle | `triangle_pose(hold=2)` | 2.4 |
| tree pose | `tree_pose(hold=2)` | 2.4 |
| garland squat | `garland_squat(hold=2)` | 2.4 |
| boat pose | `boat_pose(hold=2)` | 2.4 |
| pigeon | `pigeon_pose(hold=2)` | 2.4 |
| happy baby | `happy_baby(hold=2)` | 2.4 |
| camel | `camel_pose(hold=2)` | 2.4 |
| seated twist | `seated_twist(hold=2)` | 2.4 |
| lying twist | `supine_twist(hold=2)` | 2.4 |
| knee to chest | `knee_to_chest(hold=2)` | 2.4 |
| figure four | `figure_four_stretch(hold=2)` | 2.4 |
| side stretch | `stand + standing_side_stretch(hold=2)` | 2.4 |
| triceps stretch | `stand + triceps_stretch(hold=2)` | 2.4 |
| chest opener | `stand + chest_opener(hold=2)` | 2.4 |
| neck stretch | `stand + neck_stretch(hold=2)` | 2.4 |
| calf stretch | `calf_stretch(hold=2)` | 2.4 |
| sun salutation | `mountain_pose(hold=0.5) / stand + arms_overhead(hold=0.5) / hamstring_stretch(hold=0.6) / plank(hold=0.4) / low_plank(hold=0.4) / cobra(hold=0.6) / downward_dog(hold=1) / mountain_pose` | 5.6 |
| savasana | `lie_on_back(hold=3)` | 3.4 |

## Gym positions

| Movement | Script | Seconds |
|---|---|---|
| leg press | `leg_press(times=2)` | 4.4 |
| hack squat | `hack_squat` | 2.6 |
| leg extension | `leg_extension(times=3)` | 5.8 |
| leg curl | `lying_leg_curl(times=3)` | 5.8 |
| hip abduction | `hip_abduction(times=3)` | 5.8 |
| lat pulldown | `lat_pulldown(times=3)` | 5.8 |
| seated cable row | `seated_cable_row(times=3)` | 5.8 |
| one arm dumbbell row | `one_arm_row(times=3)` | 5.8 |
| face pull | `stand + face_pull(times=3)` | 5.8 |
| cable crossover | `stance(stagger=left, depth=0.2) + cable_crossover(times=3)` | 6.4 |
| incline bench press | `incline_press(times=2)` | 4.4 |
| overhead press | `stand + overhead_press(times=2)` | 4.4 |
| arnold press | `stand + arnold_press(times=2)` | 4.8 |
| triceps pushdown | `stand + triceps_pushdown(times=3)` | 5.2 |
| preacher curl | `sit_on_bench + preacher_curl(times=3)` | 5.8 |
| front squat | `front_rack + squat` | 2.5 |
| sumo deadlift | `sumo_deadlift` | 2.7 |
| romanian deadlift | `hinge` | 2.8 |
| back extension | `back_extension(times=3)` | 6.4 |
| ab wheel rollout | `ab_wheel_rollout(times=2)` | 5.2 |
| pallof press | `stance(depth=0.3) + pallof_press(times=3)` | 6.4 |
| farmer carry | `walk(times=3) + arms_hang` | 3.7 |
| rowing machine | `rowing_stroke(times=3)` | 6.4 |
| stair climber | `stair_climber(times=4)` | 4.4 |
| push day | `bench_press(times=2) / stand + overhead_press(times=2) / dips(times=2) / stand + triceps_pushdown(times=2)` | 11.2 |
| pull day | `lat_pulldown(times=2) / seated_cable_row(times=2) / stand + face_pull(times=2) / stand + biceps_curl(times=2)` | 11.2 |
| leg day | `back_squat / leg_press(times=2) / lying_leg_curl(times=2) / calf_raise(times=2)` | 11.3 |

## Rest / sideline positions

| Movement | Script | Seconds |
|---|---|---|
| hands on hips | `stand + hands_on_hips(hold=1)` | 1.4 |
| arms crossed | `stand + arms_crossed(hold=1)` | 1.4 |
| hands on head | `stand + hands_on_head(hold=1)` | 1.4 |
| time out | `stand + t_signal(hold=1)` | 1.4 |
| high five | `stand + high_five` | 1.2 |
| fist pump | `stand + fist_pump` | 1.7 |
