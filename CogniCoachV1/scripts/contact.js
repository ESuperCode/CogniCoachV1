// ==========================================================================
// Contact form — sends messages to the Cloudflare Worker, which relays
// them to a Google Sheet via Google Apps Script.
//
// The Apps Script Web App URL used to live here in plain sight, which
// meant anyone could read it from this file and POST directly to the
// sheet. It now lives only on the Worker as a secret (GOOGLE_SCRIPT_URL),
// so this file just talks to our own backend — same as script.js does
// for drill generation.
// ==========================================================================

// Same backend the drill generator uses.
const CONTACT_API_URL = "https://cognicoach-backend.bodhishanbhag.workers.dev/api/contact";
const PRODUCTION_URL = "https://cognicoachai.com/CogniCoachV1/";

function isConfigured() {
    return CONTACT_API_URL.startsWith('http');
}

function setStatus(message, type) {
    const status = document.getElementById('contactStatus');
    status.textContent = message;
    status.className = 'contact-status' + (type ? ' ' + type : '');
}

function isValidEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

// Same dev-password flow script.js uses: production requests need no
// password (allowed via Origin check on the Worker), anything else
// prompts once per tab and remembers it in sessionStorage.
function getAppPassword() {
    const isProduction = window.location.href.startsWith(PRODUCTION_URL);
    if (isProduction) {
        return null;
    }

    let password = sessionStorage.getItem("cognicoach_dev_password");
    if (!password) {
        password = window.prompt("This isn't the production site. Enter the dev password to send a message:");
        if (password) {
            sessionStorage.setItem("cognicoach_dev_password", password);
        }
    }
    return password;
}

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('contactForm');
    const submitBtn = document.getElementById('contactSubmitBtn');

    form.addEventListener('submit', async (e) => {
        e.preventDefault();

        // Honeypot — if this hidden field got filled in, it was a bot.
        // Pretend it worked so the bot doesn't learn anything.
        const honeypot = document.getElementById('contactCompany').value.trim();
        if (honeypot) {
            setStatus('Message sent — thanks!', 'success');
            form.reset();
            return;
        }

        const name = document.getElementById('contactName').value.trim();
        const email = document.getElementById('contactEmail').value.trim();
        const subject = document.getElementById('contactSubject').value.trim();
        const message = document.getElementById('contactMessage').value.trim();

        if (!name || !email || !subject || !message) {
            setStatus('Please fill in every field.', 'error');
            return;
        }
        if (!isValidEmail(email)) {
            setStatus('That email address doesn\'t look right.', 'error');
            return;
        }

        if (!isConfigured()) {
            setStatus(
                'The contact form isn\'t set up yet — please try again later.',
                'error'
            );
            return;
        }

        submitBtn.disabled = true;
        setStatus('Sending...', 'sending');

        try {
            const headers = { 'Content-Type': 'application/json' };
            const appPassword = getAppPassword();
            if (appPassword) {
                headers['X-App-Password'] = appPassword;
            }

            const res = await fetch(CONTACT_API_URL, {
                method: 'POST',
                headers,
                body: JSON.stringify({ name, email, subject, message })
            });

            if (res.status === 401) {
                sessionStorage.removeItem("cognicoach_dev_password");
            }

            const data = await res.json();

            if (data.result !== 'success') {
                throw new Error(data.error || 'Unknown error');
            }

            setStatus('Message sent — thanks! We\'ll get back to you soon.', 'success');
            form.reset();
        } catch (err) {
            console.error('Contact form submission failed:', err);
            setStatus(
                'Something went wrong sending that. Please try again in a moment.',
                'error'
            );
        } finally {
            submitBtn.disabled = false;
        }
    });
});