"""Public landing workbench and read-only dashboard checks, run by project_work_journey.py."""

import re
from urllib.parse import parse_qs, urlsplit
from playwright.sync_api import expect


def fits_viewport(page):
    assert page.locator("html").evaluate(
        "(el) => el.scrollWidth <= window.innerWidth"
    ), f"Horizontal overflow on {page.url}"


def check_public_journey(page, base):
    page.goto(base)
    tour_link = page.get_by_role("link", name="Take the dashboard tour")
    expect(tour_link).to_be_visible()
    tour_link.click()
    tour = page.get_by_role("region", name="Guided dashboard tour")
    titles = ["Read your visibility snapshot", "Choose the competitors to track", "Follow a buyer question",
              "Inspect a website finding", "Choose the next action", "Review a schedule"]
    for step, title in enumerate(titles, 1):
        expect(tour.get_by_role("heading", name=title)).to_be_visible()
        expect(tour).to_contain_text(f"Step {step} of 6 · your turn")
        expect(page.locator("#main .tour-target")).to_have_count(1)
        if step == 1:
            # The visitor's own click on the highlighted control completes the step.
            page.locator("#main .snapshot-metric", has_text="Site health").click()
        else:
            if step == 2:
                # A reload keeps the step; Back and Skip move between unfinished steps.
                page.reload()
                expect(tour).to_contain_text("Step 2 of 6 · your turn")
                tour.get_by_role("link", name="Back", exact=True).click()
                expect(tour).to_contain_text("Step 1 of 6")
                tour.get_by_role("link", name="Skip", exact=True).click()
                expect(tour).to_contain_text("Step 2 of 6")
            tour.get_by_role("button", name="Show me").click()
        expect(tour).to_contain_text(f"Step {step} of 6 · done")
        expect(page.locator("#main .tour-target")).to_have_count(0)
        if step < len(titles):
            tour.get_by_role("link", name="Next step", exact=True).click()
        else:
            expect(page.get_by_text("Every Monday at 09:00 · UTC", exact=True).first).to_be_visible()
            expect(page.get_by_text(re.compile("Feb 15, 2027")).first).to_be_visible()
            expect(page.get_by_role("link", name="Manage in Console")).to_have_count(0)
    tour.get_by_role("button", name="Finish tour").click()
    expect(tour.get_by_role("link", name="Add my website")).to_have_attribute("href", "/api/session/?start")
    tour.get_by_role("button", name="Explore on my own").click()
    expect(tour).to_be_hidden()
    page.goto(base)
    switch = page.get_by_role("group", name="Choose a sample project")
    cafe = switch.get_by_role("radio", name="Northwind Café")
    payroll = switch.get_by_role("radio", name="Acme Payroll")
    expect(cafe).to_be_checked()
    tabs = page.get_by_role("tablist")

    def panel_link(project, section):
        href = f"app/?demo=1#/p/{project}/{section}"
        panel = page.get_by_role("tabpanel")
        expect(panel).to_be_visible()
        link = panel.get_by_role("link")
        expect(link).to_have_attribute("href", href)
        return link

    buyer = tabs.get_by_role("tab", name="Buyer question")
    evidence = tabs.get_by_role("tab", name="Evidence")
    actions_tab = tabs.get_by_role("tab", name="Next action")
    expect(tabs).to_have_attribute("aria-orientation", "vertical")
    buyer.press("ArrowDown")
    expect(evidence).to_be_focused()
    evidence.press("ArrowUp")
    expect(buyer).to_be_focused()
    appearance = page.get_by_role("button", name="Dark appearance")
    appearance.click()
    expect(appearance).to_have_attribute("aria-pressed", "true")
    panel_link("northwind-cafe", "answers")
    actions_tab.click()
    panel_link("northwind-cafe", "todo?record=sample-0")
    buyer.click()
    page.keyboard.press("ArrowRight")
    expect(evidence).to_be_focused()
    expect(evidence).to_have_attribute("aria-selected", "true")
    panel_link("northwind-cafe", "answers").press("Enter")
    expect(page).to_have_url(base + "/app/?demo=1#/p/northwind-cafe/answers")
    expect(page.get_by_role("heading", name="Northwind Café", exact=True)).to_be_visible()
    expect(appearance).to_have_attribute("aria-pressed", "true")
    appearance.click()
    expect(appearance).to_have_attribute("aria-pressed", "false")
    desktop_view = page.viewport_size
    page.set_viewport_size({"width": 320, "height": 740})
    fits_viewport(page)
    assert page.locator("#crumbs").evaluate("(nav) => nav.scrollWidth <= nav.clientWidth")
    page.set_viewport_size(desktop_view)
    sections = page.get_by_role("navigation", name="Project sections")
    expect(page.get_by_label("Project section", exact=True)).to_be_hidden()
    expect(sections.get_by_role("link", name="AI answers")).to_have_attribute("aria-current", "page")
    questions = sections.get_by_role("link", name="Questions")
    questions.focus()
    page.keyboard.press("Enter")
    expect(page).to_have_url(base + "/app/?demo=1#/p/northwind-cafe/questions")
    expect(questions).to_have_attribute("aria-current", "page")
    sections.get_by_role("link", name="Overview").press("Enter")
    measures = page.get_by_role("group", name="Visibility measures")
    health = measures.get_by_role("button", name=re.compile("Site health"))
    expect(health).to_contain_text("64")
    health.press("Enter")
    expect(health).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("heading", name="Site health over time")).to_be_visible()
    expect(page.get_by_role("link", name="Explore site checks")).to_have_attribute(
        "href", "#/p/northwind-cafe/site"
    )
    page.get_by_text("Project tools", exact=True).press("Enter")
    page.get_by_role("button", name="Next steps", exact=True).click()
    steps = page.get_by_role("dialog", name="Next steps")
    expect(steps.get_by_text("Add opening hours and menu as text, not images", exact=True)).to_be_visible()
    expect(steps).not_to_contain_text("payroll")
    steps.press("Escape")
    expect(steps).to_have_count(0)

    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(base)
    expect(tabs).to_have_attribute("aria-orientation", "horizontal")
    expect(appearance).to_have_attribute("aria-pressed", "false")
    menu = page.locator(".mobile-navigation")
    menu.locator("summary").press("Enter")
    expect(menu.get_by_role("link", name="Examples")).to_be_visible()
    menu.get_by_role("link", name="Examples").click()
    expect(menu).not_to_have_attribute("open", "")
    fits_viewport(page)
    cafe.focus()
    page.keyboard.press("ArrowRight")
    expect(payroll).to_be_checked()
    expect(cafe).not_to_be_checked()
    buyer.click()
    panel_link("acme-payroll", "questions")
    buyer.press("End")
    expect(actions_tab).to_be_focused()
    expect(actions_tab).to_have_attribute("aria-selected", "true")
    actions_tab.press("Home")
    expect(buyer).to_be_focused()
    expect(buyer).to_have_attribute("aria-selected", "true")
    evidence.click()
    panel_link("acme-payroll", "answers")
    actions_tab.click()
    panel_link("acme-payroll", "todo?record=sample-2").click()
    expect(page).to_have_url(base + "/app/?demo=1#/p/acme-payroll/todo?record=sample-2")
    expect(page.get_by_role("heading", name="Acme Payroll", exact=True)).to_be_visible()
    selected = page.locator("article[data-selected-record]")
    expect(selected).to_have_attribute("data-record-id", "sample-2")
    expect(selected.get_by_role("heading")).to_have_text("Pitch capterra.com for the payroll comparison")
    expect(selected).to_be_focused()
    expect(page.get_by_text("Fix the slow image on the home page", exact=True)).to_be_visible()
    fits_viewport(page)
    page.get_by_role("button", name="Run AI check", exact=True).click()
    expect(page.get_by_text("Sign in with Apify to save your own project or run a check.")).to_be_visible()
    expect(page.get_by_role("button", name="Yes, start the paid check")).to_have_count(0)

    # An actual click path through the sample must leave fixture rows intact after a reload.
    page.get_by_role("button", name="New action", exact=True).click()
    page.get_by_label("Action", exact=True).fill("Private fixture write")
    page.get_by_role("button", name="Save action", exact=True).click()
    message = "Sign in with Apify to save changes to your own project. The sample is read-only."
    expect(page.get_by_role("alert").filter(has_text=message)).to_be_visible()
    page.reload()
    expect(page.get_by_text("Fix the slow image on the home page", exact=True)).to_be_visible()
    expect(page.get_by_text("Private fixture write", exact=True)).to_have_count(0)

    expect(page.get_by_label("Project section", exact=True)).to_be_hidden()
    questions_chip = sections.get_by_role("link", name="Questions")
    questions_chip.click()
    expect(page).to_have_url(base + "/app/?demo=1#/p/acme-payroll/questions")
    expect(questions_chip).to_have_attribute("aria-current", "page")
    expect(page.get_by_text("best payroll software for a 10 person company", exact=True)).to_be_visible()
    fits_viewport(page)
    sections.get_by_role("link", name="Overview").click()
    focus = page.get_by_role("region", name="What to do next")
    focus.get_by_label("Filter by priority").select_option("opportunity")
    finding_href = "#/p/acme-payroll/evidence?record=sample%2Fsite%2FThin%20pricing%20page"
    focus.locator(f'a[href="{finding_href}"]').click()
    expect(page).to_have_url(base + "/app/?demo=1" + finding_href)
    expect(selected.get_by_role("heading")).to_have_text("Thin pricing page")
    expect(selected).to_have_attribute("data-record-id", "sample/site/Thin pricing page")
    expect(selected).to_be_focused()

    page.goto(base)
    page.route("https://console.apify.com/authorize/oauth**", lambda route: route.fulfill(
        content_type="text/html", body="<title>Apify authorization fixture</title>"
    ))
    sign_in = page.get_by_role("link", name="Sign in with Apify", exact=True).first
    sign_in.click()
    expect(page).to_have_title("Apify authorization fixture")
    query = parse_qs(urlsplit(page.url).query)
    assert query["redirect_uri"] == [base + "/app/"] and query["code_challenge_method"] == ["S256"]
