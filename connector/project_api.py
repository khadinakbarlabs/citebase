"""Named HTTP routes sharing the signed-in operations used by the dashboard and MCP."""
import json

from starlette.responses import JSONResponse

import project_work
from work_auth import CallerError

# Each entry is (HTTP method, resource, operation, ID field populated from path).
ROUTES = (
    ("GET", "onboarding", "onboarding_get", None), ("POST", "onboarding/suggestions", "onboarding_suggest", None),
    ("PATCH", "onboarding", "onboarding_save", None), ("PATCH", "questions", "questions_update", None),
    ("GET", "seo-plan", "seo_plan", None), ("GET", "research", "research_get", None),
    ("GET", "research/plan", "research_plan", None), ("POST", "research/imports", "research_import", None),
    ("POST", "citations/contact", "citation_contact", None), ("POST", "citations/prospects", "citation_prospect_save", None),
    ("POST", "outreach-drafts/{item}/prepare", "outreach_prepare", "prospectId"),
    ("POST", "outreach-drafts/{item}/claim", "outreach_claim", "prospectId"),
    ("GET", "outreach-drafts/{item}/status", "outreach_status", "prospectId"),
    ("GET", "focus", "project_focus", None),
    ("GET", "brief", "brief_get", None), ("PATCH", "brief", "brief_save", None),
    ("POST", "pages/inspect", "page_inspect", None),
    ("GET", "opportunities", "opportunities_list", None), ("GET", "changes", "changes_list", None),
    ("GET", "runs", "runs_list", None), ("GET", "runs/{item}", "runs_list", "run_id"),
    ("GET", "actions", "actions_list", None), ("POST", "actions", "action_save", None),
    ("PATCH", "actions/{item}", "action_save", "id"), ("POST", "actions/{item}/recheck", "action_recheck", "id"),
    ("POST", "schedule-plans", "schedule_preview", None), ("POST", "schedules", "schedule_apply", None),
    ("GET", "schedules", "schedule_list", None), ("POST", "schedules/{item}/pause", "schedule_pause", "schedule_id"),
    ("POST", "schedules/{item}/resume", "schedule_resume", "schedule_id"),
    ("GET", "prospects", "prospects_list", None), ("POST", "prospects", "prospect_save", None),
    ("PATCH", "prospects/{item}", "prospect_save", "id"), ("POST", "outreach-drafts", "draft_save", None),
    ("POST", "outreach-drafts/{item}/approve", "draft_approve", "prospectId"),
    ("GET", "digest", "digest_get", None), ("PUT", "digest", "digest_save", None),
    ("POST", "digest/handoff", "digest_handoff", None),
    ("GET", "offers", "offers_list", None), ("POST", "offers/{item}/dismiss", "offer_dismiss", "id"),
    ("POST", "offer-measurements", "offer_measure_record", None),
)


def register(mcp, max_body):
    def endpoint(operation, key):
        async def handle(request):
            headers = {"Cache-Control": "private, no-store"}
            try:
                read_only = request.method in {"GET", "HEAD"}
                if read_only:
                    data = dict(request.query_params)
                else:
                    body = bytearray()
                    async for chunk in request.stream():
                        if len(body) + len(chunk) > max_body:
                            return JSONResponse({"error": "The request is too large."}, 413, headers=headers)
                        body.extend(chunk)
                    try:
                        data = json.loads(body) if body else {}
                    except (ValueError, RecursionError):
                        raise ValueError("Send one JSON object.") from None
                if not isinstance(data, dict):
                    raise ValueError("Send the fields as one object.")
                if key:
                    item = request.path_params["item"]
                    if data.get(key, item) != item:
                        raise ValueError("The selected record differs from the one in the request.")
                    data[key] = item
                result = await project_work.execute(request.path_params["project"], operation, data, read_only=read_only)
                return JSONResponse(result, headers=headers)
            except CallerError as error:
                return JSONResponse({"error": str(error)}, 401, headers=headers)
            except ValueError as error:
                return JSONResponse({"error": str(error)}, 400, headers=headers)
            except Exception:
                return JSONResponse({"error": "Citebase could not complete this project operation."}, 500, headers=headers)
        return handle

    for method, resource, operation, key in ROUTES:
        path = "/v1/projects/{project}/" + resource
        mcp.custom_route(path, methods=[method])(endpoint(operation, key))
