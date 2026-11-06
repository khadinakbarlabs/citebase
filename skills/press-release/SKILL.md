---
name: press-release
description: Digital PR and press releases — find a genuine news angle, write a wire-ready press release, find journalists who recently covered the topic, pitch data stories, answer expert-request platform queries (Featured, Qwoted and similar), and track coverage and AI pickup. Use for press release, PR, digital PR, newswire, journalist pitch, HARO-style requests, media coverage, brand mentions.
argument-hint: "<domain> [release|pitch|reactive] [news/angle]"
---

# Press releases and digital PR

Read `../../references/outreach-playbook.md` (§ Press releases, templates 1 and 9, hard rules) and `../../references/checklist-offpage.md` §C1–C2. Paid data runs follow the protocol in `../../references/tools-and-apis.md`.

## A. Press release
1. **Angle check** — real and verifiable: launch, feature, funding, partnership, expansion, hire, award actually won, original data study, customer result (with permission). No angle → say so and suggest creating one (a data study or free tool) instead of a fluff release.
2. **Write** `seo-workspace/<domain>/pr/release-<slug>.md` with: headline (entity + news + the category phrase the brand wants Google and AI answers to repeat), optional summary ≤45 words, dateline (City, Country — Date), lead answering who/what/when/where/why, 2–3 specific body paragraphs, a quote from a named person, consistent "About [Brand]" boilerplate (include the facts AI engines tend to get wrong: pricing model, locations, integrations), media contact. 250–1,200 words, ≤5 links (brand or naked URLs, no keyword anchors).
3. **Check** against the typical wire limits in the playbook and list any violations.
4. **Distribution**: the user publishes through their wire or PR partner. Any paid distribution needs their explicit approval of plan and price. Recommend pairing the release with an on-site page stating the same facts (releases decay within weeks; the page lasts).
5. **Track**: when the user shares the live/report URLs, log them to `offpage-log.csv` (`type=press_release`). After ~7 days, check pickup: `khadinakbar/google-news-scraper` for the brand ($0.003/article) and the brand prompts from `ai-search-visibility` (AI Overviews often repeat syndicated release facts within days). Report what changed.

## B. Proactive digital PR (data-led)
1. Pick a data angle tied to the business (survey, public-data analysis, pricing index, "cost by city/state", industry benchmark). Optional research inputs: `khadinakbar/reddit-posts-comments-scraper` (what people ask), `khadinakbar/google-trends-scraper` (timing), `khadinakbar/software-reviews-all-in-one-scraper` / `trustpilot-reviews-scraper` (review-mining studies).
2. Build the asset page on the site (methodology, charts, embed code, quotable stats).
3. **Journalist list**: `khadinakbar/google-news-scraper` for the topic over the last 60–90 days → bylines, outlets, article URLs. Contacts via the `outreach` skill (author pages, `bulk-website-contact-extractor`, `email-address-validator`).
4. Pitch with template 1 (≤90 words, 2–3 stats matched to each journalist's angle). Follow-ups day 3–4 and +2–3 days. Drafting and sending go through `outreach` (approval-gated).

## C. Reactive PR (expert-request platforms)
HARO (later Connectively) was shut down in December 2024 as far as we know; verify any platform is still operating before recommending it. If the user subscribes to Featured.com, Qwoted, Source of Sources or Help a B2B Writer and the digests reach a connected inbox: triage today's queries against the client's real expertise, skip ones that conflict with their stance, and draft answers with template 9 that mirror the journalist's stated angle. Draft only — the user edits and sends; credibility must be human. Never fabricate credentials or personas.

## Rules
- No fabricated events, awards, quotes or customers; no competitor attacks; no anchor-text stuffing.
- Nothing is published or sent without the user's explicit approval.
