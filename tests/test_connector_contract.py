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

    def test_listing_text_lengths_fit_apify_limits(self):
        self.assertLessEqual(len(self.actor["description"]), 300)  # Apify rejects longer descriptions
        self.assertGreaterEqual(len(self.actor["description"]), 150)
        self.assertLessEqual(len(self.actor["title"]), 60)

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
        for heading in ("What is", "Choose Citebase when", "do not use", "How a session works", "Tools",
                        "What one result contains", "Quick start", "Actors Citebase uses", "Pricing and cost example",
                        "Use with an AI agent", "Limits", "Evidence and freshness", "Frequently asked", "Related",
                        "Legal"):
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


ON_PLATFORM = ("apify.com", "mcp.apify.com", "docs.apify.com", "console.apify.com", "api.apify.com")
EXAMPLE_HOSTS = ("example.com", "example.org", "json-schema.org")  # IANA example domains used as sample input, not promotion


def fmt(x):
    s = f"{x:.5f}".rstrip("0")
    whole, _, frac = s.partition(".")
    return f"${whole}.{frac.ljust(2, '0')}"


class ComplianceTests(unittest.TestCase):
    """Apify Store integrity rules: no off-platform links, no third-party Actors, honest pricing wording, brand notices."""

    def setUp(self):
        self.readme = open(os.path.join(ACTOR, "ACTOR_README.md")).read()
        self.prices = load("connector", "prices.json")

    def urls_in(self, text):
        return re.findall(r"https?://[^\s)\"'`\]>\\]+", text)

    def host(self, url):
        return re.sub(r"^https?://", "", url).split("/")[0].split(":")[0].lower()

    def test_no_off_platform_links_in_store_readme(self):
        for url in self.urls_in(self.readme):
            self.assertTrue(self.host(url).endswith(ON_PLATFORM) or self.host(url) in EXAMPLE_HOSTS, url)
        for bad in ("github.com", "marketplace add", "claude plugin", "npm install", "pip install", "paypal", "stripe.com"):
            self.assertNotIn(bad, self.readme.lower())

    def test_no_off_platform_links_in_other_public_metadata(self):
        for name in ("actor.json", "input_schema.json", "dataset_schema.json", "output_schema.json",
                     "key_value_store_schema.json", "web_server_openapi.json"):
            for url in self.urls_in(open(os.path.join(ACTOR, name)).read()):
                self.assertTrue(self.host(url).endswith(ON_PLATFORM) or self.host(url) in EXAMPLE_HOSTS, f"{name}: {url}")

    def test_every_used_actor_is_listed_with_link_and_price(self):
        numbers = {round(float(n), 6) for n in re.findall(r"\$([0-9]+\.[0-9]+)", self.readme)}
        for job, spec in self.prices["jobs"].items():
            slug = spec["actor"].split("/")[1]
            self.assertIn(f"https://apify.com/khadinakbar/{slug})", self.readme, f"{job}: link to {slug}")
            self.assertIn(round(spec["per_unit"], 6), numbers, f"{job}: unit price")
            if spec["per_request"] > 0:
                self.assertIn(round(spec["per_request"], 6), numbers, f"{job}: per-run fee")
        self.assertIn(fmt(self.prices["start_fee_usd"]), self.readme)

    def test_only_own_actors_are_linked(self):
        for slug_owner in re.findall(r"https://apify\.com/([a-z0-9_.-]+)/[a-z0-9_.-]+\)", self.readme):
            self.assertEqual(slug_owner, "khadinakbar")

    def test_connector_never_calls_other_actors(self):
        for name in os.listdir(os.path.join(ROOT, "connector")):
            if name.endswith(".py"):
                code = open(os.path.join(ROOT, "connector", name)).read()
                for banned in ("Actor.call", ".call_actor(", "metamorph", "Actor.start", "ApifyClient"):
                    self.assertNotIn(banned, code, f"{name}: {banned}")

    def test_pricing_wording_names_the_payer(self):
        low = self.readme.lower()
        self.assertIn("platform usage", low)
        self.assertRegex(low, r"paid by the (apify )?account that (starts|runs)")
        self.assertIn("no start fee", low)
        self.assertNotRegex(low, r"unlimited|free forever|margin|commission")

    def test_brand_notices_match_store_compliance_record(self):
        rec = load(".actor", "STORE_COMPLIANCE.json")
        self.assertEqual(rec["schemaVersion"], 1)
        self.assertFalse(rec["publicContentReviewed"], "a human must confirm the review; never pre-marked")
        self.assertGreaterEqual(len(rec["brands"]), 6)
        for brand in rec["brands"]:
            self.assertIn(brand["disclosure"], self.readme, brand["name"])
            self.assertIn("not affiliated with", brand["disclosure"])

    def test_no_secrets_in_any_input_name(self):
        schema = load(".actor", "input_schema.json")
        for key in schema["properties"]:
            self.assertNotRegex(key, r"(?i)token|password|secret|key|cookie")

    def test_run_outcomes_are_honest(self):
        text = open(os.path.join(ROOT, "connector", "main.py")).read()
        self.assertIn("Actor.fail", text)  # bad input ends FAILED, never a fake success
        self.assertNotIn("Actor.exit(", text)


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
