"""One SEO plan per project: on-page, off-page and technical work, each with its evidence and guidelines.

Everything comes from results already saved in the project (site audit, AI answers, cited sites and search
reports). Building the plan never starts paid research."""
import re

import history
import insights
import storage
import work_actions
import work_insights

GUIDELINES = {
    "on_page": [
        "Give every important page one clear H1, a unique title under 60 characters and a description under 160.",
        "Answer each tracked buyer question on a real page, with prices, limits and named sources an assistant can quote.",
        "Add a visible author and updated date to long pages, and valid structured data that matches the page.",
        "Link related pages to each other so no key page is more than three clicks from the home page.",
    ],
    "off_page": [
        "Start with the sites AI answers already cite for your competitors; they shape what assistants say.",
        "Read the actual article first and pitch only where your product genuinely fits its readers.",
        "Offer something useful: corrected facts, original data, a quote or a product to test. Never pay for links.",
        "Keep your name, description and prices identical across directories, reviews and profiles.",
    ],
    "technical": [
        "Let search engines and AI crawlers read your pages: check robots.txt, noindex tags and server errors first.",
        "Serve the main content in the HTML, not only after JavaScript runs.",
        "Use one canonical address per page, with HTTPS and no redirect chains.",
        "Keep pages light and fast on mobile, and list every important page in the XML sitemap.",
    ],
}
LABELS = {"on_page": "On-page SEO", "off_page": "Off-page SEO", "technical": "Technical SEO"}
PRIORITY = {"fail": "high", "warn": "medium"}


def _item(slug, bucket, title, why, how, *, source, observed_on=None, pages=None, url=None, priority="medium",
          next_step=None):
    return {"id": work_insights._id(slug, "plan", bucket, title, *(pages or [])), "title": title, "why": why,
            "how": how, "source": source, "observed_on": observed_on, "pages": pages or [], "evidence_url": url,
            "priority": priority, "next_step": next_step}


def _audit_items(slug, audit):
    items = {"on_page": [], "technical": []}
    for p in audit.get("problems", []):
        bucket = "on_page" if p.get("area") in ("on-page", "ai-search", "content") else "technical"
        pages = sorted({work_insights._url(u) for u in p.get("example_urls") or []} - {""})
        items[bucket].append(_item(
            slug, bucket, p.get("check") or "Site finding", p.get("detail") or "Found in the latest site audit.",
            "Fix it on the listed pages, then run the site audit again to confirm.",
            source="Site audit", observed_on=audit.get("date"), pages=pages, url=pages[0] if pages else None,
            priority=PRIORITY.get(p.get("level"), "low"), next_step="action_save"))
    return items


def _answer_items(slug, data, label):
    on_page, off_page = [], []
    gap = insights.citation_gap(data["runs"], data["panel"], data["meta"].get("brand"), label) or {}
    sites = [s for s in gap.get("sites", []) if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z0-9-]{2,63}", s["site"])]
    proofs = work_insights._finding_proofs(data, label, {s["site"] for s in sites})
    for site in sites:
        url, observed = proofs["off_page", site["site"]]
        count = site["answers_for_rivals_without_you"]
        off_page.append(_item(
            slug, "off_page", "Get included on " + site["site"],
            f"AI answers cited this site {count} time{'s' if count != 1 else ''} for competitors but not for you.",
            "Open the cited article, confirm it fits your product, find the author or editor, then review a short pitch.",
            source="Cited domains", observed_on=observed, url=url, priority="high" if count >= 3 else "medium",
            next_step="citation_contact"))
    for q in insights.question_breakdown(data["runs"], data["panel"], label):
        if q["type"] in insights.BUYING and q["answers"] and not q["recommended"]:
            url, observed = proofs["answers", q["prompt_id"]]
            on_page.append(_item(
                slug, "on_page", "Answer: " + q["question"],
                f"No assistant recommended you in {q['answers']} saved answer{'s' if q['answers'] != 1 else ''}.",
                "Point one page at this question. State who it is for, prices and limits, with sources an assistant can cite.",
                source="AI answers", observed_on=observed, url=url, priority="medium", next_step="action_save"))
    return on_page, off_page


def build(slug, data, demand):
    plan = {bucket: [] for bucket in LABELS}
    audit = data["audits"][-1] if data["audits"] else None
    if audit:
        for bucket, rows in _audit_items(slug, audit).items():
            plan[bucket].extend(rows)
    rounds = work_insights._rounds(data)
    if rounds:
        on_page, off_page = _answer_items(slug, data, rounds[-1][0])
        plan["on_page"].extend(on_page)
        plan["off_page"].extend(off_page)
    for gap in (demand or {}).get("gaps", [])[:10]:
        plan["on_page"].append(_item(
            slug, "on_page", "Improve the result for “" + gap["query"] + "”",
            f"{int(gap['impressions'])} Google impressions but few clicks.",
            "Rewrite the title and description so they match what this searcher wants.",
            source="Search Console", observed_on=demand.get("date"), priority="medium", next_step="action_save"))
    order = {"high": 0, "medium": 1, "low": 2}
    sections = []
    for bucket, label in LABELS.items():
        rows = sorted(plan[bucket], key=lambda r: order[r["priority"]])
        missing = ("Run the site audit to find these." if bucket != "off_page" and not audit else
                   "Run an AI check to see which sites answers cite." if bucket == "off_page" and not rounds else "")
        sections.append({"area": bucket, "label": label, "items": rows[:25], "total": len(rows),
                         "guidelines": GUIDELINES[bucket], "missing_evidence": missing})
    return {"sections": sections,
            "sources": {"audit_date": audit.get("date") if audit else None, "ai_round": rounds[-1][0] if rounds else None,
                        "search_report": (demand or {}).get("date")},
            "note": "Built from saved results only. Approve an item to turn it into a tracked action."}


async def execute(project, operation, data):
    if operation != "seo_plan":
        raise ValueError("Unknown SEO plan operation.")
    work_actions.valid_keys(data, ())
    slug = storage.clean_slug(project)
    be = await storage.get_backend()
    project_data = await history.load_project(slug)
    keys = await be.keys(storage.key(slug, "signal", "search") + ".")
    demand = await be.get(keys[-1]) if keys else None
    return {"project": slug, **build(slug, project_data, demand)}
