#!/usr/bin/env python3
"""
K38 football prediction backtesting framework.

Run this script from the project directory or from /opt/k38-football:

    python3 backtest.py

It reads finished historical matches from football.db, simulates predictions
using only matches that happened earlier, and writes every prediction to the
prediction_log table.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = BASE_DIR / "football.db"
DEFAULT_ELO = 1500.0
ELO_K_FACTOR = 32.0
RECENT_MATCH_LIMIT = 5
PREDICTION_VERSION = "2026-06-18"


FINISHED_STATUS_KEYWORDS = (
    "finished",
    "after extra time",
    "after penalties",
    "match finished",
    "full time",
    "full-time",
)
FINISHED_STATUS_CODES = {"ft", "aet", "pen"}


@dataclass(frozen=True)
class Match:
    fixture_id: int
    season: str
    match_date: str
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    status: str
    league_id: int | None = None
    league_name: str | None = None
    round_name: str | None = None
    home_team_cn: str | None = None
    away_team_cn: str | None = None
    home_flag: str | None = None
    away_flag: str | None = None

    @property
    def actual_result(self) -> str:
        if self.home_goals > self.away_goals:
            return "HOME"
        if self.away_goals > self.home_goals:
            return "AWAY"
        return "DRAW"


@dataclass(frozen=True)
class Prediction:
    algorithm: str
    predicted_result: str
    confidence: float
    details: dict[str, Any]


class BacktestError(Exception):
    """Raised when the backtest cannot run safely."""


class EloModel:
    name = "elo"

    def __init__(self) -> None:
        self.ratings: dict[str, float] = defaultdict(lambda: DEFAULT_ELO)

    def predict(self, match: Match) -> Prediction:
        home_elo = self.ratings[match.home_team]
        away_elo = self.ratings[match.away_team]
        home_probability = expected_score(home_elo, away_elo)
        predicted_result = "HOME" if home_elo >= away_elo else "AWAY"
        confidence = max(home_probability, 1.0 - home_probability)

        return Prediction(
            algorithm=self.name,
            predicted_result=predicted_result,
            confidence=confidence,
            details={
                "home_elo": round(home_elo, 2),
                "away_elo": round(away_elo, 2),
                "home_win_probability": round(home_probability, 4),
                "away_win_probability": round(1.0 - home_probability, 4),
            },
        )

    def update(self, match: Match) -> None:
        if match.actual_result == "DRAW":
            return

        winner = match.home_team if match.actual_result == "HOME" else match.away_team
        loser = match.away_team if match.actual_result == "HOME" else match.home_team
        winner_elo = self.ratings[winner]
        loser_elo = self.ratings[loser]
        win_probability = expected_score(winner_elo, loser_elo)
        adjustment = ELO_K_FACTOR - (win_probability * ELO_K_FACTOR)

        self.ratings[winner] = winner_elo + adjustment
        self.ratings[loser] = loser_elo - adjustment


class RecentFormModel:
    name = "recent_form"

    def __init__(self) -> None:
        self.team_matches: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=RECENT_MATCH_LIMIT)
        )

    def predict(self, match: Match) -> Prediction:
        competition = competition_key(match)
        home_form = self._score_team(competition, match.home_team)
        away_form = self._score_team(competition, match.away_team)
        score_delta = home_form["score"] - away_form["score"]
        predicted_result = result_from_delta(score_delta, draw_band=0.08)
        confidence = bounded_confidence(0.34 + min(abs(score_delta) / 2.5, 0.55))

        return Prediction(
            algorithm=self.name,
            predicted_result=predicted_result,
            confidence=confidence,
            details={
                "competition": competition,
                "home_recent_matches": home_form["matches"],
                "away_recent_matches": away_form["matches"],
                "home_weighted_win_rate": round(home_form["weighted_win_rate"], 4),
                "away_weighted_win_rate": round(away_form["weighted_win_rate"], 4),
                "home_avg_goal_diff": round(home_form["avg_goal_diff"], 4),
                "away_avg_goal_diff": round(away_form["avg_goal_diff"], 4),
                "score_delta": round(score_delta, 4),
            },
        )

    def update(self, match: Match) -> None:
        competition = competition_key(match)
        self.team_matches[(competition, match.home_team)].append(
            {
                "result": result_for_team(match, match.home_team),
                "goal_diff": match.home_goals - match.away_goals,
            }
        )
        self.team_matches[(competition, match.away_team)].append(
            {
                "result": result_for_team(match, match.away_team),
                "goal_diff": match.away_goals - match.home_goals,
            }
        )

    def _score_team(self, competition: str, team: str) -> dict[str, float | int]:
        recent = list(self.team_matches[(competition, team)])
        if not recent:
            return {
                "matches": 0,
                "weighted_win_rate": 0.0,
                "avg_goal_diff": 0.0,
                "score": 0.0,
            }

        weights = list(range(1, len(recent) + 1))
        total_weight = float(sum(weights))
        weighted_points = 0.0
        weighted_goal_diff = 0.0

        for item, weight in zip(recent, weights):
            weighted_points += result_points(str(item["result"])) * weight
            weighted_goal_diff += float(item["goal_diff"]) * weight

        weighted_win_rate = weighted_points / total_weight
        avg_goal_diff = weighted_goal_diff / total_weight
        score = weighted_win_rate + (avg_goal_diff * 0.25)

        return {
            "matches": len(recent),
            "weighted_win_rate": weighted_win_rate,
            "avg_goal_diff": avg_goal_diff,
            "score": score,
        }


class H2HModel:
    name = "h2h"

    def __init__(self, elo_model: EloModel) -> None:
        self.elo_model = elo_model
        self.meetings: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

    def predict(self, match: Match) -> Prediction:
        key = pair_key(match.home_team, match.away_team)
        meetings = self.meetings.get(key, [])
        if not meetings:
            fallback = self.elo_model.predict(match)
            return Prediction(
                algorithm=self.name,
                predicted_result=fallback.predicted_result,
                confidence=fallback.confidence,
                details={
                    "fallback": "elo",
                    "h2h_meetings": 0,
                    "elo": fallback.details,
                },
            )

        home_score = 0.0
        away_score = 0.0
        for index, meeting in enumerate(meetings):
            recency_weight = index + 1
            if meeting["winner"] == match.home_team:
                home_score += 1.0 * recency_weight
            elif meeting["winner"] == match.away_team:
                away_score += 1.0 * recency_weight
            else:
                home_score += 0.5 * recency_weight
                away_score += 0.5 * recency_weight

        latest = meetings[-1]
        if latest["winner"] == match.home_team:
            home_score += 0.75
        elif latest["winner"] == match.away_team:
            away_score += 0.75

        score_delta = home_score - away_score
        predicted_result = result_from_delta(score_delta, draw_band=0.30)
        total_score = max(home_score + away_score, 1.0)
        confidence = bounded_confidence(0.34 + min(abs(score_delta) / total_score, 0.50))

        return Prediction(
            algorithm=self.name,
            predicted_result=predicted_result,
            confidence=confidence,
            details={
                "h2h_meetings": len(meetings),
                "home_h2h_score": round(home_score, 4),
                "away_h2h_score": round(away_score, 4),
                "latest_result": latest["result"],
                "latest_match_date": latest["match_date"],
                "score_delta": round(score_delta, 4),
            },
        )

    def update(self, match: Match) -> None:
        winner: str | None
        if match.actual_result == "HOME":
            winner = match.home_team
        elif match.actual_result == "AWAY":
            winner = match.away_team
        else:
            winner = None

        self.meetings[pair_key(match.home_team, match.away_team)].append(
            {
                "match_date": match.match_date,
                "home_team": match.home_team,
                "away_team": match.away_team,
                "result": match.actual_result,
                "winner": winner,
                "score": f"{match.home_goals}-{match.away_goals}",
            }
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backtest football prediction algorithms against historical matches."
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help=f"SQLite database path. Default: {DEFAULT_DB_PATH}",
    )
    parser.add_argument(
        "--reset-log",
        action="store_true",
        help="Delete existing prediction_log rows before writing this run.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit the number of finished matches used, for quick local checks.",
    )
    args = parser.parse_args()

    try:
        report = run_backtest(Path(args.db), reset_log=args.reset_log, limit=args.limit)
    except BacktestError as exc:
        print(f"Backtest failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # pragma: no cover - top-level safety net.
        print(f"Unexpected backtest error: {exc}", file=sys.stderr)
        return 1

    print_report(report)
    return 0


def run_backtest(
    db_path: Path,
    *,
    reset_log: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    if not db_path.exists():
        raise BacktestError(f"database not found: {db_path}")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started_at = now_iso()

    with connect_db(db_path) as conn:
        ensure_prediction_log(conn)
        if reset_log:
            conn.execute("DELETE FROM prediction_log")

        matches = load_finished_matches(conn, limit=limit)
        if not matches:
            raise BacktestError("no finished matches with scores found in football_matches")

        elo_model = EloModel()
        recent_form_model = RecentFormModel()
        h2h_model = H2HModel(elo_model)
        models = (elo_model, recent_form_model, h2h_model)

        summaries: dict[str, dict[str, int]] = {
            model.name: {"total": 0, "correct": 0, "home": 0, "away": 0, "draw": 0}
            for model in models
        }

        for match in matches:
            predictions = [model.predict(match) for model in models]
            for prediction in predictions:
                is_correct = prediction.predicted_result == match.actual_result
                summary = summaries[prediction.algorithm]
                summary["total"] += 1
                summary["correct"] += int(is_correct)
                summary[match.actual_result.lower()] += 1
                insert_prediction_log(
                    conn=conn,
                    run_id=run_id,
                    started_at=started_at,
                    match=match,
                    prediction=prediction,
                    is_correct=is_correct,
                )

            for model in models:
                model.update(match)

        conn.commit()

    return {
        "run_id": run_id,
        "started_at": started_at,
        "match_count": len(matches),
        "first_match_date": matches[0].match_date,
        "last_match_date": matches[-1].match_date,
        "summaries": summaries,
    }


def connect_db(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_prediction_log(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS prediction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            algorithm TEXT NOT NULL,
            prediction_version TEXT NOT NULL,
            fixture_id INTEGER NOT NULL,
            season TEXT,
            match_date TEXT,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            home_team_cn TEXT,
            away_team_cn TEXT,
            home_flag TEXT,
            away_flag TEXT,
            predicted_result TEXT NOT NULL,
            actual_result TEXT NOT NULL,
            predicted_winner TEXT,
            actual_winner TEXT,
            confidence REAL NOT NULL,
            is_correct INTEGER NOT NULL,
            home_goals INTEGER NOT NULL,
            away_goals INTEGER NOT NULL,
            details TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(run_id, algorithm, fixture_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prediction_log_run_algorithm
        ON prediction_log(run_id, algorithm)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_prediction_log_fixture
        ON prediction_log(fixture_id)
        """
    )


def load_finished_matches(conn: sqlite3.Connection, limit: int | None = None) -> list[Match]:
    columns = table_columns(conn, "football_matches")
    required = {
        "fixture_id",
        "season",
        "match_date",
        "home_team",
        "away_team",
        "home_goals",
        "away_goals",
        "status",
    }
    missing = sorted(required - columns)
    if missing:
        raise BacktestError(f"football_matches missing required columns: {', '.join(missing)}")

    optional_selects = {
        "league_id": "league_id" if "league_id" in columns else "NULL AS league_id",
        "league_name": "league_name" if "league_name" in columns else "NULL AS league_name",
        "round": "round" if "round" in columns else "NULL AS round",
        "home_team_cn": "home_team_cn" if "home_team_cn" in columns else "NULL AS home_team_cn",
        "away_team_cn": "away_team_cn" if "away_team_cn" in columns else "NULL AS away_team_cn",
        "home_flag": "home_flag" if "home_flag" in columns else "NULL AS home_flag",
        "away_flag": "away_flag" if "away_flag" in columns else "NULL AS away_flag",
    }

    sql = f"""
        SELECT
            fixture_id,
            season,
            match_date,
            home_team,
            away_team,
            home_goals,
            away_goals,
            status,
            {optional_selects["league_id"]},
            {optional_selects["league_name"]},
            {optional_selects["round"]},
            {optional_selects["home_team_cn"]},
            {optional_selects["away_team_cn"]},
            {optional_selects["home_flag"]},
            {optional_selects["away_flag"]}
        FROM football_matches
        WHERE home_goals IS NOT NULL
          AND away_goals IS NOT NULL
          AND home_team IS NOT NULL
          AND away_team IS NOT NULL
          AND match_date IS NOT NULL
        ORDER BY match_date ASC, fixture_id ASC
    """
    if limit is not None:
        if limit <= 0:
            raise BacktestError("--limit must be a positive integer")
        sql += " LIMIT ?"
        rows = conn.execute(sql, (limit,)).fetchall()
    else:
        rows = conn.execute(sql).fetchall()

    matches = []
    skipped_unfinished = 0
    skipped_invalid = 0
    for row in rows:
        if not is_finished_status(row["status"]):
            skipped_unfinished += 1
            continue
        try:
            matches.append(
                Match(
                    fixture_id=int(row["fixture_id"]),
                    season=str(row["season"] or ""),
                    match_date=str(row["match_date"] or ""),
                    home_team=str(row["home_team"]),
                    away_team=str(row["away_team"]),
                    home_goals=int(row["home_goals"]),
                    away_goals=int(row["away_goals"]),
                    status=str(row["status"] or ""),
                    league_id=to_optional_int(row["league_id"]),
                    league_name=to_optional_str(row["league_name"]),
                    round_name=to_optional_str(row["round"]),
                    home_team_cn=to_optional_str(row["home_team_cn"]),
                    away_team_cn=to_optional_str(row["away_team_cn"]),
                    home_flag=to_optional_str(row["home_flag"]),
                    away_flag=to_optional_str(row["away_flag"]),
                )
            )
        except (TypeError, ValueError):
            skipped_invalid += 1

    if skipped_unfinished or skipped_invalid:
        print(
            "Skipped matches: "
            f"unfinished={skipped_unfinished}, invalid_scores={skipped_invalid}",
            file=sys.stderr,
        )

    return matches


def insert_prediction_log(
    *,
    conn: sqlite3.Connection,
    run_id: str,
    started_at: str,
    match: Match,
    prediction: Prediction,
    is_correct: bool,
) -> None:
    conn.execute(
        """
        INSERT INTO prediction_log (
            run_id,
            algorithm,
            prediction_version,
            fixture_id,
            season,
            match_date,
            home_team,
            away_team,
            home_team_cn,
            away_team_cn,
            home_flag,
            away_flag,
            predicted_result,
            actual_result,
            predicted_winner,
            actual_winner,
            confidence,
            is_correct,
            home_goals,
            away_goals,
            details,
            created_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(run_id, algorithm, fixture_id) DO UPDATE SET
            predicted_result=excluded.predicted_result,
            actual_result=excluded.actual_result,
            predicted_winner=excluded.predicted_winner,
            actual_winner=excluded.actual_winner,
            confidence=excluded.confidence,
            is_correct=excluded.is_correct,
            home_goals=excluded.home_goals,
            away_goals=excluded.away_goals,
            details=excluded.details,
            created_at=excluded.created_at
        """,
        (
            run_id,
            prediction.algorithm,
            PREDICTION_VERSION,
            match.fixture_id,
            match.season,
            match.match_date,
            match.home_team,
            match.away_team,
            match.home_team_cn,
            match.away_team_cn,
            match.home_flag,
            match.away_flag,
            prediction.predicted_result,
            match.actual_result,
            winner_name(match, prediction.predicted_result),
            winner_name(match, match.actual_result),
            round(prediction.confidence, 6),
            int(is_correct),
            match.home_goals,
            match.away_goals,
            json.dumps(prediction.details, ensure_ascii=False, sort_keys=True),
            started_at,
        ),
    )


def table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    if not rows:
        raise BacktestError(f"table not found: {table_name}")
    return {str(row["name"]) for row in rows}


def is_finished_status(status: str | None) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in FINISHED_STATUS_CODES or any(
        keyword in normalized for keyword in FINISHED_STATUS_KEYWORDS
    )


def expected_score(team_elo: float, opponent_elo: float) -> float:
    return 1.0 / (1.0 + math.pow(10.0, (opponent_elo - team_elo) / 400.0))


def result_for_team(match: Match, team: str) -> str:
    if match.actual_result == "DRAW":
        return "DRAW"
    if match.actual_result == "HOME":
        return "WIN" if team == match.home_team else "LOSS"
    return "WIN" if team == match.away_team else "LOSS"


def result_points(result: str) -> float:
    if result == "WIN":
        return 1.0
    if result == "DRAW":
        return 0.5
    return 0.0


def result_from_delta(delta: float, *, draw_band: float) -> str:
    if abs(delta) <= draw_band:
        return "DRAW"
    return "HOME" if delta > 0 else "AWAY"


def bounded_confidence(value: float) -> float:
    return max(0.34, min(0.89, value))


def pair_key(team_a: str, team_b: str) -> tuple[str, str]:
    return tuple(sorted((team_a, team_b)))


def competition_key(match: Match) -> str:
    if match.league_id is not None:
        return f"league:{match.league_id}"
    if match.league_name:
        return f"league:{match.league_name}"
    return "competition:default"


def winner_name(match: Match, result: str) -> str | None:
    if result == "HOME":
        return match.home_team
    if result == "AWAY":
        return match.away_team
    return None


def to_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def to_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def print_report(report: dict[str, Any]) -> None:
    print("K38 Football Prediction Backtest")
    print("=" * 36)
    print(f"Run ID: {report['run_id']}")
    print(f"Matches: {report['match_count']}")
    print(f"Date range: {report['first_match_date']} -> {report['last_match_date']}")
    print()
    print(f"{'Algorithm':<16} {'Correct':>8} {'Total':>8} {'Accuracy':>10}")
    print("-" * 46)

    for algorithm, summary in report["summaries"].items():
        total = summary["total"]
        correct = summary["correct"]
        accuracy = (correct / total * 100.0) if total else 0.0
        print(f"{algorithm:<16} {correct:>8} {total:>8} {accuracy:>9.2f}%")

    print()
    print("Prediction records saved to prediction_log.")


if __name__ == "__main__":
    raise SystemExit(main())
