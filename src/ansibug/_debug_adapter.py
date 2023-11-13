# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import base64
import dataclasses
import functools
import json
import logging
import os
import pathlib
import shlex
import sys
import tempfile
import traceback
import types
import typing as t

from . import dap as dap
from ._debuggee import (
    DebugConfiguration,
    PathMapping,
    PlaybookProcessInfo,
    get_pid_info_path,
)
from ._logging import LogLevel, configure_file_logging
from ._mp_queue import ClientMPQueue, MPProtocol, MPQueue, ServerMPQueue
from ._socket_helper import CancelledError
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

    If TLS client authentication is required by the server the tls_cert must
    be set to the path of a PEM encoded certificate. This file can include both
    the certificate and key, if the key is separate use tls_key to specify that
    file.

    Args:
        process_id: The local ansible-playbook process to attach to.
        address: The socket address to connect to.
        connect_timeout: The timeout in seconds for the debug adapter to wait
            for when attempting to connect to the ansible-playbook process.
        use_tls: Whether to use TLS or not.
        tls_verification: The TLS verification settings.
        tls_cert: The certificate to use for client authentication if required
            by the server.
        tls_key: The certificate key if stored in a separate file.
        tls_key_password: The password for the certificate key if needed.
        path_mappings: A list of paths to map between a local and remote root.
    """

    process_id: t.Optional[int]
    address: str
    connect_timeout: float
    use_tls: bool
    tls_verification: t.Union[t.Literal["verify", "ignore"], str]
    tls_cert: t.Optional[str]
    tls_key: t.Optional[str]
    tls_key_password: t.Optional[str]
    path_mappings: t.List[PathMapping]

    def get_connection_tuple(self) -> tuple[str, bool]:
        """Gets the address and use_tls settings for this request."""
        if self.process_id is not None:
            pid_path = get_pid_info_path(self.process_id)
            if not pid_path.exists():
                raise ValueError(f"Failed to find process pid file at '{pid_path}'")

            proc_json = json.loads(pid_path.read_text())
            proc_info = PlaybookProcessInfo.from_json(proc_json)

            return (proc_info.address, proc_info.use_tls)

        elif self.address:
            return (self.address, self.use_tls)

        else:
            raise ValueError("Expected processId or address/port to be specified for attach.")

    @classmethod
    def from_json(
        cls,
        data: dict[str, t.Any],
    ) -> AttachArguments:
        path_mappings = []
        for mapping in data.get("pathMappings", []):
            path_mappings.append(
                PathMapping(
                    local_root=mapping["localRoot"],
                    remote_root=mapping["remoteRoot"],
                )
            )

        return AttachArguments(
            process_id=data.get("processId", None),
            address=data.get("address", ""),
            connect_timeout=float(data.get("connectTimeout", 5.0)),
            use_tls=bool(data.get("useTls", False)),
            tls_verification=data.get("tlsVerification", "verify"),
            tls_cert=data.get("tlsCertificate", None),
            tls_key=data.get("tlsKey", None),
            tls_key_password=data.get("tlsKeyPassword", None),
            path_mappings=path_mappings,
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
        connect_timeout: The timeout in seconds to wait for the newly spawned
            ansible-playbook process to connect back to the debug adapter.
        path_mappings: A list of paths to map between a local and remote root.
        log_file: Path to a local file to log ansibug details to.
        log_level: The level of logging to use.
    """

    playbook: str
    args: t.List[str]
    cwd: str
    env: t.Dict[str, t.Optional[str]]
    console: t.Literal["integrated", "external"]
    connect_timeout: float
    path_mappings: t.List[PathMapping]
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

        path_mappings = []
        for mapping in data.get("pathMappings", []):
            path_mappings.append(
                PathMapping(
                    local_root=mapping["localRoot"],
                    remote_root=mapping["remoteRoot"],
                )
            )

        return LaunchArguments(
            playbook=playbook,
            args=data.get("args", []),
            cwd=data.get("cwd", ""),
            env=data.get("env", {}),
            console=console_kind,
            connect_timeout=float(data.get("connectTimeout", 5.0)),
            path_mappings=path_mappings,
            log_file=data.get("logFile", None),
            log_level=data.get("logLevel", "info"),
        )


@dataclasses.dataclass
class _RunInTerminalDetails:
    request: dap.LaunchRequest
    debuggee: ServerMPQueue
    arguments: LaunchArguments
    launch_queue: ServerMPQueue


def start_dap(
    log_file: pathlib.Path | None = None,
    log_level: LogLevel = "info",
) -> None:
    if log_file:
        configure_file_logging(str(log_file.absolute()), log_level)

    log.info("DAP starting")
    try:
        with DAServer() as da:
            da.start()
    except:
        log.exception("Exception when running DA Server")
        raise

    log.info("DAP ending")


class DAProtocol(MPProtocol):
    def __init__(
        self,
        server: DAServer,
    ) -> None:
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
        self._server.stop(exp, from_debuggee=True)


class DAServer:
    def __init__(self) -> None:
        self._adapter = dap.DebugAdapterConnection()

        self._proto = DAProtocol(self)
        self._debuggee: MPQueue | None = None
        self._launch_queue: MPQueue | None = None
        self._incoming_requests: dict[int, dap.Request] = {}
        self._run_in_response_data: dict[int, _RunInTerminalDetails] = {}
        self._terminated_sent = False

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

    def start(self) -> None:
        """Start DA Server.

        Starts the DA server and continues to read from stdin for messages sent
        by the client. This continues until the client has sent the disconnect
        message.
        """
        stdin = sys.stdin.buffer.raw  # type: ignore[attr-defined]  # This is defined
        adapter = self._adapter

        is_connected = True
        while is_connected:
            data = stdin.read(4096)

            if log.isEnabledFor(logging.DEBUG):
                log.debug("STDIN: %s", data.decode())
            adapter.receive_data(data)

            while msg := adapter.next_message():
                # Trace each request from the client so we can return an
                # ErrorMessage if there was a critical failure.
                if isinstance(msg, dap.Request):
                    self._incoming_requests[msg.seq] = msg

                if isinstance(msg, dap.Request) and self._debuggee:
                    if isinstance(msg, dap.DisconnectRequest):
                        is_connected = False
                        self._send_disconnect(msg, self._debuggee)
                    else:
                        self._debuggee.send(msg)

                else:
                    self._process_msg(msg)

    def stop(
        self,
        exp: BaseException | None = None,
        from_debuggee: bool = False,
    ) -> None:
        """Stops the debuggee connection.

        This stops the debuggee connection and marks all the outstanding
        messages as done.

        Args:
            exp: If this is being stopped for an error, this is the exception
                details.
            from_debuggee: The stop is being called as the debuggee has
                disconnected.
        """
        # Ensure the DisconnectResponse is sent if there is an outstanding
        # request.
        for req in list(self._incoming_requests.values()):
            if isinstance(req, dap.DisconnectRequest):
                self.send_to_client(dap.DisconnectResponse(request_seq=req.seq))

        if exp:
            # For every incoming request relay the exception back to the client
            # for it to display to the end user.
            for req in list(self._incoming_requests.values()):
                resp = dap.ErrorResponse(
                    command=req.command,
                    request_seq=req.seq,
                    message=f"Critical DAServer exception received\n{traceback.format_exc()}",
                )
                self.send_to_client(resp)

        if not from_debuggee and self._debuggee:
            self._debuggee.stop()
            self._debuggee = None

        if self._launch_queue:
            self._launch_queue.stop()
            self._launch_queue = None

        if not self._terminated_sent:
            # Both the debuggee or start() end will hit the code here. We only
            # need to send one TerminatedEvent() for whichever was first.
            self.send_to_client(dap.TerminatedEvent())
            self._terminated_sent = True

    def send_to_client(
        self,
        msg: dap.ProtocolMessage,
    ) -> int:
        stdout = sys.stdout.buffer

        req_no = self._adapter.queue_msg(msg)
        data = self._adapter.data_to_send() or b""
        if log.isEnabledFor(logging.DEBUG):
            log.debug("STDOUT: %s", data.decode())

        stdout.write(data)
        stdout.flush()

        if isinstance(msg, dap.Response):
            self._incoming_requests.pop(msg.request_seq, None)

        return req_no

    def _send_disconnect(
        self,
        msg: dap.DisconnectRequest,
        debuggee: MPQueue,
    ) -> None:
        try:
            debuggee.send(msg)
        except OSError:
            # The debuggee might have been disconnected during the send.
            pass

        # No response is sent back to the client, is it done as part of the
        # shutdown to ensure it's sent before the TerminatedEvent.

    @functools.singledispatchmethod
    def _process_msg(self, msg: dap.ProtocolMessage) -> None:
        # This should never happen.
        raise NotImplementedError(f"Debug Adapter does not support the {type(msg).__name__} message")

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
                    # We could support suspend for debug in an attach but
                    # launch is harder as nothing can reattach to it. I'm not
                    # aware of any way to set this conditionally for the
                    # request so it's kept False for now.
                    supports_suspend_debuggee=False,
                    supports_terminate_debuggee=True,
                    supports_terminate_request=True,
                ),
            )
        )

    @_process_msg.register
    def _(self, msg: dap.AttachRequest) -> None:
        attach_args = AttachArguments.from_json(msg.arguments)
        addr, use_tls = attach_args.get_connection_tuple()

        ssl_context = None
        if use_tls:
            ssl_context = create_client_tls_context(
                attach_args.tls_verification,
                certfile=attach_args.tls_cert,
                keyfile=attach_args.tls_key,
                password=attach_args.tls_key_password,
            )

        self._debuggee = ClientMPQueue(
            addr,
            proto=lambda: self._proto,
            ssl_context=ssl_context,
        )

        self._debuggee.start(timeout=attach_args.connect_timeout)
        self.send_to_client(dap.AttachResponse(request_seq=msg.seq))
        self._debuggee.send(
            dap.OutputEvent(
                category=DebugConfiguration.OUTPUT_CATEGORY,
                output="",
                data=DebugConfiguration(path_mappings=attach_args.path_mappings),
            )
        )

    @_process_msg.register
    def _(self, msg: dap.LaunchRequest) -> None:
        launch_args = LaunchArguments.from_json(msg.arguments)

        self._debuggee = ServerMPQueue(
            "uds://",
            proto=lambda: self._proto,
        )

        ansibug_args = [
            "-m",
            "ansibug",
            "connect",
            "--addr",
            self._debuggee.address,
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

        # This is used as an indicator to see whether the launched process has
        # ended or not before it had a chance to connect to our real socket. We
        # use a UDS because we can use select on it unlike files.
        self._launch_queue = ServerMPQueue("uds://", proto=MPProtocol)

        # A temp script is used that will clean itself up as well as signal
        # our launch_queue that it has exited. This has 2 benefits, the user
        # doesn't see the inner workings of ansibug and the
        # RunInTerminalResponse has a way of detecting if the shell script or
        # ansible failed or not before a timeout is hit.
        launch_script = """#!/bin/sh
set -e

cleanup () {{
    SN="{sock_name}"
    {python} -c "
import base64
import socket

n = base64.b64decode('${{SN}}').decode()
try:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.connect(n)
except OSError:
    pass
"
}}

trap cleanup EXIT INT ABRT KILL TERM

rm -f "$0"
{python} {ansibug_args} "$@"
""".format(
            sock_name=base64.b64encode(self._launch_queue.address[6:].encode()).decode(),
            python=shlex.quote(sys.executable),
            ansibug_args=" ".join(shlex.quote(c) for c in ansibug_args),
        )

        # Default permissions are 0o600, we need the executable bit.
        launch_fd, launch_file = tempfile.mkstemp(prefix="ansibug-launch-")
        os.fchmod(launch_fd, 0o700)
        with os.fdopen(launch_fd, mode="w") as launch_writer:
            launch_writer.write(launch_script)

        log.debug("Created launch script at '%s' with\n%s", launch_file, launch_script)

        playbook_args = [launch_file, launch_args.playbook]
        playbook_args.extend(launch_args.args)

        req_no = self.send_to_client(
            dap.RunInTerminalRequest(
                cwd=launch_args.cwd,
                kind=launch_args.console,
                args=playbook_args,
                title="Ansible Debug Console",
                env=launch_args.env,
            )
        )
        # The remaining work is done in the RunInTerminalResponse from the
        # client, this stores the data needed for that to work.
        self._run_in_response_data[req_no] = _RunInTerminalDetails(
            request=msg,
            debuggee=self._debuggee,
            arguments=launch_args,
            launch_queue=self._launch_queue,
        )

    @_process_msg.register
    def _(self, msg: dap.RunInTerminalResponse) -> None:
        details = self._run_in_response_data.pop(msg.request_seq)

        try:
            details.debuggee.start(
                timeout=details.arguments.connect_timeout,
                cancel_queue=details.launch_queue,
            )

        except CancelledError:
            log.debug("Launch cancel socket was connected, launched process has ended")
            self.stop()

        else:
            log.debug("Ansible process is connected to debug adapter")
            details.launch_queue.stop()
            self._launch_queue = None

            self.send_to_client(dap.LaunchResponse(request_seq=details.request.seq))
            details.debuggee.send(
                dap.OutputEvent(
                    category=DebugConfiguration.OUTPUT_CATEGORY,
                    output="",
                    data=DebugConfiguration(path_mappings=details.arguments.path_mappings),
                )
            )
