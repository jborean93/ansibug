# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import logging
import pathlib
import pickle
import socket
import ssl
import threading
import types
import typing as t

from ._socket_helper import (
    CancelledError,
    SocketCancellationToken,
    SocketHelper,
    create_uds_with_mask,
    parse_addr_string,
)
from .dap import ProtocolMessage

log = logging.getLogger(__name__)

# How long the server waits for an accepted client to complete the handshake
# before dropping it and waiting for another connection.
SERVER_HANDSHAKE_TIMEOUT = 10.0


class MPProtocol:
    def on_msg_received(self, msg: ProtocolMessage) -> None:  # pyright: ignore[reportUnusedParameter]
        """Called when a message has been received from the peer."""
        return  # pragma: nocover

    def connection_closed(self, exp: Exception | None) -> None:  # pyright: ignore[reportUnusedParameter]
        """Called when the connection is closed, exp will contain an exception if an error occurred."""
        return  # pragma: nocover


class MPQueue:
    def __init__(
        self,
        sock: SocketHelper | None,
        proto: t.Callable[[], MPProtocol],
        cancel_token: SocketCancellationToken | None = None,
    ) -> None:
        self._socket = sock
        self._proto = proto()
        self._cancel_token = cancel_token or SocketCancellationToken()
        self._recv_thread: threading.Thread | None = None

    def __enter__(self) -> MPQueue:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None = None,
        exception_value: BaseException | None = None,
        traceback: types.TracebackType | None = None,
        **kwargs: t.Any,
    ) -> None:
        self.stop()

    @property
    def address(self) -> str:
        raise NotImplementedError()  # pragma: nocover

    @property
    def _connection(self) -> SocketHelper:
        if not self._socket:
            raise RuntimeError("The MPQueue has not been started")

        return self._socket

    def send(
        self,
        data: ProtocolMessage,
    ) -> None:
        b_data = pickle.dumps(data)
        b_len = len(b_data).to_bytes(4, byteorder="little")
        self._connection.send(b_len + b_data, self._cancel_token)

    def start(
        self,
        timeout: float = 0,  # pyright: ignore[reportUnusedParameter] # Used by the subclasses
    ) -> None:
        self._recv_thread = threading.Thread(
            target=self._recv_handler,
            name=f"{type(self).__name__} Recv",
        )
        self._recv_thread.start()

    def stop(self) -> None:
        self._cancel_token.cancel()
        if self._recv_thread:
            # Don't block forever on a stuck handler, closing the socket below
            # also unblocks a recv.
            self._recv_thread.join(timeout=5)
        self._recv_thread = None

        if self._socket:
            self._socket.shutdown(socket.SHUT_RDWR)
            self._socket.close()

    def _recv_handler(self) -> None:
        try:
            while True:
                b_data_len = self._connection.recv(4, self._cancel_token)
                if not b_data_len:
                    break

                data_len = int.from_bytes(b_data_len, byteorder="little", signed=False)
                b_data = self._connection.recv(data_len, self._cancel_token)

                py_obj = pickle.loads(b_data)
                obj = t.cast(ProtocolMessage, py_obj)
                self._proto.on_msg_received(obj)

        except CancelledError:
            self._proto.connection_closed(None)

        except Exception as e:
            self._proto.connection_closed(e)

        else:
            self._proto.connection_closed(None)


class ClientMPQueue(MPQueue):
    def __init__(
        self,
        address: str,
        proto: t.Callable[[], MPProtocol],
        *,
        ssl_context: ssl.SSLContext | None = None,
        cancel_token: SocketCancellationToken | None = None,
    ) -> None:
        # The socket is created in start().
        super().__init__(None, proto, cancel_token=cancel_token)
        self._raw_address = address
        self._address = parse_addr_string(address)
        self._ssl_context = ssl_context

    @property
    def address(self) -> str:
        return self._raw_address

    def start(
        self,
        timeout: float = 0,
    ) -> None:
        addr_info: collections.abc.Sequence[
            tuple[
                socket.AddressFamily,
                socket.SocketKind,
                int,
                str,
                t.Any,
            ]
        ]
        if isinstance(self._address, str):
            hostname = self._address
            addr_info = [(socket.AF_UNIX, socket.SOCK_STREAM, -1, "", self._address)]
            # Python's ssl handling doesn't like hostnames greater than 63
            # characters. Using SSL with a UDS should only really happen in
            # testing so we can safely truncate this.
            ssl_hostname = hostname[:63]

        else:
            hostname, port = self._address
            ssl_hostname = hostname
            addr_info = socket.getaddrinfo(hostname, port, 0, socket.SOCK_STREAM)

        sock = None
        error = OSError(f"Found no results for getaddrinfo for {self._address}")
        for family, socktype, proto, _, addr in addr_info:
            sock = socket.socket(family, socktype, proto)
            try:
                self._cancel_token.connect(sock, addr, timeout=timeout)
                break

            except OSError as e:
                error = e
                sock.close()
            sock = None

        if not sock:
            raise error

        conn = self._socket = SocketHelper("client", sock)

        # The handshake must also complete within the connect timeout.
        conn.settimeout(timeout or None)
        if self._ssl_context:
            conn.wrap_tls(
                self._ssl_context,
                self._cancel_token,
                server_side=False,
                server_hostname=ssl_hostname,
            )

        # Ensures that the server is actually connected to us and we aren't
        # in the backlog waiting for an accept(). With TLS 1.3 this also
        # validates the server accepted our cert as that is only reported on
        # the first read.
        if not conn.recv(1, self._cancel_token):
            raise ConnectionError("The server closed the connection during the handshake")
        conn.settimeout(None)

        super().start()


class ServerMPQueue(MPQueue):
    def __init__(
        self,
        address: str,
        proto: t.Callable[[], MPProtocol],
        *,
        ssl_context: ssl.SSLContext | None = None,
        cancel_token: SocketCancellationToken | None = None,
    ) -> None:
        parsed_addr = parse_addr_string(address)

        self._uds_path: str | None = None
        if isinstance(parsed_addr, str):
            self._uds_path = parsed_addr
            sock = create_uds_with_mask(parsed_addr, 0o700)
            sock.listen()

        else:
            sock_kwargs: dict[str, t.Any] = {}
            if socket.has_dualstack_ipv6():  # pragma: nocover
                # Allows the server to bind on both IPv4 and IPv6.
                sock_kwargs |= {
                    "family": socket.AF_INET6,
                    "dualstack_ipv6": True,
                }

            sock = socket.create_server(
                parsed_addr,
                backlog=0,
                **sock_kwargs,
            )

        self._listener = SocketHelper("server", sock)
        super().__init__(None, proto, cancel_token=cancel_token)
        self._ssl_context = ssl_context

    @property
    def address(self) -> str:
        sock = self._socket or self._listener
        if sock.family == socket.AddressFamily.AF_UNIX:
            host = sock.getsockname()
            return f"uds://{host}"

        elif sock.family == socket.AddressFamily.AF_INET6:
            host, port, _, _ = sock.getsockname()
            return f"tcp://[{host}]:{port}"

        else:
            host, port = sock.getsockname()
            return f"tcp://{host}:{port}"

    def start(
        self,
        timeout: float = 0,
        cancel_queue: ServerMPQueue | None = None,
    ) -> None:
        # A connection to the cancel queue's listener cancels the accept.
        cancel_socket = cancel_queue._listener if cancel_queue else None

        # If a client fails the handshake we don't want to shutdown the
        # listener, instead wait for a new client to connect. This allows an
        # attach request to be retried if the server mandates a certificate
        # but the client does not offer one (or is rejected), and stops a
        # client that connects and resets or sends nothing from ending it.
        while True:
            conn = self._listener.accept(
                self._cancel_token,
                timeout=timeout,
                cancel_socket=cancel_socket,
            )

            try:
                conn.settimeout(SERVER_HANDSHAKE_TIMEOUT)
                if self._ssl_context:
                    conn.wrap_tls(
                        self._ssl_context,
                        self._cancel_token,
                        server_side=True,
                    )

                # The client will read a single byte after the connection to
                # verify it is actually connected to a server and not just
                # part of the backlog. With TLS 1.3 this also lets the client
                # see whether its cert was accepted.
                conn.send(b"\x00", self._cancel_token)
                conn.settimeout(None)

            except OSError:
                log.exception("Server handshake failed, waiting for a new connection")
                conn.close()

            else:
                break

        # The listener is no longer needed once a client is connected.
        self._listener.close()
        self._socket = conn

        super().start()

    def stop(self) -> None:
        if self._uds_path:
            pathlib.Path(self._uds_path).unlink(missing_ok=True)

        super().stop()
        self._listener.close()
