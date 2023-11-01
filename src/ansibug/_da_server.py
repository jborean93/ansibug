# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import functools
import json
import logging
import pathlib
import sys
import threading
import time
import traceback
import types
import typing as t

from . import dap as dap
from ._debuggee import PlaybookProcessInfo, get_pid_info_path
from ._logging import LogLevel, configure_file_logging
from ._mp_queue import ClientMPQueue, MPProtocol, MPQueue, ServerMPQueue
from ._tls import create_client_tls_context

log = logging.getLogger(__name__)


def start_dap(
    log_file: pathlib.Path | None = None,
    log_level: LogLevel = "info",
) -> None:
    if log_file:
        configure_file_logging(str(log_file.absolute()), log_level)

    log.info("starting")
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
        exp: Exception | None,
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
        self._debuggee: MPQueue | None = None

        self._client_connected = True
        self._terminated_sent = False
        self._connection_exp: BaseException | None = None
        self._incoming_requests: dict[int, dap.Request] = {}
        self._outgoing_requests: set[int] = set()
        self._outgoing_lock = threading.Condition()

    def __enter__(self) -> DAServer:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None = None,
        exception_value: BaseException | None = None,
        traceback: types.TracebackType | None = None,
        **kwargs: t.Any,
    ) -> None:
        self.stop(exp=exception_value)
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
            if not data:
                break

            if log.isEnabledFor(logging.DEBUG):
                log.debug("STDIN: %s", data.decode())
            adapter.receive_data(data)

            while msg := adapter.next_message():
                # Trace each request from the client so we can return an
                # ErrorMessage if there was a critical failure.
                if isinstance(msg, dap.Request):
                    self._incoming_requests[msg.seq] = msg

                self._process_msg(msg)

    def stop(
        self,
        exp: BaseException | None = None,
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

        if close_debuggee and self._debuggee:
            self._debuggee.stop()
            self._debuggee = None

        # For every incoming request relay the exception back to the client
        # for it to display to the end user.
        # FIXME: A DAP exp when the debuggee is connected won't pass through
        if exp:
            for req in list(self._incoming_requests.values()):
                self.send_to_client(
                    dap.ErrorResponse(
                        command=req.command,
                        request_seq=req.seq,
                        message=f"Critical DAServer exception received:\n{traceback.format_exc()}",
                    )
                )
        self._incoming_requests = {}

        if not self._terminated_sent:
            self._terminated_sent = True
            self.send_to_client(dap.TerminatedEvent())

    def send_to_client(
        self,
        msg: dap.ProtocolMessage,
    ) -> None:
        stdout = sys.stdout.buffer

        self._adapter.queue_msg(msg)
        if data := self._adapter.data_to_send():
            if log.isEnabledFor(logging.DEBUG):
                log.debug("STDOUT: %s", data.decode())

            stdout.write(data)
            stdout.flush()

        with self._outgoing_lock:
            if isinstance(msg, dap.Response):
                if msg.request_seq in self._outgoing_requests:
                    self._outgoing_requests.remove(msg.request_seq)
                    self._outgoing_lock.notify_all()

                if msg.request_seq in self._incoming_requests:
                    del self._incoming_requests[msg.request_seq]

    @functools.singledispatchmethod
    def _process_msg(self, msg: dap.ProtocolMessage) -> None:
        # This should never happen.
        raise NotImplementedError(type(msg).__name__)  # pragma: nocover

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
                    message=f"Debuggee disconnected: {self._connection_exp!s}",
                )
            )
            return

        if self._debuggee:
            with self._outgoing_lock:
                self._outgoing_requests.add(msg.seq)
                self._debuggee.send(msg)
                self._outgoing_lock.wait_for(lambda: msg.seq not in self._outgoing_requests)

        if self._connection_exp:
            self.send_to_client(
                dap.ErrorResponse(
                    command=msg.command,
                    request_seq=msg.seq,
                    message=f"Debuggee disconnected: {self._connection_exp!s}",
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
                    supports_conditional_breakpoints=True,
                    supports_configuration_done_request=True,
                    supports_set_variable=True,
                ),
            )
        )

    @_process_msg.register
    def _(self, msg: dap.AttachRequest) -> None:
        try:
            attach_arguments = msg.arguments

            use_tls = attach_arguments.get("useTLS", False)

            if (playbook_pid := attach_arguments.get("processId", None)) is not None:
                pid_path = get_pid_info_path(playbook_pid)
                if not pid_path.exists():
                    raise Exception(f"Failed to find process pid file at '{pid_path}'")

                proc_json = json.loads(pid_path.read_text())
                proc_info = PlaybookProcessInfo.from_json(proc_json)
                use_tls = proc_info.use_tls
                addr = proc_info.host
                port = proc_info.port

            else:
                addr = attach_arguments.get("address", "localhost")
                if not (port := attach_arguments.get("port", None)):
                    raise Exception("Expected processId or address and port to be specified for attach")

            ssl_context = None
            if use_tls:
                verify = attach_arguments.get("tlsVerification", "verify")
                ssl_context = create_client_tls_context(verify)

            self._debuggee = ClientMPQueue(
                (addr, int(port)),
                proto=lambda: self._proto,
                ssl_context=ssl_context,
            )

            connect_timeout = float(attach_arguments.get("connectTimeout", 5.0))
            self._debuggee.start(timeout=connect_timeout)

            self.send_to_client(dap.AttachResponse(request_seq=msg.seq))
            self.send_to_client(dap.InitializedEvent())

        except Exception as e:
            self.send_to_client(
                dap.ErrorResponse(
                    command=msg.command,
                    request_seq=msg.seq,
                    message=str(e),
                )
            )

    @_process_msg.register
    def _(self, msg: dap.LaunchRequest) -> None:
        try:
            launch_arguments = msg.arguments

            self._debuggee = ServerMPQueue(
                ("", 0),
                proto=lambda: self._proto,
            )
            addr = self._debuggee.address
            addr_str = f"{addr[0]}:{addr[1]}"

            ansibug_args = [
                sys.executable,
                "-m",
                "ansibug",
                "connect",
                "--addr",
                addr_str,
            ]
            if log_file := launch_arguments.get("logFile", None):
                ansibug_args.extend(
                    [
                        "--log-file",
                        log_file,
                        "--log-level",
                        launch_arguments.get("logLevel", "info"),
                    ]
                )

            if playbook := launch_arguments.get("playbook", None):
                ansibug_args.append(playbook)
            else:
                raise Exception("Expecting playbook value but none provided.")

            ansibug_args += launch_arguments.get("args", [])

            launch_console = launch_arguments.get("console", "integratedTerminal")
            console_kind: t.Literal["external", "integrated"]
            if launch_console == "integratedTerminal":
                console_kind = "integrated"
            elif launch_console == "externalTerminal":
                console_kind = "external"
            else:
                raise Exception(
                    f"Unknown console value '{launch_console}' - expected integratedTerminal or externalTerminal."
                )

            self.send_to_client(
                dap.RunInTerminalRequest(
                    cwd=launch_arguments.get("cwd", ""),
                    kind=console_kind,
                    args=ansibug_args,
                    title="Ansible Debug Console",
                    env=launch_arguments.get("env", {}),
                )
            )

        except Exception as e:
            self.send_to_client(
                dap.ErrorResponse(
                    command=msg.command,
                    request_seq=msg.seq,
                    message=str(e),
                )
            )

    @_process_msg.register
    def _(self, msg: dap.RunInTerminalResponse) -> None:
        timeout = 5.0  # FIXME: Make configurable

        if not self._debuggee:
            raise Exception(f"RunInTerminalResponse received but debuggee connection has not been configured.")

        start = time.time()
        self._debuggee.start(timeout=timeout)
        timeout = max(1.0, time.time() - start)

        if not self._proto.connected.wait(timeout=timeout):
            raise TimeoutError("Timed out waiting for Ansible to connect to DA.")

        launch_seq = next(
            (seq_no for seq_no, msg in self._incoming_requests.items() if isinstance(msg, dap.LaunchRequest)),
            -1,
        )
        if launch_seq != -1:
            self.send_to_client(dap.LaunchResponse(request_seq=launch_seq))

        # FIXME: Move this into the strategy run() method
        self.send_to_client(dap.InitializedEvent())
