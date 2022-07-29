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

import typing as t

from ansible.executor.play_iterator import PlayIterator
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.executor.task_result import TaskResult
from ansible.inventory.host import Host
from ansible.playbook.block import Block
from ansible.playbook.included_file import IncludedFile
from ansible.playbook.play_context import PlayContext
from ansible.playbook.task import Task
from ansible.plugins.strategy.linear import StrategyModule as LinearStrategy
from ansible.utils.display import Display

import ansibug

display = Display()


class StrategyModule(LinearStrategy):
    def __init__(
        self,
        tqm: TaskQueueManager,
    ) -> None:
        super().__init__(tqm)

        # Used for type annotation checks, technically defined in __init__ as well
        self._tqm = tqm

        self._debug_state: t.Optional[ansibug.AnsibleDebugState] = None

    def _execute_meta(
        self,
        task: Task,
        play_context: PlayContext,
        iterator: PlayIterator,
        target_host: Host,
    ) -> t.List[t.Dict[str, t.Any]]:
        """Called when a meta task is about to run"""
        return super()._execute_meta(task, play_context, iterator, target_host)

    def _load_included_file(
        self,
        included_file: IncludedFile,
        iterator: PlayIterator,
        is_handler: bool = False,
    ) -> t.List[Block]:
        included_blocks = super()._load_included_file(included_file, iterator, is_handler)

        def split_task_path(task: str) -> t.Tuple[str, int]:
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

                task_list: t.List[Task] = block.block[:]
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
        task_vars: t.Dict[str, t.Any],
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
        max_passes: t.Optional[int] = None,
        do_handlers: bool = False,
    ) -> t.List[TaskResult]:
        """Called when gathering the results of a queued task."""
        res = super()._process_pending_results(iterator, one_pass, max_passes, do_handlers)

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
        import debugpy

        if not debugpy.is_client_connected():
            debugpy.listen(("localhost", 12535))
            debugpy.wait_for_client()

        debugger = ansibug.AnsibleDebugger()
        self._debug_state = ansibug.AnsibleDebugState(debugger, self._loader, iterator, iterator._play)
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
#   * IncludeFile.process_include_results (called after queue_task) to process
#       any queue entries and check breakpoints?
#   * Get details when a task finishes (_process_pending_results or _wait_pending_results)?
#   * Deal with handlers - _do_handler_run
#   * Should we have an uncaught exception (not rescue on failed task)
#   * Should we have a raised exception (- fail:) task
#   * Function breakpoints for specific actions or maybe includes?
