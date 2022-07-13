# -*- coding: utf-8 -*-
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
  socket_addr:
    description:
    - The socket addr to connect or bind to, depending on C(mode).
    type: str
    env:
    - name: ANSIBUG_SOCKET_ADDR
  wait_for_config_done:
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
    - name: ANSIBUG_WAIT_FOR_CLIENT
  wait_for_config_done_timeout:
    description:
    - The time to wait, in seconds, to wait until the configurationDone request
      has been sent by the client.
    - Set to C(-1) to wait indefinitely.
    type: float
    default: 10
    env:
    - name: ANSIBUG_WAIT_FOR_CLIENT_TIMEOUT
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
import re
import typing as t

from ansible.errors import AnsibleError
from ansible.executor.stats import AggregateStats
from ansible.playbook import Playbook
from ansible.plugins.callback import CallbackBase

import ansibug

log = logging.getLogger("ansibug.callback")

ADDR_PATTERN = re.compile(r"(?:(?P<hostname>.+):)?(?P<port>\d+)")


def configure_logging(
    file: str,
    level: str,
    format: str,
) -> None:
    log_level = {
        "info": logging.INFO,
        "debug": logging.DEBUG,
        "warning": logging.WARNING,
        "error": logging.ERROR,
    }[level]

    fh = logging.FileHandler(file, mode="w", encoding="utf-8")
    fh.setLevel(log_level)
    fh.setFormatter(logging.Formatter(format))

    ansibug_logger = logging.getLogger("ansibug")
    ansibug_logger.setLevel(log_level)
    ansibug_logger.addHandler(fh)


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
        self._debugger = ansibug.AnsibleDebugger()

    def v2_playbook_on_start(
        self,
        playbook: Playbook,
    ) -> None:
        log_file = self.get_option("log_file")
        if log_file:
            configure_logging(
                log_file,
                self.get_option("log_level"),
                self.get_option("log_format"),
            )

        mode = self.get_option("mode")
        addr = self.get_option("socket_addr")
        if not addr:
            return

        if m := ADDR_PATTERN.match(addr):
            hostname = m.group("hostname") or "127.0.0.1"
            port = int(m.group("port"))

        else:
            raise AnsibleError("socket_addr must be in the format [host:]port")

        log.info("Staring Ansible Debugger with %s on %s:%d", mode, addr[0], addr[1])
        self._debugger.start((hostname, port), mode)

        wait_for_config_done = self.get_option("wait_for_config_done")
        wait_for_config_done_timeout = self.get_option("wait_for_config_done_timeout")
        if wait_for_config_done:
            log.info("Waiting for configuration done request to be received in Ansible")
            if wait_for_config_done_timeout == -1:
                wait_for_config_done_timeout = None
            self._debugger.wait_for_config_done(timeout=wait_for_config_done_timeout)

    def v2_playbook_on_stats(
        self,
        stats: AggregateStats,
    ) -> None:
        log.info("Shutting down Ansible Debugger")
        self._debugger.shutdown()
