# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import enum
import typing as t

from ._messages import Event, EventType
from ._types import Breakpoint, Source


class StoppedReason(enum.Enum):
    STEP = "step"
    BREAKPOINT = "breakpoint"
    EXCEPTION = "exception"
    PAUSE = "pause"
    RESTART = "restart"
    ENTRY = "entry"
    GOTO = "goto"
    FUNCTION_BREAKPOINT = "function breakpoint"
    DATA_BREAKPOINT = "data breakpoint"
    INSTRUCTION_BREAKPOINT = "instruction breakpoint"


@dataclasses.dataclass()
class BreakpointEvent(Event, dap={"body": {"reason": "reason", "breakpoint": "breakpoint"}}):
    """Indicate information about a breakpoint has changed.

    Event sent by the debuggee that indicates that some information about a
    breakpoint has changed.

    Args:
        reason: The reason for the breakpoint event.
        breakpoint: The id of this value is used to select the breakpoint on
            the client, the other values are used as the new information.
    """

    event = EventType.BREAKPOINT

    reason: str | t.Literal["changed", "new", "removed"]
    breakpoint: Breakpoint


@dataclasses.dataclass()
class ExitedEvent(Event, dap={"body": {"exitCode": "exit_code"}}):
    """Indicate the debuggee has existed.

    Event sent by the debuggee that indicates it has exited with the provided
    exit code.

    Args:
        exit_code: The exit code returned from the debuggee.
    """

    event = EventType.EXITED

    exit_code: int


@dataclasses.dataclass()
class InitializedEvent(Event):
    """Indicate the DA is ready to accept configuration requests.

    A DA is expected to send this event when it is ready to accept
    configuration requests.
    """

    event = EventType.INITIALIZED


@dataclasses.dataclass()
class OutputEvent(
    Event,
    dap={
        "body": {
            "category": "category",
            "output": "output",
            "group": "group",
            "variablesReference": "variables_reference",
            "source": "source",
            "line": "line",
            "column": "column",
            "data": "data",
        }
    },
):
    """Indicates that the target has produced some output.

    A debuggee is expected to send this event when it has produced some output
    for the client to process.

    Args:
        category: The output category.
        output: The output to report.
        group: The identifier for grouping related messages.
        variables_reference: Related variables.
        source: The source location where the output was produced.
        line: The source location's line where the output was produced.
        column: The source location's column where the output was produced.
        data: Additional data to report.
    """

    event = EventType.OUTPUT

    category: t.Literal["console", "important", "stdout", "stderr", "telemetry"] | str
    output: str
    group: t.Literal["start", "startCollapsed", "end"] | None = None
    variables_reference: int | None = None
    source: Source | None = None
    line: int | None = None
    column: int | None = None
    data: t.Any = None


@dataclasses.dataclass()
class StoppedEvent(
    Event,
    dap={
        "body": {
            "reason": "reason",
            "description": "description",
            "threadId": "thread_id",
            "preserveFocusHint": "preserve_focus_hint",
            "text": "text",
            "allThreadsStopped": "all_threads_stopped",
            "hitBreakpointIds": "hit_breakpoint_ids",
        },
    },
):
    """Indicates debuggee has stopped due to some condition.

    Event sent by the debuggee that indicates it has stopped due to some
    condition, like a breakpoint, or a stepping request is completed.

    Args:
        reason: The reason for the event.
        description: Full reason, displayed in the UI as is.
        thread_id: The thread which was stopped.
        preserve_focus_hint: The client should not change the focus.
        text: Additional information.
        all_threads_stopped: All threads are stopped and not just one.
        hit_breakpoint_ids: Ids of the breakpoints that triggers the event.
    """

    event = EventType.STOPPED

    reason: StoppedReason
    description: str | None = None
    thread_id: int | None = None
    preserve_focus_hint: bool = False
    text: str | None = None
    all_threads_stopped: bool = False
    hit_breakpoint_ids: list[int] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class TerminatedEvent(Event, dap={"body": {"restart": "restart"}}):
    """Indicate the debuggee has terminated.

    Event sent by the DA that debugging of the debuggee has terminated. This
    does not mean the debuggee itself has exited.

    Args:
        restart: Opaque values not used by the client associated with this
            terminated event.
    """

    event = EventType.TERMINATED

    restart: t.Any = None


@dataclasses.dataclass()
class ThreadEvent(Event, dap={"body": {"reason": "reason", "threadId": "thread_id"}}):
    """Indicate a thread has started or exited.

    Event sent by the debuggee that indicates the status of a thread.

    Args:
        reason: The reason for the event, either started or exited.
        thread_id: The thread id the event is associated with.
    """

    event = EventType.THREAD

    reason: t.Literal["started", "exited"]
    thread_id: int


@dataclasses.dataclass()
class InvalidatedEvent(
    Event,
    dap={
        "body": {
            "areas": "areas",
            "threadId": "thread_id",
            "stackFrameId": "stack_frame_id",
        }
    },
):
    """Signals that some state in the debug adapter has changed.

    The client should refetch the areas that were invalidated. This must only
    be sent if the client set supportsInvalidatedEvent in the initialize
    request.

    Args:
        areas: The areas that were invalidated, all areas if empty.
        thread_id: Only the thread with this id was invalidated.
        stack_frame_id: Only the stack frame with this id was invalidated.
    """

    event = EventType.INVALIDATED

    areas: list[t.Literal["all", "stacks", "threads", "variables"] | str] = dataclasses.field(default_factory=list)
    thread_id: int | None = None
    stack_frame_id: int | None = None
