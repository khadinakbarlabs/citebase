"""Prioritized, read-only view of a signed-in project's saved actions and findings."""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import date
from itertools import chain, islice
import re
from urllib.parse import unquote

import history
import storage
import work_actions
import work_insights

PRIORITIES = ("review", "overdue", "open", "opportunity")
CHANNELS = ("technical", "answers", "off_page", "search")
DEFAULT_LIMIT = 5
MAX_LIMIT = 20
SAVED_VERDICTS = (0, 1, "0", "1", "true", "false", "True", "False", "yes", "no")
INCOMPLETE = "The saved project records are incomplete or inconsistent. Reload the project and check its saved evidence."
EMAIL = re.compile(r"[\w.+%-]+@[\w.-]+\.[\w-]+")
PHONE = re.compile(r"(?<!\w)(?:\+?\d[ .()\-]*){9,15}\d(?!\w)")
INLINE_URL = re.compile(r"https?://\S+", re.IGNORECASE)
ENCODED = re.compile(r"%[a-fA-F0-9]{2}")
SUMMARY_FIELDS = ("id", "title", "status", "finding_id", "page_url", "evidence_url", "due_date", "owner", "evidence",
                  "rationale", "acceptance_condition")
EDIT_FIELDS = ("after_title", "after_description", "technical_check")


def options(data):
    work_actions.valid_keys(data, {"limit", "priority"})
    limit = data.get("limit", DEFAULT_LIMIT)
    if isinstance(limit, str) and re.fullmatch(r"[1-9][0-9]?", limit):
        limit = int(limit)
    if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"Choose a whole-number limit from 1 to {MAX_LIMIT}.")
    if "priority" in data and data["priority"] not in PRIORITIES:
        raise ValueError("Choose review, overdue, open, or opportunity for priority.")
    return limit, data.get("priority")


def decoded(value):
    return unquote(unquote(value))


def has_contact(value):
    return ("@" in value and EMAIL.search(value)) or PHONE.search(value)


def safe_word(word):
    if "%" not in word:
        return word
    plain = decoded(word)
    if has_contact(plain) or ENCODED.search(plain):
        return "[contact removed]"
    return "[link]" if INLINE_URL.search(plain) else word


def excerpt(value, limit=160):
    if not isinstance(value, str):
        return ""
    clean = INLINE_URL.sub("[link]", value)
    if "%" in clean:
        clean = " ".join(safe_word(word) for word in clean.split())
    if "@" in clean:
        clean = EMAIL.sub("[contact removed]", clean)
    text = " ".join(PHONE.sub("[contact removed]", clean).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def source_url(value):
    url = work_insights._url(value)
    if not url:
        return ""
    plain = decoded(url)
    if (has_contact(plain) or ENCODED.search(plain) or any(c in plain for c in "?#\\")
            or any(ord(c) < 32 for c in plain)):
        return ""
    return url


async def latest_dated(be, keys):
    if not keys:
        return None
    key = max(keys)
    record = await be.get(key)
    day = key.rsplit(".", 1)[-1]
    if not isinstance(record, dict) or record.get("date") != day or not work_insights._date(day):
        raise ValueError(INCOMPLETE)
    return record


async def evidence(be, slug, meta):
    """Read the latest audit/export and keep only the newest observed answer round.

    Older projects index rounds by first save, which can differ from the actual answer date
    after a backfill. Inspect each round once, eight at a time, without opening answer wording.
    """
    prefix = storage.key(slug, "runs") + "."
    panel, run_keys, audit_keys, search_keys = await asyncio.gather(
        be.get(storage.key(slug, "panel")), be.keys(prefix), be.keys(storage.key(slug, "audit") + "."),
        be.keys(storage.key(slug, "signal", "search") + "."))
    panel = [] if panel is None else panel
    if not isinstance(panel, list) or any(not isinstance(q, dict) or not q.get("prompt_id")
                                          or not q.get("prompt") for q in panel):
        raise ValueError(INCOMPLETE)
    prompt_ids = {q["prompt_id"] for q in panel}
    indexed = meta.get("snapshots", {})
    found = {k[len(prefix):] for k in run_keys}
    if (not isinstance(indexed, dict) or set(indexed) - found or len(found) > storage.MAX_SNAPSHOTS
            or len(prompt_ids) != len(panel)):
        raise ValueError(INCOMPLETE)
    if meta.get("last_audit") and storage.key(slug, "audit", meta["last_audit"]["date"]) not in audit_keys:
        raise ValueError(INCOMPLETE)
    audit, demand = await asyncio.gather(latest_dated(be, audit_keys), latest_dated(be, search_keys))
    if audit and audit.get("status") == "unreadable":
        raise ValueError(INCOMPLETE)
    labels = [*indexed, *sorted(found - set(indexed))]
    latest, latest_day, latest_rows = None, None, []
    for i in range(0, len(labels), 8):
        batch = labels[i:i + 8]
        values = await asyncio.gather(*(be.get(prefix + label) for label in batch))
        for label, rows in zip(batch, values):
            if (not isinstance(rows, list) or not rows
                    or any(not isinstance(r, dict) or r.get("snapshot") != label or r.get("prompt_id") not in prompt_ids
                           or not r.get("platform") or r.get("recommended") not in SAVED_VERDICTS for r in rows)):
                raise ValueError(INCOMPLETE)
            day = max((day for r in rows if (day := work_insights._date(r.get("date")))), default=None)
            day = day or work_insights._date(indexed.get(label))
            if day is None:
                raise ValueError(INCOMPLETE)
            if latest_day is None or day >= latest_day:
                latest, latest_day, latest_rows = label, day, rows
    dates = {latest: latest_day.isoformat()} if latest else {}
    project = {"slug": slug, "meta": {**meta, "snapshots": dates}, "panel": panel, "runs": latest_rows,
               "audits": [audit] if audit else []}
    return work_insights._opportunities(project, demand, {})


def action_summary(row):
    # The inbox needs edit presence and the latest check outcome, never full edits or revision histories.
    summary = {field: row.get(field) for field in SUMMARY_FIELDS}
    summary.update({field: bool(row.get(field)) for field in EDIT_FIELDS})
    check = row.get("recheck") or {}
    summary["recheck"] = {"status": check.get("status"), "checked_at": check.get("checked_at")}
    return summary


async def actions(be, slug, meta):
    key = work_actions.prefix(be, slug) + ".action"
    legacy = work_actions.legacy_actions(meta, key)
    rows = dict(legacy)
    # Older projects can have to-dos without a private work store or election queue.
    private = await be.existing_private_store()
    candidates = await private.keys(key + ".") if private is not None else []
    if not candidates:
        return rows.values()
    queue = None
    if not isinstance(be, storage.MemoryBackend):
        queue = await be.revision_queue(work_actions.REVISION_QUEUE)
        if queue is None:
            raise ValueError(INCOMPLETE)
    reader = work_actions.RevisionStore(private, queue, "read")
    versions = defaultdict(list)
    for candidate in candidates:
        versions[candidate.rpartition(".v.")[0]].append(candidate)
    groups = iter(versions.values())
    while batch := list(islice(groups, 12)):
        for saved_key, row in await reader.entries(chain.from_iterable(batch)):
            if row is None:  # a staged record has no effect until its revision wins
                continue
            ident = row["id"]
            if not re.fullmatch(r"(?:act|legacy)-[a-f0-9]{32}", ident) or saved_key != key + "." + ident:
                raise ValueError(INCOMPLETE)
            rows[ident] = action_summary(work_actions.effective_legacy_action(row, legacy.get(ident)))
    return rows.values()


def action_item(action, today, finding):
    status = action["status"]
    title = excerpt(action["title"])
    if not title or status not in work_actions.STATES:
        raise ValueError(INCOMPLETE)
    checked = action.get("recheck") or {}
    outcome = checked.get("status")
    if status in {"done", "skipped"} or outcome == "verified":
        return None
    due = action.get("due_date")
    if due:
        work_insights._filter_date(due)
    changes = [name for key, name in (("after_title", "title"), ("after_description", "description"),
                                       ("technical_check", "technical change")) if action.get(key)]
    if changes and action.get("page_url"):
        priority = "review"
        change = changes[0] if len(changes) == 1 else "page edit"
        if outcome == "mismatch":
            reason = "At least one value on the published page differed from the saved expectations at the last check."
            step = "Compare the published page with the saved edit and recheck it after correcting the difference."
        elif outcome:
            reason = f"The last check could not verify the saved {change}."
            step = "Inspect the saved page, then recheck it when its public HTML is available."
        elif status == "approved":
            reason = f"The approved {change} has no saved page verification yet."
            step = "Confirm that the edit was published, then recheck the saved page."
        else:
            reason = f"The action has a proposed {change} and a page where it can be verified."
            step = "Review the proposed edit against the saved page and approve or dismiss it."
    else:
        priority = "overdue" if due and due < today else "open"
        reason = (f"This action was due {due} and is still {status.replace('_', ' ')}." if priority == "overdue"
                  else f"The saved action is {status.replace('_', ' ')}.")
        note = excerpt(action.get("evidence") or action.get("rationale") or finding.get("reason"), 140)
        if note:
            reason += " " + note
        step = (excerpt(action.get("acceptance_condition")) or finding.get("next_step")
                or "Open the action, complete the task and record its outcome.")
    ident = action["id"]
    item = {"id": ident, "record_id": ident, "kind": "action", "section": "todo", "title": title,
            "priority": priority, "reason": reason, "next_step": step}
    url = source_url(action.get("page_url")) or source_url(action.get("evidence_url")) or finding.get("evidence_url")
    if url:
        item["evidence_url"] = url
    if due:
        item["due_date"] = due
    owner = action.get("owner")
    if owner and not has_contact(decoded(owner)) and not INLINE_URL.search(decoded(owner)):
        item["owner"] = excerpt(owner, 80)
    if (day := work_insights._date(checked.get("checked_at"))):
        item["observed_on"] = day.isoformat()
    elif finding.get("observed_on"):
        item["observed_on"] = finding["observed_on"]
    return item


def opportunity_item(finding, slug):
    ident, channel = finding["id"], finding["channel"]
    title = finding["title"]
    if finding.get("question"):
        title += " · " + finding["question"]
    # Answer findings carry only an exact dataset URL constructed from a validated Apify ID.
    url = (finding["evidence_url"] if channel in {"answers", "off_page"} else source_url(finding["evidence_url"]))
    if not url and channel in {"technical", "search"}:
        url = f"#/p/{slug}/" + ("site" if channel == "technical" else "traffic")
    reason = finding["source"] + " · " + finding["coverage"]
    step = finding["suggested_action"]
    if channel == "technical":
        if step != "Inspect the affected page.":
            reason += ". " + step
        step = f"Inspect the affected URL for “{title}” and record the correction in an action."
    item = {"id": ident, "record_id": ident, "kind": "opportunity", "section": "evidence", "title": excerpt(title),
            "priority": "opportunity", "reason": excerpt(reason), "next_step": excerpt(step)}
    if finding.get("observed_on"):
        item["observed_on"] = finding["observed_on"]
    if url:
        item["evidence_url"] = url
    return item


def finding_order(finding):
    severity = {"fail": 0, "warn": 1}.get(finding.get("severity"), 2)
    day = work_insights._date(finding.get("observed_on")) or date.min
    return (CHANNELS.index(finding["channel"]), -day.toordinal(), severity, -(finding.get("observations") or 0),
            finding["title"].casefold(), finding["id"])


async def execute(project, operation, data):
    if operation != "project_focus":
        raise ValueError("Choose the project focus operation.")
    limit, selected = options(data)
    be = await storage.get_backend()
    meta = await be.get(storage.key(project, "meta"))
    if meta is None:
        raise ValueError("Choose an existing project in this account.")
    if not isinstance(meta, dict) or not meta or meta.get("project", project) != project:
        raise ValueError(INCOMPLETE)
    today = history.today()
    try:
        saved, findings = await asyncio.gather(actions(be, project, meta), evidence(be, project, meta))
        by_finding = {}
        for finding in sorted(findings, key=finding_order):
            if finding["id"] not in by_finding:
                by_finding[finding["id"]] = opportunity_item(finding, project)
        linked = {row.get("finding_id") for row in saved if row.get("finding_id")}
        assigned = {row["id"] for row in saved if row.get("owner")}
        items = [item for action in saved if (item := action_item(action, today, by_finding.get(action.get("finding_id"), {})))]
        items.sort(key=lambda item: (PRIORITIES.index(item["priority"]), item.get("due_date", "9999-12-31"),
                                     item["id"] not in assigned, item["title"].casefold(), item["id"]))
        # A saved action consumes its finding, including when the action is complete or dismissed.
        items.extend(finding for ident, finding in by_finding.items() if ident not in linked)
    except (KeyError, TypeError, AttributeError):
        raise ValueError(INCOMPLETE) from None
    counts = dict.fromkeys(PRIORITIES, 0)
    for item in items:
        counts[item["priority"]] += 1
    matched = [item for item in items if not selected or item["priority"] == selected]
    return {"items": matched[:limit], "counts": counts, "total": len(items), "matched_total": len(matched), "as_of": today}
