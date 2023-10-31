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
import typing as t

from ansible import constants as C
from ansible.errors import AnsibleError
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

    def to_dap(self) -> ansibug.dap.StackFrame:
        task_path = self.task.get_path()

        source: ansibug.dap.Source | None = None
        line = 0
        if task_path:
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
    def __init__(
        self,
        *,
        id: int,
        stackframe: AnsibleStackFrame,
        getter: t.Callable[[], collections.abc.Iterable[tuple[str, t.Any]]],
        setter: t.Callable[[ansibug.dap.SetVariableRequest, t.Any], None] | None = None,
        named_variables: int = 0,
        indexed_variables: int = 0,
    ) -> None:
        self.id = id
        self.stackframe = stackframe
        self.getter = getter
        self.setter = setter
        self.named_variables = named_variables
        self.indexed_variables = indexed_variables


class AnsibleDebugState(ansibug.DebugState):
    def __init__(
        self,
        debugger: ansibug.AnsibleDebugger,
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
            thread = self.add_thread(host, advertise=True)

        last_frame_id = thread.stack_frames[0] if thread.stack_frames else None
        if last_frame_id is not None:
            # The parent is the implicit block and we want the parent of that.
            parent_task = task._parent._parent
            last_frame = self.stackframes[last_frame_id]
            if (not parent_task and thread.stack_frames) or (
                last_frame.task and last_frame.task._uuid != parent_task._uuid
            ):
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
        if not task_path:
            return sf

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
        *,
        advertise: bool = True,
    ) -> AnsibleThread:
        tid = self._debugger.next_thread_id()

        thread = self.threads[tid] = AnsibleThread(
            id=tid,
            host=host,
        )
        if advertise:
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
        getter: t.Callable[[], collections.abc.Iterable[tuple[str, t.Any]]],
        setter: t.Callable[[ansibug.dap.SetVariableRequest, t.Any], None] | None = None,
        named_variables: int = 0,
        indexed_variables: int = 0,
    ) -> AnsibleVariable:
        var_id = self._debugger.next_variable_id()

        var = self.variables[var_id] = AnsibleVariable(
            id=var_id,
            stackframe=stackframe,
            named_variables=named_variables,
            indexed_variables=indexed_variables,
            getter=getter,
            setter=setter,
        )
        stackframe.variables.append(var_id)

        return var

    def add_collection_variable(
        self,
        stackframe: AnsibleStackFrame,
        value: collections.abc.Mapping[t.Any, t.Any] | collections.abc.Sequence[t.Any],
    ) -> AnsibleVariable:
        if isinstance(value, collections.abc.Mapping):

            def setter(
                request: ansibug.dap.SetVariableRequest,
                new_value: t.Any,
            ) -> None:
                value[request.name] = new_value  # type: ignore[index] # Not checking isinstance

            return self.add_variable(
                stackframe,
                lambda: iter((str(k), v) for k, v in value.items()),  # type: ignore[union-attr] # Not checking isinstance
                setter=setter,
                named_variables=len(value),
            )

        else:

            def setter(
                request: ansibug.dap.SetVariableRequest,
                new_value: t.Any,
            ) -> None:
                value[int(request.name)] = new_value  # type: ignore[index] # Not checking isinstance

            return self.add_variable(
                stackframe,
                lambda: iter((str(k), v) for k, v in enumerate(value)),
                setter=setter,
                indexed_variables=len(value),
            )

    def remove_thread(
        self,
        tid: int,
        *,
        advertise: bool = True,
    ) -> None:
        self.threads.pop(tid, None)

        if advertise:
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
        value = f"Evaluation for {request.context} is not implemented"

        # FIXME: Implement watch
        if request.context == "repl" and request.frame_id:
            sf = self.stackframes[request.frame_id]
            templar = Templar(loader=self._loader, variables=sf.task_vars)

            # FIXME: This won't fail with AnsibleUndefined as a bare expression.
            # FIXME: Wrap in custom error to display if undefined or other err.
            value = templar.template(request.expression, convert_bare=True, fail_on_undefined=True)

        return ansibug.dap.EvaluateResponse(
            request_seq=request.seq,
            result=repr(value),
            type=type(value).__name__,
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
        omit_value = sf.task_vars["omit"]
        for task_key, task_value in list(task_args.items()):
            if task_value == omit_value:
                del task_args[task_key]

        def module_opts_setter(
            request: ansibug.dap.SetVariableRequest,
            new_value: t.Any,
        ) -> None:
            sf.task.args[request.name] = new_value

        module_opts = self.add_variable(
            sf,
            lambda: iter((str(k), v) for k, v in task_args.items()),
            setter=module_opts_setter,
            named_variables=len(task_args),
        )

        task_vars = self.add_collection_variable(sf, sf.task_vars)
        # FIXME: Needs a custom setter to use self._variable_manager.set_host_variable(..., name, value)
        host_vars = self.add_collection_variable(sf, sf.task_vars["hostvars"][sf.task_vars["inventory_hostname"]])
        global_vars = self.add_collection_variable(sf, sf.task_vars["vars"])

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
        for name, value in variable.getter():
            child_var: AnsibleVariable | None = None
            if isinstance(value, (collections.abc.Mapping, collections.abc.Sequence)) and not isinstance(value, str):
                child_var = self.add_collection_variable(variable.stackframe, value)

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
        if not variable.setter:
            raise Exception(f"Cannot set {request.name}, no known setter available")

        # Run the new variable through a template, always use native types even
        # if the config has not been enabled as this allows users to set things
        # like ints and other native types.
        templar = Templar(loader=self._loader, variables=variable.stackframe.task_vars)
        if not C.DEFAULT_JINJA2_NATIVE:
            templar = templar.copy_with_new_env(environment_class=AnsibleNativeEnvironment)

        new_value = templar.template("{{ %s }}" % request.value)

        variable.setter(request, new_value)
        new_container = None
        if isinstance(new_value, (collections.abc.Mapping, collections.abc.Sequence)) and not isinstance(
            new_value, str
        ):
            new_container = self.add_collection_variable(variable.stackframe, new_value)

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


class StrategyModule(LinearStrategy):
    def __init__(
        self,
        tqm: TaskQueueManager,
    ) -> None:
        super().__init__(tqm)

        # Used for type annotation checks, technically defined in __init__ as well
        self._tqm = tqm

        self._debug_state: AnsibleDebugState | None = None

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
        if self._debug_state:
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
        if self._debug_state:
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

        if self._debug_state:
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
        # import debugpy

        # if not debugpy.is_client_connected():
        #     debugpy.listen(("localhost", 12535))
        #     debugpy.wait_for_client()

        debugger = ansibug.AnsibleDebugger()
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
                self._debug_state.remove_thread(tid, advertise=True)

            self._debug_state = None


# Other things to look at
#   * Deal with handlers - _do_handler_run
#   * Should we have an uncaught exception (not rescue on failed task)
#   * Should we have a raised exception (- fail:) task
#   * Function breakpoints for specific actions or maybe includes?
#   * Meta tasks, especially ones that deal with host details
