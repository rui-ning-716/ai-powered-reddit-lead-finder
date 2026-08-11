# Roadmap

Reddit Lead Finder 0.6 is intended for operator-managed paid pilots. It is not yet a
public multi-tenant SaaS.

## Pilot-ready foundation

- campaign-level data isolation;
- opportunity mapping and campaign setup;
- AI qualification, strategy, and drafting;
- approval, assignment, publishing feedback, and outcome tracking;
- Slack, email, reports, and CSV export;
- optional dashboard password protection.

## Recommended next milestone

1. Add an approved production Reddit data provider behind a provider interface.
2. Move scans and AI work into a durable background job queue.
3. Add per-campaign notification destinations and response-time controls.
4. Add structured subreddit-rule review dates and operator reminders.
5. Add automatic weekly insight reports and CRM lead creation.
6. Add database backups, retention controls, and operational monitoring.

## Before public self-serve SaaS

- organization accounts and invitations;
- role-based permissions and audit logs;
- secure secret storage and encryption strategy;
- tenant-aware quotas and billing;
- account recovery, deletion, and data export;
- abuse prevention and rate limiting;
- production database migrations and disaster recovery;
- privacy, terms, and data-processing documentation.

Automatic Reddit posting, account farming, concealed endorsements, and
coordinated voting are intentionally out of scope.
