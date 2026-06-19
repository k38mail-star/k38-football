#!/usr/bin/env python3
"""
K38 足球监控 — Web 仪表盘
Flask 应用，提供本地可视化界面。

业务逻辑已拆分到独立模块：
  - constants.py    联赛配色、i18n、国旗、enrich_team_fields
  - formatting.py   状态/比分/事件展示辅助
  - predictions.py  赛前预测与角球预测引擎
  - standings.py    积分榜计算
本文件只保留 Flask 路由与请求级编排。入口仍为 ``app:app``。
"""

import json
import time
from datetime import datetime
from functools import wraps

from flask import Flask, render_template, jsonify, make_response, request

import settings
from models import get_db, init_db
from collector import load_seed_data, collect_from_api, USE_MOCK
from constants import LEAGUE_COLORS, LEAGUE_ICONS, enrich_team_fields
from formatting import (
    status_emoji,
    get_status_sort_key,
    format_score,
    latest_goal_hint,
    normalize_events,
)
from predictions import (
    build_match_prediction,
    build_corner_prediction,
    _load_completed_matches,
    _calculate_elos,
)
from standings import compute_standings

app = Flask(__name__)

# 确保数据库就绪
init_db()

API_CACHE = {}
API_CACHE_TTL_SECONDS = 20
MAX_PER_PAGE = 80


def _now_label():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _cache_key(prefix):
    return (prefix, tuple(sorted(request.args.items())))


def _json_response(payload, ttl=API_CACHE_TTL_SECONDS, hit=False):
    response = make_response(jsonify(payload))
    response.headers["Cache-Control"] = f"public, max-age={ttl}"
    response.headers["X-Cache"] = "HIT" if hit else "MISS"
    return response


def _cached_json(prefix, ttl=API_CACHE_TTL_SECONDS):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            bypass = request.args.get("cache") == "0"
            key = _cache_key(prefix)
            now = time.monotonic()
            if not bypass:
                cached = API_CACHE.get(key)
                if cached and now - cached["ts"] < ttl:
                    return _json_response(cached["payload"], ttl=ttl, hit=True)
            payload = func(*args, **kwargs)
            API_CACHE[key] = {"ts": now, "payload": payload}
            return _json_response(payload, ttl=ttl)
        return wrapper
    return decorator


def _pagination_args(default_per_page=24):
    try:
        page = max(1, int(request.args.get("page", 1)))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", default_per_page))
    except (TypeError, ValueError):
        per_page = default_per_page
    per_page = min(MAX_PER_PAGE, max(1, per_page))
    return page, per_page


def _paginate(items, page, per_page):
    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": max(1, (total + per_page - 1) // per_page),
        "has_next": end < total,
        "has_prev": page > 1,
    }


def _pagination_meta(total, page, per_page):
    pages = max(1, (total + per_page - 1) // per_page)
    return {
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages,
        "has_next": page < pages,
        "has_prev": page > 1,
    }


def _match_where(league="all", status_filter="all"):
    where = []
    params = []
    if league != "all":
        where.append("league_id = ?")
        params.append(int(league))
    if status_filter == "live":
        where.append("status IN ('1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE', 'INT')")
    elif status_filter == "finished":
        where.append("status IN ('FT', 'AET', 'PEN')")
    elif status_filter == "upcoming":
        where.append("home_goals IS NULL AND away_goals IS NULL")
        where.append("status IN ('NS', 'TBD', 'PST', 'CANC', 'SUSP')")
    return (" WHERE " + " AND ".join(where)) if where else "", params


def _hydrate_match(row):
    """Turn a DB row into a JSON-ready match dict with display fields."""
    match = dict(row)
    match["stats"] = json.loads(match.get("stats", "{}") or "{}")
    match["events"] = normalize_events(json.loads(match.get("events", "[]") or "[]"))
    match["score_display"] = format_score(match.get("home_goals"), match.get("away_goals"))
    match["status_sort"] = get_status_sort_key(match.get("status"))
    match["emoj"] = status_emoji(match.get("status"))
    match["league_color"] = LEAGUE_COLORS.get(match.get("league_id"), "#666")
    match["latest_goal"] = latest_goal_hint(match["events"])
    enrich_team_fields(match)
    return match


def _is_upcoming(match):
    return (
        match["status_sort"] == 3
        and match.get("home_goals") is None
        and match.get("away_goals") is None
    )


@app.route("/")
def index():
    return render_template(
        "index.html",
        leagues=LEAGUE_COLORS,
        league_names=settings.LEAGUES,
        league_icons=LEAGUE_ICONS,
    )


@app.route("/api/matches")
@_cached_json("matches")
def api_matches():
    league = request.args.get("league", "all")
    status_filter = request.args.get("status", "all")
    page, per_page = _pagination_args()
    offset = (page - 1) * per_page
    where_sql, params = _match_where(league, status_filter)

    with get_db() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM football_matches{where_sql}",
            params,
        ).fetchone()[0]
        rows = conn.execute(
            f"""
            SELECT * FROM football_matches
            {where_sql}
            ORDER BY
                CASE
                    WHEN status IN ('1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE', 'INT') THEN 1
                    WHEN home_goals IS NULL AND away_goals IS NULL THEN 3
                    WHEN status IN ('FT', 'AET', 'PEN') THEN 4
                    ELSE 5
                END,
                match_date ASC
            LIMIT ? OFFSET ?
            """,
            [*params, per_page, offset],
        ).fetchall()
        count_where, count_params = _match_where(league, "all")
        count_row = conn.execute(
            f"""
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status IN ('1H', '2H', 'HT', 'ET', 'BT', 'P', 'LIVE', 'INT') THEN 1 ELSE 0 END) AS live,
                SUM(CASE WHEN home_goals IS NULL AND away_goals IS NULL
                    AND status IN ('NS', 'TBD', 'PST', 'CANC', 'SUSP') THEN 1 ELSE 0 END) AS upcoming,
                SUM(CASE WHEN status IN ('FT', 'AET', 'PEN') THEN 1 ELSE 0 END) AS finished
            FROM football_matches
            {count_where}
            """,
            count_params,
        ).fetchone()

    matches = [_hydrate_match(row) for row in rows]
    pagination = _pagination_meta(total, page, per_page)

    # 预测：只对当前页需要展示的即将开始比赛计算，避免列表接口全量预测。
    upcoming = [m for m in matches if _is_upcoming(m)]
    if upcoming:
        completed = _load_completed_matches(exclude_fixture_id=-1)
        elo_ratings = _calculate_elos(completed)
        for match in upcoming:
            prediction = build_match_prediction(
                match["fixture_id"], match,
                completed_matches=completed, elo_ratings=elo_ratings,
            )
            match["prediction"] = prediction["prediction"] if prediction else None
            corner_prediction = build_corner_prediction(
                match["fixture_id"], match, completed_matches=completed,
            )
            match["corner_prediction"] = corner_prediction["prediction"] if corner_prediction else None

    counts = {key: count_row[key] or 0 for key in ("total", "live", "upcoming", "finished")}
    return {
        "matches": matches,
        "pagination": pagination,
        "counts": counts,
        "total": pagination["total"],
        "is_mock": USE_MOCK,
        "updated_at": _now_label(),
    }


@app.route("/api/match/<int:fixture_id>")
def api_match_detail(fixture_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM football_matches WHERE fixture_id = ?",
            (fixture_id,),
        ).fetchone()

    if not row:
        return jsonify({"error": "not found"}), 404

    match = _hydrate_match(row)
    return jsonify(match)


@app.route("/api/predict/<int:fixture_id>")
def api_predict(fixture_id):
    prediction = build_match_prediction(fixture_id)
    if not prediction:
        return jsonify({"error": "not found"}), 404
    return jsonify(prediction)


@app.route("/api/predict/corners/<int:fixture_id>")
def api_predict_corners(fixture_id):
    prediction = build_corner_prediction(fixture_id)
    if not prediction:
        return jsonify({"error": "not found"}), 404
    return jsonify(prediction)


@app.route("/api/predictions")
@_cached_json("predictions", ttl=60)
def api_predictions():
    page, per_page = _pagination_args(default_per_page=30)
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM football_matches
            WHERE home_goals IS NULL
              AND away_goals IS NULL
            ORDER BY match_date
            """
        ).fetchall()

    upcoming = []
    for row in rows:
        match = dict(row)
        if get_status_sort_key(match.get("status")) != 3:
            continue
        match["status_sort"] = 3
        match["league_color"] = LEAGUE_COLORS.get(match.get("league_id"), "#666")
        enrich_team_fields(match)
        upcoming.append(match)

    # 一次性加载已完赛列表 + 计算 Elo，供全部预测复用（避免 N×M 全表扫描）
    predictions = []
    if upcoming:
        completed = _load_completed_matches(exclude_fixture_id=-1)
        elo_ratings = _calculate_elos(completed)
        for match in upcoming:
            prediction = build_match_prediction(
                match["fixture_id"], match,
                completed_matches=completed, elo_ratings=elo_ratings,
            )
            match["prediction"] = prediction["prediction"] if prediction else None
            predictions.append(match)

    predictions.sort(
        key=lambda match: (
            -(match.get("prediction") or {}).get("confidence", 0),
            match.get("match_date") or "",
        )
    )
    paged_predictions, pagination = _paginate(predictions, page, per_page)
    return {
        "predictions": paged_predictions,
        "pagination": pagination,
        "total": pagination["total"],
        "is_mock": USE_MOCK,
        "updated_at": _now_label(),
    }


@app.route("/predictions")
def predictions():
    return render_template("predictions.html")


@app.route("/standings")
def standings():
    return render_template(
        "standings.html",
        leagues=LEAGUE_COLORS,
        league_names=settings.LEAGUES,
        league_icons=LEAGUE_ICONS,
    )


@app.route("/api/standings")
@_cached_json("standings", ttl=60)
def api_standings():
    league = request.args.get("league", "all")
    return {
        "standings": compute_standings(league),
        "is_mock": USE_MOCK,
        "updated_at": _now_label(),
    }


@app.route("/api/refresh")
def api_refresh():
    """手动刷新数据"""
    try:
        count = collect_from_api()
        msg = f"从 API 采集到 {count} 场比赛"
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        msg = f"采集失败: {exc}"

    API_CACHE.clear()
    return jsonify({"message": msg, "is_mock": USE_MOCK})


@app.route("/api/seed")
def api_seed():
    """加载种子数据"""
    count = load_seed_data()
    API_CACHE.clear()
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

    app.run(host=settings.WEB_HOST, port=settings.WEB_PORT, debug=settings.WEB_DEBUG)
