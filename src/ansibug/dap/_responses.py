# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import typing as t

from ._messages import Command, Response, register_response
from ._types import (
    Breakpoint,
    Capabilities,
    Scope,
    StackFrame,
    Thread,
    Variable,
    VariablePresentationHint,
)


@register_response
@dataclasses.dataclass()
class CancelResponse(Response):
    """Response to the CancelRequest."""

    command = Command.CANCEL

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> CancelResponse:
        return CancelResponse(request_seq=request_seq)


@register_response
@dataclasses.dataclass()
class ConfigurationDoneResponse(Response):
    """Response to the ConfigurationDoneRequest."""

    command = Command.LAUNCH

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> ConfigurationDoneResponse:
        return ConfigurationDoneResponse(request_seq=request_seq)


@register_response
@dataclasses.dataclass()
class ContinueResponse(Response):
    """Response to the ContinueRequest."""

    command = Command.CONTINUE

    all_threads_continued: bool = True

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "allThreadsContinued": self.all_threads_continued,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> ContinueResponse:
        return ContinueResponse(
            request_seq=request_seq,
            all_threads_continued=body.get("allThreadsContinued", True),
        )


@register_response
@dataclasses.dataclass()
class DisconnectResponse(Response):
    """Response to the DisconnectRequest."""

    command = Command.DISCONNECT

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> DisconnectResponse:
        return DisconnectResponse(request_seq=request_seq)


@register_response
@dataclasses.dataclass()
class EvaluateResponse(Response):
    """Response to the EvaluateRequest."""

    command = Command.EVALUATE

    result: str
    type: t.Optional[str] = None
    presentation_hint: t.Optional[VariablePresentationHint] = None
    variables_reference: int = 0
    named_variables: t.Optional[int] = None
    indexed_variables: t.Optional[int] = None
    memory_reference: t.Optional[str] = None

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "result": self.result,
            "type": self.type,
            "presentationHint": self.presentation_hint.pack() if self.presentation_hint else None,
            "variablesReference": self.variables_reference,
            "namedVariables": self.named_variables,
            "indexedVariables": self.indexed_variables,
            "memoryReference": self.memory_reference,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> EvaluateResponse:
        return EvaluateResponse(
            request_seq=request_seq,
            result=body["result"],
            type=body.get("type", None),
            presentation_hint=VariablePresentationHint.unpack(body["presentationHint"])
            if "presentationHint" in body
            else None,
            variables_reference=body["variablesReference"],
            named_variables=body.get("namedVariables", None),
            indexed_variables=body.get("indexedVariables", None),
            memory_reference=body.get("memoryReference", None),
        )


@register_response
@dataclasses.dataclass()
class InitializeResponse(Response):
    """Response to InitializeRequest

    The reponse sent to the client of the InitializeRequest message.

    Args:
        capabilities: The DA capabilities.
    """

    command = Command.INITIALIZE

    capabilities: Capabilities

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = self.capabilities.pack()

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> InitializeResponse:
        return InitializeResponse(
            request_seq=request_seq,
            capabilities=Capabilities.unpack(body),
        )


@register_response
@dataclasses.dataclass()
class LaunchResponse(Response):
    """Response to a LaunchRequest."""

    command = Command.LAUNCH

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> LaunchResponse:
        return LaunchResponse(request_seq=request_seq)


@register_response
@dataclasses.dataclass()
class NextResponse(Response):
    """Response to a NextRequest."""

    command = Command.NEXT

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> NextResponse:
        return NextResponse(request_seq=request_seq)


@register_response
@dataclasses.dataclass()
class RunInTerminalResponse(Response):
    """Response to RunInTerminalRequest.

    The response to a RunInTerminalRequest. It is expected either process_id or
    shell_process_id is set, not both.

    Args:
        process_id: The process id
        shell_process_id: The process id of the terminal shell.
    """

    command = Command.RUN_IN_TERMINAL

    process_id: t.Optional[int]
    shell_process_id: t.Optional[int]

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "processId": self.process_id,
            "shellProcessId": self.shell_process_id,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> RunInTerminalResponse:
        return RunInTerminalResponse(
            request_seq=request_seq,
            process_id=body.get("processId", None),
            shell_process_id=body.get("shellProcessId", None),
        )


@register_response
@dataclasses.dataclass()
class ScopesResponse(Response):
    """Response to ScopesRequest.

    The response to ScopesRequest that requests the variable scopes for a given
    stackframe ID.

    Args:
        scopes: The variable scopes.
    """

    command = Command.SCOPES

    scopes: t.List[Scope] = dataclasses.field(default_factory=list)

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "scopes": [s.pack() for s in self.scopes],
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> ScopesResponse:
        return ScopesResponse(
            request_seq=request_seq,
            scopes=[Scope.unpack(s) for s in body["scopes"]],
        )


@register_response
@dataclasses.dataclass()
class SetBreakpointsResponse(Response):
    """Response to SetBreakpointsRequest.

    The response to SetBreakpointRequest that returns the information about
    all the breakpoints that were or were not set.

    Args:
        breakpoints: The breakpoints in the same order of the request and their
            status.
    """

    command = Command.SET_BREAKPOINTS

    breakpoints: t.List[Breakpoint] = dataclasses.field(default_factory=list)

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "breakpoints": [b.pack() for b in self.breakpoints],
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> SetBreakpointsResponse:
        return SetBreakpointsResponse(
            request_seq=request_seq,
            breakpoints=[Breakpoint.unpack(b) for b in body["breakpoints"]],
        )


@register_response
@dataclasses.dataclass()
class SetExceptionBreakpointsResponse(Response):
    """Response to SetExceptionBreakpointsRequest.

    This is the response to the SetExceptionBreakpointsRequest that contains
    the breakpoint information requested in the request. The breakpoints must
    be in the same order as the requested order.

    Args:
        breakpoints: The breakpoint information that was requested.
    """

    command = Command.SET_EXCEPTION_BREAKPOINTS

    breakpoints: t.List[Breakpoint] = dataclasses.field(default_factory=list)

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {"breakpoints": [b.pack() for b in self.breakpoints]}

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> SetExceptionBreakpointsResponse:
        return SetExceptionBreakpointsResponse(
            request_seq=request_seq,
            breakpoints=[Breakpoint.unpack(b) for b in body.get("breakpoints", [])],
        )


@register_response
@dataclasses.dataclass()
class SetVariableResponse(Response):
    """Response to SetVariableRequest."""

    command = Command.SET_VARIABLE

    value: str
    type: t.Optional[str] = None
    variables_reference: t.Optional[int] = None
    named_variables: t.Optional[int] = None
    indexed_variables: t.Optional[int] = None

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "value": self.value,
            "type": self.type,
            "variablesReference": self.variables_reference,
            "namedVariables": self.named_variables,
            "indexedVariables": self.indexed_variables,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> SetVariableResponse:
        return SetVariableResponse(
            request_seq=request_seq,
            value=body["value"],
            type=body.get("type", None),
            variables_reference=body.get("variablesReference", None),
            named_variables=body.get("namedVariables", None),
            indexed_variables=body.get("indexedVariables", None),
        )


@register_response
@dataclasses.dataclass()
class StackTraceResponse(Response):
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

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "stackFrames": [f.pack() for f in self.stack_frames],
            "totalFrames": self.total_frames,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> StackTraceResponse:
        return StackTraceResponse(
            request_seq=request_seq,
            stack_frames=[StackFrame.unpack(s) for s in body["stackFrames"]],
            total_frames=body.get("totalFrames", None),
        )


@register_response
@dataclasses.dataclass()
class StepInResponse(Response):
    """Response to a StepInRequest."""

    command = Command.STEP_IN

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> StepInResponse:
        return StepInResponse(request_seq=request_seq)


@register_response
@dataclasses.dataclass()
class StepOutResponse(Response):
    """Response to a StepOutRequest."""

    command = Command.STEP_OUT

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> StepOutResponse:
        return StepOutResponse(request_seq=request_seq)


@register_response
@dataclasses.dataclass()
class ThreadsResponse(Response):
    """Response to a ThreadsRequest.

    A response to a ThreadRequest that is sent to the client.

    Args:
        threads: The threads on the debuggee.
    """

    command = Command.THREADS

    threads: t.List[Thread] = dataclasses.field(default_factory=list)

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "threads": [t.pack() for t in self.threads],
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> ThreadsResponse:
        return ThreadsResponse(
            request_seq=request_seq,
            threads=[Thread.unpack(b) for b in body.get("threads", [])],
        )


@register_response
@dataclasses.dataclass()
class VariablesResponse(Response):
    """Response to a VariablesRequest.

    A response to a VariablesRequest that is sent to the client.

    Args:
        variables: The variables.
    """

    command = Command.VARIABLES

    variables: t.List[Variable] = dataclasses.field(default_factory=list)

    def pack(self) -> dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "variables": [v.pack() for v in self.variables],
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: dict[str, t.Any],
    ) -> VariablesResponse:
        return VariablesResponse(
            request_seq=request_seq,
            variables=[Variable.unpack(v) for v in body["variables"]],
        )
