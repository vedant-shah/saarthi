"""The standalone host advertiser (`scripts/advertise`) announces saarthi.local
on the LAN from the host machine, for the Docker setup where the in-container app
can't reach the home network itself.

These lock the argument resolution and the no-LAN failure path. The live network
broadcast is verified by hand (dns-sd / a phone), not here — same as test_mdns."""
from __future__ import annotations

from backend.config import settings
from scripts import advertise


def test_parse_args_defaults_to_settings():
    args = advertise.parse_args([])
    assert args.name == settings.mdns_name
    assert args.port == settings.mdns_port


def test_parse_args_honours_overrides():
    args = advertise.parse_args(["--name", "moneybox", "--port", "8000"])
    assert args.name == "moneybox"
    assert args.port == 8000


def test_main_returns_1_when_advertising_unavailable(monkeypatch):
    # No LAN / no zeroconf -> start() is False -> exit non-zero without blocking.
    class _FakeAdvertiser:
        def __init__(self, name: str, port: int) -> None:
            self.stopped = False

        def start(self) -> bool:
            return False

        def stop(self) -> None:
            self.stopped = True

    monkeypatch.setattr(advertise, "MdnsAdvertiser", _FakeAdvertiser)
    assert advertise.main([]) == 1


def test_main_handles_name_already_taken(monkeypatch):
    # The name is already being announced (app running directly, or a second
    # copy of this script) -> explain and exit cleanly, never a raw traceback.
    from zeroconf import NonUniqueNameException

    class _ClashingAdvertiser:
        def __init__(self, name: str, port: int) -> None:
            pass

        def start(self) -> bool:
            raise NonUniqueNameException

        def stop(self) -> None:
            pass

    monkeypatch.setattr(advertise, "MdnsAdvertiser", _ClashingAdvertiser)
    assert advertise.main([]) == 0
