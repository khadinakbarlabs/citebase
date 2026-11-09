"""Importing results from every Actor the plugin can buy answers from, not only the AI Brand Monitor.

Several of these Actors carry no `platform` field, so the importer recognises each by its own fields. Anything that
cannot be judged honestly is listed as skipped with a reason, or goes to needs_review; it is never counted silently.
"""
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "connector"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import importer  # noqa: E402

PANEL = [{"prompt_id": f"p{i}", "prompt": f"question {i}", "type": t}
         for i, t in enumerate(["awareness", "awareness", "consideration", "consideration", "control", "control"], 1)]
BRAND = {"name": "Acme", "domain": "acme.com", "competitors": ["Rival"]}


def aio(query="question 1", matched=True, position=2, present=True, **extra):
    item = {"query": query, "aioPresent": present,
            "brandMatch": {"matched": matched, "position": position if matched else None},
            "sources": [{"position": 1, "domain": "rival.example", "url": "https://rival.example/x", "title": "Rival guide"},
                        {"position": 2, "domain": "www.acme.com", "url": "https://www.acme.com/p", "title": "Acme pricing"}],
            "countryCode": "us", "languageCode": "en", "device": "desktop", "source": "camoufox",
            "scrapedAt": "2026-11-07T10:00:00Z", "warnings": []}
    return {**item, **extra}


def aimode(query="question 2", text="Acme is one option. Rival is another.", urls=("https://acme.com/a",), **extra):
    item = {"query": query, "responseText": text,
            "citations": [{"position": n, "title": f"t{n}", "url": u, "domain": u.split("/")[2], "source": "web",
                           "snippet": "s"} for n, u in enumerate(urls, 1)],
            "fetchedAt": "2026-11-07T11:00:00Z", "source": "serpapi", "warnings": [], "searchId": "s-1"}
    return {**item, **extra}


def tracker(query="question 1", platform="chatgpt", cited=True, **extra):
    item = {"query": query, "platform": platform, "domain_cited": cited, "citation_rank": 2 if cited else None,
            "cited_pages": ["https://www.acme.com/a"] if cited else [], "competing_domains": ["rival.example"],
            "total_sources_cited": 5, "checked_at": "2026-11-07T10:00:00Z", "model_used": "gpt-4o"}
    return {**item, **extra}


def citations_tracker(query="question 1", platform="perplexity", evidence="provider_citation", **extra):
    item = {"query": query, "platform": platform, "trackedDomainCited": True,
            "trackedCitationUrls": ["https://acme.com/a"],
            "citations": [{"url": "https://acme.com/a", "evidenceType": evidence, "sourceDomains": ["acme.com"]},
                          {"url": "https://rival.example/b", "evidenceType": "provider_citation",
                           "sourceDomains": ["rival.example"]}],
            "checkedAt": "2026-11-07T12:00:00Z", "modelUsed": "sonar"}
    return {**item, **extra}


def convert(*items, brand=BRAND, context=None):
    return importer.convert(list(items), PANEL, "baseline", brand=brand, context=context)


class BrandMonitorProvenanceTests(unittest.TestCase):
    def test_model_and_time_are_copied_and_the_judgement_is_unchanged(self):
        item = {"query": "question 1", "platform": "perplexity", "brand_mentioned": True, "sentiment": "positive",
                "model_used": "perplexity/sonar", "scraped_at": "2026-11-07T10:00:00Z"}
        row = convert(item)["runs"][0]
        self.assertTrue(row["recommended"])
        self.assertEqual(row["engine_version"], "perplexity/sonar")
        self.assertEqual(row["answered_at"], "2026-11-07T10:00:00Z")
        self.assertEqual(row["date"], "2026-11-07")

    def test_an_item_without_a_brand_field_but_with_a_platform_is_still_a_brand_monitor_row(self):
        out = convert({"query": "question 1", "platform": "chatgpt"})
        self.assertEqual(out["runs"][0]["platform"], "chatgpt")
        self.assertFalse(out["runs"][0]["mentioned"])

    def test_nothing_changes_without_a_brand(self):
        item = {"query": "question 1", "platform": "chatgpt", "brand_mentioned": True, "sentiment": "positive"}
        self.assertTrue(convert(item, brand=None)["runs"][0]["recommended"])


class AiOverviewsTests(unittest.TestCase):
    def test_a_brand_in_the_sources_is_cited_not_recommended(self):
        out = convert(aio())
        row = out["runs"][0]
        self.assertEqual(row["platform"], "google-aio")
        self.assertTrue(row["cited"])
        self.assertFalse(row["recommended"])  # no wording to judge, and a position is not a recommendation
        self.assertEqual(row["position"], 2)
        self.assertEqual(row["cited_domains"], "acme.com;rival.example")
        self.assertEqual(row["competitors"], "Rival")
        self.assertEqual(out["detected"], {"google-ai-overviews": 1})

    def test_an_early_position_alone_never_makes_it_recommended(self):
        out = convert(aio(position=1, sources=[{"position": 1, "domain": "acme.com", "url": "https://acme.com/", "title": "Acme"}]))
        self.assertFalse(out["runs"][0]["recommended"])
        self.assertTrue(out["runs"][0]["cited"])

    def test_it_goes_to_review_with_a_reason(self):
        out = convert(aio())
        review = out["needs_review"][0]
        self.assertEqual((review["prompt_id"], review["platform"]), ("p1", "google-aio"))
        self.assertIn("no wording", review["reason"])
        self.assertFalse(review["auto_recommended"])
        self.assertTrue(review["context"])
        self.assertEqual(out["summary"]["needs_review"], 1)

    def test_provenance_is_copied_from_the_item(self):
        row = convert(aio())["runs"][0]
        self.assertEqual((row["country"], row["language"], row["device"], row["source"]), ("US", "en", "desktop", "camoufox"))
        self.assertEqual(row["answered_at"], "2026-11-07T10:00:00Z")
        self.assertEqual(row["engine_version"], "")  # this Actor names no model

    def test_no_overview_for_a_question_is_a_not_recommended_row_and_is_said(self):
        out = convert(aio(matched=False, present=False, sources=[]))
        row = out["runs"][0]
        self.assertFalse(row["mentioned"] or row["cited"] or row["recommended"])
        self.assertEqual(out["needs_review"], [])
        self.assertTrue(any("no Google AI Overview" in n for n in out["notes"]), out["notes"])

    def test_not_matched_is_not_cited(self):
        out = convert(aio(matched=False, sources=[{"position": 1, "domain": "rival.example", "url": "https://rival.example/x",
                                                   "title": "Rival"}]))
        self.assertFalse(out["runs"][0]["cited"])
        self.assertEqual(out["needs_review"], [])

    def test_a_match_that_is_not_in_a_listed_source_is_mentioned_not_cited(self):
        out = convert(aio(matched=True, position=9, sources=[{"position": 1, "domain": "rival.example",
                                                              "url": "https://rival.example/x", "title": "Rival"}]))
        row = out["runs"][0]
        self.assertTrue(row["mentioned"])
        self.assertFalse(row["cited"])
        self.assertEqual(len(out["needs_review"]), 1)

    def test_without_a_brand_match_field_the_brand_domain_decides(self):
        item = aio()
        del item["brandMatch"]
        self.assertTrue(convert(item)["runs"][0]["cited"])

    def test_without_a_brand_match_field_and_without_a_brand_it_cannot_be_judged(self):
        item = aio()
        del item["brandMatch"]
        out = convert(item, aio(query="question 2"), brand=None)
        self.assertEqual(len(out["runs"]), 1)  # the item that carries its own brand match still counts
        self.assertEqual(out["skipped"][0]["reason"], "needs_brand")

    def test_repeat_numbers_count_per_question_and_engine(self):
        out = convert(aio(), aio(), aio(query="question 2"))
        self.assertEqual([(r["prompt_id"], r["repeat"]) for r in out["runs"]], [("p1", 1), ("p1", 2), ("p2", 1)])


class AiModeTests(unittest.TestCase):
    def test_the_brand_named_in_the_text_and_in_a_citation(self):
        out = convert(aimode())
        row = out["runs"][0]
        self.assertEqual(row["platform"], "google-aimode")
        self.assertTrue(row["mentioned"])
        self.assertTrue(row["cited"])
        self.assertFalse(row["recommended"])
        self.assertEqual(row["competitors"], "Rival")
        self.assertEqual(row["position"], 1)
        self.assertEqual(row["source"], "serpapi")
        self.assertEqual(row["answered_at"], "2026-11-07T11:00:00Z")
        self.assertEqual(out["needs_review"][0]["platform"], "google-aimode")
        self.assertIn("Acme is one option", out["needs_review"][0]["context"])

    def test_not_named_and_not_cited_is_a_plain_miss(self):
        out = convert(aimode(text="Rival and Other are popular.", urls=("https://rival.example/a",)))
        row = out["runs"][0]
        self.assertFalse(row["mentioned"] or row["cited"] or row["recommended"])
        self.assertEqual(out["needs_review"], [])

    def test_a_word_inside_another_word_is_not_a_mention(self):
        out = convert(aimode(text="Acmeology is a field of study.", urls=("https://rival.example/a",)))
        self.assertFalse(out["runs"][0]["mentioned"])

    def test_the_brand_domain_in_the_text_counts_as_a_mention(self):
        out = convert(aimode(text="See acme.com for details.", urls=("https://rival.example/a",)))
        self.assertTrue(out["runs"][0]["mentioned"])

    def test_without_the_brand_it_cannot_be_judged_and_says_so(self):
        with self.assertRaises(ValueError) as caught:
            convert(aimode(), aimode(query="question 3"), brand=None)
        self.assertIn("brand", str(caught.exception))
        out = convert(aimode(), aimode(query="question 3"), tracker(), brand=None)
        self.assertEqual(len(out["runs"]), 1)
        self.assertEqual(out["skipped"][0]["reason"], "needs_brand")
        self.assertEqual(out["skipped"][0]["count"], 2)
        self.assertIn("brand", out["skipped"][0]["why"])

    def test_the_run_settings_stamp_what_the_actor_does_not_echo(self):
        out = convert(aimode(), context={"country": "us", "language": "EN", "device": "Mobile", "location": "Austin, Texas"})
        row = out["runs"][0]
        self.assertEqual((row["country"], row["language"], row["device"]), ("US", "en", "mobile"))
        self.assertEqual(out["context"], {"country": "us", "language": "EN", "device": "Mobile", "location": "Austin, Texas"})
        self.assertTrue(any("location" in n for n in out["notes"]), out["notes"])  # there is no field for it: say so

    def test_the_actors_own_value_wins_over_the_run_settings(self):
        out = convert(aio(), context={"country": "de"})
        self.assertEqual(out["runs"][0]["country"], "US")
        self.assertTrue(any("country" in n and "results" in n for n in out["notes"]), out["notes"])

    def test_actor_warnings_are_passed_on(self):
        out = convert(aimode(warnings=["fell back to a second route"]))
        self.assertTrue(any("fell back" in n for n in out["notes"]), out["notes"])


class VisibilityTrackerTests(unittest.TestCase):
    def test_a_cited_domain_is_cited_not_recommended(self):
        out = convert(tracker())
        row = out["runs"][0]
        self.assertEqual(row["platform"], "chatgpt")
        self.assertTrue(row["cited"])
        self.assertFalse(row["recommended"])
        self.assertFalse(row["mentioned"])  # being a source is not the same as being named in the answer
        self.assertEqual(row["position"], 2)
        self.assertEqual(row["engine_version"], "gpt-4o")
        self.assertEqual(row["answered_at"], "2026-11-07T10:00:00Z")
        self.assertEqual(row["cited_domains"], "acme.com;rival.example")
        self.assertEqual(row["competitors"], "rival.example")
        self.assertEqual(out["detected"], {"ai-search-visibility-tracker": 1})
        self.assertEqual(len(out["needs_review"]), 1)

    def test_not_cited_is_a_plain_miss(self):
        out = convert(tracker(cited=False))
        self.assertFalse(out["runs"][0]["cited"])
        self.assertEqual(out["needs_review"], [])

    def test_it_needs_no_brand(self):
        self.assertEqual(len(convert(tracker(), brand=None)["runs"]), 1)

    def test_diagnostic_rows_are_counted_as_skipped_with_their_message(self):
        diag = {"platform": "diagnostic", "diagnostic_status": "error", "diagnostic_message": "ChatGPT could not be reached"}
        out = convert(tracker(), diag, diag)
        self.assertEqual(len(out["runs"]), 1)
        skipped = {s["reason"]: s for s in out["skipped"]}
        self.assertEqual(skipped["diagnostic"]["count"], 2)
        self.assertIn("could not be reached", skipped["diagnostic"]["example"])
        self.assertEqual(out["summary"]["skipped"], 2)

    def test_competing_domains_may_be_objects(self):
        out = convert(tracker(competing_domains=[{"domain": "rival.example", "count": 2}, "other.example"]))
        self.assertEqual(out["runs"][0]["competitors"], "rival.example;other.example")


class CitationsTrackerTests(unittest.TestCase):
    def test_a_listed_citation_is_cited(self):
        out = convert(citations_tracker())
        row = out["runs"][0]
        self.assertEqual(row["platform"], "perplexity")
        self.assertTrue(row["cited"])
        self.assertFalse(row["recommended"])
        self.assertEqual(row["engine_version"], "sonar")
        self.assertEqual(row["answered_at"], "2026-11-07T12:00:00Z")
        self.assertEqual(row["cited_domains"], "acme.com;rival.example")
        self.assertEqual(out["detected"], {"ai-citations-tracker": 1})

    def test_a_link_only_inside_the_answer_text_is_cited_but_flagged(self):
        out = convert(citations_tracker(evidence="answer_link"))
        self.assertTrue(out["runs"][0]["cited"])
        self.assertIn("link inside the answer", out["needs_review"][0]["reason"])

    def test_not_tracked_domain_cited_is_a_miss(self):
        out = convert(citations_tracker(trackedDomainCited=False, trackedCitationUrls=[]))
        self.assertFalse(out["runs"][0]["cited"])

    def test_an_item_that_does_not_say_which_ai_answered_is_skipped_with_a_reason(self):
        item = citations_tracker()
        del item["platform"]
        out = convert(citations_tracker(query="question 2"), item)
        self.assertEqual(len(out["runs"]), 1)
        self.assertEqual(out["skipped"][0]["reason"], "no_engine")


class SkippedAndErrorTests(unittest.TestCase):
    def test_every_skip_has_a_count_a_reason_and_plain_words(self):
        diag = {"platform": "diagnostic", "diagnostic_status": "error", "diagnostic_message": "blocked"}
        out = convert(tracker(), diag, {"nothing": "useful"}, "not an item", tracker(query="not in the panel"),
                      {"platform": "chatgpt"})
        skipped = {s["reason"]: s for s in out["skipped"]}
        self.assertEqual(set(skipped), {"diagnostic", "unknown_shape", "not_an_item", "no_question_text", "no_matching_question"})
        for entry in skipped.values():
            self.assertTrue(entry["count"] >= 1 and entry["why"])
        self.assertEqual(skipped["no_matching_question"]["example"], "not in the panel")
        self.assertEqual(out["unmatched_queries"], ["not in the panel"])
        self.assertEqual(out["summary"]["skipped"], sum(s["count"] for s in out["skipped"]))

    def test_all_diagnostic_rows_do_not_blame_the_question_text(self):
        diag = {"platform": "diagnostic", "diagnostic_status": "error", "diagnostic_message": "blocked"}
        with self.assertRaises(ValueError) as caught:
            convert(diag, diag)
        message = str(caught.exception)
        self.assertIn("diagnostic", message)
        self.assertIn("blocked", message)
        self.assertNotIn("same question text", message)
        self.assertNotIn("matched a question", message)

    def test_unknown_shapes_say_they_were_not_recognised(self):
        with self.assertRaises(ValueError) as caught:
            convert({"hello": "world"}, {"foo": 1})
        message = str(caught.exception)
        self.assertIn("not recognise", message)
        self.assertNotIn("same question text", message)

    def test_questions_not_in_the_panel_still_get_the_question_text_hint(self):
        with self.assertRaises(ValueError) as caught:
            convert({"query": "zzz", "platform": "chatgpt"})
        self.assertIn("same question text", str(caught.exception))
        self.assertIn("zzz", str(caught.exception))

    def test_a_mix_of_causes_names_each_one(self):
        diag = {"platform": "diagnostic", "diagnostic_status": "error", "diagnostic_message": "blocked"}
        with self.assertRaises(ValueError) as caught:
            convert(diag, {"foo": 1}, tracker(query="not in the panel"))
        message = str(caught.exception)
        for part in ("diagnostic", "not recognise", "not in the panel", "same question text"):
            self.assertIn(part, message)

    def test_empty_and_non_list_input_are_refused_plainly(self):
        for bad in ([], None, "text", {"a": 1}):
            with self.assertRaises(ValueError):
                importer.convert(bad, PANEL, "baseline")

    def test_mixed_shapes_in_one_import_all_land(self):
        out = convert(tracker(), aio(query="question 2"), aimode(query="question 3"), citations_tracker(query="question 4"),
                      {"query": "question 1", "platform": "gemini", "brand_mentioned": True, "sentiment": "positive"})
        self.assertEqual({r["platform"] for r in out["runs"]}, {"chatgpt", "google-aio", "google-aimode", "perplexity", "gemini"})
        self.assertEqual(sum(out["detected"].values()), 5)
        self.assertEqual(out["summary"]["rows"], 5)
        self.assertEqual(out["summary"]["skipped"], 0)

    def test_the_review_list_is_still_capped_and_its_total_is_true(self):
        items = [aio() for _ in range(40)]
        out = convert(*items)
        self.assertEqual(len(out["needs_review"]), importer.MAX_REVIEW)
        self.assertEqual(out["summary"]["needs_review"], 40)

    def test_row_fields_fit_the_save_format(self):
        """Every converted row can go straight into save_results."""
        import tools
        rows = convert(tracker(), aio(query="question 2"), aimode(query="question 3"))["runs"]
        stamped = [dict(r, snapshot="baseline") for r in rows]
        saved = tools.normalise_runs(stamped, {p["prompt_id"]: p for p in PANEL})
        self.assertEqual(len(saved), 3)


if __name__ == "__main__":
    unittest.main()
