"""Project history: save results and audits, load them back, show trends.

All data goes through storage.get_backend(), i.e. into the running account's own store. Nothing here talks to
any other account. Rows are saved already normalised, so later reports reuse the same maths as fresh input.

Write order matters: everything is validated first, round records are written next and `meta` last. `meta` only
holds names, dates and brand details; the list of rounds is also read back from the `runs.*` keys, so a save that
stops half way never hides data that was written.
"""
from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import storage as stg
import tools

cl = tools.cl  # tools puts the shared scripts folder on the import path

MAX_AUDIT_PROBLEMS = 10
MAX_AUDITS = 90
MAX_TEXT = 300
RECHECK_DAYS = 30
BRAND_KEYS = ("name", "domain", "competitors", "aliases", "site")
_locks: dict[str, asyncio.Lock] = {}


def lock_for(slug: str) -> asyncio.Lock:
    """One writer at a time per project inside this process (a second Standby instance is not covered)."""
    return _locks.setdefault(slug, asyncio.Lock())


def today() -> str:
    return dt.date.today().isoformat()


def _by_id(panel: list[dict]) -> dict[str, dict]:
    return {p["prompt_id"]: p for p in panel}


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    return str(value if value is not None else "")[:limit]


def clean_brand(brand: dict | None) -> dict:
    out: dict[str, Any] = {}
    for key in BRAND_KEYS:
        value = (brand or {}).get(key)
        if key in ("competitors", "aliases"):
            if isinstance(value, list):
                out[key] = [_text(v, 80) for v in value[:20] if v]
        elif value:
            out[key] = _text(value, 200)
    return out


def clean_experiments(experiments: list[dict] | None) -> list[dict]:
    if not experiments:
        return []
    if len(experiments) > tools.MAX_EXPERIMENTS:
        raise ValueError(f"Send at most {tools.MAX_EXPERIMENTS} changes at a time.")
    out = []
    for n, raw in enumerate(experiments, 1):
        if not isinstance(raw, dict) or not str(raw.get("action") or "").strip():
            raise ValueError(f"Change {n} needs an 'action' (what you changed, in plain words).")
        row = {k: _text(raw.get(k), 500) for k in cl.EXP_COLS if raw.get(k) is not None}
        row["date"] = row.get("date") or today()
        if not row.get("recheck_after") and (shipped := cl.parse_date(row["date"])):
            row["recheck_after"] = (shipped + dt.timedelta(days=RECHECK_DAYS)).isoformat()  # same default as the CLI
        out.append(row)
    return out


def clean_audit(audit: Any) -> dict:
    """Keeps only the fields reports use, with safe types and sizes. Raises ValueError for anything else."""
    if not isinstance(audit, dict):
        raise ValueError("audit must be the result object returned by audit_site, passed as is.")
    score = audit.get("health_score")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 100:
            raise ValueError("audit.health_score must be a number from 0 to 100. Pass the audit_site result unchanged.")
        score = int(round(score))

    def numbers(value: Any, limit: int) -> dict[str, int | None]:
        if not isinstance(value, dict):
            return {}
        return {_text(k, 40): (int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
                for k, v in list(value.items())[:limit]}

    problems = []
    for p in (audit.get("problems") or [])[:MAX_AUDIT_PROBLEMS]:
        if isinstance(p, dict):
            problems.append({"check": _text(p.get("check"), 120), "detail": _text(p.get("detail")),
                             "level": _text(p.get("level"), 10), "area": _text(p.get("area"), 30)})
    pages = audit.get("pages_checked")
    return {"site": _text(audit.get("site"), 200), "health_score": score, "subscores": numbers(audit.get("subscores"), 10),
            "counts": numbers(audit.get("counts"), 5),
            "pages_checked": int(pages) if isinstance(pages, (int, float)) and not isinstance(pages, bool) else None,
            "problems": problems}


async def list_projects() -> list[str]:
    be = await stg.get_backend()
    return sorted({k[len(stg.KEY_PREFIX):].split(".", 1)[0] for k in await be.keys(stg.KEY_PREFIX)})


async def _require_project(slug: str) -> dict:
    be = await stg.get_backend()
    meta = await be.get(stg.key(slug, "meta"))
    if not meta:
        known = await list_projects()
        raise ValueError(f"No saved project called '{slug}'. " + (f"Saved projects: {', '.join(known[:10])}. " if known else "")
                         + "Save results first with save_results, or check the name.")
    return meta


async def save_results(project: str, runs: list[dict], panel: list[dict] | None = None,
                       experiments: list[dict] | None = None, brand: dict | None = None,
                       replace: bool = False, append: bool = False) -> dict:
    slug = stg.clean_slug(project)
    async with lock_for(slug):
        return await _save_results(slug, runs, panel, experiments, brand, replace, append)


async def _save_results(slug: str, runs: list[dict], panel: list[dict] | None, experiments: list[dict] | None,
                        brand: dict | None, replace: bool, append: bool) -> dict:
    be = await stg.get_backend()
    meta = await be.get(stg.key(slug, "meta"))
    if meta is None and len(await list_projects()) >= stg.MAX_PROJECTS:
        raise ValueError(f"You already have {stg.MAX_PROJECTS} saved projects. Reuse one of them.")
    stored_panel = await be.get(stg.key(slug, "panel"))
    if panel:
        panel_rows = tools.normalise_panel(panel)
        if stored_panel and cl.panel_hash(_by_id(stored_panel)) != cl.panel_hash(panel_rows):
            raise ValueError("This project's question list is frozen: results are only comparable while the "
                             "questions stay identical. Use a new project name for a different list.")
    elif stored_panel:
        panel_rows = _by_id(stored_panel)
    else:
        raise ValueError("Send the question list (panel) the first time you save results for a project.")
    # clean round names BEFORE checking for repeats, so '2026 12' and '2026-12' cannot sneak in as two rounds
    cleaned = [{**r, "snapshot": stg.clean_part(r.get("snapshot"))} for r in runs]
    rows = tools.normalise_runs(cleaned, panel_rows)
    new_experiments = clean_experiments(experiments)
    new_brand = clean_brand(brand)

    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["snapshot"], []).append(r)
    meta = meta or {"project": slug, "created": today(), "brand": {}, "snapshots": {}}
    known = set(meta["snapshots"]) | {k[len(stg.key(slug, "runs")) + 1:] for k in await be.keys(stg.key(slug, "runs") + ".")}
    if len(known | set(groups)) > stg.MAX_SNAPSHOTS:
        raise ValueError(f"A project can hold {stg.MAX_SNAPSHOTS} rounds. Start a new project.")

    # 1) validate every round and build what will be written; nothing is stored yet
    to_write: dict[str, list[dict]] = {}
    for label, new_rows in groups.items():
        existing = await be.get(stg.key(slug, "runs", label))
        if existing and not (append or replace):
            raise ValueError(f"Round '{label}' already has saved results. Pass append=true to add more repeats, or "
                             "replace=true to overwrite it. Nothing was saved.")
        if existing and append and not replace:
            top: dict[tuple[str, str], int] = {}
            for r in existing:
                k = (r["prompt_id"], r["platform"])
                top[k] = max(top.get(k, 0), int(r["repeat"]))
            new_rows = existing + [{**r, "repeat": int(r["repeat"]) + top.get((r["prompt_id"], r["platform"]), 0)}
                                   for r in new_rows]
        to_write[label] = new_rows

    # 2) write rounds, then the question list, then meta last
    for label, new_rows in to_write.items():
        await be.set(stg.key(slug, "runs", label), new_rows)
        meta["snapshots"].setdefault(label, today())  # first save date; appending never moves a round in time
    if not stored_panel:
        await be.set(stg.key(slug, "panel"), list(panel_rows.values()))
    if new_experiments:
        current = await be.get(stg.key(slug, "experiments")) or []
        for e in new_experiments:
            if not any(x["action"] == e["action"] and x["date"] == e["date"] for x in current):
                if len(current) >= tools.MAX_EXPERIMENTS:
                    raise ValueError(f"A project can log {tools.MAX_EXPERIMENTS} changes. The rounds were saved; "
                                     "start a new project to log more.")
                current.append({**e, "exp_id": f"e{len(current) + 1:03d}"})
        await be.set(stg.key(slug, "experiments"), current)
    if new_brand:
        meta["brand"] = {**meta.get("brand", {}), **new_brand}
    meta["updated"] = today()
    await be.set(stg.key(slug, "meta"), meta)
    return {"project": slug, "snapshots_saved": {k: len(v) for k, v in to_write.items()},
            "panel_prompts": len(panel_rows), "snapshots_in_project": sorted(meta["snapshots"]),
            "brand": meta.get("brand", {}), "stored_in": "your own Apify account (key-value store 'citebase-projects')",
            "warnings": cl.panel_warnings(panel_rows, meta.get("brand"))}


async def save_audit(project: str, audit: dict) -> dict:
    slug = stg.clean_slug(project)
    record = {"date": today(), **clean_audit(audit)}  # validate before anything is stored
    async with lock_for(slug):
        be = await stg.get_backend()
        meta = await be.get(stg.key(slug, "meta"))
        if meta is None and len(await list_projects()) >= stg.MAX_PROJECTS:
            raise ValueError(f"You already have {stg.MAX_PROJECTS} saved projects. Reuse one of them.")
        meta = meta or {"project": slug, "created": today(), "brand": {}, "snapshots": {}}
        keys = await be.keys(stg.key(slug, "audit") + ".")  # dated keys, oldest first
        previous = None
        earlier = [k for k in keys if not k.endswith("." + record["date"])]
        if earlier:
            previous = await be.get(earlier[-1])
        trend = None
        if previous and previous.get("health_score") is not None and record["health_score"] is not None:
            trend = {"previous_date": previous.get("date"), "previous_score": previous["health_score"],
                     "change": record["health_score"] - previous["health_score"]}
        await be.set(stg.key(slug, "audit", record["date"]), record)
        keys = sorted(set(keys) | {stg.key(slug, "audit", record["date"])})
        for old in keys[:-MAX_AUDITS]:  # keep the newest MAX_AUDITS checks
            await be.delete(old)
        meta.setdefault("brand", {}).setdefault("site", record["site"])
        meta["updated"] = today()
        await be.set(stg.key(slug, "meta"), meta)
    return {"project": slug, "saved_on": record["date"], "trend": trend}


async def load_project(project: str) -> dict[str, Any]:
    be = await stg.get_backend()
    slug = stg.clean_slug(project)
    meta = await _require_project(slug)
    runs_prefix = stg.key(slug, "runs")
    in_meta = list(meta.get("snapshots", {}))  # save order
    found = {k[len(runs_prefix) + 1:] for k in await be.keys(runs_prefix + ".")}
    labels = in_meta + sorted(found - set(in_meta))  # rounds meta lost track of come last
    audit_keys = await be.keys(stg.key(slug, "audit") + ".")
    panel, exps, *fetched = await asyncio.gather(
        be.get(stg.key(slug, "panel")), be.get(stg.key(slug, "experiments")),
        *[be.get(stg.key(slug, "runs", label)) for label in labels], *[be.get(k) for k in audit_keys])
    run_rows: list[dict] = []
    for rows in fetched[:len(labels)]:
        run_rows += rows or []
    snapshots = {label: meta.get("snapshots", {}).get(label) or meta.get("created", "") for label in labels}
    return {"slug": slug, "meta": {**meta, "snapshots": snapshots}, "panel": panel or [], "runs": run_rows,
            "experiments": exps or [], "audits": [a for a in fetched[len(labels):] if a]}


def snapshot_trend(data: dict) -> list[dict]:
    panel = _by_id(data["panel"])
    out = []
    # oldest first by first-save date; rounds first saved on the same day keep the order they were saved in
    for label, saved_on in sorted(data["meta"].get("snapshots", {}).items(), key=lambda kv: kv[1]):
        s = cl.snapshot_summary(data["runs"], panel, label, None)
        if s:
            out.append({"snapshot": label, "saved_on": saved_on, "prompts": s["prompts"],
                        "recommendation_share": s["recommendation_share"], "rs_low": s["rs_low"], "rs_high": s["rs_high"],
                        "mentioned_rate": s["mentioned_rate"], "cited_rate": s["cited_rate"],
                        "reputation_share": s["reputation_share"], "reputation_prompts": s["reputation_prompts"],
                        "metric_version": s["metric_version"], "older_metric": s["older_metric"]})
    return out


async def history(project: str) -> dict:
    data = await load_project(project)
    snaps = await asyncio.to_thread(snapshot_trend, data)
    audits = [{"date": a["date"], "health_score": a.get("health_score"), "subscores": a.get("subscores", {})}
              for a in data["audits"]]
    lines = [f"# History: {data['slug']}"]
    if snaps:
        lines += ["", "| Round | Saved | Recommendation Share, buying questions (95% range) | Brand-name questions |",
                  "|---|---|---|---|"]
        lines += [f"| {s['snapshot']}{' (older counting)' if s['older_metric'] else ''} | {s['saved_on']} | "
                  f"{100 * s['recommendation_share']:.1f}% ({100 * s['rs_low']:.1f} to {100 * s['rs_high']:.1f}) | "
                  f"{'n/a' if s['reputation_share'] is None else format(100 * s['reputation_share'], '.1f') + '%'} |"
                  for s in snaps]
        if any(s["older_metric"] for s in snaps):
            lines += ["", "Rounds marked 'older counting' were saved before Citebase stopped counting every plain mention "
                          "as a recommendation. Do not compare them with newer rounds."]
    if audits:
        lines += ["", "| Site check | Health score |", "|---|---|"] + [f"| {a['date']} | {a['health_score']} |" for a in audits]
    if not snaps and not audits:
        lines += ["", "Nothing saved yet."]
    return {"project": data["slug"], "brand": data["meta"].get("brand", {}), "panel_prompts": len(data["panel"]),
            "snapshots": snaps, "audits": audits, "experiments": data["experiments"], "markdown": "\n".join(lines)}


def measure_loaded(data: dict, baseline: str = "", current: str = "") -> dict:
    """Recommendation Share report from an already loaded project (CPU work: call from a thread)."""
    if not data["runs"]:
        raise ValueError("This project has no saved AI-answer results yet. Save some with save_results first.")
    exp_rows = tools.normalise_experiments(data["experiments"])
    order = [s["snapshot"] for s in snapshot_trend(data)]  # save order, not alphabetical
    base = stg.clean_part(baseline) if baseline else (order[0] if order else "")
    cur = stg.clean_part(current) if current else (order[-1] if order else "")
    result = tools.measure_rows(_by_id(data["panel"]), data["runs"], exp_rows, base, cur)
    extra = cl.panel_warnings(data["panel"], data["meta"].get("brand"))
    if extra:
        result["warnings"] = [*result["warnings"], *extra]
        result["markdown"] = cl.render(result)
    return result


async def measure_project(project: str, baseline: str = "", current: str = "") -> dict:
    data = await load_project(project)
    return await asyncio.to_thread(measure_loaded, data, baseline, current)
