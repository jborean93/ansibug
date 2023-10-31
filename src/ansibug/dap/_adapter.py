# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import json

from ._messages import DAPEncoder, ProtocolMessage


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
        header_idx = self._in_buffer.find(b"\r\n\r\n")
        if header_idx == -1:
            return None

        raw_headers = bytes(self._in_buffer[:header_idx])
        headers = dict(h.split(b": ", 2) for h in raw_headers.split(b"\r\n"))
        if b"Content-Length" not in headers:
            raise ValueError("Expected Content-Length header before message payload but none found")

        length = int(headers[b"Content-Length"])
        header_idx += 4

        if (len(self._in_buffer) - header_idx) < length:
            return None

        raw_msg = self._in_buffer[header_idx : header_idx + length]
        self._in_buffer = self._in_buffer[header_idx + length :]

        msg_data = json.loads(raw_msg.decode())
        msg = ProtocolMessage.unpack(msg_data)
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
        serialized_msg = json.dumps(data, cls=DAPEncoder)

        self._out_buffer += f"Content-Length: {len(serialized_msg)}\r\n\r\n{serialized_msg}".encode()

        return seq_no
