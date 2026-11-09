"""Structural checks on manifests, hooks, MCP config, skills and agents."""
import json
import os
import re
import sys
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
        # Plugin MCP server must stay named "apify" so approval_gate.OWN_APIFY_PREFIX matches.
        url = load(".mcp.json")["mcpServers"]["apify"]["url"]
        tools = parse_qs(urlparse(url).query)["tools"][0].split(",")
        self.assertEqual(sorted(tools), sorted(
            ["fetch-actor-details", "call-actor", "get-actor-run", "get-dataset-items",
             "get-key-value-store-record", "abort-actor-run"]))

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


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def skill_names():
    return sorted(os.listdir(os.path.join(ROOT, "skills")))


class BeginnerFrontDoorTests(unittest.TestCase):
    """The start playbook is one short front door: a website address gets a result before any question."""

    def setUp(self):
        self.text = read("skills", "start", "SKILL.md")
        marker = "after the first result"
        self.assertIn(marker, self.text.lower(), "start needs an 'after the first result' section")
        cut = self.text.lower().index(marker)
        self.front, self.later = self.text[:cut], self.text[cut:]

    def test_every_skill_points_at_the_plain_language_guide(self):
        for name in skill_names():
            self.assertIn("references/plain-language.md", read("skills", name, "SKILL.md"), name)

    def test_there_is_one_first_menu(self):
        self.assertEqual(self.text.count("Beginner front door"), 1)
        self.assertNotRegex(self.text, r"(?mi)^## First run")
        self.assertEqual(len(re.findall(r"(?m)^[123]\. \*\*", self.front)), 3, "exactly three easy starts")

    def test_a_web_address_gets_the_site_check_before_any_question(self):
        low = self.front.lower()
        self.assertIn("run the site check now", low)
        self.assertIn("ask nothing first", low)

    def test_interview_tools_and_priorities_wait_until_after_the_first_result(self):
        for later_only in ("context.md", "tools-and-apis.md", "impact", "30/60/90"):
            self.assertNotIn(later_only, self.front, f"{later_only} belongs after the first result")
            self.assertIn(later_only, self.later, later_only)

    def test_workspace_folder_is_created_at_the_first_paid_step(self):
        self.assertNotIn("Create the folder first", self.text)
        self.assertRegex(self.text.lower(), r"first paid step")
        self.assertNotIn("seo-workspace", self.front, "the free check needs no folder")

    def test_front_door_is_short_and_plain(self):
        door = self.front[self.front.index("## Beginner front door"):]
        self.assertLess(len(door.split()), 260)
        for jargon in ("frozen prompt panel", "Recommendation Share", "SERP"):
            self.assertNotIn(jargon, self.front)
        self.assertNotRegex(self.text, r"(?i)\bfree\b", "say 'no Citebase fee': this text is served to web users")

    def test_no_hand_off_to_a_web_developer_in_the_written_guidance(self):
        for rel in ("references", "skills", "agents"):
            for base, _dirs, names in os.walk(os.path.join(ROOT, rel)):
                for name in names:
                    if name.endswith(".md"):
                        self.assertNotIn("web developer", read(os.path.relpath(os.path.join(base, name), ROOT)),
                                         name)

    def test_no_hand_off_to_a_developer_in_the_text_the_connector_serves(self):
        for rel in (("connector", "tools.py"), ("connector", "models.py")):
            self.assertNotRegex(read(*rel), r"(?i)\b(?:web )?developer\b", rel[-1])


class CrawlerGuidanceTests(unittest.TestCase):
    """Answer bots must be allowed; training bots are the owner's choice. Same lists as scripts/site_audit.py."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        import site_audit
        cls.answer, cls.training = list(site_audit.ANSWER_BOTS), list(site_audit.TRAINING_BOTS)

    def line(self, rel, start):
        for line in read(*rel).splitlines():
            if line.startswith(start):
                return line
        self.fail(f"{rel[-1]}: no line starting {start!r}")

    def check(self, line):
        head, _, tail = line.partition("Training-only")
        self.assertTrue(tail, "the line must name the training-only bots separately")
        for bot in self.answer:
            self.assertIn(bot, head, f"{bot} belongs with the answer bots")
        for bot in self.training:
            self.assertIn(bot, tail, f"{bot} belongs with the training-only bots")
            self.assertNotIn(bot, head, f"{bot} must not be in the answer-bot list")
        self.assertRegex(tail.lower(), r"(owner|your) choice")
        named = set(re.findall(r"\b(?:[A-Z][\w-]*Bot|ChatGPT-User|Claude-User|Perplexity-User)\b", head))
        self.assertLessEqual(named, set(self.answer), "the guidance names an answer bot the crawler does not check")

    def test_technical_checklist_splits_answer_bots_from_training_bots(self):
        line = self.line(("references", "checklist-technical.md"), "- [auto] **Answer bots")
        self.check(line)
        self.assertRegex(read("references", "checklist-technical.md").lower(), r"cdn")

    def test_ai_search_checklist_splits_answer_bots_from_training_bots(self):
        self.check(self.line(("references", "checklist-ai-search.md"), "- Answer bots"))


class AdviceHonestyTests(unittest.TestCase):
    def test_overlap_claim_is_hedged_and_the_88_percent_figure_is_gone(self):
        text = read("references", "checklist-ai-search.md")
        self.assertNotIn("88%", text)
        self.assertNotRegex(text, r"76% of AI Overview citations come from")
        self.assertRegex(text.lower(), r"disput|varies|very different levels")

    def test_ai_search_checklist_names_the_google_eligibility_gate(self):
        low = read("references", "checklist-ai-search.md").lower()
        self.assertIn("indexable and snippet-eligible", low)
        self.assertIn("nosnippet", low)

    def test_local_links_item_has_no_dofollow_or_price_quotes_and_names_the_paid_link_rule(self):
        item = next(l for l in read("references", "checklist-technical.md").splitlines()
                    if l.startswith("7. **Local links"))
        self.assertNotRegex(item.lower(), r"dofollow|\$\d")
        self.assertIn("sponsored", item)
        self.assertIn("nofollow", item)

    def test_drop_diagnosis_states_dates_and_googles_words_and_flags_the_rest(self):
        text = read("references", "checklist-technical.md")
        section = text.split("## Diagnosing drops")[1].split("\n---", 1)[0]
        low = section.lower()
        for claim in ("near me", "preferred sources", "ai-written"):
            self.assertIn(claim, low)
        self.assertIn("unconfirmed", low)
        self.assertIn("did not name", low)
        # none of the unconfirmed claims may sit in a sentence that is not marked unconfirmed
        first_part = low.split("unconfirmed")[0]
        for claim in ("near me", "preferred sources", "ai-written"):
            self.assertNotIn(claim, first_part, f"{claim} must only appear in the unconfirmed line")

    def test_freebies_are_never_paired_with_a_link_ask(self):
        play = read("references", "outreach-playbook.md")
        self.assertRegex(play, r"(?i)free[^\n]{0,80}same message[^\n]{0,80}link|same message[^\n]{0,120}free")
        tpl2 = play.split("**2. ")[1].split("**3. ")[0].lower()
        tpl7 = play.split("**7. ")[1].split("**8. ")[0].lower()
        self.assertNotRegex(tpl2, r"free (account|trial|product|plan)|for free")
        self.assertNotRegex(tpl7, r"https?://|\[company url\]|linking to|link back")


if __name__ == "__main__":
    unittest.main()
