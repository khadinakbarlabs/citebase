"""Offline Playwright regression for the Search tab: full sync, older query-only sync, no sync, phone width."""
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
CHANNEL = os.environ.get("CITEBASE_BROWSER_CHANNEL", "chrome")
ROWS = [{"term": "acme crm", "clicks": 30, "impressions": 100, "position": 1.2},
        {"term": "crm for teams", "clicks": 2, "impressions": 400, "position": 8},
        {"term": "best crm", "clicks": 1, "impressions": 900, "position": 12}] + \
       [{"term": f"crm idea {i}", "clicks": 0, "impressions": 10, "position": 30} for i in range(40)]
FULL = {"provenance": "google_sync", "property": "sc-domain:acme.test", "start_date": "2026-02-01", "end_date": "2026-02-28",
        "observed_at": "2026-03-03", "rows": ROWS,
        "daily": [{"date": f"2026-02-{d:02d}", "clicks": 10, "impressions": 200, "position": 5} for d in range(1, 29)],
        "pages": [{"page": f"https://acme.test/p{i}", "clicks": 20 - i, "impressions": 100, "position": 4} for i in range(14)],
        "countries": [{"country": "usa", "clicks": 200, "impressions": 3000, "position": 4}],
        "devices": [{"device": "MOBILE", "clicks": 210, "impressions": 4000, "position": 5}],
        "previous": {"start_date": "2026-01-04", "end_date": "2026-01-31",
                     "daily": [{"date": f"2026-01-{d:02d}", "clicks": 12, "impressions": 240, "position": 5} for d in range(4, 32)],
                     "rows": [{"term": "crm for teams", "clicks": 1, "impressions": 300, "position": 14}],
                     "pages": [{"page": "https://acme.test/p0", "clicks": 40, "impressions": 100, "position": 3}]}}
OLD = {"provenance": "google_sync", "property": "sc-domain:acme.test", "start_date": "2026-02-01", "end_date": "2026-02-28", "rows": ROWS[:3]}


def mount(page, report, failing=False):
    page.set_content('<html><body><div id="tip" hidden></div><main class="tabbody"></main></body></html>')
    page.add_style_tag(path=str(ROOT / "site/appearance.css"))
    for css in ("app.css", "journey.css", "search.css"):
        page.add_style_tag(path=str(ROOT / "site/app" / css))
    for script in ("core.js", "journey.js", "search-data.js", "search.js"):
        page.add_script_tag(path=str(ROOT / "site/app" / script))
    page.evaluate("""([report, failing]) => {
      CB.demo = false; CB.hasProjectWork = true;
      CB.work = async (slug, op) => { if (failing) throw Error('down'); if (op !== 'research_get') throw Error(op); return {first_party: {gsc: report, ga4: null}}; };
      return CB.searchUI.render(document.querySelector('main'), {brand: {name: 'Acme', domain: 'acme.test'}}, 'acme');
    }""", [report, failing])


with sync_playwright() as runner:
    browser = runner.chromium.launch(channel=CHANNEL)
    page = browser.new_page(viewport={"width": 1100, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    mount(page, FULL)
    expect(page.get_by_role("heading", name="Google Search")).to_be_visible()
    expect(page.get_by_text("Clicks down 17% vs the previous 28 days (336 → 280).", exact=True)).to_be_visible()
    expect(page.get_by_text("1 search moved into the top 10: “crm for teams”.")).to_be_visible()
    kpis = page.locator(".sr-kpi")
    expect(kpis.first).to_contain_text("280")
    expect(kpis.first).to_contain_text("vs previous 28 days")
    page.get_by_role("group", name="Date range").get_by_role("button", name="Last 7 days").click()
    expect(kpis.first).to_contain_text("70")
    expect(kpis.first).to_contain_text("Same as previous 7 days")
    expect(page.get_by_role("img", name="Clicks per day")).to_be_visible()
    page.get_by_role("group", name="Trend measure").get_by_role("button", name="Impressions").click()
    expect(page.get_by_role("img", name="Impressions per day")).to_be_visible()
    expect(page.get_by_text("Brand searches contain “acme”.")).to_be_visible()
    pages = page.locator(".sr-path")
    expect(pages).to_have_count(10)
    page.get_by_role("button", name="Show 4 more").click()
    expect(pages).to_have_count(14)
    expect(page.locator("tr", has_text="/p0").get_by_text("−20")).to_be_visible()
    expect(page.get_by_text("Showing 25 of 43 searches")).to_be_visible()
    search = page.get_by_role("searchbox", name="Filter Google searches")
    search.fill("teams")
    expect(page.get_by_text("Showing 1 of 1 searches")).to_be_visible()
    expect(page.locator(".sr-table tbody tr").first).to_contain_text("▲ 6.0")
    search.fill("")
    page.get_by_role("group", name="Show searches").get_by_role("button", name="Brand", exact=True).click()
    expect(page.get_by_text("Showing 1 of 1 searches")).to_be_visible()
    page.get_by_role("group", name="Show searches").get_by_role("button", name="Not brand").click()
    expect(page.get_by_text("Showing 25 of 42 searches")).to_be_visible()
    page.locator(".sr-table").get_by_role("button", name="Position").click()
    expect(page.locator(".sr-table tbody tr").first).to_contain_text("crm for teams")
    assert "null" not in page.locator("main").inner_text()

    mount(page, OLD)
    expect(page.get_by_text("Sync Search Console again to add the daily trend", exact=False)).to_be_visible()
    expect(page.get_by_text("Every day")).to_have_count(0)
    expect(page.get_by_role("button", name="Last 7 days")).to_have_count(0)
    expect(page.locator(".sr-kpi").first).to_contain_text("33")
    expect(page.locator(".sr-kpis")).not_to_contain_text("previous")
    expect(page.locator(".sr-insights")).not_to_contain_text("previous")
    expect(page.get_by_role("columnheader", name="Change")).to_have_count(0)

    mount(page, None)
    expect(page.get_by_role("heading", name="Connect Search Console to fill this page")).to_be_visible()
    mount(page, FULL, failing=True)
    expect(page.get_by_text("Your Google Search report could not be loaded.", exact=False)).to_be_visible()

    page.set_viewport_size({"width": 360, "height": 780})
    page.emulate_media(color_scheme="dark")
    mount(page, FULL)
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 360, f"page scrolls sideways at 360px: {width}"
    assert not errors, errors
    browser.close()
print("search journey ok")
