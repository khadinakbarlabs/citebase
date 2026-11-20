import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "connector"))
import work_citation_outreach as outreach


class CitationTests(unittest.TestCase):
    def test_contact_scope_and_robots(self):
        url = 'https://example.org/story'
        pages = {'/robots.txt': 'User-agent: *\nDisallow: /private',
                 '/story': '<a rel="author" href="/bio">Jane Doe</a><a rel="author" href="/private">Private</a><a href="mailto:editor@example.org">Editor</a><a href="mailto:press@quoted-company.org">Quoted company</a><a href="mailto:random@example.org">Random</a>',
                 '/bio': '<a href="mailto:jane@example.org">Email Jane Doe</a>'}
        def fetch(link):
            path = link.removeprefix('https://example.org')
            return {'status': 200, 'body': pages[path].encode(), 'headers': {}}
        with patch.object(outreach.tools.sa, 'fetch', fetch):
            got = outreach.inspect_article(url)
        assert [(c['email'], c['kind']) for c in got['contacts']] == [
            ('editor@example.org', 'editorial'), ('jane@example.org', 'author')]


    def test_wrong_question_cannot_borrow_citation(self):
        project = {'panel': [{'prompt_id': 'q', 'prompt': 'Which?'}], 'runs': [
            {'prompt_id': 'other', 'cited_urls': ['https://example.org/story']}]}
        with self.assertRaises(ValueError):
            outreach.verify_citation(project, 'Which?', 'https://example.org/story')


class ClaimTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import storage
        from test_work_outreach import DRAFT, PROSPECT
        self.backend = storage.MemoryBackend()
        storage.set_backend(self.backend)
        self.addCleanup(storage.set_backend, None)
        await self.backend.set(storage.key('alpha', 'meta'), {'project': 'alpha'})
        async def work(op, data):
            return await outreach.outreach.execute('alpha', op, data)
        row = (await work('prospect_save', PROSPECT))['prospect']
        draft = (await work('draft_save', {'prospectId': row['id'], **DRAFT}))['draft']
        await work('draft_approve', {'prospectId': row['id'], 'version': draft['version'],
                                    'expected_revision': draft['revision']})
        self.args = {'prospectId': row['id'], 'confirm': True,
                     **{k: draft[k] for k in ('version', 'to', 'subject', 'body')}}
        key = outreach.outreach.prospect_key(outreach.work_actions.prefix(self.backend, 'alpha'), row['id'])
        self.private = await self.backend.private_store()
        self.evidence_key = key + '.citation'

    async def test_atomic_claim_and_provider_receipt(self):
        async def claim(**changes):
            return await outreach.execute('alpha', 'outreach_claim', {**self.args, **changes})
        with self.assertRaises(ValueError):
            await claim()
        await self.private.set(self.evidence_key, {'email': self.args['to']})
        for changes in ({'confirm': False}, {'to': 'someone@example.org'}, {'body': 'edited'}):
            with self.assertRaises(ValueError):
                await claim(**changes)
        results = await asyncio.gather(claim(), claim(), return_exceptions=True)
        granted, = [r for r in results if isinstance(r, dict)]
        self.assertEqual(sum(isinstance(r, ValueError) for r in results), 1)
        finish = {**self.args, 'claimId': granted['claimId'], 'messageId': 'provider123'}
        for _ in range(2):
            result = await outreach.execute('alpha', 'outreach_finish', finish)
            self.assertEqual(result['status'], 'provider_accepted')
        with self.assertRaises(ValueError):
            await claim()

    async def test_reconcile_only_matching_scoped_receipt(self):
        from storage import key
        query = {k: self.args[k] for k in ('prospectId', 'version')}

        async def read():
            return await outreach.execute('alpha', 'outreach_status', query)

        self.assertEqual(await read(), {'status': 'unclaimed'})
        await self.private.set(self.evidence_key, {'email': self.args['to']})
        claim = await outreach.execute('alpha', 'outreach_claim', self.args)
        self.assertEqual(await read(), {'status': 'claimed'})
        receipt = {**query, 'provider': 'gmail', 'claimId': claim['claimId'],
                   'messageId': 'gmail1', 'status': 'provider_accepted'}
        await self.backend.set(key('other', 'gmail-receipt', claim['claimId']), receipt)
        record = key('alpha', 'gmail-receipt', claim['claimId'])
        for field in ('claimId', 'prospectId', 'version', 'provider', 'status'):
            await self.backend.set(record, {**receipt, field: 'different'})
            self.assertEqual(await read(), {'status': 'claimed'})
        await self.backend.set(record, receipt)
        self.assertEqual(await read(), {'status': 'provider_accepted', 'messageId': 'gmail1'})
