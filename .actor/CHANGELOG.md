# Changelog

## 0.4
- Eleven tools with no Citebase fee. New: save_results, get_history, make_report, import_ai_results, schedule_checks (plus scheduled_check for Apify Schedules in normal run mode).
- Optional saved projects: progress, site checks and a shareable one-page report are kept in a named key-value store (`citebase-projects`) in the account that runs the Actor. Nothing is saved unless a project name is given.
- measure_recommendation_share can read a saved project instead of new data. Reads stay read-only; only save_results, import_ai_results and make_report write.
- import_ai_results converts AI Brand Monitor output into Citebase rows and flags close calls for review.
- schedule_checks gives the cron text, ready-to-paste inputs and a monthly cost estimate for Apify Schedules.
- Tool annotations now mark the tools that write (destructiveHint where a round can be replaced).

## 0.3
- Six stateless tools: get_playbook, audit_site, quote_cost, measure_recommendation_share, next_steps, check_outreach_draft.
- Every tool has a described input schema, a typed output schema, annotations and a plain-language description.
- Works as a Standby MCP server (`/mcp`) and through a plain JSON endpoint (`/run`), which is what mcp.apify.com exposes.
- One-shot run mode with dataset, output and key-value-store schemas.
- Site check refuses private and local addresses, bounds response size and time, and never runs JavaScript.
- Logs one safe line per call (tool, input size, outcome, time); never the content.
