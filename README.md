
## Demo

Watch the 1-minute setup walkthrough: [Reddit Lead Finder Campaign Setup Guide](https://app.trupeer.ai/view/FdXsaIf6o/reddit-lead-finder)

## Preview

### Lead review dashboard

![Lead review dashboard](dashboard-preview.png)

### Campaign setup

![Campaign setup](campaign-setup.png)

# Reddit Lead Finder

Find Reddit users who are already looking for what you sell.

Reddit Lead Finder is an open-source, self-hosted, human-in-the-loop Reddit lead
discovery system. It monitors product-relevant conversations, filters for
market and customer fit, scores buying intent, recommends how to engage,
drafts a useful reply, and sends qualified opportunities to Slack or email.
It never auto-posts.

## Why Reddit Lead Finder

Keyword alerts create noise. Fully automated outreach creates spam. Reddit Lead Finder
sits between them:

1. Discover conversations from campaign-specific Reddit searches.
2. Apply deterministic market and subreddit filters before using an LLM.
3. Score relevance, purchase intent, product fit, urgency, reachability, market
   fit, and promotion risk.
4. Choose `helpful_only`, `expert_answer`, `soft_mention`,
   `direct_recommendation`, or `skip`.
5. Generate a concise draft under campaign-specific disclosure rules.
6. Notify a human, who checks the post and community rules before replying.
7. Save replied and skipped feedback for a future learning loop.

Built for teams that want a repeatable Reddit research and response workflow
without automating publication. The public version contains no private business
data.

## Features

- YAML campaigns for any product, market, and customer profile
- Managed multi-campaign workspaces with campaign-level data isolation
- Six-step browser onboarding for Product, Market, Discovery, Qualification,
  Engagement, and Review & Test
- AI-assisted keyword, subreddit, and buying-signal suggestions
- Structured core, adjacent, watch-only, and excluded community mapping
- Sample-post testing before the first real scan
- Configurable keywords, subreddits, exclusions, lookback, and thresholds
- Explainable multi-dimensional lead scoring
- Strategy selection before draft generation
- Brand disclosure and link controls
- Original post excerpts and browser-local timestamps in the review dashboard
- Concrete comparison drafts with named options and practical tradeoffs
- No fabricated personal experience
- Local FastAPI dashboard
- Slack, email, CSV, Markdown, and SQLite output
- Replied, skipped, feedback reason, and final-reply capture
- New, approved, replied, and skipped review workflow
- Opportunity assignment, outcome, and conversion-value tracking
- Client-ready HTML report and live CSV export
- Optional password protection for externally reachable dashboards
- Cross-post deduplication
- Reddit RSS caching, exponential backoff, manual cooldown, and circuit breaker
- Docker and Docker Compose support

## Quick start

```bash
git clone https://github.com/rui-ning-716/reddit-lead-finder.git
cd reddit-lead-finder
cp .env.example .env
```

Add your OpenAI API key and a descriptive Reddit User-Agent to `.env`:

```text
OPENAI_API_KEY=your_key_here
REDDIT_USER_AGENT="reddit-lead-finder/0.2 (contact: you@example.com)"
```

Start with Docker:

```bash
docker compose up --build
```

Open `http://localhost:8000`.

Open `http://localhost:8000/campaign` to configure the first campaign in the
browser. Use **+ New** to create a separate product or client workspace. Each
workspace keeps its own YAML configuration, leads, and report.

To explore the dashboard without calling Reddit or an LLM, seed one synthetic
lead before starting the server:

```bash
docker compose run --rm reddit-lead-finder python -m scripts.seed_demo
```

### Run locally without Docker

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The scheduler scans every 30 minutes by default. To trigger a manual scan:

```bash
curl -X POST http://localhost:8000/scan-now
```

## Configure a campaign

### Browser setup

The Campaign page lets a user complete the full setup without editing YAML:

1. Describe the product, value propositions, target customers, and limitations.
2. Choose markets, languages, customer signals, and exclusions.
3. Add queries and subreddits, or ask AI to suggest them.
4. Select a qualification preset and customize positive and negative signals.
5. Set brand, link, disclosure, tone, and length guardrails.
6. Paste a sample Reddit post to preview scores, strategy, and draft.

Use **Save campaign** to update the current workspace YAML or **Save and run
scan** to save and immediately start a manual scan. Saving is rejected while
another scan is active, preventing a scan from mixing two configurations.

### YAML setup

Advanced users can copy a template from `campaigns/` and edit it directly:

```yaml
name: AI Meeting Notes

product:
  name: ExampleNotes
  description: AI meeting summaries and action-item extraction.
  website: https://example.com
  value_propositions:
    - Automatic summaries
    - Action item extraction
  limitations:
    - Does not support offline meetings
  target_customers:
    - Startup founders
    - Remote teams

market:
  countries: [United States, Canada]
  languages: [English]
  customer_signals: [startup, founder, remote team]
  exclude_terms: []
  require_market_signal: false

discovery:
  keywords:
    - '"meeting notes tool"'
    - '"AI meeting assistant"'
    - '"Otter alternative"'
  subreddits: [all]
  excluded_subreddits: [selfpromotion]
  lookback: week
  sort: new
  limit_per_keyword: 25

qualification:
  minimum_lead_score: 0.72
  positive_signals:
    - Asking for recommendations
    - Comparing products
  negative_signals:
    - Job listing
    - Promotional post

engagement:
  allow_brand_mentions: true
  allow_links: false
  tone: Helpful, concise, transparent, and non-salesy
  disclosure: I work on ExampleNotes, so I may be biased.
  max_words: 140
```

Three templates are included:

- `example_saas.yaml`
- `example_local_service.yaml`
- `example_developer_tool.yaml`

## Managed multi-campaign workspace

V0.2.2 can run several client or product campaigns in one operator workspace.
Use **+ New** in the dashboard or Campaign page to create a separate workspace.
Each workspace gets its own campaign YAML file, lead queue, notifications, and
report. The scheduler scans every configured campaign, and the same Reddit post can
be evaluated independently for two products without mixing their histories.

For an existing advanced deployment, `CAMPAIGN_PATHS` remains supported as a manual
fallback. Once a campaign is created in the UI, `campaigns/workspace.yaml` becomes
the source of truth for the workspace.

The managed review workflow is:

```text
new -> approved -> replied -> outcome
                \-> skipped
```

An operator can assign each opportunity, save the final published reply, and
record `positive_reply`, `qualified_lead`, `converted`, or `no_response`.
Converted opportunities can include a value for client reporting.

Open `/report` for pipeline metrics or `/report.csv` for a live export. See
[`docs/MANAGED_SERVICE.md`](docs/MANAGED_SERVICE.md) for the recommended pilot
setup and operating procedure. The boundary between the pilot workspace and a
public SaaS is documented in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Lead scoring

The LLM returns separate scores instead of treating keyword relevance as intent:

| Dimension | Meaning |
| --- | --- |
| Relevance | Does the post match the problem? |
| Purchase intent | Is the author seeking, comparing, replacing, or paying? |
| Product fit | Can the product genuinely solve the need? |
| Urgency | Does the author need a solution soon? |
| Reachability | Can one public reply help? |
| Market fit | Does the author match the configured market? |
| Promotion risk | Would a brand response feel intrusive? |

Reddit Lead Finder recalculates the final score in code using 25% relevance, 30%
purchase intent, 25% product fit, 10% urgency, and 10% reachability, then applies
market-fit and promotion-risk penalties. The LLM cannot override this formula.
Urgency is capped at 0.60 unless the original post contains an explicit deadline
or time-sensitive phrase. The final threshold comes from the campaign.

## Response strategies

- `helpful_only`: answer without mentioning the product
- `expert_answer`: provide domain guidance without mentioning the product
- `soft_mention`: help first, then disclose affiliation and mention briefly
- `direct_recommendation`: only for an explicit request with strong product fit
- `skip`: do not engage

Brand mentions and links are removed when the campaign or selected strategy
does not allow them. A mention strategy is automatically downgraded to
`expert_answer` when the final reply cannot mention the campaign product, so the
dashboard label and generated draft stay consistent.

## Feedback data

The dashboard records:

- `new`, `approved`, `replied`, or `skipped`
- optional skip reason
- optional final reply text
- assignee, review notes, outcome, and conversion value
- generated draft and selected strategy
- all component scores and detected signals

V0.2 captures this cleanly but does not retrain a model automatically.

## Dashboard access protection

The dashboard is open by default for local use. If it is reachable outside your
computer, configure both values below and place the service behind HTTPS:

```text
DASHBOARD_USERNAME=operator
DASHBOARD_PASSWORD=use-a-long-unique-password
```

This optional HTTP Basic protection is suitable for an operator-run pilot. It
is not a replacement for organization accounts, role-based access control,
audit logs, and single sign-on in a public multi-tenant SaaS.

## Notifications

Slack uses an Incoming Webhook:

```text
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_MIN_INTENT_SCORE=0.72
```

Email uses SMTP:

```text
EMAIL_NOTIFICATIONS_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@example.com
SMTP_PASSWORD=app-password
EMAIL_FROM=you@example.com
EMAIL_TO=owner@example.com,teammate@example.com
```

Notification failures do not stop scanning.

## Reddit rate limits

Reddit RSS may return HTTP 429. Reddit Lead Finder caches feeds, retries with
exponential backoff, respects `Retry-After`, and opens a circuit breaker after
repeated rate limits. The default cooldown is 120 minutes. Manual scans have a
separate 15-minute cooldown.

RSS is convenient but less reliable than registered API access. Keep request
volume conservative and review current Reddit developer requirements before
production use.

## Safety and community respect

Reddit Lead Finder deliberately does not post comments, send DMs, vote, create
accounts, or hide affiliation. Before replying:

1. Read the full thread.
2. Check subreddit rules.
3. Edit the draft so it accurately reflects your knowledge and relationship.
4. Disclose affiliation when mentioning your product.
5. Skip any conversation where participation would feel intrusive.

Repeated or unsolicited mass engagement is prohibited by Reddit. See Reddit's
[Spam policy](https://support.reddithelp.com/hc/en-us/articles/360043504051-Spam)
and [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy).

## Development

```bash
make install
make test
make check
```

Never commit `.env`, `data/`, exports, or SQLite files. See `SECURITY.md`.

## Roadmap

- Feedback-aware ranking from replied and skipped examples
- Additional LLM providers and local models
- Registered Reddit API discovery provider
- Generic webhooks and more notification providers
- Optional browser helper for carrying an approved draft to Reddit

## License

MIT
