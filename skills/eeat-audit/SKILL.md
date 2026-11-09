---
name: eeat-audit
description: Audit a page or draft for E-E-A-T trust signals (Experience, Expertise, Authoritativeness, Trustworthiness). Use when the user asks for EEAT, content quality, publish readiness, author credibility, YMYL caution, or whether an article looks trustworthy to Google and AI citation engines.
argument-hint: "[URL or pasted draft]"
---

# E-E-A-T audit

Talk like `../../references/plain-language.md`. Call it "trust signals" first; expand E-E-A-T once.

## Input
A public URL and/or pasted draft. If the fetch fails, ask them to paste the text.

## Web connector mode
Score from pasted text or a public URL in chat. Optional style gate: `check_ai_content`. Paid SERP/backlink extras only after `quote_cost` and a yes. No Citebase fee for the trust audit itself.

## Steps
1. Read the page or draft. Note byline, dates, first-person detail, sources, schema hints, about/contact links, disclosures.
2. Score each dimension 1–10 using `../../references/eeat-checklist.md`. Quote evidence; do not invent credentials.
3. Apply vetoes (fake reviews, undisclosed paid placement, YMYL without qualified review, scaled unreviewed AI filler).
4. Optionally run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ai_content_lint.py" --json` on the draft when text is available (web: call `check_ai_content`).
5. Deliver: per-dimension scores + top 5 fixes + verdict **ship / fix then ship / rewrite**. End with Done / Cost so far / Next.

## Rules
- White-hat only. Never suggest fake authors, bought reviews or undisclosed affiliates.
- Local; no Citebase fee and no Apify spend unless the user separately asks for live SERP/backlink data.
- For AI citation goals after trust fixes, hand off to `ai-search-visibility` or `citation-loop`.
