# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import typing as t

from ._messages import Command, Request, register_request
from ._types import (
    ExceptionFilterOptions,
    ExceptionOptions,
    Source,
    SourceBreakpoint,
    StackFrameFormat,
    ValueFormat,
)


@register_request
@dataclasses.dataclass()
class CancelRequest(Request):
    """Cancel a request made by the client.

    Sent from the client to the debug adapter to cancel a request that it is
    no longer interested in or cancel a progress sequence.

    Args:
        request_id: The seq of the request to cancel. If no seq is specified
            then all are cancelled.
        progress_id: The seq of the progress to cancel.
    """

    command = Command.CANCEL

    request_id: t.Optional[int] = None
    progress_id: t.Optional[int] = None

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "requestId": self.request_id,
            "progressId": self.progress_id,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> CancelRequest:
        return CancelRequest(
            request_id=arguments.get("requestId", None),
            progress_id=arguments.get("progressId", None),
        )


@register_request
@dataclasses.dataclass()
class ConfigurationDoneRequest(Request):
    """Client has finished initialization of the debug adpater.

    Sent by the client to signal it is done with the initial configuration of
    the debug adapter.
    """

    command = Command.CONFIGURATION_DONE

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> ConfigurationDoneRequest:
        return ConfigurationDoneRequest()


@register_request
@dataclasses.dataclass()
class ContinueRequest(Request):
    """Request execution to resume.

    Sent by the client to request the thread execution to resume.

    Args:
        thread_id: The thread to resume
        single_thread: Resume only the thread specified or all threads if
            False.
    """

    command = Command.CONTINUE

    thread_id: int
    single_thread: bool = True

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "threadId": self.thread_id,
            "singleThread": self.single_thread,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> ContinueRequest:
        return ContinueRequest(
            thread_id=arguments["threadId"],
            single_thread=arguments.get("singleThread", True),
        )


@register_request
@dataclasses.dataclass()
class DisconnectRequest(Request):
    """Asks the DA to disconnect from the debuggee.

    Sent by the client to ask the DA to disconnect from the debuggee and
    end the debug session.

    Args:
        restart: This request is part of a restart sequence.
        terminate_debuggee: Indicates whether the debuggee should be terminated
            when the debugger is disconnected. If None the DA is free to do
            whatever it thinks is best.
        suspend_debuggee: Indicates whether the debuggee should stay suspended
            when the debugger is disconnected.
    """

    command = Command.DISCONNECT

    restart: bool = False
    terminate_debuggee: t.Optional[bool] = None
    suspend_debuggee: bool = False

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "restart": self.restart,
            "terminateDebuggee": self.terminate_debuggee,
            "suspendDebuggee": self.suspend_debuggee,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> DisconnectRequest:
        return DisconnectRequest(
            restart=arguments.get("restart", False),
            terminate_debuggee=arguments.get("terminateDebuggee", None),
            suspend_debuggee=arguments.get("suspendDebuggee", False),
        )


@register_request
@dataclasses.dataclass()
class InitializeRequest(Request):
    """Initialize DA with client capabailities.

    Send by the client to the debug adapter as the first message. It contains
    the capabilities of the client and expects the DA capabilities in the
    InitializeResponse.

    Args:
        adapter_id: The ID of the debug adapter.
        client_id: The ID of the client using this adapter.
        client_name: The name of the client using this adapter.
        locale: The ISO-639 locale of the client using this adapter.
        lines_start_at_1: All line numbers are 1-based, else 0-based.
        columns_start_at_1: All column numbers are 1-based, else 0-based.
        path_format: The format that paths are specified as.
        supports_variable_type: Client supports the optional type attribute for
            variables.
        supports_variable_paging: Client supports the paging of variables.
        supports_run_in_terminal_request: Client supports the
            RunInTerminalRequest.
        supports_memory_references: Client supports memory references.
        supports_progress_reporting: Client supports progress reporting.
        supports_invalidated_event: Client supports the invalidated event.
        supports_memory_event: Client supports the memory event.
    """

    command = Command.INITIALIZE

    adapter_id: str
    client_id: t.Optional[str] = None
    client_name: t.Optional[str] = None
    locale: t.Optional[str] = None
    lines_start_at_1: bool = True
    columns_start_at_1: bool = True
    path_format: t.Literal["path", "uri"] = "path"
    supports_variable_type: bool = False
    supports_variable_paging: bool = False
    supports_run_in_terminal_request: bool = False
    supports_memory_references: bool = False
    supports_progress_reporting: bool = False
    supports_invalidated_event: bool = False
    supports_memory_event: bool = False

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
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

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> InitializeRequest:
        return InitializeRequest(
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


@register_request
@dataclasses.dataclass()
class LaunchRequest(Request):
    """Request to start the debugee with or without debugging.

    This is a request sent from the client to the debug adapter to start the
    debugee with or without debugging.

    Args:
        arguments: The arguments from the client, the structure of this is
            dependent on the client and what was requested.
        no_debug: The program should launch without enabling debugging.
        restart: Optional data from the previous, restarted session.
    """

    command = Command.LAUNCH

    arguments: t.Dict[str, t.Any]
    no_debug: bool = False
    restart: t.Any = None

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        args = self.arguments.copy()
        args["noDebug"] = self.no_debug
        args["__restart"] = self.restart

        obj["arguments"] = args

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> LaunchRequest:
        args = arguments.copy()
        no_debug = args.pop("noDebug", False)
        restart = args.pop("__restart", None)
        return LaunchRequest(
            arguments=args,
            no_debug=no_debug,
            restart=restart,
        )


@register_request
@dataclasses.dataclass()
class NextRequest(Request):
    """Request to execute one step.

    This is a request sent from the client to the debug adapter to execute the
    next step and send a stop request.

    Args:
        thread_id: The thread for which to resume execution for one step.
        single_thread: All other suspended threads are not resumed.
        granularity: The granularity stepping.
    """

    command = Command.NEXT

    thread_id: int
    single_thread: bool = False
    granularity: t.Literal["statement", "line", "instruction"] = "statement"

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "threadId": self.thread_id,
            "singleThread": self.single_thread,
            "granularity": self.granularity,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> NextRequest:
        return NextRequest(
            thread_id=arguments["threadId"],
            single_thread=arguments.get("singleThread", False),
            granularity=arguments.get("granularity", "statement"),
        )


@register_request
@dataclasses.dataclass()
class RunInTerminalRequest(Request):
    """Request from the debug adapter to run a command.

    This is a request from the debug adapter to the client to run a command in
    the client's terminal. This is typically used to launch the debugee in a
    terminal provided by the client.

    Args:
        kind: The type of terminal to launch with.
        cwd: The working directory of the command.
        args: List of arguments, including the executable, to run the command
            with.
        env: Optional environment key-value pairs that are added to or removed
            from the default environment.
        title: The title of the terminal.
    """

    command = Command.RUN_IN_TERMINAL

    kind: t.Literal["integrated", "external"] = "integrated"
    cwd: str = ""
    args: t.List[str] = dataclasses.field(default_factory=list)
    env: t.Dict[str, t.Optional[str]] = dataclasses.field(default_factory=dict)
    title: t.Optional[str] = None

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "kind": self.kind,
            "title": self.title,
            "cwd": self.cwd,
            "args": self.args,
            "env": self.env,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> RunInTerminalRequest:
        return RunInTerminalRequest(
            kind=arguments.get("kind", "integrated"),
            cwd=arguments["cwd"],
            args=arguments["args"],
            env=arguments.get("env", {}),
            title=arguments.get("title", None),
        )


@register_request
@dataclasses.dataclass
class ScopesRequest(Request):
    """Request variables scopes.

    Requests variable scopes for a given stackframe ID.

    Args:
        frame_id: The stackframe identifier to retrieve the scopes for.
    """

    command = Command.SCOPES

    frame_id: int

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "frameId": self.frame_id,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> ScopesRequest:
        return ScopesRequest(
            frame_id=arguments["frameId"],
        )


@register_request
@dataclasses.dataclass
class SetBreakpointsRequest(Request):
    """Set breakpoint for a source.

    Used by the client to set breakpoints and clear any previous breakpoints
    for a source.

    Args:
        source: The source location of the breakpoints.
        breakpoints: The locations of the breakpoints in the source.
        lines: Deprecated but the lines in the source that are breakpoints.
        source_modified: Indicates the underlying source has been modified
            which results in new breakpoint locations.
    """

    command = Command.SET_BREAKPOINTS

    source: Source
    breakpoints: t.List[SourceBreakpoint] = dataclasses.field(default_factory=list)
    lines: t.List[int] = dataclasses.field(default_factory=list)
    source_modified: bool = False

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "source": self.source.pack(),
            "breakpoints": [b.pack() for b in self.breakpoints],
            "lines": self.lines,
            "sourceModified": self.source_modified,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> SetBreakpointsRequest:
        return SetBreakpointsRequest(
            source=Source.unpack(arguments["source"]),
            breakpoints=[SourceBreakpoint.unpack(b) for b in arguments.get("breakpoints", [])],
            lines=arguments.get("lines", []),
            source_modified=arguments.get("sourceModified", False),
        )


@register_request
@dataclasses.dataclass()
class SetExceptionBreakpointsRequest(Request):
    """Configure exception breakpoint behaviour.

    Sent by the client to configure the debugger's response to thrown
    exceptions.

    Args:
        filters: Set of exception filters by ID as specified by the
            Capabilities.exception_breakpoint_filters sent by the debug
            adapter.
        filter_options: List of exception filters and their options.
        exception_options: Configuration options for the selected exceptions.
    """

    command = Command.SET_EXCEPTION_BREAKPOINTS

    filters: t.List[str] = dataclasses.field(default_factory=list)
    filter_options: t.List[ExceptionFilterOptions] = dataclasses.field(default_factory=list)
    exception_options: t.List[ExceptionOptions] = dataclasses.field(default_factory=list)

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "filters": self.filters,
            "filterOptions": [fo.pack() for fo in self.filter_options],
            "exceptionOptions": [eo.pack() for eo in self.exception_options],
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> SetExceptionBreakpointsRequest:
        return SetExceptionBreakpointsRequest(
            filters=arguments.get("filters", []),
            filter_options=[ExceptionFilterOptions.unpack(e) for e in arguments.get("filterOptions", [])],
            exception_options=[ExceptionOptions.unpack(e) for e in arguments.get("exceptionOptions", [])],
        )


@register_request
@dataclasses.dataclass()
class SetVariableRequest(Request):
    """Set the variable with a new value.

    Sets a variable in a given context with a new value.

    Args:
        variables_reference: The variable container id.
        name: The name of the variable in the container.
        value: The value of the variable to set.
        format: Optional details on how the value is formatted.
    """

    command = Command.SET_VARIABLE

    variables_reference: int
    name: str
    value: str
    format: t.Optional[ValueFormat] = None

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "variablesReference": self.variables_reference,
            "name": self.name,
            "value": self.value,
            "format": self.format.pack() if self.format else None,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> SetVariableRequest:
        return SetVariableRequest(
            variables_reference=arguments["variablesReference"],
            name=arguments["name"],
            value=arguments["value"],
            format=ValueFormat.unpack(arguments["format"]) if "format" in arguments else None,
        )


@register_request
@dataclasses.dataclass()
class StackTraceRequest(Request):
    """Request a stacktrace.

    Sent by the client to request a stacktrace from the current execution
    state of a given thread.

    Args:
        thread_id: The stacktrace for this thread.
        start_frame: Index of the first frame to return.
        levels: The maximum number of frames to return.
        format: Details on how to format the stack frames.
    """

    command = Command.STACK_TRACE

    thread_id: int
    start_frame: t.Optional[int] = None
    levels: t.Optional[int] = None
    format: t.Optional[StackFrameFormat] = None

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "threadId": self.thread_id,
            "startFrame": self.start_frame,
            "levels": self.levels,
            "format": self.format.pack() if self.format else None,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> StackTraceRequest:
        return StackTraceRequest(
            thread_id=arguments["threadId"],
            start_frame=arguments.get("startFrame", None),
            levels=arguments.get("levels", None),
            format=StackFrameFormat.unpack(arguments["format"]) if "format" in arguments else None,
        )


@register_request
@dataclasses.dataclass()
class StepInRequest(Request):
    """Request to step into a function/method.

    Sent by the client to request the given thread to step into a function
    and allows all other threads to run freely by resuming them.

    Args:
        thread_id: The thread for which to resume exeuction for on step into.
        single_thread: If True, all other suspended threads are not resumed.
        target_id: The id of the target to step into.
        granularity: Granularity level to step.
    """

    command = Command.STEP_IN

    thread_id: int
    single_thread: bool = False
    target_id: t.Optional[int] = None
    granularity: t.Literal["statement", "line", "instruction"] = "statement"

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "threadId": self.thread_id,
            "singleThread": self.single_thread,
            "targetId": self.thread_id,
            "granularity": self.granularity,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> StepInRequest:
        return StepInRequest(
            thread_id=arguments["threadId"],
            single_thread=arguments.get("singleThread", False),
            target_id=arguments.get("targetId", None),
            granularity=arguments.get("granularity", "statement"),
        )


@register_request
@dataclasses.dataclass()
class StepOutRequest(Request):
    """Request to ste out from a function/method.

    Sent by the client to request the given thread to step out of a function
    and allows all the other threads to run freely by resuming them.

    Args:
        thread_id: The thread for whcih to resume exeuction for one step out.
        single_thread: If True, all other suspended threads are not resumed.
        granularity: Granularity level to step.
    """

    command = Command.STEP_OUT

    thread_id: int
    single_thread: bool = False
    granularity: t.Literal["statement", "line", "instruction"] = "statement"

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "threadId": self.thread_id,
            "singleThread": self.single_thread,
            "granularity": self.granularity,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> StepOutRequest:
        return StepOutRequest(
            thread_id=arguments["threadId"],
            single_thread=arguments.get("singleThread", False),
            granularity=arguments.get("granularity", "statement"),
        )


@register_request
@dataclasses.dataclass()
class ThreadsRequest(Request):
    """Request to retrieve a list of all thread.

    Request sent by the client to retrieve all threads of the debuggee.
    """

    command = Command.THREADS

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> ThreadsRequest:
        return ThreadsRequest()


@register_request
@dataclasses.dataclass()
class VariablesRequest(Request):
    """Retrieves variables.

    Request sent by the client to retrieve all child variables for the given
    variable reference.

    Args:
        variables_reference: The reference id to retrieve.
        filter: Optionally filter child variables to either named or indexed
            variables.
        start: The index of the first variable to return.
        count: The number of variables to return or 0 for all.
        format: Details on how to format the variable values.
    """

    command = Command.VARIABLES

    variables_reference: int
    filter: t.Optional[t.Literal["indexed", "named"]] = None
    start: t.Optional[int] = None
    count: t.Optional[int] = None
    format: t.Optional[ValueFormat] = None

    def pack(self) -> t.Dict[str, t.Any]:
        obj = super().pack()
        obj["arguments"] = {
            "variablesReference": self.variables_reference,
            "filter": self.filter,
            "start": self.start,
            "count": self.count,
            "format": self.format.pack() if self.format else None,
        }

        return obj

    @classmethod
    def unpack(
        cls,
        arguments: t.Dict[str, t.Any],
    ) -> VariablesRequest:
        return VariablesRequest(
            variables_reference=arguments["variablesReference"],
            filter=arguments.get("filter", None),
            start=arguments.get("start", None),
            count=arguments.get("count", None),
            format=ValueFormat.unpack(arguments["format"]) if "format" in arguments else None,
        )
