# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import logging
import os
import pathlib
import socket
import threading
import typing as t

from ._mp import DAPManager, client_manager, server_manager
from ._singleton import Singleton
from ._socket import CancelledError, SocketCancellationToken, SocketHelper

log = logging.getLogger(__name__)


def get_pid_info_path(pid: int) -> str:
    """Get the path used to store info about the ansible-playbook debug proc."""
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    return str(pathlib.Path(tmpdir) / f"ANSIBUG-{pid}")


# def wait_for_dap_server(
#     addr: str,
#     mode: t.Literal["connect", "listen"],
#     cancel_token: SocketCancellationToken,
# ) -> SocketHelper:
#     """Wait for DAP Server.

#     Starts a socket for the current process that the ansibug DAP server can
#     communicate with and exchange DAP requests and events.

#     Args:
#         addr: The addr of the socket.
#         mode: The socket mode to use, connect will connect to the addr while
#             listen will bind to the addr and wait for a connection.
#         cancel_token: The cancellation token to cancel the socket operations.

#     Returns:
#         SocketHelper: The socket that the DAP server is connected to.
#     """
#     log.info("Setting up ansible-playbook debug %s socket at '%s'", mode, addr)

#     sock = SocketHelper("DAP Server", socket.AF_INET, socket.SOCK_STREAM)
#     try:
#         addr_split = addr.split(":", 1)
#         hostname = addr_split[0]
#         port = int(addr_split[1])

#         if mode == "connect":
#             sock.connect((hostname, port), cancel_token)

#         else:
#             sock.bind((hostname, port))
#             with open(get_pid_info_path(os.getpid()), mode="w") as fd:
#                 fd.write(addr)

#             sock.accept(cancel_token)

#         return sock

#     except Exception:
#         sock.close()
#         raise


def wait_for_dap_server(
    addr: str,
    mode: t.Literal["connect", "listen"],
) -> DAPManager:
    log.info("Setting up ansible-playbook debug %s socket at '%s'", mode, addr)
    if mode == "listen":
        raise NotImplementedError()

    addr_split = addr.split(":", 1)
    print(addr)
    hostname = addr_split[0]
    port = int(addr_split[1])

    return client_manager((hostname, port), authkey=b"")


class DebugServer(metaclass=Singleton):
    def __init__(self) -> None:
        self._cancel_token = SocketCancellationToken()
        self._recv_thread: t.Optional[threading.Thread] = None

        self._manager: t.Optional[DAPManager] = None
        self._manager_lock = threading.Condition()

    def wait_for_client(self) -> None:
        """Waits until a client is connected.

        Waits until a client has connected to the DAP server socket and a
        server is processing the incoming requests.
        """
        with self._manager_lock:
            self._manager_lock.wait_for(lambda: self._manager is not None)

        # FIXME: Wait until configurationDone is received

    def start(
        self,
        addr: str,
        mode: t.Literal["connect", "listen"],
    ) -> None:
        """Start the background server thread.

        Starts the background server thread which waits for an incoming request
        on the process' Unix Domain Socket and then subsequently starts the
        DAP server socket on the request that came in.

        Args:
            addr: The addr of the socket.
            mode: The socket mode to use, connect will connect to the addr
                while listen will bind to the addr and wait for a connection.
        """
        self._recv_thread = threading.Thread(
            target=self._recv_task,
            args=(addr, mode),
            name="ansibug-server",
        )
        self._recv_thread.start()

    def shutdown(self) -> None:
        """Shutdown the Debug Server.

        Marks the server as completed and signals the DAP server thread to
        shutdown.
        """
        log.info("Shutting down DebugServer")
        self._cancel_token.cancel()
        if self._recv_thread:
            self._recv_thread.join()

        log.debug("DebugServer is shutdown")

    def _recv_task(
        self,
        addr: str,
        mode: t.Literal["connect", "listen"],
    ) -> None:
        """Background server recv task.

        This is the task that continuously runs in the background waiting for
        DAP server to exchange debug messages. Depending on the mode requested
        the socket could be waiting for a connection or trying to connect to
        addr requested.

        In listen mode, the socket will attempt to wait for more DAP servers to
        connect to it in order to allow multiple connections as needed. This
        continues until the playbook is completed.

        Args:
            addr: The addr of the socket.
            mode: The socket mode to use, connect will connect to the addr
                while listen will bind to the addr and wait for a connection.
        """
        log.debug("Starting DAP server thread")

        try:
            while True:
                m = wait_for_dap_server(addr, mode)
                m.connect()
                with self._manager_lock:
                    self._manager = m
                    self._manager_lock.notify_all()

                try:
                    self._process_requests(m)

                finally:
                    with self._manager_lock:
                        self._manager = m
                        self._manager_lock.notify_all()

                if mode == "connect":
                    break

        except CancelledError:
            pass

        except Exception as e:
            log.exception(f"Unknown error in DAP thread: %s", e)

        log.debug("DAP server thread task ended")

    def _process_requests(
        self,
        manager: DAPManager,
    ) -> None:
        """Continue to process client requests.

        Called by the DAP server thread to read requests coming from the client
        until either the client closes their connection or the playbook has
        ended and shutdown is called.
        """
        while True:
            msg = manager.recv()
            print(msg)
            manager.send(msg)
