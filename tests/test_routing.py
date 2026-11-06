"""Routing eval: each user phrase must point to exactly one skill description (no trigger collisions)."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (what the user might say, distinctive phrase that must live in exactly one description, expected skill)
CASES = [
    ("Where do we even start with SEO?", "where do we start", "start"),
    ("Why doesn't ChatGPT recommend us?", "why doesn't chatgpt recommend us", "ai-search-visibility"),
    ("Do we show up in AI Overviews?", "ai overviews", "ai-search-visibility"),
    ("Prove the ROI of our GEO work", "prove the roi of geo", "citation-loop"),
    ("Re-measure our AI citations next month", "re-measure", "citation-loop"),
    ("Who are our SEO competitors and what is the keyword gap?", "keyword gap", "competitor-research"),
    ("What do people search for in my niche?", "find what people search for", "keyword-research"),
    ("Find me guest posts for the blog", "guest posts", "link-building"),
    ("Do some link prospecting for our new tool", "link prospecting", "link-building"),
    ("Write a press release for our launch", "press release", "press-release"),
    ("Plan some digital PR around our data", "digital pr", "press-release"),
    ("Find influencers to feature our product", "find influencers", "creator-outreach"),
    ("Send these pitches to the list", "send these pitches", "outreach"),
    ("Handle the follow-ups for last week's emails", "follow-ups", "outreach"),
    ("Give me an on-page checklist for the homepage", "on-page checklist", "seo-checklists"),
    ("Our traffic dropped, audit the site", "traffic drop", "seo-audit"),
]


def descriptions():
    base = os.path.join(ROOT, "skills")
    out = {}
    for name in sorted(os.listdir(base)):
        with open(os.path.join(base, name, "SKILL.md")) as fh:
            match = re.search(r"(?m)^description: (.+)$", fh.read())
        out[name] = match.group(1).lower() if match else ""
    return out


class RoutingTests(unittest.TestCase):
    def test_each_phrase_matches_exactly_one_skill(self):
        desc = descriptions()
        for said, phrase, expected in CASES:
            hits = [name for name, text in desc.items() if phrase in text]
            self.assertEqual(hits, [expected], f"'{said}' -> phrase '{phrase}' matched {hits}")

    def test_every_skill_is_covered_by_a_case(self):
        covered = {expected for _, _, expected in CASES}
        self.assertEqual(covered, set(descriptions()))

    def test_descriptions_are_not_duplicated(self):
        texts = list(descriptions().values())
        self.assertEqual(len(texts), len(set(texts)))


if __name__ == "__main__":
    unittest.main()
