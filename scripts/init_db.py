#!/usr/bin/env python3
"""
scripts/init_db.py
──────────────────
Initialise the AtlasFX database and verify the project structure.

Run this once after cloning or setting up a new environment.

Usage:
    python scripts/init_db.py
"""

import sys
from pathlib import Path

# Ensure project root is in path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings
from data.database import init_db, verify_db
from logs.logger import configure_logging, get_logger


def check_env() -> bool:
    """Check that required directories and .env file exist."""
    log = get_logger("init")
    issues = []

    if not (PROJECT_ROOT / ".env").exists():
        issues.append(
            ".env file not found. Copy .env.example to .env and fill in your values."
        )

    required_dirs = [
        "config", "data", "data/historical", "data/live", "data/news",
        "strategies", "indicators", "backtesting", "risk", "broker",
        "execution", "paper_trading", "live_trading", "journal",
        "analytics", "dashboard", "notifications", "logs", "tests", "scripts",
    ]
    for d in required_dirs:
        path = PROJECT_ROOT / d
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
            log.info("directory_created", path=str(path))

    if issues:
        for issue in issues:
            log.warning("setup_issue", message=issue)
        return False

    return True


def main() -> None:
    configure_logging(log_level="INFO", environment="development")
    log = get_logger("init")

    log.info("atlasfx_init_start", version="0.1.0")

    # Check environment
    env_ok = check_env()
    if not env_ok:
        log.warning(
            "environment_warnings",
            note="Proceeding with defaults — see warnings above",
        )

    # Initialise database
    log.info("initialising_database", path=str(settings.db_path))
    init_db()

    # Verify
    ok = verify_db()
    if ok:
        log.info("database_ready", path=str(settings.db_path))
    else:
        log.error("database_verification_failed")
        sys.exit(1)

    log.info("atlasfx_init_complete", status="ready")
    print("\n✓ AtlasFX database initialised successfully.")
    print(f"  DB path: {settings.db_path}")
    print(f"  Environment: {settings.environment.value}")
    print("\nNext step: python scripts/download_data.py --help\n")


if __name__ == "__main__":
    main()
