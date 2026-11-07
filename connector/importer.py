"""Turns raw AI Brand Monitor results into Citebase run rows (so no one has to retype or judge them by hand).

The Actor returns one item per brand x query x platform. Each item becomes one run row for a panel prompt.
`recommended` is set automatically only on positive sentiment, and never when the wording is negative. A mention
position score says where the brand appeared in the answer, not whether it was recommended, so it is kept on the row
but never counts by itself. Every other mention goes to `needs_review` with the sentence around it, so the
assistant can check it with the user. Being named is not the same as being recommended.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

PLATFORM_ALIASES = {"google_ai_overviews": "google-aio", "ai_overviews": "google-aio", "ai_mode": "google-aimode"}
METRIC_VERSION = 2  # keep equal to citation_loop.METRIC_VERSION (a test checks this)
MAX_REVIEW = 25
REVIEW_ORDER = {"neutral": 0, "mixed": 0, "unknown": 0, "positive": 1, "negative": 2}  # close calls before clear ones


def norm_text(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def domain_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def whole_number(value) -> int:
    """A mention count as a whole number; anything unreadable counts as 0."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def has_position(value) -> bool:
    """True when the item carries a positive mention position score (used only to explain the review reason)."""
    if isinstance(value, bool):
        return False
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def judge(item: dict) -> tuple[bool, bool, str, str]:
    """Returns (mentioned, recommended, sentiment, reason). `reason` says why a mention is not auto-recommended."""
    mentioned = bool(item.get("brand_mentioned"))
    sentiment = str(item.get("sentiment") or "").strip().lower()
    if not mentioned:
        return False, False, sentiment, ""
    if sentiment == "negative":
        return True, False, sentiment, "negative wording"
    if sentiment == "positive":
        return True, True, sentiment, ""
    why = "no sentiment given" if not sentiment else f"{sentiment} wording"
    if has_position(item.get("mention_position_score")):
        why += ", has a position score but that is not proof of a recommendation"
    return True, False, sentiment, why


def convert(items: list[dict], panel: list[dict], snapshot: str) -> dict:
    """Maps Brand Monitor items to run rows. Returns {runs, unmatched_queries, needs_review, summary}."""
    if not isinstance(items, list) or not items:
        raise ValueError("Send the list of result items from the AI Brand Monitor run (its dataset items).")
    by_text = {norm_text(p["prompt"]): p["prompt_id"] for p in panel}
    seq: dict[tuple[str, str], int] = defaultdict(int)
    runs, unmatched, review = [], [], []
    for item in items:
        if not isinstance(item, dict):
            continue
        pid = by_text.get(norm_text(item.get("query")))
        if not pid:
            if item.get("query") and item["query"] not in unmatched:
                unmatched.append(item["query"])
            continue
        platform = str(item.get("platform") or "").strip().lower()
        platform = PLATFORM_ALIASES.get(platform, platform)
        if not platform:
            continue
        seq[(pid, platform)] += 1
        mentioned, recommended, sentiment, reason = judge(item)
        urls = [u for u in (item.get("cited_urls") or []) if isinstance(u, str)]
        runs.append({
            "snapshot": snapshot, "prompt_id": pid, "platform": platform, "repeat": seq[(pid, platform)],
            "mentioned": mentioned, "cited": bool(item.get("is_cited_as_source")), "recommended": recommended,
            "position": item.get("mention_position_score") or "",
            "competitors": ";".join(str(c) for c in (item.get("competitor_mentions") or []))[:300],
            "cited_domains": ";".join(sorted({d for d in map(domain_of, urls) if d}))[:500],
            "date": str(item.get("scraped_at") or "")[:10] or None, "metric_version": METRIC_VERSION,
        })
        if mentioned and not recommended:
            review.append({"prompt_id": pid, "platform": platform, "sentiment": sentiment or "unknown",
                           "mention_count": whole_number(item.get("brand_mention_count")), "reason": reason,
                           "context": str(item.get("mention_context") or "")[:300], "auto_recommended": False})
    if not runs:
        raise ValueError("None of the results matched a question in the panel. Use exactly the same question text in "
                         "the panel and in the Brand Monitor's customQueries.")
    review.sort(key=lambda r: REVIEW_ORDER.get(r["sentiment"], 0))  # stable: keeps result order within a group
    rec = sum(1 for r in runs if r["recommended"])
    return {"runs": [{k: v for k, v in r.items() if v is not None} for r in runs], "unmatched_queries": unmatched[:20],
            "needs_review": review[:MAX_REVIEW],
            "summary": {"rows": len(runs), "recommended": rec, "mentioned": sum(1 for r in runs if r["mentioned"]),
                        "cited": sum(1 for r in runs if r["cited"]), "unmatched": len(unmatched),
                        "needs_review": len(review)}}
