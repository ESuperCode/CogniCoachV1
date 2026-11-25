You're continuing work on CogniCoach (repo esupercode/cognicoachv1). The site is served by GitHub Pages from `main` at cognicoachai.com/CogniCoachV1/. Develop on branch claude/lucid-turing-6t04xy AND always push finished work to main as well (standing permission: nobody depends on the site yet; I'll report problems and you fix them).

HARD RULES
- OpenAI: only gpt-5-mini. Never switch to a more expensive model.
- The OpenAI key is a network credential for api.openai.com in this cloud environment; code reads OPENAI_API_KEY, so run locally with OPENAI_API_KEY=sk-proxy-injected. Never ask me to paste secrets.
- Cloudflare is on the FREE plan; don't make it paid (Workers free = 10 ms CPU/request; heavy work stays client-side). SQLite Durable Objects are fine.
- Keep requests under 10 s. Don't touch the live `cognicoach-backend` drill Worker unless I ask.
- Deploys go through GitHub Actions (the Cloudflare token in the environment is invalid):
  .github/workflows/deploy-cognicoach-motion.yml and deploy-cognicoach-accounts.yml (run on push to main touching their folder).
  Repo secrets: CLOUDFLARE_API_TOKEN, OPENAI_API_KEY, MOTION_DEV_CODE. Cloudflare account id 00ed78486159dbce2f059215aeee83e9.
- Cache busting: every page links its own CSS/JS with ?v=YYYYMMDDx (currently 20261125b) and scripts/nav.js uses the same tag for the extras it loads. Bump it in all *.html and nav.js whenever CSS/JS changes, or browsers mix old and new files.
- No emoji anywhere: use scripts/icons.js (CogniIcons.svg(name, {size}) or <i data-icon="name" data-size="24"></i> in HTML). Add new icons there.
- Accessibility bar: axe-core clean at phone width on every page, keyboard reachable, honours html.a11y-reduce-motion.

ARCHITECTURE (CogniCoachV1/)
- Pages: index.html (app), dashboard.html, arena.html (League/Friends/Quests/Shop/Bag), competition.html, about.html, contact.html, SEO sport pages. Light theme variables in styles/style.css.
- Nav (scripts/nav.js): text links only (no icons): Dashboard, Arena, Competition Mode, About Us, Contact; at <=900px they fold into a Menu drop-down.
- Loaded on every nav page: scripts/icons.js (first), scripts/nav.js -> extras: a11y.js/.css ("Aa" display & reading panel, skip link), brand3d, account.js (sign-in + cloud sync), tour.js, depth.js/.css (background pointer tilt + card tilt).
- App page: script.js (session flow, prefetch, fires cognicoach:* events: drill-loading, drill-rendered, timer, session-end), motion-viewer.js (3D preview iframe), session-timeline.js, read-aloud.js (Web Speech), session-dock.js (mobile timer bar), coach-adapt.js (readiness check-in + drill ratings -> intensity note on the focus field), coach-mode.js (hands-free full-screen workout, voice commands), session-recap.js (debrief, XP/coins/chests, rank changes).
- Stats: athlete-stats.js (CogniStats: OVR rating, 7 rank tiers Bronze..Legend with divisions + 3 placement sessions, 15 titles, card prefs in dashboard settings), athlete-card.js (3D card, frames incl. shop frames, titles, PNG export), my-stats.js (3D skyline, 3D donut, rating line, rhythm, analysis), dashboard.js / dashboard-plus.js (older dashboard widgets).
- Economy: economy.js (CogniEconomy; localStorage 'cognicoach-wallet', synced like the rest). The currency is called Grit in the UI (amber hexagon icon, CogniIcons 'coin'/'grit'); in code and data it is still wallet.coins / type 'coins'. XP per session stored as record.xp (boosts 2x/3x), Grit, chests wood/silver/gold, shop (freeze, boosts, chests, streak repair, frames neon/carbon/aurora/prism), streak freezes auto-used for missed days, daily XP goal, 3 daily quests. economy-ui.js: HUD (#econHud), chest-opening dialog, toasts. arena.js + styles/arena.css: the Arena page.
- Social client: social.js (CogniSocial) -> accounts Worker /social/*; syncs a public summary + this week's XP (weeks start Monday 00:00 UTC).
- Synced keys (account.js SYNC_KEYS): profile, history, dashboard, competition-notes, motion-saved, wallet.

WORKERS
- Accounts: workers/accounts -> cognicoach-accounts.bodhishanbhag.workers.dev. src/index.js (UserAccount SQLite DO per user: /signup /login /logout /me /profile /password /delete /google /config), src/social.js (one global SocialHub SQLite DO, migration v2: handles, friends-only public profiles, requests, cheers, weekly leagues Amateur..Olympian in groups of 30 with promotion/demotion and one-time podium claims; /social/sync|me|request|respond|remove|find|profile|league|claim|cheer|handle). Tests: test/accounts_test.mjs, test/social_test.mjs (needs ALLOW_TEST_CLOCK=1 in .dev.vars for the week-rollover tests; never set it in production).
- Motion: tests/CogniCoachVisualization(3D)/worker/ -> cognicoach-motion.bodhishanbhag.workers.dev (gpt-5-mini distill/cleanup; rebuild dist with node build_client.mjs; tests in test/run_tests.mjs). Unity WebGL viewer RagdollTest_AI.html embedded with ?embed=1 and driven by postMessage.

LOCAL TESTING (servers die when the container recycles)
- Site: from repo root `python3 -m http.server 8099 --bind 127.0.0.1` -> http://localhost:8099/CogniCoachV1/
- Accounts: in workers/accounts create .dev.vars with ALLOWED_ORIGINS=http://localhost:8099 and ALLOW_TEST_CLOCK=1, run `npx wrangler dev --port 8788`, open the site with ?accountsApi=http://localhost:8788. `node test/social_test.mjs` and `node test/accounts_test.mjs`.
- Motion: NODE_USE_ENV_PROXY=1 NODE_EXTRA_CA_CERTS=/root/.ccr/ca-bundle.crt OPENAI_API_KEY=sk-proxy-injected ALLOWED_ORIGINS=http://localhost:8099 PORT=8787 node test/dev_server.mjs
- Browser tests: preinstalled Playwright/Chromium. Mock Turnstile (window.turnstile with per-widget ids calling window.onTurnstileLoad) and route the drill API (cognicoach-backend.../api/drill) to canned JSON; stub speechSynthesis. axe-core from npm for accessibility. Ignore "gis is not defined" locally.
- The live site (cognicoachai.com) is not reachable from this environment's network.

RECENT STATE (all on main)
- Accessibility pass, read aloud, mobile session dock, Coach Mode, adaptive coach, recap, Athlete Card + ranks/frames/titles, My Stats, background tilt on every page, XP + Grit economy, chests, shop, streak freezes, quests, friends, weekly leagues, Arena page, SVG icons everywhere.
- Economy and leagues trust the client (a determined user can edit localStorage); fine for now, worth hardening (server-side XP checks) if it grows.
- Leagues start empty: groups fill as real users train; no bots.
- Ideas not done yet: friend streaks / friend quests, push or email reminders, league history page, more shop cosmetics (avatar frames, name colours), achievements sync to profile.
