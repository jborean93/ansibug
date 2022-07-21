# -*- coding: utf-8 -*-
# Copyright (c) 2022 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import dataclasses
import os
import threading
import typing as t

from ansible.executor.play_iterator import PlayIterator
from ansible.inventory.host import Host
from ansible.playbook.play import Play
from ansible.playbook.task import Task

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


# @dataclasses.dataclass()
# class AnsibleScope:
#     id: int
#     name: str
#     variables: t.List[int] = dataclasses.field(default_factory=list)


# @dataclasses.dataclass()
# class AnsibleVariable:
#     id: int
#     name: str
#     value: t.Any


class AnsibleDebugState(DebugState):
    def __init__(
        self,
        debugger: AnsibleDebugger,
        iterator: PlayIterator,
        play: Play,
    ) -> None:
        self.threads: t.Dict[int, AnsibleThread] = {1: AnsibleThread(id=1, host=None)}
        self.stackframes: t.Dict[int, AnsibleStackFrame] = {}
        # self.scopes: t.Dict[int, AnsibleScope] = {}
        # self.variables: t.Dict[int, AnsibleVariable] = {}

        self._debugger = debugger
        self._iterator = iterator
        self._play = play

        # These might need to live in AnsibleDebugger to preserve across runs.
        self._thread_counter = 2  # 1 is the "Main" thread that is always present.
        self._scope_counter = 1
        self._stackframe_counter = 1
        self._variable_counter = 1

        # self._counters = {
        #     "thread": 1,
        #     "scopes": 1,
        #     "stack_frames": 1,
        # }
        # self.threads: t.Dict[int, str] = {}
        # self.stack_frames: t.Dict[int, t.Tuple[ansibug.dap.StackFrame, t.Dict[str, t.Any]]] = {}
        # self.scopes: t.Dict[int, t.Dict[str, t.Any]] = {}
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
        del thread.stack_frames[-1]

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

        scopes: t.List[dap.Scope] = [
            # sf.task.args  # Needs templating though
            dap.Scope(
                name="Module Options",
                variables_reference=1,
                named_variables=0,
                indexed_variables=0,
            ),
            # sf.task_vars['hostvars'][inventory_hostname]
            dap.Scope(
                name="Host Variables",
                variables_reference=2,
                named_variables=0,
                indexed_variables=0,
            ),
            # sf.task_vars['vars']
            dap.Scope(
                name="Global",
                variables_reference=3,
                named_variables=0,
                indexed_variables=0,
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
        # FIXME: Implement this
        # request.variables_reference
        variables: t.List[dap.Variable] = [
            dap.Variable(
                name="foo",
                value="bar",
                type="str",
            )
        ]

        return dap.VariablesResponse(
            request_seq=request.seq,
            variables=variables,
        )
