#!/usr/bin/env python3
"""
K38 足球监控 — Web 仪表盘
Flask 应用，提供本地可视化界面
"""

import json
from datetime import datetime

from flask import Flask, render_template, jsonify, request

import settings
from models import get_db, init_db
from collector import load_seed_data, collect_from_api, USE_MOCK

app = Flask(__name__)

# 确保数据库就绪
init_db()

COLOR_PALETTE = ("#e74c3c", "#2ecc71", "#f39c12", "#3498db", "#9b59b6", "#1abc9c", "#e67e22")
LEAGUE_COLORS = {
    league_id: COLOR_PALETTE[index % len(COLOR_PALETTE)]
    for index, league_id in enumerate(settings.LEAGUES)
}
LEAGUE_ICONS = ("🏆", "🇬🇧", "🇪🇸", "🇮🇹", "🇩🇪", "🇫🇷", "🇨🇳", "⚽")


def status_emoji(status):
    if not status:
        return "📋"
    if "Finished" in status:
        return "🏁"
    if "Half" in status or "Live" in status or status in ("Second Half", "First Half", "In Progress"):
        return "🟢"
    if "Penalty" in status or "Extra" in status:
        return "⚡"
    if "Suspended" in status or "Interrupted" in status:
        return "⏸"
    return "📋"


def get_status_sort_key(status):
    """排序：进行中 > 半场 > 未开始 > 已结束"""
    if not status:
        return 3
    if "Half" in status or status in ("First Half", "Halftime"):
        return 1
    if "Live" in status or status in ("Second Half", "In Progress"):
        return 0
    if "Finished" in status:
        return 4
    if "Extra" in status or "Penalty" in status:
        return 0
    if "Suspended" in status or "Interrupted" in status:
        return 2
    return 3


def format_score(h, a):
    if h is None and a is None:
        return "vs"
    return f"{h if h is not None else '?'} - {a if a is not None else '?'}"


def latest_goal_hint(events):
    """Return a short display hint for the latest goal event."""
    goals = [event for event in events if event.get("type") == "Goal"]
    if not goals:
        return ""
    latest = max(goals, key=lambda item: int(item.get("time") or 0))
    player = latest.get("player") or latest.get("detail", "").strip()
    team = latest.get("team", "")
    minute = latest.get("time", "")
    label = f"{minute}' " if minute != "" else ""
    return f"⚽ {label}{team} {player}".strip()


def is_finished(status):
    return bool(status and "Finished" in status)


def compute_standings(league_filter="all"):
    """Calculate league standings from finished match results."""
    query = "SELECT * FROM football_matches WHERE home_goals IS NOT NULL AND away_goals IS NOT NULL"
    params = []
    if league_filter != "all":
        query += " AND league_id = ?"
        params.append(int(league_filter))
    query += " ORDER BY league_id, match_date"

    tables = {}
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    for row in rows:
        match = dict(row)
        if not is_finished(match.get("status")):
            continue

        league_id = match.get("league_id")
        league_name = match.get("league_name") or settings.LEAGUES.get(league_id, str(league_id))
        table = tables.setdefault(
            league_id,
            {
                "league_id": league_id,
                "league_name": league_name,
                "league_color": LEAGUE_COLORS.get(league_id, "#666"),
                "teams": {},
            },
        )

        home_goals = int(match["home_goals"])
        away_goals = int(match["away_goals"])
        _apply_result(table["teams"], match["home_team"], home_goals, away_goals)
        _apply_result(table["teams"], match["away_team"], away_goals, home_goals)

    standings = []
    for table in tables.values():
        teams = sorted(
            table["teams"].values(),
            key=lambda team: (
                -team["points"],
                -team["goal_difference"],
                -team["goals_for"],
                team["team"],
            ),
        )
        for index, team in enumerate(teams, start=1):
            team["rank"] = index
        table["teams"] = teams
        standings.append(table)

    standings.sort(key=lambda table: table["league_name"])
    return standings


def _apply_result(teams, team_name, goals_for, goals_against):
    team = teams.setdefault(
        team_name,
        {
            "team": team_name,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
        },
    )
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


@app.route("/")
def index():
    return render_template(
        "index.html",
        leagues=LEAGUE_COLORS,
        league_names=settings.LEAGUES,
        league_icons=LEAGUE_ICONS,
    )


@app.route("/api/matches")
def api_matches():
    league = request.args.get("league", "all")
    status_filter = request.args.get("status", "all")

    with get_db() as conn:
        if league == "all":
            rows = conn.execute(
                "SELECT * FROM football_matches ORDER BY match_date DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM football_matches WHERE league_id = ? ORDER BY match_date DESC",
                (int(league),)
            ).fetchall()

    matches = []
    for r in rows:
        m = dict(r)
        m["stats"] = json.loads(m.get("stats", "{}"))
        m["events"] = json.loads(m.get("events", "[]"))
        m["score_display"] = format_score(m.get("home_goals"), m.get("away_goals"))
        m["status_sort"] = get_status_sort_key(m.get("status"))
        m["emoj"] = status_emoji(m.get("status"))
        m["league_color"] = LEAGUE_COLORS.get(m.get("league_id"), "#666")
        m["latest_goal"] = latest_goal_hint(m["events"])
        matches.append(m)

    # 排序：进行中优先，然后是今天，最后按时间
    matches.sort(key=lambda m: (m["status_sort"], m.get("match_date", "")))

    if status_filter == "live":
        matches = [m for m in matches if m["status_sort"] <= 2]
    elif status_filter == "finished":
        matches = [m for m in matches if m["status_sort"] == 4]
    elif status_filter == "upcoming":
        matches = [m for m in matches if m["status_sort"] == 3 and m.get("home_goals") is None and m.get("away_goals") is None]

    return jsonify({
        "matches": matches,
        "total": len(matches),
        "is_mock": USE_MOCK,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/match/<int:fixture_id>")
def api_match_detail(fixture_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM football_matches WHERE fixture_id = ?",
            (fixture_id,)
        ).fetchone()

    if not row:
        return jsonify({"error": "not found"}), 404

    m = dict(row)
    m["stats"] = json.loads(m.get("stats", "{}"))
    m["events"] = json.loads(m.get("events", "[]"))
    m["score_display"] = format_score(m.get("home_goals"), m.get("away_goals"))
    m["status_sort"] = get_status_sort_key(m.get("status"))
    m["latest_goal"] = latest_goal_hint(m["events"])
    return jsonify(m)


@app.route("/standings")
def standings():
    return render_template(
        "standings.html",
        leagues=LEAGUE_COLORS,
        league_names=settings.LEAGUES,
        league_icons=LEAGUE_ICONS,
    )


@app.route("/api/standings")
def api_standings():
    league = request.args.get("league", "all")
    return jsonify({
        "standings": compute_standings(league),
        "is_mock": USE_MOCK,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })


@app.route("/api/refresh")
def api_refresh():
    """手动刷新数据"""
    try:
        count = collect_from_api()
        msg = f"从 API 采集到 {count} 场比赛"
    except Exception as e:
        msg = f"采集失败: {e}"

    return jsonify({"message": msg, "is_mock": USE_MOCK})


@app.route("/api/seed")
def api_seed():
    """加载种子数据"""
    count = load_seed_data()
    return jsonify({"message": f"已加载 {count} 场模拟比赛", "count": count})


@app.route("/match/<int:fixture_id>")
def match_detail(fixture_id):
    return render_template("match.html", fixture_id=fixture_id)


if __name__ == "__main__":
    # 首次启动自动加载种子数据
    with get_db() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM football_matches").fetchone()[0]
        if cnt == 0:
            n = load_seed_data()
            print(f"[K38] 已加载 {n} 场种子数据")

    app.run(host="127.0.0.1", port=6789, debug=True)
