#!/usr/bin/env python3
"""Application settings loaded from the shared K38 football config."""

import importlib.util
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - supports bootstrap before dependencies.
    load_dotenv = None


BASE_DIR = Path(__file__).resolve().parent
DOTENV_PATHS = (
    BASE_DIR / ".env",
    Path.home() / "Desktop" / ".env",
    Path("/opt/dlt_node_v05/.env"),
)

if load_dotenv:
    for dotenv_path in DOTENV_PATHS:
        load_dotenv(dotenv_path=dotenv_path, override=False)


def _load_shared_config():
    """Import ~/Desktop/k38_football_config.py when available."""
    config_path = Path.home() / "Desktop" / "k38_football_config.py"
    if not config_path.exists():
        return None

    spec = importlib.util.spec_from_file_location("k38_football_config", config_path)
    if not spec or not spec.loader:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


config = _load_shared_config()


def env(name, default=None):
    value = os.getenv(name)
    return default if value in (None, "") else value


def env_int(name, default):
    value = env(name)
    return default if value is None else int(value)


def env_float(name, default):
    value = env(name)
    return default if value is None else float(value)


def env_bool(name, default=False):
    value = env(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


DEFAULT_LEAGUES = {
    1: "2026世界杯",
    39: "英超",
    140: "西甲",
    135: "意甲",
    78: "德甲",
    61: "法甲",
    41: "中超",
}


def _setting(name, default=None):
    return getattr(config, name, default) if config else default


API_KEY = _setting("API_KEY", env("K38_FOOTBALL_API_KEY", ""))
API_BASE = _setting("API_BASE", env("K38_FOOTBALL_API_BASE", "https://v3.football.api-sports.io"))
API_HOST = _setting("API_HOST", env("K38_FOOTBALL_API_HOST", "v3.football.api-sports.io"))
API_TIMEOUT = _setting("API_TIMEOUT", env_int("K38_FOOTBALL_API_TIMEOUT", 15))
API_RETRIES = _setting("API_RETRIES", env_int("K38_FOOTBALL_API_RETRIES", 4))
API_BACKOFF_BASE = _setting("API_BACKOFF_BASE", env_float("K38_FOOTBALL_API_BACKOFF_BASE", 1.0))
API_BACKOFF_MAX = _setting("API_BACKOFF_MAX", env_float("K38_FOOTBALL_API_BACKOFF_MAX", 30.0))
API_BASE_DELAY = _setting("API_BASE_DELAY", env_float("K38_FOOTBALL_API_BASE_DELAY", 1.2))
API_LIVE_DELAY = _setting("API_LIVE_DELAY", env_float("K38_FOOTBALL_API_LIVE_DELAY", 0.8))
API_IDLE_DELAY = _setting("API_IDLE_DELAY", env_float("K38_FOOTBALL_API_IDLE_DELAY", 3.0))

LEAGUES = dict(_setting("LEAGUES", DEFAULT_LEAGUES))

LOOKAHEAD_DAYS = _setting("LOOKAHEAD_DAYS", env_int("K38_FOOTBALL_LOOKAHEAD_DAYS", 21))
FINISHED_LOOKBACK_DAYS = _setting("FINISHED_LOOKBACK_DAYS", env_int("K38_FOOTBALL_FINISHED_LOOKBACK_DAYS", 1))
POLL_LIVE_SECONDS = _setting("POLL_LIVE_SECONDS", env_int("K38_FOOTBALL_POLL_LIVE_SECONDS", 120))
POLL_TODAY_SECONDS = _setting("POLL_TODAY_SECONDS", env_int("K38_FOOTBALL_POLL_TODAY_SECONDS", 300))
POLL_IDLE_SECONDS = _setting("POLL_IDLE_SECONDS", env_int("K38_FOOTBALL_POLL_IDLE_SECONDS", 1800))
POLL_ERROR_SECONDS = _setting("POLL_ERROR_SECONDS", env_int("K38_FOOTBALL_POLL_ERROR_SECONDS", 600))

PREDICTION_CONTEXT_SEASON = _setting(
    "PREDICTION_CONTEXT_SEASON",
    env_int("K38_FOOTBALL_PREDICTION_CONTEXT_SEASON", 2026),
)
H2H_CACHE_SECONDS = _setting("H2H_CACHE_SECONDS", env_int("K38_FOOTBALL_H2H_CACHE_SECONDS", 7 * 24 * 60 * 60))
INJURY_CACHE_SECONDS = _setting("INJURY_CACHE_SECONDS", env_int("K38_FOOTBALL_INJURY_CACHE_SECONDS", 6 * 60 * 60))
PREDICTION_CONTEXT_REFRESH_HOUR = _setting(
    "PREDICTION_CONTEXT_REFRESH_HOUR",
    env_int("K38_FOOTBALL_PREDICTION_CONTEXT_REFRESH_HOUR", 0),
)
PREDICTION_CONTEXT_REFRESH_MINUTE = _setting(
    "PREDICTION_CONTEXT_REFRESH_MINUTE",
    env_int("K38_FOOTBALL_PREDICTION_CONTEXT_REFRESH_MINUTE", 10),
)

CHANNEL_HMAC_SECRET = env("CHANNEL_HMAC_SECRET", "")
HERMES_WEBHOOK_URL = env("K38_FOOTBALL_HERMES_WEBHOOK_URL", "http://localhost:8644/webhooks/channel-msg")
GOAL_NOTIFICATIONS_ENABLED = env_bool("K38_FOOTBALL_GOAL_NOTIFICATIONS", True)

LOG_FILE = _setting("LOG_FILE", env("K38_FOOTBALL_LOG", str(BASE_DIR / "logs" / "k38_football.log")))
PID_FILE = env("K38_FOOTBALL_PID_FILE", "/tmp/k38-football-daemon.pid")
MOCK_MODE = not bool(API_KEY)

WEB_HOST = env("K38_FOOTBALL_WEB_HOST", "127.0.0.1")
WEB_PORT = env_int("K38_FOOTBALL_WEB_PORT", 6789)
WEB_DEBUG = env_bool("K38_FOOTBALL_WEB_DEBUG", True)
