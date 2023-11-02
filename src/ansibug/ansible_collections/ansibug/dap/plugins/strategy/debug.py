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
from ansible.playbook.play import Play
from ansible.playbook.play_context import PlayContext
from ansible.playbook.task import Task
from ansible.plugins.strategy.linear import StrategyModule as LinearStrategy
from ansible.template import AnsibleNativeEnvironment, Templar
from ansible.utils.display import Display
from ansible.vars.manager import VariableManager

import ansibug
from ansibug._debuggee import AnsibleDebugger, DebugState

from ..plugin_utils._repl_util import (
    RemoveVarCommand,
    SetVarCommand,
    TemplateCommand,
    parse_repl_args,
)

display = Display()


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

    stepping_type: t.Literal["in", "out", "over"] | None = None
    stepping_task: Task | None = None

    def to_dap(self) -> ansibug.dap.Thread:
        return ansibug.dap.Thread(
            id=self.id,
            name=self.host.get_name() if self.host else "main",
        )

    def break_step_over(
        self,
        task: Task,
    ) -> bool:
        if self.stepping_type != "over" or not self.stepping_task:
            return False

        while task := task._parent:
            if isinstance(task, Task):
                break

        stepping_task = self.stepping_task
        while stepping_task := stepping_task._parent:
            if isinstance(stepping_task, Task):
                break

        # If over, this should only break if the task shares the same parent as
        # the previous stepping task.
        return getattr(stepping_task, "_uuid", None) == getattr(task, "_uuid", None)

    def break_step_in(self) -> bool:
        # If in, then the first task to call this will need to break.
        return self.stepping_type == "in"

    def break_step_out(
        self,
        task: Task,
    ) -> bool:
        if self.stepping_type != "out" or not self.stepping_task:
            return False

        # If out, then the first task that does not have the stepping_task as
        # its parent will need to break.
        while task := task._parent:
            if task._uuid == self.stepping_task._uuid:
                return False

        return True


class AnsibleStackFrame:
    def __init__(
        self,
        *,
        id: int,
        task: Task,
        task_vars: dict[str, t.Any],
    ) -> None:
        self.id = id
        self.task = task
        self.task_vars = task_vars
        self.scopes: list[int] = []
        self.variables: list[int] = []
        self.variables_options_id = 0
        self.variables_hostvars_id = 0

    def to_dap(self) -> ansibug.dap.StackFrame:
        task_path = self.task.get_path()

        task_path_and_line = task_path.rsplit(":", 1)
        path = task_path_and_line[0]
        line = int(task_path_and_line[1])
        source = ansibug.dap.Source(name=os.path.basename(path), path=path)

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
    def __init__(
        self,
        debugger: AnsibleDebugger,
        loader: DataLoader,
        iterator: PlayIterator,
        play: Play,
        variable_manager: VariableManager,
    ) -> None:
        self.threads: dict[int, AnsibleThread] = {1: AnsibleThread(id=1, host=None)}
        self.stackframes: dict[int, AnsibleStackFrame] = {}
        self.variables: dict[int, AnsibleVariable] = {}

        self._debugger = debugger
        self._loader = loader
        self._iterator = iterator
        self._play = play
        self._variable_mamanger = variable_manager

        self._waiting_condition = threading.Condition()
        self._waiting_threads: dict[int, t.Literal["in", "out", "over"] | None] = {}
        self._waiting_ended = False

    def process_task(
        self,
        host: Host,
        task: Task,
        task_vars: dict[str, t.Any],
    ) -> AnsibleStackFrame:
        thread: AnsibleThread | None = next(
            iter([t for t in self.threads.values() if t.host == host]),
            None,
        )
        if not thread:
            thread = self.add_thread(host)

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

        sfid = self._debugger.next_stackframe_id()

        sf = self.stackframes[sfid] = AnsibleStackFrame(
            id=sfid,
            task=task,
            task_vars=task_vars,
        )
        thread.stack_frames.insert(0, sfid)

        task_path = task.get_path()
        path_and_line = task_path.rsplit(":", 1)
        path = path_and_line[0]
        line = int(path_and_line[1])

        templar = Templar(loader=self._loader, variables=sf.task_vars)

        with self._waiting_condition:
            tid = thread.id

            stopped_kwargs: dict[str, t.Any] = {}
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

            if thread.break_step_over(task):
                stopped_kwargs = {
                    "reason": ansibug.dap.StoppedReason.STEP,
                    "description": "Step over",
                }

            elif thread.break_step_out(task):
                stopped_kwargs = {
                    "reason": ansibug.dap.StoppedReason.STEP,
                    "description": "Step out",
                }

            elif thread.break_step_in():
                stopped_kwargs = {
                    "reason": ansibug.dap.StoppedReason.STEP,
                    "description": "Step in",
                }

            # Breakpoints are ignored when in step out mode.
            elif thread.stepping_type != "out" and line_breakpoint:
                stopped_kwargs = {
                    "reason": ansibug.dap.StoppedReason.BREAKPOINT,
                    "description": "Breakpoint hit",
                    "hit_breakpoint_ids": [line_breakpoint.id],
                }

            if stopped_kwargs:
                stopped_event = ansibug.dap.StoppedEvent(
                    thread_id=tid,
                    **stopped_kwargs,
                )
                self._debugger.send(stopped_event)
                self._waiting_condition.wait_for(lambda: self._waiting_ended or tid in self._waiting_threads)
                if self._waiting_ended:
                    # ended() was called and the connection has been closed, do
                    # not try and process the result.
                    return sf

                stepping_type = self._waiting_threads.pop(tid)
                if stepping_type == "in" and task.action not in C._ACTION_ALL_INCLUDES:
                    stepping_type = "over"

                if stepping_type:
                    thread.stepping_type = stepping_type

                    stepping_task = task
                    if stepping_type == "out":
                        while stepping_task := stepping_task._parent:
                            if isinstance(stepping_task, Task) and stepping_task.action in C._ACTION_ALL_INCLUDES:
                                break

                    thread.stepping_task = stepping_task
                else:
                    thread.stepping_type = None
                    thread.stepping_task = None

        return sf

    def process_task_result(
        self,
        host: Host,
        task: Task,
    ) -> None:
        thread = next(iter([t for t in self.threads.values() if t.host == host]))

        if task.action not in C._ACTION_ALL_INCLUDES:
            sfid = thread.stack_frames.pop(0)
            sf = self.stackframes.pop(sfid)
            for variable_id in sf.variables:
                del self.variables[variable_id]

    def add_thread(
        self,
        host: Host,
    ) -> AnsibleThread:
        tid = self._debugger.next_thread_id()

        thread = self.threads[tid] = AnsibleThread(
            id=tid,
            host=host,
        )
        self._debugger.send(
            ansibug.dap.ThreadEvent(
                reason="started",
                thread_id=tid,
            )
        )

        return thread

    def add_variable(
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

    def remove_thread(
        self,
        tid: int,
    ) -> None:
        self.threads.pop(tid, None)

        self._debugger.send(
            ansibug.dap.ThreadEvent(
                reason="exited",
                thread_id=tid,
            )
        )

    def ended(self) -> None:
        with self._waiting_condition:
            self._waiting_ended = True
            self._waiting_threads = {}
            self._waiting_condition.notify_all()

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

                variable_id = (
                    sf.variables_options_id if repl_command.command == "set_option" else sf.variables_hostvars_id
                )
                ansible_var = self.variables[variable_id]
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

    def continue_request(
        self,
        request: ansibug.dap.ContinueRequest,
    ) -> ansibug.dap.ContinueResponse:
        if request.single_thread:
            self._continue([request.thread_id], None)
            all_threads_continued = False
        else:
            self._continue(self._waiting_threads.keys(), None)
            all_threads_continued = True

        return ansibug.dap.ContinueResponse(
            request_seq=request.seq,
            all_threads_continued=all_threads_continued,
        )

    def get_scopes(
        self,
        request: ansibug.dap.ScopesRequest,
    ) -> ansibug.dap.ScopesResponse:
        sf = self.stackframes[request.frame_id]

        # This is a very basic templating of the args and doesn't handle loops.
        templar = Templar(loader=self._loader, variables=sf.task_vars)
        task_args = templar.template(sf.task.args, fail_on_undefined=False)
        module_opts = self.add_variable(
            sf,
            task_args,
            # Any changes to our templated var also needs to reflect back onto
            # the raw datastore so use a custom variable class.
            var_factory=lambda i: AnsibleDictWithRawStoreVariable(i, sf, task_args, sf.task.args),
        )
        sf.variables_options_id = module_opts.id

        task_vars = self.add_variable(sf, sf.task_vars)

        # We use the hostvars but for simplicity sake we also overlay the task
        # vars that might be set as these will contain things like play/task
        # vars. The hostvars are a more persistent set of vars that last beyond
        # this task so is important to give the user a way to set these
        # persistently in the debugger.
        host_vars_amalgamated = {k: v for k, v in sf.task_vars["hostvars"][sf.task_vars["inventory_hostname"]].items()}
        for k, v in task_vars.get():
            if k not in host_vars_amalgamated:
                host_vars_amalgamated[k] = v

        host_vars = self.add_variable(
            sf,
            host_vars_amalgamated,
            var_factory=lambda i: AnsibleHostVarsVariable(
                i, sf, host_vars_amalgamated, sf.task_vars["inventory_hostname"], self._variable_mamanger
            ),
        )
        sf.variables_hostvars_id = host_vars.id

        global_vars = self.add_variable(sf, sf.task_vars["vars"])

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

    def get_stacktrace(
        self,
        request: ansibug.dap.StackTraceRequest,
    ) -> ansibug.dap.StackTraceResponse:
        with self._waiting_condition:
            wait_info = self._waiting_threads.get(request.thread_id, None)

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
                child_var = self.add_variable(variable.stackframe, value)

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
            new_container = self.add_variable(variable.stackframe, new_value)

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
        self._continue([request.thread_id], "in")

    def step_out(
        self,
        request: ansibug.dap.StepOutRequest,
    ) -> None:
        self._continue([request.thread_id], "out")

    def step_over(
        self,
        request: ansibug.dap.NextRequest,
    ) -> None:
        self._continue([request.thread_id], "over")

    def _continue(
        self,
        thread_ids: collections.abc.Iterable[int],
        action: t.Literal["in", "out", "over"] | None,
    ) -> None:
        with self._waiting_condition:
            for tid in thread_ids:
                self._waiting_threads[tid] = action

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
        return super()._execute_meta(task, play_context, iterator, target_host)

    def _load_included_file(
        self,
        included_file: IncludedFile,
        iterator: PlayIterator,
        is_handler: bool = False,
    ) -> list[Block]:
        included_blocks = super()._load_included_file(included_file, iterator, is_handler)

        def split_task_path(task: str) -> tuple[str, int]:
            split = task.rsplit(":", 1)
            return split[0], int(split[1])

        # Need to register these blocks as valid breakpoints and update the client bps
        for block in included_blocks:
            block_path_and_line = block.get_path()
            if block_path_and_line:
                # If the path is set this is an explicit block and should be
                # marked as an invalid breakpoint section.
                block_path, block_line = split_task_path(block_path_and_line)
                self._debug_state._debugger.register_path_breakpoint(block_path, block_line, 0)

            task_list: list[Task] = block.block[:]
            task_list.extend(block.rescue)
            task_list.extend(block.always)

            for task in task_list:
                task_path, task_line = split_task_path(task.get_path())
                self._debug_state._debugger.register_path_breakpoint(task_path, task_line, 1)

        return included_blocks

    def _queue_task(
        self,
        host: Host,
        task: Task,
        task_vars: dict[str, t.Any],
        play_context: PlayContext,
    ) -> None:
        """Called just as a task is about to be queue"""
        self._debug_state.process_task(host, task, task_vars)

        return super()._queue_task(host, task, task_vars, play_context)

    def _process_pending_results(
        self,
        iterator: PlayIterator,
        one_pass: bool = False,
        max_passes: int | None = None,
        do_handlers: bool = False,
    ) -> list[TaskResult]:
        """Called when gathering the results of a queued task."""
        res = super()._process_pending_results(iterator, one_pass=one_pass, max_passes=max_passes)

        for task_res in res:
            self._debug_state.process_task_result(task_res._host, task_res._task)

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
            iterator,
            iterator._play,
            self._variable_manager,
        )
        try:
            with debugger.with_strategy(self._debug_state):
                return super().run(iterator, play_context)
        finally:
            for tid in list(self._debug_state.threads.keys()):
                if tid == 1:
                    continue
                self._debug_state.remove_thread(tid)

            self._debug_state = None  # type: ignore[assignment]


# Other things to look at
#   * Deal with handlers - _do_handler_run
#   * Should we have an uncaught exception (not rescue on failed task)
#   * Should we have a raised exception (- fail:) task
#   * Function breakpoints for specific actions or maybe includes?
#   * Meta tasks, especially ones that deal with host details
