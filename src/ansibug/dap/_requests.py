# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import typing as t

from ._messages import Command, Request
from ._types import (
    ExceptionFilterOptions,
    ExceptionOptions,
    Source,
    SourceBreakpoint,
    StackFrameFormat,
    ValueFormat,
)


@dataclasses.dataclass()
class AttachRequest(Request, dap={"arguments": {"__restart": "restart"}}):
    """Attach DA to a debuggee that is already running.

    Sent from the client to the debug adapter to attach itself to a debuggee
    that is already running.

    Args:
        arguments: The arguments from the client, the structure of this is
            dependent on the client and what was requested.
        restart: Arbitrary data from the previous, restarted session.
    """

    command = Command.ATTACH

    arguments: t.Dict[str, t.Any]
    restart: t.Any = None

    def pack(self) -> dict[str, t.Any]:
        value = super().pack()
        value["arguments"].update(self.arguments)

        return value

    @classmethod
    def unpack(cls, data: dict[str, t.Any]) -> AttachRequest:
        arguments = data["arguments"]
        restart = arguments.pop("__restart", None)
        obj = AttachRequest(
            arguments=arguments,
            restart=restart,
        )
        object.__setattr__(obj, "seq", data["seq"])

        return obj


@dataclasses.dataclass()
class CancelRequest(Request, dap={"arguments": {"requestId": "request_id", "progressId": "progress_id"}}):
    """Cancel a request made by the client.

    Sent from the client to the debug adapter to cancel a request that it is
    no longer interested in or cancel a progress sequence.

    Args:
        request_id: The seq of the request to cancel. If no seq is specified
            then all are cancelled.
        progress_id: The seq of the progress to cancel.
    """

    command = Command.CANCEL

    request_id: t.Optional[int] = None
    progress_id: t.Optional[int] = None


@dataclasses.dataclass()
class ConfigurationDoneRequest(Request):
    """Client has finished initialization of the debug adapter.

    Sent by the client to signal it is done with the initial configuration of
    the debug adapter.
    """

    command = Command.CONFIGURATION_DONE


@dataclasses.dataclass()
class ContinueRequest(Request, dap={"arguments": {"threadId": "thread_id", "singleThread": "single_thread"}}):
    """Request execution to resume.

    Sent by the client to request the thread execution to resume.

    Args:
        thread_id: The thread to resume
        single_thread: Resume only the thread specified or all threads if
            False.
    """

    command = Command.CONTINUE

    thread_id: int
    single_thread: bool = True


@dataclasses.dataclass()
class DisconnectRequest(
    Request,
    dap={
        "arguments": {
            "restart": "restart",
            "terminateDebuggee": "terminate_debuggee",
            "suspendDebuggee": "suspend_debuggee",
        }
    },
):
    """Asks the DA to disconnect from the debuggee.

    Sent by the client to ask the DA to disconnect from the debuggee and
    end the debug session.

    Args:
        restart: This request is part of a restart sequence.
        terminate_debuggee: Indicates whether the debuggee should be terminated
            when the debugger is disconnected. If None the DA is free to do
            whatever it thinks is best.
        suspend_debuggee: Indicates whether the debuggee should stay suspended
            when the debugger is disconnected.
    """

    command = Command.DISCONNECT

    restart: bool = False
    terminate_debuggee: t.Optional[bool] = None
    suspend_debuggee: bool = False


@dataclasses.dataclass()
class EvaluateRequest(
    Request,
    dap={
        "arguments": {
            "expression": "expression",
            "frameId": "frame_id",
            "context": "context",
            "format": "format",
        }
    },
):
    """Evaluate given expression.

    Sent by the client to evaluate a given expression.

    Args:
        expression: THe expression to evaluate.
        frame_id: The expression in the scope of this stack frame. If not
            specified, the expression is evaluated in the global scope.
        context: The context in which the evaluate request is used.
        format: Details on how to format the result.
    """

    command = Command.EVALUATE

    expression: str
    frame_id: t.Optional[int] = None
    context: t.Optional[t.Union[str, t.Literal["variables", "watch", "repl", "hover", "clipboard"]]] = None
    format: t.Optional[ValueFormat] = None


@dataclasses.dataclass()
class InitializeRequest(
    Request,
    dap={
        "arguments": {
            "clientID": "client_id",
            "clientName": "client_name",
            "adapterID": "adapter_id",
            "locale": "locale",
            "linesStartAt1": "lines_start_at_1",
            "columnsStartAt1": "columns_start_at_1",
            "pathFormat": "path_format",
            "supportsVariableType": "supports_variable_type",
            "supportsVariablePaging": "supports_variable_paging",
            "supportsRunInTerminalRequest": "supports_run_in_terminal_request",
            "supportsMemoryReferences": "supports_memory_references",
            "supportsProgressReporting": "supports_progress_reporting",
            "supportsInvalidatedEvent": "supports_invalidated_event",
            "supportsMemoryEvent": "supports_memory_event",
        }
    },
):
    """Initialize DA with client capabilities.

    Send by the client to the debug adapter as the first message. It contains
    the capabilities of the client and expects the DA capabilities in the
    InitializeResponse.

    Args:
        adapter_id: The ID of the debug adapter.
        client_id: The ID of the client using this adapter.
        client_name: The name of the client using this adapter.
        locale: The ISO-639 locale of the client using this adapter.
        lines_start_at_1: All line numbers are 1-based, else 0-based.
        columns_start_at_1: All column numbers are 1-based, else 0-based.
        path_format: The format that paths are specified as.
        supports_variable_type: Client supports the optional type attribute for
            variables.
        supports_variable_paging: Client supports the paging of variables.
        supports_run_in_terminal_request: Client supports the
            RunInTerminalRequest.
        supports_memory_references: Client supports memory references.
        supports_progress_reporting: Client supports progress reporting.
        supports_invalidated_event: Client supports the invalidated event.
        supports_memory_event: Client supports the memory event.
    """

    command = Command.INITIALIZE

    adapter_id: str
    client_id: t.Optional[str] = None
    client_name: t.Optional[str] = None
    locale: t.Optional[str] = None
    lines_start_at_1: bool = True
    columns_start_at_1: bool = True
    path_format: t.Literal["path", "uri"] = "path"
    supports_variable_type: bool = False
    supports_variable_paging: bool = False
    supports_run_in_terminal_request: bool = False
    supports_memory_references: bool = False
    supports_progress_reporting: bool = False
    supports_invalidated_event: bool = False
    supports_memory_event: bool = False


@dataclasses.dataclass()
class LaunchRequest(Request, dap={"arguments": {"noDebug": "no_debug", "__restart": "restart"}}):
    """Request to start the debuggee with or without debugging.

    This is a request sent from the client to the debug adapter to start the
    debuggee with or without debugging.

    Args:
        arguments: The arguments from the client, the structure of this is
            dependent on the client and what was requested.
        no_debug: The program should launch without enabling debugging.
        restart: Optional data from the previous, restarted session.
    """

    command = Command.LAUNCH

    arguments: t.Dict[str, t.Any]
    no_debug: bool = False
    restart: t.Any = None

    def pack(self) -> dict[str, t.Any]:
        value = super().pack()
        value["arguments"].update(self.arguments)

        return value

    @classmethod
    def unpack(cls, data: dict[str, t.Any]) -> LaunchRequest:
        arguments = data["arguments"]
        no_debug = arguments.pop("noDebug", False)
        restart = arguments.pop("__restart", None)
        obj = LaunchRequest(
            arguments=arguments,
            no_debug=no_debug,
            restart=restart,
        )
        object.__setattr__(obj, "seq", data["seq"])

        return obj


@dataclasses.dataclass()
class NextRequest(
    Request,
    dap={
        "arguments": {
            "threadId": "thread_id",
            "singleThread": "single_thread",
            "granularity": "granularity",
        }
    },
):
    """Request to execute one step.

    This is a request sent from the client to the debug adapter to execute the
    next step and send a stop request.

    Args:
        thread_id: The thread for which to resume execution for one step.
        single_thread: All other suspended threads are not resumed.
        granularity: The granularity stepping.
    """

    command = Command.NEXT

    thread_id: int
    single_thread: bool = False
    granularity: t.Literal["statement", "line", "instruction"] = "statement"


@dataclasses.dataclass()
class RunInTerminalRequest(
    Request,
    dap={
        "arguments": {
            "kind": "kind",
            "title": "title",
            "cwd": "cwd",
            "args": "args",
            "env": "env",
        }
    },
):
    """Request from the debug adapter to run a command.

    This is a request from the debug adapter to the client to run a command in
    the client's terminal. This is typically used to launch the debuggee in a
    terminal provided by the client.

    Args:
        kind: The type of terminal to launch with.
        title: The title of the terminal.
        cwd: The working directory of the command.
        args: List of arguments, including the executable, to run the command
            with.
        env: Optional environment key-value pairs that are added to or removed
            from the default environment.
    """

    command = Command.RUN_IN_TERMINAL

    kind: t.Literal["integrated", "external"] = "integrated"
    title: t.Optional[str] = None
    cwd: str = ""
    args: t.List[str] = dataclasses.field(default_factory=list)
    env: t.Dict[str, t.Optional[str]] = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ScopesRequest(Request, dap={"arguments": {"frameId": "frame_id"}}):
    """Request variables scopes.

    Requests variable scopes for a given stackframe ID.

    Args:
        frame_id: The stackframe identifier to retrieve the scopes for.
    """

    command = Command.SCOPES

    frame_id: int


@dataclasses.dataclass
class SetBreakpointsRequest(
    Request,
    dap={
        "arguments": {
            "source": "source",
            "breakpoints": "breakpoints",
            "lines": "lines",
            "sourceModified": "source_modified",
        }
    },
):
    """Set breakpoint for a source.

    Used by the client to set breakpoints and clear any previous breakpoints
    for a source.

    Args:
        source: The source location of the breakpoints.
        breakpoints: The locations of the breakpoints in the source.
        lines: Deprecated but the lines in the source that are breakpoints.
        source_modified: Indicates the underlying source has been modified
            which results in new breakpoint locations.
    """

    command = Command.SET_BREAKPOINTS

    source: Source
    breakpoints: t.List[SourceBreakpoint] = dataclasses.field(default_factory=list)
    lines: t.List[int] = dataclasses.field(default_factory=list)
    source_modified: bool = False


@dataclasses.dataclass()
class SetExceptionBreakpointsRequest(
    Request,
    dap={
        "arguments": {
            "filters": "filters",
            "filterOptions": "filter_options",
            "exceptionOptions": "exception_options",
        }
    },
):
    """Configure exception breakpoint behavior.

    Sent by the client to configure the debugger's response to thrown
    exceptions.

    Args:
        filters: Set of exception filters by ID as specified by the
            Capabilities.exception_breakpoint_filters sent by the debug
            adapter.
        filter_options: List of exception filters and their options.
        exception_options: Configuration options for the selected exceptions.
    """

    command = Command.SET_EXCEPTION_BREAKPOINTS

    filters: t.List[str] = dataclasses.field(default_factory=list)
    filter_options: t.List[ExceptionFilterOptions] = dataclasses.field(default_factory=list)
    exception_options: t.List[ExceptionOptions] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class SetVariableRequest(
    Request,
    dap={
        "arguments": {
            "variablesReference": "variables_reference",
            "name": "name",
            "value": "value",
            "format": "format",
        }
    },
):
    """Set the variable with a new value.

    Sets a variable in a given context with a new value.

    Args:
        variables_reference: The variable container id.
        name: The name of the variable in the container.
        value: The value of the variable to set.
        format: Optional details on how the value is formatted.
    """

    command = Command.SET_VARIABLE

    variables_reference: int
    name: str
    value: str
    format: t.Optional[ValueFormat] = None


@dataclasses.dataclass()
class StackTraceRequest(
    Request,
    dap={
        "arguments": {
            "threadId": "thread_id",
            "startFrame": "start_frame",
            "levels": "levels",
            "format": "format",
        }
    },
):
    """Request a stacktrace.

    Sent by the client to request a stacktrace from the current execution
    state of a given thread.

    Args:
        thread_id: The stacktrace for this thread.
        start_frame: Index of the first frame to return.
        levels: The maximum number of frames to return.
        format: Details on how to format the stack frames.
    """

    command = Command.STACK_TRACE

    thread_id: int
    start_frame: t.Optional[int] = None
    levels: t.Optional[int] = None
    format: t.Optional[StackFrameFormat] = None


@dataclasses.dataclass()
class StepInRequest(
    Request,
    dap={
        "arguments": {
            "threadId": "thread_id",
            "singleThread": "single_thread",
            "targetId": "thread_id",
            "granularity": "granularity",
        }
    },
):
    """Request to step into a function/method.

    Sent by the client to request the given thread to step into a function
    and allows all other threads to run freely by resuming them.

    Args:
        thread_id: The thread for which to resume execution for on step into.
        single_thread: If True, all other suspended threads are not resumed.
        target_id: The id of the target to step into.
        granularity: Granularity level to step.
    """

    command = Command.STEP_IN

    thread_id: int
    single_thread: bool = False
    target_id: t.Optional[int] = None
    granularity: t.Literal["statement", "line", "instruction"] = "statement"


@dataclasses.dataclass()
class StepOutRequest(
    Request,
    dap={
        "arguments": {
            "threadId": "thread_id",
            "singleThread": "single_thread",
            "granularity": "granularity",
        }
    },
):
    """Request to ste out from a function/method.

    Sent by the client to request the given thread to step out of a function
    and allows all the other threads to run freely by resuming them.

    Args:
        thread_id: The thread for which to resume execution for one step out.
        single_thread: If True, all other suspended threads are not resumed.
        granularity: Granularity level to step.
    """

    command = Command.STEP_OUT

    thread_id: int
    single_thread: bool = False
    granularity: t.Literal["statement", "line", "instruction"] = "statement"


@dataclasses.dataclass()
class TerminateRequest(Request, dap={"arguments": {"restart": "restart"}}):
    """Request to gracefully terminate the debuggee.

    Request sent by the client to gracefully terminate the debuggee. This is
    sent before a DisconnectRequest as a second attempt if the terminate didn't
    occur.

    Args:
        restart: The request is part of a restart sequence.
    """

    command = Command.TERMINATE

    restart: bool = False


@dataclasses.dataclass()
class ThreadsRequest(Request):
    """Request to retrieve a list of all thread.

    Request sent by the client to retrieve all threads of the debuggee.
    """

    command = Command.THREADS


@dataclasses.dataclass()
class VariablesRequest(
    Request,
    dap={
        "arguments": {
            "variablesReference": "variables_reference",
            "filter": "filter",
            "start": "start",
            "count": "count",
            "format": "format",
        }
    },
):
    """Retrieves variables.

    Request sent by the client to retrieve all child variables for the given
    variable reference.

    Args:
        variables_reference: The reference id to retrieve.
        filter: Optionally filter child variables to either named or indexed
            variables.
        start: The index of the first variable to return.
        count: The number of variables to return or 0 for all.
        format: Details on how to format the variable values.
    """

    command = Command.VARIABLES

    variables_reference: int
    filter: t.Optional[t.Literal["indexed", "named"]] = None
    start: t.Optional[int] = None
    count: t.Optional[int] = None
    format: t.Optional[ValueFormat] = None
