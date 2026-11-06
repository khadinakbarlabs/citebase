---
name: link-building
description: Backlink analysis and link building — audit the backlink profile, find competitor link gaps and AI-cited link targets, discover and vet prospects (resource pages, listicles, guest-post guidelines, directories, broken links, unlinked mentions), and hand them to outreach. Use for backlinks, link building, guest posts, link insertions, link gap, toxic links, "get more links", or link prospecting.
argument-hint: "<domain> [audit|prospect] [topics...]"
---

# Link building

Read `../../references/checklist-offpage.md` (criteria, tactics, never-do list) and the run protocol in `../../references/tools-and-apis.md` (quote → cap → run → report cost).

## 1. Profile audit (always first)
- `khadinakbar/website-backlink-checker`: `mode: summary` for the client and the top 3 competitors, then `referring_domains` and `anchors` for the client (`maxResults` ≤100; ≈$0.05/request + $0.01/row). Or delegate to the `backlink-analyst` agent.
- Compare referring domains, anchor mix and dofollow share to the competitors. Flag over-optimised exact-match anchors, bursts, toxic neighbourhoods, and backlinks pointing at 404/redirected URLs (reclaim with 301s).
- Disavow only if there is a manual action.

## 2. Build the opportunity list (`seo-workspace/<domain>/prospects.csv`)
Columns: `domain,url,type,source,dr,traffic,relevance,contact,email,verified,status`. Sources, in order of value:
1. **Free / owned**: unlinked brand mentions (SERP: `"[brand]" -site:[domain]`), partners, suppliers, integrations, clients, associations, awards; broken links pointing at the client's old URLs.
2. **Competitor gap**: referring domains linking to ≥2 competitors but not the client (diff the `referring_domains` reports) — directories and review sites first, then editorial.
3. **AI-cited pages** from `ai-search-visibility` (listicles, roundups, comparison pages) → inclusion requests.
4. **Prospect discovery**: `khadinakbar/backlink-opportunity-finder` — `keywords` (3–10 topics), `targetDomain` (client), `excludeDomains` (competitors, marketplaces), `opportunityTypes` (resource pages, guest-post guidelines, listicles, directories…), `countryCode`, `maxResultsPerKeyword` (default 25), `minimumRelevanceScore`; $0.006 per saved prospect. Quote first (e.g. 5 topics × 20 = 100 prospects ≈ $0.60).
5. **Custom footprints** via `khadinakbar/scrape-google-serp` when needed: `"[topic]" "write for us"`, `intitle:"best [category]"`, `"[topic]" inurl:resources`, `inurl:sponsors [city]`, `"[competitor]" review -site:[competitor]`.
6. **Broken-link building**: run `khadinakbar/broken-link-checker` ($0.001/link) on the best resource pages; each dead outbound link relevant to a client page = a replacement pitch.
De-duplicate by domain; drop domains already linking to the client.

## 3. Vet every candidate (no exceptions)
Pass all: real organic traffic with no recent cliff, traffic in the target country, topical relevance to the page you'd link, the page indexed (`site:` check) and not crowded with outbound links, not a link farm / sell-to-anyone site, sensible price if paid. Record the reason in `relevance`. A smaller relevant site beats a big irrelevant one.

## 4. Act
- **Outreach links** (`type` = listicle / resource / broken-link / unlinked-mention / competitor-gap / guest-post): set `status=to_contact` and hand to the `outreach` skill (templates in `../../references/outreach-playbook.md`). Contacts come from `khadinakbar/bulk-website-contact-extractor` and are verified with `khadinakbar/email-address-validator` there.
- **Claimable listings** (directories, review sites, partner pages): list the exact URL and the fields to submit; the user (or a browser session they supervise) completes them.
- **Paid placements**: if the user buys guest posts or link insertions from a vendor, vet each site with §3 first, keep exact-match anchors ≤10% of the profile, link the most relevant page (not always the homepage), use `rel="sponsored"` where the publisher allows, and get explicit approval of item, price and total before any order.
- For guest posts, draft the article to the publisher's guidelines: genuinely useful, original, one contextual link, brand mention, no AI slop.
- Log every placement in `seo-workspace/<domain>/offpage-log.csv`: `date,type,vendor,target_url,live_url,anchor,cost_usd,status`.

## 5. Verify and maintain
Fetch each live URL: confirm the link exists, its `rel`, anchor and target; check the page is indexed after ~2 weeks; re-check monthly and log lost links. Pace: steady monthly cadence sized to the site (a 10-page new site ≈5 links in month 1), never bursts to one page.

## Never
PBNs, link farms, expired-domain redirect schemes, hacked/parasite placements, link exchanges at scale, comment/forum spam, automated directory bots. Flag these if found in the profile.
