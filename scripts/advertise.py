#!/usr/bin/env python3
"""Announce `saarthi.local` on the home network from the HOST machine.

The app already advertises its own Bonjour name when run directly (see
`backend/mdns.py`). Under Docker that advertisement can't escape the container's
network, so family devices can't resolve `saarthi.local`. Run this small script
on the host, alongside `docker compose up`, and the host does the announcing
instead — Docker's published port (5173) still forwards the traffic inward.

Usage (from the repo root, so `backend` is importable):
    python -m scripts.advertise            # saarthi.local, port 5173
    python -m scripts.advertise --name moneybox --port 8000

It runs in the foreground and keeps the name alive until you press Ctrl+C, then
withdraws it. Needs `zeroconf` installed on the host (`pip install zeroconf`).
"""
from __future__ import annotations

import argparse
import logging
import signal
import threading

from backend.config import settings
from backend.mdns import MdnsAdvertiser

try:
    from zeroconf import NonUniqueNameException
except ImportError:  # pragma: no cover - start() returns False before this matters
    class NonUniqueNameException(Exception):  # type: ignore[no-redef]
        """Placeholder when zeroconf is absent; never actually raised."""

logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Resolve the advertised name and port, defaulting to the app's config so
    the host announcement matches what the app would publish itself."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.advertise",
        description="Announce <name>.local -> this host on the LAN (for Docker).",
    )
    parser.add_argument("--name", default=settings.mdns_name)
    parser.add_argument("--port", type=int, default=settings.mdns_port)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = parse_args(argv)

    advertiser = MdnsAdvertiser(args.name, args.port)
    try:
        started = advertiser.start()
    except NonUniqueNameException:
        logger.info(
            "%s.local is already being announced on this network (the app may be "
            "running directly, or another copy of this script is open). It is "
            "already reachable — nothing to do here.",
            args.name,
        )
        return 0
    if not started:
        logger.error(
            "Could not advertise %s.local (no LAN IP, or zeroconf not installed). "
            "Install it with `pip install zeroconf` and ensure you are on a network.",
            args.name,
        )
        return 1

    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    logger.info("Open http://%s.local:%d on any device. Press Ctrl+C to stop.",
                args.name, args.port)
    try:
        stop.wait()
    finally:
        advertiser.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
