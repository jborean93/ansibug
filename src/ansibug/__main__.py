#!/usr/bin/env python
# PYTHON_ARGCOMPLETE_OK

# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import argparse
import os
import pathlib
import sys

from ._debug_adapter import start_dap
from ._exec_playbook import exec_playbook_connect, exec_playbook_listen

HAS_ARGCOMPLETE = True
try:
    import argcomplete
except ImportError:  # pragma: nocover
    HAS_ARGCOMPLETE = False


def _add_launch_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for the client to connect and send the "
        "configurationDone request before starting the playbook.",
    )

    parser.add_argument(
        "playbook_args",
        nargs=argparse.REMAINDER,
        help="Arguments to use when launching ansible-playbook.",
    )


def _add_log_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--log-file",
        action="store",
        type=_parse_path,
        help="Enable file logging to the file at this path.",
    )

    parser.add_argument(
        "--log-level",
        action="store",
        choices=["info", "debug", "warning", "error"],
        default="info",
        type=str,
        help="Set the logging filter level of the logger when --log-file is set. Defaults to info",
    )


def _add_tls_server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tls-cert",
        action="store",
        type=_parse_path,
        help="The path to the TLS server certificate pem. This can either be "
        "the certificate by itself or a bundle of the certificate and key as "
        "a PEM file. Use --tls-key to specify a separate key file and "
        "--tls-key-pass if the key is password protected. If no certificate "
        "is specified, the server will exchange data without TLS.",
    )

    parser.add_argument(
        "--tls-key",
        action="store",
        type=_parse_path,
        help="The path to the TLS server certificate key pem. This can be "
        "used if the --tls-cert only contains the certificate and the key is "
        "located in another file. Use --tls-key-pass to specify the password "
        "to decrypt the key if needed.",
    )

    parser.add_argument(
        "--tls-key-pass",
        action="store",
        default=os.environ.get("ANSIBUG_TLS_KEY_PASS", None),
        type=str,
        help="The password for the TLS key if it is encrypted. The "
        "environment variable ANSIBUG_TLS_KEY_PASS can also be used to "
        "provide the password without passing it through the command line.",
    )

    parser.add_argument(
        "--tls-client-ca",
        action="store",
        type=_parse_path,
        help="The path to a TLS CA bundle file or directory to use with "
        "verifying the identity of the client. If set the client must "
        "provide a certificate signed by a CA in the bundle specified for it "
        "to connect. There are no checks on the client provided cert's key "
        "usage or extended key usage, just the isssuer. If not set then no "
        "client authentication is needed.",
    )


def _parse_path(path: str) -> pathlib.Path:
    return pathlib.Path(os.path.expanduser(os.path.expandvars(path)))


def parse_args(
    args: list[str],
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

    # Connect

    connect = action.add_parser(
        "connect",
        description="Has the new ansible-playbook process start in connect "
        "mode. The connect mode will have the new process connect to an "
        "existing DA server that has set up a listener. The addr must be "
        "specified for the ansible-playbook process to connect to.",
        help="Launch a debuggable ansible-playbook process in connect mode.",
    )

    connect.add_argument(
        "--addr",
        action="store",
        type=str,
        required=True,
        help="Have the ansible-playbook process connect to this socket addr that is bound to the DAP server.",
    )
    _add_log_args(connect)
    _add_launch_common_args(connect)

    # DAP

    dap = action.add_parser(
        "dap",
        description="Start a new Debug Adapter Protocol process for a client "
        "to communicate with over stdin and stdout. This process is in "
        "charge of interacting with the DAP client and coordinating the debug "
        "session. All relevant debug information is passed in through stdin "
        "using the DAP protocol messages.",
        help="Start an executable Debug Adapter Protocol process",
    )
    _add_log_args(dap)

    # Listen

    listen = action.add_parser(
        "listen",
        description="Has the new ansible-playbook process start in listen "
        "mode. The listen mode allows the debug client to attach to the "
        "playbook later on through an attach request either locally by the "
        "playbook process id or through the host:port it is listening on.",
        help="Launch a debuggable ansible-playbook process in listen mode.",
    )

    listen.add_argument(
        "--addr",
        action="store",
        default="uds://",
        type=str,
        help="Specify the socket address to listen on. The address can "
        "either be a TCP or UDS address in the format 'tcp://hostname:port' "
        "or 'uds:///path/to/uds'. The default behavior is to create a UDS "
        "socket that only allows the current user to connect. Using a TCP "
        "address can allow connections from another host on that socket. For "
        "example 'tcp://:0' will bind a random port to all IPs on the "
        "current host. Using 'tcp://127.0.0.1:0' will bind a random port for "
        "localhost communication. Using the address 'uds://' will create a "
        "random Unix Domain Socket automatically. The address used will be "
        "displayed on the console when it is available.",
    )
    _add_log_args(listen)
    _add_launch_common_args(listen)
    listen.add_argument(
        "--wrap-tls",
        action="store_true",
        help="Has the ansible-playbook process wrap its socket communication with the DA server with TLS",
    )
    _add_tls_server_args(listen)

    if HAS_ARGCOMPLETE:  # pragma: nocover
        argcomplete.autocomplete(parser)

    return parser.parse_args(args)


def main() -> None:
    args = parse_args(sys.argv[1:])

    if args.action == "dap":
        start_dap(args.log_file, args.log_level)
        return

    if args.action == "connect":
        exec_playbook_connect(
            args.playbook_args,
            addr=args.addr,
            no_wait=args.no_wait,
            log_file=args.log_file,
            log_level=args.log_level,
        )

    else:
        exec_playbook_listen(
            args.playbook_args,
            addr=args.addr,
            no_wait=args.no_wait,
            use_tls=args.wrap_tls,
            tls_cert=args.tls_cert,
            tls_key=args.tls_key,
            tls_password=args.tls_key_pass,
            tls_client_ca=args.tls_client_ca,
            log_file=args.log_file,
            log_level=args.log_level,
        )


if __name__ == "__main__":  # pragma: nocover
    main()
