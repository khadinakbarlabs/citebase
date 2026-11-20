import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "connector"))
import work_research as research


class ResearchTests(unittest.TestCase):
    def test_zero_demand_keeps_source(self):
        row = research.rows("keywords", [{"term": "apple", "search_volume": 0}], "CSV", "2026-01-01")[0]
        self.assertEqual(row["search_volume"], 0)
        self.assertEqual(row["provenance"], "user_imported")

    def test_wrong_page_host_fails(self):
        with self.assertRaises(ValueError):
            research.rows("pages", [{"term": "apple", "domain": "example.org", "url": "https://other.org/a", "position": 2}], "CSV", "2026-01-01")


from datetime import datetime
from types import SimpleNamespace as Obj
from unittest.mock import AsyncMock, Mock
import history
import storage


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.be = storage.MemoryBackend()
        storage.set_backend(self.be)
        self.addCleanup(storage.set_backend, None)
        self.project = {"meta": {"brand": {"name": "Alpha", "competitors": ["rival.com"]}},
                        "panel": [{"prompt_id": "q", "prompt": "Which CRM?", "topic": "CRM"}], "runs": []}
        self.view = research.report(self.project, {})
        self.jobs = research.plan(self.view)["jobs"]
        self.client = Mock()
        self.backend = Obj(selection=Obj(caller=self.client, owner="me"))
        self.run = Obj(id="a"*17, user_id="me", status="SUCCEEDED", act_id="actor",
                       default_dataset_id="ds", default_key_value_store_id="kv", finished_at=datetime.now())
        self.client.run.return_value.get = AsyncMock(return_value=self.run)
        self.client.actor.return_value.get = AsyncMock(return_value=Obj(id="actor"))
        ds = self.client.dataset.return_value
        ds.get = AsyncMock(return_value=Obj(id="ds", user_id="me", act_run_id=self.run.id, item_count=1))

    def inputs(self, actor):
        job = next(j for j in self.jobs if j["actor"] == actor)
        self.client.key_value_store.return_value.get_record = AsyncMock(return_value={"value": job["input"]})
        return job["input"]

    async def test_scope_checked_before_loading_dataset(self):
        self.run.user_id = "stranger"
        with self.assertRaises(ValueError):
            await research.run_rows(self.backend, self.run.id, self.view)
        self.client.dataset.assert_not_called()

    async def test_actor_and_market_mismatch(self):
        self.inputs(research.ACTOR)
        self.run.act_id = "other"
        with self.assertRaises(ValueError):
            await research.run_rows(self.backend, self.run.id, self.view)
        self.client.dataset.assert_not_called()
        self.run.act_id = "actor"
        self.client.dataset.return_value.list_items = AsyncMock(return_value=Obj(items=[{"keyword": "CRM", "locationCode": 2124, "languageCode": "en", "searchVolume": 200}]))
        with self.assertRaisesRegex(ValueError, "market"):
            await research.run_rows(self.backend, self.run.id, self.view)

    async def test_foreign_term_and_rival(self):
        for actor, row in [(research.SERP, {"search_query": "unrelated", "country_code": "US", "language_code": "en"}),
                           (research.TRAFFIC, {"domain": "wrong.org", "countryName": "United States", "languageCode": "en"})]:
            self.inputs(actor)
            self.client.dataset.return_value.list_items = AsyncMock(return_value=Obj(items=[row]))
            with self.assertRaises(ValueError):
                await research.run_rows(self.backend, self.run.id, self.view)

    async def test_project_revision_and_replay(self):
        await history.save_results("alpha", [], brand={"domain": "alpha.org"})
        args = {"expected_revision": 0, "source": "Search export", "observed_at": "2026-01-01",
                "pages": [{"term": "CRM", "url": "https://example.com/crm", "domain": "example.com", "position": 2, "estimated_traffic": 20}]}
        first = await research.execute("alpha", "research_import", args)
        replay = await research.execute("alpha", "research_import", args)
        self.assertEqual(first, replay)
        self.assertEqual(first, await research.execute("alpha", "research_get", {}))
        with self.assertRaises(ValueError):
            await research.execute("alpha", "research_import", {**args, "source": "Another export"})

    async def test_verified_ai_citations(self):
        inp = self.inputs(research.AI_ACTOR)
        row = {"platform": inp["platforms"][0], "query": "Which CRM?", "brand_mentioned": True,
               "brand_mention_count": 1, "sentiment": "positive", "competitor_mentions": ["rival.com"],
               "cited_urls": ["https://example.com/r"], "mention_position_score": 3}
        self.client.dataset.return_value.list_items = AsyncMock(return_value=Obj(items=[row]))
        result = await research.run_rows(self.backend, self.run.id, self.view)
        self.assertEqual(result["citations"][0]["url"], "https://example.com/r")
        self.assertEqual(result["ai"][1]["mentions"], 1)
        self.assertIsNone(result["ai"][0]["position"])

    async def test_serp_keeps_rank_and_volume_uses_organic_field(self):
        for actor, row, key, metric, expected in [
            (research.SERP, {"search_query": "CRM", "country_code": "US", "language_code": "en",
                             "organic_results": [{"url": "https://rival.com/guide", "position": 2}]},
             "pages", "position", 2),
            (research.TRAFFIC, {"domain": "rival.com", "countryName": "United States", "languageCode": "en",
                                "organicEtv": 97.5, "visits": 20000, "status": "OK"},
             "competitors", "estimated_organic_traffic", 97.5)]:
            self.inputs(actor)
            self.client.dataset.return_value.list_items = AsyncMock(return_value=Obj(items=[row]))
            result = await research.run_rows(self.backend, self.run.id, self.view)
            self.assertEqual(result[key][0][metric], expected)
            self.assertEqual(result[key][0]["run_id"], self.run.id)

    async def test_provisional_terms_only_quote_rank_discovery(self):
        project = dict(self.project, panel=[], onboarding={"stage": "competitors", "terms": [{"term": "CRM", "selected": True}]})
        jobs = research.plan(research.report(project, {}))["jobs"]
        self.assertIn(research.SERP, [j["actor"] for j in jobs])
        self.assertNotIn(research.ACTOR, [j["actor"] for j in jobs])

    async def test_ranked_keyword_source_estimate_and_scope(self):
        self.inputs(research.RANKED)
        row = {"target": "rival.com", "mode": "organic_keywords", "locationName": "United States",
               "languageCode": "en", "rank": 4, "keyword": "CRM systems", "estimatedTraffic": 17.2,
               "rankingUrl": "https://rival.com/top"}
        self.client.dataset.return_value.list_items = AsyncMock(return_value=Obj(items=[row]))
        result = await research.run_rows(self.backend, self.run.id, self.view)
        self.assertEqual(result["pages"][0]["estimated_traffic"], 17.2)
        row["rankingUrl"] = "https://other.com/poison"
        with self.assertRaises(ValueError):
            await research.run_rows(self.backend, self.run.id, self.view)

    async def test_delayed_import_retains_scope_after_other_measurements(self):
        actual = self.inputs(research.ACTOR)
        self.view["keywords"].append({"term": "CRM", "search_volume": 50})
        self.assertIsNotNone(research.match_job(self.view, actual))
        self.view["terms"] = ["unrelated"]
        self.assertIsNone(research.match_job(self.view, actual))

    async def test_ranked_recommendations_require_explicit_order(self):
        names = ["Alpha", "Rival"]
        text = "Our top recommendations:\n1. **Rival** — a choice for teams\n2. Alpha: reporting"
        self.assertEqual(research.numbered_recommendations(text, names), {"Rival": (1, "1. **Rival**"), "Alpha": (2, "2. Alpha")})
        for ambiguous in ("1. Rival\n2. Alpha", "Rival is followed by Alpha.",
                          "Top recommendations:\n2. Rival\n1. Alpha",
                          "Top recommendations:\n1. Rival and Alpha\n3. Rival",
                          "Top recommendations:\n1. Alpha\n2. Alpha"):
            self.assertEqual(research.numbered_recommendations(ambiguous, names), {})
        data = {**self.project, "meta": {"brand": {"name": "Alpha", "competitors": ["Rival"]}},
                "runs": [{"platform": "claude", "prompt_id": "q", "date": "2026-01-05", "snapshot": "first",
                          "mentioned": True, "competitors": "Rival", "answer_text": text}]}
        ai = research.report(data, {})["ai"]
        self.assertEqual([(r["brand"], r["position"], r["position_samples"]) for r in ai], [("Alpha", 2, 1), ("Rival", 1, 1)])

    async def test_new_rival_never_inherits_old_zero(self):
        base = {"platform": "claude", "prompt_id": "q", "date": "2026-01-05", "snapshot": "first",
                "mentioned": True, "competitors": ""}
        def result(row):
            return research.report({**self.project, "runs": [row]}, {})
        unknown = result(base)
        self.assertEqual([x["brand"] for x in unknown["ai"]], ["Alpha"])
        self.assertTrue(any(j["input"].get("platforms") == ["claude"] for j in research.plan(unknown)["jobs"]))
        known = result(dict(base, monitored_competitors=["rival.com"]))
        self.assertEqual((known["ai"][1]["mentions"], known["ai"][1]["answers"]), (0, 1))
        self.assertFalse(any(j["input"].get("platforms") == ["claude"] for j in research.plan(known)["jobs"]))
        positive = result(dict(base, competitors="rival.com"))
        self.assertEqual((positive["ai"][1]["mentions"], positive["ai"][1]["answers"]), (1, None))

    async def test_verified_run_retry_returns_latest_report_even_with_stale_revision(self):
        from unittest.mock import patch
        await history.save_results("alpha", [], brand={"domain": "alpha.org"})
        rid = self.run.id
        measurement = {"keywords": [{"term": "CRM", "search_volume": 4, "provenance": "verified_actor_run",
                                     "actor": research.ACTOR, "run_id": rid, "dataset_id": "ds"}]}
        with patch.object(research, "run_rows", AsyncMock(return_value=measurement)) as verified:
            await research.execute("alpha", "research_import", {"expected_revision": 0, "run_id": rid})
            second = await research.execute("alpha", "research_import", {
                "expected_revision": 1, "source": "Sheet", "observed_at": "2026-01-01",
                "keywords": [{"term": "support", "search_volume": 5}]})
            for revision in (0, 1, 2):
                self.assertEqual(await research.execute("alpha", "research_import", {
                    "run_id": rid, "expected_revision": revision}), second)
            verified.assert_awaited_once()
            with self.assertRaisesRegex(ValueError, "revision"):
                await research.execute("alpha", "research_import", {"run_id": "b"*17, "expected_revision": 0})

    async def test_private_saved_answers_yield_only_ranked_labels(self):
        text = "Top recommendations:\n1. Rival — private explanation\n2. Alpha: private reasoning"
        await history.save_results("alpha", [{"snapshot": "baseline", "prompt_id": "q", "platform": "claude",
                                               "answer_text": text, "competitors": "Rival", "mentioned": True,
                                               "recommended": True}], panel=[{"prompt_id": "q", "type": "awareness", "prompt": "Which CRM?"}],
                                   brand={"name": "Alpha", "domain": "alpha.org", "competitors": ["Rival"]})
        saved = await history.load_project("alpha")
        self.assertNotIn("answer_text", saved["runs"][0])
        result = await research.execute("alpha", "research_get", {})
        self.assertEqual([r["position"] for r in result["ai"]], [2, 1])
        self.assertNotIn("private reasoning", str(result))

    async def test_first_party_history_and_google_provenance(self):
        await history.save_results("alpha", [], brand={"name": "Alpha", "domain": "alpha.org"})
        await history.save_signal("alpha", "search", {"clicks": 8, "impressions": 100,
                                  "top_questions": [{"query": "Which CRM?", "clicks": 8, "impressions": 100, "position": 3.5}]})
        await history.save_signal("alpha", "traffic", {"all_visits": 40, "ai_visits": 2})
        get = lambda: research.execute("alpha", "research_get", {})
        view = await get()
        self.assertEqual(view["first_party"]["gsc"]["provenance"], "user_imported")
        self.assertEqual(view["first_party"]["ga4"]["all_visits"], 40)
        for service, source, rows in [("ga4", "Google Analytics 4", [{"source": "chatgpt.com", "sessions": 10}]),
                                      ("gsc", "Google Search Console", [{"term": "CRM", "position": 3, "clicks": 14, "impressions": 60}])]:
            for site, day in [("alpha.org", "2026-01-25"), ("other.org", "2026-01-27")]:
                record = dict(service=service, source=source, website=site, property="owned", start_date="2026-01-01", end_date=day,
                              observed_at="2026-01-28", rows=rows)
                await self.be.set(storage.key("alpha", "google", service, day), record)
        view = await get()
        self.assertEqual(view["first_party"]["gsc"]["rows"][0]["clicks"], 14)
        self.assertEqual(view["first_party"]["ga4"]["rows"][0]["sessions"], 10)
        self.assertEqual(view["first_party"]["ga4"]["end_date"], "2026-01-25")
        self.assertEqual(view["first_party"]["gsc"]["provenance"], "google_sync")
        self.assertEqual(view["keywords"], [])

    async def test_same_source_observation_is_counted_once_across_imports(self):
        row = dict(prompt_id="q", platform="claude", source_dataset_id="dataset01", date="2026-01-01", mentioned=True)
        project = {**self.project, "runs": [dict(row, snapshot="first"), dict(row, snapshot="copy")]}
        self.assertEqual(sum(x["answers"] for x in research.report(project, {})["ai"]), 1)
        verified = {"ai": [dict(term="Which CRM?", engine="Claude", brand="Alpha", answers=1,
                                 dataset_id="dataset01", provenance="verified_actor_run")]}
        self.assertEqual(research.report(project, verified)["ai"], verified["ai"])

    async def test_website_change_hides_legacy_google_mirrors(self):
        await history.save_results("alpha", [], brand={"name": "Alpha", "domain": "alpha.org"})
        await history.save_signal("alpha", "search", {"clicks": 12, "impressions": 35})
        await history.save_signal("alpha", "traffic", {"all_visits": 26})
        for service, source in (("gsc", "Google Search Console"), ("ga4", "Google Analytics 4")):
            await self.be.set(storage.key("alpha", "google", service, "2026-01-25"),
                              dict(service=service, source=source, website="alpha.org", property="alpha",
                                   start_date="2026-01-01", end_date="2026-01-25", rows=[]))
        meta_key = storage.key("alpha", "meta")
        meta = await self.be.get(meta_key)
        await self.be.set(meta_key, {**meta, "brand": {"domain": "bravo.org"}})
        result = await research.execute("alpha", "research_get", {})
        self.assertEqual(result["first_party"], {"gsc": None, "ga4": None})
