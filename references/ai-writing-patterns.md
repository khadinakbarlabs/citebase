# AI writing patterns (Citebase)

Mechanical tells used by `scripts/ai_content_lint.py` and the `humanize-content` skill. Grounded in Wikipedia WikiProject AI Cleanup ("Signs of AI writing"). Pattern ids match the linter.

**Density, not existence.** Humans use these phrases. Clusters of them in one draft are the problem.

## Highest-impact fixes
| Id | Tell | Fix |
|---|---|---|
| P1–P2 | "It's not X, it's Y" / "not only… but also" | State the positive claim once |
| P3 | Rule-of-three lists ("innovative, efficient, and scalable") | One strong word, or expand honestly |
| P5 | Trailing "-ing" significance ("…, underscoring its importance") | Delete the clause |
| P13–P14 | "In conclusion" / "It's important to note" | End on the last fact; cut the disclaimer |
| P15 | "Experts say" / "studies show" | Name the source or own the claim |
| P21–P25 | Chatbot voice ("Great question!", "As an AI…") | Delete from deliverables |
| P27 | Em-dash overuse | ≤1 per ~300 words |
| P35–P36 | delve, tapestry, pivotal, leverage, "in today's fast-paced world" | Plain words |

## Hard rules for Citebase
- Never invent facts, numbers, quotes or citations to "sound human".
- Quotes, stats and proper nouns stay verbatim when rewriting.
- This lint is **not** a commercial AI-detector score and does not claim to "beat" GPTZero-style tools.
- Scaled unreviewed AI content is a Google spam risk — flag it; do not ship it as a tactic.
