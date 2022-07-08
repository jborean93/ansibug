# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import typing as t

from ._messages import Event, EventType, register_event


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
