from functools import lru_cache
from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from app.config import get_settings


class ProductConfig(BaseModel):
    name: str
    description: str
    website: str = ""
    value_propositions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    target_customers: list[str] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)


class MarketConfig(BaseModel):
    countries: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    customer_signals: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    require_market_signal: bool = False


class DiscoveryConfig(BaseModel):
    keywords: list[str]
    subreddits: list[str] = Field(default_factory=lambda: ["all"])
    excluded_subreddits: list[str] = Field(default_factory=list)
    adjacent_subreddits: list[str] = Field(default_factory=list)
    watch_only_subreddits: list[str] = Field(default_factory=list)
    community_notes: str = ""
    lookback: str = "week"
    sort: str = "new"
    limit_per_keyword: int = Field(default=25, ge=1, le=100)

    @field_validator("keywords")
    @classmethod
    def keywords_must_not_be_empty(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("discovery.keywords must contain at least one keyword")
        return cleaned


class ScoreWeights(BaseModel):
    """Relative importance for the five opportunity-score dimensions.

    Values are deliberately expressed as easy-to-edit points rather than a
    brittle required total of 100. They are normalized before scoring, so a
    campaign owner can increase one priority without having to rebalance every
    other field manually.
    """

    relevance: float = Field(default=25, ge=0, le=100)
    purchase_intent: float = Field(default=30, ge=0, le=100)
    product_fit: float = Field(default=25, ge=0, le=100)
    urgency: float = Field(default=10, ge=0, le=100)
    reachability: float = Field(default=10, ge=0, le=100)

    @model_validator(mode="after")
    def must_have_at_least_one_weight(self) -> "ScoreWeights":
        if sum(self.model_dump().values()) <= 0:
            raise ValueError("At least one opportunity score weight must be greater than zero")
        return self

    def normalized(self) -> dict[str, float]:
        values = self.model_dump()
        total = sum(values.values())
        return {name: value / total for name, value in values.items()}


class ScoreDimensionSignals(BaseModel):
    """Campaign-specific sub-signals the AI should use under each score."""

    relevance: list[str] = Field(default_factory=lambda: [
        "Matches a problem the product solves",
        "Matches the campaign's use case or target customer",
    ])
    purchase_intent: list[str] = Field(default_factory=lambda: [
        "Explicitly asks for recommendations, options, or alternatives",
        "Comparing, replacing, or evaluating a solution",
        "Mentions a budget, trial, buying process, or decision timeline",
    ])
    product_fit: list[str] = Field(default_factory=lambda: [
        "Product capabilities address the stated need",
        "The campaign limitations do not rule out this use case",
    ])
    urgency: list[str] = Field(default_factory=lambda: [
        "Has a stated deadline, renewal, launch, or time-sensitive problem",
        "Current workflow is blocking an important outcome",
    ])
    reachability: list[str] = Field(default_factory=lambda: [
        "A public reply could usefully answer the question",
        "The author is open to discussion and the thread is still timely",
    ])
    promotion_risk: list[str] = Field(default_factory=lambda: [
        "Community rules or thread context make a brand reply inappropriate",
        "The post is promotional, solved, hostile to promotion, or unrelated",
    ])
    market_fit: list[str] = Field(default_factory=lambda: [
        "Supported geography, language, and customer profile are evidenced",
        "No campaign market exclusion applies",
    ])

    @field_validator("*")
    @classmethod
    def clean_signals(cls, value: list[str]) -> list[str]:
        return [str(item).strip() for item in value if str(item).strip()]


class ScoreModelConfig(BaseModel):
    """Scoring controls saved with each isolated campaign."""

    weights: ScoreWeights = Field(default_factory=ScoreWeights)
    promotion_risk_penalty: float = Field(default=15, ge=0, le=100)
    market_mismatch_penalty: float = Field(default=10, ge=0, le=100)
    dimension_signals: ScoreDimensionSignals = Field(default_factory=ScoreDimensionSignals)


class QualificationConfig(BaseModel):
    minimum_lead_score: float = Field(default=0.72, ge=0, le=1)
    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    max_post_age_days: int = Field(default=7, ge=1, le=365)
    scoring_mode: str = Field(default="ai_adaptive", pattern="^(ai_adaptive|manual)$")
    score_model: ScoreModelConfig = Field(default_factory=ScoreModelConfig)


class EngagementConfig(BaseModel):
    allow_brand_mentions: bool = False
    allow_links: bool = False
    tone: str = "helpful, concise, transparent, and non-salesy"
    disclosure: str = ""
    max_words: int = Field(default=140, ge=30, le=400)


class Campaign(BaseModel):
    name: str
    product: ProductConfig
    market: MarketConfig = Field(default_factory=MarketConfig)
    discovery: DiscoveryConfig
    qualification: QualificationConfig = Field(default_factory=QualificationConfig)
    engagement: EngagementConfig = Field(default_factory=EngagementConfig)


@dataclass(frozen=True)
class CampaignRecord:
    key: str
    path: Path
    campaign: Campaign


WORKSPACE_PATH = Path("campaigns/workspace.yaml")
CAMPAIGNS_ROOT = Path("campaigns")


def campaign_key_for_path(path: str | Path) -> str:
    key = re.sub(r"[^a-z0-9]+", "-", Path(path).stem.casefold()).strip("-")
    return key or "campaign"


def _workspace_campaign_paths() -> list[Path]:
    """Return workspace paths, falling back to the original env configuration."""
    if WORKSPACE_PATH.exists():
        with WORKSPACE_PATH.open(encoding="utf-8") as handle:
            payload = yaml.safe_load(handle) or {}
        raw_paths = payload.get("campaigns", [])
        if not isinstance(raw_paths, list):
            raise ValueError("campaigns/workspace.yaml must contain a campaigns list")
        paths = [Path(item) for item in raw_paths if isinstance(item, str) and item.strip()]
        if paths:
            return paths
    return [Path(path) for path in get_settings().configured_campaign_paths]


def _save_workspace_campaign_paths(paths: list[Path]) -> None:
    """Atomically persist the campaign workspace registry."""
    root = CAMPAIGNS_ROOT.resolve()
    normalized: list[str] = []
    for path in paths:
        resolved = path.resolve()
        if resolved != root and root not in resolved.parents:
            raise ValueError("Campaign workspace files must be stored inside campaigns/")
        try:
            normalized.append(resolved.relative_to(Path.cwd().resolve()).as_posix())
        except ValueError:
            normalized.append(str(resolved))
    WORKSPACE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=WORKSPACE_PATH.parent, delete=False, suffix=".tmp"
        ) as handle:
            yaml.safe_dump({"campaigns": normalized}, handle, sort_keys=False)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, WORKSPACE_PATH)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def get_campaign_records() -> list[CampaignRecord]:
    """Load all campaigns in the persisted managed-service workspace."""
    records: list[CampaignRecord] = []
    seen: set[str] = set()
    for path in _workspace_campaign_paths():
        key = campaign_key_for_path(path)
        if key in seen:
            raise ValueError(f"Duplicate campaign key '{key}'. Rename one campaign file.")
        seen.add(key)
        records.append(CampaignRecord(key=key, path=path, campaign=load_campaign(path)))
    return records


def create_campaign_workspace(
    name: str, campaign: Campaign | dict | None = None
) -> CampaignRecord:
    """Create an isolated, editable campaign file and add it to the workspace."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Campaign name is required")
    root = CAMPAIGNS_ROOT.resolve()
    root.mkdir(parents=True, exist_ok=True)
    base_key = campaign_key_for_path(clean_name)
    candidate = root / f"{base_key}.yaml"
    suffix = 2
    while candidate.exists() or any(
        campaign_key_for_path(path) == candidate.stem for path in _workspace_campaign_paths()
    ):
        candidate = root / f"{base_key}-{suffix}.yaml"
        suffix += 1
    if campaign is None:
        campaign = Campaign(
            name=clean_name,
            product=ProductConfig(name="", description=""),
            market=MarketConfig(languages=[]),
            discovery=DiscoveryConfig(keywords=["product recommendation"]),
            engagement=EngagementConfig(
                allow_brand_mentions=False,
                allow_links=False,
                tone="",
                disclosure="",
            ),
        )
    else:
        campaign = campaign if isinstance(campaign, Campaign) else Campaign.model_validate(campaign)
        campaign = campaign.model_copy(update={"name": clean_name})
    save_campaign(campaign, path=candidate, allowed_root=root)
    paths = _workspace_campaign_paths()
    paths.append(candidate)
    _save_workspace_campaign_paths(paths)
    return CampaignRecord(key=candidate.stem, path=candidate, campaign=campaign)


def get_campaign_record(key: str | None = None) -> CampaignRecord:
    records = get_campaign_records()
    if not records:
        raise FileNotFoundError("No campaign files are configured.")
    if key is None:
        return records[0]
    for record in records:
        if record.key == key:
            return record
    raise KeyError(f"Unknown campaign: {key}")


def load_campaign(path: str | Path | None = None) -> Campaign:
    configured_path = str(path or get_settings().campaign_path).strip()
    if not configured_path:
        raise FileNotFoundError("No product setup is configured yet.")
    selected = Path(configured_path)
    if not selected.exists():
        raise FileNotFoundError(
            f"Campaign file not found: {selected}. Copy a template from campaigns/."
        )
    with selected.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return Campaign.model_validate(payload)


@lru_cache
def get_campaign() -> Campaign:
    configured = get_settings().campaign_path.strip()
    if configured:
        return load_campaign(configured)
    # Internal helpers and direct library users retain a stable example campaign.
    # It is intentionally not registered as a workspace, so a fresh web UI still
    # opens on the empty V0.5 onboarding screen.
    return load_campaign("campaigns/campaign.yaml")


def clear_campaign_cache() -> None:
    get_campaign.cache_clear()


def save_campaign(
    campaign: Campaign | dict,
    path: str | Path | None = None,
    allowed_root: str | Path | None = None,
) -> Campaign:
    """Validate and atomically save the active campaign YAML."""
    validated = campaign if isinstance(campaign, Campaign) else Campaign.model_validate(campaign)
    configured_path = str(path or get_settings().campaign_path).strip()
    if not configured_path:
        raise ValueError("Choose or create a product workspace before saving.")
    selected = Path(configured_path).resolve()
    root = Path(allowed_root or "campaigns").resolve()
    if selected.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Campaign configuration must be a .yaml or .yml file")
    if selected != root and root not in selected.parents:
        raise ValueError("Campaign configuration must be stored inside campaigns/")
    selected.parent.mkdir(parents=True, exist_ok=True)
    payload = yaml.safe_dump(
        validated.model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=True,
        width=100,
    )
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=selected.parent, delete=False, suffix=".tmp"
        ) as handle:
            handle.write(payload)
            temporary_path = Path(handle.name)
        os.replace(temporary_path, selected)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()
    clear_campaign_cache()
    return validated
