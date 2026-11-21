"""Website-first setup backed by the signed-in project's elected private revisions."""
import asyncio
import json
import re
from urllib.parse import unquote, urlsplit

import history
import insights
import storage
import tools
import work_actions as work


def candidate(field, value, source, reason, **extra):
    row = {field: value, "source": source, "reason": reason, "selected": True, **extra}
    if field == "name":
        row.setdefault("domain", value if re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", value, re.I) else "")
    return row


def initial(meta, panel):
    brand = meta.get("brand", {})
    site = brand.get("site") or brand.get("domain") or ""
    return {"website": site, "brand": brand.get("name") or site, "revision": 0,
            "stage": "competitors" if site else "website",
            "competitors": [candidate("name", x, "project", "Saved project competitor.")
                            for x in brand.get("competitors", [])],
            "terms": [candidate("term", q.get("topic") or q["prompt"], "panel", "Saved tracking question.")
                      for q in panel], "questions": panel}


def site_pages(site):
    try:
        crawl = tools.sa.crawl(tools._clean_url(site), 3, 0.2, 12)
    except (ValueError, SystemExit, OSError):
        return []
    return [{"url": p["url"], "title": p.get("title", "")[:220],
             "keywords": p.get("meta_keywords", "")[:500], "h2": p.get("h2", [])[:8], "description": p.get("meta_description", "")[:480], "h1": p.get("h1", [])[:3]}
            for p in crawl["pages"] if (p.get("title") or p.get("h1"))
            and urlsplit(p.get("final_url") or p["url"]).hostname == urlsplit(crawl["origin"]).hostname]


def unique(rows, field):
    result = {}
    for row in rows:
        result.setdefault(row[field].casefold(), row)
    return list(result.values())[:20]


GENERIC = {"about us", "the organization", "our organization", "our company", "our products", "our services",
           "get started", "learn more", "read more", "contact us", "our work", "our mission", "what we do",
           "our team", "how it works", "latest news", "our story", "key features", "core functions",
           "upcoming events", "success stories", "frequently asked questions", "all products"}
MARKETING = re.compile(r"^(?:welcome|about|home|discover|explore|meet|introducing|unlock|experience|empower|"
                       r"see|schedule|book a|manage|transform|built for|designed for|your|we|our|start|try|get|shop all|find out|"
                       r"learn more|sign up|join|why choose|switch from|alternative to)\b|"
                       r"\b(?:you|your|ours|today|future|reimagined|redefined|revolutionary|world.class|"
                       r"next.generation|all.in.one|effortlessly|seamlessly)\b", re.I)
CATEGORY = {"product", "products", "category", "categories", "services", "solutions", "collections", "shop"}


def site_topics(page, brand):
    signals = []
    segments = [unquote(s) for s in urlsplit(page["url"]).path.strip("/").split("/")]
    if len(segments) > 1 and any(s.casefold() in CATEGORY for s in segments[:-1]):
        signals.append((segments[-1].replace("-", " ").replace("_", " "), "product or service URL"))
    desc = page.get("description", "")
    visible = " ".join([page["title"], *page.get("h1", []), *page.get("h2", []), desc]).casefold()
    for keyword in page.get("keywords", "").split(",")[:12]:
        if keyword.strip() and keyword.strip().casefold() in visible:
            signals.append((keyword.strip(), "metadata and visible page text"))
    # Extract named offerings embedded within an otherwise promotional description.
    for match in re.finditer(r"\b((?:website|technical SEO|security|accessibility|content|energy) audits?|"
                             r"(?:search engine|conversion rate) optimi[sz]ation)\b", desc, re.I):
        signals.append((match[1], "site description"))
    for match in re.finditer(r"\b(?:is (?:an?|the) |speciali[sz](?:e|es|ing) in|offers?|provides?|manufactures?|sells?)\s*"
                             r"(.{4,100}?)(?=[.,;:!]|\s+(?:for|in|with|that|which|designed|built|to help)\b|$)", desc, re.I):
        signals.extend((x.strip(), "site description") for x in re.split(r",| and ", match[1]))
    signals.extend((x, "page heading") for x in page.get("h1", []))
    signals.extend((x, "page title") for x in re.split(r"\s*[|–—]\s*|\s+-\s+", page["title"]))
    for phrase, source in signals:
        phrase = " ".join(phrase.split()).strip(" .")
        low = phrase.casefold()
        nonbrand = low.replace(brand.casefold(), "").strip() if brand else low
        if nonbrand in {"home", "homepage", "functions", "organization", "official site", "official website",
                        "dashboard", "console", "website", "project", "welcome", "introduction", "foundation", "overview"}:
            continue
        if (not 2 <= len(phrase.split()) <= 7 or len(phrase) > 75 or low in GENERIC or MARKETING.search(phrase)
                or re.search(r"[?!:;|]|\bvs\.? |\bversus\b", low)
                or low == brand.casefold() or low.removesuffix(" homepage") == brand.casefold()):
            continue
        yield candidate("term", phrase, "website", f"Named in the {source}.", url=page["url"])


def comparison_names(page, brand):
    # Compare landing pages frequently name a rival only in their path or subheading.
    segments = [unquote(x) for x in urlsplit(page["url"]).path.strip("/").split("/")]
    if len(segments) >= 2 and segments[-2].lower() in {"compare", "vs", "alternatives"}:
        name = segments[-1].replace("-", " ")
        if re.fullmatch(r"[\w ]{2,50}", name) and name.casefold() != brand.casefold():
            yield name
    for text in [page["title"], *page["h1"], *page.get("h2", []), page.get("description", "")]:
        for match in re.finditer(r"\b(?i:alternative to|switch from|migrate from|compare " +
                                 re.escape(brand) + r" (?:to|with))\s+([A-Z][A-Za-z0-9.+-]*"
                                 r"(?: [A-Z][A-Za-z0-9.+-]*){0,2})", text, flags=0):
            name = match.group(1).rstrip(".")
            if name.casefold() != brand.casefold():
                yield name


def preserve_choices(previous, refreshed, field):
    old = {row[field].casefold(): row for row in previous}
    merged = {row[field].casefold(): {**row, "selected": old.get(row[field].casefold(), {}).get("selected", False)}
              for row in refreshed}
    for key, row in old.items():
        merged.setdefault(key, row)
        if row.get("domain_confirmed"):
            merged[key].update(domain=row["domain"], domain_confirmed=True)
    return list(merged.values())


async def suggest(be, project, state, meta, data, store):
    import onboarding_ai
    from work_research import first_party_signal
    brand = meta.get("brand") or {}
    website = brand.get("site") or brand.get("domain") or ""
    prior = []
    for row in state["terms"]:
        if row.get("source") in {"search", "Google Search Console", "Saved project export"}:
            if state.get("terms_confirmed", state["stage"] == "research") and row.get("selected"):
                prior.append(candidate("term", row["term"], "user", "Previously selected for this project."))
        else:
            prior.append(row)
    state = {**state, "website": website, "brand": brand.get("name") or website, "terms": prior}
    pages = await asyncio.to_thread(site_pages, website)
    retained = [r for r in prior if r.get("source") != "website" or state.get("terms_confirmed")]
    rivals = list(state["competitors"])
    signal = await first_party_signal(be, project, website, "gsc") or {}
    queries = sorted(signal.get("rows", []), key=lambda row: row.get("impressions") or 0, reverse=True)
    terms = []
    for row in queries:
        term = row.get("term")
        if isinstance(term, str) and term.strip():
            metrics = {field: row[field] for field in ("impressions", "clicks", "position") if row.get(field) is not None}
            terms.append(candidate("term", term, signal["source"], "Observed in the project's Search Console report.",
                                   provenance=signal.get("provenance"), **metrics))
            if len(terms) == 12:
                break
    terms.extend(retained)
    rank_keys = await be.keys(storage.key(project, "signal", "ranks") + ".")
    ranks = await be.get(max(rank_keys)) if rank_keys else {}
    terms.extend(candidate("term", row["keyword"], "ranks", "Observed in the saved search position report.")
                 for row in ranks.get("rows", []) if row.get("keyword"))
    snapshots = meta.get("snapshots") or {}
    if snapshots:
        label = max(snapshots, key=lambda k: str(snapshots[k]))
        for row in await be.get(storage.key(project, "runs", label)) or []:
            citations = [(url, (urlsplit(url).hostname or "").removeprefix("www."))
                         for url in tools.safe_evidence_urls(row.get("cited_urls"))]
            for name in insights._items(row.get("competitors")):
                normalized = re.sub(r"[^a-z0-9]", "", name)
                proof = next(((url, host) for url, host in citations if name == host or
                              normalized == re.sub(r"[^a-z0-9]", "", host.split(".")[0])), None)
                rivals.append(candidate("name", name, "ai_answers", "Named in a saved AI answer.",
                                        **({"domain": proof[1], "url": proof[0]} if proof else {})))
    research = await store.get(work.prefix(be, project) + ".research") or {}
    own_host = (urlsplit(tools._clean_url(state["website"])).hostname or "").removeprefix("www.")
    for page in research.get("pages", [])[:100]:
        domain = page.get("domain", "").lower().removeprefix("www.")
        if domain and domain != own_host and not domain.endswith("." + own_host):
            rivals.append(candidate("name", domain, "saved_search_results",
                                    f"Search competitor for {page.get('term', '')}; verify it offers a competing product.",
                                    url=page.get("url"), position=page.get("position"), selected=False))
    for page in pages:
        rivals.extend(candidate("name", name, "website", "Named on a comparison or migration page.", url=page["url"])
                      for name in comparison_names(page, state["brand"]))
        for phrase in [*page["h1"], *re.split(r"\s+[|–—-]\s+", page["title"])]:
            phrase = " ".join(phrase.split())
            comparison = re.fullmatch(r"(.{1,80}?)\s+(?:vs\.?|versus)\s+(.{1,80}?)", phrase, re.I)
            if comparison:
                left, right = comparison.groups()
                brand = state["brand"].casefold()
                rival = right if left.casefold() == brand else left if right.casefold() == brand else ""
                if rival:
                    rivals.append(candidate("name", rival, "website", "Compared directly with the brand on its website.",
                                            url=page["url"]))
        terms.extend(site_topics(page, state["brand"]))
    evidence = {**state, "language": meta.get("settings", {}).get("language", "en"),
                "pages": pages, "terms": unique(terms, "term"), "competitors": unique(rivals, "name")}
    review = await onboarding_ai.review(project, evidence, data)
    reviewed = review.get("terms", evidence["terms"])
    if any(row.get("ai_checked") for row in reviewed):
        reviewed = [{**row, "selected": bool(row.get("recommended") or row.get("source") == "panel")}
                    for row in reviewed]
    competitors = review.get("competitors", evidence["competitors"])
    if state.get("competitors_confirmed", state["stage"] in ("terms", "research")):
        competitors = preserve_choices(state["competitors"], competitors, "name")
    if state.get("terms_confirmed", state["stage"] == "research"):
        reviewed = preserve_choices(state["terms"], reviewed, "term")
    questions = state["questions"] or review.get("questions") or [
        tracking_question(row["term"]) for row in reviewed if row.get("selected")]
    context = profile(pages, meta, website)
    ideas = question_ideas([r["term"] for r in reviewed if r.get("selected")],
                           [r["name"] for r in competitors if r.get("selected")], context)
    tracked = {q.get("prompt", "").casefold() for q in questions}
    return {**state, "terms": reviewed, "profile": context,
            "question_ideas": [q for q in ideas if q["prompt"].casefold() not in tracked],
            "competitors": competitors,
            "competitor_help": ("" if competitors else "No direct competitor was identified. Add a known rival or "
                                "ask your assistant for evidence from a public comparison. You can also preview "
                                "a Google results search to discover sites appearing for your terms."),
            "questions": questions,
            "pages_checked": len(pages)}


AUDIENCE_NOUNS = (r"businesses|companies|teams|startups|agencies|founders|freelancers|marketers|developers|engineers|"
                  r"retailers|restaurants|clinics|practices|schools|students|families|parents|homeowners|landlords|"
                  r"brands|creators|sellers|shops|stores|enterprises|nonprofits|organi[sz]ations|professionals|"
                  r"accountants|lawyers|recruiters|employers|employees|contractors|manufacturers|hotels|gyms")
AUDIENCE = re.compile(r"\bfor ((?:[a-z][\w&-]* ){0,3}(?:" + AUDIENCE_NOUNS + r"))\b", re.I)
COUNTRY_TLDS = {"uk": "United Kingdom", "us": "United States", "ca": "Canada", "au": "Australia", "de": "Germany",
                "fr": "France", "es": "Spain", "it": "Italy", "nl": "Netherlands", "ie": "Ireland", "in": "India",
                "nz": "New Zealand", "ae": "United Arab Emirates", "sg": "Singapore", "pk": "Pakistan", "br": "Brazil"}
COUNTRY_NAMES = re.compile(r"\b(?:in|across|throughout) (the (?:UK|US|USA|United States|United Kingdom)|Canada|Australia|"
                           r"Germany|France|Spain|Italy|Ireland|India|Europe|New Zealand|the UAE|Singapore|Pakistan|Brazil)\b")


def profile(pages, meta, website):
    """Product context read from the site's own pages. Every entry names the page it came from."""
    settings = meta.get("settings") or {}
    home = next((p for p in pages if urlsplit(p["url"]).path in ("", "/")), pages[0] if pages else None)
    summary = (home or {}).get("description") or ((home or {}).get("h1") or [""])[0]
    audiences, markets = {}, {}
    for page in pages:
        text = " ".join([page["title"], *page.get("h1", []), *page.get("h2", []), page.get("description", "")])
        for match in AUDIENCE.finditer(text):
            name = " ".join(match[1].split()).lower()
            if not MARKETING.search(name) and len(audiences) < 8:
                audiences.setdefault(name, {"name": name, "source": "website", "url": page["url"],
                                            "reason": "Named as a customer group on this page."})
        for match in COUNTRY_NAMES.finditer(text):
            name = match[1].removeprefix("the ")
            markets.setdefault(name.casefold(), {"name": name, "source": "website", "url": page["url"],
                                                 "reason": "Named as a place the business serves."})
    if settings.get("country"):
        markets.setdefault(str(settings["country"]).casefold(), {"name": settings["country"], "source": "project",
                                                                "reason": "Saved project country."})
    suffix = (urlsplit(tools._clean_url(website)).hostname or "").rsplit(".", 1)[-1] if website else ""
    if suffix in COUNTRY_TLDS:
        markets.setdefault(COUNTRY_TLDS[suffix].casefold(), {"name": COUNTRY_TLDS[suffix], "source": "domain",
                                                             "reason": f"The website uses the .{suffix} country domain."})
    return {"summary": " ".join(summary.split())[:300], "summary_url": (home or {}).get("url"),
            "audiences": list(audiences.values()), "markets": list(markets.values())[:6],
            "language": settings.get("language", "en")}


def question_ideas(terms, competitors, context):
    """Buyer questions built from the product context. None of them names the brand, so they measure discovery."""
    audiences = [a["name"] for a in context.get("audiences", [])][:2]
    market = next((m["name"] for m in context.get("markets", [])), "")
    article = "the " if re.match(r"(?:United|Netherlands|Philippines|UAE|UK|US\b)", market) else ""
    where = f" in {article}{market}" if market else ""
    ideas = []

    def add(prompt, kind, topic, reason):
        ideas.append({"prompt": prompt, "type": kind, "topic": topic, "reason": reason,
                      "prompt_id": "setup-" + work.tag(prompt)[:16]})
    for term in terms[:4]:
        add(f"What is the best {term}{where}?", "consideration", term, "A buyer comparing options for this search term.")
        for audience in audiences:
            add(f"Which {term} would you recommend for {audience}?", "consideration", term,
                f"A buyer from the {audience} group named on your site.")
    for term in terms[:2]:
        add(f"How do I choose the right {term}?", "awareness", term, "An early-stage buyer learning what matters.")
    for rival in competitors[:3]:
        add(f"What are the best alternatives to {rival}?", "consideration", rival,
            f"A buyer looking beyond {rival}, a competitor you selected.")
    return unique(ideas, "prompt")[:15]


MAX_QUESTIONS = 50


def edit_questions(questions, data):
    """Add or remove tracked questions. Reports compare only the questions both rounds share, so this stays fair."""
    work.valid_keys(data, ("revision", "add", "remove"))
    add, remove = data.get("add", []), data.get("remove", [])
    if (not isinstance(add, list) or not isinstance(remove, list) or not (add or remove)
            or len(add) > 20 or len(remove) > MAX_QUESTIONS):
        raise ValueError("Send up to 20 questions to add and the question IDs to remove.")
    known = {q["prompt_id"] for q in questions}
    if any(not isinstance(x, str) or x not in known for x in remove):
        raise ValueError("Remove questions by the exact question IDs in this project.")
    kept = [q for q in questions if q["prompt_id"] not in set(remove)]
    texts = {q["prompt"].casefold() for q in kept}
    for item in add:
        row = {"prompt": item} if isinstance(item, str) else item
        if not isinstance(row, dict):
            raise ValueError("Each added question needs its wording.")
        prompt, kind = row.get("prompt"), row.get("type", "consideration")
        if (not isinstance(prompt, str) or not 8 <= len(prompt.strip()) <= 300
                or kind not in ("awareness", "consideration", "brand", "control")):
            raise ValueError("Write each question in 8 to 300 characters, with type awareness, consideration, brand or control.")
        prompt = " ".join(prompt.split())
        if prompt.casefold() in texts:
            continue
        texts.add(prompt.casefold())
        topic = row.get("topic") if isinstance(row.get("topic"), str) else prompt
        kept.append({"prompt": prompt, "type": kind, "topic": topic[:160], "prompt_id": "q-" + work.tag(prompt)[:16]})
    if not kept:
        raise ValueError("Keep at least one tracked question.")
    if len(kept) > MAX_QUESTIONS:
        raise ValueError(f"Track up to {MAX_QUESTIONS} questions.")
    return kept


def tracking_question(term, wording=None):
    return {"topic": term, "prompt_id": "setup-" + work.tag(term)[:16], "type": "consideration",
            "prompt": wording or (term if term.endswith("?") else f"What should I look for when comparing {term}?")}


def apply_domains(rows, domains, site):
    if not isinstance(domains, dict) or len(domains) > 20:
        raise ValueError("Supply up to 20 confirmed competitor names and public domains.")
    selected = {row["name"] for row in rows if row.get("selected")}
    if any(key not in selected for key in domains):
        raise ValueError("Supply domains only for competitors selected by their exact names.")
    own = (urlsplit(tools._clean_url(site)).hostname or "").lower().removeprefix("www.")
    normalized = {}
    for name, value in domains.items():
        domain = value.lower().removeprefix("www.") if isinstance(value, str) else ""
        if (len(domain) > 253 or not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain)
                or domain.endswith((".invalid", ".localhost", ".local", ".internal", ".example", ".test", ".onion",
                                    ".home.arpa", ".arpa", ".lan", ".home", ".corp"))
                or domain in {"example.com", "example.net", "example.org"}
                or domain == own or domain.endswith("." + own) or own.endswith("." + domain)):
            raise ValueError("Enter the competitor's public domain without a protocol, path, port or credentials.")
        normalized[name] = domain
    return [{**row, "domain": normalized[row["name"]], "domain_confirmed": True} if row["name"] in normalized
            else row for row in rows]


def choose(state, data, panel):
    step = data.get("step")
    allowed = {"competitors": ("competitors",), "terms": ("terms", "competitors"),
               "research": ("terms", "competitors")}
    if step not in allowed.get(state["stage"], ()):
        raise ValueError("Reload the project and finish the current setup step.")
    fields = {"revision", "step", step, "use_recommended"}
    if step == "competitors":
        fields.add("competitor_domains")
    work.valid_keys(data, fields)
    field = "name" if step == "competitors" else "term"
    rows = state[step]
    if step in data:
        choices = data[step]
        if (data.get("use_recommended") or not isinstance(choices, list) or len(choices) > 20
                or any(not isinstance(x, str) or not x.strip() or len(x) > 160 for x in choices)):
            raise ValueError("Choose up to 20 names or terms, or use the recommended selection.")
        existing = {r[field].casefold(): r for r in rows}
        for value in choices:
            name = value.strip()
            existing.setdefault(name.casefold(), candidate(field, name, "user", "Added during project setup."))
        picked = {x.strip().casefold() for x in choices}
        rows = [{**row, "selected": k in picked} for k, row in existing.items()]
    elif data.get("use_recommended", True) is not True:
        raise ValueError("Select entries or use the recommended selection.")
    elif step == "terms" and data.get("use_recommended") and any(r.get("ai_checked") for r in rows):
        rows = [{**r, "selected": bool(r.get("recommended") or r.get("source") == "panel")} for r in rows]
    if "competitor_domains" in data:
        rows = apply_domains(rows, data["competitor_domains"], state["website"])
    selected = [r[field] for r in rows if r.get("selected")]
    result = {**state, step: rows, f"{step}_confirmed": True,
              "stage": "research" if step == "terms" or state["stage"] == "research" else "terms"}
    if step == "terms":
        if not selected:
            raise ValueError("Choose at least one term for research.")
        proposals = {q.get("topic", q.get("term")): q.get("prompt", q.get("question"))
                     for q in state.get("questions", []) if isinstance(q, dict)}
        questions = panel or (state["questions"] if state.get("questions_edited") and state.get("questions") else
                              [tracking_question(t, proposals.get(t)) for t in selected])
        result["questions"] = questions
        result["tracking_note"] = ("Search research uses the selected terms. AI tracking keeps the existing comparison questions." if panel
                                   else "The selected terms now form the project's AI tracking questions.")
    return result


async def project_choices(be, project, state):
    """Reapply elected choices after an interrupted write or lost response."""
    if state.get("competitors_revision"):
        names = [r["name"] for r in state["competitors"] if r.get("selected")]
        key = storage.key(project, "setup", "competitors", f"{state['competitors_revision']:012d}")
        await be.set(key, names)
    if state["stage"] == "research":
        baseline = await history.first_panel(be, project, state["questions"])
        return {**state, "questions": baseline}
    return state


async def publish_questions(be, project, panel, state):
    """After the edit is recorded, update the live list. Saved rounds keep their answers and
    comparisons use only the questions both rounds share. A retry reapplies the recorded list."""
    if panel and panel != state["questions"]:
        await be.set(storage.key(project, "panel"), state["questions"])
    return state


async def execute(project, operation, data):
    reading = operation == "onboarding_get"
    if reading:
        work.valid_keys(data, ())
    elif operation == "onboarding_suggest":
        work.valid_keys(data, ("revision", "terms", "competitors"))
    elif operation not in ("onboarding_save", "questions_update"):
        raise ValueError("Unknown setup operation.")
    be = await storage.get_backend()
    async with history.lock_for(project):
        meta = await history._require_project(project)
        panel = await be.get(storage.key(project, "panel")) or []
        private = await be.existing_private_store() if reading else await be.private_store()
        state = initial(meta, panel)
        if private is None:
            return state
        key = work.prefix(be, project) + ".onboarding"
        mutation = work.tag(json.dumps([operation, data], sort_keys=True))
        store = await work.RevisionStore.open(be, private, mutation)
        saved = await store.get(key)
        if saved:
            state = work.visible(saved)
        if panel:
            state["questions"] = panel
        if reading:
            return state
        revision = data.get("revision", state["revision"] if operation == "onboarding_suggest" else None)
        if type(revision) is not int:
            raise ValueError("Supply the project setup revision.")
        if saved and saved.get("_mutation") == mutation and revision in (state["revision"] - 1, state["revision"]):
            if operation == "questions_update":
                return await publish_questions(be, project, panel, {**state, "questions": saved["questions"]})
            if state.get("competitors_revision") or operation == "onboarding_save":
                return await project_choices(be, project, state)
            return state
        work.validate_revision({"expected_revision": revision}, state["revision"])
        if operation == "onboarding_suggest":
            if not state["website"]:
                raise ValueError("Save a website before refreshing project suggestions.")
            updated = await suggest(be, project, state, meta, data, store)
        elif operation == "questions_update":
            questions = edit_questions(panel or state.get("questions") or [], data)
            updated = {**state, "questions": questions, "questions_edited": True,
                       "question_ideas": [q for q in state.get("question_ideas", [])
                                          if q["prompt"].casefold() not in {x["prompt"].casefold() for x in questions}]}
        else:
            updated = choose(state, data, panel)
            if data["step"] == "competitors":
                updated["competitors_revision"] = revision + 1
        result = work.visible(await store.set(key, {**updated, "revision": revision + 1}))
        if operation == "questions_update":
            return await publish_questions(be, project, panel, result)
        if result.get("competitors_revision") or operation == "onboarding_save":
            return await project_choices(be, project, result)
        return result
