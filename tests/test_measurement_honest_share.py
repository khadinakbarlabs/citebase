"""Top move 2: an honest headline Recommendation Share.

Headline = buying questions only (awareness + consideration). Questions that already name the brand are a
separate "reputation check". The importer only auto-calls a mention a recommendation on clear evidence.
Old rounds (no metric_version) are flagged so they are never silently compared with new ones.
"""
import asyncio
import os
import random
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import citation_loop as cl  # noqa: E402
import history as hist  # noqa: E402
import importer  # noqa: E402
import storage as stg  # noqa: E402

PANEL = [{"prompt_id": f"p{i}", "prompt": f"question {i}", "type": t}
         for i, t in enumerate(["consideration", "consideration", "awareness", "brand", "control", "control"], 1)]


def by_id(panel):
    return {p["prompt_id"]: p for p in panel}


def rows(snapshot, rec, panel=PANEL, platform="chatgpt", repeats=3, version=cl.METRIC_VERSION, date="2026-11-01"):
    out = []
    for p in panel:
        for r in range(1, repeats + 1):
            row = {"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": platform, "repeat": r,
                   "mentioned": int(p["prompt_id"] in rec), "cited": 0, "recommended": int(p["prompt_id"] in rec),
                   "date": date}
            if version is not None:
                row["metric_version"] = version
            out.append(row)
    return out


def unversioned(rs):
    return [{k: v for k, v in x.items() if k != "metric_version"} for x in rs]


class ImporterRuleTests(unittest.TestCase):
    def item(self, **kw):
        base = {"query": "question 1", "platform": "chatgpt", "brand_mentioned": True, "brand_mention_count": 2}
        return {**base, **kw}

    def convert(self, *items):
        return importer.convert(list(items), PANEL, "baseline")

    def test_neutral_mention_is_not_auto_recommended_and_is_reviewed(self):
        out = self.convert(self.item(sentiment="neutral"))
        self.assertFalse(out["runs"][0]["recommended"])
        self.assertTrue(out["runs"][0]["mentioned"])
        self.assertEqual(out["needs_review"][0]["prompt_id"], "p1")

    def test_missing_sentiment_is_reviewed_not_recommended(self):
        out = self.convert(self.item())
        self.assertFalse(out["runs"][0]["recommended"])
        self.assertEqual(len(out["needs_review"]), 1)

    def test_positive_mention_is_recommended_even_with_one_mention(self):
        out = self.convert(self.item(sentiment="positive", brand_mention_count=1))
        self.assertTrue(out["runs"][0]["recommended"])
        self.assertEqual(out["needs_review"], [])

    def test_a_position_score_alone_does_not_make_a_neutral_mention_recommended(self):
        """Where a brand appears in an answer is not proof that it was recommended."""
        for score in (2, 1, 0, "", None, "n/a"):
            out = self.convert(self.item(sentiment="neutral", mention_position_score=score))
            self.assertFalse(out["runs"][0]["recommended"], score)
            self.assertEqual(len(out["needs_review"]), 1, score)

    def test_position_score_is_kept_on_the_row_and_noted_in_the_review_reason(self):
        out = self.convert(self.item(sentiment="neutral", mention_position_score=2))
        self.assertEqual(out["runs"][0]["position"], 2)
        self.assertIn("position", out["needs_review"][0]["reason"])
        self.assertIn("not", out["needs_review"][0]["reason"])

    def test_negative_mention_is_never_recommended_even_with_a_position_score(self):
        out = self.convert(self.item(sentiment="negative", mention_position_score=1))
        self.assertFalse(out["runs"][0]["recommended"])

    def test_every_non_recommended_mention_is_listed_and_close_calls_come_first(self):
        out = self.convert(self.item(sentiment="negative"), self.item(sentiment="neutral"),
                           self.item(sentiment="positive"))
        self.assertEqual(len(out["needs_review"]), 2)
        self.assertEqual(out["needs_review"][0]["sentiment"], "neutral")
        self.assertIn("reason", out["needs_review"][0])

    def test_unmentioned_answers_are_not_reviewed(self):
        out = self.convert(self.item(brand_mentioned=False), self.item(sentiment="positive"))
        self.assertEqual(out["needs_review"], [])

    def test_summary_reports_review_total_even_when_the_list_is_capped(self):
        items = [self.item(sentiment="neutral", platform=f"engine{i}") for i in range(40)]
        out = self.convert(*items)
        self.assertEqual(len(out["needs_review"]), 25)
        self.assertEqual(out["summary"]["needs_review"], 40)

    def test_rows_carry_the_current_metric_version(self):
        out = self.convert(self.item(sentiment="positive"))
        self.assertEqual(out["runs"][0]["metric_version"], cl.METRIC_VERSION)

    def test_garbage_mention_count_is_treated_as_zero_not_a_crash(self):
        out = self.convert(self.item(sentiment="positive", brand_mention_count="lots"))
        self.assertEqual(len(out["runs"]), 1)


class HeadlineTests(unittest.TestCase):
    def test_brand_questions_are_excluded_from_the_headline(self):
        s = cl.snapshot_summary(rows("a", {"p4"}), by_id(PANEL), "a", None)  # only the brand question is recommended
        self.assertEqual(s["prompts"], 3)
        self.assertAlmostEqual(s["recommendation_share"], 0.0)
        self.assertEqual(s["reputation_prompts"], 1)
        self.assertAlmostEqual(s["reputation_share"], 1.0)

    def test_headline_is_the_mean_of_awareness_and_consideration(self):
        s = cl.snapshot_summary(rows("a", {"p1", "p4"}), by_id(PANEL), "a", None)
        self.assertAlmostEqual(s["recommendation_share"], 1 / 3)

    def test_reputation_is_none_when_the_panel_has_no_brand_questions(self):
        panel = [p for p in PANEL if p["type"] != "brand"]
        s = cl.snapshot_summary(rows("a", {"p1"}, panel), by_id(panel), "a", None)
        self.assertIsNone(s["reputation_share"])
        self.assertEqual(s["reputation_prompts"], 0)

    def test_mentioned_rate_also_leaves_out_brand_questions(self):
        s = cl.snapshot_summary(rows("a", {"p4"}), by_id(PANEL), "a", None)
        self.assertAlmostEqual(s["mentioned_rate"], 0.0, places=2)

    def test_a_panel_with_only_brand_questions_has_no_headline(self):
        panel = [{"prompt_id": "p1", "prompt": "is acme legit", "type": "brand"}]
        self.assertIsNone(cl.snapshot_summary(rows("a", {"p1"}, panel), by_id(panel), "a", None))

    def test_plain_headline_sentence(self):
        s = cl.snapshot_summary(rows("a", {"p1"}), by_id(PANEL), "a", None)
        self.assertIn("buying questions", s["headline"])
        self.assertIn("%", s["headline"])


class SimulationTests(unittest.TestCase):
    """The audit's case: a true 5% discovery rate plus brand questions that always name the brand."""

    def test_true_five_percent_is_not_reported_near_thirty_seven(self):
        rng = random.Random(2026)
        panel = ([{"prompt_id": f"d{i}", "prompt": f"best tool {i}", "type": "consideration"} for i in range(16)]
                 + [{"prompt_id": f"b{i}", "prompt": f"is acme legit {i}", "type": "brand"} for i in range(8)]
                 + [{"prompt_id": f"c{i}", "prompt": f"unrelated {i}", "type": "control"} for i in range(5)])
        items = []
        for p in panel:
            if p["type"] == "control":
                continue
            for engine in ("chatgpt", "perplexity", "gemini"):
                for _ in range(3):
                    if p["type"] == "brand":  # always named, neutral wording
                        items.append({"query": p["prompt"], "platform": engine, "brand_mentioned": True,
                                      "sentiment": "neutral", "brand_mention_count": 2})
                        continue
                    roll = rng.random()
                    if roll < 0.05:  # truly recommended
                        items.append({"query": p["prompt"], "platform": engine, "brand_mentioned": True,
                                      "sentiment": "positive", "brand_mention_count": 2})
                    elif roll < 0.35:  # named in passing, not recommended
                        items.append({"query": p["prompt"], "platform": engine, "brand_mentioned": True,
                                      "sentiment": "neutral", "brand_mention_count": 1})
                    else:
                        items.append({"query": p["prompt"], "platform": engine, "brand_mentioned": False})
        out = importer.convert(items, panel, "baseline")
        s = cl.snapshot_summary(out["runs"], by_id(panel), "baseline", None)
        self.assertLess(s["recommendation_share"], 0.15)
        self.assertEqual(s["reputation_share"], 0.0)  # neutral brand-name answers are not recommendations either

    def test_the_old_way_of_counting_would_have_shown_about_thirty_seven_percent(self):
        """Documents the bug: every non-negative mention counted, brand questions averaged in."""
        rng = random.Random(2026)
        mentions = [1 if rng.random() < 0.35 else 0 for _ in range(16)]  # 5% real + 30% passing mentions
        old_headline = (sum(mentions) + 8) / 24  # plus 8 brand questions at 100%
        self.assertGreater(old_headline, 0.3)


class PanelWarningTests(unittest.TestCase):
    BRAND = {"name": "Acme Rocket", "domain": "https://www.acmerocket.com/", "aliases": ["AcmeR"]}

    def panel(self, *pairs):
        return [{"prompt_id": f"p{i}", "prompt": text, "type": t} for i, (text, t) in enumerate(pairs, 1)]

    def test_non_brand_prompt_with_the_brand_name_is_flagged_not_rejected(self):
        w = cl.panel_warnings(self.panel(("best tool vs Acme Rocket", "consideration"), ("best crm", "consideration")),
                              self.BRAND)
        self.assertEqual(len(w), 1)
        self.assertIn("p1", w[0])
        self.assertNotIn("p2", w[0])

    def test_domain_and_alias_are_caught(self):
        w = cl.panel_warnings(self.panel(("is acmerocket.com good", "awareness"), ("why use acmer", "consideration")),
                              self.BRAND)
        joined = " ".join(w)
        self.assertIn("p1", joined)
        self.assertIn("p2", joined)

    def test_brand_questions_may_name_the_brand(self):
        self.assertEqual(cl.panel_warnings(self.panel(("is Acme Rocket legit", "brand")), self.BRAND), [])

    def test_control_questions_that_name_the_brand_get_their_own_message(self):
        w = cl.panel_warnings(self.panel(("Acme Rocket for baking", "control"), ("best crm", "consideration")), self.BRAND)
        self.assertEqual(len(w), 1)
        self.assertIn("control", w[0].lower())

    def test_matching_is_case_insensitive_and_whole_word(self):
        brand = {"name": "Acme"}
        self.assertEqual(len(cl.panel_warnings(self.panel(("ACME alternatives", "consideration")), brand)), 1)
        self.assertEqual(cl.panel_warnings(self.panel(("acmeology courses", "consideration")), brand), [])

    def test_very_short_names_are_ignored_to_avoid_noise(self):
        self.assertEqual(cl.panel_warnings(self.panel(("how to go far", "consideration")), {"name": "Go"}), [])

    def test_no_brand_means_no_warnings(self):
        self.assertEqual(cl.panel_warnings(self.panel(("anything", "consideration")), None), [])
        self.assertEqual(cl.panel_warnings(self.panel(("anything", "consideration")), {}), [])

    def test_accepts_a_dict_keyed_by_prompt_id(self):
        w = cl.panel_warnings(by_id(self.panel(("Acme Rocket pricing", "consideration"))), self.BRAND)
        self.assertEqual(len(w), 1)


class Base(unittest.TestCase):
    def setUp(self):
        self.backend = stg.MemoryBackend()
        stg.set_backend(self.backend)

    def tearDown(self):
        stg.set_backend(None)


def run(coro):
    return asyncio.run(coro)


class SavedRoundTests(Base):
    def seed_old_round(self, rec):
        run(self.backend.set(stg.key("acme-site", "panel"), PANEL))
        run(self.backend.set(stg.key("acme-site", "runs", "old-round"), unversioned(rows("old-round", rec))))  # saved before the field existed
        run(self.backend.set(stg.key("acme-site", "meta"), {"project": "acme-site", "created": "2026-10-01",
                                                            "brand": {}, "snapshots": {"old-round": "2026-10-01"}}))

    def test_new_rounds_are_stamped_with_the_metric_version(self):
        run(hist.save_results("acme-site", unversioned(rows("baseline", {"p1"})), PANEL))
        stored = run(self.backend.get(stg.key("acme-site", "runs", "baseline")))
        self.assertTrue(all(x["metric_version"] == cl.METRIC_VERSION for x in stored))

    def test_save_warns_when_a_buying_question_names_the_brand(self):
        panel = [{"prompt_id": "p1", "prompt": "best Acme alternatives", "type": "consideration"},
                 {"prompt_id": "p2", "prompt": "best crm", "type": "consideration"}]
        r = [{"snapshot": "baseline", "prompt_id": p, "platform": "chatgpt", "repeat": 1, "recommended": 0}
             for p in ("p1", "p2")]
        out = run(hist.save_results("acme-site", r, panel, brand={"name": "Acme"}))
        self.assertEqual(len(out["warnings"]), 1)
        self.assertIn("p1", out["warnings"][0])

    def test_save_without_problems_returns_an_empty_warning_list(self):
        r = [{"snapshot": "baseline", "prompt_id": "p1", "platform": "chatgpt", "repeat": 1, "recommended": 0}]
        out = run(hist.save_results("acme-site", r, [{"prompt_id": "p1", "prompt": "best crm", "type": "consideration"}],
                                    brand={"name": "Acme"}))
        self.assertEqual(out["warnings"], [])

    def test_round_saved_before_metric_version_existed_is_flagged_as_older(self):
        self.seed_old_round({"p1"})
        run(hist.save_results("acme-site", unversioned(rows("new-round", {"p1"})), None))
        out = run(hist.history("acme-site"))
        flags = {s["snapshot"]: s["older_metric"] for s in out["snapshots"]}
        self.assertEqual(flags, {"old-round": True, "new-round": False})
        self.assertIn("older counting", out["markdown"])

    def test_comparing_old_and_new_rounds_is_marked_not_comparable(self):
        self.seed_old_round({"p1", "p2"})
        new = unversioned(rows("new-round", {"p1"}, date="2026-12-01"))
        run(hist.save_results("acme-site", new, None))
        out = run(hist.measure_project("acme-site", "old-round", "new-round"))
        self.assertEqual(out["change"]["all"]["verdict"], "not comparable")
        self.assertTrue(any("older" in w for w in out["warnings"]))

    def test_measure_adds_brand_name_warnings_from_the_saved_project(self):
        panel = [{"prompt_id": "p1", "prompt": "best Acme alternatives", "type": "consideration"},
                 {"prompt_id": "p2", "prompt": "best crm", "type": "consideration"}]
        r = [{"snapshot": "baseline", "prompt_id": p, "platform": "chatgpt", "repeat": 1, "recommended": 0}
             for p in ("p1", "p2")]
        run(hist.save_results("acme-site", r, panel, brand={"name": "Acme"}))
        out = run(hist.measure_project("acme-site"))
        self.assertTrue(any("p1" in w for w in out["warnings"]))
        self.assertIn("p1", out["markdown"])


def build_report(runs, panel=PANEL, base="a", cur="b", experiments=None):
    with tempfile.TemporaryDirectory() as tmp:
        cl.write_csv(os.path.join(tmp, "panel.csv"), cl.PANEL_COLS, panel)
        cl.write_csv(os.path.join(tmp, "runs.csv"), cl.RUN_COLS, runs)
        cl.write_csv(os.path.join(tmp, "experiments.csv"), cl.EXP_COLS, experiments or [])
        return cl.build_report(SimpleNamespace(dir=tmp, baseline=base, current=cur, json=True))


class ReportMetricTests(unittest.TestCase):
    def test_mixed_versions_between_baseline_and_current_warn_and_block_the_verdict(self):
        rep = build_report(rows("a", {"p1"}, version=1) + rows("b", {"p1", "p2"}, date="2026-12-01"))
        self.assertEqual(rep["change"]["all"]["verdict"], "not comparable")
        self.assertTrue(any("older" in w for w in rep["warnings"]))

    def test_same_old_version_on_both_rounds_is_comparable_but_the_level_is_flagged(self):
        rep = build_report(rows("a", {"p1"}, version=1) + rows("b", {"p1", "p2"}, version=1, date="2026-12-01"))
        self.assertNotEqual(rep["change"]["all"]["verdict"], "not comparable")
        self.assertTrue(rep["summary"]["all"]["older_metric"])

    def test_new_rounds_are_not_flagged(self):
        rep = build_report(rows("a", {"p1"}) + rows("b", {"p1"}, date="2026-12-01"))
        self.assertFalse(rep["summary"]["all"]["older_metric"])
        self.assertFalse(any("older" in w for w in rep["warnings"]))

    def test_markdown_shows_the_plain_headline_and_the_reputation_check(self):
        rep = build_report(rows("a", {"p1", "p4"}), base="a", cur="a")
        text = cl.render(rep)
        self.assertIn("buying questions", text)
        self.assertIn("Brand-name questions", text)


if __name__ == "__main__":
    unittest.main()
