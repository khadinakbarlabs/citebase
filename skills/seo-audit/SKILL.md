---
name: seo-audit
description: Full SEO audit of a website — technical, on-page, content, backlinks/off-page, competitors, local and AI-search (GEO) visibility — with evidence, a health score and a prioritised fix plan. Use when the user asks to audit, analyze, check or diagnose a site's SEO, rankings, traffic drop or AI visibility.
argument-hint: "<site URL> [max pages]"
---

# Full SEO audit

Input: `$ARGUMENTS` (URL, optional page limit; default 50, max 500). Workspace: `seo-workspace/<domain>/` (see `start`). Load `context.md` if present.

## Step 1 — Crawl (deterministic, always)
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/site_audit.py" "<url>" --max-pages 50 --out "seo-workspace/<domain>/audit.json"
```
It prints pass/warn/fail checks for technical, on-page and AI-search readiness, a weighted health score and sub-scores per area. It blocks private/local addresses (pass `--allow-private` only for the user's own dev server). If "Content present in server HTML (heuristic)" is flagged, say so first and confirm with `curl` or view-source: neither this crawl nor `khadinakbar/complete-seo-audit` ($0.10, an extra server-HTML audit) runs JavaScript, so use a real browser to read the rendered content for the on-page review.

## Step 2 — Parallel specialist research
Launch these plugin agents in one message (independent work), passing the domain, workspace path and context:
- `technical-auditor` — interprets `audit.json`, adds Lighthouse/CWV, indexability, rendering, redirect and duplicate analysis.
- `backlink-analyst` — profile, anchors, toxic risk, lost links, gap vs top 3 competitors.
- `competitor-analyst` — real SERP competitors, keyword gap, weak-page opportunities, content gaps.
- `geo-analyst` — prompt panel across AI engines, fan-outs, cited domains, brand accuracy. For a trackable baseline hand off to `citation-loop` instead of a one-off sample.
If a paid data source is unavailable, the agent reports what it could do with free methods and what is missing.

## Step 3 — On-page review (you)
For the homepage and the top 5–10 money pages (from context, sitemap or traffic), check every `[agent]` item in `../../references/checklist-onpage.md`: keyword in the four relevance slots, title formula, intent vs SERP page type (look at the live SERP for the target keyword), above-the-fold answer/CTA, trust cues, cannibalisation, internal links, freshness. Quote the actual title/H1/first sentence as evidence.

## Step 4 — Local (only if the business serves an area)
Run the local checklist at the end of `../../references/checklist-technical.md` (GBP category, Core 30, reviews, grid) by hand with the user's Business Profile access; for the geo-grid use `khadinakbar/local-rank-tracker` ($0.06 per local check).

## Step 5 — Synthesize `report.md`
1. **Executive summary**: health score (from `audit.json`), 5 biggest problems, 5 biggest opportunities, one-paragraph strategy.
2. **Findings by area** (Technical · On-page · Content · Off-page/backlinks · Competitors · AI search · Local): each finding = issue, evidence (URL, value, data source), impact, fix, evidence grade, how to verify.
3. **Competitor snapshot** table (DR/authority, referring domains, organic keywords/traffic estimate, content types that win).
4. **AI-visibility snapshot**: mention/citation rate by engine, top cited domains, wrong facts.
5. **30/60/90-day plan** prioritised per `start` §2, with cost estimates for paid items (links, PR).
6. **What I couldn't check** and which access would close the gap (GSC, GA4, Bing WMT exports; Apify sign-in).
Then generate tailored checklists via the `seo-checklists` skill.

## Rules
- Never claim a ranking factor the references grade C as fact; label disputed items (meta descriptions, schema for AI, llms.txt, multiple H1s, nofollow value) as disputed.
- Don't recommend schema/llms.txt as AI-visibility fixes. Don't recommend disavow without a manual action.
- Match any traffic drop to the Google update timeline before diagnosing (`checklist-technical.md` § Diagnosing drops).
- Read-only: don't change the site or contact anyone during an audit.
