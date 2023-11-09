# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = """
name: debug
type: aggregate
short_description: Ansible Debug Adapter Protocol Callback Plugin
description:
- The callback plugin used to handle the DAP socket connections.
- Callers should use the C(ansibug) module to invoke ansible-playbook with the
  required debug plugins enabled rather than do it directly.
author: Jordan Borean (@jborean93)
options:
  mode:
    description:
    - The socket mode to use.
    - C(connect) will connect to the addr requested and bound on the debug
      adapter server.
    - C(listen) will bind a new socket to the addr requested and wait for a
      debug adapter server to connect.
    type: str
    choices:
    - connect
    - listen
    env:
    - name: ANSIBUG_MODE
  debug_addr:
    description:
    - For C(mode=listen), the connection string the process will listen on.
    - For C(mode=connect), the connection string the process will connect to.
    - The details of these connection strings are internal to ansibug itself.
    default: localhost
    required: true
    type: str
    env:
    - name: ANSIBUG_DEBUG_ADDR
  tls_server_certfile:
    description:
    - The TLS server certificate used when C(mode=listen).
    - This is the path to a single file in PEM format containing the
      certificate, as well as any number of CA certificates needed to establish
      the certificate's authenticity.
    - This can also contain the PEM encoded certificate key, otherwise use
      C(tls_server_keyfile).
    type: path
    env:
    - name: ANSIBUG_TLS_SERVER_CERTFILE
  tls_server_keyfile:
    description:
    - The TLS server certificate key used when C(mode=listen).
    - This is the path to a single file in PEM format containing the
      certificate key.
    - If the key is encrypted use C(tls_server_key_password) to provide the
      password needed to decrypt the key.
    type: path
    env:
    - name: ANSIBUG_TLS_SERVER_KEYFILE
  tls_server_key_password:
    description:
    - The password needed to decrypt the key specified by
      C(tls_server_certfile) or C(tls_server_keyfile).
    type: str
    env:
    - name: ANSIBUG_TLS_SERVER_KEY_PASSWORD
  tls_client_ca:
    description:
    - The TLS client authentication CA verification bundles to use when
      C(mode=listen).
    - If set this will enforce client authentication meaning the client
      connecting to the listener must provide the certificate and key issued by
      a CA in the bundle provided.
    - If not set then no client authentication will be performed.
    type: path
    env:
    - name: ANSIBUG_TLS_CLIENT_CA
  use_tls:
    description:
    - Sets up a TLS protected stream when C(mode=listen).
    - Use C(tls_server_certfile), C(tls_server_keyfile), and
      C(tls_server_key_password) to specify the certificate and key used as the
      current identity.
    default: False
    type: bool
    env:
    - name: ANSIBUG_USE_TLS
  no_wait_for_config_done:
    description:
    - If true, will wait until the DA server has passed through the
      configurationDone request from the client that indicates all the initial
      breakpoint configuration has been sent through and the client is ready to
      run the code.
    - If false, will start the playbook immediately without waiting for the
      initial configuration details.
    type: bool
    default: false
    env:
    - name: ANSIBUG_NO_WAIT_FOR_CONFIG_DONE
  log_file:
    description:
    - The path used to store background logging events of the DAP thread.
    type: path
    env:
    - name: ANSIBUG_LOG_FILE
  log_level:
    description:
    - The log level to enable if C(log_file) is set.
    type: str
    default: info
    choices:
    - info
    - debug
    - warning
    - error
    env:
    - name: ANSIBUG_LOG_LEVEL
  log_format:
    description:
    - The log format to apply to C(log_file) if set
    type: str
    default: '%(asctime)s | %(name)s | %(filename)s:%(lineno)s %(funcName)s() %(message)s'
    env:
    - name: ANSIBUG_LOG_FORMAT
"""

import logging
import os
import ssl
import typing as t

from ansible.executor.stats import AggregateStats
from ansible.playbook import Playbook
from ansible.plugins.callback import CallbackBase
from ansible.utils.display import Display

from ansibug._debuggee import AnsibleDebugger
from ansibug._logging import configure_file_logging
from ansibug._tls import create_server_tls_context

from ..plugin_utils._breakpoints import register_play_breakpoints

log = logging.getLogger("ansibug.callback")

display = Display()


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "debug"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(
        self,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._debugger = AnsibleDebugger()

    def v2_playbook_on_start(
        self,
        playbook: Playbook,
    ) -> None:
        register_play_breakpoints(self._debugger, playbook.get_plays())

        log_file = self.get_option("log_file")
        if log_file:
            configure_file_logging(
                log_file,
                self.get_option("log_level"),
                self.get_option("log_format"),
            )

        mode = self.get_option("mode")
        debug_addr = self.get_option("debug_addr")

        ssl_context: ssl.SSLContext | None = None
        if self.get_option("use_tls") and mode == "listen":
            ssl_context = create_server_tls_context(
                certfile=self.get_option("tls_server_certfile"),
                keyfile=self.get_option("tls_server_keyfile"),
                password=self.get_option("tls_server_key_password"),
                ca_trust=self.get_option("tls_client_ca"),
            )

        log.info("Staring Ansible Debugger with %s on '%s'", mode, debug_addr)
        socket_addr = self._debugger.start(
            addr=debug_addr,
            mode=mode,
            ssl_context=ssl_context,
            playbook_file=getattr(playbook, "_file_name", None),
        )

        if mode == "listen":
            display.display(f"Ansibug listener has been configured for process PID {os.getpid()} on '{socket_addr}'")

        no_wait_for_config_done = self.get_option("no_wait_for_config_done")
        if not no_wait_for_config_done:
            log.info("Waiting for configuration done request to be received in Ansible")
            self._debugger.wait_for_config_done(timeout=None)

    def v2_playbook_on_stats(
        self,
        stats: AggregateStats,
    ) -> None:
        log.info("Shutting down Ansible Debugger")
        self._debugger.shutdown()
