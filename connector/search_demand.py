"""What people search for, from the user's own Google Search Console export (the Performance report as CSV).

Pure functions: no network, no storage, no cost, no Google sign-in. The user exports the report and pastes the text.
Only short summaries leave this module (top questions, gaps, totals); the pasted rows are never kept.

Search Console shows what people TYPE into Google. That is the best free source of real buying questions to test in
AI assistants, and it shows where the site is seen often but clicked rarely. It does not show what AI assistants
answer, and it does not split out AI Overviews: say so when presenting it.
"""
from __future__ import annotations

import re
from typing import Any

from signals import _number, _pick, parse_traffic_csv  # noqa: F401  (same CSV rules as the analytics export)

TOP = 15
MIN_GAP_IMPRESSIONS = 50
LOW_CTR = 0.02
BAD_POSITION = 10.0
QUESTION_WORDS = ("what", "which", "who", "why", "how", "when", "where", "can", "does", "do", "is", "are", "should",
                  "best", "top", "cheapest", "affordable", "alternative", "alternatives")
BUYING_WORDS = ("best", "top", "vs", "versus", "alternative", "alternatives", "compare", "comparison", "review",
                "reviews", "price", "pricing", "cost", "cheap", "cheapest", "affordable", "software", "tool", "tools",
                "service", "services", "near me", "for small business", "for startups")
QUERY_KEYS = ("top queries", "query", "queries", "search query", "search queries", "keyword")
PAGE_KEYS = ("top pages", "page", "pages", "url")
CLICK_KEYS = ("clicks", "click")
IMPRESSION_KEYS = ("impressions", "impression")
POSITION_KEYS = ("position", "avg. position", "average position", "avg position")
CTR_KEYS = ("ctr", "click-through rate", "click through rate")


def parse_gsc_csv(text: str) -> list[dict]:
    """Rows from a pasted Search Console export (Queries or Pages tab). Same limits as the analytics export."""
    try:
        rows = parse_traffic_csv(text)
    except ValueError as err:
        raise ValueError(str(err).replace("analytics export", "Search Console export")) from None
    return rows


def _ctr(value: Any, clicks: float, impressions: float) -> float:
    """CTR as 0-1. The export writes '2.5%'; fall back to clicks / impressions when it is missing."""
    text = str(value or "").strip()
    if text.endswith("%"):
        return max(0.0, min(1.0, _number(text[:-1]) / 100))
    return clicks / impressions if impressions else 0.0


def _question_like(query: str) -> bool:
    words = query.lower().split()
    return bool(words) and (query.strip().endswith("?") or words[0] in QUESTION_WORDS
                            or any(w in BUYING_WORDS for w in words) or " vs " in f" {query.lower()} ")


def _buying_like(query: str) -> bool:
    low = f" {query.lower()} "
    return any(f" {w} " in low for w in BUYING_WORDS)


def _clean_query(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:120]


def summarise_search_demand(rows: list[dict], brand_terms: tuple[str, ...] = ()) -> dict:
    """Totals, the questions people search, the gaps, and queries worth testing in AI assistants."""
    brand_low = tuple(t.lower() for t in brand_terms if t and len(t) >= 3)
    queries: list[dict] = []
    pages: list[dict] = []
    for row in rows:
        clicks = _number(_pick(row, CLICK_KEYS))
        impressions = _number(_pick(row, IMPRESSION_KEYS))
        position = _number(_pick(row, POSITION_KEYS))
        ctr = _ctr(_pick(row, CTR_KEYS), clicks, impressions)
        query = _clean_query(_pick(row, QUERY_KEYS))
        page = str(_pick(row, PAGE_KEYS) or "").split("?")[0][:200]
        if query:
            branded = any(t in query.lower() for t in brand_low)
            queries.append({"query": query, "clicks": clicks, "impressions": impressions, "ctr": round(ctr, 4),
                            "position": round(position, 1) if position else None, "branded": branded})
        elif page:
            pages.append({"page": page, "clicks": clicks, "impressions": impressions, "ctr": round(ctr, 4),
                          "position": round(position, 1) if position else None})
    if not queries and not pages:
        raise ValueError("No query or page column found. Export the Performance report from Search Console (the "
                         "Queries tab has 'Top queries', Clicks, Impressions, CTR, Position) and paste it with its "
                         "header row.")
    total_clicks = sum(q["clicks"] for q in queries) or sum(p["clicks"] for p in pages)
    total_impr = sum(q["impressions"] for q in queries) or sum(p["impressions"] for p in pages)
    out: dict[str, Any] = {"kind": "queries" if queries else "pages", "rows_read": len(queries) or len(pages),
                           "clicks": int(total_clicks), "impressions": int(total_impr),
                           "ctr": round(total_clicks / total_impr, 4) if total_impr else None}
    if pages and not queries:
        top = sorted(pages, key=lambda p: -p["impressions"])[:TOP]
        out.update(top_pages=top, findings=["This is the Pages tab. Export the Queries tab too, to see the questions "
                                            "people type."])
        return out
    unbranded = [q for q in queries if not q["branded"]]
    out["branded_share_of_clicks"] = (round(sum(q["clicks"] for q in queries if q["branded"]) / total_clicks, 3)
                                      if total_clicks and brand_low else None)
    questions = sorted((q for q in unbranded if _question_like(q["query"]) and len(q["query"].split()) >= 3),
                       key=lambda q: -q["impressions"])
    gaps = [q for q in questions if q["impressions"] >= MIN_GAP_IMPRESSIONS
            and ((q["position"] or 0) > BAD_POSITION or q["ctr"] < LOW_CTR)]
    candidates = [q["query"] for q in sorted((q for q in unbranded if _buying_like(q["query"])
                                              and len(q["query"].split()) >= 3), key=lambda q: -q["impressions"])][:TOP]
    out.update(top_questions=questions[:TOP], gaps=gaps[:TOP], test_in_ai=candidates,
               long_queries=sum(1 for q in unbranded if len(q["query"].split()) >= 6))
    out["findings"] = _findings(out, bool(brand_low))
    return out


def _findings(out: dict, knows_brand: bool) -> list[str]:
    notes: list[str] = []
    if out["gaps"]:
        g = out["gaps"][0]
        notes.append(f"People search \"{g['query']}\" ({int(g['impressions'])} views) and the site is seen but rarely "
                     f"chosen (position {g['position'] if g['position'] is not None else 'unknown'}, click rate "
                     f"{100 * g['ctr']:.1f}%). A page that answers it directly is the best first fix.")
    if out["test_in_ai"]:
        notes.append(f"{len(out['test_in_ai'])} buying-style searches can go into the question list to test in AI "
                     "assistants. Use their wording; never put the brand name in a buying question.")
    if out["long_queries"]:
        notes.append(f"{out['long_queries']} searches are six words or longer: people now type full questions, "
                     "the same shape AI assistants get.")
    if not knows_brand:
        notes.append("The brand name was not known, so brand searches are mixed in. Save the brand details and send "
                     "the export again for a cleaner read.")
    notes.append("Search Console counts Google searches only. It does not show what AI assistants answer and it does "
                 "not separate AI Overviews: use it to choose questions, not as a score.")
    return notes
