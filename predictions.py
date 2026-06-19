from collections import defaultdict

from models import get_db


def _load_completed_matches(exclude_fixture_id=None):
    query = """
        SELECT * FROM football_matches
        WHERE home_goals IS NOT NULL
          AND away_goals IS NOT NULL
    """
    params = []
    if exclude_fixture_id is not None:
        query += " AND fixture_id != ?"
        params.append(exclude_fixture_id)
    query += " ORDER BY match_date DESC"
    with get_db() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def _team_key(match, side):
    return match.get(f"{side}_team_id") or match.get(f"{side}_team")


def _calculate_elos(matches):
    ratings = defaultdict(lambda: 1500.0)
    for match in sorted(matches, key=lambda item: item.get("match_date") or ""):
        home = _team_key(match, "home")
        away = _team_key(match, "away")
        if home is None or away is None:
            continue
        expected_home = 1 / (1 + 10 ** ((ratings[away] - ratings[home] - 60) / 400))
        if match["home_goals"] > match["away_goals"]:
            actual_home = 1.0
        elif match["home_goals"] == match["away_goals"]:
            actual_home = 0.5
        else:
            actual_home = 0.0
        change = 24 * (actual_home - expected_home)
        ratings[home] += change
        ratings[away] -= change
    return dict(ratings)


def _recent_stats(team_key, matches):
    relevant = []
    for match in matches:
        side = "home" if _team_key(match, "home") == team_key else "away" if _team_key(match, "away") == team_key else None
        if not side:
            continue
        goals_for = match[f"{side}_goals"]
        goals_against = match["away_goals" if side == "home" else "home_goals"]
        points = 3 if goals_for > goals_against else 1 if goals_for == goals_against else 0
        relevant.append((goals_for, goals_against, points))
    recent = relevant[:5]
    if not recent:
        return {"played": 0, "points_rate": 0.34, "gf": 1.1, "ga": 1.1}
    return {
        "played": len(recent),
        "points_rate": sum(item[2] for item in recent) / (len(recent) * 3),
        "gf": sum(item[0] for item in recent) / len(recent),
        "ga": sum(item[1] for item in recent) / len(recent),
    }


def build_match_prediction(fixture_id, fixture=None, completed_matches=None, elo_ratings=None):
    if fixture is None:
        with get_db() as conn:
            row = conn.execute("SELECT * FROM football_matches WHERE fixture_id = ?", (fixture_id,)).fetchone()
        if not row:
            return None
        fixture = dict(row)
    completed = completed_matches if completed_matches is not None else _load_completed_matches(exclude_fixture_id=fixture_id)
    if len(completed) < 3:
        return {"fixture_id": fixture_id, "prediction": {"insufficient_data": True, "confidence": 0}}
    elos = elo_ratings if elo_ratings is not None else _calculate_elos(completed)
    home_key = _team_key(fixture, "home")
    away_key = _team_key(fixture, "away")
    home_stats = _recent_stats(home_key, completed)
    away_stats = _recent_stats(away_key, completed)
    home_elo = elos.get(home_key, 1500.0)
    away_elo = elos.get(away_key, 1500.0)
    home_raw = 42 + home_stats["points_rate"] * 25 + (home_stats["gf"] - away_stats["ga"]) * 5 + (home_elo - away_elo) / 30
    away_raw = 34 + away_stats["points_rate"] * 25 + (away_stats["gf"] - home_stats["ga"]) * 5 + (away_elo - home_elo) / 30
    draw_raw = 28 - abs(home_raw - away_raw) * 0.12
    values = [max(8, home_raw), max(8, draw_raw), max(8, away_raw)]
    total = sum(values)
    home_prob, draw_prob, away_prob = [round(value / total * 100) for value in values]
    drift = 100 - home_prob - draw_prob - away_prob
    home_prob += drift
    probs = {"home": home_prob, "draw": draw_prob, "away": away_prob}
    winner = max(probs, key=probs.get)
    confidence = probs[winner]
    predicted_score = "1-1" if winner == "draw" else ("2-1" if winner == "home" else "1-2")
    prediction = {
        "winner": winner,
        "confidence": confidence,
        "home_win_prob": home_prob,
        "draw_prob": draw_prob,
        "away_win_prob": away_prob,
        "predicted_score": predicted_score,
        "prediction_detail": "基于近期战绩、进失球和 Elo 评分的轻量预测",
        "factors": [
            {"type": "stat", "text": f"主队近况 {home_stats['points_rate']:.0%} / 客队近况 {away_stats['points_rate']:.0%}"},
            {"type": "positive" if home_elo >= away_elo else "negative", "text": f"Elo {round(home_elo)} - {round(away_elo)}"},
        ],
        "h2h_summary": {"total": 0, "home_wins": 0, "away_wins": 0, "draws": 0},
        "injury_summary": {"home_count": 0, "away_count": 0, "home_penalty": 0, "away_penalty": 0},
        "elo_summary": {"home_elo": round(home_elo), "away_elo": round(away_elo)},
    }
    return {"fixture_id": fixture_id, "prediction": prediction}


def build_corner_prediction(fixture_id, fixture=None, completed_matches=None):
    completed = completed_matches if completed_matches is not None else _load_completed_matches(exclude_fixture_id=fixture_id)
    samples = []
    for match in completed:
        try:
            import json
            stats = json.loads(match.get("stats") or "{}")
        except Exception:
            stats = {}
        corners = [float(value) for key, value in stats.items() if "Corner" in key and str(value).replace(".", "", 1).isdigit()]
        if corners:
            samples.append(sum(corners))
    expected = round(sum(samples) / len(samples)) if samples else 9
    return {
        "fixture_id": fixture_id,
        "prediction": {
            "first_half": {"low": max(1, expected // 2 - 1), "high": max(3, expected // 2 + 1)},
            "full_time": {"low": max(4, expected - 2), "high": expected + 2},
        },
    }
