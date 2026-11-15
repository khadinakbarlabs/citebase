"""First-party signals a user can paste in: which AI bots visit their site (from their own server log) and how
many visits AI assistants send them (from their own analytics export).

Pure functions: no network, no storage, no cost. Only counts leave this module. Raw log lines, IP addresses and
query strings are never kept, so nothing personal is saved with a project.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import re
from collections import Counter, defaultdict
from typing import Any

MAX_LOG_CHARS = 1_500_000
MAX_LOG_LINES = 200_000
MAX_TRAFFIC_ROWS = 5000
TOP_PAGES = 5
MAX_LINE_CHARS = 8000
MAX_COUNT = 1e12
SAFE_SEGMENT = re.compile(r"^[a-z][a-z-]{0,39}$")

# (name in the user-agent, who runs it, what it does). "answer" bots fetch pages to answer a live question or to
# build the search index an assistant answers from: blocking them removes the site from those answers.
# "training" bots collect text to train models: blocking them is a business choice and does not stop citations.
AI_BOTS = [
    ("ChatGPT-User", "OpenAI", "answer"), ("OAI-SearchBot", "OpenAI", "answer"), ("GPTBot", "OpenAI", "training"),
    ("Claude-User", "Anthropic", "answer"), ("Claude-SearchBot", "Anthropic", "answer"),
    ("ClaudeBot", "Anthropic", "training"), ("anthropic-ai", "Anthropic", "training"),
    ("Perplexity-User", "Perplexity", "answer"), ("PerplexityBot", "Perplexity", "answer"),
    ("Google-CloudVertexBot", "Google", "training"), ("GoogleOther", "Google", "training"),
    ("Googlebot", "Google", "answer"),  # Google AI Overviews and AI Mode answer from the normal Google index
    ("bingbot", "Microsoft", "answer"),  # Copilot and ChatGPT search answer from the Bing index
    ("DuckAssistBot", "DuckDuckGo", "answer"), ("MistralAI-User", "Mistral", "answer"),
    ("meta-externalagent", "Meta", "training"), ("meta-externalfetcher", "Meta", "answer"),
    ("Applebot-Extended", "Apple", "training"), ("Applebot", "Apple", "answer"),
    ("Amazonbot", "Amazon", "training"), ("Bytespider", "ByteDance", "training"), ("CCBot", "Common Crawl", "training"),
    ("cohere-ai", "Cohere", "training"), ("Diffbot", "Diffbot", "training"), ("YouBot", "You.com", "answer"),
]
_BOT_PATTERNS = [(name, owner, kind, re.compile(re.escape(name), re.I)) for name, owner, kind in AI_BOTS]

# One line of the common/combined web server log format (Apache, Nginx, most hosts and CDNs export this).
LOG_LINE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] "(?P<method>[A-Z]+) (?P<path>[^\s"]+)[^"]*" (?P<status>\d{3}) \S+'
    r'(?: "(?P<referrer>[^"]*)" "(?P<agent>[^"]*)")?')

# Referrer hosts that mean "an AI assistant sent this visit".
AI_REFERRERS = {
    "chatgpt.com": "ChatGPT", "chat.openai.com": "ChatGPT", "openai.com": "ChatGPT",
    "perplexity.ai": "Perplexity", "claude.ai": "Claude", "gemini.google.com": "Gemini",
    "copilot.microsoft.com": "Copilot", "copilot.com": "Copilot", "you.com": "You.com", "phind.com": "Phind",
    "meta.ai": "Meta AI", "grok.com": "Grok", "chat.mistral.ai": "Mistral", "chat.deepseek.com": "DeepSeek",
    "duckduckgo.com/aichat": "DuckDuckGo AI",
}
BARE_NAMES = {"chatgpt": "ChatGPT", "perplexity": "Perplexity", "claude": "Claude", "gemini": "Gemini",
              "copilot": "Copilot", "grok": "Grok", "deepseek": "DeepSeek"}
SOURCE_KEYS = ("source", "session source", "session source / medium", "session source/medium", "referrer",
               "page referrer", "source / medium", "source/medium", "first user source", "channel", "referring site")
SESSION_KEYS = ("sessions", "visits", "users", "total users", "active users", "clicks", "engaged sessions", "views")
CONVERSION_KEYS = ("conversions", "key events", "purchases", "goal completions", "leads", "signups", "sign-ups")
REVENUE_KEYS = ("revenue", "total revenue", "purchase revenue")
DATE_KEYS = ("date", "month", "day", "week", "period", "year month", "yearmonth")


def identify_bot(agent: str) -> tuple[str, str, str] | None:
    """(name, owner, kind) for a user-agent that names a known AI or search bot, else None."""
    for name, owner, kind, pattern in _BOT_PATTERNS:
        if pattern.search(agent or ""):
            return name, owner, kind
    return None


def _clean_path(path: str) -> str:
    """The page path without its query string (queries can hold personal data) and capped in length."""
    path = (path or "/").split("?", 1)[0].split("#", 1)[0][:200] or "/"
    segments = [x for x in path.split("/") if x]
    # Only plain page names are kept. Paths holding ids, emails, tokens or usernames are counted as '(other)'.
    if len(segments) > 3 or not all(SAFE_SEGMENT.match(x) for x in segments):
        return "(other)"
    return path


def _log_day(stamp: str) -> str:
    """'10/Nov/2026:13:55:36 +0000' -> '2026-11-10'; '' when it cannot be read."""
    try:
        return dt.datetime.strptime(stamp.split()[0], "%d/%b/%Y:%H:%M:%S").date().isoformat()
    except (ValueError, IndexError):
        return ""


def summarise_bot_log(text: str) -> dict:
    """Which AI and search bots read the site, from a pasted web server log.

    Returns counts only: per bot the number of requests, how many different pages, the pages read most, the share
    of requests that got an error, and the first and last day seen. Raises ValueError when the text is not a web
    server log, so a wrong paste gets a plain answer instead of an empty result."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Paste lines from the website's access log (the server's list of every request).")
    if len(text) > MAX_LOG_CHARS:
        raise ValueError(f"That log is too long (limit {MAX_LOG_CHARS:,} characters). Paste the last few days only.")
    lines = text.splitlines()[:MAX_LOG_LINES]
    bots: dict[str, dict[str, Any]] = {}
    parsed = with_agent = 0
    days: list[str] = []
    for line in lines:
        if len(line) > MAX_LINE_CHARS:
            continue  # a line this long is not a log line, and matching it is slow
        hit = LOG_LINE.match(line.strip())
        if not hit:
            continue
        parsed += 1
        agent = hit.group("agent")
        if agent is None:
            continue
        with_agent += 1
        day = _log_day(hit.group("time"))
        if day:
            days.append(day)
        found = identify_bot(agent)
        if not found:
            continue
        name, owner, kind = found
        entry = bots.setdefault(name, {"bot": name, "owner": owner, "kind": kind, "requests": 0, "errors": 0,
                                       "blocked": 0, "pages": Counter(), "first_seen": day, "last_seen": day})
        entry["requests"] += 1
        status = int(hit.group("status"))
        if status >= 400:
            entry["errors"] += 1
        if status in (401, 403, 429):
            entry["blocked"] += 1
        entry["pages"][_clean_path(hit.group("path"))] += 1
        if day:
            entry["first_seen"] = min(entry["first_seen"] or day, day)
            entry["last_seen"] = max(entry["last_seen"] or day, day)
    if not parsed:
        raise ValueError("None of those lines look like a web server access log. Each line should start with an "
                         "address and a date in square brackets, and end with the visitor's user-agent in quotes. "
                         "Ask your host or site builder for the 'access log' or 'raw access logs'.")
    if not with_agent:
        raise ValueError("This log has no user-agent column, so bots cannot be told apart. Ask your host for the "
                         "'combined' log format (it includes the user-agent).")
    out = []
    for entry in sorted(bots.values(), key=lambda e: (-e["requests"], e["bot"])):
        pages = entry.pop("pages")
        out.append({**entry, "pages": len(pages), "top_pages": [p for p, _n in pages.most_common(TOP_PAGES)],
                    "error_share": round(entry["errors"] / entry["requests"], 3)})
    answer = [b for b in out if b["kind"] == "answer"]
    seen = {b["owner"] for b in answer}
    return {"lines_read": parsed, "period": {"from": min(days) if days else None, "to": max(days) if days else None},
            "bots": out, "answer_bot_requests": sum(b["requests"] for b in answer),
            "training_bot_requests": sum(b["requests"] for b in out if b["kind"] == "training"),
            "findings": _bot_findings(out, seen), "truncated": len(text.splitlines()) > MAX_LOG_LINES}


def _bot_findings(bots: list[dict], answer_owners: set[str]) -> list[str]:
    """Plain sentences worth telling the user. Each is a fact from the log, never a guess about ranking."""
    notes = []
    for bot in bots:
        if bot["kind"] == "answer" and bot["requests"] >= 5 and bot["blocked"] / bot["requests"] >= 0.5:
            notes.append(f"{bot['bot']} ({bot['owner']}) is being refused on most requests ({bot['blocked']} of "
                         f"{bot['requests']}). It fetches pages to answer questions, so those answers cannot use "
                         "your pages. Check the firewall or bot settings.")
        elif bot["kind"] == "answer" and bot["requests"] >= 5 and bot["error_share"] >= 0.3:
            notes.append(f"{bot['bot']} ({bot['owner']}) gets an error on {round(100 * bot['error_share'])}% of its "
                         "requests. Fix the broken pages it asks for.")
    for owner in ("OpenAI", "Perplexity", "Anthropic"):
        if owner not in answer_owners:
            notes.append(f"No answer bot from {owner} appears in this log. That can mean a short log, a block before "
                         "the server (a firewall or CDN rule), or that it has not looked yet.")
    if not bots:
        notes.append("No AI or search bot appears in this log at all. Check that the log covers a few days and that "
                     "bots are not blocked before they reach the server.")
    return notes


# ---------------------------------------------------------------- AI referral traffic
def ai_source(value: Any) -> str | None:
    """The assistant a traffic source belongs to ('chatgpt.com / referral' -> 'ChatGPT'), else None."""
    text = str(value or "").strip().lower()
    text = re.sub(r"^https?://", "", text)
    text = re.sub(r"^www\.", "", text)
    if text in BARE_NAMES:
        return BARE_NAMES[text]
    for host, name in AI_REFERRERS.items():
        if text == host or text.startswith(host + "/") or text.startswith(host + " ") or text.startswith(host + "?") \
                or re.match(rf"^([a-z0-9-]+\.)*{re.escape(host)}(\s|/|$)", text):
            return name
    return None


def _number(value: Any) -> float:
    """A count or amount from an export cell ('1,204', '3.5', '', None) as a number; 0 when it is not one."""
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, int):
        return float(value) if abs(value) < MAX_COUNT else 0.0
    if isinstance(value, float):
        return value if value == value and abs(value) < MAX_COUNT else 0.0
    text = str(value or "").strip()
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", text):  # 1.204,5: dots group thousands, comma is the decimal
        text = text.replace(".", "").replace(",", ".")
    text = re.sub(r"[^\d.\-]", "", text.replace(",", ""))
    try:
        number = float(text) if text not in ("", "-", ".") else 0.0
    except ValueError:
        return 0.0
    return number if abs(number) < MAX_COUNT else 0.0


def _pick(row: dict, keys: tuple[str, ...]) -> Any:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return None


def _month(value: Any) -> str:
    """'2026-11-03', '20261103', '2026-11', 'Nov 2026', '202611' -> '2026-11'; '' when it cannot be read."""
    text = str(value or "").strip()
    for pattern, fmt in ((r"^\d{4}-\d{2}-\d{2}", "%Y-%m-%d"), (r"^\d{8}$", "%Y%m%d"), (r"^\d{4}-\d{2}$", "%Y-%m"),
                         (r"^\d{6}$", "%Y%m"), (r"^[A-Za-z]{3} \d{4}$", "%b %Y"), (r"^[A-Za-z]+ \d{4}$", "%B %Y"),
                         (r"^\d{1,2}/\d{1,2}/\d{4}$", "%m/%d/%Y")):
        hit = re.match(pattern, text)
        if hit:
            try:
                return dt.datetime.strptime(hit.group(0), fmt).strftime("%Y-%m")
            except ValueError:
                continue
    return ""


def parse_traffic_csv(text: str) -> list[dict]:
    """Rows from a pasted analytics export (CSV or tab-separated). Comment lines and blank lines are skipped."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Paste the analytics export as text (CSV), with a header row.")
    if len(text) > MAX_LOG_CHARS:
        raise ValueError(f"That export is too long (limit {MAX_LOG_CHARS:,} characters). Export fewer rows.")
    lines = [ln for ln in text.lstrip("\ufeff").splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if len(lines) < 2:
        raise ValueError("The export needs a header row and at least one row of data.")
    delimiter = max(("\t", ",", ";"), key=lambda d: lines[0].count(d))
    try:
        return list(csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter))[:MAX_TRAFFIC_ROWS]
    except (csv.Error, OverflowError) as exc:
        raise ValueError("That export could not be read as a table. A cell may be far too long, or the quoting is "
                         f"broken ({type(exc).__name__}). Export it again as plain CSV.") from None


def summarise_traffic(rows: list[dict]) -> dict:
    """Visits that AI assistants sent, from analytics rows that each name a source and a visit count.

    Returns per assistant: visits, conversions and revenue (when the export has them), and per month the AI visits
    and their share of all visits in the export. Raises ValueError when no row has a source and a count."""
    if not isinstance(rows, list) or not rows:
        raise ValueError("Send the analytics rows: each needs a source (or referrer) and a number of sessions.")
    if len(rows) > MAX_TRAFFIC_ROWS:
        raise ValueError(f"Send at most {MAX_TRAFFIC_ROWS:,} rows. Export by month instead of by day.")
    by_ai: dict[str, dict[str, float]] = defaultdict(lambda: {"visits": 0.0, "conversions": 0.0, "revenue": 0.0})
    months: dict[str, dict[str, float]] = defaultdict(lambda: {"ai_visits": 0.0, "all_visits": 0.0})
    usable = 0
    total = ai_total = 0.0
    has_conversions = has_revenue = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        source, visits = _pick(row, SOURCE_KEYS), _pick(row, SESSION_KEYS)
        if source is None or visits is None:
            continue
        usable += 1
        count = max(_number(visits), 0.0)
        month = _month(_pick(row, DATE_KEYS))
        total += count
        if month:
            months[month]["all_visits"] += count
        name = ai_source(source)
        if not name:
            continue
        conversions, revenue = _pick(row, CONVERSION_KEYS), _pick(row, REVENUE_KEYS)
        has_conversions = has_conversions or conversions is not None
        has_revenue = has_revenue or revenue is not None
        by_ai[name]["visits"] += count
        by_ai[name]["conversions"] += max(_number(conversions), 0.0)
        by_ai[name]["revenue"] += max(_number(revenue), 0.0)
        ai_total += count
        if month:
            months[month]["ai_visits"] += count
    if not usable:
        raise ValueError("No row had both a source and a visit count. The export needs a column such as 'Session "
                         "source' or 'Referrer' and one such as 'Sessions' or 'Users'. In Google Analytics: Reports, "
                         "Acquisition, Traffic acquisition, set the first column to 'Session source', then export.")
    assistants = [{"assistant": name, "visits": round(v["visits"]),
                   "conversions": round(v["conversions"], 2) if has_conversions else None,
                   "revenue": round(v["revenue"], 2) if has_revenue else None}
                  for name, v in sorted(by_ai.items(), key=lambda kv: (-kv[1]["visits"], kv[0]))]
    by_month = [{"month": m, "ai_visits": round(v["ai_visits"]), "all_visits": round(v["all_visits"]),
                 "ai_share": round(v["ai_visits"] / v["all_visits"], 4) if v["all_visits"] else None}
                for m, v in sorted(months.items())]
    share = round(ai_total / total, 4) if total else None
    return {"rows_read": usable, "ai_visits": round(ai_total), "all_visits": round(total), "ai_share": share,
            "assistants": assistants, "by_month": by_month, "findings": _traffic_findings(ai_total, total, assistants)}


def _traffic_findings(ai_total: float, total: float, assistants: list[dict]) -> list[str]:
    notes = []
    if not ai_total:
        notes.append("No visits from AI assistants appear in this export. That is common: assistants often answer "
                     "without a click, and many clicks arrive with no source at all (they show as 'direct').")
    else:
        pct = 100 * ai_total / total if total else 0
        top = assistants[0]
        notes.append(f"AI assistants sent {round(ai_total)} of {round(total)} visits ({pct:.1f}%). Most came from "
                     f"{top['assistant']} ({top['visits']}).")
        notes.append("This undercounts: answers read without a click, and clicks that arrive with no source, are "
                     "not in these numbers. Read it as a floor and watch the direction over time.")
    return notes
