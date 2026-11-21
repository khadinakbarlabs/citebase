import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'connector'))
import onboarding_ai as ai


class OnboardingRelevance(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.evidence = {'website': 'https://payroll.example', 'brand': 'Fair Payroll', 'language': 'en',
                         'pages': [{'url': 'https://payroll.example', 'title': 'Payroll for small businesses',
                                    'description': 'Run payroll and manage small business taxes.'}],
                         'terms': [{'term': 'small business payroll', 'source': 'website'},
                                   {'term': 'ocean cruises', 'source': 'website'}], 'competitors': []}

    async def test_only_topically_supported_defaults_are_checked_and_recommended(self):
        with patch.object(ai, '_similarities', return_value=[0.80, 0.07]):
            result = await ai.review('demo', self.evidence, {})
        good, other = result['terms']
        self.assertTrue(good['ai_checked'] and good['recommended'])
        self.assertTrue(other['ai_checked'])
        self.assertFalse(other['recommended'])
        self.assertNotIn('search_volume', good)

    async def test_unavailable_or_unsupported_models_keep_evidence_and_disclose_coverage(self):
        for language, scores in [('English', None), ('ja', [0.8, 0.7])]:
            with patch.object(ai, '_similarities', return_value=scores):
                result = await ai.review('demo', {**self.evidence, 'language': language}, {})
            self.assertFalse(any(t['ai_checked'] for t in result['terms']))
            self.assertEqual(result['terms'][0]['source'], 'website')

    async def test_modest_model_score_can_back_an_exact_first_party_phrase_but_not_an_assistant_guess(self):
        evidence = {**self.evidence, 'pages':[{'title':'Fair Payroll','description':'Small business payroll for growing teams.'}]}
        with patch.object(ai, '_similarities', return_value=[0.32, 0.31]):
            rows = (await ai.review('demo', evidence, {}))['terms']
        self.assertTrue(rows[0]['recommended'])
        self.assertFalse(rows[1]['recommended'])

    async def test_assistant_candidates_require_attribution_and_cannot_assign_metrics(self):
        payload = {'competitors': [{'name':'Pay Rival','domain':'rival.example','url':'https://rival.example/payroll'},
                                   {'name':'Fair Payroll','url':'https://payroll.example/'},
                                   {'name':'Unsafe','url':'http://127.0.0.1/info'}],
                   'terms':[{'term':'payroll tax software','url':'https://rival.example/payroll',
                             'search_volume':50000,'recommended':True,'ai_checked':True}]}
        with patch.object(ai, '_similarities', return_value=None):
            result = await ai.review('demo', self.evidence, payload)
        self.assertEqual([r['name'] for r in result['competitors']], ['Pay Rival'])
        self.assertFalse(result['competitors'][0]['selected'])
        term = next(t for t in result['terms'] if t['term'] == 'payroll tax software')
        self.assertFalse(term['ai_checked'])
        self.assertNotIn('search_volume', term)
