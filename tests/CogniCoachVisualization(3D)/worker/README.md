# CogniCoach Motion Engine - Cloudflare Worker

The JavaScript port of `motion_engine.py` (script pipeline) and `motion_script.py`, running on the
Cloudflare Workers **free plan**. The Python files are unchanged and still work locally.

## How it is split

| Where | What |
|---|---|
| Worker (`src/index.js`) | access control (site origin or dev code, optional Turnstile), per-IP rate limit, daily cap on model calls, plan cache (per isolate + optional KV), instant phrases, **one gpt-5-mini call** per request, script validation |
| Browser (`dist/motion-compiler.js`) | the compiler: script -> frames. Same code as the Worker (`src/script.js`), loaded by `RagdollTest_AI.html` |

Why the frames are compiled in the browser: a free-plan Worker may use only **10 ms of CPU** per
request, and compiling a long clip takes 15-30 ms on a cold isolate. Waiting for OpenAI does not
count as CPU, so the model call stays on the Worker.

The motion database is exported from Python to `src/data/motion_data.json`: every motion is pre-built
for every parameter value (word parameters: each choice; numbers: a 0.01 / 5-degree grid).

## Files

- `src/rig.js` rig geometry, rotations, splines (from motion_engine.py)
- `src/script.js` parser + compiler (from motion_script.py)
- `src/engine.js` retrieval, prompt, instant phrases, model call (from motion_engine.py)
- `src/db.js`, `src/data/motion_data.json` the database (generated)
- `src/index.js` the Worker; `src/client.js` the browser bundle entry
- `dist/motion-compiler.js` browser bundle (generated, committed so GitHub Pages serves it)
- `test/` Python-vs-JS comparison and timing

## After changing motions or the compiler

Run from `tests/CogniCoachVisualization(3D)`:

```bash
python export_worker_data.py
```

```bash
cd worker && npm install && npm run build:client
```

```bash
python worker/test/make_reference.py && cd worker && npm test
```

`npm test` compiles ~400 scripts in both Python and JS and fails on any difference > 0.5 degrees,
then prints the compile time.

## Deploy

```bash
cd worker && npx wrangler deploy
```

Or connect the repo in the Cloudflare dashboard (Workers & Pages -> cognicoach-motion -> Settings ->
Build -> Connect repository): root directory `tests/CogniCoachVisualization(3D)/worker`, build command
`npm install && npm run build:client`, deploy command `npx wrangler deploy`. Every push to main then deploys.

## Settings

Variables are in `wrangler.toml` (`ALLOWED_ORIGINS`, `RATE_LIMIT_PER_MINUTE`, `DAILY_MODEL_LIMIT`).
Secrets are set in the dashboard (Worker -> Settings -> Variables and Secrets) and never committed:

- `OPENAI_API_KEY` - required for AI requests (instant phrases work without it)
- `DEV_CODE` - other origins and tools send it as the `X-Dev-Code` header; the viewer asks for it off cognicoachai.com
- `TURNSTILE_SECRET` - optional; when set, requests from the site must pass the invisible Turnstile check

Optional KV namespace bound as `MOTION_CACHE` shares the plan cache and the daily counter between isolates.

## API

- `GET /health` version, model, which protections are on
- `POST /generate` `{movement, dominant_side?, extra_instructions?, use_cache?}` -> `{script, title, coaching_cues, camera_view, steps, llm_calls, timing, compile: "client"}`
- `POST /validate` `{script}` -> `{ok, warnings}` or 400 with the error
- `GET /motions` the catalog
- `POST /form-feedback` `{drill, summary, sport?, athlete?, cues?}` -> `{headline, praise, fix, cue, next, model, seconds, tokens}`: the coach note for a camera Form Check. The site sends a text summary of measured movement (never video); one gpt-5-nano call (src/form.js). Own per-IP limit and daily cap (`FORM_DAILY_LIMIT`, default 1000).

The model is fixed to `gpt-5-mini` in `src/engine.js` (not configurable on purpose).
