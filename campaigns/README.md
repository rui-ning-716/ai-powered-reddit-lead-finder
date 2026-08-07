# Campaign templates

`campaign.yaml` is the active browser-editable configuration by default. Copy
the closest example into it, or use the Campaign page to replace its contents.

- `example_saas.yaml`: broad product search with no required geographic signal
- `example_local_service.yaml`: location-bound service with required market terms
- `example_developer_tool.yaml`: technical product scoped to selected subreddits

Keep product limitations accurate. These constraints are provided to the LLM so
it can reject leads the product cannot serve. Use `exclude_terms` for strong
deterministic exclusions and `negative_signals` for contextual LLM judgment.

For a managed workspace, create one YAML file per client and enable only those
files with `CAMPAIGN_PATHS`. A file's name becomes its stable campaign key, so
use distinct names such as `acme-crm.yaml` and `northstar-notes.yaml`.

Use `subreddits` for core communities that should be actively monitored.
`adjacent_subreddits` and `watch_only_subreddits` document the wider opportunity
map but are not scanned automatically. Put community-specific disclosure,
promotion, or moderation guidance in `community_notes`.
