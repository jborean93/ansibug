# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import functools
import json
import typing as t

from .messages import (
    Capabilities,
    DisconnectRequest,
    DisconnectResponse,
    InitializeRequest,
    InitializeResponse,
    LaunchRequest,
    LaunchResponse,
    ProtocolMessage,
    RunInTerminalRequest,
    RunInTerminalResponse,
    unpack_message,
)


class DebugAdapterServer:
    def __init__(
        self,
        capabilities: Capabilities = Capabilities(),
        *,
        seq_no_in: int = 1,
        seq_no_out: int = 1,
    ) -> None:
        self.capabilities = capabilities
        self._out_buffer = bytearray()
        self._in_buffer = bytearray()
        self.__seq_no_in = seq_no_in
        self.__seq_no_out = seq_no_out

    @property
    def _seq_no_in(self) -> int:
        no = self.__seq_no_in
        self.__seq_no_in += 1
        return no

    @property
    def _seq_no_out(self) -> int:
        no = self.__seq_no_out
        self.__seq_no_out += 1
        return no

    def data_to_send(
        self,
        n: int = -1,
    ) -> bytes:
        if n == -1:
            n = len(self._out_buffer)
        n = min(n, len(self._out_buffer))

        data = bytes(self._out_buffer[:n])
        self._out_buffer = self._out_buffer[n:]

        return data

    def receive_data(
        self,
        data: t.Union[bytes, bytearray, memoryview],
    ) -> None:
        self._in_buffer += data

    def next_message(self) -> t.Optional[ProtocolMessage]:
        length = 0
        buffer_cursor = 0

        while True:
            newline_idx = self._in_buffer[buffer_cursor:].find(b"\r\n")
            if newline_idx == -1:
                break

            line = self._in_buffer[buffer_cursor : buffer_cursor + newline_idx]
            if line == b"":
                if length == 0:
                    raise ValueError("Expected Content-Length header before message payload but none found")

                buffer_cursor += newline_idx + 2
                break

            header, value = line.split(b": ", 1)
            if header == b"Content-Length":
                length = int(value)

            buffer_cursor += newline_idx + 2

        if length == 0 or (len(self._in_buffer) - buffer_cursor) < length:
            return None

        raw_msg = self._in_buffer[buffer_cursor : buffer_cursor + length]
        self._in_buffer = self._in_buffer[buffer_cursor + length :]

        msg = unpack_message(raw_msg.decode())
        expected_seq_no_in = self._seq_no_in
        if expected_seq_no_in != msg.seq:
            raise ValueError(f"Expected seq {expected_seq_no_in} but received {msg.seq}")

        self._process_msg(msg)

        return msg

    def disconnect_response(
        self,
        request_seq: int,
    ) -> None:
        msg = DisconnectResponse(
            seq=self._seq_no_out,
            request_seq=request_seq,
            success=True,
            message=None,
        )
        self.queue_msg(msg)

    def initialize_response(
        self,
        request_seq: int,
        capabilities: Capabilities,
    ) -> None:
        msg = InitializeResponse(
            seq=self._seq_no_out,
            request_seq=request_seq,
            success=True,
            message=None,
            capabilities=capabilities,
        )
        self.queue_msg(msg)

    def launch_response(
        self,
        request_seq: int,
    ) -> None:
        msg = LaunchResponse(
            seq=self._seq_no_out,
            request_seq=request_seq,
            success=True,
            message=None,
        )
        self.queue_msg(msg)

    def run_in_terminal_request(
        self,
        kind: t.Literal["integrated", "external"],
        cwd: str,
        args: t.List[str],
        *,
        env: t.Optional[t.Dict[str, t.Optional[str]]] = None,
        title: t.Optional[str] = None,
    ) -> None:
        msg = RunInTerminalRequest(
            seq=self._seq_no_out,
            kind=kind,
            cwd=cwd,
            args=args,
            env=env or {},
            title=title,
        )
        self.queue_msg(msg)

    def queue_msg(
        self,
        msg: ProtocolMessage,
        new_seq_no: bool = False,
    ) -> None:
        if new_seq_no:
            msg.__setattr__("seq", self._seq_no_out)

        data: t.Dict[str, t.Any] = {}
        msg.pack(data)

        serialized_msg = json.dumps(data)

        self._out_buffer += f"Content-Length: {len(serialized_msg)}\r\n\r\n{serialized_msg}".encode()

    @functools.singledispatchmethod
    def _process_msg(self, msg: ProtocolMessage) -> None:
        pass

    @_process_msg.register
    def _(self, msg: DisconnectRequest) -> None:
        self.disconnect_response(msg.seq)

    @_process_msg.register
    def _(self, msg: InitializeRequest) -> None:
        self.initialize_response(msg.seq, self.capabilities)

    @_process_msg.register
    def _(self, msg: LaunchRequest) -> None:
        self.launch_response(msg.seq)
