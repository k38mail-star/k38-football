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
HOME_ADVANTAGE_ELO = 60.0
RECENT_MATCH_LIMIT = 8
PREDICTION_VERSION = "2026-06-19-v2"
RESULTS = ("HOME", "DRAW", "AWAY")


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
    probabilities: dict[str, float]
    details: dict[str, Any]


class BacktestError(Exception):
    """Raised when the backtest cannot run safely."""


class EloModel:
    name = "elo_v2"

    def __init__(self) -> None:
        self.ratings: dict[str, float] = defaultdict(lambda: DEFAULT_ELO)

    def predict(self, match: Match) -> Prediction:
        home_elo = self.ratings[match.home_team]
        away_elo = self.ratings[match.away_team]
        probabilities = elo_probabilities(home_elo, away_elo)
        predicted_result, confidence = prediction_from_probabilities(probabilities)

        return Prediction(
            algorithm=self.name,
            predicted_result=predicted_result,
            confidence=confidence,
            probabilities=probabilities,
            details={
                "home_elo": round(home_elo, 2),
                "away_elo": round(away_elo, 2),
                **rounded_probabilities(probabilities),
            },
        )

    def update(self, match: Match) -> None:
        home_elo = self.ratings[match.home_team]
        away_elo = self.ratings[match.away_team]
        expected_home = expected_score(home_elo + HOME_ADVANTAGE_ELO, away_elo)
        actual_home = {"HOME": 1.0, "DRAW": 0.5, "AWAY": 0.0}[match.actual_result]
        goal_multiplier = 1.0 + min(abs(match.home_goals - match.away_goals), 4) * 0.12
        adjustment = ELO_K_FACTOR * goal_multiplier * (actual_home - expected_home)

        self.ratings[match.home_team] = home_elo + adjustment
        self.ratings[match.away_team] = away_elo - adjustment


class RecentFormModel:
    name = "recent_form_v2"

    def __init__(self) -> None:
        self.team_matches: dict[tuple[str, str], deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=RECENT_MATCH_LIMIT)
        )

    def predict(self, match: Match) -> Prediction:
        competition = competition_key(match)
        home_form = self._score_team(competition, match.home_team)
        away_form = self._score_team(competition, match.away_team)
        score_delta = home_form["score"] - away_form["score"]
        probabilities = delta_probabilities(score_delta, draw_base=0.28, sharpness=1.55)
        predicted_result, confidence = prediction_from_probabilities(probabilities)

        return Prediction(
            algorithm=self.name,
            predicted_result=predicted_result,
            confidence=confidence,
            probabilities=probabilities,
            details={
                "competition": competition,
                "home_recent_matches": home_form["matches"],
                "away_recent_matches": away_form["matches"],
                "home_weighted_win_rate": round(home_form["weighted_win_rate"], 4),
                "away_weighted_win_rate": round(away_form["weighted_win_rate"], 4),
                "home_avg_goal_diff": round(home_form["avg_goal_diff"], 4),
                "away_avg_goal_diff": round(away_form["avg_goal_diff"], 4),
                "score_delta": round(score_delta, 4),
                **rounded_probabilities(probabilities),
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
        score = weighted_win_rate + (avg_goal_diff * 0.22)

        return {
            "matches": len(recent),
            "weighted_win_rate": weighted_win_rate,
            "avg_goal_diff": avg_goal_diff,
            "score": score,
        }


class H2HModel:
    name = "h2h_v2"

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
                probabilities=fallback.probabilities,
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
        total_score = max(home_score + away_score, 1.0)
        probabilities = delta_probabilities(score_delta / total_score, draw_base=0.30, sharpness=2.0)
        predicted_result, confidence = prediction_from_probabilities(probabilities)

        return Prediction(
            algorithm=self.name,
            predicted_result=predicted_result,
            confidence=confidence,
            probabilities=probabilities,
            details={
                "h2h_meetings": len(meetings),
                "home_h2h_score": round(home_score, 4),
                "away_h2h_score": round(away_score, 4),
                "latest_result": latest["result"],
                "latest_match_date": latest["match_date"],
                "score_delta": round(score_delta, 4),
                **rounded_probabilities(probabilities),
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


class PoissonGoalModel:
    name = "poisson_goals"

    def __init__(self) -> None:
        self.team_matches: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=RECENT_MATCH_LIMIT)
        )

    def predict(self, match: Match) -> Prediction:
        home_attack = self._team_average(match.home_team, "goals_for", default=1.35)
        home_defense = self._team_average(match.home_team, "goals_against", default=1.15)
        away_attack = self._team_average(match.away_team, "goals_for", default=1.15)
        away_defense = self._team_average(match.away_team, "goals_against", default=1.35)
        home_expected = clamp((home_attack + away_defense) / 2.0 + 0.18, 0.25, 3.8)
        away_expected = clamp((away_attack + home_defense) / 2.0, 0.20, 3.6)
        probabilities = poisson_match_probabilities(home_expected, away_expected)
        predicted_result, confidence = prediction_from_probabilities(probabilities)

        return Prediction(
            algorithm=self.name,
            predicted_result=predicted_result,
            confidence=confidence,
            probabilities=probabilities,
            details={
                "home_expected_goals": round(home_expected, 3),
                "away_expected_goals": round(away_expected, 3),
                "home_sample": len(self.team_matches[match.home_team]),
                "away_sample": len(self.team_matches[match.away_team]),
                **rounded_probabilities(probabilities),
            },
        )

    def update(self, match: Match) -> None:
        self.team_matches[match.home_team].append(
            {"goals_for": match.home_goals, "goals_against": match.away_goals}
        )
        self.team_matches[match.away_team].append(
            {"goals_for": match.away_goals, "goals_against": match.home_goals}
        )

    def _team_average(self, team: str, key: str, *, default: float) -> float:
        matches = list(self.team_matches[team])
        if not matches:
            return default
        weights = list(range(1, len(matches) + 1))
        weighted = sum(float(item[key]) * weight for item, weight in zip(matches, weights))
        return weighted / sum(weights)


class EnsembleModel:
    name = "ensemble_v2"

    def __init__(self, models: tuple[Any, ...]) -> None:
        self.models = models
        self.weights = {
            "elo_v2": 0.32,
            "recent_form_v2": 0.26,
            "h2h_v2": 0.16,
            "poisson_goals": 0.26,
        }

    def predict(self, match: Match) -> Prediction:
        parts = [model.predict(match) for model in self.models]
        weighted = {result: 0.0 for result in RESULTS}
        total_weight = 0.0
        for part in parts:
            weight = self.weights.get(part.algorithm, 0.0)
            total_weight += weight
            for result in RESULTS:
                weighted[result] += part.probabilities[result] * weight
        probabilities = normalize_probabilities(weighted, total_weight or 1.0)
        predicted_result, confidence = prediction_from_probabilities(probabilities)
        ordered = sorted(probabilities.values(), reverse=True)

        return Prediction(
            algorithm=self.name,
            predicted_result=predicted_result,
            confidence=confidence,
            probabilities=probabilities,
            details={
                "weights": self.weights,
                "probability_margin": round(ordered[0] - ordered[1], 4),
                "components": {
                    part.algorithm: {
                        "predicted_result": part.predicted_result,
                        "confidence": round(part.confidence, 4),
                        **rounded_probabilities(part.probabilities),
                    }
                    for part in parts
                },
                **rounded_probabilities(probabilities),
            },
        )

    def update(self, match: Match) -> None:
        return None


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
        poisson_model = PoissonGoalModel()
        base_models = (elo_model, recent_form_model, h2h_model, poisson_model)
        ensemble_model = EnsembleModel(base_models)
        models = (*base_models, ensemble_model)

        summaries: dict[str, dict[str, Any]] = {model.name: new_summary() for model in models}

        for match in matches:
            predictions = [model.predict(match) for model in models]
            for prediction in predictions:
                is_correct = prediction.predicted_result == match.actual_result
                summary = summaries[prediction.algorithm]
                update_summary(summary, prediction, match)
                insert_prediction_log(
                    conn=conn,
                    run_id=run_id,
                    started_at=started_at,
                    match=match,
                    prediction=prediction,
                    is_correct=is_correct,
                )

            for model in base_models:
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
            league_id INTEGER,
            league_name TEXT,
            predicted_result TEXT NOT NULL,
            actual_result TEXT NOT NULL,
            predicted_winner TEXT,
            actual_winner TEXT,
            confidence REAL NOT NULL,
            is_correct INTEGER NOT NULL,
            home_win_probability REAL,
            draw_probability REAL,
            away_win_probability REAL,
            probability_margin REAL,
            brier_score REAL,
            log_loss REAL,
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
    columns = table_columns(conn, "prediction_log")
    column_defs = {
        "league_id": "INTEGER",
        "league_name": "TEXT",
        "home_win_probability": "REAL",
        "draw_probability": "REAL",
        "away_win_probability": "REAL",
        "probability_margin": "REAL",
        "brier_score": "REAL",
        "log_loss": "REAL",
    }
    for column, definition in column_defs.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE prediction_log ADD COLUMN {column} {definition}")


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
    probability_margin = top_probability_margin(prediction.probabilities)
    brier = brier_score(prediction.probabilities, match.actual_result)
    loss = log_loss(prediction.probabilities, match.actual_result)
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
            league_id,
            league_name,
            predicted_result,
            actual_result,
            predicted_winner,
            actual_winner,
            confidence,
            is_correct,
            home_win_probability,
            draw_probability,
            away_win_probability,
            probability_margin,
            brier_score,
            log_loss,
            home_goals,
            away_goals,
            details,
            created_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(run_id, algorithm, fixture_id) DO UPDATE SET
            predicted_result=excluded.predicted_result,
            actual_result=excluded.actual_result,
            predicted_winner=excluded.predicted_winner,
            actual_winner=excluded.actual_winner,
            confidence=excluded.confidence,
            is_correct=excluded.is_correct,
            home_win_probability=excluded.home_win_probability,
            draw_probability=excluded.draw_probability,
            away_win_probability=excluded.away_win_probability,
            probability_margin=excluded.probability_margin,
            brier_score=excluded.brier_score,
            log_loss=excluded.log_loss,
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
            match.league_id,
            match.league_name,
            prediction.predicted_result,
            match.actual_result,
            winner_name(match, prediction.predicted_result),
            winner_name(match, match.actual_result),
            round(prediction.confidence, 6),
            int(is_correct),
            round(prediction.probabilities["HOME"], 6),
            round(prediction.probabilities["DRAW"], 6),
            round(prediction.probabilities["AWAY"], 6),
            round(probability_margin, 6),
            round(brier, 6),
            round(loss, 6),
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


def elo_probabilities(home_elo: float, away_elo: float) -> dict[str, float]:
    expected_home = expected_score(home_elo + HOME_ADVANTAGE_ELO, away_elo)
    draw_probability = clamp(0.28 - abs(expected_home - 0.5) * 0.18, 0.18, 0.31)
    remaining = 1.0 - draw_probability
    return {
        "HOME": remaining * expected_home,
        "DRAW": draw_probability,
        "AWAY": remaining * (1.0 - expected_home),
    }


def delta_probabilities(delta: float, *, draw_base: float, sharpness: float) -> dict[str, float]:
    home_strength = math.exp(delta * sharpness)
    away_strength = math.exp(-delta * sharpness)
    draw_probability = clamp(draw_base - min(abs(delta), 1.0) * 0.12, 0.16, 0.36)
    remaining = 1.0 - draw_probability
    side_total = home_strength + away_strength
    return {
        "HOME": remaining * home_strength / side_total,
        "DRAW": draw_probability,
        "AWAY": remaining * away_strength / side_total,
    }


def poisson_match_probabilities(home_expected: float, away_expected: float) -> dict[str, float]:
    home = draw = away = 0.0
    for home_goals in range(8):
        home_p = poisson_probability(home_expected, home_goals)
        for away_goals in range(8):
            probability = home_p * poisson_probability(away_expected, away_goals)
            if home_goals > away_goals:
                home += probability
            elif home_goals == away_goals:
                draw += probability
            else:
                away += probability
    return normalize_probabilities({"HOME": home, "DRAW": draw, "AWAY": away}, home + draw + away)


def poisson_probability(expected_goals: float, goals: int) -> float:
    return math.exp(-expected_goals) * math.pow(expected_goals, goals) / math.factorial(goals)


def normalize_probabilities(values: dict[str, float], total: float | None = None) -> dict[str, float]:
    denominator = total if total is not None else sum(values.values())
    if denominator <= 0:
        return {"HOME": 1 / 3, "DRAW": 1 / 3, "AWAY": 1 / 3}
    return {result: clamp(values.get(result, 0.0) / denominator, 0.001, 0.998) for result in RESULTS}


def prediction_from_probabilities(probabilities: dict[str, float]) -> tuple[str, float]:
    home_away_margin = abs(probabilities["HOME"] - probabilities["AWAY"])
    if probabilities["DRAW"] >= 0.24 and home_away_margin <= 0.075:
        return "DRAW", bounded_confidence(probabilities["DRAW"])
    result = max(RESULTS, key=lambda key: probabilities[key])
    return result, bounded_confidence(probabilities[result])


def rounded_probabilities(probabilities: dict[str, float]) -> dict[str, float]:
    return {
        "home_win_probability": round(probabilities["HOME"], 4),
        "draw_probability": round(probabilities["DRAW"], 4),
        "away_win_probability": round(probabilities["AWAY"], 4),
    }


def top_probability_margin(probabilities: dict[str, float]) -> float:
    ordered = sorted(probabilities.values(), reverse=True)
    return ordered[0] - ordered[1]


def brier_score(probabilities: dict[str, float], actual_result: str) -> float:
    return sum((probabilities[result] - (1.0 if result == actual_result else 0.0)) ** 2 for result in RESULTS)


def log_loss(probabilities: dict[str, float], actual_result: str) -> float:
    return -math.log(max(0.001, min(0.999, probabilities[actual_result])))


def new_summary() -> dict[str, Any]:
    return {
        "total": 0,
        "correct": 0,
        "home": 0,
        "away": 0,
        "draw": 0,
        "confidence_sum": 0.0,
        "brier_sum": 0.0,
        "log_loss_sum": 0.0,
        "margin_sum": 0.0,
        "predicted": {result: 0 for result in RESULTS},
        "actual": {result: 0 for result in RESULTS},
        "correct_by_result": {result: 0 for result in RESULTS},
    }


def update_summary(summary: dict[str, Any], prediction: Prediction, match: Match) -> None:
    actual = match.actual_result
    is_correct = prediction.predicted_result == actual
    summary["total"] += 1
    summary["correct"] += int(is_correct)
    summary[actual.lower()] += 1
    summary["confidence_sum"] += prediction.confidence
    summary["brier_sum"] += brier_score(prediction.probabilities, actual)
    summary["log_loss_sum"] += log_loss(prediction.probabilities, actual)
    summary["margin_sum"] += top_probability_margin(prediction.probabilities)
    summary["predicted"][prediction.predicted_result] += 1
    summary["actual"][actual] += 1
    summary["correct_by_result"][actual] += int(is_correct)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


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
    print(
        f"{'Algorithm':<18} {'Correct':>8} {'Total':>8} {'Accuracy':>10} "
        f"{'AvgConf':>9} {'Brier':>8} {'LogLoss':>8} {'DrawRec':>8}"
    )
    print("-" * 86)

    for algorithm, summary in report["summaries"].items():
        total = summary["total"]
        correct = summary["correct"]
        accuracy = (correct / total * 100.0) if total else 0.0
        avg_confidence = summary["confidence_sum"] / total * 100.0 if total else 0.0
        avg_brier = summary["brier_sum"] / total if total else 0.0
        avg_log_loss = summary["log_loss_sum"] / total if total else 0.0
        draw_total = summary["actual"]["DRAW"]
        draw_recall = summary["correct_by_result"]["DRAW"] / draw_total * 100.0 if draw_total else 0.0
        print(
            f"{algorithm:<18} {correct:>8} {total:>8} {accuracy:>9.2f}% "
            f"{avg_confidence:>8.2f}% {avg_brier:>8.3f} {avg_log_loss:>8.3f} "
            f"{draw_recall:>7.2f}%"
        )

    print()
    print("Prediction distribution (HOME/DRAW/AWAY):")
    for algorithm, summary in report["summaries"].items():
        predicted = summary["predicted"]
        print(
            f"- {algorithm}: "
            f"{predicted['HOME']}/{predicted['DRAW']}/{predicted['AWAY']}"
        )

    print()
    print("Prediction records saved to prediction_log.")


if __name__ == "__main__":
    raise SystemExit(main())
