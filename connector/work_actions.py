"""Project briefs, persistent recommendations and verification of raw page metadata."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
import uuid
from urllib.parse import urlsplit

import fact_checks
import history
import storage
import tools

sa = tools.sa
BRIEF_TEXT = ("goal", "market", "language", "business_type", "audience", "offer", "editorial_rules", "buyer_vocabulary")
BRIEF_LISTS = ("key_pages", "confirmed_facts", "inferred_facts")
ACTION_FIELDS = ("title", "finding_id", "evidence", "evidence_url", "page_url", "owner", "due_date",
                 "outcome", "question", "rationale", "constraints", "before_title", "after_title",
                 "before_description", "after_description", "status", "acceptance_condition",
                 "technical_check", "before_value", "expected_value")
STATES = {"open", "in_progress", "approved", "done", "skipped"}
CONTENT = {"title", "evidence", "evidence_url", "page_url", "question", "rationale", "constraints",
           "before_title", "after_title", "before_description", "after_description",
           "acceptance_condition", "technical_check", "before_value", "expected_value"}
REVISION_QUEUE = "citebase-work-revisions-v1"


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def tag(text):
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def prefix(be, slug):
    return storage.key(slug, "work", tag(str(getattr(be, "project_store_id", None) or "local")))


class RevisionStore:
    """Stage private immutable versions, then elect a winner by atomic queue insertion.

    A staged version by itself is invisible. The queue stores only an opaque slot and
    random candidate token. Readers can recover committed data even after a lost reply.
    """
    def __init__(self, store, queue, mutation):
        self.store, self.queue, self.mutation = store, queue, mutation
        self.read_backend = None
        self.queue_read = None

    @classmethod
    async def open(cls, backend, private, mutation):
        queue = None
        if getattr(backend, "read_only", False):
            reader = cls(private, None, mutation)
            reader.read_backend = backend
            return reader
        if hasattr(backend, "revision_queue"):
            queue = await backend.revision_queue(REVISION_QUEUE)
        elif not isinstance(backend, storage.MemoryBackend):
            resource = await storage.open_named_store(backend.client.request_queues().get_or_create,
                                                      REVISION_QUEUE)
            queue = backend.client.request_queue(resource.id)
        return cls(private, queue, mutation)

    async def winner(self, slot):
        if self.read_backend is not None:
            if self.queue_read is None:
                self.queue_read = asyncio.create_task(self.read_backend.revision_queue(REVISION_QUEUE))
            self.queue = await self.queue_read
            if self.queue is None:
                raise ValueError("The saved revision queue could not be read. Check the account's storage permissions.")
        if self.queue is None:
            return self.store.data.get("vote." + slot)
        from apify.storage_clients._apify._utils import unique_key_to_request_id
        record = await self.queue.get_request(unique_key_to_request_id(slot))
        if record is None:
            return None
        token = str(record.url).rsplit("/", 1)[-1]
        if not re.fullmatch("[a-f0-9]{32}", token):
            raise ValueError("The revision receipt is unreadable. Reload this project.")
        return token

    async def commit(self, slot, token):
        if storage._read_only.get():
            raise ValueError("This project operation only reads saved records.")
        if self.queue is None:
            return self.store.data.setdefault("vote." + slot, token)
        result = await self.queue.add_request({"uniqueKey": slot, "url": "https://example.invalid/" + token})
        return await self.winner(slot) if result.was_already_present else token

    async def version(self, key, rev):
        base = f"{key}.v.{rev:012d}"
        token = await self.winner(tag(base))
        if token is None:
            return None
        value = await self.store.get(base + "." + token)
        if value is None:
            raise ValueError("The committed private revision could not be loaded. Reload this project.")
        return value

    async def latest(self, key, revisions):
        for rev in sorted(revisions, reverse=True):
            value = await self.version(key, rev)
            if value is not None:
                return value
        return None

    async def get(self, key):
        keys = await self.store.keys(key + ".v.")
        return await self.latest(key, {int(k.rsplit(".", 2)[-2]) for k in keys})

    async def records(self, prefix):
        return [value for _, value in await self.entries(await self.store.keys(prefix))]

    async def entries(self, candidates):
        """Read only the elected version of each record in the supplied private key listing."""
        by_key = {}
        for candidate in candidates:
            key, separator, tail = candidate.rpartition(".v.")
            if separator:
                by_key.setdefault(key, set()).add(int(tail.split(".", 1)[0]))
        # Batch private reads to keep both memory use and concurrent Apify requests bounded.
        items = list(by_key.items())
        records = []
        for i in range(0, len(items), 12):
            batch = items[i:i + 12]
            values = await asyncio.gather(*(self.latest(k, versions) for k, versions in batch))
            records.extend((key, value) for (key, _), value in zip(batch, values))
        return records

    async def set(self, key, value):
        base = f"{key}.v.{value['revision']:012d}"
        token = uuid.uuid4().hex
        await self.store.set(base + "." + token, {**value, "_mutation": self.mutation})
        elected = await self.commit(tag(base), token)
        if elected != token:
            if elected is None:
                raise ValueError("The revision receipt is unavailable. Reload this project.")
            previous = await self.version(key, value["revision"])
            await self.store.delete(base + "." + token)
            if previous["_mutation"] != self.mutation:
                raise ValueError("Another edit won this revision. Reload the project and review the latest version.")
            return previous
        return {**value, "_mutation": self.mutation}

    async def replay(self, key, data):
        expected = data.get("expected_revision", 0)
        if type(expected) is int and 0 <= expected < 10**12 - 1:
            value = await self.version(key, expected + 1)
            if value and value.get("_mutation") == self.mutation:
                return value
        return None


def visible(record):
    return {key: value for key, value in record.items() if not key.startswith("_")}


def validate_revision(data, current):
    value = data.get("expected_revision", 0 if current == 0 else None)
    if type(value) is not int or value != current:
        raise ValueError("This revision has changed or was omitted. Reload the project and review the latest version.")


def valid_keys(data, allowed):
    if not isinstance(data, dict) or set(data) - set(allowed):
        raise ValueError("Use only the supported fields for this project operation.")


def check_page(value, meta):
    if not value:
        return ""
    parts = urlsplit(value)
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username is not None
            or parts.password is not None or parts.port is not None or parts.fragment
            or any(c.isspace() or ord(c) < 32 or c == "\\" for c in value)):
        raise ValueError("Enter the full public address of the project page.")
    brand = meta.get("brand") or {}
    hosts = set()
    for site in (brand.get("domain"), brand.get("site")):
        if site:
            host = urlsplit(site if "://" in site else "//" + site).hostname
            if host:
                hosts.add(host.lower().removeprefix("www."))
    if parts.hostname.lower().removeprefix("www.") not in hosts:
        raise ValueError("The page must belong to the website saved for this project.")
    return value


def initial_brief(meta):
    settings = meta.get("settings") or {}
    result = dict.fromkeys(BRIEF_TEXT, "")
    result.update({key: [] for key in BRIEF_LISTS})
    return {**result, "market": settings.get("country", ""), "language": settings.get("language", ""),
            "revision": 0}


async def brief_operation(store, key, op, data, meta):
    brief = await store.get(key) or initial_brief(meta)
    if op == "brief_get":
        valid_keys(data, ())
        return {"brief": visible(brief)}
    valid_keys(data, (*BRIEF_TEXT, *BRIEF_LISTS, "expected_revision"))
    receipt = await store.replay(key, data)
    if receipt:
        return {"brief": visible(receipt)}
    validate_revision(data, brief["revision"])
    result = dict(brief)
    for name in BRIEF_TEXT:
        if name in data:
            result[name] = fact_checks.field(data, name, 2000)
    for name in BRIEF_LISTS:
        if name not in data:
            continue
        values = data[name]
        if (not isinstance(values, list) or len(values) > 40
                or any(not isinstance(v, str) or not v.strip() or len(v) > 2000 for v in values)):
            raise ValueError(f"Send up to 40 short text entries for {name}.")
        result[name] = list(dict.fromkeys(v.strip() for v in values))
        if name == "key_pages":
            for url in result[name]:
                check_page(url, meta)
    result["inferred_facts"] = [f for f in result["inferred_facts"] if f not in result["confirmed_facts"]]
    if result != brief:
        result.update(revision=brief["revision"] + 1, updated_at=now())
        result = await store.set(key, result)
    return {"brief": visible(result)}


def initial_action(ident):
    return {**dict.fromkeys(ACTION_FIELDS, ""), "id": ident, "revision": 0, "status": "open",
            "history": [], "recheck": None, "approval_revision": None}


def legacy_actions(meta, key):
    result = {}
    for todo in meta.get("todo") or []:
        step = todo["step"]
        ident = "legacy-" + tag(key + "/" + step.lower())
        result[ident] = {**initial_action(ident), "title": step, "status": todo["status"],
                         "updated_at": todo.get("updated", ""), "legacy_step": step, "_legacy_status": todo["status"]}
    return result


def ticket(action):
    lines = [action["title"]]
    for label, name in (("Page", "page_url"), ("Question", "question"), ("Evidence", "evidence"),
                        ("Source", "evidence_url"), ("Reason", "rationale"), ("Constraints", "constraints"),
                        ("Acceptance", "acceptance_condition"), ("Check", "technical_check"),
                        ("Recorded baseline", "before_value"), ("Expected", "expected_value")):
        if action[name]:
            lines.append(f"{label}: {action[name]}")
    for label, name in (("Title", "title"), ("Description", "description")):
        if action["after_" + name]:
            lines.extend([f"Current {label.lower()}: {action['before_' + name] or '(unspecified)'}",
                          f"Requested {label.lower()}: {action['after_' + name]}"])
    if action["after_title"] or action["after_description"]:
        lines.append("Acceptance: recheck the saved URL and match the requested metadata in the returned HTML.")
    return "\n".join(lines)


def present(action):
    return {**visible(action), "technical_ticket": ticket(action)}


def revised(current, updated):
    snapshot = {k: v for k, v in visible(current).items() if k != "history"}
    versions = list(current["history"])
    if current["revision"] or current.get("legacy_step"):
        versions.append(snapshot)
    # Keep each Apify record bounded. Older approval references remain identifiable by revision.
    return {**updated, "updated_at": now(), "revision": current["revision"] + 1, "history": versions[-40:]}


def page_html(url, response):
    status = response.get("status")
    if not status:
        return None, "The public page could not be reached."
    if status != 200:
        return None, f"The exact page returned HTTP {status}. No page HTML was verified."
    if response.get("truncated") or not response.get("body"):
        return None, "The page returned incomplete HTML."
    page = sa.analyse_page(url, response, [url], urlsplit(url).netloc)
    if page.get("error") or "title" not in page:
        return None, "The raw response could not be read as HTML."
    return page, ""


def inspect_page(url):
    response = sa.fetch(url)
    page, reason = page_html(url, response)
    result = {"page_url": url, "checked_at": now(), "http_status": response.get("status") or None,
              "status": "unavailable", "reason": reason, "title": None, "description": None,
              "h1": [], "canonical": None, "internal_links": [], "links_truncated": False,
              "suggested_title": "", "title_guidance": "draft_needed",
              "coverage": "One exact URL, raw HTML only. JavaScript was not rendered."}
    if page is None:
        return result
    if max(len(page["title"]), len(page["meta_description"]), len(page["canonical"])) > 2000:
        return {**result, "reason": "The page metadata exceeds the editor's 2,000-character field limit."}
    if page["empty_shell"] and not page["title"] and not page["meta_description"] and not page["h1"]:
        return {**result, "reason": "The raw HTML is a JavaScript shell with no readable page metadata."}
    title = page["title"]
    headings = [h[:2000] for h in page["h1"][:10]]
    heading = next((h for h in page["h1"] if h and len(h) <= 2000), "")
    links = [link for link in page["internal_links"] if len(link) <= 2000][:20]
    return {**result, "status": "observed", "title": title, "description": page["meta_description"],
            "h1": headings, "canonical": page["canonical"], "internal_links": links,
            "links_truncated": len(links) < len(page["internal_links"]), "suggested_title": title or heading,
            "title_guidance": "keep_current" if title else "review_heading" if heading else "draft_needed"}


def page_check(action):
    url = action["page_url"]
    response = sa.fetch(url)  # single public-address and peer-checked request; redirects cannot verify this URL
    check = {"status": "unavailable", "checked_at": now(), "page_url": url, "observed_title": "",
             "observed_description": "", "changed_from_before": None, "checked_revision": action["revision"]}
    status = response.get("status", 0)
    kind = action["technical_check"]
    expected = action["expected_value"]
    checks = []
    if not status:
        return {**check, "reason": "The public page could not be reached."}
    if kind == "http_status":
        check["observed_value"] = str(status)
        checks.append(str(status) == expected)
    needs_html = action["after_title"] or action["after_description"] or kind in {"canonical", "internal_link"}
    if needs_html:
        page, reason = page_html(url, response)
        if page is None:
            return {**check, "reason": reason}
        for field, observed in (("title", page["title"]), ("description", page["meta_description"])):
            check["observed_" + field] = observed[:2000]
            if action["after_" + field]:
                checks.append(observed == action["after_" + field])
        if kind == "canonical":
            check["observed_value"] = page["canonical"][:2000]
            checks.append(page["canonical"] == expected)
        if kind == "internal_link":
            present_link = expected in page["internal_links"]
            check["observed_value"] = expected if present_link else ""
            checks.append(present_link)
        if not all(checks) and page.get("empty_shell"):
            return {**check, "reason": "The requested evidence is missing in the raw HTML of a JavaScript app shell."}
    if not all(checks):
        return {**check, "status": "mismatch"}
    # A match verifies the current page. Only a distinct recorded baseline supports a fix.
    fields = [(action["before_" + k], action["after_" + k]) for k in ("title", "description")
              if action["after_" + k]]
    if kind:
        fields.append((action["before_value"], expected))
    changed = any(before and before != after for before, after in fields)
    return {**check, "status": "verified", "changed_from_before": True if changed else
            (False if all(before for before, _ in fields) else None)}


def validate_technical(action, meta):
    kind, expected = action["technical_check"], action["expected_value"]
    if not kind and not expected:
        return
    if kind == "http_status" and re.fullmatch(r"[1-5][0-9]{2}", expected):
        return
    if kind in {"canonical", "internal_link"} and expected:
        if kind == "canonical":
            fact_checks.clean_source(expected)
        else:
            check_page(expected, meta)
        return
    raise ValueError("Choose a canonical URL, internal link URL, or expected HTTP status for the technical check.")


def effective_legacy_action(item, old):
    # The original title remains the legacy identifier, even after the action title is edited.
    # Do not write back the whole legacy meta record: other Standby instances can update it.
    if old and item.get("_legacy_status", old["status"]) != old["status"]:
        return {**item, "status": old["status"], "_legacy_status": old["status"], "approval_revision": None}
    return item


async def reconcile_todo(store, record_key, item, old):
    effective = effective_legacy_action(item, old)
    return item if effective is item else await store.set(record_key, revised(item, effective))


async def action_operation(be, slug, store, key, op, data, meta):
    legacy = legacy_actions(meta, key)
    if op == "actions_list":
        valid_keys(data, ())
        records = {}
        for record in await store.records(key + "."):
            if record:
                ident = record["id"]
                if storage._read_only.get():
                    effective = effective_legacy_action(record, legacy.get(ident))
                    records[ident] = (effective if effective is record else
                                      {**effective, "revision": record["revision"] + 1})
                else:
                    records[ident] = await reconcile_todo(store, key + "." + ident, record, legacy.get(ident))
        for ident, item in legacy.items():
            if ident not in records:
                if not storage._read_only.get():
                    await store.set(key + "." + ident, item)
                records[ident] = item
        actions = [present(item) for item in records.values()]
        return {"actions": actions, "legacy_todo": legacy_view(meta.get("todo") or [], actions)}
    if op == "action_recheck":
        valid_keys(data, ("id", "expected_revision", "request_id"))
    else:
        valid_keys(data, (*ACTION_FIELDS, "id", "expected_revision", "request_id"))
    supplied = fact_checks.field(data, "id", 80)
    if supplied and not re.fullmatch(r"(?:act|legacy)-[0-9a-f]{32}", supplied):
        raise ValueError("Select an existing action ID.")
    finding = fact_checks.field(data, "finding_id", 300)
    source = finding or fact_checks.field(data, "request_id", 200) or store.mutation
    ident = supplied or "act-" + tag(key + "/" + source)
    record_key = key + "." + ident
    receipt = await store.replay(record_key, data)
    if receipt:
        return {"action": present(receipt)}
    saved = await store.get(record_key) or legacy.get(ident)
    if (supplied or op == "action_recheck") and not saved:
        raise ValueError("Select an existing action in this project.")
    if saved and not supplied:
        return {"action": present(saved)}  # a finding may be converted only once
    current = saved or initial_action(ident)
    if current.get("legacy_step"):
        current = await reconcile_todo(store, record_key, current, legacy.get(ident))
    validate_revision(data, current["revision"])
    if op == "action_recheck":
        if not check_page(current["page_url"], meta) or not (current["after_title"] or current["after_description"] or current["technical_check"]):
            raise ValueError("Save the project page and the metadata or technical change you want to verify.")
        result = {**current, "recheck": await asyncio.to_thread(page_check, current)}
    else:
        result = dict(current)
        for field in ACTION_FIELDS:
            if field in data:
                result[field] = fact_checks.field(data, field, 2000)
        if supplied and result["finding_id"] != current["finding_id"]:
            raise ValueError("An action keeps its original finding.")
        if not result["title"] or result["status"] not in STATES:
            raise ValueError("Give the action a title and select a supported status.")
        if result["due_date"]:
            try:
                date = dt.date.fromisoformat(result["due_date"])
                if date.isoformat() != result["due_date"]:
                    raise ValueError
            except ValueError:
                raise ValueError("Use YYYY-MM-DD for the due date.") from None
        check_page(result["page_url"], meta)
        validate_technical(result, meta)
        fact_checks.clean_source(result["evidence_url"])
        content_changed = any(result[k] != current[k] for k in CONTENT)
        if content_changed:
            result.update(recheck=None, approval_revision=None)
            if "status" not in data and result["status"] in {"approved", "done"}:
                result["status"] = "open"
        if result["status"] == "approved" and not result["approval_revision"]:
            result["approval_revision"] = current["revision"] + 1
        if result["status"] in {"open", "in_progress", "skipped"}:
            result["approval_revision"] = None
        if saved and result == current:
            return {"action": present(current)}
    result = revised(current, result)
    result = await store.set(record_key, result)
    return {"action": present(result)}


def legacy_view(todos, actions):
    """Keep the old step as its editable identifier, alongside the current display title and status."""
    migrated = {a["legacy_step"].lower(): a for a in actions if a.get("legacy_step")}
    result = []
    for todo in todos:
        action = migrated.get(todo["step"].lower())
        if action:
            status = action["status"] if action["status"] in history.TODO_STATES else "open"
            result.append({**todo, "status": status, "action_id": action["id"], "action_title": action["title"]})
        else:
            result.append(todo)
    return result


async def execute(project, operation, data):
    slug = storage.clean_slug(project)
    if operation not in {"brief_get", "brief_save", "actions_list", "action_save", "action_recheck", "page_inspect"}:
        raise ValueError("Unknown project work operation.")
    if not isinstance(data, dict):
        raise ValueError("Send project work fields as an object.")
    be = await storage.get_backend()
    if operation == "page_inspect":
        valid_keys(data, ("page_url",))
        meta = await history._require_project(slug)
        url = check_page(fact_checks.field(data, "page_url", 2000, required=True), meta)
        return {"page": await asyncio.to_thread(inspect_page, url)}
    async with history.lock_for(slug):
        meta = await be.get(storage.key(slug, "meta"))
        if meta is None:
            raise ValueError("Choose an existing project.")
        mutation = tag(json.dumps([operation, data], sort_keys=True, ensure_ascii=True))
        store = await RevisionStore.open(be, await be.private_store(), mutation)
        base = prefix(be, slug)
        if operation.startswith("brief_"):
            return await brief_operation(store, base + ".brief", operation, data, meta)
        return await action_operation(be, slug, store, base + ".action", operation, data, meta)
