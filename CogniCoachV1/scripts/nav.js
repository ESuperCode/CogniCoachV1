// ==========================================================================
// Shared site navigation — a custom element (<site-nav></site-nav>).
//
// This is the ONE place the nav's markup and behavior live. To use it on a
// page, just drop <site-nav></site-nav> wherever the header should go and
// include this script — no copy-pasting the nav's HTML into every file.
//
// Behavior: slides out of view on scroll-down, fades back in on scroll-up
// or near the top of the page, and highlights whichever link matches the
// current page's filename.
// ==========================================================================

// Display preferences (scripts/a11y.js) go on <html> right away so the page doesn't flash.
(function applyA11yPrefsEarly() {
    try {
        const p = JSON.parse(localStorage.getItem('cognicoach-a11y') || '{}') || {};
        const h = document.documentElement;
        if (p.textSize === 'large') h.classList.add('a11y-text-lg');
        if (p.textSize === 'xlarge') h.classList.add('a11y-text-xl');
        if (p.contrast) h.classList.add('a11y-contrast');
        if (p.easyRead) h.classList.add('a11y-easy-read');
        const osReduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (p.motion === 'reduce' || ((!p.motion || p.motion === 'auto') && osReduce)) h.classList.add('a11y-reduce-motion');
    } catch (e) {}
})();

const NAV_LINKS = [
    { href: 'index.html', label: 'CogniCoach', brand: true },
    { href: 'dashboard.html', label: 'Dashboard' },
    { href: 'arena.html', label: 'Arena' },
    { href: 'competition.html', label: 'Competition Mode' },
    { href: 'about.html', label: 'About Us' },
    { href: 'contact.html', label: 'Contact' }
];

class SiteNav extends HTMLElement {
    connectedCallback() {
        this.classList.add('site-nav');
        this.id = 'siteNav';
        const linkHtml = link => {
            const classes = 'site-nav-link' + (link.brand ? ' site-nav-brand' : '');
            const logo = link.brand
                ? `<img src="logo-192.png" width="192" height="192" alt="" class="site-nav-logo" onerror="this.style.display='none'">`
                : '';
            return `<a href="${link.href}" class="${classes}"${link.brand ? ` aria-label="${link.label}"` : ''}>${logo}<span class="site-nav-text">${link.label}</span></a>`;
        };
        // Brand, then the page links (a drop-down "Menu" on small screens), then display settings + account.
        this.innerHTML = linkHtml(NAV_LINKS[0]) +
            '<button type="button" class="nav-menu-btn" id="navMenuBtn" aria-label="Menu" aria-expanded="false" aria-controls="navLinks">' +
            '<span class="nav-menu-bars" aria-hidden="true"><i></i><i></i><i></i></span><span class="nav-menu-text">Menu</span></button>' +
            '<div class="site-nav-links" id="navLinks">' + NAV_LINKS.slice(1).map(linkHtml).join('') + '</div>' +
            '<div class="nav-account" id="navAccount"></div>';

        this.highlightCurrentPage();
        loadSiteExtras();
        this.wireScrollBehavior();
        this.wireMenu();
    }

    wireMenu() {
        const btn = this.querySelector('#navMenuBtn');
        const links = this.querySelector('#navLinks');
        const setOpen = open => {
            btn.setAttribute('aria-expanded', open ? 'true' : 'false');
            this.classList.toggle('menu-open', open);
            if (open) { this.classList.remove('nav-hidden'); }
        };
        btn.addEventListener('click', () => setOpen(btn.getAttribute('aria-expanded') !== 'true'));
        document.addEventListener('keydown', e => {
            if (e.key === 'Escape' && this.classList.contains('menu-open')) { setOpen(false); btn.focus(); }
        });
        document.addEventListener('click', e => {
            if (this.classList.contains('menu-open') && !this.contains(e.target)) { setOpen(false); }
        });
        links.addEventListener('click', e => { if (e.target.closest('a')) { setOpen(false); } });
        window.addEventListener('scroll', () => { if (this.classList.contains('menu-open') && window.scrollY > 200) { setOpen(false); } }, { passive: true });
    }

    highlightCurrentPage() {
        let path = window.location.pathname.split('/').pop();
        if (!path) path = 'index.html';
        this.querySelectorAll('.site-nav-link').forEach(link => {
            if (link.getAttribute('href') === path) {
                link.classList.add('active');
            }
        });
    }

    wireScrollBehavior() {
        const SHOW_NEAR_TOP_PX = 80;
        let lastScrollY = window.scrollY;
        let ticking = false;
        const nav = this;

        function updateNav() {
            const currentY = window.scrollY;

            if (currentY < SHOW_NEAR_TOP_PX) {
                nav.classList.remove('nav-hidden');
            } else if (currentY > lastScrollY) {
                nav.classList.add('nav-hidden'); // scrolling down
            } else {
                nav.classList.remove('nav-hidden'); // scrolling up
            }

            lastScrollY = currentY;
            ticking = false;
        }

        window.addEventListener('scroll', () => {
            if (!ticking) {
                window.requestAnimationFrame(updateNav);
                ticking = true;
            }
        }, { passive: true });
    }
}

// Site-wide extras that every page with the nav gets: accounts (sign-in + profile sync) and, on the
// app page, the first-visit tour. Loaded from here so no page has to list them.
function loadSiteExtras() {
    const extras = [
        { css: 'styles/a11y.css', js: 'scripts/a11y.js' },
        { css: 'styles/brand3d.css', js: 'scripts/brand3d.js' },
        { css: 'styles/account.css', js: 'scripts/account.js' },
        { css: 'styles/tour.css', js: 'scripts/tour.js' },
        { css: 'styles/depth.css', js: 'scripts/depth.js' }
    ];
    const v = 'v=20261126a';   // bump with the ?v= on each page's own links so browsers fetch new files after a deploy
    extras.forEach(({ css: cssPath, js: jsPath }) => {
        const css = cssPath + '?' + v, js = jsPath + '?' + v;
        if (!document.querySelector(`link[href="${css}"]`)) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = css;
            document.head.appendChild(link);
        }
        if (!document.querySelector(`script[src="${js}"]`)) {
            const script = document.createElement('script');
            script.src = js;
            script.defer = true;
            document.head.appendChild(script);
        }
    });
}

customElements.define('site-nav', SiteNav);