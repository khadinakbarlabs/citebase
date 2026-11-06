"""Shared state helpers for the Citebase approval gate and outreach ledger.

Standard library only. State lives in one JSON file under CITEBASE_HOME
(default ~/.citebase) so the hook process and the ledger CLI always agree,
whatever environment each one is launched with.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import tempfile

try:
    import fcntl  # POSIX only; state still works without it
except ImportError:  # pragma: no cover
    fcntl = None

KEEP_DAYS = 30
APPROVAL_TTL_HOURS = 48
WORKSPACE_DIR = "seo-workspace"
MAX_STRINGS = 20000  # bounds work on hostile, deeply nested tool input
EMAIL_RE = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w-]+(?:\.[\w-]+)+")
BODY_KEYS = ("body", "text", "content", "message", "html_body", "plain_body", "html",
             "plain_text", "text_body", "textbody", "htmlbody")
NON_RECIPIENT_KEYS = set(BODY_KEYS) | {"subject", "attachments", "attachment", "files", "thread_id", "message_id",
                                       "threadid", "messageid", "draft_id", "draftid"}
SENDER_HINTS = ("from", "sender", "account", "mailbox")


class StateError(Exception):
    """State file exists but cannot be trusted; callers must fail closed."""


def home() -> str:
    return os.environ.get("CITEBASE_HOME") or os.path.expanduser("~/.citebase")


def state_path() -> str:
    return os.path.join(home(), "state.json")


def today() -> str:
    return dt.date.today().isoformat()


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def default_state() -> dict:
    return {"version": 1, "paused": False, "pause_reason": "", "days": {}, "approvals": {}}


def load_state() -> dict:
    try:
        with open(state_path()) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return default_state()
    except (OSError, ValueError, RecursionError) as err:
        raise StateError(f"state file unreadable: {err}") from err
    if not isinstance(data, dict) or not isinstance(data.get("days", {}), dict) \
            or not isinstance(data.get("approvals", {}), dict):
        raise StateError("state file has an unexpected shape")
    merged = default_state()
    merged.update(data)
    return merged


def _parse_ts(value) -> dt.datetime | None:
    try:
        stamp = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)


def approval_ok(state: dict, digest: str) -> bool:
    """True only for an approval that exists and is younger than APPROVAL_TTL_HOURS."""
    rec = state.get("approvals", {}).get(digest)
    stamp = _parse_ts(rec.get("ts")) if isinstance(rec, dict) else None
    horizon = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=APPROVAL_TTL_HOURS)
    return bool(stamp and stamp >= horizon)


def _prune(state: dict) -> dict:
    cutoff = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    state["days"] = {k: v for k, v in state["days"].items() if k >= cutoff}
    state["approvals"] = {k: v for k, v in state["approvals"].items() if approval_ok(state, k)}
    return state


def save_state(state: dict) -> None:
    os.makedirs(home(), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=home(), prefix="state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(_prune(state), fh, indent=1)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, state_path())
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def locked():
    """Serialises read-modify-write cycles across the hook and the ledger CLI."""
    os.makedirs(home(), exist_ok=True)
    with open(os.path.join(home(), ".lock"), "w") as fh:
        if fcntl:
            fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(fh, fcntl.LOCK_UN)


def day_record(state: dict) -> dict:
    return state["days"].setdefault(today(), {"sent": 0, "spend_usd": 0.0})


def _strings(value):
    """Yields every string inside nested lists/dicts without recursion, up to MAX_STRINGS."""
    stack, seen = [value], 0
    while stack and seen < MAX_STRINGS:
        item = stack.pop()
        if isinstance(item, str):
            seen += 1
            yield item
        elif isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)


def recipient_fields(tool_input: dict) -> dict[str, list[str]]:
    """Maps each recipient-like field (any key that is not body/subject/sender/attachment) to its address texts."""
    fields: dict[str, list[str]] = {}
    for key, val in tool_input.items():
        name = str(key).lower()
        if name in NON_RECIPIENT_KEYS or any(h in name for h in SENDER_HINTS):
            continue
        texts = [t for t in _strings(val) if "@" in t]
        if texts:
            fields[name] = texts
    return fields


def recipients(tool_input: dict) -> list[str]:
    seen: list[str] = []
    for texts in recipient_fields(tool_input).values():
        for text in texts:
            for addr in EMAIL_RE.findall(text):
                if addr.lower() not in seen:
                    seen.append(addr.lower())
    return seen


def unparsed_recipients(tool_input: dict) -> bool:
    """True when recipient fields hold more '@' signs than parsable addresses (fail closed on odd formats)."""
    at_signs = matches = 0
    for texts in recipient_fields(tool_input).values():
        for text in texts:
            at_signs += text.count("@")
            matches += len(EMAIL_RE.findall(text))
    return at_signs > matches


def collapse(text) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def body_text(tool_input: dict) -> str:
    for key, val in tool_input.items():
        if str(key).lower() in BODY_KEYS and isinstance(val, str) and val.strip():
            return collapse(val)
    return ""


def subject_text(tool_input: dict) -> str:
    return collapse(tool_input.get("subject") or "")


def draft_hash(tool_input: dict) -> str:
    """Fingerprint of the whole message: recipients per field, subject, every body part, attachments and extras.

    Insensitive to case in addresses/subjects and to whitespace; sensitive to anything that changes what is sent."""
    fields = recipient_fields(tool_input)
    canon: dict = {}
    for key, val in tool_input.items():
        name = str(key).lower()
        if name in fields:
            canon[name] = sorted({a.lower() for t in fields[name] for a in EMAIL_RE.findall(t)})
        elif name == "subject":
            canon[name] = collapse(val).lower()
        elif name in BODY_KEYS and isinstance(val, str):
            canon[name] = collapse(val)
        else:
            canon[name] = val
    blob = json.dumps(canon, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def find_workspace(cwd) -> str | None:
    """Returns the nearest seo-workspace directory at or above cwd, else None."""
    path = os.path.abspath(cwd if isinstance(cwd, str) and cwd else os.getcwd())
    while True:
        candidate = os.path.join(path, WORKSPACE_DIR)
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent


def normalise_rule(raw: str) -> str:
    rule = raw.split("#", 1)[0].strip().lower().lstrip("*")
    if not rule:
        return ""
    return rule if "@" in rule else "@" + rule


def _read_rules(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return [r for r in (normalise_rule(ln) for ln in fh) if r]
    except OSError:
        return []


def suppression_rules(workspace: str | None = None) -> list[str]:
    rules = _read_rules(os.path.join(home(), "suppression.txt"))
    if workspace and os.path.isdir(workspace):
        rules += _read_rules(os.path.join(workspace, "suppression.txt"))
        for entry in sorted(os.listdir(workspace)):
            rules += _read_rules(os.path.join(workspace, entry, "suppression.txt"))
    return rules


def _split(email: str) -> tuple[str, str]:
    local, _, domain = email.lower().rpartition("@")
    return local.split("+", 1)[0], domain


def is_suppressed(email: str, rules: list[str]) -> bool:
    """Address rules ignore +tags; @domain rules also cover subdomains."""
    local, domain = _split(email)
    for rule in rules:
        rule_local, rule_domain = _split(rule)
        if rule_local:
            if rule_local == local and rule_domain == domain:
                return True
        elif domain == rule_domain or domain.endswith("." + rule_domain):
            return True
    return False


def option_float(name: str, default: float, minimum: float) -> float:
    raw = os.environ.get(f"CLAUDE_PLUGIN_OPTION_{name}", "")
    try:
        value = float(raw) if raw.strip() else default
    except ValueError:
        return default
    return max(minimum, value) if value == value and abs(value) != float("inf") else default
