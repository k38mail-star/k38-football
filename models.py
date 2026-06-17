#!/usr/bin/env python3
"""
K38 足球监控 — 数据模型（SQLite）
"""

import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "football.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
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
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS football_match_notifications (
                fixture_id INTEGER NOT NULL,
                notification_type TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (fixture_id, notification_type)
            );
        """)
