---
name: competitor-research
description: SEO competitor research — find the real SERP competitors, compare authority, traffic and backlinks, mine keyword and content gaps, spot weak pages you can outrank, and turn them into a page plan. Use when the user asks who their competitors are, competitor analysis, keyword gap, content gap, backlink gap, "what are competitors ranking for", or keyword research.
argument-hint: "<your domain> [competitor domains...] [country]"
---

# Competitor research

Tools: Apify Actors per `../../references/tools-and-apis.md` (run protocol: quote → cap → run → report cost). Log paid calls in `ledger.json`.

## 1. Identify real competitors (by SERP, not by opinion)
- Take 5–15 money keywords (from `context.md`, the homepage/money pages, or the user's GSC export).
- Pull SERPs for each with `khadinakbar/scrape-google-serp` ($0.0018/page); count which domains recur in the top 10 → SERP competitors. Separate **business competitors** (sell the same thing) from **content competitors** (publishers, directories, marketplaces, Reddit, listicles) — the latter are link/mention targets, not rivals.
- Keep 3–5 business competitors (merge with the user's list).

## 2. Snapshot table
For you + each competitor: referring domains and backlink summary (`khadinakbar/website-backlink-checker`, `mode: summary`), how many of the tracked SERPs each ranks in and at what positions, top pages by traffic, page types that win (BoFu landing pages, comparison pages, tools/templates, blog), AI-visibility hints (are they named in AI answers? see `ai-search-visibility`). Label all third-party traffic numbers as estimates.

## 3. Keyword and content gaps
- Expand the topic set with `khadinakbar/dataforseo-keyword-research` (`mode: keyword_ideas`, 1–10 `seedKeywords` per run, ≤50 rows per run; $0.20 per request + $0.01/row, so batch seeds into one run); add `mode: search_volume` ($1.00 per request + $0.01/row) for specific phrases and `khadinakbar/google-trends-scraper` for seasonality.
- Gap = keywords where competitors appear in the SERP top 10 and you don't (from the SERP scrapes) or where you have no matching page.
- Classify intent from the SERP (page types ranking) and the phrasing — prioritise "best X for Y", "X vs Y", "X alternatives", "X pricing/cost", "service + city", templates/tools.
- **Weak-page mining** (high-yield): for each candidate keyword, inspect the ranking URLs. A ranking page is *weak* if it has 0–3 referring domains, the keyword missing from its title/H1/slug, a broad/accidental page type, or stale/thin content. Weak top-10 results = keywords you can win with one dedicated, intent-matched page.
- Cluster keywords sharing a SERP (>50–70% top-10 URL overlap = one page; otherwise separate pages).

## 4. Backlink gap
- Diff referring domains (`website-backlink-checker`, `mode: referring_domains`, ≤100 rows per competitor): domains linking to ≥2 competitors but not you. Classify: directory/listing (claim now), review site, listicle/roundup (pitch inclusion), publisher/editorial (digital PR), partner/integration, community. Output feeds `link-building`.

## 5. Outputs
- `seo-workspace/<domain>/competitors.md`: competitor table, what each does well, the 3 strategic gaps to exploit.
- `seo-workspace/<domain>/keyword-opportunities.csv`: `keyword,volume,kd,intent,ranking_url,weak_page_reason,proposed_page`.
- A page plan: top 10 pages to create or upgrade, each with target keyword cluster, page type (per SERP), title/H1 draft using `Keyword | benefit | Brand`, and internal links to add.

## Rules
- Pages compete, not domains: always reason at page level.
- Don't propose mass templated pages (doorways / scaled content abuse). Each proposed page needs a real reason to exist.
- Competitor data is research only; never contact competitors or copy their content.
