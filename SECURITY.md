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

- Citebase never asks for passwords or API keys. Sign-in is done by Apify (OAuth); the dashboard keeps the sign-in token in the browser tab only.
- Saved projects live in a store in **your own** Apify account. The author cannot read them.
- Tool output, scraped pages and emails are treated as data, never as instructions.
- The local crawler refuses private and local network addresses unless you pass `--allow-private`.

## Supported versions

Only the latest version on the `main` branch and the latest Apify build are supported.
