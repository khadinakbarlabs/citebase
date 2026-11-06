"""Typed inputs and outputs of the Citebase tools.

These become the MCP inputSchema / outputSchema, so every field carries a plain-language description with an
example. Output fields that can be missing are explicit nulls, never absent.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

import tools

JOB_NAMES = tuple(sorted(tools.PRICES["jobs"]))
JobName = Literal[JOB_NAMES]  # type: ignore[valid-type]
PromptType = Literal["awareness", "consideration", "brand", "control"]
Mechanism = Literal["onpage", "fact-page", "listicle", "review-site", "press", "reddit", "youtube", "directory",
                    "podcast", "creator", "schema", "llms-txt", "technical", "other"]


# ------------------------------------------------------------------ outputs
class PlaybookItem(BaseModel):
    name: str = Field(description="Playbook name to pass to get_playbook, for example 'start'.")
    kind: Literal["skill", "reference"] = Field(description="'skill' = step-by-step workflow; 'reference' = checklist or rules.")
    about: str = Field(description="One-line summary of what the playbook is for.")


class PlaybookResult(BaseModel):
    playbooks: Optional[list[PlaybookItem]] = Field(None, description="All playbooks. Set only when no name was given, else null.")
    start_here: Optional[str] = Field(None, description="Name of the playbook to read first. Set only when listing, else null.")
    name: Optional[str] = Field(None, description="Name of the playbook returned. Set only when a name was given, else null.")
    text: Optional[str] = Field(None, description="Full playbook text (Markdown). Set only when a name was given, else null.")


class AuditProblem(BaseModel):
    level: Literal["fail", "warn"] = Field(description="'fail' = fix first; 'warn' = worth fixing soon.")
    area: str = Field(description="Area of the check: technical, on-page or ai-search.")
    check: str = Field(description="Name of the check, for example 'Exactly one H1'.")
    detail: str = Field(description="What was found, in one or two sentences.")
    example_urls: list[str] = Field(description="Up to 3 example pages with the problem. Empty when not page-specific.")


class AuditResult(BaseModel):
    site: str = Field(description="The site that was checked, for example 'https://example.com'.")
    pages_checked: int = Field(description="How many pages were read (at most the max_pages asked for).")
    health_score: Optional[int] = Field(None, description="0-100 weighted score; 100 = no problems. Null if nothing could be scored.")
    subscores: dict[str, Optional[int]] = Field(description="0-100 score per area, for example {'technical': 80, 'on-page': 55}.")
    counts: dict[str, int] = Field(description="Number of checks that failed, warned and passed: {'fail': 2, 'warn': 5, 'pass': 20}.")
    problems: list[AuditProblem] = Field(description="Up to 25 problems, worst first.")
    passed: list[str] = Field(description="Names of the checks that passed.")
    limits: str = Field(description="What this check can and cannot see. Repeat this to the user when it matters.")


class QuoteLine(BaseModel):
    job: str = Field(description="Job name that was priced, for example 'serp_page'.")
    actor: str = Field(description="The Apify Actor that runs this job, for example 'khadinakbar/scrape-google-serp'.")
    units: float = Field(description="How many units were priced.")
    unit: str = Field(description="What one unit is, for example 'SERP page'.")
    requests: int = Field(description="How many separate runs (per-run fees are charged once per run).")
    cost_usd: float = Field(description="Cost of this line in US dollars, including the tiny start fee.")


class QuoteResult(BaseModel):
    lines: list[QuoteLine] = Field(description="One entry per priced job.")
    total_usd: float = Field(description="Total estimated cost in US dollars.")
    suggested_cap_usd: float = Field(description="Spending cap to pass as callOptions.maxTotalChargeUsd (total x 1.3, rounded up to the cent).")
    how_to_run: str = Field(description="Plain instruction for running the jobs with the cap.")
    prices_read_on: str = Field(description="Date the public prices were read, YYYY-MM-DD.")
    heads_up: str = Field(description="Caveat about estimates. Tell the user.")


class MeasureResult(BaseModel):
    snapshots: list[str] = Field(description="Snapshot names found in the runs, oldest first.")
    baseline: str = Field(description="Snapshot used as the starting point.")
    current: str = Field(description="Snapshot used as the latest.")
    warnings: list[str] = Field(description="Reasons to be careful with the numbers (too few prompts, no controls...). Always tell the user.")
    summary: dict[str, dict[str, Any]] = Field(description="Per engine (and 'all'): prompts, recommendation_share, rs_low, rs_high, mentioned_rate, cited_rate, control_false_positive, min_repeats. Rates are 0-1.")
    change: dict[str, dict[str, Any]] = Field(description="Per engine (and 'all') change since the baseline: delta, low, high, verdict ('improved', 'worsened' or 'no detectable change'), control_drift. Empty when baseline equals current.")
    experiments: list[dict[str, Any]] = Field(description="One entry per logged change: exp_id, mechanism, action, result (target_delta, other_delta, did, low, high, verdict 'supported'/'inconclusive'/'worse') and confounded.")
    due: list[str] = Field(description="Changes old enough to re-measure now.")
    markdown: str = Field(description="Ready-to-show report in Markdown.")


class Step(BaseModel):
    step: str = Field(description="What to do, in plain words.")
    why: str = Field(description="Why it matters, in one sentence.")
    who: str = Field(description="Who does it: 'you', 'your web developer', 'Claude'...")
    effort: str = Field(description="Rough time needed, for example '1 hour'.")
    urgency: Literal["now", "do first", "soon", "later"] = Field(description="When to do it.")
    based_on: str = Field(description="Which finding this step comes from.")


class NextStepsResult(BaseModel):
    steps: list[Step] = Field(description="Ranked steps; the last is always a 30-day re-check reminder.")
    tip: str = Field(description="One sentence of advice to pass on to the user.")


class OutreachResult(BaseModel):
    ready: bool = Field(description="True when nothing blocks sending. Warnings do not block.")
    problems: list[str] = Field(description="Things that must be fixed before sending. Empty when ready.")
    warnings: list[str] = Field(description="Things that would improve the email. Optional to fix.")
    recipients: list[str] = Field(description="The valid addresses found, lower-cased.")
    word_count: int = Field(description="Words in the body. About 60-90 works best.")
    fingerprint: str = Field(description="12-character code of the exact text; any edit changes it.")
    next: str = Field(description="What to do next: show the user the text and wait for a yes.")


# ------------------------------------------------------------------ inputs
class QuoteItem(BaseModel):
    job: JobName = Field(description="Which paid job to price, for example 'serp_page' (Google results page) or 'ai_brand_check' (one AI answer check). NOT an Apify Actor name.")
    units: float = Field(ge=0, le=1_000_000, description="How many units of that job, for example 15 for 15 results pages. Between 0 and 1,000,000. NOT dollars.")
    requests: int = Field(1, ge=0, le=1000, description="How many separate runs the units are split across, for example 1. Some jobs charge a fee per run, so fewer runs cost less. Defaults to 1.")


class PanelPrompt(BaseModel):
    prompt_id: str = Field(description="Short unique id for the prompt, for example 'p001'.")
    prompt: str = Field(description="The question a customer would ask an AI, for example 'best CRM for small teams'. Non-brand prompts must not contain the brand name.")
    type: PromptType = Field(description="'awareness', 'consideration', 'brand', or 'control' (a question where the brand should NOT be recommended; used to measure noise).")
    topic: str = Field("", description="Optional topic label, for example 'crm'. Defaults to empty.")


class RunRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    snapshot: str = Field(description="Name of the measuring round, for example 'baseline' or '2026-12'. Use the same prompts and engines in every round.")
    prompt_id: str = Field(description="Which panel prompt this answer is for, for example 'p001'.")
    platform: str = Field(description="Which AI answered, for example 'chatgpt', 'perplexity', 'gemini', 'claude' or 'google-aio'.")
    repeat: int = Field(1, ge=1, description="Which repeat of the same prompt and engine this is, starting at 1. Ask at least 3 times; answers vary.")
    recommended: bool = Field(description="True if the answer offers the brand as an option for the user's need with neutral-to-positive wording. NOT true for a passing mention or a warning.")
    mentioned: bool = Field(False, description="True if the brand is named at all. Defaults to false.")
    cited: bool = Field(False, description="True if a brand-owned link is among the answer's sources. Defaults to false.")
    date: Optional[str] = Field(None, description="Date of the answer, YYYY-MM-DD, for example '2026-11-06'. Defaults to today.")


class Experiment(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str = Field(description="What was changed, in plain words, for example 'Added the brand to two best-of lists'.")
    mechanism: Mechanism = Field("other", description="Kind of change, for example 'listicle' or 'onpage'. Defaults to 'other'.")
    target_prompt_ids: str = Field(description="Comma-separated prompt ids the change should help, for example 'p003,p007'.")
    date: Optional[str] = Field(None, description="Date the change went live, YYYY-MM-DD. Defaults to today.")
    recheck_after: Optional[str] = Field(None, description="Date to measure again, YYYY-MM-DD. Defaults to none.")
