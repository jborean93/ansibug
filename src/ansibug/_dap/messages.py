# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import enum
import json
import typing as t


def unpack_message(
    data: str,
) -> ProtocolMessage:
    obj = json.loads(data)
    obj_type = obj["type"]
    if obj_type == MessageType.REQUEST.value:
        return _unpack_request(obj)

    elif obj_type == MessageType.RESPONSE.value:
        return _unpack_response(obj)

    elif obj_type == MessageType.EVENT.value:
        return _unpack_event(obj)

    else:
        raise ValueError(f"Unknown DAP message type {obj_type}")


def _unpack_request(
    data: t.Dict[str, t.Any],
) -> Request:
    cmd = data["command"]
    request = {
        "seq": data["seq"],
    }
    if cmd == Command.INITIALIZE.value:
        return InitializeRequest.unpack(arguments=data["arguments"], **request)

    elif cmd == Command.LAUNCH.value:
        return LaunchRequest.unpack(arguments=data["arguments"], **request)

    else:
        raise ValueError(f"Unknown DAP request command {cmd}")


def _unpack_response(
    data: t.Dict[str, t.Any],
) -> Response:
    cmd = data["command"]
    response = {
        "seq": data["seq"],
        "request_seq": data["request_seq"],
        "success": data["success"],
        "message": data.get("message", None),
    }
    if cmd == Command.RUN_IN_TERMINAL.value:
        return RunInTerminalResponse.unpack(body=data["body"], **response)

    raise ValueError(f"Unknown DAP response command {cmd}")


def _unpack_event(
    data: t.Dict[str, t.Any],
) -> Event:
    event_type = data["event"]

    raise ValueError(f"Unknown DAP event type {event_type}")


class MessageType(enum.Enum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"


class Command(enum.Enum):
    CANCEL = "cancel"
    INITIALIZE = "initialize"
    LAUNCH = "launch"
    RUN_IN_TERMINAL = "runInTerminal"


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


@dataclasses.dataclass(frozen=True)
class ProtocolMessage:
    seq: int
    message_type: MessageType = dataclasses.field(init=False)

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        obj.update(
            {
                "seq": self.seq,
                "type": self.message_type.value,
            }
        )


@dataclasses.dataclass(frozen=True)
class Request(ProtocolMessage):
    message_type = MessageType.REQUEST

    command: Command = dataclasses.field(init=False)

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)
        obj.update(
            {
                "command": self.command.value,
            }
        )


@dataclasses.dataclass(frozen=True)
class Event(ProtocolMessage):
    message_type = MessageType.EVENT

    event: str
    body: t.Any = dataclasses.field(default=None)

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)
        obj.update(
            {
                "event": self.event,
                "body": self.body,
            }
        )


@dataclasses.dataclass(frozen=True)
class Response(ProtocolMessage):
    message_type = MessageType.RESPONSE

    command: Command = dataclasses.field(init=False)
    request_seq: int
    success: bool
    message: t.Optional[str]

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)
        obj.update(
            {
                "request_seq": self.request_seq,
                "success": self.success,
                "command": self.command.value,
                "message": self.message,
            }
        )


@dataclasses.dataclass(frozen=True)
class CancelRequest(Request):
    command = Command.CANCEL

    request_id: t.Optional[int] = dataclasses.field(default=None)
    progress_id: t.Optional[int] = dataclasses.field(default=None)

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)
        obj.update(
            {
                "arguments": {
                    "requestId": self.request_id,
                    "progressId": self.progress_id,
                }
            }
        )


@dataclasses.dataclass(frozen=True)
class InitializeRequest(Request):
    command = Command.INITIALIZE

    adapter_id: str
    client_id: t.Optional[str] = dataclasses.field(default=None)
    client_name: t.Optional[str] = dataclasses.field(default=None)
    locale: t.Optional[str] = dataclasses.field(default=None)
    lines_start_at_1: bool = dataclasses.field(default=True)
    columns_start_at_1: bool = dataclasses.field(default=True)
    path_format: t.Literal["path", "uri"] = dataclasses.field(default="path")
    supports_variable_type: bool = dataclasses.field(default=False)
    supports_variable_paging: bool = dataclasses.field(default=False)
    supports_run_in_terminal_request: bool = dataclasses.field(default=False)
    supports_memory_references: bool = dataclasses.field(default=False)
    supports_progress_reporting: bool = dataclasses.field(default=False)
    supports_invalidated_event: bool = dataclasses.field(default=False)
    supports_memory_event: bool = dataclasses.field(default=False)

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)
        obj.update(
            {
                "arguments": {
                    "clientID": self.client_id,
                    "clientName": self.client_name,
                    "adapterID": self.adapter_id,
                    "locale": self.locale,
                    "linesStartAt1": self.lines_start_at_1,
                    "columnsStartAt1": self.columns_start_at_1,
                    "pathFormat": self.path_format,
                    "supportsVariableType": self.supports_variable_type,
                    "supportsVariablePaging": self.supports_variable_paging,
                    "supportsRunInTerminalRequest": self.supports_run_in_terminal_request,
                    "supportsMemoryReferences": self.supports_memory_references,
                    "supportsProgressReporting": self.supports_progress_reporting,
                    "supportsInvalidatedEvent": self.supports_invalidated_event,
                    "supportsMemoryEvent": self.supports_memory_event,
                }
            }
        )

    @classmethod
    def unpack(
        cls,
        seq: int,
        arguments: t.Dict[str, t.Any],
    ) -> InitializeRequest:
        return InitializeRequest(
            seq=seq,
            adapter_id=arguments["adapterID"],
            client_id=arguments.get("clientID", None),
            client_name=arguments.get("clientName", None),
            locale=arguments.get("locale", None),
            lines_start_at_1=arguments.get("linesStartAt1", True),
            columns_start_at_1=arguments.get("columnsStartAt1", True),
            path_format=arguments.get("pathFormat", "path"),
            supports_variable_type=arguments.get("supportsVariableType", False),
            supports_variable_paging=arguments.get("supportsVariablePaging", False),
            supports_run_in_terminal_request=arguments.get("supportsRunInTerminalRequest", False),
            supports_memory_references=arguments.get("supportsMemoryReferences", False),
            supports_progress_reporting=arguments.get("supportsProgressReporting", False),
            supports_invalidated_event=arguments.get("supportsInvalidatedEvent", False),
            supports_memory_event=arguments.get("supportsMemoryEvent", False),
        )


@dataclasses.dataclass(frozen=True)
class InitializeResponse(Response):
    command = Command.INITIALIZE

    capabilities: Capabilities

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)

        obj.update(
            {
                "body": {},
            }
        )
        self.capabilities.pack(obj["body"])


@dataclasses.dataclass(frozen=True)
class LaunchRequest(Request):
    command = Command.LAUNCH

    arguments: t.Dict[str, t.Any]
    no_debug: bool = dataclasses.field(default=False)
    restart: t.Any = dataclasses.field(default=None)

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)
        args = self.arguments.copy()
        args["noDebug"] = self.no_debug
        args["__restart"] = self.restart

        obj.update({"arguments": args})

    @classmethod
    def unpack(
        cls,
        seq: int,
        arguments: t.Dict[str, t.Any],
    ) -> LaunchRequest:
        args = arguments.copy()
        no_debug = args.pop("noDebug", False)
        restart = args.pop("__restart", None)
        return LaunchRequest(
            seq=seq,
            arguments=args,
            no_debug=no_debug,
            restart=restart,
        )


@dataclasses.dataclass(frozen=True)
class LaunchResponse(Response):
    command = Command.LAUNCH


@dataclasses.dataclass(frozen=True)
class RunInTerminalRequest(Request):
    command = Command.RUN_IN_TERMINAL

    kind: t.Literal["integrated", "external"]
    cwd: str
    args: t.List[str] = dataclasses.field(default_factory=list)
    env: t.Dict[str, t.Optional[str]] = dataclasses.field(default_factory=dict)
    title: t.Optional[str] = dataclasses.field(default=None)

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)
        obj.update(
            {
                "arguments": {
                    "kind": self.kind,
                    "title": self.title,
                    "cwd": self.cwd,
                    "args": self.args,
                    "env": self.env,
                }
            }
        )


@dataclasses.dataclass(frozen=True)
class RunInTerminalResponse(Response):
    command = Command.RUN_IN_TERMINAL

    process_id: t.Optional[int]
    shell_process_id: t.Optional[int]

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        super().pack(obj)
        obj.update(
            {
                "body": {
                    "processId": self.process_id,
                    "shellProcessId": self.shell_process_id,
                }
            }
        )

    @classmethod
    def unpack(
        cls,
        seq: int,
        request_seq: int,
        success: bool,
        message: t.Optional[str],
        body: t.Dict[str, t.Any],
    ) -> RunInTerminalResponse:
        return RunInTerminalResponse(
            seq=seq,
            request_seq=request_seq,
            success=success,
            message=message,
            process_id=body.get("processId", None),
            shell_process_id=body.get("shellProcessId", None),
        )


@dataclasses.dataclass(frozen=True)
class Capabilities:
    supports_configuration_done_request: bool = dataclasses.field(default=False)

    def pack(
        self,
        obj: t.Dict[str, t.Any],
    ) -> None:
        obj.update(
            {
                "supportsConfigurationDoneRequest": self.supports_configuration_done_request,
            }
        )
