# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import importlib.metadata
import pathlib
import sys
import typing as t

from ._logging import LogLevel


def run_playbook_connect(
    playbook_args: list[str],
    addr: str,
    *,
    no_wait: bool = True,
    connect_timeout: float = 5.0,
    log_file: pathlib.Path | None = None,
    log_level: LogLevel = "info",
) -> None:
    """Run ansible-playbook in this process in connect mode.

    Runs ansible-playbook with the debugger hooks installed, the debugger will
    connect to the debug server address listed.

    Args:
        playbook_args: Arguments to invoke ansible-playbook with.
        addr: The address to connect to.
        no_wait: Do not wait until the client has communicated with the
            ansible-playbook process and sent the configurationDone request
            before starting the playbook.
        connect_timeout: The timeout, in seconds, to wait to connect to addr
            before failing.
        log_file: Set ansibug debuggee logger to log to the absolute path of
            this file if set.
        log_level: Set ansibug debuggee logger filter to use this level when
            logging. This only applies if log_file is also set.
    """
    _run_playbook(
        playbook_args,
        "connect",
        addr,
        no_wait=no_wait,
        connect_timeout=connect_timeout,
        log_file=log_file,
        log_level=log_level,
    )


def run_playbook_listen(
    playbook_args: list[str],
    addr: str,
    *,
    no_wait: bool = True,
    use_tls: bool = False,
    tls_cert: pathlib.Path | None = None,
    tls_key: pathlib.Path | None = None,
    tls_password: str | None = None,
    tls_client_ca: pathlib.Path | None = None,
    log_file: pathlib.Path | None = None,
    log_level: LogLevel = "info",
) -> None:
    """Run ansible-playbook in this process in listen mode.

    Runs ansible-playbook with the debugger hooks installed, the debugger will
    listen for the debug server to connect to it. A TCP addr with port 0, like
    'tcp://127.0.0.1:0', binds a port chosen by the OS and 'uds://' creates a
    random Unix Domain Socket path.

    If use_tls is set to True the ansible-playbook process will wrap the socket
    connection in a TLS tunnel to encrypt the data exchanged. It will use the
    existing OS CA settings when attempting to create the TLS server endpoint
    but the tls_cert, tls_key, and tls_password kwargs can be used to provide
    a custom certificate and key. The tls_cert file can contain both the
    certificate and key, if they are in separate files use the tls_key kwarg
    to specify the key path.

    Args:
        playbook_args: Arguments to invoke ansible-playbook with.
        addr: The address to listen on, 'tcp://hostname:port' or
            'uds:///path/to/uds'.
        no_wait: Do not wait until the client has communicated with the
            ansible-playbook process and sent the configurationDone request
            before starting the playbook.
        use_tls: New process will wrap the socket connection through a TLS
            tunnel.
        tls_cert: The path to the TLS certificate PEM encoded file to use for
            TLS.
        tls_key: The path to the TLS key PEM encoded file to use for TLS.
        tls_password: The password for the tls_key if it is encrypted.
        tls_client_ca: Optional CA bundle that will enforce TLS client
            authentication with a cert signed by a CA in the bundle.
        log_file: Set ansibug debuggee logger to log to the absolute path of
            this file if set.
        log_level: Set ansibug debuggee logger filter to use this level when
            logging. This only applies if log_file is also set.
    """
    _run_playbook(
        playbook_args,
        "listen",
        addr,
        no_wait=no_wait,
        use_tls=use_tls,
        tls_cert=tls_cert,
        tls_key=tls_key,
        tls_password=tls_password,
        tls_client_ca=tls_client_ca,
        log_file=log_file,
        log_level=log_level,
    )


def _ansible_playbook_path() -> str | None:
    """The installed ansible-playbook script of this Python's ansible-core."""
    try:
        files = importlib.metadata.distribution("ansible-core").files or []
    except importlib.metadata.PackageNotFoundError:
        return None

    return next((str(f.locate()) for f in files if f.name == "ansible-playbook"), None)


def _run_playbook(
    playbook_args: list[str],
    mode: t.Literal["connect", "listen"],
    addr: str,
    **debugger_kwargs: t.Any,
) -> None:
    """Common run code for connect and listen modes, exits with the playbook rc.

    The debugger_kwargs are the setup_debugger kwargs.
    """
    # We set sys.argv to include the path to the ansible-playbook script so
    # that it can be used by ssh's SSH_ASKPASS setup.
    sys.argv = [_ansible_playbook_path() or sys.argv[0], *playbook_args]

    # Imported here as the debug adapter side runs without Ansible installed.
    from ansible.cli.playbook import main  # pyright: ignore[reportUnknownVariableType]  # ansible-core is untyped

    from ._playbook._hooks import setup_debugger

    # Fail before running anything, including a failure to connect, rather
    # than run a playbook the caller wanted to debug without the debugger.
    # An OSError is a bad address, cert, or log path, anything else is a bug
    # and keeps its traceback.
    try:
        debugger = setup_debugger(mode, addr, **debugger_kwargs)
    except OSError as e:
        sys.stderr.write(f"ansibug: failed to start the debugger: {type(e).__name__}: {e}\n")
        sys.exit(1)

    with debugger:
        main(sys.argv)
