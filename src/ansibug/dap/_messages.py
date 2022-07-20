# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import enum
import json
import typing as t

from ._types import Message

_REGISTRY_REQUEST: t.Dict[str, t.Callable[[t.Dict[str, t.Any]], Request]] = {}
_REGISTRY_RESPONSE: t.Dict[str, t.Callable[[int, t.Dict[str, t.Any]], Response]] = {}
_REGISTRY_EVENT: t.Dict[str, t.Callable[[t.Dict[str, t.Any]], Event]] = {}


def register_request(cls: t.Type[Request]) -> t.Type[Request]:
    _REGISTRY_REQUEST[cls.command.value] = cls.unpack  # type: ignore[attr-defined]  # Is defined
    return cls


def register_response(cls: t.Type[Response]) -> t.Type[Response]:
    _REGISTRY_RESPONSE[cls.command.value] = cls.unpack  # type: ignore[attr-defined]  # Is defined
    return cls


def register_event(cls: t.Type[Event]) -> t.Type[Event]:
    _REGISTRY_EVENT[cls.event.value] = cls.unpack  # type: ignore[attr-defined]  # Is defined
    return cls


def unpack_message(
    data: str,
) -> ProtocolMessage:
    """Unpack DAP json string.

    Unpacks the DAP json string into a structured object. If the type or the
    type's identifier is unknown then a ValueError is raised.

    Args:
        data: The json string to unpack.

    Returns:
        ProtocolMessage: The unpacked message.
    """
    obj = json.loads(data)
    obj_type = obj["type"]

    msg_type: t.Optional[t.Callable[..., ProtocolMessage]]
    if obj_type == MessageType.REQUEST.value:
        cmd = obj["command"]

        msg_type = _REGISTRY_REQUEST.get(cmd, None)
        if not msg_type:
            raise ValueError(f"Unknown DAP request command {cmd}")

        msg = msg_type(arguments=obj.get("arguments", {}))

    elif obj_type == MessageType.RESPONSE.value:
        cmd = obj["command"]
        request_seq = obj["request_seq"]
        success = obj["success"]
        body = obj.get("body", {})

        if success:
            msg_type = _REGISTRY_RESPONSE.get(cmd, None)
            if not msg_type:
                raise ValueError(f"Unknown DAP response command {cmd}")

            msg = msg_type(request_seq=request_seq, body=body)

        else:
            message = obj.get("message", None)
            error = body.get("error", None)
            msg = ErrorResponse(
                command=Command(cmd),
                request_seq=request_seq,
                message=message,
                error=Message.unpack(error) if error else None,
            )

    elif obj_type == MessageType.EVENT.value:
        event = obj["event"]

        msg_type = _REGISTRY_EVENT.get(event, None)
        if not msg_type:
            raise ValueError(f"Unknown DAP event type {event}")

        msg = msg_type(arguments=obj.get("arguments", {}))

    else:
        raise ValueError(f"Unknown DAP message type {obj_type}")

    msg.seq = obj["seq"]
    return msg


class MessageType(enum.Enum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"


class Command(enum.Enum):
    CANCEL = "cancel"
    CONFIGURATION_DONE = "configurationDone"
    CONTINUE = "continue"
    DISCONNECT = "disconnect"
    INITIALIZE = "initialize"
    LAUNCH = "launch"
    RUN_IN_TERMINAL = "runInTerminal"
    SET_BREAKPOINTS = "setBreakpoints"
    SET_EXCEPTION_BREAKPOINTS = "setExceptionBreakpoints"
    STACK_TRACE = "stackTrace"
    THREADS = "threads"
    SCOPES = "scopes"
    VARIABLES = "variables"


class EventType(enum.Enum):
    INITIALIZED = "initialized"
    STOPPED = "stopped"
    CONTINUED = "continued"
    EXITED = "exited"
    TERMINATED = "terminated"
    THREAD = "thread"
    OUTPUT = "output"
    BREAKPOINT = "breakpoint"
    MODULE = "module"
    LOADED_SOURCE = "loadedSource"
    PROCESS = "process"
    CAPABILITIES = "capabilities"
    PROGRESS_START = "progressStart"
    PROGRESS_UPDATE = "progressUpdate"
    PROGRESS_END = "progressEnd"
    INVALIDATED = "invalidated"
    MEMORY = "memory"


@dataclasses.dataclass()
class ProtocolMessage:
    """Base class for all DAP messages."""

    seq: int = dataclasses.field(init=False, default=0)
    message_type: MessageType = dataclasses.field(init=False)

    def pack(self) -> t.Dict[str, t.Any]:
        return {
            "seq": self.seq,
            "type": self.message_type.value,
        }


@dataclasses.dataclass()
class Request(ProtocolMessage):
    """Base class for DAP request messages."""

    message_type = MessageType.REQUEST

    command: Command = dataclasses.field(init=False)

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["command"] = self.command.value

        return obj


@dataclasses.dataclass()
class Event(ProtocolMessage):
    """Base class for DAP event messages."""

    message_type = MessageType.EVENT

    event: EventType = dataclasses.field(init=False)

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["event"] = self.event.value

        return obj


@dataclasses.dataclass()
class Response(ProtocolMessage):
    """Base class for DAP response messages."""

    message_type = MessageType.RESPONSE

    command: Command = dataclasses.field(init=False)
    request_seq: int

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj.update(
            {
                "request_seq": self.request_seq,
                "success": True,
                "command": self.command.value,
            }
        )

        return obj


@dataclasses.dataclass()
class ErrorResponse(Response):
    """Error response to client.

    Sent by the debug adapter to the client to provide more error details.

    Args:
        request_seq: The seq of the request this is responding to.
        command: The command of the request this is an error for.
        message: Error message in short form.
        error: Optional structured error message.
    """

    command: Command = dataclasses.field(init=True)
    message: t.Optional[str] = None
    error: t.Optional[Message] = None

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["success"] = False
        obj["message"] = self.message
        obj["body"] = {"error": self.error.pack() if self.error else None}

        return obj
