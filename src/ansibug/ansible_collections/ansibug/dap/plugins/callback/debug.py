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
author: Jordan Borean (@jborean93)
options:
  write_fd:
    description:
    - A write pipe FD to write to that signals the callback is ready to receive
      the server bind address information.
    type: int
    env:
    - name: ANSIBUG_WRITE_FD
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
    default: '%(asctime)s | %(filename)s:%(lineno)s %(funcName)s() %(message)s'
    env:
    - name: ANSIBUG_LOG_FORMAT
"""

import logging
import os
import socket
import struct
import threading
import typing as t

from ansible.executor.stats import AggregateStats
from ansible.playbook import Playbook
from ansible.plugins.callback import CallbackBase

import ansibug


def dap_server(
    log: logging.Logger,
    ready: threading.Event,
) -> None:
    try:
        pipe_path = ansibug.get_pipe_path(os.getpid())
        log.info("Starting bind processes for '%s'", pipe_path)

        try:
            os.unlink(pipe_path)
        except OSError:
            if os.path.exists(pipe_path):
                raise

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                log.debug("UDS bind for '%s'", pipe_path)
                sock.bind(pipe_path)
                sock.listen(1)

                log.debug("Signaling parent that UDS socket is ready")
                ready.set()

                conn, addr = sock.accept()
                with conn:
                    log.info("Client connected to UDS - attempting to get addr length")
                    addr_length = struct.unpack("<I", conn.recv(4))[0]

                    log.debug("Addr length from client is %d", addr_length)
                    buffer = b""
                    while len(buffer) < addr_length:
                        buffer += conn.recv(addr_length - len(buffer))

                    addr_raw = buffer.decode()
                    log.debug("Addr info from client is '%s'", addr_raw)
                    hostname, port = addr_raw.split(":", 1)

        finally:
            log.debug("Unlinking UDS socket '%s'", pipe_path)
            os.unlink(pipe_path)

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            log.debug("Socket binding for %s:%s", hostname, port)
            sock.bind((hostname, int(port)))
            sock.listen(1)

            log.debug(f"DAP thread: waiting for {hostname}:{port} connection")
            conn, addr = sock.accept()
            with conn:
                log.info("Client connected to DAP socket from '%s'", addr)
                a = ""

    except Exception as e:
        log.exception(f"Unknown error in DAP thread: %s", e)
        raise


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

    def v2_playbook_on_start(
        self,
        playbook: Playbook,
    ) -> None:
        log = logging.getLogger(__name__)

        log_file = self.get_option("log_file")
        if log_file:
            log_level = {
                "info": logging.INFO,
                "debug": logging.DEBUG,
                "warning": logging.WARNING,
                "error": logging.ERROR,
            }[self.get_option("log_level")]
            log_format = self.get_option("log_format")

            log.setLevel(log_level)
            fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
            fh.setLevel(log_level)
            fh.setFormatter(logging.Formatter(log_format))
            log.addHandler(fh)

        log.info("Starting DAP thread")
        debug_read = threading.Event()
        threading.Thread(
            target=dap_server,
            args=(log, debug_read),
            name=f"ansibug-{os.getpid()}",
            daemon=True,
        ).start()
        log.debug("Waiting for DAP UDS to be ready")
        debug_read.wait()

        # If write_fd is set then ansibug is waiting to be signaled that the
        # UDS is online and ready to receive input. Otherwise this process
        # wasn't launched by ansibug so continue on as normal.
        write_pipe_fd = int(self.get_option("write_fd") or 0)
        if write_pipe_fd:
            log.debug("Connecting to pipe %d to signal UDS socket is ready", write_pipe_fd)
            with open(write_pipe_fd, mode="w") as fd:
                fd.writelines(["dummy"])

    def v2_playbook_on_stats(
        self,
        stats: AggregateStats,
    ) -> None:
        print(f"Ending ansbug.dap.debug callback")
