# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import functools
import logging
import pathlib
import sys
import typing as t

import debugpy

from . import _dap as dap
from ._mp_queue import ServerMPQueue

log = logging.getLogger(__name__)


def start_dap() -> None:
    log.info("starting")

    debugpy.listen(("localhost", 12535))
    debugpy.wait_for_client()
    a = ""

    with ServerMPQueue(("127.0.0.1", 0)) as server:
        server.start()
        dap = DAP(server)
        dap.start()

    log.info("ending")


class DAP:
    def __init__(
        self,
        server: ServerMPQueue,
    ) -> None:
        self._adapter = dap.DebugAdapterServer()
        self._server = server

    def start(self) -> None:
        stdin = sys.stdin.buffer.raw  # type: ignore[attr-defined]  # This is defined
        stdout = sys.stdout.buffer.raw  # type: ignore[attr-defined]  # This is defined
        adapter = self._adapter

        run = True
        while run:
            data = stdin.read(4096)
            log.debug("STDIN: %s", data.decode())
            adapter.receive_data(data)

            while msg := adapter.next_message():
                self._process_msg(msg)

            if data := adapter.data_to_send():
                stdout.write(data)

    @functools.singledispatchmethod
    def _process_msg(self, msg: dap.ProtocolMessage) -> None:
        self._server.send(msg)
        resp = self._server.recv()
        self._adapter.queue_msg(resp, new_seq_no=True)

    @_process_msg.register
    def _(self, msg: dap.LaunchRequest) -> None:
        addr = self._server.address
        addr_str = f"{addr[0]}:{addr[1]}"

        self._adapter.run_in_terminal_request(
            kind="integrated",
            cwd=str(pathlib.Path(__file__).parent.parent.parent),
            args=[
                sys.executable,
                "-m",
                "ansibug",
                "launch",
                "--wait-for-client",
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
        pass  # TODO: Validate success
