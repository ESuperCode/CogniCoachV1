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

const NAV_LINKS = [
    { href: 'index.html', label: 'CogniCoach', brand: true },
    { href: 'dashboard.html', label: 'Dashboard' },
    { href: 'about.html', label: 'About Us' },
    { href: 'contact.html', label: 'Contact' }
];

class SiteNav extends HTMLElement {
    connectedCallback() {
        this.classList.add('site-nav');
        this.id = 'siteNav';
        this.innerHTML = NAV_LINKS.map(link => {
            const classes = 'site-nav-link' + (link.brand ? ' site-nav-brand' : '');
            const logo = link.brand
                ? `<img src="logo.png" alt="" class="site-nav-logo" onerror="this.style.display='none'">`
                : '';
            return `<a href="${link.href}" class="${classes}">${logo}${link.label}</a>`;
        }).join('');

        this.highlightCurrentPage();
        this.wireBrandLink();
        this.wireScrollBehavior();
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

    wireBrandLink() {
        // The brand link always takes you to a blank setup form, rather
        // than resuming whatever sport/session was last saved.
        const brandLink = this.querySelector('.site-nav-brand');
        if (!brandLink) return;
        brandLink.addEventListener('click', (e) => {
            e.preventDefault();
            localStorage.removeItem('cognicoach-state');
            window.location.href = brandLink.getAttribute('href');
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

customElements.define('site-nav', SiteNav);