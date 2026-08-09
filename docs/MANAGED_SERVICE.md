# Reddit Lead Finder Managed Service Playbook

This guide describes the V0.2 operator workflow for running paid Reddit demand
capture pilots. Reddit Lead Finder prepares opportunities and responses. A client
employee or another transparent, authorized representative makes the final
posting decision.

## 1. Qualify the client before onboarding

A strong pilot client has:

- customers who ask for recommendations or compare products on Reddit;
- enough customer value to justify human review;
- a clear product, target customer, and conversion destination;
- someone who can publish and answer follow-up questions;
- no expectation of fake testimonials, karma farming, or coordinated voting.

Use historical Reddit searches to estimate weekly opportunity volume before
promising results.

## 2. Build the Reddit opportunity map

Create five query groups:

1. Brand: company and product names.
2. Category: the product category and common variations.
3. Competitors: alternatives, migrations, and comparison searches.
4. Problems: the language customers use before they know the category.
5. Buying triggers: recommendation, replacement, urgency, and willingness to pay.

Use Reddit search, Reddit Pro Trends, related-community maps, and manual review
to classify communities as core, adjacent, watch-only, or excluded. Enter only
communities appropriate for active monitoring into the campaign. Store
community-specific restrictions in the campaign notes or the client's operating
playbook.

## 3. Create and enable a client campaign

Open Product Setup and click **+ Add product**. Enter the client's public website,
generate the six-section draft, and review every field. Complete
all six setup steps, and test several historical posts before the first live
scan. The workspace automatically receives its own campaign YAML file, lead
queue, and report. No environment-variable changes or restart are required.

## 4. Calibrate before delivery

Review the first 20 to 50 analyzed posts. Adjust the campaign until most leads
above the threshold are genuinely actionable. Check:

- false positives caused by broad keywords;
- unsupported countries, industries, or use cases;
- posts that match the category but show no buying intent;
- subreddits where brand participation is not appropriate;
- drafts that make unsupported claims or sound promotional.

Do not lower the score threshold merely to increase lead volume.

## 5. Operate the daily queue

1. Review every `new` opportunity and the original Reddit post.
2. Confirm the subreddit rules and current conversation context.
3. Edit the draft if necessary.
4. Assign an owner and mark the opportunity `approved`.
5. The authorized client representative publishes the final response.
6. Save the final text and mark the opportunity `replied`.
7. Record the later outcome and any attributable conversion value.

Never publish automatically. Do not buy accounts, share personal accounts,
fabricate customer experience, farm karma, or coordinate votes.

## 6. Report and renew

Use `/report` for the client view and `/report.csv` for analysis. Report:

- posts processed;
- qualified opportunities;
- approved and published replies;
- positive replies and qualified leads;
- conversions and tracked value;
- common customer problems and competitor complaints;
- false-positive themes and campaign changes.

Avoid presenting views, upvotes, or karma as the primary commercial outcome.

## 7. Pilot deployment boundaries

V0.2 is designed for an operator-managed pilot. Use a separate deployment and
database when a client requires strict infrastructure isolation. Configure
dashboard credentials and HTTPS for any remotely reachable deployment.

Before offering a public self-serve SaaS, add organization accounts, role-based
permissions, durable job queues, audit logs, billing, usage limits, secret
management, backups, and an approved production Reddit data-access strategy.
