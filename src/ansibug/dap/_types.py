# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import typing as t

from ._messages import DAPObjectMeta


@dataclasses.dataclass()
class Breakpoint(
    metaclass=DAPObjectMeta,
    dap={
        "id": "id",
        "verified": "verified",
        "message": "message",
        "source": "source",
        "line": "line",
        "column": "column",
        "endLine": "end_line",
        "endColumn": "end_column",
        "instructionReference": "instruction_reference",
        "offset": "offset",
    },
):
    """Breakpoint information.

    Information about a breakpoint created in SetBreakpointsRequest,
    SetFunctionBreakpointsRequest, SetInstructionBreakspointsRequest, or
    SetDataBreakpointsRequest.

    Args:
        id: Optional identifier for the breakpoint.
        verified: The breakpoint could be set.
        message: Option explanation on the state of the breakpoint.
        source: Source where the breakpoint is located.
        line: The start line of the actual range covered by the breakpoint.
        column: The start column of the actual range covered by the breakpoint.
        end_line: End line of the actual range covered by the breakpoint.
        end_column: End column of the actual range covered by the breakpoint.
            If no end_line is specified, then the column is assumed to be in
            the start_line.
        instruction_reference: Optional memory reference to where the
            breakpoint is set.
        offset: Optional offset from the instruction reference.
    """

    id: t.Optional[int] = None
    verified: bool = False
    message: t.Optional[str] = None
    source: t.Optional[Source] = None
    line: t.Optional[int] = None
    column: t.Optional[int] = None
    end_line: t.Optional[int] = None
    end_column: t.Optional[int] = None
    instruction_reference: t.Optional[str] = None
    offset: t.Optional[int] = None


@dataclasses.dataclass()
class Capabilities(
    metaclass=DAPObjectMeta,
    dap={
        "supportsConfigurationDoneRequest": "supports_configuration_done_request",
        "supportsFunctionBreakpoints": "supports_function_breakpoints",
        "supportsConditionalBreakpoints": "supports_conditional_breakpoints",
        "supportsHitConditionalBreakpoints": "supports_hit_conditional_breakpoints",
        "supportsEvaluateForHovers": "supports_evaluate_for_hovers",
        "supportsStepBack": "supports_step_back",
        "supportsSetVariable": "supports_set_variable",
        "supportsRestartFrame": "supports_restart_frame",
        "supportsGotoTargetsRequest": "supports_goto_targets_request",
        "supportsStepInTargetsRequest": "supports_step_in_targets_request",
        "supportsCompletionsRequest": "supports_completions_request",
        "supportTerminateDebuggee": "supports_terminate_debuggee",
        "supportSuspendDebuggee": "supports_suspend_debuggee",
        "supportsTerminateRequest": "supports_terminate_request",
        "supportsClipboardContext": "supports_clipboard_context",
    },
):
    """Capabilities of a debug adapter.

    Information about the capabilities of a debug adapter.

    Args:
        supports_configuration_done_request: The debug adapter supports the
            ConfigurationDoneRequest.
        supports_function_breakpoints: The debug adapter supports function
            breakpoints.
        supports_conditional_breakpoints: The debug adapter supports conditional
            breakpoints.
        supports_hit_conditional_breakpoints: The debug adapter supports
            breakpoints that break execution after a specified number of hits.
        supports_evaluate_for_hovers: THe debug adapter supports evaluate
            request for data hovers.
        supports_step_back: The debug adapter supports stepping back via the
            StepBackRequest and ReverseContinueRequest.
        supports_set_variable: The debug adapter supports setting a variable to
            a value.
        supports_restart_frame: The debug adapter supports restarting a frame.
        supports_goto_targets_request: The debug adapter supports the
            GotoTargetsRequest.
        supports_step_in_targets_request: The debug adapter supports the
            StepInTargetsRequest.
        supports_completions_request: The debug adapter supports the
            CompletionsRequest.
        supports_terminate_debuggee: The debug adapter supports the
            terminate_debuggee` attribute on the DisconnectRequest.
        supports_suspend_debuggee: The debug adapter supports the
            suspend_debuggee attribute on the DisconnectRequest.
        supports_terminate_request: The debug adapter supports the
            TerminateRequest.
        supports_clipboard_context: The debug adapter supports the clipboard
            context value in the evaluate request.
    """

    supports_configuration_done_request: bool = False
    supports_function_breakpoints: bool = False
    supports_conditional_breakpoints: bool = False
    supports_hit_conditional_breakpoints: bool = False
    supports_evaluate_for_hovers: bool = False
    # exception_breakpoint_filters
    supports_step_back: bool = False
    supports_set_variable: bool = False
    supports_restart_frame: bool = False
    supports_goto_targets_request: bool = False
    supports_step_in_targets_request: bool = False
    supports_completions_request: bool = False
    # completion_trigger_characters
    # supports_modules_request
    # additional_module_columns
    # supported_checksum_algorithms
    # supports_restart_request
    # supports_exception_options
    # supports_value_formatting_options
    # supports_exception_info_request
    supports_terminate_debuggee: bool = False
    supports_suspend_debuggee: bool = False
    # supports_delayed_stack_trace_loading
    # supports_loaded_sources_request
    # supports_log_points
    # supports_terminate_threads_request
    # supports_set_expression
    supports_terminate_request: bool = False
    # supports_data_breakpoints
    # supports_read_memory_request
    # supports_write_memory_request
    # supports_disassemble_request
    # supports_cancel_request
    # supports_breakpoint_locations_request
    supports_clipboard_context: bool = False
    # supports_stepping_granularity
    # supports_instruction_breakpoints
    # supports_exception_filter_options
    # supports_single_thread_execution_requests


@dataclasses.dataclass()
class Checksum(metaclass=DAPObjectMeta, dap={"algorithm": "algorithm", "checksum": "checksum"}):
    """The checksum of an item.

    Describes the checksum of an item. The known algorithms are "MD5", "SHA1",
    "SHA256", and "timestamp".

    Args:
        algorithm: The algorithm used to calculate this checksum.
        checksum: The value of the checksum, encoded as a hexadecimal value.
    """

    algorithm: t.Literal["MD5", "SHA1", "SHA256", "timestamp"]
    checksum: str


@dataclasses.dataclass()
class ExceptionFilterOptions(metaclass=DAPObjectMeta, dap={"filterId": "filter_id", "condition": "condition"}):
    """Exception filter options.

    Used to specify an exception filter together with a condition for the
    SetExceptionBreakpoints request.

    Args:
        filter_id: The ID of the exception filter.
        condition: Optional condition for the filter.
    """

    filter_id: str
    condition: t.Optional[str] = None


@dataclasses.dataclass()
class ExceptionOptions(metaclass=DAPObjectMeta, dap={"path": "path", "breakMode": "break_mode"}):
    """Configuration options to a set of exceptions.

    Assigns configuration options to a set of exceptions.

    Args:
        path: A path that selects a single or multiple exceptions in a tree.
            By convention the first segment of the path is a category that is
            used to group exceptions in the UI.
        break_mode: Condition when a thrown exception should result in a break.
    """

    path: t.List[ExceptionPathSegment]
    break_mode: t.Literal["never", "always", "unhandled", "userUnhandled"]


@dataclasses.dataclass()
class ExceptionPathSegment(metaclass=DAPObjectMeta, dap={"negate": "negate", "names": "names"}):
    """Represents a segment in a path.

    Represents a segment in a path that is used to match leafs or nodes in a
    tree of exceptions.

    Args:
        negate: Controls the matching behaviour of the names.
        names: The values to match (or not match if negate=True).
    """

    negate: bool = False
    names: t.List[str] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class Message(
    metaclass=DAPObjectMeta,
    dap={
        "id": "id",
        "format": "format",
        "variables": "variables",
        "sendTelemetry": "send_telemetry",
        "showUser": "show_user",
        "url": "url",
        "urlLabel": "url_label",
    },
):
    """A structured message object.

    A structured message object used to return errors from requests.
    """

    id: int
    format: str
    variables: t.Dict[str, str] = dataclasses.field(default_factory=dict)
    send_telemetry: bool = False
    show_user: bool = False
    url: t.Optional[str] = None
    url_label: t.Optional[str] = None


@dataclasses.dataclass()
class Scope(
    metaclass=DAPObjectMeta,
    dap={
        "name": "name",
        "presentationHint": "presentation_hint",
        "variablesReference": "variables_reference",
        "namedVariables": "named_variables",
        "indexedVariables": "indexed_variables",
        "expensive": "expensive",
        "source": "source",
        "line": "line",
        "column": "column",
        "endLine": "end_line",
        "endColumn": "end_column",
    },
):
    """Named container for variables.

    A scope is a ned container for variables.

    Args:
        name: The name of the scope to be shown in the UI.
        variables_reference: The id used to retrieve the variables of this
            scope.
        presentation_hint: How to present this scope in the UI.
        named_variables: Number of named variables in the scope.
        expensive: If True, the number of variables in this scope is large or
            expensive to retrieve.
        source: Optional source for this scope.
        line: Optional start line of the range covered by this scope.
        column: Optional start column of the range covered by this scope.
        end_line: Optional end line of the range covered by this scope.
        end_column: Optional end column of the range covered by this scope.
    """

    name: str
    variables_reference: int
    presentation_hint: t.Optional[t.Union[str, t.Literal["arguments", "locals", "registers"]]] = None
    named_variables: t.Optional[int] = None
    indexed_variables: t.Optional[int] = None
    expensive: bool = False
    source: t.Optional[Source] = None
    line: t.Optional[int] = None
    column: t.Optional[int] = None
    end_line: t.Optional[int] = None
    end_column: t.Optional[int] = None


@dataclasses.dataclass()
class Source(
    metaclass=DAPObjectMeta,
    dap={
        "name": "name",
        "path": "path",
        "sourceReference": "source_reference",
        "presentationHint": "presentation_hint",
        "origin": "origin",
        "sources": "sources",
        "adapterData": "adapter_data",
        "checksums": "checksums",
    },
):
    """Descriptor for source code.

    A source is used to describe source code. It is returned from the debug
    adapter as part of a StackFrame and it is used by clients when specifying
    breakpoints.

    Args:
        name: The short name of the source.
        path: The path of the source to be shown in the UI. It is used to
            locate the source if source_reference is greater than 0.
        source_reference: If greater than 0, the contents of the source must be
            retrieved through the SourceRequest. The id is only valid for a
            session.
        presentation_hint: How to present the source in the UI. A value of
            deemphasize can be used to indicate the source is not available or
            that it is skipped on stepping.
        origin: Origin of this source.
        sources: List of sources that are related to this source.
        adapter_data: Optional opaque data to associate with the source. The
            client does not interpret this data.
        checksums: Checksum associated with this file.
    """

    name: t.Optional[str] = None
    path: t.Optional[str] = None
    source_reference: int = 0
    presentation_hint: t.Literal["normal", "emphasize", "deemphasize"] = "normal"
    origin: t.Optional[str] = None
    sources: t.List[Source] = dataclasses.field(default_factory=list)
    adapter_data: t.Any = None
    checksums: t.List[Checksum] = dataclasses.field(default_factory=list)


@dataclasses.dataclass()
class SourceBreakpoint(
    metaclass=DAPObjectMeta,
    dap={
        "line": "line",
        "column": "column",
        "condition": "condition",
        "hitCondition": "hit_condition",
        "logMessage": "log_message",
    },
):
    """Properties of a breakpoint.

    The properties of a breakpoint or logpoint passed to the
    SetBreakpoinsRequest.

    Args:
        line: The source line of the breakpoint or logpoint.
        column: The optional source column of the breakpoint.
        condition: An optional expression for conditional breakpoints.
        hit_condition: An optional expression that controls how many hits of
            the brekapoint are ignored.
        log_message: Do not break but log the message on a break.
    """

    line: int
    column: t.Optional[int] = None
    condition: t.Optional[str] = None
    hit_condition: t.Optional[str] = None
    log_message: t.Optional[str] = None


@dataclasses.dataclass()
class StackFrame(
    metaclass=DAPObjectMeta,
    dap={
        "id": "id",
        "name": "name",
        "source": "source",
        "line": "line",
        "column": "column",
        "endLine": "end_line",
        "endColumn": "end_column",
        "canRestart": "can_restart",
        "instructionPointerReference": "instruction_pointer_reference",
        "moduleId": "module_id",
        "presentationHint": "presentation_hint",
    },
):
    """A stackframe.

    A stackframe contains the source location.

    Args:
        id: Id for the stack frame.
        name: The name of the stack frame.
        source: The optional source of the frame.
        line: The line within the file of the frame, will be ignored if source
            is None.
        column: The column within the file of the frame, will be ignored if
            source is None.
        end_line: Optional end line of the range covered by the stack frame.
        end_column: Optional end column of the range covered by the stack frame.
        can_restart: Indicates whether this frame can be restarted.
        instruction_pointer_reference: Optional memory reference for the
            current instruction pointer.
        module_id: Optional module associated with this frame.
        presentation_hint: How to present this frame in the UI.
    """

    id: int
    name: str
    source: t.Optional[Source] = None
    line: int = 0
    column: int = 0
    end_line: t.Optional[int] = None
    end_column: t.Optional[int] = None
    can_restart: bool = False
    instruction_pointer_reference: t.Optional[str] = None
    module_id: t.Optional[t.Union[int, str]] = None
    presentation_hint: t.Literal["normal", "label", "subtle"] = "normal"


@dataclasses.dataclass()
class StackFrameFormat(
    metaclass=DAPObjectMeta,
    dap={
        "parameters": "parameters",
        "parameterTypes": "parameter_types",
        "parameterNames": "parameter_names",
        "parameterValues": "parameter_values",
        "line": "line",
        "module": "module",
        "includeAll": "include_all",
    },
):
    """Formatting info for a stack frame.

    Provides formatting information for a stack frame.

    Args:
        parameters: Display parameters for the stack frame.
        parameter_types: Displays the types of parameters for the stack frame.
        parameter_names: Displays the names of parameters for the stack frame.
        parameter_values: Displays the values of parameters for the stack frame.
        line: Displays the line number of the stack frame.
        module: Displays the module of the stack frame.
        include_all: Includes all stack frames, including those the debug
            adapter might otherwise hide.
    """

    parameters: bool = False
    parameter_types: bool = False
    parameter_names: bool = False
    parameter_values: bool = False
    line: bool = False
    module: bool = False
    include_all: bool = False


@dataclasses.dataclass()
class Thread(metaclass=DAPObjectMeta, dap={"id": "id", "name": "name"}):
    """A thread.

    Represents a thread on the debuggee.

    Args:
        id: The unique identifier for the thread.
        name: The name of the thread.
    """

    id: int
    name: str


@dataclasses.dataclass()
class ValueFormat(metaclass=DAPObjectMeta, dap={"hex": "hex"}):
    """Provides formatting information for a value.

    Args:
        hex: Display the value in hex.
    """

    hex: bool = False


@dataclasses.dataclass()
class Variable(
    metaclass=DAPObjectMeta,
    dap={
        "name": "name",
        "value": "value",
        "type": "type",
        "presentationHint": "presentation_hint",
        "evaluateName": "evaluate_name",
        "variablesReference": "variables_reference",
        "namedVariables": "named_variables",
        "indexedVariables": "indexed_variables",
        "memoryReference": "memory_reference",
    },
):
    """A variable is a name/value pair.

    Represents a variable with a name and value as well as other metadata to
    display in the client GUI.

    Args:
        name: The variable's name.
        value: The variable's value.
        type: The type of the variable's value to display in the client.
        presentation_hint: Properties of a variable that can be used to
            determine how to render the variable in the client.
        evaluate_name: Optional evaluable name of this variable which can be
            passed to the EvaluateRequest to fetch the variable's name.
        variables_reference: If set to > 1, the variable is structured and
            contains indexed or named variables.
        named_variables: The number of named child variables.
        indexed_variables: The number of indexed child variables.
        memory_reference: Optional memory reference for the variable if the
            variable represents executable code, such as a function pointer.
    """

    name: str
    value: str
    type: t.Optional[str] = None
    presentation_hint: t.Optional[VariablePresentationHint] = None
    evaluate_name: t.Optional[str] = None
    variables_reference: int = 0
    named_variables: t.Optional[int] = None
    indexed_variables: t.Optional[int] = None
    memory_reference: t.Optional[str] = None


@dataclasses.dataclass
class VariablePresentationHint(
    metaclass=DAPObjectMeta,
    dap={
        "kind": "kind",
        "attributes": "attributes",
        "visibility": "visibility",
        "lazy": "lazy",
    },
):
    """Optional properties of a variable.

    Optional properties of a variable that can be used to determine how to
    render the variable in the UI.

    Args:
        kind: The kind of variable.
        attributes: Set of attributes represented as a list of strings.
        visbility: Visibility of the variable.
        lazy: The value can be retrieved through a specific request.
    """

    kind: t.Optional[
        t.Union[
            str,
            t.Literal[
                "property",
                "method",
                "class",
                "data",
                "event",
                "baseClass",
                "innerClass",
                "interface",
                "mostDerivedClass",
                "virtual",
                "dataBreakpoint",
            ],
        ]
    ] = None
    attributes: t.List[
        t.Union[
            str,
            t.Literal[
                "static",
                "constant",
                "readOnly",
                "rawString",
                "hasObjectId",
                "canHaveObjectId",
                "hasSideEffect",
                "hasDataBreakpoint",
            ],
        ]
    ] = dataclasses.field(default_factory=list)
    visibility: t.Optional[t.Union[str, t.Literal["public", "private", "protected", "internal"]]] = None
    lazy: bool = False
