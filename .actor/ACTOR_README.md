## What is Citebase?

Citebase is an open-source connector that helps a brand get **recommended and cited by AI assistants** such as ChatGPT, Claude, Gemini and Perplexity. Connect it to your AI assistant and ask for help in plain words. It returns step-by-step guidelines, a website health check, price quotes for paid data jobs, "how often does AI recommend me" results and a short to-do list. All six tools are free.

Paid data (Google results, keywords, backlinks, AI answers) comes from separate Apify Actors that Citebase tells your assistant how to run, with a price quote and a spending cap first.

## When to use it and when not to

**Use it to:**
- check a website for search and AI-readiness problems;
- run a repeatable test of whether AI recommends your brand, and see if your changes helped;
- plan link-building, press and outreach with checklists, and check an email before it is sent;
- get a short, plain-language list of what to do next.

**Do not use it to:** scrape websites (use the paid data Actors), send email (it only checks drafts), or read private or local pages (the site check refuses them). It does not run JavaScript and stores nothing between calls.

## Tools

| Tool | What it returns | Price |
|---|---|---|
| `get_playbook` | Citebase's guidelines: the list of names, or one playbook's text | Free |
| `audit_site` | 0-100 health score, scores per area, the top problems with example pages | Free |
| `quote_cost` | Cost of each paid job, the total and the spending cap to use | Free |
| `measure_recommendation_share` | How often AI recommends the brand, with ranges, noise check and a verdict per change | Free |
| `next_steps` | Ranked to-do list: what, why, who, how long | Free |
| `check_outreach_draft` | Ready yes/no, problems to fix, warnings, a fingerprint of the exact text | Free |

## Connect and quick start

1. Add `https://mcp.apify.com/?actors=khadinakbar/citebase-mcp-server` as a custom MCP server in your assistant and sign in with Apify. (Or connect to this Actor's Standby URL ending in `/mcp` with your Apify token.)
2. Say: "Use Citebase to help me get my brand recommended by AI. Start with the start playbook."

Plain JSON call (what the assistant sends through `mcp.apify.com`), `POST /run`:

```json
{"tool": "quote_cost", "arguments": {"items": [{"job": "serp_page", "units": 15}]}}
```

You can also run this Actor normally with the same two fields as input (`tool`, `arguments`).

## Example output

```json
{
  "ok": true,
  "tool": "quote_cost",
  "result": {
    "lines": [{"job": "serp_page", "actor": "khadinakbar/scrape-google-serp", "units": 15, "unit": "SERP page", "requests": 1, "cost_usd": 0.0271}],
    "total_usd": 0.0271,
    "suggested_cap_usd": 0.04,
    "prices_read_on": "2026-11-06"
  }
}
```

## Price and cost

The six tools are free to call. Running this Actor uses a small amount of Apify platform compute, billed to the account that runs it; a site check of 15 pages takes under a minute. The paid data Actors that Citebase points to charge per result on your own Apify account, and `quote_cost` tells you the total before anything runs.

## Limits and reliability

- Site check: up to 30 pages, public sites only, server HTML only (no JavaScript), about a minute at most.
- Stateless: nothing is saved between calls, so keep your own data between sessions.
- Requests are limited to 2 MB. Errors say what to fix in plain words.
- On the web there is no automatic spending or sending guard. The assistant is told to quote costs and ask you first; say yes only to what you understand. The Claude Code plugin has automatic guards: `claude plugin marketplace add khadinakbarlabs/citebase`.

## Related

- [Citebase plugin and source code](https://github.com/khadinakbarlabs/citebase) for Claude Code, with approval guards and the full skill set.

## Legal and responsible use

Use Citebase for honest marketing only. It does not support fake reviews, fabricated press, hidden prompt injection or other manipulation, and its outreach checks are not legal advice: follow email laws such as CAN-SPAM, GDPR and CASL.
