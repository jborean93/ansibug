# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
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


@dataclasses.dataclass(frozen=True)
class AttachArguments:
    """Arguments for AttachRequest.

    These are the known arguments for attach request. See the from_json method
    to see the default values. There are two ways to specify a process for
    attach; through the local process id or with the manual socket address and
    port.

    If the process_id is specified, the code will attempt to lookup the
    connection details of that process stored in a local temporary file under
    the PID identifier.

    If the address and port is specified, ensure use_tls is set to whether the
    socket server is expecting TLS or not.

    Args:
        process_id: The local ansible-playbook process to attach to.
        address: The socket address to connect to.
        port: The port of the socket address to connect to.
        connect_timeout: The timeout in seconds for the connection timeout.
        use_tls: Whether to use TLS or not.
        tls_verification: The TLS verification settings.
    """

    process_id: t.Optional[int]
    address: str
    port: t.Optional[int]
    connect_timeout: float
    use_tls: bool
    tls_verification: t.Union[t.Literal["verify", "ignore"], str]

    def get_connection_tuple(self) -> tuple[str, int, bool]:
        """Gets the address, port, and use_tls settings for this request."""
        if self.process_id is not None:
            pid_path = get_pid_info_path(self.process_id)
            if not pid_path.exists():
                raise ValueError(f"Failed to find process pid file at '{pid_path}'")

            proc_json = json.loads(pid_path.read_text())
            proc_info = PlaybookProcessInfo.from_json(proc_json)
            use_tls = proc_info.use_tls
            addr = proc_info.host
            port = proc_info.port

            return (addr, port, use_tls)

        elif self.port is not None:
            return (self.address, self.port, self.use_tls)

        else:
            raise ValueError("Expected processId or address/port to be specified for attach.")

    @classmethod
    def from_json(
        cls,
        data: dict[str, t.Any],
    ) -> AttachArguments:
        attach_kwargs: dict[str, t.Any] = {}
        if "useTls" in data:
            attach_kwargs["use_tls"] = bool(data["useTls"])

        return AttachArguments(
            process_id=data.get("processId", None),
            address=data.get("address", "localhost"),
            port=data.get("port", None),
            connect_timeout=float(data.get("connectTimeout", 5.0)),
            use_tls=bool(data.get("useTls", False)),
            tls_verification=data.get("tlsVerification", "verify"),
        )


@dataclasses.dataclass(frozen=True)
class LaunchArguments:
    """Arguments for LaunchRequest.

    These are the known arguments for launch request. See the from_json method
    to see the default values. A launch request will spawn a new
    ansible-playbook process through 'python -m ansibug connect ...' which sets
    up the new process to talk to the debug adapter server.

    Args:
        playbook: The playbook to launch.
        args: Extra arguments to run with ansible-playbook.
        cwd: The working directory to launch ansible-playbook with.
        env: Extra environment variables to use when launching the process.
        console: The console type to use.
        log_file: Path to a local file to log ansibug details to.
        log_level: The level of logging to use.
    """

    playbook: str
    args: t.List[str]
    cwd: str
    env: t.Dict[str, t.Optional[str]]
    console: t.Literal["integrated", "external"]
    log_file: t.Optional[str]
    log_level: LogLevel

    @classmethod
    def from_json(
        cls,
        data: dict[str, t.Any],
    ) -> LaunchArguments:
        if not (playbook := data.get("playbook", None)):
            raise ValueError("Expected playbook to be specified for launch.")

        console = data.get("console", "integratedTerminal")
        console_kind: t.Literal["external", "integrated"]
        if console == "integratedTerminal":
            console_kind = "integrated"
        elif console == "externalTerminal":
            console_kind = "external"
        else:
            raise ValueError(f"Unknown console value '{console}' - expected integratedTerminal or externalTerminal.")

        return LaunchArguments(
            playbook=playbook,
            args=data.get("args", []),
            cwd=data.get("cwd", ""),
            env=data.get("env", {}),
            console=console_kind,
            log_file=data.get("logFile", None),
            log_level=data.get("logLevel", "info"),
        )


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
                    supports_clipboard_context=True,
                    supports_conditional_breakpoints=True,
                    supports_configuration_done_request=True,
                    supports_set_variable=True,
                ),
            )
        )

    @_process_msg.register
    def _(self, msg: dap.AttachRequest) -> None:
        try:
            attach_args = AttachArguments.from_json(msg.arguments)
            addr, port, use_tls = attach_args.get_connection_tuple()

            ssl_context = None
            if use_tls:
                ssl_context = create_client_tls_context(attach_args.tls_verification)

            self._debuggee = ClientMPQueue(
                (addr, int(port)),
                proto=lambda: self._proto,
                ssl_context=ssl_context,
            )

            self._debuggee.start(timeout=attach_args.connect_timeout)

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
            launch_args = LaunchArguments.from_json(msg.arguments)

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
            if launch_args.log_file is not None:
                ansibug_args.extend(
                    [
                        "--log-file",
                        launch_args.log_file,
                        "--log-level",
                        launch_args.log_level,
                    ]
                )

            ansibug_args.append(launch_args.playbook)
            ansibug_args.extend(launch_args.args)

            self.send_to_client(
                dap.RunInTerminalRequest(
                    cwd=launch_args.cwd,
                    kind=launch_args.console,
                    args=ansibug_args,
                    title="Ansible Debug Console",
                    env=launch_args.env,
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
