"""The repeat rule applies to AI assistants, not to single-answer search surfaces.

ChatGPT, Perplexity, Gemini and Claude answer differently every time, so a number needs 3 or more repeats. Google AI
Overviews and AI Mode are one answer per search: the ai_check pack buys exactly one per question, and a round bought
as quoted must not carry a warning that says the user under-collected.
"""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import citation_loop as cl  # noqa: E402

BASE_DATE, CUR_DATE = "2026-11-01", "2026-12-01"
LLMS = ("chatgpt", "perplexity", "gemini")


def make_panel(n_disc=24, n_ctrl=5):
    return ([{"prompt_id": f"p{i:03d}", "prompt": f"best tool number {i}", "type": "consideration"}
             for i in range(1, n_disc + 1)]
            + [{"prompt_id": f"c{i:03d}", "prompt": f"unrelated question {i}", "type": "control"}
               for i in range(1, n_ctrl + 1)])


def make_runs(panel, snapshot, date, engines):
    """engines maps platform -> number of repeats."""
    return [{"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": platform, "repeat": r,
             "mentioned": int(p["prompt_id"] == "p001"), "cited": 0, "recommended": int(p["prompt_id"] == "p001"),
             "date": date, "metric_version": cl.METRIC_VERSION}
            for p in panel for platform, repeats in engines.items() for r in range(1, repeats + 1)]


def report(panel, runs, base="a", cur="b"):
    if not any(r["snapshot"] == cur for r in runs):
        cur = base  # one round only
    with tempfile.TemporaryDirectory() as tmp:
        cl.write_csv(os.path.join(tmp, "panel.csv"), cl.PANEL_COLS, panel)
        cl.write_csv(os.path.join(tmp, "runs.csv"), cl.RUN_COLS, runs)
        cl.write_csv(os.path.join(tmp, "experiments.csv"), cl.EXP_COLS, [])
        return cl.build_report(SimpleNamespace(dir=tmp, baseline=base, current=cur, json=True))


def repeat_warnings(rep):
    return [w for w in rep["warnings"] if "repeats" in w]


class SingleAnswerEngineTests(unittest.TestCase):
    def test_known_single_answer_engines(self):
        for name in ("google-aio", "google-aimode", "GOOGLE-AIO", " google-aimode "):
            self.assertTrue(cl.is_single_answer(name), name)
        for name in ("chatgpt", "perplexity", "gemini", "claude", "", None):
            self.assertFalse(cl.is_single_answer(name), name)


class PackShapedRoundTests(unittest.TestCase):
    """3 repeats for each assistant and one Google AI Overviews answer per question: what the pack quotes."""

    def setUp(self):
        self.panel = make_panel()
        self.engines = {**{e: 3 for e in LLMS}, "google-aio": 1}

    def test_a_pack_round_has_no_repeat_warning(self):
        rep = report(self.panel, make_runs(self.panel, "a", BASE_DATE, self.engines))
        self.assertEqual(repeat_warnings(rep), [])

    def test_two_pack_rounds_compared_have_no_repeat_warning(self):
        runs = make_runs(self.panel, "a", BASE_DATE, self.engines) + make_runs(self.panel, "b", CUR_DATE, self.engines)
        self.assertEqual(report(self.panel, runs)["warnings"], [])

    def test_summary_keeps_the_true_minimum_and_adds_the_checked_one(self):
        summary = report(self.panel, make_runs(self.panel, "a", BASE_DATE, self.engines))["summary"]
        self.assertEqual(summary["all"]["min_repeats"], 1)  # the plain fact
        self.assertEqual(summary["all"]["min_repeats_checked"], 3)  # the number the 3-repeat rule looks at
        self.assertEqual(summary["google-aio"]["min_repeats"], 1)
        self.assertIsNone(summary["google-aio"]["min_repeats_checked"])  # the rule does not apply there

    def test_a_round_with_only_single_answer_engines_has_no_repeat_warning(self):
        rep = report(self.panel, make_runs(self.panel, "a", BASE_DATE, {"google-aio": 1, "google-aimode": 1}))
        self.assertEqual(repeat_warnings(rep), [])

    def test_aimode_is_treated_like_aio(self):
        rep = report(self.panel, make_runs(self.panel, "a", BASE_DATE, {"chatgpt": 3, "google-aimode": 1}))
        self.assertEqual(repeat_warnings(rep), [])


class AssistantsStillNeedRepeatsTests(unittest.TestCase):
    def setUp(self):
        self.panel = make_panel()

    def test_too_few_repeats_for_an_assistant_still_warn_and_name_it(self):
        engines = {"chatgpt": 3, "perplexity": 2, "google-aio": 1}
        rep = report(self.panel, make_runs(self.panel, "a", BASE_DATE, engines))
        warned = repeat_warnings(rep)
        self.assertEqual(len(warned), 1, warned)
        self.assertIn("fewer than 3 repeats", warned[0])
        self.assertIn("perplexity", warned[0])
        self.assertNotIn("google-aio", warned[0])
        self.assertNotIn("chatgpt", warned[0])

    def test_one_repeat_for_every_assistant_warns(self):
        rep = report(self.panel, make_runs(self.panel, "a", BASE_DATE, {e: 1 for e in LLMS}))
        self.assertEqual(len(repeat_warnings(rep)), 1)

    def test_different_repeats_between_rounds_compare_assistants_only(self):
        a = make_runs(self.panel, "a", BASE_DATE, {"chatgpt": 3, "google-aio": 1})
        b = make_runs(self.panel, "b", CUR_DATE, {"chatgpt": 3, "google-aio": 2})
        self.assertEqual(repeat_warnings(report(self.panel, a + b)), [])  # aio 1 vs 2 is not noise level
        c = make_runs(self.panel, "b", CUR_DATE, {"chatgpt": 1, "google-aio": 1})
        warned = repeat_warnings(report(self.panel, a + c))
        self.assertTrue(any("different numbers of repeats" in w and "baseline 3" in w and "now 1" in w for w in warned), warned)


class EngineSetComparisonTests(unittest.TestCase):
    """A single-answer engine in only one round must not break the comparison or cause extra problems."""

    def setUp(self):
        self.panel = make_panel()
        self.with_aio = {**{e: 3 for e in LLMS}, "google-aio": 1}
        self.without_aio = {e: 3 for e in LLMS}

    def test_one_round_without_aio_still_compares_the_shared_engines(self):
        runs = make_runs(self.panel, "a", BASE_DATE, self.with_aio) + make_runs(self.panel, "b", CUR_DATE, self.without_aio)
        rep = report(self.panel, runs)
        self.assertIn("all", rep["change"])
        self.assertEqual(repeat_warnings(rep), [])
        engine_warnings = [w for w in rep["warnings"] if "engines" in w]
        self.assertEqual(len(engine_warnings), 1)
        self.assertIn("AI Overviews", engine_warnings[0])  # says which engine, in plain words
        self.assertIn("leaves", engine_warnings[0])

    def test_the_reverse_order_is_handled_too(self):
        runs = make_runs(self.panel, "a", BASE_DATE, self.without_aio) + make_runs(self.panel, "b", CUR_DATE, self.with_aio)
        rep = report(self.panel, runs)
        self.assertIn("all", rep["change"])
        self.assertEqual(len([w for w in rep["warnings"] if "engines" in w]), 1)

    def test_assistants_that_differ_keep_the_original_wording(self):
        runs = (make_runs(self.panel, "a", BASE_DATE, {"chatgpt": 3, "perplexity": 3})
                + make_runs(self.panel, "b", CUR_DATE, {"chatgpt": 3, "gemini": 3}))
        engine_warnings = [w for w in report(self.panel, runs)["warnings"] if "engines" in w]
        self.assertEqual(len(engine_warnings), 1)
        self.assertIn("different engines", engine_warnings[0])
        self.assertIn("perplexity", engine_warnings[0])


if __name__ == "__main__":
    unittest.main()
