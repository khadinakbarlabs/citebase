"""Signed-in Connections page journey, run from project_work_journey.py.

Google replies are local fixtures: Search Console is connected with an import, Analytics is
signed in without a property, Gmail is not set up. A failed import must flip the card to
Needs action. Set CITEBASE_SCREENSHOTS to a folder to keep desktop, phone and dark captures.
"""

import json
import os
from pathlib import Path

from playwright.sync_api import expect

from public_ui_journey import fits_viewport

LAST_IMPORT = {"property": "sc-domain:example.com", "start_date": "2026-10-21", "end_date": "2026-11-17",
               "observed_at": "2026-11-18", "count": 12}
REFUSED = ("Could not confirm this Google operation. Check project history before retrying an import, "
           "or reconnect Google.")


def check_connections(page, base, slug, errors):
    calls, sync_fails = [], []
    replies = {
        "gsc": {"configured": True, "connected": True, "property": "sc-domain:example.com", "last_import": LAST_IMPORT},
        "ga4": {"configured": True, "connected": True, "property": None, "last_import": None},
        "gmail": {"configured": True, "connected": False, "property": None, "last_import": None},
    }

    def google(route):
        body = json.loads(route.request.post_data or "{}")
        calls.append(body)
        if body["action"] == "status":
            route.fulfill(json=replies[body["service"]])
        elif body["action"] == "sync" and sync_fails:
            route.fulfill(status=400, json={"error": REFUSED})
        elif body["action"] == "sync":
            route.fulfill(json={"measure": "Google Search queries", "startDate": "2026-10-22", "endDate": "2026-11-18",
                                "count": 9, "saved": True, "property": "sc-domain:example.com"})
        else:
            route.fulfill(status=400, json={"error": "Unexpected Google action in this journey."})

    page.route("**/api/google/", google)
    page.goto(base + "/app/#/p/" + slug + "/connections")
    nav = page.get_by_role("navigation", name="Project sections")
    expect(nav.get_by_role("link", name="Connections")).to_have_attribute("aria-current", "page")

    def card(key):
        return page.locator(f'[data-connection="{key}"]')

    gsc, ga4, gmail = card("gsc"), card("ga4"), card("gmail")
    expect(gsc.locator(".cn-badge")).to_have_text("Connected")
    expect(gsc).to_contain_text("Property: sc-domain:example.com")
    expect(gsc).to_contain_text("Last import Nov 18, 2026 · covers Oct 21, 2026 to Nov 17, 2026 · 12 rows")
    expect(gsc.get_by_role("button", name="Import 28 days")).to_be_visible()
    expect(gsc.get_by_role("button", name="Disconnect from project")).to_be_visible()
    expect(ga4.locator(".cn-badge")).to_have_text("Needs action")
    expect(ga4).to_contain_text("Choose property to pick the one that matches this website")
    expect(ga4.get_by_role("button", name="Choose property")).to_be_visible()
    expect(gmail.locator(".cn-badge")).to_have_text("Not set up")
    expect(gmail.get_by_role("button", name="Connect Gmail")).to_be_visible()
    expect(card("bots").locator(".cn-badge")).to_have_text("Not set up")
    expect(card("bots")).to_contain_text("access log")
    expect(card("traffic")).to_contain_text("analytics tool")
    for key in ("bing", "speed", "cloudflare"):
        expect(card(key).locator(".cn-badge")).to_have_text("Coming soon")
        expect(card(key).get_by_role("button")).to_have_count(0)
        expect(card(key)).to_have_attribute("aria-disabled", "true")
    expect(page.locator(".cn-summary")).to_have_text("1 ready · 1 needs action · 3 not set up")
    assert {c["service"] for c in calls} == {"gsc", "ga4", "gmail"}
    assert all(c["project"] == slug for c in calls), calls

    # A fresh import updates the card's date; Google refusing the saved sign-in flips it to Needs action.
    replies["gsc"] = {**replies["gsc"], "last_import": {**LAST_IMPORT, "start_date": "2026-10-22",
                                                        "end_date": "2026-11-18", "observed_at": "2026-11-19", "count": 9}}
    gsc.get_by_role("button", name="Import 28 days").click()
    expect(gsc).to_contain_text("Last import Nov 19, 2026 · covers Oct 22, 2026 to Nov 18, 2026 · 9 rows")
    sync_fails.append(True)
    gsc.get_by_role("button", name="Import 28 days").click()
    expect(gsc.locator(".cn-badge")).to_have_text("Needs action")
    expect(gsc).to_contain_text("If it keeps happening, choose Reconnect.")
    expect(gsc.get_by_role("button", name="Reconnect")).to_be_visible()
    expect(page.locator(".cn-summary")).to_have_text("2 need action · 3 not set up")
    # The refused import above is the only expected failure: one HTTP 400 and Chrome's matching console line.
    refused = [e for e in errors if "/api/google/" in e and ("HTTP 400 " in e or "status of 400" in e)]
    assert len(refused) == 2, errors
    errors[:] = [e for e in errors if e not in refused]

    shots = os.environ.get("CITEBASE_SCREENSHOTS")
    if shots:
        Path(shots).mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(Path(shots) / "connections-desktop.png"), full_page=True)
    page.set_viewport_size({"width": 360, "height": 780})
    fits_viewport(page)
    expect(gsc.get_by_role("button", name="Reconnect")).to_be_visible()
    if shots:
        page.screenshot(path=str(Path(shots) / "connections-phone.png"), full_page=True)
        page.evaluate("document.documentElement.dataset.theme = 'dark'")
        page.wait_for_timeout(600)  # let colour transitions finish; capture only
        page.screenshot(path=str(Path(shots) / "connections-phone-dark.png"), full_page=True)
        page.evaluate("delete document.documentElement.dataset.theme")
    page.set_viewport_size({"width": 1366, "height": 900})
    page.unroute("**/api/google/", google)
