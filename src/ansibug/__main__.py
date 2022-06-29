#!/usr/bin/env python
# -*- coding: utf-8 -*-
# PYTHON_ARGCOMPLETE_OK

# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys
import typing as t

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
        "python -m ansibug 1234 -- main.yml my-hosts -i inventory.ini -e 'key=value'",
    )

    parser.add_argument(
        "listener",
        nargs=1,
        type=str,
        help="The hostname:port to listen on for the DAP exchanges. The value is in the format [host]:port with the "
        "default host being localhost. Specify just a port number to listen on localhost, or specify a hostname:port "
        "to bind the listener on a specific address for external connections",
    )

    parser.add_argument(
        "--wait-for-client",
        action="store_true",
        help="Wait for the client to connect before continuing.",
    )

    if argcomplete:
        argcomplete.autocomplete(parser)

    parsed_args, playbook_args = parser.parse_known_args(args)
    if playbook_args and playbook_args[0] == "--":
        del playbook_args[0]

    playbook_args.insert(0, "ansible-playbook")

    return parsed_args, playbook_args


def main() -> None:
    args, playbook_args = parse_args(sys.argv[1:])

    addr = args.listener[0]
    if ":" in addr:
        hostname, port = addr.split(":", 2)

    else:
        hostname = "127.0.0.1"
        port = addr

    new_environ = os.environ.copy()
    new_environ["ANSIBUG_HOSTNAME"] = hostname
    new_environ["ANSIBUG_PORT"] = port

    # Env vars override settings in the ansible.cfg, figure out a better way
    # to inject our collection, callback, and strategy plugin
    collections_path = new_environ.get("ANSIBLE_COLLECTIONS_PATHS", "").split(os.pathsep)
    collections_path.insert(0, str(pathlib.Path(__file__).parent))
    new_environ["ANSIBLE_COLLECTIONS_PATHS"] = os.pathsep.join(collections_path)

    enabled_callbacks = new_environ.get("ANSIBLE_CALLBACKS_ENABLED", "").split(",")
    enabled_callbacks.insert(0, "ansibug.dap.debug")
    new_environ["ANSIBLE_CALLBACKS_ENABLED"] = ",".join(enabled_callbacks)

    new_environ["ANSIBLE_STRATEGY"] = "ansibug.dap.debug"

    proc = subprocess.run(
        playbook_args,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=new_environ,
    )
    sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
