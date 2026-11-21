import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))

import runner
import storage


class ProspectReportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = storage.MemoryBackend()
        storage.set_backend(self.backend)
        self.addCleanup(storage.set_backend, None)
        await runner.run_tool("save_results", {
            "project": "internal-client", "brand": {"name": "Acme <North>", "domain": "example.com"},
            "todo": [{"step": "Private follow-up", "status": "open"}],
            "panel": [{"prompt_id": "buy", "prompt": "Private test question", "type": "awareness"}],
        })

    async def share(self):
        return await runner.run_tool("make_report", {"project": "internal-client", "prospect": True})

    async def test_prospect_report_requires_buying_answers(self):
        with self.assertRaisesRegex(ValueError, "buying"):
            await self.share()

    async def test_only_shareable_fields_appear_in_a_separate_report_store(self):
        await runner.run_tool("save_results", {"project": "internal-client", "runs": [{
            "snapshot": "baseline", "prompt_id": "buy", "platform": "chatgpt", "recommended": False,
            "answer_text": "Private answer text", "date": "2026-11-18",
        }]})
        result = await self.share()
        self.assertEqual(result["stored_key"], (await self.share())["stored_key"])
        self.assertNotIn(result["stored_key"], self.backend.data)
        share_store = await self.backend.prospect_store()
        page = await share_store.get(result["stored_key"])
        self.assertIn("How AI sees Acme &lt;North&gt;", page)
        self.assertIn("0.0%", page)
        self.assertIn("ChatGPT", page)
        self.assertIn("noindex", page)
        for private in ("Private follow-up", "Private test question", "Private answer text", "internal-client", "<script"):
            self.assertNotIn(private, page)
