"""Logic behind the Citebase connector tools. Plain functions (no MCP imports) so they are easy to test.

The tools in this file are stateless. Saved projects live in storage.py, history.py and report.py, and only when the user gives a project name.
Users (or the AI on their behalf) pass in what a tool needs and get a result back.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
import tempfile
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import cb_state as st  # noqa: E402
import citation_loop as cl  # noqa: E402
import site_audit as sa  # noqa: E402

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "prices.json")) as _fh:
    PRICES = json.load(_fh)

MAX_PANEL, MAX_RUNS, MAX_EXPERIMENTS = 200, 5000, 100
MAX_AUDIT_PAGES = 30
CAP_MULTIPLIER = 1.3
WEB_NOTE = (
    "WEB MODE. You are using Citebase through a connector, not the Claude Code plugin, so you cannot run local "
    "scripts or save files. Replace these steps: site_audit.py -> call the audit_site tool. citation_loop.py -> call "
    "measure_recommendation_share with the panel, runs and experiments as JSON. To keep progress between sessions "
    "ask for a short project name and use save_results, get_history, make_report, import_ai_results and "
    "schedule_checks (data goes to the user's own Apify account); without a project name nothing is kept. "
    "outreach_ledger.py approve -> ask the user in chat to confirm the exact final text, and run "
    "check_outreach_draft first. Paid data runs -> call-actor on the Apify connector with "
    "callOptions.maxTotalChargeUsd set to the suggested_cap_usd from quote_cost. There is no automatic guard in this "
    "mode, so follow the spending and approval rules yourself. Ignore steps about the seo-workspace folder and keep "
    "notes in the conversation. Talk to the user in short, plain words.\n\n"
)


# ---------------------------------------------------------------- playbooks
def _split_frontmatter(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        return {}, text
    head, _, body = text[3:].partition("\n---")
    meta = {}
    for line in head.splitlines():
        key, sep, val = line.partition(":")
        if sep:
            meta[key.strip()] = val.strip()
    return meta, body.lstrip("\n")


def playbook_paths() -> dict[str, str]:
    out: dict[str, str] = {}
    skills = os.path.join(ROOT, "skills")
    for name in sorted(os.listdir(skills)):
        path = os.path.join(skills, name, "SKILL.md")
        if os.path.isfile(path):
            out[name] = path
    refs = os.path.join(ROOT, "references")
    for fname in sorted(os.listdir(refs)):
        if fname.endswith(".md"):
            out[fname[:-3]] = os.path.join(refs, fname)
    return out


def get_playbook(name: str | None = None) -> dict:
    paths = playbook_paths()
    if not name:
        items = []
        for key, path in paths.items():
            with open(path, encoding="utf-8") as fh:
                meta, body = _split_frontmatter(fh.read())
            first = next((ln.lstrip("# ").strip() for ln in body.splitlines() if ln.strip()), "")
            items.append({"name": key, "kind": "skill" if "skills" in path else "reference",
                          "about": (meta.get("description") or first)[:220]})
        return {"playbooks": items, "start_here": "start"}
    key = name.strip().lower()
    if key not in paths:
        raise ValueError(f"No playbook called '{name}'. Call get_playbook with no name to see the list. "
                         f"Example: get_playbook name='start'.")
    with open(paths[key], encoding="utf-8") as fh:
        meta, body = _split_frontmatter(fh.read())
    is_skill = os.sep + "skills" + os.sep in paths[key]
    return {"name": key, "text": (WEB_NOTE if is_skill else "") + body}


# ---------------------------------------------------------------- audit
def _clean_url(url: str) -> str:
    url = (url or "").strip()
    if not url or len(url) > 2000:
        raise ValueError("Give a website address such as https://example.com")
    return url if re.match(r"^https?://", url, re.I) else "https://" + url


def run_audit(url: str, max_pages: int = 15, time_budget: float = 60.0) -> dict:
    max_pages = max(1, min(int(max_pages), MAX_AUDIT_PAGES))
    try:
        audit = sa.crawl(_clean_url(url), max_pages, 0.2, time_budget)
    except SystemExit as err:
        raise ValueError(str(err)) from err
    checks = sa.score(audit)
    summary = sa.summarise(checks)
    problems = [{"level": c["level"], "area": c["area"], "check": c["check"], "detail": c["detail"][:300],
                 "example_urls": c["urls"][:3]} for c in checks if c["level"] != "pass"][:25]
    return {"site": audit["origin"], "pages_checked": audit["crawled"], "health_score": summary["health_score"],
            "subscores": summary["subscores"],
            "counts": {k: summary[k] for k in ("fail", "warn", "pass")},
            "problems": problems,
            "passed": [c["check"] for c in checks if c["level"] == "pass"],
            "limits": "Reads the page text the server sends (no JavaScript is run). Checks up to "
                      f"{max_pages} pages. Private and local addresses are refused."}


# ---------------------------------------------------------------- costs
def quote_cost(items: list[dict]) -> dict:
    if not items or len(items) > 50:
        raise ValueError("Send between 1 and 50 items, each like {\"job\": \"serp_page\", \"units\": 15}.")
    lines, total = [], 0.0
    for item in items:
        job = str(item.get("job", ""))
        spec = PRICES["jobs"].get(job)
        if not spec:
            raise ValueError(f"Unknown job '{job}'. Valid jobs: {', '.join(sorted(PRICES['jobs']))}.")
        try:
            units = float(item.get("units", 0))
            requests = int(item.get("requests", 1))
        except (TypeError, ValueError) as err:
            raise ValueError("'units' must be a number and 'requests' a whole number.") from err
        if not (0 <= units <= 1_000_000) or not (0 <= requests <= 1000):
            raise ValueError("'units' must be 0 to 1,000,000 and 'requests' 0 to 1,000.")
        cost = units * spec["per_unit"] + (requests * spec["per_request"] if units > 0 else 0.0)
        cost += PRICES["start_fee_usd"]
        total += cost
        lines.append({"job": job, "actor": spec["actor"], "units": units, "unit": spec["unit"], "requests": requests,
                      "cost_usd": round(cost, 4)})
    cap = max(0.01, math.ceil(total * CAP_MULTIPLIER * 100) / 100)
    return {"lines": lines, "total_usd": round(total, 4), "suggested_cap_usd": cap,
            "how_to_run": "Tell the user the total, wait for a yes, then call-actor with "
                          f"callOptions.maxTotalChargeUsd = {cap}.",
            "prices_read_on": PRICES["read_on"],
            "heads_up": "Estimates use public prices; Apify may add small platform charges. Re-check prices with "
                        "fetch-actor-details if more than a few days old."}


# ---------------------------------------------------------------- measurement
def normalise_panel(panel: list[dict]) -> dict[str, dict]:
    if not (0 < len(panel) <= MAX_PANEL):
        raise ValueError(f"Send 1-{MAX_PANEL} panel prompts.")
    panel_rows: dict[str, dict] = {}
    for row in panel:
        pid, ptype = str(row.get("prompt_id", "")).strip(), str(row.get("type", "")).strip()
        if not pid or not row.get("prompt") or ptype not in cl.TYPES:
            raise ValueError(f"Each panel prompt needs prompt_id, prompt and type ({', '.join(cl.TYPES)}).")
        panel_rows[pid] = {"prompt_id": pid, "prompt": str(row["prompt"]), "type": ptype, "topic": row.get("topic", "")}
    return panel_rows


def normalise_runs(runs: list[dict], panel_rows: dict[str, dict]) -> list[dict]:
    if not (0 < len(runs) <= MAX_RUNS):
        raise ValueError(f"Send 1-{MAX_RUNS} runs.")
    run_rows, seen = [], set()
    for i, raw in enumerate(runs, 1):
        snapshot = str(raw.get("snapshot", "")).strip()
        if not snapshot:
            raise ValueError(f"Run {i} has no 'snapshot' name (for example 'baseline' or '2026-12').")
        try:
            row = cl.normalise_run(raw, panel_rows, snapshot, i)
        except (ValueError, TypeError) as err:
            raise ValueError(f"Run {i}: {err}") from err
        key = (row["snapshot"], row["prompt_id"], row["platform"], row["repeat"])
        if key in seen:
            raise ValueError(f"Run {i} repeats {key}. Each prompt/engine/repeat appears once per snapshot.")
        seen.add(key)
        run_rows.append(row)
    return run_rows


def normalise_experiments(experiments: list[dict] | None) -> list[dict]:
    experiments = experiments or []
    if len(experiments) > MAX_EXPERIMENTS:
        raise ValueError(f"Send at most {MAX_EXPERIMENTS} experiments.")
    return [{**{c: "" for c in cl.EXP_COLS}, **{k: v for k, v in e.items() if k in cl.EXP_COLS},
             "exp_id": e.get("exp_id") or f"e{n:03d}", "status": e.get("status") or "shipped",
             "recheck_after": e.get("recheck_after") or "9999-12-31"} for n, e in enumerate(experiments, 1)]


def measure_rows(panel_rows: dict[str, dict], run_rows: list[dict], exp_rows: list[dict], baseline: str = "",
                 current: str = "") -> dict:
    """Recommendation Share report from already-normalised rows (used by both fresh input and saved projects)."""
    with tempfile.TemporaryDirectory() as tmp:
        cl.write_csv(os.path.join(tmp, "panel.csv"), cl.PANEL_COLS, list(panel_rows.values()))
        cl.write_csv(os.path.join(tmp, "runs.csv"), cl.RUN_COLS, run_rows)
        cl.write_csv(os.path.join(tmp, "experiments.csv"), cl.EXP_COLS, exp_rows)
        try:
            report = cl.build_report(SimpleNamespace(dir=tmp, baseline=baseline, current=current, json=True))
        except SystemExit as err:
            raise ValueError(str(err)) from err
    report["markdown"] = cl.render(report)
    return report


def measure(panel: list[dict], runs: list[dict], baseline: str = "", current: str = "",
            experiments: list[dict] | None = None) -> dict:
    panel_rows = normalise_panel(panel)
    return measure_rows(panel_rows, normalise_runs(runs, panel_rows), normalise_experiments(experiments),
                        baseline, current)


# ---------------------------------------------------------------- scheduling help
FREQUENCIES = {"daily": ("0 8 * * *", "every day at 08:00"), "weekly": ("0 8 * * 1", "every Monday at 08:00"),
               "monthly": ("0 8 1 * *", "on the 1st of each month at 08:00")}


def schedule_plan(project: str, url: str, frequency: str = "weekly", max_pages: int = 15,
                  panel: list[dict] | None = None, brand: dict | None = None, platforms: list[str] | None = None) -> dict:
    """Plain steps and ready-to-paste inputs for Apify Schedules (a run cannot create schedules for you)."""
    if frequency not in FREQUENCIES:
        raise ValueError(f"frequency must be one of: {', '.join(FREQUENCIES)}. Example: 'weekly'.")
    cron, when = FREQUENCIES[frequency]
    checks_per_month = {"daily": 30, "weekly": 4.33, "monthly": 1}[frequency]
    site_input = {"tool": "scheduled_check", "arguments": {"project": project, "url": _clean_url(url),
                                                           "max_pages": max(1, min(int(max_pages), MAX_AUDIT_PAGES))}}
    plan = {"frequency": frequency, "cron": cron, "when": when,
            "free_site_check": {"actor": "khadinakbar/citebase", "input": site_input,
                                "cost": "Free to call; the small Apify running cost (under a cent) is billed to you.",
                                "what_it_does": "Checks the site, saves the score to your project history and refreshes "
                                                "the report page."},
            "steps": ["Open the Apify Console and go to Schedules, then Create new schedule.",
                      f"Name it, set the cron to `{cron}` ({when}) and your time zone.",
                      "Add an Actor run for each Actor below: pick the Actor, paste its input, set the max cost "
                      "(Run options), and save.",
                      "Turn the schedule on. Results appear in your Apify account."]}
    prompts = [p["prompt"] for p in (panel or []) if p.get("prompt")]
    if prompts and brand and brand.get("name"):
        engines = platforms or ["perplexity", "chatgpt", "gemini"]
        checks = len(prompts) * len(engines)
        per_run = round(checks * PRICES["jobs"]["ai_brand_check"]["per_unit"] + PRICES["start_fee_usd"], 4)
        plan["ai_checks"] = {
            "actor": "khadinakbar/ai-search-brand-monitor",
            "input": {"brandName": brand["name"], "brandDomain": brand.get("domain") or "",
                      "competitors": brand.get("competitors") or [], "platforms": engines, "customQueries": prompts,
                      "querySelectionMode": "custom_only", "maxQueriesPerPlatform": len(prompts)},
            "checks_per_run": checks, "cost_per_run_usd": per_run, "suggested_max_cost_usd": math.ceil(per_run * 1.3 * 100) / 100,
            "estimated_cost_per_month_usd": round(per_run * checks_per_month, 2),
            "after_it_runs": "In chat, say: 'import the latest scheduled AI results for this project'. Citebase "
                             "converts them and adds them to your history."}
    else:
        plan["ai_checks"] = None
        plan["note"] = ("AI-answer checks need the project's question list and brand details. Save results once with "
                        "save_results (including the brand) and ask again.")
    return plan


# ---------------------------------------------------------------- recommendations
# (match on check-name prefix) -> plain-language step
STEP_RULES = [
    ("robots.txt reachable", "Make sure your site's robots file loads", "If it can't load, search engines and AI tools may skip you.", "your web developer", "30 minutes"),
    ("Search + AI crawler access", "Let search engines and AI tools read your site", "Your robots file blocks some of them, so they can't read or recommend you.", "your web developer", "30 minutes"),
    ("HTTP redirects to HTTPS", "Make the secure version (https) the only version", "Visitors and search engines should always land on the secure address.", "your web developer", "1 hour"),
    ("Content present in server HTML", "Make your page text visible without JavaScript", "Many AI tools only read the text the server sends. If it's empty to them, they can't recommend you.", "your web developer", "1 to 3 days"),
    ("Broken internal pages", "Fix pages that show errors", "Broken pages waste visitors' time and search engines' trust.", "you or your developer", "1 to 2 hours"),
    ("Unreachable pages", "Find out why some pages can't be reached", "Pages that don't load can't be found or recommended.", "your web developer", "1 hour"),
    ("XML sitemap", "Add a sitemap", "A sitemap is a list of your pages that helps search engines find them all.", "you or your developer", "1 hour"),
    ("Soft 404", "Make missing pages say 'not found' properly", "Right now missing pages look like real pages to search engines.", "your web developer", "1 hour"),
    ("Title tag present", "Give every page a clear title", "The title is the first thing search results and AI tools read.", "you", "2 hours"),
    ("Title length", "Tidy up page titles (30 to 60 characters)", "Titles that are too long or short get cut off or ignored.", "you", "1 hour"),
    ("Unique title", "Make each page title different", "Repeated titles make pages look like copies of each other.", "you", "1 hour"),
    ("Exactly one H1", "Give every page one main headline", "One clear headline tells readers and search engines what the page is about.", "you", "1 hour"),
    ("Meta description present", "Write a short summary for each page", "It's the line shown under your link in search results. Low priority.", "you", "2 hours"),
    ("Mobile viewport", "Make the site work properly on phones", "Most visitors use phones; search engines judge the phone version.", "your web developer", "1 hour"),
    ("Canonical tag", "Tell search engines which address is the main one for each page", "It stops duplicate versions from competing with each other.", "your web developer", "1 hour"),
    ("Thin content", "Add real, useful detail to short pages", "Very short pages rarely get picked up or recommended.", "you", "a few hours per page"),
    ("Image alt text", "Describe your images in words", "It helps search engines and people using screen readers.", "you", "1 to 2 hours"),
    ("Entity schema", "Add your business details as hidden page data", "Tells machines who you are. Helps rich search results; no proof yet that it helps AI recommend you.", "your web developer", "1 hour"),
    ("JSON-LD structured data", "Add structured page data (low priority)", "Helps rich search results. A controlled test found no AI-recommendation boost from it, so do it after the basics.", "your web developer", "a few hours"),
    ("Weak internal linking", "Link to your orphan pages from other pages", "Pages nobody links to are hard to find.", "you", "1 hour"),
]


def _rule_for(check: str):
    return next((r for r in STEP_RULES if check.startswith(r[0])), None)


def next_steps(audit: dict | None = None, report: dict | None = None, max_steps: int = 5) -> dict:
    max_steps = max(1, min(int(max_steps), 10))
    steps: list[dict] = []
    for prob in sorted((audit or {}).get("problems", []), key=lambda p: (p.get("level") != "fail",)):
        rule = _rule_for(str(prob.get("check", "")))
        steps.append({"step": rule[1] if rule else f"Look into: {prob.get('check')}",
                      "why": rule[2] if rule else str(prob.get("detail", ""))[:200],
                      "who": rule[3] if rule else "you or your developer",
                      "effort": rule[4] if rule else "unknown",
                      "urgency": "do first" if prob.get("level") == "fail" else "soon",
                      "based_on": f"site check: {prob.get('check')}"})
    if report:
        overall = (report.get("summary") or {}).get("all")
        if overall:
            share = overall.get("recommendation_share", 0)
            if share < 0.2:
                steps.append({"step": "Get your brand onto the pages AI already trusts for your topic",
                              "why": f"AI recommends you in about {share * 100:.0f}% of answers. Lists, review sites and "
                                     "community answers it already cites are the fastest way in.",
                              "who": "you, with Claude's help", "effort": "a few hours per week",
                              "urgency": "do first", "based_on": "AI recommendation results"})
            ctrl = overall.get("control_false_positive")
            if ctrl:
                steps.append({"step": "Treat the AI results with care", "why": "The test questions that should not mention you did. "
                              "The measurements are noisy.", "who": "Claude", "effort": "a re-run",
                              "urgency": "soon", "based_on": "control questions"})
        for due in report.get("due", []):
            steps.append({"step": f"Re-measure: {due}", "why": "Enough time has passed to see if the change worked.",
                          "who": "Claude", "effort": "about 15 minutes", "urgency": "now", "based_on": "experiment log"})
    rank = {"now": 0, "do first": 1, "soon": 2}
    steps.sort(key=lambda s: rank.get(s["urgency"], 3))
    steps = steps[:max_steps]
    steps.append({"step": "Check again in 30 days", "why": "Changes take weeks to show up. A repeat check tells you what worked.",
                  "who": "Claude", "effort": "about 15 minutes", "urgency": "later", "based_on": "habit"})
    return {"steps": steps, "tip": "Do the first one or two before anything else. Ask Claude to explain any step in simpler words."}


# ---------------------------------------------------------------- outreach checks
SPAM_WORDS = ("act now", "guaranteed", "100% free", "risk-free", "limited time", "click here", "buy now", "winner",
              "make money", "no obligation")
OPT_OUT = re.compile(r"unsubscribe|opt[- ]?out|not interested|no thanks|let me know if you'd rather|stop (?:receiving|emailing)",
                     re.I)


def check_outreach_draft(to: list[str] | str, subject: str, body: str, suppressed: list[str] | None = None,
                         sent_today: int = 0, daily_cap: int = 20) -> dict:
    problems: list[str] = []
    warnings: list[str] = []
    probe = {"to": to, "subject": subject, "body": body}
    addresses = st.recipients(probe)
    if not addresses or st.unparsed_recipients(probe):
        problems.append("Each recipient must be a plain address like name@company.com.")
    rules = [r for r in (st.normalise_rule(s) for s in (suppressed or [])) if r]
    blocked = [a for a in addresses if st.is_suppressed(a, rules)]
    if blocked:
        problems.append(f"On your do-not-contact list: {', '.join(blocked)}. Do not email them.")
    if sent_today + max(1, len(addresses)) > daily_cap:
        problems.append(f"This would pass your daily limit of {daily_cap} emails ({sent_today} already sent).")
    if not (body or "").strip():
        problems.append("The email body is empty.")
    if re.search(r"\[[^\]\n]{1,60}\]", f"{subject}\n{body}"):
        problems.append("There are unfilled [brackets] left in the text. Fill them with real details.")
    words = len(re.findall(r"\b\w+\b", body or ""))
    if words < 40 or words > 120:
        warnings.append(f"The email is {words} words. Short emails (about 60 to 90 words) get more replies.")
    if len(subject or "") > 60 or (subject or "").isupper() or "!!" in (subject or ""):
        warnings.append("Make the subject short, calm and specific (under 60 characters, no shouting).")
    if len(re.findall(r"https?://", body or "")) > 2:
        warnings.append("More than two links can send the email to spam. Keep one.")
    hits = [w for w in SPAM_WORDS if w in f"{subject} {body}".lower()]
    if hits:
        warnings.append(f"Spammy phrases found: {', '.join(hits)}.")
    if not OPT_OUT.search(body or ""):
        warnings.append("Add a simple way to say no (for example: 'If this isn't relevant, just tell me and I won't write again').")
    return {"ready": not problems, "problems": problems, "warnings": warnings, "recipients": addresses,
            "word_count": words, "fingerprint": st.draft_hash(probe)[:12],
            "next": "Show the user the final text and send it only after they say yes. Send exactly this text; "
                    "any change needs a new check and a new yes."}


# ---------------------------------------------------------------- one-shot dispatch (Actor run mode)
DISPATCH = {
    "get_playbook": lambda a: get_playbook(a.get("name")),
    "audit_site": lambda a: run_audit(a.get("url", ""), a.get("max_pages", 15)),
    "quote_cost": lambda a: quote_cost(a.get("items") or []),
    "measure_recommendation_share": lambda a: measure(a.get("panel") or [], a.get("runs") or [], a.get("baseline", ""),
                                                      a.get("current", ""), a.get("experiments")),
    "next_steps": lambda a: next_steps(a.get("audit"), a.get("report"), a.get("max_steps", 5)),
    "check_outreach_draft": lambda a: check_outreach_draft(a.get("to", []), a.get("subject", ""), a.get("body", ""),
                                                           a.get("suppressed"), a.get("sent_today", 0),
                                                           a.get("daily_cap", 20)),
}
ALLOWED_ARGS = {
    "get_playbook": {"name"}, "audit_site": {"url", "max_pages"}, "quote_cost": {"items"},
    "measure_recommendation_share": {"panel", "runs", "baseline", "current", "experiments"},
    "next_steps": {"audit", "report", "max_steps"},
    "check_outreach_draft": {"to", "subject", "body", "suppressed", "sent_today", "daily_cap"},
}


def dispatch(tool: str, arguments: dict | None) -> dict:
    """Runs one tool by name. Raises ValueError with a plain-language fix for bad input."""
    if tool not in DISPATCH:
        raise ValueError(f"Unknown tool '{tool}'. Choose one of: {', '.join(sorted(DISPATCH))}. "
                         "Example: tool 'get_playbook' with arguments {}.")
    args = arguments if isinstance(arguments, dict) else {}
    extra = sorted(set(args) - ALLOWED_ARGS[tool])
    if extra:
        raise ValueError(f"'{tool}' does not take {', '.join(extra)}. It takes: {', '.join(sorted(ALLOWED_ARGS[tool]))}.")
    try:
        return DISPATCH[tool](args)
    except (TypeError, AttributeError, KeyError) as err:
        raise ValueError(f"The inputs for '{tool}' are the wrong shape ({type(err).__name__}). "
                         f"It takes: {', '.join(sorted(ALLOWED_ARGS[tool]))}.") from err
