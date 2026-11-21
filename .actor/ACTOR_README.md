## Connect Citebase to your AI assistant (MCP setup and sign-in)

Citebase is an MCP server. Add it once, sign in once, then ask for help in plain words.

**You need:** an Apify account and an assistant that supports MCP connectors (Claude, ChatGPT, Cursor and others). Create an Apify account at apify.com if you do not have one. The account you sign in with pays the small run cost and any data jobs you approve.

**Setup address (use this everywhere):**

```text
https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run
```

The extra tools in this address let your assistant run the paid data jobs you approve. On the web nothing but your assistant's own confirmation prompt stops a run, so approve only the Actor and the cost it quoted. If your assistant cannot run data jobs, add the connector again using the setup address.

**Two ways to sign in**

| Way | Use it when | What you do |
|---|---|---|
| Apify sign-in (OAuth), recommended | Your assistant has a "Connect" or "Sign in" button. ChatGPT only supports this way. | Add the setup address, press Connect, sign in to Apify, press Allow. No token to copy. |
| Apify API token | Your assistant or script cannot do OAuth | Send the header `Authorization: Bearer YOUR_APIFY_TOKEN`. Find the token in Apify Console under Settings, then API and integrations. |

**Steps for each assistant** (menu names can differ a little by plan and app version)

- **Claude (claude.ai and Claude Desktop):** open Settings, then Connectors, then Add custom connector. Name it `Citebase`, paste the setup address, press Connect and sign in to Apify.
- **ChatGPT:** open Settings, then Connectors, turn on Developer mode, create a new connector, paste the setup address, choose OAuth, then sign in to Apify.
- **Claude Code:** run this in your terminal, then type `/mcp` inside Claude Code, pick `citebase` and sign in.

  ```bash
  claude mcp add --transport http citebase "https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run"
  ```

  To use a token instead, add `--header "Authorization: Bearer YOUR_APIFY_TOKEN"` to that command.
- **Cursor and other apps that use a JSON settings file:** add this block. Leave out `headers` to sign in with OAuth when the app supports it. Field names can differ slightly by app.

  ```json
  {
    "mcpServers": {
      "citebase": {
        "url": "https://mcp.apify.com/?actors=khadinakbar/citebase&tools=fetch-actor-details,call-actor,get-actor-run,get-dataset-items,get-key-value-store-record,abort-actor-run",
        "headers": { "Authorization": "Bearer YOUR_APIFY_TOKEN" }
      }
    }
  }
  ```
- **VS Code (Copilot agent mode):** add to `.vscode/mcp.json`: `{"servers": {"citebase": {"type": "http", "url": "<setup address>"}}}`, then start the server when VS Code asks.
- **Windsurf:** add to `mcp_config.json`: `{"mcpServers": {"citebase": {"serverUrl": "<setup address>"}}}`.
- **Codex CLI:** add to `~/.codex/config.toml`: a `[mcp_servers.citebase]` table with `url = "<setup address>"` and `bearer_token_env_var = "APIFY_TOKEN"`.
- **Gemini CLI:** add to `settings.json`: `{"mcpServers": {"citebase": {"httpUrl": "<setup address>"}}}`.
- **Direct connection (advanced):** use this Actor's own Standby address (the one ending in `/mcp`, shown on this Actor's API tab in Apify Console). It needs the token header and does not offer a sign-in button.

**Check that it works.** Paste your website address and ask for a quick health check. Your assistant should come back with a score in words and a short list of fixes. Citebase adds no fee for this; Apify's small run cost applies.

**Keep your token safe.**
- Prefer the sign-in route. A token gives access to your whole Apify account.
- Never type a token into a chat or into a tool field. Citebase never asks for passwords or keys.
- If a token leaks, delete it in Apify Console and make a new one.

If sign-in fails, see the troubleshooting table near the end of this page.

## What is Citebase?

Citebase is a connector that helps a brand get **recommended and cited by AI assistants** such as ChatGPT, Claude, Gemini and Perplexity. You connect it to your own AI assistant and ask for help in plain words. It returns step-by-step guidelines, a website health check, price quotes for paid data jobs, "how often does AI recommend me" results, a short to-do list, your share of voice against rivals, a check for outreach emails, saved history, a shareable report and a plan for automatic re-checks. Citebase itself adds no fee; the data jobs cost money and come from separate Actors listed below, always with a price quote and a spending cap first.

Built for founders, marketers and small agencies who want to show up when people ask an AI "what is the best X for Y?" and do not want to learn SEO jargon first.

## Choose Citebase when / do not use it when

**Choose Citebase when you want to:**
- check a website for search and AI-readiness problems, with a score and a plain list of fixes;
- find out whether AI assistants recommend your brand, repeat the test later and see whether your changes helped;
- plan links, press and outreach with checklists, and check an email draft before it is sent;
- know what to do next, in plain words, ranked, with who does it and how long it takes;
- work from one assistant (ChatGPT, Claude, Cursor or any assistant that supports MCP connectors) without five separate SEO tools.

**Do not use it to:**
- scrape websites or collect data yourself (use the paid Actors listed below, through Citebase's quotes);
- send email (it only checks drafts and never sends);
- read private, local or password-protected pages (the site check refuses them);
- get live Google rankings by itself (that is the `serp_page` job).

## How a session works: from a website address to a plan

1. **Start.** You paste your website address. The assistant reads the `start` playbook and checks your site first; it asks only what it still needs.
2. **Check the site.** `audit_site` scores the site and lists the top problems.
3. **Price the research.** `quote_cost` totals the paid data jobs (search results, keywords, backlinks, AI answers) and gives a spending cap.
4. **Research.** With your yes, the assistant runs the Actors below with that cap.
5. **Test the AI.** It builds a fixed list of questions customers might ask, collects the AI answers several times and sends them to `measure_recommendation_share`.
6. **Plan.** `next_steps` turns the audit and results into a ranked to-do list.
7. **Reach out.** For links and press, the assistant drafts emails and runs `check_outreach_draft` before asking you to approve each one.
8. **Re-check.** After about 30 days it repeats the test to see whether the changes worked.

## Tools

| Tool | What it returns | Price |
|---|---|---|
| `get_playbook` | Citebase's guidelines: the list of names, or one playbook's text (22 workflows and 12 guides and checklists) | No Citebase fee |
| `audit_site` | 0-100 health score, scores per area, the top problems with example pages. With a project name it is saved and shows what was fixed since the last check | No Citebase fee |
| `quote_cost` | Cost of each paid job, the total and the spending cap to use | No Citebase fee |
| `get_account_usage` | Your signed-in account’s monthly Apify usage, included credits remaining and spending limit where available. Open Apify Billing for your full balance. | No Citebase fee |
| `measure_recommendation_share` | How often AI recommends the brand, with ranges, a noise check and a verdict per change | No Citebase fee |
| `next_steps` | Ranked to-do list: what, why, who, how long | No Citebase fee |
| `check_outreach_draft` | Ready yes/no, problems to fix, warnings, a fingerprint of the exact text | No Citebase fee |
| `check_ai_content` | AI-writing pattern density for a draft (local style lint; not a commercial detector) | No Citebase fee |
| `save_results` | Saves AI-answer rounds and site checks under a project name in your own Apify account | No Citebase fee |
| `get_history` | With no project: every saved project and what is due now. With a project: Recommendation Share and site score over time, settings, to-dos and logged changes | No Citebase fee |
| `make_report` | A one-page report with a trend chart and a link you can share | No Citebase fee |
| `import_ai_results` | Converts results of AI Brand Monitor, Google AI Overviews, Google AI Mode and the tracker Actors into saved rows; a first round goes in with one call (send the questions and brand with it); flags close calls and rounds that were asked under different conditions | No Citebase fee |
| `schedule_checks` | Cron text, the Actor runs to add (assistants repeated 1 to 5 times, Google answers once) and the worst-case monthly cost; the website comes from the saved project | No Citebase fee |

## What one result contains

`audit_site` returns one object:

| Field | Type | Meaning | Example |
|---|---|---|---|
| `site` | text | The site that was checked | `https://example.com` |
| `headline` | text | The result in one sentence | "https://example.com scores 66 out of 100 from 3 pages" |
| `status` | text | `ok`, `partial` (stopped at the time limit) or `unreadable` (site could not be read: no score) | `ok` |
| `pages_checked` | number | Pages read | `3` |
| `health_score` | number or null | 0-100, higher is better. Null when the site could not be read | `66` |
| `subscores` | object | 0-100 per area | `{"technical": 70, "on-page": 55}` |
| `counts` | object | Checks failed, warned, passed | `{"fail": 2, "warn": 5, "pass": 20}` |
| `problems` | list | Up to 25, worst first: level, area, check, detail, example pages | see below |
| `passed` | list | Names of checks that passed | `["HTTP redirects to HTTPS"]` |
| `limits` | text | What the check cannot see | "no JavaScript is run" |
| `saved` | object or null | With a project name: where it was saved, the score change, and the checks fixed, new and still open since the last check | `{"changes": {"fixed": ["XML sitemap"]}}` |

```json
{
  "ok": true,
  "tool": "get_history",
  "result": {
    "project": null,
    "projects": [],
    "markdown": "# Your saved projects\n\nNothing saved yet.",
    "next": "No projects yet. Start with audit_site and pass a project name (for example the site's name) so the check is saved."
  }
}
```

Every tool has a typed output schema, so an assistant can read the exact shape before calling.

## Quick start and input

1. Connect your assistant using the steps at the top of this page.
2. Paste your website address and ask for a quick health check.

Plain JSON call, `POST /run` (what an assistant sends through `mcp.apify.com`):

```json
{"tool": "audit_site", "arguments": {"url": "https://example.com", "max_pages": 10}}
```

You can also run this Actor normally with the same two fields as input: `tool` (one of the twelve names, or `scheduled_check`: the site check plus report refresh, meant for an Apify Schedule) and `arguments` (a JSON object). A bad input ends the run as failed and the dataset item says what to fix.

Use the signed-in dashboard or MCP server to import answers, review private evidence and create report links.
For a direct project API request, configure the platform bearer in `X-Apify-Authorization` and the project bearer in `X-Citebase-Authorization` in your HTTPS client's private settings.
For private project work through Apify's managed MCP, use `call-actor` with an encrypted request such as `{"tool":"project_work","private_request":{"project":"acme-site","operation":"project_focus"}}`. Use the same field for `save_results` and `get_history`. Keep project details out of regular `arguments`. Read `OUTPUT` with the signed-in `get-key-value-store-record` tool, then read the record identified by `private_result.store_id` and `private_result.key`. This normal Actor run incurs Apify compute. The dashboard handles schedule changes with the customer's schedule permissions.

## Actors Citebase uses for paid data

For one-off checks, your assistant gets a spending cap, asks for your approval and starts the run on your Apify account. If you create a recurring AI schedule, its Citebase action starts the capped checks and saves their results. All listed Actors are owned by the same author.

| Job name | Actor | What it gets you |
|---|---|---|
| `site_audit` | [Complete SEO Audit](https://apify.com/khadinakbar/complete-seo-audit) | Technical site audit: crawl rules, redirects, headings, links, structured data (server HTML, no JavaScript) |
| `serp_page` | [Google SERP Scraper](https://apify.com/khadinakbar/scrape-google-serp) | Google search results pages: who ranks, questions people ask, search features |
| `keyword_ideas` | [Keyword Research](https://apify.com/khadinakbar/dataforseo-keyword-research) | Keyword ideas with search volume and difficulty |
| `keyword_volume` | [Keyword Research](https://apify.com/khadinakbar/dataforseo-keyword-research) | Exact search volume, cost per click and competition for keywords you already have |
| `backlinks` | [Website Backlink Checker](https://apify.com/khadinakbar/website-backlink-checker) | Who links to a site: backlinks, referring domains and anchor text |
| `backlink_prospects` | [Backlink Opportunity Finder](https://apify.com/khadinakbar/backlink-opportunity-finder) | Link prospects: resource pages, best-of lists and guest-post sites |
| `ai_brand_check` | [AI Brand Monitor](https://apify.com/khadinakbar/ai-search-brand-monitor) | Does an AI assistant mention or recommend your brand? Checks ChatGPT, Perplexity, Claude, Gemini, Grok and DeepSeek answers |
| `ai_page_citation` | [AI Search Visibility Tracker](https://apify.com/khadinakbar/ai-search-visibility-tracker) | Which of your pages AI assistants cite, and which competitors they cite instead |
| `ai_citation_scan` | [AI Citations Tracker](https://apify.com/khadinakbar/ai-citations-tracker) | The sources behind a Perplexity answer |
| `ai_overview` | [Google AI Overviews Scraper](https://apify.com/khadinakbar/google-ai-overviews-scraper) | Google AI Overviews for a search, and whether your domain is among the sources |
| `ai_mode` | [Google AI Mode Scraper](https://apify.com/khadinakbar/google-ai-mode-scraper) | Google AI Mode answers and their citations |
| `website_contact` | [Bulk Website Contact Extractor](https://apify.com/khadinakbar/bulk-website-contact-extractor) | Public emails and social links from a website (for outreach) |
| `email_verify` | [Email Address Validator](https://apify.com/khadinakbar/email-address-validator) | Checks that an email address is real before you send |
| `news_article` | [Google News Scraper](https://apify.com/khadinakbar/google-news-scraper) | News coverage and the journalists who wrote it (for PR) |
| `reddit_result` | [Reddit Posts and Comments Scraper](https://apify.com/khadinakbar/reddit-posts-comments-scraper) | Reddit posts and comments on a topic |
| `youtube_result` | [YouTube Search Scraper](https://apify.com/khadinakbar/youtube-search-scraper) | YouTube videos and channels on a topic |
| `review_site` | [Software Reviews Scraper](https://apify.com/khadinakbar/software-reviews-all-in-one-scraper) | Software reviews from G2, Capterra and TrustRadius |
| `trustpilot_review` | [Trustpilot Reviews Scraper](https://apify.com/khadinakbar/trustpilot-reviews-scraper) | Trustpilot ratings, reviews and replies |
| `google_trend` | [Google Trends](https://apify.com/khadinakbar/google-trends-scraper) | Interest over time, regions and rising searches for a topic |
| `search_suggestion` | [Google Autocomplete Suggestions](https://apify.com/khadinakbar/google-autocomplete-api) | What people start typing in Google for a topic |
| `longtail_keyword` | [Long-Tail Keyword Ideas](https://apify.com/khadinakbar/keyword-fanout-longtail) | Many specific long-tail phrases grown from a seed word |
| `keyword_difficulty` | [Keyword Difficulty Checker](https://apify.com/khadinakbar/ahrefs-keyword-difficulty-checker) | How hard each keyword is to rank for, in batches |
| `keyword_metrics` | [Keyword Metrics](https://apify.com/khadinakbar/ahrefs-keyword-explorer) | Search numbers, matching terms and related terms for keywords |
| `content_brief` | [SEO Content Brief Generator](https://apify.com/khadinakbar/surfer-seo-alternative) | A page outline built from what the top results cover |
| `quora_question` | [Quora Scraper](https://apify.com/khadinakbar/quora-scraper) | Real questions and answers people post on a topic |
| `reddit_search` | [Reddit Search Scraper](https://apify.com/khadinakbar/reddit-search-scraper) | Reddit posts that match a search, in people's own words |
| `forum_search` | [Google Forums Search](https://apify.com/khadinakbar/google-forums-search-scraper) | Public forum discussions Google shows for a question |
| `youtube_trending` | [YouTube Trending Videos](https://apify.com/khadinakbar/youtube-trending-videos-scraper) | Videos on YouTube's trending charts by country |
| `youtube_transcript` | [YouTube Transcript Extractor](https://apify.com/khadinakbar/youtube-transcript-extractor) | What is said in a video, as text |
| `youtube_channel_stats` | [YouTube Channel Statistics](https://apify.com/khadinakbar/youtube-channel-statistics-scraper) | Subscribers, views and activity of channels you might approach |
| `youtube_comment` | [YouTube Comments Scraper](https://apify.com/khadinakbar/youtube-comments-scraper) | What viewers say under a video |
| `creator_report` | [Creator Intelligence Report](https://apify.com/khadinakbar/influencer-marketing-intelligence-scraper) | A report on a creator's audience fit and recent posts |
| `newsletter_post` | [Substack Posts Scraper](https://apify.com/khadinakbar/substack-posts-scraper) | Posts from newsletters on your topic |
| `traffic_rank` | [Website Traffic and Rank](https://apify.com/khadinakbar/similarweb-traffic-rank-scraper) | Estimated traffic and rank of a website |
| `domain_ranked_keywords` | [Keyword and Backlink Analyzer](https://apify.com/khadinakbar/ahrefs-alternative) | Competitor ranking pages, search positions and estimated organic visits for individual keywords |
| `tech_stack` | [Website Technology Detector](https://apify.com/khadinakbar/website-tech-stack-detector) | What a site is built with |
| `bing_rank` | [Bing Rank Tracker](https://apify.com/khadinakbar/bing-rank-tracker) | Where a domain ranks on Bing for your keywords |
| `crawl_page` | [Website SEO Crawler](https://apify.com/khadinakbar/website-seo-spider) | A full-site crawl, page by page |
| `local_rank` | [Local Rank Tracker](https://apify.com/khadinakbar/local-rank-tracker) | Where a business shows on the map around a location |
| `local_pack` | [Google Local Pack](https://apify.com/khadinakbar/google-local-pack-api) | Who appears in Google's map results for a search |
| `agency_listing` | [Clutch Scraper](https://apify.com/khadinakbar/clutch-scraper) | Agencies and companies in a Clutch category |

Each job is priced before it runs: ask your assistant what a job costs and it will tell you. Each Actor's own Store page shows its current pricing. Apify also bills a small amount of compute on some jobs; it is included in the quote.

**Easy bundles.** You do not need to pick jobs yourself. Ask for a pack and the assistant prices it in one go:

| Pack | What you get |
|---|---|
| `starter` | A first look at a website |
| `keywords` | What people search for on one topic |
| `competitors` | How rivals look and rank |
| `creators` | YouTube creators worth approaching |
| `local` | Where a business shows on the map |
| `ai_check_pilot` | A first look at whether AI recommends you (30 questions, 3 assistants, once) |
| `ai_check` | Does AI recommend you (30 questions, 3 assistants, 3 times) |


## Pricing and cost example

- **Citebase itself:** the twelve tools add no fee of their own. The connector has no start fee and no minimum. Everything that runs costs what Apify charges for compute plus the data jobs below.
- **Platform usage:** running this Actor uses a small amount of Apify platform compute. It is paid by the account that starts the run, which is yours when you connect with your own sign-in. A 15-page site check takes under a minute.
- **Paid data Actors:** each is priced per result on your account; each Actor's Store page lists its price. `quote_cost` totals them before anything runs.

| Example | What it includes |
|---|---|
| Quick audit | 1 site audit + 15 results pages |
| Full audit | site audit, keywords, backlinks for you and 3 competitors, link prospects, a small AI check |
| AI recommendation baseline | 30 questions x 3 assistants x 3 repeats + 20 Google AI Overviews |

Request fees dominate small keyword and backlink jobs, so batch them into one run.

## Use with an AI agent through Apify MCP

Prompt to try: *"Use Citebase to check example.com, tell me the three most important fixes in plain words, and price a Google results check for my top 15 keywords."*

- **Inputs:** every tool field is described, with an example and limits, and job names are a closed list.
- **Failures:** errors are plain sentences that say what to fix, for example an unknown job lists the valid names.
- **Size:** results are returned whole. The longest playbook is about 2,300 tokens, so nothing needs paging. For paid Actors use `get-dataset-items` with `limit` and `offset`.
- **Run only what was quoted:** the assistant should run only the Actor and the spending cap that `quote_cost` gives you, after your yes.
- **No automatic guard on the web:** the assistant is told to quote costs and ask you before spending or sending. Say yes only to what you understand.

## Limits, reliability and troubleshooting

- Site check: up to 30 pages, public sites only, server HTML only (no JavaScript), about a minute at most.
- Nothing is saved unless you give a project name. Saved projects live in a named key-value store in your own Apify account; up to 100 projects and 160 rounds each.
- Requests are limited to 2 MB.
- Save to one project from one conversation at a time. Two saves to the same project at the same moment from different sessions can overwrite each other.

| Symptom | Likely cause | Fix |
|---|---|---|
| "Cannot reach" on the site check | The address is private, blocked or wrong | Use a public address such as `example.com` |
| "Input should be ..." on `quote_cost` | The job name is not on the list | Use a name from the table above |
| "Request is too large" | More than 2 MB was sent | Send fewer rows |
| 401 "api-token-missing" | Connected directly without a token | Use the setup address, or pass your Apify token |
| ChatGPT will not accept a token | Custom connectors there use OAuth only | Use the setup address and sign in |
| The assistant says it has no tool to run data jobs | The connector was added without the run tools | Add the connector again using the setup address |

## Evidence and freshness

The release checklist covers good, bad, oversized and hostile inputs, parallel calls and all three ways in (Standby, `/run` and normal runs). It is a check, not a guarantee of future reliability. The version history is in the changelog.

## Frequently asked questions

**What does it cost?** Citebase adds no fee. You pay Apify's running cost and the data jobs you choose to run, each priced before it starts. Apify also bills a small amount of compute on some jobs; it is included in the quote.

**Does it store my data?** Only if you ask it to. With a project name, `save_results` keeps your rounds and site checks in a store named `citebase-projects` in the Apify account that runs the Actor (yours, when you connect with your own sign-in). The author cannot see it. Without a project name every call stands alone and nothing is kept. Reports are shared by link only: delete the record to stop sharing.

**Can it send emails for me?** No. It checks a draft and returns a fingerprint of the exact text. You or your mail connector send it.

**Which assistants work?** Any assistant that supports MCP connectors. ChatGPT needs the OAuth route through `mcp.apify.com`.

**How accurate is the AI check?** It uses search-enabled model endpoints, which can differ from what a signed-in person sees. Use the trend over time, not a single number, and run each question at least three times.

**Why not just ask the assistant directly?** An assistant alone has no live data and no fixed method. Citebase adds the guidelines, a repeatable measurement and the price controls.

## Related Actors and workflow steps

- Site problems: [Complete SEO Audit](https://apify.com/khadinakbar/complete-seo-audit) for a second opinion on the same site.
- Search results and questions people ask: [Google SERP Scraper](https://apify.com/khadinakbar/scrape-google-serp).
- Do AI assistants mention you: [AI Brand Monitor](https://apify.com/khadinakbar/ai-search-brand-monitor), then [AI Search Visibility Tracker](https://apify.com/khadinakbar/ai-search-visibility-tracker) for which pages get cited.
- Who links to you and your competitors: [Website Backlink Checker](https://apify.com/khadinakbar/website-backlink-checker).
- Contacts for outreach: [Bulk Website Contact Extractor](https://apify.com/khadinakbar/bulk-website-contact-extractor), then [Email Address Validator](https://apify.com/khadinakbar/email-address-validator) before you send.

## Legal, trademarks and responsible use

Use Citebase for honest marketing only. It does not support fake reviews, fabricated press, hidden prompt injection or other manipulation. Its outreach checks are not legal advice: follow email laws such as CAN-SPAM, GDPR and CASL. Do not collect personal data you have no basis to use.

ChatGPT is a trademark of OpenAI. This independent Actor is not affiliated with, associated with, or endorsed by OpenAI.

Claude is a trademark of Anthropic. This independent Actor is not affiliated with, associated with, or endorsed by Anthropic.

Google, Gemini and YouTube are trademarks of Google LLC. This independent Actor is not affiliated with, associated with, or endorsed by Google.

Perplexity is a trademark of Perplexity AI. This independent Actor is not affiliated with, associated with, or endorsed by Perplexity AI.

Reddit is a trademark of Reddit, Inc. This independent Actor is not affiliated with, associated with, or endorsed by Reddit.

Trustpilot is a trademark of Trustpilot A/S. This independent Actor is not affiliated with, associated with, or endorsed by Trustpilot.

G2, Capterra and TrustRadius are trademarks of their respective owners. This independent Actor is not affiliated with, associated with, or endorsed by them.
