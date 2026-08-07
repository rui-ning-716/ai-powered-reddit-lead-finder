import logging
import base64
import secrets

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from app.config import get_settings
from app.ai import (
    decide_response_strategy,
    evaluate_opportunity,
    generate_personalized_comment,
    suggest_campaign_discovery,
)
from app.campaign import (
    Campaign,
    create_campaign_workspace,
    get_campaign_record,
    get_campaign_records,
    save_campaign,
)
from app.campaign_ui import render_campaign_wizard
from app.dashboard import render_dashboard
from app.db import init_db, lead_stats, list_leads, mark_draft_status, move_draft_to_campaign
from app.report import render_report, report_csv
from app.scanner import run_scan, run_when_scan_idle

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Reddit Lead Finder", version="0.2.2")
scheduler = BackgroundScheduler()


@app.middleware("http")
async def optional_basic_auth(request: Request, call_next):
    """Protect client workspaces when dashboard credentials are configured."""
    settings = get_settings()
    username = settings.dashboard_username
    password = settings.dashboard_password
    if request.url.path == "/health":
        return await call_next(request)
    if not username and not password:
        return await call_next(request)
    authorization = request.headers.get("Authorization", "")
    supplied_username = supplied_password = ""
    if authorization.startswith("Basic "):
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
            supplied_username, supplied_password = decoded.split(":", 1)
        except (ValueError, UnicodeDecodeError):
            pass
    valid = secrets.compare_digest(supplied_username, username) and secrets.compare_digest(
        supplied_password, password
    )
    if not valid:
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"},
            headers={"WWW-Authenticate": 'Basic realm="Reddit Lead Finder"'},
        )
    return await call_next(request)


class LeadStatusUpdate(BaseModel):
    status: str
    feedback_reason: str | None = Field(default=None, max_length=1000)
    final_comment: str | None = Field(default=None, max_length=10000)
    assignee: str | None = Field(default=None, max_length=120)
    review_notes: str | None = Field(default=None, max_length=4000)
    outcome: str | None = None
    conversion_value: float | None = Field(default=None, ge=0)


class SamplePost(BaseModel):
    subreddit: str = "all"
    title: str
    body: str = ""


class CampaignTestRequest(BaseModel):
    campaign: Campaign
    post: SamplePost


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class LeadCampaignMove(BaseModel):
    campaign_key: str = Field(min_length=1, max_length=100)


@app.on_event("startup")
def startup() -> None:
    settings = get_settings()
    if bool(settings.dashboard_username) != bool(settings.dashboard_password):
        raise RuntimeError(
            "Set both DASHBOARD_USERNAME and DASHBOARD_PASSWORD, or leave both blank."
        )
    init_db()
    scheduler.add_job(
        run_scan,
        "interval",
        minutes=settings.search_interval_minutes,
        id="reddit_scan",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.start()
    logger.info("scheduler started interval=%s minutes", settings.search_interval_minutes)


@app.on_event("shutdown")
def shutdown() -> None:
    scheduler.shutdown(wait=False)


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def dashboard(campaign: str | None = None) -> str:
    record = _campaign_record_or_404(campaign)
    return render_dashboard(
        leads=[dict(row) for row in list_leads(limit=100, campaign_key=record.key)],
        stats=lead_stats(campaign_key=record.key),
        campaign=record.campaign,
        campaign_key=record.key,
        campaigns=get_campaign_records(),
    )


@app.get("/campaign", response_class=HTMLResponse)
def campaign_setup(campaign: str | None = None) -> str:
    if campaign:
        _campaign_record_or_404(campaign)
    return render_campaign_wizard()


@app.get("/api/campaign")
def campaign_config(key: str | None = None) -> dict:
    settings = get_settings()
    record = _campaign_record_or_404(key)
    return {
        "campaign": record.campaign.model_dump(mode="json"),
        "campaign_key": record.key,
        "campaign_path": str(record.path),
        "openai_configured": bool(settings.openai_api_key),
    }


@app.get("/api/campaigns")
def campaigns() -> list[dict]:
    return [
        {
            "key": record.key,
            "name": record.campaign.name,
            "product": record.campaign.product.name,
            "path": str(record.path),
        }
        for record in get_campaign_records()
    ]


@app.post("/api/campaigns", status_code=201)
def create_campaign(request: CampaignCreateRequest) -> dict:
    try:
        record = create_campaign_workspace(request.name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "campaign": record.campaign.model_dump(mode="json"),
        "campaign_key": record.key,
        "campaign_path": str(record.path),
    }


@app.put("/api/campaign")
def update_campaign(campaign: Campaign, key: str | None = None) -> dict:
    record = _campaign_record_or_404(key)
    saved_ok, saved = run_when_scan_idle(
        lambda: save_campaign(campaign, path=record.path)
    )
    if not saved_ok or saved is None:
        raise HTTPException(
            status_code=409,
            detail="A Reddit scan is running. Wait for it to finish before saving the campaign.",
        )
    return {
        "campaign": saved.model_dump(mode="json"),
        "campaign_key": record.key,
        "campaign_path": str(record.path),
    }


@app.post("/api/campaign/suggest")
def suggest_campaign(campaign: Campaign) -> dict:
    _require_openai_key()
    return suggest_campaign_discovery(campaign)


@app.post("/api/campaign/test")
def test_campaign(request: CampaignTestRequest) -> dict:
    _require_openai_key()
    post = {
        "reddit_id": "manual_campaign_test",
        "subreddit": request.post.subreddit,
        "title": request.post.title,
        "selftext": request.post.body,
        "query": "manual sample",
        "permalink": "",
        "url": "",
    }
    qualification = evaluate_opportunity(post, campaign=request.campaign)
    if qualification.get("is_qualified"):
        strategy = decide_response_strategy(
            post, qualification, campaign=request.campaign
        )
        draft = generate_personalized_comment(
            post,
            qualification,
            strategy,
            recent_comments=[],
            campaign=request.campaign,
        )
    else:
        strategy = {
            "response_type": "skip",
            "should_reply": False,
            "should_mention_brand": False,
            "should_include_link": False,
            "reason": qualification.get("skip_reason") or "Lead did not qualify.",
            "tone": request.campaign.engagement.tone,
            "key_points": [],
        }
        draft = {"comment_text": "", "opening_sentence": ""}
    return {"qualification": qualification, "strategy": strategy, "draft": draft}


@app.post("/scan-now")
def scan_now(campaign: str | None = None) -> dict:
    if campaign:
        _campaign_record_or_404(campaign)
    return run_scan(manual=True, campaign_key=campaign)


@app.get("/leads")
def leads(limit: int = 50, campaign: str | None = None) -> list[dict]:
    key = _campaign_record_or_404(campaign).key if campaign else None
    return [dict(row) for row in list_leads(limit=limit, campaign_key=key)]


@app.get("/report", response_class=HTMLResponse)
def report(campaign: str | None = None) -> str:
    record = _campaign_record_or_404(campaign)
    return render_report(
        record.campaign,
        record.key,
        lead_stats(record.key),
        [dict(row) for row in list_leads(limit=500, campaign_key=record.key)],
        get_campaign_records(),
    )


@app.get("/report.csv")
def download_report(campaign: str | None = None) -> Response:
    record = _campaign_record_or_404(campaign)
    payload = report_csv(
        [dict(row) for row in list_leads(limit=5000, campaign_key=record.key)]
    )
    return Response(
        content=payload,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{record.key}-leads.csv"'
        },
    )


@app.post("/leads/{draft_id}/status")
def update_lead_status(
    draft_id: int,
    update: LeadStatusUpdate,
) -> dict:
    status = update.status
    allowed = {"new", "approved", "replied", "skipped"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of {sorted(allowed)}")
    allowed_outcomes = {
        None, "none", "positive_reply", "qualified_lead", "converted", "no_response"
    }
    if update.outcome not in allowed_outcomes:
        raise HTTPException(status_code=400, detail="Invalid lead outcome")
    mark_draft_status(
        draft_id,
        status,
        update.feedback_reason,
        update.final_comment,
        update.assignee,
        update.review_notes,
        update.outcome,
        update.conversion_value,
    )
    return {"draft_id": draft_id, "status": status}


@app.post("/leads/{draft_id}/campaign")
def move_lead(draft_id: int, move: LeadCampaignMove) -> dict:
    _campaign_record_or_404(move.campaign_key)
    try:
        move_draft_to_campaign(draft_id, move.campaign_key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"draft_id": draft_id, "campaign_key": move.campaign_key}


@app.exception_handler(Exception)
async def unhandled_exception(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled exception")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def _require_openai_key() -> None:
    if not get_settings().openai_api_key:
        raise HTTPException(
            status_code=400,
            detail="OPENAI_API_KEY is required for AI suggestions and sample tests.",
        )


def _campaign_record_or_404(key: str | None):
    try:
        return get_campaign_record(key)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
