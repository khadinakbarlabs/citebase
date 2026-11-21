"""Signed-in operations shared by the dashboard, HTTP clients and AI assistants."""
from importlib import import_module
from typing import Any, Literal, get_args

from pydantic import BaseModel, Field

import storage
import tools
import work_auth

Operation = Literal[
    "project_focus",
    "onboarding_get", "onboarding_suggest", "onboarding_save", "questions_update", "seo_plan", "research_get", "research_plan", "research_import",
    "citation_contact", "citation_prospect_save", "outreach_prepare", "outreach_claim", "outreach_status",
    "brief_get", "brief_save", "page_inspect", "actions_list", "action_save", "action_recheck",
    "opportunities_list", "changes_list", "runs_list", "offers_list", "offer_dismiss", "offer_measure_record",
    "schedule_preview", "schedule_apply", "schedule_list", "schedule_pause", "schedule_resume",
    "prospects_list", "prospect_save", "draft_save", "draft_approve", "digest_get", "digest_save", "digest_handoff",
]
MODULES = {
    "work_onboarding": {"onboarding_get", "onboarding_suggest", "onboarding_save", "questions_update"},
    "work_plan": {"seo_plan"},
    "work_research": {"research_get", "research_plan", "research_import"},
    "work_citation_outreach": {"citation_contact", "citation_prospect_save", "outreach_prepare", "outreach_claim", "outreach_status"},
    "work_focus": {"project_focus"},
    "work_actions": {"brief_get", "brief_save", "page_inspect", "actions_list", "action_save", "action_recheck"},
    "work_insights": {"opportunities_list", "changes_list", "runs_list", "offers_list", "offer_dismiss", "offer_measure_record"},
    "work_schedules": {"schedule_preview", "schedule_apply", "schedule_list", "schedule_pause", "schedule_resume"},
    "work_outreach": {"prospects_list", "prospect_save", "draft_save", "draft_approve", "digest_get", "digest_save", "digest_handoff"},
}


class WorkResult(BaseModel):
    project: str = Field(description="The selected project in the signed-in account.")
    operation: Operation = Field(description="The operation requested for this project.")
    result: dict[str, Any] = Field(description="The current record, result list or confirmation receipt for this operation.")


# Named GETs are always read-only. The POST/MCP lists for actions, digests and schedules also support
# legacy to-do migration, enabled weekly archives and expiry of a previously approved schedule.
READ_ONLY = {"onboarding_get", "research_get", "research_plan", "citation_contact", "outreach_prepare", "outreach_status",
             "project_focus", "seo_plan", "brief_get", "page_inspect", "opportunities_list", "changes_list", "runs_list",
             "prospects_list", "offers_list", "digest_handoff"}


async def execute(project, operation, data=None, *, read_only=False):
    client = await work_auth.require_caller()
    if not isinstance(operation, str) or operation not in get_args(Operation):
        raise ValueError("Choose an available project work operation.")
    if not isinstance(project, str) or storage.clean_slug(project) != project:
        raise ValueError("Select the exact saved project name, for example 'acme-site'.")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("Send the fields for the selected operation as a JSON object.")
    tools.reject_non_finite(data)
    reads_saved_proposal = operation == "schedule_preview" and set(data) == {"plan_id"}
    for module, names in MODULES.items():
        if operation in names:
            from work_storage import for_caller
            async with for_caller(client, read_only=read_only or reads_saved_proposal or operation in READ_ONLY):
                result = await import_module(module).execute(project, operation, data)
            return {"project": project, "operation": operation, "result": result}
    raise ValueError("Unknown project work operation.")
