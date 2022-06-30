# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import socket
import struct
import threading
import typing as t

from ._singleton import Singleton
from ._socket import CancelledError, SocketCancellationToken, SocketHelper

log = logging.getLogger(__name__)


def get_pipe_path(pid: int) -> str:
    """Get the UDS pipe named used to received DAP server requests."""
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    return str(pathlib.Path(tmpdir) / f"ANSIBUG-{pid}")


def wait_for_dap_request(
    cancel_token: SocketCancellationToken,
    *,
    ready: t.Optional[threading.Event] = None,
) -> t.Tuple[str, int]:
    """Wait for Incoming DAP Listen Request.

    Starts a Unix Domain Socket (UDS) for the current process that waits for a
    request to start a Debug Adapter Protocol socket bind on the addr requested.
    This UDS is called by the ansibug cmdline to provide the DAP addr info that
    the client wants to connect to.

    Args:
        ready: An event to set when the UDS is created and waiting for
            connections.

    Returns:
        t.Tuple[str, int]: The hostname and port that the DAP server should
        bind to.
    """
    pipe_path = get_pipe_path(os.getpid())
    log.info("Waiting for DAP listen request on '%s'", pipe_path)

    try:
        os.unlink(pipe_path)
    except OSError:
        if os.path.exists(pipe_path):
            raise

    try:
        with SocketHelper("DAP Request Socket", socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.bind(pipe_path)

            if ready is not None:
                ready.set()

            sock.accept(cancel_token)

            b_addr_length = sock.recv(4, cancel_token)
            addr_length = struct.unpack("<I", b_addr_length)[0]
            addr = sock.recv(addr_length, cancel_token).decode()

            log.debug("Received raw addr info from client '%s'", addr)
            hostname, port = addr.split(":", 1)

            return hostname, int(port)

    finally:
        try:
            os.unlink(pipe_path)
        except OSError:
            if os.path.exists(pipe_path):
                raise


def wait_for_dap_client(
    addr: t.Tuple[str, int],
    cancel_token: SocketCancellationToken,
) -> SocketHelper:
    """Waits for a DAP client to connect to the socket created.

    Waits for the client to connect to the DAP socket that was requested.

    Args:
        addr: The addr the client requested the socket to bind to.

    Returns:
        SocketHelper: The socket with the connected client.
    """
    sock = SocketHelper("DAP Server", socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(addr)
        sock.accept(cancel_token)

        return sock

    except Exception:
        sock.close()
        raise


class DebugServer(metaclass=Singleton):
    def __init__(self) -> None:
        self._cancel_token = SocketCancellationToken()
        self._recv_thread: t.Optional[threading.Thread] = None

        self._sock: t.Optional[SocketHelper] = None
        self._sock_lock = threading.Condition()

    def wait_for_client(self) -> None:
        """Waits until a client is connected.

        Waits until a client has connected to the DAP server socket and a
        server is processing the incoming requests.
        """
        with self._sock_lock:
            self._sock_lock.wait_for(lambda: self._sock is not None)

    def start(
        self,
        *,
        ready: t.Optional[threading.Event] = None,
    ) -> None:
        """Start the background server thread.

        Starts the background server thread which waits for an incoming request
        on the process' Unix Domain Socket and then subsequently starts the
        DAP server socket on the request that came in.

        Args:
            ready: An optional event that is fired when the UDS is ready and
                waiting for a request.
        """
        self._recv_thread = threading.Thread(
            target=self._recv_task,
            args=(ready,),
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
        ready: t.Optional[threading.Event] = None,
    ) -> None:
        """Background server recv task.

        This is the task that continuously runs in the background waiting for
        a DAP addr request and then binds a socket to the addr requested. This
        continues until the DebugServer has been signaled to shutdown as the
        play has ended.

        If a client disconnects from the DAP server socket then a new UDS will
        be created to listen for future requests. This continues until the
        playbook has completed.

        Args:
            ready: An optional event that is fired when the UDS is ready and
                waiting for a request.
        """
        log.debug("Starting DAP server thread")

        try:
            while True:
                hostname, port = wait_for_dap_request(self._cancel_token, ready=ready)

                with wait_for_dap_client((hostname, port), self._cancel_token) as sock:
                    with self._sock_lock:
                        self._sock = sock
                        self._sock_lock.notify_all()

                    try:
                        self._process_requests(sock)
                    finally:
                        with self._sock_lock:
                            self._sock = None
                            self._sock_lock.notify_all()

        except CancelledError:
            pass

        except Exception as e:
            log.exception(f"Unknown error in DAP thread: %s", e)

        finally:
            # Ensure whatever is waiting doesn't get stuck
            if ready and not ready.is_set():
                ready.set()

            log.debug("DAP server thread task ended")

    def _process_requests(
        self,
        sock: SocketHelper,
    ) -> None:
        """Continue to process client requests.

        Called by the DAP server thread to read requests coming from the client
        until either the client closes their connection or the playbook has
        ended and shutdown is called.
        """
        data = sock.recv(1024, self._cancel_token)
