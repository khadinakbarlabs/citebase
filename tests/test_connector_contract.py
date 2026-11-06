"""MCP pre-publish readiness checks (Apify Actor Builder checklist): descriptions, schemas, files, README.

Needs the `mcp` package for the served-schema checks; the file checks always run."""
import importlib.util
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTOR = os.path.join(ROOT, ".actor")
sys.path.insert(0, os.path.join(ROOT, "connector"))
HAVE_MCP = importlib.util.find_spec("mcp") is not None
TOOLS = {"get_playbook", "audit_site", "quote_cost", "measure_recommendation_share", "next_steps",
         "check_outreach_draft"}


def load(*parts):
    with open(os.path.join(ROOT, *parts)) as fh:
        return json.load(fh)


class ActorFilesTests(unittest.TestCase):
    def setUp(self):
        self.actor = load(".actor", "actor.json")

    def test_actor_json_wires_every_schema(self):
        for key in ("input", "output", "dockerfile", "readme", "changelog", "webServerSchema"):
            path = os.path.join(ACTOR, self.actor[key])
            self.assertTrue(os.path.isfile(path), f"{key} -> {self.actor[key]}")
        self.assertTrue(os.path.isfile(os.path.join(ACTOR, self.actor["storages"]["dataset"])))
        self.assertTrue(os.path.isfile(os.path.join(ACTOR, self.actor["storages"]["keyValueStore"])))

    def test_actor_json_follows_platform_rules(self):
        self.assertRegex(self.actor["version"], r"^\d+\.\d+$")  # MAJOR.MINOR, not semver
        self.assertNotIn("dataset", self.actor.get("output", ""))  # output is a file path at top level
        self.assertTrue(self.actor["usesStandbyMode"])
        self.assertEqual(self.actor["webServerMcpPath"], "/mcp")
        self.assertIn("defaultMemoryMbytes", self.actor)
        self.assertNotIn("isPublic", self.actor)

    def test_output_schema_points_at_dataset_and_output_record(self):
        out = load(".actor", "output_schema.json")
        self.assertEqual(out["actorOutputSchemaVersion"], 1)
        templates = {p["template"] for p in out["properties"].values()}
        self.assertIn("{{links.apiDefaultDatasetUrl}}/items", templates)
        for prop in out["properties"].values():
            self.assertGreater(len(prop["description"]), 20)

    def test_dataset_schema_describes_every_field_with_example(self):
        ds = load(".actor", "dataset_schema.json")
        props = ds["fields"]["properties"]
        self.assertEqual(set(props), {"tool", "ok", "result", "error"})
        for name, spec in props.items():
            for key in ("title", "description", "type"):
                self.assertIn(key, spec, f"{name}.{key}")
        self.assertIn("overview", ds["views"])
        self.assertEqual(set(ds["views"]["overview"]["transformation"]["fields"]), set(props))

    def test_key_value_store_schema_documents_the_output_record(self):
        kv = load(".actor", "key_value_store_schema.json")
        self.assertEqual(kv["actorKeyValueStoreSchemaVersion"], 1)
        self.assertEqual(kv["collections"]["output"]["key"], "OUTPUT")

    def test_input_schema_enum_and_required(self):
        schema = load(".actor", "input_schema.json")
        self.assertEqual(schema["required"], ["tool"])
        self.assertEqual(set(schema["properties"]["tool"]["enum"]), TOOLS)

    def test_openapi_lists_run_with_examples(self):
        spec = load(".actor", "web_server_openapi.json")
        self.assertTrue(spec["openapi"].startswith("3."))
        body = spec["paths"]["/run"]["post"]["requestBody"]["content"]["application/json"]
        self.assertIn("example", json.dumps(body) + json.dumps(spec["paths"]["/run"]["post"]))

    def test_changelog_has_current_version(self):
        text = open(os.path.join(ACTOR, self.actor["changelog"])).read()
        self.assertIn(f"## {self.actor['version']}", text)


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.text = open(os.path.join(ACTOR, load(".actor", "actor.json")["readme"])).read()

    def test_store_readme_shape(self):
        self.assertFalse(re.search(r"(?m)^# ", self.text), "no H1: the Store shows the title")
        for heading in ("What is", "When to use", "Tools", "Example", "Price", "Limits", "Legal"):
            self.assertRegex(self.text, rf"(?mi)^## .*{heading}", heading)

    def test_first_quarter_covers_what_when_output_price(self):
        head = self.text[: max(1200, len(self.text) // 4)].lower()
        for word in ("what", "use", "returns", "free"):
            self.assertIn(word, head)

    def test_every_tool_is_documented(self):
        for name in TOOLS:
            self.assertIn(f"`{name}`", self.text)

    def test_no_secrets_or_hype(self):
        for bad in ("#1", "best in the world", "api key:", "token:"):
            self.assertNotIn(bad, self.text.lower())


@unittest.skipUnless(HAVE_MCP, "mcp is not installed")
class ServedSchemaTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from server import build_server
        self.tools = {t.name: t for t in await build_server().list_tools()}

    def dump(self, tool):
        return tool.model_dump(by_alias=True, exclude_none=True)

    async def test_exactly_the_six_tools(self):
        self.assertEqual(set(self.tools), TOOLS)
        self.assertLessEqual(len(self.tools), 15)

    async def test_descriptions_follow_the_five_part_formula(self):
        for name, tool in self.tools.items():
            d = tool.description
            self.assertTrue(250 <= len(d) <= 520, f"{name}: {len(d)} chars")
            self.assertRegex(d, r"\bUse\b", name)  # when to use
            self.assertRegex(d, r"\bNot\b", name)  # negative scope
            self.assertRegex(d, r"\bReturns\b", name)  # return shape
            self.assertTrue(d.rstrip().endswith(("Free.", "Free; takes up to a minute.")), f"{name}: price signal")
            self.assertNotRegex(d, r"(?i)this (tool|actor) allows|best in|#1", name)

    async def test_every_input_property_is_described_with_an_example_or_bound(self):
        for name, tool in self.tools.items():
            props = self.dump(tool)["inputSchema"].get("properties", {})
            for key, spec in props.items():
                text = spec.get("description", "")
                self.assertGreaterEqual(len(text), 40, f"{name}.{key} needs a real description")
                self.assertTrue(re.search(r"(?i)for example|e\.g\.|defaults? to|between", text), f"{name}.{key}: no example/default")
                self.assertLess(len(text), 520, f"{name}.{key} too long")

    async def test_required_inputs_are_few(self):
        for name, tool in self.tools.items():
            required = self.dump(tool)["inputSchema"].get("required", [])
            self.assertLessEqual(len(required), 3, name)

    async def test_every_tool_has_a_typed_output_schema(self):
        for name, tool in self.tools.items():
            out = self.dump(tool).get("outputSchema")
            self.assertIsNotNone(out, f"{name} has no outputSchema")
            self.assertGreaterEqual(len(out.get("properties", {})), 2, name)
            for key, spec in out["properties"].items():
                self.assertTrue(spec.get("description"), f"{name}.{key} output field has no description")

    async def test_job_names_are_a_closed_list(self):
        schema = json.dumps(self.dump(self.tools["quote_cost"])["inputSchema"])
        for job in ("serp_page", "ai_brand_check", "keyword_ideas"):
            self.assertIn(job, schema)

    async def test_annotations_and_titles(self):
        for name, tool in self.tools.items():
            d = self.dump(tool)
            self.assertTrue(d["annotations"]["readOnlyHint"], name)
            self.assertIn("openWorldHint", d["annotations"], name)
            self.assertTrue(d.get("title"), name)

    async def test_no_tool_accepts_secrets(self):
        for name, tool in self.tools.items():
            props = " ".join(self.dump(tool)["inputSchema"].get("properties", {}))
            self.assertNotRegex(props, r"(?i)token|password|secret|api_?key", name)


if __name__ == "__main__":
    unittest.main()
