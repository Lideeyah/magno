"""Runtime configuration for the Magno backend.

Alpaca credentials are *not* read from the environment by default: they are
supplied per-session by the operator through the onboarding flow and held in
memory only (see ``app.state_store``). Environment values act as a fallback so
the autonomous loop can be booted headless (e.g. in Docker) for judging.
"""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- Alpaca (paper only; Magno refuses to construct a live client) ---
    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_paper_base_url: str = "https://paper-api.alpaca.markets"

    # --- Featherless AI (OpenAI-compatible serverless inference) ---
    featherless_api_key: str | None = None
    featherless_base_url: str = "https://api.featherless.ai/v1"
    featherless_model: str = "Qwen/Qwen2.5-72B-Instruct"
    featherless_timeout_s: float = 45.0

    # --- Optional Anthropic fallback reasoner ---
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"

    # --- Risk envelope defaults (overridable per session at onboarding) ---
    max_spread_pct: float = 0.05          # reject contracts wider than 5% of mid
    max_allocation_pct: float = 0.10      # max 10% of buying power per trade
    delta_drift_threshold: float = 1.0    # |net delta| that triggers a hedge
    max_daily_loss_pct: float = 0.05      # halt trading after -5% on the day
    max_open_positions: int = 6
    default_contract_qty: int = 1
    required_starting_equity: float = 100_000.0
    equity_verification_tolerance: float = 0.35  # accept 65k–135k as "the $100k account"

    # --- Loop cadences (seconds) ---
    telemetry_interval_s: float = 1.0
    hedge_interval_s: float = 5.0
    reasoning_interval_s: float = 60.0

    # --- Universe ---
    universe: list[str] = ["SPY", "QQQ", "NVDA", "AAPL"]

    # --- Dedicated auto-demo sandbox ---
    # Read by app.demo_main only. The production app never touches these.
    demo_alpaca_api_key: str | None = None
    demo_alpaca_secret_key: str | None = None
    demo_alpaca_base_url: str = "https://paper-api.alpaca.markets"
    demo_featherless_api_key: str | None = None
    demo_port: int = 3001
    demo_backend_port: int = 8001

    # --- Server ---
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    risk_free_rate: float = 0.0425


@lru_cache
def get_settings() -> Settings:
    universe_env = os.getenv("MAGNO_UNIVERSE")
    settings = Settings()
    if universe_env:
        settings.universe = [s.strip().upper() for s in universe_env.split(",") if s.strip()]
    # Deployed frontends live on a domain the image cannot know at build time,
    # so the allowed origins are supplied at boot. Localhost stays permitted by
    # the regex in main.py, which keeps local development working unchanged.
    origins_env = os.getenv("MAGNO_CORS_ORIGINS")
    if origins_env:
        settings.cors_origins = [
            o.strip().rstrip("/") for o in origins_env.split(",") if o.strip()
        ]
    return settings


settings = get_settings()
