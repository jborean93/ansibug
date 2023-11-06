# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

from dap_client import DAPClient

import ansibug.dap as dap


def test_playbook_with_multiple_hosts(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: all
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
    )

    inventory = tmp_path / "inventory.ini"
    inventory.write_text(
        r"""
host1 ansible_host=127.0.0.1 ansible_connection=local ansible_python_interpreter={{ansible_playbook_python}}
host2 ansible_host=127.0.0.1 ansible_connection=local ansible_python_interpreter={{ansible_playbook_python}}
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path, playbook_args=["-i", "inventory.ini"])

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
    bid = resp.breakpoints[0].id

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host1_tid = thread_event.thread_id

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    all_threads = dap_client.send(dap.ThreadsRequest(), dap.ThreadsResponse)
    assert len(all_threads.threads) == 3
    assert all_threads.threads[0].id == 1
    assert all_threads.threads[0].name == "main"
    assert all_threads.threads[1].id == host1_tid
    assert all_threads.threads[1].name == "host1"
    assert all_threads.threads[2].id == host2_tid
    assert all_threads.threads[2].name == "host2"

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.thread_id == host1_tid
    assert thread_event.reason == "exited"

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.thread_id == host2_tid
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_add_host(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: all
  gather_facts: false
  tasks:
  - name: add another host
    add_host:
      name: host2
      ansible_connection: local
      ansible_python_interpreter: '{{ ansible_playbook_python }}'

  - ping:

- hosts: all
  gather_facts: false
  tasks:
  - name: ping test
    ping:
"""
    )

    inventory = tmp_path / "inventory.ini"
    inventory.write_text(
        r"""
host1 ansible_host=127.0.0.1 ansible_connection=local ansible_python_interpreter={{ansible_playbook_python}}
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path, playbook_args=["-i", "inventory.ini"])

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 16],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(16)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )
    assert len(bp_resp.breakpoints) == 2
    assert bp_resp.breakpoints[0].verified
    assert bp_resp.breakpoints[0].line == 5
    assert bp_resp.breakpoints[0].end_line == 10
    assert bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 16
    assert bp_resp.breakpoints[1].end_line == 16

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host1_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    # The new host should not be added until the new play
    dap_client.send(dap.StepInRequest(thread_id=stopped_event.thread_id), dap.StepInResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.STEP
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == []

    # Stepping again will trigger the flush_handlers end task for the first play
    dap_client.send(dap.StepInRequest(thread_id=stopped_event.thread_id), dap.StepInResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.STEP
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == []

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "meta"
    assert st_resp.stack_frames[0].line == 2

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.thread_id == host1_tid
    assert thread_event.reason == "exited"

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host1_tid = thread_event.thread_id

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "ping test"

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "ping test"

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")
