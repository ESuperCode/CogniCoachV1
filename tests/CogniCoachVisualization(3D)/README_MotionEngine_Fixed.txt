CogniCoach Motion Engine - text to human animation with a small language model
===============================================================================

How it works (default pipeline: "script")
-----------------------------------------
1. A cheap text model (default gpt-5-mini) reads the request and writes WHAT happens, never joint
   angles: a few plain steps, then a short script in the CogniCoach Motion Script language that
   composes motions from the motion database.
2. The script compiler (motion_script.py) merges the motions body part by body part, times and
   blends them, mirrors for left-handers and keeps the athlete on the floor.
3. Compile errors (unknown motion, two motions driving the same body part ...) go back to the model
   once with the exact error. Near-miss motion names and "name key=value" syntax are accepted.

Files
-----
motion_database.py           THE MOTION DATABASE (647 motions: sport skills, positions, gym, calisthenics, Pilates, strongman, CrossFit, dance, mobility, stretching, yoga). Every stored motion: name, comment, kind (action /
                             cycle / pose), the body parts it drives (hard) or offers (soft),
                             parameters, and its keyframes in anatomical angles.
sport_coverage.py            351 sport movements as scripts (instant phrases + model recipes); writes SPORT_COVERAGE.md.
validate_motion_database.py  Checks every motion (arm/body contact, abrupt joint changes).
                             Run after adding or editing motions.
motion_script.py             The language: parser + compiler.
motion_engine.py             Model prompt, HTTP API, the older beat-grammar pipeline, shared math.
motion_grammar.py            The older beat-grammar pipeline (engine="grammar").
RagdollTest_AI.html          Unity WebGL viewer. "Generate AI Motion" calls the model; the script box
                             shows the script it wrote - edit it and press "Run Script" to replay
                             without a model call.

The language (CogniCoach Motion Script)
---------------------------------------
    # comment
    stance(width=wide, depth=0.5) + ready_arms       motions on one line play TOGETHER
    stance(width=wide, depth=0.5) + forehand         the next line plays AFTER the previous one
    fighting_stance + guard + jab x3                 "x3" repeats the line
    run(pace=sprint, times=2)                        times= repeats a motion
    jump + shoot(delay=0.35)                         delay= starts a motion later on its line
    loop                                             optional: the clip loops

Body parts: body (whole-body orientation, height in the air), pelvis, spine, neck, right_arm,
left_arm, right_leg, left_leg. A motion drives only the parts its skill needs (soccer_kick: legs +
hips; forehand: arms + trunk), so a lower-body motion and an upper-body motion combine into one
full-body skill. Hard part beats soft part; two hard owners of a part on one line is an error.
Parts nobody drives on a line keep their pose from the line before.
Every motion accepts side=left|right (mirror), speed=0.5..2, times=N, hold=seconds, delay=seconds.

Adding a motion
---------------
Add a function with the @motion(...) decorator in motion_database.py (see the helpers at the top:
A/Lg/S/P/N/B angle helpers, k() keys, leg_at / arm_at to place a foot or hand, grip_keys for two
hands on one implement), then run:  python validate_motion_database.py <name>
Keyframes are solved once into joint angles and interpolated as rotations, so playback cannot jitter.

Setup / run
-----------
python -m pip install --upgrade openai fastapi uvicorn numpy pydantic
API key once: setx OPENAI_API_KEY "sk-..." (Windows) or a .env file next to motion_engine.py.
python motion_engine.py              API on http://127.0.0.1:8000 (restart it after pulling new code)
python motion_engine.py --selftest   offline test, no API key

API
---
POST /generate {"movement": "...", "dominant_side": "right"|"left", "engine": "script"|"grammar"}
     -> frames, playback_fps, loop, camera_view, ground, title, coaching_cues, script, plan, report
POST /script   {"script": "...", "dominant_side": "right"}  compile a script directly (no model)
GET  /motions  the database catalog
GET  /health   engine_version, model, key configured

Cost / speed: common phrases compile instantly with no model call; otherwise one gpt-5-mini call, typically 2-8 s (logged per request).
Results are cached per prompt.
