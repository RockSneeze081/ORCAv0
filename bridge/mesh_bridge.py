#!/usr/bin/env python3
"""NUNU -> Meshtastic routing bridge.

Takes a decoded NUNU plaintext payload and injects it into a Meshtastic
mesh via the official `meshtastic` Python API. Routing rule (AGENTS.md):

    "@alias rest of message"   -> direct message to the aliased node
    "@!a1b2c3d4 rest"          -> direct message to that raw node id
    "rest of message"          -> broadcast to the whole mesh

A Meshtastic node-id string ("!xxxxxxxx") or hex literal ("0x...") is
passed straight through to sendText() -- meshtastic's own interface
already parses that format, no need to duplicate it here.

Any object exposing a Meshtastic-compatible `.sendText(text,
destinationId=...)` can be passed in as `interface`, so routing can be
unit tested without a real radio attached. For real use:

    from meshtastic.serial_interface import SerialInterface
    interface = SerialInterface()  # autodetects the Heltec/T-Beam on USB
"""

import json
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("orca.mesh_bridge")

BROADCAST_ADDR = "^all"  # meshtastic.mesh_interface.BROADCAST_ADDR
DEFAULT_ALIAS_STORE = Path(__file__).resolve().parent / "alias_store.json"


def load_aliases(path: Path = DEFAULT_ALIAS_STORE) -> dict:
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def save_aliases(aliases: dict, path: Path = DEFAULT_ALIAS_STORE) -> None:
    """Write the alias table back out, sorted for a stable, reviewable diff."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(dict(sorted(aliases.items())), f, indent=2)
        f.write("\n")


def parse_recipient(text: str) -> tuple[Optional[str], str]:
    """Split "@target rest" into (target, rest); (None, text) if no @-prefix.

    `target` is returned exactly as typed (minus the @) -- deciding
    whether it's an alias or a raw node id happens in resolve_destination.
    """
    stripped = text.strip()
    if not stripped.startswith("@"):
        return None, stripped
    token, _, rest = stripped.partition(" ")
    return token[1:], rest.strip()


def resolve_destination(target: str, aliases: dict) -> Optional[str]:
    """Resolve an @target token to a Meshtastic destinationId, or None."""
    if target.startswith("!") or target.startswith("0x"):
        return target
    return aliases.get(target)


def _safe_send(interface, message: str, destination: str, label: str) -> bool:
    """Call interface.sendText, but don't let a bad destination take the
    whole pipeline down with it.

    destination can come straight from a NUNU message's "@target" text --
    i.e. from whoever is transmitting, not from us. The real
    meshtastic.SerialInterface treats any string >=8 chars as a hex node
    id and does `int(destinationId[-8:], 16)` with no guard at all: a
    message like "@!zzzzzzzz hi" reaches that unguarded parse and raises
    ValueError. Some of its other invalid-destination branches call
    meshtastic's own our_exit(), which is sys.exit() under the hood --
    that's SystemExit, not Exception, so it has to be caught explicitly
    or it kills the whole process (the live-capture loop, or an offline
    batch partway through). Both are real for a protocol decoded from
    RF: malformed content here is normal, not a rare edge case, whether
    from noise or someone deliberately sending garbage.
    """
    try:
        interface.sendText(message, destinationId=destination)
    except (Exception, SystemExit) as exc:
        logger.warning("send to %s (%s) failed, dropping: %s", label, destination, exc)
        return False
    return True


def route_message(text: str, interface, aliases: Optional[dict] = None) -> bool:
    """Route one decoded NUNU message onto the Meshtastic mesh.

    Returns True if the message was handed to the interface successfully,
    False if it was dropped (empty body, unresolved alias) or the send
    itself failed. An unresolved @alias is dropped rather than silently
    broadcast -- a message addressed to someone specific shouldn't leak
    to the whole mesh just because the alias table is stale or has a typo.
    """
    if aliases is None:
        aliases = load_aliases()

    target, message = parse_recipient(text)
    if not message:
        logger.warning("empty message body, dropping: %r", text)
        return False

    if target is None:
        sent = _safe_send(interface, message, BROADCAST_ADDR, "broadcast")
        if sent:
            logger.info("broadcast: %r", message)
        return sent

    destination = resolve_destination(target, aliases)
    if destination is None:
        logger.warning("unknown alias %r, dropping message: %r", target, text)
        return False

    sent = _safe_send(interface, message, destination, target)
    if sent:
        logger.info("direct to %s (%s): %r", target, destination, message)
    return sent
