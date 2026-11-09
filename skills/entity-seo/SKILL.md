---
name: entity-seo
description: Map brand, person, company and product entities and reinforce their relationships on-site and off-site (JSON-LD graph, entity pages, sameAs profiles). Use when the user asks for entity SEO, Knowledge Panel readiness, "Google doesn't connect me to my company", multi-entity schema, or who-founded / who-makes relationship gaps.
argument-hint: "[brand or site URL]"
---

# Entity SEO

Talk like `../../references/plain-language.md`. Adapted from MIT entity-SEO playbooks (see `../../references/ATTRIBUTIONS.md`).

## Goal
Help search engines and AI assistants understand **who you are** and **how your entities relate** — not only rank for a name string.

## Guardrails
- Only true relationships. Never invent partnerships, awards, or "as seen in".
- Schema must match visible text. No claims in JSON-LD that the page does not say.
- Real, owned profiles only in `sameAs`. No fake directories.
- Paid live data: `quote_cost` then only `khadinakbar/*` Actors. Auth is Apify OAuth/token via the Citebase setup address — never ask for keys in chat.
- White-hat only. No PBNs, fake profiles, or rented "parasite" folders on unrelated domains.

## Web connector mode
Deliver the entity map and schema drafts in chat. Optional site readiness: `audit_site` then `next_steps`. Live SERP / AI relationship checks: `quote_cost` → yes → `call-actor` on `khadinakbar/*`. Measuring whether AI names the relationships correctly hands off to `ai-search-visibility` / `citation-loop`.

## Workflow
1. **Map** — Inventory Person / Organization / Brand / products / services / locations. For each link write one plain *why*. Confirm the map with the user before encoding it.
2. **Audit** — Per relationship: stated on-site? encoded with `@id` links? confirmed on an independent profile? answered correctly by Google / ChatGPT / Perplexity when asked "who founded X"?
3. **Site** — One home URL per entity; multi-entity JSON-LD graph; titles and internal links that name the relationships; hand off thin pages to `content-optimize` or `eeat-audit`.
4. **Reinforce** — Checklist of profile bios (LinkedIn, GitHub, Crunchbase, app stores) with exact statement-library lines. Owner applies off-site edits.
5. **Measure** — Re-ask relationship questions; optional AI check via `ai-search-visibility` / `citation-loop`.
6. Done / Cost so far / Next.

## Hand-offs
- Thin trust → `eeat-audit`. Scaled template pages → `programmatic-seo` quality gates.
- Fake authority shortcuts → refuse; offer `platform-presence` or `press-release` instead.
