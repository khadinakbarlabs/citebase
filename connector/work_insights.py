"""Private project views derived from saved evidence. Reads never start or schedule a check."""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from datetime import date, timedelta
import hashlib
import json
import re
from urllib.parse import quote

import fact_checks
import history
import insights
import storage
import work_actions


def _id(*parts):
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False).encode()).hexdigest()[:24]


def _url(value):
    try:
        return fact_checks.clean_source(value) if isinstance(value, str) else ""
    except ValueError:
        return ""


def _date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _filter_date(value):
    if value is None:
        return None
    result = _date(value)
    if not result or result.isoformat() != value:
        raise ValueError("Use a date in YYYY-MM-DD format.")
    return result


def _sources(data, label):
    return [ds for ds in (data["meta"].get("imports") or {}).get(label, [])
            if isinstance(ds, str) and storage.DATASET_ID.fullmatch(ds)]


def _proof(data, label, rows=None):
    ids = _sources(data, label)
    matched = {r.get("source_dataset_id") for r in rows or []}
    selected = next((ds for ds in ids if ds in matched), None)
    if selected is None and len(ids) == 1:
        selected = ids[0]
    if selected:
        return insights.DATASET_URL + quote(selected, safe="")
    return "#/p/" + data["slug"] + "/answers" if label else None


def _finding_proofs(data, label, sites):
    """Track the last observation and a common dataset for each finding in one pass.

    Empty source IDs mean older rows have no per-answer attribution. None means that
    several sources contributed, so a single URL cannot substantiate the whole count.
    """
    known = set(_sources(data, label))
    buying = {q["prompt_id"] for q in data["panel"] if q.get("type") in insights.BUYING}
    groups = {}
    attributed = False
    for row in data["runs"]:
        if row["snapshot"] != label:
            continue
        source = row.get("source_dataset_id") or ""
        attributed = attributed or bool(source)
        if row["prompt_id"] not in buying:
            continue
        keys = [("answers", row["prompt_id"])]
        if (sites and insights._items(row.get("competitors")) and not insights._truthy(row.get("mentioned"))
                and not insights._truthy(row.get("recommended"))):
            cited = {insights._host(d) for d in insights._items(row.get("cited_domains"))}
            keys.extend(("off_page", site) for site in sites & cited)
        day = _date(row.get("date"))
        observed = day.isoformat() if day else ""
        for key in keys:
            previous, latest = groups.get(key, (source, ""))
            groups[key] = (source if previous == source else None, max(latest, observed))
    proofs = {}
    for key, (source, latest) in groups.items():
        if source == "" and not attributed and len(known) == 1:
            source = next(iter(known))  # older rounds recorded their one dataset on the round
        url = insights.DATASET_URL + quote(source, safe="") if source in known else None
        proofs[key] = (url, latest)
    return proofs


def _rounds(data):
    dates = {}
    for row in data["runs"]:
        day = _date(row.get("date"))
        if day and day > dates.get(row["snapshot"], date.min):
            dates[row["snapshot"]] = day
    rounds = [(label, dates.get(label) or _date(saved)) for label, saved in data["meta"]["snapshots"].items()]
    return sorted(((label, day) for label, day in rounds if day), key=lambda r: r[1])


def _cited(rows):
    domains = {insights._host(s) for r in rows for s in insights._items(r.get("cited_domains"))}
    exact = sorted({url for row in rows for url in fact_checks.safe_evidence_urls(row.get("cited_urls"))})
    links = [{"site": insights._host(url), "url": url, "kind": "observed_url"} for url in exact[:15]]
    linked_domains = {s["site"] for s in links}
    for domain in sorted(domains - linked_domains):
        if re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z0-9-]{2,63}", domain):
            links.append({"site": domain, "url": "https://" + domain, "kind": "reported_domain"})
    return links[:15]


def _cells(rows, label):
    result = defaultdict(list)
    for r in rows:
        if r["snapshot"] == label:
            result[(r["prompt_id"], r["platform"])].append(r)
    return result


def _score(rows):
    return {"answers": len(rows), "recommended": sum(insights._truthy(r.get("recommended")) for r in rows),
            "cited": sum(insights._truthy(r.get("cited")) for r in rows)}


def _context(rows):
    return Counter(tuple(r.get(f) or "" for f in history.cl.PROVENANCE) + (str(r.get("metric_version") or 1),)
                   for r in rows)


def _change(before, after, old, new):
    if not before:
        return "missing_baseline"
    if not after:
        return "missing_current"
    if _context(before) != _context(after):
        return "changed_coverage"
    if not old and new:
        return "gained"
    if old and not new:
        return "lost"
    return "increased" if new > old else "decreased" if new < old else "unchanged"


def _changes(data, query):
    since = _filter_date(query.get("since"))
    rounds = _rounds(data)
    current, end = rounds[-1] if rounds else (None, None)
    if end and since and end < since:
        current, end = None, None
    target = since or (end - timedelta(days=7) if end else None)
    candidates = [(l, d) for l, d in rounds[:-1] if end and d <= target]
    previous, start = candidates[-1] if candidates else (rounds[-2] if end and not since and len(rounds) >= 2 else (None, None))
    gap = (end - start).days if start and end else None
    before, after = _cells(data["runs"], previous), _cells(data["runs"], current)
    hashes = data["meta"].get("panel_hashes") or {}
    same_panel = hashes.get(previous) and hashes.get(current) and hashes[previous] == hashes[current]
    panel_state = "unverified" if not hashes.get(previous) or not hashes.get(current) else "matched" if same_panel else "changed"
    records = []
    brand = data["meta"].get("brand") or {}
    own = insights._host(brand.get("domain") or brand.get("site") or "")
    engines = sorted({engine for _, engine in before.keys() | after.keys()})
    for q in data["panel"]:
        for engine in engines:
            key = (q["prompt_id"], engine)
            a, b = before.get(key, []), after.get(key, [])
            old, new = _score(a), _score(b)
            status = _change(a, b, old["recommended"], new["recommended"]) if a or b else "unsampled"
            if panel_state == "changed":
                status = "changed_panel"
            sources = _cited(b)
            destination = next((s["url"] for s in sources if s["kind"] == "observed_url"
                                and insights._same_site(s["site"], own)), None)
            records.append({"prompt_id": key[0], "question": q["prompt"], "engine": engine, "type": q.get("type"),
                            "before": old, "after": new, "status": status,
                            "cited_sources": sources, "evidence_url": _proof(data, current, b) if b else _proof(data, previous, a),
                            "destination_page": destination})
    statuses = Counter(r["status"] for r in records)
    changes = []
    if start and end:
        for status in ("gained", "lost", "increased", "decreased"):
            if statuses[status]:
                changes.append({"title": f"Recommendations {status}", "detail": f"{statuses[status]} question/engine comparisons.",
                                "source": "AI answers", "observed_on": end.isoformat()})
    audits = data["audits"]
    if len(audits) >= 2 and (not since or (_date(audits[-1]["date"]) or date.min) >= since):
        diff = history.compare_audits(audits[-2], audits[-1])
        for kind in ("new", "fixed"):
            for check in diff.get(kind, []):
                changes.append({"title": check, "detail": "Check passed on re-test." if kind == "fixed" else "New finding in the latest site check.",
                                "source": "Site audit", "observed_on": audits[-1]["date"]})
    return {"previous_round": previous, "current_round": current, "from_date": start.isoformat() if start else None,
            "to_date": end.isoformat() if end else None, "interval_days": gap,
            "comparison": "week_over_week" if gap == 7 else "round_to_round" if gap is not None else "baseline_needed",
            "questions": records, "changes": changes,
            "coverage": {"panel": panel_state, "counts": dict(statuses), "engines": engines,
                         "stale": (date.today() - end).days > 14 if end else None,
                         "unobserved_prompt_ids": [q["prompt_id"] for q in data["panel"]
                                                   if not any((q["prompt_id"], e) in after for e in engines)]}}


def _opportunities(data, demand, filters):
    since = _filter_date(filters.get("since"))
    findings = []

    def add(channel, title, source, when, coverage, action, manual, *, page=None, question=None, url=None,
            identity=None, severity=None, observations=None, snapshot=None):
        findings.append({"id": _id(data["slug"], channel, identity or title, page, question),
                         "title": title, "channel": channel, "source": source, "observed_on": when,
                         "coverage": coverage, "suggested_action": action, "manual_alternative": manual,
                         "page": page, "question": question, "evidence_url": url,
                         "severity": severity, "observations": observations})
        if snapshot:
            findings[-1]["snapshot"] = snapshot

    if data["audits"]:
        audit = data["audits"][-1]
        pages_checked = audit.get("pages_checked")
        extent = (f"{pages_checked} page{'s' if pages_checked != 1 else ''} checked"
                  if isinstance(pages_checked, int) else "Page count unavailable")
        for p in audit.get("problems", []):
            pages = sorted({_url(u) for u in (p.get("example_urls") or [])} - {""})
            for page in pages or [None]:
                add("technical", p.get("check") or "Site finding", "Site audit", audit["date"],
                    f"{extent} · {audit.get('status') or 'unknown coverage'}",
                    p.get("detail") or "Inspect the affected page.", "Inspect the page source and document the result.",
                    page=page, url=page, severity=p.get("level"))
    rounds = _rounds(data)
    if rounds:
        label, _ = rounds[-1]
        gap = insights.citation_gap(data["runs"], data["panel"], data["meta"].get("brand"), label)
        sites = (gap or {}).get("sites", [])
        proofs = _finding_proofs(data, label, {s["site"] for s in sites})
        for site in sites:
            if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z0-9-]{2,63}", site["site"]):
                continue
            url, observed = proofs["off_page", site["site"]]
            add("off_page", "Review coverage on " + site["site"], "Cited domains", observed or None,
                f"{site['answers_for_rivals_without_you']} rival answers cited this domain",
                "Find the actual article and confirm its relevance before creating a prospect.",
                "Read the saved answers and locate the original source.", url=url,
                observations=site["answers_for_rivals_without_you"], snapshot=label)
        for q in insights.question_breakdown(data["runs"], data["panel"], label):
            if q["type"] in insights.BUYING and q["answers"] and not q["recommended"]:
                url, observed = proofs["answers", q["prompt_id"]]
                add("answers", "Review a buyer question", "AI answers", observed or None,
                    f"0 recommendations in {q['answers']} saved answer{'s' if q['answers'] != 1 else ''} "
                    f"on {len(q['engines'])} engine{'s' if len(q['engines']) != 1 else ''}",
                    "Check whether a relevant page answers this question with verifiable facts.",
                    "Read the saved answers alongside the existing page.", question=q["question"], url=url,
                    observations=q["answers"], snapshot=label)
    for gap in (demand or {}).get("gaps", []):
        add("search", "Review a low-click search", "Search Console export", demand["date"],
            f"{int(gap['impressions'])} impressions in the export", "Review the title and page intent for the query.",
            "Inspect the existing Search Console export.", question=gap["query"], observations=int(gap["impressions"]))
    for field in ("channel", "page", "question"):
        if filters.get(field):
            value = str(filters[field]).casefold()
            findings = [f for f in findings if (value == str(f[field] or "").casefold() if field == "channel"
                                                else value in str(f[field] or "").casefold())]
    return [f for f in findings if not since or (_date(f["observed_on"]) or date.min) >= since]


async def _runs(be, data, query):
    from work_schedules import events
    records = []
    panel = {q["prompt_id"] for q in data["panel"]}
    sampled_cells = defaultdict(set)
    for row in data["runs"]:
        sampled_cells[row["snapshot"]].add((row["prompt_id"], row["platform"]))
    for label, when in _rounds(data):
        cells = sampled_cells[label]
        sampled = {p for p, _ in cells}
        engines = {e for _, e in cells}
        records.append({"id": "round-" + label, "snapshot": label, "project": data["slug"],
                        "status": "partial" if not cells or len(cells) < len(panel) * len(engines) else "complete", "observed_on": when.isoformat(),
                        "dataset_ids": _sources(data, label), "evidence_url": _proof(data, label), "kind": "saved_round",
                        "coverage": {"questions": len(sampled), "panel_questions": len(panel)}})
    by_label = {r["snapshot"]: r for r in records}
    for evt in await events(be, data["slug"]):
        rid, label = evt.get("run_id"), evt.get("snapshot")
        if not rid:
            continue
        saved = by_label.get(label, {})
        status = {"completed": "complete", "blocked": "blocked"}.get(evt.get("status"), evt.get("status") or "unknown")
        records.append({"id": rid, "project": data["slug"], "snapshot": label, "observed_on": evt.get("scheduled_at"),
                        "status": status, "kind": "scheduled_run", "dataset_ids": saved.get("dataset_ids", []),
                        "evidence_url": "https://console.apify.com/view/runs/" + quote(rid, safe="")})
    imported = {ds: r for r in by_label.values() for ds in r["dataset_ids"]}
    prefix = storage.key(data["slug"], "scheduled-runs") + "."
    for key in await be.keys(prefix):
        receipt = await be.get(key) or {}
        for rid in receipt.get("runs") or []:
            if not isinstance(rid, str):
                continue
            child = (receipt.get("children") or {}).get(rid) or {}
            ds = child.get("dataset_id")
            status = {"READY": "queued", "RUNNING": "running", "TIMING-OUT": "running", "ABORTING": "running",
                      "FAILED": "failed", "ABORTED": "failed", "TIMED-OUT": "failed"}.get(child.get("status"), "unknown")
            if child.get("status") == "SUCCEEDED":
                status = "complete" if ds in imported else "awaiting_import" if ds else "partial"
            records.append({"id": rid, "project": data["slug"], "kind": "managed_ai_run",
                            "snapshot": imported[ds]["snapshot"] if ds in imported else None,
                            "status": status, "dataset_ids": [ds] if ds else [],
                            "observed_on": child.get("finished_at") or child.get("started_at") or receipt.get("scheduled_at"),
                            "started_at": child.get("started_at"), "finished_at": child.get("finished_at"),
                            "evidence_url": "https://console.apify.com/view/runs/" + quote(rid, safe="")})
    if query.get("run_id"):
        records = [r for r in records if r["id"] == query["run_id"]]
    return sorted(records, key=lambda r: r["observed_on"] or "", reverse=True)


async def _actions(slug):
    return (await work_actions.execute(slug, "actions_list", {}))["actions"]


def _arm(scope):
    return "holdout" if int(_id("page-recheck-v1", scope), 16) % 2 else "offer"


MONEY = ("owner_receipts_cents", "provider_cost_cents", "owner_compute_cents",
         "failed_retry_cost_cents", "delivery_cost_cents", "customer_platform_usage_cents")
EVENTS = ("financial_receipt", "refund", "pause", "support_contact", "repeat_purchase", "unexpected_charge")


def _measurement(data):
    work_actions.valid_keys(data, {"event_id", "event", "date", *MONEY})
    eid, kind, day = data.get("event_id"), data.get("event"), _filter_date(data.get("date"))
    if not isinstance(eid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,64}", eid) or kind not in EVENTS:
        raise ValueError("Use a stable event ID and a supported measurement event.")
    if not day or day > date.today():
        raise ValueError("Supply an observed date up to today.")
    values = {k: data[k] for k in MONEY if k in data}
    if kind == "financial_receipt":
        if set(values) != set(MONEY) or any(type(v) is not int or not 0 <= v <= 100_000_000 for v in values.values()):
            raise ValueError("Supply each receipt and distinct cost component in nonnegative whole USD cents.")
    elif values:
        raise ValueError("Supply monetary figures only on a financial receipt.")
    return {"event": kind, "date": day.isoformat(), **values}


async def _record_measurement(be, private, prefix, event_id, event):
    # Separate containers can receive the same receipt simultaneously. Elect exactly one version;
    # the private contents stay in the account store, the shared election contains only opaque hashes.
    mutation = work_actions.tag(json.dumps(event, sort_keys=True))
    store = await work_actions.RevisionStore.open(be, private, mutation)
    key = prefix + _id(event_id)
    existing = await store.version(key, 1)
    if existing:
        if existing["_mutation"] != mutation:
            raise ValueError("This measurement ID already belongs to another event.")
        return
    await store.set(key, {**event, "revision": 1})


def _verified_date(action):
    check = action.get("recheck") or {}
    if check.get("status") == "verified" and check.get("changed_from_before") is True and _url(action.get("page_url")):
        return _date(check.get("checked_at"))
    return None


async def _offers(be, slug, op, query, meta):
    actions = await _actions(slug)
    scope = work_actions.prefix(be, slug)
    arm = _arm(scope)
    today = _date(history.today())
    cutoff = today - timedelta(days=29)
    verified = []
    fix_dates = []
    for action in actions:
        current = _verified_date(action)
        if current and cutoff <= current <= today:
            verified.append(action)
        # An action is a single fix, even if multiple later checks confirm it or another check fails.
        dates = [d for item in [*action.get("history", []), action] if (d := _verified_date(item)) and d <= today]
        if dates:
            fix_dates.append(min(dates))
    created = _date(meta.get("created"))
    first_fix = min(fix_dates) if fix_dates else None
    winner = max(verified, key=lambda a: (a["recheck"]["checked_at"], a["id"]), default=None)
    offer = None
    if winner and arm == "offer":
        offer = {"id": _id("page-recheck-v1", winner["id"], winner["page_url"],
                           *(winner.get(k) for k in ("after_title", "after_description", "technical_check", "expected_value"))), "title": "Monitor this verified page",
                 "detail": "Preview a recurring recheck for the page you just verified. Review scope and cost before enabling it.",
                 "manual_alternative": "Reopen the saved action and inspect the page yourself.",
                 "action": "schedule_preview", "action_id": winner["id"], "page": winner["page_url"]}
    store = await be.private_store()
    prefix = scope + ".offer-metrics."
    async with history.lock_for(slug):
        if op == "offer_dismiss":
            if not offer or query.get("id") != offer["id"]:
                raise ValueError("Choose the current offer for this project.")
            key = prefix + "dismiss-" + offer["id"]
            if not await store.get(key):
                await store.set(key, {"event": "dismiss", "date": today.isoformat()})
        if op == "offer_measure_record":
            event = _measurement(query)
            await _record_measurement(be, store, prefix + "event-", query["event_id"], event)
        keys = await store.keys(prefix + "dismiss-")
        if offer and prefix + "dismiss-" + offer["id"] in keys:
            offer = None
        read = await work_actions.RevisionStore.open(be, store, "read")
        all_rows = await read.records(prefix + "event-")
        for i in range(0, len(keys), 12):
            all_rows.extend(await asyncio.gather(*(store.get(k) for k in keys[i:i+12])))
        rows = [r for r in all_rows if r and cutoff <= (_date(r.get("date")) or date.min) <= today]
    counts = Counter(r["event"] for r in rows)
    finance = [r for r in rows if r["event"] == "financial_receipt"]
    totals = {k: sum(r[k] for r in finance) for k in MONEY} if finance else None
    measures = {"arm": arm, "window_days": 30, "verified_fixes_30d": sum(d >= cutoff for d in fix_dates),
                "first_verified_on": first_fix.isoformat() if first_fix else None,
                "days_to_first_verified_fix": (first_fix - created).days if created and first_fix and first_fix >= created else None,
                "dismissals_30d": counts["dismiss"], "reported_events_30d": {k: counts[k] for k in EVENTS},
                "owner_reported_usd_cents": totals, "settled_contribution_cents": None,
                "owner_reported_contribution_cents": (totals[MONEY[0]] - sum(totals[k] for k in MONEY[1:5])) if totals else None,
                "accounting_source": "Owner-entered figures; settlement and completeness unverified."}
    return {"offer": offer, "measures": measures}


async def execute(project, operation, data):
    slug = storage.clean_slug(project)
    fields = {"opportunities_list": {"channel", "page", "question", "since"}, "changes_list": {"since"},
              "runs_list": {"run_id"}, "offers_list": set(), "offer_dismiss": {"id"},
              "offer_measure_record": {"event_id", "event", "date", *MONEY}}
    if operation not in fields:
        raise ValueError("Unknown project insights operation.")
    work_actions.valid_keys(data, fields[operation])
    be = await storage.get_backend()
    if operation.startswith("offer"):
        meta = await history.load_meta(slug)
        result = await _offers(be, slug, operation, data, meta)
    else:
        project_data = await history.load_project(slug)
        if operation == "changes_list":
            result = _changes(project_data, data)
        elif operation == "runs_list":
            result = {"runs": await _runs(be, project_data, data)}
        else:
            keys = await be.keys(storage.key(slug, "signal", "search") + ".")
            demand = await be.get(keys[-1]) if keys else None
            result = {"opportunities": _opportunities(project_data, demand, data)}
    return {"project": slug, **result}
