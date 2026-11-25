// ==========================================================================
// Guided tour of the app page (index.html), shown on a device's first visit.
//
// 1. Welcome card - also the first-run setup (main sport, date of birth) with sign in /
//    Google sign in, replacing the old separate "Welcome" modal.
// 2. Setup: Quick Start, its fields, the Start button, Advanced Setup.
// 3. A demo first drill (nothing is generated or saved): the drill card, the muscle map, the 3D
//    Motion Preview playing a ready-made animation, its controls, the timer.
// 4. Dashboard + account in the nav, then a finale.
// Replay: index.html?tour=1 (account menu -> Take the tour).
//
// Page tours: the Dashboard and the Arena have their own short tours (PAGE_TOURS) that switch tabs
// as they explain them (window.CogniTabs from dash-tabs.js / arena.js). They run the first time a
// page is opened, from its "Tour this page" button, or with ?tour=1 on that page.
// ==========================================================================
(function () {
    'use strict';
    var DONE_KEY = 'cognicoach-tour-done';
    if (window.CogniTour) { return; }

    // Ready-made demo drills (scripts compiled locally by the 3D viewer - no AI call).
    var DEMOS = {
        basketball: { name: 'Defensive Slide to Closeout', focus: 'Agility',
            description: 'From a low defensive stance, slide three steps to your right, sprint forward and close out with high hands, then backpedal to the start.',
            muscles: ['quads', 'glutes', 'calves', 'adductors'],
            script: 'wide_defensive_stance(bounce=on, hold=0.4)\nshuffle(times=3)\nrun(pace=sprint, times=1)\njump + arms_up_block(hold=0.5)\nbackpedal(times=2)',
            cues: ['Sits in a low defensive stance', 'Slides laterally with quick steps', 'Sprints forward into a closeout with hands high', 'Backpedals to the start'] },
        soccer: { name: 'Cone Dribble and Finish', focus: 'Ball Control',
            description: 'Dribble through the cones with small touches, accelerate past the last cone and strike the ball with your laces.',
            muscles: ['quads', 'hamstrings', 'calves', 'abs'],
            script: 'foot_dribble(times=3)\nrun(pace=sprint, times=1)\ninstep_kick(power=full)',
            cues: ['Dribbles with quick close touches', 'Accelerates past the last cone', 'Strikes the ball with the laces'] },
        tennis: { name: 'Split Step to Forehand', focus: 'Footwork',
            description: 'Split step as the feed comes, move to your right and hit a forehand crosscourt, then shuffle back to the center.',
            muscles: ['quads', 'obliques', 'deltoids', 'forearms'],
            script: 'split_step\nshuffle(times=1)\nstance(width=wide, depth=0.4) + forehand_swing\nshuffle(side=left, times=1)',
            cues: ['Split steps as the ball is fed', 'Moves right into a wide stance', 'Swings a forehand crosscourt', 'Shuffles back to the center'] },
        swimming: { name: 'Freestyle with Streamline Kick', focus: 'Technique',
            description: 'Swim two strokes of freestyle, then push into a tight streamline and flutter kick.',
            muscles: ['lats', 'deltoids', 'triceps', 'abs', 'glutes'],
            script: 'front_crawl(times=2)\nflutter_kick(times=2)\nstreamline(hold=0.6)',
            cues: ['Swims freestyle strokes', 'Flutter kicks in a streamline', 'Holds a tight streamline glide'] },
        other: { name: 'Sprint Start Acceleration', focus: 'Speed',
            description: 'Set in a crouched start, drive out explosively for 10 meters and rise into an upright sprint.',
            muscles: ['quads', 'hamstrings', 'glutes', 'calves'],
            script: 'blocks_on_your_marks(hold=0.8)\nblocks_set(hold=0.6)\nsprint_start\nrun(pace=sprint, times=2)',
            cues: ['Sets in a crouched start', 'Drives out low and explosively', 'Rises into an upright sprint'] }
    };

    var STEPS = [
        { kind: 'hero', id: 'welcome' },
        { target: '#quickStartCard', group: ['#quickStartCard .quick-start-header', '#sportSwitcher'], title: 'Quick Start',
          text: 'The fastest way to train. CogniCoach remembers your sport and level, so most days this is all you touch.' },
        { target: '#quickStartCard .qs-length', group: ['#quickStartCard .qs-length', '#qsDetails'], title: 'How long, where, what',
          text: 'Tap how many minutes you have. Edit tells it where you are and what to work on - the AI plans every drill to fit.' },
        { target: '#readinessCheck', title: 'Your coach listens',
          text: 'Tell CogniCoach how you feel today. Low energy gets you easier drills, fired up gets harder ones. During a session, rate each drill and the next ones adjust.' },
        { target: '#quickStartBtn', title: 'One tap to train',
          text: 'Press Start and the AI builds your session drill by drill. While you do one drill, the next is already being prepared.' },
        { target: '#advancedSetup', title: 'Build my own plan',
          text: 'Pick muscle groups, set your level, or drag drills into your own warm-up, main work and cool-down timeline.' },
        { demo: 'enter', target: '#drillContent .drill-display', title: 'Inside a session',
          text: "Here's a sample drill. Each one tells you exactly what to do and what it focuses on." },
        { demo: true, target: '#coachModeBtn', title: 'Coach Mode',
          text: 'Go hands-free: a full-screen timer you can see across the gym. It reads each drill, counts you in, calls halfway and time, rests you and moves on. You can even say "pause", "next" or "too easy".' },
        { demo: true, target: '#drillContent .ra-bar', title: 'Hear it instead',
          text: 'Read aloud speaks the drill and highlights each sentence, so you can keep your eyes on the ball. The Aa button at the top sets text size, contrast, voice and speed.' },
        { demo: true, target: '#sessionTimeline', title: 'Your whole session',
          text: 'Your timeline from warm-up to cool-down: finished drills get a check, the one you are on fills up as its timer runs, and All drills lists everything ahead.' },
        { demo: true, target: '#drillContent .muscle-groups', title: 'Muscles worked',
          text: 'The muscles each drill trains light up on the body map. Tap any muscle to adjust it.' },
        { demo: 'play', target: '#motionViewer .motion-stage', title: 'Watch it in 3D',
          text: 'Generate Animation turns any drill into a 3D demonstration. Here is this drill - no waiting.' },
        { demo: 'controls', target: '#motionViewer', group: ['#motionViewer .motion-controls', '#motionViewer .motion-help'], title: 'Make it yours',
          text: 'Pause, scrub frame by frame, flip between right- and left-handed, and click the athlete then use the arrow keys to turn it.' },
        { demo: true, target: '#drillContent .timer-container', title: 'Timed for you',
          text: 'Start the timer when you are ready. Each drill is sized to fit your session, and Next Drill appears when it is done.' },
        { target: 'site-nav a[href="dashboard.html"]', smallTarget: '#navMenuBtn', nav: true, title: 'Your dashboard',
          text: 'Your streak, Athlete Card, stats and past sessions. The first time you open it, a short tour shows you around.' },
        { target: 'site-nav a[href="arena.html"]', smallTarget: '#navMenuBtn', nav: true, title: 'The Arena',
          text: 'Daily quests, the shop, weekly leagues and friends. Every session earns XP and Grit to spend there, and it has its own quick tour too.' },
        { target: '#navAccount', nav: true, title: 'Sync everywhere',
          text: 'With a free account your profile and training follow you to every device you sign in on.' },
        { kind: 'hero', id: 'finale', title: "You're all set",
          text: 'Pick a sport, press Start, and your first drill is on its way.' }
    ];

    // First visit: a short tour of just what is needed to train. The session features are shown
    // in context the first time a real drill opens (SESSION_STEPS). ?tour=1 replays the full tour.
    var SHORT_STEPS = [
        { kind: 'hero', id: 'welcome' },
        { target: '#quickStartCard', group: ['#sportSwitcher', '#quickStartCard .qs-length'], title: 'Pick your sport and time',
          text: 'That is all CogniCoach needs. Edit adds where you are and what to work on - it is optional.' },
        { target: '#readinessCheck', title: 'How do you feel?',
          text: 'Optional. Low energy gets you easier drills, fired up gets harder ones.' },
        { target: '#quickStartBtn', title: 'Press Start',
          text: 'Your coach builds the session drill by drill. The first time, we will point out the tools on the drill screen.' },
        { target: 'site-nav a[href="dashboard.html"]', smallTarget: '#navMenuBtn', nav: true, title: 'After you train',
          text: 'Dashboard shows your progress. Arena has daily quests and rewards. Both are in the menu.' },
        { kind: 'hero', id: 'finale', title: "You're all set",
          text: 'Pick your time, press Start, and your first drill is on its way.' }
    ];
    var SESSION_KEY = 'cognicoach-tour-session-done';
    var SESSION_STEPS = [
        { target: '#drillContent .drill-display', title: 'Your first drill',
          text: 'Read what to do here, or press Read aloud to hear it.' },
        { target: '#drillContent .timer-container', title: 'Start when ready',
          text: 'The timer is sized to fit your session. When it ends, Next Drill appears.' },
        { target: '#drillContent .adapt-feedback', title: 'Tell your coach',
          text: 'Too hard or too easy? Tap it and the next drills adjust.' },
        { target: '#coachModeBtn', title: 'Coach Mode',
          text: 'Hands-free and full screen: it reads each drill, counts you in, times it and moves on.' },
        { target: '#motionViewer', title: 'Watch it in 3D',
          text: 'Not sure how a drill looks? Generate Animation shows a 3D athlete doing it.' }
    ];

    // ---- page tours (dashboard.html, arena.html) ----
    var PAGE_TOURS = {
        dashboard: { key: 'cognicoach-tour-dashboard-done', steps: [
            { kind: 'hero', id: 'page-intro', title: 'Your dashboard', next: 'Show me around',
              text: 'Everything about your training lives here, split into five tabs so you only see one thing at a time.' },
            { target: '#econHud', title: 'Your day in one line',
              text: 'Your streak (and Streak Freezes), your Grit, today’s XP goal and any chests to open. Tap one to jump to the Arena.' },
            { target: '.page-tabs', title: 'Five tabs',
              text: 'Home is today. Card is your Athlete Card. Stats has charts. History lists past sessions and badges. Settings holds your profile and data.' },
            { tab: 'home', target: '#dashWelcome', title: 'Home',
              text: 'Start here: what to do next, with one tap to start training or check your quests.' },
            { tab: 'home', target: '#dashOverview', title: 'At a glance',
              text: 'This week’s sessions and minutes, your streak and favourite sport. Your level and weekly goal are just below.' },
            { tab: 'card', target: '#athleteCard .ac-card', title: 'Your Athlete Card',
              text: 'Your overall rating and rank. Three sessions get you ranked, and climbing ranks unlocks new card frames.' },
            { tab: 'card', target: '#athleteCard .ac-pick', title: 'Make it yours',
              text: 'Choose the frame and title your friends see. Frames you buy in the shop show up here too.' },
            { tab: 'stats', target: '#myStatsMount', group: ['#myStats .ms-head', '#myStats .ms-kpis'], title: 'Stats',
              text: 'Charts and a written analysis of your training. Pick a time range, drag the 3D charts to turn them, or press Table for the numbers.' },
            { tab: 'history', target: '#dashSessions', title: 'History',
              text: 'Every session you have finished, filterable by sport. Your streak calendar and badges are further down.' },
            { tab: 'settings', target: '#profileSummaryCard', title: 'Settings',
              text: 'Your sport, level and training preferences, your account, and backup or restore of your data.' },
            { kind: 'hero', id: 'finale', title: 'Next stop: the Arena', cta: 'Show me the Arena', href: 'arena.html?tour=1', home: 'home',
              text: 'Daily quests, the shop and weekly leagues with friends. Want a quick look?' }
        ] },
        arena: { key: 'cognicoach-tour-arena-done', steps: [
            { kind: 'hero', id: 'page-intro', title: 'Welcome to the Arena', next: 'Show me around',
              text: 'Training earns XP and Grit. The Arena is where you use them: daily quests, the shop, weekly leagues and friends.' },
            { target: '#arenaHud', title: 'Your streak, Grit and goal',
              text: 'The same strip you see on every page. The ring fills with today’s XP; the chest shows rewards waiting for you.' },
            { target: '.page-tabs', title: 'Four tabs',
              text: 'Quests for today’s goals, League for this week’s competition, Friends to train together, and Shop for your bag and items.' },
            { tab: 'quests', target: '#panel-quests .qs-goal', title: 'Daily goal',
              text: 'Fill the ring with XP from training to earn a chest. Tap Change to pick an easier or harder goal.' },
            { tab: 'quests', target: '#panel-quests .qs-list', title: 'Daily quests',
              text: 'Three new quests every day. When one is done, press its button to collect the Grit. Finish all three for a Silver Chest.' },
            { tab: 'quests', target: '#panel-quests .qs-streak', title: 'Keep your streak',
              text: 'Train every day to grow your streak. A Streak Freeze covers a day off so it doesn’t reset.' },
            { tab: 'league', target: '#panel-league', title: 'Weekly league',
              text: 'With a free account you join a group of up to 30 athletes. Earn the most XP this week to move up a league, from Amateur to Olympian.' },
            { tab: 'friends', target: '#panel-friends', title: 'Friends',
              text: 'Add friends by their @handle, compare weekly XP, see each other’s Athlete Cards and send a cheer.' },
            { tab: 'shop', target: '#panel-shop .bg-list', title: 'Your bag',
              text: 'Chests to open, boosts to switch on, your Streak Freezes and frames. Switch on Double XP right before you train.' },
            { tab: 'shop', target: '#panel-shop .sh-grid', group: ['#panel-shop .sh-grid .sh-item:nth-child(1)', '#panel-shop .sh-grid .sh-item:nth-child(2)'], title: 'The shop',
              text: 'Spend Grit on Streak Freezes, XP Boosts, chests and card frames.' },
            { kind: 'hero', id: 'finale', title: 'Go earn some Grit', cta: 'Start training', href: 'index.html', home: 'quests',
              text: 'Every session you finish fills your goal, moves your quests forward and climbs your league.' }
        ] }
    };
    function pageName() {
        if ($('#quickStartCard')) { return 'app'; }
        if ($('#panel-home') && $('.page-tabs')) { return 'dashboard'; }
        if ($('main.arena')) { return 'arena'; }
        return '';
    }
    var page = '';   // set when a tour starts
    var fullTour = false;   // ?tour=1 / account menu: the full tour with the demo drill
    function doneKey() { return page === 'session' ? SESSION_KEY : page && page !== 'app' ? PAGE_TOURS[page].key : DONE_KEY; }

    var plan = [];   // the tour's steps, fixed when it starts (targets hide during the demo)
    var root, spot, card, idx = 0, active = false, repositionRaf = 0, inDemo = false, demoPlayed = false, needsSetup = false;

    function $(sel) { try { return document.querySelector(sel); } catch (e) { return null; } }
    function esc(t) { return String(t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

    function visible(el) {
        if (!el) { return false; }
        var r = el.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    }

    function profile() { try { return typeof loadProfile === 'function' ? loadProfile() : {}; } catch (e) { return {}; } }

    function demoDrill() {
        var sport = String(profile().defaultSport || '').toLowerCase();
        return DEMOS[sport] || DEMOS.other;
    }

    // Steps whose target is missing are skipped (demo steps are checked after the demo opens).
    function steps() { return plan; }

    function computeSteps() {
        // On small screens the nav links live in the Menu drop-down: point those steps at the Menu button.
        var small = window.matchMedia && window.matchMedia('(max-width: 900px)').matches;
        var source = page === 'session' ? SESSION_STEPS : page && page !== 'app' ? PAGE_TOURS[page].steps : (fullTour ? STEPS : SHORT_STEPS);
        return source.map(function (s) {
            if (small && s.smallTarget) { var c = {}; Object.keys(s).forEach(function (k) { c[k] = s[k]; }); c.target = s.smallTarget; return c; }
            return s;
        }).map(function (s) {
            if (s.alt && !$(s.target) && $(s.alt)) { var c = {}; Object.keys(s).forEach(function (k) { c[k] = s[k]; }); c.target = s.alt; return c; }
            return s;
        }).filter(function (s) {
            if (!s.target || s.demo || s.nav || s.tab) { return true; }   // tab steps are checked when shown
            return visible($(s.target));
        });
    }

    function rectFor(step) {
        var els = (step.group || [step.target]).map($).filter(visible);
        if (!els.length && step.group) { els = [$(step.target)].filter(visible); }
        if (!els.length) { return null; }
        var r = els.reduce(function (acc, el) {
            var b = el.getBoundingClientRect();
            var g = el.closest && el.closest('.form-group');
            if (g && step.group && /^(INPUT|SELECT|TEXTAREA)$/.test(el.tagName)) { b = g.getBoundingClientRect(); }
            return acc ? { left: Math.min(acc.left, b.left), top: Math.min(acc.top, b.top),
                right: Math.max(acc.right, b.right), bottom: Math.max(acc.bottom, b.bottom) } :
                { left: b.left, top: b.top, right: b.right, bottom: b.bottom };
        }, null);
        var pad = 10;
        return { left: r.left - pad, top: r.top - pad, width: r.right - r.left + 2 * pad, height: r.bottom - r.top + 2 * pad };
    }

    // ------------------------------------------------------------------ demo session
    function enterDemo() {
        if (inDemo) { return; }
        var d = demoDrill();
        inDemo = true;
        var setup = $('#setupView'), intro = $('#marketingIntro'), session = $('#sessionView');
        if (setup) { setup.style.display = 'none'; }
        if (intro) { intro.classList.add('hidden'); }
        if (session) { session.classList.add('active'); }
        var loading = $('#loadingContainer'); if (loading) { loading.classList.remove('active'); }
        var content = $('#drillContent'); if (content) { content.classList.remove('hidden'); }
        var set = function (sel, text) { var el = $(sel); if (el) { el.textContent = text; } };
        set('#currentDrill', '3');
        set('#totalDrills', '8');
        if (window.CogniSessionTimeline) {
            var secs = (typeof appState !== 'undefined' && appState.setup && appState.setup.sections) ||
                [{ name: 'Warm Up', color: '#FFD700' }, { name: 'Main Work', color: '#FF6347' }, { name: 'Cool Down', color: '#4682B4' }, { name: 'Recovery', color: '#32CD32' }];
            var dd = function (section, min, name) {
                return { section: section, sectionName: secs[section].name, drillTime: min * 60, generatedDrill: name ? { name: name } : null };
            };
            window.CogniSessionTimeline.demo({
                sections: secs, index: 2, started: true, remaining: 190, total: 300,
                drills: [dd(0, 4, 'Dynamic Warm-Up'), dd(0, 3, 'Activation Skips'), dd(1, 5, d.name), dd(1, 5, 'Reaction Sprints'),
                    dd(1, 6, null), dd(1, 5, null), dd(2, 4, null), dd(3, 3, null)]
            });
        }
        set('#drillName', d.name);
        set('#drillFocus', 'Focus: ' + d.focus);
        var desc = $('#drillDescription'); if (desc) { desc.textContent = d.description; }
        set('#timerDisplay', '05:00');
        set('#timerStatus', "Drill loaded. Start when you're ready.");
        var bar = $('#timerProgressBar'); if (bar) { bar.style.width = '0%'; }
        try { if (typeof highlightMuscles === 'function') { highlightMuscles(d.muscles); } } catch (e) {}
        var next = $('#nextDrillContainer'); if (next) { next.style.display = 'none'; }
    }

    function playDemo() {
        if (demoPlayed || !window.CogniMotionViewer || !window.CogniMotionViewer.demo) { return; }
        demoPlayed = true;
        var d = demoDrill();
        window.CogniMotionViewer.demo({ script: d.script, title: d.name, coaching_cues: d.cues, camera_view: 'three_quarter', compile: 'client' });
    }

    function exitDemo() {
        if (!inDemo) { return; }
        inDemo = false;
        demoPlayed = false;
        if (window.CogniMotionViewer && window.CogniMotionViewer.endDemo) { window.CogniMotionViewer.endDemo(); }
        if (window.CogniSessionTimeline) { window.CogniSessionTimeline.endDemo(); }
        try { if (typeof resetMuscleSelections === 'function') { resetMuscleSelections(); } } catch (e) {}
        var session = $('#sessionView'), setup = $('#setupView'), intro = $('#marketingIntro'), content = $('#drillContent');
        if (session) { session.classList.remove('active'); }
        if (content) { content.classList.add('hidden'); }
        if (setup) { setup.style.display = 'block'; }
        if (intro) { intro.classList.remove('hidden'); }
    }

    // ------------------------------------------------------------------ welcome card (setup form)

    // The welcome card: create an account (its form asks for main sport + date of birth),
    // continue with Google, sign in - or just take the tour.
    function welcomeBody() {
        var signedIn = window.CogniAccount && window.CogniAccount.session();
        var p = profile(), chosen = p.defaultSport || '';
        var sports = (typeof PROFILE_SPORTS !== 'undefined' && PROFILE_SPORTS) || ['Basketball', 'Soccer', 'Tennis', 'Football', 'Baseball', 'Volleyball', 'Swimming', 'Cricket', 'Rugby', 'Golf'];
        var pickHtml = '<div class="tour-sports" role="group" aria-label="Your main sport">' + sports.map(function (sp) {
            return '<button type="button" class="tour-sport" data-t="sport" data-sport="' + esc(sp) + '" aria-pressed="' + (sp === chosen ? 'true' : 'false') + '">' + esc(sp) + '</button>';
        }).join('') + '</div><p class="tour-sport-note">Not listed? Pick any and type yours on Quick Start.</p>';
        var html = '<h2 class="tour-title" id="tourTitle">Welcome to CogniCoachAI</h2>' +
            '<p class="tour-text">Your free AI coach. Tell it your sport and time, and it plans every drill.</p>' +
            '<p class="tour-q">What sport do you train?</p>' + pickHtml;
        if (!signedIn) {
            html += '<div class="tour-join">' +
                '  <p class="tour-have">Save progress on every device: <button type="button" class="tour-link" data-t="create">Create free account</button> or <button type="button" class="tour-link" data-t="signin">Sign in</button></p>' +
                '  <div class="tour-google" id="tourGoogle"></div>' +
                '</div>';
        }
        return html;
    }

    // Taking the tour without an account still counts as finishing the first-run setup
    // (the sport can be picked on Quick Start any time).
    function saveWelcome() {
        if (needsSetup && typeof completeOnboarding === 'function' && !profile().onboarded) { completeOnboarding('', ''); }
        needsSetup = false;
    }

    // ------------------------------------------------------------------ UI
    function build() {
        root = document.createElement('div');
        root.className = 'tour-root';
        root.innerHTML =
            '<div class="tour-spot"></div>' +
            '<div class="tour-card" role="dialog" aria-live="polite" aria-labelledby="tourTitle">' +
            '  <div class="tour-stage" aria-hidden="true">' +
            '    <div class="stage-floor"></div>' +
            '    <div class="tour-brand"></div>' +
            '  </div>' +
            '  <div class="tour-step-num"></div>' +
            '  <div class="tour-body"></div>' +
            '  <div class="tour-dots"></div>' +
            '  <div class="tour-actions">' +
            '    <button type="button" class="tour-skip" data-t="skip">Skip tour</button>' +
            '    <span class="tour-spacer"></span>' +
            '    <button type="button" class="tour-back" data-t="back">Back</button>' +
            '    <button type="button" class="btn btn-primary tour-next" data-t="next">Next</button>' +
            '  </div>' +
            '</div>';
        document.body.appendChild(root);
        spot = root.querySelector('.tour-spot');
        card = root.querySelector('.tour-card');
        if (window.CogniBrand) { window.CogniBrand.mount(root.querySelector('.tour-brand')); }
        root.addEventListener('click', function (e) {
            var b = e.target.closest('[data-t]');
            if (!b) { return; }
            var t = b.getAttribute('data-t');
            if (t === 'sport') {
                var sp = b.getAttribute('data-sport');
                if (typeof completeOnboarding === 'function') { completeOnboarding(sp, ''); }
                else if (typeof setDefaultSport === 'function') { setDefaultSport(sp, false); }
                needsSetup = false;
                window.__quickStartSportOverride = null;
                if (typeof refreshQuickStartUI === 'function') { refreshQuickStartUI(); }
                root.querySelectorAll('.tour-sport').forEach(function (x) { x.setAttribute('aria-pressed', x === b ? 'true' : 'false'); });
                var nb = root.querySelector('.tour-next'); if (nb) { nb.disabled = false; nb.focus(); }
                return;
            }
            if (t === 'next') { next(); }
            else if (t === 'back') { go(idx - 1); }
            else if (t === 'signin') { if (window.CogniAccount) { window.CogniAccount.open('login'); } }
            else if (t === 'create') { if (window.CogniAccount) { window.CogniAccount.open('signup'); } }
            else { skip(); }
        });
        document.addEventListener('keydown', onKey);
        window.addEventListener('resize', schedulePosition);
        window.addEventListener('scroll', schedulePosition, { passive: true });
        window.addEventListener('cognicoach:account', function (e) {
            if (!active || !e.detail || !e.detail.signedIn) { return; }
            // signed in from the welcome card: their saved profile came with the account
            needsSetup = false;
            if (idx === 0) { go(1); }
        });
    }

    function onKey(e) {
        if (!active || document.getElementById('accountModal')) { return; }
        var typing = e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName);
        if (e.key === 'Escape') { skip(); }
        else if (!typing && (e.key === 'ArrowRight' || e.key === 'Enter')) { e.preventDefault(); next(); }
        else if (!typing && e.key === 'ArrowLeft') { e.preventDefault(); go(idx - 1); }
    }

    function schedulePosition() {
        if (!active) { return; }
        cancelAnimationFrame(repositionRaf);
        repositionRaf = requestAnimationFrame(position);
    }

    function position() {
        var list = steps(), step = list[idx];
        if (!step) { return; }
        var mobile = window.innerWidth < 640;
        if (!step.target) {
            spot.classList.add('center');
            spot.style.cssText = 'left:50%;top:50%;width:0;height:0;';
            card.classList.add('centered');
            card.classList.remove('docked');
            card.style.left = ''; card.style.top = '';
            return;
        }
        var r = rectFor(step);
        if (!r) { return; }
        spot.classList.remove('center');
        card.classList.remove('centered');
        spot.style.left = r.left + 'px';
        spot.style.top = r.top + 'px';
        spot.style.width = r.width + 'px';
        spot.style.height = r.height + 'px';
        if (mobile) { card.style.left = ''; card.style.top = ''; card.classList.add('docked'); return; }
        card.classList.remove('docked');
        var cw = card.offsetWidth, ch = card.offsetHeight, gap = 18, vw = window.innerWidth, vh = window.innerHeight;
        if (r.height > vh * 0.6) {
            card.style.left = (vw - cw - 20) + 'px';
            card.style.top = (vh - ch - 20) + 'px';
            return;
        }
        var top = r.top + r.height + gap, place = 'below';
        if (top + ch > vh - 12) { top = r.top - ch - gap; place = 'above'; }
        if (top < 12) {
            top = Math.max(12, Math.min(vh - ch - 12, r.top));
            place = r.left + r.width + gap + cw < vw ? 'right' : 'left';
        }
        var left;
        if (place === 'right') { left = r.left + r.width + gap; }
        else if (place === 'left') { left = Math.max(12, r.left - cw - gap); }
        else { left = Math.max(12, Math.min(vw - cw - 12, r.left + r.width / 2 - cw / 2)); }
        card.style.left = left + 'px';
        card.style.top = top + 'px';
    }

    function next() {
        var step = steps()[idx];
        if (step && step.id === 'welcome') { saveWelcome(); }
        go(idx + 1);
    }

    function skip() {
        saveWelcome();   // skipping still finishes the first-run setup
        finish(true);
    }

    function go(n) {
        var list = steps();
        if (n >= list.length) { finish(false); return; }
        if (n < 0) { return; }
        var dir = n >= idx ? 1 : -1;
        idx = n;
        var step = list[idx];
        if (step.tab && window.CogniTabs) { window.CogniTabs.select(step.tab); }
        if (step.home && window.CogniTabs) { window.CogniTabs.select(step.home); }
        if (step.tab && !visible($(step.target))) {   // e.g. a card that needs history: skip it
            var t = n + dir;
            if (t >= 0 && t < list.length) { go(t); return; }
        }
        if (step.demo) { enterDemo(); } else if (inDemo) { exitDemo(); }
        if (step.demo === 'play') { playDemo(); }

        card.classList.remove('enter');
        void card.offsetWidth;
        card.classList.add('enter');
        var hero = step.kind === 'hero';
        card.classList.toggle('hero', hero);
        card.classList.toggle('with-form', step.id === 'welcome');
        var body = card.querySelector('.tour-body');
        body.innerHTML = step.id === 'welcome' ? welcomeBody() :
            '<h2 class="tour-title" id="tourTitle">' + esc(step.title) + '</h2><p class="tour-text">' + esc(step.text) + '</p>';
        if (step.id === 'welcome' && window.CogniAccount && window.CogniAccount.renderGoogleButton) {
            var g = card.querySelector('#tourGoogle');
            if (g) { window.CogniAccount.renderGoogleButton(g); }
        }
        var numbered = list.filter(function (x) { return x.kind !== 'hero'; });
        card.querySelector('.tour-step-num').textContent = hero ? '' : ('Step ' + (numbered.indexOf(step) + 1) + ' of ' + numbered.length);
        card.querySelector('.tour-dots').innerHTML = list.map(function (s, i) { return '<i class="' + (i === idx ? 'on' : i < idx ? 'done' : '') + '"></i>'; }).join('');
        card.querySelector('.tour-back').style.visibility = idx > 0 ? 'visible' : 'hidden';
        var nextBtn = card.querySelector('.tour-next');
        nextBtn.textContent = step.id === 'welcome' ? "Let's go" :
            step.next ? step.next : step.id === 'finale' ? (step.cta || 'Start training') : (page === 'session' && idx === list.length - 1 ? 'Got it' : 'Next');
        nextBtn.disabled = false;
        card.querySelector('.tour-skip').textContent = step.id === 'finale' && step.href && page !== 'app' ? 'Done' : page === 'session' ? 'Skip tips' : 'Skip tour';
        card.querySelector('.tour-skip').style.visibility = step.id === 'finale' && !(step.href && page !== 'app') ? 'hidden' : 'visible';

        if (step.target) {
            var el = $(step.target);
            if (step.nav) {
                window.scrollTo({ top: 0, behavior: 'smooth' });
                var nav = document.getElementById('siteNav');
                if (nav) { nav.classList.remove('nav-hidden'); }
            } else if (el) {
                var rr = rectFor(step);   // the highlighted area, which may be part of the element
                var b = rr ? { top: rr.top, height: rr.height } : el.getBoundingClientRect();
                var mobile = window.innerWidth < 640;
                var h = Math.min(b.height, window.innerHeight * 0.6);
                var want = mobile ? 80 : Math.max(90, (window.innerHeight - h) / 2 - 70);
                window.scrollTo({ top: Math.max(0, window.scrollY + b.top - want), behavior: 'smooth' });
            }
            var t0 = performance.now();
            (function follow() {
                position();
                if (performance.now() - t0 < 1000 && active) { requestAnimationFrame(follow); }
            })();
        } else {
            window.scrollTo({ top: 0, behavior: 'smooth' });
            position();
        }
        var focusEl = card.querySelector('.tour-sport[aria-pressed="true"]') || card.querySelector('.tour-next');
        if (focusEl) { focusEl.focus({ preventScroll: true }); }
    }

    function finish(skipped) {
        var last = steps()[idx];
        active = false;
        exitDemo();
        try { localStorage.setItem(doneKey(), JSON.stringify({ at: Date.now(), skipped: !!skipped })); } catch (e) {}
        if (page === 'session') {
            if (root) { root.classList.remove('show'); }
            document.documentElement.classList.remove('tour-on');
            var sr = root; root = null;
            setTimeout(function () { if (sr) { sr.remove(); } }, 350);
            var sb = $('#startTimerBtn'); if (sb && visible(sb)) { sb.focus({ preventScroll: true }); sb.scrollIntoView({ behavior: 'smooth', block: 'center' }); }
            return;
        }
        if (page && page !== 'app') {
            if (root) { root.classList.remove('show'); }
            document.documentElement.classList.remove('tour-on');
            var pr = root; root = null;
            setTimeout(function () { if (pr) { pr.remove(); } }, 350);
            window.scrollTo({ top: 0, behavior: 'smooth' });
            if (!skipped && last && last.href) { setTimeout(function () { location.href = last.href; }, 250); }
            return;
        }
        if (root) { root.classList.remove('show'); }
        document.documentElement.classList.remove('tour-on');
        var r = root;
        root = null;
        setTimeout(function () { if (r) { r.remove(); } }, 350);
        window.scrollTo({ top: 0, behavior: 'smooth' });
        if (!skipped) {
            var btn = $('#quickStartBtn');
            if (btn && visible(btn)) {
                setTimeout(function () { btn.scrollIntoView({ behavior: 'smooth', block: 'center' }); }, 200);
                btn.classList.add('tour-glow');
                setTimeout(function () { btn.classList.remove('tour-glow'); }, 3200);
            }
        }
    }

    function start(opts) {
        if (active) { return; }
        opts = opts || {};
        page = opts.session ? 'session' : pageName();
        if (!page) { return; }
        fullTour = !!opts.full;
        if (page === 'session') {
            needsSetup = false;
            plan = computeSteps();
            if (!plan.length) { return; }
            build();
            active = true;
            idx = 0;
            document.documentElement.classList.add('tour-on');
            requestAnimationFrame(function () { root.classList.add('show'); go(0); });
            return;
        }
        if (page !== 'app') {
            needsSetup = false;
            plan = computeSteps();
            build();
            active = true;
            idx = 0;
            document.documentElement.classList.add('tour-on');
            requestAnimationFrame(function () { root.classList.add('show'); go(0); });
            return;
        }
        var setup = $('#setupView');
        if (setup && getComputedStyle(setup).display === 'none') {   // mid-session: setup only, no tour
            if (!profile().onboarded && typeof completeOnboarding === 'function') { /* answered next visit */ }
            return;
        }
        needsSetup = !profile().onboarded;
        plan = computeSteps();
        build();
        active = true;
        idx = 0;
        document.documentElement.classList.add('tour-on');
        requestAnimationFrame(function () { root.classList.add('show'); go(0); });
    }

    function seen(key) { try { return !!localStorage.getItem(key || DONE_KEY); } catch (e) { return true; } }

    function startWhenClear(delay, opts) {
        var tries = 0;
        (function wait() {
            if ($('#profileModalOverlay') || $('#accountModal')) {
                if (++tries < 600) { setTimeout(wait, 400); }
                return;
            }
            setTimeout(function () {
                if ($('#profileModalOverlay') || $('#accountModal')) { wait(); return; }
                start(opts);
            }, delay);
        })();
    }

    window.CogniTour = { start: function (o) { startWhenClear(200, o); }, reset: function () { try { localStorage.removeItem(DONE_KEY); localStorage.removeItem(SESSION_KEY); } catch (e) {} } };

    // Skipping the first tour means "no tours please": the other pages then wait for their
    // "Tour this page" button instead of starting on their own.
    function skippedMain() { try { var v = JSON.parse(localStorage.getItem(DONE_KEY) || 'null'); return !!(v && v.skipped); } catch (e) { return false; } }

    // Session tips: the first time a real drill is on screen.
    document.addEventListener('cognicoach:drill-rendered', function () {
        if (active || seen(SESSION_KEY) || skippedMain()) { return; }
        try { localStorage.setItem(SESSION_KEY, JSON.stringify({ at: Date.now(), pending: true })); } catch (e) {}
        setTimeout(function () { startWhenClear(0, { session: true }); }, 700);
    });

    // "Tour this page" buttons
    document.addEventListener('click', function (e) {
        var b = e.target.closest && e.target.closest('[data-page-tour]');
        if (b) { e.preventDefault(); startWhenClear(50); }
    });

    function init() {
        var pn = pageName();
        if (!pn) { return; }
        var forced = new URLSearchParams(location.search).get('tour') === '1';
        if (pn !== 'app') {
            if (forced) {
                try { history.replaceState(null, '', location.pathname + location.search.replace(/([?&])tour=1(&|$)/, '$1').replace(/[?&]$/, '') + location.hash); } catch (e) {}
                startWhenClear(700);
            } else if (!seen(PAGE_TOURS[pn].key) && !skippedMain()) {
                startWhenClear(900);
            }
            return;
        }
        if (forced) {
            try { history.replaceState(null, '', location.pathname + location.search.replace(/([?&])tour=1(&|$)/, '$1').replace(/[?&]$/, '') + location.hash); } catch (e) {}
            startWhenClear(400, { full: true });
        } else if (!seen() || window.cognicoachOnboardingRequested || !profile().onboarded) {
            startWhenClear(500);
        }
    }
    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', init); } else { setTimeout(init, 0); }
})();
