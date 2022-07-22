# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import collections.abc
import dataclasses
import os
import threading
import typing as t

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

    def to_dap(self) -> dap.Thread:
        return dap.Thread(
            id=self.id,
            name=self.host.get_name() if self.host else "main",
        )


@dataclasses.dataclass()
class AnsibleStackFrame:
    id: int
    task: Task
    task_vars: t.Dict[str, t.Any]
    scopes: t.List[int] = dataclasses.field(default_factory=list)
    variables: t.List[int] = dataclasses.field(default_factory=list)
    last_task: t.Optional[Task] = None

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
        self.variables: t.Dict[int, AnsibleVariable] = {}

        self._debugger = debugger
        self._loader = loader
        self._iterator = iterator
        self._play = play

        # These might need to live in AnsibleDebugger to preserve across runs.
        self._thread_counter = 2  # 1 is the "Main" thread that is always present.
        self._stackframe_counter = 1
        self._variable_counter = 1

        self._waiting_condition = threading.Condition()
        self._waiting_threads: t.Dict[int, t.Any] = {}

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

        sfid = self._stackframe_counter
        self._stackframe_counter += 1

        sf = self.stackframes[sfid] = AnsibleStackFrame(
            id=sfid,
            task=task,
            task_vars=task_vars,
        )
        thread.stack_frames.append(sfid)

        task_path = task.get_path()
        if not task_path:
            return sf

        path_and_line = task_path.rsplit(":", 1)
        path = path_and_line[0]
        line = int(path_and_line[1])

        with self._waiting_condition:
            tid = thread.id
            self._waiting_threads[tid] = None

            if self._debugger.wait_breakpoint(path, line, tid):
                self._waiting_condition.wait_for(lambda: tid not in self._waiting_threads)

            else:
                del self._waiting_threads[tid]

        return sf

    def process_task_result(
        self,
        host: Host,
        task: Task,
    ) -> None:
        # FIXME: Handle include_tasks and the results. Will need to update the
        # existing stack frame to include the last task details so it knows
        # when to remove it from the thread.
        thread = next(iter([t for t in self.threads.values() if t.host == host]))
        sfid = thread.stack_frames.pop(-1)
        sf = self.stackframes.pop(sfid)
        for variable_id in sf.variables:
            del self.variables[variable_id]

        # FIXME: Now check last frame to see if it's an include_tasks and
        # whether this is the last task in that frame.

    def add_thread(
        self,
        host: Host,
        *,
        advertise: bool = True,
    ) -> AnsibleThread:
        tid = self._thread_counter
        self._thread_counter += 1

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
    ) -> AnsibleVariable:
        var_id = self._variable_counter
        self._variable_counter += 1

        named_variables = 0
        if isinstance(value, collections.abc.Mapping):
            named_variables = len(value)

        indexed_variables = 0
        if isinstance(value, list):
            indexed_variables = len(value)

        var = self.variables[var_id] = AnsibleVariable(
            var_id,
            value=value,
            stackframe=stackframe,
            named_variables=named_variables,
            indexed_variables=indexed_variables,
        )
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
        thread_ids: t.Iterable[int]
        if request.single_thread:
            thread_ids = [request.thread_id]
            all_threads_continued = False
        else:
            thread_ids = self._waiting_threads.keys()
            all_threads_continued = True

        with self._waiting_condition:
            for tid in thread_ids:
                self._waiting_threads.pop(tid, None)

            self._waiting_condition.notify_all()

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
        non_iterable_types = (str,)
        variable = self.variables[request.variables_reference]

        variables: t.List[dap.Variable] = []
        enumerator: t.Iterable[t.Tuple[t.Any, t.Any]]
        if isinstance(variable.value, collections.abc.Mapping):
            enumerator = variable.value.items()

        elif isinstance(variable.value, collections.abc.Iterable) and not isinstance(
            variable.value, non_iterable_types
        ):
            enumerator = enumerate(variable.value)

        else:
            raise NotImplementedError("abc")

        for name, value in enumerator:
            child_var: t.Optional[AnsibleVariable] = None
            if isinstance(value, collections.abc.Iterable) and not isinstance(value, non_iterable_types):
                child_var = self.add_variable(
                    stackframe=variable.stackframe,
                    value=value,
                )

            variables.append(
                dap.Variable(
                    name=str(name),
                    value=repr(value),
                    type=type(value).__name__,
                    named_variables=child_var.named_variables if child_var else 0,
                    indexed_variables=child_var.indexed_variables if child_var else 0,
                    variables_reference=child_var.id if child_var else 0,
                )
            )

        return dap.VariablesResponse(
            request_seq=request.seq,
            variables=variables,
        )
