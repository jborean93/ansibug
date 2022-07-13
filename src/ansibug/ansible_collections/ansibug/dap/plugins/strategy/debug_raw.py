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

import enum
import typing as t

from ansible import constants as C
from ansible.errors import AnsibleAssertionError, AnsibleError, AnsibleParserError
from ansible.executor.play_iterator import (
    FailedStates,
    HostState,
    IteratingStates,
    PlayIterator,
)
from ansible.executor.task_queue_manager import TaskQueueManager
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
from ansible.template import Templar
from ansible.utils.display import Display
from ansible.vars.manager import VariableManager

import ansibug

display = Display()


class DebugState(ansibug.DebugState):
    def __init__(self) -> None:
        self._counters = {
            "thread": 1,
        }
        self._threads: t.Dict[int, ansibug.dap.Thread] = {}

    def add_thread(
        self,
        name: str,
    ) -> int:
        tid = self._counters["thread"]
        self._counters["thread"] += 1
        self._threads[tid] = ansibug.dap.Thread(id=tid, name=name)

        return tid

    def get_threads(
        self,
        request: ansibug.dap.ThreadsRequest,
    ) -> t.Iterable[ansibug.dap.Thread]:
        return self._threads.values()


class StrategyModule(StrategyBase):
    def __init__(
        self,
        tqm: TaskQueueManager,
    ) -> None:
        # Annoyingly there are some private attributes that are used outside of
        # the strategy. These are initialised in StrategyBase.
        super().__init__(tqm)

        self._debug_adapter = ansibug.AnsibleDebugger()
        self._debug_state = DebugState()
        self._tqm = tqm
        self._inventory: InventoryManager = tqm.get_inventory()
        self._loader: DataLoader = tqm.get_loader()
        self._variable_manager: VariableManager = tqm.get_variable_manager()

    def run(
        self,
        iterator: PlayIterator,
        play_context: PlayContext,
    ) -> int:
        result = self._tqm.RUN_OK

        play: Play = iterator._play
        host_list: t.List[Host] = []
        for host in self._inventory.get_hosts(play.hosts, order=play.order):
            host_list.append(host)
            self._debug_state.add_thread(host.name)

        try:
            while not self._tqm._terminated:
                # Queue up the tasks in the current host task iteration.
                hosts_left = self._filter_unreachable_hosts(host_list)
                host_tasks = self._get_next_host_tasks(hosts_left, iterator)
                if not host_tasks:
                    break

                for host, task in host_tasks:

                    # Check if task is a role and whether it should be skipped
                    # because it has run already
                    if task._role and task._role.has_run(host):
                        display.debug("'%s' skipped because role has already run", task)
                        continue

                    display.debug("getting variables")
                    self._tqm.get_variable_manager()
                    task_vars = self._variable_manager.get_vars(
                        play=iterator._play,
                        host=host,
                        task=task,
                    )
                    current_hosts = task_vars["ansible_current_hosts"] = []
                    failed_hosts = task_vars["ansible_failed_hosts"] = []
                    for h in host_list:
                        if h in self._tqm._failed_hosts:
                            failed_hosts.append(h.name)
                            continue

                        elif h not in self._tqm._unreachable_hosts:
                            current_hosts.append(h.name)
                            continue

                    templar = Templar(loader=self._loader, variables=task_vars)
                    display.debug("done getting variables")

                    # test to see if the task across all hosts points to an action plugin which
                    # sets BYPASS_HOST_LOOP to true, or if it has run_once enabled. If so, we
                    # will only send this task to the first host in the list.

                    task_action = templar.template(task.action)
                    try:
                        action = action_loader.get(task_action, class_only=True, collection_list=task.collections)
                    except KeyError:
                        action = None

                    if task_action in C._ACTION_META:
                        a = ""

                    else:
                        a = ""

                    a = ""

        except (IOError, EOFError) as e:
            display.debug("got IOError/EOFError in task loop: %s", e)
            return self._tqm.RUN_UNKNOWN_ERROR

        # TODO: Fire handlers and other cleanup actions

        return result

    def _filter_unreachable_hosts(
        self,
        hosts: t.Iterable[Host],
    ) -> t.List[Host]:
        """Get list of available hosts by filtering out unreachables."""
        return [h for h in hosts if h.name not in self._tqm._unreachable_hosts]

    def _get_next_host_tasks(
        self,
        hosts: t.List[Host],
        iterator: PlayIterator,
    ) -> t.Optional[t.List[t.Tuple[Host, Task]]]:
        """Get the next set of host tasks.

        Gets the next set of tasks for the hosts specified.

        Args:
            hosts: The host list to get the tasks for.
            iterator: The current iterator:

        Returns:
            Optional[List[Tuple[Host, Task]]]: The list of hosts and their task
            to run or None if not more tasks are available.
        """
        display.debug("building list of hosts and their next state")
        host_tasks: t.List[t.Tuple[Host, HostState, t.Optional[Task]]] = []
        lowest_cur_block = -1

        for h in hosts:
            host_state, host_task = iterator.get_next_task_for_host(h, peek=True)
            host_tasks.append((h, host_state, host_task))

            if host_task and host_state.run_state != IteratingStates.COMPLETE:

                # Check if the block of this host task is lower than the lowest block
                cur_block = iterator.get_active_state(host_state).cur_block
                if lowest_cur_block == -1 or cur_block < lowest_cur_block:
                    lowest_cur_block = cur_block

        display.debug("get task type and align into the relevant blocks")
        task_counter: t.Dict[enum.IntEnum, int] = {
            IteratingStates.SETUP: 0,
            IteratingStates.TASKS: 0,
            IteratingStates.RESCUE: 0,
            IteratingStates.ALWAYS: 0,
        }
        for h, s, t in host_tasks:
            if not t:
                continue

            state: HostState = iterator.get_active_state(s)
            if state.cur_block > lowest_cur_block:
                # Not the current block, ignore it
                continue

            if state.run_state in task_counter:
                task_counter[state.run_state] += 1

        display.debug(f"done counting tasks in each state of execution:\n{task_counter!r}")

        noop_task = Task()
        noop_task.action = "meta"
        noop_task.args["_raw_params"] = "noop"
        noop_task.implicit = True
        noop_task.set_loader(iterator._play._loader)

        for task_type, count in task_counter.items():
            if not count:
                continue

            display.debug(f"advancing hosts in {task_type}")

            final_tasks: t.List[t.Tuple[Host, Task]] = []
            for host, state, task in host_tasks:
                if task is None:
                    continue

                state = iterator.get_active_state(state)
                if state.run_state == task_type and state.cur_block == lowest_cur_block:
                    iterator.set_state_for_host(host.name, state)
                    final_tasks.append((host, task))

                else:
                    final_tasks.append((host, noop_task))

            return final_tasks

        return None

    # noop_task = None

    # def _replace_with_noop(self, target):
    #     if self.noop_task is None:
    #         raise AnsibleAssertionError("strategy.linear.StrategyModule.noop_task is None, need Task()")

    #     result = []
    #     for el in target:
    #         if isinstance(el, Task):
    #             result.append(self.noop_task)
    #         elif isinstance(el, Block):
    #             result.append(self._create_noop_block_from(el, el._parent))
    #     return result

    # def _create_noop_block_from(self, original_block, parent):
    #     noop_block = Block(parent_block=parent)
    #     noop_block.block = self._replace_with_noop(original_block.block)
    #     noop_block.always = self._replace_with_noop(original_block.always)
    #     noop_block.rescue = self._replace_with_noop(original_block.rescue)

    #     return noop_block

    # def _prepare_and_create_noop_block_from(self, original_block, parent, iterator):
    #     self.noop_task = Task()
    #     self.noop_task.action = "meta"
    #     self.noop_task.args["_raw_params"] = "noop"
    #     self.noop_task.implicit = True
    #     self.noop_task.set_loader(iterator._play._loader)

    #     return self._create_noop_block_from(original_block, parent)

    # def run2(
    #     self,
    #     iterator: PlayIterator,
    #     play_context: PlayContext,
    # ) -> int:
    #     """
    #     The linear strategy is simple - get the next task and queue
    #     it for all hosts, then wait for the queue to drain before
    #     moving on to the next task
    #     """

    #     # iterate over each task, while there is one left to run
    #     result = self._tqm.RUN_OK
    #     work_to_do = True

    #     self._set_hosts_cache(iterator._play)

    #     while work_to_do and not self._tqm._terminated:

    #         try:
    #             display.debug("getting the remaining hosts for this loop")
    #             hosts_left = self.get_hosts_left(iterator)
    #             display.debug("done getting the remaining hosts for this loop")

    #             # queue up this task for each host in the inventory
    #             callback_sent = False
    #             work_to_do = False

    #             host_results = []
    #             host_tasks = self._get_next_task_lockstep(hosts_left, iterator)

    #             # skip control
    #             skip_rest = False
    #             choose_step = True

    #             # flag set if task is set to any_errors_fatal
    #             any_errors_fatal = False

    #             results = []
    #             for (host, task) in host_tasks:
    #                 if not task:
    #                     continue

    #                 if self._tqm._terminated:
    #                     break

    #                 run_once = False
    #                 work_to_do = True

    #                 # check to see if this task should be skipped, due to it being a member of a
    #                 # role which has already run (and whether that role allows duplicate execution)
    #                 if task._role and task._role.has_run(host):
    #                     # If there is no metadata, the default behavior is to not allow duplicates,
    #                     # if there is metadata, check to see if the allow_duplicates flag was set to true
    #                     if (
    #                         task._role._metadata is None
    #                         or task._role._metadata
    #                         and not task._role._metadata.allow_duplicates
    #                     ):
    #                         display.debug("'%s' skipped because role has already run" % task)
    #                         continue

    #                 display.debug("getting variables")
    #                 task_vars = self._variable_manager.get_vars(
    #                     play=iterator._play,
    #                     host=host,
    #                     task=task,
    #                     _hosts=self._hosts_cache,
    #                     _hosts_all=self._hosts_cache_all,
    #                 )
    #                 self.add_tqm_variables(task_vars, play=iterator._play)
    #                 templar = Templar(loader=self._loader, variables=task_vars)
    #                 display.debug("done getting variables")

    #                 # test to see if the task across all hosts points to an action plugin which
    #                 # sets BYPASS_HOST_LOOP to true, or if it has run_once enabled. If so, we
    #                 # will only send this task to the first host in the list.

    #                 task_action = templar.template(task.action)

    #                 try:
    #                     action = action_loader.get(task_action, class_only=True, collection_list=task.collections)
    #                 except KeyError:
    #                     # we don't care here, because the action may simply not have a
    #                     # corresponding action plugin
    #                     action = None

    #                 if task_action in C._ACTION_META:
    #                     # for the linear strategy, we run meta tasks just once and for
    #                     # all hosts currently being iterated over rather than one host
    #                     results.extend(self._execute_meta(task, play_context, iterator, host))
    #                     if task.args.get("_raw_params", None) not in (
    #                         "noop",
    #                         "reset_connection",
    #                         "end_host",
    #                         "role_complete",
    #                     ):
    #                         run_once = True
    #                     if (task.any_errors_fatal or run_once) and not task.ignore_errors:
    #                         any_errors_fatal = True
    #                 else:
    #                     # handle step if needed, skip meta actions as they are used internally
    #                     if self._step and choose_step:
    #                         if self._take_step(task):
    #                             choose_step = False
    #                         else:
    #                             skip_rest = True
    #                             break

    #                     run_once = (
    #                         templar.template(task.run_once) or action and getattr(action, "BYPASS_HOST_LOOP", False)
    #                     )

    #                     if (task.any_errors_fatal or run_once) and not task.ignore_errors:
    #                         any_errors_fatal = True

    #                     if not callback_sent:
    #                         display.debug(
    #                             "sending task start callback, copying the task so we can template it temporarily"
    #                         )
    #                         saved_name = task.name
    #                         display.debug("done copying, going to template now")
    #                         try:
    #                             task.name = to_text(
    #                                 templar.template(task.name, fail_on_undefined=False), nonstring="empty"
    #                             )
    #                             display.debug("done templating")
    #                         except Exception:
    #                             # just ignore any errors during task name templating,
    #                             # we don't care if it just shows the raw name
    #                             display.debug("templating failed for some reason")
    #                         display.debug("here goes the callback...")
    #                         self._tqm.send_callback("v2_playbook_on_task_start", task, is_conditional=False)
    #                         task.name = saved_name
    #                         callback_sent = True
    #                         display.debug("sending task start callback")

    #                     self._blocked_hosts[host.get_name()] = True
    #                     self._queue_task(host, task, task_vars, play_context)
    #                     del task_vars

    #                 # if we're bypassing the host loop, break out now
    #                 if run_once:
    #                     break

    #                 results += self._process_pending_results(
    #                     iterator, max_passes=max(1, int(len(self._tqm._workers) * 0.1))
    #                 )

    #             # go to next host/task group
    #             if skip_rest:
    #                 continue

    #             display.debug("done queuing things up, now waiting for results queue to drain")
    #             if self._pending_results > 0:
    #                 results += self._wait_on_pending_results(iterator)

    #             host_results.extend(results)

    #             self.update_active_connections(results)

    #             included_files = IncludedFile.process_include_results(
    #                 host_results, iterator=iterator, loader=self._loader, variable_manager=self._variable_manager
    #             )

    #             if len(included_files) > 0:
    #                 display.debug("we have included files to process")

    #                 display.debug("generating all_blocks data")
    #                 all_blocks = dict((host, []) for host in hosts_left)
    #                 display.debug("done generating all_blocks data")
    #                 for included_file in included_files:
    #                     display.debug("processing included file: %s" % included_file._filename)
    #                     # included hosts get the task list while those excluded get an equal-length
    #                     # list of noop tasks, to make sure that they continue running in lock-step
    #                     try:
    #                         if included_file._is_role:
    #                             new_ir = self._copy_included_file(included_file)

    #                             new_blocks, handler_blocks = new_ir.get_block_list(
    #                                 play=iterator._play,
    #                                 variable_manager=self._variable_manager,
    #                                 loader=self._loader,
    #                             )
    #                         else:
    #                             new_blocks = self._load_included_file(included_file, iterator=iterator)

    #                         display.debug("iterating over new_blocks loaded from include file")
    #                         for new_block in new_blocks:
    #                             task_vars = self._variable_manager.get_vars(
    #                                 play=iterator._play,
    #                                 task=new_block.get_first_parent_include(),
    #                                 _hosts=self._hosts_cache,
    #                                 _hosts_all=self._hosts_cache_all,
    #                             )
    #                             display.debug("filtering new block on tags")
    #                             final_block = new_block.filter_tagged_tasks(task_vars)
    #                             display.debug("done filtering new block on tags")

    #                             noop_block = self._prepare_and_create_noop_block_from(
    #                                 final_block, task._parent, iterator
    #                             )

    #                             for host in hosts_left:
    #                                 if host in included_file._hosts:
    #                                     all_blocks[host].append(final_block)
    #                                 else:
    #                                     all_blocks[host].append(noop_block)
    #                         display.debug("done iterating over new_blocks loaded from include file")
    #                     except AnsibleParserError:
    #                         raise
    #                     except AnsibleError as e:
    #                         for r in included_file._results:
    #                             r._result["failed"] = True

    #                         for host in included_file._hosts:
    #                             self._tqm._failed_hosts[host.name] = True
    #                             iterator.mark_host_failed(host)
    #                         display.error(to_text(e), wrap_text=False)
    #                         continue

    #                 # finally go through all of the hosts and append the
    #                 # accumulated blocks to their list of tasks
    #                 display.debug("extending task lists for all hosts with included blocks")

    #                 for host in hosts_left:
    #                     iterator.add_tasks(host, all_blocks[host])

    #                 display.debug("done extending task lists")
    #                 display.debug("done processing included files")

    #             display.debug("results queue empty")

    #             display.debug("checking for any_errors_fatal")
    #             failed_hosts = []
    #             unreachable_hosts = []
    #             for res in results:
    #                 # execute_meta() does not set 'failed' in the TaskResult
    #                 # so we skip checking it with the meta tasks and look just at the iterator
    #                 if (res.is_failed() or res._task.action in C._ACTION_META) and iterator.is_failed(res._host):
    #                     failed_hosts.append(res._host.name)
    #                 elif res.is_unreachable():
    #                     unreachable_hosts.append(res._host.name)

    #             # if any_errors_fatal and we had an error, mark all hosts as failed
    #             if any_errors_fatal and (len(failed_hosts) > 0 or len(unreachable_hosts) > 0):
    #                 dont_fail_states = frozenset([IteratingStates.RESCUE, IteratingStates.ALWAYS])
    #                 for host in hosts_left:
    #                     (s, _) = iterator.get_next_task_for_host(host, peek=True)
    #                     # the state may actually be in a child state, use the get_active_state()
    #                     # method in the iterator to figure out the true active state
    #                     s = iterator.get_active_state(s)
    #                     if (
    #                         s.run_state not in dont_fail_states
    #                         or s.run_state == IteratingStates.RESCUE
    #                         and s.fail_state & FailedStates.RESCUE != 0
    #                     ):
    #                         self._tqm._failed_hosts[host.name] = True
    #                         result |= self._tqm.RUN_FAILED_BREAK_PLAY
    #             display.debug("done checking for any_errors_fatal")

    #             display.debug("checking for max_fail_percentage")
    #             if iterator._play.max_fail_percentage is not None and len(results) > 0:
    #                 percentage = iterator._play.max_fail_percentage / 100.0

    #                 if (len(self._tqm._failed_hosts) / iterator.batch_size) > percentage:
    #                     for host in hosts_left:
    #                         # don't double-mark hosts, or the iterator will potentially
    #                         # fail them out of the rescue/always states
    #                         if host.name not in failed_hosts:
    #                             self._tqm._failed_hosts[host.name] = True
    #                             iterator.mark_host_failed(host)
    #                     self._tqm.send_callback("v2_playbook_on_no_hosts_remaining")
    #                     result |= self._tqm.RUN_FAILED_BREAK_PLAY
    #                 display.debug(
    #                     "(%s failed / %s total )> %s max fail"
    #                     % (len(self._tqm._failed_hosts), iterator.batch_size, percentage)
    #                 )
    #             display.debug("done checking for max_fail_percentage")

    #             display.debug("checking to see if all hosts have failed and the running result is not ok")
    #             if result != self._tqm.RUN_OK and len(self._tqm._failed_hosts) >= len(hosts_left):
    #                 display.debug("^ not ok, so returning result now")
    #                 self._tqm.send_callback("v2_playbook_on_no_hosts_remaining")
    #                 return result
    #             display.debug("done checking to see if all hosts have failed")

    #         except (IOError, EOFError) as e:
    #             display.debug("got IOError/EOFError in task loop: %s" % e)
    #             # most likely an abort, return failed
    #             return self._tqm.RUN_UNKNOWN_ERROR

    #     # run the base class run() method, which executes the cleanup function
    #     # and runs any outstanding handlers which have been triggered

    #     # execute one more pass through the iterator without peeking, to
    #     # make sure that all of the hosts are advanced to their final task.
    #     # This should be safe, as everything should be IteratingStates.COMPLETE by
    #     # this point, though the strategy may not advance the hosts itself.

    #     for host in self._hosts_cache:
    #         if host not in self._tqm._unreachable_hosts:
    #             try:
    #                 iterator.get_next_task_for_host(self._inventory.hosts[host])
    #             except KeyError:
    #                 iterator.get_next_task_for_host(self._inventory.get_host(host))

    #     # save the failed/unreachable hosts, as the run_handlers()
    #     # method will clear that information during its execution
    #     failed_hosts = iterator.get_failed_hosts()
    #     unreachable_hosts = self._tqm._unreachable_hosts.keys()

    #     display.debug("running handlers")
    #     handler_result = self.run_handlers(iterator, play_context)
    #     if isinstance(handler_result, bool) and not handler_result:
    #         result |= self._tqm.RUN_ERROR
    #     elif not handler_result:
    #         result |= handler_result

    #     # now update with the hosts (if any) that failed or were
    #     # unreachable during the handler execution phase
    #     failed_hosts = set(failed_hosts).union(iterator.get_failed_hosts())
    #     unreachable_hosts = set(unreachable_hosts).union(self._tqm._unreachable_hosts.keys())

    #     # return the appropriate code, depending on the status hosts after the run
    #     if not isinstance(result, bool) and result != self._tqm.RUN_OK:
    #         return result
    #     elif len(unreachable_hosts) > 0:
    #         return self._tqm.RUN_UNREACHABLE_HOSTS
    #     elif len(failed_hosts) > 0:
    #         return self._tqm.RUN_FAILED_HOSTS
    #     else:
    #         return self._tqm.RUN_OK
