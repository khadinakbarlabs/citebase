"""What the saved answers say beyond the headline number: which sites AI cites for rivals but not for the brand,
how each question did (the proof behind the share), whether a question list is fit to freeze, and how search
positions moved.

Pure functions over rows that are already saved: no network, no storage, no cost.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from typing import Any

BUYING = ("awareness", "consideration")
MIN_BUYING, MIN_CONTROL = 20, 5
TOPIC_MIN, TOPIC_MAX = 8, 10
MAX_GAP_SITES = 15
MAX_RANK_ROWS = 500
RANK_ENGINES = ("google", "bing", "local")
DATASET_URL = "https://console.apify.com/storage/datasets/"
# Sites every answer cites for everyone: being listed there says nothing about a gap the brand can close.
EVERYWHERE = ("google.com", "bing.com", "youtube.com", "wikipedia.org")


def _items(value: Any) -> list[str]:
    """A saved list field ('a.com;b.com', 'a.com, b.com' or a real list) as clean lower-case items."""
    if isinstance(value, (list, tuple)):
        parts = [str(v) for v in value]
    else:
        parts = re.split(r"[;,|]", str(value or ""))
    return [p.strip().lower() for p in parts if p and p.strip()]


def _host(domain: str) -> str:
    domain = re.sub(r"^https?://", "", domain.strip().lower()).split("/")[0]
    return domain[4:] if domain.startswith("www.") else domain


def _same_site(domain: str, own: str) -> bool:
    return bool(own) and (domain == own or domain.endswith("." + own))


def _truthy(value: Any) -> bool:
    return value in (True, 1, "1", "true", "True", "yes")


def latest_round(runs: list[dict], order: list[str]) -> str | None:
    present = {r["snapshot"] for r in runs}
    return next((label for label in reversed(order) if label in present), None)


def citation_gap(runs: list[dict], panel: list[dict], brand: dict | None, snapshot: str | None,
                 limit: int = MAX_GAP_SITES) -> dict | None:
    """Sites AI cites in answers that name a rival and leave the brand out.

    Counted on buying questions of one round. A site is listed when at least two such answers cite it. The brand's
    own site and the sites cited for everyone are left out. Returns None when the round has no answers, and an
    empty list with a note when the answers carry no sources (some checks do not report them)."""
    if not snapshot:
        return None
    types = {p["prompt_id"]: p.get("type") for p in panel}
    prompts = {p["prompt_id"]: p.get("prompt", "") for p in panel}
    own = _host(str((brand or {}).get("domain") or (brand or {}).get("site") or ""))
    rows = [r for r in runs if r["snapshot"] == snapshot and types.get(r["prompt_id"]) in BUYING]
    if not rows:
        return None
    sites: dict[str, dict[str, Any]] = {}
    with_sources = 0
    for row in rows:
        domains = [_host(d) for d in _items(row.get("cited_domains"))]
        domains = [d for d in dict.fromkeys(domains) if d and not _same_site(d, own)
                   and not any(_same_site(d, e) for e in EVERYWHERE)]
        if not domains:
            continue
        with_sources += 1
        rivals = _items(row.get("competitors"))
        left_out = bool(rivals) and not _truthy(row.get("mentioned")) and not _truthy(row.get("recommended"))
        for domain in domains:
            site = sites.setdefault(domain, {"site": domain, "answers": 0, "rival_answers": 0, "with_you": 0,
                                             "engines": set(), "rivals": Counter(), "questions": []})
            site["answers"] += 1
            site["engines"].add(row["platform"])
            if _truthy(row.get("recommended")):
                site["with_you"] += 1
            if left_out:
                site["rival_answers"] += 1
                site["rivals"].update(rivals)
                question = prompts.get(row["prompt_id"], "")
                if question and question not in site["questions"] and len(site["questions"]) < 3:
                    site["questions"].append(question)
    gap = sorted((s for s in sites.values() if s["rival_answers"] >= 2),
                 key=lambda s: (-s["rival_answers"], s["with_you"], s["site"]))[:limit]
    out = [{"site": s["site"], "answers_citing_it": s["answers"], "answers_for_rivals_without_you": s["rival_answers"],
            "answers_that_recommend_you": s["with_you"], "engines": sorted(s["engines"]),
            "rivals_named": [name for name, _n in s["rivals"].most_common(3)], "example_questions": s["questions"]}
           for s in gap]
    if not with_sources:
        note = ("These answers carry no source sites, so there is nothing to compare. Checks that report sources "
                "(Perplexity, Google AI Overviews) fill this in.")
    elif not out:
        note = "No site was cited at least twice for rivals while leaving you out in this round."
    else:
        note = ("These sites were cited in answers that named a rival and not you. Getting a fair mention there is "
                "the most direct way into those answers. Earn it: no paid placements dressed up as reviews.")
    return {"round": snapshot, "answers_with_sources": with_sources, "sites": out, "note": note}


def question_breakdown(runs: list[dict], panel: list[dict], snapshot: str | None) -> list[dict]:
    """How each question did in one round, per engine: answers, and how many recommended, named or linked the brand."""
    if not snapshot:
        return []
    by_question: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(
        lambda: {"answers": 0, "recommended": 0, "named": 0, "linked": 0}))
    for row in runs:
        if row["snapshot"] != snapshot:
            continue
        cell = by_question[row["prompt_id"]][row["platform"]]
        cell["answers"] += 1
        cell["recommended"] += _truthy(row.get("recommended"))
        cell["named"] += _truthy(row.get("mentioned"))
        cell["linked"] += _truthy(row.get("cited"))
    out = []
    for prompt in panel:
        engines = by_question.get(prompt["prompt_id"])
        if not engines:
            continue
        out.append({"prompt_id": prompt["prompt_id"], "question": prompt.get("prompt", ""), "type": prompt.get("type"),
                    "topic": prompt.get("topic") or "", "answers": sum(c["answers"] for c in engines.values()),
                    "recommended": sum(c["recommended"] for c in engines.values()),
                    "engines": {name: dict(cell) for name, cell in sorted(engines.items())}})
    return out


def proof(runs: list[dict], panel: list[dict], snapshot: str | None, dataset_ids: list[str] | None) -> dict | None:
    """Everything behind one round's number: each question's result, and where the raw answers can be opened."""
    questions = question_breakdown(runs, panel, snapshot)
    if not questions:
        return None
    sources = [{"dataset_id": d, "open": DATASET_URL + d} for d in dataset_ids or []
               if isinstance(d, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9~._-]{4,79}", d)]
    how = ("Open a link to read the raw answers in your own Apify account. Citebase keeps the verdict for each answer "
           "(recommended, named, linked), not its text." if sources else
           "This round was saved from rows, not read from a dataset, so there is no link to the raw answers. Import "
           "the next round by dataset id to keep one.")
    return {"round": snapshot, "questions": questions, "raw_answers": sources, "how_to_check": how}


# ---------------------------------------------------------------- is a question list fit to freeze?
def _normal(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(text or "").lower()).split())


def review_panel(panel: list[dict]) -> dict:
    """A check of a question list before it is frozen: the mix of question types, the topics, and near-duplicates.

    Problems are things to fix before the first paid round, because the list cannot change afterwards."""
    counts = Counter(str(p.get("type") or "") for p in panel)
    buying = counts["awareness"] + counts["consideration"]
    problems: list[str] = []
    if buying < MIN_BUYING:
        problems.append(f"Only {buying} buying questions (awareness and consideration). Use at least {MIN_BUYING}, or "
                        "the number will swing too much to read.")
    if counts["control"] < MIN_CONTROL:
        problems.append(f"Only {counts['control']} control questions. Add at least {MIN_CONTROL} questions where the "
                        "brand should NOT be recommended, to tell real change from the engines changing.")
    texts = [(p.get("prompt_id"), _normal(p.get("prompt"))) for p in panel]
    seen: dict[str, Any] = {}
    doubles: list[str] = []
    for pid, text in texts:
        if not text:
            continue
        twin = seen.get(text) or next((other for known, other in seen.items()
                                       if difflib.SequenceMatcher(None, known, text).ratio() >= 0.97), None)
        if twin:
            doubles.append(f"{twin} and {pid}")
        else:
            seen[text] = pid
    if doubles:
        problems.append(f"Near-identical questions: {'; '.join(doubles[:5])}. Each should ask something different.")
    topics = Counter(str(p.get("topic") or "").strip().lower() for p in panel if p.get("type") in BUYING)
    unlabelled = topics.pop("", 0)
    topic_rows = [{"topic": name, "buying_questions": n, "can_judge_one_change": n >= TOPIC_MIN}
                  for name, n in sorted(topics.items(), key=lambda kv: (-kv[1], kv[0]))]
    advice: list[str] = []
    if unlabelled and buying:
        advice.append(f"{unlabelled} buying questions have no topic. Give each a topic so a fix can be judged on the "
                      f"questions it is meant to help (about {TOPIC_MIN} to {TOPIC_MAX} per topic).")
    small = [t["topic"] for t in topic_rows if not t["can_judge_one_change"]]
    if small:
        advice.append(f"Topics with fewer than {TOPIC_MIN} questions ({', '.join(small[:5])}) are too small to show "
                      "whether one change worked. Merge them or add questions.")
    return {"questions": len(panel), "buying_questions": buying, "control_questions": counts["control"],
            "brand_questions": counts["brand"], "topics": topic_rows, "problems": problems, "advice": advice,
            "ready_to_freeze": not problems}


# ---------------------------------------------------------------- search positions over time
def clean_ranks(rows: Any) -> list[dict]:
    """Search position rows: [{keyword, position, engine, url, country}]. position is 1 or more, or null when the
    site was not found. Raises ValueError for anything else."""
    if not isinstance(rows, list) or not rows or len(rows) > MAX_RANK_ROWS:
        raise ValueError(f"ranks must be a list of 1 to {MAX_RANK_ROWS} rows, each like "
                         '{"keyword": "payroll software", "position": 7, "engine": "google"}.')
    out, seen = [], set()
    for n, raw in enumerate(rows, 1):
        if not isinstance(raw, dict) or not str(raw.get("keyword") or "").strip():
            raise ValueError(f"Rank row {n} needs a 'keyword'.")
        engine = str(raw.get("engine") or "google").strip().lower()
        if engine not in RANK_ENGINES:
            raise ValueError(f"Rank row {n}: engine must be one of {', '.join(RANK_ENGINES)}.")
        position = raw.get("position")
        if position in ("", None):
            position = None
        elif isinstance(position, bool) or not isinstance(position, (int, float)) or position != position \
                or not 1 <= position <= 1000 or position != int(position):
            raise ValueError(f"Rank row {n}: position must be a whole number from 1 to 1000, or null when the site "
                             "was not found.")
        else:
            position = int(position)
        keyword = " ".join(str(raw["keyword"]).split())[:120].lower()
        country = re.sub(r"[^a-z]", "", str(raw.get("country") or "").lower())[:2]
        key = (keyword, engine, country)
        if key in seen:
            raise ValueError(f"Rank row {n} repeats '{keyword}' on {engine}. Send each keyword once per engine.")
        seen.add(key)
        out.append({"keyword": keyword, "engine": engine, "country": country, "position": position,
                    "url": str(raw.get("url") or "")[:300]})
    return out


def summarise_ranks(rows: list[dict]) -> dict:
    found = [r["position"] for r in rows if r["position"] is not None]
    return {"rows": rows, "keywords": len(rows), "top_3": sum(1 for p in found if p <= 3),
            "top_10": sum(1 for p in found if p <= 10), "not_found": len(rows) - len(found)}


def rank_changes(records: list[dict]) -> list[dict]:
    """The newest positions next to the ones saved before: per keyword and engine, now, before and the move
    (positive = moved up). A keyword that was not checked before has no 'before'."""
    if not records:
        return []
    now = records[-1].get("rows") or []
    before = {(r["keyword"], r["engine"], r.get("country", "")): r["position"]
              for r in (records[-2].get("rows") or [])} if len(records) > 1 else {}
    out = []
    for row in now:
        key = (row["keyword"], row["engine"], row.get("country", ""))
        old = before.get(key)
        move = None
        if key in before and old is not None and row["position"] is not None:
            move = old - row["position"]
        out.append({"keyword": row["keyword"], "engine": row["engine"], "now": row["position"],
                    "before": old if key in before else None, "checked_before": key in before, "moved_up_by": move})
    return sorted(out, key=lambda r: (r["now"] is None, r["now"] or 0, r["keyword"]))
