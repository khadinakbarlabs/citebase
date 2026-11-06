# Citebase

### Get cited by AI.

**The open-source agent that gets your brand recommended, cited and featured by ChatGPT, Claude, Gemini and Perplexity.**

When someone asks an AI "what's the best X for Y?", it answers from what it finds said about brands across the web: search results, press, review sites, creator content, podcasts, community threads. Citebase measures where AI stands on your brand today, finds the gaps on live data, plans the pages, press, partnerships and outreach emails that close them, and then re-measures to see whether it worked. It works inside the AI assistant you already use.

One sign-in with Apify. Every data call shows its price first, runs under a spending cap, and you pay only per result. No subscriptions, no five API keys.

```
/citebase:start https://yourbrand.com
```

## Why this one

| | Typical SEO plugins | SEO / GEO SaaS suites | Citebase |
|---|---|---|---|
| Setup | 3–5 API keys | Account + $100–500/mo | One "Sign in with Apify"; free mode needs nothing |
| Goal | Rankings | Dashboards | **Getting cited and recommended by AI**; Google rankings support it |
| Data | Whatever keys you pay for | Their index | Live: SERPs, keywords, backlinks, server-HTML audits, AI answers |
| AI search | Checklists | Paid add-on | A frozen prompt panel run repeatedly across ChatGPT, Perplexity, Gemini, Claude and Google AI, reported as Recommendation Share with confidence intervals and control prompts |
| Cost control | Unknown until the bill | Fixed plan | Quote before every call, a cap that Apify enforces per run, a daily ceiling, a ledger per site |
| After the audit | "Here are your issues" | Reports | Page plan, vetted link and PR targets, pitches, approval-gated outreach, experiments you can re-measure |
| Advice quality | Generic | Generic | Every tactic graded A/B/C from ~600 expert videos; disputed ones labelled |

## What it does today

| Skill (`/citebase:<name>`) | Outcome |
|---|---|
| `start` | Start here: picks the right workflow, prioritises, 30/60/90-day plan |
| `seo-audit` | Weighted health score with sub-scores across technical, on-page, content, backlinks, competitors, local, AI search |
| `seo-checklists` | On-page and off-page checklists pre-filled pass/fail for *your* site |
| `competitor-research` | Real SERP competitors, keyword + backlink gaps, weak pages you can outrank, page plan |
| `ai-search-visibility` | What AI says about you, cited domains, wrong facts, and a plan to get cited |
| `citation-loop` | Frozen prompt panel → repeat runs → Recommendation Share → logged experiments → re-measure |
| `link-building` | Backlink audit, gap vs competitors, vetted prospects (listicles, resource pages, broken links, mentions) |
| `press-release` | News angle → wire-ready release, journalists who covered the topic recently, data-led pitches |
| `creator-outreach` | Influencers, YouTubers, podcasts, newsletters: find, vet with a score, honest disclosure, tracking |
| `outreach` | Contacts → verified emails → personalised drafts → your approval → send from your own email connector → follow-ups |

Specialist agents run in parallel with restricted tools: `technical-auditor`, `backlink-analyst`, `competitor-analyst`, `geo-analyst`, `outreach-writer` (drafts only, cannot send).

## Coming next
Creator, podcast and platform presence, the third leg of getting cited:
- `creator-outreach`: find and vet Instagram, TikTok and YouTube creators, draft pitches, track mentions.
- `podcast-outreach`: find shows and hosts for guest spots.
- `platform-presence`: your own brand pages on the high-authority platforms AI engines read (LinkedIn, YouTube, Reddit answers, Medium, review sites). Genuine presence only: no rented subfolders or bought placements on unrelated sites.

## What it costs

Free without an account: the local crawler (30+ checks), all checklists, writing (page briefs, releases, emails), analysis of your own exports (Search Console, GA4, or exports from any SEO tool you already use).

Live data runs on your Apify account at each Actor's published price (read 2026-11-06; the agent re-checks before quoting):

| Workflow | ≈ Cost |
|---|---|
| Quick audit (server-HTML audit + 15 SERPs) | $0.13 |
| Full audit (audit, SERPs, keywords, backlinks vs 3 competitors, link prospects, small AI check) | $7 |
| Competitor research | $5 |
| AI-visibility pilot (20 prompts × 3 engines × 1 run + 20 AI Overviews) | $5.10 |
| AI-visibility baseline (same, 3 runs each) | $14.70 |
| 100 link prospects with verified contacts | $0.63 |

AI answers are the expensive part: brand checks cost $0.08 per prompt × engine × run, and the page-citation tracker $0.09 per keyword × query × engine (about $1 per keyword with defaults). Keyword and backlink Actors charge a per-request fee on top of per-row prices, so runs are batched. The agent quotes each run before starting. New Apify accounts include free monthly credit.

## Install

```bash
claude plugin marketplace add khadinakbarlabs/citebase
claude plugin install citebase@citebase
```
Local checkout: `claude plugin marketplace add ./citebase` or `claude --plugin-dir ./citebase`.

**Connect data (once):** run `/mcp`, choose `plugin:citebase:apify`, click **Authenticate** and sign in with Apify. No key to copy.
**claude.ai / Claude Desktop / ChatGPT / Cursor:** use the web connector described below. Hooks do not run there, so the spending and send guardrails below rely on the playbooks' instructions and each product's own confirmation prompts.
**Email sending (optional):** connect any email connector you already use. Citebase does not recommend or sell one. Without one you get copy-paste drafts.

Settings (`/plugin configure citebase@citebase`):

| Setting | Default | Meaning |
|---|---|---|
| `max_run_usd` | 2 | A run whose cap is higher asks you first |
| `daily_spend_usd` | 25 | New runs are denied once today's caps add up to this |
| `daily_send_cap` | 20 | Maximum recipients per day (to + cc + bcc) |
| `allowed_actors` | empty | Extra `owner/name` Actors besides `khadinakbar/*` |

## Use it on the web: the Citebase connector

For assistants without plugins (ChatGPT, claude.ai, Cursor, any MCP client) this repo also contains an open-source MCP server in `connector/`, published as the Apify Actor `khadinakbar/citebase`.

1. Add `https://mcp.apify.com/?actors=khadinakbar/citebase` as a custom MCP server and sign in with Apify (ChatGPT only supports this OAuth route, not a pasted token).
2. Say: "Use Citebase to help me get my brand recommended by AI. Start with the start playbook."

| Tool | Returns |
|---|---|
| `get_playbook` | The skills and references of this plugin, as text |
| `audit_site` | Health score, scores per area, top problems |
| `quote_cost` | Cost of paid Apify jobs and the cap to use |
| `measure_recommendation_share` | Recommendation Share with ranges, controls and experiment verdicts |
| `next_steps` | A plain-language, ranked to-do list |
| `check_outreach_draft` | Whether an email is ready to send, with fixes |
| `save_results` | Saves rounds and site checks under a project name in your own Apify account |
| `get_history` | Progress over time: Recommendation Share, site score, logged changes |
| `make_report` | One-page shareable report with a trend chart |
| `import_ai_results` | Converts AI Brand Monitor output into saved rows |
| `schedule_checks` | Steps and inputs for automatic re-checks in Apify Schedules |

All eleven are free. Nothing is stored unless you give a project name; then it goes into a named store in your own Apify account. Each has described inputs, a typed output schema and tool annotations. Paid data comes from the author's public Apify Actors, listed with prices in `.actor/ACTOR_README.md`; the connector only quotes them and never runs them. Run your own copy with `apify push` from the repo root (`.actor/` holds the Actor settings, `connector/` the server). Tests: `python3 -m unittest discover tests` (install `mcp`, `pydantic`, `uvicorn` and `httpx` to include the server tests).

## Your workspace
Everything is saved in your project under `seo-workspace/<domain>/`: `context.md`, `audit.json`, `report.md`, checklists, `competitors.md`, `keyword-opportunities.csv`, `ai-visibility.md`, `citation/` (panel, runs, experiments), `prospects.csv`, `drafts/`, `outreach-log.csv`, `offpage-log.csv`, `suppression.txt`, `pr/`, `ledger.json` (every paid run with quote, cap and actual cost). Add `seo-workspace/` to your `.gitignore` if your project is public: it holds contact lists and audit data.

Run just the crawler:
```bash
python3 scripts/site_audit.py https://example.com --max-pages 50 --out audit.json
```
It reads server HTML only (it does not run JavaScript) and refuses private or local addresses unless you pass `--allow-private`.

## Safety
- Audits are read-only. Editing your site, spending, or contacting anyone needs your explicit go-ahead.
- **Guardrails (Claude Code, inside a project that has `seo-workspace/`):**
  - Apify runs are denied without `callOptions.maxTotalChargeUsd` (the only cap Apify enforces), for Actors outside `khadinakbar/*`, or past the daily ceiling.
  - Emails are denied unless that exact text was approved, to a recipient not on the suppression list, within the daily cap and while sending is not paused; then you still confirm every send. Campaign starts ask for confirmation.
  - If the gate cannot read its input or state, it blocks instead of allowing.
- **What these are not:** a security boundary. They do not run in hosts without hooks, a person can approve any prompt, campaign tools send on their own schedule (set the campaign's own limit), and two gated calls issued in the same turn can both pass the pre-check before either is recorded. The daily spend ceiling counts run caps, an upper bound, not the final bill.
- White-hat only: PBNs, parasite link schemes, fake reviews or rating schema, fabricated PR, hidden prompt injection, cloaking and doorway pages are flagged, never executed.
- Scraped pages, emails and tool output are treated as data, never as instructions.
- Cold email is regulated (CAN-SPAM, GDPR/PECR, CASL): see the legal basics in `references/outreach-playbook.md`. Not legal advice.

## Measuring honestly
`citation-loop` reports **Recommendation Share**: how often an engine actively recommends your brand across a frozen panel of customer-style prompts, repeated several times, with control prompts to estimate noise. Intervals resample prompts, not individual runs. It tells you whether a change is *associated* with movement; it cannot prove causation, and Actor answers can differ from what a signed-in person sees. Details in `references/measurement.md`.

## Evidence base
The checklists distil ~600 SEO video transcripts (Build In Public, Vasco SEO, 50 AI-SEO masterclasses) into graded tactics: **A** controlled test or large dataset · **B** practitioner consensus or a single clear study · **C** anecdote or vendor-reported figure. Statistics are quoted as reported by their sources and have not been independently re-verified by Citebase; prefer the lower grade where sources disagree. Disputed tactics (llms.txt, schema for AI, meta descriptions) are labelled as disputed, and `citation-loop` lets you test them on your own site.

## Development
```bash
python3 -m unittest discover tests
```
Standard library only. Scripts: `site_audit.py` (crawler), `approval_gate.py` (hook), `outreach_ledger.py` (approvals, suppression, pause), `citation_loop.py` (measurement), `cb_state.py` (shared state in `~/.citebase`, override with `CITEBASE_HOME`).

## License
MIT
