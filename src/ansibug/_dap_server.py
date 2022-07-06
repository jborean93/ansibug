# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import functools
import logging
import pathlib
import sys
import threading
import typing as t

import debugpy

from . import _dap as dap
from ._mp import server_manager

log = logging.getLogger(__name__)


def start_dap() -> None:
    log.info("starting")

    debugpy.listen(("localhost", 12535))
    debugpy.wait_for_client()

    dap = DAP()
    dap.start()

    log.info("ending")


class DAP:
    def __init__(self) -> None:
        self._adapter = dap.DebugAdapterServer()
        self._manager, self._server = server_manager(("127.0.0.1", 0), authkey=b"")
        self._server_thread = threading.Thread(
            target=self._server.serve_forever,
            name="da-server-manager",
        )

    def start(self) -> None:
        stdin = sys.stdin.buffer.raw  # type: ignore[attr-defined]  # This is defined
        stdout = sys.stdout.buffer.raw  # type: ignore[attr-defined]  # This is defined
        adapter = self._adapter

        try:
            run = True
            while run:
                data = stdin.read(4096)
                log.debug("STDIN: %s", data.decode())
                adapter.receive_data(data)

                while msg := adapter.next_message():
                    self._process_msg(msg)

                if data := adapter.data_to_send():
                    stdout.write(data)

        finally:
            self._manager.stop()
            self._server_thread.join()

    @functools.singledispatchmethod
    def _process_msg(self, msg: dap.ProtocolMessage) -> None:
        self._manager.send(msg)
        resp = self._manager.recv()
        self._adapter.queue_msg(resp, new_seq_no=True)

    @_process_msg.register
    def _(self, msg: dap.LaunchRequest) -> None:
        self._server_thread.start()
        addr = self._server.address
        addr_str = f"{addr[0]}:{addr[1]}"

        self._adapter.run_in_terminal_request(
            kind="integrated",
            cwd=str(pathlib.Path(__file__).parent),
            args=[
                "python",
                "-m",
                "ansibug",
                "launch",
                "--connect",
                addr_str,
                "main.yml",
                "-vv",
            ],
            title="Ansible Debug Console",
        )

    @_process_msg.register
    def _(self, msg: dap.DisconnectRequest) -> None:
        pass

    @_process_msg.register
    def _(self, msg: dap.InitializeRequest) -> None:
        pass

    @_process_msg.register
    def _(self, msg: dap.RunInTerminalResponse) -> None:
        pass
