# Citebase

### Get cited by AI.

**The open-source agent that gets your brand recommended, cited and featured by ChatGPT, Claude, Gemini and Perplexity.**

When someone asks an AI "what's the best X for Y?", it answers from what it finds said about brands across the web: search results, press, review sites, creator content, podcasts, community threads. Citebase measures where AI stands on your brand today, finds the gaps on live data, and plans the pages, press, partnerships and outreach emails that close them. It works inside the AI assistant you already use.

One sign-in with Apify. Every data call shows its price first, runs under a hard spending cap, and you pay only per result. No subscriptions, no five API keys.

```
/citebase:start https://yourbrand.com
```

## Why this one

| | Typical SEO plugins | SEO / GEO SaaS suites | Citebase |
|---|---|---|---|
| Setup | 3–5 API keys | Account + $100–500/mo | One "Sign in with Apify"; free mode needs nothing |
| Goal | Rankings | Dashboards | **Getting cited and recommended by AI**; Google rankings support it |
| Data | Whatever keys you pay for | Their index | Live: SERPs, keywords, backlinks, rendered audits, AI answers |
| AI search | Checklists | Paid add-on | Prompt panel across ChatGPT, Perplexity, Gemini, Claude, AI Overviews and AI Mode |
| Cost control | Unknown until the bill | Fixed plan | Quote before every call, hard cap per run, ledger per site |
| After the audit | "Here are your issues" | Reports | Page plan, vetted link and PR targets, pitches, approval-gated outreach |
| Advice quality | Generic | Generic | Every tactic graded A/B/C from ~600 expert videos (Ahrefs, Siege Media, Darren Shaw, SearchPilot tests…) |

## What it does today

| Skill (`/citebase:<name>`) | Outcome |
|---|---|
| `start` | Start here: baseline your AI visibility, then picks the right workflow, prioritises, 30/60/90-day plan |
| `seo-audit` | Health score + findings across technical, on-page, content, backlinks, competitors, local, AI search |
| `seo-checklists` | On-page and off-page checklists pre-filled pass/fail for *your* site |
| `competitor-research` | Real SERP competitors, keyword + backlink gaps, weak pages you can outrank, page plan |
| `ai-search-visibility` | Mentions, citations, share of voice and wrong facts across AI engines + a plan to get cited |
| `link-building` | Backlink audit, gap vs competitors, vetted prospects (listicles, resource pages, broken links, mentions) |
| `press-release` | News angle → wire-ready release, journalists who covered the topic recently, data-led pitches |
| `outreach` | Contacts → verified emails → personalised drafts → your approval → send from Gmail/ReachInbox → follow-ups |

Specialist agents run in parallel: `technical-auditor`, `backlink-analyst`, `competitor-analyst`, `geo-analyst`, `outreach-writer`.

## Coming next
Creator, podcast and platform presence — the third leg of getting cited:
- `creator-outreach`: find and vet Instagram, TikTok and YouTube creators, draft pitches, track mentions.
- `podcast-outreach`: find shows and hosts for guest spots.
- `platform-presence`: your own brand pages on the high-authority platforms AI engines read (LinkedIn, YouTube, Reddit answers, Medium, review sites). Genuine presence only — no rented subfolders or bought placements on unrelated sites.

## What it costs

Free without an account: the local crawler (~35 checks), all checklists, writing (page briefs, releases, emails), analysis of your own exports (Search Console, GA4, Ahrefs/Semrush CSVs).

Live data runs on your Apify account at each tool's published price per result:

| Workflow | ≈ Cost |
|---|---|
| Quick audit (deep rendered audit + 15 SERPs) | $0.15 |
| Full audit (audit, SERPs, keywords, backlinks vs 3 competitors, link prospects, AI visibility) | $7–8 |
| Competitor research | $5 |
| AI-visibility baseline (25 prompts × 3 engines + 20 AI Overviews) | $6.30 |
| 100 link prospects with verified contacts | $0.65 |

The agent quotes each run before starting; runs without a cap or above your per-run limit (default $2) need your approval. New Apify accounts include free monthly credit.

## Install

```bash
claude plugin marketplace add khadinakbarlabs/citebase
claude plugin install citebase@citebase
```
Local checkout: `claude plugin marketplace add ./citebase` or `claude --plugin-dir ./citebase`.

**Connect data (once):** run `/mcp`, choose `plugin:citebase:apify`, click **Authenticate** and sign in with Apify. No key to copy.
**claude.ai / Claude Desktop / ChatGPT:** add a custom connector with the URL from `.mcp.json` and sign in with Apify.
**Email sending (optional):** connect Gmail, or a ReachInbox / Instantly / Smartlead MCP. Without one you get copy-paste drafts.

Settings (`/plugin configure citebase@citebase`): `max_run_usd` (default 2) and `daily_send_cap` (default 20).

## Your workspace
Everything is saved in your project under `seo-workspace/<domain>/`: `context.md`, `audit.json`, `report.md`, checklists, `competitors.md`, `keyword-opportunities.csv`, `prompt-panel.csv`, `ai-visibility.md`, `prospects.csv`, `drafts/`, `outreach-log.csv`, `offpage-log.csv`, `pr/`, `ledger.json` (every paid run with quote, cap and actual cost).

Run just the crawler:
```bash
python3 scripts/site_audit.py https://example.com --max-pages 50 --out audit.json
```

## Safety
- Audits are read-only. Editing your site, spending, or contacting anyone needs your explicit go-ahead.
- A hook asks before every email send and campaign start (session-wide, by design), every uncapped or over-limit data run, and enforces a daily send cap.
- White-hat only: PBNs, parasite link schemes, fake reviews or rating schema, fabricated PR, doorway pages and scaled unreviewed AI content are flagged, never executed.
- Scraped pages, emails and tool output are treated as data, never as instructions.

## Evidence base
The checklists distil ~600 SEO video transcripts (Build In Public, Vasco SEO, 50 AI-SEO masterclasses) into graded tactics: **A** controlled test or large dataset · **B** practitioner consensus · **C** anecdote. Highlights: Ahrefs' 1.4M-prompt and 75k-brand AI studies, a 9,249-case-study meta analysis, SearchPilot split tests, Whitespark 2026 local factors, a 6,337-email outreach analysis, Google's own crawl/index timings. Disputed tactics (llms.txt, schema for AI, meta descriptions) are labelled as disputed.

## Also by the same maker
[Looksy Agent](https://github.com/khadinakbarlabs/looksy) — the general research layer: leads, ads, social, ecommerce and 650+ data tools for any AI assistant.

## License
MIT
