import asyncio
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "connector"))

import storage
import work_outreach

PROSPECT = dict(recipientType="editor", email="Ali@example.org",
                sourceUrl="https://example.org/review", asset="Survey findings",
                readerFit="Readers asked for local data", contactProvenance="Article byline")
DRAFT = dict(subject="Survey for your review", body="We have survey data for your article. If this isn't relevant, just tell me and I won't write again.\n\nAli Example\nExample Research")


class OutreachTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.locks = patch.dict(work_outreach.history._locks, {}, clear=True)
        self.locks.start()
        self.addCleanup(self.locks.stop)
        self.backend = storage.MemoryBackend()
        storage.set_backend(self.backend)
        self.addCleanup(storage.set_backend, None)
        for project in ("alpha", "bravo"):
            await self.backend.set(storage.key(project, "meta"), {"project": project})

    async def call(self, op, project="alpha", **data):
        return await work_outreach.execute(project, op, data)

    async def test_exact_version_and_recipient_suppression(self):
        prospect = (await self.call("prospect_save", **PROSPECT))["prospect"]
        pid = prospect["id"]
        draft = (await self.call("draft_save", prospectId=pid, **DRAFT))["draft"]
        version = draft["version"]
        approved = (await self.call("draft_approve", prospectId=pid, version=version, expected_revision=draft["revision"]))["draft"]
        self.assertTrue(approved["approved"])
        edited = (await self.call("draft_save", prospectId=pid, expected_revision=approved["revision"], **{**DRAFT, "subject": "Updated"}))["draft"]
        self.assertFalse(edited["approved"])
        with self.assertRaises(ValueError):
            await self.call("draft_approve", prospectId=pid, version=version)
        await self.call("prospect_save", project="bravo", **PROSPECT, outcome="opted_out")
        with self.assertRaises(ValueError):
            await self.call("draft_approve", prospectId=pid, version=edited["version"])
        self.assertTrue((await self.call("prospects_list"))["prospects"][0]["suppressed"])
        self.assertNotIn("example.org", json.dumps(self.backend.data))

    async def test_dedup_proof_and_privacy(self):
        rows = await asyncio.gather(*[self.call("prospect_save", **PROSPECT) for _ in range(2)])
        self.assertEqual(rows[0], rows[1])
        pid = rows[0]["prospect"]["id"]
        with self.assertRaises(ValueError):
            await self.call("prospect_save", id=pid, outcome="placement_verified")
        await self.call("prospect_save", id=pid, expected_revision=rows[0]["prospect"]["revision"], outcome="placement_verified", proofUrl="https://example.org/citation")
        self.assertFalse((await self.call("digest_get"))["enabled"])
        result = await self.call("digest_save", enabled=True, recipients=["client@example.org"], muteUnchanged=True)
        self.assertEqual(result["delivery"], "in_app")
        self.assertNotIn("@", str(result["preview"]))
        self.assertIn("1", result["preview"]["whatChanged"])
        with self.assertRaises(ValueError):
            await self.call("digest_save", enabled=True, recipients="client@example.org", muteUnchanged=False)

    async def test_project_scope_and_account_isolation(self):
        self.backend.project_store_id = "storage001"
        row = (await self.call("prospect_save", **PROSPECT, outcome="opted_out"))["prospect"]
        self.backend.project_store_id = "storage002"
        self.assertFalse((await self.call("prospects_list"))["prospects"])
        with self.assertRaises(ValueError):
            await self.call("draft_save", prospectId=row["id"], **DRAFT)
        same = (await self.call("prospect_save", **PROSPECT))["prospect"]
        self.assertTrue(same["suppressed"])
        other = storage.MemoryBackend()
        await other.set(storage.key("alpha", "meta"), {"project": "alpha"})
        storage.set_backend(other)
        self.assertFalse((await self.call("prospect_save", **PROSPECT))["prospect"]["suppressed"])

    async def test_closed_draft_and_weekly_outcome_history(self):
        pid = (await self.call("prospect_save", **PROSPECT))["prospect"]["id"]
        draft = (await self.call("draft_save", prospectId=pid, **DRAFT))["draft"]
        await self.call("draft_approve", prospectId=pid, version=draft["version"], expected_revision=draft["revision"])
        revision = 1
        for outcome in ("contacted", "replied"):
            saved = await self.call("prospect_save", id=pid, outcome=outcome, expected_revision=revision)
            revision = saved["prospect"]["revision"]
        await self.call("prospect_save", id=pid, expected_revision=revision, outcome="placement_verified", proofUrl="https://example.org/article")
        with self.assertRaises(ValueError):
            await self.call("draft_approve", prospectId=pid, version=draft["version"])
        digest = await self.call("digest_get")
        self.assertIn("Prospects who replied: 1. Placements you verified: 1", digest["preview"]["whatChanged"])
        self.assertIn("0 outreach drafts", digest["preview"]["needsDecision"])
        self.assertTrue((await self.call("digest_get", project="bravo"))["muted"])

    async def test_retry_on_later_day_does_not_create_weekly_activity(self):
        with patch.object(work_outreach, "today_utc", return_value=work_outreach.dt.date(2026,11,1)):
            await self.call("prospect_save", **PROSPECT)
        with patch.object(work_outreach, "today_utc", return_value=work_outreach.dt.date(2026,11,18)):
            await self.call("prospect_save", **PROSPECT)
            self.assertTrue((await self.call("digest_get"))["muted"])

    async def test_weekly_archive_once_and_private_handoff(self):
        with patch.object(work_outreach, "today_utc", return_value=work_outreach.dt.date(2026, 11, 18)):
            self.assertEqual((await self.call("digest_get"))["archive"], [])
            await self.call("digest_save", enabled=True, recipients=["Client@example.org", "client@example.org"], muteUnchanged=False)
            first, second = await asyncio.gather(self.call("digest_get"), self.call("digest_get"))
            self.assertEqual(first["archive"], second["archive"])
            self.assertEqual(len(first["archive"]), 1)
            issue = first["currentIssue"]
            self.assertEqual((issue["week"], issue["periodStart"], issue["periodEnd"]), ("2026-11-16","2026-11-09","2026-11-15"))
            self.assertNotIn("client@example.org", json.dumps(issue))
            args = dict(week=issue["week"], version=issue["version"], recipients=["client@example.org", "CLIENT@example.org"])
            for overrides in ({"confirmed": False}, {"confirmed": True, "version": "stale"},
                              {"confirmed": True, "recipients": ["stranger@example.org"]}):
                with self.assertRaises(ValueError):
                    await self.call("digest_handoff", **{**args, **overrides})
            handoff = await self.call("digest_handoff", confirmed=True, **args)
            self.assertFalse(handoff["sent"])
            self.assertEqual(len(handoff["messages"]), 1)
            self.assertIn(issue["preview"]["whatChanged"], handoff["messages"][0]["body"])
            await self.call("prospect_save", project="bravo", **{**PROSPECT, "email": "client@example.org"}, outcome="opted_out")
            with self.assertRaises(ValueError):
                await self.call("digest_handoff", confirmed=True, **args)
        with patch.object(work_outreach, "today_utc", return_value=work_outreach.dt.date(2026, 11, 23)):
            result = await self.call("digest_save", enabled=True, recipients=["client@example.org"], muteUnchanged=True, expected_revision=first["revision"])
            self.assertEqual(result["currentIssue"]["status"], "muted")
            self.assertEqual(len(result["archive"]), 1)
            self.assertEqual((await self.call("digest_get"))["currentIssue"], result["currentIssue"])
            disabled = await self.call("digest_save", enabled=False, recipients=[], muteUnchanged=False, expected_revision=result["revision"])
            self.assertIsNone(disabled["currentIssue"])
            self.assertEqual(len(disabled["archive"]), 1)

    async def test_inbox_only_and_independent_workers_elect_same_issue(self):
        config = dict(enabled=True, muteUnchanged=False, recipients=[])
        state = await self.call("digest_save", **config)
        self.assertEqual(state["currentIssue"]["status"], "delivered")
        issue = state["currentIssue"]
        with self.assertRaises(ValueError):
            await self.call("digest_handoff", week=issue["week"], version=issue["version"], recipients=[], confirmed=True)
        store = await work_outreach.Records.open(self.backend, "digest_get", {})
        base = work_outreach.work_actions.prefix(self.backend, "bravo")
        a, b = await asyncio.gather(
            work_outreach.digest_state(self.backend, store, base, config, {}, [], []),
            work_outreach.digest_state(self.backend, store, base, config, {}, [], [{"status":"open", "due_date":"2026-12-01"}]))
        self.assertEqual(a["currentIssue"], b["currentIssue"])
        self.assertEqual(len(await store.private.keys(base + ".issue.")), 1)

    async def test_independent_writers_reject_conflicting_revisions(self):
        # Bypass the same-process lock to model separate standby instances.
        with patch.object(work_outreach.history, "lock_for", side_effect=lambda _: asyncio.Lock()):
            p = (await self.call("prospect_save", **PROSPECT))["prospect"]
            base = {"id": p["id"], "expected_revision": p["revision"]}
            attempted = await asyncio.gather(
                self.call("prospect_save", **base, outcome="replied"),
                self.call("prospect_save", **base, outcome="opted_out"), return_exceptions=True)
            self.assertEqual(sum(isinstance(x, ValueError) for x in attempted), 1)
            self.assertTrue((await self.call("prospects_list"))["prospects"][0]["suppressed"])
            p = (await self.call("prospect_save", **{**PROSPECT, "email":"second@example.org"}))["prospect"]
            initial = (await self.call("draft_save", prospectId=p["id"], **DRAFT))["draft"]
            args = dict(prospectId=p["id"], expected_revision=initial["revision"])
            drafts = await asyncio.gather(
                self.call("draft_save", **args, **{**DRAFT, "subject":"Alternative"}),
                self.call("draft_approve", **args, version=initial["version"]), return_exceptions=True)
            self.assertEqual(sum(isinstance(x, ValueError) for x in drafts), 1)
            settings = dict(enabled=True, muteUnchanged=True, recipients=[])
            saved = await self.call("digest_save", **settings)
            settings["expected_revision"] = saved["revision"]
            results = await asyncio.gather(
                self.call("digest_save", **{**settings,"enabled":False}),
                self.call("digest_save", **{**settings,"recipients":["edited@example.org"]}), return_exceptions=True)
            self.assertEqual(sum(isinstance(x, ValueError) for x in results), 1)
