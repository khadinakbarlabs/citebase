"""One release number everywhere: plugin manifests, MCP server, web description and Apify Actor.

The Actor uses MAJOR.MINOR (Apify rejects a third number); everything else uses MAJOR.MINOR.PATCH. They must agree on
MAJOR.MINOR and the full ones must agree exactly. The crawler's User-Agent is read from plugin.json at import time.
"""
import ast
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import site_audit  # noqa: E402


def load(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return json.load(fh)


def server_version() -> str:
    with open(os.path.join(ROOT, "connector", "server.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "VERSION" for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError("connector/server.py has no VERSION constant")


class VersionTests(unittest.TestCase):
    def versions(self) -> dict[str, str]:
        return {
            ".claude-plugin/plugin.json": load(".claude-plugin", "plugin.json")["version"],
            ".claude-plugin/marketplace.json": load(".claude-plugin", "marketplace.json")["metadata"]["version"],
            "connector/server.py VERSION": server_version(),
            ".actor/web_server_openapi.json": load(".actor", "web_server_openapi.json")["info"]["version"],
        }

    def test_full_versions_are_semver_and_identical(self):
        found = self.versions()
        for where, value in found.items():
            self.assertRegex(value, r"^\d+\.\d+\.\d+$", where)
        self.assertEqual(len(set(found.values())), 1, found)

    def test_actor_version_is_the_major_minor_of_the_release(self):
        release = next(iter(self.versions().values()))
        actor = load(".actor", "actor.json")["version"]
        self.assertRegex(actor, r"^\d+\.\d+$")
        self.assertEqual(actor, ".".join(release.split(".")[:2]))

    def test_marketplace_plugin_entry_has_no_conflicting_version(self):
        for entry in load(".claude-plugin", "marketplace.json")["plugins"]:
            if "version" in entry:
                self.assertEqual(entry["version"], load(".claude-plugin", "plugin.json")["version"])

    def test_crawler_user_agent_carries_the_release_version(self):
        release = load(".claude-plugin", "plugin.json")["version"]
        self.assertIn(f"/{release}", site_audit.UA)
        self.assertNotRegex(site_audit.UA, r"/0\.3(?!\d)")

    def test_changelog_mentions_the_actor_version(self):
        actor = load(".actor", "actor.json")["version"]
        with open(os.path.join(ROOT, ".actor", "CHANGELOG.md"), encoding="utf-8") as fh:
            headings = re.findall(r"^## (\S+)", fh.read(), re.M)
        self.assertIn(actor, headings)


if __name__ == "__main__":
    unittest.main()
