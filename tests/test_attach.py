# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys

import pytest
from dap_client import DAPClient

import ansibug.dap as dap


@pytest.mark.parametrize("attach_by_address", [False, True])
def test_attach_playbook(
    attach_by_address: bool,
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

    proc = dap_client.attach(
        playbook,
        playbook_dir=tmp_path,
        attach_by_address=attach_by_address,
    )

    resp = dap_client.send(
        dap.SetBreakpointsRequest(
            source=dap.Source(
                name="main.yml",
                path=str(playbook.absolute()),
            ),
            lines=[5],
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

    dap_client.send(dap.ContinueRequest(thread_id=localhost_tid), dap.ContinueResponse)

    thread_event = dap_client.wait_for_message(dap.ThreadEvent)
    assert thread_event.reason == "exited"

    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.communicate()
    if rc := proc.returncode:
        raise Exception(f"Playbook failed {rc}\nSTDOUT: {play_out[0].decode()}\nSTDERR: {play_out[1].decode()}")


def test_attach_path_mappings(
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

    proc = dap_client.attach(
        remote_dir / "main.yml",
        playbook_dir=remote_dir,
        attach_by_address=False,
        attach_options={
            "pathMappings": [
                {
                    "localRoot": str(local_dir.absolute()),
                    "remoteRoot": str(remote_dir.absolute()),
                }
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


def test_run_with_listen_no_client(
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
    actual = subprocess.run(
        [sys.executable, "-m", "ansibug", "listen", "--no-wait", str(playbook)],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if actual.returncode:
        raise Exception(f"Playbook failed {actual.returncode}\nSTDOUT: {actual.stdout}\nSTDERR: {actual.stderr}")


def test_attach_invalid_pid(
    dap_client: DAPClient,
) -> None:
    attach_args = {
        "processId": 0,
    }

    with pytest.raises(Exception, match="Failed to find process pid file at "):
        dap_client.send(dap.AttachRequest(arguments=attach_args), dap.AttachResponse)


def test_attach_no_pid_or_port(
    dap_client: DAPClient,
) -> None:
    attach_args = {
        "address": "localhost",
    }

    with pytest.raises(Exception, match="Expected processId or address/port to be specified for attach"):
        dap_client.send(dap.AttachRequest(arguments=attach_args), dap.AttachResponse)
