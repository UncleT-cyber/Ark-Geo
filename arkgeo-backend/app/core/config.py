"""Central configuration for ArkGeo backend.

All secrets and tunable values are read from environment variables so the
service never hard-codes credentials.  Sensible development defaults are
provided only for non-sensitive values.
"""
from functools import lru_cache
import os
from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARKGEO_",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application -------------------------------------------------
    app_name: str = "THE ARK ISE"
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
    geospy_api_url: str = "https://dev.geospy.ai/predict"
    geoinfer_api_key: Optional[str] = None
    geoinfer_api_url: str = "https://api.geoinfer.com/v1/prediction/predict"
    # Empty = use the server's current default model (avoids deprecated model
    # drift).  Pin an explicit id (e.g. an accuracy/regional model) if needed.
    geoinfer_model: str = ""
    vision_request_timeout: int = 30

    # --- LLM (Tier 3 clue extractors) -------------------------------
    # ``llm_api_key`` defaults to an OpenAI-compatible endpoint; Gemini and
    # Anthropic keys are accepted as alternative vision/LLM providers.
    llm_api_key: Optional[str] = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    llm_request_timeout: int = 60
    llm_max_tokens: int = 1500
    gemini_api_key: Optional[str] = None
    gemini_api_url: str = "https://generativelanguage.googleapis.com/v1beta"
    anthropic_api_key: Optional[str] = None
    anthropic_api_url: str = "https://api.anthropic.com/v1"

    # --- Mapbox (spatial reverse geocoding) -------------------------
    # Client map tiles use the Vite-side VITE_MAPBOX_TOKEN; this is the
    # server-side token for Geocoding API lookups in the reverse_geocode tool.
    mapbox_token: Optional[str] = None
    mapbox_geocoding_url: str = "https://api.mapbox.com/geocoding/v5/mapbox.places"

    # --- Reverse source discovery -----------------------------------
    tineye_api_key: Optional[str] = None
    tineye_api_url: str = "https://api.tineye.com/rest/v3/upload"
    serper_api_key: Optional[str] = None
    serper_api_url: str = "https://google.serper.dev/images"
    tavily_api_key: Optional[str] = None
    tavily_api_url: str = "https://api.tavily.com/search"

    # --- Google Street View (panorama forensics) --------------------
    google_maps_api_key: Optional[str] = None
    google_streetview_api_url: str = "https://maps.googleapis.com/maps/api/streetview"
    google_maps_tile_api_url: str = "https://tile.googleapis.com"
    # Keyless geocoding fallback (OpenStreetMap Nominatim) used when the
    # Google project has billing disabled / no key — city-level targets on
    # the map must not depend on a paid plan.
    geo_nominatim_fallback: bool = True
    geo_nominatim_url: str = "https://nominatim.openstreetmap.org/search"

    # --- Twilio (SOS dispatch) --------------------------------------
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None

    # --- Telemetry lookups (Cell / Wi-Fi) ---------------------------
    opencellid_api_key: Optional[str] = None
    opencellid_api_url: str = "https://opencellid.org/cell/get"

    # --- Live signaling (SS7 / Diameter) ----------------------------
    # Backend selector for the signaling driver layer:
    #   simulated   — deterministic dry-run engine (no live traffic)
    #   osmocom     — osmo-msc / osmo-hlr lab via osmo-hlr CTRL + GSUP
    #   sdr         — OpenBSC + USRP/GSU SDR test band (BTS/IMSI-catcher)
    #   commercial  — licensed operator SCCP/DIAMETER gateway (high-contract)
    signaling_backend: str = "simulated"
    signaling_audit_path: str = ""
    signaling_personnel_file: str = ""
    signaling_operator_token_expiry_hours: int = 24
    # Commercial (licensed) gateway adapter — populates only when YOU provision
    # a licensed operator SS7/Diameter / number-intelligence gateway. The driver
    # calls that provider's REST API; it stays inert (BackendNotProvisioned)
    # until both values are set, and is only reachable behind the certified-
    # operator + per-operator-token + audit gate in app/signaling/access.py.
    signaling_commercial_base_url: str = ""
    signaling_commercial_api_key: str = ""
    # osmo-hlr / osmo-msc lab endpoints
    osmocom_hlr_ctrl_host: str = "127.0.0.1"
    osmocom_hlr_ctrl_port: int = 4250
    osmocom_hlr_vty_host: str = "127.0.0.1"
    osmocom_hlr_vty_port: int = 4258
    osmocom_gsup_host: str = "127.0.0.1"
    osmocom_gsup_port: int = 4222
    osmocom_msc_host: str = "127.0.0.1"
    osmocom_msc_port: int = 4254
    osmocom_smsc_host: str = "127.0.0.1"
    osmocom_smsc_port: int = 4249
    osmocom_smlc_host: str = "127.0.0.1"
    osmocom_smlc_port: int = 4257
    osmocom_ctrl_timeout: int = 5
    # OpenBSC / SDR test-band configuration (informational + gating)
    sdr_bts_host: str = "127.0.0.1"
    sdr_bts_port: int = 4242
    sdr_test_band: str = "GSM-1800"
    sdr_max_imsi_catcher_radius_m: int = 2000

    # --- OSINT aggregator (non-licensed phone intelligence) --------------
    # Free tier needs no keys (public numbering-plan / carrier registries).
    # Provider tiers (hlr / cnam / risk / social) activate when keys are set
    # via BYOK in the request or as Admin system keys in the SettingsStore.
    osint_request_timeout: int = 10
    ipqs_api_url: str = "https://ipqualityscore.com/api/json/phone"
    twilio_lookup_url: str = "https://lookups.twilio.com/v1/PhoneNumbers"
    infobip_lookup_url: str = "https://api.infobip.com/number/1/query"
    opencnam_api_url: str = "https://api.opencnam.com/v3/phone"

    # --- SIM-swap providers (Telesign PhoneID / Tru.ID) -----------------
    # When neither is configured the OSINT aggregator falls back to
    # deterministic simulated SIM-swap indicators (labelled simulated).
    telesign_customer_id: Optional[str] = None
    telesign_rest_key: Optional[str] = None
    telesign_api_url: str = "https://rest-ww.telesign.com/v1/phoneid"
    truid_client_id: Optional[str] = None
    truid_client_secret: Optional[str] = None
    truid_api_url: str = "https://api.tru.id/phone_check/v1/phonechecks"
    # SIM-swap range (days) used to size the simulated fallback window.
    simswap_lookback_days: int = 120

    # --- Social enumeration / digital footprint probes ------------------
    # Active probes hit public platform resolvers; disabled by default so the
    # aggregator only ever returns deterministic simulated footprint data.
    social_probe_enabled: bool = True
    social_probe_timeout: int = 6

    # --- Billing / historical records (simulated block) ----------------
    # Always synthetic unless a licensed provider integration is configured.
    billing_live_enabled: bool = False

    # --- Dead-man switch worker -------------------------------------
    deadman_poll_seconds: int = 15
    deadman_grace_seconds: int = 60

    # --- Data retention ---------------------------------------------
    default_zero_retention: bool = False

    # --- Admin Console auth -----------------------------------------
    admin_username: str = Field(
        default="admin",
        description="Username for the authenticated Admin Console.",
    )
    admin_password_hash: str = Field(
        default="",
        description="Bcrypt hash of the admin password. If empty, a default "
                    "password 'arkgeo-admin' is hashed at startup (CHANGE IN PRODUCTION).",
    )
    admin_jwt_expiry_minutes: int = 120

    # --- ARK-CAI unified AI core -------------------------------------
    # Embedded CAI engine (app/engine/cai) acts as THE ARK's intelligence core.
    # ``cai_license_off`` bypasses the upstream license gate so CAI integrates
    # seamlessly with local (Ollama) and cloud (OpenAI/Claude/Gemini) models.
    cai_license_off: bool = True
    # Optional model backend for live autonomous execution. When unset, THE ARK
    # uses the deterministic offline executor (streaming architecture intact).
    cai_model: Optional[str] = None
    cai_base_url: Optional[str] = None

    @property
    def aes_key_bytes(self) -> bytes:
        """Return the AES key padded / truncated to exactly 32 bytes."""
        raw = self.aes_key.encode("utf-8")
        return raw.ljust(32, b"\0")[:32]

    @model_validator(mode="after")
    def _apply_cai_integration(self):
        """Force CAI license-off + model env so THE ARK's embedded CAI core
        integrates with local (Ollama) and cloud model providers."""
        if self.cai_license_off:
            os.environ["CAI_LICENSE_OFF"] = "true"
        if self.cai_model:
            os.environ["ARK_CAI_MODEL"] = self.cai_model
        if self.cai_base_url:
            os.environ["ARK_CAI_BASE_URL"] = self.cai_base_url
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


def get_admin_password_hash() -> str:
    """Return the admin password bcrypt hash.

    If ``admin_password_hash`` is not set in the environment, a default
    password ``arkgeo-admin`` is hashed lazily.  This MUST be overridden
    in production via the ``ARKGEO_ADMIN_PASSWORD_HASH`` env var.
    """
    import logging
    logger = logging.getLogger(__name__)
    if settings.admin_password_hash:
        return settings.admin_password_hash
    # Default password — only for development
    from app.core.security import hash_password
    logger.warning(
        "ARKGEO_ADMIN_PASSWORD_HASH not set — using default password. "
        "Set ARKGEO_ADMIN_PASSWORD_HASH in production."
    )
    return hash_password("arkgeo-admin")


settings = get_settings()
