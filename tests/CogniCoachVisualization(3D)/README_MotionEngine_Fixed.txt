CogniCoach Motion Engine - text to human animation with a small language model
===============================================================================

Core idea ("rigid mechanism + flexible slime")
----------------------------------------------
A small, cheap text model (default gpt-5-mini) is NOT asked to output joint angles, coordinates or
animation data, and the engine contains NO pre-programmed movements (no sport skills, exercises or
pose libraries). Instead:

  * the model describes ANY movement in a fixed, enum-only spatial grammar (flexible part), and
  * deterministic code turns that description into physically and anatomically valid motion on the
    measured rig (rigid part), and checks the result, feeding objective problems back to the model.

Every movement - a soccer instep kick, a butterfly stroke, or a drill a coach invented a minute
ago - is produced by the same mechanism from the same vocabulary.

Files
-----
motion_grammar.py    The grammar (menus) and the descriptor -> body-target compiler with its
                     biomechanical inference rules. Contains no movement data.
motion_engine.py     Language-model interface, validation/repair loop, kinematic solver, verifier,
                     playback-speed tuning and the HTTP API.
RagdollTest_AI.html  Unity WebGL viewer with the "Generate AI Motion" controls.
rig_info.md          Rig hierarchy and proportions.

Pipeline
--------
1. DESCRIBE (one structured-output call). Schema order forces the model to first simplify the request
   (canonical name, one-sentence description, phases written per body part), then encode each phase as
   a BEAT. Every beat field is an enum:
     body : base (support + orientation), level (hip height), trunk, facing, timing
     hand : height (floor..overhead) x direction (front, side, back, across, center...) x
            reach (tucked/bent/extended) x elbow direction; or auto / at_side / keep
     foot : position (under_hip, front, far_back, side, cross_back...) x height above the floor
            (floor..high) x leg shape (straight / bent / tucked)
     hands_together for implements; skill_limbs = the limbs that actually perform the skill.
2. BUILD (code, motion_grammar.build_beats). Descriptors -> exact chest/body-frame targets with
   guaranteed reachability, plus inference rules the model never has to know:
     - anatomical legs: a raised leg is built from joint angles inside real hip/knee ranges for its
       shape (a straight leg stays straight - kicks never collapse into knee lifts; a bent leg behind
       keeps the thigh behind the body; a high side leg tilts the trunk away)
     - limb synergies: limbs not in skill_limbs are synthesised - balance arm during straight-leg
       swings, sagittal gait counter-swing driven by thigh direction, relaxed arms hang with gravity
     - physics: follow-through stays in the swing plane (ballistic continuation); body rise during
       flight follows flight time (h = g*T^2/8, running strides capped); steady trunk in rhythmic
       cycles; planted feet relocate only by stepping (when the beat label says footwork)
     - two-hand grips stay in front of the chest (the trunk carries them round)
     - reach inference: hinge, then squat, until a low target (knee/shin/floor, measured from the
       floor) is reachable
     - trunk rotation implied by the arms (reaching across, winding back)
     - counter-balance for lifted legs (lean back for a front kick, forward for a rear leg)
     - automatic arms: counter-swing against the legs, balance arm, ready hands, floor support
     - support logic: feet at "floor" are planted; both feet up = airborne; turning releases feet
     - physically plausible minimum durations per beat from travel distance and rotation
3. CHECK + REPAIR. The plan is solved and verified; the engine critiques it (too few/static beats,
   loop mismatch, ending in the air, implausible straddles, and a SELF-CONSISTENCY check that the
   model's own beat labels - "jump", "kick", "touch the cone", "punch" - match what the beat
   encodes), static-balance checks (big hinge on one leg), single-leg and guard checks. If anything
   is found, one repair call receives exactly those findings.
4. SOLVE (code). Monotone splines; arc waypoints for big arm and leg swings (limbs swing around the
   shoulder/hip instead of through it); two-bone IK with anatomical knee direction from the hip->foot
   line and elbow direction hints; planted-foot locking after landing; hard arm/body collision
   constraint against chest, shoulder-top/neck, head and pelvis that preserves elbow intent (arms may
   rise overhead beside the head); elbow posture constraint (no chicken wings); swivel
   despiking with route selection; kinetic-chain lead (hips rotate before the chest); rotation-space
   smoothing; Euler-flip-free output; left-handed mirroring.
5. VERIFY + PLAYBACK. Pops, pass-through, posture (elbows, knee bow relative to the body's facing,
   side bend), motion amount; playback FPS tuned from measured limb speed.

Typical cost: one call (~3.5k in / ~3k out tokens), 20-30 s; ~1/3 of requests trigger a repair
(+20-25 s). Results are cached per prompt.

Setup
-----
python -m pip install --upgrade openai fastapi uvicorn numpy pydantic
API key once: setx OPENAI_API_KEY "sk-..." (Windows) or a .env file next to motion_engine.py.
Run:  python motion_engine.py           (API on http://127.0.0.1:8000)
      python motion_engine.py --selftest (offline grammar + solver test, no API key)
Optional env: OPENAI_MODEL, MOTION_PLANNER_EFFORT (low), MOTION_ALLOWED_ORIGINS, MOTION_CACHE_DIR,
MOTION_TARGET_SPEED (1.6 m/s), MOTION_HOST/PORT.

API
---
POST /generate {"movement": "...", "dominant_side": "right"|"left", "quality": "fast"|"high",
                "speed": "auto"|"realtime", "duration_seconds": null, "extra_instructions": ""}
 -> frames, playback_fps, loop, camera_view, title, coaching_cues, plan (incl. the model's grammar
    description in plan.description / plan.beats and the engine's inferences in plan.grammar_notes),
    report (verification metrics), llm_calls.
POST /compile {"plan": ...} re-solves a saved plan without any model call.

Limits
------
The Unity rig rotates joints only; the pelvis cannot translate, so travel happens in place and
vertical motion ("rooty") is displayed by the HTML canvas offset against a fixed floor contact
shadow (hidden for horizontal bodies; the response's "ground" flag). GET /health reports
engine_version - restart the server after pulling new code. Quality of a movement depends on
how well the model describes it in the grammar; the rigid part guarantees validity, not technique.
