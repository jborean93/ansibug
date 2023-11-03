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
  socket_host:
    description:
    - The socket hostname to connect or bind to, dependening on C(mode).
    - When C(mode=listen), the value C(localhost) will bind the socket to all
      IPv4 and IPv6 addresses on localhost.
    default: localhost
    type: str
    env:
    - name: ANSIBUG_SOCKET_HOST
  socket_port:
    description:
    - The socket port to connect or bind to, depending on C(mode).
    - When C(mode=connect), this must be set to a value greater than 0.
    - When C(mode=listen), the value 0 will bind to a port given to it by the
      OS. This vaalue will be displayed when the callback has initialised and
      is ready for the debug adapter to connect to the listening socket.
    default: 0
    type: int
    env:
    - name: ANSIBUG_SOCKET_PORT
  tls_server_certfile:
    description:
    - The TLS server certificate used when C(mode=listen).
    - This is the path to a single file in PEM format containing the
      certificate, as well as any number of CA certificates needed to establish
      the certificate's authenticity.
    - This can also contain the PEM encoded certificate key, otherwise use
      C(tls_server_keyfile).
    type: str
    env:
    - name: ANSIBUG_TLS_SERVER_CERTFILE
  tls_server_keyfile:
    description:
    - The TLS server certificate key used when C(mode=listen).
    - This is the path to a single file in PEM format containing the
      certificate key.
    - If the key is encrypted use C(tls_server_key_password) to provide the
      password needed to decrypt the key.
    type: str
    env:
    - name: ANSIBUG_TLS_SERVER_KEYFILE
  tls_server_key_password:
    description:
    - The password needed to decrypt the key specified by
      C(tls_server_certfile) or C(tls_server_keyfile).
    type: str
    env:
    - name: ANSIBUG_TLS_SERVER_KEY_PASSWORD
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
  wait_for_config_done_timeout:
    description:
    - The time to wait, in seconds, to wait until the configurationDone request
      has been sent by the client.
    - Set to C(-1) to wait indefinitely.
    type: float
    default: -1
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
import os
import ssl
import typing as t

from ansible.errors import AnsibleError
from ansible.executor.stats import AggregateStats
from ansible.playbook import Playbook
from ansible.playbook.block import Block
from ansible.playbook.play import Play
from ansible.playbook.task import Task
from ansible.plugins.callback import CallbackBase
from ansible.utils.display import Display

from ansibug._debuggee import AnsibleDebugger
from ansibug._logging import configure_file_logging
from ansibug._tls import create_server_tls_context

log = logging.getLogger("ansibug.callback")

display = Display()


def load_playbook_tasks(
    debugger: AnsibleDebugger,
    playbook: Playbook,
) -> None:
    play: Play
    block: Block
    task: Task

    def split_task_path(task: str) -> tuple[str, int]:
        split = task.rsplit(":", 1)
        return split[0], int(split[1])

    for play in playbook.get_plays():
        # This is essentially doing what play.compile() does but without the
        # flush stages.
        play_path, play_line = split_task_path(play.get_path())
        debugger.register_path_breakpoint(play_path, play_line, 1)

        play_blocks = play.compile() + play.handlers
        for r in play.roles:
            play_blocks += r.get_handler_blocks(play)

        for block in play_blocks:
            block_path_and_line = block.get_path()
            if block_path_and_line:
                # If the path is set this is an explicit block and should be
                # marked as an invalid breakpoint section.
                block_path, block_line = split_task_path(block_path_and_line)
                debugger.register_path_breakpoint(block_path, block_line, 0)

            task_list: list[Task] = block.block[:]
            task_list.extend(block.rescue)
            task_list.extend(block.always)

            for task in task_list:
                task_path, task_line = split_task_path(task.get_path())
                debugger.register_path_breakpoint(task_path, task_line, 1)


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
        load_playbook_tasks(self._debugger, playbook)

        log_file = self.get_option("log_file")
        if log_file:
            configure_file_logging(
                log_file,
                self.get_option("log_level"),
                self.get_option("log_format"),
            )

        mode = self.get_option("mode")

        socket_host = self.get_option("socket_host")
        socket_port = self.get_option("socket_port")
        if mode == "connect" and not socket_port:
            raise AnsibleError("socket_port must be specified when mode=connect")
        elif mode == "listen" and socket_host == "localhost":
            socket_host = ""

        ssl_context: ssl.SSLContext | None = None
        if self.get_option("use_tls") and mode == "listen":
            ssl_context = create_server_tls_context(
                certfile=self.get_option("tls_server_certfile"),
                keyfile=self.get_option("tls_server_keyfile"),
                password=self.get_option("tls_server_key_password"),
            )

        log.info("Staring Ansible Debugger with %s on %s:%d", mode, socket_host, socket_port)
        socket_addr = self._debugger.start(
            host=socket_host,
            port=socket_port,
            mode=mode,
            ssl_context=ssl_context,
        )

        if mode == "listen":
            display.display(f"Ansibug listener has been configured for process PID {os.getpid()} on {socket_addr}")

        no_wait_for_config_done = self.get_option("no_wait_for_config_done")
        wait_for_config_done_timeout = self.get_option("wait_for_config_done_timeout")
        if not no_wait_for_config_done:
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
