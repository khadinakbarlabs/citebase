"""The signed-in focus list reads the selected project without changing its saved state."""
import copy
import json
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "connector"))
import history
import project_work
import storage
import work_actions
import work_insights


class FocusTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.be = storage.MemoryBackend()
        storage.set_backend(self.be)
        self.addCleanup(storage.set_backend, None)
        self.enterContext(patch("work_auth.require_caller", new_callable=AsyncMock))
        self.enterContext(patch.object(history, "today", return_value="2026-11-19"))
        await history.save_results("alpha", [], brand={"domain": "example.org"})
        await history.save_results("bravo", [], brand={"domain": "example.org"})

    async def focus(self, slug="alpha", **fields):
        return (await project_work.execute(slug, "project_focus", fields))["result"]

    async def action(self, **fields):
        return (await work_actions.execute("alpha", "action_save", fields))["action"]

    async def test_new_project_is_empty_and_no_storage_is_created(self):
        meta = copy.deepcopy(self.be.data)
        with patch.object(self.be, "private_store", side_effect=AssertionError("created private store")):
            result = await self.focus()
        self.assertEqual(result, {"items": [], "counts": dict(review=0, overdue=0, open=0, opportunity=0),
                                  "total": 0, "matched_total": 0, "as_of": "2026-11-19"})
        self.assertEqual(self.be.data, meta)
        self.assertIsNone(self.be._private)
        with self.assertRaises(ValueError):
            await self.focus("unknown")

    async def test_legacy_view_agrees_without_migrating_or_writing_a_new_revision(self):
        await history.save_results("alpha", [], todo=[{"step": "Check prices", "status": "open"}])
        first, = (await self.focus())["items"]
        self.assertIsNone(self.be._private)
        self.assertEqual((first["title"], first["priority"]), ("Check prices", "open"))
        edited = await self.action(id=first["record_id"], expected_revision=0, title="Review prices", owner="Sam")
        await history.save_results("alpha", [], todo=[{"step": "Check prices", "status": "skipped"}])
        raw = copy.deepcopy(self.be._private.data)
        self.assertEqual((await self.focus())["items"], [])
        self.assertEqual(raw, self.be._private.data)
        self.assertEqual(edited["id"], first["id"])

    async def test_ranking_disjoint_counts_subsets_and_private_output(self):
        page = "https://example.org/plans"
        review = await self.action(title="Check the plan title", page_url=page, after_title="Private edit wording",
                                   due_date="2026-11-10", owner="sam@example.org")
        late = await self.action(title="Give the pricing team a brief", status="in_progress", due_date="2026-11-15",
                                 evidence_url="https://example.org/pricing", owner="Pricing team")
        open_action = await self.action(title="Review the signup form", due_date="2026-11-19", owner="Web team")
        await self.action(title="Call support@example.org", evidence="Contact +1 (212) 555-7878.",
                          evidence_url="https://example.org/contact/support%40example.org")
        await self.action(title="Completed", status="done")
        await self.action(title="Dismissed", status="skipped")
        await work_actions.execute("bravo", "action_save", {"title": "Other project only"})
        await history.save_audit("alpha", {"health_score": 70, "site": page, "pages_checked": 3, "problems": [
            {"check": "Missing H1", "detail": "One page has no H1.", "example_urls": [page]}]})
        with patch.object(work_actions.sa, "fetch", side_effect=AssertionError("external page check")):
            value = await self.focus(limit=2)
            filtered = await self.focus(limit="20", priority="open")
        self.assertEqual(value["counts"], dict(review=1, overdue=1, open=2, opportunity=1))
        self.assertEqual((value["total"], value["matched_total"]), (5, 5))
        self.assertEqual([r["record_id"] for r in value["items"]], [review["id"], late["id"]])
        self.assertEqual(filtered["counts"], value["counts"])
        self.assertEqual((filtered["total"], filtered["matched_total"]), (5, 2))
        self.assertEqual(filtered["items"][0]["id"], open_action["id"])
        self.assertTrue(all(r["section"] == "todo" and r["reason"] and r["next_step"] for r in filtered["items"]))
        self.assertEqual(value["items"][0]["evidence_url"], page)
        self.assertEqual(value["items"][1]["owner"], "Pricing team")
        result = json.dumps(await self.focus(limit=20))
        for private in ("support@example", "support%40", "555-7878", "sam@example", "Private edit wording",
                        "Other project only", "history", "technical_ticket"):
            self.assertNotIn(private, result)

    async def test_finding_identity_and_verified_or_dismissed_actions_do_not_resurface(self):
        page = "https://example.org/plans"
        problem = {"check": "Title missing", "detail": "Inspect the title.", "example_urls": [page]}
        await history.save_audit("alpha", {"site": page, "health_score": 75, "pages_checked": 2,
                                           "problems": [problem, problem]})
        pending, = (await self.focus())["items"]
        original = (await work_insights.execute("alpha", "opportunities_list", {}))["opportunities"][0]
        self.assertEqual(pending["id"], original["id"])
        self.assertEqual((pending["kind"], pending["section"], pending["evidence_url"]),
                         ("opportunity", "evidence", page))
        fix = await self.action(title="Use a specific title", page_url=page, after_title="Plans", finding_id=original["id"])
        self.assertEqual((await self.focus())["counts"], dict(review=1, overdue=0, open=0, opportunity=0))
        response = {"status": 200, "body": b"<title>Plans</title>", "headers": {"content-type": "text/html"}}
        with patch.object(work_actions.sa, "fetch", return_value=response):
            await work_actions.execute("alpha", "action_recheck", {"id": fix["id"], "expected_revision": 1})
        self.assertEqual((await self.focus())["total"], 0)
        await self.action(id=fix["id"], expected_revision=2, status="skipped")
        self.assertEqual((await self.focus())["total"], 0)

    async def test_action_with_only_a_finding_id_keeps_its_dated_evidence(self):
        page = "https://example.org/start"
        await history.save_audit("alpha", {"site": page, "health_score": 75, "pages_checked": 2, "problems": [
            {"check": "Missing title", "detail": "One page has no HTML title.", "example_urls": [page]}]})
        finding, = (await self.focus())["items"]
        await self.action(title="Fix the starter page", finding_id=finding["id"])
        action, = (await self.focus())["items"]
        self.assertEqual(action["kind"], "action")
        self.assertEqual((action["evidence_url"], action["observed_on"]), (page, "2026-11-19"))
        self.assertIn("HTML title", action["reason"])

    async def test_only_measured_buying_questions_in_latest_observed_round_become_findings(self):
        panel = [{"prompt_id": k, "prompt": "Which " + k, "type": "consideration"} for k in ("pricing", "features")]
        row = {"prompt_id": "pricing", "platform": "chatgpt", "recommended": False,
               "snapshot": "current", "date": "2026-11-17", "answer_text": "PRIVATE FULL ANSWER"}
        await history.save_results("alpha", [row], panel=panel, source_ids=["datasetA"])
        await history.save_results("alpha", [{**row, "snapshot": "late-import", "date": "2026-10-13",
                                              "recommended": True}], source_ids=["datasetB"])
        with patch.object(self.be._private, "get", wraps=self.be._private.get) as read:
            item, = (await self.focus())["items"]
        self.assertIn("Which pricing", item["title"])
        self.assertIn("1", item["reason"])
        self.assertTrue(item["evidence_url"].endswith("datasetA"))
        self.assertEqual(item["observed_on"], "2026-11-17")
        self.assertFalse(any("answers." in call.args[0] for call in read.await_args_list))
        self.assertNotIn("PRIVATE FULL ANSWER", str(item))

    async def test_source_links_on_later_backfills_are_exact_for_each_finding(self):
        panel = [{"prompt_id": key, "prompt": "Which " + key, "type": "consideration"} for key in ("plans", "tools")]
        row = {"snapshot": "november", "date": "2026-11-17", "platform": "chatgpt", "recommended": False,
               "competitors": "Rival", "cited_domains": "publisher.test"}
        november = [{**row, "prompt_id": "plans", "date": "2026-11-15", "source_dataset_id": "datasetA"},
                    {**row, "prompt_id": "tools", "source_dataset_id": "datasetA"},
                    {**row, "prompt_id": "tools", "repeat": 2, "source_dataset_id": "datasetB"}]
        for slug, source_ids in (("alpha", ["datasetA", "datasetB"]), ("bravo", [])):
            with self.subTest(slug=slug):
                with patch.object(history, "today", return_value="2026-11-18"):
                    await history.save_results(slug, november, panel=panel, source_ids=source_ids)
                await history.save_results(slug, [{**row, "prompt_id": "plans", "snapshot": "october",
                                                   "date": "2026-10-13", "recommended": True}])
                project_data = await history.load_project(slug)
                self.assertEqual(history.snapshot_trend(project_data)[-1]["snapshot"], "october")
                findings = (await work_insights.execute(slug, "opportunities_list", {}))["opportunities"]
                cards = {i["record_id"]: i for i in (await self.focus(slug))["items"]}
                self.assertEqual(len(findings), 3)
                for finding in findings:
                    card = cards[finding["id"]]
                    measured = "2026-11-15" if finding["question"] == "Which plans" else "2026-11-17"
                    self.assertEqual((finding["snapshot"], finding["observed_on"], card["observed_on"]),
                                     ("november", measured, measured))
                    if source_ids and finding["question"] == "Which plans":
                        self.assertTrue(finding["evidence_url"].endswith("datasetA"))
                        self.assertEqual(card["evidence_url"], finding["evidence_url"])
                    else:
                        self.assertIsNone(finding["evidence_url"])
                        self.assertNotIn("evidence_url", card)

    async def test_older_undated_answers_keep_the_finding_without_an_invented_observation_date(self):
        await history.save_results("alpha", [{"snapshot": "legacy", "date": "2026-11-18", "platform": "chatgpt",
                                              "prompt_id": "q", "recommended": False}],
                                   panel=[{"prompt_id": "q", "prompt": "Which plan?", "type": "consideration"}])
        del self.be.data["p.alpha.runs.legacy"][0]["date"]
        card, = (await self.focus())["items"]
        self.assertNotIn("observed_on", card)
        finding, = (await work_insights.execute("alpha", "opportunities_list", {}))["opportunities"]
        self.assertEqual(finding["snapshot"], "legacy")
        self.assertIsNone(finding["observed_on"])

    async def test_combined_page_mismatch_only_identifies_an_established_difference(self):
        item = await self.action(title="Review metadata", page_url="https://example.org/pricing",
                                 after_title="Plans", after_description="The new plan terms.")
        response = {"status": 200, "body": b'<title>Plans</title><meta name="description" content="Old terms.">',
                    "headers": {"content-type": "text/html"}}
        with patch.object(work_actions.sa, "fetch", return_value=response):
            checked = (await work_actions.execute("alpha", "action_recheck", {"id": item["id"], "expected_revision": 1}))["action"]
        self.assertEqual((checked["recheck"]["status"], checked["recheck"]["observed_title"]), ("mismatch", "Plans"))
        card, = (await self.focus())["items"]
        self.assertEqual(card["priority"], "review")
        self.assertNotIn("title", card["reason"].lower())
        self.assertIn("differ", card["reason"].lower())

    async def test_focus_omits_private_links_and_encoded_contacts_in_free_text(self):
        await self.action(title="Contact support%40example.org", evidence="See https://example.org/x?token=privatepass",
                          evidence_url="https://example.org/contact/support%2540example.org")
        item, = (await self.focus())["items"]
        self.assertNotIn("evidence_url", item)
        self.assertNotIn("support", str(item))
        self.assertNotIn("privatepass", str(item))

    async def test_incomplete_round_does_not_look_like_an_empty_or_missing_project(self):
        self.be.data["p.alpha.meta"]["snapshots"] = {"missing-round": "2026-11-17"}
        with self.assertRaisesRegex(ValueError, "incomplete|reload|Reload"):
            await self.focus()

    async def test_failed_audit_checks_and_better_sampled_questions_rank_first(self):
        await history.save_audit("alpha", {"health_score": 55, "problems": [
            {"check": "A warning", "detail": "A small omission.", "level": "warn"},
            {"check": "Zoom page missing", "detail": "The page returned a 404.", "level": "fail"}]})
        panel = [{"prompt_id": k, "prompt": "Which " + k, "type": "consideration"} for k in ("alpha", "zoom")]
        row = {"snapshot": "current", "date": "2026-11-15", "platform": "chatgpt", "recommended": False}
        await history.save_results("alpha", [{**row, "prompt_id": "alpha"}, {**row, "prompt_id": "zoom"},
                                              {**row, "prompt_id": "zoom", "repeat": 2}], panel=panel)
        first, second, third, fourth = (await self.focus())["items"]
        self.assertEqual((first["title"], second["title"]), ("Zoom page missing", "A warning"))
        self.assertIn("404", first["reason"])
        self.assertIn("Page count unavailable", first["reason"])
        self.assertIn("Which zoom", third["title"])
        self.assertIn("Which alpha", fourth["title"])

    async def test_bad_saved_audit_and_missing_measurements_are_not_reported_as_evidence(self):
        await history.save_audit("alpha", {"health_score": 60, "problems": [{"check": "Title"}]})
        self.be.data["p.alpha.audit.2026-11-19"]["status"] = "unreadable"
        with self.assertRaisesRegex(ValueError, "incomplete"):
            await self.focus()
        self.be.data["p.alpha.audit.2026-11-19"]["status"] = "ok"
        await history.save_results("alpha", [{"snapshot": "round", "date": "2026-11-18", "platform": "chatgpt",
                                              "prompt_id": "p1", "recommended": False}],
                                   panel=[{"prompt_id": "p1", "prompt": "Which tool?", "type": "consideration"}])
        del self.be.data["p.alpha.runs.round"][0]["recommended"]
        with self.assertRaisesRegex(ValueError, "incomplete"):
            await self.focus()

    async def test_filter_reaches_items_beyond_the_display_limit(self):
        for i in range(22):
            await self.action(title=f"Review title {i}", page_url="https://example.org/plans", after_title=str(i))
        await history.save_audit("alpha", {"health_score": 65, "problems": [{"check": "No canonical"}]})
        first = await self.focus(limit=20)
        specific = await self.focus(priority="opportunity", limit=20)
        self.assertTrue(all(item["kind"] == "action" for item in first["items"]))
        self.assertEqual((len(first["items"]), specific["total"], specific["matched_total"]), (20, 23, 1))
        self.assertEqual(specific["items"][0]["title"], "No canonical")

    async def test_reads_each_round_once_and_bounds_full_action_records_per_batch(self):
        from collections import Counter
        panel = [{"prompt_id": "q", "prompt": "Which plan?", "type": "consideration"}]
        for i in range(10):
            await history.save_results("alpha", [{"snapshot": f"week-{i}", "date": f"2026-10-{10+i}",
                                                  "prompt_id": "q", "platform": "chatgpt", "recommended": False}],
                                       panel=panel)
        for i in range(25):
            await self.action(title=f"Task {i}")
        reader = work_actions.RevisionStore.entries
        batches = []

        async def track(reader_self, keys):
            keys = list(keys)
            batches.append(len({k.rpartition(".v.")[0] for k in keys}))
            return await reader(reader_self, keys)

        with patch.object(self.be, "get", wraps=self.be.get) as read, \
                patch.object(work_actions.RevisionStore, "entries", autospec=True, side_effect=track):
            result = await self.focus(limit=1)
        rounds = Counter(c.args[0] for c in read.await_args_list if c.args[0].startswith("p.alpha.runs."))
        self.assertEqual((len(rounds), set(rounds.values())), (10, {1}))
        self.assertEqual(result["total"], 26)
        self.assertEqual(sum(batches), 25)
        self.assertLessEqual(max(batches), 12)

    async def test_invalid_filter_limit_and_project_are_rejected(self):
        for fields in ({"limit": True}, {"limit": 0}, {"limit": 21}, {"limit": 2.3}, {"limit": "4.0"},
                       {"priority": "urgent"}, {"priority": []}, {"priority": None}, {"owner": "team"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                await self.focus(**fields)
        with self.assertRaises(ValueError):
            await self.focus("ALPHA")


class FocusTransport(unittest.IsolatedAsyncioTestCase):
    async def test_auth_and_results_match_for_named_http_run_and_mcp(self):
        from starlette.testclient import TestClient
        from server import build_app
        storage.set_backend(storage.MemoryBackend())
        self.addCleanup(storage.set_backend, None)
        await history.save_results("alpha", [], todo=[{"step": "Review the homepage", "status": "open"}])
        name = "project_work"
        args = {"project": "alpha", "operation": "project_focus", "data": {"limit": 1, "priority": "open"}}
        rpc = {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": args}}
        headers = {"Accept": "application/json, text/event-stream"}
        with TestClient(build_app()) as client:
            self.assertEqual(client.get("/v1/projects/alpha/focus").status_code, 401)
            self.assertEqual(client.post("/run", json={"tool": name, "arguments": args}).status_code, 401)
            self.assertTrue(client.post("/mcp", json=rpc, headers=headers).json()["result"]["isError"])
            with patch("work_auth.require_caller", new_callable=AsyncMock):
                direct = client.get("/v1/projects/alpha/focus?limit=1&priority=open")
                self.assertEqual(direct.status_code, 200, direct.text)
                self.assertEqual(direct.headers["cache-control"], "private, no-store")
                self.assertEqual(client.get("/v1/projects/alpha/focus?limit=21").status_code, 400)
                self.assertEqual(client.post("/run", json={"tool": name, "arguments": args}).json()["result"],
                                 direct.json())
                self.assertEqual(client.post("/mcp", json=rpc, headers=headers).json()["result"]["structuredContent"],
                                 direct.json())
