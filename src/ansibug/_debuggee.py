# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import functools
import logging
import os
import pathlib
import queue
import threading
import typing as t

from . import dap
from ._mp_queue import ClientMPQueue, MPProtocol, MPQueue, ServerMPQueue
from ._singleton import Singleton
from ._socket_helper import CancelledError, SocketCancellationToken

log = logging.getLogger(__name__)


def get_pid_info_path(pid: int) -> str:
    """Get the path used to store info about the ansible-playbook debug proc."""
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    return str(pathlib.Path(tmpdir) / f"ANSIBUG-{pid}")


def wait_for_dap_server(
    addr: t.Tuple[str, int],
    proto_factory: t.Callable[[], MPProtocol],
    mode: t.Literal["connect", "listen"],
    cancel_token: SocketCancellationToken,
) -> MPQueue:
    """Wait for DAP Server.

    Attempts to either connect to a DAP server or start a new socket that the
    DAP server connects to. This connection exposes 2 methods that can send and
    receive DAP messages to and from the DAP server.

    Args:
        addr: The addr of the socket.
        proto_factory:
        mode: The socket mode to use, connect will connect to the addr while
            listen will bind to the addr and wait for a connection.
        cancel_token: The cancellation token to cancel the socket operations.

    Returns:
        MPQueue: The multiprocessing queue handler that can exchange DAP
        messages with the peer.
    """
    log.info("Setting up ansible-playbook debug %s socket at '%s'", mode, addr)

    mp_queue = (ClientMPQueue if mode == "connect" else ServerMPQueue)(addr, proto_factory, cancel_token=cancel_token)
    if isinstance(mp_queue, ServerMPQueue):
        bound_addr = mp_queue.address

        with open(get_pid_info_path(os.getpid()), mode="w") as fd:
            fd.write(f"{bound_addr[0]}:{bound_addr[1]}")

    return mp_queue


class DAProtocol(MPProtocol):
    def __init__(
        self,
        debugger: AnsibleDebugger,
    ) -> None:
        self._debugger = debugger

    def on_msg_received(
        self,
        msg: dap.ProtocolMessage,
    ) -> None:
        self._debugger.process_message(msg)

    def connection_closed(
        self,
        exp: t.Optional[Exception],
    ) -> None:
        self._debugger.send(exp)


class AnsibleDebugger(metaclass=Singleton):
    def __init__(self) -> None:
        self._cancel_token = SocketCancellationToken()
        self._recv_thread: t.Optional[threading.Thread] = None
        self._send_queue: queue.Queue[t.Optional[dap.ProtocolMessage]] = queue.Queue()
        self._configuration_done = threading.Event()
        self._proto = DAProtocol(self)

    def wait_for_config_done(
        self,
        timeout: t.Optional[float] = 10.0,
    ) -> None:
        """Waits until the debug config is done.

        Waits until the client has sent through the configuration done request
        that indicates no more initial configuration data is expected.

        Args:
            timeout: The maximum time, in seconds, to wait until the debug
                adapter is connected and ready.
        """
        self._configuration_done.wait(timeout=timeout)
        # FIXME: Add check that this wasn't set on recv shutdown

    def start(
        self,
        addr: t.Tuple[str, int],
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
            name="ansibug-debugger",
        )
        self._recv_thread.start()

    def shutdown(self) -> None:
        """Shutdown the Debug Server.

        Marks the server as completed and signals the DAP server thread to
        shutdown.
        """
        log.debug("Shutting down DebugServer")
        self._cancel_token.cancel()
        self.send(None)
        if self._recv_thread:
            self._recv_thread.join()

        log.debug("DebugServer is shutdown")

    def send(
        self,
        msg: t.Optional[t.Union[Exception, dap.ProtocolMessage]],
    ) -> None:
        if isinstance(msg, dap.ProtocolMessage):
            self._send_queue.put(msg)

        else:
            if isinstance(msg, Exception):
                raise Exception("FIXME Send back to DA") from msg

            self._send_queue.put(None)

    def _recv_task(
        self,
        addr: t.Tuple[str, int],
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
                with wait_for_dap_server(addr, lambda: self._proto, mode, self._cancel_token) as mp_queue:
                    mp_queue.start()

                    while True:
                        resp = self._send_queue.get()
                        if not resp:
                            break

                        mp_queue.send(resp)

                if mode == "connect":
                    break

        except CancelledError:
            pass

        except Exception as e:
            log.exception(f"Unknown error in DAP thread: %s", e)

        # Ensures client isn't stuck waiting for something to never come.
        self._configuration_done.set()
        log.debug("DAP server thread task ended")

    @functools.singledispatchmethod
    def process_message(
        self,
        msg: dap.ProtocolMessage,
    ) -> None:
        raise NotImplementedError(type(msg).__name__)

    @process_message.register
    def _(
        self,
        msg: dap.ConfigurationDoneRequest,
    ) -> None:
        resp = dap.ConfigurationDoneResponse(request_seq=msg.seq)
        self._send_queue.put(resp)
        self._configuration_done.set()

    @process_message.register
    def _(
        self,
        msg: dap.SetBreakpointsRequest,
    ) -> None:
        b = [dap.Breakpoint(id=i, verified=False, message="my message") for i in range(len(msg.breakpoints))]
        resp = dap.SetBreakpointsResponse(
            request_seq=msg.seq,
            breakpoints=b,
        )
        self._send_queue.put(resp)

    @process_message.register
    def _(
        self,
        msg: dap.SetExceptionBreakpointsRequest,
    ) -> None:
        resp = dap.SetExceptionBreakpointsResponse(
            request_seq=msg.seq,
            breakpoints=[],
        )
        self._send_queue.put(resp)

    @process_message.register
    def _(
        self,
        msg: dap.ThreadsRequest,
    ) -> None:
        resp = dap.ThreadsResponse(
            request_seq=msg.seq,
            threads=[dap.Thread(id=0, name="MainThread")],
        )
        self._send_queue.put(resp)
