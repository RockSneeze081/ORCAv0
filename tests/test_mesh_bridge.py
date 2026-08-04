import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge"))

from mesh_bridge import (
    BROADCAST_ADDR,
    load_aliases,
    parse_recipient,
    resolve_destination,
    route_message,
    save_aliases,
)


class FakeInterface:
    def __init__(self):
        self.sent = []

    def sendText(self, text, destinationId):
        self.sent.append((text, destinationId))


class RaisingInterface:
    """Simulates a real meshtastic interface choking on a bad destinationId.

    meshtastic.MeshInterface._sendPacket does `int(destinationId[-8:], 16)`
    for any >=8-char string with no try/except -- ValueError on garbage
    hex. Some of its other failure branches call meshtastic's own
    our_exit(), which is sys.exit() under the hood -- SystemExit, not
    Exception. Both are simulated here since _safe_send has to catch both.
    """

    def __init__(self, exc):
        self._exc = exc

    def sendText(self, text, destinationId):
        raise self._exc


def test_parse_recipient_no_prefix():
    assert parse_recipient("hello mesh") == (None, "hello mesh")


def test_parse_recipient_alias():
    assert parse_recipient("@ea3jhl on the summit") == ("ea3jhl", "on the summit")


def test_parse_recipient_strips_whitespace():
    assert parse_recipient("  @ea3jhl   hi  ") == ("ea3jhl", "hi")


def test_resolve_destination_raw_nodeid_passthrough():
    assert resolve_destination("!a1b2c3d4", {}) == "!a1b2c3d4"
    assert resolve_destination("0x12345678", {}) == "0x12345678"


def test_resolve_destination_alias_lookup():
    aliases = {"ea3jhl": "!a1b2c3d4"}
    assert resolve_destination("ea3jhl", aliases) == "!a1b2c3d4"
    assert resolve_destination("unknown", aliases) is None


def test_route_message_broadcast():
    iface = FakeInterface()
    assert route_message("node1 online", iface, aliases={}) is True
    assert iface.sent == [("node1 online", BROADCAST_ADDR)]


def test_route_message_direct_via_alias():
    iface = FakeInterface()
    aliases = {"ea3jhl": "!a1b2c3d4"}
    assert route_message("@ea3jhl summit activated", iface, aliases) is True
    assert iface.sent == [("summit activated", "!a1b2c3d4")]


def test_route_message_direct_via_raw_nodeid():
    iface = FakeInterface()
    assert route_message("@!a1b2c3d4 hi", iface, aliases={}) is True
    assert iface.sent == [("hi", "!a1b2c3d4")]


def test_route_message_unknown_alias_dropped():
    iface = FakeInterface()
    assert route_message("@ghost hello?", iface, aliases={}) is False
    assert iface.sent == []


def test_route_message_empty_body_dropped():
    iface = FakeInterface()
    assert route_message("@ea3jhl", iface, aliases={"ea3jhl": "!a1b2c3d4"}) is False
    assert iface.sent == []


def test_route_message_broadcast_survives_value_error():
    """A malformed "@!<garbage>" destination is attacker/sender-controlled
    -- it comes straight from the transmitted NUNU message -- so this has
    to degrade to "dropped", not crash the caller's loop."""
    iface = RaisingInterface(ValueError("invalid literal for int() with base 16: 'zzzzzzzz'"))
    assert route_message("hello mesh", iface, aliases={}) is False


def test_route_message_direct_survives_system_exit():
    """meshtastic's our_exit() helper is sys.exit() under the hood --
    SystemExit, not Exception -- so it has to be caught explicitly or it
    kills the whole process, not just this one send."""
    iface = RaisingInterface(SystemExit(1))
    aliases = {"ea3jhl": "!zzzzzzzz"}  # a bad value, e.g. from a typo'd manage_aliases.py add
    assert route_message("@ea3jhl hello", iface, aliases) is False


def test_route_message_bad_raw_nodeid_survives_value_error():
    iface = RaisingInterface(ValueError("bad hex"))
    assert route_message("@!zzzzzzzz message", iface, aliases={}) is False


def test_load_aliases_missing_file_returns_empty_dict(tmp_path):
    assert load_aliases(tmp_path / "does_not_exist.json") == {}


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "alias_store.json"
    aliases = {"ea3jhl": "!a1b2c3d4", "repeater1": "!deadbeef"}

    save_aliases(aliases, path)

    assert load_aliases(path) == aliases


def test_save_aliases_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "dir" / "alias_store.json"

    save_aliases({"x": "!11111111"}, path)

    assert path.exists()
    assert load_aliases(path) == {"x": "!11111111"}


def test_save_aliases_output_is_sorted_and_stable(tmp_path):
    path = tmp_path / "alias_store.json"

    save_aliases({"zulu": "!2", "alpha": "!1"}, path)

    assert list(json.loads(path.read_text()).keys()) == ["alpha", "zulu"]
