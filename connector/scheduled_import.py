"""Find already-started AI runs from the exact same Apify schedule occurrence."""
from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import re
import os
from collections import Counter

WAIT_SECONDS = 420
POLL_SECONDS = 15
PENDING = {"READY", "RUNNING", "TIMING-OUT", "ABORTING"}
MAX_DATASETS = 20
FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
CHILD_ACTOR_IDS = {
    "khadinakbar/ai-search-brand-monitor": "BZdaMdtW2S4K6w4t9",
    "khadinakbar/google-ai-overviews-scraper": "SMseG5HJek49LaveS",
    "khadinakbar/google-ai-mode-scraper": "W3HEPu9dfgBDhbbDv",
}


def fingerprint(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate(config: dict, allowed: set[str]) -> dict[str, int]:
    expected = config.get("expected_runs") if isinstance(config, dict) else None
    if (not isinstance(expected, dict) or not expected or not expected.keys() <= allowed
            or any(type(n) is not int or n < 1 for n in expected.values())
            or sum(expected.values()) > MAX_DATASETS):
        raise ValueError(f"Automatic import needs 1 to {MAX_DATASETS} planned runs from Citebase's own AI Actors.")
    inputs = config.get("input_fingerprints")
    if (not isinstance(inputs, list) or len(inputs) != sum(expected.values())
            or any(not isinstance(value, str) or not FINGERPRINT.fullmatch(value) for value in inputs)):
        raise ValueError("The schedule is missing its planned AI inputs. Update it from a new schedule plan.")
    return expected


def belongs_to_run(peer, site_run) -> bool:
    return (peer.user_id in (None, site_run.user_id) and peer.meta.origin == "SCHEDULER"
            and peer.meta.schedule_id == site_run.meta.schedule_id
            and peer.meta.scheduled_at == site_run.meta.scheduled_at)


def scheduled_run_id() -> str | None:
    return os.environ.get("ACTOR_RUN_ID") or os.environ.get("APIFY_ACTOR_RUN_ID")


async def find_datasets(client, expected: dict[str, int], fingerprints: list[str]) -> tuple[str, list[str]]:
    run_id = scheduled_run_id()
    if not client or not run_id:
        raise ValueError("Automatic import runs inside an Apify schedule. Import finished runs from Activity instead.")
    try:
        async with asyncio.timeout(WAIT_SECONDS):
            site_run = await client.run(run_id).get()
            if (not site_run or not site_run.user_id or site_run.meta.origin != "SCHEDULER"
                    or not site_run.meta.schedule_id or not site_run.meta.scheduled_at):
                raise ValueError("This run has no Apify schedule occurrence to match. Nothing was imported.")
            scheduled_time = site_run.meta.scheduled_at.astimezone(dt.timezone.utc)
            suffix = hashlib.sha256(site_run.meta.schedule_id.encode()).hexdigest()[:10]
            snapshot = f"scheduled-{scheduled_time:%Y%m%dT%H%M%SZ}-{suffix}"
            actors = await asyncio.gather(*(client.actor(name).get() for name in expected))
            if any(a is None for a in actors):
                raise ValueError("One of the planned AI Actors is unavailable. Nothing was imported.")
            expected_ids = Counter({a.id: n for a, n in zip(actors, expected.values())})
            actor_names = {a.id: name for a, name in zip(actors, expected)}
            while True:
                matches = {}
                for offset in range(0, 2000, 500):
                    page = await client.runs().list(limit=500, offset=offset, desc=True,
                                                    started_after=scheduled_time - dt.timedelta(minutes=1))
                    matches.update({r.id: r for r in page.items if r.act_id in expected_ids
                                    and belongs_to_run(r, site_run)})
                    if len(page.items) < 500:
                        break
                else:
                    raise ValueError("Too many recent Apify runs to confirm this round. Choose the results in Activity.")
                counts = Counter(r.act_id for r in matches.values())
                if any(counts[a] > expected_ids[a] for a in counts):
                    raise ValueError("The schedule started more AI runs than planned. Choose the results in Activity.")
                if counts == expected_ids and not any(r.status in PENDING for r in matches.values()):
                    if any(r.status != "SUCCEEDED" or not r.default_dataset_id for r in matches.values()):
                        raise ValueError("An AI run did not finish successfully. Review the scheduled runs in Activity.")
                    datasets = sorted({r.default_dataset_id for r in matches.values()})
                    if len(datasets) != len(matches):
                        raise ValueError("Scheduled runs did not produce separate datasets. Nothing was imported.")
                    records = await asyncio.gather(*(
                        client.key_value_store(r.default_key_value_store_id).get_record("INPUT")
                        for r in matches.values()
                    ))
                    if any(not record or not isinstance(record.get("value"), dict) for record in records):
                        raise ValueError("Citebase could not read the scheduled AI inputs. Nothing was imported.")
                    actual = [fingerprint([actor_names[r.act_id], record["value"]])
                              for r, record in zip(matches.values(), records)]
                    if Counter(actual) != Counter(fingerprints):
                        raise ValueError("A scheduled AI input differs from the plan. Check the schedule before importing.")
                    return snapshot, datasets
                await asyncio.sleep(POLL_SECONDS)
    except TimeoutError:
        raise ValueError("The full set of scheduled AI runs was not ready in time. Import finished results from Activity.") from None
    except ValueError:
        raise
    except Exception:
        raise ValueError("Apify could not confirm the scheduled AI runs. Check their results in Activity.") from None


def latest_alert(data: dict, snapshots: list[dict], discovery_types: tuple[str, ...]) -> dict | None:
    if len(snapshots) < 2:
        return None
    before, after = snapshots[-2:]
    old, new = before["snapshot"], after["snapshot"]
    imports = data["meta"].get("imports") or {}
    if not new.startswith("scheduled-") or not imports.get(new) or before["metric_version"] != after["metric_version"]:
        return None
    questions = {q["prompt_id"]: q["prompt"] for q in data["panel"] if q["type"] in discovery_types}
    coverage = {old: Counter(), new: Counter()}
    winners = {old: set(), new: set()}
    for row in data["runs"]:
        label, prompt_id = row["snapshot"], row["prompt_id"]
        if label in coverage and prompt_id in questions:
            key = (prompt_id, row["platform"], *(row.get(f) or "" for f in
                                                 ("engine_version", "country", "language", "device", "source")))
            coverage[label][key] += 1
            if row["recommended"]:
                winners[label].add(prompt_id)
    if coverage[old] != coverage[new]:
        return None
    lost = winners[old] - winners[new]
    if not lost:
        return None
    return {"snapshot": new, "previous_snapshot": old, "lost_questions": len(lost),
            "compared_questions": len({cell[0] for cell in coverage[new]}),
            "compared_answers_per_round": sum(coverage[new].values()),
            "examples": [question for pid, question in questions.items() if pid in lost][:5],
            "message": f"You lost recommendations on {len(lost)} {'question' if len(lost) == 1 else 'questions'} "
                       "in the latest scheduled check."}


async def checked_alert(be, data, snapshots, discovery_types):
    import storage
    if len(snapshots) < 2 or not snapshots[-1]["snapshot"].startswith("scheduled-"):
        return None
    for item in snapshots[-2:]:
        label = item["snapshot"]
        if label.startswith("scheduled-"):
            proof = await be.get(storage.key(data["slug"], "schedule-import-coverage", label))
            if proof and proof.get("status") != "imported":
                return None
    return latest_alert(data, snapshots, discovery_types)


def child_observation(run):
    """Public run metadata only, recorded at the time the managed child was observed."""
    def stamp(name):
        value = getattr(run, name, None)
        return value.isoformat() if isinstance(value, dt.datetime) else None
    return {"status": run.status, "started_at": stamp("started_at"), "finished_at": stamp("finished_at"),
            "dataset_id": getattr(run, "default_dataset_id", None) if run.status == "SUCCEEDED" else None}


async def managed_datasets(backend, project: str, checks: list[dict], fingerprints: list[str], *,
                           reconcile_only=False) -> tuple[str, list[str]]:
    """Use Apify's parent-to-child grant and keep a receipt before starting any paid work."""
    from decimal import Decimal

    run_id = scheduled_run_id()
    if not run_id or not re.fullmatch(r"[A-Za-z0-9-]{1,26}", run_id):
        raise ValueError("Automatic AI runs require an Apify schedule.")
    client = backend.client
    parent = await client.run(run_id).get() if client else None
    if (not parent or parent.meta.origin != "SCHEDULER" or not parent.meta.schedule_id
            or not parent.meta.scheduled_at):
        raise ValueError("Automatic AI runs only start from a verified Apify schedule occurrence.")
    scheduled_minute = parent.meta.scheduled_at.astimezone(dt.timezone.utc).replace(second=0, microsecond=0)
    occurrence = [project, parent.meta.schedule_id, scheduled_minute.isoformat()]

    if any(action["actor"] not in CHILD_ACTOR_IDS for action in checks):
        raise ValueError("The scheduled AI check is not from one of Citebase's own Actors.")
    snapshot = f"scheduled-{run_id}"
    receipt_key = f"p.{project}.scheduled-runs.{snapshot}"
    authorization = fingerprint([fingerprints, [a["cap"] for a in checks]])
    receipt = await backend.get(receipt_key) or {"authorization": authorization, "runs": []}
    if receipt.get("authorization") != authorization:
        raise ValueError("The approved schedule inputs changed. Review the already-started runs in Activity.")
    receipt = {**receipt, "scheduled_at": scheduled_minute.isoformat(), "children": dict(receipt.get("children") or {})}
    ids = list(receipt["runs"])
    if len(ids) > len(checks) or any(not isinstance(rid, str) or not rid for rid in ids if rid is not None):
        raise ValueError("The saved AI run receipt could not be verified.")
    if reconcile_only and ids and ids[-1] is None:
        ids.pop()  # This start has an unknown outcome. Reconcile only the earlier confirmed IDs.
    if not ids and reconcile_only:
        raise ValueError("There are no confirmed child run IDs to reconcile. Review Activity before starting more checks.")
    if any(run_id is None for run_id in ids) or len(ids) != len(set(ids)):
        raise ValueError("A previous run start could not be confirmed. Review Activity before starting it again.")

    try:
        async with asyncio.timeout(WAIT_SECONDS):
            if not reconcile_only and len(ids) < len(checks):
                from work_schedules import Ledger
                ledger = await Ledger.open(backend)
                starter = backend.child_client
                for action in checks[len(ids):]:
                    # The same occurrence can have a replacement parent run with a different run ID.
                    # Reserve even when the previous start returned no receipt or timed out.
                    claimed, _ = await ledger.claim(["child", *occurrence, len(ids)])
                    if not claimed:
                        raise ValueError("This child run was already reserved. Review Activity.")

                    await backend.set(receipt_key, {**receipt, "runs": [*ids, None]})
                    run = await starter.actor(CHILD_ACTOR_IDS[action["actor"]]).start(
                        run_input=action["input"], max_total_charge_usd=Decimal(str(action["cap"])),
                        max_items=action["checks_per_run"], run_timeout=dt.timedelta(seconds=240),
                        restart_on_error=False, force_permission_level="LIMITED_PERMISSIONS",
                    )
                    ids.append(run.id)
                    receipt["children"][run.id] = child_observation(run)
                    await backend.set(receipt_key, {**receipt, "runs": list(ids)})
            runs = await asyncio.gather(*(client.run(rid).wait_for_finish(
                wait_duration=dt.timedelta(seconds=WAIT_SECONDS)) for rid in ids))
    except Exception:
        raise ValueError("Citebase could not confirm the scheduled AI runs. Review Activity before retrying.") from None
    if any(r is None or r.id != rid or r.act_id != CHILD_ACTOR_IDS[a["actor"]]
           or getattr(r.meta, "actor_run_id", None) != run_id for r, rid, a in zip(runs, ids, checks)):
        raise ValueError("A scheduled run could not be linked to this Citebase run. Nothing was imported.")
    latest = await backend.get(receipt_key)
    if not latest or latest.get("authorization") != authorization or latest.get("runs", [])[:len(ids)] != ids:
        raise ValueError("The saved child receipt changed. Review Activity before importing.")
    latest["children"] = {**(latest.get("children") or {}), **{r.id: child_observation(r) for r in runs}}
    await backend.set(receipt_key, latest)
    successful = [r for r in runs if r.status == "SUCCEEDED" and r.default_dataset_id]
    if not successful:
        raise ValueError("An AI run did not finish successfully. Review the scheduled runs in Activity.")
    datasets = sorted({r.default_dataset_id for r in successful})
    if len(datasets) != len(successful):
        raise ValueError("Scheduled runs did not produce separate datasets. Nothing was imported.")
    return snapshot, datasets
