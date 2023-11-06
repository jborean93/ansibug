# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

"""
These are tests for scenarios that are known to not really work with ansibug.
They are tested to ensure it doesn't catastrophically break the debugger and
things work in the background.
"""

from __future__ import annotations

import pathlib

import pytest
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

    resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
            breakpoints=[dap.SourceBreakpoint(line=5)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(resp.breakpoints) == 1
    assert resp.breakpoints[0].verified
    assert resp.breakpoints[0].line == 5
    assert resp.breakpoints[0].end_line == 10
    bid = resp.breakpoints[0].id

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

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

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_task_import_task_stackframe(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    """
    Static imports are processed when loaded before the Playbook object is
    given to our callback. This means our breakpoint code is unable to see
    those tasks in the playbook object and cannot be validated. This has two
    adverse effects:

    1. It will not be included in any stackframes for the imported tasks.
    2. Breakpoints for the import_* task will snap back to the previous task.
    """
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: import tasks
    import_tasks: tasks.yml

  - name: ping 3
    ping:
"""
    )

    tasks = tmp_path / "tasks.yml"
    tasks.write_text("- name: ping 2\n  ping:")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    # import_tasks is invisible to the breakpoint engine, it'll snap back to
    # the previous task.
    play_bp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[8, 11],
            breakpoints=[dap.SourceBreakpoint(line=8), dap.SourceBreakpoint(line=11)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(play_bp.breakpoints) == 2
    assert play_bp.breakpoints[0].verified
    assert play_bp.breakpoints[0].line == 5
    assert play_bp.breakpoints[0].end_line == 10
    assert play_bp.breakpoints[1].verified
    assert play_bp.breakpoints[1].line == 11
    assert play_bp.breakpoints[1].end_line == 11

    tasks_bp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(tasks.absolute()),
            ),
            lines=[1],
            breakpoints=[dap.SourceBreakpoint(line=1)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(tasks_bp.breakpoints) == 1
    assert tasks_bp.breakpoints[0].verified
    assert tasks_bp.breakpoints[0].line == 1
    assert tasks_bp.breakpoints[0].end_line == 1

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [play_bp.breakpoints[0].id]

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
    assert stopped_event.hit_breakpoint_ids == [tasks_bp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 2"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(tasks)
    assert st_resp.stack_frames[0].source.name == "tasks.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [play_bp.breakpoints[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 3"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_task_import_role_stackframe(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    # See test_task_import_task_stackframe for more info
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: import role
    import_role:
      name: my_role

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

    # import_role is invisible to the breakpoint engine, it'll snap back to
    # the previous task.
    play_bp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[8, 12],
            breakpoints=[dap.SourceBreakpoint(line=8), dap.SourceBreakpoint(line=12)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(play_bp.breakpoints) == 2
    assert play_bp.breakpoints[0].verified
    assert play_bp.breakpoints[0].line == 5
    assert play_bp.breakpoints[0].end_line == 11
    assert play_bp.breakpoints[1].verified
    assert play_bp.breakpoints[1].line == 12
    assert play_bp.breakpoints[1].end_line == 12

    tasks_bp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(tasks.absolute()),
            ),
            lines=[1],
            breakpoints=[dap.SourceBreakpoint(line=1)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(tasks_bp.breakpoints) == 1
    assert tasks_bp.breakpoints[0].verified
    assert tasks_bp.breakpoints[0].line == 1
    assert tasks_bp.breakpoints[0].end_line == 1

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [play_bp.breakpoints[0].id]

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
    assert stopped_event.hit_breakpoint_ids == [tasks_bp.breakpoints[0].id]

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
    assert stopped_event.hit_breakpoint_ids == [play_bp.breakpoints[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 3"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_task_roles_stackframe(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    # Same as test_task_import_role_stackframe but with a more common syntax
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

    # import_role is invisible to the breakpoint engine, it'll snap back to
    # the previous task.
    play_bp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[9, 12],
            breakpoints=[dap.SourceBreakpoint(line=9), dap.SourceBreakpoint(line=12)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(play_bp.breakpoints) == 2
    assert play_bp.breakpoints[0].verified
    assert play_bp.breakpoints[0].line == 5
    assert play_bp.breakpoints[0].end_line == 11
    assert play_bp.breakpoints[1].verified
    assert play_bp.breakpoints[1].line == 12
    assert play_bp.breakpoints[1].end_line == 12

    tasks_bp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(tasks.absolute()),
            ),
            lines=[1],
            breakpoints=[dap.SourceBreakpoint(line=1)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(tasks_bp.breakpoints) == 1
    assert tasks_bp.breakpoints[0].verified
    assert tasks_bp.breakpoints[0].line == 1
    assert tasks_bp.breakpoints[0].end_line == 1

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [play_bp.breakpoints[0].id]

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
    assert stopped_event.hit_breakpoint_ids == [tasks_bp.breakpoints[0].id]

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
    assert stopped_event.hit_breakpoint_ids == [play_bp.breakpoints[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 3"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")
