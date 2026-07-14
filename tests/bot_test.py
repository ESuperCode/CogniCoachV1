"""
Headless-bot test for CogniCoachAI's drill generation flow.

Unlike a raw requests/curl test, this drives an actual (headless)
Chromium browser through the real site UI — filling the setup form,
clicking "Use Default Plan," clicking "Begin Session" — the same way a
scraping bot built with Playwright/Selenium/Puppeteer would attack it.
This is the realistic test for whether Turnstile's bot-detection (which
looks at things like navigator.webdriver, headless-specific fingerprints,
mouse/timing signals, etc.) actually blocks automation-driven browsers,
as opposed to just testing the "did you send a token at all" check.

Setup:
    pip install playwright
    playwright install chromium

Usage:
    python test_bot_ui.py                 # headless (the actual bot scenario)
    python test_bot_ui.py --headed        # headed, for comparison/debugging
    python test_bot_ui.py --url <url>     # point at a different environment
"""

import argparse
import json
import sys

from playwright.sync_api import sync_playwright


def run(url: str, headless: bool) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

        drill_requests = []
        drill_responses = []

        # Watch the actual network traffic so we can see exactly what
        # goes out to the Worker and what comes back, without relying on
        # anything visible in the DOM.
        def on_request(request):
            if "/api/drill" in request.url:
                drill_requests.append(request.post_data)

        def on_response(response):
            if "/api/drill" in response.url:
                try:
                    drill_responses.append(response.json())
                except Exception:
                    drill_responses.append({"_raw_status": response.status})

        page.on("request", on_request)
        page.on("response", on_response)

        print(f"Loading {url} (headless={headless})...")
        page.goto(url, wait_until="networkidle")

        # Fill the setup form like a real user/bot would.
        page.fill("#sport", "Basketball")
        page.fill("#location", "Gym")
        page.fill("#focus", "Speed")
        page.fill("#muscleGroup", "Quads")
        page.select_option("#level", index=1)

        # Use the built-in default plan instead of scripting HTML5
        # drag-and-drop (fragile to automate and not the part under test).
        page.click("text=Use Default Plan")
        page.wait_for_timeout(500)

        print("Clicking Begin Session...")
        page.click("text=Begin Session")

        # Give it time for the Turnstile challenge + drill fetch to
        # resolve (or fail) and for the UI to update either way.
        page.wait_for_timeout(8000)

        drill_name = page.locator("#drillName").inner_text() if page.locator("#drillName").count() else None
        timer_status = page.locator("#timerStatus").inner_text() if page.locator("#timerStatus").count() else None

        print("\n--- Results ---")
        print(f"Drill requests sent: {len(drill_requests)}")
        for i, body in enumerate(drill_requests):
            try:
                parsed = json.loads(body) if body else {}
                has_token = bool(parsed.get("turnstileToken"))
                print(f"  Request {i+1}: turnstileToken present = {has_token}")
            except (TypeError, json.JSONDecodeError):
                print(f"  Request {i+1}: could not parse body")

        print(f"Drill responses received: {len(drill_responses)}")
        for i, resp in enumerate(drill_responses):
            print(f"  Response {i+1}: {resp}")

        print(f"\nOn-screen drill name: {drill_name!r}")
        print(f"On-screen timer status: {timer_status!r}")

        got_real_drill = any(isinstance(r, dict) and r.get("content") for r in drill_responses)
        if got_real_drill:
            print("\n!! Headless automation got a real drill back — Turnstile did not block this run.")
        elif drill_responses:
            print("\nOK — the drill request was made but rejected (bot check likely blocked it).")
        else:
            print("\nNo /api/drill request completed — check screenshot/timer_status above for why "
                  "(e.g. Turnstile challenge never resolved, or form didn't submit).")

        page.screenshot(path="bot_test_result.png", full_page=True)
        print("Saved screenshot to bot_test_result.png")

        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://cognicoachai.com/CogniCoachV1/",
                         help="Site URL to test (default: production)")
    parser.add_argument("--headed", action="store_true",
                         help="Run with a visible browser instead of headless")
    args = parser.parse_args()

    run(args.url, headless=not args.headed)