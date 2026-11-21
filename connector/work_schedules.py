"""Caller-owned recurring checks and a durable, append-only project allowance ledger."""

import asyncio
import datetime as dt
import secrets
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import history
import scheduled_import as si
import storage

OPERATIONS = {"schedule_preview", "schedule_list", "schedule_apply", "schedule_pause", "schedule_resume"}
PREVIEW = {
    "frequency",
    "timezone",
    "include_ai",
    "monthly_allowance",
    "stop_date",
    "platforms",
    "repeats",
    "max_pages",
    "url",
    "prompt_ids",
    "local_time",
    "weekday",
    "month_day",
}
PLATFORM_COST = "Apify bills platform usage separately, including scheduler starts, stopped checks and retries."
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
QUEUE_FIELDS = ("schedule_ledger_id", "schedule_lock_id")
DEFINITE_CREATE_REJECTIONS = {400, 401, 403, 404, 422}
_queue_grants = ContextVar("citebase_schedule_queues", default={})


STOP_POLICY = (
    "Checks stop after the last check date. Citebase requests an Apify pause at the final check "
    "and on your next signed-in schedule view. If permission is unavailable, Apify can charge for "
    "scheduled starts until you pause it."
)


def past_cutoff(summary):
    stop = summary.get("stop_date")
    return bool(stop and dt.datetime.now(ZoneInfo(summary["timezone"])).date().isoformat() > stop)


def has_remaining_occurrence(summary):
    return next_occurrence(summary, dt.datetime.now(dt.timezone.utc)) is not None


def clock_options(data, frequency):
    local_time = data.get("local_time", "08:00")
    if not isinstance(local_time, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", local_time):
        raise ValueError("Choose a local time in HH:MM format, such as 08:00.")
    weekday, month_day = data.get("weekday", 0), data.get("month_day", 1)
    if type(weekday) is not int or not 0 <= weekday <= 6 or ("weekday" in data and frequency != "weekly"):
        raise ValueError("Use a weekday from 0 (Monday) to 6 (Sunday) for a weekly schedule.")
    if type(month_day) is not int or not 1 <= month_day <= 28 or ("month_day" in data and frequency != "monthly"):
        raise ValueError("Choose a day from 1 to 28 for a check that runs every month.")
    hour, minute = map(int, local_time.split(":"))
    cron = f"{minute} {hour} {month_day if frequency == 'monthly' else '*'} * {(weekday + 1) % 7 if frequency == 'weekly' else '*'}"
    # Omitted and explicit defaults must still match previously approved plan fingerprints.
    settings = {}
    if local_time != "08:00":
        settings["local_time"] = local_time
    if weekday:
        settings["weekday"] = weekday
    if month_day != 1:
        settings["month_day"] = month_day
    return settings, cron


def scheduled_day(summary, day):
    return ((summary["frequency"] != "weekly" or day.weekday() == summary.get("weekday", 0))
            and (summary["frequency"] != "monthly" or day.day == summary.get("month_day", 1)))


def next_occurrence(summary, after):
    """First future local wall-clock occurrence inside the plan's inclusive stop date."""
    zone = ZoneInfo(summary["timezone"])
    day = after.astimezone(zone).date()
    instant = after.astimezone(dt.timezone.utc)
    wall_time = dt.time.fromisoformat(summary.get("local_time", "08:00"))
    # The selected monthly day occurs in every month. A DST gap may skip one occurrence.
    for _ in range(65):
        if summary.get("stop_date") and day.isoformat() > summary["stop_date"]:
            return None
        if scheduled_day(summary, day):
            local = dt.datetime.combine(day, wall_time, zone)
            utc = local.astimezone(dt.timezone.utc)
            if utc > instant and utc.astimezone(zone) == local:
                return utc
        day += dt.timedelta(days=1)
    return None


def cadence(summary):
    frequency = summary["frequency"]
    when = ("Every " + WEEKDAYS[summary.get("weekday", 0)] if frequency == "weekly" else
            f"Day {summary.get('month_day', 1)} of every month" if frequency == "monthly" else "Every day")
    return when + " at " + summary.get("local_time", "08:00")


@contextmanager
def queue_grants(data):
    ids = {key: data[key] for key in QUEUE_FIELDS if data.get(key) is not None}
    if ids and (set(ids) != set(QUEUE_FIELDS) or any(not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9]{5,80}", v) for v in ids.values())):
        raise ValueError("Select the two Apify queues from the confirmed Citebase schedule.")
    token = _queue_grants.set(ids)
    try:
        yield
    finally:
        _queue_grants.reset(token)


def queue_name(field, project=None):
    base = "citebase-schedule-ledger" if field == "schedule_ledger_id" else "citebase-lock-" + si.fingerprint(project)[:12]
    name = storage.actor_owned_store_name(base)
    if not name:
        raise ValueError("The schedule requires a verified Citebase Actor identity.")
    return name


def restricted(info):
    effective = getattr(info, "effective_general_access", None) or getattr(info, "effectiveGeneralAccess", None)
    return getattr(info, "general_access", None) == "RESTRICTED" and effective in (None, "RESTRICTED")


async def caller_queue(be, name):
    """Create a private queue only if the exact name is unused. Existing sharing is never changed."""
    named = be.client.request_queue(be.selection.username + "~" + name)
    found = await named.get()
    if found is None:
        # A nameless POST always creates a new queue. Apply private access and its canonical name together.
        fresh = be.selection.owned(await be.client.request_queues().get_or_create())
        if fresh.name or fresh.total_request_count:
            raise ValueError("Citebase could not verify a new empty schedule queue.")
        own = be.client.request_queue(fresh.id)
        try:
            await own.update(name=name, general_access="RESTRICTED")
        except Exception:
            winner = await named.get()
            if winner is None:
                raise
            if winner.id != fresh.id:
                # A concurrent creator won the canonical name. Delete only our known, still-unused scratch queue.
                scratch = await own.get()
                if (scratch and scratch.id == fresh.id and scratch.user_id == be.selection.owner and not scratch.name
                        and scratch.total_request_count == 0):
                    await own.delete()
        found = await named.get()
    resource = be.selection.owned(found)
    if resource.name != name:
        raise ValueError("Apify returned a different schedule queue.")
    return resource


async def queue_id(be, field, project=None):
    name = queue_name(field, project)
    granted = _queue_grants.get().get(field)
    if granted:
        try:
            info = await be.client.request_queue(granted).get()
        except Exception as err:
            if getattr(err, "status_code", None) == 403:
                raise ValueError("Apify denied the confirmed queue grant. Sign in and review this schedule's storage permissions.") from None
            raise
        if not info or info.id != granted or info.name != name:
            raise ValueError("The Apify queue differs from this project's confirmed schedule.")
        if not restricted(info):
            raise ValueError("Set the schedule queue's General access to Restricted in Apify before running this check.")
        return granted
    if hasattr(be, "selection"):
        return (await caller_queue(be, name)).id
    try:
        resource = await be.client.request_queues().get_or_create(name=name)
    except Exception as err:
        if getattr(err, "status_code", None) == 403:
            raise ValueError("Citebase cannot access this schedule queue. Sign in and confirm a revised schedule to grant access to its existing queues.") from None
        raise
    return resource.id


async def private_queue_grants(be, project, owner, existing):
    grants = {}
    for field in QUEUE_FIELDS:
        ident = existing.get(field) or await queue_id(be, field, project)
        info = await be.client.request_queue(ident).get()
        name = queue_name(field, project)
        if not info or info.id != ident or info.name != name or info.user_id != owner or not restricted(info):
            raise ValueError(f"Set the existing Apify queue '{name}' to Restricted in its General access settings, then preview the schedule again.")
        grants[field] = ident
    return grants


@asynccontextmanager
async def schedule_lock(be, project):
    """One expiring platform lease per project, shared across dashboard and scheduler processes."""
    if isinstance(be, storage.MemoryBackend):
        if not hasattr(be, "schedule_locks"):
            be.schedule_locks = {}
        async with be.schedule_locks.setdefault(project, asyncio.Lock()):
            yield
        return
    ident = await queue_id(be, "schedule_lock_id", project)
    queue = be.client.request_queue(ident, client_key=secrets.token_hex(8))
    mutex = await queue.add_request({"url": "https://example.invalid/", "uniqueKey": "project-schedule-mutex"})
    head = await queue.list_and_lock_head(limit=1, lock_duration=dt.timedelta(minutes=5))
    if not head.items or head.items[0].id != mutex.request_id:
        raise ValueError("Another schedule change is in progress. Retry this confirmation shortly.")
    try:
        async with asyncio.timeout(90):
            yield
    finally:
        await queue.delete_request_lock(mutex.request_id)


async def _account():
    from apify import Actor
    from work_auth import require_caller, tenant_id

    client = await require_caller()
    owner = tenant_id()
    actor = Actor.configuration.actor_id
    if not owner or not actor:
        raise ValueError("Citebase could not confirm the scheduled Actor and account.")
    return client, owner, actor


class Ledger:
    def __init__(self, backend, queue):
        self.backend, self.queue = backend, queue

    @classmethod
    async def open(cls, backend):
        if isinstance(backend, storage.MemoryBackend):
            return cls(backend, None)
        # Only opaque hashes and counters are stored here. A distinct, named queue persists across runs.
        ident = await queue_id(backend, "schedule_ledger_id")
        return cls(backend, backend.client.request_queue(ident))

    async def amount(self, key):
        unique = si.fingerprint(key)
        if self.queue is None:
            return self.backend.data.get("schedule-ledger." + unique)
        from apify.storage_clients._apify._utils import unique_key_to_request_id
        rec = await self.queue.get_request(unique_key_to_request_id(unique))
        if not rec:
            return None
        value = getattr(rec.user_data, "amount", None)
        if rec.unique_key != unique or type(value) is not int or value < 1:
            raise ValueError("The monthly reservation could not be verified.")
        return value

    async def claim(self, key, amount=1):
        """Atomically insert or return the previous claimant's reservation size."""
        unique = si.fingerprint(key)
        if self.queue is None:
            record = "schedule-ledger." + unique
            if record in self.backend.data:
                return False, self.backend.data[record]
            self.backend.data[record] = amount
            return True, amount
        reply = await self.queue.add_request(
            {"url": "https://example.invalid/", "uniqueKey": unique, "userData": {"amount": amount}}
        )
        if not reply.was_already_present:
            return True, amount
        record = await self.queue.get_request(reply.request_id)
        previous = getattr(getattr(record, "user_data", None), "amount", None)
        if type(previous) is not int or previous < 1:
            raise ValueError("The schedule allowance could not be verified. Review Activity.")
        return False, previous


class DuplicateOccurrence(ValueError):
    pass


async def reserve(be, project, schedule_id, when, checks, allowance, *, charged_at=None, timezone=None):
    ledger = await Ledger.open(be)
    utc = when.astimezone(dt.timezone.utc).replace(second=0, microsecond=0)
    month = (charged_at or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc).strftime("%Y-%m")
    claimed, _ = await ledger.claim(["occurrence", project, schedule_id, utc.isoformat()])
    if not claimed:
        raise DuplicateOccurrence("This schedule occurrence was already reserved. No further checks started.")
    if timezone:
        local_day = when.astimezone(ZoneInfo(timezone)).date().isoformat()
        claimed, _ = await ledger.claim(["local-date", project, schedule_id, timezone, local_day])
        if not claimed:
            raise DuplicateOccurrence("This local day's check was already reserved. No further checks started.")
    used = 0
    while used + checks <= allowance:
        claimed, previous = await ledger.claim(["month", project, month, used], checks)
        if claimed:
            return used + checks
        used += previous
    raise ValueError("This project's monthly check allowance was reached. No further checks started.")


def plan_key(project, pid):
    if not isinstance(pid, str) or not si.FINGERPRINT.fullmatch(pid):
        raise ValueError("Select an exact previewed plan for this project.")
    return storage.key(project, "schedule-plans", pid)


def matches_plan_id(plan, project, pid):
    if not isinstance(plan, dict) or not isinstance(plan.get("summary"), dict) or plan["summary"].get("project") != project:
        return False
    # Grants are loaded from their own record only after the approved payload is verified.
    approved = {key: value for key, value in plan.items() if key != "options"}
    return si.fingerprint(approved) == pid


async def load_plan(be, project, pid):
    plan = await be.get(plan_key(project, pid))
    if not plan:
        return None
    if not matches_plan_id(plan, project, pid):
        raise ValueError("This saved schedule proposal changed. Review the settings and create a fresh preview.")
    # Queue grants are attached only by a confirmed change. An overlapping read-only preview
    # must never remove grants from the immutable plan by overwriting an older copy.
    grants = await be.get(storage.key(project, "schedule-queues", pid))
    return {**plan, "queue_grants": grants} if grants else plan


def rejection_key(project, plan):
    body = {k: v for k, v in plan.items() if k not in ("options", "queue_grants", "create_attempt")}
    return storage.key(project, "schedule-create-rejections", si.fingerprint(body))


async def preview(be, project, owner, actor, data):
    import runner

    if set(data) - PREVIEW:
        raise ValueError("The schedule preview contains unsupported options.")
    if project not in await history.list_projects():
        raise ValueError("Save the project before planning a schedule.")
    zone = data.get("timezone", "UTC")
    try:
        ZoneInfo(zone)
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        raise ValueError("Select an IANA timezone such as Asia/Karachi.") from None
    stop = data.get("stop_date") or None
    if stop:
        try:
            stop = dt.date.fromisoformat(stop).isoformat()
        except (ValueError, TypeError):
            raise ValueError("Use a stop date in YYYY-MM-DD format.") from None
    include = data.get("include_ai", False)
    if type(include) is not bool:
        raise ValueError("Choose whether to include paid AI checks.")
    opts = {k: data[k] for k in ("frequency", "url", "repeats", "platforms", "max_pages") if k in data}
    panel = (await history.load_project(project))["panel"]
    ids = data.get("prompt_ids")
    if ids is not None:
        if (
            not include
            or not isinstance(ids, list)
            or not ids
            or any(not isinstance(i, str) for i in ids)
            or len(ids) != len(set(ids))
            or not set(ids) <= {p["prompt_id"] for p in panel}
        ):
            raise ValueError("Select saved question IDs for the paid check.")
        panel = [p for p in panel if p["prompt_id"] in ids]
    plan = await runner.schedule(project, panel=panel, **opts)
    custom_clock, cron = clock_options(data, plan["frequency"])
    ai = plan.get("ai_checks") or {}
    inp = ai.get("site_check_input") if include else plan["free_site_check"]["input"]
    if not inp:
        raise ValueError("Choose fewer AI checks or save a question panel and brand first.")
    if inp.get("project_store_id"):
        from work_storage import require_private_project_store, runtime_opens_project_store
        if await runtime_opens_project_store(be):
            inp.pop("project_store_id")
        else:
            await require_private_project_store(be)
    checks = 1 + (ai["checks_per_round"] if include else 0)
    allowance = data.get("monthly_allowance", checks)
    if type(allowance) is not int or not checks <= allowance <= 100000:
        raise ValueError(f"Set a monthly allowance from {checks} to 100000 checks. One site check counts as one.")
    if ids is not None:
        inp["arguments"]["ai_import"]["managed_checks"]["prompt_ids"] = [p["prompt_id"] for p in panel]
    caps = inp["arguments"].get("ai_import", {}).get("managed_checks", {}).get("caps", [])
    summary = {
        "project": project,
        "scope": "site_and_ai" if include else "site_only",
        "site": inp["arguments"]["url"],
        "max_pages": inp["arguments"]["max_pages"],
        "question_count": len(panel) if include else 0,
        "prompt_ids": [p["prompt_id"] for p in panel] if include else [],
        "frequency": plan["frequency"],
        "timezone": zone,
        "stop_date": stop,
        "stop_policy": STOP_POLICY if stop else None,
        "engines": ai["engines"] if include else [],
        "repeats": ai["repeats"] if include else 0,
        "checks_per_occurrence": checks,
        "monthly_allowance": allowance,
        "allowance_timezone": "UTC",
        "cap_per_occurrence_usd": round(sum(caps), 6),
        "platform_usage": PLATFORM_COST,
        **custom_clock,
    }
    body = {"summary": summary, "owner": owner, "actor": actor, "input": inp, "cron": cron}
    bound = await be.get(storage.key(project, "schedule")) or {}
    body["replaces"] = bound.get("plan_id")
    if not bound:
        attempt = await be.get(rejection_key(project, body))
        if attempt:
            body["create_attempt"] = attempt
    pid = si.fingerprint(body)
    return pid, {**body, "options": data}


def action(plan, pid):
    inp = plan["input"]
    guarded = {**inp, **plan.get("queue_grants", {}), "arguments": {**inp["arguments"], "schedule_plan_id": pid}}
    return {
        "type": "RUN_ACTOR",
        "actorId": plan["actor"],
        "runInput": {"body": json.dumps(guarded), "contentType": "application/json; charset=utf-8"},
        "runOptions": {"timeoutSecs": 600, "restartOnError": False, "forcePermissionLevel": "LIMITED_PERMISSIONS"},
    }


async def events(be, project, limit=100):
    prefix = storage.key(storage.clean_slug(project), "schedule-events") + "."
    keys = sorted(await be.keys(prefix), reverse=True)[:limit]
    rows = []
    for index in range(0, len(keys), 8):
        rows.extend(r for r in await asyncio.gather(*(be.get(k) for k in keys[index:index+8])) if r)
    return rows


async def reserved_this_month(be, project, plan, month, recent):
    """Follow immutable claims using GET, including reservations left by interrupted runs."""
    if isinstance(be, storage.MemoryBackend):
        ledger = Ledger(be, None)
    else:
        ident = plan.get("queue_grants", {}).get("schedule_ledger_id")
        if not ident:
            # Older confirmed actions may predate the queue-ID grant. Never create a ledger from this read.
            name = queue_name("schedule_ledger_id")
            resource = await be.client.request_queue(be.selection.username + "~" + name).get()
            if not resource or resource.user_id != be.selection.owner:
                return None
            ident = resource.id
        ledger = Ledger(be, be.client.request_queue(ident))
    # New events carry an offset from the actual queue reservation. Check the anchor against its immutable slot.
    used = 0
    for event in recent:
        end, count = event.get("reserved_after"), event.get("checks")
        if (event.get("allowance_month") == month and type(end) is int and type(count) is int and end >= count > 0
                and await ledger.amount(["month", project, month, end - count]) == count):
            used = end
            break
    for _ in range(64):
        count = await ledger.amount(["month", project, month, used])
        if count is None:
            return used
        used += count
    return None


async def schedule_status(be, project, pid, plan, remote):
    summary = plan["summary"]
    now = dt.datetime.now(dt.timezone.utc)
    month = now.strftime("%Y-%m")
    reset = (now.replace(day=28) + dt.timedelta(days=4)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    recent = await events(be, project, limit=12)
    last = next((e for e in recent if e.get("schedule_id") == remote.id), None)
    try:
        reserved = await reserved_this_month(be, project, plan, month, recent)
    except Exception:
        # A bearer unable to read the allowance still needs the live pause control. Checks always use the ledger.
        reserved = None
    remaining = None if reserved is None else max(0, summary["monthly_allowance"] - reserved)
    enabled = remote.is_enabled
    upcoming = getattr(remote, "next_run_at", None) if enabled else None
    paused = bool(await be.get(storage.key(project, "schedule-paused", remote.id)))
    expired = past_cutoff(summary)
    if expired:
        status = "ended"
    elif not enabled or paused:
        status = "paused"
    elif remaining is None:
        status = "allowance_unverified"
    elif remaining < summary["checks_per_occurrence"]:
        status = "allowance_reached"
    else:
        status = "active"
    planned = None
    if status == "allowance_reached":
        planned = next_occurrence(summary, reset - dt.timedelta(microseconds=1))
    elif status == "active":
        planned = upcoming or next_occurrence(summary, now)
        if (planned and summary.get("stop_date") and
                planned.astimezone(ZoneInfo(summary["timezone"])).date().isoformat() > summary["stop_date"]):
            planned = None
    return {
        **summary, "plan_id": pid, "schedule_id": remote.id, "enabled": enabled, "cadence": cadence(summary),
        "check_status": status, "needs_manual_pause": bool(enabled and (expired or paused)),
        "last_outcome": last.get("status") if last else None, "last_occurrence": last,
        "next_run": upcoming.isoformat() if upcoming else None,
        "planned_next_check": planned.isoformat() if planned else None,
        "monthly_reserved": reserved, "checks_remaining": remaining, "allowance_month": month,
        "allowance_resets_at": reset.isoformat(),
    }


def matches(resource, expected, plan):
    actions = resource.actions
    if (
        len(actions) != 1
        or resource.timezone != plan["summary"]["timezone"]
        or resource.cron_expression != plan["cron"]
        or not resource.is_exclusive
    ):
        return False
    item = actions[0]
    if not isinstance(item, dict):
        item = item.model_dump(by_alias=True, exclude_none=True)
    return (
        item.get("type") == expected["type"]
        and item.get("actorId") == expected["actorId"]
        and json.loads((item.get("runInput") or {}).get("body") or "{}")
        == json.loads(expected["runInput"]["body"])
        and all((item.get("runOptions") or {}).get(k) == v for k, v in expected["runOptions"].items())
    )


async def recover_creation(client, name, expected, plan):
    # A POST can succeed even when its reply or the local binding write is lost.
    # Only reattach the exact authorized action. Never issue a second POST.
    async for item in client.schedules().iterate():
        if item.name == name:
            existing = await client.schedule(item.id).get()
            if existing and matches(existing, expected, plan):
                return existing
            break
    raise ValueError("This creation was already attempted. Review Apify Schedules before retrying.")


async def execute(project, operation, data):
    if operation not in OPERATIONS or not isinstance(data, dict):
        raise ValueError("Choose a schedule operation.")
    project = storage.clean_slug(project)
    client, owner, actor = await _account()
    be = await storage.get_backend()
    binding_key = storage.key(project, "schedule")
    if operation == "schedule_preview":
        return await manage(project, operation, data, client, owner, actor, be, binding_key)
    # Most list calls only read the saved record and live Apify resource. An expired plan
    # may pause the scheduler as agreed in its preview, so serialize that change.
    if operation == "schedule_list":
        if storage._read_only.get():
            return await manage(project, operation, data, client, owner, actor, be, binding_key, allow_expiry=False)
        existing = await be.get(binding_key) or {}
        stored = await be.get(plan_key(project, existing["plan_id"])) if existing else {}
        if not stored or not past_cutoff(stored["summary"]):
            return await manage(
                project, operation, data, client, owner, actor, be, binding_key, allow_expiry=False
            )
    async with schedule_lock(be, project):
        return await manage(project, operation, data, client, owner, actor, be, binding_key)


async def manage(project, operation, data, client, owner, actor, be, binding_key, allow_expiry=True):
    binding = await be.get(binding_key) or {}
    if operation == "schedule_preview":
        if set(data) == {"plan_id"}:
            pid = data["plan_id"]
            plan = await load_plan(be, project, pid)
            if not plan or plan["owner"] != owner or plan["actor"] != actor:
                raise ValueError("This schedule proposal is unavailable in the signed-in project.")
        else:
            pid, plan = await preview(be, project, owner, actor, data)
            key = plan_key(project, pid)
            if not matches_plan_id(await be.get(key), project, pid):
                await be.set(key, plan)
        summary = plan["summary"]
        upcoming = next_occurrence(summary, dt.datetime.now(dt.timezone.utc))
        return {**summary, "plan_id": pid, "cadence": cadence(summary), "revises_existing": bool(plan.get("replaces")),
                "review_url": f"https://citebase-iota.vercel.app/app/#/schedules?project={project}&plan={pid}",
                "planned_next_check": upcoming.isoformat() if upcoming else None}
    if operation == "schedule_list":
        if data:
            raise ValueError("List schedules with just the project name.")
        if not binding:
            return {"schedules": []}
        pid = binding["plan_id"]
    else:
        allowed = {"plan_id", "confirmed"} | ({"schedule_id"} if operation != "schedule_apply" else set())
        if set(data) != allowed or data.get("confirmed") is not True:
            raise ValueError("Confirm the exact previewed plan before changing a schedule.")
        pid = data["plan_id"]
    plan = await load_plan(be, project, pid)
    if not plan or plan["owner"] != owner or plan["actor"] != actor:
        raise ValueError("Preview this schedule in the signed-in project first.")
    new_revision = operation == "schedule_apply" and binding.get("plan_id") != pid
    if operation == "schedule_resume" or new_revision:
        latest, fresh = await preview(be, project, owner, actor, plan["options"])
        # Resume validates the content of the active revision against the freshly derived plan.
        if operation == "schedule_resume":
            fresh["replaces"] = plan["replaces"]
            if plan.get("create_attempt"):
                fresh["create_attempt"] = plan["create_attempt"]
            old_store = plan["input"].get("project_store_id")
            if old_store and old_store == getattr(be, "project_store_id", None):
                fresh["input"]["project_store_id"] = old_store
            latest = si.fingerprint({k: v for k, v in fresh.items() if k != "options"})
        if latest != pid and fresh.get("create_attempt", 0) > plan.get("create_attempt", 0):
            raise ValueError("Apify declined that schedule creation. Preview and confirm it again after correcting the issue.")
        if latest != pid:
            raise ValueError("The project changed. Preview and confirm the new schedule.")
        if past_cutoff(plan["summary"]) or not has_remaining_occurrence(plan["summary"]):
            raise ValueError("No scheduled check remains before the last check date.")
    if (new_revision or operation == "schedule_resume") and plan["input"].get("project_store_id"):
        from work_storage import require_private_project_store
        await require_private_project_store(be)
    if (new_revision or operation == "schedule_resume") and not isinstance(be, storage.MemoryBackend):
        if new_revision and binding and plan.get("replaces") != binding.get("plan_id"):
            raise ValueError("The active schedule changed. Preview again.")
        # Caller creates/opens the same named queues as the scheduler. Apify's resourcePicker
        # grants these exact IDs to the Limited run even when OAuth originally created them.
        if new_revision or plan.get("queue_grants"):
            grants = await private_queue_grants(be, project, owner, plan.get("queue_grants", {}))
            if grants != plan.get("queue_grants"):
                plan = {**plan, "queue_grants": grants}
                await be.set(storage.key(project, "schedule-queues", pid), grants)
    expected = action(plan, pid)
    if binding:
        revise = binding["plan_id"] != pid
        if revise and (operation != "schedule_apply" or plan["replaces"] != binding["plan_id"]):
            raise ValueError("The active schedule changed. Preview again.")
        if operation in ("schedule_pause", "schedule_resume") and binding["schedule_id"] != data["schedule_id"]:
            raise ValueError("Select this project's saved schedule.")
        resource = await client.schedule(binding["schedule_id"]).get()
        prior = await load_plan(be, project, binding["plan_id"]) if revise else plan
        remote_already_revised = resource and revise and matches(resource, expected, plan)
        if not remote_already_revised and (
            not resource or not matches(resource, action(prior, binding["plan_id"]), prior)
        ):
            raise ValueError("The saved schedule was removed or changed in Apify. Review it in Console.")
        if revise:
            intent_key = storage.key(project, "schedule-revision", binding["plan_id"])
            intent = await be.get(intent_key)
            if intent and intent != pid:
                raise ValueError(
                    "An earlier confirmed revision needs reconciliation. Retry that exact plan first."
                )
            if not remote_already_revised:
                await be.set(intent_key, pid)
                try:
                    resource = await client.schedule(resource.id).update(
                        actions=[expected], timezone=plan["summary"]["timezone"], cron_expression=plan["cron"]
                    )
                except Exception as err:
                    if getattr(err, "status_code", None) in (400, 401, 403, 404, 409, 422):
                        await be.delete(intent_key)
                    raise
            if not matches(resource, expected, plan):
                raise ValueError("Apify has not confirmed the revised schedule. Retry this exact plan.")
            await be.set(binding_key, {"plan_id": pid, "schedule_id": resource.id})
            await be.delete(intent_key)
        if (
            operation == "schedule_list"
            and allow_expiry
            and plan["summary"].get("stop_policy")
            and past_cutoff(plan["summary"])
            and resource.is_enabled
        ):
            try:
                resource = await client.schedule(resource.id).update(is_enabled=False)
            except Exception:
                # The signed-in reader can still see that outer starts remain enabled and pause in Console.
                pass
        if operation in ("schedule_pause", "schedule_resume"):
            enabled = operation == "schedule_resume"
            gate = storage.key(project, "schedule-paused", resource.id)
            if not enabled:
                await be.set(gate, True)
            if resource.is_enabled != enabled:
                resource = await client.schedule(resource.id).update(is_enabled=enabled)
            if enabled:
                await be.delete(gate)
    elif operation == "schedule_apply":
        # One deterministic, account-unique Apify name also conflicts with legacy dashboard schedules.
        ledger = await Ledger.open(be)
        name = "citebase-" + project
        intent_key = storage.key(project, "schedule-create-intent")
        pending = await be.get(intent_key)
        if pending and pending != pid:
            earlier = await load_plan(be, project, pending)
            if not earlier or earlier["owner"] != owner or earlier["actor"] != actor:
                raise ValueError("Review the earlier schedule creation in Apify Console before enabling a new plan.")
            declined = await be.get(rejection_key(project, earlier)) or 0
            if declined <= earlier.get("create_attempt", 0):
                prior_resource = await recover_creation(client, name, action(earlier, pending), earlier)
                await be.set(binding_key, {"plan_id": pending, "schedule_id": prior_resource.id})
                await be.delete(intent_key)
                raise ValueError("The previously confirmed schedule was found. Refresh and preview a revision.")
        await be.set(intent_key, pid)
        if (await ledger.claim(["schedule-create", project, pid]))[0]:
            try:
                resource = await client.schedules().create(
                    name=name, title="Citebase: " + project, cron_expression=plan["cron"],
                    timezone=plan["summary"]["timezone"], is_enabled=True, is_exclusive=True, actions=[expected],
                )
            except Exception as err:
                if getattr(err, "status_code", None) in DEFINITE_CREATE_REJECTIONS:
                    await be.set(rejection_key(project, plan), plan.get("create_attempt", 0) + 1)
                    await be.delete(intent_key)
                raise
        else:
            resource = await recover_creation(client, name, expected, plan)
        await be.set(binding_key, {"plan_id": pid, "schedule_id": resource.id})
        await be.delete(intent_key)
    else:
        raise ValueError("This project has no matching saved schedule.")
    row = await schedule_status(be, project, pid, plan, resource)
    return {"schedules": [row]} if operation == "schedule_list" else row


async def pause_at_final_check(be, project, pid, plan, parent, local_time):
    summary = plan["summary"]
    if not summary.get("stop_policy") or not summary["stop_date"]:
        return None
    if not past_cutoff(summary) and next_occurrence(summary, local_time):
        return None
    try:
        async with schedule_lock(be, project):
            binding = await be.get(storage.key(project, "schedule")) or {}
            if binding.get("plan_id") != pid or binding.get("schedule_id") != parent.meta.schedule_id:
                return "schedule_changed"
            # This is the current verified scheduled run's client and its restricted grant. Only
            # disable its own exact action. A denied permission falls back to the signed-in view.
            ref = be.client.schedule(parent.meta.schedule_id)
            remote = await ref.get()
            if not remote or remote.user_id != parent.user_id or not matches(remote, action(plan, pid), plan):
                return "needs_signed_in_pause"
            if remote.is_enabled:
                remote = await ref.update(is_enabled=False)
            return "paused" if not remote.is_enabled else "needs_signed_in_pause"
    except Exception:
        return "needs_signed_in_pause"


async def begin(project, pid, args):
    """Compare the scheduled Actor input and platform-assigned occurrence to the confirmed project binding."""
    be = await storage.get_backend()
    binding = await be.get(storage.key(project, "schedule")) or {}
    plan = await load_plan(be, project, pid)
    if not plan or not binding or args != plan["input"]["arguments"]:
        raise ValueError("The scheduled input differs from the approved plan.")
    if plan.get("queue_grants", {}) != _queue_grants.get():
        raise ValueError("This run is missing the confirmed schedule's exact queue grants. Sign in and review the schedule in Citebase.")
    run_id = si.scheduled_run_id()
    parent = await be.client.run(run_id).get() if run_id else None
    if (
        not parent
        or parent.meta.origin != "SCHEDULER"
        or parent.meta.schedule_id != binding["schedule_id"]
        or not parent.meta.scheduled_at
        or parent.act_id != plan["actor"]
        or parent.user_id != plan["owner"]
    ):
        raise ValueError("This run does not match the approved Apify schedule.")
    when = parent.meta.scheduled_at.astimezone(dt.timezone.utc).replace(second=0, microsecond=0)
    summary = plan["summary"]
    key = storage.key(
        project,
        "schedule-events",
        when.strftime("%Y%m%dT%H%M%SZ") + "-" + si.fingerprint(binding["schedule_id"])[:10],
    )
    event = {
        "scheduled_at": when.isoformat(),
        "schedule_id": binding["schedule_id"],
        "plan_id": pid,
        "run_id": run_id,
        "status": "running",
        "checks": summary["checks_per_occurrence"],
    }
    previous = await be.get(key)
    stats = getattr(parent, "stats", None)
    resumed = any((getattr(stats, field, 0) or 0) > 0 for field in ("migration_count", "reboot_count", "restart_count", "resurrect_count"))
    managed = (args.get("ai_import") or {}).get("managed_checks")
    if (resumed and getattr(parent, "id", None) == run_id and managed and previous
            and previous.get("status") in ("running", "partial", "failed", "completed")
            and all(previous.get(k) == event[k] for k in ("plan_id", "schedule_id", "scheduled_at", "run_id"))
            and await be.get(storage.key(project, "scheduled-runs", "scheduled-" + run_id))):
        return be, key, {**previous, "reconcile_only": True}
    if binding.get("plan_id") != pid:
        raise ValueError("The scheduled input differs from the approved plan.")
    if await be.get(storage.key(project, "schedule-paused", binding["schedule_id"])):
        raise ValueError("This project schedule is paused.")
    local_time = when.astimezone(ZoneInfo(summary["timezone"]))
    try:
        if not scheduled_day(summary, local_time.date()) or local_time.strftime("%H:%M") != summary.get("local_time", "08:00"):
            raise ValueError("This occurrence falls outside the approved schedule.")
        pause = await pause_at_final_check(be, project, pid, plan, parent, local_time)
        if pause:
            event["expiry_pause"] = pause
        if (
            summary["stop_date"]
            and max(local_time.date(), dt.datetime.now(local_time.tzinfo).date()).isoformat()
            > summary["stop_date"]
        ):
            raise ValueError("The approved stop date passed. No checks started.")
        async with schedule_lock(be, project):
            current = await be.get(storage.key(project, "schedule"))
            if current != binding or await be.get(storage.key(project, "schedule-paused", binding["schedule_id"])):
                raise ValueError("The schedule changed or paused before this check started.")
            now = dt.datetime.now(dt.timezone.utc)
            event["allowance_month"] = now.strftime("%Y-%m")
            event["reserved_after"] = await reserve(be, project, binding["schedule_id"], when, event["checks"],
                                                    summary["monthly_allowance"], charged_at=now, timezone=summary["timezone"])
            await be.set(key, event)
    except DuplicateOccurrence:
        raise
    except ValueError:
        # A duplicate cannot overwrite the original attempt's outcome.
        if not await be.get(key):
            await be.set(key, {**event, "status": "blocked", "checks": 0})
        raise
    return be, key, event
