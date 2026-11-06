"""Structural checks on manifests, hooks, MCP config, skills and agents."""
import json
import os
import re
import unittest
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRIVATE_ACTORS = ("ai-visibility-checker", "ai-rank-tracker", "google-business-profile-audit",
                  "local-citation-audit")
TEXT_SUFFIXES = (".md", ".json", ".py", ".yml", ".txt")


def load(*parts):
    with open(os.path.join(ROOT, *parts)) as fh:
        return json.load(fh)


def repo_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            if name.endswith(TEXT_SUFFIXES):
                yield os.path.join(base, name)


class ManifestTests(unittest.TestCase):
    def test_versions_match(self):
        plugin, market = load(".claude-plugin", "plugin.json"), load(".claude-plugin", "marketplace.json")
        self.assertEqual(plugin["version"], market["metadata"]["version"])
        self.assertEqual(plugin["name"], "citebase")

    def test_user_config_options(self):
        cfg = load(".claude-plugin", "plugin.json")["userConfig"]
        self.assertEqual(set(cfg), {"max_run_usd", "daily_send_cap", "daily_spend_usd", "allowed_actors"})

    def test_mcp_exposes_only_generic_apify_tools(self):
        url = load(".mcp.json")["mcpServers"]["apify"]["url"]
        tools = parse_qs(urlparse(url).query)["tools"][0].split(",")
        self.assertEqual(sorted(tools), sorted(
            ["fetch-actor-details", "call-actor", "get-actor-run", "get-dataset-items", "abort-actor-run"]))

    def test_hook_matchers_are_anchored_and_precise(self):
        hooks = load("hooks", "hooks.json")["hooks"]
        pre = re.compile(hooks["PreToolUse"][0]["matcher"])
        post = re.compile(hooks["PostToolUse"][0]["matcher"])
        for name in ("mcp__plugin_citebase_apify__call-actor", "mcp__g__send_email", "mcp__g__send_draft",
                     "mcp__r__activate_campaign", "mcp__v__purchase_order", "mcp__a__khadinakbar--serp"):
            self.assertTrue(pre.search(name), name)
        # The matcher is deliberately broad (spelling variants); approval_gate.classify() does the precise work.
        for name in ("Bash", "Read", "mcp__x__list_pages", "mcp__x__get_page"):
            self.assertFalse(pre.search(name), name)
        self.assertTrue(post.search("mcp__x__call-actor"))
        self.assertFalse(post.search("Bash"))

    def test_no_bash_matcher(self):
        text = json.dumps(load("hooks", "hooks.json"))
        self.assertNotIn("Bash", text)
        self.assertNotIn("--confirm", text)


class HygieneTests(unittest.TestCase):
    def test_no_private_actor_references(self):
        for path in repo_files():
            if path.endswith("test_manifests.py"):
                continue
            with open(path) as fh:
                text = fh.read()
            for actor in PRIVATE_ACTORS:
                self.assertFalse(actor in text, f"{actor} referenced in {os.path.relpath(path, ROOT)}")

    def test_no_previous_product_names(self):
        for path in repo_files():
            if path.endswith("test_manifests.py"):
                continue
            with open(path) as fh:
                text = fh.read().lower()
            for old in ("vibecited", "vibegrowth", "vibeseo"):
                self.assertFalse(old in text, f"{old} still in {os.path.relpath(path, ROOT)}")

    def test_every_skill_has_frontmatter_and_description(self):
        base = os.path.join(ROOT, "skills")
        for name in os.listdir(base):
            with open(os.path.join(base, name, "SKILL.md")) as fh:
                head = fh.read(2000)
            self.assertTrue(head.startswith("---"), name)
            self.assertRegex(head, r"(?m)^name: " + re.escape(name) + r"$")
            self.assertRegex(head, r"(?m)^description: .{40,}")

    def test_agents_declare_restricted_tools(self):
        base = os.path.join(ROOT, "agents")
        for fname in os.listdir(base):
            with open(os.path.join(base, fname)) as fh:
                head = fh.read(1500)
            match = re.search(r"(?m)^tools: (.+)$", head)
            self.assertIsNotNone(match, f"{fname} has no tools allowlist")
            self.assertNotIn("*", match.group(1), fname)
            if fname == "outreach-writer.md":
                for forbidden in ("send", "Bash", "Write"):
                    self.assertNotIn(forbidden, match.group(1))

    def test_referenced_files_exist(self):
        pattern = re.compile(r"(?:\.\./\.\./|\$\{CLAUDE_PLUGIN_ROOT\}/)((?:references|scripts|templates)/[\w./-]+)")
        for path in repo_files():
            with open(path) as fh:
                for ref in pattern.findall(fh.read()):
                    self.assertTrue(os.path.exists(os.path.join(ROOT, ref.rstrip(".,)`'\""))),
                                    f"{os.path.relpath(path, ROOT)} -> {ref}")


if __name__ == "__main__":
    unittest.main()
