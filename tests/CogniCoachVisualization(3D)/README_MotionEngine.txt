CogniCoach AI Motion Engine — local prototype
================================================

Files
-----
motion_engine.py   All-in-one Python backend: OpenAI planner, path interpolation,
                   two-link inverse kinematics, nominal-model verifier, and repair loop.
RagdollTest_AI.html Your supplied Unity visualizer HTML with a Generate AI Motion control.

Requirements
------------
Python 3.10+ (3.11/3.12 recommended)

Install dependencies in a terminal:
    python -m pip install --upgrade openai fastapi uvicorn numpy pydantic

Set your API key on the server process (do not paste it into the HTML):
PowerShell:
    $env:OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
    $env:OPENAI_MODEL="gpt-6-astra"
    python motion_engine.py

Windows cmd.exe:
    set OPENAI_API_KEY=YOUR_OPENAI_API_KEY
    set OPENAI_MODEL=gpt-6-astra
    python motion_engine.py

If gpt-6-astra is not enabled for your API project, set OPENAI_MODEL to a model ID available
in your API account. The default can also be changed directly near the top of motion_engine.py.

Open the HTML
-------------
Place RagdollTest_AI.html beside the existing Unity WebGL files/folders used by RagdollTest.html,
including Build/ and TemplateData/. The new HTML is a modified copy; it does not contain the Unity
WebGL build itself. Open it the same way you currently open the visualization.

Then:
1. Start motion_engine.py and leave its terminal open.
2. Open RagdollTest_AI.html.
3. Type a movement into Movement prompt.
4. Set duration and the FPS field (default 12), then click Generate AI Motion.
5. The response frames populate the textarea and are sent to Unity. The console has the full plan
   and verification report if you need to debug.

The API listens only on http://127.0.0.1:8000 by default. GET /health can be used to check that the
server is running. POST /generate accepts movement, duration_seconds, playback_fps, dominant_side,
extra_instructions, and repair_attempts.

Important limitations
---------------------
- The OpenAI key stays on the local Python backend. Do not expose it in browser code or commit it.
- The body uses nominal proportions for a 1.75-unit human: upper arm 0.315, forearm 0.285,
  thigh 0.425, shin 0.425 units. These are initial estimates only.
- Axes are assumed +X = avatar right, +Y = up, +Z = forward, with Unity's documented Z-X-Y
  Euler rotation order approximated by the internal math. Calibrate this against your WebBridge.
- The HTML adds parent/child Euler components. This is not exact 3D rotation composition. The
  compiled JSON uses the same additive convention, but complex compound rotations can differ from
  the Unity rig's real transform behavior.
- The verifier uses the nominal mathematical skeleton. It does NOT read actual Unity transforms,
  prove physical balance, or certify that a sports technique is correct. Use it to find rough target,
  continuity and reach problems, then calibrate with the real rig and reference motions.
- This is a prototype. Some target paths may be unreachable and repairs may not fix them. Inspect
  the verifier report and the rendered animation before using a motion as a coaching example.
- CORS is open for this local prototype. Before public deployment, restrict allowed origins, add
  authentication/rate limits, and move API keys to a properly secured server environment.
