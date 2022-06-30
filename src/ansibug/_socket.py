# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import base64
import contextlib
import logging
import socket
import threading
import types
import typing as t

log = logging.getLogger(__name__)


class SocketHelper:
    def __init__(
        self,
        use: str,
        family: socket.AddressFamily,
        kind: socket.SocketKind,
    ) -> None:
        self.use = use
        self._sock = socket.socket(family, kind)

    def __enter__(self) -> SocketHelper:
        log.debug("Entering %s socket", self.use)
        self._sock.__enter__()
        return self

    def __exit__(
        self,
        exception_type: t.Optional[t.Type[BaseException]] = None,
        exception_value: t.Optional[BaseException] = None,
        traceback: t.Optional[types.TracebackType] = None,
        **kwargs: t.Any,
    ) -> None:
        log.debug("Exiting %s socket", self.use)
        self._sock.__exit__(exception_type, exception_value, traceback, **kwargs)

    def close(self) -> None:
        self.__exit__()

    def bind(
        self,
        address: t.Any,
    ) -> None:
        log.debug("Socket %s binding to %s", self.use, address)
        self._sock.bind(address)
        self._sock.listen(1)

    def connect(
        self,
        address: t.Any,
        cancel_token: SocketCancellationToken,
    ) -> None:
        log.debug("Socket %s connecting to %s", self.use, address)
        cancel_token.connect(self._sock, address)
        log.debug("Socket %s connection successful", self.use)

    def accept(
        self,
        cancel_token: SocketCancellationToken,
    ) -> t.Any:
        log.debug("Socket %s starting accept", self.use)
        conn, addr = cancel_token.accept(self._sock)
        log.debug("Socket %s accepted conn from %s", self.use, addr)

        # The underlying socket is no longer needed, only 1 connection is
        # expected per server socket.
        self._sock.close()
        self._sock = conn

        return addr

    def recv(
        self,
        n: int,
        cancel_token: SocketCancellationToken,
    ) -> bytes:
        """Wraps recv but ensures the data length specified is read."""
        buffer = bytearray(n)
        view = memoryview(buffer)
        read = 0

        while read < n:
            read += cancel_token.recv_info(self._sock, view[read:], n - read)

        data = bytes(buffer)
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Socket %s recv(%d): %s", self.use, n, base64.b64encode(data).decode())
        return data

    def send(
        self,
        data: bytes,
        cancel_token: SocketCancellationToken,
    ) -> None:
        """Wraps send but ensures all the data is sent."""
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Socket %s send: %s", self.use, base64.b64encode(data).decode())
        cancel_token.sendall(self._sock, data)

    def setsockopt(
        self,
        level: int,
        name: int,
        value: t.Union[int, bytes],
    ) -> None:
        self._sock.setsockopt(level, name, value)


class SocketCancellationToken:
    def __init__(self) -> None:
        self._cancel_funcs: t.Dict[int, t.Callable[[], None]] = {}
        self._cancel_id = 0
        self._cancelled = False
        self._lock = threading.Lock()

    def accept(
        self,
        sock: socket.socket,
    ) -> t.Tuple[socket.socket, t.Any]:
        with self.with_cancel(lambda: sock.shutdown(socket.SHUT_RDWR)):
            try:
                return sock.accept()
            except OSError:
                if self._cancelled:
                    raise CancelledError()
                else:
                    raise

    def connect(
        self,
        sock: socket.socket,
        addr: t.Any,
    ) -> None:
        with self.with_cancel(lambda: sock.shutdown(socket.SHUT_RDWR)):
            try:
                sock.connect(addr)
            except OSError:
                if self._cancelled:
                    raise CancelledError()
                else:
                    raise

    def recv_info(
        self,
        sock: socket.socket,
        buffer: t.Union[bytearray, memoryview],
        n: int,
    ) -> int:
        with self.with_cancel(lambda: sock.shutdown(socket.SHUT_RD)):
            res = sock.recv_into(buffer, n)
            if self._cancelled:
                raise CancelledError()

            return res

    def sendall(
        self,
        sock: socket.socket,
        data: bytes,
    ) -> None:
        with self.with_cancel(lambda: sock.shutdown(socket.SHUT_WR)):
            try:
                sock.sendall(data)
            except OSError:
                if self._cancel_funcs:
                    raise CancelledError()
                else:
                    raise

            if self._cancelled:
                raise CancelledError()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

            for cancel_id, func in self._cancel_funcs.items():
                log.debug("Canelling function with id %d", cancel_id)
                func()

            self._cancel_funcs = {}

    @contextlib.contextmanager
    def with_cancel(
        self,
        cancel_func: t.Callable[[], None],
    ) -> t.Generator[None, None, None]:
        with self._lock:
            if self._cancelled:
                raise CancelledError()

            cancel_id = self._cancel_id
            self._cancel_id += 1
            self._cancel_funcs[cancel_id] = cancel_func

        try:
            log.debug("Calling cancellable function with id %d", cancel_id)
            yield

        finally:
            with self._lock:
                self._cancel_funcs.pop(cancel_id, None)


class CancelledError(Exception):
    pass
