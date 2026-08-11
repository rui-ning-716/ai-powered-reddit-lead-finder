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
        default="reddit-lead-finder/0.6 (human-in-the-loop reply discovery)",
        alias="REDDIT_USER_AGENT",
    )
    campaign_path: str = Field(default="", alias="CAMPAIGN_PATH")
    campaign_paths: str = Field(default="", alias="CAMPAIGN_PATHS")

    # SEARCH_INTERVAL_MINUTES remains accepted for older .env files, but V0.6
    # uses a lightweight scheduler tick and a persistent per-feed due time.
    search_interval_minutes: int = Field(default=30, alias="SEARCH_INTERVAL_MINUTES")
    reddit_scan_tick_minutes: int = Field(default=10, alias="REDDIT_SCAN_TICK_MINUTES")
    reddit_rss_requests_per_tick_min: int = Field(
        default=3, alias="REDDIT_RSS_REQUESTS_PER_TICK_MIN"
    )
    reddit_rss_requests_per_tick_max: int = Field(
        default=8, alias="REDDIT_RSS_REQUESTS_PER_TICK_MAX"
    )
    reddit_rss_request_delay_min_seconds: float = Field(
        default=8, alias="REDDIT_RSS_REQUEST_DELAY_MIN_SECONDS"
    )
    reddit_rss_request_delay_max_seconds: float = Field(
        default=15, alias="REDDIT_RSS_REQUEST_DELAY_MAX_SECONDS"
    )
    reddit_high_intent_interval_min_minutes: int = Field(
        default=30, alias="REDDIT_HIGH_INTENT_INTERVAL_MIN_MINUTES"
    )
    reddit_high_intent_interval_max_minutes: int = Field(
        default=60, alias="REDDIT_HIGH_INTENT_INTERVAL_MAX_MINUTES"
    )
    reddit_standard_interval_min_minutes: int = Field(
        default=120, alias="REDDIT_STANDARD_INTERVAL_MIN_MINUTES"
    )
    reddit_standard_interval_max_minutes: int = Field(
        default=180, alias="REDDIT_STANDARD_INTERVAL_MAX_MINUTES"
    )
    reddit_research_interval_min_minutes: int = Field(
        default=360, alias="REDDIT_RESEARCH_INTERVAL_MIN_MINUTES"
    )
    reddit_research_interval_max_minutes: int = Field(
        default=720, alias="REDDIT_RESEARCH_INTERVAL_MAX_MINUTES"
    )
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
    reddit_429_cooldown_steps_minutes: str = Field(
        default="120,240,480,720", alias="REDDIT_429_COOLDOWN_STEPS_MINUTES"
    )
    reddit_429_strike_window_hours: int = Field(
        default=24, alias="REDDIT_429_STRIKE_WINDOW_HOURS"
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
        """Return explicitly configured legacy campaign files.

        New installations start with an empty product workspace. Existing
        installations can still opt into the original single-file behavior by
        keeping CAMPAIGN_PATH in their .env file.
        """
        paths = [item.strip() for item in self.campaign_paths.split(",") if item.strip()]
        if paths:
            return paths
        return [self.campaign_path.strip()] if self.campaign_path.strip() else []

    @property
    def reddit_429_cooldown_steps(self) -> list[int]:
        steps: list[int] = []
        for item in self.reddit_429_cooldown_steps_minutes.split(","):
            try:
                value = int(item.strip())
            except ValueError:
                continue
            if value > 0:
                steps.append(value)
        return steps or [120, 240, 480, 720]


@lru_cache
def get_settings() -> Settings:
    return Settings()
