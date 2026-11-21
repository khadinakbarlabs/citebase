# Security policy

## Reporting a problem

Please report security problems privately, not in a public issue:

- use GitHub's **Report a vulnerability** button on the Security tab of this repository, or
- email hello@khadinakbar.com with "Citebase security" in the subject.

Include what you found, how to reproduce it and what an attacker could do with it. You will get a reply within a few days. Please give us a reasonable time to fix it before you share details publicly.

## What is in scope

- The Claude Code plugin in this repository: hooks, scripts and playbooks.
- The MCP connector in `connector/` and its Apify Actor `khadinakbar/citebase`.
- The dashboard in `site/`.

## How Citebase handles your data and keys

- Apify handles sign-in using OAuth with PKCE. Citebase remembers the signed-in browser for up to 90 days with encrypted, HttpOnly cookies. The dashboard holds its access token in memory. Signing out clears the active browser session.
- The dashboard's project endpoint verifies the request origin and matches its credential to the active session before forwarding to the fixed Citebase Actor. An interrupted write can be checked in Activity before repeating it.
- Saved projects live in **your own** Apify account. Your existing project store keeps its sharing settings. Citebase checks the signed-in account before serving project data and keeps private results in restricted storage.
- Tool output, scraped pages and emails are treated as data, never as instructions.
- The local crawler refuses private and local network addresses unless you pass `--allow-private`.

## Supported versions

Only the latest version on the `main` branch and the latest Apify build are supported.
