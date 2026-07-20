#!/usr/bin/env python3
"""
Flights Overhead — Portland / Vancouver, OR desk display.

Usage:
  python main.py                 # live OpenSky data
  python main.py --simulate      # fake data, no network needed
  python main.py --fullscreen    # fullscreen (used by the systemd service)
  SIMULATE=true python main.py   # env-var alternative
"""

import sys
import os
import argparse
import threading
import time
import logging
import logging.handlers

# Parse args before importing fetcher — SIMULATE is read at import time.
_parser = argparse.ArgumentParser(description="Flights Overhead display")
_parser.add_argument("--simulate",   action="store_true", help="Use fake flight data")
_parser.add_argument("--fullscreen", action="store_true", help="Run fullscreen (Pi)")
_parser.add_argument(
    "--interval", type=int, default=45,
    metavar="SEC", help="Refresh interval in seconds (default: 45)",
)
_args = _parser.parse_args()

if _args.simulate:
    os.environ["SIMULATE"] = "true"

# LOG_LEVEL=DEBUG shows per-card route rendering; INFO (default) shows route
# lookup outcomes (HTTP status, empty records, etc.) without the per-frame noise.
#
# Logs also go to logs/flights.log on disk, not just stdout/journal — Pi
# images typically run journald with volatile (tmpfs) storage, so
# journalctl history is wiped on every reboot and won't survive long enough
# to catch an intermittent crash.
_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(_LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            os.path.join(_LOG_DIR, "flights.log"),
            maxBytes=1_000_000, backupCount=3,
        ),
    ],
)
logger = logging.getLogger(__name__)

# Load .env before any project imports — enrichment.py captures creds at import time.
def _load_dotenv(path: str = ".env") -> None:
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())
    except FileNotFoundError:
        pass

_load_dotenv()

import pygame
from fetcher import fetch_flights, SIMULATE
from display import FlightDisplay


def _fetch_loop(display: FlightDisplay, interval: int, stop: threading.Event) -> None:
    """Background thread: refresh flight data on a fixed interval."""
    while not stop.is_set():
        stop.wait(interval)
        if stop.is_set():
            break
        try:
            flights = fetch_flights()
            display.update(flights)
        except Exception as exc:
            logger.exception("fetch loop: refresh failed")
            display.update([], error=str(exc))


def main() -> None:
    display = FlightDisplay(fullscreen=_args.fullscreen)

    # Initial fetch (blocking, so we show data immediately on startup)
    try:
        display.update(fetch_flights())
    except Exception as exc:
        logger.exception("initial fetch failed")
        display.update([], error=str(exc))

    stop = threading.Event()
    worker = threading.Thread(
        target=_fetch_loop,
        args=(display, _args.interval, stop),
        daemon=True,
    )
    worker.start()

    clock   = pygame.time.Clock()
    running = True
    try:
        while running:
            running = display.handle_events()
            display.draw()
            clock.tick(10)   # 10 fps is plenty
    except Exception:
        # Log the full traceback before we die so systemd's restart isn't
        # the only trace this crash leaves behind.
        logger.exception("main loop crashed — exiting so systemd can restart it")
        raise
    finally:
        stop.set()
        pygame.quit()

    sys.exit(0)


if __name__ == "__main__":
    main()
