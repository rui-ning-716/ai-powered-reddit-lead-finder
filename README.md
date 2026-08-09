# Reddit Lead Finder

Find Reddit users who are already looking for what you sell.

Reddit Lead Finder is an open-source, self-hosted, human-in-the-loop Reddit lead
discovery system. It monitors product-relevant conversations, filters for
market and customer fit, scores buying intent, recommends how to engage,
drafts a useful reply, and sends qualified opportunities to Slack or email.
It never auto-posts.

## New in V0.5

Fresh installations now open on a clean website-first onboarding screen. Enter a
public product URL and AI drafts the complete six-step Product Setup for human
review: Product, Market, Discovery, Qualification, Engagement, and Review & Test.
No demo product, default language, brand mention, link permission, or Reddit scan
is created automatically.

If a valid website blocks automated reading, add a concise product description
under optional product notes. AI can then draft the setup from those notes while
marking assumptions for review.

The website reader only accepts public HTTP and HTTPS pages. It blocks private
network addresses, validates redirects, limits response size and page count, and
uses timeouts. Generated community names are candidates, not claims that a
subreddit permits promotion. The operator must still review current rules.

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
- Website-to-setup AI generation across all six sections
- Clean empty first run with no preloaded demo product
- AI-assisted keyword, subreddit, and buying-signal suggestions
- Structured core, adjacent, watch-only, and excluded community mapping
- Sample-post testing before the first real scan
- Configurable keywords, subreddits, exclusions, lookback, thresholds, score weights, and risk deductions
- Explainable multi-dimensional lead scoring
- Fine-grained AI evaluation signals under each scoring dimension
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
REDDIT_USER_AGENT="reddit-lead-finder/0.5 (contact: you@example.com)"
```

Start with Docker:

```bash
docker compose up --build
```


Open `http://localhost:8000`. On a fresh installation, enter a public product
website and select **Generate product setup**. Review the AI draft before saving.
Use **+ Add product** to create another isolated product workspace. Each workspace
keeps its own YAML configuration, reply opportunities, and performance report.

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

## Configure a product

### Website-first browser setup

The Product Setup page lets a user complete the workflow without editing YAML.
For a new product, enter its public website. Reddit Lead Finder reads a limited
set of public same-domain product pages, then AI drafts all six sections:

1. Describe the product, value propositions, target customers, and limitations.
2. Choose markets, languages, customer signals, and exclusions.
3. Review varied lexical search phrases and candidate subreddits.
4. Review positive and negative qualification signals and the AI-adaptive threshold.
5. Set brand, link, disclosure, tone, and length guardrails.
6. Paste a sample Reddit post to preview scores, strategy, and draft.

Use **Save product setup** to update the current workspace YAML or **Save and find
opportunities** to save and immediately start a manual scan. Saving is rejected while
another scan is active, preventing a scan from mixing two configurations.

Reddit RSS search is lexical. Search queries do not need to match an entire post
title, but Reddit first retrieves posts based on the words and phrases in each
query. Quotation marks make a multi-word phrase more exact. AI evaluates meaning
and buying intent only after Reddit returns a candidate post, so use several ways
a buyer might describe the same problem.

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
  score_model:
    # Relative importance. Values are normalized automatically.
    weights:
      relevance: 25
      purchase_intent: 30
      product_fit: 25
      urgency: 10
      reachability: 10
    # Deductions expressed as percentage points (0 to 100).
    promotion_risk_penalty: 15
    market_mismatch_penalty: 10
    # Optional campaign-specific evidence to assess beneath each dimension.
    dimension_signals:
      purchase_intent:
        - Explicitly asks for recommendations or alternatives
        - Is comparing, replacing, or evaluating a solution
        - Mentions a budget, trial, buying process, or timeline

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

## Multiple product workspaces

The application can run several client or product setups in one operator workspace.
Use **+ Add product** from Reply Opportunities or Product Setup to create a separate
workspace. Each workspace gets its own YAML file, opportunity queue, notifications,
and Performance page. The scheduler scans every configured product, and the same Reddit post can
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

Reddit Lead Finder recalculates the final score in code. Each campaign can set the
relative weight of relevance, purchase intent, product fit, urgency, and
reachability. The app normalizes these values automatically, then applies the
campaign's promotion-risk and market-mismatch deductions. It can also store custom
sub-signals beneath each dimension, so a team can define what "purchase intent" or
"product fit" means for its own product. The LLM cannot override the final formula.
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
