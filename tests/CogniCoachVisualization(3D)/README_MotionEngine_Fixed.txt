CogniCoach Motion Engine — Single-file AI-call split edition
===========================================================

Files
-----
motion_engine.py    The entire Python backend in one file.
RagdollTest_AI.html  Existing Unity WebGL visualizer with AI generation controls and fixed keyboard semantics.

What changed
------------
1. The backend stays in one Python file; no imported project-specific Python modules are needed.
2. Motion generation is split into three small structured OpenAI calls:
   - Stage 1: movement director creates seven semantic phases.
   - Stage 2: upper-body specialist generates torso, neck, hand targets and elbow flexion.
   - Stage 3: lower-body specialist generates foot targets, knee flexion and foot-contact flags.
   Stages 2 and 3 run concurrently after Stage 1. The verifier may trigger one targeted segment-repair call.
3. Default OpenAI model is gpt-6-luna. It can be changed with OPENAI_MODEL. Model IDs and prices can change; check current OpenAI API model/pricing docs.
4. The swimming fallback only intervenes when the generated hand or foot path is too static; it avoids unconditionally replacing all the LLM's motion outputs.
5. Position X travel stays a root-position channel and is separate from hip rotation.
6. In the HTML, plain arrow keys rotate the hip by 5 degrees per key press. Shift + arrows translate the whole avatar using 1.0 Unity unit per press. Focusing a text/input field disables these shortcuts to preserve text editing.
7. The Unity WebGL `config` block (canvas sizing/build URLs) was compared with the original HTML and remains unchanged.

Setup (Windows PowerShell)
--------------------------
1. Put motion_engine.py beside your project folder (or run it from any working directory).
2. Install dependencies:
   python -m pip install --upgrade openai fastapi uvicorn numpy pydantic
3. Set your API key in the same PowerShell terminal:
   $env:OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
4. Optionally select another model:
   $env:OPENAI_MODEL="gpt-6-luna"
5. Start the service:
   python motion_engine.py
6. Place RagdollTest_AI.html next to your Unity WebGL Build/ and TemplateData/ folders. Open the HTML and use Generate AI Motion.

Security
--------
Do not put OPENAI_API_KEY in HTML or client-side JavaScript. The key stays in the Python backend.

Notes / limitations
-------------------
- The model is a nominal 1.75-unit human with assumed +X right, +Y up, +Z forward axes. If Unity uses different axes or rotated pivots, adjust MOTION_KNEE_HINGE_SIGN and the kinematic assumptions before judging the result.
- Geometric verification uses the mathematical model, not transforms read back live from Unity. A passing report is not proof of correct sports technique.
- I ran Python syntax checks, JavaScript syntax checks, and stubbed (non-network) pipeline tests. I did not run an authenticated OpenAI API call or a live Unity WebGL session in this environment.
