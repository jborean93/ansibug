from __future__ import annotations

import os
import socket
import tempfile
import threading


def _client(s: socket.socket, addr: str, state: dict) -> None:
    try:
        s.connect(addr)

        data = s.recv(4)
        assert data == b"data"

    except Exception as e:
        state["client_exp"] = e


def _server(s: socket.socket, state: dict) -> None:
    try:
        c, _ = s.accept()

        c.sendall(b"data")

    except Exception as e:
        state["server_exp"] = e


def test_tempdir() -> None:
    uds_path = f"{tempfile.gettempdir()}/my-uds"
    if os.path.exists(uds_path):
        os.unlink(uds_path)

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server, socket.socket(
            socket.AF_UNIX, socket.SOCK_STREAM
        ) as client:
            os.fchmod(server.fileno(), 0o700)
            server.bind(uds_path)
            server.listen()

            state = {
                "server_exp": None,
                "client_exp": None,
            }
            c_thread = threading.Thread(target=_client, args=(client, uds_path, state), daemon=True)
            c_thread.start()

            s_thread = threading.Thread(target=_server, args=(server, state), daemon=True)
            s_thread.start()

            s_thread.join()
            c_thread.join()

            if state["server_exp"]:
                raise state["server_exp"]

            if state["client_exp"]:
                raise state["client_exp"]

    finally:
        if os.path.exists(uds_path):
            os.unlink(uds_path)
