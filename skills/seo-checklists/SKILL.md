---
name: seo-checklists
description: Produce tailored, prioritised on-page, off-page, technical and AI-search (GEO) SEO checklists for a specific site, pre-filled with pass/fail status from the audit. Use when the user asks for an SEO checklist, on-page checklist, off-page checklist, link-building checklist, or "what should I do next".
argument-hint: "<site URL or domain> [onpage|offpage|technical|ai|all]"
---

# Tailored SEO checklists

Sources of truth (read the relevant ones fully before writing):
- `../../references/checklist-onpage.md`
- `../../references/checklist-offpage.md`
- `../../references/checklist-technical.md` (includes local)
- `../../references/checklist-ai-search.md`

## Steps
1. Load `seo-workspace/<domain>/audit.json` and `context.md`. If there is no audit, run the crawl from `seo-audit` Step 1 first (fast, free) so items can be pre-filled.
2. For every reference item that applies to this site type (SaaS, local service, e-commerce, publisher, agency), emit one row:
   `- [ ] <action> — status: pass|fail|warn|todo — evidence: <URL/value or "needs GSC"> — owner: user|agent|vendor — effort: S|M|L`
   Mark `[x]` for verified passes. Skip items that don't apply (e.g. local items for a national SaaS) and say why in one line.
3. Order each checklist by priority (blockers → money-page relevance → quick wins → longer plays), not by reference order.
4. Make off-page items concrete for this site: name the actual competitor gap domains, the actual listicles/review sites cited by AI for their category, the PR angle that fits their real news, and the monthly link budget from `context.md`.
5. Write `seo-workspace/<domain>/checklist-onpage.md` and `checklist-offpage.md` (technical and AI-search sections go in the on-page file unless the user asked for them separately). Keep each under ~60 rows; put the long tail in a "Later" section.
6. Reply with the top 10 items across both lists and the file paths.

## Rules
- Carry each item's evidence grade (A/B/C). Never present a C item as required.
- Re-running the skill updates statuses in place; keep user edits (rows the user checked or annotated).
- No black-hat items, ever (see `checklist-offpage.md` §E).
