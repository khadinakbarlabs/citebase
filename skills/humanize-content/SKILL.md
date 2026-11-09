---
name: humanize-content
description: Rewrite or draft audience-facing prose so it reads human — remove AI-writing patterns while preserving facts, quotes and numbers. Use when the user asks to humanize text, make it sound natural, remove AI slop, or clean an AI draft for SEO or outreach.
argument-hint: "[pasted draft or file]"
---

# Humanize content

Talk like `../../references/plain-language.md`. Adapted from MIT-licensed humanize workflows (see `../../references/ATTRIBUTIONS.md`).

## Modes
- **Rewrite:** user pastes a draft → strip AI patterns only.
- **Generation:** user asks for new copy → apply rules while drafting.

## Hard rules
1. Never add facts, numbers, quotes, names or citations that were not in the source or brief.
2. Keep quotes, stats, dates, URLs and proper nouns verbatim in rewrite mode.
3. Do not change meaning. If removing a pattern would change a claim, keep the claim and only rephrase.
4. Detect register first (social / email / editorial / formal) and match it.

## Web connector mode
Call `check_ai_content` with the draft, rewrite in chat, then call `check_ai_content` again. No Citebase fee; no Apify spend.

## Workflow
1. Lint first when a draft exists: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ai_content_lint.py" --json` (web: `check_ai_content`).
2. Rewrite using `../../references/ai-writing-patterns.md` (P1–P36 priority table).
3. Re-lint until density is under threshold or the user accepts remaining hits.
4. Deliver the cleaned text. Add a change list only if asked.
5. Done / Cost so far ($0) / Next — offer `eeat-audit` or `content-optimize` if they want trust/SEO next.

## Out of scope
Code, commit messages, legal boilerplate that must stay formulaic, and any request to "beat" a named commercial AI detector by gaming it.
