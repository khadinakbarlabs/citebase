# Citebase: get cited by AI (MCP server)

Connect your AI assistant (claude.ai, ChatGPT, Claude Desktop, Cursor and others) to Citebase. It helps a brand get **recommended and cited by AI assistants**, using plain-language steps.

## What you get
| Tool | What it does | Cost |
|---|---|---|
| `get_playbook` | Reads Citebase's step-by-step guidelines (start with `start`) | Free |
| `audit_site` | Checks a public website for search and AI-readiness problems | Free |
| `quote_cost` | Works out what paid data jobs cost and the spending cap to use | Free |
| `measure_recommendation_share` | Turns AI-answer test results into "how often AI recommends you" | Free |
| `next_steps` | Gives a short to-do list in plain words | Free |
| `check_outreach_draft` | Checks an email before you send it | Free |

Paid data (search results, keywords, backlinks, AI answers) comes from the separate Apify connector at `https://mcp.apify.com`. Citebase tells your assistant what each job will cost and which cap to set.

## Connect
1. Add this Actor's Standby URL ending in `/mcp` as a custom connector in your assistant, and sign in with Apify.
2. Say: "Use Citebase to help me get my brand recommended by AI. Start with the start playbook."

## Good to know
- **Nothing is stored.** Each call stands alone; the server keeps no customer data.
- **No automatic safety guard on the web.** Citebase asks the assistant to quote costs and ask you before spending or sending. You stay in control: say yes only to what you understand.
- The site check reads the page text a server sends and does not run JavaScript. It refuses private and local addresses.
- Claude Code users get the full plugin with automatic guards: `claude plugin marketplace add khadinakbarlabs/citebase`.
