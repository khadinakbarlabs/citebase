#!/usr/bin/env python3
"""Compare connector/prices.json with the live public pricing of each Actor it quotes.

Read-only: it only sends GET requests to https://api.apify.com/v2/acts/... and never starts a run.

    python3 scripts/check_prices.py            # drift table, exit 1 on drift, exit 2 if an Actor could not be read
    python3 scripts/check_prices.py --all      # also list the prices that match
    python3 scripts/check_prices.py --json     # rows as JSON

The token (optional, public Actors can be read without one) comes from the APIFY_TOKEN environment variable or from
~/.apify/api-token.txt. It is passed to curl on stdin, never on the command line, and is never printed.
curl is used because the Python on some machines has no working certificate store.
Importing this file does nothing: no network, no token, no file reads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES_PATH = os.path.join(ROOT, "connector", "prices.json")
TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".apify", "api-token.txt")
API = "https://api.apify.com/v2/acts/"
START_EVENT = "apify-actor-start"
EPSILON = 1e-9


# ---------------------------------------------------------------- reading live data
def read_token(env: dict | None = None, path: str = TOKEN_FILE) -> str | None:
    env = os.environ if env is None else env
    token = (env.get("APIFY_TOKEN") or "").strip()
    if token:
        return token
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def curl_get(url: str, token: str | None, runner: Callable[..., Any] = subprocess.run) -> dict:
    """GET one api.apify.com URL with curl and return the parsed JSON. The token travels on stdin only."""
    if not url.startswith("https://api.apify.com/"):
        raise ValueError("Only https://api.apify.com/ is ever requested.")
    config = ""
    if token:
        config = 'header = "Authorization: Bearer %s"\n' % token.replace("\\", "").replace('"', "")
    done = runner(["curl", "-sS", "-f", "-m", "30", "-K", "-", url], input=config, capture_output=True, text=True)
    if done.returncode != 0:
        detail = (done.stderr or "").strip().replace(token or "\0", "***")
        raise RuntimeError(f"curl failed ({done.returncode}): {detail[:200]}")
    try:
        return json.loads(done.stdout)
    except ValueError as err:
        raise RuntimeError("Apify answered with something that is not JSON.") from err


def make_fetcher(token: str | None) -> Callable[[str], dict]:
    def fetch(actor: str) -> dict:
        return curl_get(API + actor.replace("/", "~"), token)
    return fetch


def parse_date(stamp: str) -> dt.date:
    return dt.date.fromisoformat(stamp[:10])


def live_pricing(data: dict, today: dt.date) -> tuple[dict | None, dict[dt.date, dict]]:
    """(the pricing entry in force today, {start date: entry} for entries that start later)."""
    data = data.get("data", data)
    entries = sorted(data.get("pricingInfos") or [], key=lambda e: e.get("startedAt", ""))
    current, future = None, {}
    for entry in entries:
        started = parse_date(entry["startedAt"])
        if started <= today:
            current = entry
        else:
            future[started] = entry
    return current, future


def event_prices(entry: dict | None) -> dict[str, float]:
    events = ((entry or {}).get("pricingPerEvent") or {}).get("actorChargeEvents") or {}
    return {name: spec.get("eventPriceUsd") for name, spec in events.items()}


# ---------------------------------------------------------------- comparing
def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) < EPSILON


def _row(job: str, spec: dict, field: str, quote: Any, live: Any, ok: bool) -> dict:
    return {"job": job, "actor": spec["actor"], "field": field, "quote": quote, "live": live,
            "status": "ok" if ok else "DRIFT"}


def _known_events(spec: dict) -> set[str]:
    names = {spec.get("unit_event"), spec.get("request_event"), spec.get("worst_event")}
    for key in ("extra_events", "optional_events", "other_events"):
        names.update(e["event"] for e in spec.get(key, []))
    return {n for n in names if n}


def check_job(job: str, spec: dict, actor_data: dict, today: dt.date, default_start_fee: float,
              known_events: set[str] | None = None) -> list[dict]:
    """One row per thing the quote relies on. `known_events` is every event any job of this Actor accounts for."""
    data = actor_data.get("data", actor_data)
    current, future = live_pricing(data, today)
    rows: list[dict] = []
    if current is None:
        return [_row(job, spec, "pricing model", "PAY_PER_EVENT", None, False)]
    if current.get("pricingModel") != "PAY_PER_EVENT":
        rows.append(_row(job, spec, "pricing model", "PAY_PER_EVENT", current.get("pricingModel"), False))

    # Which entry do the prices come from? A job that is declared "not live until a date" is checked against the
    # entry that starts that day; everything else against what is in force today.
    entry = current
    effective = spec.get("effective_from")
    if effective:
        wanted = dt.date.fromisoformat(effective)
        if wanted > today:
            if wanted in future:
                entry = future[wanted]
            else:
                found = ", ".join(str(d) for d in sorted(future)) or "none"
                rows.append(_row(job, spec, "effective date", effective, found, False))
    else:
        for started in sorted(future):
            rows.append(_row(job, spec, "coming change", "no change planned", f"new prices from {started}", False))
    prices = event_prices(entry)

    unit_price = prices.get(spec["unit_event"])
    rows.append(_row(job, spec, "unit price", spec["per_unit"], unit_price, _same(spec["per_unit"], unit_price)))
    if spec.get("request_event"):
        live = prices.get(spec["request_event"])
        rows.append(_row(job, spec, "request fee", spec["per_request"], live, _same(spec["per_request"], live)))
    elif spec.get("per_request"):
        rows.append(_row(job, spec, "request fee", spec["per_request"], None, False))
    if spec.get("worst_event"):
        live = prices.get(spec["worst_event"])
        rows.append(_row(job, spec, "worst-case price", spec["per_unit_worst"], live, _same(spec["per_unit_worst"], live)))
    for key, label in (("extra_events", "extra event"), ("optional_events", "extra event"), ("other_events", "other event")):
        for event in spec.get(key, []):
            live = prices.get(event["event"])
            rows.append(_row(job, spec, f"{label} {event['event']}", event["price_usd"], live,
                             _same(event["price_usd"], live)))

    # start events: price, presence and how many the Actor's default memory would bill
    live_start = prices.get(START_EVENT)
    if spec["start_events"] > 0:
        fee = spec.get("start_fee_usd", default_start_fee)
        rows.append(_row(job, spec, "start fee", fee, live_start, _same(fee, live_start)))
        if live_start is not None:
            memory = (data.get("defaultRunOptions") or {}).get("memoryMbytes") or 256
            billed = max(1, math.ceil(memory / 1024))
            rows.append(_row(job, spec, "start events", spec["start_events"], billed, spec["start_events"] >= billed))
    else:
        rows.append(_row(job, spec, "start events", 0, 1 if live_start is not None else 0, live_start is None))

    live_usage = bool(entry.get("isPPEPlatformUsagePaidByUser"))
    rows.append(_row(job, spec, "compute billed to you", spec["usage_paid_by_caller"], live_usage,
                     spec["usage_paid_by_caller"] == live_usage))

    known = (known_events if known_events is not None else _known_events(spec)) | {START_EVENT}
    for name in sorted(set(prices) - known):
        rows.append(_row(job, spec, f"unknown event {name}", None, prices[name], False))
    return rows


def compare(prices: dict, actors: dict[str, Any], today: dt.date) -> list[dict]:
    """Rows for every job. `actors` maps an Actor name to its API answer, or to an Exception if it could not be read."""
    default_fee = prices["start_fee_usd"]
    known: dict[str, set[str]] = {}
    for spec in prices["jobs"].values():
        known.setdefault(spec["actor"], set()).update(_known_events(spec))
    rows: list[dict] = []
    for job, spec in prices["jobs"].items():
        data = actors.get(spec["actor"])
        if data is None or isinstance(data, Exception):
            reason = "not read" if data is None else (str(data) or type(data).__name__)
            rows.append({"job": job, "actor": spec["actor"], "field": "live pricing", "quote": None, "live": reason,
                         "status": "ERROR"})
            continue
        rows.extend(check_job(job, spec, data, today, default_fee, known[spec["actor"]]))
    return rows


# ---------------------------------------------------------------- output
def _show(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.6f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def render(rows: list[dict], show_all: bool = False) -> str:
    shown = [r for r in rows if show_all or r["status"] != "ok"]
    bad = [r for r in rows if r["status"] == "DRIFT"]
    errors = [r for r in rows if r["status"] == "ERROR"]
    jobs = len({r["job"] for r in rows})
    out = []
    if shown:
        table = [("status", "job", "field", "prices.json", "live")]
        table += [(r["status"], r["job"], r["field"], _show(r["quote"]), _show(r["live"])) for r in shown]
        widths = [max(len(row[i]) for row in table) for i in range(5)]
        for n, row in enumerate(table):
            out.append(" ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip() + " ")
            if n == 0:
                out.append(" ".join("-" * w for w in widths) + " ")
    if not bad and not errors:
        out.append(f"No drift: {len(rows)} checks on {jobs} jobs match the live pricing.")
    else:
        out.append(f"{len(bad)} drifted and {len(errors)} unreadable, out of {len(rows)} checks on {jobs} jobs.")
    return "\n".join(out)


def load_prices(path: str = PRICES_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main(argv: list[str] | None = None, *, fetch: Callable[[str], dict] | None = None, prices: dict | None = None,
         today: dt.date | None = None, out=None, env: dict | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare connector/prices.json with the live Actor pricing (GET only).")
    parser.add_argument("--all", action="store_true", help="also list the checks that match")
    parser.add_argument("--json", action="store_true", help="print the rows as JSON")
    args = parser.parse_args(argv)
    out = out or sys.stdout
    prices = prices if prices is not None else load_prices()
    today = today or dt.date.today()
    fetch = fetch or make_fetcher(read_token(env))
    names = sorted({spec["actor"] for spec in prices["jobs"].values()})

    def read_one(name: str) -> Any:
        try:
            return fetch(name)
        except Exception as err:  # one unreadable Actor must not hide the rest
            return err

    with ThreadPoolExecutor(max_workers=6) as pool:  # GET requests only, a few at a time
        actors = dict(zip(names, pool.map(read_one, names)))
    rows = compare(prices, actors, today)
    if args.json:
        out.write(json.dumps(rows, indent=1, default=str) + "\n")
    else:
        out.write(render(rows, args.all) + "\n")
    if any(r["status"] == "DRIFT" for r in rows):
        return 1
    return 2 if any(r["status"] == "ERROR" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
