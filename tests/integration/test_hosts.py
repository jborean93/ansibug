# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

from dap_client import DAPClient, write_inventory

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

    write_inventory(tmp_path, 2)

    proc = dap_client.launch(playbook, playbook_dir=tmp_path, playbook_args=["-i", "inventory.ini"])

    resp = dap_client.set_breakpoints(playbook, 5)
    bid = resp[0].id

    host1_tid = dap_client.configuration_done()

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    assert stopped_event.thread_id is not None
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host2_tid = thread_event.thread_id

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

    assert stopped_event.thread_id is not None
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.thread_id == host1_tid
    assert thread_event.reason == "exited"

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.thread_id == host2_tid
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    proc.wait_rc()


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

    write_inventory(tmp_path, 1)

    proc = dap_client.launch(playbook, playbook_dir=tmp_path, playbook_args=["-i", "inventory.ini"])

    bp_resp = dap_client.set_breakpoints(playbook, 5, 16)
    assert bp_resp[0].verified
    assert bp_resp[0].line == 5
    assert bp_resp[0].end_line == 10
    assert bp_resp[1].verified
    assert bp_resp[1].line == 16
    assert bp_resp[1].end_line == 16

    host1_tid = dap_client.configuration_done()

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp[0].id]

    # The new host should not be added until the new play
    assert stopped_event.thread_id is not None
    dap_client.send(dap.StepInRequest(thread_id=stopped_event.thread_id), dap.StepInResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.STEP
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == []

    assert stopped_event.thread_id is not None
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.thread_id == host1_tid
    assert thread_event.reason == "exited"

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host1_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host1_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "ping test"

    assert stopped_event.thread_id is not None
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp[1].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=host2_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "ping test"

    assert stopped_event.thread_id is not None
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    dap_client.wait_for_thread("exited")
    dap_client.wait_for_end(proc)
