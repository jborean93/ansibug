# Copyright (c) 2023 Jordan Borean
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import typing as t

import pytest
from dap_client import AnsibleProcess, DAPClient, DAPErrorResponse, get_test_env

import ansibug.dap as dap


@pytest.mark.parametrize(
    ["attach_by_address", "connection_type"],
    [
        (False, "uds"),
        (False, "ipv4"),
        (False, "ipv6"),
        (True, "uds"),
        (True, "ipv4"),
        (True, "ipv6"),
    ],
    ids=[
        "pid_uds",
        "pid_tcp_ipv4",
        "pid_tcp_ipv6",
        "address_uds",
        "address_tcp_ipv4",
        "address_tcp_ipv6",
    ],
)
def test_attach_playbook(
    attach_by_address: bool,
    connection_type: t.Literal["uds", "ipv4", "ipv6"],
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    ansibug_args = []
    if connection_type == "ipv4":
        ansibug_args.extend(["--addr", "tcp://:0"])
    elif connection_type == "ipv6":
        ansibug_args.extend(["--addr", "tcp://[::]:0"])

    proc = dap_client.attach(
        ping_playbook,
        playbook_dir=tmp_path,
        ansibug_args=ansibug_args,
        attach_by_address=attach_by_address,
    )

    resp = dap_client.set_breakpoints(ping_playbook, 6)
    assert resp[0].verified
    assert resp[0].line == 5
    assert resp[0].end_line == 5
    bid = resp[0].id

    localhost_tid = dap_client.configuration_done()

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [bid]

    dap_client.continue_to_end(proc, localhost_tid)


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

    playbook_bp = dap_client.set_breakpoints(playbook, 9)
    assert playbook_bp[0].verified
    assert playbook_bp[0].line == 9
    assert playbook_bp[0].end_line == 9

    role_bp = dap_client.set_breakpoints(tasks, 1)
    assert role_bp[0].verified is False
    assert role_bp[0].message == "File has not been loaded by Ansible, cannot detect breakpoints yet."
    assert role_bp[0].line == 1
    assert role_bp[0].end_line is None

    localhost_tid = dap_client.configuration_done()

    # First role task will verify the breakpoint
    bp_event = dap_client.wait_for_message(dap.BreakpointEvent)
    assert bp_event.breakpoint.id == role_bp[0].id
    assert bp_event.breakpoint.verified
    assert bp_event.breakpoint.line == 1
    assert bp_event.breakpoint.end_line == 1

    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == localhost_tid
    assert stopped_event.hit_breakpoint_ids == [role_bp[0].id]

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
    assert stopped_event.hit_breakpoint_ids == [playbook_bp[0].id]

    st_resp = dap_client.send(dap.StackTraceRequest(thread_id=localhost_tid), dap.StackTraceResponse)
    assert len(st_resp.stack_frames) == 1
    assert st_resp.total_frames == 1
    assert st_resp.stack_frames[0].name == "ping 1"
    assert st_resp.stack_frames[0].source is not None
    assert st_resp.stack_frames[0].source.path == str(playbook)
    assert st_resp.stack_frames[0].source.name == "main.yml"

    dap_client.continue_to_end(proc, localhost_tid)


def test_run_with_listen_no_client(
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    actual = subprocess.run(
        [sys.executable, "-m", "ansibug", "listen", "--no-wait", str(ping_playbook)],
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    if actual.returncode:
        raise Exception(f"Playbook failed {actual.returncode}\nSTDOUT: {actual.stdout}\nSTDERR: {actual.stderr}")


def test_attach_with_disconnect(
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

    proc = dap_client.attach(playbook, playbook_dir=tmp_path)

    dap_client.set_breakpoints(playbook, 8)

    dap_client.configuration_done()

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.DisconnectRequest(terminate_debuggee=False), dap.DisconnectResponse)

    play_out = proc.wait_rc()

    assert "ok=3" in play_out[0]


def test_attach_with_terminate(
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

    proc = dap_client.attach(playbook, playbook_dir=tmp_path)

    dap_client.set_breakpoints(playbook, 8)

    dap_client.configuration_done()

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.TerminateRequest())

    dap_client.wait_for_message(dap.TerminateResponse)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.wait_rc(2)
    stdout = play_out[0]
    play_out[1]

    assert "Debugger has requested the process to terminate" in stdout
    assert "ok=1" in stdout


def test_attach_with_terminate_multiple_plays(
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
  - name: ping 1
    ping:

  - name: ping 2
    ping:

  - name: ping 3
    ping:

- name: play 2
  hosts: localhost
  gather_facts: false
  tasks:
  - name: ping 4
    ping:
"""
    )

    proc = dap_client.attach(playbook, playbook_dir=tmp_path)

    dap_client.set_breakpoints(playbook, 9)

    dap_client.configuration_done()

    dap_client.wait_for_message(dap.StoppedEvent)
    dap_client.send(dap.TerminateRequest())

    dap_client.wait_for_message(dap.TerminateResponse)
    dap_client.wait_for_message(dap.TerminatedEvent)

    play_out = proc.wait_rc(2)
    stdout = play_out[0]
    play_out[1]

    assert "PLAY [play 1]" in stdout
    assert "Debugger has requested the process to terminate" in stdout
    assert "PLAY [play 2]" not in stdout
    assert "ok=1" in stdout


def test_attach_invalid_pid(
    dap_client: DAPClient,
) -> None:
    attach_args = {
        "processId": 0,
    }

    with pytest.raises(DAPErrorResponse, match="Failed to find process pid file at "):
        dap_client.send(dap.AttachRequest(arguments=attach_args), dap.AttachResponse)


def test_attach_invalid_address(
    dap_client: DAPClient,
) -> None:
    attach_args = {
        "address": "tcp://invalid:port",
    }

    with pytest.raises(DAPErrorResponse, match="Port could not be cast to integer value"):
        dap_client.send(dap.AttachRequest(arguments=attach_args), dap.AttachResponse)


def test_attach_no_pid_or_port(
    dap_client: DAPClient,
) -> None:
    with pytest.raises(DAPErrorResponse, match="Expected processId or address/port to be specified for attach"):
        dap_client.send(dap.AttachRequest(arguments={}), dap.AttachResponse)


def test_attach_disconnect_before_config_done(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
    ping_playbook: pathlib.Path,
) -> None:
    proc = dap_client.attach(ping_playbook, playbook_dir=tmp_path)
    dap_client.send(dap.DisconnectRequest(), dap.DisconnectResponse)

    # The ping_playbook was waiting for configurationDone, it should now run to the
    # end without the debugger.
    proc.wait_rc()


def test_attach_multiple_playbooks(
    dap_client: DAPClient,
    tmp_path: pathlib.Path,
) -> None:
    playbooks = []
    for name in ["one", "two"]:
        playbook = tmp_path / f"{name}.yml"
        playbook.write_text(
            rf"""
- hosts: localhost
  gather_facts: false
  tasks:
  - name: {name}
    ping:
"""
        )
        playbooks.append(playbook)

    proc = dap_client.attach(playbooks[0], playbook_dir=tmp_path, playbook_args=[str(playbooks[1])])

    # One session covers both playbooks, the second playbook's breakpoints are
    # validated once it is loaded.
    resp = dap_client.set_breakpoints(playbooks[1], 5)
    assert not resp[0].verified
    dap_client.configuration_done()
    dap_client.wait_for_thread("exited")

    # The play line is registered first, then the task line narrows it.
    for line, end_line in [(2, 2), (5, 5)]:
        bp_event = dap_client.wait_for_message(dap.BreakpointEvent)
        assert bp_event.breakpoint.id == resp[0].id
        assert bp_event.breakpoint.verified
        assert bp_event.breakpoint.line == line
        assert bp_event.breakpoint.end_line == end_line

    tid = dap_client.wait_for_thread("started")
    stopped_event = dap_client.wait_for_message(dap.StoppedEvent)
    assert stopped_event.reason == dap.StoppedReason.BREAKPOINT
    assert stopped_event.thread_id == tid

    dap_client.continue_to_end(proc, tid)


def test_listen_syntax_check_does_not_wait(
    tmp_path: pathlib.Path,
) -> None:
    playbook = tmp_path / "main.yml"
    playbook.write_text(
        r"""
- hosts: localhost
  gather_facts: false
  tasks:
  - ping:
"""
    )

    # No play runs so it must not wait for a client to attach.
    proc = AnsibleProcess(
        [sys.executable, "-m", "ansibug", "listen", str(playbook), "--syntax-check"],
        cwd=tmp_path,
        env=get_test_env(),
    )
    stdout, _ = proc.wait_rc(0)
    assert "playbook: " in stdout
