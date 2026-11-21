"""Private outreach records and a client-safe weekly digest for an existing project."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
import uuid

import fact_checks
import history
import storage
import tools
import work_actions

GUIDANCE = {
    "customer": "Ask about the customer's own experience. Keep feedback voluntary and open to criticism.",
    "editor": "Reference a specific article and explain how the offered evidence helps its readers.",
    "partner": "Describe the shared audience and the concrete collaboration you propose.",
    "creator": "Reference a specific piece of their work and disclose any sponsorship.",
    "directory": "Check the listing criteria and provide verifiable business information.",
}
SUPPRESS = {"opted_out", "hard_bounce", "complaint"}
OUTCOMES = ("new", "contacted", "declined", "replied", "opted_out", "hard_bounce", "complaint", "placement_verified")
DEFAULT_DIGEST = {"revision": 0, "enabled": False, "recipients": [], "muteUnchanged": True}
HANDOFF = ("Read your weekly issue here. To share it, review the exact client copy and recipients, "
           "then prepare separate messages for your own mail app. Email delivery requires your approval there.")

MAX_PROSPECTS = 300


def email(value):
    if not isinstance(value, str) or len(value) > 254 or not tools.st.EMAIL_RE.fullmatch(value.strip()):
        raise ValueError("Enter one plain email address for each recipient.")
    return value.strip().lower()


def text(data, name, limit=1200):
    return fact_checks.field(data, name, limit, required=True)


def date(value):
    try:
        if not isinstance(value, str) or dt.date.fromisoformat(value).isoformat() != value:
            raise ValueError
    except ValueError:
        raise ValueError("Enter the contact date as YYYY-MM-DD.") from None
    if value > today_utc().isoformat():
        raise ValueError("Last contact cannot be in the future.")
    return value


def prospect_id(address):
    return hashlib.sha256(address.encode()).hexdigest()


def prospect_key(slug, pid):
    if not isinstance(pid, str) or len(pid) != 64 or any(c not in "0123456789abcdef" for c in pid):
        raise ValueError("Select a saved prospect.")
    return slug + ".prospect." + pid


class Records:
    """Mutable project records use compare-and-set. Suppression is a separate, permanent account flag."""

    def __init__(self, private, revisions):
        self.private = private
        self.revisions = revisions

    @classmethod
    async def open(cls, backend, operation, data):
        private = await backend.private_store()
        mutation = work_actions.tag(json.dumps([operation, data], sort_keys=True))
        return cls(private, await work_actions.RevisionStore.open(backend, private, mutation))

    async def read(self, key):
        current = await self.revisions.get(key)
        if current:
            return current
        legacy = await self.private.get(key)
        return {**legacy, "revision": 0} if legacy else None

    async def write(self, key, data, current, updated):
        revision = (current or {}).get("revision", 0)
        expected = data.get("expected_revision", 0)
        if (current and type(expected) is int and revision == expected + 1
                and current.get("_mutation") == self.revisions.mutation):
            return current  # lost acknowledgement of the same exact edit
        work_actions.validate_revision(data, revision)
        return await self.revisions.set(key, {**updated, "revision": revision + 1})

    async def prospect_keys(self, prefix):
        # Include old plain records as well as elected revisions. Draft and approval keys are excluded.
        candidates = await self.private.keys(prefix)
        return sorted({key.split(".v.", 1)[0] for key in candidates if
                       "." not in key[len(prefix):].split(".v.", 1)[0]})


async def require_prospect(store, slug, pid):
    row = await store.read(prospect_key(slug, pid))
    if not row:
        raise ValueError("Select a saved prospect in this project.")
    return row


async def view(store, slug, row):
    key = prospect_key(slug, row["id"])
    blocked, draft, citation = await asyncio.gather(store.private.get("suppressed." + row["id"]),
                                                  store.read(key + ".draft"), store.private.get(key + ".citation"))
    if draft:
        approval = draft.get("approval") if "approval" in draft else await store.private.get(key + ".approval")
        usable = bool(approval and approval["version"] == draft["version"]
                      and approval["expiresAt"] > dt.datetime.now(dt.timezone.utc).isoformat()
                      and row.get("closedDraftVersion") != draft["version"]
                      and not blocked and row["outcome"] != "declined")
        draft = {**work_actions.visible(draft), "approved": usable}
        draft.pop("approval", None)
    return {**work_actions.visible(row), "suppressed": bool(blocked), "citationVerified": bool(citation and citation.get("email") == row["email"]), "draft": draft}


async def rows_for(store, slug):
    prefix = slug + ".prospect."
    keys = await store.prospect_keys(prefix)
    results = []
    for start in range(0, len(keys), 12):
        rows = await asyncio.gather(*(store.read(key) for key in keys[start:start + 12]))
        results.extend(await asyncio.gather(*(view(store, slug, row) for row in rows if row)))
    return results


async def save_prospect(store, slug, data):
    pid = data.get("id")
    if pid is None:
        pid = prospect_id(email(data.get("email")))
        old = await store.read(prospect_key(slug, pid))
    else:
        old = await require_prospect(store, slug, pid)
    fields = {**(old or {}), **data}
    address = email(fields.get("email"))
    if prospect_id(address) != pid:
        raise ValueError("Save a different address as a new prospect.")
    kind, outcome = fields.get("recipientType"), fields.get("outcome", "new")
    if not isinstance(kind, str) or kind not in GUIDANCE or outcome not in OUTCOMES:
        raise ValueError("Select a supported recipient type and outcome.")
    proof = fact_checks.clean_source(fact_checks.field(fields, "proofUrl", 1500))
    if outcome == "placement_verified" and not proof:
        raise ValueError("Open the published placement and save its URL to record your verification.")
    today = today_utc().isoformat()
    last = fields.get("lastContact", "")
    row = {"id": pid, "email": address, "recipientType": kind, "outcome": outcome,
           "sourceUrl": fact_checks.clean_source(text(fields, "sourceUrl", 1500)), "proofUrl": proof,
           "lastContact": date(last) if last else "", "outcomeDate": today, "updated": today,
           **{name: text(fields, name) for name in ("readerFit", "asset", "contactProvenance")}}
    events = list((old or {}).get("outcomeHistory", []))
    if not old or old["outcome"] != outcome or old.get("proofUrl") != proof:
        events.append({"outcome": outcome, "date": today, "proofUrl": proof})
    row["outcomeHistory"] = events[-100:]
    row["closedDraftVersion"] = (old or {}).get("closedDraftVersion")
    if (old or {}).get("outcome") != outcome and outcome in ("contacted", "declined"):
        draft = await store.read(prospect_key(slug, pid) + ".draft")
        if draft:
            row["closedDraftVersion"] = draft["version"]
    if old and old["outcome"] == outcome:
        row["outcomeDate"] = old["outcomeDate"]
    if not old:
        prefix = slug + ".prospect."
        if len(await store.prospect_keys(prefix)) >= MAX_PROSPECTS:
            raise ValueError("This project already has the maximum number of saved prospects.")
    if outcome in SUPPRESS:
        # Write first so a partial failure can never leave someone contactable after an opt-out.
        await store.private.set("suppressed." + pid, {"reason": outcome, "date": today})
    if outcome == "contacted" and not row["lastContact"]:
        row["lastContact"] = today
    comparable = {k: v for k, v in (old or {}).items() if k not in {"revision", "_mutation"}}
    if old and {**row, "updated": old["updated"]} == comparable:
        return {"prospect": await view(store, slug, old)}
    try:
        row = await store.write(prospect_key(slug, pid), data, old, row)
    except ValueError:
        if outcome in SUPPRESS:
            raise ValueError("This recipient is on the account do-not-contact list. Reload the prospect "
                             "and review its latest revision before recording the outcome.") from None
        raise
    return {"prospect": await view(store, slug, row)}


async def edit_draft(store, slug, operation, data):
    pid = data.get("prospectId")
    row = await view(store, slug, await require_prospect(store, slug, pid))
    if row["suppressed"] or row["outcome"] == "declined":
        raise ValueError("Contact has stopped for this recipient.")
    key = prospect_key(slug, pid)
    draft_key = key + ".draft"
    saved = await store.read(draft_key)
    if operation == "draft_save":
        subject, body = text(data, "subject", 250), text(data, "body", 8000)
        if "\n" in subject or "\r" in subject:
            raise ValueError("The subject must fit on one line.")
        if row["draft"] and (subject, body) == (row["draft"]["subject"], row["draft"]["body"]):
            return {"draft": row["draft"]}
        updated = {"to": row["email"], "subject": subject, "body": body, "version": uuid.uuid4().hex,
                   "updated": today_utc().isoformat(), "approval": None}
        stored = await store.write(draft_key, data, saved, updated)
        return {"draft": {k: v for k, v in {**work_actions.visible(stored), "approved": False}.items()
                          if k != "approval"}}
    draft = row["draft"]
    if not draft or not saved or saved["version"] != draft["version"] or draft["version"] != data.get("version"):
        raise ValueError("Review the latest saved draft before approving.")
    if row.get("closedDraftVersion") == draft["version"]:
        raise ValueError("This draft is closed. Write and review a new draft to follow up.")
    checked = tools.check_outreach_draft(draft["to"], draft["subject"], draft["body"])
    if not checked["ready"]:
        raise ValueError(" ".join(checked["problems"]))
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=48)
    updated = {**saved, "approval": {"version": draft["version"], "expiresAt": expires.isoformat()}}
    await store.write(draft_key, data, saved, updated)
    current = await view(store, slug, await require_prospect(store, slug, pid))
    if not current["draft"] or current["draft"]["version"] != draft["version"] or not current["draft"]["approved"]:
        raise ValueError("The draft or recipient changed. Review the prospect again.")
    return {"draft": current["draft"]}


def digest_settings(data):
    enabled = data.get("enabled")
    mute = data.get("muteUnchanged")
    addresses = data.get("recipients")
    if not isinstance(enabled, bool) or not isinstance(mute, bool):
        raise ValueError("Choose whether to enable the digest and mute unchanged weeks.")
    if not isinstance(addresses, list) or len(addresses) > 20:
        raise ValueError("Select up to twenty client recipients for optional email copies.")
    return {"enabled": enabled, "recipients": list(dict.fromkeys(email(a) for a in addresses)), "muteUnchanged": mute}


def today_utc():
    return dt.datetime.now(dt.timezone.utc).date()


def summarize(period_end, review_date, meta, audit_keys, actions, rows):
    start = (period_end - dt.timedelta(days=6)).isoformat()
    end = period_end.isoformat()

    def in_period(value):
        return isinstance(value, str) and start <= value[:10] <= end

    snapshots = list((meta.get("snapshots") or {}).values())
    checks = sum(in_period(d) for d in snapshots)
    audit = sum(in_period(key.rsplit(".", 1)[-1]) for key in audit_keys)

    def recorded_this_week(row, outcome):
        return any(e["outcome"] == outcome and in_period(e["date"]) for e in row.get("outcomeHistory", []))

    placements = sum(recorded_this_week(r, "placement_verified") for r in rows)
    replies = sum(recorded_this_week(r, "replied") for r in rows)
    pending = sum(bool(r["draft"] and not r["draft"]["approved"] and not r["suppressed"]
                       and r.get("closedDraftVersion") != r["draft"]["version"]
                       and r["outcome"] != "declined") for r in rows)
    open_actions = [a for a in actions if a.get("status") in {"open", "in_progress"}]
    action_updates = sum(in_period(a.get("updated_at")) for a in actions)
    next_due = min((a["due_date"] for a in open_actions if isinstance(a.get("due_date"), str)
                    and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", a["due_date"])), default=None)
    next_check = (f"Next open action due: {next_due}." if next_due else
                  f"Next suggested weekly review: {(review_date + dt.timedelta(days=7)).isoformat()}.")
    preview = {
        "whatChanged": (f"{start} to {end} · AI rounds: {checks}. Site checks: {audit}. Actions updated: {action_updates}. "
                        f"Prospects who replied: {replies}. Placements you verified: {placements}."),
        "needsDecision": f"{pending} outreach drafts await review. {len(open_actions)} project actions are open.",
        "nextCheck": next_check,
    }
    changed = checks or audit or action_updates or placements or replies or any(
        in_period(r["updated"]) or in_period((r["draft"] or {}).get("updated"))
        or any(in_period(e["date"]) for e in r["outcomeHistory"]) for r in rows)
    return preview, bool(changed)


async def digest_state(backend, store, base, settings, meta, audit_keys, actions):
    today = today_utc()
    rows = await rows_for(store, base)
    live, changed = summarize(today, today, meta, audit_keys, actions, rows)
    prefix = base + ".issue."
    week = today - dt.timedelta(days=today.weekday())
    key = prefix + week.isoformat()
    current = None
    if settings["enabled"]:
        current = await store.private.get(key)
        if current is None and not storage._read_only.get():
            period_end = week - dt.timedelta(days=1)
            preview, had_changes = summarize(period_end, today, meta, audit_keys, actions, rows)
            current = {"week": week.isoformat(), "periodStart": (week - dt.timedelta(days=7)).isoformat(),
                       "periodEnd": period_end.isoformat(), "createdOn": today.isoformat(), "preview": preview,
                       "status": "muted" if settings["muteUnchanged"] and not had_changes else "delivered"}
            current["version"] = hashlib.sha256(json.dumps([base, current], sort_keys=True).encode()).hexdigest()
            # Elect a single private copy even if two Standby instances open this inbox together.
            # After a lost response the same slot recovers its winner before materializing the archive entry.
            election = await work_actions.RevisionStore.open(backend, store.private, "weekly-digest-v1")
            elected = await election.set(base + ".issue-winner." + week.isoformat(), {**current, "revision": 1})
            current = {k: v for k, v in elected.items() if k not in {"_mutation", "revision"}}
            await store.private.set(key, current)
    keys = sorted(await store.private.keys(prefix), reverse=True)
    archive = []
    for start in range(0, len(keys), 12):
        records = await asyncio.gather(*(store.private.get(k) for k in keys[start:start + 12]))
        archive.extend(r for r in records if r and r["status"] == "delivered")
        if len(archive) >= 52:
            break
    return {**work_actions.visible(settings), "delivery": "in_app", "handoffDelivery": "manual", "preview": live, "handoff": HANDOFF,
            "muted": bool(settings["muteUnchanged"] and not changed), "currentIssue": current, "archive": archive[:52]}


async def prepare_handoff(store, base, data):
    settings = await store.read(base + ".weekly-digest") or DEFAULT_DIGEST
    if not settings["enabled"] or data.get("confirmed") is not True:
        raise ValueError("Enable the weekly summary and confirm the exact client copy and recipients first.")
    week = data.get("week")
    if not isinstance(week, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", week):
        raise ValueError("Choose a delivered weekly issue.")
    issue = await store.private.get(base + ".issue." + week)
    if not issue or issue["status"] != "delivered" or issue["version"] != data.get("version"):
        raise ValueError("Review the current copy of a delivered issue before preparing messages.")
    selected = digest_settings({"enabled": True, "muteUnchanged": False, "recipients": data.get("recipients")})
    addresses = selected["recipients"]
    if not addresses or any(address not in settings["recipients"] for address in addresses):
        raise ValueError("Select recipients from the saved weekly summary settings.")
    blocked = await asyncio.gather(*(store.private.get("suppressed." + prospect_id(address)) for address in addresses))
    if any(blocked):
        raise ValueError("A selected recipient is on the account's do-not-contact list.")
    preview = issue["preview"]
    body = "\n\n".join(preview[k] for k in ("whatChanged", "needsDecision", "nextCheck"))
    subject = f"Weekly project summary · {issue['periodStart']} to {issue['periodEnd']}"
    return {"status": "prepared", "sent": False, "week": week, "version": issue["version"],
            "messages": [{"to": address, "subject": subject, "body": body} for address in addresses]}


async def execute(project, operation, data):
    slug = storage.clean_slug(project)
    backend = await storage.get_backend()
    meta = await backend.get(storage.key(slug, "meta"))
    if meta is None:
        raise ValueError("Choose an existing project.")
    base = work_actions.prefix(backend, slug)
    if not isinstance(data, dict):
        raise ValueError("Provide the operation fields as an object.")
    store = await Records.open(backend, operation, data)
    if operation in {"digest_get", "digest_save"}:
        actions = (await work_actions.execute(slug, "actions_list", {}))["actions"]
        audit_keys = await backend.keys(storage.key(slug, "audit") + ".")
        key = base + ".weekly-digest"
        async with history.lock_for(slug):
            settings = await store.read(key) or DEFAULT_DIGEST
            if operation == "digest_save":
                updated = digest_settings(data)
                settings = await store.write(key, data, settings, updated)
            return await digest_state(backend, store, base, settings, meta, audit_keys, actions)
    async with history.lock_for(slug):
        if operation == "digest_handoff":
            return await prepare_handoff(store, base, data)
        if operation == "prospects_list":
            return {"prospects": await rows_for(store, base), "recipientTypes": list(GUIDANCE),
                    "outcomes": list(OUTCOMES), "guidance": GUIDANCE}
        if operation == "prospect_save":
            return await save_prospect(store, base, data)
        if operation in {"draft_save", "draft_approve"}:
            return await edit_draft(store, base, operation, data)
    raise ValueError("Select a supported outreach operation.")
