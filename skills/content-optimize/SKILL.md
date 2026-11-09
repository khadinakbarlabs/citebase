---
name: content-optimize
description: Optimize an existing page or draft for SEO and AI citation readiness — headings, intent match, snippet answer, internal links, E-E-A-T gaps and anti-AI-slop voice. Use when the user asks to improve content, refresh a page, SEO-optimize an article, or rewrite underperforming copy.
argument-hint: "[URL or keyword + draft]"
---

# Content optimize

Talk like `../../references/plain-language.md`. White-hat only.

## Input
URL and/or draft, plus the target keyword if known.

## Web connector mode
Work from pasted draft or public URL in chat. Style gate: `check_ai_content`. Optional SERP skim: `quote_cost` → yes → `call-actor` on `khadinakbar/*`. Rewrite has no Citebase fee.

## Steps
1. Read the current page/draft (title, H1/H2s, word count, intent).
2. Light SERP skim for the keyword when live data is allowed: quote with `quote_cost` first, then only `khadinakbar/*` Actors. Otherwise work from the draft + user brief.
3. Run `ai-content-check` (local lint; web: `check_ai_content`) and note E-E-A-T gaps via `../../references/eeat-checklist.md`.
4. Produce an optimized markdown draft that:
   - Matches search intent; primary keyword in title/H1/first 100 words naturally
   - Opens with a 40–60 word direct answer where a snippet is plausible
   - Adds specific experience and sources (ask the user; never invent)
   - Uses human voice from `humanize-content` rules
   - Suggests 3–5 internal link targets (do not invent URLs)
5. List what changed and what still needs a first-party fact from the user.
6. Done / Cost so far / Next — offer `eeat-audit` for a scored pass, or `citation-loop` to measure AI mentions later.

## Rules
- No doorway pages, spun content, or scaled unreviewed AI.
- Paid Apify jobs only after a quote and approval; content rewrite itself has no Citebase fee (local).
