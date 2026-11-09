---
name: content-brief
description: Produce an entity-aware SEO content brief with outline, snippet answer, required entities, internal-link targets and a do-not-fabricate list. Use when the user asks for a content brief, article outline for SEO, Frase/Surfer-style brief, or topical brief before drafting.
argument-hint: "[keyword or topic] [URL optional]"
---

# Content brief

Talk like `../../references/plain-language.md`. Fabrication guard: never invent stats, quotes or "studies show" claims.

## Input
Primary keyword / question, optional URL of a draft or competitor page, brand facts the user already confirmed.

## Web connector mode
Deliver the brief in chat. Optional live SERP skim: `quote_cost` (pack `keywords` about $1.42 or `starter` about $0.17) → yes → `call-actor` on `khadinakbar/*`. Without live data, label assumptions.

## Steps
1. Clarify intent (informational / commercial / comparison). If unclear, ask one question.
2. Optional live SERP skim: `quote_cost` then only `khadinakbar/*` (or the `keywords` / `starter` pack). Without live data, work from the brief + user notes and label assumptions.
3. Deliver a Markdown brief:
   - Target query, intent, primary entity
   - 40–60 word suggested snippet answer (placeholder facts marked `[NEED FACT]`)
   - H2/H3 outline ordered by searcher needs
   - Required entities / attributes to mention (from `entity-seo` map if present)
   - Internal link targets (ask for real URLs; do not invent paths)
   - **Do-not-fabricate** list (numbers, awards, customers that must come from the user)
   - Suggested schema types (Article / FAQ / HowTo) — hygiene only, not an AI-ranking promise
4. Offer next: draft via `humanize-content` rules, or score trust with `eeat-audit`, or optimize an existing URL with `content-optimize`.
5. Done / Cost so far / Next.

## Rules
- White-hat. No scaled unreviewed AI page farms.
- Auth for paid data: Apify OAuth or token on the Citebase MCP setup address.
