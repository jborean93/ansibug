# -*- coding: utf-8 -*-
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

import dataclasses
import enum
import threading
import types
import typing as t

import debugpy
from ansible import constants as C
from ansible.errors import AnsibleAssertionError, AnsibleError, AnsibleParserError
from ansible.executor.play_iterator import (
    FailedStates,
    HostState,
    IteratingStates,
    PlayIterator,
)
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.executor.task_result import TaskResult
from ansible.inventory.host import Host
from ansible.inventory.manager import InventoryManager
from ansible.module_utils._text import to_text
from ansible.parsing.dataloader import DataLoader
from ansible.playbook.block import Block
from ansible.playbook.included_file import IncludedFile
from ansible.playbook.play import Play
from ansible.playbook.play_context import PlayContext
from ansible.playbook.task import Task
from ansible.plugins.loader import action_loader
from ansible.plugins.strategy import StrategyBase
from ansible.plugins.strategy.linear import StrategyModule as LinearStrategy
from ansible.template import Templar
from ansible.utils.display import Display
from ansible.vars.manager import VariableManager

import ansibug

display = Display()


class DebugState(ansibug.DebugState):
    def __init__(
        self,
        debugger: ansibug.AnsibleDebugger,
        iterator: PlayIterator,
        play: Play,
    ) -> None:
        self._debugger = debugger
        self._iterator = iterator
        self._play = play

        self._counters = {
            "thread": 1,
            "scopes": 1,
            "stack_frames": 1,
        }
        self.threads: t.Dict[int, str] = {}
        self.stack_frames: t.Dict[int, t.Tuple[ansibug.dap.StackFrame, t.Dict[str, t.Any]]] = {}
        self.scopes: t.Dict[int, t.Dict[str, t.Any]] = {}
        self._waiting_condition = threading.Condition()
        self._waiting_threads: t.Dict[int, t.Tuple[Task, t.Dict[str, t.Any]]] = {}

    def ended(self) -> None:
        with self._waiting_condition:
            self._waiting_threads = {}
            self._waiting_condition.notify_all()

    def continue_request(
        self,
        request: ansibug.dap.ContinueRequest,
    ) -> ansibug.dap.ContinueResponse:
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

        return ansibug.dap.ContinueResponse(
            request_seq=request.seq,
            all_threads_continued=all_threads_continued,
        )

    def add_thread(
        self,
        name: str,
    ) -> int:
        tid = self._counters["thread"]
        self._counters["thread"] += 1
        self.threads[tid] = name

        return tid

    def get_scopes(
        self,
        request: ansibug.dap.ScopesRequest,
    ) -> ansibug.dap.ScopesResponse:
        sf = self.stack_frames.get(request.frame_id, None)
        scopes: t.List[ansibug.dap.Scope] = []

        if sf:
            stack_frame, task_vars = sf
            scope_id = self._counters["scopes"]
            self._counters["scopes"] += 1
            scope = ansibug.dap.Scope(
                name="hostvars",
                variables_reference=1,
                named_variables=0,
                indexed_variables=0,
            )
            scopes.append(scope)
            self.scopes[scope_id] = task_vars

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

        stack_frames: t.List[ansibug.dap.StackFrame] = []
        if wait_info:
            task, task_vars = wait_info
            sfid = self._counters["stack_frames"]
            self._counters["stack_frames"] += 1
            sf = ansibug.dap.StackFrame(
                id=sfid,
                name=str(task),
            )
            self.stack_frames[sfid] = (sf, task_vars)
            stack_frames.append(sf)

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
            threads=[ansibug.dap.Thread(id=tid, name=name) for tid, name in self.threads.items()],
        )

    def get_variables(
        self,
        request: ansibug.dap.VariablesRequest,
    ) -> ansibug.dap.VariablesResponse:
        # FIXME: Implement this
        # request.variables_reference
        variables: t.List[ansibug.dap.Variable] = [
            ansibug.dap.Variable(
                name="foo",
                value="bar",
                type="str",
            )
        ]

        return ansibug.dap.VariablesResponse(
            request_seq=request.seq,
            variables=variables,
        )

    def wait_breakpoint(
        self,
        host: Host,
        task: Task,
        task_vars: t.Dict[str, t.Any],
    ) -> None:
        task_path = task.get_path()
        if not task_path:
            return

        path_and_line = task_path.rsplit(":", 1)
        path = path_and_line[0]
        line = int(path_and_line[1])
        thread_id = next(tid for tid, name in self.threads.items() if name == host.name)

        with self._waiting_condition:
            self._waiting_threads[thread_id] = (task, task_vars)

            if self._debugger.wait_breakpoint(path, line, thread_id):
                self._waiting_condition.wait_for(lambda: thread_id not in self._waiting_threads)

            else:
                del self._waiting_threads[thread_id]


class StrategyModule(LinearStrategy):
    def __init__(
        self,
        tqm: TaskQueueManager,
    ) -> None:
        super().__init__(tqm)

        # Used for type annotation checks, technically defined in __init__ as well
        self._hosts_cache_all: t.List[str] = []
        self._tqm = tqm

        self._debug_state: t.Optional[DebugState] = None

    def _set_hosts_cache(
        self,
        play: Play,
        refresh: bool = True,
    ) -> None:
        """
        Called internally a few times to cache the host list. This is used to
        keep track of the hosts which are seen as "threads" in the debugger
        client. Only update the thread entries when refresh=True which denotes
        when the caller wants to update the inventory.
        """
        super()._set_hosts_cache(play, refresh)

        if refresh and self._debug_state:
            new_host_list = set(self._hosts_cache_all)
            existing_hosts = set()

            for tid in self._debug_state.threads.keys():
                thread = self._debug_state.threads[tid]
                existing_hosts.add(thread)

                if thread not in new_host_list:
                    del self._debug_state.threads[tid]

            for host in new_host_list.difference(existing_hosts):
                self._debug_state.add_thread(host)

    def _execute_meta(
        self,
        task: Task,
        play_context: PlayContext,
        iterator: PlayIterator,
        target_host: Host,
    ) -> t.List[t.Dict[str, t.Any]]:
        """Called when a meta task is about to run"""
        return super()._execute_meta(task, play_context, iterator, target_host)

    def _queue_task(
        self,
        host: Host,
        task: Task,
        task_vars: t.Dict[str, t.Any],
        play_context: PlayContext,
    ) -> None:
        """Called just as a task is about to be queue"""
        # include_* are set as actual tasks, we can use _parent to determine
        # heirarchy and see if this is part of a parent include.

        if self._debug_state:
            self._debug_state.wait_breakpoint(host, task, task_vars)

        return super()._queue_task(host, task, task_vars, play_context)

    def _process_pending_results(
        self,
        iterator: PlayIterator,
        one_pass: bool = False,
        max_passes: t.Optional[int] = None,
        do_handlers: bool = False,
    ) -> t.List[TaskResult]:
        """Called when gathering the results of a queued task."""
        res = super()._process_pending_results(iterator, one_pass, max_passes, do_handlers)
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
        if not debugpy.is_client_connected():
            debugpy.listen(("localhost", 12535))
            debugpy.wait_for_client()

        debugger = ansibug.AnsibleDebugger()
        self._debug_state = DebugState(debugger, iterator, iterator._play)
        try:
            with debugger.with_strategy(self._debug_state):
                return super().run(iterator, play_context)
        finally:
            self._debug_state = None


# Other things to look at
#   * Need some way for something to hook in and validate breakpoints being requested
#   * IncludeFile.process_include_results (called after queue_task) to process
#       any queue entries and check breakpoints?
#   * Get details when a task finishes (_process_pending_results or _wait_pending_results)?
#   * Deal with handlers - _do_handler_run
#   * Should we have an uncaught exception (not rescue on failed task)
#   * Should we have a raised exception (- fail:) task
#   * Function breakpoints for specific actions or maybe includes?
