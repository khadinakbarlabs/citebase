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

VERSION = "0.4.1"
MAX_BODY = 2 * 1024 * 1024
log = logging.getLogger("citebase")
INSTRUCTIONS = (
    "Citebase helps a brand get recommended and cited by AI assistants such as ChatGPT, Claude, Gemini and Perplexity. "
    "Default path (one yes at a time): (1) get_playbook name='start', (2) audit_site when you have a URL, "
    "(3) next_steps with that audit, (4) offer a quoted AI recommend check — one-round about $9 or pack ai_check "
    "about $24 — only after quote_cost and a clear yes. Talk in short, plain words. Never spend money or send email "
    "without the user's clear yes. Paid data uses the Apify connector: quote_cost first, then call-actor with "
    "callOptions.maxTotalChargeUsd = suggested_cap_usd. Keep progress with a project name via save_results, "
    "get_history and make_report. For drafts, check_ai_content is local and has no Citebase fee. When showing "
    "Recommendation Share, lead with the headline and show the brand-name check separately. "
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
        "headlines, page text, images. Use at the start of any SEO or 'get cited by AI' project. Not for private or "
        "local addresses; it does not run JavaScript. Returns a 0-100 health score, scores per area and the top "
        "problems with example pages. No Citebase fee; takes up to a minute."),
    "quote_cost": (
        "Quote costs",
        "Work out what paid Apify data jobs will cost and which spending cap to use. Use before every call-actor "
        "run: pass a pack name (starter, keywords, competitors, creators, local, ai_check) or custom items. Not for "
        "running jobs: it only prices them. Returns each job's cost, the total and suggested_cap_usd "
        "for callOptions.maxTotalChargeUsd. No Citebase fee."),
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
        "Not a substitute for reading the results first. Returns ranked steps plus a 30-day re-check reminder. No Citebase fee."),
    "save_results": (
        "Save progress",
        "Save AI-answer results, the question list, brand details and/or a site check under a project name in the "
        "user's own Apify account, so progress can be compared next month. Use after a round of answers or audit_site, "
        "once the user agrees to a project name; the question list can go in first, alone. Not for measuring: use "
        "measure_recommendation_share. The list is frozen after the first save. Returns what was stored. No Citebase fee."),
    "get_history": (
        "Show history",
        "Show a saved project's history: Recommendation Share per round with ranges, site health score over time and "
        "logged changes. Use when the user asks 'how am I doing?' or returns to a project. Not for new measurements. "
        "Reads only. Returns tables and numbers. No Citebase fee."),
    "make_report": (
        "Make a shareable report",
        "Build a one-page report from a saved project (trend chart, rounds, what worked, top problems, next steps) "
        "and save it in the user's Apify account with a link. Use when the user wants something to show a boss, client "
        "or teammate. Anyone with the link can open it; say so. Not for new measurements. Returns share_url. No Citebase fee."),
    "import_ai_results": (
        "Import AI check results",
        "Convert results of a paid or scheduled AI-answer check (AI Brand Monitor, Google AI Overviews, Google AI Mode "
        "or the two tracker Actors) into Citebase rows. Use after the check, even for a first round: send panel and brand "
        "with save true and the project is created in one step. Not for running the check. Only clearly positive "
        "wording counts as recommended; other mentions go to needs_review and skipped items are counted. Returns "
        "rows, the review list and skipped. No Citebase fee."),
    "schedule_checks": (
        "Plan automatic checks",
        "Give the exact steps and ready-to-paste inputs to run a project's site check and AI-answer checks on a "
        "schedule (daily, weekly or monthly) in Apify Schedules, so each round can be compared with the last. Use "
        "when the user wants tracking to happen by itself. Not a scheduler: the user creates the schedule. Returns "
        "cron, the Actor runs to add, and the worst-case monthly cost. No Citebase fee."),
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

    def record(started: float, kwargs: dict, ok: bool) -> None:
        log.info(json.dumps({"event": "tool_call", "tool": name, "input_bytes": len(json.dumps(kwargs, default=str)),
                             "ok": ok, "ms": int((time.monotonic() - started) * 1000)}))

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            started, ok = time.monotonic(), False
            try:
                result = await fn(*args, **kwargs)
                ok = True
                return result
            except ValueError as err:
                raise ToolError(str(err)) from err
            finally:
                record(started, kwargs, ok)
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            started, ok = time.monotonic(), False
            try:
                result = fn(*args, **kwargs)
                ok = True
                return result
            except ValueError as err:
                raise ToolError(str(err)) from err
            finally:
                record(started, kwargs, ok)
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
            url: Annotated[str, Field(description=(
                "Address of the public website to check, for example 'https://example.com' or 'example.com'. "
                "Must be reachable from the internet. NOT a private, local or login-protected address."))],
            max_pages: Annotated[int, Field(ge=1, le=30, description=(
                "How many pages to read, for example 15. Between 1 and 30. More pages take longer. "
                "Defaults to 15."))] = 15) -> m.AuditResult:
        return m.AuditResult(**await runner.audit(url, max_pages))

    @tool("quote_cost", READ_ONLY)
    @friendly
    def quote_cost(
            pack: Annotated[Optional[str], Field(json_schema_extra=m.PACK_SCHEMA, description=(
                "The easy way: a ready-made bundle, for example 'starter' (first look at a site), 'keywords', "
                "'competitors', 'creators', 'local' or 'ai_check'. Use this unless the user wants something custom. "
                "Defaults to none. NOT a job name."))] = None,
            items: Annotated[Optional[list[m.QuoteItem]], Field(max_length=50, description=(
                "Custom jobs instead of a pack, each like {\"job\": \"serp_page\", \"units\": 15}. Up to 50 items. "
                "Defaults to none. NOT a list of Actor names."))] = None) -> m.QuoteResult:
        return m.QuoteResult(**tools.quote_cost(dump(items), pack))

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
                "The full result of audit_site, passed as is, to store a dated site check. Defaults to none. "
                "NOT a summary you wrote."))] = None,
            replace: Annotated[bool, Field(description=(
                "True to overwrite a round that already exists. Defaults to false. Only with the user's yes."))] = False,
            append: Annotated[bool, Field(description=(
                "True to add more repeats to a round that already exists. Defaults to false."))] = False
    ) -> m.SaveResult:
        brand_dict = brand.model_dump(exclude_none=True) if brand else None
        return m.SaveResult(**await runner.save(project, dump(runs), dump(panel), dump(experiments), brand_dict, audit,
                                                replace, append))

    @tool("get_history", READ_ONLY)
    @friendly
    async def get_history(project: Annotated[str, Field(description=(
            "Name of a saved project, for example 'acme-site'. NOT a URL."))]) -> m.HistoryResult:
        return m.HistoryResult(**await hist.history(project))

    @tool("make_report", SAVE_REPORT)
    @friendly
    async def make_report(project: Annotated[str, Field(description=(
            "Name of a saved project, for example 'acme-site'. NOT a URL."))]) -> m.ReportLinkResult:
        return m.ReportLinkResult(**await runner.report.make_report(project))

    @tool("import_ai_results", SAVE)
    @friendly
    async def import_ai_results(
            project: Annotated[str, Field(description=(
                "Project name, for example 'acme-site'. For a new project also send panel (and brand) and save true."))],
            items: Annotated[list[dict[str, Any]], Field(min_length=1, max_length=5000, description=(
                "The dataset items of an AI check run, passed as is, for example the list from get-dataset-items. "
                "1 to 5,000 items. NOT a summary."))],
            snapshot: Annotated[str, Field(description=(
                "Round name for these results, for example '2026-12' or 'baseline'. Letters, numbers, dashes."))],
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
                                                            brand_dict, context_dict))

    @tool("schedule_checks", READ_ONLY)
    @friendly
    async def schedule_checks(
            project: Annotated[str, Field(description="Name of the project to schedule, for example 'acme-site'.")],
            url: Annotated[Optional[str], Field(description=(
                "The site to check on schedule, for example 'https://example.com'. Defaults to the website saved with "
                "the project; needed only when the project has none."))] = None,
            frequency: Annotated[str, Field(description="'daily', 'weekly' or 'monthly'. Defaults to 'weekly'.")] = "weekly",
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
    def next_steps(
            audit: Annotated[Optional[dict[str, Any]], Field(description=(
                "The full result object returned by audit_site, passed as is. Defaults to none. "
                "NOT a summary you wrote yourself."))] = None,
            report: Annotated[Optional[dict[str, Any]], Field(description=(
                "The full result object returned by measure_recommendation_share, passed as is. Defaults to none. "
                "NOT a summary you wrote yourself."))] = None,
            max_steps: Annotated[int, Field(ge=1, le=10, description=(
                "How many steps to return, for example 5. Between 1 and 10. Defaults to 5."))] = 5
    ) -> m.NextStepsResult:
        return m.NextStepsResult(**tools.next_steps(audit, report, max_steps))

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
            log.info(json.dumps({"event": "run_call", "tool": tool_name, "ok": False,
                                 "ms": int((time.monotonic() - started) * 1000)}))
            return JSONResponse({"ok": False, "error": str(err)}, 400)
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
