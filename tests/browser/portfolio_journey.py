"""Project comparison, saved audits and duplicate-safe creation through the dashboard."""

import json

from playwright.sync_api import expect

from public_ui_journey import fits_viewport


def check_portfolio(page, base, call, ops):
    brand = {"name": "Harbor Studio", "site": "https://harbor.example"}
    audit = {
        "site": brand["site"], "status": "partial", "health_score": 61, "pages_checked": 3,
        "subscores": {"technical": 55, "on-page": 67}, "counts": {"fail": 1, "warn": 1, "pass": 3},
        "problems": [
            {"check": "Page titles", "level": "fail", "area": "on-page", "detail": "A page has no title.",
             "example_urls": ["https://harbor.example/services"]},
            {"check": "Slow HTML", "level": "warn", "area": "technical", "detail": "The home page was slow."},
        ],
        "passed": ["HTTPS"],
    }
    call("save_results", {"project": "harbor-example", "brand": brand, "audit": audit})
    call("save_results", {"project": "beacon-studio", "brand": {"name": "Beacon Studio"}})
    page.goto(base + "/app/#/")
    directory = page.get_by_role("region", name="Project directory")
    search = directory.get_by_role("searchbox", name="Find a project")
    search.fill("Studio")
    projects = directory.get_by_role("rowheader")
    expect(projects).to_have_count(2)
    directory.get_by_label("Sort projects").select_option("name")
    expect(projects.first).to_contain_text("Beacon Studio")
    directory.get_by_label("Sort projects").select_option("health")
    expect(projects.first).to_contain_text("Harbor Studio")
    directory.get_by_role("button", name="No site audit", exact=False).click()
    expect(projects).to_have_count(1)
    expect(projects.first).to_contain_text("Beacon Studio")
    search.fill("no-matching-project")
    directory.get_by_role("button", name="Clear filters").click()
    expect(search).to_have_value("")
    harbor = directory.get_by_role("row").filter(has=page.get_by_role("link", name="Harbor Studio", exact=True))
    expect(harbor).to_contain_text("61")
    page.set_viewport_size({"width": 390, "height": 844})
    fits_viewport(page)
    harbor.get_by_role("link", name="Site audit", exact=True).press("Enter")
    expect(page).to_have_url(base + "/app/#/p/harbor-example/site")
    findings = page.get_by_role("region", name="Audit findings")
    expect(findings.get_by_text("Page titles", exact=True)).to_be_visible()
    findings.get_by_text("Page titles", exact=True).click()
    expect(findings.get_by_role("link", name="harbor.example/services")).to_have_attribute(
        "href", "https://harbor.example/services"
    )
    findings.get_by_label("Filter findings").select_option("warn")
    expect(findings.get_by_text("Page titles", exact=True)).to_have_count(0)
    expect(findings.get_by_text("Slow HTML", exact=True)).to_be_visible()
    expect(page.get_by_text("Partial coverage", exact=True)).to_be_visible()
    fits_viewport(page)

    offset = len(ops)
    page.get_by_role("button", name="Run site audit", exact=True).click()
    dialog = page.get_by_role("dialog", name="Site audit")
    dialog.get_by_role("spinbutton", name="Maximum pages", exact=True).fill("2")
    assert not any(req["tool"] == "audit_site" for req in ops[offset:])
    dialog.get_by_role("button", name="Start audit").press("Enter")
    expect(dialog.get_by_role("button", name="View site audit")).to_be_enabled()
    assert [req["arguments"] for req in ops[offset:] if req["tool"] == "audit_site"] == [
        {"project": "harbor-example", "url": "https://harbor.example/", "max_pages": 2}
    ]
    dialog.get_by_role("button", name="View site audit").click()
    page.goto(base + "/app/#/")
    page.get_by_role("button", name="+ New project", exact=True).click()
    form = page.get_by_role("dialog", name="New project")
    offset = len(ops)
    form.get_by_label("Website", exact=True).fill("harbor.example")
    form.get_by_label("Website", exact=True).press("Enter")
    existing = form.get_by_role("link", name="Open existing project")
    expect(existing).to_have_attribute("href", "#/p/harbor-example/overview")
    assert not any(req["tool"] in {"save_results", "audit_site"} for req in ops[offset:])
    expect(form.get_by_placeholder("yourbrand-com")).to_be_focused()
    existing.click()
    expect(page.get_by_role("heading", name="Harbor Studio", exact=True)).to_be_visible()
    check_interrupted_creation(page, base, ops)
    check_older_actor(page, base, ops)
    check_audit_billing(page.context, base)
    page.set_viewport_size({"width": 1366, "height": 900})


def check_interrupted_creation(page, base, ops):
    """A lost first reply can point to a real record. Never repeat the save or chain an audit."""
    api_url = base + "/run"
    slug = "saved-once-example"

    def lose_confirmation(route):
        req = route.request.post_data_json
        if req["tool"] == "save_results" and req["arguments"].get("project") == slug:
            assert req["arguments"].get("create_only") is True
            response = route.fetch()
            assert response.ok and response.json()["result"]["created"]
            route.fulfill(json={"ok": False, "error": "The save confirmation was interrupted."})
        else:
            route.fallback()

    page.route(api_url, lose_confirmation)
    offset = len(ops)
    page.goto(base + "/app/#/new")
    dialog = page.get_by_role("dialog", name="New project")
    dialog.get_by_label("Website", exact=True).fill("saved-once.example")
    dialog.get_by_role("button", name="Create and check the site").click()
    dialog.get_by_role("link", name="Open existing project").click()
    expect(page.get_by_role("heading", name="saved-once.example", exact=True)).to_be_visible()
    writes = [r["tool"] for r in ops[offset:] if r["tool"] in {"save_results", "audit_site"}]
    assert writes == ["save_results"], writes
    page.unroute(api_url, lose_confirmation)


def check_older_actor(page, base, ops):
    """The history-only dashboard can use a pre-project_work Actor without a new input or detailed findings."""
    def old_config(route):
        original = route.fetch().text()
        config = json.loads(original.partition("=")[2].strip().rstrip(";"))
        config["projectWork"] = False
        route.fulfill(content_type="application/javascript", body="window.__CB=" + json.dumps(config) + ";")

    def old_history(route):
        req = route.request.post_data_json
        if req == {"tool": "get_history", "arguments": {"project": "harbor-example"}}:
            response = route.fetch()
            result = response.json()
            result["result"].pop("latest_audit", None)
            route.fulfill(json=result)
        else:
            route.fallback()

    config_url, api_url = base + "/app/config.js", base + "/run"
    page.route(config_url, old_config)
    page.route(api_url, old_history)
    page.goto(base + "/app/#/p/harbor-example/site")
    page.reload()
    suggested = page.get_by_role("button", name="See suggested fixes")
    expect(suggested).to_be_visible()
    suggested.click()
    expect(page.get_by_role("dialog", name="Next steps")).to_be_visible()
    page.keyboard.press("Escape")
    offset = len(ops)
    page.goto(base + "/app/#/new")
    dialog = page.get_by_role("dialog", name="New project")
    dialog.get_by_label("Website", exact=True).fill("older-contract.example")
    dialog.get_by_role("button", name="Create and check the site").click()
    expect(dialog.get_by_role("heading", name="Site audit saved")).to_be_visible()
    dialog.get_by_role("button", name="Close", exact=True).last.click()
    directory = page.get_by_role("region", name="Project directory")
    expect(directory.get_by_role("link", name="older-contract.example")).to_be_visible()
    saves = [r["arguments"] for r in ops[offset:] if r["tool"] == "save_results"]
    assert len(saves) == 1 and "create_only" not in saves[0]
    page.unroute(api_url, old_history)
    page.unroute(config_url, old_config)
    page.reload()


def check_audit_billing(context, base):
    """Both entry points keep Apify's billing recovery link inside the active dialog."""
    page = context.new_page()
    errors, declined = [], []
    page.on("pageerror", lambda err: errors.append(str(err)))

    def limit(route):
        request = route.request.post_data_json
        if request["tool"] in {"save_results", "audit_site"}:
            declined.append(request["tool"])
            route.fulfill(status=403, json={"error": {"type": "limit-reached", "message": "Monthly usage limit reached."}})
        else:
            route.fallback()

    page.route(base + "/run", limit)
    page.goto(base + "/app/#/p/harbor-example/site")
    page.get_by_role("button", name="Run site audit").click()
    dialog = page.get_by_role("dialog", name="Site audit")
    dialog.get_by_role("button", name="Start audit").click()
    expect(dialog.get_by_role("link", name="Open Apify Billing")).to_have_attribute("href", "https://console.apify.com/billing")
    dialog.press("Escape")
    page.goto(base + "/app/#/new")
    dialog = page.get_by_role("dialog", name="New project")
    dialog.get_by_label("Website", exact=True).fill("billing-fixture.example")
    dialog.get_by_role("button", name="Create and check the site").click()
    expect(dialog.get_by_role("link", name="Open Apify Billing")).to_have_attribute("href", "https://console.apify.com/billing")
    expect(dialog.get_by_role("button", name="Create and check the site")).to_be_enabled()
    assert declined == ["audit_site", "save_results"] and not errors, (declined, errors)
    page.close()
