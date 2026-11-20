# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import contextlib
import dataclasses
import enum
import fnmatch
import functools
import itertools
import json
import logging
import operator
import os
import pathlib
import queue
import re
import ssl
import threading
import traceback
import typing as t

from . import dap
from ._mp_queue import ClientMPQueue, MPProtocol, MPQueue, ServerMPQueue
from ._socket_helper import CancelledError, SocketCancellationToken

# Only used when debugging ansibug itself so it isn't a dependency.
try:  # pragma: nocover
    import debugpy  # pyright: ignore[reportMissingImports]

except Exception:  # pragma: nocover
    debugpy = None

log = logging.getLogger(__name__)


class DebuggeeShutdownError(Exception):
    """The debuggee is shutting down and no strategy will be available."""


class ExceptionBreakpointType(enum.Enum):
    """Known exception breakpoint filter type ids."""

    ON_ERROR = "on_error"
    ON_UNREACHABLE = "on_unreachable"
    ON_SKIPPED = "on_skipped"


@dataclasses.dataclass(frozen=True)
class PathMapping:
    """Maps a local path to the equivalent remote path."""

    local_root: str
    remote_root: str


@dataclasses.dataclass(frozen=True)
class DebugConfiguration:
    """Debug configuration data.

    Extra debug configuration data sent from the DA server after the debuggee
    has connected. This data is used to send extra data not defined in the
    debug adapter protocol needed for debug operations.

    Args:
        path_mappings: The path mappings to use when translating source paths
            with what Ansible is running with.
        supports_invalidated_event: The client set supportsInvalidatedEvent
            in its initialize request.
    """

    OUTPUT_CATEGORY: t.ClassVar[str] = "ansibug_debug_configuration"

    path_mappings: list[PathMapping] = dataclasses.field(default_factory=list)
    supports_invalidated_event: bool = False

    @classmethod
    def from_json(
        cls,
        data: dict[str, t.Any],
    ) -> DebugConfiguration:
        return DebugConfiguration(
            path_mappings=[
                PathMapping(local_root=m["local_root"], remote_root=m["remote_root"])
                for m in data.get("path_mappings", [])
            ],
            supports_invalidated_event=data.get("supports_invalidated_event", False),
        )

    def to_json(self) -> dict[str, t.Any]:
        return {
            "path_mappings": [dataclasses.asdict(m) for m in self.path_mappings],
            "supports_invalidated_event": self.supports_invalidated_event,
        }


@dataclasses.dataclass(frozen=True)
class PlaybookProcessInfo:
    pid: int
    address: str
    use_tls: bool
    playbook_file: str | None

    @classmethod
    def from_json(
        cls,
        data: dict[str, t.Any],
    ) -> PlaybookProcessInfo:
        return PlaybookProcessInfo(
            pid=data["pid"],
            address=data["address"],
            use_tls=data["use_tls"],
            playbook_file=data["playbook_file"],
        )

    def to_json(self) -> dict[str, t.Any]:
        return {
            "pid": self.pid,
            "address": self.address,
            "use_tls": self.use_tls,
            "playbook_file": self.playbook_file,
        }


def _replace_root(path: str, root: str, new_root: str) -> str | None:
    """Replaces root with new_root if path is under root, otherwise None.

    The root must match whole path segments so /foo does not match /foobar.
    Both separators are checked as the client could be on Windows.
    """
    if not path.startswith(root):
        return None

    rest = path[len(root) :]
    if rest and root[-1:] not in ("/", "\\") and rest[0] not in ("/", "\\"):
        return None

    return new_root + rest


_HIT_CONDITION_OPS: dict[str, t.Callable[[int, int], bool]] = {
    "==": operator.eq,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "%": lambda hits, n: hits % n == 0,
}


def parse_hit_condition(hit_condition: str) -> t.Callable[[int], bool] | None:
    """Parses a breakpoint hit condition.

    The condition is an optional operator ==, >, >=, <, <=, or % followed by
    a number. A number without an operator is the same as ==. For example
    '5' stops on the 5th hit, '>=5' on every hit from the 5th, and '%5' on
    every 5th hit.

    Returns:
        The function that checks the hit count or None if the condition is
        invalid.
    """
    match = re.fullmatch(r"\s*(==|>=|<=|>|<|%)?\s*(\d+)\s*", hit_condition)
    if not match or (match.group(1) == "%" and int(match.group(2)) == 0):
        return None

    op = _HIT_CONDITION_OPS[match.group(1) or "=="]
    value = int(match.group(2))
    return lambda hits: op(hits, value)


def get_pid_info_path(pid: int) -> pathlib.Path:
    """Get the path used to store info about the ansible-playbook debug proc."""
    # It is important that changes here are also reflected in the extension code
    # so that it knows where dir and what file pattern to look for when
    # scanning for available playbooks.
    tmpdir = os.environ.get("TMPDIR", "/tmp")
    return pathlib.Path(tmpdir) / f"ansibug-pid-{pid}"


class EndStrategy(Exception):
    """Exception used to end the strategy."""


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
        log.info("Processing msg %r", msg)
        try:
            self._debugger.process_message(msg)
        except Exception:
            log.exception("Exception while processing msg seq %d", msg.seq)

            # The DA Server will only ever send a Request msg here, this just
            # satisfies the type checker.
            req = t.cast(dap.Request, msg)
            resp = dap.ErrorResponse(
                command=req.command,
                request_seq=req.seq,
                message=f"Critical Debuggee exception received\n{traceback.format_exc()}",
            )
            self._debugger.queue_msg(resp)

    def connection_closed(
        self,
        exp: Exception | None,
    ) -> None:
        if exp:
            msg = "".join(traceback.format_exception(None, exp, exp.__traceback__))
            log.info("Socket connection failed with\n%s", msg)

        # This ensures we don't get stuck waiting for this same thread to finish.
        self._debugger.shutdown(join=False)


class DebugState(t.Protocol):
    def continue_request(
        self,
        request: dap.ContinueRequest,
    ) -> None:
        raise NotImplementedError()  # pragma: nocover

    def disconnect(
        self,
        request: dap.DisconnectRequest,
    ) -> None:
        raise NotImplementedError()  # pragma: nocover

    def completions(
        self,
        request: dap.CompletionsRequest,
    ) -> dap.CompletionsResponse:
        raise NotImplementedError()  # pragma: nocover

    def evaluate(
        self,
        request: dap.EvaluateRequest,
    ) -> dap.EvaluateResponse | dap.ErrorResponse:
        raise NotImplementedError()  # pragma: nocover

    def exception_info(
        self,
        request: dap.ExceptionInfoRequest,
    ) -> dap.ExceptionInfoResponse | dap.ErrorResponse:
        raise NotImplementedError()  # pragma: nocover

    def get_scopes(
        self,
        request: dap.ScopesRequest,
    ) -> dap.ScopesResponse:
        raise NotImplementedError()  # pragma: nocover

    def get_stacktrace(
        self,
        request: dap.StackTraceRequest,
    ) -> dap.StackTraceResponse:
        raise NotImplementedError()  # pragma: nocover

    def get_threads(
        self,
        request: dap.ThreadsRequest,
    ) -> dap.ThreadsResponse:
        raise NotImplementedError()  # pragma: nocover

    def get_variables(
        self,
        request: dap.VariablesRequest,
    ) -> dap.VariablesResponse:
        raise NotImplementedError()  # pragma: nocover

    def set_variable(
        self,
        request: dap.SetVariableRequest,
    ) -> dap.SetVariableResponse | dap.ErrorResponse:
        raise NotImplementedError()  # pragma: nocover

    def pause(
        self,
        request: dap.PauseRequest,
    ) -> None:
        raise NotImplementedError()  # pragma: nocover

    def restart_frame(
        self,
        request: dap.RestartFrameRequest,
    ) -> dap.ErrorResponse | None:
        raise NotImplementedError()  # pragma: nocover

    def step_in(
        self,
        request: dap.StepInRequest,
    ) -> None:
        raise NotImplementedError()  # pragma: nocover

    def step_out(
        self,
        request: dap.StepOutRequest,
    ) -> None:
        raise NotImplementedError()  # pragma: nocover

    def step_over(
        self,
        request: dap.NextRequest,
    ) -> None:
        raise NotImplementedError()  # pragma: nocover


@dataclasses.dataclass
class AnsibleLineBreakpoint:
    id: int
    source: dap.Source
    source_breakpoint: dap.SourceBreakpoint
    breakpoint: dap.Breakpoint
    actual_path: str
    source_path: str
    hit_check: t.Callable[[int], bool] | None = None
    hit_count: int = 0

    @property
    def condition(self) -> str | None:
        return self.source_breakpoint.condition

    @property
    def log_message(self) -> str | None:
        return self.source_breakpoint.log_message


@dataclasses.dataclass
class AnsibleFunctionBreakpoint:
    id: int
    function_breakpoint: dap.FunctionBreakpoint
    hit_check: t.Callable[[int], bool] | None = None
    hit_count: int = 0

    @property
    def condition(self) -> str | None:
        return self.function_breakpoint.condition

    @property
    def log_message(self) -> str | None:
        return None


class AnsibleDebugger:
    """The debuggee side of the debug session, shutdown when used as a context manager."""

    def __init__(self) -> None:
        self._cancel_token = SocketCancellationToken()
        self._configuration_done = threading.Event()
        self._adapter_connected = False
        self._debug_config: DebugConfiguration = DebugConfiguration()
        self._proc_pid_file = get_pid_info_path(os.getpid())
        self._proto = DAProtocol(self)
        self._send_queue: queue.Queue[dap.ProtocolMessage | None] = queue.Queue()
        self._send_thread: threading.Thread | None = None
        self._strategy_connected = threading.Condition()
        self._strategy: DebugState | None = None
        self._terminated = False
        self._shutting_down = False
        # The InitializedEvent asks the client for its breakpoints, see
        # _initialize_when_ready() for when it is sent.
        self._init_lock = threading.Lock()
        self._playbook_loaded = False
        self._config_received = False
        self._initialized_sent = False
        # Set in listen mode, the pid file is rewritten once the playbook is known.
        self._proc_info: PlaybookProcessInfo | None = None

        # Ids are allocated from both the strategy and the recv thread.
        self._thread_counter = itertools.count(2)  # 1 is always the main thread
        self._stackframe_counter = itertools.count(1)
        self._variable_counter = itertools.count(1)

        # Stores all the client breakpoints, key is the breakpoint number/id
        # The enabled exception filter ids and their optional condition.
        self._exception_filters: dict[str, str | None] = {}
        self._breakpoints: dict[int, AnsibleLineBreakpoint] = {}
        self._breakpoint_counter = itertools.count(1)
        self._function_breakpoints: list[AnsibleFunctionBreakpoint] = []
        # Guards _breakpoints and _source_info which are used by both the
        # strategy and the recv thread.
        self._breakpoint_lock = threading.Lock()

        # Key is the path, the value is a list of the lines in that file where:
        #   None - Line is a continuation of a breakpoint range
        #   0    - Line is not something a breakpoint can be set at.
        #   1    - Line is the start of a breakpoint range
        #
        # The lines are 1 based with the 0 index representing 0 meaning a
        # breakpoint cannot be set until the first valid entry is found. A
        # continuation means the behaviour of the previous int in the list
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
        self._source_info: dict[str, list[int | None]] = {}

    @property
    def adapter_connected(self) -> bool:
        return self._adapter_connected

    @property
    def supports_invalidated_event(self) -> bool:
        """The client can be sent an InvalidatedEvent."""
        return self._debug_config.supports_invalidated_event

    def get_exception_filter(
        self,
        filter_type: ExceptionBreakpointType,
    ) -> tuple[bool, str | None]:
        """Gets whether the exception filter is enabled and its condition."""
        filters = self._exception_filters
        return filter_type.value in filters, filters.get(filter_type.value)

    @contextlib.contextmanager
    def with_strategy(
        self,
        strategy: DebugState,
    ) -> collections.abc.Generator[None, None, None]:
        """Sets the current strategy.

        Sets the current strategy that is being used by Ansible. This is used
        as a way to route any requests to the strategy for it to handle
        accordingly.

        Args:
            strategy: The strategy to set.
        """
        with self._strategy_connected:
            self._strategy = strategy
            self._strategy_connected.notify_all()

        try:
            yield

        finally:
            with self._strategy_connected:
                self._strategy = None
                self._strategy_connected.notify_all()

    def next_thread_id(self) -> int:
        return next(self._thread_counter)

    def next_stackframe_id(self) -> int:
        return next(self._stackframe_counter)

    def next_variable_id(self) -> int:
        return next(self._variable_counter)

    def wait_for_config_done(
        self,
        timeout: float | None,
    ) -> None:
        """Waits until the debug config is done.

        Waits until the client has sent through the configuration done request
        that indicates no more initial configuration data is expected.

        Args:
            timeout: The maximum time, in seconds, to wait until the debug
                adapter is connected and ready.
        """
        self._configuration_done.wait(timeout=timeout)

    def get_breakpoint(
        self,
        path: str,
        line: int,
    ) -> AnsibleLineBreakpoint | None:
        """Gets the breakpoint for the path/line specified.

        Checks to see if there is a breakpoint set for the path and line that
        is requested. If no breakpoint is associated with the arguments then
        None will be returned.

        Args:
            path: The path of the file to check.
            line: The line in the file to check.

        Returns:
            Optional[AnsibleLineBreakpoint]: The breakpoint associated with the
            args if present.
        """
        with self._breakpoint_lock:
            for b in self._breakpoints.values():
                if (
                    b.actual_path == path
                    and (b.breakpoint.line is None or b.breakpoint.line <= line)
                    and (b.breakpoint.end_line is None or b.breakpoint.end_line >= line)
                ):
                    return b

        return None

    def get_function_breakpoint(
        self,
        names: collections.abc.Iterable[str],
    ) -> AnsibleFunctionBreakpoint | None:
        """Gets the first function breakpoint whose name glob matches a name.

        Args:
            names: The task names and module names to match.

        Returns:
            Optional[AnsibleFunctionBreakpoint]: The matching breakpoint.
        """
        with self._breakpoint_lock:
            function_breakpoints = self._function_breakpoints

        names = list(names)
        for b in function_breakpoints:
            if any(fnmatch.fnmatchcase(n, b.function_breakpoint.name) for n in names):
                return b

        return None

    def start(
        self,
        addr: str,
        mode: t.Literal["connect", "listen"],
        *,
        ssl_context: ssl.SSLContext | None = None,
        connect_timeout: float = 0,
    ) -> str:
        """Start the background server thread.

        Starts the background server thread which starts the debuggee socket
        with the debug adapter server. The InitializedEvent is sent once the
        debug adapter has connected and playbook_loaded() has been called.

        In connect mode the connection is made before this returns so a
        failure to connect is raised to the caller.

        Args:
            addr: The socket address to connect/bind.
            mode: The socket mode to use, connect will connect to the addr
                while listen will bind to the addr and wait for a connection.
            ssl_context: Optional client SSLContext to wrap the socket
                connection with.
            connect_timeout: The timeout, in seconds, to connect in connect
                mode, 0 waits forever.

        returns:
            str: The socket address that is being used, this is only valid when
            using listen mode.
        """
        log.info("Setting up ansible-playbook debug %s socket at '%s'", mode, addr)

        queue_kwargs: dict[str, t.Any] = {
            "address": addr,
            "proto": lambda: self._proto,
            "ssl_context": ssl_context,
            "cancel_token": self._cancel_token,
        }

        mp_queue: MPQueue
        if mode == "connect":
            mp_queue = ClientMPQueue(**queue_kwargs)
            addr = mp_queue.address
            mp_queue.start(timeout=connect_timeout)
            self._adapter_connected = True

        else:
            mp_queue = ServerMPQueue(**queue_kwargs)
            addr = mp_queue.address

            self._proc_info = PlaybookProcessInfo(
                pid=os.getpid(),
                address=addr,
                use_tls=ssl_context is not None,
                playbook_file=None,
            )
            self._write_pid_file(self._proc_info)

        log.debug("MPQueue set on address %s", addr)

        self._send_thread = threading.Thread(
            target=self._send_task,
            args=(mp_queue,),
            name="ansibug-debugger",
            # Daemon so a stuck send thread can't block the interpreter exit.
            daemon=True,
        )
        self._send_thread.start()

        return addr

    def playbook_loaded(
        self,
        playbook_file: str | None,
    ) -> None:
        """Called once each playbook has been loaded and its breakpoints registered.

        Args:
            playbook_file: The playbook path, stored in the pid file on listen.
        """
        if playbook_file and self._proc_info:
            self._proc_info = dataclasses.replace(self._proc_info, playbook_file=playbook_file)
            self._write_pid_file(self._proc_info)

        self._initialize_when_ready(playbook_loaded=True)

    def __enter__(self) -> AnsibleDebugger:
        return self

    def __exit__(self, *_args: object) -> None:
        try:
            self.shutdown()
        except Exception:
            # Don't replace the exception or exit code from Ansible with a
            # failure to clean up.
            log.exception("Failed to shutdown the debugger")

    def shutdown(
        self,
        join: bool = True,
    ) -> None:
        """Shutdown the Debuggee.

        Marks the debuggee as completed and signals the send thread to
        shutdown.

        Args:
            join: Wait for the send thread to stop, set to False when called
                from the socket recv thread which the send thread joins.
        """
        log.debug("Shutting down DebugServer")

        # Wake up any request waiting in _get_strategy so the recv thread can
        # exit, no new strategy will be set once we are shutting down.
        with self._strategy_connected:
            self._shutting_down = True
            self._strategy_connected.notify_all()

        if self._send_thread:
            # If we aren't connected we need to cancel the queue start method
            # before trying to join the thread. If we are connected we want to
            # add None to the queue for the thread to exit gracefully once all
            # messages have been sent.
            if not self._adapter_connected:
                self._cancel_token.cancel()

            self.queue_msg(None)
            if join:
                # The thread is a daemon so don't block the exit if it is stuck.
                self._send_thread.join(timeout=5)
                if self._send_thread.is_alive():
                    log.warning("Timed out waiting for the debuggee send thread to stop")
                self._send_thread = None

        # If the strategy is still running we don't want it to fire on any
        # breakpoints and our debug config no longer applies
        self._debug_config = DebugConfiguration()
        self._breakpoints = {}
        self._function_breakpoints = []

        # Ensure the strategy isn't stuck waiting for this
        self._configuration_done.set()

        # Ensure the strategy isn't waiting for a response to anything
        with self._strategy_connected:
            if self._strategy and not self._terminated:
                self._strategy.disconnect(
                    dap.DisconnectRequest(
                        restart=False,
                        terminate_debuggee=False,
                        suspend_debuggee=False,
                    )
                )

        self._proc_pid_file.unlink(missing_ok=True)

        log.debug("DebugServer is shutdown")

    def queue_msg(
        self,
        msg: dap.ProtocolMessage | None,
    ) -> None:
        """Queues a message to send to the debug adapter.

        Adds the message to the send queue for the send thread to send to the
        debug adapter.

        Args:
            msg: The message to send.
        """
        # Nothing will drain the queue once the send thread has ended.
        if self._send_thread and self._send_thread.is_alive():
            self._send_queue.put(msg)

    def convert_to_client_path(
        self,
        path: str,
    ) -> str:
        """Converts the path to the client path.

        Converts the path provided to the client path equivalent based on the
        mappings provided. This is used in cases where the paths in the client
        does not match up with what Ansible is running with, for example
        debugging on a different host with a different path root.

        Args:
            path: The path to convert.

        Returns:
            str: The converted path.
        """
        for mapping in self._debug_config.path_mappings:
            if (client_path := _replace_root(path, mapping.remote_root, mapping.local_root)) is not None:
                return client_path

        return path

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
        with self._breakpoint_lock:
            file_lines = self._source_info.setdefault(path, [0])
            file_lines.extend([None] * (1 + line - len(file_lines)))
            file_lines[line] = bp_type

            for breakpoint in self._breakpoints.values():
                if breakpoint.actual_path != path:
                    continue

                source_breakpoint = breakpoint.source_breakpoint
                bp = self._calculate_breakpoint(
                    breakpoint.id,
                    breakpoint.source,
                    source_breakpoint.line,
                    file_lines,
                )

                if (
                    breakpoint.breakpoint.verified != bp.verified
                    or breakpoint.breakpoint.line != bp.line
                    or breakpoint.breakpoint.end_line != bp.end_line
                ):
                    breakpoint.breakpoint = bp
                    self.queue_msg(
                        dap.BreakpointEvent(
                            reason="changed",
                            breakpoint=bp,
                        )
                    )

    @classmethod
    def _enable_debugpy(cls) -> None:  # pragma: nocover
        """This is only meant for debugging ansibug in Ansible purposes."""
        if not debugpy:
            raise Exception("Failed to enable debugging because debugpy is not installed")

        elif not debugpy.is_client_connected():
            debugpy.listen(("localhost", 12535))
            debugpy.wait_for_client()

    def _get_strategy(self) -> DebugState:
        with self._strategy_connected:
            self._strategy_connected.wait_for(lambda: self._strategy is not None or self._shutting_down)
            if self._strategy is None:
                raise DebuggeeShutdownError("The debuggee is shutting down and cannot process the request")

            return self._strategy

    @functools.singledispatchmethod
    def process_message(
        self,
        msg: dap.ProtocolMessage,
    ) -> None:
        raise NotImplementedError(f"Debuggee does not support the {type(msg).__name__} message")

    @process_message.register
    def _(
        self,
        msg: dap.ConfigurationDoneRequest,
    ) -> None:
        resp = dap.ConfigurationDoneResponse(request_seq=msg.seq)
        self.queue_msg(resp)
        self._configuration_done.set()

    @process_message.register
    def _(
        self,
        msg: dap.ContinueRequest,
    ) -> None:
        strategy = self._get_strategy()
        # Queue the response before resuming so it is sent before any event
        # the resumed threads emit.
        self.queue_msg(dap.ContinueResponse(request_seq=msg.seq, all_threads_continued=not msg.single_thread))
        strategy.continue_request(msg)

    @process_message.register
    def _(
        self,
        msg: dap.DisconnectRequest,
    ) -> None:
        self._disconnect(msg)
        self.queue_msg(None)
        # The response is sent by the debug adapter.

    @process_message.register
    def _(
        self,
        msg: dap.EvaluateRequest,
    ) -> None:
        strategy = self._get_strategy()
        resp = strategy.evaluate(msg)
        self.queue_msg(resp)

    @process_message.register
    def _(
        self,
        msg: dap.CompletionsRequest,
    ) -> None:
        strategy = self._get_strategy()
        self.queue_msg(strategy.completions(msg))

    @process_message.register
    def _(
        self,
        msg: dap.ExceptionInfoRequest,
    ) -> None:
        strategy = self._get_strategy()
        self.queue_msg(strategy.exception_info(msg))

    @process_message.register
    def _(
        self,
        msg: dap.NextRequest,
    ) -> None:
        strategy = self._get_strategy()
        self.queue_msg(dap.NextResponse(request_seq=msg.seq))
        strategy.step_over(msg)

    @process_message.register
    def _(
        self,
        msg: dap.PauseRequest,
    ) -> None:
        strategy = self._get_strategy()
        # The StoppedEvent is sent once the thread reaches its next task.
        self.queue_msg(dap.PauseResponse(request_seq=msg.seq))
        strategy.pause(msg)

    @process_message.register
    def _(
        self,
        msg: dap.RestartFrameRequest,
    ) -> None:
        strategy = self._get_strategy()
        # On success the strategy queues the response itself before resuming
        # the thread so it is sent before the restart StoppedEvent.
        if err := strategy.restart_frame(msg):
            self.queue_msg(err)

    @process_message.register
    def _(
        self,
        msg: dap.ScopesRequest,
    ) -> None:
        strategy = self._get_strategy()
        resp = strategy.get_scopes(msg)
        self.queue_msg(resp)

    @process_message.register
    def _(
        self,
        msg: dap.SetExceptionBreakpointsRequest,
    ) -> None:
        # A client that supports filter options sends the enabled filters
        # there instead with the optional condition.
        filters: dict[str, str | None] = dict.fromkeys(msg.filters)
        for option in msg.filter_options:
            filters[option.filter_id] = option.condition or None
        self._exception_filters = filters

        resp = dap.SetExceptionBreakpointsResponse(request_seq=msg.seq)
        self.queue_msg(resp)

    @process_message.register
    def _(
        self,
        msg: dap.SetBreakpointsRequest,
    ) -> None:
        # FIXME: Deal with source_reference if set
        source_path = msg.source.path or ""
        actual_path = self._convert_to_ansible_path(source_path)

        # Held so a line registered by the strategy can't be missed between
        # reading _source_info and storing the new breakpoints.
        with self._breakpoint_lock:
            source_info = self._source_info.get(actual_path, None)

            # Clear out existing breakpoints for the source as each request should
            # send the latest list for a source. Build a new dict so the strategy
            # never sees it partially updated.
            breakpoints = {bpid: b for bpid, b in self._breakpoints.items() if b.source_path != source_path}

            breakpoint_info: list[dap.Breakpoint] = []
            for source_breakpoint in msg.breakpoints:
                bp_id = next(self._breakpoint_counter)

                hit_check = None
                if source_breakpoint.hit_condition and not (
                    hit_check := parse_hit_condition(source_breakpoint.hit_condition)
                ):
                    breakpoint_info.append(
                        dap.Breakpoint(
                            id=bp_id,
                            verified=False,
                            message=f"Invalid hit condition '{source_breakpoint.hit_condition}'.",
                            source=msg.source,
                            line=source_breakpoint.line,
                        )
                    )
                    continue

                bp: dap.Breakpoint
                if msg.source_modified:
                    bp = dap.Breakpoint(
                        id=bp_id,
                        verified=False,
                        message="Cannot set breakpoint on a modified source.",
                        source=msg.source,
                    )
                    # I don't think we need to preserve this bp for later reference.
                    breakpoint_info.append(bp)
                    continue

                if not source_info:
                    bp = dap.Breakpoint(
                        id=bp_id,
                        verified=False,
                        message="File has not been loaded by Ansible, cannot detect breakpoints yet.",
                        source=msg.source,
                        line=source_breakpoint.line,
                    )

                else:
                    bp = self._calculate_breakpoint(
                        bp_id,
                        msg.source,
                        source_breakpoint.line,
                        source_info,
                    )

                breakpoints[bp_id] = AnsibleLineBreakpoint(
                    id=bp_id,
                    source=msg.source,
                    source_breakpoint=source_breakpoint,
                    breakpoint=bp,
                    actual_path=actual_path,
                    source_path=source_path,
                    hit_check=hit_check,
                )
                breakpoint_info.append(bp)

            self._breakpoints = breakpoints

        resp = dap.SetBreakpointsResponse(
            request_seq=msg.seq,
            breakpoints=breakpoint_info,
        )
        self.queue_msg(resp)

    @process_message.register
    def _(
        self,
        msg: dap.SetFunctionBreakpointsRequest,
    ) -> None:
        function_breakpoints: list[AnsibleFunctionBreakpoint] = []
        breakpoint_info: list[dap.Breakpoint] = []
        for function_breakpoint in msg.breakpoints:
            bp_id = next(self._breakpoint_counter)

            hit_check = None
            if function_breakpoint.hit_condition and not (
                hit_check := parse_hit_condition(function_breakpoint.hit_condition)
            ):
                breakpoint_info.append(
                    dap.Breakpoint(
                        id=bp_id,
                        verified=False,
                        message=f"Invalid hit condition '{function_breakpoint.hit_condition}'.",
                    )
                )
                continue

            function_breakpoints.append(
                AnsibleFunctionBreakpoint(
                    id=bp_id,
                    function_breakpoint=function_breakpoint,
                    hit_check=hit_check,
                )
            )
            # The name is a glob matched against tasks as they run, it can't
            # be validated beforehand.
            breakpoint_info.append(dap.Breakpoint(id=bp_id, verified=True))

        with self._breakpoint_lock:
            self._function_breakpoints = function_breakpoints

        self.queue_msg(
            dap.SetFunctionBreakpointsResponse(
                request_seq=msg.seq,
                breakpoints=breakpoint_info,
            )
        )

    @process_message.register
    def _(
        self,
        msg: dap.SetVariableRequest,
    ) -> None:
        strategy = self._get_strategy()
        resp = strategy.set_variable(msg)
        self.queue_msg(resp)

    @process_message.register
    def _(
        self,
        msg: dap.StackTraceRequest,
    ) -> None:
        strategy = self._get_strategy()
        resp = strategy.get_stacktrace(msg)
        self.queue_msg(resp)

    @process_message.register
    def _(
        self,
        msg: dap.StepInRequest,
    ) -> None:
        strategy = self._get_strategy()
        self.queue_msg(dap.StepInResponse(request_seq=msg.seq))
        strategy.step_in(msg)

    @process_message.register
    def _(
        self,
        msg: dap.StepOutRequest,
    ) -> None:
        strategy = self._get_strategy()
        self.queue_msg(dap.StepOutResponse(request_seq=msg.seq))
        strategy.step_out(msg)

    @process_message.register
    def _(
        self,
        msg: dap.TerminateRequest,
    ) -> None:
        self._terminated = True
        self._disconnect(dap.DisconnectRequest(terminate_debuggee=True))
        self.queue_msg(dap.TerminateResponse(request_seq=msg.seq))
        self.queue_msg(None)

    @process_message.register
    def _(
        self,
        msg: dap.ThreadsRequest,
    ) -> None:
        strategy = self._get_strategy()
        resp = strategy.get_threads(msg)
        self.queue_msg(resp)

    @process_message.register
    def _(
        self,
        msg: dap.VariablesRequest,
    ) -> None:
        strategy = self._get_strategy()
        resp = strategy.get_variables(msg)
        self.queue_msg(resp)

    @process_message.register
    def _(
        self,
        msg: dap.OutputEvent,
    ) -> None:
        # This should always be this category as only the da server sends this
        # message to the debuggee.
        if msg.category != DebugConfiguration.OUTPUT_CATEGORY or not isinstance(msg.data, dict):  # pragma: nocover
            return

        self._debug_config = DebugConfiguration.from_json(t.cast(dict[str, t.Any], msg.data))

        self._initialize_when_ready(config_received=True)

    def _calculate_breakpoint(
        self,
        bp_id: int,
        bp_source: dap.Source,
        line: int,
        file_lines: list[int | None],
    ) -> dap.Breakpoint:
        """Builds a Breakpoint object based on the source provided and known file_lines."""
        start_line = min(line, len(file_lines) - 1)
        end_line = start_line + 1

        line_type = file_lines[start_line]
        while line_type is None:
            start_line -= 1
            line_type = file_lines[start_line]

        while end_line < len(file_lines) and file_lines[end_line] is None:
            end_line += 1

        end_line -= 1

        if line_type == 0:
            verified = False
            bp_msg = "Breakpoint cannot be set here."
        else:
            verified = True
            bp_msg = None

        return dap.Breakpoint(
            id=bp_id,
            verified=verified,
            message=bp_msg,
            source=bp_source,
            line=start_line,
            end_line=end_line,
        )

    def _convert_to_ansible_path(
        self,
        path: str,
    ) -> str:
        """Converts the client path to the path known to Ansible.

        This is the reverse of convert_to_client_path, the breakpoint and
        source info are keyed by the paths Ansible uses.
        """
        for mapping in self._debug_config.path_mappings:
            if (remote_path := _replace_root(path, mapping.local_root, mapping.remote_root)) is not None:
                return remote_path

        return path

    def _disconnect(
        self,
        msg: dap.DisconnectRequest,
    ) -> None:
        self._debug_config = DebugConfiguration()
        self._breakpoints = {}
        self._function_breakpoints = []

        # Don't wait for a strategy, none can start while the first strategy
        # run is blocked waiting for configuration done.
        with self._strategy_connected:
            strategy = self._strategy

        if strategy:
            strategy.disconnect(msg)
        else:
            self._configuration_done.set()

    def _initialize_when_ready(
        self,
        *,
        config_received: bool = False,
        playbook_loaded: bool = False,
    ) -> None:
        """Sends the InitializedEvent once both conditions are met.

        The debug config from the adapter (recv thread) and the playbook load
        (main thread) can happen in either order, whichever is last sends it.
        The breakpoints the client sends in reply need the config's path
        mappings and the loaded playbook to be validated. It is only sent
        once, later playbooks loading don't send it again.
        """
        with self._init_lock:
            self._config_received |= config_received
            self._playbook_loaded |= playbook_loaded
            send = self._config_received and self._playbook_loaded and not self._initialized_sent
            if send:
                self._initialized_sent = True

        if send:
            self.queue_msg(dap.InitializedEvent())

    def _send_task(
        self,
        mp_queue: MPQueue,
    ) -> None:
        """Debuggee send task

        This is the task that waits for the debug adapter to be connected to
        the socket and continuously sends the queued messages back to the
        adapter.

        Args:
            mp_queue: The queue to use for communication.
        """
        log.debug("Debuggee server send thread started")
        try:
            if not self._adapter_connected:
                mp_queue.start()
                log.debug("Debuggee socket is connected and ready for use.")
                self._adapter_connected = True

            while msg := self._send_queue.get():
                log.info("Sending to debug adapter %r", msg)
                mp_queue.send(msg)

        except CancelledError:
            pass

        except Exception:
            log.exception("Unknown error in Debuggee send thread")

        finally:
            mp_queue.stop()
            self._adapter_connected = False
            # Nothing can send configuration done anymore, don't block the
            # callback waiting for it.
            self._configuration_done.set()

        log.debug("Debuggee server send thread ended")

    def _write_pid_file(self, proc_info: PlaybookProcessInfo) -> None:
        # Replaced atomically as the client picker may read it at any time, the
        # dot prefix keeps the temp file out of its ansibug-pid-* glob.
        tmp_file = self._proc_pid_file.with_name(f".{self._proc_pid_file.name}.tmp")
        tmp_file.write_text(json.dumps(proc_info.to_json()))
        os.replace(tmp_file, self._proc_pid_file)
