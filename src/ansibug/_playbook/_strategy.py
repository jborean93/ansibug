# Copyright (c) 2026 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import functools
import inspect
import logging
import typing as t

from ansible.executor.play_iterator import PlayIterator
from ansible.executor.task_queue_manager import TaskQueueManager
from ansible.executor.task_result import TaskResult
from ansible.inventory.host import Host
from ansible.playbook.block import Block
from ansible.playbook.handler import Handler
from ansible.playbook.play_context import PlayContext
from ansible.playbook.task import Task
from ansible.plugins.strategy import StrategyBase
from ansible.utils.display import Display

from ansibug._debuggee import AnsibleDebugger, EndStrategy

from ._breakpoints import register_block_breakpoints
from ._debug_state import AnsibleDebugState
from ._task_result import AnsibugTaskResult

log = logging.getLogger(__name__)

display = Display()


class DebugStrategy(StrategyBase):
    """Overrides the StrategyBase methods each builtin strategy calls into."""

    @classmethod
    def install_ansibug_hooks(
        cls,
        debugger: AnsibleDebugger,
        *,
        wait_for_config_done: bool,
    ) -> None:
        """Runs every strategy with the debugger.

        Custom strategy plugins are deprecated so rather than provide one the
        StrategyBase init is wrapped to swap the instance class to a subclass
        of the strategy the play uses with this class inserted first in the
        MRO. This must be called before the TaskQueueManager loads the
        strategy.

        Args:
            debugger: The debugger each strategy reports to.
            wait_for_config_done: The first play waits for the client to send
                the configurationDone request before it runs.
        """
        orig_init = StrategyBase.__init__

        @functools.cache
        def debug_class(strategy_cls: type[StrategyBase]) -> type[StrategyBase]:
            return type(strategy_cls.__name__, (cls, strategy_cls), {})

        def __init__(self: StrategyBase, tqm: TaskQueueManager) -> None:
            nonlocal wait_for_config_done

            orig_init(self, tqm)
            self.__class__ = debug_class(type(self))
            t.cast(DebugStrategy, self)._ansibug_init(debugger, wait_for_config_done=wait_for_config_done)
            # Each play has its own strategy, only the first one waits.
            wait_for_config_done = False

        StrategyBase.__init__ = __init__  # type: ignore[method-assign]

    _tqm: TaskQueueManager

    def _ansibug_init(
        self,
        debugger: AnsibleDebugger,
        *,
        wait_for_config_done: bool,
    ) -> None:
        """Sets the debug attributes, called once the class has been swapped.

        The attributes are name mangled so they can't clash with those of the
        strategy this is inserted in front of.
        """
        self.__debugger = debugger
        self.__wait_for_config_done = wait_for_config_done
        self.__debug_state = AnsibleDebugState(
            debugger,
            self._loader,
            self._variable_manager,
        )
        # The _queue_task task_vars and play_context by (host name, task uuid).
        self.__queued_args: dict[tuple[str, str], tuple[dict[str, t.Any], PlayContext]] = {}

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

        task_vars = inspect.currentframe().f_back.f_locals["task_vars"]  # pyright: ignore[reportOptionalMemberAccess]  # I know this is bad
        task = self.__debug_state.start_task(target_host, task, task_vars)
        res = super()._execute_meta(task, play_context, iterator, target_host)

        meta_action = task.args.get("_raw_params", None)
        if meta_action == "refresh_inventory":
            # refresh_inventory will update the uuid on the host object, we
            # need to mark the existing threads as exited so the next run will
            # pick up the correct changes. It will automatically start those
            # threads as they run.
            self.__debug_state.exit_threads()

        else:
            # Needed to ensure the stackframe is removed as these meta tasks
            # have no results for _process_pending_results to handle.
            self.__debug_state.end_task(AnsibugTaskResult.from_meta_task(target_host, task))

        return res

    def _load_included_file(
        self,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> list[Block]:
        included_blocks = super()._load_included_file(*args, **kwargs)

        # Need to register these blocks as valid breakpoints and update the client bps
        register_block_breakpoints(self.__debugger, included_blocks)

        return included_blocks

    def _queue_task(
        self,
        host: Host,
        task: Task,
        task_vars: dict[str, t.Any],
        play_context: PlayContext,
    ) -> None:
        """Called just as a task is about to be queue"""
        task = self.__debug_state.start_task(host, task, task_vars)

        # Kept to re-run the task if the client restarts its frame.
        self.__queued_args[(host.name, task._uuid)] = (task_vars, play_context)

        return super()._queue_task(host, task, task_vars, play_context)

    def _process_pending_results(
        self,
        iterator: PlayIterator,
        *args: t.Any,
        **kwargs: t.Any,
    ) -> list[TaskResult]:
        """Called when gathering the results of a queued task."""
        # The iterator replaces the host states rather than changing them so
        # a shallow copy is enough to roll back a restarted task.
        prev_host_states = iterator.host_states.copy()
        res = super()._process_pending_results(iterator, *args, **kwargs)

        processed: list[TaskResult] = []
        for task_res in res:
            result = AnsibugTaskResult.from_task_result(task_res)
            queued_args = self.__queued_args.pop((result.host.name, result.task._uuid), None)

            redo_task = self.__debug_state.end_task(result, can_restart=queued_args is not None)
            if redo_task and queued_args:
                self._rollback_result(iterator, result, prev_host_states)
                self._send_restart_task_start(redo_task)
                # The base strategy unblocked the host when it processed the
                # result, without this the free strategy queues the host's
                # next task while the re-run is still running.
                self._blocked_hosts[result.host.name] = True
                self._queue_task(result.host, redo_task, *queued_args)

                # The new result is likely still running, it is picked up
                # by a later call as the pending results count includes it.
                processed.extend(self._process_pending_results(iterator, *args, **kwargs))

            else:
                processed.append(task_res)

        return processed

    def _send_restart_task_start(
        self,
        task: Task,
    ) -> None:
        """Sends the task start callback again for a restarted task.

        The base strategy only sends v2_runner_on_start when a task is queued,
        without this the re-run result appears under the original task header.
        A copy is renamed so the header shows it was restarted, it keeps the
        same uuid. The free and host_pinned strategies show no header, the
        default callback only prints one there when the task uuid of a result
        changes.
        """
        banner_task = task.copy()
        banner_task.name = f"{task.name or task.action} (restarted)"

        if isinstance(task, Handler):
            self._tqm.send_callback("v2_playbook_on_handler_task_start", banner_task)
        else:
            self._tqm.send_callback("v2_playbook_on_task_start", banner_task, is_conditional=False)

    def _rollback_result(
        self,
        iterator: PlayIterator,
        result: AnsibugTaskResult,
        prev_host_states: dict[str, t.Any],
    ) -> None:
        """Undoes what the base strategy did for a result that is re-run.

        Only covers the results end_task stops on: failed (not ignored or
        rescued), unreachable (not ignored), and skipped. This is based on the
        redo handling in Ansible's debug_closure.
        """
        host_name = result.host.name
        stats = self._tqm._stats

        if result.failed:
            failed_hosts = [host_name]
            if result.task.run_once:
                # The same hosts the base strategy marks failed for run_once.
                failed_hosts = [
                    h.name
                    for h in self._inventory.get_hosts(iterator._play.hosts)
                    if h.name not in self._tqm._unreachable_hosts
                ]

            for name in failed_hosts:
                if name in prev_host_states:
                    iterator.set_state_for_host(name, prev_host_states[name])
                # Each mark_host_failed call appended the host once, an
                # earlier failure keeps its own entry.
                if name in iterator._play._removed_hosts:
                    iterator._play._removed_hosts.remove(name)

            self._tqm._failed_hosts.pop(host_name, None)
            stats.decrement("failures", host_name)

        elif result.unreachable:
            self._tqm._unreachable_hosts.pop(host_name, None)
            if host_name in iterator._play._removed_hosts:
                iterator._play._removed_hosts.remove(host_name)
            stats.decrement("dark", host_name)

        elif result.skipped:
            stats.decrement("skipped", host_name)

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
        debugger = self.__debugger

        # Waited here rather than when the playbook is loaded so modes that
        # run no play, like --syntax-check, don't wait for a client.
        if self.__wait_for_config_done:
            log.info("Waiting for configuration done request to be received in Ansible")
            debugger.wait_for_config_done(timeout=None)
            if not debugger.adapter_connected:
                display.warning("Ansibug debug adapter is not connected, running the playbook without the debugger")

        try:
            with debugger.with_strategy(self.__debug_state):
                try:
                    return super().run(iterator, play_context)
                finally:
                    self.__debug_state.exit_threads()

        except EndStrategy:
            display.display("Debugger has requested the process to terminate")
            return TaskQueueManager.RUN_FAILED_BREAK_PLAY
