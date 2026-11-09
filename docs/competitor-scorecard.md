# Citebase scorecard: where it competes, where it does not yet

> **Internal planning note. Not part of the product and not for the README, the Apify page or any public claim.** Do not copy its prices or product names into public text. Updated to the 0.4 state (saved history, hosted reports, `schedule_checks`).

Facts about other products come from their own public pages, read on **2026-11-07**, and from the open-source projects' own READMEs. Prices are as shown on the pages (billing period and currency as noted). They change: re-check before you quote them. Citebase is independent and not affiliated with any product named here. Moz could not be read and is not covered.

## 1. Price snapshot

| Tool | Cheapest paid plan with AI-visibility tracking (as shown) | What the page says you get | Source |
|---|---|---|---|
| Otterly.AI | Lite $29/mo ($25 on the other toggle; which is monthly is not stated) | 15 prompts, daily, ChatGPT, AI Overviews, Perplexity, Copilot; Claude, AI Mode, Gemini are add-ons | otterly.ai/pricing |
| Peec AI | Starter $95/mo | 50 prompts, 3 models, daily, 4,500 AI answers per month, MCP on all plans | peec.ai/pricing |
| SE Ranking | Core $129/mo ($103.20 annual) | 25 prompts daily, 5 engines, plus site audit, keywords, backlinks, rank tracking | seranking.com/pricing.html |
| Surfer | AI Search Analytics $82/mo billed yearly | 50 prompts daily, 5 brand spaces, MCP | surfer.ai/pricing |
| Semrush | SEO + AI Search Starter $165.17/mo annual ($199 monthly); standalone AI Visibility Base $99/mo per domain annual | 50 prompts daily, 1 domain, MCP (Starter) | semrush.com/pricing |
| Ahrefs | Brand Radar from $199/mo as an add-on to a plan (Lite $129/mo) | 5 prompts / 150 checks per month on Lite; 7 AI surfaces; daily; MCP | ahrefs.com/brand-radar |
| Scrunch AI | Starter $250/mo annual ($300 monthly) | 350 custom prompts, 3 users, trends dashboard | scrunch.com/pricing |
| AthenaHQ | Starter $295/mo | Unlimited prompts, 11 models, CSV export, API is a paid add-on | athenahq.ai/pricing |
| Profound | Enterprise, custom (free 7-day trial) | Up to 9 engines, history, API | tryprofound.com/pricing |
| Screaming Frog | £199 per licence per year | Desktop crawler, 300+ issues, JavaScript rendering, MCP server (not an AI tracker) | screamingfrog.co.uk |
| Elmo (open source, MIT) | Self-hosted free; Elmo Cloud from $29/mo | Dashboards, share of voice, sentiment, trends, reports, API, SDKs, MCP | Elmo README |
| Ansvisor (open source, MIT) | Self-hosted free; managed cloud | Citations, prompts, competitors, MCP | Ansvisor README |
| GEO/AEO Tracker (open source, MIT) | Free software; you pay data providers per call | 5 engines, optional cloud sync | its README |
| **Citebase** | **No subscription.** No Citebase fee on the tools; paid data per result on your Apify account | AI brand check $0.08 per prompt x engine x run, and the other jobs in the Store README | Actor listing |

## 2. Same-job cost: checking whether AI recommends you

Arithmetic from the prices above. Assumption: one "check" = one prompt on one engine on one day.

| Usage | Citebase | Subscription tools |
|---|---|---|
| 60 checks a week (20 prompts, 3 engines, weekly) = about 260 a month | about **$21/mo** | Otterly Lite $29/mo |
| Daily tracking, 20 prompts x 3 engines = 1,800 a month | about **$144/mo** | Otterly Lite $29/mo (15 prompts x 4 engines daily is 1,800), Peec Starter $95/mo (4,500 answers stated) |
| A one-off baseline, 270 checks + 20 AI Overviews | **$23.60, once** | A month of any plan |

Reading it honestly:
- At steady daily volume, subscriptions cost roughly **4 to 9 times less per check** than Citebase today (about $0.016 to $0.021 per check against $0.08).
- Citebase is cheaper when you check **less than about 360 times a month** (against Otterly Lite) or **about 1,190** (against Peec Starter), and for one-off audits, per-client project work and people who do not want a subscription.
- To compete on always-on tracking, the cost per check has to come down (see the build list).

## 3. Feature scorecard

Status: **Covered** = works today. **Partial** = works with limits. **Not yet** = not built.

| Capability | Citebase today | What the tools above typically offer |
|---|---|---|
| Check AI answers across engines | **Covered** for ChatGPT, Perplexity, Gemini, Claude, Google AI Overviews and AI Mode (separate paid Actors) | 5 to 11 engines; adds Copilot, Grok, DeepSeek, Meta AI |
| Daily or scheduled tracking | **Partial** (0.4: `schedule_checks` gives the cron text, ready-to-paste inputs and a monthly cost; the scheduled site check refreshes the report by itself; AI re-checks run from an Apify Schedule you create, then an import step. Weekly or monthly, not daily) | Daily on almost every plan |
| History and trends over time | **Covered** from 0.4 (named projects in your own Apify account: AI rounds, site scores and logged changes; up to 100 projects and 60 rounds each; `get_history`) | 6 months to all-time history, dashboards |
| Shareable reports and exports | **Partial** (0.4: `make_report` gives a one-page report with a trend chart and a link you can share; no CSV export, no scheduled email) | Dashboards, CSV, scheduled reports, Looker Studio |
| Alerts when visibility changes | **Not yet** | Offered by some (Otterly, AthenaHQ); others not stated |
| Citation and source analysis | **Partial** (Perplexity sources job, cited domains in results) | Source and citation share dashboards |
| Sentiment | **Not yet** in Citebase's own numbers | Common |
| Competitor benchmarking / share of voice | **Partial** | Common, often unlimited competitors |
| Statistical honesty (repeat runs, control questions, confidence ranges, change verdicts) | **Covered**, and a real differentiator | Not stated on the pages read |
| Plain-language recommended actions | **Covered** (playbooks and `next_steps`) | Content or action recommendations on many plans |
| Technical site audit | **Partial** (30+ checks, up to 30 pages, no JavaScript; larger crawls through the Actors) | Large crawls (for example 250,000 pages a month), JavaScript rendering on some |
| Keyword research | **Covered** through the `keywords` pack (about $1.42), per row, no history | Large databases with history |
| Backlink research | **Covered** through a paid Actor | Own backlink databases |
| Rank tracking over time | **Partial** (Bing and local rank checks are priced jobs behind `quote_cost`; no stored rank history yet) | Standard |
| Writing and content optimisation editor | **Partial** (local `content-brief`, `content-optimize`, `humanize-content`, `eeat-audit`, `ai-content-check`; no Surfer-style proprietary content score) | Surfer, Frase, SE Ranking, Semrush, Outrank |
| Entity / Knowledge graph SEO | **Partial** (`entity-seo` playbook + schema hygiene in audit) | SearchAtlas / SEOmatic-style entity claims (verify on their pages) |
| Programmatic SEO at scale | **Partial** (`programmatic-seo` with anti-spam gates; no auto-publish farm) | Outrank / proprietary pSEO suites |
| Platform presence (vs parasite spam) | **Partial** (`platform-presence`; refuses rented-subfolder schemes) | Often sold as gray-hat elsewhere — Citebase will not |
| Outreach and PR workflow | **Covered** (playbooks, email checker, never sends) | Mostly not included |
| MCP and API | **Covered** | MCP on many plans (Peec, Otterly Standard+, Semrush Starter, Ahrefs, SE Ranking, Surfer) |
| Open source | **Covered** (MIT) | Elmo, Ansvisor and GEO/AEO Tracker are also open source |
| No subscription, pay per use | **Covered** | Mostly subscriptions |
| Team seats, client portals, white label | **Not yet** | Common on higher plans |
| Local SEO | **Partial** (the `local` pack prices map rank and the local results pack; guidance in the technical checklist) | Varies |

## 4. What this means for positioning

- Citebase is **not** a replacement for the whole of these suites, and should not be described as one.
- It is a credible **pay-per-use, open-source alternative for three jobs**: a one-off or occasional AI-visibility check, a first-pass site audit with a plain fix list, and planning plus outreach checks, all from inside your own AI assistant.
- The open-source AI-visibility space already has **dashboard-first** tools (Elmo, Ansvisor). Citebase's different angle is the **thinking and doing layer**: guidelines, honest measurement, a ranked to-do list and outreach checks, with no server to host.
- Choose a subscription or self-hosted dashboard instead when you need **daily tracking at volume, long history, alerts or client reporting**.

## 5. Ranked build list (what earns the bigger claim)

Status at 0.4: builds 1 and 3 shipped, build 2 partly (the steps and inputs ship; the AI re-check still needs a schedule the user creates). The list below keeps the original order for reference.

| # | Build | Closes | Impact | Effort |
|---|---|---|---|---|
| 1 | Save results and history in the user's own Apify storage; load them for trends | history, trends, "nothing is kept" | High | Medium |
| 2 | Scheduled re-checks (Apify schedules + a scheduled-measure run mode) | daily/weekly tracking | High | Medium |
| 3 | Shareable report page (hosted HTML in the user's storage) | reports, client sharing | High | Low to medium |
| 4 | Lower the cost per AI check (own checker using direct provider APIs, or a cheaper tier; owner's pricing decision) | the 4 to 9 times cost gap | High | High |
| 5 | Alerts through Apify webhooks and integrations | alerts | Medium | Low |
| 6 | Wire the existing rank-tracking Actor into quotes and playbooks | rank tracking | Medium | Low |
| 7 | More engines: Copilot, Grok, DeepSeek, Meta AI | engine coverage | Medium | Medium |
| 8 | Sentiment and share-of-voice in `measure_recommendation_share` | sentiment, benchmarking | Medium | Medium |
| 9 | Bigger crawls with JavaScript rendering through the existing spider and audit Actors | site audit depth | Medium | Low to medium |
| 10 | Read results from Elmo or Ansvisor through their APIs, so Citebase can be the planning layer on top | interoperability | Medium | Medium (verify their APIs first) |

The original first bundle (**1 + 2 + 3**: history, scheduling, report) is now mostly shipped. Next: finish 2 (a digest after each scheduled run, so the result reaches the user), then 4 (cost per check), then 5 and 6.

## 6. Method and limits

- Pages were read by an automated reader on 2026-11-07. Anything a page did not state is written as "not stated" and is not counted as missing from the product.
- Moz blocked the reader and was not checked. Surfer's AI tracker page and Screaming Frog's pricing page were linked but not read.
- Prices shown without a billing label are listed as the page showed them. Re-check before publishing a comparison.
- Cost arithmetic uses Citebase's public prices (read 2026-11-07) and the stated plan limits above; it ignores free trials, annual discounts and add-ons.
