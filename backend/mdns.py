"""Advertise the app on the local network under its OWN mDNS/Bonjour name.

The app publishes `<name>.local` (default `saarthi.local`) -> this machine's LAN
IP, so family devices reach it at e.g. http://saarthi.local:5173 without anyone
knowing an IP or renaming the host machine. The name belongs to the app, not the
computer: move the app to another machine and the name moves with it. The
advertisement lives for the app's lifetime (registered on startup, withdrawn on
shutdown).

Best-effort: if the network can't be probed or zeroconf isn't installed, the app
logs and runs without mDNS rather than failing to boot.
"""
from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)

try:
    from zeroconf import ServiceInfo, Zeroconf

    _HAVE_ZEROCONF = True
except ImportError:  # pragma: no cover - only when the optional dep is absent
    _HAVE_ZEROCONF = False

_SERVICE_TYPE = "_http._tcp.local."


def _primary_lan_ip() -> str | None:
    """This machine's primary LAN IPv4, or None if it can't be determined.

    Opens a UDP socket toward a public address to learn which local interface the
    OS would route through; no packet is actually sent. Loopback is treated as
    "no LAN" so we never advertise an unreachable address."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def _build_service_info(name: str, ip: str, port: int) -> "ServiceInfo":
    """The Bonjour record set: an `_http._tcp` service whose host record maps
    `<name>.local` to `ip`, so the hostname resolves for any port (the port in
    the record is just the advertised http service)."""
    return ServiceInfo(
        type_=_SERVICE_TYPE,
        name=f"{name}.{_SERVICE_TYPE}",
        addresses=[socket.inet_aton(ip)],
        port=port,
        server=f"{name}.local.",
    )


class MdnsAdvertiser:
    """Owns the lifetime of one published mDNS name. One start per stop."""

    def __init__(self, name: str, port: int) -> None:
        self._name = name
        self._port = port
        self._zc: "Zeroconf | None" = None
        self._info: "ServiceInfo | None" = None

    def start(self) -> bool:
        """Publish `<name>.local`. Returns True when advertising, False when it
        couldn't (no zeroconf, no LAN IP). Blocking (registration probes the
        network for name conflicts) — call it off the event loop."""
        if not _HAVE_ZEROCONF:
            logger.warning("mDNS: zeroconf not installed; not advertising")
            return False
        ip = _primary_lan_ip()
        if ip is None:
            logger.warning("mDNS: no LAN IP found; not advertising")
            return False
        info = _build_service_info(self._name, ip, self._port)
        zc = Zeroconf()
        zc.register_service(info)
        self._zc, self._info = zc, info
        logger.info(
            "mDNS: advertising http://%s.local:%d -> %s", self._name, self._port, ip
        )
        return True

    def stop(self) -> None:
        """Withdraw the name and release the responder. Safe to call even if
        start was never called or returned False."""
        if self._zc is not None and self._info is not None:
            try:
                self._zc.unregister_service(self._info)
            finally:
                self._zc.close()
        self._zc = None
        self._info = None
