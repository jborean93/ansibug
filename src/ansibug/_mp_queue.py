# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pickle
import socket
import ssl
import threading
import types
import typing as t

from ._socket_helper import CancelledError, SocketCancellationToken, SocketHelper
from .dap import ProtocolMessage


class MPProtocol(t.Protocol):
    def on_msg_received(self, msg: ProtocolMessage) -> None:
        """Called when a message has been received from the peer."""
        return

    def connection_closed(self, exp: Exception | None) -> None:
        """Called when the connection is closed, exp will contain an exception if an error occurred."""
        return

    def connection_made(self) -> None:
        """Called when the connection has been made with the peer."""
        return


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
    def address(self) -> tuple[str, int, bool]:
        if self._socket.family == socket.AddressFamily.AF_INET6:
            host, port, flowinfo, scope_id = self._socket.getsockname()
            ipv6 = True
        else:
            host, port = self._socket.getsockname()
            ipv6 = False

        return host, port, ipv6

    def send(
        self,
        data: ProtocolMessage,
    ) -> None:
        b_data = pickle.dumps(data)
        b_len = len(b_data).to_bytes(4, byteorder="little")
        self._socket.send(b_len, self._cancel_token)
        self._socket.send(b_data, self._cancel_token)

    def start(
        self,
        timeout: float = 0,
    ) -> None:
        self._recv_thread = threading.Thread(
            target=self._recv_handler,
            name=f"{type(self).__name__} Recv",
        )
        self._recv_thread.start()
        self._proto.connection_made()

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

                # FIXME: Have some way for the client to notify on an exception
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
        address: tuple[str, int],
        proto: t.Callable[[], MPProtocol],
        *,
        ssl_context: ssl.SSLContext | None = None,
        cancel_token: SocketCancellationToken | None = None,
    ) -> None:
        # Use a blank socket, the real one is created in start()
        super().__init__(SocketHelper("client", socket.socket()), proto, cancel_token=cancel_token)
        self._host, self._port = address
        self._ssl_context = ssl_context

    def __enter__(self) -> ClientMPQueue:
        super().__enter__()
        return self

    def start(
        self,
        timeout: float = 0,
    ) -> None:
        sock = None
        error = OSError(f"Found no results for getaddrinfo for {self._host}:{self._port}")

        for family, socktype, proto, _, addr in socket.getaddrinfo(self._host, self._port, 0, socket.SOCK_STREAM):
            try:
                sock = socket.socket(family, socktype, proto)
                self._cancel_token.connect(sock, addr, timeout=timeout)
                break

            except OSError as e:
                error = e
                if sock:
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
                server_hostname=self._host,
            )

        super().start()


class ServerMPQueue(MPQueue):
    def __init__(
        self,
        address: tuple[str, int],
        proto: t.Callable[[], MPProtocol],
        *,
        ssl_context: ssl.SSLContext | None = None,
        cancel_token: SocketCancellationToken | None = None,
    ) -> None:
        sock_kwargs: dict[str, t.Any] = {}
        if address[0] == "" and socket.has_dualstack_ipv6():
            # Allows the server to bind on both IPv4 and IPv6.
            sock_kwargs |= {
                "family": socket.AF_INET6,
                "dualstack_ipv6": True,
            }

        sock = socket.create_server(
            address,
            reuse_port=True,
            **sock_kwargs,
        )

        super().__init__(SocketHelper("server", sock), proto, cancel_token=cancel_token)
        self._ssl_context = ssl_context

    def __enter__(self) -> ServerMPQueue:
        super().__enter__()
        return self

    def start(
        self,
        timeout: float = 0,
    ) -> None:
        self._socket.accept(self._cancel_token, timeout=timeout)
        if self._ssl_context:
            self._socket.wrap_tls(
                self._ssl_context,
                server_side=True,
            )

        super().start()
