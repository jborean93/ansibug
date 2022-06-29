#!/usr/bin/env python
# -*- coding: utf-8 -*-
# PYTHON_ARGCOMPLETE_OK

# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import argparse
import asyncio
import os
import pathlib
import select
import socket
import subprocess
import sys
import typing as t

from ._server import get_pipe_path

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
        action="store",
        type=str,
        help="The hostname:port to listen on for the DAP exchanges. The value is in the format [host]:port with the "
        "default host being localhost. Specify just a port number to listen on localhost, or specify a hostname:port "
        "to bind the listener on a specific address for external connections",
    )

    parser.add_argument(
        "--pid",
        action="store",
        type=int,
        help="Attach to the running ansible-playbook process instead of launch. "
        "The remaining arguments will be ignored",
    )

    parser.add_argument(
        "--wait-for-client",
        action="store_true",
        help="Wait for the client to connect before continuing.",
    )

    parser.add_argument(
        "--timeout",
        action="store",
        type=int,
        default=10,
        help="Time to wait until the ansible-playbook has started and the debug pipe is ready.",
    )

    parser.add_argument(
        "--log-file",
        action="store",
        type=lambda p: pathlib.Path(os.path.expanduser(os.path.expandvars(p))).absolute(),
        help="If set, will log DAP background events to the path specified.",
    )

    parser.add_argument(
        "--log-level",
        action="store",
        type=str,
        default="info",
        choices=["info", "debug", "warning", "error"],
        help="The log level to use when logging entries",
    )

    parser.add_argument(
        "--log-format",
        action="store",
        type=str,
        default="%(asctime)s | %(filename)s:%(lineno)s %(funcName)s() %(message)s",
        help="The formatting to apply to the log entries",
    )

    if argcomplete:
        argcomplete.autocomplete(parser)

    parsed_args, playbook_args = parser.parse_known_args(args)
    if playbook_args and playbook_args[0] == "--":
        del playbook_args[0]

    playbook_args.insert(0, "ansible-playbook")

    return parsed_args, playbook_args


async def main() -> None:
    args, playbook_args = parse_args(sys.argv[1:])

    addr = args.listener
    if ":" in addr:
        hostname, port = addr.split(":", 2)

    else:
        hostname = "127.0.0.1"
        port = addr

    if args.pid:
        # If the PID is specified just try to connect to the DAP config pipe
        # in order to write the server addr info.
        attach_playbook(hostname, port, args.pid)

    else:
        # If the playbook + args are specified launch the new process and wait
        # for it to complete.
        sys.exit(
            launch_playbook(
                hostname,
                port,
                playbook_args,
                args.timeout,
                args.log_file,
                args.log_level,
                args.log_format,
            )
        )


def launch_playbook(
    hostname: str,
    port: int,
    args: t.List[str],
    timeout: int,
    log_file: t.Optional[pathlib.Path],
    log_level: str,
    log_format: str,
) -> int:
    """Launch a new ansible-playbook subprocess.

    Launches a new ansible-playbook subprocess with the ansibug debug adapter
    protocol plugins configured. This will wait for the process to start and
    send through the required server bind address the client wishes to connect
    to.

    Args:
        hostname: The hostname the Ansible process needs to bind to.
        port: The port the Ansible process needs to bind to.
        args: The arguments of the ansible-playbook process to run.
        timeout: The time to wait for the process to be ready to send the DAP
            info to.

    Returns:
        int: The return code of the process.
    """
    read_pipe, write_pipe = os.pipe()
    try:
        with open(read_pipe, mode="r") as read_fd:
            proc = ansible_playbook(
                args,
                write_pipe,
                log_file,
                log_level,
                log_format,
            )

            # Wait for the timeout period to be notified the DAP config pipe
            # has been creating and is waiting for further configuration.
            read_ready, _, _ = select.select([read_fd], [], [], timeout)
            if not read_ready:
                proc.terminate()
                raise TimeoutError("Timeout while waiting for ansible-playbook subprocess to be ready")

    finally:
        os.close(write_pipe)

    # Once the process has started, write the host:port addr for it to bind to.
    attach_playbook(hostname, port, proc.pid)

    return proc.wait()


def attach_playbook(
    hostname: str,
    port: int,
    pid: int,
) -> None:
    pipe_path = get_pipe_path(pid)

    if not os.path.exists(pipe_path):
        raise Exception(f"Cannot attach to {pid} as ansibug debug pipe does not exist")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(pipe_path)
        addr = f"{hostname}:{port}".encode()
        addr_length = len(addr).to_bytes(4, byteorder="little")
        data = bytearray().join([addr_length, addr])

        while data:
            bytes_sent = sock.send(data)
            data = data[bytes_sent:]


def ansible_playbook(
    args: t.List[str],
    write_pipe: int,
    log_file: t.Optional[pathlib.Path],
    log_level: str,
    log_format: str,
) -> subprocess.Popen:
    ansibug_path = pathlib.Path(__file__).parent
    new_environ = os.environ.copy()
    new_environ["ANSIBUG_WRITE_FD"] = str(write_pipe)
    if log_file:
        new_environ["ANSIBUG_LOG_FILE"] = str(log_file)
        new_environ["ANSIBUG_LOG_LEVEL"] = log_level
        new_environ["ANSIBUG_LOG_FORMAT"] = log_format

    python_path = new_environ.get("PYTHONPATH", "").split(os.pathsep)
    python_path.insert(0, str(ansibug_path.parent))
    new_environ["PYTHONPATH"] = os.pathsep.join(python_path)

    # Env vars override settings in the ansible.cfg, figure out a better way
    # to inject our collection, callback, and strategy plugin
    collections_path = new_environ.get("ANSIBLE_COLLECTIONS_PATHS", "").split(os.pathsep)
    collections_path.insert(0, str(ansibug_path))
    new_environ["ANSIBLE_COLLECTIONS_PATHS"] = os.pathsep.join(collections_path)

    enabled_callbacks = new_environ.get("ANSIBLE_CALLBACKS_ENABLED", "").split(",")
    enabled_callbacks.insert(0, "ansibug.dap.debug")
    new_environ["ANSIBLE_CALLBACKS_ENABLED"] = ",".join(enabled_callbacks)

    new_environ["ANSIBLE_STRATEGY"] = "ansibug.dap.debug"

    return subprocess.Popen(
        args,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=new_environ,
        pass_fds=(write_pipe,),
    )


if __name__ == "__main__":
    asyncio.run(main())
