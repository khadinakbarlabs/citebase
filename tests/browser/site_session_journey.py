"""Run the built site and real sign-in function through a browser restart using an offline Apify fixture."""
import os
import json
import re
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright


def main():
    script = Path(__file__).with_name("site_session_fixture.cjs")
    with tempfile.TemporaryDirectory() as output, tempfile.TemporaryDirectory() as profile:
        server = subprocess.Popen(["node", str(script), output], stdout=subprocess.PIPE, text=True)
        try:
            base, tls_port = json.loads(server.stdout.readline())
            assert base.startswith("http://127.0.0.1:")
            with sync_playwright() as pw:
                # Preserve the real 302 and hostnames, including the cross-site OAuth return.
                # Route both Apify hostnames to our local TLS fixture and disable all other DNS.
                rules = (f"MAP console.apify.com 127.0.0.1:{tls_port}, MAP api.apify.com 127.0.0.1:{tls_port}, "
                         "MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost")

                def open_browser(*, no_channel=False):
                    ctx = pw.chromium.launch_persistent_context(
                        profile, channel=os.environ.get("CITEBASE_BROWSER_CHANNEL", "chrome"), service_workers="block",
                        ignore_https_errors=True, args=["--host-resolver-rules=" + rules, "--no-proxy-server"]
                    )
                    if no_channel:
                        ctx.add_init_script("Object.defineProperty(window, 'BroadcastChannel', {value: undefined})")
                    tab = ctx.pages[0]
                    tab.set_default_timeout(6000)
                    tab.goto(base)
                    return ctx, tab

                ctx, page = open_browser()
                page.get_by_role("link", name="Sign in with Apify", exact=True).click()
                expect(page).to_have_url(re.compile(r"^https://console\.apify\.com/authorize/oauth\?"))
                query = parse_qs(urlsplit(page.url).query)
                assert query["code_challenge_method"] == ["S256"]
                assert query["redirect_uri"] == [base + "/app/"]
                assert query["client_id"] == [base + "/oauth-client.json"]
                page.get_by_role("link", name="Allow fixture").click()
                expect(page.get_by_role("button", name="Sign out")).to_be_visible()
                expect(page).to_have_url(base + "/app/")
                expect(page.get_by_text("fixture-owner-1", exact=True)).to_be_visible()
                setup = page.get_by_role("region", name="Workspace guide")
                expect(setup).to_contain_text("Signed in with Apify")
                setup.get_by_role("link", name="Connect an AI assistant").click()
                expect(page.get_by_role("heading", name="Connect an AI assistant")).to_be_visible()
                for name in ["ChatGPT", "Hermes", "Codex", "Claude", "Claude Code", "Cursor", "Other"]:
                    page.get_by_label("Your assistant").select_option(label=name)
                    expect(page.get_by_role("region", name="Connection instructions")).to_contain_text(name)
                    expect(page.get_by_role("button", name="Copy setup")).to_be_visible()
                expect(page.get_by_role("button", name="Copy first question")).to_be_visible()
                page.get_by_role("link", name="Back to projects").click()
                page.get_by_role("link", name="Account", exact=True).click()
                credit = page.get_by_role("region", name="Remaining prepaid credits")
                expect(credit).to_contain_text("No balance recorded")
                credit.get_by_role("button", name="Record a balance").click()
                credit.get_by_label("Remaining prepaid usage (USD)").fill("23.45")
                credit.get_by_label("Billing period ends").fill(str(date.today() + timedelta(days=40)))
                credit.get_by_role("button", name="Save checked balance").click()
                expect(credit).to_contain_text("$23.45")
                expect(page.locator(".usage-shortcut")).to_contain_text("$23.45")
                page.reload()
                expect(credit).to_contain_text("$23.45")
                credit.get_by_role("button", name="Update balance").click()
                credit.get_by_label("Remaining prepaid usage (USD)").fill("0")
                credit.get_by_role("button", name="Save checked balance").click()
                expect(credit).to_contain_text("Prepaid balance was zero")
                page.get_by_role("link", name="Projects", exact=True).click()
                desktop_size = page.viewport_size
                page.set_viewport_size({"width": 800, "height": 850})
                expect(page.locator(".usage-shortcut")).to_be_visible()
                assert page.locator("#crumbs").evaluate("(nav) => nav.scrollWidth <= nav.clientWidth")
                page.set_viewport_size(desktop_size)
                assert page.evaluate("!document.cookie && !sessionStorage.getItem('cb.t') && !sessionStorage.getItem('cb.r') && !localStorage.length")
                cookies = ctx.cookies()
                assert any(c["httpOnly"] and c["expires"] > 0 and "_session_" in c["name"] for c in cookies)
                project_calls, remote_actor_calls = [], []

                def track_project_call(request):
                    if request.url == base + "/api/actor/" and request.method == "POST":
                        project_calls.append(request.post_data_json)
                    elif urlsplit(request.url).hostname == "khadinakbar--citebase.apify.actor":
                        remote_actor_calls.append(request.method)

                page.on("request", track_project_call)
                expect(page.get_by_role("heading", name="Add your first website")).to_be_visible()
                page.get_by_role("button", name="+ New project", exact=True).click()
                form = page.get_by_role("dialog", name="New project")
                form.get_by_label("Website", exact=True).fill("first-relay.example")
                form.get_by_role("button", name="Create and check the site").click()
                expect(form.get_by_role("heading", name="Site audit saved")).to_be_visible()
                form.get_by_role("button", name="Close", exact=True).last.click()
                expect(page.get_by_role("region", name="Project directory").get_by_role(
                    "link", name="first-relay.example", exact=True)).to_be_visible()
                writes = [call for call in project_calls if call["tool"] in {"save_results", "audit_site"}]
                assert [call["tool"] for call in writes] == ["save_results", "audit_site"]
                assert writes[0]["arguments"]["project"] == "first-relay-example" and writes[0]["arguments"]["create_only"]
                assert any(call["tool"] == "get_history" for call in project_calls)
                assert not remote_actor_calls
                print("PASS signed-in first project and saved audit through the same-origin Actor function")
                page.goto(base)
                expect(page.locator("[data-account-link]").and_(page.get_by_role("link", name="Dashboard", exact=True))).to_have_count(2)
                ctx.close()

                ctx, page = open_browser(no_channel=True)
                expect(page.locator("[data-account-link]").and_(page.get_by_role("link", name="Dashboard", exact=True))).to_have_count(2)
                page.get_by_role("link", name="Dashboard", exact=True).first.click()
                expect(page.get_by_role("button", name="Sign out")).to_be_visible()
                expect(page).to_have_url(base + "/app/")
                other = ctx.new_page()
                other.goto(base + "/app/")
                expect(other.get_by_role("button", name="Sign out")).to_be_visible()
                # Simulate a suspended tab missing both cross-tab events and foreground checks.
                stale = ctx.new_page()
                stale.add_init_script("""for (const type of ['storage','focus','visibilitychange'])
                    window.addEventListener(type, e => e.stopImmediatePropagation(), true)""")
                stale.goto(base + "/app/")
                expect(stale.get_by_text("fixture-owner-1", exact=True)).to_be_visible()
                page.get_by_role("button", name="Sign out").click()
                expect(page.get_by_role("button", name="Sign in with Apify")).to_be_visible()
                expect(other.get_by_role("button", name="Sign in with Apify")).to_be_visible()
                page.goto(base)
                expect(page.get_by_role("link", name="Sign in with Apify")).to_be_visible()
                page.get_by_role("link", name="Sign in with Apify").click()
                page.get_by_role("link", name="Allow fixture").click()
                expect(page.get_by_text("fixture-owner-2", exact=True)).to_be_visible()
                expect(stale.get_by_text("fixture-owner-1", exact=True)).to_be_visible()
                stale.evaluate("""() => { CB.apify('POST', 'acts/fixture~offline/runs', {}).catch(() => {}); }""")
                expect(stale.get_by_text("fixture-owner-2", exact=True)).to_be_visible()
                # A fresh, verified owner can perform the same simulated write exactly once.
                page.evaluate("""() => CB.apify('POST', 'acts/fixture~offline/runs', {})""")
                page.get_by_role("button", name="Sign out").click()
                expect(page.get_by_role("button", name="Sign in with Apify")).to_be_visible()
                ctx.close()

                # One click: a signed-out visit to the dashboard goes straight to Apify, with no second
                # Citebase sign-in screen. A deliberate sign-out above kept that tab on the sign-in screen.
                ctx, page = open_browser()
                page.goto(base + "/app/")
                expect(page).to_have_url(re.compile(r"^https://console\.apify\.com/authorize/oauth\?"))
                ctx.close()
                with urlopen(base + "/fixture-count", timeout=5) as count:
                    # Three deliberate Apify visits (first sign-in, re-sign-in, one-click restart); signing out
                    # in one tab never bounces the others to Apify. Only the fresh owner's write starts a run.
                    assert json.load(count) == {"consents": 3, "starts": 1}
                print("PASS one-click OAuth, dashboard CTA, browser restart, cross-tab sign-out without BroadcastChannel, stale paid request blocked and signed-out restart")
        finally:
            server.terminate()
            server.wait(timeout=5)


if __name__ == "__main__":
    main()
