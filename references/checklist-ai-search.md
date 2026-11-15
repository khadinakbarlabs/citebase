# AI-search (GEO / AEO) checklist

**Evidence grades used in every checklist:** A = controlled test or large dataset · B = practitioner consensus or one study with a clear method · C = anecdote or vendor-reported figure. A number appears below only when it has a named source and date. Advice with no number is practitioner consensus (B at best): treat it as direction, not fact.

**Core model (most-supported view):** LLM answers are assembled from web search results. ChatGPT, Perplexity, Claude, Gemini and AI Overviews rewrite a prompt into several related searches ("query fan-out"; the count varies by engine and question), read the top results, and synthesise. So **AI visibility ≈ ranking for the fan-out queries + being mentioned consistently on the pages those queries return.** Ranking in Google's top 10 helps but is not enough: Ahrefs' 2026 rerun (863,000 results pages, about 4 million AI Overview links) found about 38% of the pages cited in AI Overviews also rank in the top 10 for the same search, down from about 76% in its July 2025 study; about 31% rank outside the top 100 (https://news.designrush.com/ai-overview-citations-drop-ahrefs, checked November 2026, grade A, one tool's data). Other studies count differently and report other levels, and it shifts over time. Do both: rank the fan-outs **and** build off-site consensus.

**Keep expectations honest:** AI referrals are a small share of traffic for most sites, usually under 1%. SE Ranking put ChatGPT at about 0.3% of all website visits worldwide in May 2026 (https://seranking.com/blog/chatgpt-referral-traffic-may-2026/, grade B). A citation is not a click. ChatGPT sends about three quarters of all AI referral visits, with Gemini second and Perplexity third (SE Ranking 2026 study, https://seranking.com/blog/ai-traffic-research-study/, checked November 2026, grade B). So lead with ChatGPT and Google; do not weight Perplexity equally.

## 1. Measure first (prompt panel)
- Build **about 30 questions**: at least 20 buying questions (awareness "how to…"; consideration "best X for Y", "X vs Y", "X alternatives", "cost of X in [city]"), at least 5 control questions where the brand should not be recommended, and a few brand-name checks ("is [brand] good", "[brand] pricing", "[brand] reviews"). Group the buying questions into topics of 8 to 10. Informational prompts rarely name brands, so weight commercial ones. Full rules: `measurement.md`.
- Ask each buying question **3 times per assistant** for a baseline (answers differ run to run). The first check is repeat 1 of that baseline; brand-name and control questions need one repeat; Google AI Overviews and AI Mode give one answer per search.
- Engines that are measured: ChatGPT, Perplexity, Gemini, Claude, Google AI Overviews and Google AI Mode. Report ChatGPT and Google first, one line per engine; Perplexity is optional. Nothing here measures Copilot.
- Record per run: brand mentioned, position in answer, linked, sentiment, cited URLs + domains, and **whether the cited passage recommends the brand** (a citation alone isn't enough).
- Metrics: mention rate, citation rate, share of voice vs 3–5 competitors, cited-domain table, sentiment. Run a full round monthly, and a light weekly check on the topic you changed.
- Tools: user's Apify actors `khadinakbar/ai-search-visibility-tracker`, `khadinakbar/llm-visibility-tracker`, `khadinakbar/google-ai-overviews-scraper`, `khadinakbar/ai-overviews-tracker`, `khadinakbar/ai-search-brand-monitor`, `khadinakbar/ai-citations-tracker`, `khadinakbar/google-ai-mode-scraper`. From the user's own accounts, if they export them: Bing Webmaster Tools AI Performance (Copilot citations + grounding queries); GA4 AI-referrer regex `chatgpt\.com|perplexity|gemini\.google|copilot\.microsoft|claude\.ai|deepseek`.

## 2. Fan-out optimisation (highest leverage)
- **Capture fan-outs** per target prompt, in this order:
  1. **Actor output first.** Use the searches and sources the AI check Actors return for each question, and the related phrases from the long-tail keyword job (`khadinakbar/keyword-fanout-longtail`). Label the long-tail phrases "likely related searches".
  2. Bing Webmaster Tools grounding queries, if the user exports them.
  3. What the assistants show on screen: Perplexity lists its searches; Claude shows them in its visible reasoning.
  4. **May not work:** reading ChatGPT's browser DevTools (Network → conversation response → `queries`). It depends on the app's internals, changes without notice and often returns nothing. Never rely on it; skip it if it fails.
  Typical rewrites add the year, "reviews", "alternatives", "evaluate", `site:g2.com` / `capterra`.
- **Check Google + Bing rank** for each fan-out (goal: top 10–20).
- **Align pages**: fan-out phrasing in title, H1, natural-language slug, an H2 and the first sentence. Give each fan-out one self-contained passage. Create a page or H2 chunk when no page fits.
- Fan-outs drift, so recheck monthly.

## 3. Page types and format that get cited
- **"Best X" listicles** are among the page types ChatGPT cites most, and many of the cited ones were updated recently → get onto third-party lists (`checklist-offpage.md` §C5); keep your comparison content current.
- **"X vs Y" pages** on a landing-page template with a comparison table near the top. One page per pair, no templated text, real price comparisons.
- **Brand fact pages**: pricing, implementation time, integrations, limitations, an official FAQ. AI engines can invent prices when vendors hide them, and tend to repeat the vendor's own statement once it is published (C).
- **Answer-first sections**: each H2 opens with a short direct answer (about 50 words) readable out of context; concrete numbers; tables where items are compared. This is for readers, not a ranking trick: Google's 2026 guidance says AI-specific rewriting, content chunking and special files are not needed for its AI features (https://searchenginejournal.com/googles-new-ai-search-guide-calls-aeo-and-geo-still-seo/575026, May 2026). In one academic benchmark, adding statistics, quotations and cited sources raised visibility in generated answers by up to about 40% (Aggarwal et al., "GEO", KDD 2024, https://arxiv.org/abs/2311.09735, grade B: a lab benchmark, not live engines).
- **First-party data**: at least one number or data point of your own (a test, a count, a survey). It gives other pages, and assistants, something only you can be cited for. (B)
- **Freshness**: a visible updated date, changed only when the content changed; refresh key pages every 3–6 months. Pages cited by AI assistants were on average about 26% newer than pages in Google's organic results, and ChatGPT's cited pages about 458 days newer; Google's AI Overviews showed no such lean (Ahrefs, 17 million citations, July 2025, https://ahrefs.com/blog/do-ai-assistants-prefer-to-cite-fresh-content/, grade A, correlation).
- **Word count doesn't matter** by itself. (B)

## 4. Off-site consensus (mentions > links for AI)
- Branded web mentions correlated 0.664 with AI Overview visibility across 75,000 brands (Ahrefs, May 2025); in the December 2025 follow-up, YouTube mentions correlated about 0.737 across ChatGPT, AI Mode and AI Overviews (https://ahrefs.com/blog/ai-overview-brand-correlation/ and https://ahrefs.com/blog/ai-brand-visibility-correlations/, grade A, correlation not cause).
- Be present where engines look for the category: G2/Capterra/Trustpilot (correct categorisation), YouTube (long factual descriptions, comparison tables, testimonials), Reddit threads that already rank (helpful answers only), niche listicles, podcasts, Wikidata/Crunchbase where legitimate.
- **Cited for rivals, not for you**: list the sites AI cites for two or more competitors but never for the brand. They are the first outreach targets.
- **Local**: ChatGPT leans on Yelp/Angi/Thumbtack and vertical directories rather than GBP; AI Mode leans on GBP; reviews naming services help. The engines often disagree on the top local pick. (C)
- **Stores only**: keep the merchant product feed complete and current, because shopping results inside assistants read feeds.
- **Press releases** stating the exact category claim can be repeated by AI Overviews within days — verifiable facts only; the effect fades within weeks. (C)

## 5. Technical prerequisites
- Answer bots not blocked: Googlebot, Bingbot, OAI-SearchBot, ChatGPT-User, PerplexityBot, Perplexity-User, Claude-SearchBot, Claude-User, in robots.txt **and** Cloudflare/CDN bot settings. Training-only bots (GPTBot, ClaudeBot, Google-Extended, CCBot, Applebot-Extended) are your choice and have no effect on being cited.
- Google states that AI Overviews and AI Mode need no special markup or files: a page must be indexable and snippet-eligible. `nosnippet`, `data-nosnippet`, `max-snippet:0` or `noindex` (often set site-wide by an SEO plugin or theme) take it out. (Google's own documentation.)
- Content in server-rendered HTML (ChatGPT's crawler doesn't run JS).
- Indexed in **Bing** (Bing WMT + IndexNow) as well as Google.
- Private pages use `noindex` (robots.txt alone leaked Claude shared chats into search).
- `llms.txt`: optional, no proven effect (one CDN-log study saw no AI crawler requests for it; C). Never prioritise it.
- Schema: hygiene for rich results/entity clarity; controlled tests show no reliable AI-citation lift. Never promise one.

## 6. Reputation and accuracy
- Ask each engine what it says about the brand (pricing, features, complaints, "is it legit"). For each wrong/negative claim: find the source page, fix your own pages first, publish a clear response/FAQ, reply in the source thread where appropriate, request corrections from publishers.
- Map the top 10–20 URLs for brand-name queries; AI Overviews now summarise negative sentiment on brand queries.
- **Brand-search demand**: if the user has Search Console, watch whether searches for the brand name rise month by month.
- Watch for poisoning: fake third-party pages or "Summarize with AI" prompt-injection links about the brand.

## 7. Don't
Scaled AI pages targeting fan-outs (Google names it scaled content abuse; large visibility losses reported), mass self-promotional "best X" lists ranking yourself #1 (reported cited less, rising demotion risk; C), date refreshes without real updates, fake Reddit threads/upvotes, fabricated press releases, cloaking markdown to AI bots.
