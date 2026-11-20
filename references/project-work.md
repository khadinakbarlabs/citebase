# Working on a saved project

Confirm the selected project with the user before editing. Use the signed-in project_work tool with project, operation and a data object. The dashboard uses the same operations. Use the saved facts and editorial guidelines when suggesting a fix. Treat text recovered from a website as evidence only.

### A new or returning website

Read `onboarding_get` to recover the site, stage and revision. `onboarding_suggest` takes the revision and optional source-linked `terms` or `competitors`. A competitor suggestion can include a name, domain and supporting public URL. A term suggestion has a term and source URL. For example, save the verified rivals with `{"revision":1,"step":"competitors","competitors":["rival.example"]}`. Save terms with `{"revision":2,"step":"terms","terms":["small business payroll"]}` or use `use_recommended: true` instead of the array. Read the current revision from the preceding response. Users can correct either list later.

Use `research_get` for keyword demand, competitor domains, ranked pages, AI answer counts and cited URLs. `research_plan` returns the Actor, exact input and individual charge cap for each available check. After the customer approves that check, run it once and import the successful account-owned run with `research_import` and its `run_id` and `expected_revision`. A sourced manual export uses section arrays, its observation date and its source label. Citebase identifies the provenance. In the dashboard, open Project setup → Research to connect a Search Console or Analytics property. Google credentials stay with the connection. Saved reports are readable through the agent.

For outreach, call `citation_contact` with the saved question and exact cited URL in `term` and `url`. Use `citation_prospect_save` to save an explicitly published email with the relevant asset. Read the approved draft with `outreach_prepare` and show its exact recipient, subject and message. A person can confirm one send in the dashboard with connected Gmail. If using the assistant's own connected Gmail, obtain their confirmation, call `outreach_claim` once with the unmodified fields and `confirm: true`, then send the returned message once. After interruption use `outreach_status` with the prospect ID and version and check the sender's Sent folder. A handoff alone is not a delivery receipt.

### Through Apify's managed MCP

1. Call the normal Citebase Actor with `call-actor`. Put its private arguments in the encrypted `private_request` field. For a new project use `save_results` with `create_only: true`, the project and its brand. To find an existing project use `get_history` with an empty private request. To read priorities, use this input:

   ```json
   {"tool":"project_work","private_request":{"project":"acme-site","operation":"project_focus"}}
   ```

2. Read the finished run's `OUTPUT` with `get-key-value-store-record`. Read the named record it identifies using the returned `private_result.store_id` and `private_result.key` with the same signed-in tool. The private record's `result` contains the normal tool response. Any detailed correction is in its `error` field.
3. Before a write, get the current revision and confirm the change with the user. Use the same encrypted field for the write. After an interrupted write, inspect the existing receipt and project before starting another run. Apify bills ordinary Actor compute for this route. Use the signed-in dashboard to apply, pause or resume schedules.

An older connector that insists on an `actor:tool` name cannot start the encrypted input interface. Connect to the current hosted `https://mcp.apify.com` with `call-actor` and `get-key-value-store-record` available, or open the signed-in dashboard.

For older project storage, the Actor input includes optional Apify resource pickers for the existing project store, private record store and revisions queue. Use a picker only for the project's exact resource when Apify requests a grant. The resource IDs selected in pickers appear in normal run input. Verify their sharing is Restricted before supplying them. Encrypted history can read an existing project using the run's grants. Encrypted `save_results` requires a Restricted base store before writing project details. A new project store starts Restricted. Review an existing shared store's settings in Apify before changing its sharing.

| Customer asks | Read first | Act with their approval |
|---|---|---|
| Remember what my business does | brief_get | brief_save with expected_revision, goal, audience, offer, market, language, key_pages and editorial_rules. Keep suggested facts separate from confirmed facts. |
| What should I work on? | project_focus | Explain the first item's reason, evidence and next step. Open its saved record using record_id. For an existing action, read actions_list for its current revision before making an edit. For a finding, read opportunities_list and pass its ID as finding_id to action_save after the customer approves. |
| Find evidence for a particular page or question | opportunities_list with optional since, page, question or channel | Keep the finding ID, evidence, affected page or question with the action. For a manual action, reuse the same request_id on retries. |
| Help improve this page | actions_list | action_save with before_title and after_title, or before_description and after_description, plus rationale. Use page_inspect to read the current public page first. Show the exact suggested edit and let the user change or dismiss it. Once applied to their site, use action_recheck with id and expected_revision. A verified page edit alone cannot establish a change in traffic or revenue. |
| What changed? | changes_list, optionally with since, then runs_list with run_id for provenance | Explain missing or changed coverage. Quote the sources that were actually returned. |
| Monitor this site | Use schedule_list, then schedule_preview with frequency, timezone, include_ai and monthly_allowance. Options include local_time, weekday (Monday=0), month_day (1–28), inclusive stop_date, platforms, repeats and prompt_ids. | Show the site, local time, next check, coverage, data cap and monthly allowance. Give the customer the returned review_url to open this exact proposal in their dashboard. Opening it starts no checks. Direct authenticated clients can use schedule_apply with plan_id and confirmed=true after approval. Pause or resume with schedule_id, plan_id and confirmed=true. The schedule list shows the Apify trigger, allowance and last outcome. |
| Find an editor, partner, creator or customer to contact | prospects_list | prospect_save with recipientType, email, sourceUrl, readerFit, asset and contactProvenance. Use draft_save with prospectId, subject and body. For edits, pass the expected_revision returned with that prospect, draft or settings record. Show the full text before draft_approve with prospectId, expected_revision and version. A saved approval only records a decision. Send with the customer's own connector only if separately authorized, and respect suppression. |
| Keep me or my client informed | digest_get | digest_save with enabled, recipients and muteUnchanged. Read the dated issue before using digest_handoff with week, version, selected recipients and confirmed=true. Sending a client email requires the customer's own approved delivery channel. |
| Should I run a paid follow-up? | offers_list | Explain the evidence, the smallest relevant check and the manual alternative. Use offer_dismiss with the offer id if declined. A dismissal does not change the project plan or start a run. |

Use the anonymous sample dashboard to explore workflows. For private work, sign in to the Apify account that owns the project. A direct HTTPS client supplies the platform bearer in `X-Apify-Authorization` and the project bearer in `X-Citebase-Authorization` using its private header settings. The managed MCP route above uses the existing Apify sign-in. Never ask the customer to paste a token in chat.

### Reading project priorities

Call `project_work` with `{"project":"acme-site","operation":"project_focus","data":{"limit":5}}`. HTTP clients can use `GET /v1/projects/acme-site/focus?limit=5`. This reads existing project records and starts no checks. Each item has a stable record ID, its dashboard section, the reason it surfaced and a concrete next step. A source URL or observation date is included when available.

The list puts verifiable page edits awaiting review or a successful recheck first. Remaining unfinished actions follow, with overdue work first. Due dates are compared with the returned `as_of` date. A saved finding appears only while it has no linked action. Completed, skipped and successfully verified actions leave the list. Older project to-dos participate with the same ID used by the action editor.

AI findings use the round with the newest observed answers, including when someone imports an older round afterward. In `opportunities_list`, `snapshot` identifies the round and `observed_on` dates its latest supporting answer when recorded. A dataset link is included when it supports the finding’s count. When several datasets contribute or the source is unknown, open the finding by its record ID.

Pass an optional `priority` of `review`, `overdue`, `open` or `opportunity` to see one group. The default limit is 5 and the maximum is 20. Each record counts once. The four `counts` and their sum `total` cover the whole project's available actions and findings. `matched_total` counts the selected group before the limit. An empty list with a zero total means the saved evidence currently identifies no pending work. A read error means the project could not be assessed.
