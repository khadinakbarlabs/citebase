# On-page SEO checklist

Distilled from ~600 SEO video transcripts (Build In Public / Edward Sturm show, Vasco SEO tips, 50 "AI SEO masterclass" videos incl. Ahrefs, Kyle Roof, Charles Floate, David Quaid, James Dooley, Lily Ray, Patrick Stox, SearchPilot tests, a 9,249-case-study meta study). Each item: **check → pass criterion → why / evidence**. `[auto]` = `site_audit.py` tests it; `[agent]` = the agent must judge it (SERP, GSC, reading the page).

Evidence grades: **A** controlled test or large dataset · **B** repeated practitioner consensus · **C** single anecdote / opinion. Never present C items as facts.

## 1. Relevance slots (highest leverage)
- [agent] **Target keyword in title, URL slug, H1 and first sentence.** Pass = all four; fail if 2+ missing. Competitors skipping these is what makes a keyword "easy". Kyle Roof: title, H1, body and URL are the placements that matter most; ~60% of LLM-written pages miss the keyword in title/H1. (B)
- [auto] **Title present and unique.**
- [agent] **Title formula `Keyword | benefit or searcher goal | Brand`**, keyword first, brand last. Flag titles that are only "Home" or the brand (>60% of 100+ local sites audited did this). (B)
- [agent] **Don't shorten titles by stripping synonyms**: removing synonyms cost −27% traffic; removing "compare" gained +24%; price in title −15%; emojis −6%; ALL CAPS +17.5% (test only). Long multi-variant titles can win; test, don't assume the 60-char rule. (A for listed tests, C for ultra-long titles)
- [auto] **Exactly one H1** (fail if none; warn if several — a Tripadvisor split test favoured two, so "test, not rule").
- [agent] **H1 = keyword + benefit** ("Roof replacement in Austin: installed in one day"), not "Premier Exterior Solutions". (B)
- [agent] **No keyword stuffing / keyword in every H2.** Vary naturally; Chewy repeated "dry dog food" 88× and its page fell 98k → 23k clicks/mo (correlation). (B)
- [auto] **Meta description present, 70–160 chars** — low priority: Google rewrites 60–70% of them; SearchPilot found auto snippets beat custom by ~3%. (A)
- [agent] **Descriptive slug** with the keyword; flag opaque slugs (`dry-food-294`).

## 2. Intent and page type
- [agent] **Page type matches the SERP's dominant type** (landing vs blog vs category vs tool vs listicle). Mismatch = pogo-sticking; leaked Google docs reference good/bad/last-longest clicks (NavBoost). (B)
- [agent] **Bottom-of-funnel first.** Prioritise "service + city", "X alternatives", "best X for Y", "X vs Y", "brand reviews", "cost of X", templates. One page per intent; don't stack money keywords on the homepage. HubSpot moved its blog down-funnel; Jotform template pages drive most of its 2.7M clicks/mo. (B)
- [agent] **Weak-page keyword mining**: find keywords where a big domain ranks with an *accidental* page (0–3 referring domains, keyword missing from title/H1/slug, thin or broad page) — a dedicated page can outrank it. (B)
- [agent] **Answer / offer above the fold**: TL;DR under the title (+33% conversions, reported), benefit H1, explanatory hero image, visible CTA, phone in nav for local. (B)
- [agent] **Core text visible, not hidden in tabs/accordions** (+12% organic sessions for visible text, SearchPilot). (A)
- [agent] **Trust cues near the top**: customer counts, logos, press, years, certifications, author, date, sources. Original photos over stock (stock cost ~19% conversions over 130k A/B tests). (B)
- [agent] **Buyer-intent FAQ** on conversion pages (objections, pricing, timelines) — as on-page content; FAQ rich results were removed from Google on 7 May 2026.

## 3. Content quality and effort
- [auto] **Thin content** under ~300 words on non-home pages → warn (context-dependent; BoFu pages ranking at ~415 words exist).
- [auto] **Content present in server HTML** (no JS needed) — AI crawlers don't execute JavaScript.
- [agent] **Information gain**: original data, tests, photos, methodology, first-hand experience. Google's Oct 2026 guidance: AI output (incl. titles, meta, alt text, structured data) must be human-reviewed. 2025–26 spam updates hit scaled, unreviewed AI content: AInvest ~9.5M → <8k clicks; ClickUp blog −97.6% in 15 months; WPBeginner 2.6M → ~27k. (A — observed cases)
- [agent] **No cannibalisation**: same query shows 2+ of your URLs in GSC, positions bounce (20↔80), or two pages share >70% of top-10 SERP URLs → merge into the winner (best position, most clicks over 90 days, most links), 301 the losers, update internal links. Don't fix with canonicals; no year-stamped duplicate URLs. (B)
- [agent] **Freshness**: visible updated date; refresh decaying pages. AI-cited content is ~25.7% fresher than organic results (Ahrefs); 79% of AI-cited "best X" lists were updated in the last year. (B)
- [auto] **Published/updated date + author byline on long content** (E-E-A-T; bylines also correlate with AI citation).
- [agent] **Index bloat**: pages with zero clicks/impressions for 12 months → improve, merge, or prune (one audit found ~90% of pages ranked for nothing). Pruning wins are anecdotal; prune carefully. (C)

## 4. GSC refresh loop (best effort-to-result ratio)
1. GSC → Pages → page → Queries; filter positions 3–20.
2. List queries the page ranks for but never uses verbatim → work them in (1–2 sentences or a new H2).
3. Rewrite title/intro where position ≤3 but CTR is low (pos 1 CTR ≈39.8% vs 18.7% at pos 2).
4. Add internal links from pages that already rank and get clicks.
5. If an easy-keyword page is stuck, republish at a new URL and 301 the old one (anecdotal).
6. Update date, request indexing, and log the change with a date so effects can be attributed.

## 5. Internal linking
- [auto] **Orphans / weak pages** (0 crawled inlinks) → link them; internal links to orphan posts moved pages up to +64 positions (meta study). (A)
- [auto] **Click depth ≤ 3**; money pages ≤ 2 clicks from home via hubs (/alternatives/, /locations/, /tools/). (B)
- [agent] **`site:domain "keyword"` method**: find your pages mentioning the target keyword and link them to the target with descriptive anchors. (B)
- [agent] **Authority relay**: link from ranking, clicked pages to the next target; small ranking pages feed the money page. (B)
- [agent] Link density is disputed (some sites run 30–50 internal links/page and rank). Don't fail a page on count.

## 6. Images and media
- [auto] **Alt text on meaningful images**; descriptive filenames (`service-city-descriptive.webp`, not `image_9283.jpg`); WebP/AVIF; image near related text. Keyword-alt image links beat text links in the Petrovic test; image backlinks correlated with AI visibility in a 35k-point Semrush/Indig study. (B)
- [auto] **Open Graph title + image** (sharing, Discover).
- [agent] Hero images must not push the answer below the fold on informational pages.

## 7. Structured data (hygiene, not a ranking lever)
- [auto] **Valid JSON-LD**; Organization/WebSite (or LocalBusiness/Person) entity schema sitewide.
- [agent] Product, Review (not self-reviews), Job, Article, Breadcrumb only where they unlock rich results competitors already earn.
- Evidence: Ahrefs found AI-cited pages ~3× likelier to have JSON-LD (correlation), but a controlled test of 1,885 pages adding JSON-LD vs ~4,000 controls showed no significant AI-citation lift; invented schema properties were read as plain text ("duck test"). One LocalBusiness study: ChatGPT +3 positions at 92% confidence, no effect elsewhere. **Never sell schema as an AI-visibility fix.** (A)

## 8. Conversion layer
- [agent] Clear CTA per page, simple path to lead/checkout, phone visible for local.
- [agent] Install Microsoft Clarity (free): rage/dead clicks, scroll depth (60–70% of visitors never scroll on many landing pages).
