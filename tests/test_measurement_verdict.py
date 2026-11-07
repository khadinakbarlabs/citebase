"""Top move 3: a trustworthy "did it work" verdict.

Experiments are only scored when they shipped between the two rounds, confounding comes from shared targets,
engine-wide movement is called out, the report says what the panel can reliably see, zero shares get an upper
bound instead of false certainty, and the overall verdict respects control drift.
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
import history as hist  # noqa: E402

BASE_DATE, CUR_DATE = "2026-11-01", "2026-12-01"


def make_panel(n_disc=24, n_ctrl=5):
    return ([{"prompt_id": f"p{i:03d}", "prompt": f"best tool number {i}", "type": "consideration"}
             for i in range(1, n_disc + 1)]
            + [{"prompt_id": f"c{i:03d}", "prompt": f"unrelated question {i}", "type": "control"}
               for i in range(1, n_ctrl + 1)])


def make_runs(panel, snapshot, hits, date, platforms=("chatgpt", "perplexity"), repeats=3):
    """hits maps prompt_id -> how many of the repeats were recommended (default 0)."""
    out = []
    for p in panel:
        k = hits.get(p["prompt_id"], 0)
        for platform in platforms:
            for r in range(1, repeats + 1):
                out.append({"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": platform, "repeat": r,
                            "mentioned": int(r <= k), "cited": 0, "recommended": int(r <= k), "date": date,
                            "metric_version": cl.METRIC_VERSION})
    return out


def exp(exp_id, targets, date, status="shipped", action="changed pages", mechanism="onpage"):
    return {"exp_id": exp_id, "date": date, "action": action, "mechanism": mechanism,
            "target_prompt_ids": ",".join(targets), "url": "", "status": status, "recheck_after": "2099-01-01", "notes": ""}


def report(panel, runs, experiments=None, base="a", cur="b"):
    with tempfile.TemporaryDirectory() as tmp:
        cl.write_csv(os.path.join(tmp, "panel.csv"), cl.PANEL_COLS, panel)
        cl.write_csv(os.path.join(tmp, "runs.csv"), cl.RUN_COLS, runs)
        cl.write_csv(os.path.join(tmp, "experiments.csv"), cl.EXP_COLS, experiments or [])
        return cl.build_report(SimpleNamespace(dir=tmp, baseline=base, current=cur, json=True))


def ids(lo, hi):
    return [f"p{i:03d}" for i in range(lo, hi + 1)]


class TimingTests(unittest.TestCase):
    def setUp(self):
        self.panel = make_panel()
        self.targets = ids(1, 4)
        self.runs = (make_runs(self.panel, "a", {}, BASE_DATE)
                     + make_runs(self.panel, "b", {p: 3 for p in self.targets}, CUR_DATE))

    def result(self, date):
        rep = report(self.panel, self.runs, [exp("e001", self.targets, date)])
        return rep["experiments"][0]

    def test_change_made_between_the_rounds_is_scored(self):
        e = self.result("2026-11-15")
        self.assertEqual(e["timing"], "ok")
        self.assertIsNotNone(e["result"])

    def test_change_on_the_day_of_the_current_round_is_scored(self):
        self.assertEqual(self.result(CUR_DATE)["timing"], "ok")

    def test_change_made_before_the_baseline_is_not_scored(self):
        e = self.result("2026-10-15")
        self.assertEqual(e["timing"], "before_baseline")
        self.assertIsNone(e["result"])
        self.assertIn("Not scored", e["note"])

    def test_change_on_the_baseline_day_is_not_scored(self):
        self.assertEqual(self.result(BASE_DATE)["timing"], "before_baseline")

    def test_change_dated_after_the_current_round_is_not_scored(self):
        e = self.result("2027-03-01")
        self.assertEqual(e["timing"], "after_current")
        self.assertIsNone(e["result"])

    def test_change_without_a_valid_date_is_not_scored(self):
        e = self.result("soon")
        self.assertEqual(e["timing"], "undated")
        self.assertIsNone(e["result"])

    def test_rounds_on_the_same_day_do_not_claim_the_change_came_first(self):
        runs = (make_runs(self.panel, "a", {}, CUR_DATE)
                + make_runs(self.panel, "b", {p: 3 for p in self.targets}, CUR_DATE))
        e = report(self.panel, runs, [exp("e001", self.targets, "2026-11-10")])["experiments"][0]
        self.assertEqual(e["timing"], "rounds_not_separated")
        self.assertIsNone(e["result"])
        self.assertIn("Not scored", e["note"])
        self.assertIn("date", e["note"])
        self.assertNotIn("on or before the day the starting round", e["note"])

    def test_markdown_explains_why_an_experiment_was_not_scored(self):
        rep = report(self.panel, self.runs, [exp("e001", self.targets, "2027-03-01")])
        self.assertIn("Not scored", cl.render(rep))


class DueTests(unittest.TestCase):
    """A change is due for a re-measure only until a round has been measured on or after its recheck date."""

    def setUp(self):
        self.panel = make_panel()
        self.targets = ids(1, 4)

    def due(self, cur_date, recheck_after):
        runs = (make_runs(self.panel, "a", {}, "2026-01-01")
                + make_runs(self.panel, "b", {p: 3 for p in self.targets}, cur_date))
        e = dict(exp("e001", self.targets, "2026-01-15"), recheck_after=recheck_after)
        return report(self.panel, runs, [e])["due"]

    def test_change_is_due_when_no_round_is_newer_than_its_recheck_date(self):
        self.assertEqual(len(self.due("2026-02-01", "2026-03-01")), 1)

    def test_change_is_not_due_once_a_round_was_measured_after_its_recheck_date(self):
        self.assertEqual(self.due("2026-04-01", "2026-03-01"), [])

    def test_change_is_not_due_on_the_recheck_day_itself_when_measured_that_day(self):
        self.assertEqual(self.due("2026-03-01", "2026-03-01"), [])


class ConfoundingTests(unittest.TestCase):
    def setUp(self):
        self.panel = make_panel()
        self.runs = (make_runs(self.panel, "a", {}, BASE_DATE)
                     + make_runs(self.panel, "b", {p: 3 for p in ids(1, 8)}, CUR_DATE))

    def rows(self, *experiments):
        return {e["exp_id"]: e for e in report(self.panel, self.runs, list(experiments))["experiments"]}

    def test_shared_targets_in_the_same_window_are_confounded(self):
        out = self.rows(exp("e001", ids(1, 4), "2026-11-10"), exp("e002", ids(4, 8), "2026-11-12"))
        self.assertTrue(out["e001"]["confounded"])
        self.assertEqual(out["e001"]["confounded_with"], ["e002"])
        self.assertTrue(out["e002"]["confounded"])

    def test_disjoint_targets_are_not_confounded_even_if_shipped_together(self):
        out = self.rows(exp("e001", ids(1, 4), "2026-11-10"), exp("e002", ids(5, 8), "2026-11-10"))
        self.assertFalse(out["e001"]["confounded"])
        self.assertEqual(out["e001"]["confounded_with"], [])

    def test_an_overlapping_change_outside_the_window_does_not_confound(self):
        out = self.rows(exp("e001", ids(1, 4), "2026-11-10"), exp("e002", ids(1, 4), "2026-09-01"))
        self.assertFalse(out["e001"]["confounded"])

    def test_abandoned_changes_do_not_confound(self):
        out = self.rows(exp("e001", ids(1, 4), "2026-11-10"), exp("e002", ids(1, 4), "2026-11-11", status="abandoned"))
        self.assertFalse(out["e001"]["confounded"])

    def test_other_changes_targets_are_left_out_of_the_comparison_group(self):
        out = self.rows(exp("e001", ids(1, 4), "2026-11-10"), exp("e002", ids(5, 8), "2026-11-10"))
        res = out["e001"]["result"]
        self.assertEqual(res["others"], 16)  # 24 - 4 own targets - 4 other change's targets
        self.assertEqual(res["others_excluded"], 4)

    def test_exclusion_is_skipped_when_too_few_peers_would_remain(self):
        panel = make_panel(n_disc=8)
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {p: 3 for p in ids(1, 2)}, CUR_DATE)
        out = report(panel, runs, [exp("e001", ids(1, 2), "2026-11-10"), exp("e002", ids(3, 6), "2026-11-10")])
        res = {e["exp_id"]: e for e in out["experiments"]}["e001"]["result"]
        self.assertEqual(res["others"], 6)  # all 6 non-target peers, because only 2 would remain
        self.assertEqual(res["others_excluded"], 0)


class EngineWideTests(unittest.TestCase):
    def test_other_prompts_rising_too_is_called_engine_wide_not_a_win(self):
        panel = make_panel()
        everything = {p["prompt_id"]: 3 for p in panel if p["type"] != "control"}
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", everything, CUR_DATE)
        e = report(panel, runs, [exp("e001", ids(1, 4), "2026-11-10")])["experiments"][0]
        self.assertNotEqual(e["result"]["verdict"], "supported")
        self.assertTrue(e["result"]["engine_wide_likely"])
        self.assertIn("other prompts rose too", e["result"]["reading"].lower())

    def test_a_real_lift_on_the_targets_alone_is_supported(self):
        panel = make_panel()
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {p: 3 for p in ids(1, 6)}, CUR_DATE)
        e = report(panel, runs, [exp("e001", ids(1, 6), "2026-11-10")])["experiments"][0]
        self.assertEqual(e["result"]["verdict"], "supported")
        self.assertFalse(e["result"]["engine_wide_likely"])


class TinyTargetSetTests(unittest.TestCase):
    def one(self, n_targets):
        panel = make_panel()
        targets = ids(1, n_targets)
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {p: 3 for p in targets}, CUR_DATE)
        return report(panel, runs, [exp("e001", targets, "2026-11-10")])["experiments"][0]["result"]

    def test_two_targeted_questions_cannot_be_called_supported(self):
        res = self.one(2)
        self.assertEqual(res["verdict"], "inconclusive")
        self.assertIn("too few", res["reading"])

    def test_three_targeted_questions_can_be_scored(self):
        self.assertEqual(self.one(3)["verdict"], "supported")


class ControlDriftTests(unittest.TestCase):
    def change(self, control_hits):
        panel = make_panel()
        half = {p: 3 for p in ids(1, 12)}
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {**half, **control_hits}, CUR_DATE)
        return report(panel, runs)["change"]["all"]

    def test_improvement_with_flat_controls_stays_improved(self):
        c = self.change({})
        self.assertEqual(c["verdict"], "improved")
        self.assertEqual(c["control_drift"], 0.0)

    def test_improvement_is_downgraded_when_controls_rose_just_as_much(self):
        c = self.change({f"c{i:03d}": 3 for i in range(1, 6)})
        self.assertEqual(c["verdict"], "engines moved")
        self.assertIn("control", c["note"].lower())

    def test_small_control_drift_does_not_cancel_a_large_improvement(self):
        c = self.change({"c001": 3})  # one of five controls rose: drift 0.2, delta about 0.5
        self.assertEqual(c["verdict"], "improved")

    def test_worsening_is_downgraded_when_controls_fell_too(self):
        panel = make_panel()
        base_hits = {**{p: 3 for p in ids(1, 12)}, **{f"c{i:03d}": 3 for i in range(1, 6)}}
        runs = make_runs(panel, "a", base_hits, BASE_DATE) + make_runs(panel, "b", {}, CUR_DATE)
        self.assertEqual(report(panel, runs)["change"]["all"]["verdict"], "engines moved")


class PowerTests(unittest.TestCase):
    def deltas(self, plus, minus, flat):
        n = plus + minus + flat
        panel = make_panel(n_disc=n)
        base = {p: 3 for p in ids(plus + 1, plus + minus)}
        cur = {p: 3 for p in ids(1, plus)}
        runs = make_runs(panel, "a", base, BASE_DATE) + make_runs(panel, "b", cur, CUR_DATE)
        return report(panel, runs)

    def test_wide_interval_that_includes_a_worthwhile_change_is_too_early_to_tell(self):
        rep = self.deltas(plus=4, minus=4, flat=2)
        self.assertEqual(rep["change"]["all"]["verdict"], "too early to tell")

    def test_every_prompt_unchanged_on_a_large_panel_is_no_detectable_change(self):
        panel = make_panel(n_disc=40)
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {}, CUR_DATE)
        self.assertEqual(report(panel, runs)["change"]["all"]["verdict"], "no detectable change")

    def test_one_shared_prompt_cannot_be_called_improved(self):
        panel = make_panel(n_disc=1)
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {"p001": 3}, CUR_DATE)
        self.assertEqual(report(panel, runs)["change"]["all"]["verdict"], "too early to tell")

    def test_smallest_visible_change_is_reported_in_points(self):
        rep = self.deltas(plus=4, minus=4, flat=2)
        pts = rep["change"]["all"]["min_detectable_points"]
        self.assertIsInstance(pts, int)
        self.assertGreaterEqual(pts, 1)
        self.assertEqual(rep["smallest_change_points"], pts)
        self.assertIn("smallest change this panel can reliably see: about", cl.render(rep).lower())

    def test_a_bigger_panel_can_see_smaller_changes(self):
        small = self.deltas(plus=4, minus=4, flat=2)["change"]["all"]["min_detectable_points"]
        large = self.deltas(plus=16, minus=16, flat=8)["change"]["all"]["min_detectable_points"]
        self.assertLess(large, small)

    def test_too_early_message_is_printed(self):
        text = cl.render(self.deltas(plus=4, minus=4, flat=2))
        self.assertIn("too early to tell", text.lower())


class ZeroShareTests(unittest.TestCase):
    def test_all_zero_gets_a_rule_of_three_upper_bound(self):
        mid, low, high = cl.boot_ci([0.0] * 20)
        self.assertEqual((mid, low), (0.0, 0.0))
        self.assertAlmostEqual(high, 3 / 20)

    def test_all_one_gets_a_lower_bound(self):
        mid, low, high = cl.boot_ci([1.0] * 20)
        self.assertEqual((mid, high), (1.0, 1.0))
        self.assertAlmostEqual(low, 1 - 3 / 20)

    def test_single_unit_is_not_reported_as_certain(self):
        _, low, high = cl.boot_ci([0.4])
        self.assertEqual((low, high), (0.0, 1.0))

    def test_ordinary_values_keep_the_bootstrap_interval(self):
        mean, low, high = cl.boot_ci([0.0, 1.0, 0.0, 1.0, 0.0, 0.0])
        self.assertLess(low, mean)
        self.assertGreater(high, mean)

    def test_identical_values_that_are_not_extreme_still_get_a_range(self):
        mid, low, high = cl.boot_ci([1 / 3] * 6)
        self.assertAlmostEqual(mid, 1 / 3)
        self.assertLess(low, mid)
        self.assertGreater(high, mid)

    def test_identical_change_in_every_prompt_is_not_a_zero_width_interval(self):
        panel = make_panel(n_disc=24)
        runs = (make_runs(panel, "a", {}, BASE_DATE)
                + make_runs(panel, "b", {p["prompt_id"]: 1 for p in panel}, CUR_DATE))
        c = report(panel, runs)["change"]["all"]
        self.assertLess(c["low"], c["delta"])
        self.assertGreater(c["high"], c["delta"])

    def test_experiment_with_identical_deltas_is_not_called_supported(self):
        panel = make_panel(n_disc=6, n_ctrl=5)
        targets = ids(1, 3)
        runs = (make_runs(panel, "a", {}, BASE_DATE)
                + make_runs(panel, "b", {p: 1 for p in targets}, CUR_DATE))
        e = report(panel, runs, [exp("e001", targets, "2026-11-15")])["experiments"][0]["result"]
        self.assertNotEqual(e["low"], e["high"])
        self.assertEqual(e["verdict"], "inconclusive")
        self.assertIn("early", e["reading"].lower())

    def test_experiment_with_all_zero_deltas_gets_a_range_and_a_caution(self):
        panel = make_panel(n_disc=6, n_ctrl=5)
        targets = ids(1, 3)
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {}, CUR_DATE)
        e = report(panel, runs, [exp("e001", targets, "2026-11-15")])["experiments"][0]["result"]
        self.assertNotEqual(e["low"], e["high"])
        self.assertIsNotNone(e["min_detectable_points"])
        self.assertIn("early", e["reading"].lower())

    def test_zero_share_report_does_not_print_zero_to_zero(self):
        panel = make_panel(n_disc=20)
        rep = report(panel, make_runs(panel, "a", {}, BASE_DATE), base="a", cur="a")
        s = rep["summary"]["all"]
        self.assertEqual(s["recommendation_share"], 0.0)
        self.assertAlmostEqual(s["rs_high"], 0.15)
        text = cl.render(rep)
        self.assertNotIn("(0.0% to 0.0%)", text)
        self.assertIn("0.0% to 15.0%", text)
        self.assertTrue(any("exactly 0%" in w for w in rep["warnings"]))

    def test_unchanged_zero_to_zero_change_gets_a_two_sided_bound(self):
        panel = make_panel(n_disc=20)
        runs = make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {}, CUR_DATE)
        c = report(panel, runs)["change"]["all"]
        self.assertAlmostEqual(c["low"], -0.15)
        self.assertAlmostEqual(c["high"], 0.15)


class ControlCountTests(unittest.TestCase):
    def warnings(self, n_ctrl):
        panel = make_panel(n_ctrl=n_ctrl)
        return report(panel, make_runs(panel, "a", {}, BASE_DATE), base="a", cur="a")["warnings"]

    def test_fewer_than_five_controls_warns(self):
        w = " ".join(self.warnings(3))
        self.assertIn("3 control", w)
        self.assertIn("5", w)

    def test_five_controls_is_fine(self):
        self.assertFalse(any("control" in w.lower() for w in self.warnings(5)))

    def test_no_controls_keeps_the_existing_warning(self):
        self.assertTrue(any("No control prompts" in w for w in self.warnings(0)))

    def test_no_buying_questions_is_called_out(self):
        panel = [{"prompt_id": "p1", "prompt": "is acme legit", "type": "brand"}]
        runs = make_runs(panel, "a", {"p1": 3}, BASE_DATE)
        rep = report(panel, runs, base="a", cur="a")
        self.assertTrue(any("buying questions" in w for w in rep["warnings"]))


class ComparabilityTests(unittest.TestCase):
    def test_different_engine_sets_warn_and_compare_on_the_shared_engines_only(self):
        panel = make_panel()
        base = make_runs(panel, "a", {}, BASE_DATE, platforms=("chatgpt",))
        base += make_runs(panel, "a", {p["prompt_id"]: 3 for p in panel}, BASE_DATE, platforms=("perplexity",))
        cur = make_runs(panel, "b", {}, CUR_DATE, platforms=("chatgpt",))
        rep = report(panel, base + cur)
        self.assertTrue(any("engines" in w and "perplexity" in w for w in rep["warnings"]))
        self.assertEqual(rep["change"]["all"]["delta"], 0.0)

    def test_rounds_with_no_engine_in_common_are_not_compared_overall(self):
        panel = make_panel()
        runs = (make_runs(panel, "a", {}, BASE_DATE, platforms=("chatgpt",))
                + make_runs(panel, "b", {p["prompt_id"]: 3 for p in panel}, CUR_DATE, platforms=("gemini",)))
        rep = report(panel, runs)
        self.assertNotIn("all", rep["change"])
        self.assertTrue(any("engines" in w for w in rep["warnings"]))

    def test_same_engines_raise_no_engine_warning(self):
        panel = make_panel()
        rep = report(panel, make_runs(panel, "a", {}, BASE_DATE) + make_runs(panel, "b", {}, CUR_DATE))
        self.assertFalse(any("engines" in w for w in rep["warnings"]))

    def test_different_repeat_counts_warn(self):
        panel = make_panel()
        rep = report(panel, make_runs(panel, "a", {}, BASE_DATE, repeats=3) + make_runs(panel, "b", {}, CUR_DATE, repeats=1))
        self.assertTrue(any("repeats" in w and "baseline" in w for w in rep["warnings"]))


class RecheckDefaultTests(unittest.TestCase):
    def test_saved_changes_default_to_a_recheck_thirty_days_later(self):
        out = hist.clean_experiments([{"action": "wrote a page", "date": "2026-11-10"}])
        self.assertEqual(out[0]["recheck_after"], "2026-12-10")

    def test_an_explicit_recheck_date_is_kept(self):
        out = hist.clean_experiments([{"action": "wrote a page", "date": "2026-11-10", "recheck_after": "2027-01-01"}])
        self.assertEqual(out[0]["recheck_after"], "2027-01-01")

    def test_an_unreadable_date_leaves_recheck_unset(self):
        out = hist.clean_experiments([{"action": "wrote a page", "date": "soon"}])
        self.assertNotIn("recheck_after", out[0])


if __name__ == "__main__":
    unittest.main()
