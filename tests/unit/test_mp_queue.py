# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import concurrent.futures
import json
import socket
import struct
import time
import typing as t

import pytest
from tls_info import CertFixture

import ansibug.dap as dap
from ansibug import _mp_queue as mpq
from ansibug._debuggee import DebugConfiguration, PathMapping
from ansibug._socket_helper import CancelledError, SocketCancellationToken, SocketHelper
from ansibug._tls import create_client_tls_context, create_server_tls_context


def test_connect_failure_unknown_target() -> None:
    with mpq.ClientMPQueue("tcp://unknown:12345", mpq.MPProtocol) as client:
        # The error message differs depending on the host, just check there
        # was an error.
        with pytest.raises(OSError):
            client.start()


def test_connect_failure_refused() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        addr = server.getsockname()

    with mpq.ClientMPQueue(f"tcp://{addr[0]}:{addr[1]}", mpq.MPProtocol) as client:
        with pytest.raises(OSError, match="Connection refused"):
            client.start()


def _start_server(server: mpq.ServerMPQueue) -> concurrent.futures.Future[None]:
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = pool.submit(server.start)
    pool.shutdown(wait=False)
    return fut


def _connect_raw(address: str) -> socket.socket:
    host, port = address.removeprefix("tcp://").rsplit(":", 1)
    return socket.create_connection((host.strip("[]"), int(port)))


def test_server_survives_client_reset() -> None:
    server = mpq.ServerMPQueue("tcp://:0", mpq.MPProtocol)
    with server:
        # Connect and reset before the server accepts it.
        raw = _connect_raw(server.address)
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        raw.close()

        server_fut = _start_server(server)
        with mpq.ClientMPQueue(server.address, mpq.MPProtocol) as client:
            client.start(timeout=5)
            server_fut.result(timeout=5)


def test_server_tls_handshake_timeout(
    certs: CertFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mpq, "SERVER_HANDSHAKE_TIMEOUT", 0.5)
    server_ctx = create_server_tls_context(certfile=str(certs.server_combined))
    client_ctx = create_client_tls_context(verify="ignore")

    server = mpq.ServerMPQueue("tcp://:0", mpq.MPProtocol, ssl_context=server_ctx)
    with server:
        # A client that connects but never sends the TLS hello.
        with _connect_raw(server.address):
            server_fut = _start_server(server)

            with mpq.ClientMPQueue(server.address, mpq.MPProtocol, ssl_context=client_ctx) as client:
                client.start(timeout=5)
                server_fut.result(timeout=5)


def test_server_tls_handshake_cancel(certs: CertFixture) -> None:
    server_ctx = create_server_tls_context(certfile=str(certs.server_combined))
    token = SocketCancellationToken()

    server = mpq.ServerMPQueue("tcp://:0", mpq.MPProtocol, ssl_context=server_ctx, cancel_token=token)
    with server:
        with _connect_raw(server.address):
            server_fut = _start_server(server)
            time.sleep(0.5)  # Give the server time to reach the handshake.
            token.cancel()

            # Must not wait for SERVER_HANDSHAKE_TIMEOUT.
            with pytest.raises(CancelledError):
                server_fut.result(timeout=mpq.SERVER_HANDSHAKE_TIMEOUT / 2)


def test_client_handshake_timeout() -> None:
    # The connection sits in the backlog and the server never sends anything.
    with socket.create_server(("127.0.0.1", 0)) as listener:
        host, port = listener.getsockname()
        with mpq.ClientMPQueue(f"tcp://{host}:{port}", mpq.MPProtocol) as client:
            with pytest.raises(TimeoutError):
                client.start(timeout=0.5)


def test_client_handshake_server_closed() -> None:
    with socket.create_server(("127.0.0.1", 0)) as listener:
        host, port = listener.getsockname()

        def accept_and_close() -> None:
            conn, _ = listener.accept()
            conn.close()

        with concurrent.futures.ThreadPoolExecutor() as pool:
            fut = pool.submit(accept_and_close)
            with mpq.ClientMPQueue(f"tcp://{host}:{port}", mpq.MPProtocol) as client:
                with pytest.raises(ConnectionError, match="closed the connection during the handshake"):
                    client.start(timeout=5)
            fut.result(timeout=5)


def test_send_is_json() -> None:
    config = DebugConfiguration(path_mappings=[PathMapping(local_root="/local", remote_root="/remote")])
    msg = dap.OutputEvent(category=DebugConfiguration.OUTPUT_CATEGORY, output="", data=config.to_json())

    sender_sock, receiver_sock = socket.socketpair()
    with receiver_sock, mpq.MPQueue(SocketHelper("sender", sender_sock), mpq.MPProtocol) as sender:
        sender.send(msg)

        data_len = int.from_bytes(receiver_sock.recv(4), byteorder="little")
        actual = dap.ProtocolMessage.unpack(json.loads(receiver_sock.recv(data_len)))

    assert isinstance(actual, dap.OutputEvent)
    assert actual.category == DebugConfiguration.OUTPUT_CATEGORY
    assert isinstance(actual.data, dict)
    assert DebugConfiguration.from_json(t.cast(dict[str, t.Any], actual.data)) == config
