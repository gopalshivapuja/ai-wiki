"""Pre-flight checks run before the app serves traffic.

Two failure modes this guards against, both specific to a real deployment:

* The container starts before the database accepts connections. On Railway the app and the
  Postgres service come up together and the private network takes a few seconds, so the very
  first connect routinely fails.
* Secrets left at their published defaults. The app would otherwise boot happily and sign
  tokens with a value anyone can read in this repository.
"""

from __future__ import annotations

import logging
import os
import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "dev-secret-change-in-production"
DEFAULT_ADMIN_PASSWORD = "changeme"

DB_CONNECT_ATTEMPTS = int(os.environ.get("DB_CONNECT_ATTEMPTS", "12"))
DB_CONNECT_MAX_BACKOFF = float(os.environ.get("DB_CONNECT_MAX_BACKOFF", "5"))


class StartupError(RuntimeError):
    """Refusing to start. The message is intended for the deploy log."""


def is_production() -> bool:
    """True when this looks like a real deployment rather than local development.

    Keyed on the database: a hosted Postgres means production, SQLite or a local host means
    someone is developing and should not be forced to set secrets.
    """
    url = os.environ.get("DATABASE_URL", "")
    if not url or url.startswith("sqlite"):
        return False
    return not any(host in url for host in ("localhost", "127.0.0.1", "@db:", "@postgres:"))


def check_secrets() -> None:
    """Warn about default credentials; refuse to start with a default JWT secret in prod."""
    prod = is_production()

    if os.environ.get("JWT_SECRET", DEFAULT_JWT_SECRET) == DEFAULT_JWT_SECRET:
        if prod:
            raise StartupError(
                "JWT_SECRET is unset or still the built-in default, which is published in "
                "this repository — anyone could forge an admin token. Set it to a random "
                "value (openssl rand -hex 32) and redeploy."
            )
        logger.warning(
            "JWT_SECRET is the built-in default. Fine for local development; set a real "
            "secret before deploying."
        )

    if os.environ.get("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD) == DEFAULT_ADMIN_PASSWORD and prod:
        # A warning, not a failure: locking someone out of their own deployment over this
        # would be worse than the risk.
        logger.warning(
            "ADMIN_PASSWORD is still '%s'. Anyone can log in — change it in the environment "
            "and redeploy; the password is re-hashed on boot.",
            DEFAULT_ADMIN_PASSWORD,
        )


def wait_for_database(attempts: int = DB_CONNECT_ATTEMPTS) -> None:
    """Block until the database answers, with bounded exponential backoff.

    Without this, a database that is not yet accepting connections makes the whole startup
    raise, uvicorn exit non-zero, and the platform burn one of its limited automatic
    restarts — for a condition that resolves itself in a few seconds.
    """
    from wiki_api.database import engine

    delay = 0.5
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            if attempt > 1:
                logger.info("Database reachable after %d attempts", attempt)
            return
        except SQLAlchemyError as exc:
            last_error = exc
            if attempt == attempts:
                break
            logger.warning(
                "Database not ready (attempt %d/%d), retrying in %.1fs: %s",
                attempt,
                attempts,
                delay,
                str(exc).splitlines()[0][:200],
            )
            time.sleep(delay)
            delay = min(delay * 2, DB_CONNECT_MAX_BACKOFF)

    raise StartupError(
        f"Could not reach the database after {attempts} attempts. Check that DATABASE_URL is "
        f"correct and the database service is running. Last error: {last_error}"
    )
