# Changelog

## 0.4
- Eleven tools with no Citebase fee. New: save_results, get_history, make_report, import_ai_results, schedule_checks (plus scheduled_check for Apify Schedules in normal run mode).
- Optional saved projects: progress, site checks and a shareable one-page report are kept in a named key-value store (`citebase-projects`) in the account that runs the Actor. Nothing is saved unless a project name is given.
- measure_recommendation_share can read a saved project instead of new data. Reads stay read-only; only save_results, import_ai_results and make_report write.
- import_ai_results converts AI Brand Monitor output into Citebase rows and flags close calls for review.
- schedule_checks gives the cron text, ready-to-paste inputs and a monthly cost estimate for Apify Schedules.
- Tool annotations now mark the tools that write (destructiveHint where a round can be replaced).
- 22 new priced jobs (keywords, trends, questions and forums, content briefs, newsletters, YouTube, creators, rival sites, agency listings, page crawling, local search) behind six easy packs: `starter`, `keywords`, `competitors`, `creators`, `local` and `ai_check`. `quote_cost` takes a pack name and totals every job in it; there are still eleven tools.
- The site check now separates answer bots (allow them) from training-only bots (your choice).
- One setup address now also adds the tools that run the paid data jobs you approve.
- Recommendation Share is now counted over buying questions only (counting rule version 2). Questions that name the brand are shown separately as a reputation check. Rounds saved by an earlier build used the old rule, so comparing them with new rounds reads "not comparable": start a new baseline.
- Change verdicts are stricter: "too early to tell", "engines moved" and "not comparable" join "improved" and "worsened", every result says the smallest change the panel can see, and a change is scored only when it was made between the two rounds.
- measure_recommendation_share takes an optional `brand` (name, domain, aliases) so questions that give the brand away are flagged. Saved projects now keep brand aliases too.
- import_ai_results counts only positive wording as a recommendation; every other mention is listed for review.
- check_outreach_draft now reports a missing opt-out line or sender identity as a problem that blocks `ready`, and rejects numbers that are not finite.
- The AI check pack now covers 30 questions (20 buying questions, 5 controls, 5 brand-name checks) so a first baseline meets the minimums: about $21.90.
- The site check also looks for rules that stop search and AI from quoting your pages.

## 0.3
- Six stateless tools: get_playbook, audit_site, quote_cost, measure_recommendation_share, next_steps, check_outreach_draft.
- Every tool has a described input schema, a typed output schema, annotations and a plain-language description.
- Works as a Standby MCP server (`/mcp`) and through a plain JSON endpoint (`/run`), which is what mcp.apify.com exposes.
- One-shot run mode with dataset, output and key-value-store schemas.
- Site check refuses private and local addresses, bounds response size and time, and never runs JavaScript.
- Logs one safe line per call (tool, input size, outcome, time); never the content.
