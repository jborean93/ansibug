# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import typing as t

from ._messages import Command, Response, register_response
from ._types import Breakpoint, Capabilities, Thread


@register_response
@dataclasses.dataclass()
class CancelResponse(Response):
    """Response to the CancelRequest."""

    command = Command.CANCEL

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: t.Dict[str, t.Any],
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
        body: t.Dict[str, t.Any],
    ) -> ConfigurationDoneResponse:
        return ConfigurationDoneResponse(request_seq=request_seq)


@register_response
@dataclasses.dataclass()
class DisconnectResponse(Response):
    """Response to the DisconnectRequest."""

    command = Command.DISCONNECT

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: t.Dict[str, t.Any],
    ) -> DisconnectResponse:
        return DisconnectResponse(request_seq=request_seq)


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

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = self.capabilities.pack()

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: t.Dict[str, t.Any],
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
        body: t.Dict[str, t.Any],
    ) -> LaunchResponse:
        return LaunchResponse(request_seq=request_seq)


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

    def pack(self) -> t.Dict[str, t.Any]:
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
        body: t.Dict[str, t.Any],
    ) -> RunInTerminalResponse:
        return RunInTerminalResponse(
            request_seq=request_seq,
            process_id=body.get("processId", None),
            shell_process_id=body.get("shellProcessId", None),
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

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "breakpoints": [b.pack() for b in self.breakpoints],
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: t.Dict[str, t.Any],
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

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {"breakpoints": [b.pack() for b in self.breakpoints]}

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: t.Dict[str, t.Any],
    ) -> SetExceptionBreakpointsResponse:
        return SetExceptionBreakpointsResponse(
            request_seq=request_seq,
            breakpoints=[Breakpoint.unpack(b) for b in body.get("breakpoints", [])],
        )


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

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "threads": [t.pack() for t in self.threads],
        }

        return obj

    @classmethod
    def unpack(
        cls,
        request_seq: int,
        body: t.Dict[str, t.Any],
    ) -> ThreadsResponse:
        return ThreadsResponse(
            request_seq=request_seq,
            threads=[Thread.unpack(b) for b in body.get("threads", [])],
        )
