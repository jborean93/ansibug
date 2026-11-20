# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import logging
import os
import pathlib
import ssl
import typing as t

from ansible.playbook import Playbook

from ansibug._debuggee import AnsibleDebugger
from ansibug._logging import LogLevel, configure_file_logging
from ansibug._tls import create_server_tls_context

from ._breakpoints import register_play_breakpoints
from ._strategy import DebugStrategy

log = logging.getLogger(__name__)


def setup_debugger(
    mode: t.Literal["connect", "listen"],
    addr: str,
    *,
    no_wait: bool = True,
    connect_timeout: float = 0,
    use_tls: bool = False,
    tls_cert: pathlib.Path | None = None,
    tls_key: pathlib.Path | None = None,
    tls_password: str | None = None,
    tls_client_ca: pathlib.Path | None = None,
    log_file: pathlib.Path | None = None,
    log_level: LogLevel = "info",
) -> AnsibleDebugger:
    """Starts the debugger and hooks it into Ansible.

    Must be called before the CLI runs, the returned debugger is a context
    manager that shuts it down once the CLI has finished. The args are the
    ones of run_playbook_connect and run_playbook_listen.
    """
    if log_file:
        configure_file_logging(log_file, log_level)

    ssl_context: ssl.SSLContext | None = None
    if use_tls:
        ssl_context = create_server_tls_context(
            certfile=tls_cert,
            keyfile=tls_key,
            password=tls_password,
            ca_trust=tls_client_ca,
        )

    debugger = AnsibleDebugger()
    log.info("Staring Ansible Debugger with %s on '%s'", mode, addr)
    socket_addr = debugger.start(
        addr=addr,
        mode=mode,
        ssl_context=ssl_context,
        connect_timeout=connect_timeout,
    )

    if mode == "listen":
        # Flushed as the process may block waiting for a client, a piped
        # stdout would otherwise never show the address to attach to.
        print(f"Ansibug listener has been configured for process PID {os.getpid()} on '{socket_addr}'", flush=True)

    # We setup two hooks before starting the playbook executions:
    #
    #   1. Setup our base strategy to intercept and handle debug events.
    #   2. Hook into the playbook loading process to register breakpoints and
    #      notify the debugger once the playbook is loaded.

    DebugStrategy.install_ansibug_hooks(debugger, wait_for_config_done=not no_wait)

    # Only the playbook executor calls this, import_playbook loads the
    # imported playbook itself and its plays are part of get_plays().
    orig_load = Playbook.load

    def load(*args: t.Any, **kwargs: t.Any) -> Playbook:
        playbook = orig_load(*args, **kwargs)
        register_play_breakpoints(debugger, playbook.get_plays())
        debugger.playbook_loaded(getattr(playbook, "_file_name", None))
        return playbook

    Playbook.load = staticmethod(load)  # type: ignore[method-assign]

    return debugger
