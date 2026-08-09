import csv
import io
from html import escape

from app.campaign import Campaign, CampaignRecord


def report_csv(leads: list[dict]) -> str:
    output = io.StringIO()
    fields = [
        "campaign_key",
        "created_at",
        "status",
        "outcome",
        "conversion_value",
        "assignee",
        "intent_score",
        "purchase_intent_score",
        "product_fit_score",
        "subreddit",
        "title",
        "permalink",
        "query",
        "response_type",
        "reason",
        "strategy_reason",
        "comment_text",
        "final_comment",
        "feedback_reason",
        "review_notes",
    ]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for lead in leads:
        writer.writerow({field: _csv_safe(lead.get(field, "")) for field in fields})
    return output.getvalue()


def render_report(
    campaign: Campaign,
    campaign_key: str,
    stats: dict,
    leads: list[dict],
    campaigns: list[CampaignRecord],
) -> str:
    by_status = stats.get("by_status", {})
    by_outcome = stats.get("by_outcome", {})
    replied = int(by_status.get("replied", 0))
    qualified = int(by_outcome.get("qualified_lead", 0))
    converted = int(by_outcome.get("converted", 0))
    positive = int(by_outcome.get("positive_reply", 0))
    response_rate = replied / stats.get("leads_total", 1) if stats.get("leads_total") else 0
    qualified_rate = stats.get("qualified_rate", 0)
    rows = "".join(_row(lead) for lead in leads)
    if not rows:
        rows = '<tr><td colspan="8" class="empty">No opportunities recorded yet.</td></tr>'
    options = "".join(
        f'<option value="{escape(record.key)}"'
        f'{" selected" if record.key == campaign_key else ""}>'
        f'{escape(record.campaign.name)}</option>'
        for record in campaigns
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(campaign.name)} Performance · Reddit Lead Finder</title>
<style>
:root{{--bg:#f7f8fc;--panel:#fff;--line:#e3e6f1;--text:#20233b;--muted:#6f7591;--purple:#6c63ff;--purple-soft:#ecebff;--mint:#1db88c}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 95% 0,#efeaff 0,transparent 28%),var(--bg);color:var(--text);font:14px/1.5 Inter,system-ui,sans-serif}}header,main{{max-width:1280px;margin:auto;padding:24px}}header{{display:flex;justify-content:space-between;gap:16px;align-items:center}}h1{{letter-spacing:-.5px}}a{{color:#5a52df}}select,.button{{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:10px;padding:9px 11px;text-decoration:none}}.stats{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}}.stat{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:15px;box-shadow:0 8px 22px rgba(41,46,100,.04)}}.stat b{{font-size:24px;display:block;color:var(--purple)}}.stat span,.muted{{color:var(--muted)}}.toolbar{{display:flex;justify-content:space-between;align-items:center;margin:24px 0 12px}}.table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:14px;box-shadow:0 8px 22px rgba(41,46,100,.04)}}table{{width:100%;border-collapse:collapse;background:var(--panel)}}th,td{{padding:11px 12px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}th{{color:var(--muted);font-size:12px;text-transform:uppercase;background:#fafbfe}}td.title{{min-width:280px;white-space:normal}}.empty{{text-align:center;padding:40px}}@media(max-width:900px){{.stats{{grid-template-columns:repeat(2,1fr)}}header{{align-items:flex-start;flex-direction:column}}}}
</style></head><body>
<header><div><a href="/?campaign={escape(campaign_key)}">← Reply Opportunities</a><h1>{escape(campaign.name)} Performance</h1><div class="muted">{escape(campaign.product.name)} · Reddit reply opportunity pipeline</div></div><div><select id="campaign">{options}</select> <a class="button" href="/report.csv?campaign={escape(campaign_key)}">Download CSV</a></div></header>
<main><section class="stats">
<div class="stat"><b>{stats.get('posts_seen',0)}</b><span>Posts processed</span></div>
<div class="stat"><b>{stats.get('leads_total',0)}</b><span>Qualified opportunities</span></div>
<div class="stat"><b>{replied}</b><span>Replies published</span></div>
<div class="stat"><b>{positive}</b><span>Positive replies</span></div>
<div class="stat"><b>{qualified + converted}</b><span>Qualified outcomes</span></div>
<div class="stat"><b>${float(stats.get('conversion_value',0)):,.0f}</b><span>Tracked value</span></div>
</section>
<div class="toolbar"><div><strong>Reply rate:</strong> {response_rate:.0%} &nbsp; <strong>Qualified outcome rate:</strong> {qualified_rate:.0%}</div><div class="muted">Update outcomes from Reply Opportunities.</div></div>
<div class="table-wrap"><table><thead><tr><th>Date</th><th>Status</th><th>Outcome</th><th>Assignee</th><th>Score</th><th>Subreddit</th><th>Opportunity</th><th>Value</th></tr></thead><tbody>{rows}</tbody></table></div>
</main><script>document.getElementById('campaign').onchange=e=>location.href='/report?campaign='+encodeURIComponent(e.target.value)</script></body></html>"""


def _row(lead: dict) -> str:
    title = escape(str(lead.get("title") or "Untitled"))
    url = escape(str(lead.get("permalink") or ""))
    return "".join(
        [
            "<tr>",
            f"<td>{escape(str(lead.get('created_at') or '')[:10])}</td>",
            f"<td>{escape(_status_label(str(lead.get('status') or 'new')))}</td>",
            f"<td>{escape(str(lead.get('outcome') or 'none').replace('_', ' '))}</td>",
            f"<td>{escape(str(lead.get('assignee') or ''))}</td>",
            f"<td>{float(lead.get('intent_score') or 0):.2f}</td>",
            f"<td>r/{escape(str(lead.get('subreddit') or 'unknown'))}</td>",
            f'<td class="title"><a href="{url}" target="_blank" rel="noopener noreferrer">{title}</a></td>',
            f"<td>${float(lead.get('conversion_value') or 0):,.0f}</td>",
            "</tr>",
        ]
    )


def _csv_safe(value):
    """Prevent user-controlled Reddit text from becoming a spreadsheet formula."""
    if not isinstance(value, str):
        return value
    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _status_label(value: str) -> str:
    return {
        "new": "Needs review",
        "approved": "Ready to reply",
        "replied": "Published",
        "skipped": "Skipped",
    }.get(value, value.replace("_", " ").title())
