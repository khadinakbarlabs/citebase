"""Turns raw AI-check results into Citebase run rows (so no one has to retype or judge them by hand).

Results from five kinds of Actor are read, each recognised by its own fields because several carry no `platform`:

* AI Brand Monitor: one item per brand x question x AI, with sentiment. Only positive wording counts as recommended.
* Google AI Overviews: one item per question. Sources and a brand match, no wording to judge.
* Google AI Mode: one item per question. Answer text and citations, no brand match field, so the brand is needed.
* AI Search Visibility Tracker: per AI, whether the tracked domain was cited, and at which rank.
* AI Citations Tracker: per AI, whether the tracked domain was cited, with the kind of evidence.

Honesty rules (the same for every kind): `recommended` needs positive wording, and never follows negative wording. A
position, a rank or a citation says where or whether the brand appeared, not that it was recommended, so those only
set `cited` (and `mentioned` when the answer text names the brand). Results with no wording to judge (everything
except the Brand Monitor) therefore never count as recommended by themselves: every mention or citation goes to
`needs_review` with the reason and the sentence around it. Anything that cannot be judged at all is skipped and
counted with a plain reason, never counted silently.

Where an answer came from (model, country, language, device, collection method, time) is copied onto the row when
the results say it. Settings the Actor does not echo can be supplied once as `context`; the results' own value wins.
"""
from __future__ import annotations

import os
import re
import sys
from collections import defaultdict
from urllib.parse import urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import citation_loop as cl  # noqa: E402

PLATFORM_ALIASES = {"google_ai_overviews": "google-aio", "ai_overviews": "google-aio", "google-ai-overviews": "google-aio",
                    "ai_mode": "google-aimode", "google_ai_mode": "google-aimode", "google-ai-mode": "google-aimode"}
METRIC_VERSION = 2  # keep equal to citation_loop.METRIC_VERSION (a test checks this)
MAX_REVIEW = 25
MAX_NOTES = 12
REVIEW_ORDER = {"neutral": 0, "mixed": 0, "unknown": 0, "positive": 1, "negative": 2}  # close calls before clear ones
CONTEXT_KEYS = ("country", "language", "device", "location")
CONTEXT_STAMPED = ("country", "language", "device")  # location has no field on a run row

BRAND_MONITOR, AI_OVERVIEWS, AI_MODE = "ai-brand-monitor", "google-ai-overviews", "google-ai-mode"
VISIBILITY, CITATIONS = "ai-search-visibility-tracker", "ai-citations-tracker"
BRAND_MONITOR_KEYS = ("brand_mentioned", "is_cited_as_source", "cited_urls", "mention_position_score",
                      "competitor_mentions", "sentiment", "brand_mention_count")
QUERY_KEYS = ("query", "prompt", "question", "searchQuery", "keyword")
TEXT_KEYS = ("responseText", "aiOverviewText", "overviewText", "answerText", "answer", "text", "summary")
PROVENANCE_KEYS = {
    "engine_version": ("model_used", "modelUsed", "model", "engine_version"),
    "country": ("countryCode", "country_code", "country"),
    "language": ("languageCode", "language_code", "language"),
    "device": ("device",),
    "source": ("source",),
    "answered_at": ("scrapedAt", "scraped_at", "fetchedAt", "fetched_at", "checkedAt", "checked_at", "answered_at"),
}
NO_WORDING = "carries no wording to judge, so it is not counted as a recommendation until you review it"
SHAPE_LABELS = {AI_OVERVIEWS: "Google AI Overviews", AI_MODE: "Google AI Mode", VISIBILITY: "AI Search Visibility Tracker",
                CITATIONS: "AI Citations Tracker"}

# reason code -> (plain sentence for the skipped list, phrase for the error when nothing could be imported)
SKIP_TEXT = {
    "diagnostic": ("Diagnostic rows: the check could not run for that AI, so they hold no answer.",
                   "{n} diagnostic row(s) (the check could not run for that AI{e})"),
    "unknown_shape": ("Items in a shape Citebase does not recognise as AI-check results.",
                      "{n} item(s) in a shape Citebase does not recognise{e}"),
    "no_engine": ("Items that do not say which AI answered, so they cannot be placed.",
                  "{n} item(s) that do not say which AI answered"),
    "needs_brand": ("Results that can only be judged with the brand's name or website. Send brand, or save it with the project.",
                    "{n} item(s) that can only be judged with the brand's name or website (send brand, or save it with the project)"),
    "no_question_text": ("Items with no question text.", "{n} item(s) with no question text"),
    "no_matching_question": ("Items whose question is not in the project's question list.",
                             "{n} item(s) asked a question that is not in the panel{e}"),
    "not_an_item": ("Entries that are not result objects.", "{n} entr(ies) that are not result objects"),
}
SKIP_ADVICE = {
    "diagnostic": "Diagnostic rows mean the AI could not be checked (blocked or unreachable): look at the Actor run's log and run it again.",
    "needs_brand": "Send the brand (name and website), or save it with the project, then import again.",
    "no_matching_question": "Use exactly the same question text in the panel and in the Actor's input (for the Brand Monitor, customQueries).",
}


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


# ---------------------------------------------------------------- reading items
class Skip(Exception):
    """An item that cannot be turned into a row; `code` is a key of SKIP_TEXT."""

    def __init__(self, code: str, example: str = ""):
        super().__init__(code)
        self.code, self.example = code, example


def first_text(item: dict, keys) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def as_domain(value) -> str:
    """A domain from a URL, a bare domain or an object holding either; '' when there is none."""
    if isinstance(value, dict):
        return as_domain(value.get("domain") or value.get("url") or "")
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "/" in text or ":" in text:
        return domain_of(text if "://" in text else "//" + text)
    return text[4:] if text.startswith("www.") else text


def url_of(value) -> str:
    return str(value.get("url") or "") if isinstance(value, dict) else str(value or "")


def clean_domains(values) -> list[str]:
    """Domains in order, without repeats."""
    seen: list[str] = []
    for value in values if isinstance(values, list) else []:
        domain = as_domain(value)
        if domain and domain not in seen:
            seen.append(domain)
    return seen


def brand_view(brand) -> dict | None:
    """What matching needs from the brand: name terms, own domains and competitor names. None when there is nothing."""
    if not isinstance(brand, dict):
        return None
    terms = cl.brand_terms(brand)
    domains = {d for d in (as_domain(brand.get("domain")), as_domain(brand.get("site"))) if d}
    if not terms and not domains:
        return None
    competitors = [str(c).strip() for c in (brand.get("competitors") or []) if str(c).strip()]
    return {"terms": terms, "domains": domains, "competitors": competitors}


def own_domain(domain: str, brand: dict) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in brand["domains"])


def term_pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(term).replace(r"\ ", r"\s+") + r"(?![a-z0-9])")


def count_mentions(text: str, brand: dict) -> int:
    low = norm_text(text)
    return sum(len(term_pattern(t).findall(low)) for t in brand["terms"]) if low else 0


def snippet_around(text: str, brand: dict, width: int = 300) -> str:
    """The part of the answer around the first mention of the brand, as written."""
    plain = " ".join(str(text or "").split())
    for term in brand["terms"]:
        hit = re.search(term_pattern(term).pattern, plain, re.IGNORECASE)
        if hit:
            start = max(0, hit.start() - width // 3)
            return plain[start:start + width]
    return plain[:width]


def competitors_in(blob: str, brand: dict) -> str:
    low = norm_text(blob)
    return ";".join(c for c in brand["competitors"] if low and term_pattern(c.lower()).search(low))[:300]


def clean_context(context) -> dict[str, str]:
    """The run settings the user passed, checked. Raises ValueError with a plain fix."""
    if context in (None, {}):
        return {}
    if not isinstance(context, dict):
        raise ValueError('context must be an object like {"country": "US", "language": "en", "device": "desktop"}.')
    extra = sorted(set(context) - set(CONTEXT_KEYS))
    if extra:
        raise ValueError(f"context does not take {', '.join(extra)}. It takes: {', '.join(CONTEXT_KEYS)}.")
    out = {}
    for key, value in context.items():
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"context.{key} must be plain text, for example {{\"{key}\": \"US\"}}.")
        if str(value).strip():
            out[key] = " ".join(str(value).split())[:80]
    return out


class Tally:
    """Collects what happens to the items so the result can say it in plain words."""

    def __init__(self, context: dict[str, str]):
        self.context = context
        self.skips: dict[str, dict] = {}
        self.warnings: list[str] = []
        self.conflicts: set[str] = set()
        self.no_overview = 0

    def skip(self, code: str, example: str = "") -> None:
        entry = self.skips.setdefault(code, {"count": 0, "example": ""})
        entry["count"] += 1
        entry["example"] = entry["example"] or str(example)[:120]


def provenance(item: dict, tally: Tally) -> dict[str, str]:
    """Model, country, language, device, collection method and time of one answer, from the item or the run settings."""
    out = {}
    for field, keys in PROVENANCE_KEYS.items():
        value = next((item[k] for k in keys if isinstance(item.get(k), (str, int, float))
                      and not isinstance(item.get(k), bool) and str(item[k]).strip()), "")
        limit = cl.ANSWERED_AT_LIMIT if field == "answered_at" else cl.PROVENANCE_LIMITS[field]
        out[field] = " ".join(str(value).split())[:limit]
    for field in CONTEXT_STAMPED:
        given = tally.context.get(field)
        if not given:
            continue
        if not out[field]:
            out[field] = given
        elif cl.clean_prov(field, out[field]) != cl.clean_prov(field, given):
            tally.conflicts.add(field)
    return {f: (v if f == "answered_at" else cl.clean_prov(f, v)) for f, v in out.items()}


def detect_shape(item: dict) -> str | None:
    """Which kind of result an item is, from its own fields. 'diagnostic' for rows that hold no answer."""
    if (str(item.get("platform") or "").strip().lower() == "diagnostic" or "diagnostic_status" in item
            or "diagnostic_message" in item):
        return "diagnostic"
    if "aioPresent" in item or ("brandMatch" in item and "sources" in item):
        return AI_OVERVIEWS
    if "trackedDomainCited" in item or "trackedCitationUrls" in item:
        return CITATIONS
    if "domain_cited" in item or "citation_rank" in item:
        return VISIBILITY
    if isinstance(item.get("citations"), list) and any(k in item for k in ("responseText", "searchId", "fetchedAt")):
        return AI_MODE
    if "platform" in item or any(k in item for k in BRAND_MONITOR_KEYS):
        return BRAND_MONITOR
    return None


def platform_of(item: dict) -> str:
    raw = first_text(item, ("platform", "provider", "engine")).lower()
    return PLATFORM_ALIASES.get(raw, PLATFORM_ALIASES.get(raw.replace(" ", "_"), raw))


# ---------------------------------------------------------------- one adapter per kind
# Each returns the judged part of a row: platform, mentioned, cited, recommended, position, competitors,
# cited_domains, plus review = None (nothing to check) or {sentiment, mention_count, reason, context}.
def judged(platform, mentioned, cited, position="", competitors="", cited_domains=(), review=None, recommended=False):
    return {"platform": platform, "mentioned": mentioned, "cited": cited, "recommended": recommended,
            "position": position, "competitors": competitors,
            "cited_domains": ";".join(sorted({d for d in cited_domains if d}))[:500], "review": review}


def review_entry(reason: str, context: str = "", count: int = 0, sentiment: str = "unknown") -> dict:
    return {"sentiment": sentiment, "mention_count": count, "reason": reason, "context": str(context)[:300]}


def adapt_brand_monitor(item: dict, brand, tally: Tally) -> dict:
    platform = platform_of(item)
    if not platform:
        raise Skip("no_engine")
    mentioned, recommended, sentiment, reason = judge(item)
    urls = [u for u in (item.get("cited_urls") or []) if isinstance(u, str)]
    review = None
    if mentioned and not recommended:
        review = review_entry(reason, item.get("mention_context") or "", whole_number(item.get("brand_mention_count")),
                              sentiment or "unknown")
    return judged(platform, mentioned, bool(item.get("is_cited_as_source")), item.get("mention_position_score") or "",
                  ";".join(str(c) for c in (item.get("competitor_mentions") or []))[:300], map(domain_of, urls), review,
                  recommended)


def adapt_ai_overviews(item: dict, brand, tally: Tally) -> dict:
    match = item.get("brandMatch") if isinstance(item.get("brandMatch"), dict) and "matched" in item["brandMatch"] else None
    if match is None and brand is None:
        raise Skip("needs_brand")
    if item.get("aioPresent") is False:
        tally.no_overview += 1
        return judged("google-aio", False, False)
    sources = [s for s in (item.get("sources") or []) if isinstance(s, dict)]
    text = first_text(item, TEXT_KEYS)
    domains = [as_domain(s) for s in sources]
    matched = bool(match and match.get("matched"))
    own = [s for s, d in zip(sources, domains) if brand and own_domain(d, brand)]
    if not own and matched and match.get("position") is not None:  # is the Actor's match one of the listed sources?
        own = [s for s in sources if s.get("position") == match["position"]]
    cited = bool(own)
    position = ""
    if cited:
        position = match["position"] if matched and match.get("position") is not None else own[0].get("position", "")
    named = count_mentions(text, brand) if brand and text else 0
    mentioned = bool(named) or (matched and not cited)  # a match outside the sources can only be the answer text
    blob = " ".join([text] + [f"{s.get('title') or ''} {d}" for s, d in zip(sources, domains)])
    review = None
    if cited or mentioned:
        where = (f"cited as a source (position {position})" if position != "" else "cited as a source") if cited \
            else "matched by the Actor but not in a listed source"
        context = f"{own[0].get('title') or ''} ({url_of(own[0])})" if cited else (snippet_around(text, brand) if named else "")
        review = review_entry(f"{where}; a Google AI Overview {NO_WORDING}", context, named or int(mentioned))
    return judged("google-aio", mentioned, cited, position, competitors_in(blob, brand) if brand else "", domains, review)


def adapt_ai_mode(item: dict, brand, tally: Tally) -> dict:
    if brand is None:
        raise Skip("needs_brand")
    text = first_text(item, ("responseText",))
    cites = [c for c in (item.get("citations") or []) if isinstance(c, dict)]
    domains = [as_domain(c) for c in cites]
    hits = [c for c, d in zip(cites, domains) if d and own_domain(d, brand)]
    mentions = count_mentions(text, brand)
    cited = bool(hits)
    position = hits[0].get("position") if hits and hits[0].get("position") is not None else ""
    blob = " ".join([text] + [f"{c.get('title') or ''} {d}" for c, d in zip(cites, domains)])
    review = None
    if cited or mentions:
        where = "named in the answer and cited as a source" if cited and mentions else (
            "cited as a source" if cited else "named in the answer")
        context = snippet_around(text, brand) if mentions else f"{hits[0].get('title') or ''} {hits[0].get('snippet') or ''}"
        review = review_entry(f"{where}; a Google AI Mode answer {NO_WORDING}", context, mentions)
    return judged("google-aimode", bool(mentions), cited, position, competitors_in(blob, brand), domains, review)


def adapt_visibility(item: dict, brand, tally: Tally) -> dict:
    platform = platform_of(item)
    if not platform:
        raise Skip("no_engine")
    cited = bool(item.get("domain_cited"))
    pages = [url_of(p) for p in item.get("cited_pages") or []]
    competing = clean_domains(item.get("competing_domains"))
    rank = item.get("citation_rank")
    position = rank if cited and rank not in (None, "") and not isinstance(rank, bool) else ""
    review = None
    if cited:
        where = f"cited as a source (rank {position})" if position != "" else "cited as a source"
        review = review_entry(f"{where}; this result lists sources only and {NO_WORDING}", next((p for p in pages if p), ""))
    return judged(platform, False, cited, position, ";".join(competing)[:300],
                  [as_domain(p) for p in pages] + competing, review)


def adapt_citations(item: dict, brand, tally: Tally) -> dict:
    platform = platform_of(item)
    if not platform:
        raise Skip("no_engine")
    tracked = [str(u) for u in item.get("trackedCitationUrls") or [] if isinstance(u, str)]
    cited = bool(item.get("trackedDomainCited")) or bool(tracked)
    cites = [c for c in item.get("citations") or [] if isinstance(c, dict)]
    domains: list[str] = []
    for c in cites:
        domains += [as_domain(c)] + [as_domain(d) for d in (c.get("sourceDomains") or [])]
    evidence = {str(c.get("evidenceType") or "") for c in cites if url_of(c) in tracked}
    review = None
    if cited:
        lead = ("the only evidence is a link inside the answer text, not a listed source" if evidence == {"answer_link"}
                else "cited as a source")
        review = review_entry(f"{lead}; this result {NO_WORDING}", tracked[0] if tracked else "")
    return judged(platform, False, cited, "", "", domains, review)


ADAPTERS = {BRAND_MONITOR: adapt_brand_monitor, AI_OVERVIEWS: adapt_ai_overviews, AI_MODE: adapt_ai_mode,
            VISIBILITY: adapt_visibility, CITATIONS: adapt_citations}


# ---------------------------------------------------------------- the whole import
def explain_nothing_imported(total: int, tally: Tally) -> str:
    parts = [SKIP_TEXT[code][1].format(n=e["count"], e=_example(code, e["example"])) for code, e in tally.skips.items()]
    advice = " ".join(SKIP_ADVICE[code] for code in tally.skips if code in SKIP_ADVICE)
    return (f"None of the {total} items could be imported: " + "; ".join(parts) + ". " + advice).strip()


def _example(code: str, example: str) -> str:
    if not example:
        return ""
    return f", for example '{example}'" if code == "no_matching_question" else f", for example: '{example}'"


def notes_for(tally: Tally, shapes: dict[str, int]) -> list[str]:
    notes = []
    if tally.no_overview:
        notes.append(f"{tally.no_overview} question(s) had no Google AI Overview, so they are saved as not mentioned and "
                     "not recommended.")
    wordless = [SHAPE_LABELS[s] for s in shapes if s in SHAPE_LABELS]
    if wordless:
        notes.append(f"Results from {', '.join(wordless)} have no wording to judge: they count as cited (or mentioned), "
                     "never as recommended, until you review them. Read them in needs_review.")
    if tally.warnings:
        notes.append("The Actor reported: " + "; ".join(tally.warnings[:3]))
    for field in sorted(tally.conflicts):
        notes.append(f"Some results report a different {field} than the run settings you passed; the results' own value was used.")
    if tally.context.get("location"):
        notes.append(f"The location '{tally.context['location']}' was noted here but is not stored on the rows (rows keep "
                     "country, language and device).")
    return notes[:MAX_NOTES]


def convert(items: list[dict], panel: list[dict], snapshot: str, brand: dict | None = None,
            context: dict | None = None) -> dict:
    """Maps AI-check results to run rows.

    Returns {runs, unmatched_queries, needs_review, summary, skipped, detected, notes, context}. Raises ValueError,
    saying which causes applied, when no item could be imported."""
    if not isinstance(items, list) or not items:
        raise ValueError("Send the list of result items from the AI check run (its dataset items).")
    tally = Tally(clean_context(context))
    view = brand_view(brand)
    by_text = {norm_text(p["prompt"]): p["prompt_id"] for p in panel}
    seq: dict[tuple[str, str], int] = defaultdict(int)
    shapes: dict[str, int] = defaultdict(int)
    runs, unmatched, review = [], [], []
    for item in items:
        if not isinstance(item, dict):
            tally.skip("not_an_item", type(item).__name__)
            continue
        shape = detect_shape(item)
        if shape == "diagnostic":
            tally.skip("diagnostic", first_text(item, ("diagnostic_message", "diagnostic_status")))
            continue
        if shape is None:
            tally.skip("unknown_shape", ", ".join(sorted(map(str, item))[:6]))
            continue
        query = first_text(item, QUERY_KEYS)
        if not query:
            tally.skip("no_question_text")
            continue
        pid = by_text.get(norm_text(query))
        if not pid:
            if query not in unmatched:
                unmatched.append(query)
            tally.skip("no_matching_question", query)
            continue
        try:
            row = ADAPTERS[shape](item, view, tally)
        except Skip as skip:
            tally.skip(skip.code, skip.example)
            continue
        platform = row["platform"]
        seq[(pid, platform)] += 1
        shapes[shape] += 1
        stamp = provenance(item, tally)
        day = cl.parse_date(stamp["answered_at"])
        runs.append({
            "snapshot": snapshot, "prompt_id": pid, "platform": platform, "repeat": seq[(pid, platform)],
            "mentioned": row["mentioned"], "cited": row["cited"], "recommended": row["recommended"],
            "position": row["position"], "competitors": row["competitors"], "cited_domains": row["cited_domains"],
            "date": day.isoformat() if day else None, "metric_version": METRIC_VERSION, **stamp})
        if row["review"]:
            review.append({"prompt_id": pid, "platform": platform, "auto_recommended": False, **row["review"]})
        for warning in (w for w in (item.get("warnings") or []) if isinstance(w, str) and w):
            if warning not in tally.warnings:
                tally.warnings.append(warning)
    if not runs:
        raise ValueError(explain_nothing_imported(len(items), tally))
    review.sort(key=lambda r: REVIEW_ORDER.get(r["sentiment"], 0))  # stable: keeps result order within a group
    skipped = [{"reason": code, "count": e["count"], "why": SKIP_TEXT[code][0], "example": e["example"]}
               for code, e in tally.skips.items()]
    return {"runs": [{k: v for k, v in r.items() if v is not None} for r in runs], "unmatched_queries": unmatched[:20],
            "needs_review": review[:MAX_REVIEW], "skipped": skipped, "detected": dict(shapes),
            "notes": notes_for(tally, shapes), "context": tally.context or None,
            "summary": {"rows": len(runs), "recommended": sum(1 for r in runs if r["recommended"]),
                        "mentioned": sum(1 for r in runs if r["mentioned"]), "cited": sum(1 for r in runs if r["cited"]),
                        "unmatched": len(unmatched), "skipped": sum(e["count"] for e in tally.skips.values()),
                        "needs_review": len(review)}}
