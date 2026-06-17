"""Gunicorn configuration for the K38 football Flask app."""

import multiprocessing
import os

bind = os.getenv("K38_FOOTBALL_BIND", "127.0.0.1:6789")
workers = int(os.getenv("K38_FOOTBALL_WORKERS", max(2, multiprocessing.cpu_count() * 2 + 1)))
threads = int(os.getenv("K38_FOOTBALL_THREADS", 2))
timeout = int(os.getenv("K38_FOOTBALL_GUNICORN_TIMEOUT", 60))
graceful_timeout = int(os.getenv("K38_FOOTBALL_GUNICORN_GRACEFUL_TIMEOUT", 30))
accesslog = os.getenv("K38_FOOTBALL_ACCESS_LOG", "-")
errorlog = os.getenv("K38_FOOTBALL_ERROR_LOG", "-")
loglevel = os.getenv("K38_FOOTBALL_LOG_LEVEL", "info")
preload_app = True
