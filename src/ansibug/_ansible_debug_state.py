# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import dataclasses
import os
import threading
import typing as t

from ansible import constants as C
from ansible.executor.play_iterator import PlayIterator
from ansible.inventory.host import Host
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.play import Play
from ansible.playbook.task import Task
from ansible.template import Templar

from . import dap
from ._debuggee import AnsibleDebugger, DebugState


@dataclasses.dataclass()
class AnsibleThread:
    id: int
    host: t.Optional[Host]
    stack_frames: t.List[int] = dataclasses.field(default_factory=list)

    stepping_type: t.Optional[t.Literal["in", "out", "over"]] = None
    stepping_task: t.Optional[Task] = None

    def to_dap(self) -> dap.Thread:
        return dap.Thread(
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


@dataclasses.dataclass()
class AnsibleStackFrame:
    id: int
    task: Task
    task_vars: t.Dict[str, t.Any]
    scopes: t.List[int] = dataclasses.field(default_factory=list)
    variables: t.List[int] = dataclasses.field(default_factory=list)

    def to_dap(self) -> dap.StackFrame:
        task_path = self.task.get_path()

        source: t.Optional[dap.Source] = None
        line = 0
        if task_path:
            task_path_and_line = task_path.rsplit(":", 1)
            path = task_path_and_line[0]
            line = int(task_path_and_line[1])

            source = dap.Source(name=os.path.basename(path), path=path)

        return dap.StackFrame(
            id=self.id,
            name=self.task.get_name(),
            source=source,
            line=line,
        )


@dataclasses.dataclass()
class AnsibleVariable:
    id: int
    value: t.Iterable[t.Any]
    stackframe: AnsibleStackFrame
    named_variables: int
    indexed_variables: int


class VariableContainer(t.Protocol):
    id: int
    stackframe: AnsibleStackFrame
    named_variables: int = 0
    indexed_variables: int = 0

    def get(
        self,
        debug: AnsibleDebugState,
    ) -> t.List[dap.Variable]:
        raise NotImplementedError()

    def set(
        self,
        debug: AnsibleDebugState,
        name: str,
        value: str,
        format: t.Optional[dap.ValueFormat] = None,
    ) -> t.Tuple[str, str, t.Optional[VariableContainer]]:
        raise NotImplementedError()


class DictVariableContainer(VariableContainer):
    def __init__(
        self,
        id: int,
        stackframe: AnsibleStackFrame,
        value: collections.abc.Mapping,
    ) -> None:
        self.id = id
        self.named_variables = len(value)
        self.stackframe = stackframe
        self._value = value

    def get(
        self,
        debug: AnsibleDebugState,
    ) -> t.List[dap.Variable]:
        non_iterable_types = (str,)

        variables: t.List[dap.Variable] = []
        for key, value in self._value.items():
            child_var: t.Optional[VariableContainer] = None
            if isinstance(value, (collections.abc.Mapping, collections.abc.Sequence)) and not isinstance(
                value, non_iterable_types
            ):
                child_var = debug.add_variable(
                    stackframe=self.stackframe,
                    value=value,
                )

            variables.append(
                dap.Variable(
                    name=str(key),
                    value=repr(value),
                    type=type(value).__name__,
                    named_variables=child_var.named_variables if child_var else 0,
                    indexed_variables=child_var.indexed_variables if child_var else 0,
                    variables_reference=child_var.id if child_var else 0,
                )
            )

        return variables

    def set(
        self,
        debug: AnsibleDebugState,
        name: str,
        value: str,
        format: t.Optional[dap.ValueFormat] = None,
    ) -> t.Tuple[str, str, t.Optional[VariableContainer]]:
        # FIXME: Support complex objects through yaml/json and ints by trying to parse
        # Looks like I need to also set this somewhere else as it isn't persisted beyond the task.
        self._value[name] = value
        return name, value, None


class ListVariableContainer(VariableContainer):
    def __init__(
        self,
        id: int,
        stackframe: AnsibleStackFrame,
        value: t.Sequence[t.Any],
    ) -> None:
        self.id = id
        self.indexed_variables = len(value)
        self.stackframe = stackframe
        self._value = value

    def get(
        self,
        debug: AnsibleDebugState,
    ) -> t.List[dap.Variable]:
        non_iterable_types = (str,)

        variables: t.List[dap.Variable] = []
        for idx, value in enumerate(self._value):
            child_var: t.Optional[VariableContainer] = None
            if isinstance(value, (collections.abc.Mapping, collections.abc.Sequence)) and not isinstance(
                value, non_iterable_types
            ):
                child_var = debug.add_variable(
                    stackframe=self.stackframe,
                    value=value,
                )

            variables.append(
                dap.Variable(
                    name=str(idx),
                    value=repr(value),
                    type=type(value).__name__,
                    named_variables=child_var.named_variables if child_var else 0,
                    indexed_variables=child_var.indexed_variables if child_var else 0,
                    variables_reference=child_var.id if child_var else 0,
                )
            )

        return variables

    def set(
        self,
        debug: AnsibleDebugState,
        name: str,
        value: str,
        format: t.Optional[dap.ValueFormat] = None,
    ) -> t.Tuple[str, str, t.Optional[VariableContainer]]:
        # FIXME: Support complex objects through yaml/json and ints by trying to parse
        self._value[int(name)] = value
        return name, value, None


class AnsibleDebugState(DebugState):
    def __init__(
        self,
        debugger: AnsibleDebugger,
        loader: DataLoader,
        iterator: PlayIterator,
        play: Play,
    ) -> None:
        self.threads: t.Dict[int, AnsibleThread] = {1: AnsibleThread(id=1, host=None)}
        self.stackframes: t.Dict[int, AnsibleStackFrame] = {}
        self.variables: t.Dict[int, VariableContainer] = {}

        self._debugger = debugger
        self._loader = loader
        self._iterator = iterator
        self._play = play

        self._waiting_condition = threading.Condition()
        self._waiting_threads: t.Dict[int, t.Optional[t.Literal["in", "out", "over"]]] = {}

    def process_task(
        self,
        host: Host,
        task: Task,
        task_vars: t.Dict[str, t.Any],
    ) -> AnsibleStackFrame:
        thread: t.Optional[AnsibleThread] = next(
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
            if parent_task and last_frame.task and last_frame.task._uuid != parent_task._uuid:
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

        with self._waiting_condition:
            tid = thread.id

            stopped_kwargs: t.Dict[str, t.Any] = {}

            if thread.break_step_over(task):
                stopped_kwargs = {
                    "reason": dap.StoppedReason.STEP,
                    "description": "Step over",
                }

            elif thread.break_step_out(task):
                stopped_kwargs = {
                    "reason": dap.StoppedReason.STEP,
                    "description": "Step out",
                }

            elif thread.break_step_in():
                stopped_kwargs = {
                    "reason": dap.StoppedReason.STEP,
                    "description": "Step in",
                }

            # Breakpoints are ignored when in step out mode.
            elif thread.stepping_type != "out" and self._debugger.wait_breakpoint(path, line):
                stopped_kwargs = {
                    "reason": dap.StoppedReason.BREAKPOINT,
                    "description": "Breakpoint hit",
                }

            if stopped_kwargs:
                stopped_event = dap.StoppedEvent(
                    thread_id=tid,
                    **stopped_kwargs,
                )
                self._debugger.send(stopped_event)
                self._waiting_condition.wait_for(lambda: tid in self._waiting_threads)

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
                dap.ThreadEvent(
                    reason="started",
                    thread_id=tid,
                )
            )

        return thread

    def add_variable(
        self,
        stackframe: AnsibleStackFrame,
        value: t.Iterable[t.Any],
    ) -> VariableContainer:
        var_id = self._debugger.next_variable_id()

        var: VariableContainer
        if isinstance(value, collections.abc.Mapping):
            var = self.variables[var_id] = DictVariableContainer(var_id, stackframe, value)

        elif isinstance(value, collections.abc.Sequence):
            var = self.variables[var_id] = ListVariableContainer(var_id, stackframe, value)

        else:
            raise Exception(f"Cannot store variable of type {type(value).__name__} - must be list or dict")

        stackframe.variables.append(var_id)
        return var

    def remove_thread(
        self,
        tid: int,
        *,
        advertise: bool = True,
    ) -> None:
        self.threads.pop(tid, None)

        if advertise:
            self._debugger.send(
                dap.ThreadEvent(
                    reason="exited",
                    thread_id=tid,
                )
            )

    def ended(self) -> None:
        with self._waiting_condition:
            self._waiting_threads = {}
            self._waiting_condition.notify_all()

    def continue_request(
        self,
        request: dap.ContinueRequest,
    ) -> dap.ContinueResponse:
        if request.single_thread:
            self._continue([request.thread_id], None)
            all_threads_continued = False
        else:
            self._continue(self._waiting_threads.keys(), None)
            all_threads_continued = True

        return dap.ContinueResponse(
            request_seq=request.seq,
            all_threads_continued=all_threads_continued,
        )

    def get_scopes(
        self,
        request: dap.ScopesRequest,
    ) -> dap.ScopesResponse:
        sf = self.stackframes[request.frame_id]

        # This is a very basic templating of the args and doesn't handle loops.
        templar = Templar(loader=self._loader, variables=sf.task_vars)
        task_args = templar.template(sf.task.args, fail_on_undefined=False)
        omit_value = sf.task_vars["omit"]
        for task_key, task_value in list(task_args.items()):
            if task_value == omit_value:
                del task_args[task_key]

        task_vars = self.add_variable(sf, task_args)
        host_vars = self.add_variable(sf, sf.task_vars["hostvars"][sf.task_vars["inventory_hostname"]])
        global_vars = self.add_variable(sf, sf.task_vars["vars"])

        scopes: t.List[dap.Scope] = [
            dap.Scope(
                name="Module Options",
                variables_reference=task_vars.id,
                named_variables=task_vars.named_variables,
                indexed_variables=task_vars.indexed_variables,
            ),
            dap.Scope(
                name="Host Variables",
                variables_reference=host_vars.id,
                named_variables=host_vars.named_variables,
                indexed_variables=host_vars.indexed_variables,
                expensive=True,
            ),
            dap.Scope(
                name="Global",
                variables_reference=global_vars.id,
                named_variables=global_vars.named_variables,
                indexed_variables=global_vars.indexed_variables,
                expensive=True,
            ),
        ]

        return dap.ScopesResponse(
            request_seq=request.seq,
            scopes=scopes,
        )

    def get_stacktrace(
        self,
        request: dap.StackTraceRequest,
    ) -> dap.StackTraceResponse:
        with self._waiting_condition:
            wait_info = self._waiting_threads.get(request.thread_id, None)

        stack_frames: t.List[dap.StackFrame] = []
        thread = self.threads[request.thread_id]
        for sfid in thread.stack_frames:
            sf = self.stackframes[sfid]
            stack_frames.append(sf.to_dap())

        return dap.StackTraceResponse(
            request_seq=request.seq,
            stack_frames=stack_frames,
            total_frames=len(stack_frames),
        )

    def get_threads(
        self,
        request: dap.ThreadsRequest,
    ) -> dap.ThreadsResponse:
        return dap.ThreadsResponse(
            request_seq=request.seq,
            threads=[t.to_dap() for t in self.threads.values()],
        )

    def get_variables(
        self,
        request: dap.VariablesRequest,
    ) -> dap.VariablesResponse:
        variable = self.variables[request.variables_reference]
        return dap.VariablesResponse(
            request_seq=request.seq,
            variables=variable.get(self),
        )

    def set_variable(
        self,
        request: dap.SetVariableRequest,
    ) -> dap.SetVariableResponse:
        variable = self.variables[request.variables_reference]
        new_value, new_type, new_container = variable.set(self, request.name, request.value, request.format)

        return dap.SetVariableResponse(
            request_seq=request.seq,
            value=new_value,
            type=new_type,
            variables_reference=new_container.id if new_container else 0,
            named_variables=new_container.named_variables if new_container else 0,
            indexed_variables=new_container.indexed_variables if new_container else 0,
        )

    def step_in(
        self,
        request: dap.StepInRequest,
    ) -> None:
        self._continue([request.thread_id], "in")

    def step_out(
        self,
        request: dap.StepOutRequest,
    ) -> None:
        self._continue([request.thread_id], "out")

    def step_over(
        self,
        request: dap.NextRequest,
    ) -> None:
        self._continue([request.thread_id], "over")

    def _continue(
        self,
        thread_ids: t.Iterable[int],
        action: t.Optional[t.Literal["in", "out", "over"]],
    ) -> None:
        with self._waiting_condition:
            for tid in thread_ids:
                self._waiting_threads[tid] = action

            self._waiting_condition.notify_all()
