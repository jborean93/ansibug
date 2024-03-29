# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import shutil

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


def test_playbook_no_breakpoints(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "started"

    resp = dap_client.wait_for_message(dap.ThreadEvent)
    assert resp.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_playbook_with_logging(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
    )

    log_path = tmp_path / "ansibug.log"
    proc = dap_client.launch(
        playbook,
        playbook_dir=tmp_path,
        launch_options={"logFile": str(log_path)},
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")

    assert log_path.exists()


@pytest.mark.parametrize("single_thread", [True, False])
def test_playbook_with_breakpoint(
    single_thread: bool,
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[4],
            breakpoints=[dap.SourceBreakpoint(line=6)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(resp.breakpoints) == 1
    assert resp.breakpoints[0].verified
    assert resp.breakpoints[0].line == 5
    assert resp.breakpoints[0].end_line == 5
    bid = resp.breakpoints[0].id

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping test"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid, single_thread=single_thread), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_breakpoint_at_end_of_file(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[8],
            breakpoints=[dap.SourceBreakpoint(line=8)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(resp.breakpoints) == 1
    assert resp.breakpoints[0].verified
    assert resp.breakpoints[0].line == 5
    assert resp.breakpoints[0].end_line == 5
    bid = resp.breakpoints[0].id

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping test"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_playbook_with_modified_source(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: ping 2
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 8],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=8)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 2
    assert bp_resp.breakpoints[0].verified
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line == 7
    assert bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 8
    assert bp_resp.breakpoints[1].end_line == 8

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 1"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    # Mimick the file being modified. Will invalidate all breakpoints in the
    # file.
    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 8],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=8)],
            source_modified=True,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 2
    assert bp_resp.breakpoints[0].verified is False
    assert bp_resp.breakpoints[0].message == "Cannot set breakpoint on a modified source."
    assert bp_resp.breakpoints[0].line is None
    assert bp_resp.breakpoints[0].end_line is None
    assert bp_resp.breakpoints[1].verified is False
    assert bp_resp.breakpoints[1].message == "Cannot set breakpoint on a modified source."
    assert bp_resp.breakpoints[1].line is None
    assert bp_resp.breakpoints[1].end_line is None

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_breakpoint_with_disconnect_on_stop(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:

  - ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 8],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=8)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(resp.breakpoints) == 2
    assert resp.breakpoints[0].verified
    assert resp.breakpoints[0].line == 5
    assert resp.breakpoints[0].end_line == 7
    assert resp.breakpoints[1].verified
    assert resp.breakpoints[1].line == 8
    assert resp.breakpoints[1].end_line == 8

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    dap_client.wait_for_message(dap.ThreadEvent)

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.DisconnectRequest(), dap.DisconnectResponse)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_breakpoint_stepping(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: include play tasks
    include_tasks: tasks.yml

  - name: final task
    ping:
"""
    )

    tasks = tmp_path / "tasks.yml"
    tasks.write_text(
        r"""
- name: task 1
  ping:

- name: include tasks 1
  include_tasks: sub_tasks.yml

- name: task 2
  ping:

- name: task 3
  ping:
"""
    )

    sub_tasks = tmp_path / "sub_tasks.yml"
    sub_tasks.write_text(
        r"""
- name: sub task 1
  ping:

- name: sub task 2
  ping:

- name: sub task 3
  ping:
"""
    )

    # Set BP on 'include tasks 1' and 'task 2'
    # Step into sub_tasks - 'sub task 1'
    # Step over to next task - 'sub task 2'
    # Continue - 'task 2'
    # Step out - 'final ping'
    # Step out - finished
    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="tasks.yml",
                path=str(tasks.absolute()),
            ),
            lines=[5, 8],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=8)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    # They won't be verified until include_tasks was run
    assert len(bp_resp.breakpoints) == 2
    assert not bp_resp.breakpoints[0].verified
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."

    assert not bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 8
    assert bp_resp.breakpoints[1].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    # Once running it'll run include_tasks which then validates the breakpoints
    # This is a complicated step as the debuggee is building the source map
    # based on the tasks found in order so it'll send multiple breakpoints
    # update events.

    # First task processed, both breakpoints are updated with the new lines
    bp_event1 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event1.breakpoint.id == bp_resp.breakpoints[0].id
    assert bp_event1.breakpoint.line == 2
    assert bp_event1.breakpoint.end_line == 2

    bp_event2 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event2.breakpoint.id == bp_resp.breakpoints[1].id
    assert bp_event2.breakpoint.line == 2
    assert bp_event2.breakpoint.end_line == 2

    # Middle task is processed, both breakpoints are updated with the new lines
    bp_event3 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event3.breakpoint.id == bp_resp.breakpoints[0].id
    assert bp_event3.breakpoint.line == 5
    assert bp_event3.breakpoint.end_line == 5

    bp_event4 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event4.breakpoint.id == bp_resp.breakpoints[1].id
    assert bp_event4.breakpoint.line == 5
    assert bp_event4.breakpoint.end_line == 5

    # Task 2 is processed, first breakpoint has the updated end_line,
    # second breakpoint has new line updated for new task
    bp_event5 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event5.breakpoint.id == bp_resp.breakpoints[0].id
    assert bp_event5.breakpoint.line == 5
    assert bp_event5.breakpoint.end_line == 7
    bp_event6 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event6.breakpoint.id == bp_resp.breakpoints[1].id
    assert bp_event6.breakpoint.line == 8
    assert bp_event6.breakpoint.end_line == 8

    # Task 3 is processed, last breakpoint has new end_line
    bp_event7 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event7.breakpoint.id == bp_resp.breakpoints[1].id
    assert bp_event7.breakpoint.line == 8
    assert bp_event7.breakpoint.end_line == 10

    bp_id1 = bp_event5.breakpoint.id
    bp_id2 = bp_event7.breakpoint.id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_id1]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 2
    assert st_resp.total_frames == 2
    assert st_resp.stack_frames[0].name == "include tasks 1"
    assert st_resp.stack_frames[1].name == "include play tasks"

    dap_client.send(dap.StepInRequest(thread_id=localhost_tid), dap.StepInResponse)
    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.STEP
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == []

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 3
    assert st_resp.total_frames == 3
    assert st_resp.stack_frames[0].name == "sub task 1"
    assert st_resp.stack_frames[1].name == "include tasks 1"
    assert st_resp.stack_frames[2].name == "include play tasks"

    dap_client.send(dap.NextRequest(thread_id=localhost_tid), dap.NextResponse)
    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.STEP
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == []

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 3
    assert st_resp.total_frames == 3
    assert st_resp.stack_frames[0].name == "sub task 2"
    assert st_resp.stack_frames[1].name == "include tasks 1"
    assert st_resp.stack_frames[2].name == "include play tasks"

    # This is just a test to ensure variables are cleaned up from parent stack frames
    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[1].id), dap.ScopesResponse)
    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    for v in task_vars.variables:
        if v.name == "inventory_hostname":
            assert v.value == "'localhost'"
            break
    else:
        raise Exception("Failed to find inventory_hostname in sub task")

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_id2]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 2
    assert st_resp.total_frames == 2
    assert st_resp.stack_frames[0].name == "task 2"
    assert st_resp.stack_frames[1].name == "include play tasks"

    dap_client.send(dap.StepOutRequest(thread_id=localhost_tid), dap.StepOutResponse)
    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.STEP
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == []

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "final task"

    dap_client.send(dap.StepOutRequest(thread_id=localhost_tid), dap.StepOutResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_conditional_breakpoint(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: ping 2
    ping:
    register: ping_res

  - name: ping 3
    ping:

  - name: ping 4
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7, 9, 12, 15],
            breakpoints=[
                dap.SourceBreakpoint(line=7, condition="inventory_hostname == 'fake'"),
                dap.SourceBreakpoint(line=9, condition="inventory_hostname == 'localhost'"),
                dap.SourceBreakpoint(line=12, condition="ping_res.ping == 'pong'"),
                # Invalid conditional is ignored and treated as False.
                dap.SourceBreakpoint(line=15, condition="invalid"),
            ],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 4
    assert bp_resp.breakpoints[0].verified
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line == 7
    assert bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 8
    assert bp_resp.breakpoints[1].end_line == 11
    assert bp_resp.breakpoints[2].verified
    assert bp_resp.breakpoints[2].line == 12
    assert bp_resp.breakpoints[2].end_line == 14
    assert bp_resp.breakpoints[3].verified
    assert bp_resp.breakpoints[3].line == 15
    assert bp_resp.breakpoints[3].end_line == 15

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[1].id]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[2].id]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_breakpoint_misaligned(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: ping 2
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[7, 9],
            breakpoints=[dap.SourceBreakpoint(line=7), dap.SourceBreakpoint(line=9)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 2
    assert bp_resp.breakpoints[0].verified
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line == 7
    assert bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 8
    assert bp_resp.breakpoints[1].end_line == 8

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[1].id]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_breakpoint_block(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - block:
    - name: ping 1
      ping:

    rescue:
    - name: ping 2
      ping:

    always:
    - name: ping 3
      ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 7, 12, 15],
            breakpoints=[
                dap.SourceBreakpoint(line=5),
                dap.SourceBreakpoint(line=7),
                dap.SourceBreakpoint(line=12),
                dap.SourceBreakpoint(line=15),
            ],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 4
    # Currently blocks are limited in how they are mapped, the block/rescue/always
    # label are included in the previous task, the breakpoint task mapping only
    # works from the `- name: ...` declaration of the task until the next one
    assert bp_resp.breakpoints[0].verified is False
    assert bp_resp.breakpoints[0].message == "Breakpoint cannot be set here."
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line == 5
    assert bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 6
    assert bp_resp.breakpoints[1].end_line == 9
    assert bp_resp.breakpoints[2].verified
    assert bp_resp.breakpoints[2].line == 10
    assert bp_resp.breakpoints[2].end_line == 13
    assert bp_resp.breakpoints[3].verified
    assert bp_resp.breakpoints[3].line == 14
    assert bp_resp.breakpoints[3].end_line == 14

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[1].id]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[3].id]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_breakpoint_block_in_include(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - include_tasks: tasks.yml
"""
    )

    tasks = tmp_path / "tasks.yml"
    tasks.write_text(
        r"""
- name: ping pre
  ping:

- block:
  - name: ping 1
    ping:

  rescue:
  - name: ping 2
    ping:

  always:
  - name: ping 3
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="tasks.yml",
                path=str(tasks.absolute()),
            ),
            lines=[5, 6, 10, 17],
            breakpoints=[
                dap.SourceBreakpoint(line=5),
                dap.SourceBreakpoint(line=6),
                dap.SourceBreakpoint(line=10),
                dap.SourceBreakpoint(line=17),
            ],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 4
    assert bp_resp.breakpoints[0].verified is False
    assert bp_resp.breakpoints[0].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line is None
    assert bp_resp.breakpoints[1].verified is False
    assert bp_resp.breakpoints[1].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."
    assert bp_resp.breakpoints[1].line == 6
    assert bp_resp.breakpoints[1].end_line is None
    assert bp_resp.breakpoints[2].verified is False
    assert bp_resp.breakpoints[2].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."
    assert bp_resp.breakpoints[2].line == 10
    assert bp_resp.breakpoints[2].end_line is None
    assert bp_resp.breakpoints[3].verified is False
    assert bp_resp.breakpoints[3].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."
    assert bp_resp.breakpoints[3].line == 17
    assert bp_resp.breakpoints[3].end_line is None

    bp_id1 = bp_resp.breakpoints[0].id
    bp_id2 = bp_resp.breakpoints[1].id
    bp_id3 = bp_resp.breakpoints[2].id
    bp_id4 = bp_resp.breakpoints[3].id

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    # Tasks are processed one by one which will affect the breakpoints in the
    # file and their locations.

    # First task is processed, all breakpoints are set to this task
    bp_event1 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event1.breakpoint.id == bp_id1
    assert bp_event1.breakpoint.verified is True
    assert bp_event1.breakpoint.message is None
    assert bp_event1.breakpoint.line == 2
    assert bp_event1.breakpoint.end_line == 2

    bp_event2 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event2.breakpoint.id == bp_id2
    assert bp_event2.breakpoint.verified is True
    assert bp_event2.breakpoint.message is None
    assert bp_event2.breakpoint.line == 2
    assert bp_event2.breakpoint.end_line == 2

    bp_event3 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event3.breakpoint.id == bp_id3
    assert bp_event3.breakpoint.verified is True
    assert bp_event3.breakpoint.message is None
    assert bp_event3.breakpoint.line == 2
    assert bp_event3.breakpoint.end_line == 2

    bp_event4 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event4.breakpoint.id == bp_id4
    assert bp_event4.breakpoint.verified is True
    assert bp_event4.breakpoint.message is None
    assert bp_event4.breakpoint.line == 2
    assert bp_event4.breakpoint.end_line == 2

    # block is processed, all are marked as invalid
    bp_event5 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event5.breakpoint.id == bp_id1
    assert bp_event5.breakpoint.verified is False
    assert bp_event5.breakpoint.message == "Breakpoint cannot be set here."
    assert bp_event5.breakpoint.line == 5
    assert bp_event5.breakpoint.end_line == 5

    bp_event6 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event6.breakpoint.id == bp_id2
    assert bp_event6.breakpoint.verified is False
    assert bp_event6.breakpoint.message == "Breakpoint cannot be set here."
    assert bp_event6.breakpoint.line == 5
    assert bp_event6.breakpoint.end_line == 5

    bp_event7 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event7.breakpoint.id == bp_id3
    assert bp_event7.breakpoint.verified is False
    assert bp_event7.breakpoint.message == "Breakpoint cannot be set here."
    assert bp_event7.breakpoint.line == 5
    assert bp_event7.breakpoint.end_line == 5

    bp_event8 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event8.breakpoint.id == bp_id4
    assert bp_event8.breakpoint.verified is False
    assert bp_event8.breakpoint.message == "Breakpoint cannot be set here."
    assert bp_event8.breakpoint.line == 5
    assert bp_event8.breakpoint.end_line == 5

    # ping 1 is processed, bp1 is still invalid but remaining are updated to
    # new location
    bp_event9 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event9.breakpoint.id == bp_id2
    assert bp_event9.breakpoint.verified
    assert bp_event9.breakpoint.message is None
    assert bp_event9.breakpoint.line == 6
    assert bp_event9.breakpoint.end_line == 6

    bp_event10 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event10.breakpoint.id == bp_id3
    assert bp_event10.breakpoint.verified
    assert bp_event10.breakpoint.message is None
    assert bp_event10.breakpoint.line == 6
    assert bp_event10.breakpoint.end_line == 6

    bp_event11 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event11.breakpoint.id == bp_id4
    assert bp_event11.breakpoint.verified
    assert bp_event11.breakpoint.message is None
    assert bp_event11.breakpoint.line == 6
    assert bp_event11.breakpoint.end_line == 6

    # rescue/ping 2 is processed, bp1 stays the same, bp2 has new lines, bp3+
    # are set to the end lines.
    bp_event12 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event12.breakpoint.id == bp_id2
    assert bp_event12.breakpoint.verified
    assert bp_event12.breakpoint.message is None
    assert bp_event12.breakpoint.line == 6
    assert bp_event12.breakpoint.end_line == 9

    bp_event13 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event13.breakpoint.id == bp_id3
    assert bp_event13.breakpoint.verified
    assert bp_event13.breakpoint.message is None
    assert bp_event13.breakpoint.line == 10
    assert bp_event13.breakpoint.end_line == 10

    bp_event14 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event14.breakpoint.id == bp_id4
    assert bp_event14.breakpoint.verified
    assert bp_event14.breakpoint.message is None
    assert bp_event14.breakpoint.line == 10
    assert bp_event14.breakpoint.end_line == 10

    # always/ping 3 is processed, bp1/2 stays the same, bp3 has new end line,
    # bp4 has updated line.
    bp_event15 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event15.breakpoint.id == bp_id3
    assert bp_event15.breakpoint.verified
    assert bp_event15.breakpoint.message is None
    assert bp_event15.breakpoint.line == 10
    assert bp_event15.breakpoint.end_line == 13

    bp_event16 = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event16.breakpoint.id == bp_id4
    assert bp_event16.breakpoint.verified
    assert bp_event16.breakpoint.message is None
    assert bp_event16.breakpoint.line == 14
    assert bp_event16.breakpoint.end_line == 14

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_id2]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_id4]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_multiple_plays(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- name: play 1
  hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:

- name: play 2
  hosts: localhost
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[13],
            breakpoints=[dap.SourceBreakpoint(line=13)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(resp.breakpoints) == 1
    assert resp.breakpoints[0].verified
    assert resp.breakpoints[0].line == 13
    assert resp.breakpoints[0].end_line == 13
    bid = resp.breakpoints[0].id

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    # The host thread will start and stop for the first play
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    # The second play has a new thread that's started
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_breakpoint_set_during_run(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 1
    ping:

  - name: ping 2
    ping:

  - name: ping 3
    ping:
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 11],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=11)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 2
    assert bp_resp.breakpoints[0].verified
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line == 7
    assert bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 11
    assert bp_resp.breakpoints[1].end_line == 11

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    # Unset the second breakpoint
    bp_resp = dap_client.send(
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
    assert len(bp_resp.breakpoints) == 1
    assert bp_resp.breakpoints[0].verified
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line == 7

    # Add in the second breakpoint again in a new location
    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 8],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=8)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 2
    assert bp_resp.breakpoints[0].verified
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line == 7
    assert bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 8
    assert bp_resp.breakpoints[1].end_line == 10

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[1].id]

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_role_include(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: including my role
    include_role:
      name: my_role

  - name: ping 1
    ping:
"""
    )

    my_role = tmp_path / "roles" / "my_role"
    my_role.mkdir(parents=True)

    role_tasks = my_role / "tasks"
    role_tasks.mkdir()
    tasks = role_tasks / "main.yml"
    tasks.write_text("- ping:")

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    playbook_bp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[9],
            breakpoints=[dap.SourceBreakpoint(line=9)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(playbook_bp.breakpoints) == 1
    assert playbook_bp.breakpoints[0].verified
    assert playbook_bp.breakpoints[0].line == 9
    assert playbook_bp.breakpoints[0].end_line == 9

    role_bp = dap_client.send(
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
    assert len(role_bp.breakpoints) == 1
    assert role_bp.breakpoints[0].verified is False
    assert role_bp.breakpoints[0].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."
    assert role_bp.breakpoints[0].line == 1
    assert role_bp.breakpoints[0].end_line is None

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    # First role task will verify the breakpoint before it will be hit
    bp_event = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event.breakpoint.id == role_bp.breakpoints[0].id
    assert bp_event.breakpoint.verified
    assert bp_event.breakpoint.message is None
    assert bp_event.breakpoint.line == 1
    assert bp_event.breakpoint.end_line == 1

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [role_bp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 2
    assert st_resp.total_frames == 2
    assert st_resp.stack_frames[0].name == "my_role : ping"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(tasks)
    assert st_resp.stack_frames[0].source.name == "main.yml"
    assert st_resp.stack_frames[1].name == "including my role"
    assert st_resp.stack_frames[1].source is not None
    assert st_resp.stack_frames[1].source.path == str(playbook)
    assert st_resp.stack_frames[1].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [playbook_bp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 1"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_path_mappings(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    local_dir = tmp_path / "local"
    local_dir.mkdir()

    playbook = local_dir / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: including my role
    include_role:
      name: my_role

  - name: ping 1
    ping:
"""
    )

    my_role = local_dir / "roles" / "my_role"
    my_role.mkdir(parents=True)

    role_tasks = my_role / "tasks"
    role_tasks.mkdir()
    tasks = role_tasks / "main.yml"
    tasks.write_text("- ping:")

    remote_dir = tmp_path / "remote"
    shutil.copytree(local_dir, remote_dir)

    proc = dap_client.launch(
        remote_dir / "main.yml",
        playbook_dir=remote_dir,
        launch_options={
            "pathMappings": [
                {
                    "localRoot": "/unknown/local/project",
                    "remoteRoot": "/unknown/remote/project",
                },
                {
                    "localRoot": str(local_dir.absolute()),
                    "remoteRoot": str(remote_dir.absolute()),
                },
            ],
        },
    )

    playbook_bp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[9],
            breakpoints=[dap.SourceBreakpoint(line=9)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(playbook_bp.breakpoints) == 1
    assert playbook_bp.breakpoints[0].verified
    assert playbook_bp.breakpoints[0].line == 9
    assert playbook_bp.breakpoints[0].end_line == 9

    role_bp = dap_client.send(
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
    assert len(role_bp.breakpoints) == 1
    assert role_bp.breakpoints[0].verified is False
    assert role_bp.breakpoints[0].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."
    assert role_bp.breakpoints[0].line == 1
    assert role_bp.breakpoints[0].end_line is None

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    # First role task will verify the breakpoint
    bp_event = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event.breakpoint.id == role_bp.breakpoints[0].id
    assert bp_event.breakpoint.verified
    assert bp_event.breakpoint.line == 1
    assert bp_event.breakpoint.end_line == 1

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [role_bp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 2
    assert st_resp.total_frames == 2
    assert st_resp.stack_frames[0].name == "my_role : ping"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(tasks)
    assert st_resp.stack_frames[0].source.name == "main.yml"
    assert st_resp.stack_frames[1].name == "including my role"
    assert st_resp.stack_frames[1].source is not None
    assert st_resp.stack_frames[1].source.path == str(playbook)
    assert st_resp.stack_frames[1].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [playbook_bp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 1"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")
