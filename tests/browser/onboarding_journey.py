"""Offline Playwright regression covering setup choices, save errors and research navigation."""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
with sync_playwright() as runner:
    browser = runner.chromium.launch(channel="chrome")
    page = browser.new_page(viewport={"width": 390, "height": 844})
    page.set_content('<main></main>')
    page.add_script_tag(path=str(ROOT / 'site/app/core.js'))
    page.add_script_tag(path=str(ROOT / 'site/app/onboarding.js'))
    page.evaluate("""() => {
      const state={stage:'competitors',revision:1,competitors:[],terms:[{term:'buyer search',selected:true}]};
      CB.demo=false; window.calls=[];
      CB.work=async (slug,op,data)=>{
        if(op==='onboarding_get')return state;
        if(op==='onboarding_save'){calls.push(data);if(data.competitors?.[0]==='invalid')throw Error('Invalid competitor');state.stage=data.step==='competitors'?'terms':'research';state.revision++;return state;}
        if(op==='research_get')return {keywords:[{term:'buyer search',clicks:8}],ai:[{engine:'Claude',term:'Question',answers:null,mentions:1,position:3,position_samples:1,position_evidence:['3. Fixture Brand']}],first_party:{ga4:{source:'Google Analytics',provenance:'google_sync',rows:Array.from({length:5000},(_,i)=>({source:'channel-'+i,sessions:i}))},gsc:{source:'Google Search Console',provenance:'google_sync',rows:[{term:'Observed query',clicks:4,impressions:90}]}}};
        return {};
      };
      CB.onboarding(document.querySelector('main'),{brand:{site:'https://example.org'}},'sample');
    }""")
    competitor = page.get_by_label('Additional competitors')
    competitor.fill('invalid')
    page.get_by_role('button', name='Save and continue').click()
    expect(page.get_by_role('status')).to_have_text('Invalid competitor')
    competitor.fill('example.net')
    page.get_by_role('button', name='Save and continue').click()
    expect(page.get_by_label('buyer search')).to_be_checked()
    page.get_by_role('button', name='Use recommended terms').click()
    expect(page.get_by_role('heading', name='AI rank by engine')).to_be_visible()
    expect(page.get_by_text('buyer search', exact=True)).to_be_visible()
    expect(page.get_by_text('total answers unknown',exact=False)).to_be_visible()
    page.get_by_text('View ranking evidence').click()
    expect(page.get_by_text('3. Fixture Brand')).to_be_visible()
    expect(page.get_by_text('Showing 10 of 5000 matching rows')).to_be_visible()
    page.get_by_role('searchbox',name='Filter traffic sources').fill('channel-4999')
    expect(page.locator('.gr-table').get_by_text('channel-4999',exact=True)).to_be_visible()
    expect(page.get_by_text('Observed query',exact=True)).to_be_visible()
    assert page.evaluate('calls.at(-1).use_recommended && calls.at(-1).revision===2')
    browser.close()

# Exercise the production router, creation dialog and connector with in-memory account storage.
import project_work_journey as dashboard

class JourneyComplete(Exception):
    pass

def full_dashboard(page, base, call, ops):
    page.set_viewport_size({"width":390, "height":844})
    page.goto(base + "/app/#/")
    page.get_by_role("button",name="+ New project",exact=True).click()
    page.get_by_label("Website",exact=True).fill("copper.example")
    page.get_by_role("button",name="Create and check the site").click()
    page.get_by_role("button",name="Open the project").click()
    expect(page).to_have_url(base + "/app/#/p/copper-example/setup")
    expect(page.get_by_label("Atlas", exact=False).first).to_be_visible()
    call("project_work",{"project":"copper-example","operation":"research_import","data":{"expected_revision":0,"observed_at":"2025-01-01","source":"Fixture Google results","pages":[{"domain":"searchfixture.com","url":"https://searchfixture.com/guide","term":"Copper marketing software","position":2,"estimated_traffic":None}]}})
    page.evaluate("""() => {
      const original=CB.researchCollection.panel;
      CB.researchCollection.panel=(slug,plan,notify,opts)=>{
        const result=original(slug,plan,notify,opts);
        if(opts?.discovery)result.append(CB.h('button',{text:'Finish fixture import',onclick:()=>{notify({});notify({});}}));
        return result;
      };
    }""")
    page.get_by_text("Optional competitor search check",exact=True).click()
    page.get_by_role("button",name="Finish fixture import").click()
    expect(page.get_by_role("checkbox",name="searchfixture.com",exact=False)).not_to_be_checked()
    expect(page.get_by_text("Review the Google search competitors",exact=False)).to_be_visible()
    page.get_by_label("Website domain for Atlas",exact=True).fill("atlasfixture.com")
    page.get_by_label("Additional competitors").fill("Example Rival")
    page.get_by_role("button",name="Save and continue").click()
    page.get_by_label("Additional search terms").fill("Copper marketing software")
    page.get_by_role("button",name="Save and continue").click()
    expect(page.get_by_role("heading",name="AI rank by engine")).to_be_visible()
    page.goto(base + "/app/#/p/copper-example/overview")
    page.get_by_role("link",name="Resume project setup").click()
    expect(page.get_by_role("heading",name="Questions, plan and research")).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.get_by_role("button", name="Search terms",exact=True).click()
    page.get_by_role("button", name="Use recommended terms").click()
    expect(page.get_by_role("heading",name="Questions, plan and research")).to_be_visible()
    assert sum(req.get("arguments",{}).get("operation")=="onboarding_suggest" for req in ops)==2
    setup = call("project_work", {"project":"copper-example","operation":"onboarding_get","data":{}})["result"]
    assert any(row.get("domain")=="atlasfixture.com" for row in setup["competitors"])
    question = setup["questions"][0]
    call("save_results", {"project":"copper-example",
                          "runs":[{"snapshot":"baseline","prompt_id":question["prompt_id"],"platform":"chatgpt","cited_urls":["https://publisher.example/copper"]}]})
    page.reload()
    page.get_by_role("button", name="Review author and outreach").click()
    expect(page.get_by_role("dialog").get_by_role("heading",name="Contact the cited publisher")).to_be_visible()
    expect(page.get_by_role("dialog").get_by_text(question["prompt"],exact=True)).to_be_visible()
    page.get_by_role("dialog").get_by_role("button", name="Close").click()
    call("save_results",{"project":"legacy-brand","brand":{"name":"Legacy brand","aliases":["Previous name"]}})
    page.goto(base + "/app/#/p/legacy-brand/setup")
    page.get_by_label("Project website").fill("legacybrandfixture.com")
    page.get_by_role("button",name="Save website and continue").click()
    expect(page.get_by_label("Additional competitors")).to_be_visible()
    legacy=call("get_history",{"project":"legacy-brand"})["brand"]
    assert legacy["site"]=="https://legacybrandfixture.com/" and "Previous name" in legacy["aliases"]
    page.goto(base + "/app/?demo=1#/p/acme-payroll/setup")
    expect(page.get_by_text('This sample is read-only.', exact=False)).to_be_visible()
    page.get_by_role('button',name='View search terms').click()
    page.get_by_role('button',name='View research').click()
    expect(page.get_by_text('Fictional sample research.',exact=False)).to_be_visible()
    expect(page.get_by_text('Fictional Search Console export',exact=True).first).to_be_visible()
    for defaults in [True, False]:
        page.get_by_role('button',name='Practice setup').click()
        page.get_by_role('checkbox').first.uncheck()
        page.get_by_role('button',name='Save and continue').click()
        if not defaults:page.get_by_label('Additional search terms').fill('Practice term')
        page.get_by_role('button',name='Use recommended terms' if defaults else 'Save and continue').click()
        expect(page.get_by_role('heading',name='Questions, plan and research')).to_be_visible()
        page.get_by_role('button',name='Reset practice').click()
        expect(page.get_by_role('checkbox').first).to_be_disabled()
    raise JourneyComplete

if __name__ == '__main__':
    import work_onboarding
    work_onboarding.site_pages = lambda site: [{"url":site.rstrip("/")+"/compare/Atlas","title":"Copper buying guide","h1":["Copper marketing software"]}]
    dashboard.check_portfolio = full_dashboard
    try:
        dashboard.main()
    except JourneyComplete:
        print("PASS website creation, selected competitor and term, research and return to setup at 390px")
