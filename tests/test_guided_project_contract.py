import json
import pathlib
import sys
import unittest
from typing import get_args

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "connector"))


class GuidedProjectContract(unittest.TestCase):
    def test_quotes_apply_published_search_pricing_on_the_announced_date(self):
        from datetime import date
        import tools
        job = [{"job":"serp_page","units":100,"requests":1}]
        before = tools.quote_cost(job, today=date(2026,11,28))
        after = tools.quote_cost(job, today=date(2026,11,29))
        self.assertGreater(before["total_usd"], after["total_usd"])
        self.assertAlmostEqual(after["total_usd"], 0.3001, places=3)

    def test_http_mcp_and_dashboard_share_the_guided_project_operations(self):
        import project_api
        import project_work

        operations = {"onboarding_get", "onboarding_suggest", "onboarding_save", "research_get",
                      "research_plan", "research_import", "citation_contact", "citation_prospect_save",
                      "outreach_prepare", "outreach_claim"}
        self.assertTrue(operations <= set(get_args(project_work.Operation)))
        self.assertTrue(operations <= set.union(*project_work.MODULES.values()))
        api = json.loads((ROOT / ".actor/web_server_openapi.json").read_text())["paths"]
        actual_routes = {op: (method, "/v1/projects/{project}/" + path) for method, path, op, _ in project_api.ROUTES}
        for operation in operations:
            with self.subTest(operation=operation):
                method, path = actual_routes[operation]
                self.assertIn(method.lower(), api[path])
                self.assertIn("security", api[path][method.lower()])
        self.assertTrue({"onboarding_get", "research_get", "research_plan"} <= project_work.READ_ONLY)
        self.assertTrue({"onboarding_save", "research_import", "outreach_claim"}.isdisjoint(project_work.READ_ONLY))

    def test_first_agent_playbook_can_resume_the_same_website_and_terms(self):
        import tools

        playbook = tools.get_playbook("start")["text"]
        for name in ("onboarding_get", "onboarding_suggest", "onboarding_save", "research_get"):
            self.assertIn(name, playbook)
