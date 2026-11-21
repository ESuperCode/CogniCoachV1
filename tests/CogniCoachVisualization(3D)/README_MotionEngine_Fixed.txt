CogniCoach Motion Engine v2
===========================

Files you touch
---------------
motion_engine.py     Python backend: text prompt -> animation frames for the Unity ragdoll.
RagdollTest_AI.html  Unity WebGL page with the "Generate AI Motion" controls.
rig_info.md          Rig hierarchy / proportions (source of truth for the solver constants).

One-time setup
--------------
1. Install:   python -m pip install --upgrade openai fastapi uvicorn numpy pydantic
2. API key (pick ONE, do it once):
   a) Windows, permanent for every new terminal:   setx OPENAI_API_KEY "sk-..."
      (then open a NEW terminal; setx does not change the current one)
      macOS/Linux: add  export OPENAI_API_KEY="sk-..."  to ~/.zshrc or ~/.bashrc
   b) Or create a file named .env next to motion_engine.py containing one line:
         OPENAI_API_KEY=sk-...
      .env files are already git-ignored, so it can never be committed.
   An environment variable always wins over .env.
3. Optional settings (env vars or .env):
      OPENAI_MODEL=gpt-5-mini            (default; the engine was tuned for it)
      MOTION_REASONING_EFFORT=low        (low is the sweet spot; output length dominates latency)
      MOTION_ALLOWED_ORIGINS=https://cognicoachai.com,https://www.cognicoachai.com   (default *)
      MOTION_CACHE_DIR=./motion_cache    (persist generated plans across restarts)
      MOTION_HOST / MOTION_PORT          (default 127.0.0.1:8000)

Run
---
   python motion_engine.py              starts the API on http://127.0.0.1:8000
   python motion_engine.py --selftest   offline solver check, no API key needed
Serve the folder over HTTP (the .unityweb files are Brotli: the server must send
"Content-Encoding: br"), open RagdollTest_AI.html, type a movement, press Generate AI Motion.
Use ?api=https://your-backend to point the page at a different backend.

How it works (why it is better than before)
-------------------------------------------
Root causes of the old, bad animations (all verified by rendering the Unity build):
  * The old solver added Euler angles (spine + shoulder ...) but the HTML/Unity compose them as
    quaternions through the hierarchy, so every solved limb ended up somewhere else.
  * positionx/y/z are the WHOLE-BODY ROTATION in Unity, not a translation; the old engine wrote
    metres into them.
  * The model had to invent raw 3D coordinates, which cheap models do badly.

The pipeline (v5) - rigid code, flexible model, works for ANY drill:
  1. NORMALIZE   call 1 simplifies the request (canonical name, one-line description, phases,
                 cues) and checks for an EXACT standard movement in motion_library.py.
  2a. EXACT      standard skills (tennis forehand, butterfly, golf swing...) play the hand-built,
                 render-verified template: one call, ~9 s, identical however it is phrased.
  2b. ANYTHING ELSE (invented drills, combinations, cones, holds, turns) -> CHOREOGRAPH:
                 call 2 writes the drill as a timeline of BEATS. Every field is an enum menu:
                 stance (athletic, lunge, single-leg, plank, reverse tabletop, dive, airborne...),
                 level, trunk (hinge, coil, side bend...), facing, an action per arm (touch
                 opposite foot, punch, throw cock, overhead, contest...), an action per leg (knee
                 drive, kick, step, cross behind...), timing (quick/slow/hold), or a "macro" that
                 drops in a library template. The model never writes numbers.
                 Code (motion_library.build_beats) turns beats into precise targets and adds the
                 biomechanics itself: hinging/squatting to reach the floor, hip rotation on punches
                 and throws, counter-swinging arms, pivoting feet on facing changes, protecting the
                 standing leg, floor-aware arm support, camera choice. A structural check triggers
                 one repair call if the beats are empty/static.
  3. SOLVE       FK/IK as before (foot locking, collisions, smoothing, Euler-safe output).
  Speed: simplification and choreography now happen in ONE structured call (the schema makes the
  model simplify first, then choreograph), so standard skills take ~8 s and invented drills ~15 s.
  MOTION_PLANNER_EFFORT=minimal is ~35% faster again but produced more motion glitches in testing.
  Cleanliness safeguards in code: physical speed limit per beat (distance/rotation based, incl. the
  loop seam), elbow/knee swivel limit, time-smoothed collision corrections (two-pass solve), one IK
  solve per arm for two-hand grips, arcs at near-full arm length for big arm swings, guardrails
  that fix contradictory beat choices (both arms throwing, both knees driving, scissor crosses).
  To extend the grammar, add entries to STANCES / ARM_ACTIONS / LEG_ACTIONS in motion_library.py.

The HTML now blends frames with quaternion slerp (no Euler pops), auto-plays, shows the title and
coaching cues, has camera-view buttons (front / 3/4 / side / back), a Hand selector, a Quality
selector, and "Vertical motion": the rig cannot translate, so hip drops and jumps (frame key
"rooty", metres) are shown by sliding the canvas inside its frame.

API
---
POST /generate
  {"movement": "tennis forehand",          required
   "duration_seconds": null,               null = planner picks a realistic duration
   "playback_fps": 24,
   "dominant_side": "right" | "left",
   "extra_instructions": "",               e.g. "beginner level, slow tempo"
   "quality": "fast" | "high",             high = +1 review call (~2x time)
   "use_cache": true}
-> {"frames": [...], "playback_fps", "duration_seconds", "loop", "camera_view", "title",
    "movement_summary", "coaching_cues", "plan", "report", "llm_calls", "cached"}
POST /compile   {"plan": <plan from /generate>, ...}  re-solve a saved plan with no API call
GET  /health, GET /rig

Frames: sparse objects with the 33 joint keys (hipx ... rightelbowz), positionx/y/z (whole-body
pitch/yaw/roll) and rooty (vertical root offset in metres; Unity ignores it today).
In a page that already embeds the Unity build, call window.playGeneratedMotion(payload).

Cost / speed (gpt-5-mini)
-------------------------
About 3.5k input + 3k output tokens per generation, so well under one cent each, and 25-45 s
(the time is the JSON output length). Identical prompts are served from the cache instantly.
For cognicoachai.com, pre-generate the drill library once and serve cached plans.

Integrating into cognicoachai.com
---------------------------------
* Run motion_engine.py server-side (behind your web server); never put the API key in browser JS.
* Set MOTION_ALLOWED_ORIGINS to your domain(s) and MOTION_CACHE_DIR to a persistent folder.
* Point the page at it with ?api=https://motion.yourdomain or set window.COGNICOACH_MOTION_API
  before the page script runs.
* Optional Unity upgrade: let WebBridge/MotionController read "rooty" and add it to the hip
  object's localPosition.y (metres * your rig scale). Squats and jumps then move for real and the
  HTML "Vertical motion" canvas trick can be switched off.
