#!/usr/bin/env python
# -*- coding: utf-8 -*-
# PYTHON_ARGCOMPLETE_OK

# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import argparse
import sys
import typing as t

from ._listener import listen

try:
    import argcomplete
except ImportError:
    argcomplete = None


def parse_args(
    args: t.List[str],
) -> t.Tuple[argparse.Namespace, t.List[str]]:
    parser = argparse.ArgumentParser(
        prog="python -m ansibug",
        description="Ansible Debug Adapter Protocol Launcher (DAP). This is used as a stub to launch Ansible "
        "playbooks that run with the DAP plugins for interactive debugging. The DAP messages are exchanged with the "
        "socket that is created by this process. Any remaining arguments to provide with ansible-playbook should be "
        "provided after --, e.g. "
        "python -m ansibug 1234 --playbook main.yml -- my-hosts -i inventory.ini -e 'key=value'",
    )

    parser.add_argument(
        "listener",
        nargs=1,
        type=str,
        help="The hostname:port to connect to listener on for the DAP exchanges. The value is in the format "
        "[host]:port with the default host being localhost. Specify just a port number to listen on localhost, "
        "or specify a hostname:port to bind the listener on a specific address for external connections",
    )

    parser.add_argument(
        "--wait-for-client",
        action="store_true",
        help="Wait for the client to connect before continuing.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)

    mode.add_argument(
        "--pid",
        nargs=1,
        type=int,
        help="The running ansible-playbook process to attach to.",
    )

    mode.add_argument(
        "--playbook",
        nargs=1,
        type=str,
        help="The Ansible playbook to debug that is passed to ansible-playbook",
    )

    if argcomplete:
        argcomplete.autocomplete(parser)

    parsed_args, playbook_args = parser.parse_known_args(args)
    if playbook_args and playbook_args[0] == "--":
        del playbook_args[0]

    return parsed_args, playbook_args


def main() -> None:
    args, playbook_args = parse_args(sys.argv[1:])

    addr = args.listener[0]
    if ":" in addr:
        hostname, port = addr.split(":", 2)

    else:
        hostname = "127.0.0.1"
        port = addr

    listen(hostname, port, args.wait_for_client)

    print(args)
    print(f"Playbook args: {playbook_args}")


if __name__ == "__main__":
    main()
