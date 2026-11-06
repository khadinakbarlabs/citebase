# Measuring AI citations honestly

Used by `skills/citation-loop`. The aim is a number you can trust enough to decide with, and a clear statement of what it cannot tell you.

## Three different outcomes
| Outcome | Meaning | Why it matters |
|---|---|---|
| **Mentioned** | The brand is named in the answer. | Awareness, but could be negative or incidental. |
| **Cited** | A brand-owned URL is among the answer's sources. | Traffic path and evidence the engine read your page. Citation is not endorsement. |
| **Recommended** | The answer offers the brand as an option for the user's need, with neutral-to-positive framing. | The outcome that drives choice. This is the north-star metric. |

**Recommendation Share (RS)** = share of answers that recommend the brand, computed per prompt (mean over engines and repeats) and averaged over the non-control prompts. Report it per engine and overall, with its interval.

## Why the design looks like this
- **Frozen panel.** Compare like with like: the same prompts every time. Editing prompts after seeing results turns the metric into a marketing tool.
- **Repeats (3 or more).** Answers differ run to run; back-to-back repeats agree only part of the time. One run is an anecdote.
- **Prompts are the unit, not individual runs.** Repeats of one prompt are correlated, so treating 180 runs as 180 independent samples fakes certainty. Intervals resample prompts (bootstrap, fixed seed). The pooled Wilson interval is shown for mention and cite rates only as a rough guide.
- **Control prompts.** Questions where the brand should not be recommended. If controls move, the engines changed; if controls show recommendations, the rubric or the engine is noisy. Report the false-positive rate next to RS.
- **Paired comparison.** Change in RS is computed per prompt (current minus baseline), then summarised, so easy and hard prompts do not distort the result.
- **Difference-in-differences for experiments.** For each logged change, the prompts it targeted are compared with the other prompts over the same window. `supported` needs the interval of the difference to sit above zero; `inconclusive` is the honest default.

## Minimums
- At least 20 non-control prompts and 3 repeats per prompt and engine before quoting a number; below that the report says "directional".
- At least 5 control prompts.
- Re-measure no sooner than 30 days after a change; new pages need time to be crawled, indexed and picked up, and some engines refresh slowly.

## What this cannot tell you
- **Causation.** Several changes in one window, engine updates, seasonality and press cycles all confound. `supported` means "worth repeating", not "proven".
- **What a signed-in person sees.** Actors call search-enabled model endpoints; the consumer apps add personalisation, location, memory and different retrieval. Use the trend, not the absolute level.
- **Traffic or revenue.** AI referrals are usually under 1% of site traffic for most sites; connect RS to analytics separately before promising ROI.
- **Permanence.** Models and retrieval change without notice. Keep the panel and rubric fixed so you can see when they do.

## Mechanism tags for experiments
`onpage`, `fact-page`, `listicle`, `review-site`, `press`, `reddit`, `youtube`, `directory`, `podcast`, `creator`, `schema`, `llms-txt`, `technical`, `other`. Tagging `schema` and `llms-txt` experiments is encouraged: they are disputed levers, and the loop is how to test them on your own site.

## Evidence grades used across the references
**A** controlled test or large dataset · **B** practitioner consensus or one study with a clear method · **C** anecdote or vendor-reported figure (same definition in every checklist). Cite the grade next to any statistic you put in a report, and prefer the lower grade when sources disagree.
