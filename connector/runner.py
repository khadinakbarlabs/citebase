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
    "measure_recommendation_share": {"panel", "runs", "baseline", "current", "experiments", "brand", "project"},
    "save_results": {"project", "runs", "panel", "experiments", "brand", "audit", "replace", "append"},
    "get_history": {"project"},
    "make_report": {"project"},
    "import_ai_results": {"project", "items", "snapshot", "save", "append", "replace", "panel", "brand", "context"},
    "schedule_checks": {"project", "url", "frequency", "max_pages", "platforms", "repeats"},  # panel and brand come from the project
    "scheduled_check": {"project", "url", "max_pages"},
}
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


async def audit(url: str, max_pages: int = 15) -> dict:
    async with AUDIT_SLOTS:
        return await asyncio.to_thread(tools.run_audit, url, max_pages)


async def save(project: str, runs: list[dict] | None, panel: list[dict] | None, experiments: list[dict] | None,
               brand: dict | None, audit_result: dict | None, replace: bool = False, append: bool = False) -> dict:
    """Saves AI-answer results, the question list, brand details, logged changes and/or one site check."""
    if not (runs or panel or experiments or brand or audit_result):
        raise ValueError("Send runs (AI answers), the question list (panel), an audit (the result of audit_site), "
                         "brand details or logged changes. Nothing was saved.")
    if runs or panel or experiments or brand:
        out = await hist.save_results(project, runs or [], panel, experiments, brand, replace, append)
    else:
        data = await hist.load_project(project) if await _exists(project) else None
        out = {"project": stg.clean_slug(project), "snapshots_saved": {}, "panel_prompts": len(data["panel"]) if data else 0,
               "snapshots_in_project": sorted(data["meta"]["snapshots"]) if data else [],
               "brand": data["meta"].get("brand", {}) if data else {}, "warnings": [],
               "stored_in": "your own Apify account (key-value store 'citebase-projects')"}
    out["audit_saved"] = await hist.save_audit(project, audit_result) if audit_result else None
    out["next"] = SAVE_NEXT_RUNS if runs else SAVE_NEXT_PANEL if panel else SAVE_NEXT_AUDIT
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


async def import_results(project: str, items: list[dict], snapshot: str, save: bool = False, append: bool = False,
                         replace: bool = False, panel: list[dict] | None = None, brand: dict | None = None,
                         context: dict | None = None) -> dict:
    """Converts AI-check results into rows. A new project can be created in the same step: send the question list
    (panel) and the brand with save=true. Nothing is stored unless save is true."""
    slug = stg.clean_slug(project)
    settings = importer.clean_context(context)
    data = await hist.load_project(slug) if await _exists(slug) else None
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
    snap = stg.clean_part(snapshot)
    known_brand = {**(data["meta"].get("brand") or {}), **(brand or {})} if data else brand
    converted = importer.convert(items, questions, snap, known_brand, settings)
    converted["saved"] = None
    if save:
        converted["saved"] = await hist.save_results(slug, converted["runs"], panel or None, None, brand or None,
                                                     replace, append)
    elif panel or brand:
        converted["notes"].append("The question list and brand you sent were not saved (save is false): nothing has been "
                                  "stored yet. Call again with save=true to keep this round.")
    return converted


async def schedule(project: str, url: str | None = None, frequency: str = "weekly", max_pages: int = 15,
                   panel: list[dict] | None = None, brand: dict | None = None, platforms: list[str] | None = None,
                   repeats: int | None = tools.DEFAULT_REPEATS) -> dict:
    """The plan reads the project's questions, brand, site and the engines of its first round, so the round the schedule
    produces is comparable with the ones already saved."""
    baseline_engines = None
    try:
        data = await hist.load_project(project)
        panel = panel or data["panel"]
        brand = brand or data["meta"].get("brand")
        rounds = await asyncio.to_thread(hist.snapshot_trend, data)
        baseline_engines = rounds[0]["engines"] if rounds else None
    except ValueError:
        pass  # a brand-new project is fine: the plan then covers the site check only (it needs the url typed)
    return tools.schedule_plan(stg.clean_slug(project), url, frequency, max_pages, panel, brand, platforms, repeats,
                               baseline_engines)


async def scheduled_check(project: str, url: str, max_pages: int = 15) -> dict:
    result = await audit(url, max_pages)
    saved = await hist.save_audit(project, result)
    rep = await report.make_report(project)
    return {"site": result["site"], "health_score": result["health_score"], "trend": saved["trend"],
            "top_problems": [p["check"] for p in result["problems"][:5]], "report_url": rep["share_url"],
            "project": rep["project"]}


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
            return await audit(args.get("url", ""), args.get("max_pages", 15))
        if tool == "measure_recommendation_share":
            return await measure(args.get("project"), args.get("panel"), args.get("runs"), args.get("baseline", ""),
                                 args.get("current", ""), args.get("experiments"), args.get("brand"))
        if tool == "save_results":
            return await save(args.get("project", ""), args.get("runs"), args.get("panel"), args.get("experiments"),
                              args.get("brand"), args.get("audit"), flag(args, "replace"), flag(args, "append"))
        if tool == "get_history":
            return await hist.history(args.get("project", ""))
        if tool == "make_report":
            return await report.make_report(args.get("project", ""))
        if tool == "import_ai_results":
            return await import_results(args.get("project", ""), args.get("items") or [], args.get("snapshot", ""),
                                        flag(args, "save"), flag(args, "append"), flag(args, "replace"),
                                        args.get("panel"), args.get("brand"), args.get("context"))
        if tool == "schedule_checks":
            return await schedule(args.get("project", ""), args.get("url"), args.get("frequency", "weekly"),
                                  args.get("max_pages", 15), None, None, args.get("platforms"), args.get("repeats"))
        if tool == "scheduled_check":
            return await scheduled_check(args.get("project", ""), args.get("url", ""), args.get("max_pages", 15))
        return await asyncio.to_thread(tools.dispatch, tool, args)
    except ArithmeticError as err:
        raise ValueError(tools.NOT_FINITE_MESSAGE) from err
    except (TypeError, AttributeError, KeyError) as err:
        raise ValueError(f"The inputs for '{tool}' are the wrong shape ({type(err).__name__}). "
                         f"It takes: {', '.join(sorted(ALLOWED_ARGS[tool]))}.") from err
