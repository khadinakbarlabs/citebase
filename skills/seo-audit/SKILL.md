---
name: seo-audit
description: Full SEO audit of a website — technical, on-page, content, backlinks/off-page, competitors, local and AI-search (GEO) visibility — with evidence, a health score and a prioritised fix plan. Use when the user asks to audit, analyze, check or diagnose a site's SEO, rankings, traffic drop or AI visibility.
argument-hint: "<site URL> [max pages]"
---

# Full SEO audit

Talk like `../../references/plain-language.md`: plain words, and end each step with Done / Cost so far / Next, asking for one yes.

Input: `$ARGUMENTS` (URL, optional page limit; default 50, max 500). Workspace: `seo-workspace/<domain>/` (see `start`). Load `context.md` if present.

**Paid checks:** the crawl in Step 1 is not paid. Everything else that uses an Apify Actor is. Before any paid run, say it is a paid check billed to the user's own Apify account and wait for a clear yes. Do not state an amount; give it only if the user asks what that task costs (then call `quote_cost` and tell them). Always call `quote_cost` anyway to get the spending cap for each run, and set it without comment.

## Web connector mode
Call `audit_site` (not `site_audit.py`), then `next_steps` with that audit. Paid extras (packs `local`, `competitors`, `ai_check`): say it is paid → yes → `quote_cost` for the caps → `call-actor`. Keep findings in chat; offer `save_results` / `make_report` under a project name. Skip agent launches that need local workspace files.

## Step 1 — Crawl (deterministic, always)
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/site_audit.py" "<url>" --max-pages 50 --out "seo-workspace/<domain>/audit.json"
```
On the web, call `audit_site` with the URL instead. It prints pass/warn/fail checks for technical, on-page and AI-search readiness, a weighted health score and sub-scores per area. It blocks private/local addresses (pass `--allow-private` only for the user's own dev server). If "Content present in server HTML (heuristic)" is flagged, say so first and confirm with `curl` or view-source: neither this crawl nor `khadinakbar/complete-seo-audit` (a paid extra server-HTML audit) runs JavaScript, so use a real browser to read the rendered content for the on-page review.

## Step 2 — Parallel specialist research
**Get the yes first. Helper agents never spend on their own.**
1. Tell the user, in one short message, which parts of the full audit are paid checks (backlinks, competitor and keyword data, the AI check) and that they are billed to their own Apify account. Ask which ones they want. Wait for a clear yes.
2. For each part the user approved, get the per-run caps (`quote_cost` on the web; the run protocol in `../../references/tools-and-apis.md` in Claude Code).
3. Pass each agent only its approved caps. An agent with no approved cap uses unpaid methods (the crawl, public pages, the user's own exports) and must not start a paid run.
4. For the AI part, the question list must be approved by the user before it is asked. The first run is repeat 1 of the baseline (see `citation-loop`), so its answers are kept.

Then launch these plugin agents in one message (independent work), passing the domain, workspace path, context and approved caps:
- `technical-auditor` — interprets `audit.json`, adds Lighthouse/CWV, indexability, rendering, redirect and duplicate analysis.
- `backlink-analyst` — profile, anchors, toxic risk, lost links, gap vs top 3 competitors.
- `competitor-analyst` — real SERP competitors, keyword gap, weak-page opportunities, content gaps.
- `geo-analyst` — the approved question list across AI engines (ChatGPT and Google first), fan-outs, cited domains, brand accuracy. For a trackable baseline hand off to `citation-loop` instead of a one-off sample.
If a paid check was not approved or is unavailable, the agent reports what it could do with unpaid methods and what is missing.

## Step 3 — On-page review (you)
For the homepage and the top 5–10 money pages (from context, sitemap or traffic), check every `[agent]` item in `../../references/checklist-onpage.md`: keyword in the four relevance slots, title formula, intent vs SERP page type (look at the live SERP for the target keyword), above-the-fold answer/CTA, trust cues, cannibalisation, internal links, freshness. Quote the actual title/H1/first sentence as evidence.

## Step 4 — Local (only if the business serves an area)
On the web, `quote_cost` with `pack: "local"` covers map ranking and the local results pack (paid; ask first).
Run the local checklist at the end of `../../references/checklist-technical.md` (GBP category, Core 30, reviews, grid) by hand with the user's Business Profile access; for the geo-grid use `khadinakbar/local-rank-tracker` (paid; ask first).

## Step 5 — Synthesize `report.md`
1. **Executive summary**: health score (from `audit.json`), 5 biggest problems, 5 biggest opportunities, one-paragraph strategy.
2. **Findings by area** (Technical · On-page · Content · Off-page/backlinks · Competitors · AI search · Local): each finding = issue, evidence (URL, value, data source), impact, fix, evidence grade, how to verify.
3. **Competitor snapshot** table (DR/authority, referring domains, organic keywords/traffic estimate, content types that win).
4. **AI-visibility snapshot**: mention/citation rate by engine, top cited domains, wrong facts.
5. **30/60/90-day plan** prioritised per `start` §2, marking which items need a paid check or outside spend (links, PR), without amounts.
6. **What I couldn't check** and which access would close the gap (GSC, GA4, Bing WMT exports; Apify sign-in).
Then generate tailored checklists via the `seo-checklists` skill.

## Step 6 — Say it simply and keep it
- Start the answer with a three-line summary a non-expert can act on: the score in words ("needs work"), the top three fixes with who does each and how long, and what to check again in 30 days. Follow `../../references/plain-language.md`.
- Group fixes into **Do first** (blockers), **Do soon** (clear wins) and **Later** (nice to have). At most five actions in the first message; the rest go in `report.md`.
- On the web connector, offer to save the check with `save_results` (including the `audit` result) under a project name so the score can be compared next month, and `make_report` for a page to share. In Claude Code, `report.md` and `audit.json` are the record.
- Offer a recurring re-check (`schedule_checks` on the web; monthly is enough for most sites). The user creates the schedule in their own Apify account and can turn it off any time.
- Always end with the re-check date.

## Rules
- Never claim a ranking factor the references grade C as fact; label disputed items (meta descriptions, schema for AI, llms.txt, multiple H1s, nofollow value) as disputed.
- Don't recommend schema/llms.txt as AI-visibility fixes. Don't recommend disavow without a manual action.
- Match any traffic drop to the Google update timeline before diagnosing (`checklist-technical.md` § Diagnosing drops). When a drop matches an update, say what Google stated, not what blogs infer, and label third-party explanations "unconfirmed".
- Read-only: don't change the site or contact anyone during an audit.
- Finish with the three-line footer (Done, Cost so far, Next).
