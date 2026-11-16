# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import enum
import functools
import json
import sys
import types
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


class UnknownRequestError(ValueError):
    """The request command is not one known to this library.

    The seq and command are kept so the receiver can still send back an
    ErrorResponse for the request.
    """

    def __init__(self, seq: int, command: str) -> None:
        super().__init__(f"Unknown DAP request command '{command}'")
        self.seq = seq
        self.command = command


class DAPEncoder(json.JSONEncoder):
    def default(self, o: t.Any) -> t.Any:
        if isinstance(o.__class__, DAPObjectMeta) and hasattr(o, "pack"):
            return o.pack()

        elif isinstance(o, enum.Enum):
            return o.value

        else:
            return str(o)


def _enum_or_str(enum_type: type[enum.Enum], value: str) -> enum.Enum | str:
    try:
        return enum_type(value)
    except ValueError:
        return value


def _parse_field_type(obj: type, value: str) -> t.Callable[[t.Any], t.Any] | None:
    base_globals = getattr(sys.modules.get(obj.__module__, None), "__dict__", {})
    base_locals = dict(vars(obj))
    evaled_type = eval(value, base_globals, base_locals)

    # The origin is checked first as Python 3.10 treats list[X] as an instance of type.
    attr_type = None
    type_origin = t.get_origin(evaled_type)
    # X | None is a types.UnionType before 3.14, which made it the same as t.Union.
    if type_origin in (t.Union, types.UnionType):  # pyright: ignore[reportDeprecated]
        union_types = t.get_args(evaled_type)
        if len(union_types) == 2 and type(None) in union_types:
            attr_type = union_types[0]
        elif (
            len(union_types) == 2
            and union_types[1] is str
            and isinstance(union_types[0], type)
            and issubclass(union_types[0], enum.Enum)
        ):
            # An enum that also accepts values it does not define, like the
            # command of an ErrorResponse to an unknown request.
            return functools.partial(_enum_or_str, union_types[0])
    elif type_origin is list:
        attr_type = t.get_args(evaled_type)[0]
    elif isinstance(evaled_type, type):
        attr_type = evaled_type

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
        dap_map: dict[str, t.Any] = dap or {}
        for base in reversed(bases):
            dap_map = getattr(base, "_dap", {}) | dap_map

        # We cannot refer to these types directly as they are created by this
        # metaclass, store them for easier referencing later.
        if name == "Event" and namespace["__module__"] == DAPObjectMeta.__module__:
            DAPObjectMeta.EVENT_TYPE = cls

        elif name == "Request" and namespace["__module__"] == DAPObjectMeta.__module__:
            DAPObjectMeta.REQUEST_TYPE = cls

        elif name == "Response" and namespace["__module__"] == DAPObjectMeta.__module__:
            DAPObjectMeta.RESPONSE_TYPE = cls

        setattr(cls, "_dap", dap_map)

        # Only add pack to the first class in inheritance.
        if "pack" not in cls.__dict__:
            setattr(cls, "pack", DAPObjectMeta.default_pack)

        # Use the explicitly defined unpack class method if it's present
        # otherwise use ours.
        unpack: t.Callable[[dict[str, t.Any]], t.Any]
        if namespace.get("unpack", None):
            unpack = getattr(cls, "unpack")
        else:
            unpack = lambda d: DAPObjectMeta.default_unpack(cls, d)
            setattr(cls, "unpack", unpack)

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

        todo: list[tuple[dict[str, t.Any], dict[str, t.Any]]] = [(getattr(self.__class__, "_dap", {}), packed_value)]
        while todo:
            mapping, value = todo.pop()

            for key, info in mapping.items():
                if key == "__types":
                    continue
                elif isinstance(info, dict):
                    todo.append((info, value.setdefault(key, {})))
                elif (field_value := getattr(self, info)) is not None:
                    # The spec has optional fields omitted rather than null.
                    value[key] = field_value

        return packed_value

    def default_unpack(
        cls,
        data: dict[str, t.Any],
    ) -> t.Any:
        dap = getattr(cls, "_dap", {})
        type_info: dict[str, tuple[bool, t.Callable[[t.Any], t.Any] | None]] = dap.get("__types", {})
        if not type_info and dataclasses.is_dataclass(cls):
            field_info = dataclasses.fields(cls)

            type_info = {}
            cls_fields: dict[str, type] = {}
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

        todo: list[tuple[dict[str, t.Any], dict[str, t.Any]]] = [(dap, data)]
        while todo:
            mapping, body = todo.pop()

            for key, value in body.items():
                if key not in mapping or value is None:
                    continue

                field_meta = mapping[key]
                if isinstance(field_meta, dict):
                    todo.append((field_meta, value))
                    continue

                can_init, field_unpack = type_info[field_meta]
                unpack_func: t.Callable[[t.Any], t.Any] = field_unpack or (lambda v: v)

                dict_to_update = kwargs if can_init else manual_set
                if isinstance(value, list):
                    dict_to_update[field_meta] = [unpack_func(v) for v in t.cast("list[t.Any]", value)]
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

    def pack(self) -> dict[str, t.Any]:  # Defined in metaclass
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
                raise UnknownRequestError(data.get("seq", 0), cmd)

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
