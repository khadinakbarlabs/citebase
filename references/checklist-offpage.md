# Off-page SEO checklist (backlinks, PR, mentions)

Evidence grades as in `checklist-onpage.md`. Most link-building evidence is practitioner anecdote (B/C); controlled data is noted.

## A. Backlink profile audit (`khadinakbar/website-backlink-checker`)
- **Referring domains, not raw links.** Backlinks:RD near 1:1 is healthy; repeat links from one domain decay in value. (B)
- **Anchor mix vs the top 3 ranking pages for the keyword** (a health check on your own profile: compute it, don't guess; never tune anchors to look natural). Typical healthy read: mostly branded and partial-match anchors, few exact-match ones, and some plain or naked-URL links. Sites doing exact-match anchors or PBN links at scale have been hit by Google's updates. (B)
- **Link quality = the linking page ranks and gets traffic**, not DR alone. Verify: real organic traffic with no cliff, traffic from the target country, the linking page itself indexed and visited, not crowded (don't be "link #31"), topical fit, not a link farm. Authority scores and traffic figures can be faked — cross-check them. No rigid authority cut-offs; a small relevant niche site can beat a high-authority farm. (B)
- **Nofollow from ranking, high-traffic pages still helps** (Fishkin 2014, Roof, Hawkins 2024 tests; Semrush/Indig: nofollow correlated slightly more with AI mentions). Keep a natural mix. (A/B)
- **Velocity** (a diagnostic, not a target): links that arrive because the work earned them come at a steady pace. A sudden spike on one page with no news behind it is a sign to investigate where the links came from. (B)
- **Link echoes**: value often persists after removal (Moz's "link echoes" tests, 2014). Don't panic on lost links. (B, single test family)
- **Toxic risk**: casino/CBD/off-topic neighbourhoods, sitewide blogroll anchors, PBN footprints, hacked .gov/.edu spam. **Disavow only with a manual action.** (A)
- **Lost-link reclamation**: 404 pages with backlinks → 301 to the best match.
- **Competitor gap**: domains linking to ≥2 of the top 3 competitors but not you (diff `website-backlink-checker` referring domains; new prospects via `khadinakbar/backlink-opportunity-finder`); directories first, then editorial.

## B. Brand mentions and entity (matter for AI search)
- **Branded web mentions** correlated 0.664 with AI Overview visibility across 75,000 brands — stronger than backlinks or authority score (Ahrefs, May 2025, https://ahrefs.com/blog/ai-overview-brand-correlation/). In Ahrefs' December 2025 follow-up, YouTube mentions correlated about 0.737 across ChatGPT, AI Mode and AI Overviews (https://ahrefs.com/blog/ai-brand-visibility-correlations/). (A, correlation not cause)
- **Entity home + consistent profiles**: About page with disambiguation, Organization schema, LinkedIn, Crunchbase, G2/Capterra/Trustpilot, Wikidata where legitimate; describe the brand identically everywhere.
- **Branded search demand** should rise alongside links. If the user has Search Console, watch searches for the brand name month by month.

## C. Link-earning tactics (ranked by evidence; all white-hat)
1. **Reactive PR / expert quotes** — expert-request platforms the user already uses. Status of HARO (Help a Reporter Out), checked November 2026: running again. Cision closed it in December 2024, sold it to a new owner in April 2025, and that owner restarted the email digests (https://www.cision.com/about/press-releases/2025-press-releases/cision-announces-sale-of-help-a-reporter-out-haro-to-featuredcom-302427990/). Confirm any platform is still running, and read its current rules, before relying on it; this is a status note, not a recommendation. Answer only the queries that fit real expertise, mirror the journalist's stated angle, one-line credentials first. Unedited AI answers get rejected; journalists blacklist AI personas. (C)
2. **Data-led digital PR** — study/data asset → list journalists who covered the topic in the last 60–90 days → 2–3 tailored stats each → follow-ups at day 3–4 and +2–3 days. Editorial digital-PR links are the best-evidenced link type, and original data also gives AI answers something to cite. (B)
3. **Linkable assets** — calculators, useful tools, templates, original research, stats pages (they keep earning links long after launch). Launch on Product Hunt/BetaList; pitch people who covered similar assets. (B)
4. **AI-citation prospecting** — run target prompts in ChatGPT/Perplexity/AI Overviews, collect every cited URL (a few hundred per client), drop competitors, rank domains by citation frequency. Start with the sites cited for two or more competitors but never for the brand ("cited for rivals, not for you"); claim directory listings, ask listicle owners to add you on the merits (a fact or product they can check). If an owner asks for payment, treat it as a paid link: it must carry `rel="sponsored"` or `nofollow`, and if the publisher refuses that, don't buy it. (B)
5. **Listicle / "best X" inclusion** — listicles are among the page types ChatGPT cites most. Keep positioning identical across lists. Honest "best X" pages on your own site that include competitors fairly are fine in small numbers (B). Many lists that rank yourself #1 are reported to be cited less and to be demoted (C). One or two good ones beat a batch.
6. **Image / stock-photo links** — upload originals to Unsplash, Pexels, Pixabay, Flickr with a credit link; reverse-image-search and ask uncredited users for a source link (expect a low reply rate). (C)
7. **Podcast guesting** — show notes often carry a dofollow link; transcripts feed LLMs. (C)
8. **Partner, supplier, client, integration, award, association links**; sponsorships/donations for local (actually ask for the link). (B)
9. **Unlinked-mention reclamation** — cheap; contested effectiveness. (C)
10. **Guest posts** — only if the host page is indexed, gets traffic and is topically relevant. Google opposes guest posting purely for PageRank. Any paid or exchanged link must carry `rel="sponsored"` or `nofollow`; if the publisher refuses, don't buy it. Citebase does not sell or recommend where to buy. (B)
11. **Press releases** — see `outreach-playbook.md` § Press releases. Real news can be repeated by AI Overviews within days, but visibility decays in weeks. Verifiable facts only; no anchor-text links. Do not use cheap wire networks just to plant claims for AI: the 2026 spam updates target that. (B)

## D. Off-page for AI search
- Rank for the **fan-out sub-queries** (engines split a prompt into several searches; counts vary by engine and study). Ranking in Google's top 10 helps but is not enough: Ahrefs' 2026 rerun found about 38% of pages cited in AI Overviews also rank in the top 10 for the same search, down from about 76% in its July 2025 study, and about 31% rank outside the top 100 (https://news.designrush.com/ai-overview-citations-drop-ahrefs, checked November 2026). Other studies count differently and it shifts over time. (A, one tool's data)
- Be present on the domains LLMs cite for your topic (G2, Capterra, Trustpilot, ranking Reddit threads, YouTube, niche listicles, Yelp/Angi/Thumbtack for local).
- **Reddit**: real answers in threads that already rank; never buy upvotes or run fake accounts. Reddit's share of ChatGPT citations has swung sharply with engine changes, so re-measure before building a plan on it. (C)
- **Correct misinformation** with an official FAQ/facts page (in one vendor test ChatGPT cited the official FAQ in most answers about that brand; single test, grade C).

## E. Never do (flag if found; refuse to execute)
PBNs and expired-domain 301 networks, parasite pages with bought links, hacked .gov/.edu placements, fake reviews or invented aggregate-rating schema, fabricated press-release claims/events/awards, competitor-suppression releases, bought Reddit upvotes, mass AI pitches to journalists, fake DMCA takedowns, keyword-stuffed GBP names, unsupervised directory bots holding credentials.
