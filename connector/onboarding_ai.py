"""Score project keyword candidates against the website using a bundled English embedding model."""
import asyncio
from functools import lru_cache
import logging
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import fact_checks

MODEL = "minishlab/potion-base-2M"
logger = logging.getLogger("citebase")


@lru_cache(maxsize=1)
def _model():
    directory = Path(os.environ.get("CITEBASE_ONBOARDING_MODEL_DIR") or Path(__file__).with_name("onboarding-model"))
    if not (directory / "model.safetensors").is_file():
        return None
    from model2vec import StaticModel
    return StaticModel.from_pretrained(str(directory))


def _similarities(context, terms):
    try:
        model = _model()
        if model is None:
            return None
        vectors = model.encode([*context, *terms], normalize=True, max_length=192, use_multiprocessing=False)
        return (vectors[len(context):] @ vectors[:len(context)].T).max(axis=1).tolist()
    except (ImportError, ValueError, OSError, RuntimeError):
        logger.warning("Website keyword relevance model unavailable.")
        return None


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 for c in value):
        return ""
    return " ".join(value.split())


def _domain(url):
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _public_reference(value):
    if not isinstance(value, str) or len(value) > 500:
        return ""
    try:
        if not fact_checks.clean_source(value):
            return ""
        host = _domain(value)
        if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,63}", host) or host.endswith((".internal", ".local", ".localhost")):
            return ""
        return value
    except ValueError:
        return ""


def _candidate_rows(existing, proposals, key, evidence):
    rows = {row[key].casefold(): dict(row) for row in existing}
    if proposals is None:
        return list(rows.values())
    if not isinstance(proposals, list) or len(proposals) > 20:
        raise ValueError("Supply at most 20 suggestions with a public source link.")
    for item in proposals:
        if not isinstance(item, dict):
            raise ValueError("Each suggestion needs a name or search term and its public source link.")
        name = _text(item.get(key), 160)
        url = _public_reference(item.get("url") or item.get("source_url"))
        if not name or not url:
            continue
        row = {key: name, "url": url, "source": "assistant", "reason": "Proposed by your assistant from a linked source.", "selected": False}
        if key == "name":
            own = _domain(evidence["website"] if "://" in evidence["website"] else "https://" + evidence["website"])
            supplied = _text(item.get("domain"), 253).lower().removeprefix("www.")
            if supplied and not _public_reference("https://" + supplied):
                supplied = ""
            if name.casefold() == str(evidence.get("brand", "")).casefold() or own in {supplied, name.casefold()}:
                continue
            row["domain"] = supplied
        rows.setdefault(name.casefold(), row)
    return list(rows.values())[:40]


async def review(project, evidence, suggestions):
    terms = _candidate_rows(evidence["terms"], suggestions.get("terms"), "term", evidence)
    competitors = _candidate_rows(evidence["competitors"], suggestions.get("competitors"), "name", evidence)
    context = []
    for page in evidence.get("pages", [])[:3]:
        for snippet in [page.get("title", ""), page.get("description", ""), *page.get("h1", [])]:
            if isinstance(snippet, str) and snippet.strip():
                context.append(" ".join(snippet.split())[:700])
    language = str(evidence.get("language") or "en").lower().replace("_", "-")
    scores = None
    if terms and context and (language == "english" or language.split("-")[0] == "en"):
        scores = await asyncio.to_thread(_similarities, context, [row["term"] for row in terms])
    if scores is not None:
        # Compare with observed page topics. Scores describe semantic fit, not search volume.
        best = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        def relevant(index):
            row = terms[index]
            if scores[index] >= 0.40:
                return True
            phrase = r"(?<!\w)" + re.escape(row["term"].casefold()) + r"(?!\w)"
            site_match = row.get("source") == "website" and any(re.search(phrase, snippet.casefold()) for snippet in context)
            return scores[index] >= 0.25 and site_match
        recommended = set([i for i in best if relevant(i)][:8])
        terms = [{**row, "ai_checked": True, "model": MODEL, "recommended": i in recommended,
                  "relevance": round(scores[i], 3)} for i, row in enumerate(terms)]
    else:
        terms = [{**row, "ai_checked": False, "recommended": False} for row in terms]
    return {"terms": terms, "competitors": competitors}
