# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import contextlib
import dataclasses
import functools
import logging
import os
import pathlib
import queue
import threading
import typing as t
import uuid
import weakref

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
        try:
            self._debugger.process_message(msg)
        except Exception as e:
            # FIXME: log exception

            if isinstance(msg, dap.Request):
                resp = dap.ErrorResponse(
                    command=msg.command,
                    request_seq=msg.seq,
                    message=str(e),
                    # error=dap.Message(),  # FIXME
                )
                self._debugger.send(resp)

    def connection_closed(
        self,
        exp: t.Optional[Exception],
    ) -> None:
        # FIXME: log exception
        self._debugger.send(None)


class DebugState(t.Protocol):
    def get_scopes(
        self,
        request: dap.Request,
    ) -> dap.Response:
        raise NotImplementedError()

    def get_stacktrace(
        self,
        request: dap.Request,
    ) -> dap.Response:
        raise NotImplementedError()

    def get_threads(
        self,
        request: dap.ThreadsRequest,
    ) -> dap.ThreadsResponse:
        raise NotImplementedError()

    def get_variables(
        self,
        request: dap.Request,
    ) -> t.Iterable[t.Any]:
        raise NotImplementedError()

    def set_variable(
        self,
        request: dap.Request,
    ) -> dap.Response:
        raise NotImplementedError()


@dataclasses.dataclass
class AnsibleLineBreakpoint:

    id: int
    source: dap.Source
    start_line: int
    end_line: int = -1
    verified: bool = False

    def generate_breakpoint(
        self,
        message: t.Optional[str] = None,
    ) -> dap.Breakpoint:
        return dap.Breakpoint(
            id=self.id,
            verified=self.verified,
            message=message,
            source=self.source,
            line=self.start_line,
            end_line=self.end_line,
        )


class AnsibleDebugger(metaclass=Singleton):
    def __init__(self) -> None:
        self._cancel_token = SocketCancellationToken()
        self._recv_thread: t.Optional[threading.Thread] = None
        self._send_queue: queue.Queue[t.Optional[dap.ProtocolMessage]] = queue.Queue()
        self._da_connected = threading.Event()
        self._configuration_done = threading.Event()
        self._proto = DAProtocol(self)
        self._strategy_connected = threading.Condition()
        self._strategy: t.Optional[DebugState] = None

        # Stores all the client breakpoints, key is the breakpoint number/id
        self._breakpoints: t.Dict[int, AnsibleLineBreakpoint] = {}

        # Key is the path, the value is a list of the lines in that file where:
        #   None - Line is a continuation of a breakpoint range
        #   0    - Line is not something a breakpoint can be set at.
        #   1    - Line is the start of a breakpoint range
        #
        # A continuation means the behaviour of the previous int in the list
        # continues to apply at that line.
        #
        # Examples of None would be
        #   - block/rescue/always - cannot stop on this, bp needs to be on a
        #     task.
        #   - import_* - These tasks are seen as the imported value not as
        #     itself
        #
        # Known Problems:
        #   - import_* tasks aren't present in the Playbook block. According to
        #     these rules it will be set as a breakpoint for the previous entry
        #   - roles in a play act like import_role - same as above
        #   - always and rescue aren't seen as an exact entry, will be set to
        #     the task that preceeds it
        #   - Won't contain the remaining lines of the file - bp checks will
        #     just have to use the last entry
        # FIXME: Somehow detect import entries to invalidate them.
        self._playbook_sections: t.Dict[str, t.List[t.Optional[int]]] = {}

    @contextlib.contextmanager
    def with_strategy(
        self,
        strategy: DebugState,
    ) -> t.Generator[None, None, None]:
        with self._strategy_connected:
            if self._strategy:
                raise Exception("Strategy has already been registered")

            self._strategy = strategy
            self._strategy_connected.notify_all()

        try:
            if self._da_connected.is_set():
                self._configuration_done.wait()

            yield

        finally:
            with self._strategy_connected:
                self._strategy = None
                self._strategy_connected.notify_all()

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
        self._da_connected.wait(timeout=timeout)
        # self._configuration_done.wait(timeout=timeout)
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
        if self._recv_thread:
            self._recv_thread.join()

        log.debug("DebugServer is shutdown")

    def send(
        self,
        msg: t.Optional[dap.ProtocolMessage],
    ) -> None:
        self._send_queue.put(msg)

    def register_path_breakpoint(
        self,
        path: str,
        line: int,
        bp_type: int,
    ) -> None:
        """Register a valid breakpoint section.

        Registers a line as a valid breakpoint in a path. This registration is
        used when responding the breakpoint requests from the client.

        Args:
            path: The file path the line is set.
            line: The line the breakpoint is registered to.
            bp_type: Set to 1 for a valid breakpoint and 0 for an invalid
                breakpoint section.
        """
        # Ensure each new entry has a starting value of 0 which denotes that
        # a breakpoint cannot be set at the start of the file. It can only be
        # set when a line was registered.
        file_lines = self._playbook_sections.setdefault(path, [0])
        file_lines.extend([None] * (1 + line - len(file_lines)))
        file_lines[line] = bp_type

    def _get_strategy(self) -> DebugState:
        with self._strategy_connected:
            self._strategy_connected.wait_for(lambda: self._strategy is not None)
            return t.cast(DebugState, self._strategy)

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
                    self._da_connected.set()
                    try:
                        while True:
                            resp = self._send_queue.get()
                            if not resp:
                                break

                            mp_queue.send(resp)

                    finally:
                        self._da_connected.clear()

                if mode == "connect":
                    break

        except CancelledError:
            pass

        except Exception as e:
            log.exception(f"Unknown error in DAP thread: %s", e)

        # Ensures client isn't stuck waiting for something to never come.
        self._da_connected.set()
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
        # FIXME: Deal with source_reference if set
        source_path = msg.source.path or ""
        playbook_lines = self._playbook_sections.get(source_path, None)

        # FIXME: Use global id for bp_id
        breakpoint_info: t.List[dap.Breakpoint] = []
        for idx, source_breakpoint in enumerate(msg.breakpoints):
            bp_line = source_breakpoint.line
            verified = False
            bp_msg: t.Optional[str] = None

            if msg.source_modified:
                bp_msg = "Cannot set breakpoint on modified source."

            elif not playbook_lines:
                bp_msg = "File not loaded in current playbook."

            else:
                a = ""

            bp_info = AnsibleLineBreakpoint(
                id=idx,
                source=msg.source,
                start_line=bp_line,
                verified=verified,
            )
            self._breakpoints[idx] = bp_info
            breakpoint_info.append(bp_info.generate_breakpoint(bp_msg))

        resp = dap.SetBreakpointsResponse(
            request_seq=msg.seq,
            breakpoints=breakpoint_info,
        )
        self._send_queue.put(resp)

    @process_message.register
    def _(
        self,
        msg: dap.SetExceptionBreakpointsRequest,
    ) -> None:
        raise NotImplementedError()

    @process_message.register
    def _(
        self,
        msg: dap.ThreadsRequest,
    ) -> None:
        strategy = self._get_strategy()
        resp = strategy.get_threads(msg)
        self._send_queue.put(resp)
