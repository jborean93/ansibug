# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import json
import pathlib

from dap_client import DAPClient

import ansibug.dap as dap


def test_meta_simple_breakpoint(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  vars:
    foo: bar
  tasks:
  - meta: noop

  - name: task 2
    meta: noop
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
    assert bp_resp.breakpoints[0].line == 7
    assert bp_resp.breakpoints[0].end_line == 8
    assert bp_resp.breakpoints[1].verified
    assert bp_resp.breakpoints[1].line == 9
    assert bp_resp.breakpoints[1].end_line == 9

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    localhost_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.stack_frames[0].name == "meta"

    scope_resp = dap_client.send(dap.ScopesRequest(frame_id=st_resp.stack_frames[0].id), dap.ScopesResponse)
    assert len(scope_resp.scopes) == 4

    module_opts = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[0].variables_reference),
        dap.VariablesResponse,
    )
    assert len(module_opts.variables) == 1
    assert module_opts.variables[0].name == "_raw_params"
    assert module_opts.variables[0].value == "'noop'"

    task_vars = dap_client.send(
        dap.VariablesRequest(variables_reference=scope_resp.scopes[1].variables_reference),
        dap.VariablesResponse,
    )
    found = False
    for v in task_vars.variables:
        if v.name == "foo":
            assert v.value == "'bar'"
            found = True
            break

    assert found

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


def test_meta_refresh_inventory_extra_hosts(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: all
  gather_facts: false
  tasks:
  - meta: refresh_inventory

  - meta: noop

- hosts: all
  gather_facts: false
  tasks:
  - meta: noop
"""
    )

    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("host1\nhost2\n")

    inventory = tmp_path / "ns.name.inv.yml"
    inventory.write_text(json.dumps({"plugin": "ns.name.inv", "hosts_file": str(hosts_file)}))

    collections_path = pathlib.Path(__file__).parent / "data"
    ansible_cfg = tmp_path / "ansible.cfg"
    ansible_cfg.write_text(
        rf"""[defaults]
collections_path = {collections_path.absolute()!s}
inventory = ns.name.inv.yml
"""
    )

    proc = dap_client.launch(
        playbook,
        playbook_dir=tmp_path,
        playbook_args=["-vvv"],
        launch_options={
            "env": {"ANSIBLE_CONFIG": str(ansible_cfg.absolute())},
        },
    )

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 7, 12],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=7), dap.SourceBreakpoint(line=12)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host1_tid = thread_event.thread_id
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id is not None

    hosts_file.write_text("host1\nhost2\nhost3\n")

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    # Existing hosts are removed
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"
    assert thread_event.thread_id == host1_tid

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"
    assert thread_event.thread_id == host2_tid

    # Hosts are added back in as they are processed on the task
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host1_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host1_tid
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host2_tid
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"
    assert thread_event.thread_id == host1_tid

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"
    assert thread_event.thread_id == host2_tid

    # New play starts and the new hosts are added
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host1_tid = thread_event.thread_id

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host2_tid = thread_event.thread_id

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host3_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host1_tid
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host2_tid
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host3_tid
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_meta_refresh_inventory_removed_hosts(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: all
  gather_facts: false
  tasks:
  - meta: refresh_inventory

  - meta: noop

- hosts: all
  gather_facts: false
  tasks:
  - meta: noop
"""
    )

    hosts_file = tmp_path / "hosts"
    hosts_file.write_text("host1\nhost2\n")

    inventory = tmp_path / "ns.name.inv.yml"
    inventory.write_text(json.dumps({"plugin": "ns.name.inv", "hosts_file": str(hosts_file)}))

    collections_path = pathlib.Path(__file__).parent / "data"
    ansible_cfg = tmp_path / "ansible.cfg"
    ansible_cfg.write_text(
        rf"""[defaults]
collections_path = {collections_path.absolute()!s}
inventory = ns.name.inv.yml
"""
    )

    proc = dap_client.launch(
        playbook,
        playbook_dir=tmp_path,
        playbook_args=["-vvv"],
        launch_options={
            "env": {"ANSIBLE_CONFIG": str(ansible_cfg.absolute())},
        },
    )

    dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 7, 12],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=7), dap.SourceBreakpoint(line=12)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host1_tid = thread_event.thread_id
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id is not None

    hosts_file.write_text("host1\n")

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    # Existing hosts are removed
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"
    assert thread_event.thread_id == host1_tid

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"
    assert thread_event.thread_id == host2_tid

    # Refresh inventory will remove hosts from the existing play
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host1_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host1_tid
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"
    assert thread_event.thread_id == host1_tid

    # New play starts and the refreshed hosts are used
    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "started"
    host1_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.thread_id == host1_tid
    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_meta_end_host(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: all
  gather_facts: false
  tasks:
  - meta: noop

  - meta: end_host
    when: inventory_hostname == 'host1'

  - meta: noop
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

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 10],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=10)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host1_tid = thread_event.thread_id

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[1].id]

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_meta_end_play(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: all
  gather_facts: false
  tasks:
  - meta: noop

  - meta: end_play

  - meta: noop
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

    bp_resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5, 10],
            breakpoints=[dap.SourceBreakpoint(line=5), dap.SourceBreakpoint(line=10)],
            source_modified=False,
        ),
        dap.SetBreakpointsResponse,
    )

    dap_client.send(dap.ConfigurationDoneRequest(), dap.ConfigurationDoneResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host1_tid = thread_event.thread_id

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    host2_tid = thread_event.thread_id

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host1_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == host2_tid
    assert stopped_event.hit_breakpoint_ids == [bp_resp.breakpoints[0].id]

    dap_client.send(dap.ContinueRequest(thread_id=stopped_event.thread_id), dap.ContinueResponse)

    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.ThreadEvent)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")
