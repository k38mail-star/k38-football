#!/usr/bin/env python3
"""
K38 football data collector.

Collects fixtures from API-Football when configured, otherwise stays in mock
mode so the web UI can run from seed data.
"""

import hashlib
import hmac
import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import settings
from models import get_db

logger = logging.getLogger(__name__)

USE_MOCK = settings.MOCK_MODE
LEAGUES = settings.LEAGUES

LIVE_STATUS = {
    "First Half",
    "Halftime",
    "Second Half",
    "Extra Time",
    "Penalty In Progress",
    "Match Suspended",
    "Match Interrupted",
    "In Progress",
}


def api_call(endpoint, params=None):
    """Call API-Football with configured retry and exponential backoff."""
    if USE_MOCK:
        return None

    url = f"{settings.API_BASE.rstrip('/')}/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "x-rapidapi-key": settings.API_KEY,
        "x-rapidapi-host": settings.API_HOST,
    }

    attempts = max(1, int(settings.API_RETRIES))
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=settings.API_TIMEOUT) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            retryable = exc.code in {408, 425, 429, 500, 502, 503, 504}
            if not retryable or attempt == attempts - 1:
                logger.warning("API call failed: %s %s", exc.code, url)
                return None
        except Exception as exc:
            if attempt == attempts - 1:
                logger.warning("API call failed: %s", exc)
                return None

        sleep_for = min(settings.API_BACKOFF_MAX, settings.API_BACKOFF_BASE * (2 ** attempt))
        time.sleep(sleep_for)

    return None


def save_match(match):
    """Write a match to SQLite and emit goal notifications for score changes."""
    with get_db() as conn:
        old = conn.execute(
            "SELECT home_goals, away_goals FROM football_matches WHERE fixture_id = ?",
            (match["fixture_id"],),
        ).fetchone()
        old_exists = old is not None
        old_home = old["home_goals"] if old else None
        old_away = old["away_goals"] if old else None

        conn.execute(
            """
            INSERT INTO football_matches
                (fixture_id, league_id, league_name, season, round,
                 match_date, status, elapsed,
                 home_team, away_team, home_team_id, away_team_id,
                 home_goals, away_goals,
                 halftime_home, halftime_away,
                 fulltime_home, fulltime_away,
                 extra_home, extra_away,
                 penalty_home, penalty_away,
                 referee, venue, stats, events, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
            ON CONFLICT(fixture_id) DO UPDATE SET
                league_id=excluded.league_id,
                league_name=excluded.league_name,
                season=excluded.season,
                round=excluded.round,
                match_date=excluded.match_date,
                status=excluded.status,
                elapsed=excluded.elapsed,
                home_team=excluded.home_team,
                away_team=excluded.away_team,
                home_team_id=excluded.home_team_id,
                away_team_id=excluded.away_team_id,
                home_goals=excluded.home_goals,
                away_goals=excluded.away_goals,
                halftime_home=excluded.halftime_home,
                halftime_away=excluded.halftime_away,
                fulltime_home=excluded.fulltime_home,
                fulltime_away=excluded.fulltime_away,
                extra_home=excluded.extra_home,
                extra_away=excluded.extra_away,
                penalty_home=excluded.penalty_home,
                penalty_away=excluded.penalty_away,
                referee=excluded.referee,
                venue=excluded.venue,
                stats=excluded.stats,
                events=excluded.events,
                updated_at=datetime('now')
            """,
            (
                match["fixture_id"],
                match.get("league_id"),
                match.get("league_name"),
                match.get("season"),
                match.get("round"),
                match.get("match_date"),
                match.get("status"),
                match.get("elapsed", 0),
                match.get("home_team"),
                match.get("away_team"),
                match.get("home_team_id"),
                match.get("away_team_id"),
                match.get("home_goals"),
                match.get("away_goals"),
                match.get("halftime_home"),
                match.get("halftime_away"),
                match.get("fulltime_home"),
                match.get("fulltime_away"),
                match.get("extra_home"),
                match.get("extra_away"),
                match.get("penalty_home"),
                match.get("penalty_away"),
                match.get("referee", ""),
                match.get("venue", ""),
                json.dumps(match.get("stats", {}), ensure_ascii=False),
                json.dumps(match.get("events", []), ensure_ascii=False),
            ),
        )

    notify_goal_if_needed(match, old_home, old_away, old_exists)


def notify_goal_if_needed(match, old_home, old_away, old_exists=True):
    """Send a Hermes webhook when a persisted score increases."""
    if not settings.GOAL_NOTIFICATIONS_ENABLED or not settings.CHANNEL_HMAC_SECRET:
        return
    if not old_exists:
        return

    new_home = match.get("home_goals")
    new_away = match.get("away_goals")
    if new_home is None or new_away is None:
        return
    old_home = 0 if old_home is None else int(old_home)
    old_away = 0 if old_away is None else int(old_away)
    if int(new_home) <= int(old_home) and int(new_away) <= int(old_away):
        return

    text = f"⚽ {match.get('home_team')} {new_home}-{new_away} {match.get('away_team')}"
    payload = {
        "source": "football",
        "from": "K38足球监控",
        "text": text,
    }
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(
        settings.CHANNEL_HMAC_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    req = urllib.request.Request(
        settings.HERMES_WEBHOOK_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Signature": signature,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
        logger.info("Goal notification sent for fixture %s", match.get("fixture_id"))
    except Exception as exc:
        logger.warning("Goal notification failed for fixture %s: %s", match.get("fixture_id"), exc)


def load_seed_data():
    """Load seed matches for development and mock mode."""
    from seed_data import SEED_MATCHES

    for match in SEED_MATCHES:
        save_match(match)
    return len(SEED_MATCHES)


def collect_live_matches():
    """Collect live fixtures for configured leagues."""
    if USE_MOCK:
        return 0

    count = 0
    data = api_call("fixtures", {"live": "all"})
    if data and "response" in data:
        for fix in data["response"]:
            league_id = fix.get("league", {}).get("id")
            if league_id in LEAGUES:
                save_match(_parse_fixture(fix))
                count += 1
                time.sleep(settings.API_LIVE_DELAY)
    return count


def collect_schedule():
    """Collect recent, current, and upcoming fixtures for configured leagues."""
    if USE_MOCK:
        return 0

    count = 0
    today = datetime.now().date()
    start = today - timedelta(days=settings.FINISHED_LOOKBACK_DAYS)
    end = today + timedelta(days=settings.LOOKAHEAD_DAYS)
    current = start

    while current <= end:
        date_value = current.strftime("%Y-%m-%d")
        for league_id in LEAGUES:
            season = _season_for_date(current, league_id)
            data = api_call("fixtures", {"league": league_id, "season": season, "date": date_value})
            if data and "response" in data:
                for fix in data["response"]:
                    save_match(_parse_fixture(fix))
                    count += 1
            time.sleep(settings.API_BASE_DELAY)
        current += timedelta(days=1)

    return count


def collect_from_api():
    """Collect live fixtures and configured schedule window."""
    return collect_live_matches() + collect_schedule()


def _season_for_date(value, league_id):
    """Return API-Football season parameter for a fixture date."""
    league_name = str(LEAGUES.get(league_id, ""))
    if league_id == 1 or "世界杯" in league_name:
        return value.year
    return value.year if value.month >= 7 else value.year - 1


def _parse_fixture(fix):
    """Parse an API-Football fixture into the local match dictionary."""
    fixture = fix.get("fixture", {})
    league = fix.get("league", {})
    teams = fix.get("teams", {})
    goals = fix.get("goals", {}) or {}
    score = fix.get("score", {}) or {}
    status = fixture.get("status", {}) or {}
    home = teams.get("home", {}) or {}
    away = teams.get("away", {}) or {}
    venue = fixture.get("venue", {}) or {}

    return {
        "fixture_id": fixture.get("id"),
        "league_id": league.get("id"),
        "league_name": LEAGUES.get(league.get("id"), league.get("name", "")),
        "season": str(league.get("season", "")),
        "round": league.get("round", ""),
        "match_date": fixture.get("date", ""),
        "status": status.get("long", ""),
        "elapsed": status.get("elapsed") or 0,
        "home_team": home.get("name", "?"),
        "away_team": away.get("name", "?"),
        "home_team_id": home.get("id"),
        "away_team_id": away.get("id"),
        "home_goals": goals.get("home"),
        "away_goals": goals.get("away"),
        "halftime_home": (score.get("halftime") or {}).get("home"),
        "halftime_away": (score.get("halftime") or {}).get("away"),
        "fulltime_home": (score.get("fulltime") or {}).get("home"),
        "fulltime_away": (score.get("fulltime") or {}).get("away"),
        "extra_home": (score.get("extra") or {}).get("home"),
        "extra_away": (score.get("extra") or {}).get("away"),
        "penalty_home": (score.get("penalty") or {}).get("home"),
        "penalty_away": (score.get("penalty") or {}).get("away"),
        "referee": fixture.get("referee", ""),
        "venue": venue.get("name", ""),
        "stats": {},
        "events": [],
    }
