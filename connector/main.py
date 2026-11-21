"""Apify entry point: runs the Citebase MCP server in Standby mode."""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn  # noqa: E402
from apify import Actor  # noqa: E402

import runner  # noqa: E402
import storage  # noqa: E402
import managed_project  # noqa: E402
from server import build_app, setup_logging  # noqa: E402


PRIVATE_STORAGE_REQUIRED = (
    "Use the signed-in Citebase dashboard or MCP server for imported answers, private reviews and report links. "
    "Apify one-shot runs can expose inputs and outputs to anyone with a storage ID."
)


def uses_private_run_data(tool: str, args: dict) -> bool:
    if tool in runner.SERVER_ONLY:
        return True
    if tool == "get_history":
        return args.get("answer_review") is not None
    if tool in ("make_report", "import_ai_results"):
        return True  # signed links and imported review excerpts convey access to private data
    if tool == "save_results":
        runs = args.get("runs")
        return bool(args.get("fact_checks")) or (
            isinstance(runs, list) and any(isinstance(row, dict) and row.get("answer_text") for row in runs)
        )
    return False


def only_fields(source, fields):
    return {k: source[k] for k in fields if k in source}


def public_schedule_input(value):
    if isinstance(value, list):
        return [public_schedule_input(item) for item in value]
    if isinstance(value, dict):
        grants = {"project_store_id", "schedule_lock_id", "schedule_ledger_id", "schedule_plan_id",
                  "private_store_id", "revisions_queue_id", "queue_grants", "private_result"}
        return {key: public_schedule_input(item) for key, item in value.items() if key not in grants}
    return value


def protect_run_summary(result: dict, tool: str = "scheduled_check") -> dict:
    """Normal Actor runs may share default storage. Build their output from public fields only."""
    if tool == "schedule_checks":
        return public_schedule_input(result)
    if tool == "get_history":
        protected = only_fields(result, ("project", "panel_prompts"))
        if "projects" in result:
            fields = ("project", "site", "brand", "rounds", "last_round_saved", "last_site_check", "health_score",
                      "open_todos", "updated", "due")
            protected["projects"] = [only_fields(p, fields) for p in result["projects"]] if result["projects"] is not None else None
        if "audits" in result:
            protected["audits"] = [only_fields(a, ("date", "health_score")) for a in result["audits"]]
        if "snapshots" in result:
            fields = ("saved_on", "prompts", "recommendation_share", "rs_low", "rs_high", "reputation_share")
            protected["snapshots"] = [only_fields(s, fields) for s in result["snapshots"]]
        if "markdown" in result:
            protected["markdown"] = "Open the signed-in project for its full history, questions and evidence."
        if "next" in result:
            protected["next"] = "Read the full history through the signed-in dashboard or encrypted private_request."
    else:
        protected = only_fields(result, ("project", "site", "health_score", "trend", "top_problems"))
        if "report_url" in result:
            protected["report_url"] = None
    alert_fields = ("lost_questions", "compared_questions", "compared_answers_per_round")
    if "scheduled_alert" in result:
        alert = result["scheduled_alert"]
        protected["scheduled_alert"] = only_fields(alert, alert_fields) if isinstance(alert, dict) else None
    if isinstance(result.get("ai_import"), dict):
        imported = result["ai_import"]
        safe = only_fields(imported, ("status", "saved_answers"))
        if isinstance(imported.get("alert"), dict):
            safe["alert"] = only_fields(imported["alert"], alert_fields)
        protected["ai_import"] = safe
    return protected


async def run_once() -> None:
    """Normal run: execute one Citebase tool and return its result (this is what mcp.apify.com calls)."""
    data = await Actor.get_input() or {}
    tool = str(data.get("tool") or "get_playbook")
    if tool == "project_work" or "private_request" in data:
        await managed_project.run_once(Actor, data)
        return
    args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
    try:
        at_home = bool(os.environ.get("APIFY_IS_AT_HOME"))
        if at_home and uses_private_run_data(tool, args):
            raise ValueError(PRIVATE_STORAGE_REQUIRED)
        with storage.project_store_grant(data.get("project_store_id")), runner.work_schedules.queue_grants(data):
            result = await runner.run_tool(tool, args)
        if tool == "scheduled_check":
            if result.get("health_score") is None and not (result.get("ai_import") or {}).get("saved_answers"):
                raise ValueError("The scheduled check could not save a site score or any AI answers. Review Activity.")
        if at_home and tool in ("scheduled_check", "schedule_checks", "get_history"):
            result = protect_run_summary(result, tool)
    except ValueError as err:  # bad input: say what to fix, and end the run honestly as failed
        message = str(err)
        if at_home and tool in {"get_history", "schedule_checks", "scheduled_check"} and message != PRIVATE_STORAGE_REQUIRED:
            message = "Citebase could not finish this project request. Check the signed-in dashboard for its history and Activity."
        await Actor.push_data({"tool": tool, "ok": False, "result": None, "error": message})
        await Actor.fail(status_message=message[:200])
        return
    except Exception as err:  # a fault in Citebase itself: say so plainly, keep the class for the run log
        Actor.log.error(f"{tool} failed unexpectedly: {type(err).__name__}")
        message = "Citebase could not finish this request. Check Activity for completed work and any platform or data charges before retrying."
        await Actor.push_data({"tool": tool, "ok": False, "result": None, "error": message})
        await Actor.fail(status_message=message)
        return
    await Actor.push_data({"tool": tool, "ok": True, "result": result, "error": None})
    await Actor.set_value("OUTPUT", result)
    await Actor.set_status_message(f"{tool}: done")


async def main() -> None:
    setup_logging()  # one safe line per call (tool, size, outcome, time); never the content
    async with Actor:
        if os.environ.get("APIFY_META_ORIGIN") != "STANDBY":
            await run_once()
            return
        port = int(os.environ.get("ACTOR_STANDBY_PORT") or os.environ.get("ACTOR_WEB_SERVER_PORT") or 8080)
        Actor.log.info(f"Citebase MCP server listening on port {port}")
        server = uvicorn.Server(uvicorn.Config(build_app(), host="0.0.0.0", port=port, log_level="info", access_log=False,
                                               timeout_graceful_shutdown=25))
        await server.serve()


if __name__ == "__main__":
    asyncio.run(main())
