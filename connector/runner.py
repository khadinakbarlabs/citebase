"""Runs any Citebase tool by name, including the ones that use saved project history.

tools.dispatch handles the stateless tools. This module adds the tools that read or write the caller's own store
(history, reports, schedules). `run_tool` is used by the /run endpoint and by one-shot Actor runs, so both behave
the same way as the MCP tools.
"""
from __future__ import annotations

import asyncio
from typing import Any

import history as hist
import importer
import report
import storage as stg
import tools

SAVED = {"save_results", "get_history", "make_report", "import_ai_results", "schedule_checks"}
ONE_SHOT_ONLY = {"scheduled_check"}  # meant for Apify Schedules; not offered as an MCP tool
ALLOWED_ARGS = {
    **tools.ALLOWED_ARGS,
    "audit_site": {"url", "max_pages", "project"},
    "next_steps": {"audit", "report", "max_steps", "project"},
    "measure_recommendation_share": {"panel", "runs", "baseline", "current", "experiments", "brand", "project"},
    "save_results": {"project", "runs", "panel", "experiments", "brand", "audit", "replace", "append", "settings",
                     "todo"},
    "get_history": {"project"},
    "make_report": {"project"},
    "import_ai_results": {"project", "items", "dataset_ids", "snapshot", "save", "append", "replace", "panel", "brand",
                          "context"},
    "schedule_checks": {"project", "url", "frequency", "max_pages", "platforms", "repeats"},  # panel and brand come from the project
    "scheduled_check": {"project", "url", "max_pages"},
}
MAX_DATASETS = 20  # one round of the AI check is about seven runs; this leaves room for a larger panel
TOOL_NAMES = sorted(set(tools.DISPATCH) | SAVED | ONE_SHOT_ONLY)
AUDIT_SLOTS = asyncio.Semaphore(2)
SAVE_NEXT_RUNS = "Saved. Re-check in 30 days to see what moved, or offer schedule_checks to run the checks automatically."
SAVE_NEXT_AUDIT = "Saved. Check the site again in 30 days to see what moved, or offer schedule_checks to automate it."
SAVE_NEXT_PANEL = ("Saved the question list. Next, run the AI check with exactly these questions, then call "
                   "import_ai_results with save=true to bring the first round in (no retyping).")


def flag(args: dict, name: str) -> bool:
    """True/false switches must be real booleans: the string "false" must never count as true."""
    value = args.get(name, False)
    if not isinstance(value, bool):
        raise ValueError(f"'{name}' must be true or false (a real boolean), not {value!r}.")
    return value


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
                      "back). Then offer a quoted AI recommend check, and a re-check in 30 days.")
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
    if not audit_result and not report_result:
        out["tip"] = (f"Project '{slug}' has no saved site check or AI results yet. Start with audit_site and pass "
                      "this project name.")
    else:
        out["tip"] += (" When the user finishes or skips a step, save it with save_results todo "
                       "[{step, status}] so it is not suggested again.")
    return out


async def save(project: str, runs: list[dict] | None, panel: list[dict] | None, experiments: list[dict] | None,
               brand: dict | None, audit_result: dict | None, replace: bool = False, append: bool = False,
               settings: dict | None = None, todo: list[dict] | None = None) -> dict:
    """Saves AI-answer results, the question list, brand details, settings, to-do updates, logged changes and/or
    one site check."""
    if not (runs or panel or experiments or brand or audit_result or settings or todo):
        raise ValueError("Send runs (AI answers), the question list (panel), an audit (the result of audit_site), "
                         "brand details, settings, to-do updates or logged changes. Nothing was saved.")
    if audit_result:
        hist.checked_audit(audit_result)  # refuse a bad site check before the rounds are written, not after
    if runs or panel or experiments or brand or settings or todo:
        out = await hist.save_results(project, runs or [], panel, experiments, brand, replace, append, settings, todo)
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
    out["next"] = (SAVE_NEXT_RUNS if runs else SAVE_NEXT_PANEL if panel else SAVE_NEXT_AUDIT if audit_result
                   else "Saved. These details are reused by later checks, so the user is not asked again.")
    return out


async def _exists(project: str) -> bool:
    return stg.clean_slug(project) in await hist.list_projects()


async def measure(project: str | None, panel: list[dict] | None, runs: list[dict] | None, baseline: str = "",
                  current: str = "", experiments: list[dict] | None = None, brand: dict | None = None) -> dict:
    if not project:
        return await asyncio.to_thread(tools.measure, panel or [], runs or [], baseline, current, experiments, brand)
    if panel or runs or experiments or brand:
        raise ValueError("With a project name, measure reads the saved results. Save new ones first with save_results, "
                         "or leave project empty to measure the data you send.")
    result = await hist.measure_project(project, baseline, current)
    result["project"] = stg.clean_slug(project)
    result["next"] = tools.measure_next(result, saved=True)
    return result


async def fetch_datasets(dataset_ids: list, already: list[str]) -> tuple[list[dict], list[str]]:
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
    if not items:
        raise ValueError("Those datasets are empty. The runs may still be going: check each with get-actor-run and "
                         "import when they have finished. Do not start the runs again.")
    return items, ids


async def import_results(project: str, items: list[dict] | None, snapshot: str, save: bool = False,
                         append: bool = False, replace: bool = False, panel: list[dict] | None = None,
                         brand: dict | None = None, context: dict | None = None,
                         dataset_ids: list[str] | None = None) -> dict:
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
    if dataset_ids:
        if items:
            raise ValueError("Send either items or dataset_ids, not both.")
        already = [] if replace else list(((data or {}).get("meta", {}).get("imports") or {}).get(snap) or [])
        items, source_ids = await fetch_datasets(dataset_ids, already)
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
    converted = importer.convert(items, questions, snap, known_brand, settings)
    converted["saved"] = None
    converted["dataset_ids"] = source_ids or None
    if save:
        converted["saved"] = await hist.save_results(slug, converted["runs"], panel or None, None, brand or None,
                                                     replace, append, None, None, source_ids or None)
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
    if missing:
        plan["note"] = missing + (" " + plan["note"] if plan.get("note") else "")
    return plan


async def scheduled_check(project: str, url: str, max_pages: int = 15) -> dict:
    result = await audit(url, max_pages, project)
    saved = result["saved"]
    if not saved:  # the site could not be read: say so and leave the saved trend alone
        return {"site": result["site"], "health_score": None, "trend": None, "changes": None,
                "top_problems": [p["check"] for p in result["problems"][:5]], "report_url": None,
                "project": stg.clean_slug(project), "note": result.get("headline")}
    rep = await report.make_report(project)
    return {"site": result["site"], "health_score": result["health_score"], "trend": saved["trend"],
            "changes": saved.get("changes"),
            "top_problems": [p["check"] for p in result["problems"][:5]], "report_url": rep["share_url"],
            "project": rep["project"], "note": result.get("headline")}


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
        if tool == "audit_site":
            return await audit(args.get("url"), args.get("max_pages", 15), args.get("project"))
        if tool == "next_steps" and str(args.get("project") or "").strip():
            return await next_steps(args.get("audit"), args.get("report"), args.get("max_steps", 5), args.get("project"))
        if tool == "measure_recommendation_share":
            return await measure(args.get("project"), args.get("panel"), args.get("runs"), args.get("baseline", ""),
                                 args.get("current", ""), args.get("experiments"), args.get("brand"))
        if tool == "save_results":
            return await save(args.get("project", ""), args.get("runs"), args.get("panel"), args.get("experiments"),
                              args.get("brand"), args.get("audit"), flag(args, "replace"), flag(args, "append"),
                              args.get("settings"), args.get("todo"))
        if tool == "get_history":
            return await hist.history(args.get("project"))
        if tool == "make_report":
            return await report.make_report(args.get("project", ""))
        if tool == "import_ai_results":
            return await import_results(args.get("project", ""), args.get("items") or [], args.get("snapshot", ""),
                                        flag(args, "save"), flag(args, "append"), flag(args, "replace"),
                                        args.get("panel"), args.get("brand"), args.get("context"),
                                        args.get("dataset_ids"))
        if tool == "schedule_checks":
            return await schedule(args.get("project", ""), args.get("url"), args.get("frequency"),
                                  args.get("max_pages", 15), None, None, args.get("platforms"), args.get("repeats"))
        if tool == "scheduled_check":
            return await scheduled_check(args.get("project", ""), args.get("url", ""), args.get("max_pages", 15))
        if tool == "next_steps":
            args = {k: v for k, v in args.items() if k != "project"}  # blank project: the stateless tool
        return await asyncio.to_thread(tools.dispatch, tool, args)
    except ArithmeticError as err:
        raise ValueError(tools.NOT_FINITE_MESSAGE) from err
    except (TypeError, AttributeError, KeyError) as err:
        raise ValueError(f"The inputs for '{tool}' are the wrong shape ({type(err).__name__}). "
                         f"It takes: {', '.join(sorted(ALLOWED_ARGS[tool]))}.") from err
