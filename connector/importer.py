"""Turns raw AI Brand Monitor results into Citebase run rows (so no one has to retype or judge them by hand).

The Actor returns one item per brand x query x platform. Each item becomes one run row for a panel prompt.
`recommended` is an automatic estimate: the brand is named with neutral or positive wording. Items where the
call is close are listed under `needs_review` with the sentence around the mention, so the assistant can check.
"""
from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlsplit

PLATFORM_ALIASES = {"google_ai_overviews": "google-aio", "ai_overviews": "google-aio", "ai_mode": "google-aimode"}


def norm_text(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def domain_of(url: str) -> str:
    try:
        host = urlsplit(url).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


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
        mentioned = bool(item.get("brand_mentioned"))
        sentiment = str(item.get("sentiment") or "").lower()
        count = int(item.get("brand_mention_count") or 0)
        recommended = mentioned and sentiment != "negative" and count >= 1
        urls = [u for u in (item.get("cited_urls") or []) if isinstance(u, str)]
        runs.append({
            "snapshot": snapshot, "prompt_id": pid, "platform": platform, "repeat": seq[(pid, platform)],
            "mentioned": mentioned, "cited": bool(item.get("is_cited_as_source")), "recommended": recommended,
            "position": item.get("mention_position_score") or "",
            "competitors": ";".join(str(c) for c in (item.get("competitor_mentions") or []))[:300],
            "cited_domains": ";".join(sorted({d for d in map(domain_of, urls) if d}))[:500],
            "date": str(item.get("scraped_at") or "")[:10] or None,
        })
        if mentioned and (sentiment in ("", "neutral", "mixed") or count == 1):
            review.append({"prompt_id": pid, "platform": platform, "sentiment": sentiment or "unknown",
                           "mention_count": count, "context": str(item.get("mention_context") or "")[:300],
                           "auto_recommended": recommended})
    if not runs:
        raise ValueError("None of the results matched a question in the panel. Use exactly the same question text in "
                         "the panel and in the Brand Monitor's customQueries.")
    rec = sum(1 for r in runs if r["recommended"])
    return {"runs": [{k: v for k, v in r.items() if v is not None} for r in runs], "unmatched_queries": unmatched[:20],
            "needs_review": review[:25],
            "summary": {"rows": len(runs), "recommended": rec, "mentioned": sum(1 for r in runs if r["mentioned"]),
                        "cited": sum(1 for r in runs if r["cited"]), "unmatched": len(unmatched)}}
