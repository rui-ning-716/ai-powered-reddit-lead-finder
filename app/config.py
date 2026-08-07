from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1-mini", alias="OPENAI_MODEL")

    reddit_user_agent: str = Field(
        default="reddit-lead-finder/0.2 (human-in-the-loop lead discovery)",
        alias="REDDIT_USER_AGENT",
    )
    campaign_path: str = Field(
        default="campaigns/campaign.yaml", alias="CAMPAIGN_PATH"
    )
    campaign_paths: str = Field(default="", alias="CAMPAIGN_PATHS")

    search_interval_minutes: int = Field(default=30, alias="SEARCH_INTERVAL_MINUTES")
    min_manual_scan_interval_minutes: int = Field(
        default=15, alias="MIN_MANUAL_SCAN_INTERVAL_MINUTES"
    )
    max_ai_posts_per_scan: int = Field(default=8, alias="MAX_AI_POSTS_PER_SCAN")
    reddit_rss_cache_ttl_minutes: int = Field(
        default=10, alias="REDDIT_RSS_CACHE_TTL_MINUTES"
    )
    reddit_rss_max_retries: int = Field(default=3, alias="REDDIT_RSS_MAX_RETRIES")
    reddit_429_circuit_breaker_threshold: int = Field(
        default=3, alias="REDDIT_429_CIRCUIT_BREAKER_THRESHOLD"
    )
    reddit_429_cooldown_minutes: int = Field(
        default=120, alias="REDDIT_429_COOLDOWN_MINUTES"
    )
    database_path: str = Field(default="data/threadscout.sqlite3", alias="DATABASE_PATH")
    leads_csv_path: str = Field(default="data/leads.csv", alias="LEADS_CSV_PATH")
    leads_markdown_path: str = Field(default="data/leads.md", alias="LEADS_MARKDOWN_PATH")

    dashboard_username: str = Field(default="", alias="DASHBOARD_USERNAME")
    dashboard_password: str = Field(default="", alias="DASHBOARD_PASSWORD")

    slack_notifications_enabled: bool = Field(
        default=False, alias="SLACK_NOTIFICATIONS_ENABLED"
    )
    slack_webhook_url: str = Field(default="", alias="SLACK_WEBHOOK_URL")
    slack_min_intent_score: float = Field(default=0.72, alias="SLACK_MIN_INTENT_SCORE")

    email_notifications_enabled: bool = Field(
        default=False, alias="EMAIL_NOTIFICATIONS_ENABLED"
    )
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: str = Field(default="", alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    email_from: str = Field(default="", alias="EMAIL_FROM")
    email_to: str = Field(default="", alias="EMAIL_TO")

    @property
    def email_recipients(self) -> list[str]:
        return [item.strip() for item in self.email_to.split(",") if item.strip()]

    @property
    def configured_campaign_paths(self) -> list[str]:
        """Return the managed campaigns, preserving V0.1 single-campaign behavior."""
        paths = [item.strip() for item in self.campaign_paths.split(",") if item.strip()]
        return paths or [self.campaign_path]


@lru_cache
def get_settings() -> Settings:
    return Settings()
