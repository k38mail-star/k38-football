#!/usr/bin/env python3
"""
K38 足球监控 — 数据模型（SQLite）
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "football.db")


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS football_matches (
                fixture_id INTEGER PRIMARY KEY,
                league_id INTEGER,
                league_name TEXT,
                season TEXT,
                round TEXT,
                match_date TEXT,
                status TEXT,
                elapsed INTEGER DEFAULT 0,
                home_team TEXT,
                away_team TEXT,
                home_team_id INTEGER,
                away_team_id INTEGER,
                home_goals INTEGER,
                away_goals INTEGER,
                halftime_home INTEGER,
                halftime_away INTEGER,
                fulltime_home INTEGER,
                fulltime_away INTEGER,
                extra_home INTEGER,
                extra_away INTEGER,
                penalty_home INTEGER,
                penalty_away INTEGER,
                referee TEXT,
                venue TEXT,
                stats TEXT DEFAULT '{}',
                events TEXT DEFAULT '[]',
                details_fetched_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS football_match_notifications (
                fixture_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (fixture_id, notification_type)
            );

            CREATE TABLE IF NOT EXISTS football_h2h_cache (
                team1_id INTEGER NOT NULL,
                team2_id INTEGER NOT NULL,
                fixture_count INTEGER NOT NULL DEFAULT 0,
                team1_wins INTEGER NOT NULL DEFAULT 0,
                team2_wins INTEGER NOT NULL DEFAULT 0,
                draws INTEGER NOT NULL DEFAULT 0,
                fixtures TEXT NOT NULL DEFAULT '[]',
                fetched_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (team1_id, team2_id)
            );

            CREATE TABLE IF NOT EXISTS football_injuries (
                team_id INTEGER NOT NULL,
                season INTEGER NOT NULL,
                player_id INTEGER,
                player_name TEXT NOT NULL,
                injury_type TEXT,
                reason TEXT,
                expected_return TEXT,
                raw TEXT NOT NULL DEFAULT '{}',
                fetched_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (team_id, season, player_name, injury_type, expected_return)
            );

            CREATE TABLE IF NOT EXISTS football_prediction_refreshes (
                refresh_key TEXT PRIMARY KEY,
                refreshed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS football_api_cache (
                cache_key TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL,
                params TEXT NOT NULL DEFAULT '{}',
                response TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS prediction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                algorithm TEXT NOT NULL,
                prediction_version TEXT NOT NULL,
                fixture_id INTEGER NOT NULL,
                season TEXT,
                league_id INTEGER,
                league_name TEXT,
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
            );

            CREATE INDEX IF NOT EXISTS idx_football_injuries_team_season
                ON football_injuries(team_id, season, fetched_at);

            CREATE INDEX IF NOT EXISTS idx_prediction_log_run_algorithm
                ON prediction_log(run_id, algorithm);

            CREATE INDEX IF NOT EXISTS idx_prediction_log_fixture
                ON prediction_log(fixture_id);

            CREATE INDEX IF NOT EXISTS idx_prediction_log_algorithm_created
                ON prediction_log(algorithm, created_at);

            CREATE INDEX IF NOT EXISTS idx_football_matches_league_date
                ON football_matches(league_id, match_date);

            CREATE INDEX IF NOT EXISTS idx_football_matches_status_date
                ON football_matches(status, match_date);

            CREATE INDEX IF NOT EXISTS idx_football_api_cache_expires
                ON football_api_cache(expires_at);
        """)
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(football_matches)").fetchall()
        }
        if "details_fetched_at" not in columns:
            conn.execute("ALTER TABLE football_matches ADD COLUMN details_fetched_at TEXT")

        prediction_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(prediction_log)").fetchall()
        }
        prediction_column_defs = {
            "league_id": "INTEGER",
            "league_name": "TEXT",
            "home_win_probability": "REAL",
            "draw_probability": "REAL",
            "away_win_probability": "REAL",
            "probability_margin": "REAL",
            "brier_score": "REAL",
            "log_loss": "REAL",
        }
        for column, definition in prediction_column_defs.items():
            if column not in prediction_columns:
                conn.execute(f"ALTER TABLE prediction_log ADD COLUMN {column} {definition}")
