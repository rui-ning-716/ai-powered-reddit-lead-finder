# Changelog

## 0.7.5

- Increased the production default from 25 to 150 AI-analyzed new posts per scan.
- Changed the automatic Perplexity discovery schedule from every six hours to every hour.
- Applied both defaults in application settings and `.env.example`, so fresh installs and
  deployments without explicit overrides behave consistently.

## 0.7.4

- Removed the Market setup checkbox that required a country, customer, or location
  signal. Older campaign files still load, but the legacy field is ignored.
- Replaced the conflicting model boolean plus score gate with one deterministic
  qualification decision based on the visible component scores and campaign threshold.
- Recalibrated AI buying-intent guidance so category recommendations, comparisons,
  migrations, quotes, replacements, build-versus-buy decisions, and competitor pain do
  not require an explicit campaign-brand mention.
- Changed missing geography, budget, company size, timeline, and customer details from
  disqualifiers to unknown evidence. Only an explicit market mismatch can reduce priority.
- Reduced the evidence-confidence penalty so incomplete search snippets cannot erase
  strong intent expressed in the Reddit title.
- Moved excluded terms out of pre-AI substring filtering. Semantic qualification can now
  preserve cases such as an author outgrowing a free CRM and seeking a paid replacement.
- Fixed discovery ranking so the Perplexity query itself cannot make an unrelated result
  look high-intent. Author titles and post excerpts now control ranking, with extra weight
  for direct questions and evaluation language.
- Removed the redundant scanner-level market-fit gate that could prevent a qualified post
  from receiving a reply strategy and draft.

## 0.7.3

- Fixed the exact-phrase market prefilter that removed hundreds of semantically
  relevant posts before AI analysis when "Require market signal" was enabled.
- Moved market-signal enforcement into semantic AI qualification and made the
  checkbox a hard gate only when the operator enables it.
- Kept strict recent-post filtering and changed generated campaigns to default to
  seven days, with 30 days available for lower-volume categories.
- Added product, pricing, upgrade, competitor migration, and replacement query
  variants for high-intent discovery.
- Ranked active evaluation, recommendation, pricing, switching, and migration
  conversations ahead of generic mentions before the OpenAI analysis limit is applied.

## 0.7.2

- Fixed Perplexity Search API requests to send one supported string query at a time.
- Broadened Reddit result normalization to accept canonical, old Reddit, query-string,
  and provider-supplied post identity formats.
- Added discovery diagnostics for planned queries, raw results, valid Reddit posts,
  and rejected result counts.

## 0.7.1

- Expanded the default discovery capacity to 40 campaign queries, 20 Perplexity results per query, and 25 AI-reviewed posts per scan.
- Preserved every broad buyer-language query before adding optional subreddit-specific variants, so a selected community cannot replace or narrow the primary search.
- Updated AI-generated discovery setup to use 12 to 20 natural-language queries across buyer needs, alternatives, comparisons, pricing, implementation, and pain points.
- Updated qualification guidance so semantic problem and intent matches do not require an exact campaign-product or keyword match.
- Preserved non-qualified but relevant candidates as visible **Skipped** records with the source post, scores, and AI reason. They never generate a reply draft or trigger notifications.

## 0.7.0

- Replaced the production Reddit RSS scan path with Perplexity Search API as the primary discovery provider.
- Added `reddit.com` domain filtering, campaign recency filters, and batches of up to five queries per request.
- Added an optional Apify Reddit Scraper fallback that runs only on primary failure or insufficient results.
- Added strict Apify result caps and disabled comment crawling and Actor-side AI analysis by default.
- Normalized Perplexity and Apify payloads into one post model before market filtering, age filtering, and deduplication.
- Added retry handling, provider-specific errors, partial-result preservation, and health endpoint configuration status.
- Changed automatic discovery to a cost-controlled six-hour default interval.
- Added Perplexity website research fallback when direct product-page reading is blocked.
- Allowed conservative website-only Product Setup generation instead of returning a blocking error.
- Added provider integration tests and runtime smoke coverage.

## 0.6.0

- Replaced burst-style full scans with a persistent per-feed schedule that wakes every 10 minutes.
- Limited each scheduler tick to 3 to 8 of the most-due RSS feeds and distributed work across campaigns in round-robin order.
- Added 8 to 15 seconds of randomized spacing between uncached Reddit RSS requests.
- Added separate automatic cadences for high-intent searches, standard searches, and adjacent or research communities.
- Persisted every feed's last attempt, last success, next due time, and error status in SQLite so restarts do not reset pacing.
- Changed HTTP 429 handling to stop the current scan immediately instead of retrying the same or remaining URLs.
- Added strict `Retry-After` support and persistent 2, 4, 8, and 12 hour cooldown escalation when Reddit omits the header.
- Kept the dashboard, existing opportunity review, editing, reporting, and notifications available while Reddit fetching is paused.

## 0.5.0

- Added a clean first-run screen with no preloaded demo product or language.
- Added website-to-setup onboarding: enter a public product URL and AI drafts Product, Market, Discovery, Qualification, Engagement, and Review & Test.
- Added safe public-page fetching with URL validation, private-network blocking, redirect checks, timeouts, page-size limits, and same-domain key-page research.
- Added optional operator notes and explicit review notes for uncertain AI assumptions.
- Added an operator-notes fallback when a valid public product site blocks automated reading.
- Added diverse lexical Reddit search-query generation and clearer search guidance.
- Kept generated brand mentions and links disabled until a human explicitly enables them.
- Renamed the operator navigation to Reply Opportunities, Product Setup, and Performance.
- Made the Reddit Lead Finder logo return to the Reply Opportunities home page.
- Preserved legacy `CAMPAIGN_PATH` and `CAMPAIGN_PATHS` behavior for existing installations.

## 0.4.0

- Added AI adaptive scoring as the default Campaign scoring mode.
- AI now infers product-specific evidence internally and returns an evidence-confidence score for every lead.
- Final priority now uses `positive need score × evidence confidence − risk deductions` while unsupported markets remain disqualified.
- Simplified the Campaign UI so operators do not need to configure scoring weights or hidden sub-signals.

## 0.3.0

- Replaced the fixed lead-score formula with a per-campaign scoring model.
- Added configurable relative weights for relevance, purchase intent, product fit, urgency, and reachability.
- Added configurable promotion-risk and market-mismatch deductions.
- Added campaign-specific sub-signals under every scoring dimension so teams can tune the AI's evaluation depth without editing code.
- Added Qualification-page controls and deterministic score breakdowns for AI test runs.

## 0.2.2

- Added persistent campaign workspaces: create a campaign from the UI and it receives its own YAML configuration, lead queue, and report.
- Added workspace switching and a clear New Campaign action on the Leads and Campaign pages.
- Added lead migration controls so mixed historical leads can be moved into the correct campaign without deleting them.
- Preserved the original `CAMPAIGN_PATHS` configuration as an advanced fallback for existing installations.

## 0.2.0

- Added explicit multi-campaign configuration with `CAMPAIGN_PATHS`.
- Isolated posts, drafts, feedback, and reporting by campaign.
- Allowed the same Reddit post to be evaluated for different products.
- Added core, adjacent, watch-only, and excluded community mapping.
- Added competitor inputs and expanded AI discovery suggestions.
- Added `new`, `approved`, `replied`, and `skipped` workflow states.
- Added opportunity assignment, outcomes, and conversion-value tracking.
- Added client-ready HTML reports and live CSV downloads.
- Added optional dashboard password protection and safer error responses.
- Fixed clean-environment execution for command-line helper scripts.
- Added managed-service tests and operating documentation.

## 0.1.0

- Initial open-source human-in-the-loop Reddit opportunity workflow.
