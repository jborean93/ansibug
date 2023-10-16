# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import json

from ._messages import ProtocolMessage, unpack_message


class DebugAdapterConnection:
    def __init__(self) -> None:
        self._out_buffer = bytearray()
        self._in_buffer = bytearray()
        self.__seq_no_in = 1
        self.__seq_no_out = 1

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
        data: bytes | bytearray | memoryview,
    ) -> None:
        self._in_buffer += data

    def next_message(self) -> ProtocolMessage | None:
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

        return msg

    def queue_msg(
        self,
        msg: ProtocolMessage,
    ) -> int:
        seq_no = self._seq_no_out
        msg.seq = seq_no
        data = msg.pack()
        serialized_msg = json.dumps(data)

        self._out_buffer += f"Content-Length: {len(serialized_msg)}\r\n\r\n{serialized_msg}".encode()

        return seq_no
