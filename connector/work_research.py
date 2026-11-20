"""Project-scoped evidence and reviewed search-volume collection."""
from collections import defaultdict
from datetime import date
import asyncio
import json
import re
from urllib.parse import urlsplit

import history
import insights
import importer
import storage
import tools
import work_actions as work
from work_focus import source_url

ACTOR = "khadinakbar/dataforseo-keyword-research"
SERP = "khadinakbar/scrape-google-serp"
AI_ACTOR = "khadinakbar/ai-search-brand-monitor"
RANKED = "khadinakbar/ahrefs-alternative"
TRAFFIC = "khadinakbar/similarweb-traffic-rank-scraper"
MARKETS = {"us": (2840, "United States"), "gb": (2826, "United Kingdom"), "ca": (2124, "Canada"), "au": (2036, "Australia"), "de": (2276, "Germany"), "fr": (2250, "France"), "in": (2356, "India")}
FIELDS = {
    "keywords": ("term", "search_volume"),
    "competitors": ("name", "domain", "estimated_organic_traffic"),
    "pages": ("term", "domain", "url", "position", "estimated_traffic"),
    "ai": ("term", "engine", "brand", "mentions", "answers", "position"),
    "citations": ("term", "engine", "url"),
}
NUMBERS = {"search_volume", "estimated_organic_traffic", "estimated_traffic", "position", "mentions", "answers"}
ENGINES = {"chatgpt": "ChatGPT", "claude": "Claude", "gemini": "Gemini"}


def label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 500 or any(ord(c) < 32 for c in value):
        raise ValueError("Supply a short text label.")
    return value.strip()


def rows(kind, values, source, day):
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError("Import up to 100 rows per section.")
    result = []
    for item in values:
        if not isinstance(item, dict):
            raise ValueError("Each evidence row must be an object.")
        work.valid_keys(item, (*FIELDS[kind], "country", "language", "evidence_url", *(("recommended",) if kind == "ai" else ())))
        row = {}
        for key in FIELDS[kind]:
            value = item.get(key)
            if value is None and (key == "position" and kind == "ai" or key == "estimated_traffic"):
                row[key] = None
            elif key in NUMBERS:
                if type(value) not in (int, float) or not 0 <= value <= 10**15 or (key in {"position", "mentions", "answers", "search_volume"} and int(value) != value) or (key in {"position", "answers"} and value < 1):
                    raise ValueError(f"Invalid {key}.")
                row[key] = value
            else:
                row[key] = label(value)
        if "url" in row and not source_url(row["url"]):
            raise ValueError("Supply a public evidence URL.")
        if "domain" in row:
            domain = row["domain"].lower()
            if not re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,63}", domain):
                raise ValueError("Supply a domain without a path.")
            row["domain"] = domain
            if "url" in row and (urlsplit(row["url"]).hostname or "").removeprefix("www.") != domain.removeprefix("www."):
                raise ValueError("Ranked URL must belong to the supplied domain.")
        if "engine" in row:
            engine = ENGINES.get(row["engine"].lower())
            if not engine:
                raise ValueError("Choose ChatGPT, Claude or Gemini.")
            row["engine"] = engine
        if kind == "ai" and row["mentions"] > row["answers"]:
            raise ValueError("Mentioned answers exceed sampled answers.")
        for field in ("country", "language"):
            if field in item:
                row[field] = label(item[field]).lower()
                if not re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", row[field]):
                    raise ValueError("Use a country or language code for market context.")
        if "evidence_url" in item:
            row["evidence_url"] = source_url(item["evidence_url"])
            if not row["evidence_url"]:
                raise ValueError("Use a public evidence link.")
        if kind == "ai" and "recommended" in item:
            count = item["recommended"]
            if type(count) is not int or not 0 <= count <= row["mentions"]:
                raise ValueError("Recommended answers must be within the mentioned answer count.")
            row["recommended"] = count
        result.append({**row, "source": source, "observed_at": day, "provenance": "user_imported"})
    return result


def numbered_recommendations(text, names):
    """Accept contiguous, explicitly recommended list entries headed by a tracked brand."""
    if not isinstance(text, str):
        return {}
    lines = text[:12000].splitlines()
    headings = [i for i, line in enumerate(lines) if re.fullmatch(
        r"(?:my |our |the )?(?:ranked recommendations|recommendations in order|recommended options in order|top recommendations)[: ]*",
        line.strip().strip("#* ").casefold())]
    if len(headings) != 1:
        return {}
    output = {}
    count = 0
    aliases = {name.casefold(): name for name in names if isinstance(name, str) and name.strip()}
    for raw in lines[headings[0] + 1:]:
        line = raw.strip()
        if not line:
            continue
        match = re.fullmatch(r"(\d{1,2})[.)]\s+(.+)", line)
        if not match:
            break
        count += 1
        if int(match[1]) != count:
            return {}
        quoted_title = re.split(r"\s+[—–-]\s+|:\s+|\s+\(", match[2], maxsplit=1)[0].strip()
        title = quoted_title.replace("**", "").rstrip(".")
        name = aliases.get(title.casefold())
        if name:
            if name in output:
                return {}
            output[name] = (count, line[:line.index(match[2]) + len(quoted_title)][:180])
    return output if count >= 2 else {}


def ranked_cell(answers, name, names):
    samples = []
    for row in answers:
        ranks = row.get("_ranked_labels") or numbered_recommendations(row.get("answer_text"), names)
        if name in ranks:
            position, evidence = ranks[name]
            samples.append((position, evidence))
    return {"position": sum(p for p, _ in samples) / len(samples) if samples else None,
            "position_samples": len(samples), "position_evidence": list(dict.fromkeys(line for _, line in samples))[:10]}


def report(project, record):
    out = {k: list(record.get(k, [])) for k in FIELDS}
    prompts = {p["prompt_id"]: p["prompt"] for p in project["panel"]}
    brand = project["meta"].get("brand") or {}
    cells = defaultdict(list)
    imported = {(r.get("dataset_id"), r["term"], r["engine"]) for r in out["ai"]
                if r.get("provenance") == "verified_actor_run" and r.get("dataset_id")}
    snapshots = {}
    for r in project["runs"]:
        engine = ENGINES.get(str(r.get("platform")).lower())
        term = prompts.get(r.get("prompt_id"))
        if engine and term:
            dataset = r.get("source_dataset_id")
            identity = (dataset, term, engine)
            if dataset and (identity in imported or snapshots.setdefault(identity, r.get("snapshot")) != r.get("snapshot")):
                continue
            cells[term, engine, r.get("date"), r.get("snapshot")].append(r)
    for (term, engine, day, snapshot), answers in cells.items():
        common = dict(term=term, engine=engine, observed_at=day, snapshot=snapshot, source="Saved project answers", provenance="project_history")
        common["dataset_ids"] = sorted({r["source_dataset_id"] for r in answers if r.get("source_dataset_id")})
        name = brand.get("name")
        names = [name, *brand.get("competitors", [])]
        out["ai"].append(dict(common, brand=name, answers=len(answers), mentions=sum(insights._truthy(r.get("mentioned")) for r in answers),
                              recommended=sum(insights._truthy(r.get("recommended")) for r in answers), **ranked_cell(answers, name, names)))
        for rival in brand.get("competitors", []):
            tracked = [r for r in answers if rival.casefold() in insights._items(r.get("monitored_competitors"))]
            positives = [r for r in answers if rival.casefold() in insights._items(r.get("competitors"))]
            rank = ranked_cell(answers, rival, names)
            if tracked or positives or rank["position_samples"]:
                known = len(tracked) == len(answers)
                out["ai"].append(dict(common, brand=rival, answers=len(answers) if known else None,
                                      mentions=len(positives) if known or positives else None,
                                      coverage_known=known, **rank))
        for url in sorted({url for r in answers for url in r.get("cited_urls", []) if source_url(url)}):
            out["citations"].append(dict(common, url=url))
    for snapshot in project.get("ranks", []):
        for rank in snapshot.get("rows", []):
            url = source_url(rank.get("url"))
            if url and rank.get("position"):
                out["pages"].append(dict(term=rank["keyword"], domain=urlsplit(url).hostname,
                                         url=url, position=rank["position"], estimated_traffic=None,
                                         observed_at=snapshot["date"], source="Saved search rank",
                                         country=rank.get("country"), engine=rank.get("engine"),
                                         provenance="project_history"))
    onboarding = project.get("onboarding") or {}
    chosen = [r["term"] for r in onboarding.get("terms", []) if r.get("selected")] if onboarding.get("stage") == "research" else []
    return {**out, "first_party": project.get("first_party", {"gsc": None, "ga4": None}), "revision": record.get("revision", 0), "coverage": {k: len(v) for k,v in out.items()},
            "terms": chosen or list(dict.fromkeys(p.get("topic") or p["prompt"] for p in project["panel"])), "rivals": brand.get("competitors", []),
            "market": tools.search_context(project["meta"].get("settings")),
            "brand": brand, "questions": list(prompts.values()),
            "provisional_terms": [r["term"] for r in onboarding.get("terms", []) if r.get("selected")] if onboarding.get("stage") != "research" else [],
            "rival_domains": {r["domain"]: r["name"] for r in onboarding.get("competitors", []) if onboarding.get("competitors_confirmed", onboarding.get("stage") in ("terms", "research")) and r.get("selected") and r.get("domain")} or
                            {n: n for n in brand.get("competitors", []) if isinstance(n, str) and re.fullmatch(r"[a-z0-9.-]+\.[a-z]{2,}", n)},
            "metric_notes": {"estimated_traffic": "Estimated organic search visits for this ranked page and query.", "position": "AI history averages explicit numbered recommendation list positions across ranked samples. Unranked answers have no position.", "search_volume": "Estimated monthly searches in the source market."}}


def plan(view):
    market = view["market"]
    country, language = market["country"], market["language"]
    geo = MARKETS.get(country)
    jobs = []

    def add(job, count, inputs, purpose, source):
        quote = tools.quote_cost([{"job": job, "units": count, "requests": 1}])
        if quote["run_caps"]:
            cap = quote["run_caps"][0]
            jobs.append(dict(actor=cap["actor"], input=inputs, maxTotalChargeUsd=cap["max_cost_per_run_usd"],
                             platform_usage_separate=tools.job_pricing(job, date.today())["usage_paid_by_caller"],
                             purpose=purpose, source=source))
    for kind, job in (("keywords", "keyword_volume"), ("pages", "serp_page")):
        measured = {r["term"].casefold() for r in view[kind] if r.get("country", country) == country and r.get("language", language) == language}
        available = view["terms"] or (view["provisional_terms"] if job == "serp_page" else [])
        terms = [t for t in available if t.casefold() not in measured and len(t) <= 200][:10]
        if not terms:
            continue
        if job == "keyword_volume" and geo:
            add(job, len(terms), {"mode": "search_volume", "seedKeywords": terms, "locationCode": geo[0], "languageCode": language}, "Estimate monthly searches", "DataForSEO Google Ads")
        if job == "serp_page":
            add(job, len(terms), {"queries": terms, "maxResultsPages": 1, "countryCode": country.upper(), "languageCode": language}, "Discover ranking domains for provisional terms" if not view["terms"] else "Measure organic ranking pages and positions", "Google organic results")
    measured_domains = {r["domain"] for r in view["competitors"] if r.get("country", country) == country and r.get("language", language) == language}
    domains = [d for d in view["rival_domains"] if d not in measured_domains][:5]
    if domains and geo:
        add("traffic_rank", len(domains), {"domains": domains, "mode": "free_tier", "countryName": geo[1], "languageCode": language, "includeSimilarweb": False}, "Estimate monthly competitor organic search traffic", "DataForSEO organic estimated traffic volume")
    measured_pages = {r["target"] for r in view["pages"] if r.get("actor") == RANKED and r.get("country") == country and r.get("language") == language and r.get("target")}
    if geo and "domain_ranked_keywords" in tools.PRICES["jobs"]:
        for domain in [d for d in view["rival_domains"] if d not in measured_pages][:5]:
            add("domain_ranked_keywords", 10, {"mode": "organic_keywords", "target": domain, "locationName": geo[1], "languageCode": language, "maxResults": 10}, f"Find ranking pages, keywords, and estimated organic visits for {domain}", "DataForSEO ranked keywords")
    brand = view["brand"]
    if brand.get("name") and view["questions"]:
        observed = {(r["term"], r["engine"], r["brand"]) for r in view["ai"] if r.get("answers") and r.get("coverage_known", True)}
        for engine, display in ENGINES.items():
            pending = [q for q in view["questions"] if any((q, display, name) not in observed for name in [brand["name"], *view["rivals"]])][:10]
            if pending:
                inp = {"brandName": brand["name"], "brandDomain": tools._brand_domain(brand), "competitors": list(view["rivals"]),
                       "platforms": [engine], "customQueries": pending, "querySelectionMode": "custom_only", "maxQueriesPerPlatform": len(pending)}
                if brand.get("aliases"):
                    inp["brandAliases"] = brand["aliases"]
                add("ai_brand_check", len(pending), inp, f"Measure brand and competitor mentions on {display}", display)
    return {"jobs": jobs, "terms": view["terms"], "rivals": view["rivals"]}


def match_job(view, actual):
    """Reconstruct the reviewed scope even if another import filled some cells first."""
    if not isinstance(actual, dict):
        return None
    scope = {**view, **{k: [] for k in FIELDS}}
    for field, collection, limit in (("queries", "terms", 10), ("seedKeywords", "terms", 10),
                                    ("domains", "rival_domains", 5),
                                    ("customQueries", "questions", 10)):
        if field not in actual:
            continue
        selected = actual[field]
        allowed = view[collection] or (view["provisional_terms"] if field == "queries" else [])
        if (not isinstance(selected, list) or not 1 <= len(selected) <= limit or
                not all(isinstance(x, str) and x in allowed for x in selected) or len(set(selected)) != len(selected)):
            return None
        scope[collection] = {d: view[collection][d] for d in selected} if collection == "rival_domains" else selected
    if actual.get("mode") == "organic_keywords":
        domain = actual.get("target")
        if not isinstance(domain, str) or domain not in view["rival_domains"]:
            return None
        scope["rival_domains"] = {domain: view["rival_domains"][domain]}
    return next((j for j in plan(scope)["jobs"] if j["input"] == actual), None)


async def run_rows(be, run_id, view):
    if not re.fullmatch(r"[a-zA-Z0-9]{17}", label(run_id)) or not hasattr(be, "selection"):
        raise ValueError("Choose a completed run owned by this account.")
    client, owner = be.selection.caller, be.selection.owner
    run = await client.run(run_id).get()
    if not run or run.id != run_id or run.user_id != owner or run.status != "SUCCEEDED":
        raise ValueError("Choose a successful account-owned research run.")
    record = await client.key_value_store(run.default_key_value_store_id).get_record("INPUT")
    actual = (record or {}).get("value")
    job = match_job(view, actual)
    if not job:
        raise ValueError("Run inputs differ from this project's collection plan.")
    actor = await client.actor(job["actor"].replace("/", "~")).get()
    if not actor or run.act_id != actor.id:
        raise ValueError("Run Actor differs from the reviewed project plan.")
    ds = client.dataset(run.default_dataset_id)
    info = await ds.get()
    if not info or info.user_id != owner or getattr(info, "act_run_id", run_id) not in (None, run_id) or info.id != run.default_dataset_id or not 1 <= info.item_count <= 10:
        raise ValueError("Dataset does not match the completed run.")
    data = await ds.list_items(limit=11)
    day = run.finished_at.date().isoformat()
    market = view["market"]
    if job["actor"] == AI_ACTOR:
        engine = actual["platforms"][0]
        if any(importer.platform_of(x) != engine or importer.first_text(x, importer.QUERY_KEYS) not in actual["customQueries"] or type(x.get("brand_mentioned")) is not bool for x in data.items):
            raise ValueError("AI answers differ from the reviewed questions or engine.")
        by_question = {importer.first_text(item, importer.QUERY_KEYS): item for item in data.items}
        if len(by_question) != len(data.items):
            raise ValueError("AI dataset returned duplicate answers for a single-engine measurement.")
        panel = [{"prompt": q, "prompt_id": str(i)} for i, q in enumerate(actual["customQueries"])]
        converted = importer.convert(data.items, panel, run_id, brand=view["brand"])["runs"]
        for row in converted:
            row["date"] = row.get("date") or day
            raw = by_question[actual["customQueries"][int(row["prompt_id"])]]
            if isinstance(raw.get("competitor_mentions"), list):
                row["monitored_competitors"] = actual.get("competitors", [])
        evidence = report({"panel": panel, "runs": converted, "meta": {"brand": view["brand"]}}, {})
        return {k: [dict(row, provenance="verified_actor_run", actor=job["actor"], source=job["source"], run_id=run_id, dataset_id=info.id) for row in evidence[k]] for k in ("ai", "citations")}
    output = []
    for item in data.items:
        if job["actor"] == ACTOR:
            kind = "keywords"
            if item.get("keyword") not in actual["seedKeywords"] or item.get("locationCode") != actual["locationCode"] or item.get("languageCode") != actual["languageCode"]:
                raise ValueError("Keyword evidence differs from the reviewed terms or market.")
            if item.get("searchVolume") is not None:
                output.append(dict(term=item["keyword"], search_volume=item["searchVolume"]))
        elif job["actor"] == SERP:
            kind = "pages"
            term = item.get("search_query")
            if term not in actual["queries"] or str(item.get("country_code")).upper() != actual["countryCode"] or item.get("language_code") != actual["languageCode"]:
                raise ValueError("Rank evidence differs from the reviewed terms or market.")
            for ranked in item.get("organic_results", [])[:10]:
                url = source_url(ranked.get("url"))
                if url:
                    output.append(dict(term=term, url=url, position=ranked.get("position"), domain=urlsplit(url).hostname))
        elif job["actor"] == RANKED:
            kind = "pages"
            if item.get("target") != actual["target"] or item.get("locationName") != actual["locationName"] or item.get("languageCode") != actual["languageCode"] or item.get("mode") != "organic_keywords":
                raise ValueError("Ranked keyword report differs from the reviewed rival or market.")
            url = source_url(item.get("rankingUrl"))
            domain = urlsplit(url).hostname if url else None
            if domain and not (domain == actual["target"] or domain.endswith("." + actual["target"])):
                raise ValueError("Ranking URL does not belong to the reviewed competitor.")
            if domain and item.get("rank") and item.get("keyword"):
                output.append(dict(term=item["keyword"], domain=domain, url=url, position=item["rank"], estimated_traffic=item.get("estimatedTraffic")))
        else:
            kind = "competitors"
            domain = item.get("domain")
            if domain not in actual["domains"] or item.get("countryName") != actual["countryName"] or item.get("languageCode") != actual["languageCode"]:
                raise ValueError("Domain evidence differs from the reviewed rivals or market.")
            if item.get("status") == "OK" and item.get("organicEtv") is not None:
                output.append(dict(domain=domain, name=view["rival_domains"][domain], estimated_organic_traffic=item["organicEtv"]))
    if not output:
        raise ValueError("Dataset has no usable measurements.")
    cleaned = rows(kind, output, job["source"], day)
    return {kind: [dict(r, provenance="verified_actor_run", run_id=run_id, actor=job["actor"], target=actual.get("target"), dataset_id=info.id, country=market["country"], language=market["language"]) for r in cleaned]}


async def first_party_signal(be, slug, site, service):
    """Read the latest matching site snapshot among 32 recent periods, or a manual-only export."""
    name = "Google Search Console" if service == "gsc" else "Google Analytics 4"
    prefix = storage.key(slug, "google", service) + "."
    keys = sorted(await be.keys(prefix), reverse=True)
    for key in keys[:32]:
        record = await be.get(key)
        if not isinstance(record, dict) or not site or record.get("website") != site or record.get("service") != service:
            continue
        if record.get("source") != name or key != prefix + str(record.get("end_date")):
            continue
        if not isinstance(record.get("property"), str) or not isinstance(record.get("rows"), list):
            continue
        fields = ("service", "website", "property", "observed_at", "start_date", "end_date", "source")
        metrics = ("term", "clicks", "impressions", "position") if service == "gsc" else ("source", "sessions")
        return {**{field: record.get(field) for field in fields}, "provenance": "google_sync",
                "rows": [{k: row.get(k) for k in metrics} for row in record["rows"] if isinstance(row, dict)]}
    if keys:
        # Native sync also writes a legacy mirror without the site. Its origin cannot
        # be distinguished from a manual upload after the project changes websites.
        return None
    kind = "search" if service == "gsc" else "traffic"
    keys = sorted(await be.keys(storage.key(slug, "signal", kind) + "."))
    if not keys:
        return None
    record = await be.get(keys[-1])
    if not isinstance(record, dict):
        return None
    result = {"service": service, "source": "Saved project export", "provenance": "user_imported",
              "observed_at": record.get("date"), "property": None, "website": None,
              "start_date": None, "end_date": None, "rows": []}
    if service == "ga4":
        result.update(all_visits=record.get("all_visits"), ai_visits=record.get("ai_visits"))
    else:
        result.update(clicks=record.get("clicks"), impressions=record.get("impressions"))
        queries = {}
        for row in [*record.get("top_questions", []), *record.get("gaps", [])]:
            if row.get("query"):
                queries[row["query"]] = {"term": row["query"], **{k: row.get(k) for k in ("clicks", "impressions", "position")}}
        result["rows"] = list(queries.values())
    return result


async def historical_ranks(content, private):
    if not private:
        return
    by_record = defaultdict(list)
    for row in content["runs"]:
        ref, record = row.get("answer_ref"), row.get("answer_record")
        if not isinstance(ref, str) or not re.fullmatch("[a-f0-9]{64}", ref) or not isinstance(record, str):
            continue
        prefix = storage.key(content["slug"], "answers", str(row.get("snapshot"))) + "."
        if record.startswith(prefix) and re.fullmatch("[a-f0-9]{64}", record[len(prefix):]):
            by_record[record].append((ref, row))
    brand = content["meta"].get("brand") or {}
    names = [brand.get("name"), *brand.get("competitors", [])]
    for record, refs in by_record.items():
        texts = await private.get(record)
        if isinstance(texts, dict):
            for ref, row in refs:
                row["_ranked_labels"] = numbered_recommendations(texts.get(ref), names)


async def execute(project, operation, data):
    slug = storage.clean_slug(project)
    be = await storage.get_backend()
    async with history.lock_for(slug):
        content = await history.load_project(slug)
        write = operation == "research_import"
        private = await be.private_store() if write else await be.existing_private_store()
        content["runs"] = [dict(row) for row in content["runs"]]
        await historical_ranks(content, private)
        mutation = work.tag(json.dumps([operation, data], sort_keys=True))
        store = await work.RevisionStore.open(be, private, mutation) if private is not None else None
        key = work.prefix(be, slug) + ".research"
        current = await store.get(key) if store else None
        content["onboarding"] = await store.get(work.prefix(be, slug) + ".onboarding") if store else None
        rank_keys = sorted(await be.keys(storage.key(slug, "signal", "ranks") + "."))
        content["ranks"] = [await be.get(rank_keys[-1])] if rank_keys else []
        brand = content["meta"].get("brand") or {}
        site = brand.get("site") or brand.get("domain")
        services = ("gsc", "ga4")
        signals = await asyncio.gather(*(first_party_signal(be, slug, site, service) for service in services))
        content["first_party"] = dict(zip(services, signals))
        view = report(content, current or {})
        if not write:
            work.valid_keys(data, ())
            if operation == "research_plan":
                return plan(view)
            if operation != "research_get":
                raise ValueError("Unknown research operation.")
            return view
        if "run_id" in data:
            work.valid_keys(data, ("run_id", "expected_revision"))
            if not re.fullmatch(r"[A-Za-z0-9]{17}", label(data["run_id"])):
                raise ValueError("Choose a valid completed run.")
            # This elected record is inside the signed-in account's project store.
            # Export imports cannot supply provenance, Actor, dataset or run IDs.
            if any(r.get("run_id") == data["run_id"] and r.get("dataset_id") and
                   r.get("actor") in (ACTOR, RANKED, SERP, TRAFFIC, AI_ACTOR) and
                   r.get("provenance") == "verified_actor_run"
                   for k in FIELDS for r in (current or {}).get(k, [])):
                return view
        receipt = await store.replay(key, data)
        if receipt:
            return report(content, receipt)
        work.validate_revision(data, view["revision"])
        if "run_id" in data:
            added = await run_rows(be, data["run_id"], view)
        else:
            work.valid_keys(data, (*FIELDS, "expected_revision", "source", "observed_at"))
            source = label(data.get("source"))
            day = date.fromisoformat(label(data.get("observed_at")))
            if day > date.today():
                raise ValueError("Observation date is in the future.")
            added = {k: rows(k,data[k], source, day.isoformat()) for k in FIELDS if k in data}
        if not any(added.values()):
            raise ValueError("Supply at least one evidence row.")
        updated = {k: list((current or {}).get(k, [])) for k in FIELDS}
        for k, values in added.items():
            updated[k].extend(r for r in values if r not in updated[k])
        if sum(map(len, updated.values())) > 1500:
            raise ValueError("Project research storage is full.")
        updated["revision"] = view["revision"] + 1
        await store.set(key, updated)
        return report(content, updated)
