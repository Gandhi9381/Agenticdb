"""
AgenticDB Core Configuration
"""
import os
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict

_backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_root_dir = os.path.dirname(_backend_dir)
_env_files = (
    os.path.join(_root_dir, ".env"),
    os.path.join(_backend_dir, ".env"),
)


PLACEHOLDER_KEY_PATTERNS = (
    "your_api_key",
    "your_google",
    "your_gemini",
    "your_key",
    "your-api-key",
    "api_key_here",
    "change_me",
    "changeme",
    "placeholder",
    "todo",
    "xxx",
)


def is_valid_llm_key(key: Optional[str]) -> bool:
    """Validate that an API key is non-empty, not a template placeholder, and has minimum length."""
    if not key or not isinstance(key, str):
        return False
    k = key.strip()
    if not k:
        return False
    k_lower = k.lower()
    for pattern in PLACEHOLDER_KEY_PATTERNS:
        if pattern in k_lower:
            return False
    if k.startswith(("<", "[", "{", "(", "your_")):
        return False
    # Standard Gemini API keys are typically ~39 characters; require at least 15 characters
    return len(k) >= 15


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: str = "google"
    llm_model: str = "gemini-3.1-flash-lite"
    llm_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    google_api_key: Optional[str] = None

    # Database
    database_url: str = "sqlite:///./agenticdb.db"
    test_database_url: Optional[str] = None
    monitored_database_url: Optional[str] = None

    # Monitoring
    monitor_interval_seconds: int = 30
    slow_query_threshold_ms: int = 1000
    anomaly_detection_enabled: bool = True

    # Safety
    approval_required_for_persistent_changes: bool = True
    max_query_rows: int = 10000
    query_timeout_seconds: int = 30

    # Application
    app_env: str = "development"
    secret_key: str = "dev-secret-key-change-in-production"
    debug: bool = True
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # Sample Data
    sample_data_rows: int = 1000
    sample_data_seed: int = 42

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",")]

    @property
    def effective_llm_api_key(self) -> Optional[str]:
        candidates = [
            self.llm_api_key,
            self.gemini_api_key,
            self.google_api_key,
            os.environ.get("LLM_API_KEY"),
            os.environ.get("GEMINI_API_KEY"),
            os.environ.get("GOOGLE_API_KEY"),
        ]
        for key in candidates:
            if is_valid_llm_key(key):
                return key.strip()
        return None

    @property
    def llm_configured(self) -> bool:
        if self.llm_provider and self.llm_provider.lower() in ("mock", "demo", "offline", "synthetic"):
            return True
        return bool(self.effective_llm_api_key)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url.startswith("sqlite:///./"):
            backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_name = self.database_url.replace("sqlite:///./", "")
            abs_db_path = os.path.join(backend_dir, db_name).replace("\\", "/")
            return f"sqlite:///{abs_db_path}"
        return self.database_url


@lru_cache()
def _get_cached_settings() -> Settings:
    return Settings()


def get_settings(reload: bool = False) -> Settings:
    if reload:
        _get_cached_settings.cache_clear()
    return _get_cached_settings()
