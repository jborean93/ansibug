# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""
These are tests for scenarios that are known to not really work with ansibug.
They are tested to ensure it doesn't catastrophically break the debugger and
things work in the background.
"""

from __future__ import annotations

import pathlib

from dap_client import DAPClient

import ansibug.dap as dap


def test_task_loop(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    """
    Loops are run in the fork which our strategy does not have control over.
    It will be treated as one single task with the looping happening as part
    of its execution.
    """
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: loop test
    ping:
    loop:
    - 1
    - 2

  - debug:
      msg: Placeholder
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    resp = dap_client.set_breakpoints(playbook, 5)
    assert resp[0].verified
    assert resp[0].line == 5
    assert resp[0].end_line == 10
    bid = resp[0].id

    localhost_tid = dap_client.configuration_done()

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "loop test"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.StepInRequest(thread_id=localhost_tid), dap.StepInResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.STEP
    assert stopped_event.thread_id == localhost_tid

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "debug"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.continue_to_end(proc, localhost_tid)


def test_task_roles_stackframe(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    # Roles under 'roles:' have no task in their parent chain so get no frame.
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  pre_tasks:
  - name: ping 1
    ping:

  roles:
  - my_role

  post_tasks:
  - name: ping 3
    ping:
"""
    )

    my_role = tmp_path / "roles" / "my_role"
    my_role.mkdir(parents=True)

    role_tasks = my_role / "tasks"
    role_tasks.mkdir()
    tasks = role_tasks / "main.yml"
    tasks.write_text("- name: ping 2\n  ping:")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    # The roles entry is invisible to the breakpoint engine, it'll snap back
    # to the previous task.
    play_bp = dap_client.set_breakpoints(playbook, 9, 12)
    assert play_bp[0].verified
    assert play_bp[0].line == 5
    assert play_bp[0].end_line == 11
    assert play_bp[1].verified
    assert play_bp[1].line == 12
    assert play_bp[1].end_line == 12

    tasks_bp = dap_client.set_breakpoints(tasks, 1)
    assert tasks_bp[0].verified
    assert tasks_bp[0].line == 1
    assert tasks_bp[0].end_line == 1

    localhost_tid = dap_client.configuration_done()

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [play_bp[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 1"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [tasks_bp[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "my_role : ping 2"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(tasks)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [play_bp[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 3"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.continue_to_end(proc, localhost_tid)
