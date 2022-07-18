#!/usr/bin/env python
# -*- coding: utf-8 -*-
# PYTHON_ARGCOMPLETE_OK

# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import argparse
import os
import pathlib
import re
import sys
import typing as t

from ._da_server import start_dap
from ._launch import launch

try:
    import argcomplete
except ImportError:
    argcomplete = None


ADDR_PATTERN = re.compile(r"(?:(?P<hostname>.+):)?(?P<port>\d+)")


def parse_args(
    args: t.List[str],
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m ansibug",
        description="Ansible Debug Adapter Protocol Launcher (DAP).",
    )

    action = parser.add_subparsers(
        dest="action",
        required=True,
        help="The action for ansibug to perform",
    )

    def parse_addr(addr: str) -> t.Tuple[str, int]:
        if m := ADDR_PATTERN.match(addr):
            hostname = m.group("hostname") or "127.0.0.1"
            port = int(m.group("port"))

            return hostname, port

        else:
            raise argparse.ArgumentTypeError("listener must be in the format [host:]port")

    # DAP

    action.add_parser(
        "dap",
        description="Start a new Debug Adapter Protocol process for a client "
        "to communicate with over stdin and stdout. This process is in "
        "charge of interacting with the DAP client and coordinating the debug "
        "session. All relevant debug information is passed in through stdin "
        "using the DAP protocol messages.",
        help="Start an executable Debug Adapter Protocol process",
    )

    # Launch

    launch = action.add_parser(
        "launch",
        description="Starts a new ansible-playbook process with the arguments "
        "specified. This new process will have the required ansibug plugins "
        "enabled in order for 'ansibug dap ...' to communicate with. Use "
        "--connect to have the process connect to an existing socket or use "
        "--listen to have the process listen on a port and wait for the dap "
        "server to connect to it.",
        help="Launch ansible-playbook process with debug enabled",
    )

    launch_mode = launch.add_mutually_exclusive_group(required=True)

    launch_mode.add_argument(
        "--connect",
        action="store",
        type=parse_addr,
        help="Have the ansible-playbook process connect to the socket addr "
        "that is bound to the DAP server. The addr is in the form [host:]port "
        "where host defaults to 127.0.0.1 if not specified.",
    )

    launch_mode.add_argument(
        "--listen",
        action="store",
        type=parse_addr,
        help="Have the ansible-playbook process bind to the socket addr "
        "specified. The addr is in the form [host:]port where host defaults "
        "to 127.0.0.1 if not specified.",
    )

    launch.add_argument(
        "--wait-for-client",
        action="store_true",
        help="Wait for the client to connect and send the configurationDone request before starting the playbook.",
    )

    launch.add_argument(
        "--log-file",
        action="store",
        type=lambda p: pathlib.Path(os.path.expanduser(os.path.expandvars(p))),
        help="Enable file logging to the file at this path for the ansibug debuggee logger.",
    )

    launch.add_argument(
        "--log-level",
        action="store",
        choices=["info", "debug", "warning", "error"],
        default="info",
        type=str,
        help="Set the logging filter level of the ansibug debuggee logger when --log-file is set. Defaults to info",
    )

    launch.add_argument(
        "playbook_args",
        nargs=argparse.REMAINDER,
        help="Arguments to use when launching ansible-playbook.",
    )

    if argcomplete:
        argcomplete.autocomplete(parser)

    return parser.parse_args(args)


def main() -> None:
    args = parse_args(sys.argv[1:])

    if args.action == "dap":
        start_dap()

    else:
        import os

        print(os.getcwd())
        mode: t.Literal["connect", "listen"]
        addr: t.Any
        if args.listen:
            mode = "listen"
            addr = args.listen
        else:
            mode = "connect"
            addr = args.connect

        rc = launch(
            args.playbook_args,
            mode=mode,
            addr=f"{addr[0]}:{addr[1]}",
            wait_for_client=args.wait_for_client,
            log_file=args.log_file,
            log_level=args.log_level,
        )
        sys.exit(rc)


if __name__ == "__main__":
    main()
