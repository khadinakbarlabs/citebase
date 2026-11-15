---
name: content-optimize
description: Optimize an existing page or draft for SEO and AI citation readiness — headings, intent match, snippet answer, internal links, E-E-A-T gaps and anti-AI-slop voice. Use when the user asks to improve content, refresh a page, SEO-optimize an article, or rewrite underperforming copy.
argument-hint: "[URL or keyword + draft]"
---

# Content optimize

Talk like `../../references/plain-language.md`. White-hat only. Read `../../references/checklist-ai-search.md` first (sections 2 and 3: related questions, page format, freshness).

## Input
URL and/or draft, plus the target keyword if known.

## Web connector mode
Work from pasted draft or public URL in chat. Style gate: `check_ai_content`. Optional SERP skim: say it is a paid check billed to the user's own Apify account → yes → `quote_cost` for the cap → `call-actor` on `khadinakbar/*`. Give the amount only if the user asks. Rewrite has no Citebase fee.

## Steps
1. Read the current page/draft (title, H1/H2s, word count, intent).
2. Light SERP skim for the keyword when the user has said yes to a paid check: get the cap from `quote_cost` first, then only `khadinakbar/*` Actors. Otherwise work from the draft + user brief.
3. Run `ai-content-check` (local lint; web: `check_ai_content`) and note E-E-A-T gaps via `../../references/eeat-checklist.md`.
4. **List the related questions.** An AI assistant answering one question runs several related searches behind the scenes (query fan-out). Write down 5 to 8 of them for this page: take them from `keyword-research` (fan-out step) if it was run, otherwise infer the likely ones (comparisons, "reviews", "alternatives", pricing, the current year, a use case) and say they are inferred.
5. Produce an optimized markdown draft that:
   - Matches search intent; primary keyword in title/H1/first 100 words naturally
   - Opens with a 40–60 word direct answer where a snippet is plausible, and gives a short direct answer under each heading. This is for readers: it makes the page quicker to use. It is not a ranking trick. Google's 2026 guidance says AI-specific rewriting is not needed for its AI features (https://searchenginejournal.com/googles-new-ai-search-guide-calls-aeo-and-geo-still-seo/575026, May 2026)
   - Covers each related question from step 4 with **one self-contained passage**: a heading in the question's own words, then an answer that makes sense when read alone
   - Includes **at least one first-party number or original data point** (the user's own figure, test, survey or count). Ask the user for it; never invent one. If they have none, say what is missing
   - Uses **a table wherever items are compared** (plans, products, options, before/after)
   - Shows a real **"updated" date**. Change the date only when the content changed; a new date on old text is a fake refresh
   - Adds specific experience and sources (ask the user; never invent)
   - Uses human voice from `humanize-content` rules
   - Suggests 3–5 internal link targets (do not invent URLs)
6. List what changed and what still needs a first-party fact from the user.
7. Done / Cost so far / Next — offer `eeat-audit` for a scored pass, or `citation-loop` to measure AI mentions later.

## Rules
- No doorway pages, spun content, or scaled unreviewed AI.
- Paid Apify jobs only after the user's clear yes, each with its cap from `quote_cost`; content rewrite itself has no Citebase fee (local).
