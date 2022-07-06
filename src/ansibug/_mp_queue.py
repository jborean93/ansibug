# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pickle
import queue
import socket
import ssl
import struct
import threading
import types
import typing as t

from ._dap import ProtocolMessage
from ._socket_helper import CancelledError, SocketCancellationToken, SocketHelper


class MPQueue:
    def __init__(
        self,
        role: t.Literal["client", "server"],
        cancel_token: t.Optional[SocketCancellationToken] = None,
    ) -> None:
        self._socket = SocketHelper(f"{role} MPQueue", socket.AF_INET, socket.SOCK_STREAM)
        self._cancel_token = cancel_token or SocketCancellationToken()
        self._recv_exp: t.Optional[Exception] = None
        self._recv_queue: queue.Queue[t.Optional[ProtocolMessage]] = queue.Queue()
        self._recv_thread = threading.Thread(
            target=self._recv_handler,
            name=f"{role} MPQueue Recv",
        )

    def __enter__(self) -> MPQueue:
        self._socket.__enter__()
        return self

    def __exit__(
        self,
        exception_type: t.Optional[t.Type[BaseException]] = None,
        exception_value: t.Optional[BaseException] = None,
        traceback: t.Optional[types.TracebackType] = None,
        **kwargs: t.Any,
    ) -> None:
        self.stop()

    def recv(self) -> ProtocolMessage:
        obj = self._recv_queue.get()
        if obj is None:
            if isinstance(self._recv_exp, CancelledError):
                raise CancelledError()

            msg = str(self._recv_exp or "Unknown error")
            raise Exception(f"Error while receiving data: {msg}") from self._recv_exp

        return obj

    def send(
        self,
        data: ProtocolMessage,
    ) -> None:
        if isinstance(self._recv_exp, CancelledError):
            raise CancelledError()

        b_data = pickle.dumps(data)
        b_len = len(b_data).to_bytes(4, byteorder="little")
        self._socket.send(b_len, self._cancel_token)
        self._socket.send(b_data, self._cancel_token)

    def start(self) -> None:
        self._recv_thread.start()

    def stop(self) -> None:
        self._cancel_token.cancel()
        self._recv_thread.join()
        self._socket.close()

    def _recv_handler(self) -> None:
        try:
            while True:
                b_data_len = self._socket.recv(4, self._cancel_token)
                data_len = struct.unpack("<I", b_data_len)[0]
                b_data = self._socket.recv(data_len, self._cancel_token)
                obj = t.cast(ProtocolMessage, pickle.loads(b_data))
                self._recv_queue.put(obj)

        except Exception as e:
            self._recv_exp = e
            self._recv_queue.put(None)


class ClientMPQueue(MPQueue):
    def __init__(
        self,
        address: t.Tuple[str, int],
        *,
        ssl_context: t.Optional[ssl.SSLContext] = None,
        cancel_token: t.Optional[SocketCancellationToken] = None,
    ) -> None:
        super().__init__("client", cancel_token=cancel_token)
        self._address = address
        self._ssl_context = ssl_context

    def __enter__(self) -> ClientMPQueue:
        super().__enter__()
        return self

    def _recv_handler(self) -> None:
        self._socket.connect(self._address, self._cancel_token)
        if self._ssl_context:
            raise NotImplementedError()

        super()._recv_handler()


class ServerMPQueue(MPQueue):
    def __init__(
        self,
        address: t.Tuple[str, int],
        *,
        ssl_context: t.Optional[ssl.SSLContext] = None,
        cancel_token: t.Optional[SocketCancellationToken] = None,
    ) -> None:
        super().__init__("server", cancel_token=cancel_token)
        self._ssl_context = ssl_context
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(address)

    @property
    def address(self) -> t.Tuple[str, int]:
        return self._socket.getsockname()

    def __enter__(self) -> ServerMPQueue:
        super().__enter__()
        return self

    def _recv_handler(self) -> None:
        self._socket.accept(self._cancel_token)
        if self._ssl_context:
            raise NotImplementedError()

        super()._recv_handler()
