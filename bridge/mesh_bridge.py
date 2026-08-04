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


def route_message(text: str, interface, aliases: Optional[dict] = None) -> bool:
    """Route one decoded NUNU message onto the Meshtastic mesh.

    Returns True if a send was attempted, False if it was dropped. An
    unresolved @alias is dropped rather than silently broadcast -- a
    message addressed to someone specific shouldn't leak to the whole
    mesh just because the alias table is stale or has a typo.
    """
    if aliases is None:
        aliases = load_aliases()

    target, message = parse_recipient(text)
    if not message:
        logger.warning("empty message body, dropping: %r", text)
        return False

    if target is None:
        interface.sendText(message, destinationId=BROADCAST_ADDR)
        logger.info("broadcast: %r", message)
        return True

    destination = resolve_destination(target, aliases)
    if destination is None:
        logger.warning("unknown alias %r, dropping message: %r", target, text)
        return False

    interface.sendText(message, destinationId=destination)
    logger.info("direct to %s (%s): %r", target, destination, message)
    return True
