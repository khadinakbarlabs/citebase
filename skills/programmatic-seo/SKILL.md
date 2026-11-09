---
name: programmatic-seo
description: Design safe programmatic SEO (pSEO) page systems with data sufficiency gates, unique intent per template, and anti-scaled-abuse checks. Use when the user asks for programmatic SEO, thousands of location or integration pages, template-driven SEO at scale, or how to avoid thin doorway spam.
argument-hint: "[site or niche + page type]"
---

# Programmatic SEO (quality-first)

Talk like `../../references/plain-language.md`. Ideas adapted from MIT pSEO skill sets (see `../../references/ATTRIBUTIONS.md`).

## Positioning
pSEO is useful when **each page answers a distinct search intent with enough unique data**. It is not a way to flood the index with near-duplicates.

## Hard vetoes (refuse and explain)
- Doorway / spun / synonym-swapped pages
- Pages with no unique facts beyond the city or product name
- Unreviewed scaled AI filler (Google spam-update risk)
- Rented subfolders on unrelated high-DR domains ("parasite" spam)

## Web connector mode
Design the data architecture and quality gates in chat. Sample drafts: `check_ai_content`. Live SERP/keyword checks: `quote_cost` → yes → `call-actor` on `khadinakbar/*`. Citebase does not auto-publish page farms.

## Workflow
1. **Discover** — Which entities × attributes have enough first-party or licensed data? (cities × services, integrations × features, comparisons with real specs.)
2. **Data architecture** — One row per page; required fields; sufficiency gate (skip rows missing required facts).
3. **Templates** — Unique H1/title pattern, answer-first intro, sections driven by data columns, not filler paragraphs.
4. **Quality gates** before publish:
   - Intent uniqueness (no cannibalization with an existing money page)
   - Minimum unique tokens / facts per page
   - `ai-content-check` / `check_ai_content` on sample drafts
   - `eeat-audit` sample on YMYL niches
5. **Rollout** — Gradual indexing (sitemap batches), internal hub links, monitor thin-content flags via `seo-audit`.
6. Live SERP/keyword checks only after `quote_cost` on `khadinakbar/*`.
7. Done / Cost so far / Next.

## Hand-offs
- Entity graph for the niche → `entity-seo`
- Single-page rewrite → `content-optimize` / `humanize-content`
- Briefs for hub pages → `content-brief`
