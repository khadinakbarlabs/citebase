"""The very first round can be imported into a brand-new project, and every refusal says what is actually wrong."""
import asyncio
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import history as hist  # noqa: E402
import runner  # noqa: E402
import storage as stg  # noqa: E402

PANEL = [{"prompt_id": f"p{i}", "prompt": f"question {i}", "type": t}
         for i, t in enumerate(["awareness", "awareness", "consideration", "consideration", "control", "control"], 1)]
BRAND = {"name": "Acme", "domain": "acme.com", "competitors": ["Rival"]}
AUDIT = {"site": "https://acme.com", "health_score": 70, "subscores": {"technical": 70}, "counts": {"fail": 1},
         "pages_checked": 5, "problems": [{"check": "Sitemap", "detail": "missing"}]}
ITEMS = [{"query": p["prompt"], "platform": "chatgpt", "brand_mentioned": p["prompt_id"] == "p1", "sentiment": "positive",
          "scraped_at": "2026-11-07T10:00:00Z", "model_used": "gpt-4o"} for p in PANEL]


def run(coro):
    return asyncio.run(coro)


def tool(name, **args):
    return run(runner.run_tool(name, args))


class Base(unittest.TestCase):
    def setUp(self):
        self.backend = stg.MemoryBackend()
        stg.set_backend(self.backend)
        self.addCleanup(stg.set_backend, None)


class ImportCreatesTheProjectTests(Base):
    def test_panel_brand_and_items_in_one_call_create_and_fill_the_project(self):
        out = tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", panel=PANEL, brand=BRAND,
                   save=True)
        self.assertEqual(out["saved"]["snapshots_saved"], {"baseline": len(PANEL)})
        self.assertEqual(out["saved"]["panel_prompts"], len(PANEL))
        self.assertEqual(out["saved"]["brand"]["name"], "Acme")
        data = run(hist.load_project("acme-site"))
        self.assertEqual(len(data["panel"]), len(PANEL))
        self.assertEqual(data["runs"][0]["engine_version"], "gpt-4o")

    def test_the_questions_are_frozen_afterwards(self):
        tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", panel=PANEL, save=True)
        changed = [dict(p) for p in PANEL]
        changed[0]["prompt"] = "a completely different question"
        with self.assertRaises(ValueError) as caught:
            tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="2026-12", panel=changed, save=True)
        self.assertIn("frozen", str(caught.exception))
        self.assertEqual([s["snapshot"] for s in run(hist.history("acme-site"))["snapshots"]], ["baseline"])

    def test_the_same_panel_sent_again_is_fine(self):
        tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", panel=PANEL, save=True)
        out = tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="2026-12", panel=PANEL, save=True)
        self.assertEqual(out["saved"]["snapshots_saved"], {"2026-12": len(PANEL)})

    def test_without_save_it_only_converts_and_stores_nothing(self):
        out = tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", panel=PANEL, brand=BRAND)
        self.assertEqual(out["summary"]["rows"], len(PANEL))
        self.assertIsNone(out["saved"])
        self.assertEqual(run(hist.list_projects()), [])
        self.assertTrue(any("not saved" in n for n in out["notes"]), out["notes"])

    def test_a_saved_brand_is_used_when_none_is_sent(self):
        run(hist.save_results("acme-site", [{"snapshot": "baseline", "prompt_id": "p1", "platform": "chatgpt",
                                             "recommended": True}], PANEL, brand=BRAND))
        item = {"query": "question 2", "responseText": "Acme is a choice.", "citations": [], "fetchedAt": "2026-11-07T11:00:00Z",
                "searchId": "s"}
        out = tool("import_ai_results", project="acme-site", items=[item], snapshot="2026-12")
        self.assertTrue(out["runs"][0]["mentioned"])

    def test_context_is_accepted_and_stamped(self):
        item = {"query": "question 2", "responseText": "Acme is a choice.", "citations": [], "fetchedAt": "2026-11-07T11:00:00Z",
                "searchId": "s"}
        out = tool("import_ai_results", project="acme-site", items=[item], snapshot="baseline", panel=PANEL, brand=BRAND,
                   context={"country": "us", "language": "en", "device": "desktop"}, save=True)
        row = run(hist.load_project("acme-site"))["runs"][0]
        self.assertEqual((row["country"], row["language"], row["device"]), ("US", "en", "desktop"))
        self.assertEqual(out["context"]["country"], "us")

    def test_a_bad_context_is_refused_plainly(self):
        with self.assertRaises(ValueError) as caught:
            tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", panel=PANEL,
                 context={"country": ["us"]})
        self.assertIn("context", str(caught.exception))
        with self.assertRaises(ValueError):
            tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", panel=PANEL, context="us")
        with self.assertRaises(ValueError) as caught:
            tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", panel=PANEL,
                 context={"planet": "mars"})
        self.assertIn("country", str(caught.exception))


class RefusalsSayWhatIsWrongTests(Base):
    def test_a_new_project_without_a_question_list_says_to_send_or_save_it_first(self):
        with self.assertRaises(ValueError) as caught:
            tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", save=True)
        message = str(caught.exception)
        self.assertIn("question list", message)
        self.assertIn("panel", message)
        self.assertIn("save_results", message)
        self.assertNotIn("matched a question", message)
        self.assertEqual(run(hist.list_projects()), [])  # nothing was created by a refused call

    def test_a_project_that_has_no_question_list_says_to_save_it_first(self):
        tool("save_results", project="acme-site", audit=AUDIT)  # an old-style audit-only project: no panel
        with self.assertRaises(ValueError) as caught:
            tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline")
        self.assertIn("save the question list first", str(caught.exception))

    def test_items_that_match_nothing_are_not_blamed_on_the_project(self):
        with self.assertRaises(ValueError) as caught:
            tool("import_ai_results", project="acme-site", items=[{"query": "zzz", "platform": "chatgpt"}],
                 snapshot="baseline", panel=PANEL, save=True)
        self.assertIn("same question text", str(caught.exception))
        self.assertEqual(run(hist.list_projects()), [])

    def test_a_refused_import_does_not_leave_a_half_made_project(self):
        diag = [{"platform": "diagnostic", "diagnostic_status": "error", "diagnostic_message": "blocked"}]
        with self.assertRaises(ValueError):
            tool("import_ai_results", project="acme-site", items=diag, snapshot="baseline", panel=PANEL, brand=BRAND,
                 save=True)
        self.assertEqual(run(hist.list_projects()), [])


class SaveResultsFirstSaveTests(Base):
    def test_panel_and_brand_alone_create_the_project(self):
        out = tool("save_results", project="acme-site", panel=PANEL, brand=BRAND)
        self.assertEqual(out["panel_prompts"], len(PANEL))
        self.assertEqual(out["snapshots_saved"], {})
        self.assertEqual(out["brand"]["name"], "Acme")
        self.assertIn("import_ai_results", out["next"])
        self.assertEqual(len(run(hist.load_project("acme-site"))["panel"]), len(PANEL))

    def test_panel_with_an_audit_keeps_the_panel(self):
        out = tool("save_results", project="acme-site", panel=PANEL, brand=BRAND, audit=AUDIT)
        self.assertEqual(out["panel_prompts"], len(PANEL))  # used to be dropped without a word
        self.assertIsNotNone(out["audit_saved"])
        self.assertEqual(out["brand"]["name"], "Acme")

    def test_then_the_first_round_imports_by_name_alone(self):
        tool("save_results", project="acme-site", panel=PANEL, brand=BRAND, audit=AUDIT)
        out = tool("import_ai_results", project="acme-site", items=ITEMS, snapshot="baseline", save=True)
        self.assertEqual(out["saved"]["snapshots_saved"], {"baseline": len(PANEL)})

    def test_a_brand_with_an_audit_is_kept_not_dropped(self):
        out = tool("save_results", project="acme-site", brand=BRAND, audit=AUDIT)
        self.assertEqual(out["brand"]["name"], "Acme")
        self.assertEqual(out["panel_prompts"], 0)

    def test_a_changed_panel_on_a_second_panel_only_save_is_refused(self):
        tool("save_results", project="acme-site", panel=PANEL)
        changed = [dict(p) for p in PANEL]
        changed[0]["prompt"] = "something else"
        with self.assertRaises(ValueError) as caught:
            tool("save_results", project="acme-site", panel=changed)
        self.assertIn("frozen", str(caught.exception))

    def test_experiments_alone_can_be_logged(self):
        tool("save_results", project="acme-site", panel=PANEL)
        out = tool("save_results", project="acme-site",
                   experiments=[{"action": "Joined a list", "mechanism": "listicle", "target_prompt_ids": "p1,p2,p3"}])
        self.assertEqual(out["snapshots_saved"], {})
        self.assertEqual(len(run(hist.load_project("acme-site"))["experiments"]), 1)

    def test_saving_nothing_still_says_what_can_be_sent(self):
        with self.assertRaises(ValueError) as caught:
            tool("save_results", project="acme-site")
        message = str(caught.exception)
        for word in ("runs", "audit", "panel"):
            self.assertIn(word, message)

    def test_runs_without_any_question_list_still_say_so(self):
        with self.assertRaises(ValueError) as caught:
            tool("save_results", project="acme-site", runs=[{"snapshot": "baseline", "prompt_id": "p1",
                                                             "platform": "chatgpt", "recommended": True}])
        self.assertIn("question list", str(caught.exception))


class OtherActorsEndToEndTests(Base):
    """A first round bought from Google AI Overviews alone: imported, saved, measured, honestly."""

    BIG_PANEL = ([{"prompt_id": f"a{n:02d}", "prompt": f"best tool number {n}", "type": "awareness"} for n in range(1, 21)]
                 + [{"prompt_id": f"x{n:02d}", "prompt": f"how do I bake bread {n}", "type": "control"} for n in range(1, 6)])

    def overview(self, prompt, cited):
        sources = [{"position": 1, "domain": "rival.example", "url": "https://rival.example/a", "title": "Rival"}]
        if cited:
            sources.append({"position": 2, "domain": "acme.com", "url": "https://acme.com/a", "title": "Acme"})
        return {"query": prompt, "aioPresent": True, "brandMatch": {"matched": cited, "position": 2 if cited else None},
                "sources": sources, "countryCode": "us", "languageCode": "en", "device": "desktop", "source": "camoufox",
                "scrapedAt": "2026-11-07T10:00:00Z", "warnings": []}

    def test_a_google_ai_overviews_round_is_saved_cited_not_recommended_and_not_warned_about_repeats(self):
        items = [self.overview(p["prompt"], p["prompt_id"] in {"a01", "a02", "a03"}) for p in self.BIG_PANEL]
        out = tool("import_ai_results", project="acme-site", items=items, snapshot="baseline", panel=self.BIG_PANEL,
                   brand=BRAND, save=True)
        self.assertEqual(out["saved"]["snapshots_saved"], {"baseline": 25})
        self.assertEqual(out["summary"]["cited"], 3)
        self.assertEqual(out["summary"]["recommended"], 0)
        self.assertEqual(out["summary"]["needs_review"], 3)
        measured = tool("measure_recommendation_share", project="acme-site")
        aio = measured["summary"]["google-aio"]
        self.assertAlmostEqual(aio["cited_rate"], 3 / 20, places=2)
        self.assertEqual(aio["recommendation_share"], 0.0)
        self.assertFalse([w for w in measured["warnings"] if "repeats" in w], measured["warnings"])
        self.assertEqual(measured["context"]["baseline"]["google-aio"]["country"], ["US"])
        history = run(hist.history("acme-site"))
        self.assertEqual(history["snapshots"][0]["context"]["google-aio"]["source"], ["camoufox"])

    def test_importing_more_of_the_same_round_under_other_settings_warns(self):
        items = [self.overview(p["prompt"], False) for p in self.BIG_PANEL]
        tool("import_ai_results", project="acme-site", items=items, snapshot="baseline", panel=self.BIG_PANEL, brand=BRAND,
             save=True)
        later = [dict(i, countryCode="de") for i in items]
        out = tool("import_ai_results", project="acme-site", items=later, snapshot="baseline", save=True, append=True)
        self.assertTrue(any("different country" in w for w in out["saved"]["warnings"]), out["saved"]["warnings"])


@unittest.skipUnless(importlib.util.find_spec("pydantic"), "pydantic is not installed")
class ModelTests(unittest.TestCase):
    def test_import_result_reports_what_was_skipped(self):
        import importer
        import models
        out = importer.convert(ITEMS + [{"platform": "diagnostic", "diagnostic_message": "x"}], PANEL, "baseline")
        parsed = models.ImportResult(**out)
        self.assertEqual(parsed.skipped[0]["reason"], "diagnostic")
        self.assertEqual(parsed.summary["skipped"], 1)
        self.assertEqual(parsed.detected, {"ai-brand-monitor": len(PANEL)})

    def test_import_context_model_has_described_fields(self):
        import models
        props = models.ImportContext.model_json_schema()["properties"]
        for field in ("country", "language", "device", "location"):
            self.assertTrue(props[field].get("description"), field)

    def test_measure_result_accepts_the_context(self):
        import models
        self.assertIn("context", models.MeasureResult.model_fields)


if __name__ == "__main__":
    unittest.main()
