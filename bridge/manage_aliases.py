#!/usr/bin/env python3
"""Manage bridge/alias_store.json without hand-editing JSON.

Usage:
    python bridge/manage_aliases.py add ea3jhl '!a1b2c3d4'
    python bridge/manage_aliases.py list
    python bridge/manage_aliases.py remove ea3jhl
"""

import argparse
import sys
from pathlib import Path

from mesh_bridge import DEFAULT_ALIAS_STORE, load_aliases, save_aliases


def cmd_add(args) -> int:
    aliases = load_aliases(args.store)
    if not (args.node_id.startswith("!") or args.node_id.startswith("0x")):
        print(
            f"warning: {args.node_id!r} doesn't look like a Meshtastic node id "
            "(usually starts with '!' or '0x') -- storing it anyway",
            file=sys.stderr,
        )
    existing = aliases.get(args.name)
    aliases[args.name] = args.node_id
    save_aliases(aliases, args.store)
    if existing is not None and existing != args.node_id:
        print(f"updated {args.name}: {existing} -> {args.node_id}")
    else:
        print(f"added {args.name} -> {args.node_id}")
    return 0


def cmd_remove(args) -> int:
    aliases = load_aliases(args.store)
    if args.name not in aliases:
        print(f"no such alias: {args.name}", file=sys.stderr)
        return 1
    del aliases[args.name]
    save_aliases(aliases, args.store)
    print(f"removed {args.name}")
    return 0


def cmd_list(args) -> int:
    aliases = load_aliases(args.store)
    if not aliases:
        print(f"(no aliases in {args.store})")
        return 0
    width = max(len(name) for name in aliases)
    for name, node_id in sorted(aliases.items()):
        print(f"{name:<{width}}  {node_id}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--store", type=Path, default=DEFAULT_ALIAS_STORE, help="path to alias_store.json"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add or update an alias")
    p_add.add_argument("name", help="alias name, as used in '@name' NUNU messages")
    p_add.add_argument("node_id", help="Meshtastic node id, e.g. !a1b2c3d4")
    p_add.set_defaults(func=cmd_add)

    p_remove = sub.add_parser("remove", help="remove an alias")
    p_remove.add_argument("name")
    p_remove.set_defaults(func=cmd_remove)

    p_list = sub.add_parser("list", help="list all aliases")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
