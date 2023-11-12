# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import enum
import json
import queue
import sys
import typing as t


class MessageType(enum.Enum):
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"


class Command(enum.Enum):
    ATTACH = "attach"
    CANCEL = "cancel"
    CONFIGURATION_DONE = "configurationDone"
    CONTINUE = "continue"
    DISCONNECT = "disconnect"
    EVALUATE = "evaluate"
    INITIALIZE = "initialize"
    LAUNCH = "launch"
    NEXT = "next"
    RUN_IN_TERMINAL = "runInTerminal"
    SET_BREAKPOINTS = "setBreakpoints"
    SET_EXCEPTION_BREAKPOINTS = "setExceptionBreakpoints"
    SET_VARIABLE = "setVariable"
    STACK_TRACE = "stackTrace"
    STEP_IN = "stepIn"
    STEP_OUT = "stepOut"
    TERMINATE = "terminate"
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


class DAPEncoder(json.JSONEncoder):
    def default(self, obj: t.Any) -> t.Any:
        if isinstance(obj.__class__, DAPObjectMeta) and hasattr(obj, "pack"):
            return obj.pack()

        elif isinstance(obj, enum.Enum):
            return obj.value

        else:
            return str(obj)


def _parse_field_type(obj: type, value: str) -> t.Callable[[t.Any], t.Any] | None:
    base_globals = getattr(sys.modules.get(obj.__module__, None), "__dict__", {})
    base_locals = dict(vars(obj))
    evaled_type = eval(value, base_globals, base_locals)

    attr_type = None
    if isinstance(evaled_type, type):
        attr_type = evaled_type
    else:
        type_origin = t.get_origin(evaled_type)
        if type_origin is t.Union:
            union_types = t.get_args(evaled_type)
            if len(union_types) == 2 and type(None) in union_types:
                attr_type = union_types[0]
        elif type_origin is list:
            attr_type = t.get_args(evaled_type)[0]

    if not attr_type:
        return None

    elif isinstance(attr_type, type) and issubclass(attr_type, enum.Enum):
        return attr_type

    elif isinstance(attr_type, DAPObjectMeta) and (unpack := getattr(attr_type, "unpack")):
        return unpack

    else:
        return None


class DAPObjectMeta(type):
    EVENT_TYPE: type | None = None
    REQUEST_TYPE: type | None = None
    RESPONSE_TYPE: type | None = None
    REGISTRY: dict[str, dict[str, t.Callable[[dict[str, t.Any]], ProtocolMessage]]] = {
        MessageType.EVENT.value: {},
        MessageType.REQUEST.value: {},
        MessageType.RESPONSE.value: {},
    }

    def __new__(
        mcs: type[DAPObjectMeta],
        name: str,
        bases: tuple[type, ...],
        namespace: dict[str, t.Any],
        dap: dict[str, t.Any] | None = None,
    ) -> DAPObjectMeta:
        cls = super().__new__(mcs, name, bases, namespace)

        # Build the DAP key mapping dictionary for each type, merge it with the
        # base class definition.
        dap = dap or {}
        for base in reversed(bases):
            dap = getattr(base, "_dap", {}) | dap

        # We cannot refer to these types directly as they are created by this
        # metaclass, store them for easier referencing later.
        if name == "Event" and namespace["__module__"] == DAPObjectMeta.__module__:
            DAPObjectMeta.EVENT_TYPE = cls

        elif name == "Request" and namespace["__module__"] == DAPObjectMeta.__module__:
            DAPObjectMeta.REQUEST_TYPE = cls

        elif name == "Response" and namespace["__module__"] == DAPObjectMeta.__module__:
            DAPObjectMeta.RESPONSE_TYPE = cls

        setattr(cls, "_dap", dap)

        # Only add pack to the first class in inheritance.
        if "pack" not in cls.__dict__:
            setattr(cls, "pack", DAPObjectMeta.default_pack)

        # Use the explicitly defined unpack class method if it's present
        # otherwise use ours.
        if not (unpack := namespace.get("unpack", None)):
            unpack = lambda d: DAPObjectMeta.default_unpack(cls, d)
            setattr(cls, "unpack", unpack)
        else:
            unpack = getattr(cls, "unpack")

        # Register the unpack methods for each message according to the type
        # and type identifier.
        if (
            DAPObjectMeta.EVENT_TYPE
            and issubclass(cls, DAPObjectMeta.EVENT_TYPE)
            and cls != DAPObjectMeta.EVENT_TYPE
            and (event := namespace.get("event", None))
            and isinstance(event, EventType)
        ):
            DAPObjectMeta.REGISTRY[MessageType.EVENT.value][event.value] = unpack

        elif (
            DAPObjectMeta.REQUEST_TYPE
            and issubclass(cls, DAPObjectMeta.REQUEST_TYPE)
            and cls != DAPObjectMeta.REQUEST_TYPE
            and (command := namespace.get("command", None))
            and isinstance(command, Command)
        ):
            DAPObjectMeta.REGISTRY[MessageType.REQUEST.value][command.value] = unpack

        elif (
            DAPObjectMeta.RESPONSE_TYPE
            and issubclass(cls, DAPObjectMeta.RESPONSE_TYPE)
            and cls != DAPObjectMeta.RESPONSE_TYPE
        ):
            if (command := namespace.get("command", None)) and isinstance(command, Command):
                DAPObjectMeta.REGISTRY[MessageType.RESPONSE.value][command.value] = unpack
            else:
                # ErrorRecord is special where it's not a specific command but
                # is handled in a special way during the unpacking phase.
                DAPObjectMeta.REGISTRY[MessageType.RESPONSE.value]["error"] = unpack

        return cls

    def default_pack(
        self: t.Any,
    ) -> dict[str, t.Any]:
        packed_value: dict[str, t.Any] = {}

        todo: queue.Queue[tuple[t.Dict[str, t.Any], t.Dict[str, t.Any]]] = queue.Queue()
        todo.put((getattr(self.__class__, "_dap", {}), packed_value))

        while True:
            try:
                mapping, value = todo.get(block=False)
            except queue.Empty:
                break

            for key, info in mapping.items():
                if key == "__types":
                    continue
                elif isinstance(info, dict):
                    todo.put((info, value.setdefault(key, {})))
                else:
                    value[key] = getattr(self, info)

        return packed_value

    def default_unpack(
        cls,
        data: dict[str, t.Any],
    ) -> t.Any:
        dap = getattr(cls, "_dap", {})
        type_info = dap.get("__types", {})
        if not type_info and dataclasses.is_dataclass(cls):
            field_info = dataclasses.fields(cls)

            type_info = {}
            cls_fields = {}
            for base_cls in cls.__mro__:
                if not dataclasses.is_dataclass(base_cls):
                    continue

                cls_fields.update({k: base_cls for k in base_cls.__dataclass_fields__.keys()})

            for field in field_info:
                field_unpacker = None
                base_cls = cls_fields[field.name]
                field_unpacker = _parse_field_type(base_cls, str(field.type))
                type_info[field.name] = (field.init, field_unpacker)

            dap["__types"] = type_info

        kwargs: dict[str, t.Any] = {}
        manual_set: dict[str, t.Any] = {}

        todo: queue.Queue[tuple[t.Dict[str, t.Any], t.Dict[str, t.Any]]] = queue.Queue()
        todo.put((dap, data))

        while True:
            try:
                mapping, body = todo.get(block=False)
            except queue.Empty:
                break

            for key, value in body.items():
                if key not in mapping or value is None:
                    continue

                field_meta = mapping[key]
                if isinstance(field_meta, dict):
                    todo.put((field_meta, value))
                    continue

                can_init, unpack_func = type_info.get(field_meta, None)
                if not unpack_func:
                    unpack_func = lambda v: v

                dict_to_update = kwargs if can_init else manual_set
                if isinstance(value, list):
                    dict_to_update[field_meta] = [unpack_func(v) for v in value]
                else:
                    dict_to_update[field_meta] = unpack_func(value)

        new_obj = cls(**kwargs)
        for key, value in manual_set.items():
            object.__setattr__(new_obj, key, value)

        return new_obj


@dataclasses.dataclass()
class ProtocolMessage(metaclass=DAPObjectMeta, dap={"seq": "seq", "type": "message_type"}):
    """Base class for all DAP messages."""

    seq: int = dataclasses.field(init=False, default=0)
    message_type: MessageType = dataclasses.field(init=False)

    def pack(self) -> dict[str, t.Any]:  # type: ignore[empty-body] # Defined in metaclass
        ...  # pragma: no cover

    @classmethod
    def unpack(
        cls,
        data: dict[str, t.Any],
    ) -> ProtocolMessage:
        """Unpack DAP JSON data.

        Unpacks the DAP JSON data object into a structured object. If the type
        or the type's identifier is unknown then a ValueError is raised.

        Args:
            data: The JSON data dictionary to unpack.

        Returns:
            ProtocolMessage: The unpacked message.
        """
        obj_type = data["type"]

        registry = DAPObjectMeta.REGISTRY.get(obj_type, None)
        if not registry:
            raise ValueError(f"Unknown DAP message type '{obj_type}'")

        if obj_type == MessageType.REQUEST.value:
            cmd = data["command"]

            request_unpack = registry.get(cmd, None)
            if not request_unpack:
                raise ValueError(f"Unknown DAP request command '{cmd}'")

            return request_unpack(data)

        elif obj_type == MessageType.RESPONSE.value:
            cmd = data["command"]
            if not data["success"]:
                cmd = "error"

            response_unpack = registry.get(cmd, None)
            if not response_unpack:
                raise ValueError(f"Unknown DAP response command '{cmd}'")

            return response_unpack(data)

        else:
            event = data["event"]

            event_unpack = registry.get(event, None)
            if not event_unpack:
                raise ValueError(f"Unknown DAP event type '{event}'")

            return event_unpack(data)


@dataclasses.dataclass()
class Request(ProtocolMessage, dap={"command": "command"}):
    """Base class for DAP request messages."""

    message_type = MessageType.REQUEST

    command: Command = dataclasses.field(init=False)


@dataclasses.dataclass()
class Event(ProtocolMessage, dap={"event": "event"}):
    """Base class for DAP event messages."""

    message_type = MessageType.EVENT

    event: EventType = dataclasses.field(init=False)


@dataclasses.dataclass()
class Response(ProtocolMessage, dap={"request_seq": "request_seq", "success": "success", "command": "command"}):
    """Base class for DAP response messages."""

    message_type = MessageType.RESPONSE

    success: bool = dataclasses.field(init=False, default=True)
    command: Command = dataclasses.field(init=False)
    request_seq: int
