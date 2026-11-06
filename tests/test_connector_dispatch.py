"""One-shot mode: tools.dispatch (what a normal Apify run calls) and the Actor input schema."""
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
import tools  # noqa: E402


class DispatchTests(unittest.TestCase):
    def test_every_tool_runs_by_name(self):
        self.assertIn("playbooks", tools.dispatch("get_playbook", {}))
        self.assertIn("text", tools.dispatch("get_playbook", {"name": "start"}))
        self.assertEqual(tools.dispatch("quote_cost", {"items": [{"job": "serp_page", "units": 15}]})["suggested_cap_usd"], 0.04)
        self.assertEqual(tools.dispatch("next_steps", {})["steps"][-1]["step"], "Check again in 30 days")
        out = tools.dispatch("check_outreach_draft", {"to": "a@b.com", "subject": "Hi there", "body": "short"})
        self.assertIn("ready", out)

    def test_unknown_tool_and_arguments_get_plain_errors(self):
        with self.assertRaisesRegex(ValueError, "Unknown tool"):
            tools.dispatch("nope", {})
        with self.assertRaisesRegex(ValueError, "does not take"):
            tools.dispatch("quote_cost", {"nonsense": 1})

    def test_wrong_shapes_become_value_errors(self):
        with self.assertRaises(ValueError):
            tools.dispatch("quote_cost", {"items": "not a list"})
        with self.assertRaises(ValueError):
            tools.dispatch("measure_recommendation_share", {"panel": [], "runs": []})

    def test_missing_arguments_default_to_empty(self):
        self.assertIn("playbooks", tools.dispatch("get_playbook", None))

    def test_results_are_json_serialisable(self):
        json.dumps(tools.dispatch("get_playbook", {"name": "measurement"}))

    def test_dispatch_covers_exactly_the_tools_the_server_exposes(self):
        text = open(os.path.join(ROOT, "connector", "server.py")).read()
        for name in tools.DISPATCH:
            self.assertIn(f'name="{name}"', text)


class InputSchemaTests(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(ROOT, ".actor", "input_schema.json")) as fh:
            self.schema = json.load(fh)

    def test_enum_matches_dispatch(self):
        self.assertEqual(set(self.schema["properties"]["tool"]["enum"]), set(tools.DISPATCH))

    def test_required_and_defaults(self):
        self.assertEqual(self.schema["required"], ["tool"])
        self.assertEqual(self.schema["properties"]["arguments"]["default"], {})

    def test_every_tool_is_described_in_the_arguments_help(self):
        help_text = self.schema["properties"]["arguments"]["description"]
        for name in tools.DISPATCH:
            self.assertIn(name, help_text)


if __name__ == "__main__":
    unittest.main()
