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
PACK_NAMES = tuple(sorted(tools.PRICES.get("packs", {})))
# The tool takes the pack name as text and checks it in quote_cost, so a wrong name gets a plain sentence listing the
# valid ones. The list stays visible to clients through this schema.
PACK_SCHEMA = {"anyOf": [{"type": "string", "enum": list(PACK_NAMES)}, {"type": "null"}]}
PromptType = Literal["awareness", "consideration", "brand", "control"]
Mechanism = Literal["onpage", "fact-page", "listicle", "review-site", "press", "reddit", "youtube", "directory",
                    "podcast", "creator", "schema", "llms-txt", "technical", "other"]


# ------------------------------------------------------------------ outputs
class PlaybookItem(BaseModel):
    name: str = Field(description="Playbook name to pass to get_playbook, for example 'start'.")
    kind: Literal["skill", "reference"] = Field(description="'skill' = step-by-step workflow; 'reference' = checklist or rules.")
    about: str = Field(description="One-line summary of what the playbook is for.")


class JourneyStep(BaseModel):
    step: int = Field(description="Order in the default path, starting at 1.")
    do: str = Field(description="What the assistant should do at this step, in plain words.")
    playbook: str = Field(description="Playbook name to read for detail, for example 'start'.")


class PlaybookResult(BaseModel):
    playbooks: Optional[list[PlaybookItem]] = Field(None, description="All playbooks. Set only when no name was given, else null.")
    start_here: Optional[str] = Field(None, description="Name of the playbook to read first. Set only when listing, else null.")
    journey: Optional[list[JourneyStep]] = Field(
        None, description="Default path to get a brand cited by AI. Set only when listing playbooks, else null.")
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
    saved: Optional[dict[str, Any]] = Field(None, description="Set only when a project name was given: {project, saved_on, trend}. trend is {previous_date, previous_score, change} when an earlier check exists, else null. Null when nothing was saved.")
    next: str = Field(description="One short line on what to do next: call next_steps with this result, then offer a quoted AI recommend check. Say it in your own words.")


class QuoteLine(BaseModel):
    job: str = Field(description="Job name that was priced, for example 'serp_page'.")
    actor: str = Field(description="The Apify Actor that runs this job, for example 'khadinakbar/scrape-google-serp'.")
    units: float = Field(description="How many units were priced.")
    unit: str = Field(description="What one unit is, for example 'SERP page'.")
    requests: int = Field(description="How many separate runs (per-run fees are charged once per run).")
    cost_usd: float = Field(description="Cost of this line in US dollars at its realistic worst case: results, start fees and any Apify compute.")
    compute_usd: Optional[float] = Field(None, description="The part of cost_usd that is Apify compute billed on top of the data price. Missing when there is none.")
    note: Optional[str] = Field(None, description="One plain sentence when this line is priced at a fallback rate. Missing otherwise.")
    not_before: Optional[str] = Field(None, description="Date (YYYY-MM-DD) before which this job cannot run, because Apify's fees for it are not live yet. Missing when it can run now.")


class QuoteResult(BaseModel):
    pack: Optional[str] = Field(None, description="Name of the pack that was priced, for example 'starter'. Null when single jobs were priced.")
    pack_about: Optional[str] = Field(None, description="One plain sentence about what the pack gets you. Null when single jobs were priced.")
    lines: list[QuoteLine] = Field(description="One entry per priced job.")
    total_usd: float = Field(description="Total estimated cost in US dollars.")
    suggested_cap_usd: float = Field(description="Spending cap to pass as callOptions.maxTotalChargeUsd (total x 1.3, rounded up to the cent). It covers only the jobs that can run now and is 0 when none can.")
    how_to_run: str = Field(description="Plain instruction for running the jobs with the cap.")
    prices_read_on: str = Field(description="Date the public prices were read, YYYY-MM-DD.")
    heads_up: str = Field(description="Caveat about estimates, including that whether Apify's cap counts compute is unconfirmed. Tell the user.")
    includes_compute_usd: Optional[float] = Field(None, description="Apify compute included in total_usd, in US dollars. Null when none is billed on top of the data prices.")
    compute_note: Optional[str] = Field(None, description="One plain sentence saying how much of the total is Apify compute, for example 'This total includes about $0.05 of Apify compute...'. Say it to the user. Null when there is none.")
    warnings: list[str] = Field(default_factory=list, description="Plain warnings, for example that a job cannot run until a date. Empty when there is nothing to warn about. Always tell the user.")
    runnable_total_usd: Optional[float] = Field(None, description="Total of the jobs that can run now, in US dollars. Set only when some job cannot run yet, otherwise null.")


class MeasureResult(BaseModel):
    snapshots: list[str] = Field(description="Snapshot names found in the runs, oldest first.")
    baseline: str = Field(description="Snapshot used as the starting point.")
    current: str = Field(description="Snapshot used as the latest.")
    headline: Optional[str] = Field(None, description="One plain sentence with the headline number: how often AI recommends the brand in buying questions, with a likely range. Lead with it. Null when there are no buying questions.")
    warnings: list[str] = Field(description="Reasons to be careful with the numbers (too few buying questions or controls, different engines or repeats, older counting, brand name inside a question, zero results...). Always tell the user.")
    summary: dict[str, dict[str, Any]] = Field(description="Per engine (and 'all') for the latest round. prompts = buying questions (awareness and consideration) only. recommendation_share, rs_low, rs_high = the headline, 0-1. mentioned_rate, cited_rate, control_false_positive, min_repeats. reputation_share, reputation_low, reputation_high, reputation_prompts = the separate check on brand-name questions (null when none): show it apart from the headline. metric_version (2 = current counting) and older_metric (true = counted more loosely, do not compare with newer rounds). Rates are 0-1.")
    change: dict[str, dict[str, Any]] = Field(description="Per engine (and 'all') change since the baseline: delta, low, high, min_detectable_points (smallest change the panel can reliably see), comparable, control_drift, note (may be empty) and verdict: 'improved', 'worsened', 'no detectable change', 'too early to tell' (the range could hide a real change), 'engines moved' (control questions moved the same way, so it may be the AI engines) or 'not comparable' (different counting versions). Empty when baseline equals current.")
    smallest_change_points: Optional[int] = Field(None, description="Smallest change in whole percentage points this panel can reliably see, for example 14. Say it with any verdict. Null when unknown.")
    experiments: list[dict[str, Any]] = Field(description="One entry per logged change: exp_id, mechanism, action, timing ('ok', 'before_baseline', 'after_current', 'undated' or 'rounds_not_separated' when both rounds carry the same dates; only 'ok' is scored), note (why it was not scored, else empty), confounded and confounded_with (ids of overlapping changes) and result (null when not scored; else target_delta, other_delta, did, low, high, others_excluded, engine_wide_likely, min_detectable_points, reading, verdict 'supported', 'inconclusive' or 'worse').")
    due: list[str] = Field(description="Changes old enough to re-measure now.")
    markdown: str = Field(description="Ready-to-show report in Markdown.")
    project: Optional[str] = Field(None, description="Project name the numbers came from. Set only when a saved project was used, else null.")
    context: Optional[dict[str, Any]] = Field(None, description="Where each round's answers came from, for the baseline and the current round: per engine the number of answers and any recorded model, country, language, device and collection method. Engines with nothing recorded show only the answer count. Null when unknown.")
    next: str = Field(description="One short line on what to offer next, for example saving results or a 30-day re-check. Say it in your own words.")


class Step(BaseModel):
    step: str = Field(description="What to do, in plain words.")
    why: str = Field(description="Why it matters, in one sentence.")
    who: str = Field(description="Who does it: 'you', 'your site builder or host', 'Claude'...")
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


class AiContentHit(BaseModel):
    line: int = Field(description="1-based line number in the draft.")
    pattern: str = Field(description="Pattern id, for example 'P35' or 'P36'.")
    name: str = Field(description="Short name of the pattern, for example 'ai-vocabulary'.")
    match: str = Field(description="The matching excerpt, truncated.")


class AiContentPatternCount(BaseModel):
    pattern: str = Field(description="Pattern id, for example 'P35'.")
    count: int = Field(description="How many times this pattern fired.")


class AiContentResult(BaseModel):
    """Return shape for check_ai_content. Callers: connector/server.py check_ai_content tool."""
    words: int = Field(description="Word count of the draft (code fences skipped).")
    hit_count: int = Field(description="Total pattern hits found.")
    density_per_1000_words: float = Field(description="Hits per 1,000 words. Lower is better.")
    threshold: float = Field(description="Fail when density is at or above this number. Default 5.")
    pass_: bool = Field(alias="pass", description="True when density is under the threshold.")
    hits: list[AiContentHit] = Field(description="Up to 100 hits, earliest lines first.")
    by_pattern: list[AiContentPatternCount] = Field(description="Hit counts grouped by pattern id, worst first.")
    limits: str = Field(description="What this check is and is not. Tell the user in plain words.")
    next: str = Field(description="What to offer next: rewrite, re-check, or a trust/SEO pass.")

    model_config = ConfigDict(populate_by_name=True)


class SaveResult(BaseModel):
    project: str = Field(description="Project name as saved (lower-case, dashes).")
    snapshots_saved: dict[str, int] = Field(description="Rows now stored per round, for example {'baseline': 54}.")
    panel_prompts: int = Field(description="Number of test questions in the project's frozen list.")
    snapshots_in_project: list[str] = Field(description="All rounds saved in the project, in name order.")
    brand: dict[str, Any] = Field(description="Brand details saved with the project (name, domain, competitors). Empty if none.")
    stored_in: str = Field(description="Where the data lives. Tell the user it is in their own Apify account.")
    audit_saved: Optional[dict[str, Any]] = Field(None, description="Set only when an audit was saved: {project, saved_on, trend}. trend is {previous_date, previous_score, change} when an earlier check exists, else null. Null when no audit was sent.")
    warnings: list[str] = Field(default_factory=list, description="Things to fix in the question list, for example a buying question that names the brand. Tell the user. Empty when none.")
    next: str = Field(description="One short line on what to offer next, for example a 30-day re-check or schedule_checks. Say it in your own words.")


class HistoryResult(BaseModel):
    project: str = Field(description="Project name.")
    brand: dict[str, Any] = Field(description="Brand details saved with the project. Empty if none.")
    panel_prompts: int = Field(description="Number of test questions in the project.")
    snapshots: list[dict[str, Any]] = Field(description="One entry per saved round, oldest first: snapshot, saved_on, prompts (buying questions), recommendation_share, rs_low, rs_high (the headline), mentioned_rate, cited_rate, reputation_share and reputation_prompts (brand-name questions, shown apart), metric_version and older_metric (true = counted more loosely: do not compare with newer rounds), engines (which AI engines answered) and context (per engine: answers and any recorded model, country, language, device and collection method; empty when nothing was recorded). Rates are 0-1.")
    audits: list[dict[str, Any]] = Field(description="One entry per saved site check, oldest first: date, health_score, subscores.")
    experiments: list[dict[str, Any]] = Field(description="Logged changes: exp_id, date, action, mechanism, target_prompt_ids.")
    markdown: str = Field(description="Ready-to-show history tables in Markdown.")


class ReportLinkResult(BaseModel):
    project: str = Field(description="Project name.")
    share_url: Optional[str] = Field(None, description="Link to the one-page report. Anyone with the link can open it. Null if the store cannot make a link; then the report is still saved under stored_key.")
    stored_key: str = Field(description="Record name of the report inside the key-value store 'citebase-projects'.")
    bytes: int = Field(description="Size of the report page.")
    snapshots: int = Field(description="Rounds of AI-answer results included.")
    site_checks: int = Field(description="Site checks included.")
    note: str = Field(description="How sharing works and how to stop it. Tell the user.")


class ImportResult(BaseModel):
    runs: list[dict[str, Any]] = Field(description="Converted rows, ready for save_results.")
    unmatched_queries: list[str] = Field(description="Questions in the results that are not in the project's list. They were skipped.")
    needs_review: list[dict[str, Any]] = Field(description="Every mention or citation that was not clearly positive, up to 25 (close calls first), each with a reason and the sentence around it. None of them is counted as recommended until reviewed. Read them with the user and fix with save_results replace=true if needed.")
    summary: dict[str, int] = Field(description="Counts: rows, recommended, mentioned, cited, unmatched, skipped (all items left out, any reason) and needs_review (the true total, even when only 25 are listed).")
    skipped: list[dict[str, Any]] = Field(default_factory=list, description="Items that were left out, grouped by reason: reason, count, why (plain words) and an example. Reasons: diagnostic (the check could not run for that engine), unknown_shape (not a result this tool reads), no_engine (does not say which AI answered), needs_brand (cannot judge without the brand), no_question_text, no_matching_question (not in the panel), not_an_item. Tell the user when anything was skipped.")
    detected: dict[str, int] = Field(default_factory=dict, description="How many items were read from each kind of result, for example {'ai-brand-monitor': 90, 'google-ai-overviews': 20}.")
    notes: list[str] = Field(default_factory=list, description="Plain remarks about this import, for example that Google AI Overviews results carry no wording to judge so they count as cited, not recommended, or that nothing was saved yet. Pass them on.")
    context: Optional[dict[str, str]] = Field(None, description="The run settings that were used to fill in country, language or device the Actor did not report, or null when none were given.")
    saved: Optional[dict[str, Any]] = Field(None, description="Result of saving, only when save was true, else null.")


class SchedulePlanResult(BaseModel):
    frequency: str = Field(description="'daily', 'weekly' or 'monthly'.")
    cron: str = Field(description="Cron text to paste into the Apify schedule.")
    when: str = Field(description="The same schedule in plain words.")
    free_site_check: dict[str, Any] = Field(description="Actor, ready-to-paste input and cost of the free scheduled site check and report refresh.")
    ai_checks: Optional[dict[str, Any]] = Field(None, description="The scheduled AI-answer checks: repeats, engines, the Actor runs to add (each with its input, how many times to add it, cost and suggested max cost), checks and cost per round, the worst-case monthly estimate, and the country, language and device to pass as context when importing. Null when the project has no questions or brand yet.")
    steps: list[str] = Field(description="Plain steps for creating the schedule in Apify Console.")
    note: Optional[str] = Field(None, description="Why ai_checks is null, when it is. Null otherwise.")


# ------------------------------------------------------------------ inputs
class BrandInfo(BaseModel):
    name: str = Field(description="Brand name as people write it, for example 'Acme'.")
    domain: Optional[str] = Field(None, description="Main website domain, for example 'acme.com'. Defaults to none.")
    competitors: Optional[list[str]] = Field(None, max_length=20, description="Competitor brand names, for example ['Rival', 'Other Co']. Up to 20. Defaults to none.")
    aliases: Optional[list[str]] = Field(None, max_length=20, description="Other ways people write the brand, for example ['AcmePay']. Used to warn when a buying question gives the brand away. Up to 20. Defaults to none.")


class ImportContext(BaseModel):
    country: Optional[str] = Field(None, max_length=40, description="Country the checks were run for (the Actor's country setting), for example 'US'. Used only where the results do not say. Defaults to none.")
    language: Optional[str] = Field(None, max_length=40, description="Language the checks were run in, for example 'en'. Used only where the results do not say. Defaults to none.")
    device: Optional[str] = Field(None, max_length=40, description="Device type of the checks, for example 'desktop' or 'mobile'. Used only where the results do not say. Defaults to none.")
    location: Optional[str] = Field(None, max_length=80, description="Place the checks were run for, for example 'Austin, Texas'. Noted in the import result but not stored on the rows. Defaults to none.")


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
    date: Optional[str] = Field(None, description="Date of the answer, YYYY-MM-DD, for example '2026-11-06'. Defaults to the date in answered_at, else today.")
    engine_version: Optional[str] = Field(None, max_length=80, description="Which model answered, if known, for example 'gpt-4o'. Lets later rounds warn when the model changed. Defaults to unknown.")
    country: Optional[str] = Field(None, max_length=40, description="Country the question was asked from, if known, for example 'US'. Defaults to unknown.")
    language: Optional[str] = Field(None, max_length=40, description="Language the question was asked in, if known, for example 'en'. Defaults to unknown.")
    device: Optional[str] = Field(None, max_length=40, description="Device type used, if known, for example 'desktop' or 'mobile'. Defaults to unknown.")
    source: Optional[str] = Field(None, max_length=40, description="How the answer was collected, if the tool says, for example 'serpapi' or 'camoufox'. Defaults to unknown.")
    answered_at: Optional[str] = Field(None, max_length=40, description="Full time of the answer, for example '2026-11-06T10:00:00Z'. Defaults to unknown.")
    # metric_version (1 or 2) is also accepted. Leave it out for new answers: Citebase stamps the current version.


class Experiment(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: str = Field(description="What was changed, in plain words, for example 'Added the brand to two best-of lists'.")
    mechanism: Mechanism = Field("other", description="Kind of change, for example 'listicle' or 'onpage'. Defaults to 'other'.")
    target_prompt_ids: str = Field(description="Comma-separated prompt ids the change should help, for example 'p003,p007'.")
    date: Optional[str] = Field(None, description="Date the change went live, YYYY-MM-DD. It must fall after the baseline round and on or before the latest round, or the change is not scored. Defaults to today.")
    recheck_after: Optional[str] = Field(None, description="Date to measure again, YYYY-MM-DD. Defaults to 30 days after the change date.")
