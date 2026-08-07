# Changelog

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
