# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import enum
import typing as t

from ._messages import Event, EventType, register_event


class StoppedReason(enum.Enum):
    STEP = "step"
    BREAKPOINT = "breakpoint"
    EXCEPTION = "exception"
    PAUSE = "pause"
    ENTRY = "entry"
    GOTO = "goto"
    FUNCTION_BREAKPOINT = "function breakpoint"
    DATA_BREAKPOINT = "data breakpoint"
    INSTRUCTION_BREAKPOINT = "instruction breakpoint"


@register_event
@dataclasses.dataclass()
class InitializedEvent(Event):
    """Indicate the DA is ready to accept configuration requests.

    A DA is expected to send this event when it is ready to accept
    configuration requests.
    """

    event = EventType.INITIALIZED

    @classmethod
    def unpack(cls) -> InitializedEvent:
        return InitializedEvent()


@register_event
@dataclasses.dataclass()
class StoppedEvent(Event):
    """Indicates debuggee has stopped due to some condition.

    Event sent by the debuggee that indicates it has stopped due to some
    condition, like a breakpoint, or a stepping request is completed.

    Args:
        reason: The reason for the event.
        description: Full reason, dispayed in the UI as is.
        thread_id: The thread which was stopped.
        preserve_focus_hint: The client should not change the focus.
        text: Additional information.
        all_threads_stopped: All threads are stopped and not just one.
        hit_breakpoint_ids: Ids of the breakpoints that triggers the event.
    """

    event = EventType.STOPPED

    reason: StoppedReason
    description: t.Optional[str] = None
    thread_id: t.Optional[int] = None
    preserve_focus_hint: bool = False
    text: t.Optional[str] = None
    all_threads_stopped: bool = False
    hit_breakpoint_ids: t.List[int] = dataclasses.field(default_factory=list)

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "reason": self.reason.value,
            "description": self.description,
            "threadId": self.thread_id,
            "preserveFocusHint": self.preserve_focus_hint,
            "text": self.text,
            "allThreadsStopped": self.all_threads_stopped,
            "hitBreakpointIds": self.hit_breakpoint_ids,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        body: t.Dict[str, t.Any],
    ) -> StoppedEvent:
        return StoppedEvent(
            reason=StoppedReason(body["reason"]),
            description=body.get("description", None),
            thread_id=body.get("threadId", None),
            preserve_focus_hint=body.get("preseveFocusHint", False),
            text=body.get("text", None),
            all_threads_stopped=body.get("allThreadStopped", False),
            hit_breakpoint_ids=body.get("hitBreakpointIds", []),
        )


@register_event
@dataclasses.dataclass()
class TerminatedEvent(Event):
    """Indicate the debuggee has terminated.

    Event sent by the DA that debugging of the gebuggee has terminated. This
    does not mean the debuggee itself has exited.
    """

    event = EventType.TERMINATED

    restart: t.Any = None

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "restart": self.restart,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        body: t.Dict[str, t.Any],
    ) -> TerminatedEvent:
        return TerminatedEvent(restart=body.get("restart", None))


@register_event
@dataclasses.dataclass()
class ExitedEvent(Event):

    event = EventType.EXITED

    exit_code: int

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["body"] = {
            "exitCode": self.exit_code,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        body: t.Dict[str, t.Any],
    ) -> ExitedEvent:
        return ExitedEvent(exit_code=body["exitCode"])
