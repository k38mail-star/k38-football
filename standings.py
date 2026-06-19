from constants import LEAGUE_COLORS
from models import get_db


def compute_standings(league_filter="all"):
    params = []
    where = "home_goals IS NOT NULL AND away_goals IS NOT NULL"
    if league_filter != "all":
        where += " AND league_id = ?"
        params.append(int(league_filter))
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM football_matches WHERE {where} ORDER BY league_id, match_date",
            params,
        ).fetchall()

    tables = {}
    for row in rows:
        match = dict(row)
        league_id = match.get("league_id")
        table = tables.setdefault(league_id, {
            "league_id": league_id,
            "league_name": match.get("league_name") or str(league_id),
            "league_color": LEAGUE_COLORS.get(league_id, "#666"),
            "teams": {},
        })
        _apply_result(table["teams"], match.get("home_team"), match.get("home_goals"), match.get("away_goals"))
        _apply_result(table["teams"], match.get("away_team"), match.get("away_goals"), match.get("home_goals"))

    result = []
    for table in tables.values():
        teams = sorted(
            table["teams"].values(),
            key=lambda team: (-team["points"], -team["goal_difference"], -team["goals_for"], team["team"]),
        )
        for index, team in enumerate(teams, 1):
            team["rank"] = index
        result.append({**table, "teams": teams})
    return result


def _apply_result(teams, name, goals_for, goals_against):
    if not name:
        return
    team = teams.setdefault(name, {
        "team": name,
        "played": 0,
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "goals_for": 0,
        "goals_against": 0,
        "goal_difference": 0,
        "points": 0,
    })
    team["played"] += 1
    team["goals_for"] += goals_for
    team["goals_against"] += goals_against
    team["goal_difference"] = team["goals_for"] - team["goals_against"]
    if goals_for > goals_against:
        team["wins"] += 1
        team["points"] += 3
    elif goals_for == goals_against:
        team["draws"] += 1
        team["points"] += 1
    else:
        team["losses"] += 1
