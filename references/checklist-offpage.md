# Off-page SEO checklist (backlinks, PR, mentions)

Evidence grades as in `checklist-onpage.md`. Most link-building evidence is practitioner anecdote (B/C); controlled data is noted.

## A. Backlink profile audit (`khadinakbar/website-backlink-checker`)
- **Referring domains, not raw links.** Backlinks:RD near 1:1 is healthy; repeat links from one domain decay in value. (B)
- **Anchor mix vs the top 3 ranking pages for the keyword** (compute it, don't guess). Typical healthy read: branded ≈20%, partial ≈50%, exact ≈≤10%, generic/naked 15–20%. Local: exact-match anchors "five or so". Core updates (Dec 2025) wiped sites doing anchored/PBN links at scale. (B)
- **Link quality = the linking page ranks and gets traffic**, not DR alone. Verify: real organic traffic with no cliff, traffic from the target country, the linking page itself indexed and visited, not crowded (don't be "link #31"), topical fit, not a link farm. DR/traffic can be faked ("DA50/50k" may be 5k) — cross-check. No rigid DR cut-offs; a relevant 1k-visit niche site can beat a DR70 farm. Common agency floors: DR 40+ and 500–2,000+ organic visits/mo. (B)
- **Nofollow from ranking, high-traffic pages still helps** (Fishkin 2014, Roof, Hawkins 2024 tests; Semrush/Indig: nofollow correlated slightly more with AI mentions). Keep a natural mix. (A/B)
- **Velocity**: steady cadence, not bursts; a 10-page new site ≈5 links in month 1; never 100 links to one page; a link spike without branded-search growth looks unnatural. (B)
- **Link echoes**: value often persists after removal (Moz: 31st → 1st with 22 links, stayed 1st after removal). Don't panic on lost links. (A, single test family)
- **Toxic risk**: casino/CBD/off-topic neighbourhoods, sitewide blogroll anchors, PBN footprints, hacked .gov/.edu spam. **Disavow only with a manual action.** (A)
- **Lost-link reclamation**: 404 pages with backlinks → 301 to the best match.
- **Competitor gap**: domains linking to ≥2 of the top 3 competitors but not you (diff `website-backlink-checker` referring domains; new prospects via `khadinakbar/backlink-opportunity-finder`); directories first, then editorial.

## B. Brand mentions and entity (matter for AI search)
- **Branded web mentions** on pages that already get cited correlate 0.664 with AI Overview visibility across 75k brands — stronger than backlinks/DR (Ahrefs). YouTube mentions correlate 0.737 with ChatGPT visibility. (A, correlation)
- **Entity home + consistent profiles**: About page with disambiguation, Organization schema, LinkedIn, Crunchbase, G2/Capterra/Trustpilot, Wikidata where legitimate; describe the brand identically everywhere.
- **Branded search demand** should rise alongside links.

## C. Link-earning tactics (ranked by evidence; all white-hat)
1. **Reactive PR / expert quotes** — expert-request platforms: Featured.com, Qwoted, Source of Sources, Help a B2B Writer (HARO, later Connectively, was shut down in December 2024 as far as we know; verify each platform is still running). ~1 relevant reply/day, mirror the journalist's stated angle, one-line credentials first. A reported 70–79% acceptance rate comes from a single host. Vanilla AI answers are banned; journalists blacklist AI personas. (C)
2. **Data-led digital PR** — study/data asset → list journalists who covered the topic in the last 60–90 days → 2–3 tailored stats each → follow-ups at day 3–4 and +2–3 days. Editorial digital-PR links +71% sessions (meta study); one data study: 80 links, ~40% LLM citation share on its topic. (A/B)
3. **Linkable assets** — calculators, free tools, templates, original research, stats pages (earn links 12+ months once indexed). Canva palette tool ≈8.1k links / 2.2k domains. Launch on Product Hunt/BetaList; pitch people who covered similar assets. (B)
4. **AI-citation prospecting** — run target prompts in ChatGPT/Perplexity/AI Overviews, collect every cited URL (500–1,000 per client), drop competitors, rank domains by citation frequency; claim directory listings, ask listicle owners to add you (5–10-entry lists best; owners often ask $50–$1,000), niche-edit pages already cited. (B)
5. **Listicle / "best X" inclusion** — listicles are ~44–50% of ChatGPT citations in two datasets. Keep positioning identical across lists. Self-promotional listicles ranking yourself #1 are reported to be cited ~2× less and to be volatile in Google. (B/C)
6. **Image / stock-photo links** — upload originals to Unsplash, Pexels, Pixabay, Flickr with a credit link; reverse-image-search and ask uncredited users for a source link (reported 5–7% conversion). (C)
7. **Podcast guesting** — show notes often carry a dofollow link; transcripts feed LLMs. ~30 shows in 3 months via PodMatch reported. (C)
8. **Partner, supplier, client, integration, award, association links**; sponsorships/donations for local (actually ask for the link). (B)
9. **Unlinked-mention reclamation** — cheap; contested effectiveness. (C)
10. **Guest posts** — only if the host page is indexed, gets traffic and is topically relevant. Google opposes guest posting purely for PageRank. If buying, use a reputable marketplace with real traffic metrics and vet each site anyway (95% of bloggers asked for payment). (B)
11. **Press releases** — see `outreach-playbook.md` § Press releases. Cheap syndicated releases can seed brand facts AI Overviews repeat within days, but visibility decays in weeks. Verifiable facts only; no anchor-text links. (B)

## D. Off-page for AI search
- Rank for the **fan-out sub-queries** (engines split a prompt into several searches; counts vary by engine and study). Overlap between AI citations and Google's top 10 is reported at very different levels (one 2025 study put it near 76% for AI Overviews, others far lower, and it shifts over time), and one study reported that most ChatGPT-cited URLs come from a search index. Read these as "ranking helps, it is not sufficient". (C)
- Be present on the domains LLMs cite for your topic (G2, Capterra, Trustpilot, ranking Reddit threads, YouTube, niche listicles, Yelp/Angi/Thumbtack for local).
- **Reddit**: real answers in threads that already rank; never buy upvotes or run fake accounts. One tracker reported Reddit's share of ChatGPT citations falling from ~10–14% to ~1–3% after September 2025; shares swing with engine changes, so re-measure before building a plan on it. (C)
- **Correct misinformation** with an official FAQ/facts page (in one vendor test ChatGPT cited the official FAQ in 84% of answers about that brand; single test, grade C).

## E. Never do (flag if found; refuse to execute)
PBNs and expired-domain 301 networks, parasite pages with bought links, hacked .gov/.edu placements, fake reviews or invented aggregate-rating schema, fabricated press-release claims/events/awards, competitor-suppression releases, bought Reddit upvotes, mass AI pitches to journalists, fake DMCA takedowns, keyword-stuffed GBP names, unsupervised directory bots holding credentials.
