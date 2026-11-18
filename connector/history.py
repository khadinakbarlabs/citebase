"""Project history: save results and audits, load them back, show trends.

All data goes through storage.get_backend(), i.e. into the running account's own store. Nothing here talks to
any other account. Rows are saved already normalised, so later reports reuse the same maths as fresh input.

Write order matters: everything is validated first, round records are written next and `meta` last. `meta` only
holds names, dates and brand details; the list of rounds is also read back from the `runs.*` keys, so a save that
stops half way never hides data that was written.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import re
from typing import Any

import insights
import storage as stg
import tools

cl = tools.cl  # tools puts the shared scripts folder on the import path

MAX_AUDIT_PROBLEMS = 25  # every problem a site check returns, so the next check can say what was fixed
MAX_AUDITS = 90
MAX_TEXT = 300
RECHECK_DAYS = 30
BRAND_KEYS = ("name", "domain", "competitors", "aliases", "site")
SETTINGS_KEYS = ("country", "language", "device", "frequency")  # asked once, then reused by every later check
# These values become Actor input and plan text, so only plain codes are accepted (never free text from a page).
SETTINGS_RULES = {"country": (r"[a-z]{2}", "a two-letter country code, for example 'gb'"),
                  "language": (r"[a-z]{2,3}(-[a-z0-9]{2,4})?", "a language code, for example 'en' or 'pt-br'"),
                  "device": (r"desktop|mobile|tablet", "'desktop', 'mobile' or 'tablet'")}
TODO_STATES = ("open", "done", "skipped")
MAX_TODO = 40
MAX_IMPORT_IDS = 40
_locks: dict[str, asyncio.Lock] = {}


def lock_for(slug: str) -> asyncio.Lock:
    """One writer at a time per project inside this process (a second Standby instance is not covered)."""
    return _locks.setdefault(slug, asyncio.Lock())


def today() -> str:
    return dt.date.today().isoformat()


def _by_id(panel: list[dict]) -> dict[str, dict]:
    return {p["prompt_id"]: p for p in panel}


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value if value is not None else "")[:limit]


def clean_brand(brand: dict | None) -> dict:
    out: dict[str, Any] = {}
    for key in BRAND_KEYS:
        value = (brand or {}).get(key)
        if key in ("competitors", "aliases"):
            if isinstance(value, list):
                out[key] = [_text(v, 80) for v in value[:20] if v]
        elif value:
            out[key] = _text(value, 200)
    return out


def clean_settings(settings: dict | None) -> dict:
    """Country, language, device and check frequency as short plain text. Unknown keys are dropped."""
    if not isinstance(settings, dict):
        return {}
    out = {key: _text(settings[key], 40).strip().lower() for key in SETTINGS_KEYS if settings.get(key)}
    for key, (pattern, example) in SETTINGS_RULES.items():
        if key in out and not re.fullmatch(pattern, out[key]):
            raise ValueError(f"settings.{key} must look like {example}.")
    if out.get("frequency") and out["frequency"] not in tools.FREQUENCIES:
        raise ValueError(f"settings.frequency must be one of: {', '.join(tools.FREQUENCIES)}. Example: 'monthly'.")
    return out


def clean_todo(todo: list[dict] | None) -> list[dict]:
    """To-do updates: [{step, status}] with status open, done or skipped. Raises ValueError for anything else."""
    if not todo:
        return []
    if not isinstance(todo, list) or len(todo) > MAX_TODO:
        raise ValueError(f"Send at most {MAX_TODO} to-do items, each like {{\"step\": \"Add a sitemap\", \"status\": \"done\"}}.")
    out = []
    for n, raw in enumerate(todo, 1):
        step = _text((raw or {}).get("step") if isinstance(raw, dict) else "", 200).strip()
        status = str((raw or {}).get("status") or "open").strip().lower() if isinstance(raw, dict) else ""
        if not step or status not in TODO_STATES:
            raise ValueError(f"To-do item {n} needs a 'step' (plain words) and a 'status' of {', '.join(TODO_STATES)}.")
        out.append({"step": step, "status": status, "updated": today()})
    return out


def merge_todo(current: list[dict], updates: list[dict]) -> list[dict]:
    """Updates replace the item with the same step text; new steps are added; the newest MAX_TODO are kept."""
    merged = {item["step"].lower(): item for item in current if isinstance(item, dict) and item.get("step")}
    for item in updates:
        merged[item["step"].lower()] = item
    return list(merged.values())[-MAX_TODO:]


def similar_names(slug: str, known: list[str]) -> list[str]:
    """Saved project names that look like a misspelling of `slug` (never `slug` itself)."""
    return difflib.get_close_matches(slug, [k for k in known if k != slug], n=3, cutoff=0.8)


def has_time(stamp: Any) -> bool:
    """True for a full timestamp such as '2026-11-06T10:00:00Z'. A bare date is not enough to tell two repeats apart."""
    text = str(stamp or "")
    return len(text) > 10 and (":" in text)


def answer_key(row: dict) -> tuple:
    """What makes two saved answers the same answer: question, engine, exact time and where it was asked from."""
    return (row["prompt_id"], row["platform"], row.get("answered_at"), row.get("country") or "",
            row.get("language") or "", row.get("device") or "")


def clean_experiments(experiments: list[dict] | None) -> list[dict]:
    if not experiments:
        return []
    if len(experiments) > tools.MAX_EXPERIMENTS:
        raise ValueError(f"Send at most {tools.MAX_EXPERIMENTS} changes at a time.")
    out = []
    for n, raw in enumerate(experiments, 1):
        if not isinstance(raw, dict) or not str(raw.get("action") or "").strip():
            raise ValueError(f"Change {n} needs an 'action' (what you changed, in plain words).")
        row = {k: _text(raw.get(k), 500) for k in cl.EXP_COLS if raw.get(k) is not None}
        row["date"] = row.get("date") or today()
        if not row.get("recheck_after") and (shipped := cl.parse_date(row["date"])):
            row["recheck_after"] = (shipped + dt.timedelta(days=RECHECK_DAYS)).isoformat()  # same default as the CLI
        out.append(row)
    return out


def clean_audit(audit: Any) -> dict:
    """Keeps only the fields reports use, with safe types and sizes. Raises ValueError for anything else."""
    if not isinstance(audit, dict):
        raise ValueError("audit must be the result object returned by audit_site, passed as is.")
    score = audit.get("health_score")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise ValueError("audit.health_score must be a number from 0 to 100. Pass the audit_site result unchanged.")
        score = int(round(score))

    def numbers(value: Any, limit: int) -> dict[str, int | None]:
        if not isinstance(value, dict):
            return {}
        return {_text(k, 40): (int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
                for k, v in list(value.items())[:limit]}

    problems = []
    for p in (audit.get("problems") or [])[:MAX_AUDIT_PROBLEMS]:
        if isinstance(p, dict):
            problems.append({"check": _text(p.get("check"), 120), "detail": _text(p.get("detail")),
                             "level": _text(p.get("level"), 10), "area": _text(p.get("area"), 30)})
    pages = audit.get("pages_checked")
    passed = audit.get("passed") if isinstance(audit.get("passed"), list) else []
    return {"site": _text(audit.get("site"), 200), "health_score": score, "subscores": numbers(audit.get("subscores"), 10),
            "counts": numbers(audit.get("counts"), 5),
            "pages_checked": int(pages) if isinstance(pages, (int, float)) and not isinstance(pages, bool) else None,
            "status": _text(audit.get("status") or "ok", 12),
            "problems": problems, "passed": [_text(name, 120) for name in passed[:80]]}


def compare_audits(previous: dict | None, record: dict) -> dict | None:
    """What changed since the last site check: problems that are gone, new ones, and ones still open.

    A problem counts as fixed only when the newer check ran that check and it passed. A check that simply did not
    run this time (fewer pages read, or an older record without a pass list) is left out instead of being called fixed."""
    if not previous:
        return None
    before = [p["check"] for p in previous.get("problems") or [] if p.get("check")]
    now = [p["check"] for p in record.get("problems") or [] if p.get("check")]
    passed = set(record.get("passed") or [])
    out = {"since": previous.get("date"),
           "fixed": [c for c in before if c in passed],
           "new": [c for c in now if c not in before],
           "still_open": [c for c in now if c in before]}
    if "passed" not in previous:
        # Checks saved by older versions kept only their first ten problems, so a problem missing from that list
        # may simply not have been stored. Say so instead of calling it new.
        out["new"] = []
        out["note"] = ("The earlier check was saved in a shorter form, so new problems cannot be told apart this "
                       "time. The next check will show them.")
    return out


async def list_projects() -> list[str]:
    be = await stg.get_backend()
    return sorted({k[len(stg.KEY_PREFIX):].split(".", 1)[0] for k in await be.keys(stg.KEY_PREFIX)})


def unknown_project(slug: str, known: list[str]) -> str:
    """One plain sentence for a project name that is not saved, with the closest saved names first."""
    close = similar_names(slug, known)
    listed = close + [k for k in known if k not in close]
    hint = f"Did you mean '{close[0]}'? " if close else ""
    return (f"No saved project called '{slug}'. {hint}" + (f"Saved projects: {', '.join(listed[:10])}. " if listed else "")
            + "Save results first with save_results, or check the name.")


async def _require_project(slug: str) -> dict:
    be = await stg.get_backend()
    meta = await be.get(stg.key(slug, "meta"))
    if not meta:
        raise ValueError(unknown_project(slug, await list_projects()))
    return meta


def check_frozen(stored_panel: list[dict] | None, panel_rows: dict[str, dict]) -> None:
    """Refuses a question list that differs from the one already saved for the project."""
    if stored_panel and cl.panel_hash(_by_id(stored_panel)) != cl.panel_hash(panel_rows):
        raise ValueError("This project's question list is frozen: results are only comparable while the "
                         "questions stay identical. Use a new project name for a different list.")


async def save_results(project: str, runs: list[dict], panel: list[dict] | None = None,
                       experiments: list[dict] | None = None, brand: dict | None = None,
                       replace: bool = False, append: bool = False, settings: dict | None = None,
                       todo: list[dict] | None = None, source_ids: list[str] | None = None) -> dict:
    slug = stg.clean_slug(project)
    async with lock_for(slug):
        return await _save_results(slug, runs, panel, experiments, brand, replace, append, settings, todo,
                                   source_ids)


async def _save_results(slug: str, runs: list[dict], panel: list[dict] | None, experiments: list[dict] | None,
                        brand: dict | None, replace: bool, append: bool, settings: dict | None = None,
                        todo: list[dict] | None = None, source_ids: list[str] | None = None) -> dict:
    be = await stg.get_backend()
    meta = await be.get(stg.key(slug, "meta"))
    created = meta is None
    others = [p for p in await list_projects() if p != slug] if created else []
    if created and len(others) >= stg.MAX_PROJECTS:
        raise ValueError(f"You already have {stg.MAX_PROJECTS} saved projects. Reuse one of them.")
    stored_panel = await be.get(stg.key(slug, "panel"))
    if panel:
        panel_rows = tools.normalise_panel(panel)
        check_frozen(stored_panel, panel_rows)
    elif stored_panel:
        panel_rows = _by_id(stored_panel)
    elif runs:
        raise ValueError("Send the question list (panel) the first time you save results for a project. It can also be "
                         "saved on its own, before any results, so the first round can be imported instead of retyped.")
    else:
        panel_rows = {}
    # clean round names BEFORE checking for repeats, so '2026 12' and '2026-12' cannot sneak in as two rounds
    cleaned = [{**r, "snapshot": stg.clean_part(r.get("snapshot"))} for r in runs]
    rows = tools.normalise_runs(cleaned, panel_rows) if runs else []
    new_experiments = clean_experiments(experiments)
    new_brand = clean_brand(brand)
    new_settings = clean_settings(settings)
    new_todo = clean_todo(todo)
    if not (rows or panel or new_experiments or new_brand or new_settings or new_todo):
        raise ValueError("Nothing to save: send results (runs), the question list (panel), brand details, settings, "
                         "to-do updates or logged changes.")

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["snapshot"], []).append(r)
    meta = meta or {"project": slug, "created": today(), "brand": {}, "snapshots": {}}
    known = set(meta["snapshots"]) | {k[len(stg.key(slug, "runs")) + 1:] for k in await be.keys(stg.key(slug, "runs") + ".")}
    if len(known | set(groups)) > stg.MAX_SNAPSHOTS:
        raise ValueError(f"A project can hold {stg.MAX_SNAPSHOTS} rounds and this one is full. Nothing was saved. "
                         "Start a new project with the same question list and brand (for example the same name with "
                         "the year added); the old one stays readable for comparison.")

    # 1) validate every round and build what will be written; nothing is stored yet
    to_write: dict[str, list[dict]] = {}
    notes: list[str] = []
    for label, new_rows in groups.items():
        existing = await be.get(stg.key(slug, "runs", label))
        if existing and not (append or replace):
            raise ValueError(f"Round '{label}' already has saved results. Pass append=true to add more repeats, or "
                             "replace=true to overwrite it. Nothing was saved.")
        if existing and append and not replace:
            top: dict[tuple[str, str], int] = {}
            for r in existing:
                k = (r["prompt_id"], r["platform"])
                top[k] = max(top.get(k, 0), int(r["repeat"]))
            # The same answers sent twice (a retry after a slow save) must not count twice: an answer already saved
            # for this question and engine at the same moment is left out.
            seen = {answer_key(r) for r in existing if has_time(r.get("answered_at"))}
            fresh = [r for r in new_rows if not (has_time(r.get("answered_at")) and answer_key(r) in seen)]
            if len(fresh) < len(new_rows):
                notes.append(f"Round '{label}': {len(new_rows) - len(fresh)} answers were already saved and were not "
                             "added again.")
            if not fresh:
                continue
            notes += [f"Round '{label}': {w}" for w in cl.context_warnings(
                cl.round_context(existing, label), cl.round_context(fresh, label), "saved", "new",
                "between the saved answers and these new ones", "the saved answers", "the new answers")]
            new_rows = existing + [{**r, "repeat": int(r["repeat"]) + top.get((r["prompt_id"], r["platform"]), 0)}
                                   for r in fresh]
        to_write[label] = new_rows

    # 2) write rounds, then the question list, then meta last
    imports = meta.setdefault("imports", {})
    for label, new_rows in to_write.items():
        await be.set(stg.key(slug, "runs", label), new_rows)
        meta["snapshots"].setdefault(label, today())  # first save date; appending never moves a round in time
        kept = [] if replace else list(imports.get(label) or [])  # a replaced round holds none of its old datasets
        if source_ids or replace:
            imports[label] = list(dict.fromkeys([*kept, *(source_ids or [])]))[-MAX_IMPORT_IDS:]
    if not stored_panel and panel_rows:
        await be.set(stg.key(slug, "panel"), list(panel_rows.values()))
    if new_experiments:
        current = await be.get(stg.key(slug, "experiments")) or []
        for e in new_experiments:
            if not any(x["action"] == e["action"] and x["date"] == e["date"] for x in current):
                if len(current) >= tools.MAX_EXPERIMENTS:
                    raise ValueError(f"A project can log {tools.MAX_EXPERIMENTS} changes. The rounds were saved; "
                                     "start a new project to log more.")
                current.append({**e, "exp_id": f"e{len(current) + 1:03d}"})
        await be.set(stg.key(slug, "experiments"), current)
    if new_brand:
        meta["brand"] = {**meta.get("brand", {}), **new_brand}
    if new_settings:
        meta["settings"] = {**meta.get("settings", {}), **new_settings}
    if new_todo:
        meta["todo"] = merge_todo(meta.get("todo") or [], new_todo)
    meta["updated"] = today()
    await be.set(stg.key(slug, "meta"), meta)
    return {"project": slug, "snapshots_saved": {k: len(v) for k, v in to_write.items()},
            "panel_prompts": len(panel_rows), "snapshots_in_project": sorted(meta["snapshots"]),
            "brand": meta.get("brand", {}), "settings": meta.get("settings", {}), "todo": meta.get("todo", []),
            "created": created, "stored_in": "your own Apify account (key-value store 'citebase-projects')",
            "warnings": [*new_project_warnings(slug, created, others), *cl.panel_warnings(panel_rows, meta.get("brand")),
                         *notes]}


def new_project_warnings(slug: str, created: bool, others: list[str]) -> list[str]:
    """Says so when a save started a NEW project whose name looks like a misspelling of a saved one."""
    close = similar_names(slug, others) if created else []
    if not close:
        return []
    return [f"This started a NEW project called '{slug}'. You already have '{close[0]}'. If you meant that one, say so "
            "and save again under its name."]


def checked_audit(audit: Any) -> dict:
    """A site check ready to store, dated today. Raises ValueError for a wrong shape or a check that read nothing."""
    record = {"date": today(), **clean_audit(audit)}
    if record["health_score"] is None and record["status"] == "unreadable":
        raise ValueError("That site check could not read the site, so there is nothing to save. Fix the address or let "
                         "crawlers in, then check again.")
    return record


async def save_audit(project: str, audit: dict) -> dict:
    slug = stg.clean_slug(project)
    record = checked_audit(audit)  # validate before anything is stored
    async with lock_for(slug):
        be = await stg.get_backend()
        meta = await be.get(stg.key(slug, "meta"))
        created = meta is None
        others = [p for p in await list_projects() if p != slug] if created else []
        if created and len(others) >= stg.MAX_PROJECTS:
            raise ValueError(f"You already have {stg.MAX_PROJECTS} saved projects. Reuse one of them.")
        meta = meta or {"project": slug, "created": today(), "brand": {}, "snapshots": {}}
        keys = await be.keys(stg.key(slug, "audit") + ".")  # dated keys, oldest first
        previous = None
        earlier = [k for k in keys if not k.endswith("." + record["date"])]
        if earlier:
            previous = await be.get(earlier[-1])
        trend = None
        if previous and previous.get("health_score") is not None and record["health_score"] is not None:
            trend = {"previous_date": previous.get("date"), "previous_score": previous["health_score"],
                     "change": record["health_score"] - previous["health_score"]}
        today_key = stg.key(slug, "audit", record["date"])
        replaced = await be.get(today_key) if today_key in keys else None  # an earlier check from the same day
        await be.set(today_key, record)
        keys = sorted(set(keys) | {today_key})
        for old in keys[:-MAX_AUDITS]:  # keep the newest MAX_AUDITS checks
            await be.delete(old)
        meta.setdefault("brand", {}).setdefault("site", record["site"])
        meta["last_audit"] = {"date": record["date"], "health_score": record["health_score"]}
        meta["updated"] = today()
        await be.set(stg.key(slug, "meta"), meta)
    return {"project": slug, "saved_on": record["date"], "trend": trend, "created": created,
            "changes": compare_audits(replaced or previous, record),
            "warnings": new_project_warnings(slug, created, others)}


MAX_QUESTION_VIEW = 80
SIGNAL_KINDS = ("bots", "traffic", "ranks", "search")
MAX_SIGNALS = 24  # per kind: two years of monthly pastes


async def save_signal(project: str, kind: str, summary: dict) -> dict:
    """Keeps one dated summary of a pasted server log ('bots') or analytics export ('traffic') with the project.
    Only the counts are stored: the pasted text itself is never kept."""
    if kind not in SIGNAL_KINDS:
        raise ValueError(f"Unknown signal '{kind}'.")
    slug = stg.clean_slug(project)
    async with lock_for(slug):
        be = await stg.get_backend()
        meta = await be.get(stg.key(slug, "meta"))
        created = meta is None
        others = [p for p in await list_projects() if p != slug] if created else []
        if created and len(others) >= stg.MAX_PROJECTS:
            raise ValueError(f"You already have {stg.MAX_PROJECTS} saved projects. Reuse one of them.")
        meta = meta or {"project": slug, "created": today(), "brand": {}, "snapshots": {}}
        prefix = stg.key(slug, "signal", kind) + "."
        keys = await be.keys(prefix)
        earlier = [k for k in keys if not k.endswith("." + today())]
        previous = await be.get(earlier[-1]) if earlier else None
        record = {"date": today(), **summary}
        same_day = await be.get(prefix + today()) if kind == "ranks" else None
        if same_day and same_day.get("rows"):
            # a second save today adds to the first (Google rows, then Bing rows); a repeated keyword is replaced
            merged = {(r["keyword"], r["engine"], r.get("country", "")): r for r in same_day["rows"]}
            merged.update({(r["keyword"], r["engine"], r.get("country", "")): r for r in summary["rows"]})
            record = {"date": today(), **insights.summarise_ranks(list(merged.values()))}
        await be.set(prefix + today(), record)
        for old in sorted(set(keys) | {prefix + today()})[:-MAX_SIGNALS]:
            await be.delete(old)
        meta["updated"] = today()
        await be.set(stg.key(slug, "meta"), meta)
    return {"saved_on": record["date"], "previous": previous, "created": created, "record": record,
            "warnings": new_project_warnings(slug, created, others)}


async def latest_signals(slug: str) -> dict[str, list[dict]]:
    """Every saved summary per kind, oldest first: {'bots': [...], 'traffic': [...]}."""
    be = await stg.get_backend()
    out: dict[str, list[dict]] = {}
    for kind in SIGNAL_KINDS:
        keys = await be.keys(stg.key(slug, "signal", kind) + ".")
        out[kind] = [r for r in await asyncio.gather(*[be.get(k) for k in keys]) if r]
    return out


def signal_lines(signals: dict[str, list[dict]]) -> list[str]:
    """Short history lines for the newest bot log and traffic export, with the change since the one before."""
    lines: list[str] = []
    bots = signals.get("bots") or []
    if bots and "bots" in bots[-1]:
        now = bots[-1]
        names = ", ".join(f"{b['bot']} ({b['requests']})" for b in now["bots"] if b["kind"] == "answer")[:300]
        lines += ["", f"AI bot visits (server log read {now['date']}, covering {now['period']['from']} to "
                      f"{now['period']['to']}): {now['answer_bot_requests']} requests from answer bots"
                      + (f": {names}." if names else ".")]
        lines += [f"- {finding}" for finding in now.get("findings", [])[:4]]
    traffic = signals.get("traffic") or []
    if traffic and "ai_visits" in traffic[-1]:
        now = traffic[-1]
        share = f" ({100 * now['ai_share']:.1f}% of all visits)" if now.get("ai_share") is not None else ""
        line = f"Visits from AI assistants (export read {now['date']}): {now['ai_visits']}{share}."
        if len(traffic) > 1 and "ai_visits" in traffic[-2]:
            line += f" The export before that ({traffic[-2]['date']}) showed {traffic[-2]['ai_visits']}."
        lines += ["", line]
        if now.get("by_month"):
            lines += ["", "| Month | Visits from AI | All visits |", "|---|---|---|"]
            lines += [f"| {m['month']} | {m['ai_visits']} | {m['all_visits']} |" for m in now["by_month"][-12:]]
    search = (signals.get("search") or [])
    if search and "impressions" in search[-1]:
        now = search[-1]
        lines += ["", f"Google searches (Search Console export read {now['date']}): {now['clicks']} clicks, "
                      f"{now['impressions']} views."]
        lines += [f"- {finding}" for finding in now.get("findings", [])[:3]]
    ranks = [r for r in signals.get("ranks") or [] if "rows" in r]
    if ranks:
        moves = insights.rank_changes(ranks)
        lines += ["", f"Search positions (saved {ranks[-1]['date']}): {ranks[-1]['top_10']} of {ranks[-1]['keywords']} "
                      f"keywords in the top 10, {ranks[-1]['not_found']} not found.",
                  "", "| Keyword | Where | Now | Before |", "|---|---|---|---|"]
        lines += [f"| {m['keyword'].replace('|', '/')} | {m['engine']} | {m['now'] if m['now'] is not None else 'not found'} | "
                  f"{(m['before'] if m['before'] is not None else 'not found') if m['checked_before'] else 'new'} |"
                  for m in moves[:20]]
    return lines


def ranks_view(records: list[dict]) -> dict | None:
    """The newest saved search positions with the move since the ones before, or None when none are saved."""
    records = [r for r in records if "rows" in r]
    if not records:
        return None
    now = records[-1]
    return {"saved_on": now["date"], "previous_date": records[-2]["date"] if len(records) > 1 else None,
            "keywords": now["keywords"], "top_3": now["top_3"], "top_10": now["top_10"], "not_found": now["not_found"],
            "positions": insights.rank_changes(records)}


async def load_meta(project: str) -> dict:
    """A saved project's details (brand, settings, to-dos, round dates). Raises ValueError when it is not saved."""
    return await _require_project(stg.clean_slug(project))


async def latest_audit(project: str) -> dict | None:
    """The newest saved site check of a project, or None. Raises ValueError when the project is not saved."""
    slug = stg.clean_slug(project)
    await _require_project(slug)
    be = await stg.get_backend()
    keys = await be.keys(stg.key(slug, "audit") + ".")
    return await be.get(keys[-1]) if keys else None


async def load_project(project: str) -> dict[str, Any]:
    be = await stg.get_backend()
    slug = stg.clean_slug(project)
    meta = await _require_project(slug)
    runs_prefix = stg.key(slug, "runs")
    in_meta = list(meta.get("snapshots", {}))  # save order
    found = {k[len(runs_prefix) + 1:] for k in await be.keys(runs_prefix + ".")}
    labels = in_meta + sorted(found - set(in_meta))  # rounds meta lost track of come last
    audit_keys = await be.keys(stg.key(slug, "audit") + ".")
    panel, exps, *fetched = await asyncio.gather(
        be.get(stg.key(slug, "panel")), be.get(stg.key(slug, "experiments")),
        *[be.get(stg.key(slug, "runs", label)) for label in labels], *[be.get(k) for k in audit_keys])
    run_rows: list[dict] = []
    answered: dict[str, str] = {}
    for label, rows in zip(labels, fetched[:len(labels)]):
        run_rows += rows or []
        answered[label] = max((str(r.get("date") or "") for r in rows or []), default="")
    # A round that `meta` lost track of (a save that stopped half way) is dated by its own answers. Falling back to
    # the project's creation date would sort the newest round first and make an old one look current.
    snapshots = {label: meta.get("snapshots", {}).get(label) or answered[label] or today() for label in labels}
    return {"slug": slug, "meta": {**meta, "snapshots": snapshots}, "panel": panel or [], "runs": run_rows,
            "experiments": exps or [], "audits": [a for a in fetched[len(labels):] if a]}


def snapshot_trend(data: dict) -> list[dict]:
    panel = _by_id(data["panel"])
    out = []
    # oldest first by first-save date; rounds first saved on the same day keep the order they were saved in
    for label, saved_on in sorted(data["meta"].get("snapshots", {}).items(), key=lambda kv: kv[1]):
        s = cl.snapshot_summary(data["runs"], panel, label, None)
        if s:
            context = cl.compact_context(cl.round_context(data["runs"], label))
            recorded = any(len(entry) > 1 for entry in context.values())
            out.append({"snapshot": label, "saved_on": saved_on, "prompts": s["prompts"],
                        "engines": sorted(context), "context": context if recorded else {},
                        "recommendation_share": s["recommendation_share"], "rs_low": s["rs_low"], "rs_high": s["rs_high"],
                        "mentioned_rate": s["mentioned_rate"], "cited_rate": s["cited_rate"],
                        "reputation_share": s["reputation_share"], "reputation_prompts": s["reputation_prompts"],
                        "metric_version": s["metric_version"], "older_metric": s["older_metric"],
                        "by_engine": _by_engine(data["runs"], panel, label, sorted(context))})
    return out


def _by_engine(runs: list[dict], panel: dict, label: str, engines: list[str]) -> dict:
    """The same headline numbers for each engine on its own, so a chart can show which engine moved."""
    out = {}
    for name in engines:
        s = cl.snapshot_summary(runs, panel, label, name)
        if s:
            out[name] = {"prompts": s["prompts"], "recommendation_share": s["recommendation_share"], "rs_low": s["rs_low"],
                         "rs_high": s["rs_high"], "mentioned_rate": s["mentioned_rate"], "cited_rate": s["cited_rate"]}
    return out


def question_view(data: dict, snaps: list[dict]) -> list[dict]:
    """Each test question in the latest round, with how many answers recommended the brand there and in the round
    before. Lets a page show which questions were won, lost or never won."""
    if not snaps:
        return []
    now = insights.question_breakdown(data["runs"], data["panel"], snaps[-1]["snapshot"])
    before = {q["prompt_id"]: q for q in insights.question_breakdown(data["runs"], data["panel"], snaps[-2]["snapshot"])} \
        if len(snaps) > 1 else {}
    out = []
    for q in now[:MAX_QUESTION_VIEW]:
        prev = before.get(q["prompt_id"])
        out.append({**q, "before": {"answers": prev["answers"], "recommended": prev["recommended"]} if prev else None})
    return out


def _due(last: str | None, days: int = RECHECK_DAYS) -> str | None:
    """The date a re-check is due, `days` after the last one, or None when there is no usable date."""
    then = cl.parse_date(last or "")
    return (then + dt.timedelta(days=days)).isoformat() if then else None


def due_lines(meta: dict) -> list[str]:
    """Plain lines for checks that are due today or overdue, so a returning user is told what to do first."""
    out = []
    audit_due = _due((meta.get("last_audit") or {}).get("date"))
    if audit_due and audit_due <= today():
        out.append(f"Site check is due (last one {meta['last_audit']['date']}).")
    rounds = [d for d in (meta.get("snapshots") or {}).values() if d]
    round_due = _due(max(rounds)) if rounds else None
    if round_due and round_due <= today():
        out.append(f"AI recommendation check is due (last round saved {max(rounds)}).")
    return out


async def overview() -> dict:
    """Every saved project in one call: what it is, when it was last checked and what is due.

    This is the 'where am I' answer for a user who comes back in a new chat and does not remember the project name."""
    be = await stg.get_backend()
    keys = await be.keys(stg.KEY_PREFIX)
    names = sorted({k[len(stg.KEY_PREFIX):].split(".", 1)[0] for k in keys})
    metas = await asyncio.gather(*[be.get(stg.key(n, "meta")) for n in names])
    projects = []
    for name, meta in zip(names, metas):
        meta = dict(meta or {})
        rounds = meta.get("snapshots") or {}
        if not meta.get("last_audit"):  # projects saved before the last check was kept in meta: read it from the keys
            prefix = stg.key(name, "audit") + "."
            dates = sorted(k[len(prefix):] for k in keys if k.startswith(prefix))
            meta["last_audit"] = {"date": dates[-1]} if dates else {}
        last_audit = meta["last_audit"]
        projects.append({"project": name, "site": (meta.get("brand") or {}).get("site") or (meta.get("brand") or {}).get("domain"),
                         "brand": (meta.get("brand") or {}).get("name"), "rounds": len(rounds),
                         "last_round_saved": max(rounds.values()) if any(rounds.values()) else None,
                         "last_site_check": last_audit.get("date"), "health_score": last_audit.get("health_score"),
                         "open_todos": sum(1 for t in meta.get("todo") or [] if t.get("status") == "open"),
                         "updated": meta.get("updated") or meta.get("created"), "due": due_lines(meta)})
    projects.sort(key=lambda p: p["updated"] or "", reverse=True)
    lines = ["# Your saved projects"]
    if projects:
        lines += ["", "| Project | Site | AI rounds | Last AI round | Last site check | Health | Due now |", "|---|---|---|---|---|---|---|"]
        lines += [f"| {p['project']} | {p['site'] or 'not set'} | {p['rounds']} | {p['last_round_saved'] or 'none'} | "
                  f"{p['last_site_check'] or 'none'} | {p['health_score'] if p['health_score'] is not None else 'n/a'} | "
                  f"{' '.join(p['due']) or 'nothing'} |" for p in projects]
        nxt = ("Ask which project to continue, then call get_history with that name. Mention anything due now.")
    else:
        lines += ["", "Nothing saved yet."]
        nxt = ("No projects yet. Start with audit_site and pass a project name (for example the site's name) so the "
               "check is saved.")
    return {"project": None, "brand": {}, "panel_prompts": 0, "snapshots": [], "audits": [], "experiments": [],
            "ai_bot_visits": None, "ai_traffic": None, "search_demand": None, "ranks": None, "questions": [], "rivals": None, "citation_gap": None,
            "projects": projects, "markdown": "\n".join(lines), "next": nxt}


async def history(project: str | None = None) -> dict:
    if not str(project or "").strip():
        return await overview()
    data = await load_project(project)
    snaps = await asyncio.to_thread(snapshot_trend, data)
    audits = [{"date": a["date"], "health_score": a.get("health_score"), "subscores": a.get("subscores", {})}
              for a in data["audits"]]
    lines = [f"# History: {data['slug']}"]
    if snaps:
        lines += ["", "| Round | Saved | Recommendation Share, buying questions (95% range) | Brand-name questions | Answered by |",
                  "|---|---|---|---|---|"]
        lines += [f"| {s['snapshot']}{' (older counting)' if s['older_metric'] else ''} | {s['saved_on']} | "
                  f"{100 * s['recommendation_share']:.1f}% ({100 * s['rs_low']:.1f} to {100 * s['rs_high']:.1f}) | "
                  f"{'n/a' if s['reputation_share'] is None else format(100 * s['reputation_share'], '.1f') + '%'} | "
                  f"{cl.describe_context(s['context']) if s['context'] else ', '.join(cl.engine_name(e) for e in s['engines'])} |"
                  for s in snaps]
        if any(s["older_metric"] for s in snaps):
            lines += ["", "Rounds marked 'older counting' were saved before Citebase stopped counting every plain mention "
                          "as a recommendation. Do not compare them with newer rounds."]
    if audits:
        lines += ["", "| Site check | Health score |", "|---|---|"] + [f"| {a['date']} | {a['health_score']} |" for a in audits]
    if not snaps and not audits:
        lines += ["", "Nothing saved yet."]
    meta = data["meta"]
    stored = data["audits"]
    changes = compare_audits(stored[-2], stored[-1]) if len(stored) > 1 else None
    if changes and (changes["fixed"] or changes["new"]):
        lines += ["", f"Since the site check on {changes['since']}: {len(changes['fixed'])} fixed, {len(changes['new'])} "
                      f"new, {len(changes['still_open'])} still open."]
    signals = await latest_signals(data["slug"])
    lines += signal_lines(signals)
    todo = meta.get("todo") or []
    open_items = [t["step"] for t in todo if t.get("status") == "open"]
    if open_items:
        lines += ["", "Open to-dos: " + "; ".join(open_items[:10]) + "."]
    due = due_lines({**meta, "last_audit": meta.get("last_audit") or ({"date": audits[-1]["date"]} if audits else {})})
    if due:
        nxt = (" ".join(due) + " Offer to run it now. If it is a paid check, say so and wait for a yes; no amount "
               "unless asked. " + tools.RECHECK_OFFER)
    elif not snaps:
        nxt = ("No AI recommendation round saved yet. Offer a paid AI recommend check (say it is paid; quote_cost "
               "first for the caps).")
    else:
        nxt = "Nothing is due. Offer next_steps with this project name to pick one thing to work on."
    return {"project": data["slug"], "brand": meta.get("brand", {}), "panel_prompts": len(data["panel"]),
            "snapshots": snaps, "audits": audits, "experiments": data["experiments"],
            "settings": meta.get("settings", {}), "todo": todo, "site_changes": changes, "due": due,
            "ai_bot_visits": signals["bots"][-1] if signals["bots"] else None,
            "ai_traffic": signals["traffic"][-1] if signals["traffic"] else None,
            "search_demand": signals["search"][-1] if signals["search"] else None,
            "ranks": ranks_view(signals["ranks"]),
            "questions": question_view(data, snaps),
            "rivals": insights.rivals(data["runs"], data["panel"], meta.get("brand"), [x["snapshot"] for x in snaps]),
            "citation_gap": insights.citation_gap(data["runs"], data["panel"], meta.get("brand"),
                                                  snaps[-1]["snapshot"] if snaps else None),
            "projects": None, "markdown": "\n".join(lines), "next": nxt}


def measure_loaded(data: dict, baseline: str = "", current: str = "") -> dict:
    """Recommendation Share report from an already loaded project (CPU work: call from a thread)."""
    if not data["runs"]:
        raise ValueError("This project has no saved AI-answer results yet. Save some with save_results first.")
    exp_rows = tools.normalise_experiments(data["experiments"])
    order = [s["snapshot"] for s in snapshot_trend(data)]  # save order, not alphabetical
    base = stg.clean_part(baseline) if baseline else (order[0] if order else "")
    cur = stg.clean_part(current) if current else (order[-1] if order else "")
    result = tools.measure_rows(_by_id(data["panel"]), data["runs"], exp_rows, base, cur)
    extra = cl.panel_warnings(data["panel"], data["meta"].get("brand"))
    if extra:
        result["warnings"] = [*result["warnings"], *extra]
        result["markdown"] = cl.render(result)
    return result


async def measure_project(project: str, baseline: str = "", current: str = "") -> dict:
    data = await load_project(project)
    return await asyncio.to_thread(measure_loaded, data, baseline, current)
