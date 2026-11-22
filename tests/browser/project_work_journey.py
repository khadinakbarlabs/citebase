"""Offline browser journeys for the built landing page and signed-in dashboard.

From the repo root, install the connector dependencies and Playwright, then run
python tests/browser/project_work_journey.py. By default it launches the installed
Chrome channel. Set CITEBASE_BROWSER_CHANNEL=chromium to use Playwright Chromium.
The real /run endpoint and project storage operations use an in-memory account.
Public page fetches, Apify identity, paid starts and the scheduler are local fixtures.
"""

import json
import logging
import os
import re
import sys
import tempfile
import threading
from contextlib import ExitStack
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, quote, urlsplit

from playwright.sync_api import expect, sync_playwright
from starlette.testclient import TestClient

from public_ui_journey import check_public_journey, fits_viewport
from portfolio_journey import check_portfolio

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "connector"), str(ROOT / "scripts")]
import build_site
import server as connector_server
import storage
import work_auth
import work_schedules
import work_actions
import work_insights


def saved_project(call, slug, name, questions=(), engines=("chatgpt",), topics=()):
    brand = {"name": name, "domain": "example.com", "site": "https://example.com"}
    args = {"project": slug, "brand": brand}
    if questions:
        args["panel"] = [
            {"prompt_id": f"q{i}", "prompt": question, "type": "consideration"}
            for i, question in enumerate(questions, start=1)
        ]
        if topics:
            for item, topic in zip(args["panel"], topics, strict=True):
                item["topic"] = topic
        args["runs"] = [
            {"snapshot": "baseline", "prompt_id": q["prompt_id"], "platform": engine,
             "recommended": False}
            for q in args["panel"] for engine in engines
        ]
    call("save_results", args)


def check_project_focus(page, base, call, ops):
    project = "travel-clinic"
    saved_project(call, "new-clinic", "Unmeasured Clinic")
    questions = ["Which clinic checks travel vaccines?", "Who offers same-day travel advice?"]
    saved_project(call, project, "Travel Clinic", questions, topics=("Vaccines", "Travel advice"))

    def work(op, **data):
        return call("project_work", {"project": project, "operation": op, "data": data})["result"]

    urgent = work("action_save", title="Update the clinic directory", due_date="2000-01-01",
                  owner="Clara")["action"]
    other = work("action_save", title="Check opening hours", owner="Tariq")["action"]
    findings = work("opportunities_list")["opportunities"]
    target = next(item for item in findings if item["question"] == questions[1])
    focus = page.get_by_role("region", name="What to do next")
    priority = focus.get_by_label("Filter by priority")
    selected = page.locator("article[data-selected-record]")
    root = f"#/p/{project}"

    def focus_requests(slug):
        return [
            req["arguments"]["data"] for req in ops if req["tool"] == "project_work"
            and req["arguments"]["project"] == slug and req["arguments"]["operation"] == "project_focus"
        ]

    def record_link(section, record):
        return f"{root}/{section}?record=" + quote(record["id"], safe="")

    def open_selected(link, href, record):
        expect(link).to_have_attribute("href", href)
        link.press("Enter")
        expect(page).to_have_url(base + "/app/" + href)
        expect(selected).to_have_count(1)
        expect(selected).to_have_attribute("data-record-id", record["id"])
        expect(selected).to_be_focused()
        expect(page.locator("article[data-record-id]").first).to_have_attribute(
            "data-record-id", record["id"]
        )

    first_op = len(ops)
    page.goto(base + "/app/#/p/new-clinic/overview")
    expect(focus.get_by_role("heading", name="No next steps yet")).to_be_visible()
    expect(page.get_by_text("No recommendation rate is available yet.", exact=True)).to_be_visible()
    measures = page.get_by_role("group", name="Visibility measures")
    expect(measures.get_by_role("button", name="Recommended Needs an AI check", exact=True)).to_be_visible()
    journey = page.get_by_role("region", name="Project progress")
    expect(journey.get_by_role("button", name="Add questions")).to_be_visible()
    expect(focus.get_by_role("link", name="View actions")).to_have_attribute("href", "#/p/new-clinic/todo")
    expect(focus.get_by_role("link", name="View evidence")).to_have_attribute("href", "#/p/new-clinic/evidence")
    expect(focus.get_by_role("link", name="Open action")).to_have_count(0)

    def unavailable(route):
        payload = route.request.post_data_json or {}
        if payload.get("arguments", {}).get("operation") == "project_focus":
            route.fulfill(json={"ok": False, "error": "Temporary queue fixture"})
        else:
            route.fallback()

    page.route(base + "/run", unavailable)
    page.goto(base + "/app/" + root + "/overview")
    retry = focus.get_by_role("button", name="Try again")
    expect(retry).to_be_visible()
    expect(focus.get_by_role("heading", name="No next steps yet")).to_have_count(0)
    expect(focus.get_by_role("link", name="View actions")).to_be_visible()
    page.unroute(base + "/run", unavailable)
    retry.press("Enter")
    expect(priority.locator('option[value="all"]')).to_have_text("All priorities (4)")
    expect(priority.locator('option[value="opportunity"]')).to_have_text("Opportunities (2)")
    expect(focus.get_by_role("heading", name=urgent["title"])).to_be_visible()
    priority.select_option("review")
    expect(focus.get_by_role("heading", name="No actions need review")).to_be_visible()
    expect(focus.get_by_role("link", name="Open action")).to_have_count(0)
    priority.select_option("all")
    expect(focus.get_by_role("heading", name=urgent["title"])).to_be_visible()
    assert len(focus_requests(project)) == 1, "Already loaded priorities should not reread the account"
    open_selected(focus.get_by_role("link", name="Open action"), record_link("todo", urgent), urgent)
    expect(selected.get_by_role("heading", name=urgent["title"])).to_be_visible()
    selected.get_by_role("button", name="Review or edit").click()
    expect(page.get_by_label("Action", exact=True)).to_have_value(urgent["title"])
    page.get_by_role("button", name="Cancel", exact=True).click()

    search = page.get_by_label("Search actions", exact=True)
    search.fill(other["owner"])
    expect(page.locator("article[data-record-id]")).to_have_count(1)
    expect(page.get_by_role("heading", name=other["title"])).to_be_visible()
    expect(selected).to_have_count(0)
    page.get_by_label("Show actions").select_option("done")
    expect(page.get_by_text("No actions match your search or status.")).to_be_visible()
    page.get_by_role("button", name="Clear filters").click()
    expect(search).to_have_value("")
    expect(search).to_be_focused()
    expect(page.get_by_label("Show actions")).to_have_value("all")
    expect(page.locator("article[data-record-id]")).to_have_count(2)

    page.go_back()
    expect(page).to_have_url(base + "/app/" + root + "/overview")
    expect(focus.get_by_role("heading", name=urgent["title"])).to_be_visible()
    assert len(focus_requests(project)) == 1, "Returning to the same fresh overview should reuse its result"
    priority.select_option("opportunity")
    href = record_link("evidence", target)
    evidence_op = len(ops)
    open_selected(focus.locator(f'a[href="{href}"]'), href, target)
    expect(selected.get_by_role("heading")).to_have_text(target["question"])

    def evidence_reads():
        return [
            req["arguments"]["operation"] for req in ops[evidence_op:] if req["tool"] == "project_work"
            and req["arguments"]["operation"] in {"opportunities_list", "changes_list", "runs_list"}
        ]

    assert evidence_reads() == ["opportunities_list"], "Opening one finding should only load Findings"
    page.reload()
    expect(selected).to_have_attribute("data-record-id", target["id"])
    expect(selected).to_be_focused()
    page.get_by_label("Question", exact=True).fill("no matching buyer question")
    page.get_by_role("button", name="Apply filters").click()
    expect(page.get_by_text("No saved findings match these filters.")).to_be_visible()
    page.get_by_role("button", name="Clear filters").click()
    expect(page.get_by_label("Question", exact=True)).to_have_value("")
    expect(page.locator("article[data-record-id]")).to_have_count(2)

    # A view first loads on selection, stays cached on tab changes, and can be bookmarked.
    views = page.get_by_role("group", name="Evidence view")
    views.get_by_role("button", name="Changes").press("Enter")
    expect(page).to_have_url(base + "/app/" + root + "/evidence?view=changes")
    expect(page.get_by_role("heading", name=questions[0])).to_be_visible()
    views.get_by_role("button", name="Run history").press("Enter")
    expect(page).to_have_url(base + "/app/" + root + "/evidence?view=runs")
    expect(page.get_by_role("heading", name="baseline", exact=True)).to_be_visible()
    views.get_by_role("button", name="Changes").press("Enter")
    expect(page.get_by_role("heading", name=questions[0])).to_be_visible()
    assert evidence_reads().count("changes_list") == evidence_reads().count("runs_list") == 1
    evidence_op = len(ops)
    page.reload()
    expect(views.get_by_role("button", name="Changes")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("heading", name=questions[0])).to_be_visible()
    assert evidence_reads() == ["changes_list"]

    for section, noun, expected_count in (("todo", "action", 2), ("evidence", "finding", 2)):
        page.goto(base + "/app/" + root + "/" + section + "?record=missing-fixture")
        expect(page.get_by_text(f"This {noun} is no longer in this project.")).to_be_visible()
        expect(selected).to_have_count(0)
        expect(page.locator("article[data-record-id]")).to_have_count(expected_count)
    # A valid record from another project must not select or disclose it.
    page.goto(base + "/app/#/p/new-clinic/todo?record=" + urgent["id"])
    expect(page.get_by_text("This action is no longer in this project.")).to_be_visible()
    expect(page.get_by_text(urgent["title"], exact=True)).to_have_count(0)
    page.get_by_label("Switch project", exact=True).select_option(project)
    expect(page).to_have_url(base + "/app/" + root + "/todo")
    expect(page.get_by_role("heading", name=urgent["title"])).to_be_visible()
    expect(page.get_by_text("This action is no longer in this project.")).to_have_count(0)
    expect(selected).to_have_count(0)

    operations = [
        (req["arguments"]["project"], req["arguments"]["operation"])
        for req in ops[first_op:] if req["tool"] == "project_work"
    ]
    assert {(project, "project_focus"), ("new-clinic", "project_focus"),
            (project, "opportunities_list"), (project, "actions_list")} <= set(operations)
    assert all(req["tool"] in {"get_history", "project_work"} for req in ops[first_op:])
    assert all(op in {"project_focus", "actions_list", "opportunities_list", "brief_get",
                      "offers_list", "schedule_list", "changes_list", "runs_list", "seo_plan"} for _, op in operations)
    assert {row["id"]: row["revision"] for row in work("actions_list")["actions"]} == {
        urgent["id"]: urgent["revision"], other["id"]: other["revision"]
    }

    # A project edit invalidates the previously visited overview immediately.
    nav = page.get_by_role("navigation", name="Project sections")
    nav.get_by_role("link", name="Overview").press("Enter")
    expect(focus.get_by_role("heading", name=urgent["title"])).to_be_visible()
    before_edit = len(focus_requests(project))
    open_selected(focus.get_by_role("link", name="Open action"), record_link("todo", urgent), urgent)
    selected.get_by_role("button", name="Review or edit").click()
    updated_title = "Update the directory’s holiday hours"
    page.get_by_label("Action", exact=True).fill(updated_title)
    page.get_by_role("button", name="Save action").click()
    expect(selected.get_by_role("heading")).to_have_text(updated_title)
    nav.get_by_role("link", name="Overview").press("Enter")
    expect(focus.get_by_role("heading", name=updated_title)).to_be_visible()
    expect(focus.get_by_role("link", name="Open action")).to_have_attribute("href", record_link("todo", urgent))
    assert len(focus_requests(project)) == before_edit + 1

    # The first page of a busy account can contain only actions. A full opportunity group
    # then needs one filtered server read and remains available on repeat selection.
    busy = "busy-clinic"
    busy_questions = ["Which practice books weekend visits?", "Which branch has extended evening hours?"]
    saved_project(call, busy, "Clinic Network", busy_questions, topics=("Appointments", "Opening hours"))
    call("save_results", {"project": busy, "todo": [
        {"step": f"Check clinic listing {i}", "status": "open"} for i in range(21)
    ]})
    page.goto(base + f"/app/#/p/{busy}/overview")
    expect(priority.locator('option[value="all"]')).to_have_text("All priorities (23)")
    expect(focus.get_by_role("heading", name="Check clinic listing 0")).to_be_visible()
    more = focus.get_by_role("button", name="Show 4 more")
    more.press("Enter")
    expect(focus.get_by_text("Showing 8 of 23", exact=True)).to_be_visible()
    priority.select_option("opportunity")
    expect(focus.get_by_role("link", name="Open opportunity")).to_be_visible()
    assert [req.get("priority") for req in focus_requests(busy)] == [None, "opportunity"]
    priority.select_option("all")
    expect(focus.get_by_role("heading", name="Check clinic listing 0")).to_be_visible()
    priority.select_option("opportunity")
    expect(focus.get_by_role("link", name="Open opportunity")).to_be_visible()
    assert len(focus_requests(busy)) == 2

    nav.get_by_role("link", name="Questions").press("Enter")
    topic = page.get_by_label("Topic", exact=True)
    search_questions = page.get_by_label("Search questions", exact=True)
    topic.select_option(label="Appointments")
    search_questions.fill("weekend")
    expect(page.get_by_text(busy_questions[0], exact=True)).to_be_visible()
    expect(page.get_by_text(busy_questions[1], exact=True)).to_have_count(0)
    page.get_by_label("Switch project", exact=True).select_option(project)
    expect(page).to_have_url(base + "/app/" + root + "/questions")
    expect(topic).to_have_value("")
    expect(search_questions).to_have_value("")
    expect(topic.get_by_role("option", name="Appointments")).to_have_count(0)
    expect(topic.get_by_role("option", name="Vaccines")).to_have_count(1)
    for question in questions:
        expect(page.get_by_text(question, exact=True)).to_be_visible()


def browser_page(browser, base, errors, *, signed_in, interrupted_requests=()):
    ctx = browser.new_context(viewport={"width": 1366, "height": 900}, service_workers="block")
    if signed_in:
        ctx.add_init_script("sessionStorage.setItem('cb.t','fixture')")

    def network(route):
        req = route.request
        parts = urlsplit(req.url)
        if req.url.startswith(base + "/") and (
            req.method == "GET" or (signed_in and req.method == "POST" and parts.path == "/run")
        ):
            route.continue_()
        elif signed_in and req.method == "GET" and parts.netloc == "api.apify.com" and parts.path in {
            "/v2/users/me", "/v2/users/me/limits", "/v2/users/me/usage/monthly", "/v2/actor-runs"
        }:
            cycle = {"startAt": "2026-11-01T00:00:00Z", "endAt": "2026-11-30T23:59:59Z"}
            data = {
                "/v2/users/me": {"username": "fixture", "plan": {"id": "STARTER", "monthlyUsageCreditsUsd": 20}},
                "/v2/users/me/limits": {"monthlyUsageCycle": cycle, "current": {"monthlyUsageUsd": 4},
                                        "limits": {"maxMonthlyUsageUsd": 50}},
                "/v2/users/me/usage/monthly": {"usageCycle": cycle, "totalUsageCreditsUsdAfterVolumeDiscount": 4},
                "/v2/actor-runs": {"items": [], "total": 0},
            }[parts.path]
            route.fulfill(json={"data": data})
        else:
            errors.append(f"Unexpected {req.method} {req.url}")
            route.abort()

    ctx.route("**/*", network)
    page = ctx.new_page()
    page.set_default_timeout(6000)
    page.set_default_navigation_timeout(30_000)
    page.on("pageerror", lambda err: errors.append(f"Page exception on {page.url}: {err}"))
    page.on("response", lambda res: errors.append(f"HTTP {res.status} {res.url}") if res.status >= 400 else None)

    def console(message):
        url = message.location.get("url")
        if message.type == "error" and not (
            url in interrupted_requests and message.text.startswith("Failed to load resource: net::ERR_FAILED")
        ):
            errors.append(f"Browser console error on {url}: {message.text}")

    page.on("console", console)
    return page


def check_account_billing(browser, base, errors):
    page = browser_page(browser, base, errors, signed_in=True)
    page.set_viewport_size({"width": 375, "height": 812})
    page.goto(base + "/app/#/account")
    shortcut = page.get_by_role("link", name=re.compile("Apify ·"))
    expect(shortcut).to_contain_text("$4.00 used")
    expect(shortcut).to_contain_text("$16.00 est. plan allowance left")
    for label, value in (("Used this cycle", "$4.00"), ("Included per month", "$20.00"),
                         ("Est. monthly allowance left", "$16.00"), ("Monthly hard limit", "$50.00"),
                         ("Room before hard limit", "$46.00")):
        expect(page.locator(".billing-figures dt", has_text=label).locator("..").locator("dd")).to_have_text(value)
    expect(page.get_by_role("link", name="Open Apify Billing")).to_have_attribute("href", "https://console.apify.com/billing")
    fits_viewport(page)

    page.route("https://api.apify.com/v2/users/me/limits", lambda route: route.fulfill(json={"data": {
        "current": {"monthlyUsageUsd": 10}, "limits": {"maxMonthlyUsageUsd": 10}}}))
    page.goto(base + "/app/#/p/clinic/overview")
    page.reload()
    expect(page.get_by_role("link", name=re.compile("Apify limit reached"))).to_be_visible()
    page.get_by_role("button", name="Run AI check", exact=True).click()
    expect(page.get_by_text("Your monthly Apify spending limit has been reached.", exact=False)).to_be_visible()
    expect(page.get_by_role("button", name="Yes, start the paid check")).to_be_disabled()
    fits_viewport(page)
    page.context.close()


def check_expired_session(browser, base, account):
    errors = []
    page = browser_page(browser, base, errors, signed_in=True)
    page.clock.install()
    page.goto(base + "/app/#/p/clinic/todo")
    actions = page.get_by_role("region", name="Actions for Clinic")
    expect(actions.get_by_role("heading", name="Appointment page title")).to_be_visible()
    skip = page.get_by_role("link", name="Skip to content")
    expect(skip).to_be_hidden()
    skip.focus()
    expect(skip).to_be_visible()
    expect(skip).to_be_in_viewport()
    skip.press("Enter")
    expect(actions).to_be_focused()
    expect(skip).to_be_hidden()
    expect(page).to_have_url(base + "/app/#/p/clinic/todo")

    # Keep a previously authorized schedule read in flight while another operation detects expiry.
    page.clock.fast_forward(31_000)
    api_url = base + "/run"
    held = []

    def history_read(req):
        return (req.url == api_url and req.method == "POST"
                and req.post_data_json == {"tool": "get_history", "arguments": {"project": "clinic"}})

    def hold_history(route):
        if history_read(route.request) and not held:
            reply = route.fetch()
            assert reply.ok and reply.json()["result"]["brand"]["name"] == "Clinic"
            held.append((route, reply))
        else:
            route.fallback()

    page.route(api_url, hold_history)
    page.get_by_text("Project tools", exact=True).click()
    with page.expect_request(history_read):
        page.get_by_role("button", name="Schedule", exact=True).click()
    actions.get_by_role("button", name="Review or edit").click()
    editor = page.get_by_role("dialog", name="Review action")
    expect(editor.get_by_label("Action", exact=True)).to_have_value("Appointment page title")
    assert len(held) == 1
    account.id = "revoked-fixture"
    with page.expect_response(lambda res: res.url == api_url and res.status == 401) as denied:
        editor.get_by_role("button", name="Read current page").click()
    assert denied.value.request.post_data_json["arguments"]["operation"] == "page_inspect"
    sign_in = page.get_by_role("button", name="Sign in with Apify", exact=True)
    expect(sign_in).to_be_focused()
    expect(page.locator("dialog")).to_have_count(0)
    with page.expect_request_finished(predicate=history_read):
        held[0][0].fulfill(response=held[0][1])
    page.evaluate("() => new Promise(resolve => requestAnimationFrame(resolve))")
    expect(sign_in).to_be_focused()
    expect(page.locator("dialog")).to_have_count(0)
    expect(page.get_by_role("navigation", name="Project sections")).to_have_count(0)
    expect(page.get_by_role("navigation", name="Workspace").get_by_role("link")).to_have_count(0)
    expect(page.get_by_text("Appointment page title", exact=True)).to_have_count(0)
    assert page.evaluate("sessionStorage.getItem('cb.t')") is None
    # Chrome also logs the expected denied request to its console. Require exactly one denied response.
    assert errors.count("HTTP 401 " + api_url) == 1, errors
    assert all(err == "HTTP 401 " + api_url or err.startswith(
        f"Browser console error on {api_url}: Failed to load resource: the server responded with a status of 401"
    ) for err in errors), errors
    page.context.close()


def main():
    be = storage.MemoryBackend()
    storage.set_backend(be)
    account = NS(id="fixture-owner")
    identity = NS(user=lambda: NS(get=AsyncMock(return_value=account)))
    work_auth.tenant_id = lambda: "fixture-owner"

    def account_for(token):
        assert token == "fixture", "Local account requires the signed-in fixture token"
        return identity

    work_auth.new_client = account_for
    # Exercise the treatment branch. Assignment stability and holdout behavior have unit coverage.
    work_insights._arm = lambda scope: "offer"
    items = {}

    async def create(**kw):
        it = NS(id="sch0001", **kw)
        items[it.id] = items["owner~" + it.name] = it
        return it

    def schedule(key):
        async def update(**kw):
            for k, v in kw.items():
                setattr(items[key], k, v)
            return items[key]

        return NS(get=AsyncMock(side_effect=lambda: items.get(key)), update=update)

    client = NS(schedule=schedule, schedules=lambda: NS(create=create))
    work_schedules._account = AsyncMock(return_value=(client, "owner", "actor"))
    observed_title = "Appointments"
    work_actions.sa.fetch = lambda url: {
        "status": 200,
        "headers": {"content-type": "text/html"},
        "body": (
            f"<html><head><title>{observed_title}</title></head><body>"
            + ("Public evidence text " * 60)
            + "</body></html>"
        ).encode(),
        "url": url,
    }
    ops = []

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            ops.append(req)
            response = api.post(self.path, json=req, headers={
                k: v for k, v in self.headers.items()
                if k.lower() in {"authorization", "x-apify-authorization", "x-citebase-authorization"}
            })
            self.send_response(response.status_code)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            self.wfile.write(response.content)

    with TestClient(connector_server.build_app()) as api, tempfile.TemporaryDirectory() as tmp, ExitStack() as cleanup:
        def call(tool, args):
            response = api.post("/run", json={"tool": tool, "arguments": args},
                                headers={"Authorization": "Bearer fixture"})
            assert response.is_success, response.text
            return response.json()["result"]

        assert api.post("/run", json={"tool": "get_history", "arguments": {}}).status_code == 401
        saved_project(call, "clinic", "Clinic", ["Best local clinic?"], engines=("chatgpt", "google-aio"))
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=tmp))
        cleanup.callback(server.server_close)
        base = f"http://127.0.0.1:{server.server_port}"
        build_site.build(base, Path(tmp), api=base, local_static=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cleanup.callback(server.shutdown)
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                channel=os.environ.get("CITEBASE_BROWSER_CHANNEL", "chrome")
            )
            errors = []
            public = browser_page(browser, base, errors, signed_in=False)
            check_public_journey(public, base)
            public.context.close()
            assert not ops and not errors, (ops, errors)
            print("PASS public samples, keyboard switching, mobile project navigation and read-only actions")
            interrupted_requests = set()
            check_account_billing(browser, base, errors)
            page = browser_page(browser, base, errors, signed_in=True, interrupted_requests=interrupted_requests)
            check_portfolio(page, base, call, ops)
            check_project_focus(page, base, call, ops)
            assert not errors, errors
            print("PASS signed-in empty project, exact action/finding links, queue retry, cached filters, "
                  "evidence subviews, project switch and isolation")

            def go(tab):
                page.goto(base + "/app/#/p/clinic/" + tab)

            def btn(name):
                return page.get_by_role("button", name=name, exact=True).last

            def label(name):
                return page.get_by_label(name, exact=True).last

            def wait(text):
                expect(page.get_by_text(text, exact=True).last).to_be_visible(
                    timeout=6000
                )

            def planning():
                page.get_by_text("Project planning", exact=True).click()

            page.goto(base + "/app/#/")
            btn("+ New project").click()
            new_project_op = len(ops)
            label("Website").fill("https://name:password@weblog.example")
            btn("Create and check the site").click()
            wait("Use a website address without a username or password.")
            assert not any(req["tool"] in {"save_results", "audit_site"} for req in ops[new_project_op:])
            label("Website").fill("weblog.example")
            page.get_by_text("Project details and buying questions", exact=True).click()
            expect(label("Brand name")).to_have_value("weblog.example")
            expect(page.get_by_placeholder("yourbrand-com")).to_have_value(
                "weblog-example"
            )
            new_project = page.get_by_role("dialog", name="New project")
            new_project.get_by_role("combobox", name=re.compile("^Country")).select_option(label="Pakistan")
            page.get_by_label("Language code", exact=False).fill("en")
            btn("Create and check the site").click()
            btn("Open the project").click()
            expect(
                page.get_by_role("heading", name="weblog.example", exact=True)
            ).to_be_visible()
            created = call("get_history", {"project": "weblog-example"})
            assert created["brand"]["site"] == "https://weblog.example/"
            assert (created["settings"]["country"], created["settings"]["language"]) == ("pk", "en")
            audit_urls = [req["arguments"].get("url") for req in ops[new_project_op:] if req["tool"] == "audit_site"]
            assert audit_urls == ["https://weblog.example/"]
            go("overview")
            planning()
            btn("Set project brief").click()
            label("Business goal").fill("Book appointments")
            btn("Save brief").click()
            wait("Book appointments")
            go("evidence")
            btn("Create action").click()
            label("Action").fill("Fix appointment title")
            label("Affected page URL").fill("https://example.com/appointments")
            btn("Read current page").click()
            btn("Keep observed title").click()
            expect(label("Current page title")).to_have_value("Appointments")
            expect(label("Expected page title")).to_have_value("Appointments")
            label("Expected page title").fill("Book an appointment")
            btn("Save action").click()
            wait("Fix appointment title")
            observed_title = "Book an appointment"
            btn("Recheck page").click()
            btn("Check this page").click()
            expect(page.get_by_text("verified ·", exact=False)).to_be_visible(
                timeout=5000
            )
            go("overview")
            planning()
            btn("Preview page recheck").click()
            expect(label("Starting page (defaults to the project website)")).to_have_value(
                "https://example.com/appointments"
            )
            expect(label("Maximum pages per site check")).to_have_value("1")
            btn("Cancel").click()
            btn("Dismiss suggestion").click()
            expect(btn("Dismiss suggestion")).to_have_count(0)
            page.reload()
            planning()
            wait("Book appointments")
            expect(btn("Preview page recheck")).to_have_count(0)
            btn("One-time reminder").click()
            review_date = date.today() + timedelta(days=21)
            label("Review date").fill(review_date.isoformat())
            with page.expect_download() as pending_download:
                btn("Download reminder").click()
            assert (
                "DTSTART;VALUE=DATE:" + review_date.strftime("%Y%m%d")
                in pending_download.value.path().read_text()
            )
            go("todo")
            btn("Review or edit").click()
            label("Action").fill("Appointment page title")
            btn("Save action").click()
            wait("Appointment page title")
            page.reload()
            wait("Appointment page title")
            go("outreach")
            btn("Add a prospect").click()
            label("Who is the recipient?").select_option("editor")
            for k, v in {
                "Recipient email": "editor@example.org",
                "Specific source page": "https://example.org/news",
                "Why this fits their readers": "Local health readers",
                "What you can offer": "Local data",
                "Where you found the contact": "Byline",
            }.items():
                label(k).fill(v)
            btn("Save prospect").click()
            wait("editor@example.org")
            btn("Write draft").click()
            label("Subject").fill("Local data")
            label("Exact message").fill(
                "We have survey data for your article. If this isn't relevant, just tell me and I won't write again.\n\nAli Example\nExample Research"
            )
            btn("Save draft").click()
            btn("Review for approval").click()
            btn("Approve draft").click()
            wait("Approved for this version")
            btn("Summary settings").click()
            label("Enable the weekly summary").check()
            label("Mute unchanged weeks").uncheck()
            label("Recipient emails, one per line").fill("client@example.org")
            btn("Save settings").click()
            wait("Weekly archive")
            page.locator("summary").filter(has_text=" – ").last.click()
            btn("Prepare email copies").click()
            btn("Prepare copies").click()
            wait("Prepared email copies")
            wait("client@example.org")
            btn("Close").click()
            go("overview")
            planning()
            btn("Plan a check").click()
            expect(label("Include paid AI question checks")).not_to_be_checked()
            expect(label("Day of the week")).to_be_hidden()
            label("Frequency").select_option("weekly")
            label("Day of the week").select_option("4")
            expect(label("Day of the month (1–28)")).to_be_hidden()
            label("Local start time").fill("15:45")
            label("Time zone").fill("Asia/Karachi")
            label("Include paid AI question checks").check()
            label("AI engines").select_option("custom")
            label("ChatGPT").check()
            label("Questions").select_option("custom")
            label("Best local clinic?").check()
            btn("Preview schedule").click()
            paid_preview = page.get_by_role("dialog", name="Confirm schedule")
            expect(paid_preview).to_contain_text("Every Friday at 15:45 · Asia/Karachi")
            expect(paid_preview).to_contain_text("One round per local calendar day")
            expect(paid_preview).to_contain_text("1 question · ChatGPT")
            expect(paid_preview).to_contain_text("2 checks · 1 full round")
            paid_enable = paid_preview.get_by_role("button", name="Enable this schedule")
            expect(paid_enable).to_be_disabled()
            paid_preview.get_by_label("I approve recurring paid checks", exact=False).check()
            expect(paid_enable).to_be_enabled()
            assert not items
            btn("Cancel").click()
            proposed = call("project_work", {"project":"clinic", "operation":"schedule_preview", "data":{
                "frequency":"weekly", "weekday":4, "local_time":"15:45", "timezone":"Asia/Karachi", "include_ai":True,
            }})["result"]
            page.goto(base + "/app/" + proposed["review_url"].split("/app/", 1)[1])
            btn("Review saved proposal").click()
            handoff = page.get_by_role("dialog", name="Confirm schedule")
            expect(handoff).to_contain_text("Every Friday at 15:45")
            expect(handoff.get_by_role("button", name="Enable this schedule")).to_be_disabled()
            assert not items
            handoff.get_by_role("button", name="Cancel").click()
            go("overview")
            planning()
            btn("Plan a check").click()
            label("Frequency").select_option("weekly")
            label("Day of the week").select_option("4")
            label("Local start time").fill("15:45")
            label("Time zone").fill("Asia/Karachi")
            btn("Preview schedule").click()
            wait("Confirm schedule")
            assert not items
            btn("Enable this schedule").click()
            wait("Scheduled checks")
            expect(page.get_by_text("1 of 1 check remaining", exact=True)).to_be_visible()
            assert items["sch0001"].cron_expression == "45 15 * * 5"
            assert "ai_import" not in json.loads(items["sch0001"].actions[0]["runInput"]["body"])["arguments"]
            btn("Pause schedule").click()
            btn("Pause schedule").click()
            wait("Paused checks")
            page.set_viewport_size({"width": 390, "height": 844})
            go("evidence")
            btn("Changes").click()
            wait("Changes between saved rounds")
            btn("Findings").click()
            btn("Apply filters").click()
            fits_viewport(page)
            assert "[object Object]" not in page.locator("body").inner_text()
            # An uncertain paid child must not cause a repeated POST in the same tab after refresh.
            paid_requests = []

            def pretend_start(route):
                req = route.request
                paid_requests.append((req.method, req.url, req.post_data_json))
                if len(paid_requests) == 1:
                    route.fulfill(json={"data": {"id": "accepted-fixture"}})
                else:
                    interrupted_requests.add(route.request.url)
                    route.abort()

            quoted = call("quote_cost", {"pack": "ai_check_pilot", "project": "clinic"})
            starts = [item for item in quoted["ready_runs"] for _ in range(item["times"])]
            assert len(starts) >= 2, "The multi-engine fixture needs two distinct checks"
            page.context.route("https://api.apify.com/v2/acts/*/runs?*", pretend_start)
            btn("Run AI check").click()
            btn("Yes, start the paid check").click()
            expect(page.get_by_text("Start interrupted.", exact=False)).to_be_visible()
            page.reload()
            btn("Run AI check").click()
            wait("Previous AI check")
            assert len(paid_requests) == 2
            for (method, url, body), item in zip(paid_requests, starts):
                parsed = urlsplit(url)
                assert method == "POST"
                assert parsed.path == "/v2/acts/" + item["actor"].replace("/", "~") + "/runs"
                assert float(parse_qs(parsed.query)["maxTotalChargeUsd"][0]) == item["max_cost_per_run_usd"]
                assert body == item["input"]
            assert not errors, errors
            check_expired_session(browser, base, account)
            print("PASS skip navigation and session expiry with an open private form and a delayed schedule reply")
            print(
                "PASS signed-in onboarding, verified action, rename/reload, project brief, approved outreach draft, "
                "digest, calendar reminder, preview/enable/pause schedule and interrupted paid-start recovery.",
                flush=True,
            )
            print(
                "Shared operations exercised:",
                sorted(
                    {
                        q["arguments"].get("operation", "")
                        for q in ops
                        if q["tool"] == "project_work"
                    }
                ),
            )
            browser.close()


if __name__ == "__main__":
    # The script prints its verified journeys; keep warnings and failures from the server visible.
    logging.disable(logging.INFO)
    main()
