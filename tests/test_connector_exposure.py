"""What the connector shows the AI: new measurement fields, the short 'next' hints, brand warnings, saved defaults."""
import ast
import asyncio
import datetime as dt
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import history as hist  # noqa: E402
import runner  # noqa: E402
import storage as stg  # noqa: E402
import tools  # noqa: E402
from test_site_audit import ServerCase  # noqa: E402

HAVE_PYDANTIC = importlib.util.find_spec("pydantic") is not None
MAX_NEXT_WORDS = 25


def run(coro):
    return asyncio.run(coro)


def panel(buying=24, brand_prompts=4, controls=5):
    rows = [{"prompt_id": f"p{n:03d}", "prompt": f"best tool {n}", "type": "consideration"} for n in range(1, buying + 1)]
    rows += [{"prompt_id": f"b{n:03d}", "prompt": f"is Acme good {n}", "type": "brand"} for n in range(1, brand_prompts + 1)]
    rows += [{"prompt_id": f"c{n:03d}", "prompt": f"control {n}", "type": "control"} for n in range(1, controls + 1)]
    return rows


def answers(rows, snapshot, date, hits, repeats=3, engines=("chatgpt", "perplexity")):
    out = []
    for p in rows:
        for engine in engines:
            for rep in range(1, repeats + 1):
                hit = p["prompt_id"] in hits
                out.append({"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": engine, "repeat": rep,
                            "mentioned": hit, "cited": hit, "recommended": hit, "date": date})
    return out


def two_rounds():
    rows = panel()
    first = {"p001", "p002", "b001", "b002", "b003", "b004"}
    second = {f"p{n:03d}" for n in range(1, 13)} | {"b001", "b002", "b003", "b004"}
    return rows, answers(rows, "baseline", "2026-11-01", first) + answers(rows, "after", "2026-12-01", second)


def words(text: str) -> int:
    return len(text.split())


class MeasureExposure(unittest.TestCase):
    def setUp(self):
        self.rows, self.runs = two_rounds()

    def test_headline_reputation_and_metric_version_reach_the_result(self):
        rep = tools.measure(self.rows, self.runs, "baseline", "after")
        overall = rep["summary"]["all"]
        for key in ("reputation_share", "reputation_low", "reputation_high", "reputation_prompts", "metric_version",
                    "older_metric", "headline"):
            self.assertIn(key, overall)
        self.assertEqual(overall["prompts"], 24)  # buying questions only
        self.assertEqual(overall["reputation_prompts"], 4)
        self.assertIn("buying questions", rep["headline"])
        self.assertTrue(rep["smallest_change_points"])
        self.assertIn("min_detectable_points", rep["change"]["all"])

    def test_next_hint_is_short_and_points_at_the_next_move(self):
        rep = tools.measure(self.rows, self.runs, "baseline", "after")
        self.assertTrue(rep["next"])
        self.assertLessEqual(words(rep["next"]), MAX_NEXT_WORDS)
        self.assertIn("30 days", rep["next"])

    def test_next_hint_changes_when_changes_are_due(self):
        exp = [{"action": "Joined listicles", "mechanism": "listicle", "date": "2026-11-15",
                "recheck_after": "2026-11-20", "target_prompt_ids": "p003,p004,p005"}]
        rep = tools.measure(self.rows, self.runs, "baseline", "after", exp)
        self.assertLessEqual(words(rep["next"]), MAX_NEXT_WORDS)

    def test_brand_name_in_a_buying_question_is_warned_about(self):
        rows = [dict(r) for r in self.rows]
        rows[0]["prompt"] = "is Acme the best tool"
        rep = tools.measure(rows, self.runs, "baseline", "after", brand={"name": "Acme", "domain": "acme.com"})
        self.assertTrue(any("name the brand" in w for w in rep["warnings"]), rep["warnings"])
        self.assertIn("name the brand", rep["markdown"])

    def test_no_brand_means_no_brand_warning(self):
        rep = tools.measure(self.rows, self.runs, "baseline", "after")
        self.assertFalse(any("name the brand" in w for w in rep["warnings"]))

    def test_brand_aliases_are_used(self):
        rows = [dict(r) for r in self.rows]
        rows[1]["prompt"] = "is acmepay good for payroll"
        rep = tools.measure(rows, self.runs, "baseline", "after", brand={"name": "Acme", "aliases": ["AcmePay"]})
        self.assertTrue(any("name the brand" in w for w in rep["warnings"]))

    def test_brand_is_accepted_over_run_for_fresh_data_only(self):
        out = run(runner.run_tool("measure_recommendation_share", {"panel": self.rows, "runs": self.runs,
                                                                    "brand": {"name": "Acme"}}))
        self.assertIn("headline", out)
        with self.assertRaisesRegex(ValueError, "saved results"):
            run(runner.run_tool("measure_recommendation_share", {"project": "acme-site", "brand": {"name": "Acme"}}))

    def test_change_stops_being_due_once_a_round_is_measured_after_its_recheck_date(self):
        today = dt.date.today()
        day = lambda n: (today - dt.timedelta(days=n)).isoformat()  # noqa: E731
        rows = panel()
        exp = [{"action": "Joined listicles", "mechanism": "listicle", "date": day(50),
                "target_prompt_ids": "p001,p002,p003,p004"}]
        hits = {"p001", "p002", "p003", "p004"}
        early = answers(rows, "baseline", day(80), set()) + answers(rows, "after", day(40), hits)
        late = answers(rows, "baseline", day(80), set()) + answers(rows, "after", day(0), hits)
        self.assertTrue(tools.measure(rows, early, "baseline", "after", exp)["due"])  # re-measured too soon
        self.assertEqual(tools.measure(rows, late, "baseline", "after", exp)["due"], [])

    def test_rounds_without_separate_dates_say_so_instead_of_blaming_the_change_date(self):
        today = dt.date.today().isoformat()
        rows = panel()
        runs_ = answers(rows, "baseline", today, set()) + answers(rows, "after", today, {"p001", "p002", "p003"})
        exp = [{"action": "Joined listicles", "mechanism": "listicle", "date": "2026-10-01",
                "target_prompt_ids": "p001,p002,p003"}]
        e = tools.measure(rows, runs_, "baseline", "after", exp)["experiments"][0]
        self.assertEqual(e["timing"], "rounds_not_separated")
        self.assertNotIn("on or before", e["note"])

    def test_experiments_default_to_today_and_a_thirty_day_recheck(self):
        row = tools.normalise_experiments([{"action": "Added FAQ", "target_prompt_ids": "p001"}])[0]
        today = dt.date.today()
        self.assertEqual(row["date"], today.isoformat())
        self.assertEqual(row["recheck_after"], (today + dt.timedelta(days=30)).isoformat())

    def test_a_given_date_moves_the_recheck_with_it(self):
        row = tools.normalise_experiments([{"action": "x", "date": "2026-11-15", "target_prompt_ids": "p001"}])[0]
        self.assertEqual(row["recheck_after"], "2026-12-15")

    def test_an_explicit_recheck_date_is_kept_and_a_bad_date_does_not_crash(self):
        keep = tools.normalise_experiments([{"action": "x", "date": "2026-11-15", "recheck_after": "2027-01-01"}])[0]
        self.assertEqual(keep["recheck_after"], "2027-01-01")
        odd = tools.normalise_experiments([{"action": "x", "date": "last tuesday"}])[0]
        self.assertTrue(odd["recheck_after"])  # something sensible, never a crash


class AuditNext(ServerCase):
    def test_audit_result_has_a_short_next_hint(self):
        out = tools.run_audit(self.base, 5)
        self.assertTrue(out["next"])
        self.assertLessEqual(words(out["next"]), MAX_NEXT_WORDS)
        self.assertIn("next_steps", out["next"])


class SaveNext(unittest.TestCase):
    def setUp(self):
        stg.set_backend(stg.MemoryBackend())
        self.rows, self.runs = two_rounds()

    def tearDown(self):
        stg.set_backend(None)

    def test_save_result_has_a_short_next_hint_and_warnings(self):
        out = run(runner.run_tool("save_results", {"project": "acme-site", "runs": self.runs[:len(self.runs) // 2],
                                                    "panel": self.rows, "brand": {"name": "Acme"}}))
        self.assertLessEqual(words(out["next"]), MAX_NEXT_WORDS)
        self.assertIn("30 days", out["next"])
        self.assertEqual(out["warnings"], [])

    def test_saving_an_audit_only_also_gets_a_hint(self):
        audit = {"site": "https://acme.com", "health_score": 70, "subscores": {}, "counts": {}, "pages_checked": 3,
                 "problems": [], "passed": [], "limits": ""}
        out = run(runner.run_tool("save_results", {"project": "acme-site", "audit": audit}))
        self.assertTrue(out["next"])
        self.assertLessEqual(words(out["next"]), MAX_NEXT_WORDS)

    def test_saved_project_measure_has_a_hint_and_new_fields(self):
        run(runner.run_tool("save_results", {"project": "acme-site", "runs": self.runs, "panel": self.rows}))
        out = run(runner.run_tool("measure_recommendation_share", {"project": "acme-site"}))
        self.assertIn("30 days", out["next"])
        self.assertIn("headline", out)
        self.assertIn("reputation_share", out["summary"]["all"])


class StepRules(unittest.TestCase):
    def test_snippet_check_has_a_plain_step(self):
        audit = {"problems": [{"level": "warn", "check": "Snippets allowed (no nosnippet / max-snippet:0)",
                               "detail": "2 pages block snippets"}]}
        step = tools.next_steps(audit)["steps"][0]
        self.assertEqual(step["step"], "Let search and AI quote your pages")
        self.assertNotIn("Look into", step["step"])


def model_fields(name: str) -> set[str]:
    with open(os.path.join(ROOT, "connector", "models.py"), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == name)
    return {n.target.id for n in cls.body if isinstance(n, ast.AnnAssign)}


class ModelFields(unittest.TestCase):
    def test_result_models_declare_the_new_fields(self):
        self.assertLessEqual({"headline", "smallest_change_points", "next"}, model_fields("MeasureResult"))
        self.assertLessEqual({"next", "warnings"}, model_fields("SaveResult"))
        self.assertIn("next", model_fields("AuditResult"))
        self.assertIn("aliases", model_fields("BrandInfo"))

    def test_descriptions_name_the_new_verdicts_and_the_reputation_check(self):
        with open(os.path.join(ROOT, "connector", "models.py"), encoding="utf-8") as fh:
            text = fh.read()
        for phrase in ("too early to tell", "engines moved", "not comparable", "reputation", "metric_version",
                       "timing", "confounded_with"):
            self.assertIn(phrase, text, phrase)


@unittest.skipUnless(HAVE_PYDANTIC, "pydantic is not installed")
class ModelsAcceptTheResults(unittest.TestCase):
    def test_measure_result_keeps_the_new_fields(self):
        import models as m
        rows, runs = two_rounds()
        rep = tools.measure(rows, runs, "baseline", "after")
        out = m.MeasureResult(**rep).model_dump()
        self.assertTrue(out["headline"])
        self.assertTrue(out["next"])
        self.assertIn("reputation_share", out["summary"]["all"])
        self.assertIsNotNone(out["smallest_change_points"])

    def test_save_and_audit_results_keep_next(self):
        import models as m
        save = m.SaveResult(project="acme-site", snapshots_saved={}, panel_prompts=1, snapshots_in_project=[], brand={},
                            stored_in="x", next="Re-check in 30 days.")
        self.assertEqual(save.warnings, [])
        self.assertEqual(save.next, "Re-check in 30 days.")


if __name__ == "__main__":
    unittest.main()
