# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

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


class MPProtocol:
    def on_msg_received(self, msg: ProtocolMessage) -> None:
        """Called when a message has been received from the peer."""
        return  # pragma: nocover

    def connection_closed(self, exp: Exception | None) -> None:
        """Called when the connection is closed, exp will contain an exception if an error occurred."""
        return  # pragma: nocover


class MPQueue:
    def __init__(
        self,
        sock: SocketHelper,
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
        if self._socket.family == socket.AddressFamily.AF_UNIX:
            host = self._socket.getsockname()
            return f"uds://{host}"

        elif self._socket.family == socket.AddressFamily.AF_INET6:
            host, port, _, _ = self._socket.getsockname()
            return f"tcp://[{host}]:{port}"

        else:
            host, port = self._socket.getsockname()
            return f"tcp://{host}:{port}"

    def send(
        self,
        data: ProtocolMessage,
    ) -> None:
        b_data = pickle.dumps(data)
        b_len = len(b_data).to_bytes(4, byteorder="little")
        self._socket.send(b_len + b_data, self._cancel_token)

    def start(
        self,
        timeout: float = 0,
    ) -> None:
        self._recv_thread = threading.Thread(
            target=self._recv_handler,
            name=f"{type(self).__name__} Recv",
        )
        self._recv_thread.start()

    def stop(self) -> None:
        self._cancel_token.cancel()
        if self._recv_thread:
            self._recv_thread.join()
        self._recv_thread = None

        self._socket.shutdown(socket.SHUT_RDWR)
        self._socket.close()

    def _recv_handler(self) -> None:
        try:
            while True:
                b_data_len = self._socket.recv(4, self._cancel_token)
                if not b_data_len:
                    break

                data_len = int.from_bytes(b_data_len, byteorder="little", signed=False)
                b_data = self._socket.recv(data_len, self._cancel_token)

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
        # Use a blank socket, the real one is created in start()
        super().__init__(SocketHelper("client", socket.socket()), proto, cancel_token=cancel_token)
        self._address = parse_addr_string(address)
        self._ssl_context = ssl_context

    def start(
        self,
        timeout: float = 0,
    ) -> None:
        addr_info: list[
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

        if sock:
            self._socket = SocketHelper("client", sock)
        else:
            raise error

        if self._ssl_context:
            self._socket.wrap_tls(
                self._ssl_context,
                server_side=False,
                server_hostname=ssl_hostname,
            )
            # TLS 1.3 won't validate their cert was accepted until its first
            # read. This ensures the connection is validated before it is
            # going to be used.
            self._socket.recv(1, self._cancel_token)
        else:
            # Ensures that the server is actually connected to us and we aren't
            # in the backlog waiting for an accept().
            self._socket.recv(1, self._cancel_token)

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
                # If port 0 is requested, don't set SO_REUSEPORT
                reuse_port=parsed_addr[1] != 0,
                backlog=0,
                **sock_kwargs,
            )

        super().__init__(SocketHelper("server", sock), proto, cancel_token=cancel_token)
        self._ssl_context = ssl_context

    def start(
        self,
        timeout: float = 0,
        cancel_queue: MPQueue | None = None,
    ) -> None:
        cancel_socket = None
        if cancel_queue:
            cancel_socket = cancel_queue._socket

        conn = self._socket.accept(
            self._cancel_token,
            timeout=timeout,
            cancel_socket=cancel_socket,
        )

        if self._ssl_context:
            # If the server fails to complete the TLS handshake we don't want
            # to shutdown the socket, instead this will recreate it allowing a
            # new client to connect. This allows an attach request to be
            # retried if the server mandates a certificate but the client does
            # not offer one (or is rejected).
            while True:
                try:
                    conn.wrap_tls(
                        self._ssl_context,
                        server_side=True,
                    )
                    # The client will read a single byte after the handshake to
                    # verify it was able to auth correctly. TLS 1.3 only errors
                    # on the client side on the first recv/send call after the
                    # handshake.
                    conn.send(b"\x00", self._cancel_token)

                except ssl.SSLError:
                    log.exception("Server TLS handshake failed, trying again")
                    conn.close()
                    conn = self._socket.accept(
                        self._cancel_token,
                        timeout=timeout,
                        cancel_socket=cancel_socket,
                    )

                else:
                    break

        else:
            # The client will read a single byte after the connection to verify
            # it is actually connected to a server and not just part of the
            # backlog.
            conn.send(b"\x00", self._cancel_token)

        # The original server socket is no longer needed, replace it with the
        # client connection one.
        self._socket.close()
        self._socket = conn

        super().start()

    def stop(self) -> None:
        if self._uds_path:
            pathlib.Path(self._uds_path).unlink(missing_ok=True)

        super().stop()
