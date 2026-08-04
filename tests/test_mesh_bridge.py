import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge"))

from mesh_bridge import BROADCAST_ADDR, parse_recipient, resolve_destination, route_message


class FakeInterface:
    def __init__(self):
        self.sent = []

    def sendText(self, text, destinationId):
        self.sent.append((text, destinationId))


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
