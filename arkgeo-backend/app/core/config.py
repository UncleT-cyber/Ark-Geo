"""Central configuration for ArkGeo backend.

All secrets and tunable values are read from environment variables so the
service never hard-codes credentials.  Sensible development defaults are
provided only for non-sensitive values.
"""
from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARKGEO_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------
    app_name: str = "ArkGeo Core"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000

    # --- Security ----------------------------------------------------
    jwt_secret: str = Field(
        default="change-me-in-production",
        description="Secret used to sign / verify JWT access tokens.",
    )
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 60
    aes_key: str = Field(
        default="0" * 32,
        description="32-byte key (as utf-8 string) for AES-256 field-level encryption.",
    )
    allowed_origins: List[str] = ["*"]

    # --- Storage -----------------------------------------------------
    storage_backend: str = "local"  # "local" | "s3"
    local_storage_path: str = "./arkgeo_data"
    s3_bucket: Optional[str] = None
    s3_region: Optional[str] = None

    # --- Vision ensemble (Tier 2) -----------------------------------
    geospy_api_key: Optional[str] = None
    geospy_api_url: str = "https://api.geospy.ai/v1/predict"
    geoinfer_api_key: Optional[str] = None
    geoinfer_api_url: str = "https://api.geoinfer.ai/v1/locate"
    vision_request_timeout: int = 30

    # --- LLM (Tier 3 clue extractors) -------------------------------
    llm_api_key: Optional[str] = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_request_timeout: int = 60
    llm_max_tokens: int = 1500

    # --- Twilio (SOS dispatch) --------------------------------------
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None

    # --- Telemetry lookups (Cell / Wi-Fi) ---------------------------
    opencellid_api_key: Optional[str] = None
    opencellid_api_url: str = "https://opencellid.org/cell/get"

    # --- Dead-man switch worker -------------------------------------
    deadman_poll_seconds: int = 15
    deadman_grace_seconds: int = 60

    # --- Data retention ---------------------------------------------
    default_zero_retention: bool = False

    @property
    def aes_key_bytes(self) -> bytes:
        """Return the AES key padded / truncated to exactly 32 bytes."""
        raw = self.aes_key.encode("utf-8")
        return raw.ljust(32, b"\0")[:32]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
