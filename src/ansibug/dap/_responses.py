# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import typing as t

from ._messages import Command, Response
from ._types import (
    Breakpoint,
    Capabilities,
    Message,
    Scope,
    StackFrame,
    Thread,
    Variable,
    VariablePresentationHint,
)


@dataclasses.dataclass()
class AttachResponse(Response):
    """Response to the AttachRequest."""

    command = Command.ATTACH


@dataclasses.dataclass()
class CancelResponse(Response):
    """Response to the CancelRequest."""

    command = Command.CANCEL


@dataclasses.dataclass()
class ConfigurationDoneResponse(Response):
    """Response to the ConfigurationDoneRequest."""

    command = Command.CONFIGURATION_DONE


@dataclasses.dataclass()
class ContinueResponse(Response, dap={"body": {"allThreadsContinued": "all_threads_continued"}}):
    """Response to the ContinueRequest."""

    command = Command.CONTINUE

    all_threads_continued: bool = True


@dataclasses.dataclass()
class DisconnectResponse(Response):
    """Response to the DisconnectRequest."""

    command = Command.DISCONNECT


@dataclasses.dataclass()
class EvaluateResponse(
    Response,
    dap={
        "body": {
            "result": "result",
            "type": "type",
            "presentationHint": "presentation_hint",
            "variablesReference": "variables_reference",
            "namedVariables": "named_variables",
            "indexedVariables": "indexed_variables",
            "memoryReference": "memory_reference",
        }
    },
):
    """Response to the EvaluateRequest."""

    command = Command.EVALUATE

    result: str
    type: t.Optional[str] = None
    presentation_hint: t.Optional[VariablePresentationHint] = None
    variables_reference: int = 0
    named_variables: t.Optional[int] = None
    indexed_variables: t.Optional[int] = None
    memory_reference: t.Optional[str] = None


@dataclasses.dataclass()
class InitializeResponse(Response, dap={"body": "capabilities"}):
    """Response to InitializeRequest

    The response sent to the client of the InitializeRequest message.

    Args:
        capabilities: The DA capabilities.
    """

    command = Command.INITIALIZE

    capabilities: Capabilities


@dataclasses.dataclass()
class LaunchResponse(Response):
    """Response to a LaunchRequest."""

    command = Command.LAUNCH


@dataclasses.dataclass()
class NextResponse(Response):
    """Response to a NextRequest."""

    command = Command.NEXT


@dataclasses.dataclass()
class RunInTerminalResponse(Response, dap={"body": {"processId": "process_id", "shellProcessId": "shell_process_id"}}):
    """Response to RunInTerminalRequest.

    The response to a RunInTerminalRequest. It is expected either process_id or
    shell_process_id is set, not both.

    Args:
        process_id: The process id
        shell_process_id: The process id of the terminal shell.
    """

    command = Command.RUN_IN_TERMINAL

    process_id: t.Optional[int] = None
    shell_process_id: t.Optional[int] = None


@dataclasses.dataclass()
class ScopesResponse(Response, dap={"body": {"scopes": "scopes"}}):
    """Response to ScopesRequest.

    The response to ScopesRequest that requests the variable scopes for a given
    stackframe ID.

    Args:
        scopes: The variable scopes.
    """

    command = Command.SCOPES

    scopes: t.List[Scope] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class SetBreakpointsResponse(Response, dap={"body": {"breakpoints": "breakpoints"}}):
    """Response to SetBreakpointsRequest.

    The response to SetBreakpointRequest that returns the information about
    all the breakpoints that were or were not set.

    Args:
        breakpoints: The breakpoints in the same order of the request and their
            status.
    """

    command = Command.SET_BREAKPOINTS

    breakpoints: t.List[Breakpoint] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class SetExceptionBreakpointsResponse(Response, dap={"body": {"breakpoints": "breakpoints"}}):
    """Response to SetExceptionBreakpointsRequest.

    This is the response to the SetExceptionBreakpointsRequest that contains
    the breakpoint information requested in the request. The breakpoints must
    be in the same order as the requested order.

    Args:
        breakpoints: The breakpoint information that was requested.
    """

    command = Command.SET_EXCEPTION_BREAKPOINTS

    breakpoints: t.List[Breakpoint] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class SetVariableResponse(
    Response,
    dap={
        "body": {
            "value": "value",
            "type": "type",
            "variablesReference": "variables_reference",
            "namedVariables": "named_variables",
            "indexedVariables": "indexed_variables",
        }
    },
):
    """Response to SetVariableRequest."""

    command = Command.SET_VARIABLE

    value: str
    type: t.Optional[str] = None
    variables_reference: t.Optional[int] = None
    named_variables: t.Optional[int] = None
    indexed_variables: t.Optional[int] = None


@dataclasses.dataclass()
class StackTraceResponse(Response, dap={"body": {"stackFrames": "stack_frames", "totalFrames": "total_frames"}}):
    """Response to a StackTraceRequest.

    A response to a StackTraceRequest that returns the stack frames for the
    thread(s) requested.

    Args:
        stack_frames: The frames of the stack frame.
        total_frames: The total number of frames available in the stack.
    """

    command = Command.STACK_TRACE

    stack_frames: t.List[StackFrame] = dataclasses.field(default_factory=list)
    total_frames: t.Optional[int] = None


@dataclasses.dataclass()
class StepInResponse(Response):
    """Response to a StepInRequest."""

    command = Command.STEP_IN


@dataclasses.dataclass()
class StepOutResponse(Response):
    """Response to a StepOutRequest."""

    command = Command.STEP_OUT


@dataclasses.dataclass()
class TerminateResponse(Response):
    """Response to a TerminateRequest."""

    command = Command.TERMINATE


@dataclasses.dataclass()
class ThreadsResponse(Response, dap={"body": {"threads": "threads"}}):
    """Response to a ThreadsRequest.

    A response to a ThreadRequest that is sent to the client.

    Args:
        threads: The threads on the debuggee.
    """

    command = Command.THREADS

    threads: t.List[Thread] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class VariablesResponse(Response, dap={"body": {"variables": "variables"}}):
    """Response to a VariablesRequest.

    A response to a VariablesRequest that is sent to the client.

    Args:
        variables: The variables.
    """

    command = Command.VARIABLES

    variables: t.List[Variable] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class ErrorResponse(Response, dap={"message": "message", "body": {"error": "error"}}):
    """Error response to client.

    Sent by the debug adapter to the client to provide more error details.

    Args:
        request_seq: The seq of the request this is responding to.
        command: The command of the request this is an error for.
        message: Error message in short form.
        error: Optional structured error message.
    """

    success: bool = dataclasses.field(init=False, default=False)
    command: Command = dataclasses.field(init=True)
    message: t.Optional[str] = None
    error: t.Optional[Message] = None
