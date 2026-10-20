"""Explicit environment wiring; no credentials or presentation changes."""

import os

STAGING_API = "https://oplates-pricing-api-staging.onrender.com"
STAGING_UI = "https://oplates-customer-ui-staging.onrender.com"
PRODUCTION_API = "https://orifice-pricing-api.onrender.com"
PRODUCTION_UI = "https://quote.o-plates.com"
PRODUCTION_PROJECT = "kboaovlhilonlymcuqcr"


def enabled(environ=None, *, app_env=None):
    env = os.environ if environ is None else environ
    environment = env.get("APP_ENV") if app_env is None else app_env
    return bool(env.get("FROZEN_PLATE_DATABASE_URL")) and (
        environment == "staging"
        or (environment == "production" and env.get("FROZEN_PLATE_ENABLED") == "true")
    )


def ui_origin(environ=None):
    env = os.environ if environ is None else environ
    if env.get("APP_ENV") == "production":
        return PRODUCTION_UI
    return STAGING_UI


def ui_enabled(environ=None):
    env = os.environ if environ is None else environ
    base = env.get("API_BASE", "").rstrip("/")
    return (base == STAGING_API and env.get("APP_ENV") != "production") or (
        env.get("APP_ENV") == "production"
        and base == PRODUCTION_API
        and env.get("FROZEN_PLATE_ENABLED") == "true"
    )


def repository(environ=None):
    env = os.environ if environ is None else environ
    if env.get("APP_ENV") == "production":
        from .production import ProductionRepository

        return ProductionRepository(env)
    from .staging import StagingRepository

    return StagingRepository(env)
