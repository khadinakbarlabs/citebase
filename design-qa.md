# Citebase design review

20 November 2026. The review compared the published Featured Forge landing page with the production Citebase homepage and the sample Acme Payroll dashboard. The landing screenshots show the signed-in Citebase entry point. The dashboard screenshots use the public fictional project. [Featured Forge](https://featuredforge.vercel.app/) · [Citebase](https://citebase-iota.vercel.app/) · [Sample project](https://citebase-iota.vercel.app/app/?demo=1#/p/acme-payroll/overview)

## Findings and fixes

| Priority and location | What the comparison exposed | Fix and verification |
| --- | --- | --- |
| P1 · Dashboard header on tablets | A real account's billing message competed with the persistent navigation. A returning user could lose access to a section at intermediate widths. | The header gives navigation a dedicated row from 781 through 1080 CSS pixels. The signed-in browser fixture checked the links at 800 pixels with the billing message present. |
| P2 · Landing navigation on small phones | The theme control crowded the brand at 390 pixels. At 320 pixels the navigation could overflow. | Compact spacing and a collapsible menu keep the controls reachable. The 320-pixel regression passed. At 390 pixels the live menu opened by keyboard, navigated to Questions and closed, with zero horizontal overflow. |
| P2 · Sample workbench | The desktop examples ran vertically but lacked matching up and down keyboard navigation. | The tab list exposes its orientation and supports the corresponding arrows. The browser test changed the selection from the keyboard. On phones the tabs sit above the example. |
| P2 · Selected values and form states | Dark-mode fields and some heatmap and error states needed stronger contrast. A selected metric also needed to remain identifiable when the browser supplies its own colors. | Updated field, text and state colors. The strong heatmap cell reached 5.46:1 text contrast. A double border identifies the selection in forced-colors mode. Keyboard and contrast review passed. |

## Visual comparison

The desktop captures contain 1280 × 720 image pixels at a 1280 × 720 CSS viewport. The phone captures contain 390 × 844 image pixels at a 390 × 844 CSS viewport. Each pair uses one image pixel per CSS pixel, light mode and page content without browser chrome. The phone dashboard capture shows the state after selecting Site health.

| View | Source capture | Production capture |
| --- | --- | --- |
| Desktop landing | [Featured Forge hero](/Users/khadinakbar/.codex/visualizations/2026/11/19/01a1f3f3-505b-79d3-a201-289ceda6cb73/featured-forge-landing-reference.jpg) | [Citebase hero](/Users/khadinakbar/.codex/visualizations/2026/11/19/01a1f3f3-505b-79d3-a201-289ceda6cb73/citebase-forge-landing-live.jpg) |
| Desktop cards | [Featured Forge workflow](/Users/khadinakbar/.codex/visualizations/2026/11/19/01a1f3f3-505b-79d3-a201-289ceda6cb73/featured-forge-workflow-reference.jpg) | [Citebase project overview](/Users/khadinakbar/.codex/visualizations/2026/11/19/01a1f3f3-505b-79d3-a201-289ceda6cb73/citebase-forge-dashboard-live.jpg) |
| Phone | [Featured Forge landing](/Users/khadinakbar/.codex/visualizations/2026/11/19/01a1f3f3-505b-79d3-a201-289ceda6cb73/featured-forge-mobile-reference.jpg) | [Citebase landing](/Users/khadinakbar/.codex/visualizations/2026/11/19/01a1f3f3-505b-79d3-a201-289ceda6cb73/citebase-forge-landing-mobile.jpg) · [Citebase project overview](/Users/khadinakbar/.codex/visualizations/2026/11/19/01a1f3f3-505b-79d3-a201-289ceda6cb73/citebase-forge-dashboard-mobile.jpg) |

- **Header and hero.** Both pages place a light, inset navigation bar above a centered headline and two pill-shaped actions. The lavender grid is visible around the content. Featured Forge’s desktop headline measured 97.6 pixels at weight 760. Citebase’s Manrope headline measured 92.8 pixels at weight 770. Compact tracking and a 0.99 line height keep the question on two desktop lines and three phone lines. Geist body and control text retain regular spacing, with system fallbacks. Both fonts are served by Citebase.
- **Cards and hierarchy.** Featured Forge uses a three-card row to explain its process. Citebase carries the rounded corners, pale borders, soft shadows and violet icon backgrounds into a four-metric row. The selected metric is a solid violet card with a visible label and value. Two columns fit on a phone. The tighter dashboard headings leave the next recommended action visible below the metrics.
- **Color, assets and content.** The primary light-mode action uses `#6d31ed`. Alerts retain distinct colors and text. The Citebase mark and vector interface icons stay legible at navigation size. The homepage replaces Featured Forge’s service preview with an interactive example of a buyer question, the evidence and the suggested action. The sample is labeled fictional in both the homepage and the dashboard. The production sign-in control displayed Dashboard for a returning user.

## Verification

- [x] Compared full desktop and mobile captures, then checked navigation, headline wrapping, button labels, card selection and the example workbench at the same scale.
- [x] Switched examples and metrics, filtered the sample portfolio and opened the mobile navigation. Light and dark choices persisted between screens. The production desktop landing, sample project and mobile landing recorded zero browser console errors.
- [x] Ran the local suite with connector dependencies enabled. All 1,232 tests passed. Separate Chromium journeys covered saved sign-in, project creation, audit results, the schedule planner and credit guidance.
- [x] Verified the canonical Vercel deployment `dpl_2g1TVBHdWMrefLYgpVkKgw37uRyh`, all 31 deployed public assets, the OAuth redirect and the signed-out protections on the Actor endpoint.

## Final result

passed

## Guided sample and account onboarding

Production release `dpl_HD8Q3pZ82pfS1AzXtTzn3aEebxiR` adds a desktop and mobile walkthrough across the actual project screens. The visitor can filter a buyer question, inspect a website finding, read an action and review an example schedule. Signed-in users see project-specific assistant setup and a private billing reference alongside current monthly usage. The signed-in personal and organization accounts each saved a project through the dashboard. A new browser tab returned to the personal workspace directly.

All 34 public files matched production. The 1,233-test suite passed. Separate browser checks covered the five tour steps, mobile width, seven assistant guides, account isolation and positive and zero prepaid balances.
