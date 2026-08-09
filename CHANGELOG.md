# Changelog

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
