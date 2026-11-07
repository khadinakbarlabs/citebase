# AI-search (GEO / AEO) checklist

**Evidence grades used in every checklist:** A = controlled test or large dataset · B = practitioner consensus or one study with a clear method · C = anecdote or vendor-reported figure. Numbers below without a grade are B at best: treat as direction, not fact.

**Core model (most-supported view across the transcripts):** LLM answers are assembled from web search results. ChatGPT, Perplexity, Claude, Gemini and AI Overviews rewrite a prompt into several search queries ("query fan-out", ~9–11 on average, up to 28; deep research ran 420), read the top results, and synthesise. So **AI visibility ≈ ranking for the fan-out queries + being mentioned consistently on the pages those queries return.** How much AI citations overlap with Google's top 10 is disputed: studies report very different levels (one 2025 study near 76% for AI Overviews, others far lower), they count different things, and it shifts over time. Read it as "ranking helps, it is not sufficient". (C) Dissent: one study found only ~16% of prompts trigger retrieval; ~14–33% of citations come from outside the top 100. Do both: rank the fan-outs **and** build off-site consensus.

**Keep expectations honest:** AI referrals are ~0.25–1% of site traffic for most sites (ChatGPT ≈0.62% of Google organic across 100 sites / 145M sessions); citations ≠ clicks (37,000 Bing citations vs ~300 clicks in one case). ChatGPT sends 8–9× more referrals than the next AI platform; don't weight Perplexity equally.

## 1. Measure first (prompt panel)
- Build **25–75 prompts** across funnel stages: awareness ("how to…"), consideration ("best X for Y", "X vs Y", "X alternatives", "cost of X in [city]"), brand ("is [brand] good", "[brand] pricing", "[brand] reviews"). Informational prompts rarely name brands — weight commercial ones.
- Run each prompt **≥3 times per engine** (answers repeat back-to-back only ~40% of the time; 10–20 runs for stable averages) across ChatGPT, Google AI Overviews / AI Mode, Perplexity, Gemini, Claude, Copilot.
- Record per run: brand mentioned, position in answer, linked, sentiment, cited URLs + domains, and **whether the cited passage recommends the brand** (a citation alone isn't enough).
- Metrics: mention rate %, citation rate %, share of voice vs 3–5 competitors, cited-domain table, sentiment (<60–65/100 needs work). Repeat monthly; ~20% prompt win rate a few months in is a good early result.
- Tools: user's Apify actors `khadinakbar/ai-search-visibility-tracker`, `khadinakbar/llm-visibility-tracker`, `khadinakbar/google-ai-overviews-scraper`, `khadinakbar/ai-overviews-tracker`, `khadinakbar/ai-search-brand-monitor`, `khadinakbar/ai-citations-tracker`, `khadinakbar/google-ai-mode-scraper`; Bing Webmaster Tools AI Performance (Copilot citations + grounding queries); GA4 AI-referrer regex `chatgpt\.com|perplexity|gemini\.google|copilot\.microsoft|claude\.ai|deepseek`.

## 2. Fan-out optimisation (highest leverage)
- **Capture fan-outs** per target prompt: Bing WMT grounding queries; ChatGPT web UI → DevTools → Network → conversation response → `queries`; Perplexity shows its searches; Claude shows them in visible reasoning. Typical rewrites add the year, "reviews", "alternatives", "evaluate", `site:g2.com` / `capterra`.
- **Check Google + Bing rank** for each fan-out (goal: top 10–20).
- **Align pages**: fan-out phrasing in title, H1, natural-language slug, an H2 and the first sentence. Titles closer to fan-outs were cited more than titles closer to the raw prompt; natural-language slugs 89.8% vs 81.1% citation rate. Create a page or H2 chunk when no page fits.
- Fan-outs drift (every few days; Gemini most) — recheck monthly.

## 3. Page types and format that get cited
- **"Best X" listicles** ≈44% of ChatGPT-cited page types (26k-URL study); 79% updated within the year, 26% in the last 2 months; 35% on low-authority domains → get onto third-party lists (`checklist-offpage.md` §C5); keep your comparison content fresh with the current year.
- **"X vs Y" pages** on a landing-page template with a comparison table near the top — clients with the most versus pages had the most AI traffic (Siege Media). One page per pair, no templated text, real price comparisons.
- **Brand fact pages**: pricing, implementation time, integrations, limitations, an official FAQ. AI engines invent prices when vendors hide them and repeat the vendor's own statement once published (official FAQ cited in 84% of ChatGPT answers in one manipulation test).
- **Answer-first sections**: each H2 opens with a direct ~50-word answer readable out of context; concrete numbers; tables. Statistics (+33–37%), quotations (+22–41%) and cited sources (+40%) lifted GEO visibility in studies — but most GEO numbers are bundled changes; treat as readability best practice.
- **Freshness**: visible updated date; refresh key pages every 3–6 months. AI-cited content is ~25.7% fresher than organic; ChatGPT cites URLs ~458 days newer than Google's.
- **Word count doesn't matter** (0.04 correlation over 174k pages).

## 4. Off-site consensus (mentions > links for AI)
- Branded mentions correlate 0.664 with AIO visibility; mentions on highly linked pages ~0.7; YouTube mentions 0.737 with ChatGPT visibility (Ahrefs, 75k brands).
- Be present where engines look for the category: G2/Capterra/Trustpilot (correct categorisation), YouTube (long factual descriptions, comparison tables, testimonials), Reddit threads that already rank (helpful answers only), niche listicles, podcasts, Wikidata/Crunchbase where legitimate.
- **Local**: ChatGPT leans on Yelp/Angi/Thumbtack and vertical directories rather than GBP; AI Mode leans on GBP; reviews naming services drive "Ask Maps"; GBP-synced LocalBusiness schema +34 pts in one study; the three engines disagree on the #1 local pick 91% of the time.
- **Press releases** stating the exact category claim can be repeated by AI Overviews within 24–72 h — verifiable facts only; decays in weeks.

## 5. Technical prerequisites
- Answer bots not blocked: Googlebot, Bingbot, OAI-SearchBot, ChatGPT-User, PerplexityBot, Perplexity-User, Claude-SearchBot, Claude-User, in robots.txt **and** Cloudflare/CDN bot settings. Training-only bots (GPTBot, ClaudeBot, Google-Extended, CCBot, Applebot-Extended) are your choice and have no effect on being cited.
- Google states that AI Overviews and AI Mode need no special markup or files: a page must be indexable and snippet-eligible. `nosnippet`, `data-nosnippet`, `max-snippet:0` or `noindex` (often set site-wide by an SEO plugin or theme) take it out. (Google's own documentation.)
- Content in server-rendered HTML (ChatGPT's crawler doesn't run JS).
- Indexed in **Bing** (Bing WMT + IndexNow) as well as Google.
- Private pages use `noindex` (robots.txt alone leaked Claude shared chats into search).
- `llms.txt`: optional, no proven effect (no LLM bot requested it across 1,000 domains in 30 days of CDN logs). Never prioritise it.
- Schema: hygiene for rich results/entity clarity; controlled tests show no reliable AI-citation lift. Never promise one.

## 6. Reputation and accuracy
- Ask each engine what it says about the brand (pricing, features, complaints, "is it legit"). For each wrong/negative claim: find the source page, fix your own pages first, publish a clear response/FAQ, reply in the source thread where appropriate, request corrections from publishers.
- Map the top 10–20 URLs for brand-name queries; AI Overviews now summarise negative sentiment on brand queries.
- Watch for poisoning: fake third-party pages or "Summarize with AI" prompt-injection links about the brand.

## 7. Don't
Scaled AI pages targeting fan-outs (Google names it scaled content abuse; 85–95% visibility losses reported), mass self-promotional "best X" lists ranking yourself #1 (reported cited less, rising demotion risk; C), date refreshes without real updates, fake Reddit threads/upvotes, fabricated press releases, cloaking markdown to AI bots.
