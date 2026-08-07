import json
from html import escape

from app.campaign import Campaign, CampaignRecord, get_campaign


def render_dashboard(
    leads: list[dict],
    stats: dict,
    campaign: Campaign | None = None,
    campaign_key: str = "campaign",
    campaigns: list[CampaignRecord] | None = None,
) -> str:
    campaign = campaign or get_campaign()
    status = stats.get("by_status", {})
    cards = "\n".join(_render_lead_card(lead, campaign, campaigns or []) for lead in leads)
    if not cards:
        cards = '<div class="empty"><h2>No qualified leads yet</h2><p>Run a scan after configuring your campaign.</p></div>'
    campaign_options = "".join(
        f'<option value="{escape(record.key)}"'
        f'{" selected" if record.key == campaign_key else ""}>'
        f'{escape(record.campaign.name)}</option>'
        for record in (campaigns or [])
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(campaign.name)} · Reddit Lead Finder</title>
<style>
:root{{--bg:#f7f8fc;--panel:#ffffff;--card:#f5f6ff;--line:#e3e6f1;--text:#20233b;--muted:#6f7591;--purple:#6c63ff;--purple-soft:#ecebff;--mint:#1db88c;--mint-soft:#e4f8f0;--amber:#ffb547;--amber-soft:#fff3db;--red:#e96370;--red-soft:#ffe9ec}}
*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 93% -5%,#efeaff 0,transparent 26%),radial-gradient(circle at 3% 12%,#e5fbf3 0,transparent 24%),var(--bg);color:var(--text);font:15px/1.5 Inter,ui-sans-serif,system-ui,sans-serif}}header{{padding:24px max(24px,calc((100% - 1240px)/2));background:rgba(255,255,255,.88);border-bottom:1px solid var(--line);backdrop-filter:blur(14px)}}h1{{margin:0 0 4px;font-size:28px;letter-spacing:-.6px}}header p{{margin:0;color:var(--muted)}}main{{max-width:1240px;margin:auto;padding:28px 24px 46px}}.brand-row{{display:flex;align-items:center;gap:11px}}.brand-dot{{width:14px;height:14px;border-radius:50%;background:linear-gradient(135deg,#ff856c,#ffc548);box-shadow:0 0 0 5px #fff2df}}.nav{{display:flex;align-items:center;gap:4px}}.nav a{{color:var(--muted);text-decoration:none;padding:9px 10px;border-radius:9px;font-weight:650}}.nav a:hover,.nav a.active{{color:var(--purple);background:var(--purple-soft)}}.nav select{{margin-right:6px}}.stats{{display:grid;grid-template-columns:repeat(5,1fr);gap:14px}}.stat,.card{{background:var(--panel);border:1px solid var(--line);border-radius:16px;box-shadow:0 10px 30px rgba(41,46,100,.04)}}.stat{{padding:18px}}.stat b{{display:block;font-size:29px;letter-spacing:-.8px}}.stat span,.muted{{color:var(--muted)}}.toolbar{{display:flex;justify-content:space-between;gap:12px;margin:22px 0;flex-wrap:wrap}}button,.button,select{{border:1px solid var(--line);border-radius:10px;background:var(--panel);color:var(--text);padding:9px 12px;cursor:pointer;text-decoration:none;font:inherit}}button:hover,.button:hover{{border-color:var(--purple);box-shadow:0 3px 12px rgba(108,99,255,.12)}}.primary{{background:var(--purple);border-color:var(--purple);color:#fff}}.success{{background:var(--mint-soft);border-color:#9de0ca;color:#087653}}.danger{{background:var(--red-soft);border-color:#f6b7c0;color:#b23b4b}}.filters{{display:flex;gap:8px;flex-wrap:wrap}}.cards{{display:grid;gap:16px}}.card{{padding:20px;border-left:4px solid var(--amber)}}.status-approved{{border-left-color:var(--purple)}}.status-replied{{border-left-color:var(--mint);opacity:.88}}.status-skipped{{border-left-color:var(--red);opacity:.76}}.badges,.actions,.scores{{display:flex;flex-wrap:wrap;gap:8px}}.badge{{font-size:12px;padding:4px 8px;border-radius:999px;background:#f0f2f8;color:#5b6382}}.score{{background:var(--purple-soft);color:#5149d4;font-weight:750}}h2{{font-size:19px;margin:12px 0 8px;letter-spacing:-.2px}}h2 a{{color:var(--text);text-decoration:none}}h2 a:hover{{color:var(--purple)}}.post-excerpt{{white-space:pre-wrap;background:#f8f9fd;border-radius:10px;padding:11px 12px;margin:12px 0;color:#505775}}.scores{{margin:12px 0}}.meter{{min-width:125px;background:#fafbfe;border:1px solid #edf0f6;border-radius:10px;padding:8px 10px}}.meter b{{display:block;color:var(--purple)}}.reason{{color:var(--muted);margin:10px 0}}.reason strong{{color:var(--text)}}.signals{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}}.signal{{background:#fafbfe;border:1px solid #edf0f6;border-radius:10px;padding:10px}}.signal ul{{margin:5px 0 0;padding-left:18px}}.draft{{white-space:pre-wrap;background:#f8f7ff;border:1px solid #e0defd;border-radius:11px;padding:14px;margin:14px 0}}.empty{{text-align:center;padding:70px;color:var(--muted)}}@media(max-width:760px){{.stats{{grid-template-columns:1fr 1fr}}.signals{{grid-template-columns:1fr}}main{{padding:14px}}header{{padding:18px 14px}}.nav{{flex-wrap:wrap;justify-content:flex-end}}}}
</style></head><body>
<header><div style="max-width:1240px;margin:auto;display:flex;justify-content:space-between;gap:16px;align-items:center"><div><div class="brand-row"><span class="brand-dot"></span><h1>Reddit Lead Finder</h1></div><p><strong>{escape(campaign.name)}</strong> · Find high-intent Reddit conversations for {escape(campaign.product.name)}. Every reply stays human-approved.</p></div><nav class="nav"><select id="campaign-switch">{campaign_options}</select><a class="active" href="/?campaign={escape(campaign_key)}">Leads</a><a href="/campaign?campaign={escape(campaign_key)}">Campaign</a><a href="/report?campaign={escape(campaign_key)}">Report</a><a href="/campaign?new=1">+ New</a></nav></div></header>
<main><section class="stats">
<div class="stat"><b>{stats.get('posts_seen',0)}</b><span>Posts processed</span></div>
<div class="stat"><b>{stats.get('leads_total',0)}</b><span>Qualified leads</span></div>
<div class="stat"><b>{status.get('new',0)}</b><span>Awaiting review</span></div>
<div class="stat"><b>{status.get('approved',0)}</b><span>Approved to publish</span></div>
<div class="stat"><b>{status.get('replied',0)}</b><span>Replied</span></div>
</section><div class="toolbar"><div class="filters">
<button data-filter="all">All</button><button data-filter="new">New</button><button data-filter="approved">Approved</button><button data-filter="replied">Replied</button><button data-filter="skipped">Skipped</button>
</div><button class="primary" id="scan">Run scan now</button></div><section class="cards">{cards}</section></main>
<script>
const campaignKey={json.dumps(campaign_key)};
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>document.querySelectorAll('.card').forEach(c=>c.hidden=b.dataset.filter!=='all'&&!c.classList.contains('status-'+b.dataset.filter)));
document.getElementById('campaign-switch').onchange=e=>location.href='/?campaign='+encodeURIComponent(e.target.value);
document.getElementById('scan').onclick=async e=>{{e.target.disabled=true;e.target.textContent='Scanning...';const r=await fetch('/scan-now?campaign='+encodeURIComponent(campaignKey),{{method:'POST'}});const data=await r.json();if(data.status==='cooldown'){{alert(data.message)}}else{{location.reload()}}e.target.disabled=false}};
async function statusUpdate(id,status,extra={{}}){{let feedback_reason=null,final_comment=null;if(status==='skipped')feedback_reason=prompt('Why are you skipping this lead? (optional)');if(status==='replied')final_comment=prompt('Paste the final published reply if you want to save it. (optional)');await fetch(`/leads/${{id}}/status`,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{status,feedback_reason,final_comment,...extra}})}});location.reload()}}
async function assignLead(id,status){{const assignee=prompt('Assign this opportunity to:');if(assignee!==null)await statusUpdate(id,status,{{assignee}})}}
async function trackOutcome(id,status){{const outcome=prompt('Outcome: positive_reply, qualified_lead, converted, no_response, or none','qualified_lead');if(!outcome)return;let conversion_value=null;if(outcome==='converted'){{const raw=prompt('Tracked conversion value (optional)');if(raw)conversion_value=Number(raw)}}await statusUpdate(id,status,{{outcome,conversion_value}})}}
async function copyDraft(id){{const node=document.getElementById('draft-'+id);await navigator.clipboard.writeText(node.innerText);alert('Draft copied')}}
async function moveLead(id){{const select=document.getElementById('move-'+id);const destination=select&&select.value;if(!destination)return;if(!confirm('Move this lead to the selected campaign?'))return;const r=await fetch(`/leads/${{id}}/campaign`,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{campaign_key:destination}})}});const data=await r.json();if(!r.ok){{alert(data.detail||'Could not move lead');return}}location.href='/?campaign='+encodeURIComponent(destination)}}
document.querySelectorAll('.local-time').forEach(node=>{{const date=new Date(node.dateTime);if(!Number.isNaN(date.getTime()))node.textContent=date.toLocaleString([],{{dateStyle:'medium',timeStyle:'short'}})}});
</script></body></html>"""


def _render_lead_card(
    lead: dict, campaign: Campaign, campaigns: list[CampaignRecord]
) -> str:
    def value(name: str) -> float:
        return float(lead.get(name) or 0)

    created = str(lead.get("created_at") or "")
    excerpt = _excerpt(lead.get("selftext") or "")
    excerpt_html = (
        f'<div class="post-excerpt"><strong>Original post:</strong> {escape(excerpt)}</div>'
        if excerpt
        else '<div class="post-excerpt muted">Original post body is empty.</div>'
    )
    positive = _json_list(lead.get("positive_signals"))
    negative = _json_list(lead.get("negative_signals"))
    status = escape(lead.get("status") or "new")
    brand_label = "Brand mention" if lead.get("should_mention_brand") else "No brand mention"
    if status == "new":
        actions = (
            f'<button class="success" onclick="statusUpdate({lead["id"]},\'approved\')">Approve</button>'
            f'<button onclick="assignLead({lead["id"]},\'new\')">Assign</button>'
            f'<button class="danger" onclick="statusUpdate({lead["id"]},\'skipped\')">Skip</button>'
        )
    elif status == "approved":
        actions = (
            f'<button class="success" onclick="statusUpdate({lead["id"]},\'replied\')">Mark replied</button>'
            f'<button onclick="assignLead({lead["id"]},\'approved\')">Assign</button>'
            f'<button class="danger" onclick="statusUpdate({lead["id"]},\'skipped\')">Skip</button>'
        )
    elif status == "replied":
        actions = (
            f'<button onclick="trackOutcome({lead["id"]},\'replied\')">Track outcome</button>'
            f'<button onclick="statusUpdate({lead["id"]},\'new\')">Reset</button>'
        )
    else:
        actions = f'<button onclick="statusUpdate({lead["id"]},\'new\')">Reset to new</button>'
    move_options = "".join(
        f'<option value="{escape(record.key)}">{escape(record.campaign.name)}</option>'
        for record in campaigns
        if record.key != lead.get("campaign_key")
    )
    move_control = (
        f'<select id="move-{lead["id"]}" aria-label="Move lead to campaign">'
        f'<option value="">Move to campaign…</option>{move_options}</select>'
        f'<button onclick="moveLead({lead["id"]})">Move</button>'
        if move_options
        else ""
    )
    assignee = escape(lead.get("assignee") or "Unassigned")
    outcome = escape((lead.get("outcome") or "none").replace("_", " ").title())
    return f"""<article class="card status-{status}">
<div class="badges"><span class="badge">{status}</span><span class="badge">{escape(_label(lead.get('response_type')))}</span><span class="badge">r/{escape(lead.get('subreddit') or 'unknown')}</span><span class="badge score">Lead {value('intent_score'):.2f}</span><span class="badge">{brand_label}</span><span class="badge">Owner: {assignee}</span><span class="badge">Outcome: {outcome}</span></div>
<h2><a href="{escape(lead.get('permalink') or '')}" target="_blank" rel="noopener noreferrer">{escape(lead.get('title') or 'Untitled')}</a></h2>
<div class="muted">Matched: {escape(lead.get('query') or '')} · <time class="local-time" datetime="{escape(created)}">{escape(created)}</time></div>
{excerpt_html}
<div class="scores">{_meter('Relevance',value('relevance_score'))}{_meter('Purchase intent',value('purchase_intent_score'))}{_meter('Product fit',value('product_fit_score'))}{_meter('Urgency',value('urgency_score'))}{_meter('Promotion risk',value('promotion_risk_score'))}</div>
<p class="reason"><strong>Why it qualifies:</strong> {escape(lead.get('reason') or '')}</p><p class="reason"><strong>Recommended strategy:</strong> {escape(lead.get('strategy_reason') or '')}</p>
<div class="signals"><div class="signal"><strong>Positive signals</strong>{_list_html(positive)}</div><div class="signal"><strong>Risks / negative signals</strong>{_list_html(negative)}</div></div>
<div class="draft" id="draft-{lead['id']}">{escape(lead.get('comment_text') or '(No draft generated)')}</div>
<div class="actions"><button class="primary" onclick="copyDraft({lead['id']})">Copy draft</button><a class="button" href="{escape(lead.get('permalink') or '')}" target="_blank" rel="noopener noreferrer">Open on Reddit</a>{actions}{move_control}</div>
</article>"""


def _meter(label: str, score: float) -> str:
    return f'<span class="meter"><b>{score:.2f}</b>{escape(label)}</span>'


def _json_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        return [str(item) for item in json.loads(value or "[]")]
    except (json.JSONDecodeError, TypeError):
        return []


def _list_html(items: list[str]) -> str:
    if not items:
        return '<div class="muted">None identified</div>'
    return "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"


def _label(value: str | None) -> str:
    return (value or "helpful_only").replace("_", " ").title()


def _excerpt(value: str, limit: int = 700) -> str:
    normalized = " ".join(str(value).split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"
