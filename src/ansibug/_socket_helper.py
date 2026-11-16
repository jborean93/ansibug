# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import base64
import collections.abc
import contextlib
import errno
import logging
import os
import os.path
import pathlib
import selectors
import socket
import ssl
import tempfile
import threading
import typing as t
import urllib.parse
import uuid

log = logging.getLogger(__name__)


def parse_addr_string(
    value: str,
) -> t.Any:
    """Parse the an address string.

    Parses the address string using the formats known to Ansibug. Currently the
    following formats are allowed:

        # TCP for all interfaces and available port
        tcp://

        # Hostname
        tcp://hostname:1234

        # IPv4
        tcp://192.168.1.0:5678

        # IPv6
        tcp://[::1]:1010

        # No hostname (represents 0.0.0.0)
        tcp://:2020

        # UDS generate random filename in tmp
        uds://

        # UDS with just the filename
        uds://ansibug-dap-sock

        # UDS with full path
        uds:/tmp/ansibug-dap-socket

        # UDS with full path alternative
        uds:///tmp/ansibug-dap-socket

    A TCP socket must include both the hostname and port. A UDS socket can be
    just the socket filename located in the temporary directory or the full
    path to the UDS socket.

    Args:
        value: The string to parse.

    Returns:
        Any: The required address for the scheme specified.
    """
    value_split = urllib.parse.urlsplit(value)

    if value_split.scheme == "tcp":
        if not value_split.netloc and not value_split.port:
            return "", 0

        if value_split.port is not None:
            return value_split.hostname or "", value_split.port

        else:
            raise ValueError("Specifying a tcp address must include the port")

    elif value_split.scheme == "uds":
        if value_split.netloc and value_split.path:
            raise ValueError("Specifying a uds address must only contain the port or netloc, not both")

        elif value_split.netloc:
            return os.path.join(tempfile.gettempdir(), value_split.netloc)

        elif value_split.path:
            return value_split.path

        else:
            return str(pathlib.Path(tempfile.gettempdir()) / f"ansibug-dap-{uuid.uuid4()}")

    else:
        raise ValueError(f"An address must be for the tcp or uds scheme")


def create_uds_with_mask(
    addr: str,
    mask: int,
) -> socket.socket:
    """Create a server Unix Domain Socket with mask specified.

    This function can be used to create a bound Unix Domain Socket with the
    mask specified.

    Args:
        addr: The UDS address to bind to.
        mask: The mask to set on the UDS created.

    Returns:
        socket.socket: The bound UDS that was created.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    original_umask = None
    try:
        try:
            # Works on Linux only
            os.fchmod(sock.fileno(), mask)
        except OSError as e:
            if e.errno != errno.EINVAL:  # pragma: nocover
                raise

            # fchmod doesn't work on other platforms like macOS. At this point
            # no thread should have started so it should be safe to use the
            # umask before binding the socket.
            original_umask = os.umask(~mask)

        sock.bind(addr)

    finally:
        if original_umask is not None:
            os.umask(original_umask)

    return sock


class SocketHelper:
    def __init__(
        self,
        use: str,
        sock: socket.socket,
    ) -> None:
        self.use = use
        self._sock = sock

    @property
    def family(self) -> socket.AddressFamily:
        return self._sock.family

    def close(self) -> None:
        log.debug("Closing %s socket", self.use)
        self._sock.close()

    def accept(
        self,
        cancel_token: SocketCancellationToken,
        timeout: float = 0,
        cancel_socket: SocketHelper | None = None,
    ) -> SocketHelper:
        log.debug("Socket %s starting accept", self.use)
        conn, addr = cancel_token.accept(
            self._sock,
            timeout=timeout,
            cancel_socket=cancel_socket._sock if cancel_socket else None,
        )
        log.debug("Socket %s accepted conn from '%s'", self.use, addr)

        return SocketHelper(self.use, conn)

    def getsockname(self) -> t.Any:
        return self._sock.getsockname()

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
            data_read = cancel_token.recv_into(self._sock, view[read:], n - read)
            read += data_read

            # On a socket shutdown 0 bytes will be read.
            if data_read == 0:
                break

        data = bytes(buffer[:read])
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Socket %s recv(%d): '%s'", self.use, n, base64.b64encode(data).decode())
        return data

    def send(
        self,
        data: bytes,
        cancel_token: SocketCancellationToken,
    ) -> None:
        """Wraps send but ensures all the data is sent."""
        if log.isEnabledFor(logging.DEBUG):
            log.debug("Socket %s send: '%s'", self.use, base64.b64encode(data).decode())
        cancel_token.sendall(self._sock, data)

    def settimeout(
        self,
        timeout: float | None,
    ) -> None:
        self._sock.settimeout(timeout)

    def shutdown(
        self,
        how: int,
    ) -> None:
        try:
            self._sock.shutdown(how)
        except OSError:
            pass

    def wrap_tls(
        self,
        ssl_context: ssl.SSLContext,
        cancel_token: SocketCancellationToken,
        *,
        server_side: bool = True,
        server_hostname: str | None = None,
    ) -> None:
        log.debug("Wrapping socket with TLS context")
        self._sock = cancel_token.wrap_tls(
            self._sock,
            ssl_context,
            server_side=server_side,
            server_hostname=server_hostname,
        )


class SocketCancellationToken:
    def __init__(self) -> None:
        self._cancel_funcs: dict[int, t.Callable[[], None]] = {}
        self._cancel_id = 0
        self._cancelled = False
        self._lock = threading.Lock()

    def accept(
        self,
        sock: socket.socket,
        timeout: float = 0,
        cancel_socket: socket.socket | None = None,
    ) -> tuple[socket.socket, t.Any]:
        socks = [(sock, selectors.EVENT_READ)]
        if cancel_socket:
            socks.append((cancel_socket, selectors.EVENT_READ))

        ready = self._wait(socks, timeout, "Timed out waiting for socket.accept()")
        if cancel_socket and cancel_socket in ready:
            raise CancelledError()

        return sock.accept()

    def connect(
        self,
        sock: socket.socket,
        addr: t.Any,
        timeout: float = 0,
    ) -> None:
        # A non-blocking connect is waited on rather than cancelling a blocked
        # connect() with shutdown, which fails with EBUSY on some Linux
        # kernels (seen on Ubuntu 22.04 with Linux 5.15.0).
        if self._cancelled:
            raise CancelledError()

        sock.setblocking(False)

        try:
            sock.connect(addr)
        except BlockingIOError:
            pass

        self._wait([(sock, selectors.EVENT_WRITE)], timeout, "Timed out waiting for socket.connect")
        if err := sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR):
            raise OSError(err, os.strerror(err))

        sock.setblocking(True)

    def _wait(
        self,
        socks: list[tuple[socket.socket, int]],
        timeout: float,
        timeout_msg: str,
    ) -> list[socket.socket]:
        """Waits for the sockets to be ready, or the token to be cancelled.

        Cancelling writes to a socketpair registered with the selector rather
        than closing the waited on socket. A closed fd is silently removed
        from an epoll/kqueue selector so the wait would never wake up.

        Returns:
            list[socket.socket]: The sockets that are ready.
        """
        wake_r, wake_w = socket.socketpair()
        with wake_r, wake_w, selectors.DefaultSelector() as selector:
            selector.register(wake_r, selectors.EVENT_READ)
            for sock, events in socks:
                selector.register(sock, events)

            def _wake() -> None:
                wake_w.send(b"\x00")

            with self.with_cancel(_wake):
                ready = selector.select(timeout or None)

            if self._cancelled:
                raise CancelledError()
            elif not ready:
                raise TimeoutError(timeout_msg)

            return [t.cast(socket.socket, key.fileobj) for key, _ in ready]

    def recv_into(
        self,
        sock: socket.socket,
        buffer: bytearray | memoryview,
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
                if self._cancelled:
                    raise CancelledError()
                else:
                    raise

    def wrap_tls(
        self,
        sock: socket.socket,
        ssl_context: ssl.SSLContext,
        *,
        server_side: bool,
        server_hostname: str | None,
    ) -> ssl.SSLSocket:
        # wrap_socket detaches sock so the cancel must act on the new socket.
        # SSLSocket.shutdown also clears its TLS state, bypass it to only
        # shutdown the underlying socket.
        ssl_sock = ssl_context.wrap_socket(
            sock,
            server_side=server_side,
            server_hostname=server_hostname,
            do_handshake_on_connect=False,
        )
        with self.with_cancel(lambda: socket.socket.shutdown(ssl_sock, socket.SHUT_RDWR)):
            try:
                ssl_sock.do_handshake()
            except OSError:
                if self._cancelled:
                    raise CancelledError()
                else:
                    raise

        return ssl_sock

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True

            for cancel_id, func in self._cancel_funcs.items():
                log.debug("Cancelling function with id %d", cancel_id)
                try:
                    func()
                except OSError:
                    # The peer may have already reset the socket, the other
                    # functions still need to be cancelled.
                    log.debug("Failed to cancel function with id %d", cancel_id, exc_info=True)

            self._cancel_funcs = {}

    @contextlib.contextmanager
    def with_cancel(
        self,
        cancel_func: t.Callable[[], None],
    ) -> collections.abc.Generator[None, None, None]:
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
