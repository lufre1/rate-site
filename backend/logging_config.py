"""Logging for the backend.

Everything goes to stdout: Docker's json-file driver is the sink, and
/etc/docker/daemon.json caps it at 10m x 5 with compression (added 2026-09-01 --
before that it was unbounded, and the backend alone produced ~255 KB per two
minutes of browsing). There is no log file and no log shipper on this host,
deliberately.

Before this module, main.py contained zero `try`, zero `except` and no
`@app.exception_handler`, so every 500 was a traceback that went nowhere.

`request_id` is a ContextVar rather than a parameter, so every line emitted while
handling a request -- including tracebacks from library code -- carries the id
without any call site knowing about it. Every route in main.py is a sync `def`
and therefore runs on the anyio worker thread pool; ContextVars propagate into
those threads, so this works there too.
"""
import contextvars
import logging
import os
import sys

request_id_var = contextvars.ContextVar("request_id", default="-")

_configured = False


class _RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = request_id_var.get()
        return True


def configure_logging():
    """Idempotent -- main.py, run_scraper.py and the tests may all call it."""
    global _configured
    if _configured:
        return
    _configured = True

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        fmt="%(asctime)s %(levelname)-7s %(name)s rid=%(request_id)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
    ))
    handler.addFilter(_RequestIdFilter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())

    # Uvicorn installs its own handlers with its own format. Strip them and let
    # its records propagate to the root handler, or every line appears twice.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True

    # main.py's request_context middleware already logs every request with the
    # method, path, status, duration AND the request id. Leaving uvicorn's own
    # access log at INFO too means two lines per request -- double the volume
    # into a log that /etc/docker/daemon.json caps at 10m x 5.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    # SQLAlchemy at INFO echoes every statement. Never on this box.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
