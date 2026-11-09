# Changelog

## 0.4
- Easier “get cited by AI” path: `get_playbook` lists a short journey and featured playbooks first; `audit_site` points at `next_steps` plus a quoted AI recommend check; `next_steps` always keeps the AI-recommend step even when the site has many problems, and an empty call offers the site check + AI path instead of only a 30-day reminder.
- Every skill now has a **Web connector mode** that names the exact tools (`audit_site`, `next_steps`, `quote_cost`, `call-actor`, `check_ai_content`, `check_outreach_draft`, …). `WEB_NOTE` includes `next_steps` and pack `ai_check`.
- Twelfth tool with no Citebase fee: `check_ai_content` — local AI-writing pattern lint (density + hits). No API, no Apify spend.
- New playbooks: `ai-content-check`, `humanize-content`, `eeat-audit`, `content-optimize`, `content-brief`, `entity-seo`, `programmatic-seo`, `platform-presence`, `directory-listings`, `social-content`, `social-listening` (adapted from MIT/Apache sources; Apify-compliant — no third-party Actors; connector auth remains Apify OAuth/token on mcp.apify.com).
- Explicit refusal of parasite / rented-subfolder spam; white-hat `platform-presence` instead.
- Eleven tools with no Citebase fee. New: save_results, get_history, make_report, import_ai_results, schedule_checks (plus scheduled_check for Apify Schedules in normal run mode).
- Optional saved projects: progress, site checks and a shareable one-page report are kept in a named key-value store (`citebase-projects`) in the account that runs the Actor. Nothing is saved unless a project name is given.
- measure_recommendation_share can read a saved project instead of new data. Reads stay read-only; only save_results, import_ai_results and make_report write.
- import_ai_results converts AI Brand Monitor output into Citebase rows and flags close calls for review.
- schedule_checks gives the cron text, ready-to-paste inputs and a monthly cost estimate for Apify Schedules.
- Tool annotations now mark the tools that write (destructiveHint where a round can be replaced).
- 22 new priced jobs (keywords, trends, questions and forums, content briefs, newsletters, YouTube, creators, rival sites, agency listings, page crawling, local search) behind six easy packs: `starter`, `keywords`, `competitors`, `creators`, `local` and `ai_check`. `quote_cost` takes a pack name and totals every job in it.
- The site check now separates answer bots (allow them) from training-only bots (your choice).
- One setup address now also adds the tools that run the paid data jobs you approve.
- Recommendation Share is now counted over buying questions only (counting rule version 2). Questions that name the brand are shown separately as a reputation check. Rounds saved by an earlier build used the old rule, so comparing them with new rounds reads "not comparable": start a new baseline.
- Change verdicts are stricter: "too early to tell", "engines moved" and "not comparable" join "improved" and "worsened", every result says the smallest change the panel can see, and a change is scored only when it was made between the two rounds.
- measure_recommendation_share takes an optional `brand` (name, domain, aliases) so questions that give the brand away are flagged. Saved projects now keep brand aliases too.
- import_ai_results counts only positive wording as a recommendation; every other mention is listed for review.
- check_outreach_draft now reports a missing opt-out line or sender identity as a problem that blocks `ready`, and rejects numbers that are not finite.
- The AI check pack now covers 30 questions (20 buying questions, 5 controls, 5 brand-name checks) so a first baseline meets the minimums: about $23.60.
- `quote_cost` now prices each job at its realistic worst case: start fees that follow run memory, the fallback rate Google AI Overviews checks used in every test run, per-run product fees, and the Apify compute that some jobs bill on top of the data price. It says how much of the total is compute, warns when a job cannot run yet (keyword ideas and volume, until 2026-11-14) and keeps such jobs out of the spending cap. Whether Apify's cap counts compute is unconfirmed, so the cap stays 30% above the total.
- The site check also looks for rules that stop search and AI from quoting your pages.
- Quotes now price the worst case, compute included, so the number you are shown is the number to plan with.
- import_ai_results now reads the results of Google AI Overviews, Google AI Mode and the two tracker Actors as well as AI Brand Monitor. Anything that cannot be judged honestly is listed as skipped or sent to review.
- Each saved answer can carry the model, country, language, device and how it was collected. Measurements warn in plain words when two rounds were not asked under the same conditions. import_ai_results takes `context` (country, language, device) for results that do not say; Google AI Mode does not.
- The first round can be imported in one step: send `panel` and `brand` with `save` and the project is created with its results. No retyping.
- Google AI Overviews and AI Mode give one answer per search, so they are no longer held to the three-repeat minimum. A round bought exactly as the AI check pack quotes it carries no repeat warning.
- schedule_checks takes `repeats` (1 to 5, default 3) for the AI assistants, plans Google AI Overviews and AI Mode once, splits long question lists into runs the Actor accepts, takes the website from the saved project when `url` is left out, follows the engines of the first saved round, and shows the worst-case monthly cost.
- quote_cost answers a wrong pack name with a plain sentence that lists the packs.
- The daily spend ceiling of the Citebase plugin now defaults to $40 (it was $25), so the AI check baseline can run. Runs above $2 still ask first.

## 0.3
- Six stateless tools: get_playbook, audit_site, quote_cost, measure_recommendation_share, next_steps, check_outreach_draft.
- Every tool has a described input schema, a typed output schema, annotations and a plain-language description.
- Works as a Standby MCP server (`/mcp`) and through a plain JSON endpoint (`/run`), which is what mcp.apify.com exposes.
- One-shot run mode with dataset, output and key-value-store schemas.
- Site check refuses private and local addresses, bounds response size and time, and never runs JavaScript.
- Logs one safe line per call (tool, input size, outcome, time); never the content.
