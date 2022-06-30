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
  write_fd:
    description:
    - A write pipe FD to write to that signals the callback is ready to receive
      the server bind address information.
    type: int
    env:
    - name: ANSIBUG_WRITE_FD
  wait_for_client:
    description:
    - Waits for the client to request a DAP server socket and then connect to
      it.
    - The playbook will wait until the connection is made before starting.
    type: bool
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

        self._dap_server = ansibug.DebugServer()
        ready = threading.Event()
        self._dap_server.start(ready=ready)

        log.debug("Waiting for DAP UDS to be ready")
        ready.wait()

        # If write_fd is set then ansibug is waiting to be signaled that the
        # UDS is online and ready to receive input. Otherwise this process
        # wasn't launched by ansibug so continue on as normal.
        write_pipe_fd = int(self.get_option("write_fd") or 0)
        if write_pipe_fd:
            log.debug("Connecting to pipe %d to signal DAP request socket is ready", write_pipe_fd)
            with open(write_pipe_fd, mode="w") as fd:
                fd.writelines(["dummy"])

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
