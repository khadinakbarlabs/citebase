import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))

import runner
import storage

PANEL = [{"prompt_id": "buy", "prompt": "Best notebooks?", "type": "awareness"}]
ITEM = {"query": "Best notebooks?", "platform": "chatgpt", "brand_mentioned": True,
        "brand_mention_count": 1, "sentiment": "positive",
        "ai_response_summary": "Acme makes notebooks in Canada.\nAcme ships to five countries.",
        "answer_truncated": True}


class FactChecksTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = storage.MemoryBackend()
        storage.set_backend(self.backend)
        self.addCleanup(storage.set_backend, None)
        self.backend.datasets["dataset01"] = [ITEM]
        self.backend.dataset_sources["dataset01"] = "khadinakbar/ai-search-brand-monitor"
        await runner.run_tool("import_ai_results", {
            "project": "acme", "panel": PANEL, "brand": {"name": "Acme", "domain": "example.com"},
            "snapshot": "baseline", "save": True, "dataset_ids": ["dataset01"],
        })

    async def review(self):
        result = await runner.run_tool("get_history", {
            "project": "acme", "answer_review": {"snapshot": "baseline"},
        })
        return result["answer_review"]

    async def submit(self, **overrides):
        answer = (await self.review())["answers"][0]
        claim = {"answer_id": answer["answer_id"], "quote": "Acme makes notebooks in Canada.",
                 "verdict": "false", "source_url": "https://example.com/about",
                 "evidence": "All notebooks are made in Portugal."}
        return await runner.run_tool("save_results", {
            "project": "acme",
            "fact_checks": {"snapshot": "baseline", "claims": [{**claim, **overrides}]},
        })

    async def test_saved_text_is_preserved_and_shown_only_on_request(self):
        result = await runner.run_tool("get_history", {"project": "acme"})
        self.assertNotIn(ITEM["ai_response_summary"], str(result))
        view = await self.review()
        self.assertEqual(view["answers"][0]["text"], ITEM["ai_response_summary"])
        self.assertTrue(view["answers"][0]["truncated"])

    async def test_verdicts_have_evidence_and_survive_a_reload(self):
        await self.submit()
        await self.submit()
        view = await self.review()
        self.assertEqual([(c["verdict"], c["source_url"]) for c in view["claims"]],
                         [("false", "https://example.com/about")])
        history = await runner.run_tool("get_history", {"project": "acme"})
        self.assertEqual(history["fact_check_summary"]["false"], 1)

    async def test_decisive_verdict_requires_evidence_and_real_quote(self):
        for change in ({"source_url": ""}, {"evidence": ""}, {"quote": "Invented quote."},
                       {"source_url": "https://example.com/?token=private"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                await self.submit(**change)
        self.assertEqual((await self.review())["claims"], [])

    async def test_legacy_answers_remain_readable_and_cannot_be_fact_checked(self):
        await runner.run_tool("save_results", {"project": "acme", "runs": [{
            "snapshot": "legacy", "prompt_id": "buy", "platform": "chatgpt", "recommended": True,
        }]})
        view = await runner.run_tool("get_history", {
            "project": "acme", "answer_review": {"snapshot": "legacy"},
        })
        self.assertEqual(view["answer_review"]["answers"], [])
        self.assertEqual(view["answer_review"]["missing_text"], 1)

    async def test_replacing_answer_invalidates_its_review(self):
        await self.submit()
        await runner.run_tool("save_results", {"project": "acme", "replace": True, "runs": [{
            "snapshot": "baseline", "prompt_id": "buy", "platform": "chatgpt", "recommended": True,
            "answer_text": "A different answer.",
        }]})
        self.assertEqual((await self.review())["claims"], [])

    async def test_dataset_preview_does_not_copy_the_answer_into_chat(self):
        preview = await runner.run_tool("import_ai_results", {
            "project": "acme", "dataset_ids": ["dataset01"], "snapshot": "preview",
        })
        self.assertNotIn("answer_text", preview["runs"][0])

    async def test_same_wording_in_a_different_sample_does_not_reuse_the_review(self):
        await self.submit()
        await runner.run_tool("save_results", {"project": "acme", "replace": True, "runs": [{
            "snapshot": "baseline", "prompt_id": "buy", "platform": "chatgpt", "recommended": True,
            "answer_text": ITEM["ai_response_summary"], "answer_truncated": True, "date": "2026-10-01",
        }]})
        self.assertEqual((await self.review())["claims"], [])

    async def test_raw_answers_and_verdicts_are_in_the_private_store(self):
        await self.submit()
        raw = ITEM["ai_response_summary"]
        self.assertNotIn(raw, str(self.backend.data))
        private = await self.backend.private_store()
        records = await private.keys("p.acme.answers.baseline.")
        self.assertEqual(len(records), 1)
        self.assertIn(raw, (await private.get(records[0])).values())
        self.assertIsNone(await self.backend.get("p.acme.facts.baseline"))
        self.assertEqual((await private.get("p.acme.facts.baseline"))[0]["verdict"], "false")

    async def test_replacing_a_round_does_not_overwrite_the_prior_storage_record(self):
        private = await self.backend.private_store()
        before = await private.keys("p.acme.answers.baseline")
        self.assertEqual(len(before), 1)
        await runner.run_tool("save_results", {"project": "acme", "replace": True, "runs": [{
            "snapshot": "baseline", "prompt_id": "buy", "platform": "chatgpt", "recommended": True,
            "answer_text": "Another answer.",
        }]})
        after = await private.keys("p.acme.answers.baseline")
        self.assertEqual(len(after), 2)
        self.assertEqual(list((await private.get(before[0])).values()), [ITEM["ai_response_summary"]])
        self.assertEqual((await self.review())["answers"][0]["text"], "Another answer.")
