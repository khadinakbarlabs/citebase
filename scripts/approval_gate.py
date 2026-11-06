#!/usr/bin/env python3
"""Approval gate for outward-facing or paid actions (PreToolUse / PostToolUse hook).

pre  : forces a human confirmation ("ask") before any email send, campaign start,
       marketplace cart/purchase, paid script action (`--confirm`), or uncapped /
       over-limit Apify run, and denies sends
       once the daily cap is reached.
post : counts successful sends toward the daily cap.

Reads the hook payload (JSON) on stdin. Standard library only. Never blocks
unrelated tools: anything that doesn't match exits 0 with no output.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys

SEND_TOOL = re.compile(r"__(send_message|send_email|send_reply|reply|forward|start_campaign)$")
PAID_TOOL = re.compile(r"__(add_guest_post_to_cart|add_link_insertion_to_cart|checkout\w*|purchase_\w+|buy_\w+)$")
PAID_BASH = re.compile(r"\b(submit|order|purchase|retract)\b.*--confirm\b")
APIFY_RUN = re.compile(r"__(call-actor|khadinakbar--[\w-]+)$")
CAP_KEYS = ("maxTotalChargeUsd", "max_total_charge_usd", "max_charge_usd")
DEFAULT_MAX_RUN_USD = 2.0
DEFAULT_CAP = 20
COUNT_FILE = "send-count.json"
KEEP_DAYS = 30


def data_dir() -> str:
    d = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser("~/.claude/plugins/data/vibecited")
    os.makedirs(d, exist_ok=True)
    return d


def cap() -> int:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_DAILY_SEND_CAP", "")
    try:
        return max(1, int(float(raw)))
    except ValueError:
        return DEFAULT_CAP


def load_counts() -> dict:
    try:
        with open(os.path.join(data_dir(), COUNT_FILE)) as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_counts(counts: dict) -> None:
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    keep = {k: v for k, v in counts.items() if k >= cutoff}
    with open(os.path.join(data_dir(), COUNT_FILE), "w") as fh:
        json.dump(keep, fh)


def max_run_usd() -> float:
    try:
        return max(0.01, float(os.environ.get("CLAUDE_PLUGIN_OPTION_MAX_RUN_USD", "") or DEFAULT_MAX_RUN_USD))
    except ValueError:
        return DEFAULT_MAX_RUN_USD


def find_cap(obj) -> float | None:
    """Finds a spending cap anywhere in the tool input (call-actor nests it in options)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in CAP_KEYS:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            found = find_cap(v)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_cap(v)
            if found is not None:
                return found
    return None


def apify_decision(tool: str, tool_input: dict) -> None:
    actor = tool_input.get("actor") or tool.rsplit("__", 1)[-1]
    if not tool.endswith("__call-actor"):
        decide("ask", f"Apify run of {actor} via a dedicated tool cannot carry a spending cap. "
                      "Prefer call-actor with maxTotalChargeUsd; approve only if you accept the estimated cost.")
        return
    cap_usd = find_cap(tool_input)
    if cap_usd is None:
        decide("ask", f"Apify run of {actor} has no maxTotalChargeUsd cap. Approve only if you accept an uncapped charge.")
    elif cap_usd > max_run_usd():
        decide("ask", f"Apify run of {actor} capped at ${cap_usd:.2f}, above your ${max_run_usd():.2f} per-run limit.")
    # within the limit: no output, normal permissions apply


def summarize(tool_input: dict) -> str:
    keys = ("to", "recipient", "recipients", "email", "subject", "campaign_id", "campaignId",
            "site_id", "domain", "url", "price", "quantity", "command")
    parts = []
    for k in keys:
        val = tool_input.get(k)
        if val in (None, "", []):
            continue
        text = val if isinstance(val, str) else json.dumps(val)
        parts.append(f"{k}={text[:120]}")
    return "; ".join(parts) or "see tool input"


def decide(decision: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": decision,
                                             "permissionDecisionReason": reason}}))


def classify(tool: str, tool_input: dict) -> tuple[bool, bool]:
    is_mcp = tool.startswith("mcp__")
    is_send = is_mcp and bool(SEND_TOOL.search(tool))
    is_paid = (is_mcp and bool(PAID_TOOL.search(tool))) or (
        tool == "Bash" and bool(PAID_BASH.search(str(tool_input.get("command", "")))))
    return is_send, is_paid


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return 0
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    if mode == "pre" and tool.startswith("mcp__") and APIFY_RUN.search(tool):
        apify_decision(tool, tool_input)
        return 0
    is_send, is_paid = classify(tool, tool_input)
    if not (is_send or is_paid):
        return 0

    today = dt.date.today().isoformat()
    if mode == "post":
        if is_send:
            counts = load_counts()
            counts[today] = int(counts.get(today, 0)) + 1
            save_counts(counts)
        return 0

    if is_send:
        sent = int(load_counts().get(today, 0))
        if sent >= cap():
            decide("deny", f"VibeCited daily send cap reached ({sent}/{cap()}). "
                           "Raise daily_send_cap in the plugin settings or continue tomorrow.")
            return 0
        decide("ask", f"Outreach send ({sent + 1}/{cap()} today): {summarize(tool_input)}. "
                      "Approve only if you reviewed this exact message and recipient.")
        return 0
    decide("ask", f"Paid action: {summarize(tool_input)}. Approve only if you confirmed item, price and total.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
