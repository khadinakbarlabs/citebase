"""Citebase MCP server: exposes the plugin's playbooks and tools to web assistants (claude.ai, ChatGPT, ...).

Stateless by design: nothing is stored between calls, so the server holds no customer data.
"""
from __future__ import annotations

import asyncio
import functools
import inspect
import os
import sys
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.server.transport_security import TransportSecuritySettings  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402

import tools  # noqa: E402

VERSION = "0.3.0"
INSTRUCTIONS = (
    "Citebase helps a brand get recommended and cited by AI assistants such as ChatGPT, Claude, Gemini and Perplexity. "
    "Start by calling get_playbook with name 'start', then follow it. Talk to the user in short, plain words. "
    "Never spend money or send email without the user's clear yes. Paid data comes from the separate Apify connector; "
    "use quote_cost first and pass its suggested cap to call-actor as callOptions.maxTotalChargeUsd."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
READ_WEB = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
AUDIT_SLOTS = asyncio.Semaphore(2)  # protects memory when several people audit at once


def friendly(fn):
    """Shows the user-facing message of expected problems (bad input, unreachable site) to the AI.

    The MCP library hides the text of ordinary exceptions as a crash; ToolError carries it through."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except ValueError as err:
                raise ToolError(str(err)) from err
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except ValueError as err:
                raise ToolError(str(err)) from err
    return wrapper


def build_server() -> MCPServer:
    mcp = MCPServer("citebase", title="Citebase: get cited by AI", version=VERSION, instructions=INSTRUCTIONS)

    @mcp.tool(name="get_playbook", annotations=READ_ONLY, description=(
        "Read Citebase's step-by-step guidelines: skills (start, seo-audit, ai-search-visibility, citation-loop, "
        "link-building, press-release, outreach, competitor-research, seo-checklists) and references (checklists, "
        "outreach playbook, measurement rules, Apify tools and prices). Call with no name to list them, or with a name "
        "to read one. Start with 'start'. Returns the list, or {name, text}. Free."))
    @friendly
    def get_playbook(name: str | None = None) -> dict[str, Any]:
        return tools.get_playbook(name)

    @mcp.tool(name="audit_site", annotations=READ_WEB, description=(
        "Check one public website for search and AI-readiness problems: crawling rules, security redirects, sitemap, "
        "titles, headlines, page text, images. Use at the start of an SEO or 'get cited by AI' project. Not for "
        "private or local addresses, and it does not run JavaScript. Returns a 0-100 health score, scores per area, "
        "and the top problems with example pages. Free; takes up to a minute."))
    @friendly
    async def audit_site(url: str, max_pages: int = 15) -> dict[str, Any]:
        async with AUDIT_SLOTS:
            return await asyncio.to_thread(tools.run_audit, url, max_pages)

    @mcp.tool(name="quote_cost", annotations=READ_ONLY, description=(
        "Work out what a set of paid data jobs will cost on the user's Apify account, and the spending cap to use. "
        "Use before any call-actor run. Items look like {job, units, requests}; jobs include serp_page, keyword_ideas, "
        "backlinks, ai_brand_check, ai_overview, website_contact, email_verify. Returns per-job costs, the total, and "
        "suggested_cap_usd (total x 1.3) to pass as callOptions.maxTotalChargeUsd. Free."))
    @friendly
    def quote_cost(items: list[dict[str, Any]]) -> dict[str, Any]:
        return tools.quote_cost(items)

    @mcp.tool(name="measure_recommendation_share", annotations=READ_ONLY, description=(
        "Turn AI-answer test results into Recommendation Share: how often ChatGPT, Perplexity, Gemini and others "
        "actively recommend the brand, with confidence ranges, control-question noise, change since the baseline and "
        "a verdict on each logged change. Use after collecting answers for a fixed prompt panel; read the "
        "citation-loop playbook first. Send panel [{prompt_id, prompt, type}], runs [{snapshot, prompt_id, platform, "
        "repeat, mentioned, cited, recommended}] and optional experiments. Returns numbers, warnings and a markdown "
        "report. Stores nothing: give the user their data to keep. Free."))
    @friendly
    def measure_recommendation_share(panel: list[dict[str, Any]], runs: list[dict[str, Any]], baseline: str = "",
                                     current: str = "", experiments: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return tools.measure(panel, runs, baseline, current, experiments)

    @mcp.tool(name="next_steps", annotations=READ_ONLY, description=(
        "Turn audit and measurement results into a short, plain-language to-do list: what to do, why, who does it, how "
        "long it takes. Use after audit_site and/or measure_recommendation_share, and when the user asks 'what "
        "should I do next?'. Send the audit result and/or the measurement report. Returns up to max_steps ranked "
        "steps plus a re-check reminder. Free."))
    @friendly
    def next_steps(audit: dict[str, Any] | None = None, report: dict[str, Any] | None = None,
                   max_steps: int = 5) -> dict[str, Any]:
        return tools.next_steps(audit, report, max_steps)

    @mcp.tool(name="check_outreach_draft", annotations=READ_ONLY, description=(
        "Check one outreach email before it is sent: valid recipients, do-not-contact list, daily limit, leftover "
        "[brackets], length, spammy wording, a way to opt out. Use for every cold email, after drafting and before "
        "asking the user to approve. Not a sender: it never sends anything. Returns ready (true/false), problems that "
        "must be fixed, warnings, and a short fingerprint of the exact text. Free."))
    @friendly
    def check_outreach_draft(to: list[str] | str, subject: str, body: str, suppressed: list[str] | None = None,
                             sent_today: int = 0, daily_cap: int = 20) -> dict[str, Any]:
        return tools.check_outreach_draft(to, subject, body, suppressed, sent_today, daily_cap)

    @mcp.custom_route("/", methods=["GET"])
    async def readiness(_request):  # Apify's readiness probe and a human-readable landing line
        return PlainTextResponse("Citebase MCP server is running. Connect your AI assistant to /mcp.")

    return mcp


def build_app():
    return build_server().streamable_http_app(
        json_response=True, stateless_http=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))  # Apify proxy fronts this
