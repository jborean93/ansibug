# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import platform
import socket
import tempfile
import threading
import time
import typing as t

import pytest

from ansibug import _socket_helper as sh


def test_connect_with_precancelled_cancelled_token() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        cancel_token = sh.SocketCancellationToken()
        cancel_token.cancel()

        with pytest.raises(sh.CancelledError):
            cancel_token.connect(client, ("", 0))


def test_recv_with_precancelled_cancelled_token() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        cancel_token = sh.SocketCancellationToken()
        cancel_token.cancel()

        buffer = bytearray(1)
        with pytest.raises(sh.CancelledError):
            cancel_token.recv_into(client, buffer, 1)


def test_send_with_precancelled_cancelled_token() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        cancel_token = sh.SocketCancellationToken()
        cancel_token.cancel()

        with pytest.raises(sh.CancelledError):
            cancel_token.sendall(client, b"data")


@pytest.mark.skipif(platform.system() != "Darwin", reason="Socket blocking behaviour is different")
def test_connect_with_cancel_macos() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # On macOS a socket that is not listening will cause the connect to
        # block until there is one.
        server.bind(("127.0.0.1", 0))
        server_port = server.getsockname()[1]

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            cancel_token = sh.SocketCancellationToken()

            def client_connect(s: socket.socket, cancel_token: sh.SocketCancellationToken, state: dict) -> None:
                try:
                    cancel_token.connect(s, ("localhost", server_port))
                except Exception as e:
                    state["exp"] = e

            state: dict = {}
            connect_thread = threading.Thread(
                target=client_connect,
                args=(client, cancel_token, state),
                daemon=True,
            )
            connect_thread.start()

            time.sleep(1)
            cancel_token.cancel()

            connect_thread.join()
            assert "exp" in state
            assert isinstance(state["exp"], sh.CancelledError)


@pytest.mark.skipif(platform.system() != "Linux", reason="Socket blocking behaviour is different")
def test_connect_with_cancel_linux() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # To simulate a blocked connect on Linux we need to connect 1 client
        # and try again with another client.
        server.bind(("127.0.0.1", 0))
        server.listen(0)
        server_port = server.getsockname()[1]

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client1, socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        ) as client2:
            # The first client will connect without any troubles and stays in
            # the backlog
            client1.connect(("localhost", server_port))

            # The second client will hang until the backlog is freed.
            cancel_token = sh.SocketCancellationToken()

            def client_connect(s: socket.socket, cancel_token: sh.SocketCancellationToken, state: dict) -> None:
                try:
                    cancel_token.connect(s, ("localhost", server_port))
                except Exception as e:
                    state["exp"] = e

            state: dict = {}
            connect_thread = threading.Thread(
                target=client_connect,
                args=(client2, cancel_token, state),
                daemon=True,
            )
            connect_thread.start()

            time.sleep(1)
            cancel_token.cancel()

            connect_thread.join()
            assert "exp" in state
            assert isinstance(state["exp"], sh.CancelledError)


def test_recv_with_cancel() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.connect(("localhost", server.getsockname()[1]))

            c_helper = sh.SocketHelper("client", client)
            cancel_token = sh.SocketCancellationToken()

            def client_recv(s: sh.SocketHelper, cancel_token: sh.SocketCancellationToken, state: dict) -> None:
                try:
                    s.recv(1, cancel_token)
                except Exception as e:
                    state["exp"] = e

            state: dict = {}
            recv_thread = threading.Thread(
                target=client_recv,
                args=(c_helper, cancel_token, state),
                daemon=True,
            )
            recv_thread.start()

            time.sleep(1)
            cancel_token.cancel()

            recv_thread.join()
            assert "exp" in state
            assert isinstance(state["exp"], sh.CancelledError)


def test_send_with_cancel() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4)
            client.connect(("localhost", server.getsockname()[1]))

            c_helper = sh.SocketHelper("client", client)
            cancel_token = sh.SocketCancellationToken()

            def client_send(s: sh.SocketHelper, cancel_token: sh.SocketCancellationToken, state: dict) -> None:
                try:
                    # Even though SO_SNDBUF is set to 4 I still need to send a
                    # lot of data to have this become blocking.
                    s.send(b"\x00" * 666666, cancel_token)
                except Exception as e:
                    state["exp"] = e

            state: dict = {}
            send_thread = threading.Thread(
                target=client_send,
                args=(c_helper, cancel_token, state),
                daemon=True,
            )
            send_thread.start()

            time.sleep(1)
            cancel_token.cancel()

            send_thread.join()
            assert "exp" in state
            assert isinstance(state["exp"], sh.CancelledError)


def test_send_with_broken_pipe() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4)
            client.connect(("localhost", server.getsockname()[1]))

            c_helper = sh.SocketHelper("client", client)
            cancel_token = sh.SocketCancellationToken()

            def client_send(s: sh.SocketHelper, cancel_token: sh.SocketCancellationToken, state: dict) -> None:
                try:
                    # Even though SO_SNDBUF is set to 4 I still need to send a
                    # lot of data to have this become blocking.
                    s.send(b"\x00" * 666666, cancel_token)
                except Exception as e:
                    state["exp"] = e

            state: dict = {}
            send_thread = threading.Thread(
                target=client_send,
                args=(c_helper, cancel_token, state),
                daemon=True,
            )
            send_thread.start()

            time.sleep(1)
            server.close()
            # cancel_token.cancel()

            send_thread.join()
            assert "exp" in state
            assert isinstance(state["exp"], OSError)
            if platform.system() == "Darwin":
                assert "Broken pipe" in str(state["exp"])
            else:
                assert "Connection reset by peer" in str(state["exp"])


@pytest.mark.skipif(platform.system() != "Darwin", reason="Socket blocking behaviour is different")
def test_connect_with_timeout_macos() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # On macOS the client will block until the server is listening to the
        # bound socket.
        server.bind(("127.0.0.1", 0))
        server_port = server.getsockname()[1]

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            cancel_token = sh.SocketCancellationToken()
            with pytest.raises(TimeoutError):
                cancel_token.connect(client, ("localhost", server_port), timeout=0.5)


@pytest.mark.skipif(platform.system() != "Linux", reason="Socket blocking behaviour is different")
def test_connect_with_timeout_linux() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        # On Linux the client will only block if there is already listen + 1
        # number of clients connected.
        server.bind(("127.0.0.1", 0))
        server.listen(0)
        server_port = server.getsockname()[1]

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client1, socket.socket(
            socket.AF_INET, socket.SOCK_STREAM
        ) as client2:
            # The first client will connect without any troubles and stays in
            # the backlog
            client1.connect(("localhost", server_port))

            # The second client will hang until the backlog is freed or the
            # timeout is hit
            cancel_token = sh.SocketCancellationToken()
            with pytest.raises(TimeoutError):
                cancel_token.connect(client2, ("localhost", server_port), timeout=0.5)


@pytest.mark.parametrize(
    ["value", "expected"],
    [
        ("tcp://", ("", 0)),
        ("tcp://localhost:0", ("localhost", 0)),
        ("TCP://localhost:0", ("localhost", 0)),
        ("tcp://192.168.1.1:1234", ("192.168.1.1", 1234)),
        ("tcp://[2001:db8::1]:22", ("2001:db8::1", 22)),
        ("uds://file", f"{tempfile.gettempdir()}/file"),
        ("UDS:/tmp/file", "/tmp/file"),
        ("uds:///tmp/file", "/tmp/file"),
    ],
)
def test_parse_addr_string(
    value: str,
    expected: t.Any,
) -> None:
    actual = sh.parse_addr_string(value)

    assert actual == expected


def test_parse_addr_empty_uds() -> None:
    actual = sh.parse_addr_string("uds://")
    assert isinstance(actual, str)
    assert actual.startswith(f"{tempfile.gettempdir()}/ansibug-dap-")


def test_parse_addr_tcp_no_port() -> None:
    with pytest.raises(ValueError, match="Specifying a tcp address must include the port"):
        sh.parse_addr_string("tcp://hostname")


def test_parse_addr_uds_both_netloc_and_path() -> None:
    with pytest.raises(ValueError, match="Specifying a uds address must only contain the port or netloc, not both"):
        sh.parse_addr_string("uds://netloc/path")


def test_parse_addr_invalid_scheme() -> None:
    with pytest.raises(ValueError, match="An address must be for the tcp or uds scheme"):
        sh.parse_addr_string("path")


def test_parse_addr_tcp_invalid_port() -> None:
    with pytest.raises(ValueError, match="Port could not be cast to integer value as 'port'"):
        sh.parse_addr_string("tcp://hostname:port")


def test_fail_to_create_uds_invalid_path() -> None:
    with pytest.raises(FileNotFoundError):
        sh.create_uds_with_mask("/invalid/path/uds", 0o700)
