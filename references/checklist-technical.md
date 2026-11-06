# Technical SEO checklist (+ local)

`[auto]` = `scripts/site_audit.py` tests it. `[gsc]` = needs Google Search Console data (ask for an export or GSC access). `[agent]` = judgement. Evidence grades as in `checklist-onpage.md`.

## Crawl and access
- [auto] **robots.txt reachable, not over-broad.** `Disallow: /category` also blocks `/category-1` and `/category.html`.
- [auto] **Googlebot, Bingbot and AI crawlers allowed** (GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, PerplexityBot, Google-Extended). ~5.9% of 140M sites block GPTBot; Cloudflare's managed robots.txt / AI-bot toggle can add blocks silently — check the CDN settings too. (A)
- [auto] **Content in server HTML.** H1, body, internal links and reviews must exist without JavaScript. ChatGPT's crawler does not render JS; Google renders late; JS review widgets are invisible to LLMs. Fix: SSR/SSG/prerendering. (B)
- [agent] **Bing indexed + Bing Webmaster Tools + IndexNow.** ChatGPT search has used Bing's index and is reported to be building its own, so don't rely on Bing alone; Bing WMT's AI Performance report shows Copilot citations and grounding queries. (B)
- [agent] **LLM fetch test**: ask an LLM with browsing to fetch the URL and describe it; a wrong summary = retrievability problem. (B)

## Indexing
- [auto] **XML sitemap** reachable, referenced in robots.txt, listing canonical 200 URLs only. Helps discovery, not authority.
- [auto] **No accidental noindex** on 200 pages (staging leftovers, plugin checkbox); don't noindex nav category pages. (B)
- [gsc] **"Crawled – currently not indexed"** is usually a value/authority problem, not crawl budget: differentiate titles (`Keyword | benefit | Brand`), ≥5 internal links in/out (a $50k 15-site test fixed indexing at ≥5), depth ≤3, more authority; republish at a new URL if stuck. (B)
- [gsc] **Monitor every property variant** (Domain + URL-prefix, www/non-www, http/https): a hacked non-canonical www homepage got a site deindexed while the canonical looked fine. (C, cheap check)
- [agent] **Backlink-bearing pages indexed** — an unindexed backlink passes nothing.
- [agent] **Google's own timings** (Gary Illyes via SEJ): new URL discovered ~20 h; known URL refreshed ~1 month; title/snippet update 1–2 days; duplicate clustering ≤2 weeks; removals 2–24 h; manual-action review 1–2 weeks; core-update recovery 3–6 months (6–12 slowest). Set expectations with these. (A)

## URLs, redirects, status codes
- [auto] **HTTP → HTTPS**; **www/non-www consolidated**; one trailing-slash convention.
- [auto] **No redirect chains.** Permanent moves = 301 to the specific new URL (301s don't lose PageRank, Google 2016+); 302s for permanent moves leak value. (A)
- [auto] **Real 404/410** for removed content, never blanket-redirected to the homepage; 410 de-indexes ~2× faster. **Soft 404** (nonexistent URL returns 200) = fail. (A)
- [agent] **301 only URLs with links or traffic**; changing top URLs without 301s cost one site 70% of traffic. Reclaim equity from 404 pages that have backlinks ("best by links" report). (B)

## Canonicals and duplicates
- [auto] **Self-referencing canonical** on indexable pages; flag canonicals pointing elsewhere.
- [agent] **Product variants**: self-canonical variation URLs; generic product canonical → primary variation (+22% organic, SearchPilot; may not generalise). (A)
- [agent] **Near-duplicate city/service pages** (doorways): pages differing only by city/keyword, thin, hidden from nav. One HVAC site lost >80% of doorway pages and 63% traffic in 30 days after a core update. Add 10–20% genuinely local content or consolidate. (B)

## Performance and rendering
- [auto] **Server response <1.5 s**, HTML <500 KB (proxy checks).
- [agent] **Core Web Vitals** via PageSpeed Insights / CrUX. Speed is secondary to relevance for rankings (several experts) but matters for conversion — don't oversell it.
- [auto] **Mobile viewport**, `<html lang>`, hreflang where multilingual.

## Security and abuse monitoring
- [gsc] **Manual actions / security issues** empty.
- [agent] **Negative SEO watch**: exact-match anchor blasts, fake-lawyer AI DMCA emails demanding "credit" backlinks, DMCA abuse de-indexing pages; file counter-notices fast. Disavow only with a manual action (+80% sessions only in that case). (A/B)

## Structured data
- [auto] JSON-LD parses; entity schema exists. FAQ rich results were removed from Google Search on 7 May 2026 and more types deprecated in 2026. Marking up your own reviews violates guidelines; never add invented aggregate ratings. (A)

## Migrations
Freeze content ~1 month before; crawl before/after; preserve titles, canonicals, internal links and anchors; HTML sitemap; settle trailing slash; prioritise the 80/20 pages; re-check noindex after launch.

## Diagnosing drops: match the date to the update first
2025–26 updates targeted scaled content abuse (AI or programmatic), thin affiliate, site-reputation abuse (Cointelegraph ~4M → ~75k clicks/mo after casino directories), expired-domain abuse, keyword stuffing, doorway pages, self-promotional listicles; directories lost "near me" in the May 2026 core update. Spam-update phases in March and September 2026 (reported in the analysed videos; verify dates in Google's status page) target AI-written scaled pages. Google's "Preferred Sources" setting became a global signal on 1 May 2026 as reported: being a source people choose to follow helps. Spam updates can hit a whole domain and every site in one GSC account. Rank-tracker data is distorted since Google removed `num=100` and added `goto` redirects — use GSC as ground truth.

---

# Local SEO checklist (when the business serves an area)
1. **GBP primary category** = money keyword's category (Whitespark 2026 survey: #1 local factor; proximity #2). Fill secondary categories, ≥20 services, products.
2. **"Core 30" site**: homepage targets the primary category + city; one page (or ~50–70-word H2) per secondary category and core service.
3. **Title tags** = primary category + city (not "Home").
4. **Reviews**: ask every customer; request descriptive reviews; drip via CRM/payment events (~10 min after service); reply to 100% with name/brand/service/location. Recency (#11 factor) beats count; customer-written keywords matter; diversify to Yelp (Gemini and ChatGPT cite Yelp/Angi/Thumbtack — ChatGPT largely ignores GBP), Facebook, niche directories. No gating, no incentives.
5. **Geo-grid rank map** weekly at a fixed time; size so leaders show 60–90% top-3; track your top-3%.
6. **Real address** (sub-lease with signage OK; PO box/virtual office violates guidelines). Service areas don't expand radius; prominence and real locations do.
7. **Local links**: sponsorships (~$350–500, dofollow, ≥12 months), chambers ($100–300), local news, .edu sponsor tiers; close a ~10-link gap vs the top 3. Keep exact-match anchors to "five or so".
8. **GBP upkeep**: weekly 250–300-char post + image, ≥10 real photos + 1/month, holiday hours, change alerts. GBP landing page usually the homepage.
9. **City pages**: single-location sites with >20 city pages rarely rank; each needs unique local content.
10. **Competitor watch**: monthly competitor list; keyword-stuffed GBP names can be reported with evidence.
11. **NAP consistency**: low ranking weight now, but fix top directories (Apple Maps, Bing Places, Yelp).
12. **Skip geotagging photos** — no benefit in a 10-week Local Falcon study.
