# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import functools
import json
import sys
import typing as t

from .messages import (
    Capabilities,
    InitializeRequest,
    LaunchRequest,
    ProtocolMessage,
    RunInTerminalResponse,
)


class DebugAdapterServer:
    def __init__(
        self,
        capabilities: Capabilities = Capabilities(),
    ) -> None:
        self.capabilities = capabilities
        self.__seq_no = 1

    @property
    def _seq_no(self) -> int:
        no = self.__seq_no
        self.__seq_no += 1
        return no

    @functools.singledispatchmethod
    def _process_msg(self, msg: ProtocolMessage) -> None:
        raise NotImplementedError(type(msg).__name__)

    @_process_msg.register
    def _(self, msg: InitializeRequest) -> None:
        a = ""

    @_process_msg.register
    def _(self, msg: LaunchRequest) -> None:
        a = ""

    @_process_msg.register
    def _(self, msg: RunInTerminalResponse) -> None:
        a = ""

    def _queue_msg(self, msg: ProtocolMessage) -> bytes:
        data: t.Dict[str, t.Any] = {}
        msg.pack(data)

        serialized_msg = json.dumps(data)

        return f"Content-Length: {len(serialized_msg)}\r\n\r\n{serialized_msg}".encode()

    def _recv(self) -> bytes:
        return sys.stdin.buffer.raw.read()  # type: ignore[attr-defined] # It is defined

    def _send(
        self,
        data: bytes,
    ) -> None:
        sys.stdout.buffer.raw.write(data)  # type: ignore[attr-defined] # It is defined
