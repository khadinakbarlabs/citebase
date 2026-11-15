"""Citebase MCP server: exposes the plugin's playbooks and tools to web assistants (claude.ai, ChatGPT, ...).

Nothing is stored unless the user passes a project name to save_results or make_report. Then the data goes into a
named store in the caller's own Apify account (single-tenant), never into the author's. Every tool has a
plain-language description, described inputs and a typed output schema.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import os
import sys
import time
from typing import Annotated, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from pydantic import Field  # noqa: E402
from starlette.responses import JSONResponse, PlainTextResponse  # noqa: E402

import history as hist  # noqa: E402
import models as m  # noqa: E402
import runner  # noqa: E402
import tools  # noqa: E402

VERSION = "0.5.0"
MAX_BODY = 2 * 1024 * 1024
log = logging.getLogger("citebase")
INSTRUCTIONS = (
    "Citebase helps a brand get recommended and cited by AI assistants such as ChatGPT, Claude, Gemini and Perplexity. "
    "First, in any new chat: call get_history with no project to see what the user already saved, and continue "
    "there instead of starting over. Reuse saved country, language and site; do not ask again. "
    "Default path (one yes at a time): (1) get_playbook name='start', (2) audit_site with the URL and a project "
    "name so it is saved, (3) next_steps with that project, (4) offer a paid AI recommend check (a first look, "
    "then the full baseline), (5) import and measure, (6) pick one fix, log it, (7) offer a monthly re-check. "
    "Talk in short, plain words. End each answer with one next step. Never spend money or send email without "
    "the user's clear yes. " + tools.PRICE_RULE + " Paid data uses the Apify connector: quote_cost first, then "
    "call-actor. " + tools.CAP_PER_RUN + " " + tools.RUN_ONCE + " When runs finish, pass their dataset "
    "ids to import_ai_results (dataset_ids) instead of copying items. Keep progress with a project name via "
    "save_results, get_history and make_report. For drafts, check_ai_content is local and has no Citebase fee. "
    "When showing Recommendation Share, lead with the headline and show the brand-name check separately. If a "
    "site check says it could not read the site, say so and give no score. "
    + tools.DATA_NOT_INSTRUCTIONS + " " + tools.WEB_FALLBACK
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
READ_WEB = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
SAVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)
SAVE_REPORT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)  # makes a link anyone can open

TOOL_TEXT = {
    "get_playbook": (
        "Read guidelines",
        "Read Citebase's step-by-step guidelines for getting a brand recommended by AI assistants: workflows (start, "
        "seo-audit, citation-loop, outreach, link-building, press-release and more) and checklists. Use first, with "
        "name 'start', and whenever a task needs the exact steps. Not for running audits or prices: use audit_site or "
        "quote_cost. Returns the list of names (featured first) plus start_here, featured and journey, or "
        "{name, text} when a name is given. No Citebase fee."),
    "audit_site": (
        "Check a website",
        "Check one public website for search and AI-readiness problems: crawl rules, secure redirects, sitemap, titles, "
        "headlines, page text, images. Use at the start of any project and for every re-check; pass a project name "
        "to save it and see what was fixed since last time. Not for private or local addresses; no JavaScript is "
        "run. Returns a headline, a 0-100 score (none if the site could not be read) and the top problems. "
        "No Citebase fee; takes up to a minute."),
    "quote_cost": (
        "Quote costs",
        "Get the spending cap for paid Apify data jobs, and the amount when the user asks what a task costs. Use "
        "before every call-actor run: pass a pack name (for example ai_check_pilot, ai_check, starter, keywords) or "
        "custom items; add project to get ready-to-run inputs for the AI check. Not for running jobs, and do not "
        "read amounts out unless asked. Returns run_caps (the cap for each Actor run as "
        "callOptions.maxTotalChargeUsd), ready_runs and the totals. No Citebase fee."),
    "measure_recommendation_share": (
        "Measure AI recommendations",
        "Turn AI-answer test results into Recommendation Share: how often ChatGPT, Perplexity, Gemini and others "
        "recommend the brand in buying questions (brand-name questions are a separate reputation check), with "
        "ranges, the smallest change the panel can see and a verdict on each logged change. Use after collecting "
        "answers for a fixed panel, or with a project name. Not for collecting answers; it never saves (use "
        "save_results). Returns a headline, numbers, warnings and a markdown report. No Citebase fee."),
    "next_steps": (
        "What to do next",
        "Turn audit and measurement results into a short plain-language to-do list: what to do, why, who does it, how "
        "long it takes. Use after audit_site or measure_recommendation_share, or when asked 'what should I do next?'. "
        "Pass a project name and it reads the saved results itself and skips steps already done. Not a substitute "
        "for reading the results first. Returns ranked steps plus a 30-day re-check reminder. No Citebase fee."),
    "save_results": (
        "Save progress",
        "Save a project's details in the user's own Apify account: AI-answer results, the question list, brand, "
        "settings, to-do updates and logged changes. Also keeps counts from a pasted server log (AI bot visits), "
        "an analytics export (visits from AI) and search positions. Use when the user agrees to a project name or "
        "shares something worth keeping; set check_only to test a question list before it is frozen. Not for "
        "measuring; site checks save themselves. Returns what was stored. No Citebase fee."),
    "get_history": (
        "Show projects and history",
        "With no project: list every saved project with its site, last checks and what is due now. Use this first "
        "in a new chat, or when the user does not say which project. With a project: its Recommendation Share per "
        "round, site health over time, what was fixed since the last check, settings and to-dos. Not for new "
        "measurements. Reads only. Returns tables, numbers and a next step. No Citebase fee."),
    "make_report": (
        "Make a shareable report",
        "Build a one-page report from a saved project (trend chart, rounds, what worked, top problems, next steps) "
        "and save it in the user's Apify account with a link. Use when the user wants something to show a boss, client "
        "or teammate. Anyone with the link can open it; say so. Not for new measurements. Returns share_url. No Citebase fee."),
    "import_ai_results": (
        "Import AI check results",
        "Bring the results of a paid or scheduled AI-answer check (AI Brand Monitor, Google AI Overviews, Google AI "
        "Mode or the two tracker Actors) into a project. Use after the runs finish: pass their dataset ids as "
        "dataset_ids and Citebase reads them itself; for a first round also send panel and brand with save true. "
        "Not for running the check. Only clearly positive wording counts as recommended; the rest goes to "
        "needs_review. Results are never counted twice. Returns counts, the review list and skipped. "
        "No Citebase fee."),
    "schedule_checks": (
        "Plan automatic checks",
        "Give the exact steps and ready-to-paste inputs to run a project's site check and AI-answer checks on a "
        "schedule (daily, weekly or monthly) in Apify Schedules, so each round can be compared with the last. Use "
        "when the user wants tracking to happen by itself, and offer it after a check. Not a scheduler: the user "
        "creates the schedule and can switch it off any time. Returns cron, the Actor runs to add with their max "
        "costs, how to stop, and a monthly estimate to share only if asked. No Citebase fee."),
    "check_outreach_draft": (
        "Check an outreach email",
        "Check one outreach email before sending: valid recipients, do-not-contact list, daily limit, leftover "
        "[brackets], length, spammy wording, opt-out line. Use for every cold email after drafting and before asking "
        "the user to approve. Not a sender: it never sends. Returns ready (true/false), problems to fix, warnings and "
        "a fingerprint of the exact text. No Citebase fee."),
    "check_ai_content": (
        "Check AI writing style",
        "Lint a draft for known AI-writing patterns (stock phrases, filler vocabulary, density per 1,000 words). Use "
        "before publishing or when the user asks if text sounds AI-generated. Not a commercial detector and never "
        "calls an API. Returns density, pass/fail vs threshold, hits and counts by pattern. No Citebase fee."),
}


def setup_logging() -> None:
    """Sends the one-line call records to stdout (Apify shows it in the run log). Safe to call more than once."""
    if not any(getattr(h, "_citebase", False) for h in log.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler._citebase = True  # type: ignore[attr-defined]
        log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def friendly(fn):
    """Shows the user-facing message of expected problems to the AI, and logs one safe line per call.

    The MCP library hides the text of ordinary exceptions as a crash; ToolError carries it through. The log line
    holds the tool name, input size, outcome and time only: never the content."""
    name = fn.__name__

    def record(started: float, kwargs: dict, ok: bool, error_class: str | None = None) -> None:
        line = {"event": "tool_call", "tool": name, "input_bytes": len(json.dumps(kwargs, default=str)),
                "ok": ok, "ms": int((time.monotonic() - started) * 1000)}
        if error_class:
            line["error_class"] = error_class  # the kind of failure only, never its text
        log.info(json.dumps(line))

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            started, ok, kind = time.monotonic(), False, None
            try:
                result = await fn(*args, **kwargs)
                ok = True
                return result
            except ValueError as err:
                kind = "bad_input"
                raise ToolError(str(err)) from err
            except Exception as err:
                kind = type(err).__name__
                raise
            finally:
                record(started, kwargs, ok, kind)
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            started, ok, kind = time.monotonic(), False, None
            try:
                result = fn(*args, **kwargs)
                ok = True
                return result
            except ValueError as err:
                kind = "bad_input"
                raise ToolError(str(err)) from err
            except Exception as err:
                kind = type(err).__name__
                raise
            finally:
                record(started, kwargs, ok, kind)
    return wrapper


def dump(items, *, exclude_none: bool = True) -> list[dict[str, Any]] | None:
    return None if items is None else [i.model_dump(exclude_none=exclude_none) for i in items]


def build_server() -> MCPServer:
    mcp = MCPServer("citebase", title="Citebase: get cited by AI", version=VERSION, instructions=INSTRUCTIONS,
                    website_url="https://apify.com/khadinakbar/citebase")

    def tool(name: str, annotations: ToolAnnotations):
        title, description = TOOL_TEXT[name]
        return mcp.tool(name=name, title=title, description=description, annotations=annotations, structured_output=True)

    @tool("get_playbook", READ_ONLY)
    @friendly
    def get_playbook(name: Annotated[Optional[str], Field(description=(
            "Which playbook to read, for example 'start' or 'citation-loop'. Leave empty to list all playbooks first. "
            "Defaults to empty. NOT a file path and NOT an Apify Actor name."))] = None) -> m.PlaybookResult:
        return m.PlaybookResult(**tools.get_playbook(name))

    @tool("audit_site", READ_WEB)
    @friendly
    async def audit_site(
            url: Annotated[Optional[str], Field(description=(
                "Address of the public website to check, for example 'https://example.com' or 'example.com'. "
                "Must be reachable from the internet. Can be left empty for a saved project that has a website. "
                "NOT a private, local or login-protected address."))] = None,
            max_pages: Annotated[int, Field(ge=1, le=30, description=(
                "How many pages to read, for example 15. Between 1 and 30. More pages take longer. "
                "Defaults to 15."))] = 15,
            project: Annotated[Optional[str], Field(description=(
                "Project name to save this check under, for example 'acme-site' (3 to 40 letters, numbers or "
                "dashes). Saves the check and shows what was fixed, what is new and what is still open since the "
                "last one. Defaults to none: nothing is saved. NOT a URL."))] = None) -> m.AuditResult:
        return m.AuditResult(**await runner.audit(url, max_pages, project))

    @tool("quote_cost", READ_ONLY)
    @friendly
    async def quote_cost(
            pack: Annotated[Optional[str], Field(json_schema_extra=m.PACK_SCHEMA, description=(
                "The easy way: a ready-made bundle, for example 'ai_check_pilot' (first look at AI recommendations), "
                "'ai_check' (full baseline), 'starter' (first look at a site), 'keywords', 'competitors', 'creators' "
                "or 'local'. Use this unless the user wants something custom. Defaults to none. NOT a job name."))] = None,
            items: Annotated[Optional[list[m.QuoteItem]], Field(max_length=50, description=(
                "Custom jobs instead of a pack, each like {\"job\": \"serp_page\", \"units\": 15}. Up to 50 items. "
                "Defaults to none. NOT a list of Actor names."))] = None,
            project: Annotated[Optional[str], Field(description=(
                "Only with pack 'ai_check' or 'ai_check_pilot': name of a saved project, for example 'acme-site'. "
                "The quote is then worked out from its saved question list and brand, and ready_runs holds the exact "
                "Actor inputs to run, so nothing has to be made up. Defaults to none. NOT a URL."))] = None
    ) -> m.QuoteResult:
        return m.QuoteResult(**await runner.quote(dump(items), pack, project))

    @tool("measure_recommendation_share", READ_ONLY)
    @friendly
    async def measure_recommendation_share(
            panel: Annotated[Optional[list[m.PanelPrompt]], Field(max_length=200, description=(
                "The fixed list of test questions, for example [{\"prompt_id\": \"p001\", \"prompt\": \"best crm for "
                "small teams\", \"type\": \"consideration\"}]. Include at least 20 buying questions (awareness or "
                "consideration, never naming the brand) and at least 5 control questions. Up to 200 items. "
                "Do not change it between rounds. Leave empty when using project."))] = None,
            runs: Annotated[Optional[list[m.RunRow]], Field(max_length=5000, description=(
                "The AI answers collected so far, one row per prompt, engine and repeat, for example [{\"snapshot\": "
                "\"baseline\", \"prompt_id\": \"p001\", \"platform\": \"chatgpt\", \"repeat\": 1, \"recommended\": true}]. "
                "Up to 5,000 rows. NOT the raw answer text. Leave empty when using project."))] = None,
            baseline: Annotated[str, Field(description=(
                "Snapshot to compare against, for example 'baseline'. Defaults to the oldest snapshot. "
                "Leave empty for the default."))] = "",
            current: Annotated[str, Field(description=(
                "Snapshot to report as the latest, for example '2026-12'. Defaults to the newest snapshot. "
                "Leave empty for the default."))] = "",
            experiments: Annotated[Optional[list[m.Experiment]], Field(max_length=100, description=(
                "Changes you made, to judge whether they helped, for example [{\"action\": \"Joined two best-of "
                "lists\", \"mechanism\": \"listicle\", \"target_prompt_ids\": \"p003,p007\"}]. Up to 100. "
                "Defaults to none. Leave empty when using project."))] = None,
            project: Annotated[Optional[str], Field(description=(
                "Name of a saved project to measure, for example 'acme-site'. Measures everything saved under it and "
                "ignores panel/runs/experiments/brand (which must be empty). Defaults to none. NOT a brand name you "
                "invent: it must match a project from save_results."))] = None,
            brand: Annotated[Optional[m.BrandInfo], Field(description=(
                "Brand details, only to warn when a buying question names the brand, for example {\"name\": \"Acme\", "
                "\"domain\": \"acme.com\"}. Defaults to none. Leave empty when using project."))] = None) -> m.MeasureResult:
        brand_dict = brand.model_dump(exclude_none=True) if brand else None
        return m.MeasureResult(**await runner.measure(project, dump(panel), dump(runs), baseline, current,
                                                      dump(experiments), brand_dict))

    @tool("save_results", SAVE)
    @friendly
    async def save_results(
            project: Annotated[str, Field(description=(
                "Project name, 3 to 40 letters, numbers or dashes, for example 'acme-site'. One project per brand or "
                "site. Reuse the same name every time. NOT a URL."))],
            runs: Annotated[Optional[list[m.RunRow]], Field(max_length=5000, description=(
                "AI answers from one or more rounds, same rows as measure_recommendation_share, for example "
                "[{\"snapshot\": \"baseline\", \"prompt_id\": \"p001\", \"platform\": \"chatgpt\", \"repeat\": 1, "
                "\"recommended\": true}]. Up to 5,000 rows. Defaults to none."))] = None,
            panel: Annotated[Optional[list[m.PanelPrompt]], Field(max_length=200, description=(
                "The test question list. Required the first time you save runs for a project; after that it is frozen "
                "and must be identical or left empty. Up to 200 items. Defaults to none."))] = None,
            experiments: Annotated[Optional[list[m.Experiment]], Field(max_length=100, description=(
                "Changes you made, to judge later whether they helped. Up to 100. Defaults to none."))] = None,
            brand: Annotated[Optional[m.BrandInfo], Field(description=(
                "Brand details to keep with the project, for example {\"name\": \"Acme\", \"domain\": \"acme.com\"}. "
                "Used for schedules and reports. Defaults to none."))] = None,
            audit: Annotated[Optional[dict[str, Any]], Field(description=(
                "The full result of audit_site, passed as is, to store a dated site check. Rarely needed: audit_site "
                "saves by itself when given a project name. Defaults to none. NOT a summary you wrote."))] = None,
            replace: Annotated[bool, Field(description=(
                "True to overwrite a round that already exists. Defaults to false. Only with the user's yes."))] = False,
            append: Annotated[bool, Field(description=(
                "True to add more repeats to a round that already exists. Defaults to false."))] = False,
            settings: Annotated[Optional[m.ProjectSettings], Field(description=(
                "Details to remember so the user is not asked again, for example {\"country\": \"gb\", \"language\": "
                "\"en\", \"frequency\": \"monthly\"}. Later checks reuse them. Defaults to none."))] = None,
            todo: Annotated[Optional[list[m.TodoItem]], Field(max_length=40, description=(
                "To-do updates, for example [{\"step\": \"Add a sitemap\", \"status\": \"done\"}]. Steps marked done "
                "or skipped are not suggested again. Up to 40. Defaults to none."))] = None,
            server_log: Annotated[Optional[str], Field(max_length=1_500_000, description=(
                "Lines pasted from the website's own access log (combined format, a few days is enough), to see "
                "which AI bots read the site and whether any are refused. Only counts are kept: no addresses, no "
                "raw lines. Defaults to none. NOT a file path or a URL."))] = None,
            traffic: Annotated[Optional[list[dict[str, Any]]], Field(max_length=5000, description=(
                "Rows from the user's analytics export, each with a source and a visit count, for example "
                "[{\"Session source\": \"chatgpt.com\", \"Sessions\": 40, \"Date\": \"20261101\"}]. Shows "
                "the visits AI assistants sent. Up to 5,000 rows. Defaults to none."))] = None,
            traffic_csv: Annotated[Optional[str], Field(max_length=1_500_000, description=(
                "The same analytics export pasted as CSV text with its header row, instead of traffic rows. "
                "Defaults to none. NOT a file path or a URL."))] = None,
            ranks: Annotated[Optional[list[m.RankRow]], Field(max_length=500, description=(
                "Search positions to keep over time, one row per keyword and engine, for example [{\"keyword\": "
                "\"payroll software\", \"position\": 7, \"engine\": \"google\"}]. Use null for position when the site "
                "was not found. Each save is compared with the one before. Up to 500. Defaults to none."))] = None,
            check_only: Annotated[bool, Field(description=(
                "True to check and review without storing anything: use it on a new question list before the "
                "first save, because the list cannot change afterwards. Defaults to false."))] = False
    ) -> m.SaveResult:
        brand_dict = brand.model_dump(exclude_none=True) if brand else None
        settings_dict = settings.model_dump(exclude_none=True) if settings else None
        return m.SaveResult(**await runner.save(project, dump(runs), dump(panel), dump(experiments), brand_dict, audit,
                                                replace, append, settings_dict, dump(todo), server_log, traffic,
                                                traffic_csv, dump(ranks, exclude_none=False), check_only))

    @tool("get_history", READ_ONLY)
    @friendly
    async def get_history(project: Annotated[Optional[str], Field(description=(
            "Name of a saved project, for example 'acme-site'. Leave empty to list every saved project with what is "
            "due: do that first in a new chat. Defaults to none. NOT a URL."))] = None) -> m.HistoryResult:
        return m.HistoryResult(**await hist.history(project))

    @tool("make_report", SAVE_REPORT)
    @friendly
    async def make_report(project: Annotated[str, Field(description=(
            "Name of a saved project, for example 'acme-site'. NOT a URL."))]) -> m.ReportLinkResult:
        return m.ReportLinkResult(**await runner.make_report(project))

    @tool("import_ai_results", SAVE)
    @friendly
    async def import_ai_results(
            project: Annotated[str, Field(description=(
                "Project name, for example 'acme-site'. For a new project also send panel (and brand) and save true."))],
            snapshot: Annotated[str, Field(description=(
                "Round name for these results, for example '2026-12' or 'baseline'. Letters, numbers, dashes."))],
            dataset_ids: Annotated[Optional[list[str]], Field(max_length=20, description=(
                "The best way: dataset ids of the finished runs, for example ['aBcD1234efGh5678'] (each run's "
                "defaultDatasetId). Citebase reads the results itself. Put all runs of one round in one call. Up to "
                "20. Defaults to none. NOT run ids or web addresses."))] = None,
            items: Annotated[Optional[list[dict[str, Any]]], Field(max_length=5000, description=(
                "Only when dataset_ids cannot be used: the dataset items of an AI check run, passed as is, for "
                "example the list from get-dataset-items. Up to 5,000 items. Defaults to none. NOT a summary."))] = None,
            save: Annotated[bool, Field(description=(
                "True to store the converted rows in the project. Defaults to false: only convert, so you can review "
                "first."))] = False,
            append: Annotated[bool, Field(description="True to add to an existing round. Defaults to false.")] = False,
            replace: Annotated[bool, Field(description="True to overwrite an existing round, only with the user's yes. Defaults to false.")] = False,
            panel: Annotated[Optional[list[m.PanelPrompt]], Field(max_length=200, description=(
                "The test question list, exactly as used in the check. Needed only the first time (a project with no "
                "saved list); after that it is frozen and must be identical or left empty. Up to 200 items. "
                "Defaults to none."))] = None,
            brand: Annotated[Optional[m.BrandInfo], Field(description=(
                "Brand details, for example {\"name\": \"Acme\", \"domain\": \"acme.com\"}. Needed to judge Google AI "
                "Mode results; saved with the project when save is true. Defaults to the brand already saved."))] = None,
            context: Annotated[Optional[m.ImportContext], Field(description=(
                "The country, language and device the check was run for, copied from the Actor's input, for results "
                "that do not say (Google AI Mode does not). Defaults to none."))] = None
    ) -> m.ImportResult:
        brand_dict = brand.model_dump(exclude_none=True) if brand else None
        context_dict = context.model_dump(exclude_none=True) if context else None
        return m.ImportResult(**await runner.import_results(project, items, snapshot, save, append, replace, dump(panel),
                                                            brand_dict, context_dict, dataset_ids))

    @tool("schedule_checks", READ_ONLY)
    @friendly
    async def schedule_checks(
            project: Annotated[str, Field(description="Name of the project to schedule, for example 'acme-site'.")],
            url: Annotated[Optional[str], Field(description=(
                "The site to check on schedule, for example 'https://example.com'. Defaults to the website saved with "
                "the project; needed only when the project has none."))] = None,
            frequency: Annotated[Optional[str], Field(description=(
                "'daily', 'weekly' or 'monthly'. Defaults to the frequency saved with the project, else 'weekly'."))] = None,
            max_pages: Annotated[int, Field(ge=1, le=30, description="Pages per site check, 1 to 30. Defaults to 15.")] = 15,
            platforms: Annotated[Optional[list[str]], Field(max_length=10, description=(
                "AI engines to check, for example ['perplexity', 'chatgpt', 'gemini', 'google-aio', 'google-aimode']. "
                "Defaults to the engines of the project's first saved round, or ChatGPT, Perplexity, Gemini and Google "
                "AI Overviews."))] = None,
            repeats: Annotated[int, Field(ge=1, le=5, description=(
                "How many times each question is asked of the AI assistants (ChatGPT, Perplexity, Gemini), for example "
                "3. Between 1 and 5. Google AI Overviews and AI Mode are asked once. Defaults to 3."))] = 3
    ) -> m.SchedulePlanResult:
        return m.SchedulePlanResult(**await runner.schedule(project, url, frequency, max_pages, None, None, platforms,
                                                            repeats))

    @tool("next_steps", READ_ONLY)
    @friendly
    async def next_steps(
            project: Annotated[Optional[str], Field(description=(
                "The easy way: name of a saved project, for example 'acme-site'. Reads its latest site check and AI "
                "results itself and skips steps already marked done. Defaults to none. NOT a URL."))] = None,
            audit: Annotated[Optional[dict[str, Any]], Field(description=(
                "Only without a project: the full result object returned by audit_site, passed as is. Defaults to "
                "none. NOT a summary you wrote yourself."))] = None,
            report: Annotated[Optional[dict[str, Any]], Field(description=(
                "Only without a project: the full result object returned by measure_recommendation_share, passed as "
                "is. Defaults to none. NOT a summary you wrote yourself."))] = None,
            max_steps: Annotated[int, Field(ge=1, le=10, description=(
                "How many steps to return, for example 5. Between 1 and 10. Defaults to 5."))] = 5
    ) -> m.NextStepsResult:
        return m.NextStepsResult(**await runner.next_steps(audit, report, max_steps, project))

    @tool("check_outreach_draft", READ_ONLY)
    @friendly
    def check_outreach_draft(
            to: Annotated[list[str], Field(min_length=1, max_length=50, description=(
                "Recipient addresses, for example [\"sam@example.com\"]. Plain name@domain addresses only. "
                "1 to 50 items. NOT names or display text."))],
            subject: Annotated[str, Field(max_length=300, description=(
                "The email subject, for example 'Payroll cost data for your piece'. Under 60 characters works best. "
                "NOT the body."))],
            body: Annotated[str, Field(max_length=20000, description=(
                "The full email text, for example 'Hi Sam, I read your piece on...'. About 60 to 90 words works "
                "best. NOT a summary of the email."))],
            suppressed: Annotated[Optional[list[str]], Field(max_length=5000, description=(
                "Do-not-contact list: addresses or domains, for example [\"bad@x.com\", \"@blocked.org\"]. "
                "Defaults to none."))] = None,
            sent_today: Annotated[int, Field(ge=0, le=100000, description=(
                "How many emails were already sent today, for example 4. Defaults to 0."))] = 0,
            daily_cap: Annotated[int, Field(ge=1, le=100000, description=(
                "Most emails allowed per day, for example 20. Defaults to 20."))] = 20) -> m.OutreachResult:
        return m.OutreachResult(**tools.check_outreach_draft(to, subject, body, suppressed, sent_today, daily_cap))

    @tool("check_ai_content", READ_ONLY)
    @friendly
    def check_ai_content(
            text: Annotated[str, Field(max_length=200000, description=(
                "The draft to lint, for example the full article body pasted as plain text or Markdown. "
                "Code fences are skipped. NOT a file path and NOT a URL."))],
            threshold: Annotated[float, Field(gt=0, le=100, description=(
                "Max hits per 1,000 words before fail, for example 5. Between 0 exclusive and 100. "
                "Defaults to 5."))] = 5.0) -> m.AiContentResult:
        return m.AiContentResult(**tools.check_ai_content(text, threshold))

    @mcp.custom_route("/run", methods=["POST"])
    async def run(request):
        """Plain JSON endpoint: POST {"tool": "...", "arguments": {...}}. This is what assistants reach through
        mcp.apify.com, which turns the web-server description into one generic HTTP tool."""
        too_big = JSONResponse({"ok": False, "error": "Request is too large (limit 2 MB). Send less data."}, 413)
        declared = request.headers.get("content-length") or "0"
        if not declared.isdigit() or int(declared) > MAX_BODY:
            return too_big
        body = bytearray()
        async for chunk in request.stream():  # also stops chunked uploads that never declare a size
            body += chunk
            if len(body) > MAX_BODY:
                return too_big
        try:
            data = json.loads(bytes(body))
        except ValueError:
            return JSONResponse({"ok": False, "error": 'Send JSON like {"tool": "get_playbook", "arguments": {}}.'}, 400)
        if not isinstance(data, dict):
            return JSONResponse({"ok": False, "error": 'Send a JSON object like {"tool": "get_playbook"}.'}, 400)
        tool_name = str(data.get("tool") or "")
        started = time.monotonic()
        try:
            result = await runner.run_tool(tool_name, data.get("arguments"))
        except ValueError as err:
            log.info(json.dumps({"event": "run_call", "tool": tool_name, "ok": False, "error_class": "bad_input",
                                 "ms": int((time.monotonic() - started) * 1000)}))
            return JSONResponse({"ok": False, "error": str(err)}, 400)
        except Exception as err:  # a fault in Citebase itself: one log line with the class, never the content
            log.info(json.dumps({"event": "run_call", "tool": tool_name, "ok": False,
                                 "error_class": type(err).__name__, "ms": int((time.monotonic() - started) * 1000)}))
            return JSONResponse({"ok": False, "error": "Citebase hit an unexpected problem with this request. "
                                                       "Try again; if it keeps happening, report it on the Actor's "
                                                       "Issues tab."}, 500)
        log.info(json.dumps({"event": "run_call", "tool": tool_name, "ok": True,
                             "ms": int((time.monotonic() - started) * 1000)}))
        return JSONResponse({"ok": True, "tool": tool_name, "result": result})

    @mcp.custom_route("/", methods=["GET"])
    async def readiness(_request):  # Apify's readiness probe and a human-readable landing line
        return PlainTextResponse("Citebase MCP server is running. Connect your AI assistant to /mcp.")

    return mcp


def build_app():
    return build_server().streamable_http_app(
        json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))  # Apify proxy fronts this
