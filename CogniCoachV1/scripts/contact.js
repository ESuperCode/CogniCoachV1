// ==========================================================================
// Contact form — sends messages to a Google Sheet via Google Apps Script.
//
// SETUP:
//   1. Follow the instructions at the top of apps-script/Code.gs to deploy
//      the Apps Script as a Web App connected to a Google Sheet.
//   2. Paste the deployed Web App URL (ends in /exec) into GOOGLE_SCRIPT_URL
//      below.
//
// Until GOOGLE_SCRIPT_URL is filled in, the form will show an error and
// people can still use the mailto fallback link on the page.
//
// Note on the request: Content-Type is set to 'text/plain' on purpose.
// Apps Script Web Apps don't implement CORS preflight (OPTIONS) requests,
// so sending JSON as 'text/plain' keeps this a "simple request" that
// skips the preflight the browser would otherwise block on. Code.gs still
// parses the body as JSON on the way in.
// ==========================================================================

const GOOGLE_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbyK8x6_qrZ466tNnnIQVpLqA7KapHUF011YVw47_CHWrn--piJPPGiH8uiYGDJ_JtLT/exec';

function isConfigured() {
    return GOOGLE_SCRIPT_URL.startsWith('http');
}

function setStatus(message, type) {
    const status = document.getElementById('contactStatus');
    status.textContent = message;
    status.className = 'contact-status' + (type ? ' ' + type : '');
}

function isValidEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
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
            const res = await fetch(GOOGLE_SCRIPT_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'text/plain;charset=utf-8' },
                body: JSON.stringify({ name, email, subject, message })
            });
            const data = await res.json();

            if (data.result !== 'success') {
                throw new Error(data.message || 'Unknown error');
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