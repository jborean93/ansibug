#!/usr/bin/env python
# -*- coding: utf-8 -*-
# PYTHON_ARGCOMPLETE_OK

# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import argparse
import glob
import os
import pathlib
import re
import select
import socket
import subprocess
import sys
import typing as t

from ._server import get_pipe_path
from ._socket import SocketCancellationToken, SocketHelper

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

    # Common options

    def parse_listener(addr: str) -> t.Tuple[str, int]:
        if m := ADDR_PATTERN.match(addr):
            hostname = m.group("hostname") or "127.0.0.1"
            port = int(m.group("port"))

            return hostname, port

        else:
            raise argparse.ArgumentTypeError("listener must be in the format [host:]port")

    listener = argparse.ArgumentParser(add_help=False)
    listener.add_argument(
        "listener",
        action="store",
        type=parse_listener,
        help="The hostname:port to listen on for the DAP exchanges. The value is in the format [host]:port with the "
        "default host being localhost. Specify just a port number to listen on localhost, or specify a hostname:port "
        "to bind the listener on a specific address for external connections",
    )

    action = parser.add_subparsers(
        dest="action",
        required=True,
        help="The action for ansibug to perform.",
    )

    # Attach options

    attach = action.add_parser(
        "attach",
        parents=[listener],
        description="Starts the Debug Adapter Protocol server in an existing ansible-playbook process. The playbook "
        "process must have been started with the ansibug debug callback and strategy plugins so it can be attached "
        "to. If the ansible-playbook is not using those plugins then attach will fail or it has already been "
        "attached to another ansibug client then it will fail.",
        help="Attach ansibug to an existing ansible-playbook process.",
    )

    def autocomplete_pids(**kwargs: t.Any) -> t.List[str]:
        pipe_path = get_pipe_path(os.getpid())
        path_prefix = pipe_path.split("-", 1)[0]
        path_prefix += "-*"
        return [n.split("-")[-1] for n in glob.glob(path_prefix)]

    attach.add_argument(  # type: ignore[attr-defined] # weirdness for argcomplete
        "--pid",
        action="store",
        type=int,
        help="The process id of the ansible-playbook process.",
    ).completer = autocomplete_pids

    # Launch options

    launch = action.add_parser(
        "launch",
        parents=[listener],
        description="Starts a new ansible-playbook process with the arguments passed in. The new process will be "
        "launched with the ansibug arguments specified after the listen addr with the ansibug debug callback and "
        "strategy plugins loaded.",
        help="Launch a new ansible-playbook process.",
    )

    launch.add_argument(
        "--wait-for-client",
        action="store_true",
        help="Wait for the client to connect before continuing.",
    )

    launch.add_argument(
        "--timeout",
        action="store",
        type=int,
        default=10,
        help="Time to wait until the ansible-playbook has started and the debug pipe is ready.",
    )

    launch.add_argument(
        "--log-file",
        action="store",
        type=lambda p: pathlib.Path(os.path.expanduser(os.path.expandvars(p))).absolute(),
        help="If set, will log DAP background events to the path specified.",
    )

    launch.add_argument(
        "--log-level",
        action="store",
        type=str,
        default="info",
        choices=["info", "debug", "warning", "error"],
        help="The log level to use when logging entries",
    )

    launch.add_argument(
        "--log-format",
        action="store",
        type=str,
        default="%(asctime)s | %(name)s | %(filename)s:%(lineno)s %(funcName)s() %(message)s",
        help="The formatting to apply to the log entries",
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
    hostname: str
    port: int
    hostname, port = args.listener

    if args.action == "attach":
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
                args.playbook_args,
                args.wait_for_client,
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
    wait_for_client: bool,
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
                wait_for_client,
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
    """Attach to running ansible-playbook process.

    Attempts to connect to the Unix Domain Socket of the specified
    ansible-playbook process and signal what addr the client wants it to start
    listening on. The target ansible-playbook service must be running with the
    ansibug debug callback and strategy plugin for it to be a valid target.

    Args:
        hostname: The hostname the process should bind to.
        port: The port the process should bind to.
        pid: The ansible-playbook process to target.
    """
    pipe_path = get_pipe_path(pid)

    if not os.path.exists(pipe_path):
        raise Exception(f"Cannot attach to {pid} as ansibug debug pipe does not exist")

    cancel_token = SocketCancellationToken()
    with SocketHelper("", socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.connect(pipe_path, cancel_token)
        addr = f"{hostname}:{port}".encode()

        sock.send(len(addr).to_bytes(4, byteorder="little"), cancel_token)
        sock.send(addr, cancel_token)


def ansible_playbook(
    args: t.List[str],
    write_pipe: int,
    wait_for_client: bool,
    log_file: t.Optional[pathlib.Path],
    log_level: str,
    log_format: str,
) -> subprocess.Popen:
    """Starts a new ansible-playbook process with ansibug.

    Starts a new ansible-playbook process with the ansibug collection set to
    run. This allows it to process the DAP requests from a client for debugging
    purposes.

    Args:
        args: The arguments to invoke with ansible-playbook.
        write_pipe: The fd of the pipe used by the ansible-playbook process to
            notify ansibug that UDS socket is ready.
        wait_for_client: Tells the ansibug callback to wait for the client to
            connect to the DAP server before starting the playbook.
        log_file: An optional file to log ansibug messages to.
        log_level: The level to display in the log file.
        log_format: The format to use when writing log messages.

    Returns:
        subprocess.Popen: The ansible-playbook process.
    """
    ansibug_path = pathlib.Path(__file__).parent
    new_environ = os.environ.copy()
    new_environ["ANSIBUG_WRITE_FD"] = str(write_pipe)
    new_environ["ANSIBUG_WAIT_FOR_CLIENT"] = str(wait_for_client).lower()
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
        ["ansible-playbook"] + args,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        env=new_environ,
        pass_fds=(write_pipe,),
    )


if __name__ == "__main__":
    main()
