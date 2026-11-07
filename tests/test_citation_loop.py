"""Tests for scripts/citation_loop.py (stdlib unittest, synthetic data only)."""
import csv
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "citation_loop.py")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import citation_loop as cl  # noqa: E402

ENGINES = ("chatgpt", "perplexity")
REPEATS = 3


class LoopCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "citation")

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, check=True):
        proc = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)
        if check:
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc

    def build_panel(self, consideration=24, controls=4, freeze=True):
        self.cli("init", self.dir)
        for i in range(consideration):
            self.cli("panel", "add", self.dir, "--prompt", f"best tool number {i} for teams", "--type", "consideration")
        for i in range(controls):
            self.cli("panel", "add", self.dir, "--prompt", f"unrelated control question {i}", "--type", "control")
        if freeze:
            self.cli("panel", "freeze", self.dir)

    def runs(self, recommended_ids, snapshot, control_ids=(), total=28):
        rows = []
        for n in range(1, total + 1):
            pid = f"p{n:03d}"
            for engine in ENGINES:
                for rep in range(1, REPEATS + 1):
                    hit = pid in recommended_ids or pid in control_ids
                    rows.append({"prompt_id": pid, "platform": engine, "repeat": rep, "brand_mentioned": hit,
                                 "brand_cited": hit, "brand_recommended": hit, "date": "2026-11-01" if snapshot == "base" else "2026-12-01"})
        path = os.path.join(self.tmp.name, f"{snapshot}.json")
        with open(path, "w") as fh:
            json.dump(rows, fh)
        self.cli("ingest", self.dir, "--snapshot", snapshot, "--file", path)

    def report(self, *extra):
        return json.loads(self.cli("report", self.dir, "--json", *extra).stdout)


class MathTests(unittest.TestCase):
    def test_wilson_known_value(self):
        rate, low, high = cl.wilson(5, 10)
        self.assertAlmostEqual(rate, 0.5)
        self.assertAlmostEqual(low, 0.2366, places=3)
        self.assertAlmostEqual(high, 0.7634, places=3)

    def test_wilson_edges(self):
        self.assertEqual(cl.wilson(0, 0), (0.0, 0.0, 0.0))
        _, low, high = cl.wilson(0, 20)
        self.assertEqual(low, 0.0)
        self.assertGreater(high, 0.1)

    def test_bootstrap_is_deterministic_and_brackets_mean(self):
        vals = [0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 0.0, 1.0]
        a, b = cl.boot_ci(vals), cl.boot_ci(vals)
        self.assertEqual(a, b)
        self.assertLessEqual(a[1], a[0])
        self.assertGreaterEqual(a[2], a[0])

    def test_to_bool(self):
        self.assertEqual([cl.to_bool(x) for x in (True, "yes", "0", "", "FALSE", 1)], [1, 1, 0, 0, 0, 1])
        with self.assertRaises(ValueError):
            cl.to_bool("maybe")


class PanelTests(LoopCase):
    def test_frozen_panel_refuses_edits(self):
        self.build_panel(consideration=2, controls=1)
        proc = self.cli("panel", "add", self.dir, "--prompt", "late addition", check=False)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("frozen", proc.stderr)

    def test_duplicate_prompt_refused(self):
        self.cli("init", self.dir)
        self.cli("panel", "add", self.dir, "--prompt", "Best CRM?")
        self.assertNotEqual(self.cli("panel", "add", self.dir, "--prompt", "best crm?", check=False).returncode, 0)

    def test_ingest_requires_frozen_panel(self):
        self.build_panel(consideration=2, controls=1, freeze=False)
        path = os.path.join(self.tmp.name, "r.json")
        with open(path, "w") as fh:
            json.dump([], fh)
        self.assertNotEqual(self.cli("ingest", self.dir, "--snapshot", "s", "--file", path, check=False).returncode, 0)

    def test_ingest_rejects_unknown_prompt_and_duplicates(self):
        self.build_panel(consideration=1, controls=0)
        row = {"prompt_id": "p001", "platform": "chatgpt", "repeat": 1, "recommended": 1}
        for rows, snap in (([dict(row, prompt_id="p999")], "a"), ([row, row], "b")):
            path = os.path.join(self.tmp.name, f"{snap}.json")
            with open(path, "w") as fh:
                json.dump(rows, fh)
            self.assertNotEqual(self.cli("ingest", self.dir, "--snapshot", snap, "--file", path, check=False).returncode, 0)


class BrandAndVersionCliTests(LoopCase):
    def test_panel_add_warns_but_still_adds_when_a_buying_question_names_the_brand(self):
        self.cli("init", self.dir)
        proc = self.cli("panel", "add", self.dir, "--prompt", "best alternatives to Acme", "--type", "consideration",
                        "--brand", "Acme")
        self.assertIn("WARNING", proc.stderr)
        self.assertIn("p001", proc.stderr)
        self.assertIn("added p001", proc.stdout)

    def test_brand_type_questions_do_not_warn(self):
        self.cli("init", self.dir)
        proc = self.cli("panel", "add", self.dir, "--prompt", "is Acme legit", "--type", "brand", "--brand", "Acme")
        self.assertNotIn("WARNING", proc.stderr)

    def test_ingested_rows_are_stamped_with_the_metric_version(self):
        self.build_panel(consideration=2, controls=1)
        self.runs({"p001"}, "base", total=3)
        with open(os.path.join(self.dir, "runs.csv"), newline="") as fh:
            first = next(csv.DictReader(fh))
        self.assertEqual(first["metric_version"], str(cl.METRIC_VERSION))

    def test_report_leads_with_the_plain_buying_question_sentence(self):
        self.build_panel()
        self.runs({"p001", "p002"}, "base")
        out = self.cli("report", self.dir).stdout
        self.assertIn("of buying questions", out)

    def test_experiment_dated_after_the_latest_round_is_not_scored_in_the_cli_report(self):
        self.build_panel()
        self.runs(set(), "base")
        self.runs({"p001"}, "after")
        self.cli("experiment", "add", self.dir, "--action-text", "Later change", "--mechanism", "onpage",
                 "--targets", "p001", "--date", "2027-03-01")
        out = self.cli("report", self.dir, "--baseline", "base", "--current", "after").stdout
        self.assertIn("Not scored", out)


class ReportTests(LoopCase):
    def test_share_and_ci_for_single_snapshot(self):
        self.build_panel()
        self.runs({f"p{n:03d}" for n in range(1, 7)}, "base")
        s = self.report()["summary"]["all"]
        self.assertAlmostEqual(s["recommendation_share"], 6 / 24)
        self.assertLessEqual(s["rs_low"], s["recommendation_share"])
        self.assertGreaterEqual(s["rs_high"], s["recommendation_share"])
        self.assertEqual(s["control_false_positive"], 0.0)
        self.assertEqual(s["prompts"], 24)

    def test_improvement_is_detected_and_attributed_to_targets(self):
        self.build_panel()
        before = {f"p{n:03d}" for n in range(1, 5)}
        targets = [f"p{n:03d}" for n in range(5, 13)]
        self.runs(before, "base")
        self.runs(before | set(targets), "after")
        self.cli("experiment", "add", self.dir, "--action-text", "Added to two listicles", "--mechanism", "listicle",
                 "--targets", ",".join(targets), "--date", "2026-11-15", "--recheck-after", "2026-11-02")
        rep = self.report("--baseline", "base", "--current", "after")
        change = rep["change"]["all"]
        self.assertGreater(change["delta"], 0.2)
        self.assertEqual(change["verdict"], "improved")
        self.assertEqual(change["control_drift"], 0.0)
        exp = rep["experiments"][0]["result"]
        self.assertEqual(exp["verdict"], "supported")
        self.assertAlmostEqual(exp["target_delta"], 1.0)
        self.assertAlmostEqual(exp["other_delta"], 0.0)
        self.assertEqual(rep["due"], [])  # the current round was measured after the recheck date: already re-measured

    def test_engine_drift_without_real_change_is_not_called_an_improvement_of_targets(self):
        self.build_panel()
        everything = {f"p{n:03d}" for n in range(1, 25)}
        self.runs(set(), "base")
        self.runs(everything, "after")
        self.cli("experiment", "add", self.dir, "--action-text", "Rewrote pages", "--mechanism", "onpage",
                 "--targets", "p001,p002,p003,p004", "--date", "2026-11-15")
        res = self.report("--baseline", "base", "--current", "after")["experiments"][0]["result"]
        self.assertEqual(res["verdict"], "inconclusive")

    def test_control_false_positives_are_reported(self):
        self.build_panel()
        self.runs({"p001"}, "base", control_ids={"p025", "p026"})
        s = self.report()["summary"]["all"]
        self.assertAlmostEqual(s["control_false_positive"], 0.5)

    def test_warnings_for_small_panels(self):
        self.build_panel(consideration=5, controls=0)
        rows = [{"prompt_id": f"p{n:03d}", "platform": "chatgpt", "repeat": 1, "recommended": 1} for n in range(1, 6)]
        path = os.path.join(self.tmp.name, "s.json")
        with open(path, "w") as fh:
            json.dump(rows, fh)
        self.cli("ingest", self.dir, "--snapshot", "s", "--file", path)
        text = " ".join(self.report()["warnings"])
        self.assertIn("directional", text)
        self.assertIn("repeats", text)
        self.assertIn("control", text.lower())

    def test_markdown_report_renders(self):
        self.build_panel()
        self.runs({"p001"}, "base")
        out = self.cli("report", self.dir).stdout
        self.assertIn("Recommendation Share", out)
        self.assertIn("Correlation, not proof", out)

    def test_edited_panel_after_freeze_is_flagged(self):
        self.build_panel(consideration=2, controls=1)
        self.runs({"p001"}, "base", total=3)
        panel = os.path.join(self.dir, "panel.csv")
        with open(panel) as fh:
            text = fh.read().replace("best tool number 0", "best tool number zero")
        with open(panel, "w") as fh:
            fh.write(text)
        self.assertTrue(any("frozen" in w.lower() for w in self.report()["warnings"]))


if __name__ == "__main__":
    unittest.main()
