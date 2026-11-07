"""Shared state helpers for the Citebase approval gate and outreach ledger.

Standard library only. State lives in one JSON file under CITEBASE_HOME
(default ~/.citebase) so the hook process and the ledger CLI always agree,
whatever environment each one is launched with.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import html
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


PREVIEW_CHARS = 300  # how much of the message text the send prompt shows
PREVIEW_SOURCE_CHARS = 100_000  # only the start of a long body is turned into the preview
SCAN_LIMIT = 4_000_000  # characters scanned for links across one message
MAX_HOSTS_SCANNED = 20000
MAX_DOMAINS_KEPT = 50  # per approval record
HTML_KEYS = ("html", "html_body", "htmlbody")
_INVISIBLE = re.compile(r"[\x00-\x08\x0e-\x1f\x7f-\x9f\u00ad\u061c\u180e\u200b-\u200f\u202a-\u202e\u2060-\u206f"
                        r"\ufeff\ufff9-\ufffb\U000e0001\U000e0020-\U000e007f]")  # control, zero-width and bidi characters
_DOTS = {0x3002: ".", 0xFF0E: ".", 0xFF61: "."}  # dots that browsers treat as "."
_BLOCKS = re.compile(r"(?is)<(script|style)\b[^>]{0,1000}>.*?(?:</\1\s*>|$)")
_TAGS = re.compile(r"<[^>]{0,1000}>")
_LOOKS_HTML = re.compile(r"</?[a-zA-Z][^>]{0,200}>")
_AUTH = r"(\[[0-9a-fA-F:.%]{2,45}\]|[^\s/?#\\\"'<>()\[\]{}|^`]+)"
_URL = re.compile(r"(?:\b[a-zA-Z][a-zA-Z0-9+.-]{1,15}:|(?<![\w:/.%-]))//" + _AUTH)  # http://host and //host
_BEFORE = r"(?<![\w@./:-])"  # start of a word, not inside an address or a longer host
_WWW = re.compile(_BEFORE + r"(www\.[a-z0-9-]+(?:\.[a-z0-9-]+)+)", re.I)
_PATH_HOST = re.compile(_BEFORE + r"((?:[a-z0-9-]+\.)+[a-z]{2,24})(?=/)", re.I)  # evil.example/page
_COMMON_TLDS = ("com|net|org|io|co|ai|dev|app|info|biz|xyz|me|us|uk|de|fr|ca|au|nl|in|shop|site|online|blog|tech|"
                "link|ly|to|gg|tv|cc|ru|cn|top|club|store|zip|mov|click|help|work|support|live|icu|cyou|sbs|rest|fit|monster|"
                "cfd|buzz|vip|win|loan|review|date|stream|download|party|trade|bid|host|website|space|press|today|"
                "world|life|email|cloud|digital|network|solutions|services|agency|group|pro|one|page|xxx|ink|run")
_BARE = re.compile(_BEFORE + r"((?:[a-z0-9-]+\.)+(?:" + _COMMON_TLDS + r"))(?![\w-])", re.I)
_DOMAIN_DIR = re.compile(r"[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+", re.I)


def _clean_host(authority: str) -> str:
    """The host a browser would contact for the text after '//': no user info, port, trailing punctuation."""
    host = authority.rpartition("@")[2]
    if host.startswith("["):
        host = host.split("]", 1)[0] + "]"
    else:
        host = re.sub(r":\d*$", "", host)
    host = host.strip(".,;:!?'\u2019\u201d").lower().rstrip(".")
    return host[:80] if ("." in host or host.startswith("[")) else ""


def _hosts_in(text: str):
    text = text.translate(_DOTS)
    for match in _URL.finditer(text):
        yield _clean_host(match.group(1))
    for pattern in (_WWW, _PATH_HOST, _BARE):
        for match in pattern.finditer(text):
            yield _clean_host(match.group(1))


def link_scan(tool_input: dict) -> tuple[list[str], bool]:
    """Distinct hosts linked from any text in the message, and whether some text was beyond SCAN_LIMIT.

    Linear in the input: patterns are anchored at word starts and every bracketed part is bounded."""
    found: dict[str, None] = {}
    budget, truncated = SCAN_LIMIT, False
    for text in _strings(tool_input):
        if budget <= 0:
            truncated = True
            break
        if len(text) > budget:
            text, truncated = text[:budget], True
        budget -= len(text)
        for host in _hosts_in(_INVISIBLE.sub("", text)):
            if host and len(found) < MAX_HOSTS_SCANNED:
                found.setdefault(host)
    return list(found), truncated


def body_preview(tool_input: dict) -> tuple[str, bool]:
    """The first PREVIEW_CHARS characters of the message as plain, single-line text, and whether more follows."""
    for key, val in tool_input.items():
        name = str(key).lower()
        if name in BODY_KEYS and isinstance(val, str) and val.strip():
            raw = val[:PREVIEW_SOURCE_CHARS]
            if name in HTML_KEYS or _LOOKS_HTML.search(raw[:5000]):
                raw = html.unescape(_TAGS.sub(" ", _BLOCKS.sub(" ", raw)))
            text = _INVISIBLE.sub("", collapse(raw))
            return text[:PREVIEW_CHARS], len(text) > PREVIEW_CHARS or len(val) > len(raw)
    return "", False


def sender_domains(tool_input: dict) -> set[str]:
    out: set[str] = set()
    for key, val in tool_input.items():
        if any(hint in str(key).lower() for hint in SENDER_HINTS):
            for text in _strings(val):
                out.update(addr.lower().rpartition("@")[2] for addr in EMAIL_RE.findall(text))
    return out


def _bare(domain: str) -> str:
    domain = domain.lower()
    return domain[4:] if domain.startswith("www.") else domain


def brand_domains(workspace: str | None, tool_input: dict | None = None) -> set[str]:
    """Domains that are 'ours': seo-workspace/<domain>/ folder names and the sender address's domain."""
    names = set(sender_domains(tool_input or {}))
    if workspace and os.path.isdir(workspace):
        try:
            entries = os.listdir(workspace)
        except OSError:
            entries = []
        names.update(e for e in entries if _DOMAIN_DIR.fullmatch(e) and os.path.isdir(os.path.join(workspace, e)))
    return {_bare(n) for n in names}


def foreign_domains(domains: list[str], brand: set[str], to: list[str]) -> list[str]:
    """Linked domains that are neither the brand's nor a recipient's own."""
    ok = {_bare(d) for d in brand} | {_bare(a.rpartition("@")[2]) for a in to}
    return [d for d in domains if not any(_bare(d) == b or _bare(d).endswith("." + b) for b in ok)]


def draft_id(tool_input: dict) -> str:
    """The draft id a send-by-id call refers to ('' when the call carries none)."""
    for key, val in tool_input.items():
        if str(key).lower() in ("draft_id", "draftid") and isinstance(val, (str, int)) and not isinstance(val, bool):
            text = str(val).strip()
            if text:
                return text[:200]
    return ""


def draft_approval(state: dict, tool_input: dict) -> dict | None:
    """The newest unexpired approval record registered for this call's draft id, else None.

    Raises StateError when a matching record has no readable recipient list (callers fail closed)."""
    ident = draft_id(tool_input)
    best = None
    for digest, rec in (state.get("approvals", {}).items() if ident else ()):
        if not isinstance(rec, dict) or rec.get("draft_id") != ident or not approval_ok(state, digest):
            continue
        to = rec.get("to")
        if not (isinstance(to, list) and to and all(isinstance(a, str) and a for a in to)):
            raise StateError("a registered draft has no readable recipient list")
        if best is None or str(rec.get("ts")) > str(best.get("ts")):
            best = rec
    return best


def drop_draft_approvals(state: dict, ident: str) -> None:
    state["approvals"] = {k: v for k, v in state["approvals"].items()
                          if not (isinstance(v, dict) and v.get("draft_id") == ident)}


def draft_record(tool_input: dict, ident: str) -> dict:
    """What the gate needs later to judge a send-by-draft-id call: id, text preview, links and sender domains."""
    domains, truncated = link_scan(tool_input)
    excerpt, more = body_preview(tool_input)
    return {"draft_id": ident, "excerpt": excerpt, "excerpt_more": more, "domains": domains[:MAX_DOMAINS_KEPT],
            "domains_total": len(domains), "scan_truncated": truncated, "senders": sorted(sender_domains(tool_input))}


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
