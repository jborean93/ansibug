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
    - C(connect) will connect to the addr requested as a client.
    - C(listen) will bind a new socket to the addr requested and wait for a
      client to connect.
    type: str
    choices:
    - connect
    - listen
    env:
    - name: ANSIBUG_MODE
  socket_addr:
    description:
    - A write pipe FD to write to that is used to signal the UDS pipe is ready
      for a connection.
    type: str
    env:
    - name: ANSIBUG_SOCKET_ADDR
  wait_for_client:
    description:
    - If true, will wait until the DAP server indicates the initial
      configuration is complete and the playbook can start.
    - If false, will start the playbook immediately without waiting for the
      initial configuration details.
    type: bool
    default: false
    env:
    - name: ANSIBUG_WAIT_FOR_CLIENT
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
import threading
import typing as t

from ansible.executor.stats import AggregateStats
from ansible.playbook import Playbook
from ansible.plugins.callback import CallbackBase

import ansibug

log = logging.getLogger("ansibug.callback")


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
        self._dap_server: t.Optional[ansibug.DebugServer] = None

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

        addr = self.get_option("socket_addr")
        mode = self.get_option("mode")
        self._dap_server = ansibug.DebugServer()
        self._dap_server.start(addr, mode)

        wait_for_client = self.get_option("wait_for_client")
        if wait_for_client:
            log.info("Waiting for client to connect to DAP server")
            self._dap_server.wait_for_client()

    def v2_playbook_on_stats(
        self,
        stats: AggregateStats,
    ) -> None:
        if self._dap_server:
            self._dap_server.shutdown()
