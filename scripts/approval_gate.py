#!/usr/bin/env python3
"""Citebase approval gate (PreToolUse / PostToolUse hook).

pre  : decides before outreach sends, paid vendor actions and Apify runs.
         deny -> blocked (missing price cap, unapproved draft, suppressed recipient,
                 daily limits, paused sending, actor not on the allowlist)
         ask  -> a human must approve this exact action
         none -> normal permissions apply
post : records recipients sent and the spend cap of Apify runs that actually ran.

Guardrails, not a security boundary: it only runs where the host supports hooks
(Claude Code) and only inside a project that has a seo-workspace/ folder. It never
returns "allow", so a human prompt always remains the final gate for sends and purchases.
Fails closed: an unreadable payload or state file blocks the call instead of waving it through.
Known limit: two gated calls issued in the same turn can both pass the pre check before either
post hook records its effect. Standard library only.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cb_state as st  # noqa: E402

READ_ONLY = re.compile(r"(get|list|search|read|prepare|fetch|find|count|check|create_draft|update_draft|delete|"
                       r"mark|label|unlabel|trash|untrash|unmark)_")
CAMPAIGN = re.compile(r"(start|resume|activate|launch)_campaign")
SEND_STRONG = re.compile(r"send_(e?mail|draft|reply)s?(_|$)|reply_all")
SEND_REPLY_FORWARD = re.compile(r"(^|_)(reply|forward)(_|$)")
SEND_MESSAGE = re.compile(r"send_message")
PAID = re.compile(r"add_.*to_cart|(^|_)(checkout|purchase|buy)(_|$)")
DEDICATED_ACTOR = re.compile(r"[\w.]+--[\w.-]+")
ACTOR_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$")
OWNER_ALLOWLIST = ("khadinakbar/",)
DEFAULT_MAX_RUN_USD = 2.0
DEFAULT_DAILY_SPEND_USD = 25.0
DEFAULT_SEND_CAP = 20
LEDGER = "${CLAUDE_PLUGIN_ROOT}/scripts/outreach_ledger.py"


class Decision(Exception):
    def __init__(self, verdict: str, reason: str):
        super().__init__(reason)
        self.verdict, self.reason = verdict, reason


def emit(verdict: str, reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                             "permissionDecision": verdict,
                                             "permissionDecisionReason": reason}}))


def classify(tool: str, tool_input: dict) -> str | None:
    """Maps a tool name to apify | dedicated | campaign | send | paid, or None when it is not ours.

    Names are matched case-, camelCase- and hyphen-insensitively (sendEmail, send-email, send_email)."""
    if not tool.startswith("mcp__"):
        return None
    last = tool.rsplit("__", 1)[-1]
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", last).lower().replace("-", "_").replace(".", "_")
    if snake == "call_actor":
        return "apify"
    if DEDICATED_ACTOR.fullmatch(last):
        return "dedicated"
    if READ_ONLY.match(snake):
        return None
    if CAMPAIGN.search(snake):
        return "campaign"
    if SEND_STRONG.search(snake) or SEND_REPLY_FORWARD.search(snake):
        return "send"
    if SEND_MESSAGE.search(snake) and st.recipients(tool_input):
        return "send"  # chat tools with no email recipient (Slack etc.) are none of our business
    if PAID.search(snake):
        return "paid"
    return None


def allowed_extra() -> list[str]:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_ALLOWED_ACTORS", "")
    return [x.strip().lower().replace("~", "/") for x in re.split(r"[,\s]+", raw) if x.strip()]


def actor_allowed(actor: str) -> bool:
    if any(actor.startswith(p) for p in OWNER_ALLOWLIST):
        return True
    for rule in allowed_extra():
        if rule == actor or (rule.endswith("/*") and actor.startswith(rule[:-1])):
            return True
    return False


def run_cap(tool_input: dict) -> float:
    """The only cap the Apify platform enforces is callOptions.maxTotalChargeUsd."""
    options = tool_input.get("callOptions")
    value = options.get("maxTotalChargeUsd") if isinstance(options, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise Decision("deny", "Apify run has no valid spending cap. Call call-actor again with "
                               "callOptions.maxTotalChargeUsd set to the quoted estimate x 1.3 "
                               "(a cap placed inside the Actor input is not enforced by Apify).")
    return float(value)


def decide_apify(tool_input: dict, state: dict) -> None:
    actor = str(tool_input.get("actor") or "").strip().lower().replace("~", "/")
    if not ACTOR_NAME.match(actor):
        raise Decision("deny", f"Actor '{actor or 'missing'}' is not a readable owner/name. "
                               "Use the Actor's public owner/name so its owner and price can be checked.")
    if not actor_allowed(actor):
        raise Decision("deny", f"Actor {actor} is not on the Citebase allowlist (khadinakbar/*). "
                               "Add it to the allowed_actors plugin setting if you trust it and have checked its pricing.")
    cap = run_cap(tool_input)
    ceiling = st.option_float("DAILY_SPEND_USD", DEFAULT_DAILY_SPEND_USD, 0.01)
    spent = float(st.day_record(state)["spend_usd"])
    if spent + cap > ceiling:
        raise Decision("deny", f"Daily spend ceiling: ${spent:.2f} already committed today + ${cap:.2f} cap "
                               f"exceeds ${ceiling:.2f}. Raise daily_spend_usd in the plugin settings or continue tomorrow.")
    limit = st.option_float("MAX_RUN_USD", DEFAULT_MAX_RUN_USD, 0.01)
    if cap > limit:
        raise Decision("ask", f"Apify run of {actor} capped at ${cap:.2f}, above your ${limit:.2f} per-run limit.")


def decide_dedicated(tool: str) -> None:
    last = tool.rsplit("__", 1)[-1].lower()
    owner, _, name = last.partition("--")
    if not actor_allowed(f"{owner}/{name}"):
        raise Decision("deny", f"Actor tool {last} is not on the Citebase allowlist (khadinakbar/*). "
                               "Add the owner to the allowed_actors plugin setting if you trust it.")
    raise Decision("ask", "A dedicated Actor tool cannot carry a spending cap. Prefer call-actor with "
                          "callOptions.maxTotalChargeUsd; approve only if you accept the estimated cost.")


def summarize(tool_input: dict) -> str:
    parts = []
    for key in ("to", "cc", "bcc", "subject", "campaign_id", "campaignId", "domain", "url", "price", "quantity"):
        val = tool_input.get(key)
        if val not in (None, "", []):
            parts.append(f"{key}={(val if isinstance(val, str) else json.dumps(val))[:100]}")
    return "; ".join(parts) or "see tool input"


def decide_send(tool_input: dict, state: dict, workspace: str | None) -> None:
    if state.get("paused"):
        raise Decision("deny", f"Outreach is paused ({state.get('pause_reason') or 'no reason given'}). "
                               f"Fix the cause, then run: python3 \"{LEDGER}\" resume")
    if st.unparsed_recipients(tool_input):
        raise Decision("deny", "Could not read every recipient address (unusual format). Use plain "
                               "name@domain addresses so suppression, caps and approval can be checked.")
    to = st.recipients(tool_input)
    rules = st.suppression_rules(workspace)
    hit = [a for a in to if st.is_suppressed(a, rules)]
    if hit:
        raise Decision("deny", f"Recipient on the suppression list: {', '.join(hit)}. Do not contact them.")
    count = max(1, len(to))
    sent, cap = int(st.day_record(state)["sent"]), int(st.option_float("DAILY_SEND_CAP", DEFAULT_SEND_CAP, 1))
    if sent + count > cap:
        raise Decision("deny", f"Daily send cap: {sent} sent today + {count} now exceeds {cap}. "
                               "Raise daily_send_cap in the plugin settings or continue tomorrow.")
    if not (to and st.body_text(tool_input)):
        raise Decision("ask", f"Outreach send ({sent + count}/{cap} today), recipient or body not visible to the "
                              f"gate: {summarize(tool_input)}. Open the draft and read it before approving.")
    if not st.approval_ok(state, st.draft_hash(tool_input)):
        raise Decision("deny", "This exact message was not approved (or the approval expired or was already used). "
                               "Show the user the final draft, and after they say yes run: "
                               f"python3 \"{LEDGER}\" approve --args '<the exact tool arguments as JSON>'. "
                               "Any edit after approval needs approval again.")
    raise Decision("ask", f"Outreach send ({sent + count}/{cap} today), matches the approved draft: "
                          f"{summarize(tool_input)}. Approve only if this recipient and text are right.")


def pre(kind: str, tool: str, tool_input: dict, workspace: str | None) -> None:
    state = st.load_state()
    if kind == "apify":
        decide_apify(tool_input, state)
    elif kind == "dedicated":
        decide_dedicated(tool)
    elif kind == "campaign":
        raise Decision("ask", f"Campaign start/resume: {summarize(tool_input)}. The campaign sends on its own schedule; "
                              "Citebase cannot count or cap those sends. Confirm list, copy, schedule and daily limit.")
    elif kind == "send":
        decide_send(tool_input, state, workspace)
    else:
        raise Decision("ask", f"Paid action: {summarize(tool_input)}. Approve only after confirming item, price and total.")


def post(kind: str, tool_input: dict) -> None:
    if kind not in ("send", "apify"):
        return
    with st.locked():
        state = st.load_state()
        rec = st.day_record(state)
        if kind == "send":
            rec["sent"] = int(rec["sent"]) + max(1, len(st.recipients(tool_input)))
            state["approvals"].pop(st.draft_hash(tool_input), None)
        else:
            try:
                rec["spend_usd"] = round(float(rec["spend_usd"]) + run_cap(tool_input), 4)
            except Decision:
                return
        st.save_state(state)


def _reject_constant(name: str):
    raise ValueError(f"unsupported JSON constant {name}")


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "pre"
    try:
        payload = json.load(sys.stdin, parse_constant=_reject_constant)
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except (ValueError, RecursionError) as err:
        print(f"Citebase gate: unreadable hook payload ({type(err).__name__}); blocking.", file=sys.stderr)
        return 2
    tool = str(payload.get("tool_name", ""))
    tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
    try:
        kind = classify(tool, tool_input)
        if kind is None:
            return 0
        workspace = st.find_workspace(payload.get("cwd"))
        if workspace is None and os.environ.get("CITEBASE_GATE") != "always":
            return 0
        if mode == "post":
            post(kind, tool_input)
        else:
            pre(kind, tool, tool_input, workspace)
    except Decision as d:
        emit(d.verdict, d.reason)
    except Exception as err:  # fail closed (includes RecursionError from hostile input)
        if mode == "post":
            print(f"Citebase gate: could not record the action ({type(err).__name__}).", file=sys.stderr)
        else:
            emit("deny", f"Citebase gate error ({type(err).__name__}). Blocked rather than guessing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
