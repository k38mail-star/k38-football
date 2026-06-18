#!/usr/bin/env python3
"""Standalone background collector daemon for K38 football monitoring."""

import logging
import os
import signal
import sys
import time
from pathlib import Path

import settings
from collector import (
    collect_live_matches,
    collect_schedule,
    load_seed_data,
    refresh_prediction_context_daily,
    USE_MOCK,
)
from models import get_db, init_db

shutdown_requested = False


def _next_interval(base_seconds, error_count=0):
    """Return base interval with capped exponential backoff for repeated failures."""
    if error_count <= 0:
        return float(base_seconds)
    return float(min(settings.POLL_ERROR_SECONDS * (2 ** (error_count - 1)), settings.POLL_IDLE_SECONDS))


def configure_logging():
    """Configure file and stdout logging for daemon and logrotate."""
    handlers = [logging.StreamHandler()]
    log_path = Path(settings.LOG_FILE)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_path, encoding="utf-8"))
    except OSError:
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=handlers,
    )


def write_pid():
    """Write the daemon PID file, refusing to overwrite a running process."""
    pid_path = Path(settings.PID_FILE)
    if pid_path.exists():
        try:
            old_pid = int(pid_path.read_text().strip())
            signal.kill(old_pid, 0)
            raise RuntimeError(f"daemon already running with PID {old_pid}")
        except ProcessLookupError:
            pass
        except ValueError:
            pass

    pid_path.write_text(str(os.getpid()))


def remove_pid():
    """Remove PID file on shutdown."""
    try:
        Path(settings.PID_FILE).unlink()
    except FileNotFoundError:
        pass


def handle_shutdown(signum, _frame):
    """Request graceful shutdown from SIGTERM/SIGINT."""
    global shutdown_requested
    logging.getLogger(__name__).info("received signal %s, shutting down", signum)
    shutdown_requested = True


def sleep_until(deadline):
    """Sleep in short intervals so signals stop the loop promptly."""
    while not shutdown_requested and time.monotonic() < deadline:
        time.sleep(min(1.0, deadline - time.monotonic()))


def ensure_seed_data():
    """Load seed data automatically in mock mode when the database is empty."""
    if not USE_MOCK:
        return
    with get_db() as conn:
        count = conn.execute("SELECT COUNT(*) FROM football_matches").fetchone()[0]
    if count == 0:
        loaded = load_seed_data()
        logging.getLogger(__name__).info("loaded %s seed matches in mock mode", loaded)


def main():
    """Run adaptive live and schedule polling."""
    configure_logging()
    logger = logging.getLogger(__name__)
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    init_db()
    ensure_seed_data()
    write_pid()

    next_live = 0.0
    next_schedule = 0.0
    live_errors = 0
    schedule_errors = 0
    logger.info("daemon started pid=%s mock=%s", Path(settings.PID_FILE).read_text().strip(), USE_MOCK)

    try:
        while not shutdown_requested:
            now = time.monotonic()
            if now >= next_live:
                try:
                    count = collect_live_matches()
                    logger.info("live collection complete: %s matches", count)
                    live_errors = 0
                    interval = settings.POLL_LIVE_SECONDS if count else settings.POLL_IDLE_SECONDS
                    next_live = time.monotonic() + interval
                except Exception:
                    live_errors += 1
                    logger.exception("live collection failed")
                    next_live = time.monotonic() + _next_interval(settings.POLL_ERROR_SECONDS, live_errors)

            if now >= next_schedule:
                try:
                    count = collect_schedule()
                    logger.info("schedule collection complete: %s matches", count)
                    schedule_errors = 0
                    next_schedule = time.monotonic() + settings.POLL_TODAY_SECONDS
                except Exception:
                    schedule_errors += 1
                    logger.exception("schedule collection failed")
                    next_schedule = time.monotonic() + _next_interval(settings.POLL_ERROR_SECONDS, schedule_errors)

                try:
                    context = refresh_prediction_context_daily()
                    if not context.get("skipped"):
                        logger.info(
                            "prediction context refresh complete: fixtures=%s h2h=%s injuries=%s",
                            context["fixtures"],
                            context["h2h"],
                            context["injuries"],
                        )
                except Exception:
                    logger.exception("prediction context refresh failed")

            sleep_until(min(next_live, next_schedule))
    finally:
        remove_pid()
        logger.info("daemon stopped")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logging.getLogger(__name__).error("daemon failed: %s", exc)
        remove_pid()
        sys.exit(1)
