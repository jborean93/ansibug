# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

DOCUMENTATION = """
name: debug
short_description: Executes tasks with a Debug Adapter Protocol debugger
description:
- Acts like the linear strategy plugin but adds functionality for interacting
  with a Debug Adapter Protocol (DAP) debugger, like one used by
  Visual Studio Code.
author: Jordan Borean (@jborean93)
"""

import collections.abc
import enum
import inspect
import logging
import os
import threading
import traceback
import typing as t

from ansible import constants as C
from ansible.errors import AnsibleError, AnsibleUndefinedVariable
from ansible.executor.play_iterator import PlayIterator
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.executor.task_result import TaskResult
from ansible.inventory.host import Host
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.block import Block
from ansible.playbook.conditional import Conditional
from ansible.playbook.included_file import IncludedFile
from ansible.playbook.play_context import PlayContext
from ansible.playbook.task import Task
from ansible.plugins.strategy.linear import StrategyModule as LinearStrategy
from ansible.template import AnsibleNativeEnvironment, Templar
from ansible.utils.display import Display
from ansible.vars.manager import VariableManager

import ansibug
from ansibug._debuggee import (
    AnsibleDebugger,
    AnsibleLineBreakpoint,
    DebugState,
    EndStrategy,
)

from ..plugin_utils._breakpoints import register_block_breakpoints
from ..plugin_utils._repl_util import (
    RemoveVarCommand,
    SetVarCommand,
    TemplateCommand,
    parse_repl_args,
)

display = Display()
log = logging.getLogger("ansibug.strategy")


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
        breakpoint: AnsibleLineBreakpoint | None,
    ) -> ansibug.dap.StoppedEvent | None:
        stopped_kwargs: dict[str, t.Any] = {}

        if self._break_step_over(task):
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
            stopped_kwargs = {
                "reason": ansibug.dap.StoppedReason.BREAKPOINT,
                "description": "Breakpoint hit",
                "hit_breakpoint_ids": [breakpoint.id],
                "thread_id": self.id,
            }

        if stopped_kwargs:
            # Store this task so the step_* actions can use it when verifying
            # if the requested action for this task should cause a stop.
            self._stopped_task = task
            self.state = ThreadState.WAIT
            return ansibug.dap.StoppedEvent(**stopped_kwargs)

        return None

    def _break_step_over(
        self,
        task: Task,
    ) -> bool:
        if self.state != ThreadState.STEP_OVER or not self._stopped_task:
            return False

        # Get the parent task of the current task being evaluated as well as
        # the task which was resumed with step over. If they are the same then
        # the task should stop.
        task_parent = self._get_parent_task(task)
        stopped_parent = self._get_parent_task(self._stopped_task)

        return getattr(task_parent, "_uuid", None) == getattr(stopped_parent, "_uuid", None)

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
        while task := task._parent:
            if isinstance(task, Task):
                return task

        return None


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

        self._debugger = debugger

    def to_dap(self) -> ansibug.dap.StackFrame:
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

    def get(self) -> collections.abc.Iterable[tuple[str, t.Any]]:
        return iter((str(k), v) for k, v in enumerate(self._ds))

    def set(
        self,
        index: str,
        value: t.Any,
    ) -> None:
        self._ds[int(index)] = value  # type: ignore[index]


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
        if index in self._ds:
            del self._ds[index]  # type: ignore[attr-defined]

    def set(
        self,
        index: str,
        value: t.Any,
    ) -> None:
        self._ds[index] = value  # type: ignore[index]


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
    """AnsibleDictVariable with integration into a host variable manager."""

    def __init__(
        self,
        id: int,
        stackframe: AnsibleStackFrame,
        value: collections.abc.Mapping[t.Any, t.Any],
        host: str,
        variable_manager: VariableManager,
    ) -> None:
        super().__init__(id, stackframe, value)
        self._host = host
        self._variable_manager = variable_manager

    def set(self, index: str, value: t.Any) -> None:
        super().set(index, value)
        # Persisting hostvars need to be done as a host_variable.
        self._variable_manager.set_host_variable(self._host, index, value)


class AnsibleDebugState(DebugState):
    """Ansible Debug State.

    A class used to handle the debug state with a strategy plugin. It exposes
    the methods needed for interaction with the ansibug debugger.

    Args:
        debugger: The debugger instance connected to the debug adapter.
        loader: The data loader used by the strategy plugin.
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
        self.stackframes: dict[int, AnsibleStackFrame] = {}
        self.variables: dict[int, AnsibleVariable] = {}

        self._debugger = debugger
        self._loader = loader
        self._variable_mamanger = variable_manager
        self._waiting_condition = threading.Condition()

    def start_task(
        self,
        host: Host,
        task: Task,
        task_vars: dict[str, t.Any],
    ) -> None:
        """Start a task.

        Processes the Ansible task before it is run. Processing a task will
        synchronize the stack frames by adding or removing the frames needed
        as well as check if a stopped even should be triggered.

        Args:
            host: The inventory host for the task.
            task: The task to process.
            task_vars: The task variables.
        """
        thread: AnsibleThread | None = next(
            iter([t for t in self.threads.values() if t.host == host]),
            None,
        )
        if not thread:
            thread = self._add_thread(host)

        if thread.stack_frames:
            # The parent is the implicit block and we want the parent of that.
            parent_task = task._parent._parent
            last_frame_id = thread.stack_frames[0]
            last_frame = self.stackframes[last_frame_id]
            if not parent_task or (last_frame.task and last_frame.task._uuid != parent_task._uuid):
                thread.stack_frames.pop(0)
                self.stackframes.pop(last_frame_id)
                for variable_id in last_frame.variables:
                    del self.variables[variable_id]

            # If this is the first task in a role included by include_role we
            # need to scan the tasks and handlers to validate the breakpoints
            if (
                parent_task
                and last_frame.task
                and last_frame.task.action in C._ACTION_INCLUDE_ROLE
                and hasattr(task, "_role")
            ):
                task_handlers = task._role.get_task_blocks()
                role_handlers = task._role.get_handler_blocks(task.play)
                register_block_breakpoints(self._debugger, task_handlers)
                register_block_breakpoints(self._debugger, role_handlers)

        sfid = self._debugger.next_stackframe_id()

        sf = self.stackframes[sfid] = AnsibleStackFrame(
            id=sfid,
            task=task,
            task_vars=task_vars,
            debugger=self._debugger,
        )
        thread.stack_frames.insert(0, sfid)

        task_path = task.get_path()
        path_and_line = task_path.rsplit(":", 1)
        path = path_and_line[0]
        line = int(path_and_line[1])

        templar = Templar(loader=self._loader, variables=sf.task_vars)

        with self._waiting_condition:
            tid = thread.id

            line_breakpoint = self._debugger.get_breakpoint(path, line)
            if line_breakpoint and line_breakpoint.source_breakpoint.condition:
                cond = Conditional(loader=self._loader)
                cond.when = [line_breakpoint.source_breakpoint.condition]

                try:
                    if not cond.evaluate_conditional(templar, templar.available_variables):
                        line_breakpoint = None
                except AnsibleError:
                    # Treat a broken template as a false condition result.
                    line_breakpoint = None

            stopped_event = thread.should_break(task, line_breakpoint)

            if stopped_event:
                self._debugger.queue_msg(stopped_event)
                self._waiting_condition.wait_for(lambda: self.threads[tid].state != ThreadState.WAIT)

                # If thread is marked as end then the client has requested us
                # to terminate the debuggee.
                if thread.state == ThreadState.END:
                    raise EndStrategy()

    def end_task(
        self,
        host: Host,
        task: Task,
    ) -> None:
        """Ends a task.

        Marks the task on the host specified as complete adjusting the stack
        frames for that host as needed.

        Args:
            host: The inventory host for the task.
            task: The task to process.
        """
        thread = next(iter([t for t in self.threads.values() if t.host == host]))

        if task.action not in C._ACTION_ALL_INCLUDES:
            sfid = thread.stack_frames.pop(0)
            sf = self.stackframes.pop(sfid)
            for variable_id in sf.variables:
                del self.variables[variable_id]

    def exit_threads(self) -> None:
        """Exits all active threads.

        Exits all active threads and passes along the exit event to the debug
        adapter. This is used by the strategy plugin when the inventory has
        been refreshed or the strategy is complete.
        """
        for tid in list(self.threads.keys()):
            if tid == 1:
                continue

            del self.threads[tid]
            self._debugger.queue_msg(
                ansibug.dap.ThreadEvent(
                    reason="exited",
                    thread_id=tid,
                )
            )

    def continue_request(
        self,
        request: ansibug.dap.ContinueRequest,
    ) -> ansibug.dap.ContinueResponse:
        if request.single_thread:
            self._resume_threads([request.thread_id], ThreadState.CONTINUE)
            all_threads_continued = False
        else:
            self._resume_threads(self.threads.keys(), ThreadState.CONTINUE)
            all_threads_continued = True

        return ansibug.dap.ContinueResponse(
            request_seq=request.seq,
            all_threads_continued=all_threads_continued,
        )

    def disconnect(
        self,
        request: ansibug.dap.DisconnectRequest,
    ) -> None:
        state = ThreadState.END if request.terminate_debuggee else ThreadState.CONTINUE
        self._resume_threads(list(self.threads.keys()), state)

    def get_scopes(
        self,
        request: ansibug.dap.ScopesRequest,
    ) -> ansibug.dap.ScopesResponse:
        sf = self.stackframes[request.frame_id]

        # This is a very basic templating of the args and doesn't handle loops.
        templar = Templar(loader=self._loader, variables=sf.task_vars)
        task_args = templar.template(sf.task.args, fail_on_undefined=False)
        module_opts = self._add_variable(
            sf,
            task_args,
            # Any changes to our templated var also needs to reflect back onto
            # the raw datastore so use a custom variable class.
            var_factory=lambda i: AnsibleDictWithRawStoreVariable(i, sf, task_args, sf.task.args),
        )
        sf.variables_options_id = module_opts.id

        task_vars = self._add_variable(sf, sf.task_vars)
        sf.variables_taskvar_id = task_vars.id

        # We use the hostvars but for simplicity sake we also overlay the task
        # vars that might be set as these will contain things like play/task
        # vars. The hostvars are a more persistent set of vars that last beyond
        # this task so is important to give the user a way to set these
        # persistently in the debugger.
        host_vars_amalgamated = {k: v for k, v in sf.task_vars["hostvars"][sf.task_vars["inventory_hostname"]].items()}
        for k, v in task_vars.get():
            if k not in host_vars_amalgamated:
                host_vars_amalgamated[k] = v

        host_vars = self._add_variable(
            sf,
            host_vars_amalgamated,
            var_factory=lambda i: AnsibleHostVarsVariable(
                i, sf, host_vars_amalgamated, sf.task_vars["inventory_hostname"], self._variable_mamanger
            ),
        )
        sf.variables_hostvars_id = host_vars.id

        global_vars = self._add_variable(sf, sf.task_vars["vars"])

        scopes: list[ansibug.dap.Scope] = [
            # Options for the module itself
            ansibug.dap.Scope(
                name="Module Options",
                variables_reference=module_opts.id,
                named_variables=module_opts.named_variables,
                indexed_variables=module_opts.indexed_variables,
            ),
            # Variables sent to the worker, complete snapshot for the task.
            ansibug.dap.Scope(
                name="Task Variables",
                variables_reference=task_vars.id,
                named_variables=task_vars.named_variables,
                indexed_variables=task_vars.indexed_variables,
            ),
            # Scoped task vars but for the current host
            ansibug.dap.Scope(
                name="Host Variables",
                variables_reference=host_vars.id,
                named_variables=host_vars.named_variables,
                indexed_variables=host_vars.indexed_variables,
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

        return ansibug.dap.ScopesResponse(
            request_seq=request.seq,
            scopes=scopes,
        )

    def evaluate(
        self,
        request: ansibug.dap.EvaluateRequest,
    ) -> ansibug.dap.EvaluateResponse:
        value = ""
        value_type = None

        # Known contexts and how they are used in VSCode
        # repl - Debug Console with the expression entered
        # watch - WATCH pane with an expression set
        # clipboard - VARIABLES pane, right click variable -> 'Copy Value'
        # variables - same as clipboard but only present for older code
        # hover - not used as we don't set the capability, a bit dangerous to enable IMO

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

            repl_command = parse_repl_args(expression[1:])
            if isinstance(repl_command, TemplateCommand):
                value, value_type = self._safe_evaluate_expression(repl_command.expression, sf.task_vars)

            elif isinstance(repl_command, RemoveVarCommand):
                ansible_var = self.variables[sf.variables_options_id]
                ansible_var.remove(repl_command.name)

            elif isinstance(repl_command, SetVarCommand):
                new_value = self._template(repl_command.expression, sf.task_vars)

                var_ids = []
                if repl_command.command == "set_option":
                    var_ids += [sf.variables_options_id]
                else:
                    # We want to have changing hostvars also apply to the task
                    # vars
                    var_ids += [sf.variables_taskvar_id, sf.variables_hostvars_id]

                for vid in var_ids:
                    ansible_var = self.variables[vid]
                    ansible_var.set(repl_command.name, new_value)

            else:
                # Error during parsing or --help was requested
                value = str(repl_command)

        elif request.context in ["repl", "watch", "clipboard", "variables"] and request.frame_id:
            sf = self.stackframes[request.frame_id]
            value, value_type = self._safe_evaluate_expression(expression, sf.task_vars)

        else:
            value = f"Evaluation for {request.context} is not implemented"

        return ansibug.dap.EvaluateResponse(
            request_seq=request.seq,
            result=value,
            type=value_type,
        )

    def get_stacktrace(
        self,
        request: ansibug.dap.StackTraceRequest,
    ) -> ansibug.dap.StackTraceResponse:
        stack_frames: list[ansibug.dap.StackFrame] = []
        thread = self.threads[request.thread_id]
        for sfid in thread.stack_frames:
            sf = self.stackframes[sfid]
            stack_frames.append(sf.to_dap())

        return ansibug.dap.StackTraceResponse(
            request_seq=request.seq,
            stack_frames=stack_frames,
            total_frames=len(stack_frames),
        )

    def get_threads(
        self,
        request: ansibug.dap.ThreadsRequest,
    ) -> ansibug.dap.ThreadsResponse:
        return ansibug.dap.ThreadsResponse(
            request_seq=request.seq,
            threads=[t.to_dap() for t in self.threads.values()],
        )

    def get_variables(
        self,
        request: ansibug.dap.VariablesRequest,
    ) -> ansibug.dap.VariablesResponse:
        variable = self.variables[request.variables_reference]

        variables: list[ansibug.dap.Variable] = []
        for name, value in variable.get():
            child_var: AnsibleVariable | None = None
            if isinstance(value, (collections.abc.Mapping, collections.abc.Sequence)) and not isinstance(value, str):
                child_var = self._add_variable(variable.stackframe, value)

            variables.append(
                ansibug.dap.Variable(
                    name=name,
                    value=repr(value),
                    type=type(value).__name__,
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
    ) -> ansibug.dap.SetVariableResponse:
        variable = self.variables[request.variables_reference]

        new_value = self._template(request.value, variable.stackframe.task_vars)
        variable.set(request.name, new_value)

        new_container = None
        if isinstance(new_value, (collections.abc.Mapping, collections.abc.Sequence)) and not isinstance(
            new_value, str
        ):
            new_container = self._add_variable(variable.stackframe, new_value)

        return ansibug.dap.SetVariableResponse(
            request_seq=request.seq,
            value=repr(new_value),
            type=type(new_value).__name__,
            variables_reference=new_container.id if new_container else 0,
            named_variables=new_container.named_variables if new_container else 0,
            indexed_variables=new_container.indexed_variables if new_container else 0,
        )

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

        thread = self.threads[tid] = AnsibleThread(
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
                self.threads[tid].set_state(thread_state)

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
            value_type = type(templated_value).__name__

        return value, value_type

    def _template(
        self,
        value: str,
        variables: dict[t.Any, t.Any],
    ) -> t.Any:
        templar = Templar(loader=self._loader, variables=variables)

        # Always use native types even if the config has not been enabled as it
        # allows expressions like `1` to be returned as an int and keeps things
        # consistent.
        if not C.DEFAULT_JINJA2_NATIVE:
            templar = templar.copy_with_new_env(environment_class=AnsibleNativeEnvironment)

        expression = "{{ %s }}" % value

        return templar.template(expression)


class StrategyModule(LinearStrategy):
    def __init__(
        self,
        tqm: TaskQueueManager,
    ) -> None:
        super().__init__(tqm)

        # Used for type annotation checks, technically defined in __init__ as well
        self._tqm = tqm

        # Set in run()
        self._debug_state: AnsibleDebugState

    def _execute_meta(
        self,
        task: Task,
        play_context: PlayContext,
        iterator: PlayIterator,
        target_host: Host,
    ) -> list[dict[str, t.Any]]:
        """Called when a meta task is about to run"""
        # This is super ick but recreating the vars just for meta tasks would
        # involve too many internal attributes so just get it from the parent
        # locals.

        task_vars = inspect.currentframe().f_back.f_locals["task_vars"]  # type: ignore[union-attr]  # I know this is bad
        self._debug_state.start_task(target_host, task, task_vars)
        res = super()._execute_meta(task, play_context, iterator, target_host)

        meta_action = task.args.get("_raw_params", None)
        if meta_action == "refresh_inventory":
            # refresh_inventory will update the uuid on the host object, we
            # need to mark the existing threads as exited so the next run will
            # pick up the correct changes. It will automatically start those
            # threads as they run.
            self._debug_state.exit_threads()

        else:
            # Needed to ensure the stackframe is removed as these meta tasks
            # have no results for _process_pending_results to handle.
            self._debug_state.end_task(target_host, task)

        return res

    def _load_included_file(
        self,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> list[Block]:
        included_blocks = super()._load_included_file(*args, **kwargs)

        # Need to register these blocks as valid breakpoints and update the client bps
        register_block_breakpoints(self._debug_state._debugger, included_blocks)

        return included_blocks

    def _queue_task(
        self,
        host: Host,
        task: Task,
        task_vars: dict[str, t.Any],
        play_context: PlayContext,
    ) -> None:
        """Called just as a task is about to be queue"""
        self._debug_state.start_task(host, task, task_vars)

        return super()._queue_task(host, task, task_vars, play_context)

    def _process_pending_results(
        self,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> list[TaskResult]:
        """Called when gathering the results of a queued task."""
        res = super()._process_pending_results(*args, **kwargs)

        for task_res in res:
            self._debug_state.end_task(task_res._host, task_res._task)

        return res

    def run(
        self,
        iterator: PlayIterator,
        play_context: PlayContext,
    ) -> int:
        """Main strategy entrypoint.

        This is the main strategy entrypoint that is called per play. The first
        step is to associate the current strategy with the debuggee adapter so
        it can respond to breakpoint and other information.
        """
        debugger = AnsibleDebugger()
        self._debug_state = AnsibleDebugState(
            debugger,
            self._loader,
            self._variable_manager,
        )
        try:
            with debugger.with_strategy(self._debug_state):
                try:
                    return super().run(iterator, play_context)
                finally:
                    self._debug_state.exit_threads()

        except EndStrategy:
            display.display("Debugger has requested the process to terminate")
            return TaskQueueManager.RUN_FAILED_BREAK_PLAY
