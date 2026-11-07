"""One aggregated snippet_blocked check: nosnippet or max-snippet:0 in meta robots or X-Robots-Tag."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_site_audit_hardening import html_response  # noqa: E402

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import site_audit as sa  # noqa: E402

CHECK = "Snippets allowed (no nosnippet / max-snippet:0)"
WORDS = " ".join(f"w{i}" for i in range(400))


def page_html(robots=None):
    meta = f'<meta name="robots" content="{robots}">' if robots is not None else ""
    return (f'<!doctype html><html lang="en"><head><title>A fixture page title that is long enough</title>{meta}'
            f'</head><body><h1>Hello</h1><p>{WORDS}</p></body></html>')


def analyse(robots=None, header=None):
    res = html_response(page_html(robots))
    if header is not None:
        res["headers"]["x-robots-tag"] = header
    return sa.analyse_page("http://h/", res, ["http://h/"], "h")


def snippet_checks(pages):
    return [c for c in sa.ai_search_checks({"signals": {}}, pages) if c["check"] == CHECK]


class DetectionTests(unittest.TestCase):
    def test_blocking_directives_are_detected(self):
        for value in ("nosnippet", "noindex, nosnippet", "NOSNIPPET", "max-snippet:0", "max-snippet: 0",
                      "MAX-SNIPPET:0", "index, max-snippet:0, max-image-preview:large", "googlebot: nosnippet",
                      "max-snippet:00", "max-snippet :0"):
            self.assertTrue(sa.snippet_blocked(value), value)

    def test_allowing_or_unrelated_directives_are_not_flagged(self):
        for value in ("", "index, follow", "noindex", "max-snippet:-1", "max-snippet:50", "max-snippet:0.5x",
                      "max-snippet:10", "max-snippet:100", "nosnippets", "data-nosnippet", "max-snippet",
                      "max-image-preview:none", "unavailable_after: 2030-01-01"):
            self.assertFalse(sa.snippet_blocked(value), value)

    def test_non_string_input_is_not_flagged_and_does_not_crash(self):
        for value in (None, 0, [], {}):
            self.assertFalse(sa.snippet_blocked(value))

    def test_meta_robots_and_header_are_both_read(self):
        self.assertTrue(sa.snippet_blocked(analyse(robots="nosnippet")["robots"]))
        self.assertTrue(sa.snippet_blocked(analyse(header="max-snippet:0")["robots"]))
        self.assertTrue(sa.snippet_blocked(analyse(robots="index", header="nosnippet")["robots"]))
        self.assertFalse(sa.snippet_blocked(analyse(robots="index, follow")["robots"]))
        self.assertFalse(sa.snippet_blocked(analyse()["robots"]))


class CheckTests(unittest.TestCase):
    def test_one_aggregated_warning_listing_the_affected_pages(self):
        pages = [dict(analyse(robots="nosnippet"), url=f"http://h/{i}") for i in range(3)]
        pages.append(dict(analyse(header="max-snippet:0"), url="http://h/header"))
        pages.append(dict(analyse(robots="index"), url="http://h/fine"))
        found = snippet_checks(pages)
        self.assertEqual(len(found), 1)
        check = found[0]
        self.assertEqual(check["level"], "warn")
        self.assertEqual(check["area"], "ai-search")
        self.assertIn("4", check["detail"])
        self.assertEqual(check["weight"], 1)
        self.assertNotIn("http://h/fine", check["urls"])
        self.assertIn("http://h/header", check["urls"])

    def test_passes_when_no_page_blocks_snippets(self):
        found = snippet_checks([analyse(robots="index, follow"), analyse()])
        self.assertEqual([c["level"] for c in found], ["pass"])
        self.assertEqual(found[0]["urls"], [])

    def test_noindex_alone_is_not_a_snippet_block(self):
        self.assertEqual(snippet_checks([analyse(robots="noindex")])[0]["level"], "pass")

    def test_pages_without_the_robots_field_do_not_crash(self):
        found = snippet_checks([{"url": "http://h/x", "word_count": 10}])
        self.assertEqual(found[0]["level"], "pass")

    def test_url_list_is_capped_like_other_checks(self):
        pages = [dict(analyse(robots="nosnippet"), url=f"http://h/{i}") for i in range(40)]
        self.assertLessEqual(len(snippet_checks(pages)[0]["urls"]), 15)
        self.assertIn("40", snippet_checks(pages)[0]["detail"])

    def test_check_flows_through_score_and_lowers_the_score_a_little(self):
        def audit(robots):
            pages = [dict(analyse(robots=robots), url=f"http://h/{i}", depth=0, inlinks=1) for i in range(3)]
            return {"origin": "http://h", "crawled": 3, "pages": pages,
                    "signals": {"robots_txt": {"status": 200, "bytes": 10},
                                "ai_crawler_access": {bot: True for bot in sa.AI_CRAWLERS},
                                "http_to_https": True, "http_redirect_chain": [], "www_consolidated": True,
                                "sitemaps": [], "soft_404": False}}
        blocked, clean = audit("nosnippet"), audit("index")
        blocked["checks"], clean["checks"] = sa.score(blocked), sa.score(clean)
        self.assertEqual([c["level"] for c in blocked["checks"] if c["check"] == CHECK], ["warn"])
        self.assertEqual([c["level"] for c in clean["checks"] if c["check"] == CHECK], ["pass"])
        self.assertLess(sa.summarise(blocked["checks"])["health_score"], sa.summarise(clean["checks"])["health_score"])


if __name__ == "__main__":
    unittest.main()
