# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


def test_handler_in_play(
    strategy: str,
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  handlers:
  - name: my handler
    meta: noop
  tasks:
  - ping:
    changed_when: true
    notify: my handler
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.set_breakpoints(playbook, 5)
    assert bp_resp[0].verified
    assert bp_resp[0].line == 5
    assert bp_resp[0].end_line == 7

    localhost_tid = dap_client.configuration_done()

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "my handler"

    dap_client.continue_to_end(proc, localhost_tid)


def test_handler_in_imported_role(
    strategy: str,
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  roles:
  - my_role
"""
    )

    my_role = tmp_path / "roles" / "my_role"
    my_role.mkdir(parents=True)

    role_tasks = my_role / "tasks"
    role_tasks.mkdir()
    tasks = role_tasks / "main.yml"
    tasks.write_text(
        r"""
- ping:
  changed_when: true
  notify: my handler
"""
    )

    role_handlers = my_role / "handlers"
    role_handlers.mkdir()
    handlers = role_handlers / "main.yml"
    handlers.write_text(
        r"""
- name: my handler
  meta: noop
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.set_breakpoints(handlers, 2)
    assert bp_resp[0].verified
    assert bp_resp[0].line == 2
    assert bp_resp[0].end_line == 2

    localhost_tid = dap_client.configuration_done()

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "my_role : my handler"

    dap_client.continue_to_end(proc, localhost_tid)


@pytest.mark.parametrize("set_tasks", [True, False])
def test_handler_in_included_role(
    strategy: str,
    set_tasks: bool,
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: include my role
    include_role:
      name: my_role

  - ping:
    changed_when: True
    notify: my handler
"""
    )

    my_role = tmp_path / "roles" / "my_role"
    my_role.mkdir(parents=True)

    if set_tasks:
        role_tasks = my_role / "tasks"
        role_tasks.mkdir()
        tasks = role_tasks / "main.yml"
        tasks.write_text("- ping:")

    role_handlers = my_role / "handlers"
    role_handlers.mkdir()
    handlers = role_handlers / "main.yml"
    handlers.write_text(
        r"""
- name: my handler
  meta: noop
"""
    )

    proc = dap_client.launch(playbook, playbook_dir=tmp_path)

    bp_resp = dap_client.set_breakpoints(handlers, 2)
    assert bp_resp[0].verified is False
    assert bp_resp[0].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."
    assert bp_resp[0].line == 2
    assert bp_resp[0].end_line is None

    localhost_tid = dap_client.configuration_done()

    # When the first role task is run the breakpoint will be validated. Even if
    # a role has no tasks Ansible injects a meta task that will hit this after
    # an include.
    bp_event = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event.breakpoint.id == bp_resp[0].id
    assert bp_event.breakpoint.verified
    assert bp_event.breakpoint.line == 2
    assert bp_event.breakpoint.end_line == 2

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "my_role : my handler"

    dap_client.continue_to_end(proc, localhost_tid)
