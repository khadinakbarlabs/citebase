---
name: social-content
description: Plan and draft organic social and short-form content (LinkedIn posts, YouTube titles/descriptions, Reddit answers, newsletter blurbs, X/Threads posts) that reinforces brand entities and stays human. Use when the user asks for social media content, LinkedIn posts, YouTube SEO copy, Reddit replies, a content calendar for social, or short-form posts that support SEO and AI citation.
argument-hint: "[platform + topic or URL]"
---

# Social content

Talk like `../../references/plain-language.md`. Organic posts only — Citebase does not auto-publish to social networks.

## Goal
Create platform-native copy that (1) helps people, (2) reinforces the entity map (`entity-seo`), and (3) can be cited or shared without looking like spam.

## Hard rules
- No fake engagement, pods, bought comments, or undisclosed ads. FTC/ASA disclosure when there is any material connection (`../../references/creator-playbook.md`).
- No automated DMs or mass connection requests.
- Never invent case studies, metrics, or customer names — mark `[NEED FACT]`.
- Run drafts that sound robotic through `humanize-content` / `check_ai_content` when length warrants it.
- Paid research (trending topics, competitor videos, Reddit threads): `quote_cost` then only `khadinakbar/*`. Auth = Apify OAuth/token on the Citebase MCP setup address.

## Web connector mode
Draft in chat. Paid research: `quote_cost` → yes → `call-actor` on `khadinakbar/*`. Style gate: `check_ai_content` on longer posts. Citebase never auto-publishes to social networks.

## Workflow
1. Ask platform + goal (awareness, launch, hiring, thought leadership, support FAQ) if not clear.
2. Pull angle from brand facts, a URL, or a brief (`content-brief`). Optional live data: YouTube search/trending, Reddit search, newsletter posts, Google Trends — quote first.
3. Deliver for each piece:
   - Hook (first line)
   - Body (platform length limits respected)
   - CTA (one ask)
   - Hashtags sparingly (LinkedIn/YouTube: few or none; never hashtag stuffing)
   - Assets needed (image, clip, link)
   - Disclosure line if sponsored/gifted
4. Batch into a simple calendar (3–10 posts) when asked; otherwise one strong draft.
5. Hand off creator pitches to `creator-outreach`, long articles to `content-optimize`, profiles to `platform-presence`.
6. Done / Cost so far / Next.

## Platform notes
- **LinkedIn:** first-person or brand voice; one idea; no engagement bait.
- **YouTube:** title ≤ ~60 chars intent; description with chapters + canonical URL; no keyword stuffing.
- **Reddit:** answer the question first; no bare promo; follow sub rules; disclose affiliation.
- **Newsletter / Substack blurbs:** value in the subject; body teaser + one link.
- **X / Threads:** one claim + proof link; thread only when each beat stands alone.
