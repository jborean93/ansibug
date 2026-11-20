# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

"""The debugger state the strategy hooks drive."""

import collections.abc
import dataclasses
import enum
import functools
import itertools
import logging
import os
import re
import threading
import traceback
import typing as t

from ansible import constants as C
from ansible.errors import AnsibleError, AnsibleUndefinedVariable
from ansible.inventory.host import Host
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.block import Block
from ansible.playbook.conditional import Conditional
from ansible.playbook.task import Task
from ansible.template import Templar
from ansible.utils.display import Display
from ansible.vars.hostvars import HostVars
from ansible.vars.manager import VariableManager

# Data Tagging was introduced in 2.19, this can be removed once 2.19 is the
# minimum supported version.
POST_DATATAGGING = False
# Raised when a value to set is templated to omit, 2.19+ raises it where older
# versions return a placeholder string that Ansible removes when the task runs.
_OMIT_ERRORS: tuple[type[Exception], ...] = ()
try:
    from ansible.errors import AnsibleBrokenConditionalError, AnsibleValueOmittedError
    from ansible.template import trust_as_template

    POST_DATATAGGING = True
    _OMIT_ERRORS = (AnsibleValueOmittedError,)
except ImportError:
    from ansible.template import AnsibleNativeEnvironment

    pass

import ansibug
from ansibug._debuggee import (
    AnsibleDebugger,
    AnsibleFunctionBreakpoint,
    AnsibleLineBreakpoint,
    DebugState,
    EndStrategy,
    ExceptionBreakpointType,
)

from ._breakpoints import (
    get_on_failed_details,
    get_on_skipped_details,
    get_on_unreachable_details,
    get_result_error,
    register_block_breakpoints,
)
from ._repl_util import (
    REPL_COMMANDS,
    RemoveVarCommand,
    SetVarCommand,
    TemplateCommand,
    parse_repl_args,
)
from ._task_result import AnsibugTaskResult
from ._variables import get_canonicalized_variable_type

display = Display()
log = logging.getLogger(__name__)


class OmitMarker:
    """A value to set that was templated to omit, it is removed instead of set."""


def _get_parent_tasks(
    task: Task,
) -> collections.abc.Iterator[Task]:
    """Yields each parent Task, i.e. the includes, of the task."""
    while task := task._parent:
        if isinstance(task, Task):
            yield task


def _get_task_names(task: Task) -> set[str]:
    """The names a function breakpoint can match for a task.

    This is the module as written, the module it resolved to after any
    redirects, and the task name. A module in a library/ dir resolves to its
    bare name so the ansible.legacy form is also added.
    """
    names = {task.action}
    # resolved_action is None for some actions like include_role on older
    # Ansible versions.
    if resolved := getattr(task, "resolved_action", None):
        names.add(resolved)
        if "." not in resolved:
            names.add(f"ansible.legacy.{resolved}")

    if task.name:
        # get_name() adds the role prefix for role tasks.
        names.update([task.name, task.get_name()])

    return names


# A variable name followed by any .name, [0], ['name'], or ["name"] lookups.
_HOVER_ROOT = re.compile(r"\s*([A-Za-z_]\w*)")
_HOVER_SEGMENT = re.compile(r"\.([A-Za-z_]\w*)|\[(\d+)\]|\['([^']*)'\]|\[\"([^\"]*)\"\]")


def _resolve_raw_path(expression: str, variables: dict[str, t.Any]) -> t.Any:
    """Resolves a variable path without templating any value.

    The dict and list lookups are done through the base types so a container
    that templates its values on access, like the ones Data Tagging uses,
    returns the raw value. Other containers, like hostvars, would template so
    are not traversed.

    Raises:
        KeyError: The expression is not a plain variable path or a part of it
            is not present.
    """
    root = _HOVER_ROOT.match(expression)
    if not root:
        raise KeyError(expression)

    keys: list[str | int] = [root.group(1)]
    pos = root.end()
    while segment := _HOVER_SEGMENT.match(expression, pos):
        attr, index, single, double = segment.groups()
        keys.append(int(index) if index is not None else next(k for k in (attr, single, double) if k is not None))
        pos = segment.end()

    if expression[pos:].strip():
        raise KeyError(expression)

    value: t.Any = variables
    for key in keys:
        if isinstance(value, dict):
            value = dict.__getitem__(t.cast(dict[t.Any, t.Any], value), key)
        elif isinstance(value, list) and isinstance(key, int):
            value = list.__getitem__(t.cast(list[t.Any], value), key)
        else:
            raise KeyError(key)

    return value


def _raw_repr(value: t.Any) -> str:
    """repr() of the value without a container templating its values."""
    if isinstance(value, dict):
        return dict.__repr__(t.cast(dict[t.Any, t.Any], value))
    elif isinstance(value, list):
        return list.__repr__(t.cast(list[t.Any], value))
    else:
        return repr(value)


def _completion_detail(value: t.Any) -> str:
    """The type and a short preview of a value for a completion item.

    Containers only show their size, building their repr for every completion
    request is expensive and a lazy container would template its values.
    """
    value_type = get_canonicalized_variable_type(value)
    if isinstance(value, (dict, list)):
        return f"{value_type} ({len(t.cast(t.Sized, value))} items)"

    elif value is None or isinstance(value, (str, int, float, bool)):
        preview = repr(value)
        return f"{value_type}: {preview if len(preview) <= 50 else preview[:47] + '...'}"

    else:
        return value_type


def _is_container(value: t.Any) -> bool:
    """Whether the value can be expanded as a child variable."""
    return isinstance(value, (collections.abc.Mapping, collections.abc.Sequence)) and not isinstance(
        value, (str, bytes, bytearray)
    )


class ThreadState(enum.Enum):
    CONTINUE = enum.auto()
    """Thread will continue to run until a breakpoint is hit."""

    STEP_IN = enum.auto()
    """Thread should step in and break on the next task."""

    STEP_OUT = enum.auto()
    """Thread should step out and break on the next task outside of the stack."""

    STEP_OVER = enum.auto()
    """Thread should step over and break on the next task in the same stack."""

    WAIT = enum.auto()
    """Thread has hit a breakpoint and is waiting for the client to respond."""

    END = enum.auto()
    """Thread has been requested to end and should not process any more tasks."""

    RESTART = enum.auto()
    """Thread should re-run the task it stopped on and break before it runs."""


class AnsibleThread:
    def __init__(
        self,
        *,
        id: int,
        host: Host | None = None,
    ) -> None:
        self.id = id
        self.host = host
        self.stack_frames: list[int] = []
        self.state: ThreadState = ThreadState.CONTINUE
        self._stopped_task: Task | None = None
        # Set by a pause request, the thread stops before its next task.
        self.pause_requested = False
        # The ExceptionInfoResponse body when stopped on an exception.
        self.exception_info: dict[str, t.Any] | None = None
        # The frame that can be restarted while stopped on its task result.
        self.restart_frame_id = 0

    def to_dap(self) -> ansibug.dap.Thread:
        return ansibug.dap.Thread(
            id=self.id,
            name=self.host.get_name() if self.host else "main",
        )

    def set_state(
        self,
        state: ThreadState,
    ) -> None:
        log.debug("Setting thread %d state to %s->%s", self.id, self.state, state)

        if state == ThreadState.STEP_OUT and self._stopped_task:
            # If a thread has been set to step out we want to make comparisons
            # later on easier by setting the stopped task to the parent include
            # task.
            task = self._stopped_task
            while task := task._parent:
                if isinstance(task, Task) and task.action in C._ACTION_ALL_INCLUDES:
                    break

            self._stopped_task = task

        elif (
            state == ThreadState.STEP_IN
            and self._stopped_task
            and self._stopped_task.action not in C._ACTION_ALL_INCLUDES
        ):
            # If changing to STEP_IN but the stopped task was not an include,
            # treat it like STEP_OVER.
            state = ThreadState.STEP_OVER

        self.state = state

    def should_break(
        self,
        task: Task,
        breakpoint: AnsibleLineBreakpoint | AnsibleFunctionBreakpoint | None,
        pause: bool = False,
    ) -> ansibug.dap.StoppedEvent | None:
        stopped_kwargs: dict[str, t.Any] = {}

        if self.state == ThreadState.RESTART:
            stopped_kwargs = {
                "reason": ansibug.dap.StoppedReason.RESTART,
                "description": "Restarted task",
                "thread_id": self.id,
            }

        elif self._break_step_over(task):
            stopped_kwargs = {
                "reason": ansibug.dap.StoppedReason.STEP,
                "description": "Step over",
                "thread_id": self.id,
            }
            self._stopped_task = task

        elif self._break_step_out(task):
            stopped_kwargs = {
                "reason": ansibug.dap.StoppedReason.STEP,
                "description": "Step out",
                "thread_id": self.id,
            }

        elif self._break_step_in():
            stopped_kwargs = {
                "reason": ansibug.dap.StoppedReason.STEP,
                "description": "Step in",
                "thread_id": self.id,
            }

        elif breakpoint and self.state != ThreadState.STEP_OUT:
            # Breakpoints are ignored when stepping out.
            is_function = isinstance(breakpoint, AnsibleFunctionBreakpoint)
            stopped_kwargs = {
                "reason": (
                    ansibug.dap.StoppedReason.FUNCTION_BREAKPOINT
                    if is_function
                    else ansibug.dap.StoppedReason.BREAKPOINT
                ),
                "description": "Function breakpoint hit" if is_function else "Breakpoint hit",
                "hit_breakpoint_ids": [breakpoint.id],
                "thread_id": self.id,
            }

        elif pause:
            stopped_kwargs = {
                "reason": ansibug.dap.StoppedReason.PAUSE,
                "description": "Paused",
                "thread_id": self.id,
            }

        if stopped_kwargs:
            # Any stop satisfies a pause request.
            self.pause_requested = False
            # Store this task so the step_* actions can use it when verifying
            # if the requested action for this task should cause a stop.
            self._stopped_task = task
            self.exception_info = None
            self.state = ThreadState.WAIT
            return ansibug.dap.StoppedEvent(**stopped_kwargs)

        return None

    def should_stop_on_exception(
        self,
        result: AnsibugTaskResult,
        check_filter: t.Callable[[ExceptionBreakpointType], bool],
    ) -> ansibug.dap.StoppedEvent | None:
        """Checks if the task result should stop on an exception filter.

        Args:
            result: The task result.
            check_filter: Called with the exception filter that applies to the
                result, returns whether it is enabled and its condition passes.

        Returns:
            Optional[StoppedEvent]: The stopped event if the thread should stop.
        """
        details: tuple[str, str] | None = None
        exception_id = ""
        break_mode = "unhandled"
        message: str = ""
        traceback: str | None = None

        if result.failed and not result.ignore_errors:
            is_rescued = False

            # Only a failure in a block section is rescued, not one in its
            # rescue or always section. Compare by uuid as the iterator works
            # on copies of the blocks.
            child = result.task
            while parent := child._parent:
                if isinstance(parent, Block) and parent.rescue and any(c._uuid == child._uuid for c in parent.block):
                    is_rescued = True
                    break
                child = parent

            if not is_rescued and check_filter(ExceptionBreakpointType.ON_ERROR):
                details = get_on_failed_details(result.result)
                exception_id = "Task failed"
                message, traceback = get_result_error(result.result)

        elif result.unreachable and not result.ignore_unreachable:
            if check_filter(ExceptionBreakpointType.ON_UNREACHABLE):
                details = get_on_unreachable_details(result.result)
                exception_id = "Host unreachable"
                message, traceback = get_result_error(result.result)

        elif result.skipped:
            if check_filter(ExceptionBreakpointType.ON_SKIPPED):
                details = get_on_skipped_details(result.result)
                exception_id = "Task skipped"
                # A skip is expected rather than an error.
                break_mode = "always"
                # The text after the 'Task skipped' header line.
                message = details[1].partition("\n")[2]

        if details:
            task = result.task
            self.exception_info = {
                "exception_id": exception_id,
                "description": message,
                "break_mode": break_mode,
                "details": ansibug.dap.ExceptionDetails(
                    message=message,
                    type_name=getattr(task, "resolved_action", None) or task.action,
                    stack_trace=traceback,
                ),
            }
            self._stopped_task = task
            self.state = ThreadState.WAIT
            return ansibug.dap.StoppedEvent(
                reason=ansibug.dap.StoppedReason.EXCEPTION,
                description=details[0],
                thread_id=self.id,
                preserve_focus_hint=False,
                text=details[1],
                all_threads_stopped=False,
                hit_breakpoint_ids=[],
            )

        return None

    def _break_step_over(
        self,
        task: Task,
    ) -> bool:
        if self.state != ThreadState.STEP_OVER or not self._stopped_task:
            return False

        # Break if the task has the same parent as the task which was resumed
        # with step over or if that parent is no longer in the task's parent
        # chain, i.e. the include it was in has ended.
        task_parents = [p._uuid for p in _get_parent_tasks(task)]
        stopped_parent = self._get_parent_task(self._stopped_task)
        if stopped_parent is None:
            return not task_parents

        return task_parents[:1] == [stopped_parent._uuid] or stopped_parent._uuid not in task_parents

    def _break_step_in(self) -> bool:
        # If in, then the first task to call this will need to break.
        return self.state == ThreadState.STEP_IN

    def _break_step_out(
        self,
        task: Task,
    ) -> bool:
        if self.state != ThreadState.STEP_OUT or not self._stopped_task:
            return False

        # If step out, we only want to break if the current task's parent does
        # not match the stopped task stored at state change (the include). If
        # the parent matches it means we are still in the same include scope.
        task_parent = self._get_parent_task(task)
        return getattr(task_parent, "_uuid", None) != self._stopped_task._uuid

    def _get_parent_task(
        self,
        task: Task,
    ) -> Task | None:
        return next(_get_parent_tasks(task), None)


class AnsibleStackFrame:
    def __init__(
        self,
        *,
        id: int,
        task: Task,
        task_vars: dict[str, t.Any],
        debugger: AnsibleDebugger,
    ) -> None:
        self.id = id
        self.task = task
        self.task_vars = task_vars
        self.scopes: list[int] = []
        self.variables: list[int] = []
        self.variables_options_id = 0
        self.variables_taskvar_id = 0
        self.variables_hostvars_id = 0
        self.variables_globalvars_id = 0
        self.variables_result_id = 0

        self._debugger = debugger

    def to_dap(self, can_restart: bool = False) -> ansibug.dap.StackFrame:
        task_path = self.task.get_path()

        task_path_and_line = task_path.rsplit(":", 1)
        path = task_path_and_line[0]
        line = int(task_path_and_line[1])
        client_path = self._debugger.convert_to_client_path(path)
        source = ansibug.dap.Source(name=os.path.basename(client_path), path=client_path)

        return ansibug.dap.StackFrame(
            id=self.id,
            name=self.task.get_name(),
            source=source,
            line=line,
            can_restart=can_restart,
        )


class AnsibleVariable:
    """Structure needed for an AnsibleVariable implementation."""

    def __init__(
        self,
        id: int,
        stackframe: AnsibleStackFrame,
    ) -> None:
        self.id = id
        self.stackframe = stackframe
        # Child variables created for container values, keyed by name, so
        # each variables request reuses them. Cleared when the name is changed.
        self.children: dict[str, AnsibleVariable] = {}
        # The expression that evaluates to this variable, None if there is
        # none. An empty string is the task vars where a child is its name.
        self.evaluate_name: str | None = None

    def child_evaluate_name(
        self,
        name: str,
    ) -> str | None:
        """The expression that evaluates to the child with the name."""
        if self.evaluate_name is None:
            return None
        elif not self.evaluate_name:
            return name if name.isidentifier() else None
        else:
            return f"{self.evaluate_name}[{name!r}]"

    @property
    def named_variables(self) -> int:
        return 0

    @property
    def indexed_variables(self) -> int:
        return 0

    def get(self) -> collections.abc.Iterable[tuple[str, t.Any]]:
        raise NotImplementedError()  # pragma: nocover

    def remove(
        self,
        index: str,
    ) -> None:
        raise NotImplementedError()  # pragma: nocover

    def set(
        self,
        index: str,
        value: t.Any,
    ) -> None:
        raise NotImplementedError()  # pragma: nocover


class AnsibleListVariable(AnsibleVariable):
    """AnsibleVariable with a list datastore."""

    def __init__(
        self,
        id: int,
        stackframe: AnsibleStackFrame,
        value: collections.abc.Sequence[t.Any],
    ) -> None:
        super().__init__(id, stackframe)
        self._ds = value

    @property
    def indexed_variables(self) -> int:
        return len(self._ds)

    def child_evaluate_name(
        self,
        name: str,
    ) -> str | None:
        return None if self.evaluate_name is None else f"{self.evaluate_name}[{name}]"

    def get(self) -> collections.abc.Iterable[tuple[str, t.Any]]:
        return iter((str(k), v) for k, v in enumerate(self._ds))

    def set(
        self,
        index: str,
        value: t.Any,
    ) -> None:
        self.children.pop(index, None)
        self._ds[int(index)] = value  # pyright: ignore[reportIndexIssue]


class AnsibleDictVariable(AnsibleVariable):
    """AnsibleVariable with a dict datastore."""

    def __init__(
        self,
        id: int,
        stackframe: AnsibleStackFrame,
        value: collections.abc.Mapping[t.Any, t.Any],
    ) -> None:
        super().__init__(id, stackframe)
        self._ds = value

    @property
    def named_variables(self) -> int:
        return len(self._ds)

    def get(self) -> collections.abc.Iterable[tuple[str, t.Any]]:
        return iter((str(k), v) for k, v in self._ds.items())

    def remove(
        self,
        index: str,
    ) -> None:
        self.children.pop(index, None)
        if index in self._ds:
            del self._ds[index]  # pyright: ignore[reportIndexIssue]

    def set(
        self,
        index: str,
        value: t.Any,
    ) -> None:
        self.children.pop(index, None)
        self._ds[index] = value  # pyright: ignore[reportIndexIssue]


class AnsibleDictWithRawStoreVariable(AnsibleDictVariable):
    """AnsibleDictVariable with a secondary/raw datastore to replicate changes to."""

    def __init__(
        self,
        id: int,
        stackframe: AnsibleStackFrame,
        value: collections.abc.Mapping[t.Any, t.Any],
        raw: dict[t.Any, t.Any],
    ) -> None:
        super().__init__(id, stackframe, value)
        self._raw_ds = raw

    def remove(self, index: str) -> None:
        super().remove(index)
        self._raw_ds.pop(index, None)

    def set(self, index: str, value: t.Any) -> None:
        super().set(index, value)
        self._raw_ds[index] = value


class AnsibleHostVarsVariable(AnsibleDictVariable):
    """AnsibleDictVariable with integration into a host variable manager.

    The host vars are only templated when first used as reading each value
    templates it, the scope is marked as expensive so the client only expands
    it when requested.
    """

    def __init__(
        self,
        id: int,
        stackframe: AnsibleStackFrame,
        host: str,
        variable_manager: VariableManager,
    ) -> None:
        AnsibleVariable.__init__(self, id, stackframe)
        self._host = host
        self._variable_manager = variable_manager
        # Set when _ds is built, the names that come from the inventory.
        self._inventory_keys: set[str] = set()

    @functools.cached_property
    def _ds(self) -> dict[str, t.Any]:
        # We use the hostvars but for simplicity sake we also overlay the task
        # vars that might be set as these will contain things like play/task
        # vars. The hostvars are a more persistent set of vars that last beyond
        # this task so is important to give the user a way to set these
        # persistently in the debugger.
        task_vars = self.stackframe.task_vars
        host_vars: dict[str, t.Any] = {}

        inventory_hostvars = task_vars["hostvars"][task_vars["inventory_hostname"]]
        self._inventory_keys = {str(k) for k in inventory_hostvars.keys()}
        for k in inventory_hostvars.keys():
            try:
                host_vars[k] = inventory_hostvars[k]
            except AnsibleUndefinedVariable:
                host_vars[k] = task_vars.get(k, "<undefined>")

        for k, v in task_vars.items():
            host_vars.setdefault(str(k), v)

        return host_vars

    def child_evaluate_name(
        self,
        name: str,
    ) -> str | None:
        # The task vars overlaid on the host vars aren't in hostvars.
        if name in self._ds and name in self._inventory_keys:
            return f"hostvars[inventory_hostname][{name!r}]"

        return name if name.isidentifier() else None

    def set(self, index: str, value: t.Any) -> None:
        super().set(index, value)
        # Persisting hostvars need to be done as a host_variable.
        self._variable_manager.set_host_variable(self._host, index, value)


class AnsibleDebugState(DebugState):
    """Ansible Debug State.

    A class used to handle the debug state of a strategy. It exposes
    the methods needed for interaction with the ansibug debugger.

    Args:
        debugger: The debugger instance connected to the debug adapter.
        loader: The data loader used by the strategy.
        variable_manager: The variable manager for the strategy.

    Attributes:
        threads: The debug adapter threads.
        stackframes: The debug adapter stack frames.
        variables: The debug adapter variables.
    """

    def __init__(
        self,
        debugger: AnsibleDebugger,
        loader: DataLoader,
        variable_manager: VariableManager,
    ) -> None:
        self.threads: dict[int, AnsibleThread] = {1: AnsibleThread(id=1, host=None)}
        # Lookup of threads by host as it is needed for every task on every host.
        self._host_threads: dict[Host, AnsibleThread] = {}
        self.stackframes: dict[int, AnsibleStackFrame] = {}
        self.variables: dict[int, AnsibleVariable] = {}

        self._debugger = debugger
        self._loader = loader
        self._variable_mamanger = variable_manager
        self._waiting_condition = threading.Condition()
        # Set by a pause request without a host thread, the next host to start
        # a task stops.
        self._pause_next_host = False

    def start_task(
        self,
        host: Host,
        task: Task,
        task_vars: dict[str, t.Any],
    ) -> Task:
        """Start a task.

        Processes the Ansible task before it is run. Processing a task will
        synchronize the stack frames by adding or removing the frames needed
        as well as check if a stopped even should be triggered.

        Args:
            host: The inventory host for the task.
            task: The task to process.
            task_vars: The task variables.

        Returns:
            Task: The task to run for the host. This is a copy if the client
            inspected or changed its options while stopped.
        """
        thread = self._host_threads.get(host) or self._add_thread(host)

        # Remove the frames of any includes that have ended, the top frame
        # should be the task's parent include.
        parent_task = next(_get_parent_tasks(task), None)
        while thread.stack_frames:
            last_frame = self.stackframes[thread.stack_frames[0]]
            if parent_task and last_frame.task._uuid == parent_task._uuid:
                # If this is a task in a role included by include_role we
                # need to scan the tasks and handlers to validate the
                # breakpoints.
                if last_frame.task.action in C._ACTION_INCLUDE_ROLE and hasattr(task, "_role"):
                    task_handlers = task._role.get_task_blocks()
                    role_handlers = task._role.get_handler_blocks(task.play)
                    register_block_breakpoints(self._debugger, task_handlers)
                    register_block_breakpoints(self._debugger, role_handlers)

                break

            self._pop_stackframe(thread)

        sfid = self._debugger.next_stackframe_id()

        sf = self.stackframes[sfid] = AnsibleStackFrame(
            id=sfid,
            task=task,
            task_vars=task_vars,
            debugger=self._debugger,
        )
        thread.stack_frames.insert(0, sfid)

        # Some implicit meta tasks are added without a loader so won't have
        # a path. We can't set breakpoints on these tasks so skip the check.
        task_path = task.get_path()
        if not task_path:
            return task

        path_and_line = task_path.rsplit(":", 1)
        path = path_and_line[0]
        line = int(path_and_line[1])

        with self._waiting_condition:
            tid = thread.id

            breakpoint = self._match_breakpoint(
                self._debugger.get_breakpoint(path, line), sf
            ) or self._match_breakpoint(self._debugger.get_function_breakpoint(_get_task_names(task)), sf)
            stopped_event = thread.should_break(task, breakpoint, thread.pause_requested or self._pause_next_host)

            if stopped_event:
                self._pause_next_host = False
                self._debugger.queue_msg(stopped_event)
                self._waiting_condition.wait_for(lambda: self.threads[tid].state != ThreadState.WAIT)
                self._reset_frame_variables(thread)

                # If thread is marked as end then the client has requested us
                # to terminate the debuggee.
                if thread.state == ThreadState.END:
                    raise EndStrategy()

        return sf.task

    def end_task(
        self,
        result: AnsibugTaskResult,
        can_restart: bool = False,
    ) -> Task | None:
        """Ends a task.

        Marks the task on the host specified as complete adjusting the stack
        frames for that host as needed. This will also check if an exception
        stop event should be fired.

        Args:
            result: The task result to process.
            can_restart: The caller can re-run the task if the client
                restarts the frame while stopped on the result.

        Returns:
            Task | None: The task to re-run if the client restarted the frame.
        """
        task = result.task
        thread = self._host_threads[result.host]
        sf = self.stackframes[thread.stack_frames[0]]

        def check_filter(filter_type: ExceptionBreakpointType) -> bool:
            enabled, condition = self._debugger.get_exception_filter(filter_type)
            if not enabled or not condition:
                return enabled

            return self._eval_condition(condition, sf.task_vars | {"result": result.result})

        with self._waiting_condition:
            stopped_event = thread.should_stop_on_exception(result, check_filter)
            if stopped_event:
                result_variable = self._add_variable(sf, result.result)
                sf.variables_result_id = result_variable.id
                if can_restart:
                    thread.restart_frame_id = sf.id

                self._debugger.queue_msg(stopped_event)
                self._waiting_condition.wait_for(lambda: self.threads[thread.id].state != ThreadState.WAIT)
                thread.restart_frame_id = 0
                self._reset_frame_variables(thread)

            if thread.state == ThreadState.END:
                raise EndStrategy()

        # The re-run creates a new frame in start_task, an include frame is
        # popped there as it is not the parent of the new task.
        restart = thread.state == ThreadState.RESTART
        if task.action not in C._ACTION_ALL_INCLUDES:
            self._pop_stackframe(thread)

        # The frame task has any option changes the client made while stopped.
        return sf.task if restart else None

    def exit_threads(self) -> None:
        """Exits all active threads.

        Exits all active threads and passes along the exit event to the debug
        adapter. This is used by the strategy when the inventory has
        been refreshed or the strategy is complete.
        """
        for tid in list(self.threads.keys()):
            if tid == 1:
                continue

            with self._waiting_condition:
                thread = self.threads.pop(tid)
                if thread.host:
                    self._host_threads.pop(thread.host, None)
                while thread.stack_frames:
                    self._pop_stackframe(thread)

            self._debugger.queue_msg(
                ansibug.dap.ThreadEvent(
                    reason="exited",
                    thread_id=tid,
                )
            )

    def _create_scope_variables(
        self,
        sf: AnsibleStackFrame,
    ) -> None:
        """Creates the scope variables for the frame if not already created."""
        # The client requests the scopes each time a frame is selected, only
        # create the variables once per frame.
        if not sf.variables_options_id:
            # The Task object is shared by every host, use a copy so changes to
            # the options only apply to this host. It keeps the same uuid.
            sf.task = sf.task.copy()

            # This is a very basic templating of the args and doesn't handle loops.
            templar = Templar(loader=self._loader, variables=sf.task_vars)
            task_args = templar.template(sf.task.args, fail_on_undefined=False)
            sf.variables_options_id = self._add_variable(
                sf,
                task_args,
                # Any changes to our templated var also needs to reflect back onto
                # the raw datastore so use a custom variable class.
                var_factory=lambda i: AnsibleDictWithRawStoreVariable(i, sf, task_args, sf.task.args),
            ).id
            task_vars = self._add_variable(sf, sf.task_vars)
            task_vars.evaluate_name = ""
            sf.variables_taskvar_id = task_vars.id
            sf.variables_hostvars_id = self._add_variable(
                sf,
                {},
                var_factory=lambda i: AnsibleHostVarsVariable(
                    i, sf, sf.task_vars["inventory_hostname"], self._variable_mamanger
                ),
            ).id
            global_vars = self._add_variable(sf, sf.task_vars["vars"])
            global_vars.evaluate_name = "vars"
            sf.variables_globalvars_id = global_vars.id

    def _match_breakpoint(
        self,
        breakpoint: AnsibleLineBreakpoint | AnsibleFunctionBreakpoint | None,
        sf: AnsibleStackFrame,
    ) -> AnsibleLineBreakpoint | AnsibleFunctionBreakpoint | None:
        """Applies the breakpoint's condition, hit condition, and log message.

        Returns:
            The breakpoint if it should stop the thread, otherwise None. A
            logpoint writes its message and never stops.
        """
        if not breakpoint or (breakpoint.condition and not self._eval_condition(breakpoint.condition, sf.task_vars)):
            return None

        breakpoint.hit_count += 1
        if breakpoint.hit_check and not breakpoint.hit_check(breakpoint.hit_count):
            return None

        if breakpoint.log_message:
            frame = sf.to_dap()
            self._debugger.queue_msg(
                ansibug.dap.OutputEvent(
                    category="console",
                    output=self._template_message(breakpoint.log_message, sf.task_vars) + "\n",
                    source=frame.source,
                    line=frame.line,
                )
            )
            return None

        return breakpoint

    def _template_message(
        self,
        message: str,
        variables: dict[str, t.Any],
    ) -> str:
        """Templates a logpoint message, the message can contain {{ ... }}."""
        templar = Templar(loader=self._loader, variables=variables)
        try:
            return str(templar.template(trust_as_template(message) if POST_DATATAGGING else message))  # pyright: ignore[reportPossiblyUnboundVariable]
        except Exception as e:
            return f"{message} (failed to template: {type(e).__name__}: {e})"

    def _eval_condition(
        self,
        condition: str,
        task_vars: dict[str, t.Any],
    ) -> bool:
        templar = Templar(loader=self._loader, variables=task_vars)

        if POST_DATATAGGING:
            template = trust_as_template(condition)  # pyright: ignore[reportPossiblyUnboundVariable]

            try:
                return templar.evaluate_conditional(template)
            except (AnsibleBrokenConditionalError, AnsibleUndefinedVariable):  # pyright: ignore[reportPossiblyUnboundVariable]
                return False

        else:
            cond = Conditional(loader=self._loader)
            cond.when = [condition]

            try:
                return cond.evaluate_conditional(templar, templar.available_variables)
            except AnsibleError:
                return False

    def _reset_frame_variables(
        self,
        thread: AnsibleThread,
        keep: AnsibleStackFrame | None = None,
    ) -> None:
        """Drops the cached scope variables of the thread's frames.

        Include frames live across multiple stops and the tasks run in between
        can change the host vars. Their scopes are recreated on the next stop.
        The module result does not change so is kept.

        Args:
            thread: The thread whose frames are reset.
            keep: A frame to leave as is.
        """
        for sfid in thread.stack_frames:
            sf = self.stackframes[sfid]
            if sf is keep:
                continue

            for variable_id in sf.variables:
                if variable_id != sf.variables_result_id:
                    del self.variables[variable_id]

            if sf.variables_result_id:
                sf.variables = [sf.variables_result_id]
                self.variables[sf.variables_result_id].children.clear()
            else:
                sf.variables = []

            sf.variables_options_id = 0
            sf.variables_taskvar_id = 0
            sf.variables_hostvars_id = 0
            sf.variables_globalvars_id = 0

    def _pop_stackframe(
        self,
        thread: AnsibleThread,
    ) -> None:
        sf = self.stackframes.pop(thread.stack_frames.pop(0))
        for variable_id in sf.variables:
            del self.variables[variable_id]

    def continue_request(
        self,
        request: ansibug.dap.ContinueRequest,
    ) -> None:
        thread_ids = [request.thread_id] if request.single_thread else self.threads.keys()
        self._resume_threads(thread_ids, ThreadState.CONTINUE)

    def disconnect(
        self,
        request: ansibug.dap.DisconnectRequest,
    ) -> None:
        state = ThreadState.END if request.terminate_debuggee else ThreadState.CONTINUE
        self._resume_threads(self.threads.keys(), state)

    def get_scopes(
        self,
        request: ansibug.dap.ScopesRequest,
    ) -> ansibug.dap.ScopesResponse:
        sf = self.stackframes[request.frame_id]

        self._create_scope_variables(sf)

        module_opts = self.variables[sf.variables_options_id]
        task_vars = self.variables[sf.variables_taskvar_id]
        host_vars = self.variables[sf.variables_hostvars_id]
        global_vars = self.variables[sf.variables_globalvars_id]

        scopes: list[ansibug.dap.Scope] = [
            # Options for the module itself
            ansibug.dap.Scope(
                name="Module Options",
                presentation_hint="arguments",
                variables_reference=module_opts.id,
                named_variables=module_opts.named_variables,
                indexed_variables=module_opts.indexed_variables,
            ),
            # Variables sent to the worker, complete snapshot for the task.
            ansibug.dap.Scope(
                name="Task Variables",
                presentation_hint="locals",
                variables_reference=task_vars.id,
                named_variables=task_vars.named_variables,
                indexed_variables=task_vars.indexed_variables,
            ),
            # Scoped task vars but for the current host
            ansibug.dap.Scope(
                name="Host Variables",
                variables_reference=host_vars.id,
                # Counting them requires templating each one.
                expensive=True,
            ),
            # Scoped task vars but the full vars dict
            ansibug.dap.Scope(
                name="Global Variables",
                variables_reference=global_vars.id,
                named_variables=global_vars.named_variables,
                indexed_variables=global_vars.indexed_variables,
                expensive=True,
            ),
        ]

        if sf.variables_result_id:
            result_variables = self.variables[sf.variables_result_id]
            scopes.insert(
                0,
                ansibug.dap.Scope(
                    name="Module Result",
                    variables_reference=sf.variables_result_id,
                    named_variables=result_variables.named_variables,
                    indexed_variables=result_variables.indexed_variables,
                ),
            )

        return ansibug.dap.ScopesResponse(
            request_seq=request.seq,
            scopes=scopes,
        )

    def completions(
        self,
        request: ansibug.dap.CompletionsRequest,
    ) -> ansibug.dap.CompletionsResponse:
        # The column is 1 based and the completion is for the text before it.
        text = request.text[: request.column - 1]
        sf = self.stackframes.get(request.frame_id) if request.frame_id else None

        # The name and detail of each candidate.
        candidates: dict[str, str]
        item_type = "variable"
        if command := re.fullmatch(r"\s*!(\w*)", text):
            prefix = command.group(1)
            candidates = {}
            for name, info in REPL_COMMANDS.items():
                for typed in (name, info.alias):
                    candidates[typed] = f"!{typed} {info.usage}: {info.help}"
            item_type = "keyword"
        elif option := re.fullmatch(r"\s*!(?:so|set_option|ro|remove_option)\s+(\w*)", text):
            prefix = option.group(1)
            # The raw options before templating.
            candidates = {str(k): _completion_detail(v) for k, v in sf.task.args.items()} if sf else {}
            item_type = "property"
        else:
            word = re.search(r"[A-Za-z_]\w*$", text)
            prefix = word.group(0) if word else ""
            # dict.items avoids a lazy container templating the values.
            candidates = {str(k): _completion_detail(v) for k, v in dict.items(sf.task_vars)} if sf else {}

        # VS Code reads start as a 0 based offset into the text regardless of
        # columnsStartAt1, a 1 based start makes it filter out the completions.
        start = len(text) - len(prefix)
        return ansibug.dap.CompletionsResponse(
            request_seq=request.seq,
            targets=[
                ansibug.dap.CompletionItem(
                    label=name,
                    detail=candidates[name],
                    type=item_type,
                    start=start,
                    length=len(prefix),
                )
                for name in sorted(candidates)
                if name.startswith(prefix)
            ],
        )

    def evaluate(
        self,
        request: ansibug.dap.EvaluateRequest,
    ) -> ansibug.dap.EvaluateResponse | ansibug.dap.ErrorResponse:
        value = ""
        value_type = None
        changed_variables = False

        # Known contexts and how they are used in VSCode
        # repl - Debug Console with the expression entered
        # watch - WATCH pane with an expression set
        # clipboard - VARIABLES pane, right click variable -> 'Copy Value'
        # variables - same as clipboard but only present for older code
        # hover - hovering over text in the editor, only plain variable names
        #   are resolved without templating as templating can have side effects

        expression = request.expression

        if request.context == "repl" and expression.startswith("!") and request.frame_id:
            # The following repl commands are available, all start with !
            # ro - remove option
            #   Removes the option specified from the current module options
            # so - set option
            #   Add/sets the option on the module options.
            # sh - set hostvar
            #   Adds/sets the variable on the host vars.
            # t - template
            #   Templates the expression (default behaviour without !)
            # The argparse library is used to parse this data rather than do
            # it manually.
            sf = self.stackframes[request.frame_id]
            # The client may not have requested the scopes for this frame yet.
            self._create_scope_variables(sf)

            repl_command = parse_repl_args(expression[1:])
            if isinstance(repl_command, TemplateCommand):
                value, value_type = self._safe_evaluate_expression(repl_command.expression, sf.task_vars)

            elif isinstance(repl_command, RemoveVarCommand):
                ansible_var = self.variables[sf.variables_options_id]
                ansible_var.remove(repl_command.name)
                changed_variables = True

            elif isinstance(repl_command, SetVarCommand):
                new_value = self._template_new_value(repl_command.expression, sf.task_vars)
                omitted = isinstance(new_value, OmitMarker)

                var_ids = []
                if repl_command.command == "set_option":
                    var_ids += [sf.variables_options_id]
                else:
                    # We want to have changing hostvars also apply to the task
                    # and global vars of this frame.
                    var_ids += [sf.variables_taskvar_id, sf.variables_hostvars_id, sf.variables_globalvars_id]

                if omitted and repl_command.command == "set_hostvar":
                    value = "omit can only remove a module option, it cannot remove a host variable"
                    var_ids = []

                for vid in var_ids:
                    ansible_var = self.variables[vid]
                    if omitted:
                        ansible_var.remove(repl_command.name)
                    else:
                        ansible_var.set(repl_command.name, new_value)
                changed_variables = bool(var_ids)

                if repl_command.command == "set_hostvar":
                    # The other frames of the host cached their variables,
                    # recreate them from the updated host vars.
                    if thread := next((t for t in self.threads.values() if sf.id in t.stack_frames), None):
                        self._reset_frame_variables(thread, keep=sf)

            else:
                # Error during parsing or --help was requested
                value = str(repl_command)

        elif request.context in ["repl", "watch", "clipboard", "variables"] and request.frame_id:
            sf = self.stackframes[request.frame_id]
            value, value_type = self._safe_evaluate_expression(expression, sf.task_vars)

        elif request.context == "hover" and request.frame_id:
            sf = self.stackframes[request.frame_id]
            try:
                hover_value = _resolve_raw_path(expression, sf.task_vars)
            except (KeyError, IndexError):
                # No hover is shown for an error.
                return ansibug.dap.ErrorResponse(
                    command=ansibug.dap.Command.EVALUATE,
                    request_seq=request.seq,
                    message=f"'{expression}' is not a variable",
                )

            value = _raw_repr(hover_value)
            value_type = get_canonicalized_variable_type(hover_value)

        elif not request.frame_id:
            value = "Evaluation requires a stack frame, select a frame of a stopped thread"

        else:
            value = f"Evaluation for {request.context} is not implemented"

        if changed_variables and self._debugger.supports_invalidated_event:
            # The Variables pane doesn't know the repl changed a variable.
            self._debugger.queue_msg(ansibug.dap.InvalidatedEvent(areas=["variables"]))

        return ansibug.dap.EvaluateResponse(
            request_seq=request.seq,
            result=value,
            type=value_type,
        )

    def exception_info(
        self,
        request: ansibug.dap.ExceptionInfoRequest,
    ) -> ansibug.dap.ExceptionInfoResponse | ansibug.dap.ErrorResponse:
        thread = self.threads.get(request.thread_id)
        if not thread or not thread.exception_info:
            return ansibug.dap.ErrorResponse(
                command=ansibug.dap.Command.EXCEPTION_INFO,
                request_seq=request.seq,
                message="The thread is not stopped on an exception",
            )

        return ansibug.dap.ExceptionInfoResponse(request_seq=request.seq, **thread.exception_info)

    def get_stacktrace(
        self,
        request: ansibug.dap.StackTraceRequest,
    ) -> ansibug.dap.StackTraceResponse:
        stack_frames: list[ansibug.dap.StackFrame] = []
        thread = self.threads[request.thread_id]
        for sfid in thread.stack_frames:
            sf = self.stackframes[sfid]
            stack_frames.append(sf.to_dap(can_restart=sfid == thread.restart_frame_id))

        return ansibug.dap.StackTraceResponse(
            request_seq=request.seq,
            stack_frames=stack_frames,
            total_frames=len(stack_frames),
        )

    def get_threads(
        self,
        request: ansibug.dap.ThreadsRequest,
    ) -> ansibug.dap.ThreadsResponse:
        # The strategy adds and removes threads under this lock.
        with self._waiting_condition:
            threads = [t.to_dap() for t in self.threads.values()]

        return ansibug.dap.ThreadsResponse(
            request_seq=request.seq,
            threads=threads,
        )

    def get_variables(
        self,
        request: ansibug.dap.VariablesRequest,
    ) -> ansibug.dap.VariablesResponse:
        variable = self.variables[request.variables_reference]

        # A list only has indexed variables and a dict only named variables.
        is_list = isinstance(variable, AnsibleListVariable)
        if (request.filter == "indexed" and not is_list) or (request.filter == "named" and is_list):
            return ansibug.dap.VariablesResponse(request_seq=request.seq, variables=[])

        start = request.start or 0
        page = itertools.islice(variable.get(), start, start + request.count if request.count else None)

        variables: list[ansibug.dap.Variable] = []
        for name, value in page:
            evaluate_name = variable.child_evaluate_name(name)
            child_var = variable.children.get(name)
            if child_var:
                pass
            elif _is_container(value):
                child_var = variable.children[name] = self._add_variable(variable.stackframe, value)
                child_var.evaluate_name = evaluate_name
            elif dataclasses.is_dataclass(value) and not isinstance(value, type):
                child_var = variable.children[name] = self._add_variable(variable.stackframe, dataclasses.asdict(value))
                child_var.evaluate_name = evaluate_name

            value_repr: str
            if isinstance(value, HostVars):
                # The repr would template every var of every host, the client
                # can expand it to view each host.
                # HostVars is from the untyped ansible-core so isinstance doesn't narrow value.
                value_repr = f"HostVars ({len(t.cast(t.Any, value))} hosts)"
            else:
                value_repr = repr(value)

            variables.append(
                ansibug.dap.Variable(
                    name=name,
                    value=value_repr,
                    type=get_canonicalized_variable_type(value),
                    evaluate_name=evaluate_name,
                    named_variables=child_var.named_variables if child_var else 0,
                    indexed_variables=child_var.indexed_variables if child_var else 0,
                    variables_reference=child_var.id if child_var else 0,
                )
            )

        return ansibug.dap.VariablesResponse(
            request_seq=request.seq,
            variables=variables,
        )

    def set_variable(
        self,
        request: ansibug.dap.SetVariableRequest,
    ) -> ansibug.dap.SetVariableResponse | ansibug.dap.ErrorResponse:
        variable = self.variables[request.variables_reference]

        new_value = self._template_new_value(request.value, variable.stackframe.task_vars)
        if isinstance(new_value, OmitMarker):
            if isinstance(variable, AnsibleListVariable):
                return ansibug.dap.ErrorResponse(
                    command=ansibug.dap.Command.SET_VARIABLE,
                    request_seq=request.seq,
                    message="omit cannot remove a list item",
                )

            # Like omit on a module option in the playbook, it is removed.
            variable.remove(request.name)
            if self._debugger.supports_invalidated_event:
                # The client only knows the value changed, not that it is gone.
                self._debugger.queue_msg(ansibug.dap.InvalidatedEvent(areas=["variables"]))

            return ansibug.dap.SetVariableResponse(request_seq=request.seq, value="omit")

        variable.set(request.name, new_value)

        new_container = None
        if _is_container(new_value):
            new_container = variable.children[request.name] = self._add_variable(variable.stackframe, new_value)

        return ansibug.dap.SetVariableResponse(
            request_seq=request.seq,
            value=repr(new_value),
            type=get_canonicalized_variable_type(new_value),
            variables_reference=new_container.id if new_container else 0,
            named_variables=new_container.named_variables if new_container else 0,
            indexed_variables=new_container.indexed_variables if new_container else 0,
        )

    def pause(
        self,
        request: ansibug.dap.PauseRequest,
    ) -> None:
        # A running module cannot be interrupted, the thread stops before its
        # next task so tell the user it is waiting.
        with self._waiting_condition:
            thread = self.threads.get(request.thread_id)
            if thread and thread.state == ThreadState.WAIT:
                return

            if thread and thread.host:
                host = thread.host.get_name()
                already = thread.pause_requested
                thread.pause_requested = True
                msg = f"{host} is already pausing" if already else f"Pausing {host}"
                msg += ", it will stop before its next task starts."

            else:
                # The main thread or a thread that has since exited.
                already = self._pause_next_host
                self._pause_next_host = True
                msg = "Already pausing" if already else "Pausing"
                msg += ", the next host to start a task will stop."

        # Shown in the terminal running ansible-playbook alongside its output.
        display.display(f"ansibug: {msg}")

    def restart_frame(
        self,
        request: ansibug.dap.RestartFrameRequest,
    ) -> ansibug.dap.ErrorResponse | None:
        with self._waiting_condition:
            thread = next(
                (t for t in self.threads.values() if t.restart_frame_id and t.restart_frame_id == request.frame_id),
                None,
            )
            if not thread or thread.state != ThreadState.WAIT:
                return ansibug.dap.ErrorResponse(
                    command=ansibug.dap.Command.RESTART_FRAME,
                    request_seq=request.seq,
                    message="Only the task of a host stopped on a failed, unreachable, or skipped result can be restarted",
                )

            # Sent before resuming so it is ahead of the restart StoppedEvent.
            self._debugger.queue_msg(ansibug.dap.RestartFrameResponse(request_seq=request.seq))
            thread.set_state(ThreadState.RESTART)
            self._waiting_condition.notify_all()

        return None

    def step_in(
        self,
        request: ansibug.dap.StepInRequest,
    ) -> None:
        self._resume_threads([request.thread_id], ThreadState.STEP_IN)

    def step_out(
        self,
        request: ansibug.dap.StepOutRequest,
    ) -> None:
        self._resume_threads([request.thread_id], ThreadState.STEP_OUT)

    def step_over(
        self,
        request: ansibug.dap.NextRequest,
    ) -> None:
        self._resume_threads([request.thread_id], ThreadState.STEP_OVER)

    def _add_thread(
        self,
        host: Host,
    ) -> AnsibleThread:
        tid = self._debugger.next_thread_id()

        with self._waiting_condition:
            thread = self.threads[tid] = self._host_threads[host] = AnsibleThread(
                id=tid,
                host=host,
            )
        self._debugger.queue_msg(
            ansibug.dap.ThreadEvent(
                reason="started",
                thread_id=tid,
            )
        )

        return thread

    def _add_variable(
        self,
        stackframe: AnsibleStackFrame,
        value: collections.abc.Mapping[t.Any, t.Any] | collections.abc.Sequence[t.Any],
        var_factory: t.Callable[[int], AnsibleVariable] | None = None,
    ) -> AnsibleVariable:
        var_id = self._debugger.next_variable_id()

        if var_factory:
            var = var_factory(var_id)

        elif isinstance(value, collections.abc.Mapping):
            var = AnsibleDictVariable(var_id, stackframe, value)

        else:
            var = AnsibleListVariable(var_id, stackframe, value)

        self.variables[var_id] = var
        stackframe.variables.append(var_id)

        return var

    def _resume_threads(
        self,
        thread_ids: collections.abc.Iterable[int],
        thread_state: ThreadState,
    ) -> None:
        with self._waiting_condition:
            for tid in thread_ids:
                # The thread may have exited since the client last saw it.
                if thread := self.threads.get(tid):
                    thread.set_state(thread_state)

            self._waiting_condition.notify_all()

    def _safe_evaluate_expression(
        self,
        expression: str,
        task_vars: dict[t.Any, t.Any],
    ) -> tuple[t.Any, str | None]:
        """Evaluates an expression with a fallback on exception."""
        value_type = None
        try:
            templated_value = self._template(expression, task_vars)
        except AnsibleUndefinedVariable as e:
            value = f"{type(e).__name__}: {e!s}"
        except Exception as e:
            value = traceback.format_exc()
        else:
            value = repr(templated_value)
            value_type = get_canonicalized_variable_type(templated_value)

        return value, value_type

    def _template_new_value(
        self,
        expression: str,
        variables: dict[t.Any, t.Any],
    ) -> OmitMarker | t.Any:
        """Templates a value to set, OmitMarker if it was omit and should be removed instead."""
        try:
            return self._template(expression, variables)
        except _OMIT_ERRORS:
            return OmitMarker()

    def _template(
        self,
        value: str,
        variables: dict[t.Any, t.Any],
    ) -> t.Any:
        templar = Templar(loader=self._loader, variables=variables)
        expression = "{{ %s }}" % value  # noqa: UP031 # format() would need the Jinja braces escaped

        if POST_DATATAGGING:
            expression = trust_as_template(expression)  # pyright: ignore[reportPossiblyUnboundVariable]

        elif not C.DEFAULT_JINJA2_NATIVE:
            # Always use native types even if the config has not been enabled as
            # it allows expressions like `1` to be returned as an int and keeps
            # things consistent.
            templar = templar.copy_with_new_env(environment_class=AnsibleNativeEnvironment)  # pyright: ignore[reportPossiblyUnboundVariable]

        return templar.template(expression)
