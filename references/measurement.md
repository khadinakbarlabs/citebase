# Measuring AI citations honestly

Used by `skills/citation-loop`. The aim is a number you can trust enough to decide with, and a clear statement of what it cannot tell you.

## Three different outcomes
| Outcome | Meaning | Why it matters |
|---|---|---|
| **Mentioned** | The brand is named in the answer. | Awareness, but could be negative or incidental. |
| **Cited** | A brand-owned URL is among the answer's sources. | Traffic path and evidence the engine read your page. Citation is not endorsement. |
| **Recommended** | The answer clearly offers or endorses the brand as an option for the user's need, with positive framing. A neutral mention is "mentioned", not recommended. | The outcome that drives choice. This is the north-star metric. |

**Recommendation Share (RS)** = share of answers that recommend the brand, computed per prompt (mean over engines and repeats) and averaged over the **buying questions** only (awareness and consideration prompts). Report it per engine and overall, with its interval. In plain words: "AI recommends you in X% of buying questions."

**Reputation check** = the same share over the brand-name questions ("is Acme legit", "Acme pricing"). Those questions name the brand, so the answer almost always mentions it. They are shown on their own line and never averaged into the headline; otherwise a true 5% discovery rate can read as about 37%.

**What counts as recommended when answers are imported automatically:** only positive wording, and never negative wording. A mention position score says where the brand appeared in the answer, not whether it was recommended, so it never counts by itself. Every other mention goes to a review list with the sentence around it, because being named is not the same as being recommended.

**`metric_version`.** Every saved row carries the version of this counting rule (currently 2). A round saved without it (version 1) counted any non-negative mention as a recommendation and had brand-name questions in the headline. Version 1 and version 2 rounds are never compared with each other; the report says so and the change reads "not comparable".

## Why the design looks like this
- **Frozen panel.** Compare like with like: the same prompts every time. Editing prompts after seeing results turns the metric into a marketing tool.
- **Repeats (3 or more).** Answers differ run to run; back-to-back repeats agree only part of the time. One run is an anecdote.
- **Prompts are the unit, not individual runs.** Repeats of one prompt are correlated, so treating 180 runs as 180 independent samples fakes certainty. Intervals resample prompts (bootstrap, fixed seed). The pooled Wilson interval is shown for mention and cite rates only as a rough guide.
- **Control prompts.** Questions where the brand should not be recommended. They sit near zero, so they are a false-positive check: if controls show recommendations, the rubric or the engine is noisy. Report the false-positive rate next to RS. They are a weak drift signal, because a rate pinned near zero cannot fall, and a rise only shows when the engines start recommending the brand in unrelated topics. Drift is also read from how much the *other* buying questions moved (see experiments below), and an overall "improved" or "worsened" is only kept when it survives the controls' own movement; otherwise the verdict is "engines moved".
- **Paired comparison.** Change in RS is computed per prompt (current minus baseline), then summarised, so easy and hard prompts do not distort the result.
- **Difference-in-differences for experiments.** For each logged change, the prompts it targeted are compared with the other prompts over the same window. `supported` needs the interval of the difference to sit above zero; `inconclusive` is the honest default. When the other prompts rose too, the report says so ("other prompts rose too, likely engine-wide") instead of letting a rise on the targets read as a win.
- **Timing.** A change is only scored when it was made after the baseline round was measured and no later than the first day of the latest round (baseline date < change date <= current date). Anything else is shown as "not scored" with the reason. A change dated after the latest round was saved (the usual case when it is logged with today's date) is "not scored" until the next round. Rounds that carry no real dates, or the same date, cannot place a change between them either: give each round the date it was really measured.
- **Confounding.** A change is flagged when another change in the same window targeted any of the same prompts. Other changes' targets are left out of its comparison group when enough prompts remain.
- **Zero and near-zero results.** When every prompt is at 0% the interval is a rule-of-three upper bound (about 3 divided by the number of prompts, so 15% for 20 prompts); at 100% it is a lower bound; when every prompt changed by exactly the same amount (including no change at all) the interval reaches about 3 divided by the number of prompts to either side. The report never prints a zero-width interval such as "0.0% (0.0% to 0.0%)". Read a zero as "below about X%".
- **What this panel can see.** The report prints "smallest change this panel can reliably see: about N points", worked out from the width of the interval. When the interval includes zero but is wide enough to hide a change of 10 points or more, the verdict is "too early to tell" rather than "no detectable change".

## Minimums
- 3 repeats per prompt and engine before quoting a number; below that the report warns that answers vary run to run.
- At least 20 buying questions (awareness and consideration), not counting brand-name or control questions.
- At least 5 control prompts; fewer than 5 triggers a warning.
- An experiment needs at least 3 targeted prompts (fewer is always "inconclusive") and at least 3 comparison prompts left after other changes' targets are set aside.
- The same engines and the same number of repeats in every round. If they differ the report warns, and the overall change uses only the engines both rounds share.
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
