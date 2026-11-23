# Citebase — Google app approval pack

Prepared 23 November 2026 for Phase 2. Google Cloud project: **Citebase** (`citebase-515306`), owner `hello@khadinakbar.com`. Today the app is in **Testing** with two testers. Google normally ends a test app's sign-in after about 7 days, and only listed testers can connect.

The goal is to move the app to **In production** and pass Google's check for its three **sensitive** permissions. None of them are **restricted**, so the paid security audit (CASA) should not be needed.

## What Google asks for (and status)

| Item | Status |
|---|---|
| App name, logo, support email | Name and email set. Logo 120×120 PNG still to upload (from `site/favicon.svg`) |
| App home page on a domain we own | **Waiting on address choice** (`citebase-iota.vercel.app` cannot be approved) |
| Privacy policy on that domain | Done: `/privacy/` (moves with the site) |
| Terms of service | Done: `/terms/` |
| Domain proven in Search Console by the project owner | After the address is chosen |
| Redirect address updated to the new domain | After the move: `https://<domain>/api/google` |
| Reason for each permission | Below |
| Demo video (unlisted YouTube) | Script below; record after the move |

## Permissions and the reason to paste

**`https://www.googleapis.com/auth/webmasters.readonly`** (Search Console, read only)
> Citebase shows website owners their own Google Search performance next to how AI assistants mention them. After the user picks one of their Search Console properties, Citebase reads clicks, impressions, average position, search queries, pages, countries, devices and daily totals for the last 28 days and the 28 days before. It shows them in the Search tab and uses them to point out searches where the site ranks but gets few clicks. Read-only access is the narrowest scope that returns this data. Citebase never changes Search Console settings.

**`https://www.googleapis.com/auth/analytics.readonly`** (Google Analytics, read only)
> Citebase shows how many visits a website gets from AI assistants such as ChatGPT and Perplexity, compared with all other sources. After the user picks one of their GA4 properties, Citebase reads sessions by source and landing page and shows them in the Traffic tab. Read-only access is the narrowest scope that returns this report. Citebase never changes Analytics settings or data.

**`https://www.googleapis.com/auth/gmail.send`** (send only)
> Citebase helps users ask websites that AI assistants cite to mention their business. The user writes or edits each outreach email in Citebase and approves it. Only then does Citebase send that single email from the user's own Gmail. Citebase cannot read, search or delete mail. Send-only is the narrowest scope that lets the email come from the user's own address.

**Data handling (for the form):** tokens are encrypted with AES-256-GCM and stored in a restricted key-value store in the user's own Apify account. Google data is never sold, never used for ads and never used to train AI models. Disconnecting deletes the stored token. We follow the Google API Services User Data Policy, including Limited Use.

## Demo video script (2–3 minutes, English, unlisted on YouTube)

1. Show the browser address bar on `https://<domain>/` and the Citebase home page. Open `/privacy/`.
2. Sign in to Citebase. Open a project and go to **Connections**.
3. Click **Connect** for Search Console. Show Google's consent screen with the app name **Citebase**, the domain, and the permission. Approve it. Pick a property and click **Import 28 days**. Open the **Search** tab and show the data being used.
4. Do the same for Google Analytics. Show the **Traffic** tab with "Visits from AI".
5. Connect Gmail and show the send-only consent screen. In **Outreach**, open a draft, edit it, approve it, then send it to a test inbox you own. Show the email arriving.
6. Back in **Connections**, click **Disconnect** for one service to show the token being removed.

## Steps after the address is chosen

1. Point the domain at the `citebase` Vercel project. Rebuild with `--site https://<domain>`, then deploy.
2. Update the Vercel environment variable `CITEBASE_GOOGLE_REDIRECT_URI` to `https://<domain>/api/google`. Add that redirect and the JavaScript origin to the Google OAuth client.
3. Prove the domain in Search Console with `hello@khadinakbar.com`.
4. Branding page: home page, privacy page, terms page, authorized domain, logo.
5. Record the video and fill in the permission reasons above.
6. Click **Publish app**, then **Prepare for verification**, and submit.
7. Keep `citebase-iota.vercel.app` redirecting to the new domain. Apify sign-in uses `oauth-client.json` on the site address, so check sign-in after the move.
