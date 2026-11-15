import unittest

from connector import insights


def run(pid, platform="chatgpt", snap="r1", cited="", comps="", mentioned=False, recommended=False, linked=False):
    return {"prompt_id": pid, "platform": platform, "snapshot": snap, "cited_domains": cited,
            "competitors": comps, "mentioned": mentioned, "recommended": recommended, "cited": linked}


PANEL = [
    {"prompt_id": "q1", "prompt": "best payroll software", "type": "consideration", "topic": "payroll"},
    {"prompt_id": "q2", "prompt": "payroll tool for startups", "type": "awareness", "topic": "payroll"},
    {"prompt_id": "c1", "prompt": "best pizza oven", "type": "control", "topic": ""},
]


class CitationGap(unittest.TestCase):
    def test_site_cited_for_rivals_without_brand_is_listed(self):
        runs = [run("q1", cited="g2.com;mysite.com", comps="rival"),
                run("q2", cited="https://www.g2.com/x", comps="rival")]
        out = insights.citation_gap(runs, PANEL, {"domain": "mysite.com"}, "r1")
        self.assertEqual([s["site"] for s in out["sites"]], ["g2.com"])
        self.assertEqual(out["sites"][0]["answers_for_rivals_without_you"], 2)
        self.assertEqual(out["sites"][0]["rivals_named"], ["rival"])

    def test_own_site_and_everywhere_sites_are_left_out(self):
        runs = [run("q1", cited="mysite.com;wikipedia.org", comps="rival"),
                run("q2", cited="blog.mysite.com;en.wikipedia.org", comps="rival")]
        out = insights.citation_gap(runs, PANEL, {"domain": "mysite.com"}, "r1")
        self.assertEqual(out["sites"], [])

    def test_answers_that_name_the_brand_do_not_count_as_gap(self):
        runs = [run("q1", cited="g2.com", comps="rival", mentioned=True),
                run("q2", cited="g2.com", comps="rival", recommended=True)]
        out = insights.citation_gap(runs, PANEL, None, "r1")
        self.assertEqual(out["sites"], [])

    def test_no_sources_says_so(self):
        out = insights.citation_gap([run("q1", comps="rival")], PANEL, None, "r1")
        self.assertEqual(out["answers_with_sources"], 0)
        self.assertIn("no source sites", out["note"])

    def test_control_questions_ignored_and_empty_round_is_none(self):
        runs = [run("c1", cited="g2.com", comps="rival"), run("c1", cited="g2.com", comps="rival")]
        self.assertIsNone(insights.citation_gap(runs, PANEL, None, "r1"))
        self.assertIsNone(insights.citation_gap(runs, PANEL, None, None))

    def test_latest_round_follows_order(self):
        runs = [run("q1", snap="a"), run("q1", snap="b")]
        self.assertEqual(insights.latest_round(runs, ["a", "b", "c"]), "b")
        self.assertIsNone(insights.latest_round([], ["a"]))


class Proof(unittest.TestCase):
    def test_breakdown_counts_per_engine(self):
        runs = [run("q1", "chatgpt", recommended=True, mentioned=True, linked=True),
                run("q1", "google", mentioned=True), run("q2", "chatgpt")]
        rows = insights.question_breakdown(runs, PANEL, "r1")
        q1 = next(r for r in rows if r["prompt_id"] == "q1")
        self.assertEqual((q1["answers"], q1["recommended"]), (2, 1))
        self.assertEqual(q1["engines"]["chatgpt"]["linked"], 1)
        self.assertEqual(q1["engines"]["google"]["named"], 1)

    def test_proof_links_only_valid_dataset_ids(self):
        out = insights.proof([run("q1")], PANEL, "r1", ["abcDEF123456", "../bad id"])
        self.assertEqual([s["dataset_id"] for s in out["raw_answers"]], ["abcDEF123456"])
        self.assertTrue(out["raw_answers"][0]["open"].endswith("abcDEF123456"))

    def test_proof_without_dataset_explains_missing_link(self):
        out = insights.proof([run("q1")], PANEL, "r1", None)
        self.assertEqual(out["raw_answers"], [])
        self.assertIn("no link", out["how_to_check"])

    def test_proof_none_without_answers(self):
        self.assertIsNone(insights.proof([], PANEL, "r1", None))


WORDS = ["alpha", "bravo", "cobalt", "delta", "ember", "fjord", "garnet", "harbor", "indigo", "juniper",
         "kestrel", "lantern", "meadow", "nebula", "orchid", "pewter", "quartz", "russet", "saffron", "tundra",
         "umber", "velvet", "willow", "xenon", "yarrow", "zephyr"]


def panel(buying=20, control=5, topic="a"):
    rows = [{"prompt_id": f"b{i}", "prompt": f"which {WORDS[i]} vendor suits a {WORDS[-1 - i]} team best",
             "type": "consideration", "topic": topic} for i in range(buying)]
    rows += [{"prompt_id": f"c{i}", "prompt": f"how do I cook {WORDS[i + 5]} rice for {WORDS[i]} dinner",
              "type": "control"} for i in range(control)]
    return rows


class ReviewPanel(unittest.TestCase):
    def test_small_panel_has_problems(self):
        out = insights.review_panel(PANEL)
        self.assertFalse(out["ready_to_freeze"])
        self.assertEqual(len(out["problems"]), 2)

    def test_good_panel_is_ready_and_flags_small_topics(self):
        out = insights.review_panel(panel())
        self.assertTrue(out["ready_to_freeze"])
        self.assertTrue(out["topics"][0]["can_judge_one_change"])
        small = insights.review_panel(panel(topic=""))
        self.assertTrue(any("no topic" in a for a in small["advice"]))

    def test_near_duplicates_are_flagged(self):
        rows = panel()
        rows.append({"prompt_id": "dup", "prompt": rows[0]["prompt"] + "?", "type": "consideration", "topic": "a"})
        out = insights.review_panel(rows)
        self.assertTrue(any("Near-identical" in p for p in out["problems"]))
        self.assertFalse(out["ready_to_freeze"])


class Ranks(unittest.TestCase):
    def test_clean_accepts_null_position_and_normalises(self):
        rows = insights.clean_ranks([{"keyword": " Payroll  Software ", "position": 7, "country": "US"},
                                     {"keyword": "hr tool", "position": None, "engine": "Bing"}])
        self.assertEqual(rows[0]["keyword"], "payroll software")
        self.assertEqual((rows[0]["engine"], rows[0]["country"]), ("google", "us"))
        self.assertIsNone(rows[1]["position"])

    def test_clean_rejects_bad_rows(self):
        bad = [None, [], "x", [{"keyword": ""}], [{"keyword": "a", "position": 0}], [{"keyword": "a", "position": True}],
               [{"keyword": "a", "position": float("nan")}], [{"keyword": "a", "engine": "yahoo"}],
               [{"keyword": "a"}, {"keyword": "A "}], [{"keyword": "k%d" % i} for i in range(501)]]
        for value in bad:
            with self.assertRaises(ValueError, msg=repr(value)[:60]):
                insights.clean_ranks(value)

    def test_summary_and_changes(self):
        old = insights.summarise_ranks(insights.clean_ranks(
            [{"keyword": "a", "position": 12}, {"keyword": "b", "position": 3}, {"keyword": "c", "position": None}]))
        new = insights.summarise_ranks(insights.clean_ranks(
            [{"keyword": "a", "position": 8}, {"keyword": "b", "position": 5}, {"keyword": "d", "position": 1}]))
        self.assertEqual((new["top_3"], new["top_10"], new["not_found"]), (1, 3, 0))
        moves = {r["keyword"]: r for r in insights.rank_changes([old, new])}
        self.assertEqual(moves["a"]["moved_up_by"], 4)
        self.assertEqual(moves["b"]["moved_up_by"], -2)
        self.assertFalse(moves["d"]["checked_before"])
        self.assertEqual(insights.rank_changes([]), [])


if __name__ == "__main__":
    unittest.main()


class ReviewFixes(unittest.TestCase):
    def test_fractional_position_rejected(self):
        with self.assertRaises(ValueError):
            insights.clean_ranks([{"keyword": "a", "position": 7.5}])

    def test_proof_ignores_non_string_dataset_id(self):
        out = insights.proof([run("q1")], PANEL, "r1", [123456, "abcDEF123456"])
        self.assertEqual(len(out["raw_answers"]), 1)


class SignalHardening(unittest.TestCase):
    def test_long_line_is_fast_and_skipped(self):
        import time
        from connector import signals
        line = '1.2.3.4 - - [10/Nov/2026:13:55:36 +0000] "GET /' + "a" * 150000
        good = ('1.2.3.4 - - [10/Nov/2026:13:55:36 +0000] "GET /pricing HTTP/1.1" 200 5 "-" "GPTBot/1.0"')
        start = time.time()
        out = signals.summarise_bot_log(line + "\n" + good)
        self.assertLess(time.time() - start, 2)
        self.assertEqual(out["bots"][0]["bot"], "GPTBot")

    def test_paths_with_ids_are_not_kept(self):
        from connector import signals
        for bad in ("/reset/TOKEN123", "/unsubscribe/a@b.co", "/u/john/x/y/z", "/invoice/20491"):
            self.assertEqual(signals._clean_path(bad), "(other)")
        self.assertEqual(signals._clean_path("/pricing?x=1"), "/pricing")

    def test_huge_numbers_do_not_crash(self):
        from connector import signals
        rows = [{"source": "chatgpt.com", "sessions": "1" * 400}, {"source": "chatgpt.com", "sessions": 10 ** 400}]
        self.assertEqual(signals.summarise_traffic(rows)["ai_visits"], 0)
        with self.assertRaises(ValueError):
            signals.parse_traffic_csv("a,b\n" + "x" * 200000 + ",1")

    def test_bom_semicolon_and_locale_numbers(self):
        from connector import signals
        rows = signals.parse_traffic_csv("﻿Session source;Sessions\nchatgpt.com;1.204\ngoogle;50")
        out = signals.summarise_traffic(rows)
        self.assertEqual(out["ai_visits"], 1204)
        self.assertEqual(signals._number("1.204,5"), 1204.5)
        self.assertEqual(signals.ai_source("ChatGPT"), "ChatGPT")


class SameDayRanks(unittest.IsolatedAsyncioTestCase):
    async def test_second_save_adds_rows(self):
        import os, sys
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "connector"))
        import history as hist
        import storage as stg
        stg.set_backend(stg.MemoryBackend())
        try:
            first = insights.summarise_ranks(insights.clean_ranks([{"keyword": "a", "engine": "google", "position": 3}]))
            second = insights.summarise_ranks(insights.clean_ranks([{"keyword": "b", "engine": "bing", "position": 5}]))
            await hist.save_signal("rank-merge-test", "ranks", first)
            kept = await hist.save_signal("rank-merge-test", "ranks", second)
            self.assertEqual({r["keyword"] for r in kept["record"]["rows"]}, {"a", "b"})
        finally:
            stg.set_backend(None)
