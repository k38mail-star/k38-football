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
import random
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

API_CACHE_TTLS = {
    "fixtures:live": 20,
    "fixtures:id": 15 * 60,
    "fixtures:date": 10 * 60,
    "fixtures/headtohead": 7 * 24 * 60 * 60,
    "injuries": 6 * 60 * 60,
}

DETAIL_RETRY_SECONDS = 30 * 60
_last_api_call_at = 0.0


def _utcnow():
    return datetime.utcnow()


def _utcnow_iso():
    return _utcnow().isoformat(timespec="seconds")


def _utc_iso_after(seconds):
    return (_utcnow() + timedelta(seconds=int(seconds))).isoformat(timespec="seconds")


def _parse_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _ordered_team_pair(team1_id, team2_id):
    if team1_id is None or team2_id is None:
        return None
    team1_id = int(team1_id)
    team2_id = int(team2_id)
    return (team1_id, team2_id) if team1_id <= team2_id else (team2_id, team1_id)


def _cache_is_fresh(fetched_at, ttl_seconds):
    fetched = _parse_datetime(fetched_at)
    if not fetched:
        return False
    return (_utcnow() - fetched).total_seconds() < ttl_seconds


def _canonical_params(params):
    return {
        str(key): str(value)
        for key, value in sorted((params or {}).items())
        if value is not None
    }


def _cache_key(endpoint, params):
    encoded = json.dumps(
        {"endpoint": endpoint, "params": _canonical_params(params)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cache_ttl(endpoint, params):
    params = params or {}
    if endpoint == "fixtures" and params.get("live"):
        return API_CACHE_TTLS["fixtures:live"]
    if endpoint == "fixtures" and params.get("id"):
        return API_CACHE_TTLS["fixtures:id"]
    if endpoint == "fixtures" and params.get("date"):
        return API_CACHE_TTLS["fixtures:date"]
    return API_CACHE_TTLS.get(endpoint)


def _get_cached_api_response(endpoint, params):
    ttl = _cache_ttl(endpoint, params)
    if not ttl:
        return None

    key = _cache_key(endpoint, params)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT response
            FROM football_api_cache
            WHERE cache_key = ?
              AND expires_at > ?
            """,
            (key, _utcnow_iso()),
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["response"])
    except json.JSONDecodeError:
        logger.warning("Ignoring corrupt API cache entry for %s %s", endpoint, params)
        return None


def _save_api_cache(endpoint, params, data):
    ttl = _cache_ttl(endpoint, params)
    if not ttl or data is None:
        return

    key = _cache_key(endpoint, params)
    params_json = json.dumps(_canonical_params(params), ensure_ascii=False, sort_keys=True)
    response_json = json.dumps(data, ensure_ascii=False)
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO football_api_cache
                (cache_key, endpoint, params, response, fetched_at, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(cache_key) DO UPDATE SET
                response=excluded.response,
                fetched_at=excluded.fetched_at,
                expires_at=excluded.expires_at,
                updated_at=datetime('now')
            """,
            (key, endpoint, params_json, response_json, _utcnow_iso(), _utc_iso_after(ttl)),
        )


def _rate_limit_sleep(delay):
    global _last_api_call_at
    delay = float(delay or 0)
    if delay <= 0:
        return
    elapsed = time.monotonic() - _last_api_call_at
    if elapsed < delay:
        time.sleep(delay - elapsed)


def _record_api_call():
    global _last_api_call_at
    _last_api_call_at = time.monotonic()


def _retry_after_seconds(exc):
    value = exc.headers.get("Retry-After") if getattr(exc, "headers", None) else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


def _api_has_errors(data):
    if not isinstance(data, dict):
        return False
    errors = data.get("errors")
    if isinstance(errors, list):
        return bool(errors)
    if isinstance(errors, dict):
        return bool(errors)
    return bool(errors)


def api_call(endpoint, params=None, use_cache=True, force_refresh=False):
    """Call API-Football with cache, retry, rate limiting, and exponential backoff."""
    if USE_MOCK:
        return None

    params = params or {}
    if use_cache and not force_refresh:
        cached = _get_cached_api_response(endpoint, params)
        if cached is not None:
            logger.debug("API cache hit: %s %s", endpoint, params)
            return cached

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
            _rate_limit_sleep(settings.API_BASE_DELAY)
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=settings.API_TIMEOUT) as resp:
                _record_api_call()
                data = json.loads(resp.read().decode())
                if _api_has_errors(data):
                    logger.warning("API returned errors for %s %s: %s", endpoint, params, data.get("errors"))
                else:
                    _save_api_cache(endpoint, params, data)
                return data
        except urllib.error.HTTPError as exc:
            _record_api_call()
            retryable = exc.code in {408, 425, 429, 500, 502, 503, 504}
            if not retryable or attempt == attempts - 1:
                logger.warning("API call failed after %s attempt(s): HTTP %s %s", attempt + 1, exc.code, url)
                return None
            retry_after = _retry_after_seconds(exc)
        except Exception as exc:
            _record_api_call()
            if attempt == attempts - 1:
                logger.warning("API call failed after %s attempt(s): %s %s", attempt + 1, endpoint, exc)
                return None
            retry_after = None

        base_sleep = min(settings.API_BACKOFF_MAX, settings.API_BACKOFF_BASE * (2 ** attempt))
        sleep_for = retry_after if retry_after is not None else base_sleep + random.uniform(0, base_sleep * 0.25)
        time.sleep(sleep_for)

    return None


def save_match(match):
    """Write a match to SQLite and emit goal notifications for score changes."""
    stats_json = json.dumps(match.get("stats", {}), ensure_ascii=False)
    events_json = json.dumps(match.get("events", []), ensure_ascii=False)

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
                 referee, venue, stats, events, details_fetched_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
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
                stats=CASE
                    WHEN excluded.details_fetched_at IS NULL AND excluded.stats = '{}'
                    THEN football_matches.stats
                    ELSE excluded.stats
                END,
                events=CASE
                    WHEN excluded.details_fetched_at IS NULL AND excluded.events = '[]'
                    THEN football_matches.events
                    ELSE excluded.events
                END,
                details_fetched_at=COALESCE(excluded.details_fetched_at, football_matches.details_fetched_at),
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
                stats_json,
                events_json,
                match.get("details_fetched_at"),
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
    detail_count = 0
    data = api_call("fixtures", {"live": "all"}, use_cache=False)
    if data and "response" in data:
        for fix in data["response"]:
            league_id = fix.get("league", {}).get("id")
            if league_id in LEAGUES:
                match = _parse_fixture(fix)
                save_match(match)
                if _should_fetch_detail(match) and fetch_and_save_detail(match["fixture_id"]):
                    detail_count += 1
                count += 1
    if detail_count:
        logger.info("live detail refresh complete: %s fixtures", detail_count)
    return count


def collect_schedule():
    """Collect fixtures using a tighter detail policy around match day."""
    if USE_MOCK:
        return 0

    count = 0
    today = datetime.now().date()
    start = today - timedelta(days=settings.FINISHED_LOOKBACK_DAYS)
    end = today + timedelta(days=min(settings.LOOKAHEAD_DAYS, 3))
    current = start

    while current <= end:
        date_value = current.strftime("%Y-%m-%d")
        days_ahead = (current - today).days
        if days_ahead >= 4:
            current += timedelta(days=1)
            continue

        for league_id in LEAGUES:
            season = _season_for_date(current, league_id)
            data = api_call("fixtures", {"league": league_id, "season": season, "date": date_value})
            if data and "response" in data:
                for fix in data["response"]:
                    match = _parse_fixture(fix)
                    save_match(match)
                    if current <= today and _should_fetch_detail(match):
                        fetch_and_save_detail(match["fixture_id"])
                    count += 1
        current += timedelta(days=1)

    collect_finished_match_details()
    return count


def collect_from_api():
    """Collect live fixtures and configured schedule window."""
    return collect_live_matches() + collect_schedule()


def ensure_prediction_context_for_fixture(fixture, force=False):
    """Refresh H2H and injury context for one upcoming fixture when stale."""
    if not fixture:
        return {"h2h_refreshed": False, "injury_refreshed": 0}

    home_team_id = fixture.get("home_team_id")
    away_team_id = fixture.get("away_team_id")
    refreshed = {"h2h_refreshed": False, "injury_refreshed": 0}

    if home_team_id and away_team_id:
        refreshed["h2h_refreshed"] = fetch_and_save_h2h(home_team_id, away_team_id, force=force)

    for team_id in (home_team_id, away_team_id):
        if team_id and fetch_and_save_injuries(team_id, force=force):
            refreshed["injury_refreshed"] += 1

    return refreshed


def collect_prediction_context(force=False, limit=20):
    """Refresh cached H2H and injury data for upcoming fixtures."""
    if USE_MOCK:
        return {"fixtures": 0, "h2h": 0, "injuries": 0}

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM football_matches
            WHERE home_goals IS NULL
              AND away_goals IS NULL
            ORDER BY match_date
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    totals = {"fixtures": 0, "h2h": 0, "injuries": 0}
    for row in rows:
        fixture = dict(row)
        result = ensure_prediction_context_for_fixture(fixture, force=force)
        totals["fixtures"] += 1
        totals["h2h"] += 1 if result["h2h_refreshed"] else 0
        totals["injuries"] += result["injury_refreshed"]
        if result["h2h_refreshed"] or result["injury_refreshed"]:
            time.sleep(settings.API_BASE_DELAY)

    return totals


def refresh_prediction_context_daily():
    """Run the prediction context refresh at most once per configured day."""
    if USE_MOCK:
        return {"fixtures": 0, "h2h": 0, "injuries": 0, "skipped": True}

    now = datetime.now()
    scheduled = now.replace(
        hour=int(settings.PREDICTION_CONTEXT_REFRESH_HOUR),
        minute=int(settings.PREDICTION_CONTEXT_REFRESH_MINUTE),
        second=0,
        microsecond=0,
    )
    refresh_key = f"prediction_context:{now.date().isoformat()}"
    if now < scheduled:
        return {"fixtures": 0, "h2h": 0, "injuries": 0, "skipped": True}

    with get_db() as conn:
        done = conn.execute(
            "SELECT 1 FROM football_prediction_refreshes WHERE refresh_key = ?",
            (refresh_key,),
        ).fetchone()
        if done:
            return {"fixtures": 0, "h2h": 0, "injuries": 0, "skipped": True}

    totals = collect_prediction_context(force=False)
    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO football_prediction_refreshes (refresh_key, refreshed_at)
            VALUES (?, ?)
            """,
            (refresh_key, _utcnow_iso()),
        )
    totals["skipped"] = False
    return totals


def fetch_and_save_h2h(team1_id, team2_id, force=False):
    """Fetch and cache the latest head-to-head fixtures for two teams."""
    pair = _ordered_team_pair(team1_id, team2_id)
    if USE_MOCK or not pair:
        return False

    cached = get_h2h_cache(team1_id, team2_id)
    if not force and cached and cached.get("fresh"):
        return False

    data = api_call("fixtures/headtohead", {"h2h": f"{pair[0]}-{pair[1]}", "last": 10})
    response = data.get("response", []) if data else []
    if not isinstance(response, list):
        response = []

    stats = _parse_h2h_response(response, pair[0], pair[1])
    fetched_at = _utcnow_iso()
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO football_h2h_cache
                (team1_id, team2_id, fixture_count, team1_wins, team2_wins, draws, fixtures, fetched_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(team1_id, team2_id) DO UPDATE SET
                fixture_count=excluded.fixture_count,
                team1_wins=excluded.team1_wins,
                team2_wins=excluded.team2_wins,
                draws=excluded.draws,
                fixtures=excluded.fixtures,
                fetched_at=excluded.fetched_at,
                updated_at=datetime('now')
            """,
            (
                pair[0],
                pair[1],
                stats["total"],
                stats["team1_wins"],
                stats["team2_wins"],
                stats["draws"],
                json.dumps(stats["fixtures"], ensure_ascii=False),
                fetched_at,
            ),
        )
    logger.info("h2h cache refreshed for %s-%s: %s fixtures", pair[0], pair[1], stats["total"])
    return True


def get_h2h_cache(team1_id, team2_id):
    pair = _ordered_team_pair(team1_id, team2_id)
    if not pair:
        return None

    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM football_h2h_cache WHERE team1_id = ? AND team2_id = ?",
            pair,
        ).fetchone()
    if not row:
        return None

    cached = dict(row)
    try:
        fixtures = json.loads(cached.get("fixtures") or "[]")
    except json.JSONDecodeError:
        fixtures = []

    team1_wins = int(cached.get("team1_wins") or 0)
    team2_wins = int(cached.get("team2_wins") or 0)
    draws = int(cached.get("draws") or 0)
    total = int(cached.get("fixture_count") or (team1_wins + team2_wins + draws))
    return {
        "team1_id": pair[0],
        "team2_id": pair[1],
        "total": total,
        "team1_wins": team1_wins,
        "team2_wins": team2_wins,
        "draws": draws,
        "fixtures": fixtures,
        "fetched_at": cached.get("fetched_at"),
        "fresh": _cache_is_fresh(cached.get("fetched_at"), settings.H2H_CACHE_SECONDS),
    }


def fetch_and_save_injuries(team_id, season=None, force=False):
    """Fetch and cache current injuries for one team and season."""
    if USE_MOCK or not team_id:
        return False

    season = int(season or settings.PREDICTION_CONTEXT_SEASON)
    cached = get_team_injuries(team_id, season=season)
    if not force and cached.get("fresh"):
        return False

    data = api_call("injuries", {"team": int(team_id), "season": season})
    response = data.get("response", []) if data else []
    if not isinstance(response, list):
        response = []

    fetched_at = _utcnow_iso()
    injuries = [_parse_injury(item, int(team_id), season, fetched_at) for item in response]
    with get_db() as conn:
        conn.execute(
            "DELETE FROM football_injuries WHERE team_id = ? AND season = ?",
            (int(team_id), season),
        )
        conn.executemany(
            """
            INSERT OR REPLACE INTO football_injuries
                (team_id, season, player_id, player_name, injury_type, reason, expected_return, raw, fetched_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            """,
            [
                (
                    injury["team_id"],
                    injury["season"],
                    injury["player_id"],
                    injury["player_name"],
                    injury["injury_type"],
                    injury["reason"],
                    injury["expected_return"],
                    injury["raw"],
                    injury["fetched_at"],
                )
                for injury in injuries
            ],
        )
        if not injuries:
            conn.execute(
                """
                INSERT OR REPLACE INTO football_injuries
                    (team_id, season, player_name, injury_type, reason, expected_return, raw, fetched_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                """,
                (int(team_id), season, "__NO_CURRENT_INJURIES__", "", "", "", "{}", fetched_at),
            )

    logger.info("injury cache refreshed for team %s season %s: %s players", team_id, season, len(injuries))
    return True


def get_team_injuries(team_id, season=None):
    season = int(season or settings.PREDICTION_CONTEXT_SEASON)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM football_injuries
            WHERE team_id = ? AND season = ?
            ORDER BY player_name
            """,
            (int(team_id), season),
        ).fetchall()

    if not rows:
        return {"team_id": int(team_id), "season": season, "injuries": [], "fetched_at": None, "fresh": False}

    fetched_at = rows[0]["fetched_at"]
    injuries = []
    for row in rows:
        item = dict(row)
        if item["player_name"] == "__NO_CURRENT_INJURIES__":
            continue
        injuries.append({
            "player_id": item.get("player_id"),
            "player_name": item.get("player_name"),
            "injury_type": item.get("injury_type") or item.get("reason") or "Injury",
            "reason": item.get("reason") or "",
            "expected_return": item.get("expected_return") or "",
        })

    return {
        "team_id": int(team_id),
        "season": season,
        "injuries": injuries,
        "fetched_at": fetched_at,
        "fresh": _cache_is_fresh(fetched_at, settings.INJURY_CACHE_SECONDS),
    }


def fetch_and_save_detail(fixture_id):
    """Fetch fixtures?id=xxx and persist detailed events/statistics once available."""
    if USE_MOCK or not fixture_id:
        return False

    if _detail_recently_attempted(fixture_id):
        return False

    data = api_call("fixtures", {"id": fixture_id})
    response = data.get("response", []) if data else []
    if not response:
        _mark_detail_attempt(fixture_id)
        return False

    match = _parse_fixture(response[0], details_fetched=True)
    save_match(match)
    _mark_detail_attempt(fixture_id)
    return True


def collect_finished_match_details(limit=50):
    """Backfill detail data for finished matches that have not been fetched yet."""
    if USE_MOCK:
        return 0

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT fixture_id
            FROM football_matches
            WHERE status LIKE '%Finished%'
              AND details_fetched_at IS NULL
            ORDER BY match_date DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

    count = 0
    for row in rows:
        if fetch_and_save_detail(row["fixture_id"]):
            count += 1
            time.sleep(settings.API_BASE_DELAY)
    return count


def _season_for_date(value, league_id):
    """Return API-Football season parameter for a fixture date."""
    league_name = str(LEAGUES.get(league_id, ""))
    if league_id == 1 or "世界杯" in league_name:
        return value.year
    return value.year if value.month >= 7 else value.year - 1


def _should_fetch_detail(match):
    """Return whether this saved fixture should call the detailed endpoint now."""
    fixture_id = match.get("fixture_id")
    if not fixture_id:
        return False
    if _detail_recently_attempted(fixture_id):
        return False
    if not _is_finished_status(match.get("status")):
        return True
    return not _details_already_fetched(fixture_id)


def _details_already_fetched(fixture_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT details_fetched_at FROM football_matches WHERE fixture_id = ?",
            (fixture_id,),
        ).fetchone()
    return bool(row and row["details_fetched_at"])


def _detail_recently_attempted(fixture_id):
    key = _cache_key("fixtures:detail-attempt", {"id": fixture_id})
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM football_api_cache
            WHERE cache_key = ?
              AND expires_at > ?
            """,
            (key, _utcnow_iso()),
        ).fetchone()
    return bool(row)


def _mark_detail_attempt(fixture_id):
    key = _cache_key("fixtures:detail-attempt", {"id": fixture_id})
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO football_api_cache
                (cache_key, endpoint, params, response, fetched_at, expires_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(cache_key) DO UPDATE SET
                fetched_at=excluded.fetched_at,
                expires_at=excluded.expires_at,
                updated_at=datetime('now')
            """,
            (
                key,
                "fixtures:detail-attempt",
                json.dumps({"id": int(fixture_id)}, sort_keys=True),
                "{}",
                _utcnow_iso(),
                _utc_iso_after(DETAIL_RETRY_SECONDS),
            ),
        )


def _is_finished_status(status):
    return bool(status and "Finished" in status)


def _parse_fixture(fix, details_fetched=False):
    """Parse an API-Football fixture into the local match dictionary."""
    fixture = fix.get("fixture", {})
    league = fix.get("league", {})
    teams = fix.get("teams", {})
    goals = fix.get("goals", {}) or {}
    score = fix.get("score", {}) or {}
    status = fixture.get("status", {}) or {}
    status_long = status.get("long", "")
    home = teams.get("home", {}) or {}
    away = teams.get("away", {}) or {}
    venue = fixture.get("venue", {}) or {}
    statistics = _parse_statistics(fix.get("statistics", []))
    events = _parse_events(fix.get("events", []))

    return {
        "fixture_id": fixture.get("id"),
        "league_id": league.get("id"),
        "league_name": LEAGUES.get(league.get("id"), league.get("name", "")),
        "season": str(league.get("season", "")),
        "round": league.get("round", ""),
        "match_date": fixture.get("date", ""),
        "status": status_long,
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
        "stats": statistics,
        "events": events,
        "details_fetched_at": (
            datetime.now().isoformat(timespec="seconds")
            if details_fetched and _is_finished_status(status_long)
            else None
        ),
    }


def _parse_h2h_response(fixtures, team1_id, team2_id):
    parsed_fixtures = []
    team1_wins = team2_wins = draws = 0
    for fix in fixtures or []:
        fixture = fix.get("fixture", {}) or {}
        teams = fix.get("teams", {}) or {}
        goals = fix.get("goals", {}) or {}
        league = fix.get("league", {}) or {}
        home = teams.get("home", {}) or {}
        away = teams.get("away", {}) or {}
        home_id = home.get("id")
        away_id = away.get("id")
        home_goals = goals.get("home")
        away_goals = goals.get("away")

        winner = None
        if home_goals is not None and away_goals is not None:
            if int(home_goals) > int(away_goals):
                winner = home_id
            elif int(home_goals) < int(away_goals):
                winner = away_id
            else:
                winner = "draw"

        if winner == team1_id:
            team1_wins += 1
        elif winner == team2_id:
            team2_wins += 1
        elif winner == "draw":
            draws += 1

        parsed_fixtures.append({
            "fixture_id": fixture.get("id"),
            "date": fixture.get("date"),
            "league": league.get("name"),
            "home_team_id": home_id,
            "home_team": home.get("name"),
            "away_team_id": away_id,
            "away_team": away.get("name"),
            "home_goals": home_goals,
            "away_goals": away_goals,
            "winner": winner,
        })

    return {
        "total": team1_wins + team2_wins + draws,
        "team1_wins": team1_wins,
        "team2_wins": team2_wins,
        "draws": draws,
        "fixtures": parsed_fixtures,
    }


def _parse_injury(item, team_id, season, fetched_at):
    player = item.get("player", {}) or {}
    fixture = item.get("fixture", {}) or {}
    return {
        "team_id": team_id,
        "season": season,
        "player_id": player.get("id"),
        "player_name": player.get("name") or "Unknown player",
        "injury_type": player.get("type") or item.get("type") or "",
        "reason": player.get("reason") or item.get("reason") or "",
        "expected_return": (
            player.get("return")
            or player.get("expected_return")
            or item.get("return")
            or item.get("expected_return")
            or fixture.get("date")
            or ""
        ),
        "raw": json.dumps(item, ensure_ascii=False),
        "fetched_at": fetched_at,
    }


def _parse_statistics(statistics):
    """Flatten API-Football team statistics for the existing match detail UI."""
    parsed = {}
    for team_stats in statistics or []:
        team = team_stats.get("team", {}) or {}
        team_key = team.get("id") or team.get("name")
        if not team_key:
            continue
        for stats_block, period in _iter_statistics_blocks(team_stats):
            for stat in stats_block:
                stat_type, stat_period = _normalize_stat_type_and_period(stat, period)
                if not stat_type:
                    continue
                value = stat.get("value")
                label = f"{stat_period} {stat_type}" if stat_period else stat_type
                parsed[f"{label}_{team_key}"] = "" if value is None else str(value)
    return parsed


def _iter_statistics_blocks(team_stats):
    stats = team_stats.get("statistics", [])
    if isinstance(stats, list):
        yield stats, None
    elif isinstance(stats, dict):
        for key, value in stats.items():
            period = _normalize_period_name(key)
            if isinstance(value, list):
                yield value, period
            elif isinstance(value, dict) and isinstance(value.get("statistics"), list):
                yield value["statistics"], period

    for key in (
        "first_half",
        "firstHalf",
        "1st_half",
        "halftime",
        "half_time",
        "full_time",
        "fullTime",
        "match",
        "periods",
        "halves",
    ):
        value = team_stats.get(key)
        if isinstance(value, list):
            yield value, _normalize_period_name(key)
        elif isinstance(value, dict):
            period = _normalize_period_name(key)
            if isinstance(value.get("statistics"), list):
                yield value["statistics"], period
            else:
                for nested_key, nested_value in value.items():
                    nested_period = _normalize_period_name(nested_key) or period
                    if isinstance(nested_value, list):
                        yield nested_value, nested_period
                    elif isinstance(nested_value, dict) and isinstance(nested_value.get("statistics"), list):
                        yield nested_value["statistics"], nested_period


def _normalize_stat_type_and_period(stat, fallback_period=None):
    raw_type = str(stat.get("type") or "").strip()
    if not raw_type:
        return "", fallback_period

    period = _normalize_period_name(
        stat.get("period")
        or stat.get("half")
        or stat.get("time")
        or stat.get("scope")
        or fallback_period
    )
    cleaned = raw_type
    markers = (
        ("1st Half", "First Half"),
        ("First Half", "First Half"),
        ("Half Time", "First Half"),
        ("Halftime", "First Half"),
        ("HT", "First Half"),
        ("2nd Half", "Second Half"),
        ("Second Half", "Second Half"),
        ("Full Time", None),
        ("Fulltime", None),
        ("Match", None),
    )
    for marker, marker_period in markers:
        if marker.lower() in cleaned.lower():
            period = marker_period
            cleaned = _remove_case_insensitive(cleaned, marker)
    cleaned = cleaned.replace("()", "").replace("[]", "").strip(" -:()[]")
    return cleaned, period


def _normalize_period_name(value):
    if not value:
        return None
    normalized = str(value).strip().lower().replace("_", " ").replace("-", " ")
    if normalized in {"1", "h1", "ht"} or "first" in normalized or "1st" in normalized or "halftime" in normalized or "half time" in normalized:
        return "First Half"
    if normalized in {"2", "h2"} or "second" in normalized or "2nd" in normalized:
        return "Second Half"
    if "full" in normalized or "match" in normalized or "all" in normalized:
        return None
    return None


def _remove_case_insensitive(value, needle):
    lower_value = value.lower()
    lower_needle = needle.lower()
    index = lower_value.find(lower_needle)
    if index == -1:
        return value
    return value[:index] + value[index + len(needle):]


def _parse_events(events):
    """Normalize goals, cards, and substitutions from API-Football events."""
    parsed = []
    for event in events or []:
        event_type = event.get("type", "")
        if not _is_supported_event(event_type):
            continue

        time_info = event.get("time", {}) or {}
        team = event.get("team", {}) or {}
        player = event.get("player", {}) or {}
        assist = event.get("assist", {}) or {}
        parsed.append(
            {
                "time": time_info.get("elapsed"),
                "extra": time_info.get("extra"),
                "type": event_type,
                "detail": event.get("detail", ""),
                "team": team.get("name", ""),
                "team_id": team.get("id"),
                "player": player.get("name", ""),
                "player_id": player.get("id"),
                "assist": assist.get("name", ""),
                "assist_id": assist.get("id"),
                "comments": event.get("comments", ""),
            }
        )
    return parsed


def _is_supported_event(event_type):
    normalized = str(event_type or "").lower()
    return normalized in {"goal", "card", "subst"} or "substitution" in normalized
