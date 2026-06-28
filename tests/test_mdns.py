"""The app advertises its own Bonjour name so family devices reach it at
http://saarthi.local:<port> without an IP or renaming the host machine.

These lock the pure record-building and the safety of the lifecycle calls. The
actual network broadcast is verified live (dns-sd / a phone), not here."""
from __future__ import annotations

from backend import mdns


def test_build_service_info_maps_hostname_to_ip():
    info = mdns._build_service_info("saarthi", "192.168.0.106", 5173)
    assert info.server == "saarthi.local."
    assert info.port == 5173
    assert info.parsed_addresses() == ["192.168.0.106"]
    assert info.type == "_http._tcp.local."
    assert info.name == "saarthi._http._tcp.local."


def test_build_service_info_honours_custom_name_and_port():
    info = mdns._build_service_info("moneybox", "10.0.0.5", 8000)
    assert info.server == "moneybox.local."
    assert info.port == 8000
    assert info.parsed_addresses() == ["10.0.0.5"]


def test_primary_lan_ip_is_non_loopback_or_none():
    ip = mdns._primary_lan_ip()
    assert ip is None or (ip.count(".") == 3 and not ip.startswith("127."))


def test_advertiser_stop_without_start_is_safe():
    # Shutdown must never raise just because advertising never started.
    mdns.MdnsAdvertiser("saarthi", 5173).stop()
