"""Saved project evidence, coverage, attribution and post-verification offers."""
import asyncio
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "connector"))
import history
import storage
import work_insights as work


class WorkInsightsTests(unittest.TestCase):
    def setUp(self):
        self.be = storage.MemoryBackend()
        storage.set_backend(self.be)
        self.addCleanup(storage.set_backend, None)

    def call(self, operation, **data):
        return asyncio.run(work.execute("acme", operation, data))

    def save(self, label, day, rows, dataset="source123"):
        panel = [{"prompt_id": p, "prompt": "Which " + p, "type": "consideration"} for p in ["p1", "p2"]]
        with patch.object(history, "today", return_value=day):
            asyncio.run(history.save_results("acme", [dict(snapshot=label, date=day, **row) for row in rows],
                                             panel=panel, source_ids=[dataset]))

    @staticmethod
    def row(prompt="p1", won=False, engine="chatgpt", **extra):
        return dict(prompt_id=prompt, recommended=won, platform=engine, **extra)

    def test_changes_find_previous_week_and_expose_missing_samples(self):
        self.save("week-one", "2026-11-02", [self.row(won=True), self.row("p2")])
        self.save("mid-week", "2026-11-07", [self.row()])
        self.save("week-two", "2026-11-09", [self.row(), self.row("p2", engine="gemini")])
        view = self.call("changes_list")
        self.assertEqual(view["previous_round"], "week-one")
        by_cell = {(q["prompt_id"], q["engine"]): q for q in view["questions"]}
        self.assertEqual(by_cell["p1", "chatgpt"]["status"], "lost")
        self.assertEqual(by_cell["p2", "chatgpt"]["status"], "missing_current")
        self.assertEqual(by_cell["p2", "gemini"]["status"], "missing_baseline")
        self.assertEqual(by_cell["p1", "chatgpt"]["after"]["recommended"], 0)
        self.assertTrue(by_cell["p1", "chatgpt"]["evidence_url"].endswith("source123"))

    def test_different_country_and_repeat_count_never_imply_a_loss(self):
        self.save("base", "2026-11-02", [self.row(won=True, country="US")])
        self.save("now", "2026-11-09", [self.row(country="GB"), self.row(country="GB", repeat=2)])
        self.assertEqual(self.call("changes_list")["questions"][0]["status"], "changed_coverage")

    def test_opportunity_links_to_saved_affected_page_without_claiming_unobserved_urls(self):
        audit = {"site": "https://acme.test", "health_score": 70, "pages_checked": 3, "problems": [
            {"check": "Title missing", "detail": "No title", "example_urls": ["https://acme.test/plans", "javascript:bad"]}]}
        asyncio.run(history.save_audit("acme", audit))
        entry, = self.call("opportunities_list", page="/plans")["opportunities"]
        self.assertEqual(entry["page"], "https://acme.test/plans")
        self.assertEqual(entry["id"], self.call("opportunities_list")["opportunities"][0]["id"])
        self.assertEqual(self.call("opportunities_list", channel="off_page")["opportunities"], [])

    def test_saved_ids_belong_to_correct_project_and_replaced_rounds_release_ids(self):
        self.save("base", "2026-11-02", [self.row()], dataset="actual123")
        asyncio.run(history.save_audit("other", {"health_score": 50}))
        overview = asyncio.run(history.overview())["projects"]
        rows = {p["project"]: p for p in overview}
        self.assertEqual(rows["acme"]["imported_dataset_ids"], ["actual123"])
        self.assertEqual(rows["other"]["imported_dataset_ids"], [])
        self.assertEqual(self.call("runs_list")["runs"][0]["dataset_ids"], ["actual123"])
        self.assertEqual(asyncio.run(work.execute("other", "runs_list", {}))["runs"], [])
        asyncio.run(history.save_results("acme", [dict(snapshot="base", **self.row())], replace=True))
        self.assertEqual(self.call("runs_list")["runs"][0]["dataset_ids"], [])

    def test_multi_dataset_import_links_answers_only_to_datasets_with_matching_rows(self):
        import runner
        self.save("baseline", "2026-11-02", [self.row()])
        def item(prompt, url):
            return {"query": "Which " + prompt, "platform": "chatgpt", "brand_mentioned": False, "cited_urls": [url]}
        self.be.datasets.update({"first11": [item("p1", "https://publisher.test/story")],
                                 "other22": [item("p2", "https://acme.test/plans")],
                                 "empty33": [item("rejected", "https://unmatched.test/story")]})
        asyncio.run(runner.import_results("acme", None, "current", save=True, dataset_ids=list(self.be.datasets)))
        data = asyncio.run(history.load_project("acme"))
        self.assertEqual(data["meta"]["imports"]["current"], ["first11", "other22"])
        self.assertEqual({r["prompt_id"]: r["source_dataset_id"] for r in data["runs"] if r["snapshot"] == "current"},
                         {"p1": "first11", "p2": "other22"})
        sources = {r["prompt_id"]: r["evidence_url"] for r in self.call("changes_list")["questions"]}
        self.assertTrue(sources["p2"].endswith("other22"))

    def test_saved_panel_fingerprint_mismatch_suppresses_comparison(self):
        self.save("a", "2026-11-02", [self.row(won=True)])
        self.save("b", "2026-11-09", [self.row()])
        self.be.data["p.acme.meta"].setdefault("panel_hashes", {})["a"] = "old-panel"
        result = self.call("changes_list")
        self.assertEqual(result["coverage"]["panel"], "changed")
        self.assertEqual(result["questions"][0]["status"], "changed_panel")
        self.assertEqual(result["changes"], [])

    def test_managed_run_states_join_exact_dataset_and_hide_other_project_receipts(self):
        self.save("baseline", "2026-11-02", [self.row()], dataset="datasetA")
        self.be.data["p.acme.scheduled-runs.scheduled-Parent123"] = {
            "runs": ["ai1", "ai2", "ai3", "ai4", "ai5", "ai6"], "scheduled_at": "2026-11-09T03:00:00Z",
            "children": {"ai1": {"status": "READY"}, "ai2": {"status": "RUNNING"},
                         "ai3": {"status": "SUCCEEDED", "dataset_id": "datasetA"},
                         "ai4": {"status": "SUCCEEDED", "dataset_id": "datasetB"}, "ai5": {"status": "FAILED"}}}
        rows = self.call("runs_list")["runs"]
        states = {r["id"]: r["status"] for r in rows}
        self.assertEqual([states[k] for k in ("ai1", "ai2", "ai3", "ai4", "ai5", "ai6")],
                         ["queued", "running", "complete", "awaiting_import", "failed", "unknown"])
        self.assertEqual(len(self.call("runs_list", run_id="ai3")["runs"]), 1)
        self.assertEqual(self.call("runs_list", run_id="notInProject")["runs"], [])

    def test_offer_requires_fresh_verified_page_and_persists_dismissal_by_evidence(self):
        asyncio.run(history.save_audit("acme", {"health_score": 80}))
        actions = [{"id": "a1", "page_url": "https://acme.test/pricing", "recheck": {"status": "inconclusive"}}]
        with patch.object(work, "_actions", return_value=actions), patch.object(work, "_arm", return_value="offer"):
            self.assertIsNone(self.call("offers_list")["offer"])
            actions[0]["recheck"] = {"status": "verified", "changed_from_before": True, "checked_at": history.today()}
            offer = self.call("offers_list")["offer"]
            self.assertIsNotNone(offer)
            saved = self.call("offer_dismiss", id=offer["id"])
            self.assertIsNone(saved["offer"])
            self.assertIsNone(self.call("offers_list")["offer"])
            with self.assertRaises(ValueError):
                self.call("offer_dismiss", id="made-up")
            self.assertEqual(self.call("offers_list")["measures"]["dismissals_30d"], 1)

    def test_same_recheck_does_not_resurface_dismissed_offer_or_count_unchanged_page(self):
        asyncio.run(history.save_audit("acme", {"health_score": 80}))
        check = {"status": "verified", "checked_at": history.today(), "changed_from_before": False}
        action = {"id": "a1", "page_url": "https://acme.test/plans", "recheck": check}
        with patch.object(work, "_actions", return_value=[action]), patch.object(work, "_arm", return_value="offer"):
            self.assertIsNone(self.call("offers_list")["offer"])
            check["changed_from_before"] = True
            offer = self.call("offers_list")["offer"]
            self.call("offer_dismiss", id=offer["id"])
            check["checked_at"] += "T23:59:59Z"
            self.assertIsNone(self.call("offers_list")["offer"])

    def test_citation_urls_survive_normalization_with_safe_destination_only(self):
        self.save("round", "2026-11-09", [self.row(cited=True, cited_urls=["https://publisher.test/review",
                     "https://private.test/doc?token=secret", "https://x:y@secret.test/read",
                     "https://acme.test/plans"], cited_domains="publisher.test;acme.test")])
        asyncio.run(history.save_results("acme", [], brand={"domain": "acme.test"}))
        view = self.call("changes_list")["questions"][0]
        self.assertEqual(view["destination_page"], "https://acme.test/plans")
        self.assertIn("https://publisher.test/review", [s["url"] for s in view["cited_sources"]])
        self.assertNotIn("secret", str(asyncio.run(history.load_project("acme"))))

    def test_receipt_math_is_explicit_idempotent_and_owner_reported(self):
        asyncio.run(history.save_audit("acme", {"health_score": 80}))
        values = dict(zip(work.MONEY, (1000, 100, 20, 30, 10, 50)))
        args = dict(event="financial_receipt", event_id="store-123", date=history.today(), **values)
        with patch.object(work, "_actions", return_value=[]):
            self.call("offer_measure_record", **args)
            measured = self.call("offer_measure_record", **args)["measures"]
            self.assertEqual(measured["owner_reported_contribution_cents"], 840)
            self.assertIsNone(measured["settled_contribution_cents"])
            self.assertEqual(measured["reported_events_30d"]["financial_receipt"], 1)
            with self.assertRaises(ValueError):
                self.call("offer_measure_record", **{**args, "owner_receipts_cents": 2000})

    def test_metrics_count_verified_fix_after_followup_fails_without_selling_another_check(self):
        asyncio.run(history.save_audit("acme", {"health_score": 80}))
        verified = {"page_url": "https://acme.test/page", "recheck": {"status": "verified",
                    "changed_from_before": True, "checked_at": history.today()}}
        latest = {"id": "a1", "page_url": verified["page_url"], "history": [verified, verified],
                  "recheck": {"status": "mismatch", "checked_at": history.today()}}
        with patch.object(work, "_actions", return_value=[latest]), patch.object(work, "_arm", return_value="offer"):
            res = self.call("offers_list")
            self.assertIsNone(res["offer"])
            self.assertEqual(res["measures"]["verified_fixes_30d"], 1)
            self.assertEqual(res["measures"]["days_to_first_verified_fix"], 0)

    def test_independent_writers_elect_one_financial_event_and_retry_reuses_it(self):
        async def race():
            private = await self.be.private_store()
            prefix = "p.acme.metrics.event-"
            first = {"event": "financial_receipt", "owner_receipts_cents": 400, "date": history.today()}
            second = {**first, "owner_receipts_cents": 900}
            results = await asyncio.gather(work._record_measurement(self.be, private, prefix, "same-id", first),
                                           work._record_measurement(self.be, private, prefix, "same-id", second),
                                           return_exceptions=True)
            self.assertEqual(sum(isinstance(x, ValueError) for x in results), 1)
            winner = first if not isinstance(results[0], Exception) else second
            await work._record_measurement(self.be, private, prefix, "same-id", winner)
            store = await work.work_actions.RevisionStore.open(self.be, private, "read")
            self.assertEqual([r["owner_receipts_cents"] for r in await store.records(prefix)],
                             [winner["owner_receipts_cents"]])
        asyncio.run(race())

    def test_holdout_never_displays_offer_and_read_does_not_record_exposure(self):
        asyncio.run(history.save_audit("acme", {"health_score": 80}))
        actions = [{"id": "a1", "page_url": "https://acme.test/plans",
                    "recheck": {"status": "verified", "changed_from_before": True, "checked_at": history.today()}}]
        with patch.object(work, "_actions", return_value=actions), patch.object(work, "_arm", return_value="holdout"):
            before = set(self.be.data)
            result = self.call("offers_list")
            self.assertIsNone(result["offer"])
            self.assertEqual(result["measures"]["verified_fixes_30d"], 1)
            self.assertEqual(set(self.be.data), before)

class DashboardAttributionTests(unittest.TestCase):
    def test_exact_ids_identify_imported_assigned_unassigned_and_unrelated_same_day_runs(self):
        import subprocess
        script = """
const assert = require('node:assert/strict');
global.window={CB:{flows:{},h:()=>{}}};
require('./site/app/pages.js');
const projects = [{project:'client-a', imported_dataset_ids:['old'], attributed_runs:{parent1:'managed'}},
                  {project:'client-b', imported_dataset_ids:['saved'], attributed_runs:{}}];
const check=(extras)=>window.CB.pages.importState({actorName:'ai-search-brand-monitor',id:'run1',
    defaultDatasetId:'fresh',status:'SUCCEEDED',finishedAt:'2026-11-19',...extras},projects);
assert.equal(check({defaultDatasetId:'saved'}).status,'imported');
assert.deepEqual(check({meta:{actorRunId:'parent1'}}),{status:'awaiting_import',projects:['client-a']});
assert.deepEqual(check({defaultDatasetId:'saved',meta:{actorRunId:'parent1'}}),{status:'awaiting_import',projects:['client-a']});
assert.equal(check({}).status,'unassigned');
assert.equal(check({actorName:'linkedin-profile-scraper'}).status,'unrelated');
assert.equal(check({status:'FAILED'}).status,'unrelated');
assert.equal(check({defaultDatasetId:null}).status,'unrelated');
"""
        subprocess.run(["node", "-e", script], cwd=pathlib.Path(__file__).resolve().parents[1], check=True)

    def test_selecting_another_project_updates_each_step_and_ignores_older_schedule_reply(self):
        import subprocess
        js = """
const assert=require('node:assert/strict');
class E {
  constructor(tag,attrs={},...children) {
    this.tag=tag; this.attrs=attrs; this.list=[]; this.listeners={}; this.value=attrs.value;
    this.list.push(...children.flat(Infinity).filter(Boolean));
    if(tag==='select') this.value=this.list[0]?.value;
  }
  addEventListener(evt,fn) { this.listeners[evt]=fn; }
  appendChild(el) { this.list.push(el); return el; }
  get text() { return [this.attrs.text,...this.list.map(x=>x.text)].filter(Boolean).join(' '); }
  get elements() { return [this,...this.list.flatMap(x=>x.elements||[])]; }
}
let callbacks={};
global.window={CB:{hasProjectWork:true,h:(...args)=>new E(...args),flows:{},clear:e=>{e.list=[];return e;},
  work:(slug,op)=>new Promise(r=>callbacks[slug]=r)}};
require('./site/app/pages.js');
(async()=>{
  let result=window.CB.pages.onboarding([{project:'client-a',rounds:1,last_site_check:'2026-11-02'},
                                         {project:'client-b',rounds:0,last_site_check:null}],()=>{});
  assert.match(result.text,/4 of 4/);
  let select=result.elements.find(e=>e.tag==='select');
  select.value='client-b';select.listeners.change();
  callbacks['client-b']({schedules:[]}); await new Promise(setImmediate);
  callbacks['client-a']({schedules:[{enabled:true}]}); await new Promise(setImmediate);
  assert.match(result.text,/2 of 4/);
  let steps=result.elements.filter(e=>e.tag==='li');
  assert.equal(steps.find(e=>e.text.includes('Schedule project')).attrs.class,'');
  assert.equal(steps.find(e=>e.text.includes('Connection unverified')).attrs.class,'');
})().catch(e=>{console.error(e);process.exitCode=1;});
"""
        subprocess.run(["node", "-e", js], cwd=pathlib.Path(__file__).resolve().parents[1], check=True)
