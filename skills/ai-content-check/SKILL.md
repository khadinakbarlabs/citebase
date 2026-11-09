---
name: ai-content-check
description: Detect AI-writing patterns in a draft with a local deterministic lint (density score, named tells, fixes). Use when the user asks if text sounds AI-generated, wants an AI content check, anti-slop audit, or a pre-publish style gate. Not a commercial detector and does not claim to beat GPTZero-class tools.
argument-hint: "[file path or pasted text]"
---

# AI content check

Talk like `../../references/plain-language.md`. Be honest: this finds **known AI style patterns**, not a secret model fingerprint.

## Input
A file path in the workspace, or pasted text.

## Web connector mode
Call `check_ai_content` with the pasted text (optional `threshold`, default 5). No Citebase fee; no Apify spend. Hand fails to `humanize-content`.

## Steps
1. Run the local linter (no network, no Apify fee):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ai_content_lint.py" --json --threshold 5 PATH
```

On the web connector, call `check_ai_content` with the text instead.

2. Explain density (hits per 1,000 words). Threshold default **5**; above that → revise.
3. Group the worst pattern ids using `../../references/ai-writing-patterns.md`.
4. Offer to hand off to `humanize-content` for a rewrite that preserves facts.
5. End with Done / Cost so far ($0) / Next.

## Rules
- Never invent facts to "fix" the score.
- Do not promise "this will pass Detector X".
- Flag scaled unreviewed AI pages as a spam risk; do not recommend them as a growth tactic.
