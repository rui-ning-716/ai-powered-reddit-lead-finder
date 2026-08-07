from functools import lru_cache
from dataclasses import dataclass
import os
from pathlib import Path
import re
import tempfile

import yaml
from pydantic import BaseModel, Field, field_validator

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
    languages: list[str] = Field(default_factory=lambda: ["English"])
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


class QualificationConfig(BaseModel):
    minimum_lead_score: float = Field(default=0.72, ge=0, le=1)
    positive_signals: list[str] = Field(default_factory=list)
    negative_signals: list[str] = Field(default_factory=list)
    max_post_age_days: int = Field(default=7, ge=1, le=365)


class EngagementConfig(BaseModel):
    allow_brand_mentions: bool = True
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


def create_campaign_workspace(name: str) -> CampaignRecord:
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
    campaign = Campaign(
        name=clean_name,
        product=ProductConfig(
            name="New product",
            description="Describe the product, customer problem, and differentiation.",
        ),
        discovery=DiscoveryConfig(keywords=["product recommendation"]),
    )
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
    selected = Path(path or get_settings().campaign_path)
    if not selected.exists():
        raise FileNotFoundError(
            f"Campaign file not found: {selected}. Copy a template from campaigns/."
        )
    with selected.open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return Campaign.model_validate(payload)


@lru_cache
def get_campaign() -> Campaign:
    return load_campaign()


def clear_campaign_cache() -> None:
    get_campaign.cache_clear()


def save_campaign(
    campaign: Campaign | dict,
    path: str | Path | None = None,
    allowed_root: str | Path | None = None,
) -> Campaign:
    """Validate and atomically save the active campaign YAML."""
    validated = campaign if isinstance(campaign, Campaign) else Campaign.model_validate(campaign)
    selected = Path(path or get_settings().campaign_path).resolve()
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
