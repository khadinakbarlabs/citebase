"""Private, evidence-backed reviews of exact wording in saved AI answers."""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections import Counter
from urllib.parse import urlsplit

import storage as stg

PAGE_SIZE = 8
MAX_CLAIMS = 100
VERDICTS = ("true", "false", "unverified")
REVIEW_NOTE = ("These verdicts come from your review or your assistant's review of the cited evidence. "
               "Citebase checks that the quote is in the saved answer. Read the source before relying on a verdict.")


def answer_id(row: dict) -> str:
    fields = ("snapshot", "prompt_id", "platform", "repeat", "date", "answered_at", "answer_text",
              "answer_truncated", "engine_version", "country", "language", "device", "source")
    payload = json.dumps([row.get(field) for field in fields])
    return hashlib.sha256(payload.encode()).hexdigest()


def text_answers(rows: list[dict]) -> dict[str, dict]:
    return {row["answer_ref"]: row for row in rows if row.get("answer_ref")}


async def load_text(be, answers: dict) -> dict:
    records = {row["answer_record"] for row in answers.values()}
    if not records:
        return {}
    store = await be.private_store()
    fetched = await asyncio.gather(*(store.get(record) for record in records))
    return {ref: text for record in fetched if record for ref, text in record.items() if ref in answers}


def clean_source(value: str) -> str:
    if not value:
        return ""
    try:
        url = urlsplit(value)
        valid = (url.scheme == "https" and url.hostname and "." in url.hostname and not url.username
                 and not url.password and not url.query and not url.fragment and not url.port
                 and not any(c.isspace() or c == "\\" or ord(c) < 32 for c in value))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Use a public HTTPS source link without sign-in details, query parameters or a fragment.")
    return value


def safe_evidence_urls(values, limit=8):
    """Keep bounded, query-free HTTPS evidence references. Never propagate sign-in URLs."""
    urls = []
    if not isinstance(values, list):
        return urls
    for value in values[:60]:
        if not isinstance(value, str) or len(value) > 500 or value in urls:
            continue
        try:
            if clean_source(value):
                urls.append(value)
        except ValueError:
            continue
        if len(urls) == limit:
            break
    return urls


def field(claim: dict, name: str, limit: int, required: bool = False) -> str:
    value = claim.get(name, "")
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise ValueError(f"Send {name} as text up to {limit} characters.")
    return value.strip()


async def read_claims(be, project: str, snapshot: str, answers: dict) -> list[dict]:
    if not answers:
        return []
    store = await be.private_store()
    stored = await store.get(stg.key(project, "facts", snapshot)) or []
    return [claim for claim in stored if claim["answer_id"] in answers]


async def save_claims(be, project: str, snapshot: str, claims: list, today: str) -> int:
    if not isinstance(claims, list) or not 1 <= len(claims) <= MAX_CLAIMS:
        raise ValueError(f"Send 1 to {MAX_CLAIMS} claims to review.")
    rows = await be.get(stg.key(project, "runs", snapshot)) or []
    answers = text_answers(rows)
    selected = {c.get("answer_id") for c in claims if isinstance(c, dict) and isinstance(c.get("answer_id"), str)}
    text = await load_text(be, {ref: row for ref, row in answers.items() if ref in selected})
    current = await read_claims(be, project, snapshot, answers)
    merged = {(c["answer_id"], c["quote"]): c for c in current}
    for claim in claims:
        if not isinstance(claim, dict):
            raise ValueError("Each claim needs an answer ID, exact quote and verdict.")
        ref = field(claim, "answer_id", 64, True)
        quote = field(claim, "quote", 600, True)
        answer = answers.get(ref)
        if not answer or quote not in text.get(ref, ""):
            raise ValueError("The quote must match wording in the selected saved answer. Open the round to review it.")
        verdict = field(claim, "verdict", 10, True)
        if verdict not in VERDICTS:
            raise ValueError("The verdict must be true, false or unverified.")
        source_url = clean_source(field(claim, "source_url", 1000))
        evidence = field(claim, "evidence", 600)
        if verdict != "unverified" and not (source_url and evidence):
            raise ValueError("True and false verdicts need a source link and a short evidence excerpt.")
        merged[ref, quote] = {"answer_id": ref, "quote": quote, "verdict": verdict,
                              "source_url": source_url, "evidence": evidence, "reviewed_on": today}
    if len(merged) > MAX_CLAIMS:
        raise ValueError(f"This round already has the limit of {MAX_CLAIMS} reviewed claims.")
    store = await be.private_store()
    await store.set(stg.key(project, "facts", snapshot), list(merged.values()))
    return len(merged)


async def review_page(be, data: dict, snapshot: str, offset: int) -> dict:
    if snapshot not in data["meta"]["snapshots"]:
        raise ValueError("Choose a saved round to review.")
    if type(offset) is not int or offset < 0:
        raise ValueError("Send the next_offset from the previous answer page, or 0 to start.")
    rows = [r for r in data["runs"] if r["snapshot"] == snapshot]
    answers = text_answers(rows)
    page = dict(list(answers.items())[offset:offset + PAGE_SIZE])
    text = await load_text(be, page)
    displayed = {ref: row for ref, row in page.items() if ref in text}
    questions = {q["prompt_id"]: q["prompt"] for q in data["panel"]}
    claims = await read_claims(be, data["slug"], snapshot, displayed)
    missing = len(rows) - len(answers) + len(page) - len(displayed)
    return {"snapshot": snapshot, "missing_text": missing, "answers_with_text": len(rows) - missing,
            "answers": [{"answer_id": ref, "question": questions.get(r["prompt_id"]), "engine": r["platform"],
                         "text": text[ref], "truncated": bool(r.get("answer_truncated"))}
                        for ref, r in displayed.items()],
            "claims": claims, "next_offset": offset + PAGE_SIZE if offset + PAGE_SIZE < len(answers) else None,
            "note": REVIEW_NOTE}


async def summary(be, data: dict, snapshot: str) -> dict:
    rows = [r for r in data["runs"] if r["snapshot"] == snapshot]
    answers = text_answers(rows)
    claims = await read_claims(be, data["slug"], snapshot, answers)
    counts = Counter(c["verdict"] for c in claims)
    return {"snapshot": snapshot, "answers_with_text": len(answers), "missing_text": len(rows) - len(answers),
            **{v: counts[v] for v in VERDICTS}, "note": REVIEW_NOTE}
