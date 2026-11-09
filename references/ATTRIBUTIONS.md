# Third-party attributions

Citebase is MIT-licensed. Skills adapt ideas (and some deterministic lint code) from these MIT/Apache-2.0/CC BY-SA projects. We keep their licenses; we do not wrap their hosted APIs or other creators' Apify Actors.

| Project | License | What we used |
|---|---|---|
| [Shirhussain/humanize](https://github.com/Shirhussain/humanize) | MIT | Deterministic AI-pattern linter → `scripts/ai_content_lint.py`; humanize workflow ideas → `skills/humanize-content` |
| [inhouseseo/superseo-skills](https://github.com/inhouseseo/superseo-skills) | Apache-2.0 | E-E-A-T scoring dimensions and improve-content workflow ideas → `skills/eeat-audit`, `skills/content-optimize` |
| [parweb/mcp-ai-slop-checker](https://github.com/parweb/mcp-ai-slop-checker) | MIT | Scoring-dimension ideas for local AI-style checks (no code copied) |
| [saadsalmankhan/entity-seo-skill](https://github.com/saadsalmankhan/entity-seo-skill) | MIT | Entity map / reinforce / measure workflow ideas → `skills/entity-seo` |
| [teekoo5/pseo-skills](https://github.com/teekoo5/pseo-skills) | MIT | Data-sufficiency and quality-gate ideas for scale → `skills/programmatic-seo` |
| [siddiqss/semantic-seo-suite](https://github.com/siddiqss/semantic-seo-suite) | MIT | Content-brief structure and fabrication-guard ideas → `skills/content-brief` |
| Wikipedia WikiProject AI Cleanup — "Signs of AI writing" | CC BY-SA | Pattern catalog grounding |

Citebase still runs paid live data only through Actors owned by `khadinakbar/*` on the user's Apify account, with a quote before every run. Auth for connectors is Apify OAuth or Apify API token via the documented mcp.apify.com setup address. Local skills (lint, humanize, E-E-A-T, entity, pSEO, briefs, platform presence, listings) add no Citebase fee.
