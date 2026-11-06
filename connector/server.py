"""Citebase MCP server: exposes the plugin's playbooks and tools to web assistants (claude.ai, ChatGPT, ...).

Stateless by design: nothing is stored between calls, so the server holds no customer data.
Every tool has a plain-language description, described inputs and a typed output schema.
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

import models as m  # noqa: E402
import tools  # noqa: E402

VERSION = "0.3.0"
MAX_BODY = 2 * 1024 * 1024
log = logging.getLogger("citebase")
INSTRUCTIONS = (
    "Citebase helps a brand get recommended and cited by AI assistants such as ChatGPT, Claude, Gemini and Perplexity. "
    "Start by calling get_playbook with name 'start', then follow it. Talk to the user in short, plain words. "
    "Never spend money or send email without the user's clear yes. Paid data comes from the separate Apify connector; "
    "use quote_cost first and pass its suggested cap to call-actor as callOptions.maxTotalChargeUsd."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
READ_WEB = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
AUDIT_SLOTS = asyncio.Semaphore(2)  # protects memory when several people audit at once

TOOL_TEXT = {
    "get_playbook": (
        "Read guidelines",
        "Read Citebase's step-by-step guidelines for getting a brand recommended by AI assistants: workflows (start, "
        "seo-audit, citation-loop, outreach, link-building, press-release and more) and checklists. Use first, with "
        "name 'start', and whenever a task needs the exact steps. Not for running audits or prices: use audit_site or "
        "quote_cost. Returns the list of names, or {name, text}. Free."),
    "audit_site": (
        "Check a website",
        "Check one public website for search and AI-readiness problems: crawl rules, secure redirects, sitemap, titles, "
        "headlines, page text, images. Use at the start of any SEO or 'get cited by AI' project. Not for private or "
        "local addresses; it does not run JavaScript. Returns a 0-100 health score, scores per area and the top "
        "problems with example pages. Free; takes up to a minute."),
    "quote_cost": (
        "Quote costs",
        "Work out what a set of paid Apify data jobs will cost and which spending cap to use. Use before every "
        "call-actor run. Not for running jobs: it only prices them. Items are {job, units, requests}. Returns each "
        "job's cost, the total and suggested_cap_usd (total x 1.3) for callOptions.maxTotalChargeUsd. Free."),
    "measure_recommendation_share": (
        "Measure AI recommendations",
        "Turn AI-answer test results into Recommendation Share: how often ChatGPT, Perplexity, Gemini and others "
        "actively recommend the brand, with ranges, noise from control questions and a verdict on each logged change. "
        "Use after collecting answers for a fixed prompt panel. Not for collecting answers. Returns numbers, warnings "
        "and a markdown report. Stores nothing, so give the user their data to keep. Free."),
    "next_steps": (
        "What to do next",
        "Turn audit and measurement results into a short plain-language to-do list: what to do, why, who does it, how "
        "long it takes. Use after audit_site or measure_recommendation_share, or when asked 'what should I do next?'. "
        "Not a substitute for reading the results first. Returns ranked steps plus a 30-day re-check reminder. Free."),
    "check_outreach_draft": (
        "Check an outreach email",
        "Check one outreach email before sending: valid recipients, do-not-contact list, daily limit, leftover "
        "[brackets], length, spammy wording, opt-out line. Use for every cold email after drafting and before asking "
        "the user to approve. Not a sender: it never sends. Returns ready (true/false), problems to fix, warnings and "
        "a fingerprint of the exact text. Free."),
}


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
                    website_url="https://github.com/khadinakbarlabs/citebase")

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
        async with AUDIT_SLOTS:
            return m.AuditResult(**await asyncio.to_thread(tools.run_audit, url, max_pages))

    @tool("quote_cost", READ_ONLY)
    @friendly
    def quote_cost(items: Annotated[list[m.QuoteItem], Field(min_length=1, max_length=50, description=(
            "The paid jobs to price, each like {\"job\": \"serp_page\", \"units\": 15}. Between 1 and 50 items. "
            "NOT a list of Actor names."))]) -> m.QuoteResult:
        return m.QuoteResult(**tools.quote_cost(dump(items)))

    @tool("measure_recommendation_share", READ_ONLY)
    @friendly
    def measure_recommendation_share(
            panel: Annotated[list[m.PanelPrompt], Field(min_length=1, max_length=200, description=(
                "The fixed list of test questions, for example [{\"prompt_id\": \"p001\", \"prompt\": \"best crm for "
                "small teams\", \"type\": \"consideration\"}]. Include at least 5 control questions. 1 to 200 items. "
                "Do not change it between rounds."))],
            runs: Annotated[list[m.RunRow], Field(min_length=1, max_length=5000, description=(
                "The AI answers collected so far, one row per prompt, engine and repeat, for example [{\"snapshot\": "
                "\"baseline\", \"prompt_id\": \"p001\", \"platform\": \"chatgpt\", \"repeat\": 1, \"recommended\": true}]. "
                "1 to 5,000 rows. NOT the raw answer text."))],
            baseline: Annotated[str, Field(description=(
                "Snapshot to compare against, for example 'baseline'. Defaults to the oldest snapshot. "
                "Leave empty for the default."))] = "",
            current: Annotated[str, Field(description=(
                "Snapshot to report as the latest, for example '2026-12'. Defaults to the newest snapshot. "
                "Leave empty for the default."))] = "",
            experiments: Annotated[Optional[list[m.Experiment]], Field(max_length=100, description=(
                "Changes you made, to judge whether they helped, for example [{\"action\": \"Joined two best-of "
                "lists\", \"mechanism\": \"listicle\", \"target_prompt_ids\": \"p003,p007\"}]. Up to 100. "
                "Defaults to none."))] = None) -> m.MeasureResult:
        return m.MeasureResult(**tools.measure(dump(panel), dump(runs), baseline, current, dump(experiments)))

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

    @mcp.custom_route("/run", methods=["POST"])
    async def run(request):
        """Plain JSON endpoint: POST {"tool": "...", "arguments": {...}}. This is what assistants reach through
        mcp.apify.com, which turns the web-server description into one generic HTTP tool."""
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return JSONResponse({"ok": False, "error": "Request is too large (limit 2 MB). Send less data."}, 413)
        try:
            data = await request.json()
        except ValueError:
            return JSONResponse({"ok": False, "error": 'Send JSON like {"tool": "get_playbook", "arguments": {}}.'}, 400)
        if not isinstance(data, dict):
            return JSONResponse({"ok": False, "error": 'Send a JSON object like {"tool": "get_playbook"}.'}, 400)
        tool_name = str(data.get("tool") or "")
        started = time.monotonic()
        try:
            if tool_name == "audit_site":
                async with AUDIT_SLOTS:
                    result = await asyncio.to_thread(tools.dispatch, tool_name, data.get("arguments"))
            else:
                result = await asyncio.to_thread(tools.dispatch, tool_name, data.get("arguments"))
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
