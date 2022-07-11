# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import functools
import logging
import pathlib
import sys
import threading
import time
import types
import typing as t

import debugpy

from . import dap as dap
from ._mp_queue import MPProtocol, ServerMPQueue

log = logging.getLogger(__name__)


def start_dap() -> None:
    log.info("starting")

    debugpy.listen(("localhost", 12535))
    debugpy.wait_for_client()

    try:
        with DAServer() as da:
            da.start()
    except:
        log.exception("Exception when running DA Server")

    log.info("ending")


class DAProtocol(MPProtocol):
    def __init__(
        self,
        server: DAServer,
    ) -> None:
        self.connected = threading.Event()
        self._server = server

    def on_msg_received(
        self,
        msg: dap.ProtocolMessage,
    ) -> None:
        self._server.send_to_client(msg)

    def connection_closed(
        self,
        exp: t.Optional[Exception],
    ) -> None:
        # Cannot close the debuggee here as this is run in a debuggee thread
        # and close awaits the thread to finish.
        self._server.stop(exp, close_debuggee=False)

    def connection_made(self) -> None:
        self.connected.set()


class DAServer:
    def __init__(self) -> None:
        self._adapter = dap.DebugAdapterConnection()

        self._proto = DAProtocol(self)
        self._debuggee = ServerMPQueue(("127.0.0.1", 0), lambda: self._proto)

        self._client_connected = True
        self._terminated_sent = False
        self._connection_exp: t.Optional[Exception] = None
        self._outgoing_requests: t.Set[int] = set()
        self._outgoing_lock = threading.Condition()

    def __enter__(self) -> DAServer:
        self._debuggee.__enter__()
        return self

    def __exit__(
        self,
        exception_type: t.Optional[t.Type[BaseException]] = None,
        exception_value: t.Optional[BaseException] = None,
        traceback: t.Optional[types.TracebackType] = None,
        **kwargs: t.Any,
    ) -> None:
        self.stop()
        self.send_to_client(dap.ExitedEvent(exit_code=1 if exception_value else 0))

    def start(self) -> None:
        """Start DA Server.

        Starts the DA server and continues to read from stdin for messages sent
        by the client. This continues until the client has sent the disconnect
        message.
        """
        stdin = sys.stdin.buffer.raw  # type: ignore[attr-defined]  # This is defined
        adapter = self._adapter

        while self._client_connected:
            data = stdin.read(4096)
            log.debug("STDIN: %s", data.decode())
            adapter.receive_data(data)

            while msg := adapter.next_message():
                self._process_msg(msg)

    def stop(
        self,
        exp: t.Optional[Exception] = None,
        close_debuggee: bool = True,
    ) -> None:
        """Stops the debuggee connection.

        This stops the debuggee connection and marks all the outstanding
        messages as done.

        Args:
            exp: If this is being stopped for an error, this is the exception
                details.
            close_debuggee: Close the debuggee socket.
        """
        self._connection_exp = exp
        with self._outgoing_lock:
            self._outgoing_requests = set()
            self._outgoing_lock.notify_all()

        if close_debuggee:
            self._debuggee.stop()

        if not self._terminated_sent:
            self._terminated_sent = True
            self.send_to_client(dap.TerminatedEvent())

    def send_to_client(
        self,
        msg: dap.ProtocolMessage,
    ) -> None:
        stdout = sys.stdout.buffer.raw  # type: ignore[attr-defined]  # This is defined

        self._adapter.queue_msg(msg)
        if data := self._adapter.data_to_send():
            stdout.write(data)

        with self._outgoing_lock:
            if isinstance(msg, dap.Response) and msg.request_seq in self._outgoing_requests:
                self._outgoing_requests.remove(msg.request_seq)
                self._outgoing_lock.notify_all()

    @functools.singledispatchmethod
    def _process_msg(self, msg: dap.ProtocolMessage) -> None:
        # This should never happen.
        raise NotImplementedError(type(msg).__name__)

    @_process_msg.register
    def _(self, msg: dap.Request) -> None:
        # Any requests from the client that is not already registered need to
        # be sent to the debuggee. This also checks if the debuggee connection
        # is down and send through the error details if so.

        if self._connection_exp:
            self.send_to_client(
                dap.ErrorResponse(
                    command=msg.command,
                    request_seq=msg.seq,
                    message="debuggee disconnected",
                    # TODO: populate error
                )
            )
            return

        with self._outgoing_lock:
            self._outgoing_requests.add(msg.seq)
            self._debuggee.send(msg)
            self._outgoing_lock.wait_for(lambda: msg.seq not in self._outgoing_requests)

        if self._connection_exp:
            self.send_to_client(
                dap.ErrorResponse(
                    command=msg.command,
                    request_seq=msg.seq,
                    message="debuggee disconnected",
                    # TODO: populate error
                )
            )

    @_process_msg.register
    def _(self, msg: dap.DisconnectRequest) -> None:
        self._client_connected = False
        self.send_to_client(
            dap.DisconnectResponse(
                request_seq=msg.seq,
            )
        )

    @_process_msg.register
    def _(self, msg: dap.InitializeRequest) -> None:
        self.send_to_client(
            dap.InitializeResponse(
                request_seq=msg.seq,
                capabilities=dap.Capabilities(
                    supports_configuration_done_request=True,
                ),
            )
        )

    @_process_msg.register
    def _(self, msg: dap.LaunchRequest) -> None:
        addr = self._debuggee.address
        addr_str = f"{addr[0]}:{addr[1]}"

        req = dap.RunInTerminalRequest(
            kind="integrated",
            cwd=str(pathlib.Path(__file__).parent.parent.parent),
            args=[
                sys.executable,
                "-m",
                "ansibug",
                "launch",
                "--wait-for-client",
                "--connect",
                addr_str,
                "main.yml",
                "-vv",
            ],
            title="Ansible Debug Console",
        )
        self.send_to_client(req)

    @_process_msg.register
    def _(self, msg: dap.RunInTerminalResponse) -> None:
        timeout = 5.0  # FIXME: Make configurable

        start = time.time()
        self._debuggee.start(timeout=timeout)
        timeout = max(1.0, time.time() - start)

        if not self._proto.connected.wait(timeout=timeout):
            raise TimeoutError("Timed out waiting for Ansible to connect to DA.")

        self.send_to_client(dap.InitializedEvent())
