"""Runs any Citebase tool by name, including the ones that use saved project history.

tools.dispatch handles the stateless tools. This module adds the tools that read or write the caller's own store
(history, reports, schedules). `run_tool` is used by the /run endpoint and by one-shot Actor runs, so both behave
the same way as the MCP tools.
"""
from __future__ import annotations

import asyncio
import math
from collections import Counter
from contextlib import nullcontext
from typing import Any

import fact_checks
import history as hist
import importer
import insights
import signals
import report
import scheduled_import
import search_demand
import storage as stg
import tools
import work_schedules

SAVED = {"save_results", "get_history", "make_report", "import_ai_results", "schedule_checks"}
SERVER_ONLY = {"project_work", "get_account_usage"}
ONE_SHOT_ONLY = {"scheduled_check"}  # meant for Apify Schedules; not offered as an MCP tool
ALLOWED_ARGS = {
    **tools.ALLOWED_ARGS,
    "project_work": {"project", "operation", "data"},
    "get_account_usage": set(),
    "audit_site": {"url", "max_pages", "project"},
    "quote_cost": {"items", "pack", "project"},
    "next_steps": {"audit", "report", "max_steps", "project"},
    "measure_recommendation_share": {"panel", "runs", "baseline", "current", "experiments", "brand", "project"},
    "save_results": {"project", "runs", "panel", "experiments", "brand", "audit", "replace", "append", "settings",
                     "todo", "server_log", "traffic", "traffic_csv", "ranks", "check_only", "gsc_csv", "fact_checks", "create_only"},
    "get_history": {"project", "answer_review"},
    "make_report": {"project", "prospect"},
    "import_ai_results": {"project", "items", "dataset_ids", "snapshot", "save", "append", "replace", "panel", "brand",
                          "context"},
    "schedule_checks": {"project", "url", "frequency", "max_pages", "platforms", "repeats"},  # panel and brand come from the project
    "scheduled_check": {"project", "url", "max_pages", "ai_import", "schedule_plan_id"},
}
MAX_DATASETS = scheduled_import.MAX_DATASETS
TOOL_NAMES = sorted(set(tools.DISPATCH) | SAVED | ONE_SHOT_ONLY | SERVER_ONLY)
AUDIT_SLOTS = asyncio.Semaphore(2)
SAVE_NEXT_RUNS = "Saved. Measure with the project name, then re-check in 30 days: offer schedule_checks to automate it."
SAVE_NEXT_AUDIT = "Saved. " + tools.RECHECK_OFFER
SAVE_NEXT_PANEL = ("Saved the question list. Next, run the AI check with exactly these questions, then call "
                   "import_ai_results with save=true to bring the first round in (no retyping).")


def flag(args: dict, name: str) -> bool:
    """True/false switches must be real booleans: the string "false" must never count as true."""
    value = args.get(name, False)
    if not isinstance(value, bool):
        raise ValueError(f"'{name}' must be true or false (a real boolean), not {value!r}.")
    return value


AI_PACK_REPEATS = {"ai_check": tools.DEFAULT_REPEATS, "ai_check_pilot": 1}


async def quote(items: list[dict] | None, pack: str | None, project: str | None = None) -> dict:
    """Prices jobs. For the AI check of a saved project it prices that project's own question list and returns the
    exact Actor inputs (ready_runs), so the assistant never has to invent questions or inputs that would later
    fail to match on import."""
    if not str(project or "").strip():
        return await asyncio.to_thread(tools.quote_cost, items, pack)
    name = str(pack or "").strip().lower()
    if name not in AI_PACK_REPEATS or items:
        raise ValueError("project works only with pack 'ai_check' or 'ai_check_pilot' (and no items). For other jobs "
                         "leave project empty.")
    data = await hist.load_project(project)
    brand = data["meta"].get("brand") or {}
    if not data["panel"] or not brand.get("name"):
        raise ValueError(f"Project '{data['slug']}' needs a saved question list and brand name first. Save them with "
                         "save_results (panel and brand), then ask again.")
    rounds = await asyncio.to_thread(hist.snapshot_trend, data)
    engines, notes = tools.plan_engines(None, rounds[0]["engines"] if rounds else None)
    repeats, round_name = AI_PACK_REPEATS[name], None
    if name == "ai_check" and rounds:
        # A first look is repeat 1 of this check. Top it up instead of buying those answers again: ask the
        # assistants only for the missing repeats, and leave out Google (one answer per search is already saved).
        last = rounds[-1]["snapshot"]
        asked = [int(r["repeat"]) for r in data["runs"]
                 if r["snapshot"] == last and r["platform"] in tools.ASSISTANT_ENGINES]
        have = max(asked) if asked else 0
        if 0 < have < tools.DEFAULT_REPEATS:
            repeats, round_name = tools.DEFAULT_REPEATS - have, last
            engines = [e for e in engines if e in tools.ASSISTANT_ENGINES]
            notes = [*notes, f"Round '{last}' already holds {have} answer(s) per question, so this adds {repeats} more "
                             "repeat(s) from the assistants only. Nothing already saved is bought again."]
    plan = tools._ai_check_plan(data["panel"], brand, engines, notes, repeats, "monthly",
                                tools.search_context(data["meta"].get("settings")))
    priced = await asyncio.to_thread(tools.quote_cost, [
        {"job": r["job"], "units": r["checks_per_run"] * r["times"], "requests": r["times"]} for r in plan["runs"]])
    engine_names = ", ".join(tools.cl.engine_name(e) for e in plan["engines"])
    priced["pack"] = name
    priced["pack_about"] = (f"{len(data['panel'])} saved questions on {engine_names}; the assistants are asked "
                            f"{plan['repeats']} time(s) each.")
    priced["project"] = data["slug"]
    # Only runs that can start now are offered, each with the same cap quote_cost worked out for it.
    blocked = {ln["job"] for ln in priced["lines"] if ln.get("not_before")}
    caps = iter(priced["run_caps"])
    ready = []
    for planned in plan["runs"]:
        if planned["job"] in blocked:
            continue
        ready.append({"name": planned["name"], "actor": planned["actor"], "times": planned["times"],
                      "how_often": f"Start {planned['times']} separate run(s) with this input, one start each.",
                      "input": planned["input"], "max_cost_per_run_usd": next(caps)["max_cost_per_run_usd"]})
    priced["ready_runs"] = ready
    where = (f"round name '{round_name}' and append=true (it adds to the saved first look)" if round_name else
             "one new round name (use append=true only when adding to a round that already exists)")
    priced["after_the_runs"] = (f"When every run has finished, call import_ai_results with project='{data['slug']}', "
                                f"the runs' dataset ids as dataset_ids, save=true, and {where}.")
    priced["warnings"] = [*priced["warnings"], *plan["notes"]]
    return priced


async def make_report(project: str, prospect: bool = False) -> dict:
    out = await report.make_report(project, prospect)
    if prospect:
        out["next"] = "Preview the audit, then share the link with the prospect if you choose."
        return out
    out["next"] = "Give the user the link and say anyone with it can open it. " + tools.RECHECK_OFFER
    return out


async def audit(url: str | None = None, max_pages: int = 15, project: str | None = None) -> dict:
    """Checks a site. With a project name the check is saved by itself and compared with the last one, so the
    assistant never has to pass the whole result back in. The address can be left out for a saved project."""
    slug = stg.clean_slug(project) if str(project or "").strip() else None
    site = str(url or "").strip()
    if not site and slug:
        if not await _exists(slug):
            raise ValueError(hist.unknown_project(slug, await hist.list_projects())
                             + " To start this project, pass the website address as url.")
        brand = (await hist.load_meta(slug)).get("brand") or {}
        site = str(brand.get("site") or brand.get("domain") or "").strip()
        if not site:
            raise ValueError(f"Project '{slug}' has no website saved yet. Pass the website address as url.")
    async with AUDIT_SLOTS:
        result = await asyncio.to_thread(tools.run_audit, site, max_pages)
    result["saved"] = None
    unreadable = result.get("status") == "unreadable"
    if not slug:
        if not unreadable:
            result["next"] = (result.get("next") or "") + (" To keep this check and see what changes next time, run "
                                                           "it with a project name (for example the site's name).")
        return result
    if unreadable:
        return result  # nothing to save: a check that read nothing must not become a point on the trend
    saved = await hist.save_audit(slug, result)
    result["saved"] = saved
    changes = saved.get("changes")
    if changes:
        result["headline"] = (result.get("headline") or "") + (
            f" Since {changes['since']}: {len(changes['fixed'])} fixed, {len(changes['new'])} new, "
            f"{len(changes['still_open'])} still open.")
    result["next"] = (f"Saved to project '{slug}'. Call next_steps with project='{slug}' (no need to pass this result "
                      "back). Then offer a paid AI recommend check (say it is paid; no amount unless asked). "
                      + tools.RECHECK_OFFER)
    return result


async def next_steps(audit_result: dict | None, report_result: dict | None, max_steps: int = 5,
                     project: str | None = None) -> dict:
    """The to-do list. With a project name it reads the latest saved site check and saved AI results itself, and
    leaves out steps the user already marked as done."""
    if not str(project or "").strip():
        return await asyncio.to_thread(tools.next_steps, audit_result, report_result, max_steps)
    slug = stg.clean_slug(project)
    meta = await hist.load_meta(slug)
    if audit_result is None:
        audit_result = await hist.latest_audit(slug)
    if report_result is None and meta.get("snapshots"):
        try:
            report_result = await hist.measure_project(slug)
        except ValueError:
            report_result = None  # a project with a question list but no answers yet still gets its site steps
    done = {t["step"].lower() for t in meta.get("todo") or [] if t.get("status") in ("done", "skipped")}
    out = await asyncio.to_thread(tools.next_steps, audit_result, report_result, max_steps, done)
    out["project"] = slug
    gap = (report_result or {}).get("citation_gap") or {}
    if not gap and report_result and not report_result.get("citation_gap"):
        try:
            data = await hist.load_project(slug)
            gap = insights.citation_gap(data["runs"], data["panel"], (data.get("meta") or {}).get("brand"),
                                        report_result.get("current")) or {}
        except (ValueError, KeyError, AttributeError):
            gap = {}
    step_name = "Get a fair mention on the sites AI cites for your rivals"
    if gap.get("sites") and step_name.lower() not in done:
        top = [s["site"] for s in gap["sites"][:3]]
        out["steps"].insert(min(1, len(out["steps"]) - 1), {
            "step": step_name,
            "why": f"In the latest round AI cited {', '.join(top)} in answers that named a rival and left you out. "
                   "Those pages feed the answers you are missing from.",
            "who": "you, with Claude's help (link-building and outreach playbooks)", "effort": "a few hours per site",
            "urgency": "do first", "based_on": f"cited sites in round {gap.get('round')}"})
        if len(out["steps"]) > max_steps + 1:
            del out["steps"][-2]  # keep the closing re-check step; drop the weakest step before it
    if not audit_result and not report_result:
        out["tip"] = (f"Project '{slug}' has no saved site check or AI results yet. Start with audit_site and pass "
                      "this project name.")
    else:
        out["tip"] += (" When the user finishes or skips a step, save it with save_results todo "
                       "[{step, status}] so it is not suggested again.")
    return out


async def save(project: str, runs: list[dict] | None, panel: list[dict] | None, experiments: list[dict] | None,
               brand: dict | None, audit_result: dict | None, replace: bool = False, append: bool = False,
               settings: dict | None = None, todo: list[dict] | None = None, server_log: str | None = None,
               traffic: list[dict] | None = None, traffic_csv: str | None = None, ranks: list[dict] | None = None,
               check_only: bool = False, gsc_csv: str | None = None, review: dict | None = None,
               create_only: bool = False) -> dict:
    """Saves AI-answer results, the question list, brand details, settings, to-do updates, logged changes, one
    site check, and/or counts from a pasted server log, an analytics export or search positions.

    With check_only nothing is stored: the question list, log, export or positions are checked and reviewed, so a
    question list can be put right before it is frozen."""
    has_signal = bool(server_log or traffic or traffic_csv or ranks or gsc_csv)
    if create_only and (not brand or any((runs, panel, experiments, audit_result, todo, has_signal, check_only,
                                          replace, append, review is not None))):
        raise ValueError("Create a new project with brand details and optional settings. Save other changes after creation.")
    if review is not None:
        if not isinstance(review, dict) or any((runs, panel, experiments, brand, audit_result, settings, todo,
                                                has_signal, check_only, replace, append)):
            raise ValueError("Send fact_checks as a separate save with only the project name.")
        slug = stg.clean_slug(project)
        snapshot = stg.clean_part(review.get("snapshot"))
        async with hist.lock_for(slug):
            data = await hist.load_project(slug)
            be = await stg.get_backend()
            count = await fact_checks.save_claims(be, slug, snapshot, review.get("claims"), hist.today())
        return {"project": slug, "snapshots_saved": {}, "panel_prompts": len(data["panel"]),
                "snapshots_in_project": sorted(data["meta"]["snapshots"]), "brand": data["meta"].get("brand", {}),
                "fact_checks_saved": count, "stored_in": "your own Apify account",
                "next": "Open the project's Answers tab or ask for the saved fact checks and their sources."}
    if not (runs or panel or experiments or brand or audit_result or settings or todo or has_signal):
        raise ValueError("Send runs (AI answers), the question list (panel), an audit (the result of audit_site), "
                         "brand details, settings, to-do updates, a server log, an analytics export or logged "
                         "changes. Nothing was saved.")
    if traffic and traffic_csv:
        raise ValueError("Send the analytics export either as rows (traffic) or as pasted text (traffic_csv), not both.")
    stg.clean_slug(project)  # a bad project name is refused before any work
    # Everything is checked before anything is written, so a bad paste cannot leave a half-saved project.
    bots = await asyncio.to_thread(signals.summarise_bot_log, server_log) if server_log else None
    visits = None
    if traffic or traffic_csv:
        rows = traffic or await asyncio.to_thread(signals.parse_traffic_csv, traffic_csv)
        visits = await asyncio.to_thread(signals.summarise_traffic, rows)
    rank_rows = insights.clean_ranks(ranks) if ranks else None
    demand = None
    if gsc_csv:
        rows = await asyncio.to_thread(search_demand.parse_gsc_csv, gsc_csv)
        demand = await asyncio.to_thread(search_demand.summarise_search_demand, rows, await _brand_terms(project, brand))
    panel_rows = tools.normalise_panel(panel) if panel else None
    review = await asyncio.to_thread(insights.review_panel, list(panel_rows.values())) if panel_rows else None
    if audit_result:
        hist.checked_audit(audit_result)  # refuse a bad site check before the rounds are written, not after
    if check_only:
        return await _check_only(project, runs, panel_rows, brand, review, bots, visits, rank_rows, demand)
    if runs or panel or experiments or brand or settings or todo:
        out = await hist.save_results(project, runs or [], panel, experiments, brand, replace, append, settings, todo,
                                      create_only=create_only)
    else:
        data = await hist.load_project(project) if await _exists(project) else None
        meta = data["meta"] if data else {}
        out = {"project": stg.clean_slug(project), "snapshots_saved": {}, "panel_prompts": len(data["panel"]) if data else 0,
               "snapshots_in_project": sorted(meta["snapshots"]) if data else [],
               "brand": meta.get("brand", {}), "settings": meta.get("settings", {}), "todo": meta.get("todo", []),
               "created": data is None, "warnings": [],
               "stored_in": "your own Apify account (key-value store 'citebase-projects')"}
    out["audit_saved"] = await hist.save_audit(project, audit_result) if audit_result else None
    if out["audit_saved"]:
        out["warnings"] = [*out["warnings"], *out["audit_saved"].get("warnings", [])]
    out["ai_bot_visits"] = out["ai_traffic"] = None
    for kind, summary, field in (("bots", bots, "ai_bot_visits"), ("traffic", visits, "ai_traffic")):
        if summary:
            kept = await hist.save_signal(project, kind, summary)
            out[field] = {**summary, "saved_on": kept["saved_on"], "previous": _signal_change(kind, kept["previous"])}
            out["warnings"] = [*out["warnings"], *kept["warnings"]]
            out["created"] = out["created"] or kept["created"]
    out["search_demand"] = None
    if demand:
        kept = await hist.save_signal(project, "search", demand)
        out["search_demand"] = {**demand, "saved_on": kept["saved_on"], "previous": _search_change(kept["previous"])}
        out["warnings"] = [*out["warnings"], *kept["warnings"]]
        out["created"] = out["created"] or kept["created"]
    out["ranks"] = None
    if rank_rows:
        summary = insights.summarise_ranks(rank_rows)
        kept = await hist.save_signal(project, "ranks", summary)
        summary = kept["record"] if "rows" in kept["record"] else summary
        history = [r for r in (kept["previous"], summary) if r and "rows" in r]
        out["ranks"] = {"saved_on": kept["saved_on"], "previous_date": (kept["previous"] or {}).get("date"),
                        "keywords": summary["keywords"], "top_3": summary["top_3"], "top_10": summary["top_10"],
                        "not_found": summary["not_found"], "positions": insights.rank_changes(history)}
        out["warnings"] = [*out["warnings"], *kept["warnings"]]
        out["created"] = out["created"] or kept["created"]
    out["panel_review"], out["checked_only"] = review, False  # problems stay in the review: the list is saved as sent
    out["next"] = (SAVE_NEXT_RUNS if runs else SAVE_NEXT_PANEL if panel else SAVE_NEXT_AUDIT if audit_result
                   else SAVE_NEXT_SIGNAL if has_signal
                   else "Saved. These details are reused by later checks, so the user is not asked again.")
    return out


async def _check_only(project: str, runs: list[dict] | None, panel_rows: dict | None, brand: dict | None,
                      review: dict | None, bots: dict | None, visits: dict | None, rank_rows: list[dict] | None, demand: dict | None = None) -> dict:
    """What a save would look like, with nothing stored. Raises ValueError exactly where the real save would."""
    if runs:
        raise ValueError("check_only checks a question list, a server log, an analytics export or search positions. "
                         "Leave runs out, or save them without check_only.")
    slug = stg.clean_slug(project)
    meta = await hist.load_meta(slug) if await _exists(slug) else {}
    warnings: list[str] = []
    if panel_rows:
        be = await stg.get_backend()
        hist.check_frozen(await be.get(stg.key(slug, "panel")), panel_rows)
        known_brand = {**(meta.get("brand") or {}), **hist.clean_brand(brand)}
        warnings = [*tools.cl.panel_warnings(panel_rows, known_brand), *(review or {}).get("problems", [])]
    ready = not warnings
    return {"project": slug, "snapshots_saved": {}, "panel_prompts": len(panel_rows or {}),
            "snapshots_in_project": sorted(meta.get("snapshots") or {}), "brand": meta.get("brand", {}),
            "settings": meta.get("settings", {}), "todo": meta.get("todo", []), "created": False,
            "stored_in": "Nothing was stored: this was a check only.", "warnings": warnings, "audit_saved": None,
            "ai_bot_visits": bots, "ai_traffic": visits, "search_demand": demand,
            "ranks": {**insights.summarise_ranks(rank_rows), "positions": insights.rank_changes(
                [insights.summarise_ranks(rank_rows)])} if rank_rows else None,
            "panel_review": review, "checked_only": True,
            "next": ("Nothing was stored. " + ("It looks ready: " if ready else "Fix the warnings with the user, then ")
                     + "call save_results again without check_only to keep it. A question list cannot change once saved.")}


SAVE_NEXT_SIGNAL = ("Saved. Lead with the findings in plain words. These are the site's own numbers: read them as a "
                    "floor, and paste a fresh export next month to see the direction.")


async def _brand_terms(project: str, brand: dict | None) -> tuple[str, ...]:
    """Brand name and domain label, from this call or the saved project, to tell brand searches from the rest."""
    saved = {}
    slug = stg.clean_slug(project)
    if await _exists(slug):
        saved = (await hist.load_meta(slug)).get("brand") or {}
    names = [(brand or {}).get("name"), saved.get("name"), str((brand or saved).get("domain") or "").split(".")[0]]
    return tuple(dict.fromkeys(str(n).strip() for n in names if n and len(str(n).strip()) >= 3))


def _search_change(previous: dict | None) -> dict | None:
    if not previous or "impressions" not in previous:
        return None
    return {"date": previous.get("date"), "clicks": previous.get("clicks"), "impressions": previous.get("impressions"),
            "gaps": len(previous.get("gaps") or [])}


def _signal_change(kind: str, previous: dict | None) -> dict | None:
    """The headline numbers of the summary saved before this one, so the assistant can say what changed."""
    if not previous:
        return None
    if kind == "bots":
        return {"date": previous.get("date"), "answer_bot_requests": previous.get("answer_bot_requests"),
                "period": previous.get("period")}
    return {"date": previous.get("date"), "ai_visits": previous.get("ai_visits"), "ai_share": previous.get("ai_share")}


async def _exists(project: str) -> bool:
    """True when the project has its details record. Stray records without one (a save that stopped half way) do
    not count, so the next save simply completes the project instead of failing to load it."""
    be = await stg.get_backend()
    return await be.get(stg.key(stg.clean_slug(project), "meta")) is not None


async def measure(project: str | None, panel: list[dict] | None, runs: list[dict] | None, baseline: str = "",
                  current: str = "", experiments: list[dict] | None = None, brand: dict | None = None) -> dict:
    if not project:
        return await asyncio.to_thread(tools.measure, panel or [], runs or [], baseline, current, experiments, brand)
    if panel or runs or experiments or brand:
        raise ValueError("With a project name, measure reads the saved results. Save new ones first with save_results, "
                         "or leave project empty to measure the data you send.")
    data = await hist.load_project(project)
    result = await asyncio.to_thread(hist.measure_loaded, data, baseline, current)
    # The proof behind the number, and where to act: both read from the same saved answers.
    brand_saved = data["meta"].get("brand")
    result["citation_gap"] = insights.citation_gap(data["runs"], data["panel"], brand_saved, result.get("current"))
    result["proof"] = insights.proof(data["runs"], data["panel"], result.get("current"),
                                     (data["meta"].get("imports") or {}).get(result.get("current") or ""))
    result["project"] = stg.clean_slug(project)
    result["next"] = tools.measure_next(result, saved=True)
    return result


OWN_ACTOR_PREFIX = "khadinakbar/"


async def fetch_datasets(dataset_ids: list, already: list[str], *, owned_children: bool = False,
                         item_origins: list[str] | None = None) -> tuple[list[dict], list[str]]:
    """Reads the results of finished runs from the caller's own account. Returns (items, ids that were read).

    A dataset that was already imported into this round is refused, so a retry cannot count the same answers twice."""
    if not isinstance(dataset_ids, list) or not dataset_ids or len(dataset_ids) > MAX_DATASETS:
        raise ValueError(f"dataset_ids must be a list of 1 to {MAX_DATASETS} dataset ids, for example "
                         "['aBcD1234efGh5678'].")
    ids = list(dict.fromkeys(stg.clean_dataset_id(d) for d in dataset_ids))
    repeated = [d for d in ids if d in already]
    if repeated:
        raise ValueError(f"These results are already in this round: {', '.join(repeated)}. Nothing was added. To load "
                         "them again from scratch, pass replace=true with the user's yes.")
    be = await stg.get_backend()
    for dataset_id in [] if owned_children else ids:
        source = await be.dataset_source(dataset_id)
        if source is None:
            raise ValueError(f"Could not tell which Actor made dataset {dataset_id}, so Citebase will not read it: it "
                             "only reads results from its own Actors (khadinakbar/*). Nothing was imported. Check the "
                             "dataset id and that the run belongs to this account, then try again.")
        if source and not source.startswith(OWN_ACTOR_PREFIX):
            raise ValueError(f"Dataset {dataset_id} was made by {source}, which is not one of Citebase's own Actors "
                             "(khadinakbar/*). Citebase only reads results from its own Actors. Nothing was imported.")
    items: list[dict] = []
    for dataset_id in ids:
        room = stg.MAX_DATASET_ITEMS - len(items)
        if room <= 0:
            raise ValueError(f"These datasets hold more than {stg.MAX_DATASET_ITEMS} items together. Import fewer at a time.")
        batch = await be.dataset_items(dataset_id, room + 1)  # one extra item shows that something was left out
        if len(batch) > room:
            raise ValueError(f"These datasets hold more than {stg.MAX_DATASET_ITEMS} items together, so some answers "
                             "would be left out. Nothing was imported. Import fewer datasets at a time.")
        items += batch
        if item_origins is not None:
            item_origins.extend([dataset_id] * len(batch))
    if not items:
        raise ValueError("Those datasets are empty. The runs may still be going: check each with get-actor-run and "
                         "import when they have finished. Do not start the runs again.")
    return items, ids


async def import_results(project: str, items: list[dict] | None, snapshot: str, save: bool = False,
                         append: bool = False, replace: bool = False, panel: list[dict] | None = None,
                         brand: dict | None = None, context: dict | None = None,
                         dataset_ids: list[str] | None = None, *, google_context_only: bool = False,
                         owned_children: bool = False) -> dict:
    """Converts AI-check results into rows. A new project can be created in the same step: send the question list
    (panel) and the brand with save=true. Nothing is stored unless save is true.

    Results come either as `items` or, better, as `dataset_ids`: then Citebase reads them itself and the assistant
    does not copy hundreds of items through the chat."""
    slug = stg.clean_slug(project)
    data = await hist.load_project(slug) if await _exists(slug) else None
    # Only what the caller says about this run is stamped on the rows. The project's saved country or device is what
    # the user wants checked, not proof of how an assistant's answer was produced.
    settings = importer.clean_context(context)
    snap = stg.clean_part(snapshot)
    source_ids: list[str] = []
    item_origins: list[str] = []
    if dataset_ids:
        if items:
            raise ValueError("Send either items or dataset_ids, not both.")
        already = [] if replace else list(((data or {}).get("meta", {}).get("imports") or {}).get(snap) or [])
        items, source_ids = await fetch_datasets(dataset_ids, already, owned_children=owned_children, item_origins=item_origins)
    if not items:
        raise ValueError("Send the finished runs' dataset ids as dataset_ids (best), or the result items as items.")
    stored = data["panel"] if data else []
    if panel:
        rows = tools.normalise_panel(panel)
        hist.check_frozen(stored, rows)
        questions = list(rows.values())
    elif stored:
        questions = stored
    elif data is None:
        raise ValueError(f"There is no saved project called '{slug}' yet and no question list was sent. Send the question "
                         "list as `panel` (and the brand as `brand`) with this import and save=true, or save the question "
                         "list first with save_results (panel only).")
    else:
        raise ValueError(f"Project '{slug}' has no question list yet: save the question list first (save_results with "
                         "panel), or send it as `panel` with this import.")
    known_brand = {**(data["meta"].get("brand") or {}), **(brand or {})} if data else brand
    converted = importer.convert(items, questions, snap, known_brand, settings,
                                 google_context_only=google_context_only, item_origins=item_origins)
    converted["saved"] = None
    converted["dataset_ids"] = source_ids or None
    if save:
        contributed = {r.get("source_dataset_id") for r in converted["runs"]}
        saved_sources = [ds for ds in source_ids if ds in contributed]
        if len(saved_sources) != len(source_ids):
            converted["notes"].append("Only datasets with a matching answer are linked to the saved round.")
        converted["saved"] = await hist.save_results(slug, converted["runs"], panel or None, None, brand or None,
                                                     replace, append, None, None, saved_sources or None)
        if source_ids:
            # The rows are stored and Citebase read them itself, so they are not sent back through the chat.
            converted["runs"] = []
            if converted["saved"]["snapshots_saved"]:
                converted["notes"].append(f"Round '{snap}' now holds {converted['saved']['snapshots_saved'][snap]} "
                                          "answers. They are not listed here; call measure_recommendation_share "
                                          "with the project name to see the result.")
            else:
                converted["notes"].append(f"Nothing new was added to round '{snap}': these answers were already saved.")
        converted["next"] = (f"Saved. Call measure_recommendation_share with project='{slug}' to see the numbers. "
                             "Read any needs_review items with the user first.")
    else:
        if panel or brand:
            converted["notes"].append("The question list and brand you sent were not saved (save is false): nothing "
                                      "has been stored yet. Call again with save=true to keep this round.")
        converted["next"] = "Nothing is stored yet. Call again with save=true to keep this round."
    for row in converted["runs"]:
        row.pop("answer_text", None)
        row.pop("answer_truncated", None)
    return converted


async def schedule(project: str, url: str | None = None, frequency: str | None = None, max_pages: int = 15,
                   panel: list[dict] | None = None, brand: dict | None = None, platforms: list[str] | None = None,
                   repeats: int | None = tools.DEFAULT_REPEATS) -> dict:
    """The plan reads the project's questions, brand, site and the engines of its first round, so the round the schedule
    produces is comparable with the ones already saved."""
    baseline_engines = None
    slug = stg.clean_slug(project)
    known = await hist.list_projects()
    settings: dict = {}
    missing = None
    if slug in known:
        data = await hist.load_project(slug)
        panel = panel or data["panel"]
        brand = brand or data["meta"].get("brand")
        settings = data["meta"].get("settings") or {}
        rounds = await asyncio.to_thread(hist.snapshot_trend, data)
        baseline_engines = rounds[0]["engines"] if rounds else None
    else:
        # A brand-new project is fine (the plan then covers the site check only), but a misspelt name must not
        # quietly produce a plan for the wrong project.
        close = hist.similar_names(slug, known)
        if close and not str(url or "").strip():
            raise ValueError(hist.unknown_project(slug, known))  # no address either: almost certainly a typo
        missing = (f"There is no saved project called '{slug}' yet, so this plan covers the site check only."
                   + (f" Did you mean '{close[0]}'? If so, ask again with that name." if close else "")
                   + (f" Saved projects: {', '.join(known[:10])}." if known else ""))
    plan = tools.schedule_plan(slug, url, frequency, max_pages, panel, brand, platforms, repeats, baseline_engines,
                               settings)
    store_id = getattr(await stg.get_backend(), "project_store_id", None)
    if store_id:
        plan["free_site_check"]["input"]["project_store_id"] = store_id
        if plan.get("ai_checks", None) and plan["ai_checks"].get("site_check_input"):
            plan["ai_checks"]["site_check_input"]["project_store_id"] = store_id
    if missing:
        plan["note"] = missing + (" " + plan["note"] if plan.get("note") else "")
    return plan


def managed_schedule_checks(managed: dict, config: dict, data: dict) -> list[dict]:
    context = tools.search_context(data["meta"].get("settings"))
    if not isinstance(managed, dict) or managed.get("settings_fingerprint") != scheduled_import.fingerprint(context):
        raise ValueError("The project's search settings changed. Update the schedule before running new checks.")
    engines, _ = tools.plan_engines(managed.get("engines"), None)
    panel = data["panel"]
    selected = managed.get("prompt_ids")
    if selected is not None:
        if not isinstance(selected, list) or any(not isinstance(i,str) for i in selected):
            raise ValueError("The approved question group changed.")
        panel = [p for p in panel if p["prompt_id"] in selected]
    plan = tools._ai_check_plan(panel, data["meta"]["brand"], engines, [],
                                tools.clean_repeats(managed.get("repeats")), "monthly", context)
    actions = [action for action in plan["runs"] for _ in range(action["times"])]
    fingerprints = [scheduled_import.fingerprint([a["actor"], a["input"]]) for a in actions]
    caps = managed.get("caps")
    if (fingerprints != config["input_fingerprints"] or not isinstance(caps, list) or len(caps) != len(actions)
            or any(type(c) not in (float, int) or not math.isfinite(c) or c <= 0 for c in caps)):
        raise ValueError("The scheduled AI checks differ from the approved plan. Update the schedule first.")
    return [{**a, "cap": min(cap, a["suggested_max_cost_usd"])} for a, cap in zip(actions, caps)]


async def import_scheduled(project: str, config: dict, *, reconcile_only=False) -> dict:
    allowed = {tools.PRICES["jobs"][key]["actor"] for key in ("ai_brand_check", "ai_overview", "ai_mode")}
    expected = scheduled_import.validate(config, allowed)
    be = await stg.get_backend()
    meta = await hist.load_meta(project)
    if scheduled_import.fingerprint(meta.get("brand") or {}) != config.get("brand_fingerprint"):
        raise ValueError("The project's brand details changed. Update the schedule before importing.")
    managed = config.get("managed_checks")
    context = config.get("context")
    planned_answers = None
    if managed is not None:
        data = await hist.load_project(project)
        context = tools.search_context(data["meta"].get("settings"))
        checks = managed_schedule_checks(managed, config, data)
        planned_answers = Counter()
        for action in checks:
            values = action["input"]
            if "customQueries" in values:
                cells = ((q, eng) for q in values["customQueries"] for eng in values["platforms"])
            else:
                eng = "google-aio" if action["actor"] == tools.PRICES["jobs"]["ai_overview"]["actor"] else "google-aimode"
                cells = ((q, eng) for q in values["queries"])
            planned_answers.update(cells)
        current_run = scheduled_import.scheduled_run_id()
        snapshots = data["meta"]["snapshots"]
        if len(snapshots) >= stg.MAX_SNAPSHOTS and f"scheduled-{current_run}" not in snapshots:
            raise ValueError("This project has reached its round limit. Move the schedule to a new project.")
        snapshot, datasets = await scheduled_import.managed_datasets(be, data["slug"], checks, config["input_fingerprints"],
                                                                     reconcile_only=reconcile_only)
    else:
        snapshot, datasets = await scheduled_import.find_datasets(getattr(be, "client", None), expected,
                                                                  config["input_fingerprints"])
    # The first process and its migrated replacement can observe the same completed children.
    # Serialize the import itself after waiting on children, never across a paid start or wait.
    committed = await be.get(stg.key(project, "schedule"))
    async with work_schedules.schedule_lock(be, project) if committed else nullcontext():
        return await save_scheduled_round(project, config, snapshot, datasets, context, sum(expected.values()), planned_answers)


async def save_scheduled_round(project, config, snapshot, datasets, context, expected_datasets, planned_answers):
    be = await stg.get_backend()
    coverage_key = stg.key(project, "schedule-import-coverage", snapshot)
    data = await hist.load_project(project)
    if scheduled_import.fingerprint(data["meta"].get("brand") or {}) != config["brand_fingerprint"]:
        raise ValueError("The project's brand details changed. Update the schedule before importing.")
    imported = (data["meta"].get("imports") or {}).get(snapshot)
    if snapshot in data["meta"]["snapshots"]:
        if not imported or not set(imported).issubset(datasets):
            raise ValueError("This scheduled round already exists. Review the saved results before importing again.")
    remaining = [ds for ds in datasets if ds not in (imported or [])]
    if remaining:
        await be.set(coverage_key, {"status": "importing"})
        try:
            await import_results(project, None, snapshot, save=True, append=bool(imported), dataset_ids=remaining,
                                 context=context, google_context_only=True,
                                 owned_children=config.get("managed_checks") is not None)
        except ValueError:
            if not imported:
                raise ValueError("The scheduled AI datasets could not be saved. Review the results in Activity.") from None
        data = await hist.load_project(project)
    linked = (data["meta"].get("imports") or {}).get(snapshot) or []
    panel = {q["prompt_id"]: q["prompt"] for q in data["panel"]}
    answers = Counter((panel.get(r["prompt_id"]), r["platform"]) for r in data["runs"] if r["snapshot"] == snapshot)
    complete = len(linked) == expected_datasets and (planned_answers is None or answers == planned_answers)
    coverage = {"status": "imported" if complete else "partial", "saved_answers": sum(answers.values()),
                "expected_answers": sum(planned_answers.values()) if planned_answers is not None else None,
                "matched_answers": sum((answers & planned_answers).values()) if planned_answers is not None else None,
                "expected_datasets": expected_datasets, "saved_datasets": len(linked)}
    await be.set(coverage_key, coverage)
    snaps = await asyncio.to_thread(hist.snapshot_trend, data)
    return {**coverage, "snapshot": snapshot,
            "alert": await scheduled_import.checked_alert(be, data, snaps, hist.cl.DISCOVERY_TYPES)
            if complete and snaps and snaps[-1]["snapshot"] == snapshot else None}


async def scheduled_check(project: str, url: str, max_pages: int = 15, ai_import: dict | None = None, *, occurrence=None) -> dict:
    result = await audit(url, max_pages, project)
    saved = result["saved"]
    if occurrence:
        be, key, event = occurrence
        event["site_health_score"] = result["health_score"] if saved else None
        await be.set(key, event)
    imported = {}
    if ai_import is not None:
        try:
            imported["ai_import"] = await import_scheduled(project, ai_import)
        except ValueError as err:
            if not saved:
                raise ValueError("The site check could not be saved and the AI results could not be imported. "
                                 + str(err)) from None
            imported["ai_import"] = {"status": "failed", "message": str(err)}
    if not saved:  # the site could not be read: say so and leave the saved trend alone
        return {"site": result["site"], "health_score": None, "trend": None, "changes": None,
                "top_problems": [p["check"] for p in result["problems"][:5]], "report_url": None,
                "project": stg.clean_slug(project), "note": result.get("headline"), **imported}
    rep = await report.make_report(project)
    return {"site": result["site"], "health_score": result["health_score"], "trend": saved["trend"],
            "changes": saved.get("changes"),
            "top_problems": [p["check"] for p in result["problems"][:5]], "report_url": rep["share_url"],
            "project": rep["project"], "note": result.get("headline"), **imported}


async def guarded_check(args: dict) -> dict:
    project = stg.clean_slug(args.get("project"))
    pid = args.get("schedule_plan_id")
    if pid is None:
        if await (await stg.get_backend()).get(stg.key(project, "schedule")):
            raise ValueError("This project requires its confirmed schedule plan.")
        return await scheduled_check(project, args.get("url", ""), args.get("max_pages", 15), args.get("ai_import"))
    approved = {k:v for k,v in args.items() if k != "schedule_plan_id"}
    be, key, event = await work_schedules.begin(project, pid, approved)
    readonly = event.pop("reconcile_only", False)
    try:
        if readonly:
            ai = await import_scheduled(project, approved["ai_import"], reconcile_only=True)
            result = {"project": project, "site": approved["url"], "health_score": event.get("site_health_score"),
                      "ai_import": ai, "note": "Reconciled previously started AI runs."}
        else:
            result = await scheduled_check(project, approved["url"], approved["max_pages"], approved.get("ai_import"),
                                           occurrence=(be, key, event))
    except Exception:
        if not readonly:
            await be.set(key, {**event, "status":"failed"})
        raise
    ai = result.get("ai_import") or {}
    site_saved = result.get("health_score") is not None
    status = "completed" if site_saved and ai.get("status") not in ("partial", "failed") else (
        "partial" if site_saved or ai.get("saved_answers") else "failed")
    async with work_schedules.schedule_lock(be, project):
        previous = await be.get(key) or {}
        if previous.get("status") != "completed":
            await be.set(key, {**event, "status":status, "saved_answers":ai.get("saved_answers",0),
                               "matched_answers":ai.get("matched_answers"),
                               "expected_answers":ai.get("expected_answers"), "saved_datasets":ai.get("saved_datasets"),
                               "expected_datasets":ai.get("expected_datasets"), "snapshot":ai.get("snapshot")})
    return result


async def run_tool(tool: str, arguments: dict | None) -> dict[str, Any]:
    """Runs one tool by name. Raises ValueError with a plain-language fix for bad input."""
    if tool not in TOOL_NAMES:
        raise ValueError(f"Unknown tool '{tool}'. Choose one of: {', '.join(TOOL_NAMES)}. "
                         "Example: tool 'get_playbook' with arguments {}.")
    args = arguments if isinstance(arguments, dict) else {}
    extra = sorted(set(args) - ALLOWED_ARGS[tool])
    if extra:
        raise ValueError(f"'{tool}' does not take {', '.join(extra)}. It takes: {', '.join(sorted(ALLOWED_ARGS[tool]))}.")
    tools.reject_non_finite(args)
    try:
        if tool == "get_account_usage":
            import account_usage
            return await account_usage.read()
        if tool == "project_work":
            from project_work import execute
            return await execute(args.get("project"), args.get("operation"), args.get("data"))
        if tool == "audit_site":
            return await audit(args.get("url"), args.get("max_pages", 15), args.get("project"))
        if tool == "next_steps" and str(args.get("project") or "").strip():
            return await next_steps(args.get("audit"), args.get("report"), args.get("max_steps", 5), args.get("project"))
        if tool == "measure_recommendation_share":
            return await measure(args.get("project"), args.get("panel"), args.get("runs"), args.get("baseline", ""),
                                 args.get("current", ""), args.get("experiments"), args.get("brand"))
        if tool == "quote_cost" and str(args.get("project") or "").strip():
            return await quote(args.get("items") or [], args.get("pack"), args.get("project"))
        if tool == "make_report":
            return await make_report(args.get("project", ""), flag(args, "prospect"))
        if tool == "save_results":
            return await save(args.get("project", ""), args.get("runs"), args.get("panel"), args.get("experiments"),
                              args.get("brand"), args.get("audit"), flag(args, "replace"), flag(args, "append"),
                              args.get("settings"), args.get("todo"), args.get("server_log"),
                              args.get("traffic"), args.get("traffic_csv"), args.get("ranks"),
                              flag(args, "check_only"), args.get("gsc_csv"), args.get("fact_checks"), flag(args, "create_only"))
        if tool == "get_history":
            return await hist.history(args.get("project"), args.get("answer_review"))
        if tool == "import_ai_results":
            return await import_results(args.get("project", ""), args.get("items") or [], args.get("snapshot", ""),
                                        flag(args, "save"), flag(args, "append"), flag(args, "replace"),
                                        args.get("panel"), args.get("brand"), args.get("context"),
                                        args.get("dataset_ids"))
        if tool == "schedule_checks":
            return await schedule(args.get("project", ""), args.get("url"), args.get("frequency"),
                                  args.get("max_pages", 15), None, None, args.get("platforms"), args.get("repeats"))
        if tool == "scheduled_check":
            return await guarded_check(args)
        if tool in ("next_steps", "quote_cost"):
            args = {k: v for k, v in args.items() if k != "project"}  # blank project: the stateless tool
        return await asyncio.to_thread(tools.dispatch, tool, args)
    except ArithmeticError as err:
        raise ValueError(tools.NOT_FINITE_MESSAGE) from err
    except (TypeError, AttributeError, KeyError) as err:
        raise ValueError(f"The inputs for '{tool}' are the wrong shape ({type(err).__name__}). "
                         f"It takes: {', '.join(sorted(ALLOWED_ARGS[tool]))}.") from err
