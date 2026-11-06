#!/usr/bin/env python3
"""Outreach ledger CLI: draft approvals, suppression list, pause switch and status.

  approve  --args '<tool arguments as JSON>' | --args-file FILE
  suppress add ADDRESS_OR_@DOMAIN [--reason TEXT] | list | check ADDRESS   (check exits 1 if suppressed)
  pause [--reason TEXT] | resume | status

`approve` records the hash of the exact message the user just reviewed. The approval gate
refuses to send anything whose hash was not approved, and each approval works once. This
catches drift (text edited after review); the human "ask" prompt remains the real gate.
Standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cb_state as st  # noqa: E402


def load_args(ns: argparse.Namespace) -> dict:
    raw = open(ns.args_file).read() if ns.args_file else ns.args
    try:
        data = json.loads(raw or "")
    except ValueError as err:
        raise SystemExit(f"--args must be the tool arguments as JSON: {err}")
    if not isinstance(data, dict):
        raise SystemExit("--args must be a JSON object")
    return data


def cmd_approve(ns: argparse.Namespace) -> int:
    args = load_args(ns)
    to = st.recipients(args)
    if st.unparsed_recipients(args):
        raise SystemExit("Cannot approve: some recipient text is not a plain name@domain address.")
    if not to or not st.body_text(args):
        raise SystemExit("Cannot approve: the arguments need at least one recipient email and a message body.")
    rules = st.suppression_rules(st.find_workspace(os.getcwd()))
    blocked = [a for a in to if st.is_suppressed(a, rules)]
    if blocked:
        raise SystemExit(f"Cannot approve: on the suppression list: {', '.join(blocked)}")
    with st.locked():
        state = st.load_state()
        digest = st.draft_hash(args)
        state["approvals"][digest] = {"ts": st.now_iso(), "to": to, "subject": st.subject_text(args)[:120]}
        st.save_state(state)
    print(f"approved {digest[:12]} for {', '.join(to)} (valid {st.APPROVAL_TTL_HOURS}h, one send)")
    return 0


def cmd_suppress(ns: argparse.Namespace) -> int:
    path = os.path.join(st.home(), "suppression.txt")
    if ns.action == "add":
        rule = st.normalise_rule(ns.value)
        if "." not in rule:
            raise SystemExit("Give an email address or a domain.")
        os.makedirs(st.home(), exist_ok=True)
        with open(path, "a") as fh:
            fh.write(f"{rule}  # {ns.reason or st.today()}\n")
        print(f"suppressed {rule}")
        return 0
    rules = st.suppression_rules(st.find_workspace(os.getcwd()))
    if ns.action == "list":
        print("\n".join(rules) or "(empty)")
        return 0
    if not ns.value:
        raise SystemExit("check needs an address")
    hit = st.is_suppressed(ns.value, rules)
    print("suppressed" if hit else "ok")
    return 1 if hit else 0


def cmd_pause(ns: argparse.Namespace) -> int:
    with st.locked():
        state = st.load_state()
        state["paused"] = ns.command == "pause"
        state["pause_reason"] = (ns.reason or "") if state["paused"] else ""
        st.save_state(state)
    print("outreach paused" if state["paused"] else "outreach resumed")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    state = st.load_state()
    day = st.day_record(state)
    print(f"paused: {state['paused']}" + (f" ({state['pause_reason']})" if state["pause_reason"] else ""))
    print(f"sent today: {day['sent']} / cap {int(st.option_float('DAILY_SEND_CAP', 20, 1))}")
    print(f"apify spend committed today: ${float(day['spend_usd']):.2f} / ceiling "
          f"${st.option_float('DAILY_SPEND_USD', 25.0, 0.01):.2f}")
    print(f"approved drafts waiting: {len(state['approvals'])}")
    return 0


def build() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    a = sub.add_parser("approve")
    a.add_argument("--args", default="")
    a.add_argument("--args-file", default="")
    a.set_defaults(fn=cmd_approve)
    s = sub.add_parser("suppress")
    s.add_argument("action", choices=["add", "list", "check"])
    s.add_argument("value", nargs="?", default="")
    s.add_argument("--reason", default="")
    s.set_defaults(fn=cmd_suppress)
    for name in ("pause", "resume"):
        p = sub.add_parser(name)
        p.add_argument("--reason", default="")
        p.set_defaults(fn=cmd_pause)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    return ap


def main() -> int:
    ns = build().parse_args()
    try:
        return ns.fn(ns)
    except st.StateError as err:
        raise SystemExit(f"State file problem: {err}. Fix or delete {st.state_path()} and retry.")


if __name__ == "__main__":
    sys.exit(main())
