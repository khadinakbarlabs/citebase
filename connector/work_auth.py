"""Bind signed-in project operations to the account that owns this Actor run."""
from contextvars import ContextVar
from contextlib import asynccontextmanager, contextmanager
import re

from apify import Actor
from storage import account_client as new_client

_request = ContextVar("citebase_project_request", default=None)


class CallerError(ValueError):
    """Request credentials could not be bound to this tenant."""


def tenant_id():
    return Actor.configuration.user_id


_BEARER = re.compile(rb"Bearer ([A-Za-z0-9._~+/\-]+=*)", re.I)


def application_token(headers):
    values = {}
    for name, value in headers:
        name = name.lower()
        if name not in (b"x-citebase-authorization", b"authorization"):
            continue
        if name in values or len(value) > 8192:
            return None
        match = _BEARER.fullmatch(value)
        if match is None:
            return None
        values[name] = match.group(1)
    tokens = set(values.values())
    return tokens.pop().decode("ascii") if len(tokens) == 1 else None


def middleware(app):
    async def scoped(scope, receive, send):
        if scope["type"] != "http":
            return await app(scope, receive, send)
        token = application_token(scope.get("headers", ()))
        reset = _request.set({"token": token})
        try:
            return await app(scope, receive, send)
        finally:
            _request.reset(reset)
    return scoped


async def require_caller():
    context = _request.get()
    if context and "client" in context:
        return context["client"]
    if not context or not context.get("token"):
        raise CallerError("Sign in to the Citebase dashboard. In Apify's managed MCP use call-actor with private_request.")
    owner = tenant_id()
    if not owner:
        raise CallerError("Citebase could not confirm the account for this server.")
    client = new_client(context["token"])
    try:
        user = await client.user().get()
    except Exception:
        raise CallerError("Citebase could not verify your account. Sign in again and retry.") from None
    if not user or user.id != owner:
        raise CallerError("Sign in with the account that owns this Citebase project.")
    context["client"] = client
    return client


@contextmanager
def batch_caller(client, *, owner, grants=None):
    """Bind a verified normal Actor start. An HTTP handler cannot enter this scope."""
    if _request.get() is not None:
        raise CallerError("Private Actor runs must start through the Apify input interface.")
    reset = _request.set({"client": client, "batch_owner": owner, "grants": grants or {}})
    try:
        yield
    finally:
        _request.reset(reset)


def batch_context():
    context = _request.get()
    return context if context and context.get("batch_owner") else None

@asynccontextmanager
async def legacy_scope(tool, args):
    """Use the verified bearer for every existing server operation that reads or writes saved data."""
    protected = (tool in {"get_history", "save_results", "make_report", "import_ai_results", "schedule_checks", "scheduled_check"}
                 or (tool in {"audit_site", "next_steps", "measure_recommendation_share", "quote_cost"}
                     and isinstance(args, dict) and args.get("project")))
    if protected:
        from work_storage import for_caller
        options = args if isinstance(args, dict) else {}
        read_only = (tool in {"get_history", "schedule_checks", "next_steps", "measure_recommendation_share", "quote_cost"}
                     or (tool == "import_ai_results" and options.get("save") is not True)
                     or (tool == "save_results" and options.get("check_only", False) is not False))
        async with for_caller(await require_caller(), read_only=read_only):
            yield
    else:
        yield
