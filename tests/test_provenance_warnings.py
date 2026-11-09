"""The report warns when two rounds were not asked under the same conditions (model, country, language, device, path).

It only warns: a difference never turns the verdict into 'not comparable'. Old rounds that did not record a field
get a plain 'not recorded' note instead of a guess.
"""
import asyncio
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
import storage as stg  # noqa: E402

BASE_DATE, CUR_DATE = "2026-11-01", "2026-12-01"


def make_panel(n_disc=24, n_ctrl=5):
    return ([{"prompt_id": f"p{i:03d}", "prompt": f"best tool number {i}", "type": "consideration"}
             for i in range(1, n_disc + 1)]
            + [{"prompt_id": f"c{i:03d}", "prompt": f"unrelated question {i}", "type": "control"}
               for i in range(1, n_ctrl + 1)])


def make_runs(panel, snapshot, date, prov=None, platforms=("chatgpt", "perplexity"), repeats=3):
    """prov maps platform -> provenance fields (or a list of dicts to alternate between, for a mixed round)."""
    prov = prov or {}
    out = []
    for i, p in enumerate(panel):
        for platform in platforms:
            for r in range(1, repeats + 1):
                fields = prov.get(platform, {})
                if isinstance(fields, list):
                    fields = fields[i % len(fields)]
                out.append({"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": platform, "repeat": r,
                            "mentioned": int(p["prompt_id"] == "p001"), "cited": 0,
                            "recommended": int(p["prompt_id"] == "p001"), "date": date,
                            "metric_version": cl.METRIC_VERSION, **fields})
    return out


def report(panel, runs, base="a", cur="b"):
    with tempfile.TemporaryDirectory() as tmp:
        cl.write_csv(os.path.join(tmp, "panel.csv"), cl.PANEL_COLS, panel)
        cl.write_csv(os.path.join(tmp, "runs.csv"), cl.RUN_COLS, runs)
        cl.write_csv(os.path.join(tmp, "experiments.csv"), cl.EXP_COLS, [])
        return cl.build_report(SimpleNamespace(dir=tmp, baseline=base, current=cur, json=True))


def two_rounds(base_prov, cur_prov, **kw):
    panel = make_panel()
    runs = make_runs(panel, "a", BASE_DATE, base_prov, **kw) + make_runs(panel, "b", CUR_DATE, cur_prov, **kw)
    return report(panel, runs)


def about(rep, *words):
    return [w for w in rep["warnings"] if all(word in w for word in words)]


class RoundContextTests(unittest.TestCase):
    def setUp(self):
        self.panel = make_panel(n_disc=2, n_ctrl=0)
        self.runs = make_runs(self.panel, "a", BASE_DATE, {"chatgpt": {"engine_version": "gpt-4o", "country": "us"}},
                              repeats=2)

    def test_context_lists_what_each_engine_recorded(self):
        ctx = cl.round_context(self.runs, "a")
        self.assertEqual(set(ctx), {"chatgpt", "perplexity"})
        chat = ctx["chatgpt"]
        self.assertEqual(chat["rows"], 4)
        self.assertEqual(chat["fields"]["engine_version"], {"values": ["gpt-4o"], "blank": 0})
        self.assertEqual(chat["fields"]["country"], {"values": ["US"], "blank": 0})  # same tidying as saved rows
        self.assertEqual(ctx["perplexity"]["fields"]["engine_version"], {"values": [], "blank": 4})

    def test_other_rounds_are_ignored(self):
        self.assertEqual(cl.round_context(self.runs, "nope"), {})

    def test_compact_form_keeps_only_recorded_values(self):
        compact = cl.compact_context(cl.round_context(self.runs, "a"))
        self.assertEqual(compact["chatgpt"], {"answers": 4, "engine_version": ["gpt-4o"], "country": ["US"]})
        self.assertEqual(compact["perplexity"], {"answers": 4})

    def test_rows_without_the_keys_at_all_count_as_not_recorded(self):
        old = [{"snapshot": "a", "prompt_id": "p001", "platform": "chatgpt", "repeat": 1}]
        self.assertEqual(cl.round_context(old, "a")["chatgpt"]["fields"]["device"], {"values": [], "blank": 1})


class SameConditionsTests(unittest.TestCase):
    def test_identical_conditions_raise_no_warning(self):
        prov = {"chatgpt": {"engine_version": "gpt-4o", "country": "US", "language": "en", "device": "desktop"}}
        rep = two_rounds(prov, prov)
        self.assertEqual(rep["warnings"], [])

    def test_differences_in_letter_case_are_not_differences(self):
        rep = two_rounds({"chatgpt": {"country": "us", "engine_version": "GPT-4o"}},
                         {"chatgpt": {"country": "US", "engine_version": "gpt-4o"}})
        self.assertEqual(rep["warnings"], [])

    def test_nothing_recorded_on_either_side_raises_no_warning(self):
        self.assertEqual(two_rounds({}, {})["warnings"], [])


class DifferenceTests(unittest.TestCase):
    def test_a_different_model_is_named_in_plain_words(self):
        rep = two_rounds({"chatgpt": {"engine_version": "gpt-4o"}}, {"chatgpt": {"engine_version": "gpt-5"}})
        hit = about(rep, "ChatGPT answers came from a different model between rounds")
        self.assertEqual(len(hit), 1, rep["warnings"])
        self.assertIn("gpt-4o", hit[0])
        self.assertIn("gpt-5", hit[0])

    def test_a_different_model_only_warns_it_never_makes_the_change_not_comparable(self):
        rep = two_rounds({"chatgpt": {"engine_version": "gpt-4o"}}, {"chatgpt": {"engine_version": "gpt-5"}})
        for change in rep["change"].values():
            self.assertTrue(change["comparable"])
            self.assertNotEqual(change["verdict"], "not comparable")

    def test_country_language_device_and_route_each_get_their_own_sentence(self):
        cases = {"country": ("US", "DE", "different country"), "language": ("en", "de", "different language"),
                 "device": ("desktop", "mobile", "different device"), "source": ("camoufox", "serpapi", "different way")}
        for field, (a, b, words) in cases.items():
            rep = two_rounds({"chatgpt": {field: a}}, {"chatgpt": {field: b}})
            hit = about(rep, "ChatGPT", words)
            self.assertEqual(len(hit), 1, (field, rep["warnings"]))
            self.assertIn(a, hit[0])
            self.assertIn(b, hit[0])

    def test_each_engine_is_judged_on_its_own(self):
        rep = two_rounds({"chatgpt": {"engine_version": "gpt-4o"}, "perplexity": {"engine_version": "sonar"}},
                         {"chatgpt": {"engine_version": "gpt-4o"}, "perplexity": {"engine_version": "sonar-pro"}})
        self.assertEqual(about(rep, "ChatGPT"), [])
        self.assertEqual(len(about(rep, "Perplexity", "different model")), 1)

    def test_an_engine_in_only_one_round_gets_no_provenance_sentence(self):
        panel = make_panel()
        runs = (make_runs(panel, "a", BASE_DATE, {"chatgpt": {"country": "US"}}, platforms=("chatgpt", "perplexity"))
                + make_runs(panel, "b", CUR_DATE, {"chatgpt": {"country": "US"}, "gemini": {"country": "DE"}},
                            platforms=("chatgpt", "gemini")))
        rep = report(panel, runs)
        self.assertEqual(about(rep, "Gemini", "country"), [])
        self.assertEqual(about(rep, "Perplexity", "country"), [])


class NotRecordedTests(unittest.TestCase):
    def test_recorded_now_but_not_in_the_baseline(self):
        rep = two_rounds({}, {"chatgpt": {"engine_version": "gpt-4o", "country": "US"}})
        hit = about(rep, "ChatGPT", "not recorded in the baseline")
        self.assertEqual(len(hit), 1, rep["warnings"])
        self.assertIn("model", hit[0])
        self.assertIn("country", hit[0])  # one sentence per engine, not one per field

    def test_recorded_in_the_baseline_but_not_now(self):
        rep = two_rounds({"chatgpt": {"engine_version": "gpt-4o"}}, {})
        self.assertEqual(len(about(rep, "ChatGPT", "not recorded in the current round")), 1, rep["warnings"])

    def test_not_recorded_is_only_a_warning(self):
        rep = two_rounds({}, {"chatgpt": {"engine_version": "gpt-4o"}})
        self.assertTrue(all(c["comparable"] for c in rep["change"].values()))


class MixedRoundTests(unittest.TestCase):
    def test_a_round_that_mixes_models_says_so(self):
        mixed = [{"engine_version": "gpt-4o"}, {"engine_version": "gpt-5"}]
        rep = two_rounds({"chatgpt": {"engine_version": "gpt-4o"}}, {"chatgpt": mixed})
        hit = about(rep, "ChatGPT", "current round", "more than one model")
        self.assertEqual(len(hit), 1, rep["warnings"])
        self.assertIn("gpt-5", hit[0])

    def test_a_round_where_only_some_answers_record_a_field_says_so(self):
        partial = [{"country": "US"}, {}]
        rep = two_rounds({"chatgpt": {"country": "US"}}, {"chatgpt": partial})
        self.assertEqual(len(about(rep, "ChatGPT", "current round", "only some")), 1, rep["warnings"])


class WarningCapTests(unittest.TestCase):
    def test_many_differences_do_not_flood_the_report(self):
        engines = ("chatgpt", "perplexity", "gemini", "claude")
        fields = {"engine_version": "a", "country": "US", "language": "en", "device": "desktop", "source": "x"}
        other = {"engine_version": "b", "country": "DE", "language": "de", "device": "mobile", "source": "y"}
        rep = two_rounds({e: fields for e in engines}, {e: other for e in engines}, platforms=engines)
        provenance = [w for w in rep["warnings"] if "between rounds" in w or "more" in w]
        self.assertLessEqual(len(provenance), 9)
        self.assertTrue(any("more" in w for w in provenance), rep["warnings"])  # says that some were left out


class ReportContextTests(unittest.TestCase):
    def test_the_report_carries_a_compact_context_for_both_rounds(self):
        rep = two_rounds({"chatgpt": {"engine_version": "gpt-4o"}}, {"chatgpt": {"engine_version": "gpt-5"}})
        self.assertEqual(rep["context"]["baseline"]["chatgpt"]["engine_version"], ["gpt-4o"])
        self.assertEqual(rep["context"]["current"]["chatgpt"]["engine_version"], ["gpt-5"])

    def test_markdown_shows_the_models_when_something_was_recorded(self):
        panel = make_panel()
        runs = make_runs(panel, "a", BASE_DATE, {"chatgpt": {"engine_version": "gpt-4o"}})
        runs += make_runs(panel, "b", CUR_DATE, {"chatgpt": {"engine_version": "gpt-5"}})
        md = cl.render(report(panel, runs))
        self.assertIn("gpt-5", md)
        self.assertIn("different model", md)

    def test_markdown_has_no_extra_section_when_nothing_was_recorded(self):
        panel = make_panel()
        runs = make_runs(panel, "a", BASE_DATE) + make_runs(panel, "b", CUR_DATE)
        self.assertNotIn("Where the answers came from", cl.render(report(panel, runs)))


class ContextWarningFunctionTests(unittest.TestCase):
    def test_labels_and_wording_can_be_chosen_by_the_caller(self):
        a = cl.round_context(make_runs(make_panel(2, 0), "a", BASE_DATE, {"chatgpt": {"country": "US"}}), "a")
        b = cl.round_context(make_runs(make_panel(2, 0), "b", CUR_DATE, {"chatgpt": {"country": "DE"}}), "b")
        out = cl.context_warnings(a, b, "saved", "new", "between the saved answers and these new ones")
        self.assertEqual(len([w for w in out if "ChatGPT" in w]), 1)
        self.assertIn("between the saved answers and these new ones", out[0])
        self.assertIn("saved: US", out[0])
        self.assertIn("new: DE", out[0])


class SavedProjectTests(unittest.TestCase):
    PANEL = make_panel(n_disc=2, n_ctrl=1)

    def setUp(self):
        stg.set_backend(stg.MemoryBackend())
        self.addCleanup(stg.set_backend, None)

    @staticmethod
    def rows(snapshot, **prov):
        return [{"snapshot": snapshot, "prompt_id": p["prompt_id"], "platform": "chatgpt", "repeat": r, "recommended": True,
                 **prov} for p in SavedProjectTests.PANEL for r in (1, 2)]

    def save(self, rows, **kw):
        return asyncio.run(hist.save_results("acme-site", rows, self.PANEL, **kw))

    def test_history_lists_each_rounds_engines_models_and_countries(self):
        self.save(self.rows("baseline", engine_version="gpt-4o", country="US"))
        history = asyncio.run(hist.history("acme-site"))
        snap = history["snapshots"][0]
        self.assertEqual(snap["engines"], ["chatgpt"])
        self.assertEqual(snap["context"]["chatgpt"], {"answers": 6, "engine_version": ["gpt-4o"], "country": ["US"]})
        self.assertIn("gpt-4o", history["markdown"])

    def test_append_with_a_different_model_warns(self):
        self.save(self.rows("baseline", engine_version="gpt-4o", country="US"))
        out = asyncio.run(hist.save_results("acme-site", self.rows("baseline", engine_version="gpt-5", country="US"),
                                            append=True))
        hit = [w for w in out["warnings"] if "different model" in w]
        self.assertEqual(len(hit), 1, out["warnings"])
        self.assertIn("gpt-4o", hit[0])
        self.assertIn("gpt-5", hit[0])
        self.assertEqual(out["snapshots_saved"]["baseline"], 12)  # it still saves: a warning is not a refusal

    def test_append_with_a_different_country_warns(self):
        self.save(self.rows("baseline", country="US"))
        out = asyncio.run(hist.save_results("acme-site", self.rows("baseline", country="DE"), append=True))
        self.assertTrue(any("different country" in w for w in out["warnings"]), out["warnings"])

    def test_append_under_the_same_conditions_is_quiet(self):
        self.save(self.rows("baseline", engine_version="gpt-4o", country="US"))
        out = asyncio.run(hist.save_results("acme-site", self.rows("baseline", engine_version="gpt-4o", country="US"),
                                            append=True))
        self.assertEqual(out["warnings"], [])

    def test_append_that_adds_or_drops_a_recorded_field_warns(self):
        self.save(self.rows("baseline"))
        out = asyncio.run(hist.save_results("acme-site", self.rows("baseline", engine_version="gpt-4o"), append=True))
        self.assertTrue(any("not recorded" in w for w in out["warnings"]), out["warnings"])

    def test_a_new_round_is_not_checked_at_save_time(self):
        self.save(self.rows("baseline", engine_version="gpt-4o"))
        out = asyncio.run(hist.save_results("acme-site", self.rows("2026-12", engine_version="gpt-5")))
        self.assertEqual(out["warnings"], [])  # measure_recommendation_share is where rounds are compared

    def test_measure_warns_across_saved_rounds(self):
        self.save(self.rows("baseline", engine_version="gpt-4o"))
        asyncio.run(hist.save_results("acme-site", [dict(r, date="2026-12-01") for r in self.rows("2026-12", engine_version="gpt-5")]))
        out = asyncio.run(hist.measure_project("acme-site"))
        self.assertTrue(any("different model" in w for w in out["warnings"]), out["warnings"])
        self.assertIn("different model", out["markdown"])


if __name__ == "__main__":
    unittest.main()
