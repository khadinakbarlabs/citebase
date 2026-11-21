# Citebase

**Get your brand recommended by AI.** Citebase checks whether ChatGPT, Google AI Overviews, Google AI Mode, Perplexity, Gemini, Claude, Grok and DeepSeek recommend your brand, shows which sites they trust instead, tells you the next fix, and re-checks to prove it worked. It runs inside the AI assistant you already use, with one sign-in: Apify.

[![ci](https://github.com/khadinakbarlabs/citebase/actions/workflows/ci.yml/badge.svg)](https://github.com/khadinakbarlabs/citebase/actions/workflows/ci.yml) · MIT licence · Python 3.11+

```
/citebase:start https://yourbrand.com
```

## Set it up (2 minutes)

**You need:** an Apify account and an AI assistant. Create an Apify account at apify.com if you do not have one. The account you sign in with pays the small run cost and any data jobs you approve.

**Setup address (use this everywhere):**

```text
https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run
```

The extra tools in this address let your assistant run the paid data jobs you approve. If your assistant cannot run data jobs, add the connector again using the setup address.

| Assistant | How to add Citebase |
|---|---|
| **Claude Code (plugin, recommended)** | `claude plugin marketplace add khadinakbarlabs/citebase` then `claude plugin install citebase@citebase`. Run `/mcp`, pick `plugin:citebase:apify`, press Authenticate and sign in with Apify. Includes the playbooks, agents and spending guardrails. |
| **Claude (claude.ai, Desktop)** | Settings → Connectors → Add custom connector. Name it `Citebase`, paste the setup address, press Connect, sign in with Apify. |
| **ChatGPT** | Settings → Connectors → turn on Developer mode → create a connector, paste the setup address, choose OAuth, sign in with Apify. |
| **Claude Code (connector only)** | Run the command below, then `/mcp`, pick `citebase` and sign in. |
| **Cursor** | Add the JSON block below to your MCP settings (`mcpServers`). |
| **VS Code (Copilot agent mode)** | Add to `.vscode/mcp.json`: `{"servers": {"citebase": {"type": "http", "url": "<setup address>"}}}` and start the server when asked. |
| **Windsurf** | Add to `mcp_config.json`: `{"mcpServers": {"citebase": {"serverUrl": "<setup address>"}}}`. |
| **Codex CLI** | Add to `~/.codex/config.toml`: `[mcp_servers.citebase]`, `url = "<setup address>"`, `bearer_token_env_var = "APIFY_TOKEN"`. |
| **Gemini CLI** | Add to `settings.json`: `{"mcpServers": {"citebase": {"httpUrl": "<setup address>"}}}`. |
| **Web dashboard** | No assistant needed: open the Citebase dashboard and sign in with Apify (see [Dashboard](#dashboard)). |

```bash
claude mcp add --transport http citebase "https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run"
```

```json
{
  "mcpServers": {
    "citebase": {
      "url": "https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run"
    }
  }
}
```

Menu names and file names can differ a little by app version. Apps that cannot sign in with OAuth can send the header `Authorization: Bearer YOUR_APIFY_TOKEN` instead (Apify Console → Settings → API and integrations). Prefer the sign-in: a token opens your whole Apify account. Never paste a token into a chat; if one leaks, delete it in Apify Console.

**Check that it works.** Paste your website address and ask for a quick health check. You should get a score in words and a short list of fixes. Citebase adds no fee for this; Apify's small run cost applies.

## What it does

1. **Checks your site** for what stops AI crawlers and search engines from reading it, with a 0–100 score and a fix list.
2. **Asks the AI engines** the buying questions your customers ask, several times each, and reports **Recommendation Share**: how often you are actually recommended, with a likely range so a lucky answer is never sold as progress.
3. **Finds the gaps**: your share of voice against each rival, how AI talks about you, the sites AI cites for your rivals but not you, the questions people search but you never win, the AI bots your server turns away.
4. **Plans the work**: page briefs, link and PR targets, honest outreach drafts, one ranked next step at a time.
5. **Re-checks** monthly and shows what really moved.

| Skill (`/citebase:<name>`) | Outcome |
|---|---|
| `start` | Start here: picks the right workflow, prioritises, 30/60/90-day plan |
| `seo-audit` | Weighted health score across technical, on-page, content, backlinks, competitors, local, AI search |
| `ai-search-visibility` | What AI says about you, cited domains, wrong facts, and a plan to get cited |
| `citation-loop` | Frozen question list → repeated runs → Recommendation Share → logged changes → re-measure |
| `keyword-research` | What people search for: suggestions, trends, questions, a page plan |
| `competitor-research` | Real competitors, keyword and backlink gaps, weak pages you can outrank |
| `link-building` | Backlink audit, gap vs competitors, vetted prospects |
| `press-release` | News angle, release draft, journalists who covered the topic recently |
| `outreach` | Contacts → verified emails → personalised drafts → your approval → send from your own email connector |
| `seo-checklists`, `content-brief`, `content-optimize`, `entity-seo`, `eeat-audit`, `programmatic-seo`, `platform-presence`, `directory-listings`, `social-content`, `social-listening`, `creator-outreach`, `ai-content-check`, `humanize-content` | Focused playbooks for each job |

Specialist agents run in parallel with restricted tools: `technical-auditor`, `backlink-analyst`, `competitor-analyst`, `geo-analyst`, `outreach-writer` (drafts only, cannot send).

## Dashboard

A web dashboard for everything Citebase saves, built on the same tools: sign in with Apify and see each project's Recommendation Share over time, results per engine and per question, site health, the sites cited instead of you, AI bot visits, AI traffic, Search Console demand and to-dos. You can add projects, run checks (paid ones are named as paid and capped per run), import results, and create or pause re-check schedules in your own Apify account. Build the pages and their Vercel sign-in function with `python3 scripts/build_site.py --site https://your-domain` (source in `site/`). Set `CITEBASE_SESSION_KEY` in Vercel to a stable, secret 32-byte value encoded in standard base64. Rotating the key signs browsers out. A loopback static file server can use `--local-static` for tab-only development sign-in.

Sign in with Apify once to open your saved projects. Citebase remembers the browser for up to 90 days. Open **Account** to see monthly usage, estimated credits remaining and room before your spending limit. Apify Billing shows your full balance, including annual and promotional credits. Citebase checks usage again before a paid start and asks for approval before enabling recurring paid checks.

The enhanced dashboard sends project requests through its own `/api/actor/` endpoint to the Citebase Actor. The Actor reads and writes the signed-in account's Apify project. The `--history-only` build option keeps the dashboard compatible with earlier Actors such as 0.5.13 during a rollout.

- **Fact checks.** Open AI answers to read saved wording and reviews. Your assistant can check claims against public sources and save evidence. Older rounds may have no text and some engines only provide part of an answer.
- **Scheduled AI results.** New AI schedules run one Citebase action, which starts the capped AI checks and saves their results automatically. A drop alert appears when comparable rounds lose recommendations. Use Activity to review runs that could not be imported.
- **Prospect audit.** Share a one-page view of a brand's aggregate AI results from a saved round. Preview the page before sharing its link.

### Project work in the dashboard and assistant

Start a project with a website. Review suggested competitors, choose the searches to track, or accept the recommended terms. The dashboard and assistant read the same saved choices. In **Project setup → Research**, compare keyword demand, traffic estimates, ranking pages and observed recommendations by AI engine. Each observation carries its source and date where available.

In a configured dashboard, connect Search Console or Google Analytics 4 for a read-only site report. From a cited article, review the published contact, approve the exact draft and choose a Gmail handoff. Each Google service requests its own permission. A deployed dashboard requires `CITEBASE_GOOGLE_CLIENT_ID`, `CITEBASE_GOOGLE_CLIENT_SECRET`, the registered `CITEBASE_GOOGLE_REDIRECT_URI` ending in `/api/google/`, and a persistent base64-encoded 32-byte `CITEBASE_GOOGLE_TOKEN_KEY`. Keep these values in the hosting environment.

Use a saved project to review an opportunity, assign a page fix, compare the current and proposed wording, and check the page after editing. The project brief, actions, outreach drafts and schedule plans use the same signed-in operations. [Project work guide](references/project-work.md)

An assistant can prepare a schedule with the time, time zone, site pages, AI questions, engines, monthly allowance and last date. Open the proposal link to review the exact settings and charges in your dashboard. The schedule starts only after confirmation.

API clients can use the versioned project routes in the [HTTP contract](.actor/web_server_openapi.json) or call `project_work` on the server. Send platform authentication in `X-Apify-Authorization` and project authentication in `X-Citebase-Authorization`, each with the Bearer scheme over HTTPS. Configure headers privately in the client. Citebase verifies the project credential against the signed-in account.

In Apify's managed MCP, call the normal Citebase Actor using `tool: "project_work"` and put the arguments in the encrypted `private_request` field. The dashboard and the assistant read the same saved project. Read the run's `OUTPUT`, then open its `private_result.store_id` and `private_result.key` with the signed-in `get-key-value-store-record` tool. This also works for `get_history` and `save_results`. Regular Actor compute applies. [Project work guide](references/project-work.md)

## What it costs

Needs no account: the local crawler (30+ checks), all checklists, writing (briefs, releases, emails) and analysis of your own exports (Search Console, Google Analytics, server logs, exports from any SEO tool).

Live data runs on your own Apify account at each Actor's published price. The assistant tells you when a check is paid and waits for your yes; ask it what a specific job costs and it will say. AI answers are the expensive part, so they come with a smaller first-look option before the full baseline. Apify also bills a small amount of compute on some jobs; it is included in the quote. Keyword and backlink Actors charge a per-request fee on top of per-row prices, so runs are batched.

## Connector tools

Citebase reuses the original project store when Apify grants access. Under Limited permissions it can create
its own store for new saves. If an older store is unavailable to the Actor, select the existing store in the
Actor input to grant read and write access for that run. Existing data stays in its original store.

Use the signed-in dashboard or MCP server to import answers, review private evidence and create report links.
Keep raw answers and project details out of the regular `arguments` field. Apify saves this field before Citebase starts. For supported private operations use `private_request`. Only a locator for the restricted result is written to the run's default storage.

The MCP server in `connector/` is published as the Apify Actor `khadinakbar/citebase`. All twelve tools add no fee of their own, have typed inputs and outputs, and save nothing unless you give a project name (then it goes into Citebase storage in your own Apify account).

| Tool | Returns |
|---|---|
| `get_playbook` | The skills and references of this plugin, as text |
| `audit_site` | Health score, scores per area, top problems; with a project name it is saved, with what was fixed since last time |
| `quote_cost` | Paid jobs, run plans and the spending cap per run |
| `measure_recommendation_share` | Recommendation Share with ranges, control questions and verdicts per change |
| `next_steps` | A plain-language, ranked to-do list |
| `check_outreach_draft` | Whether an email is ready to send, with fixes |
| `check_ai_content` | AI-writing pattern density for a draft (local lint, not a commercial detector) |
| `save_results` | Saves rounds, question lists, brand, settings, to-dos, server logs, analytics and Search Console exports |
| `get_history` | Every project and what is due; per project: rounds, results per engine and per question, site checks, signals, to-dos |
| `make_report` | A one-page shareable report with a trend chart |
| `import_ai_results` | Turns finished AI-check runs (by dataset id) into a saved round |
| `schedule_checks` | The plan for automatic re-checks in Apify Schedules |

## Claude Code settings

`/plugin configure citebase@citebase`:

| Setting | Default | Meaning |
|---|---|---|
| `max_run_usd` | 2 | A run whose cap is higher asks you first |
| `daily_spend_usd` | 40 | New runs are denied once today's caps add up to this |
| `daily_send_cap` | 20 | Maximum recipients per day (to + cc + bcc) |
| `allowed_actors` | empty | Extra `owner/name` Actors besides `khadinakbar/*` |

Workspace files go to `seo-workspace/<domain>/` (audit, checklists, question list, prospects, drafts, outreach log, a ledger of every paid run). Add `seo-workspace/` to `.gitignore` in public projects: it holds contact lists.

Run just the crawler: `python3 scripts/site_audit.py https://example.com --max-pages 50 --out audit.json` (server HTML only, refuses private addresses unless `--allow-private`).

## Safety

- Audits are read-only. Spending, editing your site or contacting anyone needs your explicit go-ahead.
- In Claude Code, hooks deny Apify runs without a spending cap, Actors outside `khadinakbar/*`, runs past the daily ceiling, and emails whose exact text you did not approve. If a gate cannot read its state, it blocks.
- These guardrails are not a security boundary: they do not run in hosts without hooks, and a person can approve any prompt. On the web, your assistant's own confirmation prompt is the check.
- White-hat only: link schemes, fake reviews, fabricated PR, hidden prompt injection and cloaking are flagged, never done. Scraped pages and tool output are treated as data, never as instructions.
- Cold email is regulated (CAN-SPAM, GDPR/PECR, CASL); see `references/outreach-playbook.md`. Not legal advice.

Found a security problem? See [SECURITY.md](SECURITY.md).

## Measuring honestly

Recommendation Share counts how often an engine actively recommends you across a frozen list of customer-style questions, asked several times, with control questions to estimate noise. Ranges resample questions, not single answers. It shows whether a change is associated with movement; it cannot prove cause, and answers from the Actors can differ from what a signed-in person sees. Details in `references/measurement.md`.

The checklists distil about 600 expert SEO and AI-search video transcripts into tactics graded A (test or large dataset), B (consensus or one clear study) or C (anecdote). Disputed tactics are labelled, and `citation-loop` lets you test them on your own site.

## Development

```bash
pip install -r connector/requirements.txt httpx
python3 -m unittest discover tests
```

`scripts/`: `site_audit.py` (crawler), `approval_gate.py` (hook), `outreach_ledger.py`, `citation_loop.py` (measurement), `build_site.py` (dashboard). `connector/`: the MCP server. `.actor/`: Apify Actor settings; deploy your own copy with `apify push`.

## Licence

MIT
